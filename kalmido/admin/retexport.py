"""2.146.0 D (#2468): the retention export before an account or an organisation is deleted.

Kalmido does not keep other people's records for ten years (the hosted instance, decision of 20.10.2026; the duty to keep them lies
with the person): before an account or an organisation goes, its records that the law asks to keep can be downloaded as one
readable ZIP -- invoices and other finalised documents (the stored PDF and e-invoice XML, else rendered from the snapshot),
receipts with their files, project receipts of lists, the cash books (PDF + CSV), the bank statements, the office log
(GoBD), the archive and every other file of the office folder, each table also as CSV, with a table of contents
(00-index.txt) and a manifest (SHA-256 per file).

Subjects: "user:<id>" = a person's own records (the personal office, the documents of the own space, the receipts of the
lists the person owns) -- only the person themself downloads them; "org:<id>" = an organisation's office, the receipts of its
documents space and of its lists -- only its admins. Nobody else (an instance admin neither: the organisation boundary).

The ZIP is streamed (built while it is sent, nothing on the disk); only a download that ran to its end is noted in
retention_log. Deleting the account (DELETE /api/users/<id>) or the organisation (DELETE /api/admin/orgs/<id>) while it has
such records needs ?retention=exported (a finished export of the subject within RX_VALID_DAYS) or ?retention=waived (the
deleting admin says so; noted too); both land in the security log (useradmin.ua8_audit style, notify.alerts)."""
import csv
import hashlib
import io
import json
import os
import time
import zipfile

from flask import Response, g, jsonify, request, stream_with_context

from ..core.access import Denied
from ..core.config import app, APP_VERSION, ATT_DIR, OFFICE_DIR
from ..core.db import connect, db, iso, now_utc
from ..core.i18n import N_, lang, tr
from ..core.pg import system_ctx
from ..accounts.session import me

RX_VALID_DAYS = 7  # a finished export counts this long as "exported" for the deletion
RX_YEARS = {"documents": 8, "books": 10}  # what the hint says (invoices / receipts 8 years, books 10 years)
RX_NOTE = N_("Keep these records yourself: invoices and receipts for 8 years, books (cash book, logs, bank statements) for 10 years. "
             "Kalmido does not keep them after the deletion; the duty to keep them lies with you.")
RX_NEEDED = N_("This account or organisation has records you must keep (invoices, receipts, cash book). Download the retention "
               "export first and confirm it, or say explicitly that you do without it.")
# (archive name, table) of the tables that go along as CSV; the where clause is the organisation export's (orgexport.OX_AREAS)
RX_TABLES = (
    ("invoices/documents.csv", "office_docs"),
    ("invoices/positions.csv", "office_doc_items"),
    ("invoices/payments.csv", "office_payments"),
    ("invoices/clients.csv", "clients"),
    ("invoices/company.csv", "office_company"),
    ("archive/archive.csv", "office_archive"),
    ("cashbook/cashbooks.csv", "office_cashbooks"),
    ("cashbook/entries.csv", "office_cash_entries"),
    ("cashbook/closings.csv", "office_cash_closings"),
    ("bank/imports.csv", "office_bank_imports"),
    ("bank/transactions.csv", "office_bank_tx"),
    ("expenses/meals.csv", "office_meals"),
    ("expenses/trips.csv", "office_trips"),
    ("expenses/trip-items.csv", "office_trip_items"),
    ("expenses/drives.csv", "office_drives"),
    ("logs/office-log.csv", "office_doc_log"),
    ("logs/cashbook-log.csv", "office_cash_log"),
    ("logs/archive-log.csv", "office_archive_log"),
    ("logs/meal-log.csv", "office_meal_log"),
    ("logs/drive-log.csv", "office_drive_log"),
)


# ---------------------------------------------------------------- the subject: whose records, who may download them
def rx_subject(c, kind, sid):
    """{key, kind, id, office (office area id or None), ws (documents space), lists (SQL for the list ids)} of user / org sid."""
    from ..docs.store import doc_ws
    with system_ctx(c):  # structure only: the personal office of a person, whether an organisation exists
        if kind == "user":
            r = c.execute("SELECT id FROM orgs WHERE personal_of=?", (sid,)).fetchone()
            return {"key": f"user:{int(sid)}", "kind": kind, "id": int(sid), "office": r[0] if r else None, "ws": doc_ws(None, sid),
                    "lists": ("SELECT id FROM lists WHERE owner_id=? AND is_inbox=0", (sid,))}
        if not c.execute("SELECT 1 FROM orgs WHERE id=? AND personal_of IS NULL", (sid,)).fetchone():
            raise Denied(404)
    return {"key": f"org:{int(sid)}", "kind": kind, "id": int(sid), "office": int(sid), "ws": doc_ws(sid, None),
            "lists": ("SELECT id FROM lists WHERE org_id=? AND is_inbox=0", (sid,))}


