"""2.148.0 B (#2470): the receipts go to the tax advisor together with the bookings, as with DATEV Unternehmen online.

GET /api/office/datev/zip -> one ZIP with
- the EXTF booking batch (office/datev.py dx_extf, the same lines), every line of an invoice / credit note or a receipt
  with its "Beleglink" = BEDI "<GUID>";
- Belege_<from>_<to>.zip = the receipt images in the format of the DATEV XML interface (document.xml, schema
  Document_v05.0, one <document guid=...> per file at the root of that archive, which the advisor reads into DATEV DMS /
  Belegverwaltung): the PDF of every finalised invoice / credit note of the period (its finalised state) and the file of
  every receipt (only receipts the signed-in person sees, as everywhere in the bookkeeping).
The GUID of a document is stable: 2.188.0 A (#2498) keeps it from its first export (office_datev_guids; the start value is the
uuid5 of the office area, kind and id as before), so a second export and one after a move of the office link the same.
?locked=1: only locked months (office/periodlock.py; the period is cut at the last locked month, header Festschreibung 1).
?check=1: {count, files, from, to, hints, no_booking: [...], no_receipt: [...]} without building the files: receipts the
batch cannot book (no amount) and bookings without a receipt (money paid out on the bank account without a matched receipt,
cash paid out without a receipt file)."""
import io
import re
import uuid
import zipfile
from datetime import date, timedelta
from xml.sax.saxutils import escape, quoteattr

from flask import Response, g, request

from ..core.config import app
from ..core.i18n import N_, tr
from ..core.db import db, iso, now_utc
from ..core.access import Denied
from ..personal.timetrack import BadInput
from .calc import dec, dstr, money
from .model import office_gate, office_need_feature, office_org, office_settings
from .ledger import ofx_log

DZ_NS = uuid.UUID("6f0a4c2e-1d8b-4f7e-9a3c-5b2d8e7f1a90")  # the name space of Kalmido's receipt GUIDs (never change)
DZ_MAX_BYTES = 80 * 1024 * 1024  # the receipt files of one export together (the archive is built in memory)
DZ_MAX_FILES = 1500  # documents per export (every invoice PDF is rendered)
DZ_LIST_MAX = 50  # entries per list of the check
DZ_TOO_BIG = N_("The receipts of this period are too large for one file ({0} MB); please export a shorter period.")
DZ_TOO_MANY = N_("More than {0} receipts in this period; please export a shorter period.")
DZ_NOTHING_LOCKED = N_("No month of this period is locked yet.")


def dz_guid(oid, kind, ident):
    return str(uuid.uuid5(DZ_NS, f"{int(oid)}/{kind}/{int(ident)}")).upper()


def _month_end(m):
    y, mo = int(m[:4]), int(m[5:7])
    nxt = date(y + (mo == 12), mo % 12 + 1, 1)
    return (nxt - timedelta(days=1)).isoformat()


def dz_period(c, oid, d_from, d_to, locked_only):
    """(from, to) of the export; locked_only cuts at the last locked month (400 when none of the period is locked)."""
    if not locked_only:
        return d_from, d_to
    from .periodlock import pl_through
    t = pl_through(c, oid)
    if not t or t < d_from[:7]:
        raise BadInput(tr(DZ_NOTHING_LOCKED))
    return d_from, min(d_to, _month_end(t))


def dz_kept(c, oid, col, ids, kind, store):
    """2.188.0 A (#2498): {id: guid} of the documents (col doc_id) / receipt files (node_id), the kept GUID where there is one,
    else the computed start value -- stored when store (the first real export), so it never changes afterwards."""
    out, ids = {}, sorted({int(x) for x in ids})
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        q = ",".join("?" * len(part))
        for r in c.execute(f"SELECT {col}, guid FROM office_datev_guids WHERE org_id=? AND {col} IN ({q})", (oid, *part)):
            out[r[0]] = r[1]
    ts = None
    for x in ids:
        if x in out:
            continue
        out[x] = dz_guid(oid, kind, x)
        if store:
            ts = ts or iso(now_utc())
            c.execute(f"INSERT INTO office_datev_guids(org_id, {col}, guid, created_at) VALUES(?,?,?,?) ON CONFLICT DO NOTHING",
                      (oid, x, out[x], ts))
    return out


def dz_link(rows, oid, c=None, store=False):
    """Sets Beleglink on the lines of invoices / credit notes (_doc) and receipts (_node); -> ({doc id: guid}, {node id: guid}).
    With c: the kept GUIDs (dz_kept, stored when store)."""
    dids = {int(r["_doc"]) for r in rows if r.get("_doc")}
    nids = {int(r["_node"]) for r in rows if not r.get("_doc") and r.get("_node")}
    if c is not None:
        kd, kn = dz_kept(c, oid, "doc_id", dids, "doc", store), dz_kept(c, oid, "node_id", nids, "receipt", store)
    else:
        kd, kn = {x: dz_guid(oid, "doc", x) for x in dids}, {x: dz_guid(oid, "receipt", x) for x in nids}
    docs, nodes = {}, {}
    for r in rows:
        if r.get("_doc"):
            gd = docs.setdefault(r["_doc"], kd[int(r["_doc"])])
        elif r.get("_node"):
            gd = nodes.setdefault(r["_node"], kn[int(r["_node"])])
        else:
            continue
        r["Beleglink"] = f'BEDI "{gd}"'
    return docs, nodes


def _safe(name, fallback, ext=""):
    """A plain file name for the archive: the stem cleaned and cut, the extension kept (DATEV picks the type by it)."""
    stem, dot, e = str(name or "").rpartition(".")
    if not dot:
        stem, e = str(name or ""), ""
    e = re.sub(r"[^A-Za-z0-9]+", "", e)[:8].lower() or ext
    v = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-.")[:80] or fallback
    return f"{v}.{e}" if e else v


def dz_no_booking(c, oid, d_from, d_to):
    """Receipts of the period without an amount (the batch cannot book them) -> [{node_id, title, date}]."""
    from ..docs.store import doc_open
    from ..files.store import fs_chain, fs_deleted, fs_role
    from .books import _uid_filter, bk_ws
    ws = bk_ws(c, oid)
    uid = _uid_filter(None)
    day = "COALESCE(NULLIF(d.doc_date, ''), NULLIF(r.paid_at, ''), substr(r.set_at, 1, 10))"
    out = []
    for r in c.execute(f"SELECT r.node_id, d.amount, d.ws, n.name, {day} AS day FROM rc_receipts r JOIN doc_meta d ON d.node_id=r.node_id "
                       f"JOIN fs_nodes n ON n.id=r.node_id WHERE d.ws=? AND n.kind='file' AND n.deleted_at IS NULL "
                       f"AND {day}>=? AND {day}<=? ORDER BY {day}, r.node_id", (ws, d_from, d_to)).fetchall():
        raw = doc_open(c, r["ws"], "doc_meta.amount", r["amount"]) or ""
        if raw and dec(raw, "0") != 0:
            continue
        if fs_deleted(fs_chain(c, r["node_id"])) or (uid and not fs_role(c, r["node_id"], uid)):
            continue
        out.append({"node_id": r["node_id"], "title": r["name"] or "", "date": r["day"]})
    return out


def dz_no_receipt(c, oid, d_from, d_to):
    """Money paid out without a receipt: bank bookings (amount < 0, not matched) and cash entries out without a file."""
    from .bank import _tx_dec
    from ..core.orgcrypt import oc_dec_fields
    out = []
    for r in c.execute("SELECT * FROM office_bank_tx WHERE org_id=? AND deleted_at IS NULL AND match_kind IS NULL AND day>=? AND day<=? "
                       "ORDER BY day, id", (oid, d_from, d_to)).fetchall():
        t = _tx_dec(c, oid, r)
        if t["amount"] < 0:
            out.append({"kind": "bank", "id": t["id"], "date": t["day"], "amount": dstr(money(-t["amount"])),
                        "text": (t.get("counterpart") or t.get("purpose") or "")[:120]})
    for r in c.execute("SELECT * FROM office_cash_entries WHERE org_id=? AND dir='out' AND node_id IS NULL AND storno_of IS NULL "
                       "AND day>=? AND day<=? ORDER BY day, id", (oid, d_from, d_to)).fetchall():
        e = oc_dec_fields(c, oid, "office_cash_entries", r)
        out.append({"kind": "cash", "id": e["id"], "date": e["day"], "amount": dstr(money(dec(e["amount"], "0"))), "text": (e["text"] or "")[:120]})
    return out


def dz_document_xml(entries, d_from, d_to, now):
    """document.xml of the DATEV XML interface (Document_v05.0) for entries [(guid, file name, description)]."""
    docs = "".join(f'    <document guid={quoteattr(gd)}>\n      <description>{escape(desc[:40])}</description>\n'
                   f'      <extension xsi:type="File" name={quoteattr(name)}/>\n    </document>\n' for gd, name, desc in entries)
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            '<archive xmlns="http://xml.datev.de/bedi/tps/document/v05.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xsi:schemaLocation="http://xml.datev.de/bedi/tps/document/v05.0 Document_v050.xsd" version="5.0" generatingSystem="Kalmido">\n'
            f'  <header>\n    <date>{now.strftime("%Y-%m-%dT%H:%M:%S")}</date>\n'
            f'    <description>{escape(f"Belege {d_from} - {d_to}")}</description>\n  </header>\n'
            f'  <content>\n{docs}  </content>\n</archive>\n').encode("utf-8")