def rx_may_export(c, sub):
    """Only the person themself (user) or an admin of the organisation (org); people only, never an API token."""
    from ..agents.core import is_agent
    if not g.user or is_agent(g.user) or getattr(g, "auth_via", None) == "token":
        return False
    if sub["kind"] == "user":
        return sub["id"] == me()
    from ..accounts.orgs import org_role
    return org_role(c, me(), sub["id"]) == "admin"


def rx_counts(c, sub, along=True):
    """How many records of each kind the subject has (along = with the receipts of its lists: they go with the deletion only
    when the lists are deleted along)."""
    oid = sub["office"]
    q, a = sub["lists"]
    out = {}
    with system_ctx(c):  # counts only (no content): the deleting admin may not see the records themselves
        if oid:
            out["documents"] = c.execute("SELECT COUNT(*) FROM office_docs WHERE org_id=? AND locked_at IS NOT NULL", (oid,)).fetchone()[0]
            out["archive"] = c.execute("SELECT COUNT(*) FROM office_archive WHERE org_id=?", (oid,)).fetchone()[0]
            out["cash"] = c.execute("SELECT COUNT(*) FROM office_cash_entries WHERE org_id=?", (oid,)).fetchone()[0]
            out["bank"] = c.execute("SELECT COUNT(*) FROM office_bank_tx WHERE org_id=?", (oid,)).fetchone()[0]
        out["receipts"] = c.execute("SELECT COUNT(*) FROM rc_receipts r JOIN doc_meta d ON d.node_id=r.node_id WHERE d.ws=?",
                                    (sub["ws"],)).fetchone()[0]
        if along:
            out["project_receipts"] = c.execute(f"SELECT COUNT(*) FROM budget_files WHERE list_id IN ({q})", a).fetchone()[0]
    return {k: int(v) for k, v in out.items() if v}


def rx_last(c, sub, kind="export"):
    """When the subject's last finished export (or waiver) was (ISO) or None."""
    with system_ctx(c):  # the log of the subject (the deleting admin and the exporting person may differ)
        r = c.execute("SELECT at FROM retention_log WHERE subject=? AND kind=? ORDER BY id DESC LIMIT 1", (sub["key"], kind)).fetchone()
    return r[0] if r else None


def rx_fresh(at):
    if not at:
        return False
    try:
        from datetime import datetime
        t = datetime.fromisoformat(str(at).replace("Z", "+00:00"))
    except ValueError:
        return False
    return (now_utc() - t).total_seconds() < RX_VALID_DAYS * 86400


def rx_info(c, sub, along=True):
    """What the delete dialogs and the settings show: needed (records exist), can_export, exported_at (a finished export within
    RX_VALID_DAYS), the counts (only to who may export), the years of the hint, hosted."""
    from .hosting import hosted
    counts = rx_counts(c, sub, along)
    can = rx_may_export(c, sub)
    at = rx_last(c, sub)
    d = {"needed": bool(counts), "can_export": can, "exported_at": at if rx_fresh(at) else None, "years": RX_YEARS,
         "note": tr(RX_NOTE), "hosted": hosted(), "valid_days": RX_VALID_DAYS}
    if can:
        d["counts"] = counts
        d["url"] = "/api/retention/me/export.zip" if sub["kind"] == "user" else f"/api/retention/org/{sub['id']}/export.zip"
    return d


def rx_log(c, sub, kind, detail=None):
    from ..core.pg import insert_id
    with system_ctx(c):  # the subject's log row (no organisation column: it outlives the deleted organisation / account)
        return insert_id(c, "INSERT INTO retention_log(subject, kind, by_user, at, detail) VALUES(?,?,?,?,?)",
                         (sub["key"], kind, me(), iso(now_utc()), json.dumps(detail or {}, ensure_ascii=False)))