def dz_build(c, oid, d_from, d_to, by="", inside=True, locked_only=False, check=False):
    from .datev import dx_check, dx_extf, dx_rows, dx_settings
    from ..core.db import local_now
    s = office_settings(c, oid)
    st = dx_settings(s)
    d_from, d_to = dz_period(c, oid, d_from, d_to, locked_only)
    dx_check(st, d_from, d_to)
    hints = []
    rows = dx_rows(c, oid, d_from, d_to, s, inside=inside, hints_out=hints)
    docs, nodes = dz_link(rows, oid, c, store=not check)  # 2.188.0 A (#2498): the kept GUIDs
    info = {"from": d_from, "to": d_to, "count": len(rows), "files": len(docs) + len(nodes), "hints": hints}
    if check:
        info["no_booking"] = dz_no_booking(c, oid, d_from, d_to)[:DZ_LIST_MAX]
        info["no_receipt"] = dz_no_receipt(c, oid, d_from, d_to)[:DZ_LIST_MAX]
        return None, info
    if len(docs) + len(nodes) > DZ_MAX_FILES:
        raise BadInput(tr(DZ_TOO_MANY, DZ_MAX_FILES))
    now = local_now()
    batch, _n = dx_extf(c, oid, d_from, d_to, by=by, s=s, now=now, inside=inside, rows=rows, fixed=locked_only)
    from .invoices import inv_files
    from ..files.store import fs_read
    entries, files, total, used = [], [], 0, set()

    def add(gd, name, data, desc):
        nonlocal total
        total += len(data)
        if total > DZ_MAX_BYTES:
            raise BadInput(tr(DZ_TOO_BIG, DZ_MAX_BYTES // (1024 * 1024)))
        base, n = name, 2
        while name.lower() in used:
            stem, dot, ext = base.rpartition(".")
            name = f"{stem}-{n}.{ext}" if dot else f"{base}-{n}"
            n += 1
        used.add(name.lower())
        entries.append((gd, name, desc))
        files.append((name, data))

    for did, gd in docs.items():
        fl = inv_files(c, oid, did)
        pdf = next((f for f in fl if f[2] == "application/pdf"), fl[0] if fl else None)
        if pdf:
            add(gd, _safe(pdf[0], f"doc-{did}", "pdf"), pdf[1], pdf[0])
    for nid, gd in nodes.items():
        n = c.execute("SELECT name FROM fs_nodes WHERE id=?", (nid,)).fetchone()
        try:
            data = fs_read(c, nid)
        except Denied:
            continue  # no content (a receipt without a file stays linked in the batch; the advisor sees the gap)
        add(gd, _safe(n["name"] if n else "", f"receipt-{nid}", "pdf" if data[:4] == b"%PDF" else ""), data, (n["name"] if n else "") or f"B{nid}")
    span = f"{d_from.replace('-', '')}_{d_to.replace('-', '')}"
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w", zipfile.ZIP_STORED) as z:  # PDFs and photos are compressed already
        z.writestr("document.xml", dz_document_xml(entries, d_from, d_to, now), compress_type=zipfile.ZIP_DEFLATED)
        for name, data in files:
            z.writestr(name, data)
    files.clear()
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w", zipfile.ZIP_STORED) as z:
        z.writestr(f"EXTF_Buchungsstapel_{span}.csv", batch)
        z.writestr(f"Belege_{span}.zip", inner.getvalue())
    info["file"] = f"DATEV_{span}.zip"
    return outer.getvalue(), info


@app.get("/api/office/datev/zip")
def dz_zip_get():
    """Org admin: ?from=&to= (default: the previous month), in=0 (no input side), locked=1 (only locked months), check=1."""
    from .datev import _period
    c = db()
    uid = office_gate(c)
    oid = office_org(c, uid, admin=True)
    office_need_feature(c, oid, "books.datev")  # 2.147.0 (#2460): the country switch also closes the ZIP
    d_from, d_to = _period()
    u = g.user
    by = (u["display_name"] if "display_name" in u.keys() else "") or u["username"]
    data, info = dz_build(c, oid, d_from, d_to, by=by, inside=request.args.get("in") != "0",
                          locked_only=request.args.get("locked") == "1", check=request.args.get("check") == "1")
    if data is None:
        return info
    ofx_log(c, oid, "export", target="datev", detail={"from": info["from"], "to": info["to"], "count": info["count"], "files": info["files"]})
    c.commit()
    return Response(data, mimetype="application/zip", headers={"Content-Disposition": f'attachment; filename="{info["file"]}"'})