def rx_alert(text, args):
    from ..notify.alerts import aa_now
    aa_now("security", f"retention:{int(time.time() * 1000)}", text, args)


def rx_gate(c, sub, along=True):
    """Before the deletion of sub: None = it may go (no records, a fresh export, or ?retention=waived -- noted), else the 409
    answer. The caller deletes in the same transaction (a waiver row goes away with a failed deletion)."""
    counts = rx_counts(c, sub, along)
    if not counts:
        return None, None
    how = request.args.get("retention") or ""
    if how == "waived":
        rx_log(c, sub, "waiver", {"counts": counts})
        return None, (N_("{0} deleted {1} without the retention export (waived explicitly)."), "waiver")
    if how == "exported" and rx_fresh(rx_last(c, sub)):
        return None, (N_("{0} deleted {1} after the retention export."), "exported")
    info = rx_info(c, sub, along)
    if how == "exported":
        msg = tr("No finished retention export of the last {0} days was found. Download it again or do without it.", RX_VALID_DAYS)
    else:
        msg = tr(RX_NEEDED)
    return (jsonify(error=msg, code="retention", retention=info), 409), None


# ---------------------------------------------------------------- the ZIP
class _Pipe:
    """A write-only, unseekable stream: zipfile writes into it (data descriptors), the generator takes the bytes out."""

    def __init__(self):
        self.buf = bytearray()

    def write(self, b):
        self.buf += b
        return len(b)

    def flush(self):
        pass

    def take(self):
        b = bytes(self.buf)
        self.buf.clear()
        return b


def _cell(v):
    from ..office.books import bk_csv_cell
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        v = json.dumps(v, ensure_ascii=False)
    return bk_csv_cell(v) if isinstance(v, str) else str(v)


def _csv(rows, cols=None):
    """Rows (dicts) as CSV text (semicolon, byte order mark, formula-safe cells); cols = the column order (default: as they come)."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    rows = list(rows)
    if cols is None:
        cols = []
        for r in rows:
            cols += [k for k in r if k not in cols]
    w.writerow(cols)
    for r in rows:
        w.writerow([_cell(r.get(k)) for k in cols])
    return "﻿" + buf.getvalue(), len(rows)


class _Zip:
    def __init__(self):
        self.pipe = _Pipe()
        self.zf = zipfile.ZipFile(self.pipe, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6)
        self.files, self.sections, self.missing, self.names = {}, {}, [], set()

    def put(self, name, data, section=None):
        if isinstance(data, str):
            data = data.encode("utf-8")
        base, n = name, 1
        while name in self.names:  # two files of the same name: number them
            n += 1
            stem, dot, ext = base.rpartition(".")
            name = f"{stem}-{n}.{ext}" if dot else f"{base}-{n}"
        self.names.add(name)
        zi = zipfile.ZipInfo(name, date_time=time.localtime()[:6])
        zi.compress_type = zipfile.ZIP_DEFLATED
        self.zf.writestr(zi, data)
        self.files[name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        if section:
            self.sections[section] = self.sections.get(section, 0) + 1
        return self.pipe.take()


def _names(c):
    cache = {}

    def name(uid):
        if not uid:
            return ""
        if uid not in cache:
            r = c.execute("SELECT COALESCE(display_name, username) FROM users WHERE id=?", (uid,)).fetchone()
            cache[uid] = r[0] if r else f"#{uid}"
        return cache[uid]
    return name


def _tables(c, z, sub):
    """The office tables as CSV (decrypted like the organisation export, secrets dropped) -> chunks."""
    from .orgexport import OX_AREAS, OX_PB_CLIENTS, _rows
    oid = sub["office"]
    where = {t: w for _n, t, w in OX_AREAS}
    have = {r[0] for r in c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()")}
    name = _names(c)
    for arc, table in RX_TABLES:
        if table not in have or table not in where:
            continue
        if sub["kind"] == "user" and table in OX_PB_CLIENTS:  # a personal office: the owner's private clients
            rows = _rows(c, oid, table, OX_PB_CLIENTS[table], (sub["id"],))
        else:
            w = where[table]
            rows = _rows(c, oid, table, w, (oid,) * w.count("?"))
        rows = [dict(r, user_name=name(r.get("user_id") or r.get("by_user"))) if ("user_id" in r or "by_user" in r) else r for r in rows]
        if not rows:
            continue
        text, _n = _csv(rows)
        yield z.put(arc, text, arc.split("/")[0])


def _invoices(c, z, sub, done):
    """Every finalised document: its stored PDF / XML (decrypted), else rendered from its snapshot."""
    from ..core.orgcrypt import oc_read_file
    from ..office.pdfweb import _render, _stored, epdf_name
    from .orgexport import _safe_part
    oid = sub["office"]
    for r in c.execute("SELECT * FROM office_docs WHERE org_id=? AND locked_at IS NOT NULL ORDER BY date, id", (oid,)).fetchall():
        stem = "invoices/" + _safe_part(epdf_name(r), 100)
        p, x = _stored(oid, r, "pdf"), _stored(oid, r, "xml")
        try:
            if p:
                done.add(os.path.realpath(p))
                yield z.put(stem + ".pdf", oc_read_file(c, p), "invoices")
                if x:
                    done.add(os.path.realpath(x))
                    yield z.put(stem + ".xml", oc_read_file(c, x), "invoices")
                continue
            pdf, xml, _fmt = _render(c, oid, r)
        except Exception as e:  # noqa: BLE001 -- one unreadable document must not stop the export: named in the index
            print("retention export: document", r["id"], "of area", oid, "not readable:", type(e).__name__, flush=True)
            z.missing.append(f"{stem}.pdf")
            continue
        yield z.put(stem + ".pdf", pdf, "invoices")
        if xml:
            yield z.put(stem + ".xml", xml, "invoices")


def _receipts(c, z, sub):
    """The receipts of the documents space (also those in the trash: they go with the deletion) with their files + receipts.csv."""
    from ..docs.store import doc_open
    from ..files.store import fs_read
    from .orgexport import _safe_part
    rows = c.execute("SELECT r.node_id, r.category, r.vat_pct, r.paid_at, d.doc_date, d.amount, d.currency, d.ws, n.name, n.deleted_at "
                     "FROM rc_receipts r JOIN doc_meta d ON d.node_id=r.node_id JOIN fs_nodes n ON n.id=r.node_id "
                     "WHERE d.ws=? AND n.kind='file' ORDER BY COALESCE(NULLIF(d.doc_date, ''), r.paid_at), r.node_id", (sub["ws"],)).fetchall()
    out = []
    for r in rows:
        fn = f"receipts/{int(r['node_id'])}-{_safe_part(r['name'], 100)}"
        try:
            data = fs_read(c, r["node_id"])
        except Exception as e:  # noqa: BLE001 -- a file without content (or held by the scan guard): named in the index
            print("retention export: receipt", r["node_id"], "not readable:", type(e).__name__, flush=True)
            z.missing.append(fn)
            data, fn = None, ""
        if data is not None:
            yield z.put(fn, data, "receipts")
        out.append({"node_id": r["node_id"], "file": fn, "name": r["name"], "doc_date": r["doc_date"], "paid_at": r["paid_at"],
                    "amount": doc_open(c, r["ws"], "doc_meta.amount", r["amount"]) or "", "currency": r["currency"] or "",
                    "vat_pct": r["vat_pct"], "category": r["category"] or "", "in_trash": 1 if r["deleted_at"] else 0})
    if out:
        yield z.put("receipts/receipts.csv", _csv(out)[0])


def _project_receipts(c, z, sub):
    """The receipt files of the lists (budget_files) + project-receipts.csv."""
    from ..core.orgcrypt import oc_read_file
    from .orgexport import _safe_part, _under
    q, a = sub["lists"]
    rows = c.execute(f"SELECT f.*, l.name AS list_name FROM budget_files f JOIN lists l ON l.id=f.list_id WHERE f.list_id IN ({q}) "
                     "ORDER BY f.list_id, f.id", a).fetchall()
    out = []
    for r in rows:
        fn = f"project-receipts/{int(r['list_id'])}-{_safe_part(r['list_name'], 40)}/{int(r['id'])}-{_safe_part(r['name'], 100)}"
        full = _under(ATT_DIR, r["path"])
        try:
            data = oc_read_file(c, full) if full else None
        except Exception as e:  # noqa: BLE001 -- named in the index
            print("retention export: project receipt", r["id"], "not readable:", type(e).__name__, flush=True)
            data = None
        if data is None:
            z.missing.append(fn)
            fn = ""
        else:
            yield z.put(fn, data, "project-receipts")
        out.append({"id": r["id"], "file": fn, "list_id": r["list_id"], "list": r["list_name"], "entry_id": r["entry_id"], "name": r["name"],
                    "size": r["size"], "created_at": r["created_at"]})
    if out:
        yield z.put("project-receipts/project-receipts.csv", _csv(out)[0])


def _cashbooks(c, z, sub, uid, lg):
    """Every cash book of the office as PDF (entries, day closings, change log) and CSV, over its whole time."""
    from ..office.cashbook import cb_csv_text, cb_export_data, cb_pdf_bytes
    from .orgexport import _safe_part
    oid = sub["office"]
    today = now_utc().date().isoformat()
    for b in c.execute("SELECT * FROM office_cashbooks WHERE org_id=? ORDER BY id", (oid,)).fetchall():
        first, last = c.execute("SELECT MIN(day), MAX(day) FROM office_cash_entries WHERE book_id=?", (b["id"],)).fetchone()
        frm = min(x for x in (b["opening_day"], first, today) if x)
        vals = cb_export_data(c, oid, uid, b, frm, max(today, last or today))
        stem = f"cashbook/{int(b['id'])}-{_safe_part(b['name'], 60)}"
        yield z.put(stem + ".csv", cb_csv_text(*vals), "cashbook")
        try:
            yield z.put(stem + ".pdf", cb_pdf_bytes(c, oid, *vals, lg), "cashbook")
        except Exception as e:  # noqa: BLE001 -- the CSV holds the same
            print("retention export: cash book PDF", b["id"], "failed:", type(e).__name__, flush=True)
            z.missing.append(stem + ".pdf")


def _office_files(c, z, sub, done):
    """Every other file of the office folder (archive PDFs, accepted quotations, meal bills, contract files ...), decrypted."""
    from ..core.orgcrypt import oc_read_file
    from .orgexport import _safe_part
    base = os.path.join(OFFICE_DIR, str(int(sub["office"])))
    if not os.path.isdir(base):
        return
    for root, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if not os.path.islink(os.path.join(root, d)))
        for fn in sorted(files):
            full = os.path.join(root, fn)
            if os.path.islink(full) or not os.path.isfile(full) or os.path.realpath(full) in done or fn.endswith(".tmp"):
                continue
            rel = os.path.relpath(full, base).split(os.sep)
            try:
                data = oc_read_file(c, full)
            except Exception as e:  # noqa: BLE001 -- named in the index
                print("retention export: office file not readable:", type(e).__name__, flush=True)
                z.missing.append("office-files/" + "/".join(_safe_part(p) for p in rel))
                continue
            yield z.put("office-files/" + "/".join(_safe_part(p) for p in rel), data, "office-files")


RX_SECTIONS = (
    ("invoices", N_("Invoices, credit notes and other finalised documents (PDF, e-invoice XML) and their lists (CSV)")),
    ("receipts", N_("Receipts with their files and receipts.csv")),
    ("project-receipts", N_("Receipts of projects and lists")),
    ("cashbook", N_("Cash books (PDF and CSV with day closings and change log)")),
    ("bank", N_("Imported bank statements (CSV)")),
    ("expenses", N_("Entertainment receipts, travel expenses, logbook (CSV)")),
    ("archive", N_("Archive of imported documents (CSV; the files are under office-files)")),
    ("logs", N_("Office log and change logs (GoBD)")),
    ("office-files", N_("All other files of the office folder")),
)


def _index(z, sub, title, by, when):
    lines = [tr("Retention export"), "=" * 40, "", tr("Of: {0}", title), tr("Created: {0}", when), tr("By: {0}", by),
             f"Kalmido {APP_VERSION}", "", tr(RX_NOTE), "", tr("Contents"), "-" * 40]
    for key, label in RX_SECTIONS:
        n = z.sections.get(key, 0)
        if n:
            lines.append(f"{key}/  ({n})  {tr(label)}")
    if not z.sections:
        lines.append(tr("No records found."))
    if z.missing:
        lines += ["", tr("Could not be read (please check in Kalmido before the deletion):")] + [f"  {m}" for m in z.missing]
    lines += ["", tr("manifest.json lists every file with its SHA-256 checksum."), ""]
    return "\r\n".join(lines)


def rx_stream(sub, uid, by, title, lg):
    """The generator of the ZIP (own connection, system context for the subject's rows only; the caller checked the right)."""
    c = connect()
    z = _Zip()
    done = set()
    ok = False
    try:
        with system_ctx(c):  # the subject's records only (every query names its office / documents space / lists); checked by rx_may_export
            if sub["office"]:
                yield from _invoices(c, z, sub, done)
            yield from _receipts(c, z, sub)
            yield from _project_receipts(c, z, sub)
            if sub["office"]:
                yield from _cashbooks(c, z, sub, uid, lg)
                yield from _tables(c, z, sub)
                yield from _office_files(c, z, sub, done)
            when = iso(now_utc())
            idx = _index(z, sub, title, by, when)
            man = {"format": "kalmido-retention-export", "format_version": 1, "kalmido_version": APP_VERSION, "subject": sub["key"],
                   "created_at": when, "created_by": by, "files": dict(z.files), "missing": z.missing}
            yield z.put("00-index.txt", idx)
            yield z.put("manifest.json", json.dumps(man, ensure_ascii=False, indent=1))
            z.zf.close()
            yield z.pipe.take()
            ok = True
    finally:
        if ok:  # only a download that ran to its end counts as "exported"
            try:
                with system_ctx(c):  # the subject's log row + the office log
                    c.execute("INSERT INTO retention_log(subject, kind, by_user, at, detail) VALUES(?,?,?,?,?)",
                              (sub["key"], "export", uid, iso(now_utc()), json.dumps({"files": len(z.files), "missing": len(z.missing)})))
                    if sub["office"]:
                        from ..office.ledger import ofx_log
                        ofx_log(c, sub["office"], "export", target="retention", detail={"files": len(z.files), "missing": len(z.missing)})
                c.commit()
                rx_alert(N_("{0} downloaded the retention export of {1}."), [by, title])
            except Exception as e:  # noqa: BLE001 -- the file is sent; a failed note only means "export again"
                print("retention export: note failed:", type(e).__name__, flush=True)
        c.close()


def _download(sub, title):
    c = db()
    if not rx_may_export(c, sub):
        raise Denied(404 if sub["kind"] == "org" else 403)
    by = g.user["username"]
    lg = lang()
    name = f"kalmido-retention-{sub['kind']}{sub['id']}-{now_utc().strftime('%Y-%m-%d')}.zip"
    resp = Response(stream_with_context(rx_stream(sub, me(), by, title, lg)), mimetype="application/zip")
    resp.headers["Content-Disposition"] = f'attachment; filename="{name}"'
    resp.headers["Cache-Control"] = "private, no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


# ---------------------------------------------------------------- routes (people only, app only)
def _org_sub(c, oid):
    """The organisation subject for an admin of it or an instance admin (who sees only whether records exist); else 404."""
    sub = rx_subject(c, "org", oid)
    if not rx_may_export(c, sub) and not (g.user and g.user["is_admin"] and getattr(g, "auth_via", None) != "token"):
        raise Denied(404)
    return sub


@app.get("/api/retention/me")
def rx_me_get():
    """The own records: {needed, can_export, exported_at, counts, years, note, url}."""
    c = db()
    sub = rx_subject(c, "user", me())
    if not rx_may_export(c, sub):
        raise Denied(403)
    return jsonify(rx_info(c, sub))


@app.get("/api/retention/me/export.zip")
def rx_me_zip():
    return _download(rx_subject(db(), "user", me()), g.user["display_name"] or g.user["username"])


@app.get("/api/retention/org/<int:oid>")
def rx_org_get(oid):
    c = db()
    return jsonify(rx_info(c, _org_sub(c, oid)))


@app.get("/api/retention/org/<int:oid>/export.zip")
def rx_org_zip(oid):
    c = db()
    sub = rx_subject(c, "org", oid)
    with system_ctx(c):  # the organisation's name for the index (the right is checked in _download)
        name = (c.execute("SELECT name FROM orgs WHERE id=?", (oid,)).fetchone() or [""])[0]
    return _download(sub, name)


def rx_user_info(c, uid, along=True):
    """For the account delete dialog (useradmin.ua8_delete_info)."""
    return rx_info(c, rx_subject(c, "user", uid), along)
