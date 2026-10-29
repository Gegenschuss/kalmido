"""2.153.0 (#2055): the receipts list of the bookkeeping over all months, with filters, and the export of exactly that list.

GET /api/office/books/receipts (the list, its sums and the choices of the filters), receipts.csv (one row per receipt:
both days, supplier, VAT id and invoice number of an incoming e-invoice, category, project, amounts, the file name in the
ZIP) and receipts.zip (belege.csv + the original files in belege/, as uploaded). The export of the whole period with
invoices, payments and travel expenses is office/bkexport.py (#2461); this one is the filtered receipts only, with the
receipt's own columns (supplier, invoice number, project, payment day), under the same switch (books.export_csv) and the
same ZIP limits (files/bulk.py). The same rules as the bookkeeping
(books.py): admins of the office area only (a personal office: its owner), agents and kids 403, only receipts of the
office's documents space the signed-in person sees (fs_role), nothing in the trash, amounts in the office currency
(bk_to_home), net / VAT by the receipt's VAT rate (_split). Amounts are sealed: filters and sums run in Python.
The day of a receipt: its document date (by=doc, default: the tax adviser books by it), else the payment day; by=paid
the other way round (as the EUeR). A project name only when the person sees the project.
Invoice number and VAT id only from an incoming e-invoice (office/einvoice_in.py, #2451: doc_meta.extracted with "_einv"),
never from the text recognition's guesses."""
import csv
import io
import os
import re
import tempfile
import zipfile
from datetime import date
from decimal import Decimal

from flask import Response, jsonify, request

from ..core.access import Denied, list_role
from ..core.config import app
from ..core.db import local_now
from ..core.i18n import tr
from ..core.orgcrypt import OrgCryptError
from ..personal.timetrack import BadInput
from .homecur import hc_code
from .books import BK_VAT, DAY_RE, _ctx, _de, _home, _split, bk_csv_cell, bk_to_home, bk_ws
from .calc import dec, dstr, money
from .model import office_need_feature, office_settings
from .rights import ofr_own_only
from .rcsubmit import rsb_who  # 2.356.0 D (#3129)

RCL_PAGE = 200  # rows per page of the list
RCL_PAGE_MAX = 500
RCL_STATUS = ("all", "paid", "open")
RCL_CHECKED = ("all", "yes", "no")  # 2.420.0 C (#3448): the filter checked / not checked
RCL_CHECK_MAX = 500  # 2.420.0 C (#3448): receipts ticked in one request (the multiple choice of the list)
RCL_NAME_MAX = 120
RCL_RCK = ("rchk", "rchk_at", "rchk_ok", "updated_at", "extracted", "amount", "doc_date", "currency", "sender_id", "type_id", "set_at",
           "category", "vat_pct")  # 2.299.0 D (#3193): what rck_seen reads (receipts/rchecks.py rck_stamp)


def rcl_args(args):
    """The filters of a request -> dict; BadInput on wrong values. Period default: this year."""
    y = local_now().year
    frm, to = args.get("from") or f"{y}-01-01", args.get("to") or f"{y}-12-31"
    for k, v in (("from", frm), ("to", to)):
        if not DAY_RE.match(v):
            raise BadInput(tr("Invalid value: {0}", k))
        try:
            date.fromisoformat(v)
        except ValueError:
            raise BadInput(tr("Invalid value: {0}", k))
    if frm > to:
        raise BadInput(tr("Invalid value: {0}", "from"))
    by = args.get("by") or "doc"
    status = args.get("status") or "all"
    if by not in ("doc", "paid"):
        raise BadInput(tr("Invalid value: {0}", "by"))
    if status not in RCL_STATUS:
        raise BadInput(tr("Invalid value: {0}", "status"))
    checked = args.get("checked") or "all"
    if checked not in RCL_CHECKED:
        raise BadInput(tr("Invalid value: {0}", "checked"))
    ids = {}
    for k in ("supplier", "project"):
        v = args.get(k) or ""
        if v and not (v.isdigit() and 0 < int(v) < 1 << 62):
            raise BadInput(tr("Invalid value: {0}", k))
        ids[k] = int(v) if v else None
    try:
        limit = int(args.get("limit") or RCL_PAGE)
        offset = int(args.get("offset") or 0)
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "limit"))
    return {"from": frm, "to": to, "by": by, "status": status, "checked": checked, "category": (args.get("category") or "").strip()[:200],
            "supplier": ids["supplier"], "project": ids["project"], "novat": args.get("novat") in ("1", "true"),
            "hints": args.get("hints") in ("1", "true"),  # 2.299.0 D (#3193): only receipts with hints of the check
            "q": (args.get("q") or "").strip().lower()[:200], "limit": max(1, min(limit, RCL_PAGE_MAX)), "offset": max(0, offset)}


def rcl_all(c, oid, f, uid, own=False):
    """All receipts of office area oid in the period of f that uid sees (no other filter), oldest first ->
    [{node_id, date, doc_date, paid_at, due_date, title, category, project_id, project, supplier_id, supplier, vat_pct,
    net, vat, amount (Decimal, office currency), currency, orig_amount, orig_currency, mime, size, file, einvoice,
    number, vat_id}]. 2.187.0 B (#2476): own=True only the receipts uid uploaded (office groups, level "own")."""
    from ..docs.store import doc_open, label_name, meta_json
    from ..files.store import fs_chain, fs_deleted, fs_role
    ws = bk_ws(c, oid)
    s = office_settings(c, oid)
    home = _home(s)
    day = ("COALESCE(NULLIF(r.paid_at, ''), d.doc_date)" if f["by"] == "paid"
           else "COALESCE(NULLIF(d.doc_date, ''), NULLIF(r.paid_at, ''))")
    rows = c.execute(f"SELECT r.node_id, r.vat_pct, r.paid_at, r.category, r.list_id, r.list_name, d.doc_date, d.due_date, d.amount, d.currency, "
                     f"d.sender_id, d.ws, d.extracted, d.rchk, d.rchk_at, d.rchk_ok, d.updated_at, d.type_id, r.set_at, r.submitted_by, r.checked_at, r.checked_by, n.name, n.mime, n.size, {day} AS day FROM rc_receipts r JOIN doc_meta d ON d.node_id=r.node_id "
                     f"JOIN fs_nodes n ON n.id=r.node_id WHERE d.ws=? AND n.kind='file' AND n.deleted_at IS NULL AND {day}>=? AND {day}<=? "
                     + ("AND COALESCE(n.created_by, n.owner_id)=? " if own else "")
                     + f"ORDER BY {day}, r.node_id", (ws, f["from"], f["to"]) + ((uid,) if own else ())).fetchall()
    lists, out = {}, []
    for r in rows:
        raw = doc_open(c, r["ws"], "doc_meta.amount", r["amount"]) or ""
        a = dec(raw, "0") if raw else Decimal(0)
        if a == 0:
            continue  # as the bookkeeping: a receipt without an amount is none yet
        if fs_deleted(fs_chain(c, r["node_id"])):
            continue
        if not fs_role(c, r["node_id"], uid):
            continue
        cur = hc_code(r["currency"]) or (r["currency"] or "").strip().upper() or home  # 2.189.0 B (#2475): also "£"
        gross = money(bk_to_home(a, cur, s))
        vat_pct = r["vat_pct"] if r["vat_pct"] in BK_VAT else None
        net, vat = _split(gross, vat_pct)
        lid = r["list_id"]
        if lid and lid not in lists:
            lr = c.execute("SELECT name, org_id FROM lists WHERE id=?", (lid,)).fetchone()
            ok = lr is not None and (lr["org_id"] or None) == (None if ws[0] == "u" else oid) and list_role(c, lid, uid)
            lists[lid] = lr["name"] if ok else None
        out.append({"node_id": r["node_id"], "date": r["day"], "doc_date": r["doc_date"], "paid_at": r["paid_at"] or None,
                    "due_date": r["due_date"], "title": r["name"] or "", "category": r["category"] or "",
                    "project_id": lid if lid and lists.get(lid) else None, "project": lists.get(lid) if lid else (r["list_name"] or None),  # 2.239.0 D (#2874): a deleted project's name
                    "supplier_id": r["sender_id"], "supplier": label_name(c, ws, "sender", r["sender_id"]) or "",
                    "vat_pct": vat_pct, "net": net, "vat": vat, "amount": gross, "currency": home,
                    "orig_amount": money(a) if cur != home else None, "orig_currency": cur if cur != home else None,
                    "mime": r["mime"] or "", "size": int(r["size"] or 0), "file": r["name"] or "", **_rcl_einv(meta_json(c, r, "extracted", {})),
                    "submitted_by": _rcl_who(c, r["submitted_by"]),  # 2.356.0 D (#3129): handed in by a member
                    "checked_at": r["checked_at"] or None, "checked_by": _rcl_who(c, r["checked_by"]) if r["checked_at"] else None})  # 2.420.0 C (#3448)
    from ..docs.dups import dup_seen
    dups = dup_seen(c, [x["node_id"] for x in out], uid)  # 2.185.0 A (#2583): a possible duplicate (marked, still counted)
    for x in out:
        x["dup"] = x["node_id"] in dups
    from ..receipts.rchecks import rck_seen  # 2.299.0 D (#3193): hints of the fixed check (stored; fill: stale ones now)
    ids = {x["node_id"] for x in out}
    seen, f["_rck_pending"] = rck_seen(c, [{"node_id": r["node_id"], **{k: r[k] for k in RCL_RCK}} for r in rows if r["node_id"] in ids], f.get("_rck_fill"))
    for x in out:
        x["hints"] = seen.get(x["node_id"], 0) + (1 if x["dup"] else 0)
    return out


def _rcl_who(c, uid):
    """2.356.0 D (#3129): the name of the person who handed a receipt in (None: uploaded in the bookkeeping)."""
    w = rsb_who(c, uid)
    return w["name"] if w else None


def _rcl_einv(ex):
    """The fixed fields of an incoming e-invoice (#2451 keeps them in doc_meta.extracted with the key _einv)."""
    if not isinstance(ex, dict) or not ex.get("_einv"):
        return {"einvoice": False, "number": "", "vat_id": ""}
    return {"einvoice": True, "number": str(ex.get("invoice_no") or "")[:120], "vat_id": str(ex.get("vat_id") or "")[:40]}


def rcl_filter(rows, f):
    """The rows matching the filters of f (category, supplier, project, status, without VAT rate, the search)."""
    out = []
    cat = f["category"].lower()
    for x in rows:
        if cat and x["category"].lower() != cat:
            continue
        if f["supplier"] and x["supplier_id"] != f["supplier"]:
            continue
        if f["project"] and x["project_id"] != f["project"]:
            continue
        if f["status"] == "paid" and not x["paid_at"]:
            continue
        if f["status"] == "open" and x["paid_at"]:
            continue
        if f.get("checked", "all") != "all" and bool(x.get("checked_at")) != (f["checked"] == "yes"):
            continue  # 2.420.0 C (#3448)
        if f["novat"] and x["vat_pct"] is not None:
            continue
        if f.get("hints") and not x.get("hints"):
            continue
        if f["q"] and f["q"] not in " ".join((x["title"], x["supplier"], x["number"])).lower():
            continue
        out.append(x)
    return out


def rcl_choices(rows):
    """The choices of the filters: only what the receipts of the period carry."""
    cats = sorted({x["category"] for x in rows if x["category"]}, key=str.lower)
    sup = sorted({(x["supplier_id"], x["supplier"]) for x in rows if x["supplier_id"] and x["supplier"]}, key=lambda t: t[1].lower())
    pro = sorted({(x["project_id"], x["project"]) for x in rows if x["project_id"]}, key=lambda t: t[1].lower())
    return cats, [{"id": i, "name": n} for i, n in sup], [{"id": i, "name": n} for i, n in pro]


def rcl_total(rows):
    t = {"gross": Decimal(0), "net": Decimal(0), "vat": Decimal(0)}
    for x in rows:
        t["gross"] += x["amount"]
        t["net"] += x["net"]
        t["vat"] += x["vat"]
    return {k: dstr(money(v)) for k, v in t.items()} | {"count": len(rows)}


def rcl_public(x):
    return {"node_id": x["node_id"], "date": x["date"], "doc_date": x["doc_date"], "paid_at": x["paid_at"], "due_date": x["due_date"],
            "title": x["title"], "category": x["category"], "project": {"id": x["project_id"], "name": x["project"]} if x["project_id"] else None,
            "supplier": x["supplier"] or None, "number": x["number"] or None, "einvoice": x["einvoice"], "vat_pct": x["vat_pct"],
            "net": dstr(x["net"]), "vat": dstr(x["vat"]), "amount": dstr(x["amount"]), "currency": x["currency"],
            "orig_amount": dstr(x["orig_amount"]) if x["orig_amount"] is not None else None, "orig_currency": x["orig_currency"],
            "dup": bool(x.get("dup")), "hints": x.get("hints") or 0,  # 2.185.0 A (#2583); 2.299.0 D (#3193): + hints
            "submitted_by": x.get("submitted_by"),  # 2.356.0 D (#3129)
            "checked_at": x.get("checked_at"), "checked_by": x.get("checked_by")}  # 2.420.0 C (#3448): a person's tick


def _rcl_load(c, oid, uid, fill=False):
    f = rcl_args(request.args)
    f["_rck_fill"] = fill  # 2.299.0 D (#3193): the list checks stale receipts (the exports only read the stored hints)
    rows = rcl_all(c, oid, f, uid, own=ofr_own_only(c, uid, oid, "receipts"))
    return f, rows, rcl_filter(rows, f)


_EXT = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png", "image/heic": "heic", "image/webp": "webp",
        "application/xml": "xml", "text/xml": "xml", "image/tiff": "tif"}


def rcl_clean(v, n):
    """A part of a file name: no path parts, no control or special characters, at most n characters."""
    v = re.sub(r"[^\w.\- ]+", "-", str(v or ""), flags=re.UNICODE)
    v = re.sub(r"[\s]+", "-", v)
    v = re.sub(r"\.{2,}", ".", re.sub(r"-{2,}", "-", v)).strip(".-_ ")
    return v[:n].strip(".-_ ")


def rcl_file_name(x):
    """belege/<YYYY-MM-DD>_<supplier>_<gross>_<id>.<ext> inside the ZIP (ext from the uploaded name, else the type)."""
    ext = ""
    m = re.search(r"\.([A-Za-z0-9]{1,8})$", x["file"] or "")
    if m:
        ext = m.group(1).lower()
    ext = ext or _EXT.get((x["mime"] or "").split(";")[0].strip().lower(), "bin")
    who = rcl_clean(x["supplier"] or os.path.splitext(x["title"])[0] or "", 60) or "beleg"
    head = f"{x['date'] or ''}_"
    tail = f"_{dstr(x['amount'])}_{x['node_id']}.{ext}"
    who = who[:max(1, RCL_NAME_MAX - len(head) - len(tail))].strip(".-_ ") or "beleg"
    return head + who + tail


def rcl_csv_text(c, oid, rows):
    """The CSV of the rows (BOM, CRLF, formula injection made harmless); as the booking list (bkexport.bx_csv) the number
    format follows the country pack: decimal comma -> semicolon, DD.MM.YYYY; else comma, decimal point, ISO days."""
    from .packs import office_pack_for
    comma = ((office_pack_for(office_settings(c, oid)) or {}).get("formats") or {}).get("decimal") == ","
    num = _de if comma else (lambda v: v)  # noqa: E731
    day = (lambda v: f"{v[8:10]}.{v[5:7]}.{v[:4]}" if v and DAY_RE.match(v) else "") if comma else (lambda v: v if v and DAY_RE.match(v) else "")  # noqa: E731
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";" if comma else ",", lineterminator="\r\n")
    w.writerow([tr("Receipt date"), tr("Paid on"), tr("Checked on"), tr("Checked by"), tr("Supplier"), tr("VAT ID"), tr("Invoice number"), tr("E-invoice"), tr("Title"),
                tr("Category"), tr("Project"), tr("Net"), tr("VAT rate"), tr("VAT"), tr("Gross"), tr("Currency"), tr("Original amount"),
                tr("Original currency"), tr("File name in the ZIP"), tr("Kalmido ID")])
    for x in rows:
        w.writerow([day(x["doc_date"]), day(x["paid_at"]), day((x.get("checked_at") or "")[:10]), bk_csv_cell(x.get("checked_by") or ""),  # 2.420.0 C (#3448)
                    bk_csv_cell(x["supplier"]), bk_csv_cell(x["vat_id"]), bk_csv_cell(x["number"]),
                    tr("yes") if x["einvoice"] else tr("no"), bk_csv_cell(x["title"]), bk_csv_cell(x["category"]), bk_csv_cell(x["project"] or ""),
                    num(dstr(x["net"])), x["vat_pct"] if x["vat_pct"] is not None else "", num(dstr(x["vat"])), num(dstr(x["amount"])),
                    bk_csv_cell(x["currency"]), num(dstr(x["orig_amount"])) if x["orig_amount"] is not None else "",
                    bk_csv_cell(x["orig_currency"] or ""), bk_csv_cell(x["zip_name"] if "zip_name" in x else "belege/" + rcl_file_name(x)),
                    x["node_id"]])
    return "﻿" + buf.getvalue()


def _fname(f, ext):
    return f"belege-{f['from']}-{f['to']}.{ext}"


# ---------------------------------------------------------------- routes
@app.get("/api/office/books/receipts")
def rcl_get():
    """?from=&to= (ISO days, default: this year) &by=doc|paid &status=all|paid|open &checked=all|yes|no (2.420.0 C, #3448) &category= &supplier=<sender id>
    &project=<list id> &novat=1 &q= &limit= (200, max 500) &offset= -> {rows (newest first), total {gross, net, vat, count},
    more, categories, suppliers, projects (of the period), currency, from, to, by}. 2.299.0 D (#3193): &hints=1 only receipts
    with hints of the check (or a possible duplicate); + hints (receipts of the period with hints), hints_pending (not
    checked yet: the next request checks them), row "hints" (their number)."""
    c, uid, oid = _ctx()
    f, rows, hit = _rcl_load(c, oid, uid, fill=True)
    cats, sup, pro = rcl_choices(rows)
    page = list(reversed(hit))[f["offset"]:f["offset"] + f["limit"]]
    return jsonify(rows=[rcl_public(x) for x in page], total=rcl_total(hit), more=f["offset"] + len(page) < len(hit),
                   categories=cats, suppliers=sup, projects=pro, currency=_home(office_settings(c, oid)),
                   hints=sum(1 for x in rows if x.get("hints")), hints_pending=f.get("_rck_pending") or 0,  # 2.299.0 D (#3193)
                   **{"from": f["from"], "to": f["to"], "by": f["by"]})


def rcl_set_checked(c, oid, uid, ids, on):
    """2.420.0 C (#3448): tick (on) or untick receipts ids of office area oid as checked by person uid (who + when, like the
    check mark of DATEV) -> the ids whose state changed. All or nothing: 404 when one is no receipt of this area the person
    sees (or in the trash), 403 when the person may only read one, 409 when one lies in a locked month (office/periodlock.py).
    Only people: the office routes refuse agent tokens (model.office_gate). The automatic check (receipts/rchecks.py) is apart."""
    from ..files.store import fs_chain, fs_deleted, fs_role
    from ..core.db import now_iso
    from .periodlock import pl_receipt_need_open
    q = ",".join("?" * len(ids))
    found = {r["node_id"]: r for r in c.execute(
        f"SELECT r.node_id, r.checked_at FROM rc_receipts r JOIN doc_meta d ON d.node_id=r.node_id JOIN fs_nodes n ON n.id=r.node_id "
        f"WHERE r.node_id IN ({q}) AND d.ws=? AND n.kind='file' AND n.deleted_at IS NULL", (*ids, bk_ws(c, oid))).fetchall()}
    for nid in ids:
        chain = fs_chain(c, nid) if nid in found else None
        role = fs_role(c, nid, uid, chain=chain) if chain and not fs_deleted(chain) else None
        if not role:
            raise Denied(404)
        if role not in ("owner", "edit"):
            raise Denied(403, tr("You may only read this receipt"))
        pl_receipt_need_open(c, nid)  # a receipt of a locked month stays as it was handed over
    changed = [nid for nid in ids if bool(found[nid]["checked_at"]) != on]
    if changed:
        q = ",".join("?" * len(changed))
        c.execute(f"UPDATE rc_receipts SET checked_at=?, checked_by=? WHERE node_id IN ({q})",
                  ((now_iso(), uid) if on else (None, None)) + tuple(changed))
    return changed


@app.post("/api/office/books/receipts/checked")
def rcl_checked_post():
    """2.420.0 C (#3448): {node_ids: [ids] (one or up to 500, the multiple choice of the list), checked: true|false} -> {changed:
    [ids whose state changed], rows: [{node_id, checked_at, checked_by}]}. A person of the bookkeeping (the rights of the
    receipts list, POST = edit); agents 403."""
    from ..core.db import body
    from .ledger import ofx_log
    c, uid, oid = _ctx()
    b = body()
    extra = sorted(set(b) - {"node_ids", "checked"})
    if extra:
        raise BadInput(tr("Unknown field: {0}", ", ".join(extra)[:200]))
    ids, on = b.get("node_ids"), b.get("checked")
    if not isinstance(on, bool):
        raise BadInput(tr("Invalid value: {0}", "checked"))
    if (not isinstance(ids, list) or not ids or len(ids) > RCL_CHECK_MAX
            or not all(isinstance(x, int) and not isinstance(x, bool) and 0 < x < 1 << 62 for x in ids)):
        raise BadInput(tr("Invalid value: {0}", "node_ids"))
    ids = list(dict.fromkeys(ids))
    changed = rcl_set_checked(c, oid, uid, ids, on)
    if changed:
        ofx_log(c, oid, "receipt_checked" if on else "receipt_unchecked", target="books", detail={"node_ids": changed[:100], "count": len(changed)})
    c.commit()
    q = ",".join("?" * len(ids))
    rows = c.execute(f"SELECT node_id, checked_at, checked_by FROM rc_receipts WHERE node_id IN ({q}) ORDER BY node_id", tuple(ids)).fetchall()
    return jsonify(changed=changed, rows=[{"node_id": r["node_id"], "checked_at": r["checked_at"],
                                           "checked_by": _rcl_who(c, r["checked_by"]) if r["checked_at"] else None} for r in rows])


def _rcl_export_ctx():
    """The export routes: the bookkeeping's rights + the country pack's switch of the export (#2459 features_off)."""
    c, uid, oid = _ctx()
    office_need_feature(c, oid, "books.export_csv")
    return c, uid, oid


@app.get("/api/office/books/receipts.csv")
def rcl_csv():
    """The same filters -> the filtered receipts as CSV for the tax adviser (oldest first)."""
    from .ledger import ofx_log
    c, uid, oid = _rcl_export_ctx()
    f, rows, hit = _rcl_load(c, oid, uid)
    data = rcl_csv_text(c, oid, hit)
    ofx_log(c, oid, "export", target="books", detail={"what": "receipts.csv", "from": f["from"], "to": f["to"], "count": len(hit)})
    c.commit()
    return Response(data, mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{_fname(f, "csv")}"', "Cache-Control": "no-store"})


@app.get("/api/office/books/receipts.zip")
def rcl_zip():
    """The same filters -> a ZIP: belege.csv + belege/ with the original files (as uploaded, no conversion). The limits
    of the files ZIP (files/bulk.py, 413 before anything is sent), built in a temporary file like bkexport.bx_zip."""
    from ..files.bulk import abm_send_zip
    from .ledger import ofx_log
    c, uid, oid = _rcl_export_ctx()
    f, rows, hit = _rcl_load(c, oid, uid)
    path, put, missing = rcl_zip_file(c, oid, hit)
    ofx_log(c, oid, "export", target="books", detail={"what": "receipts.zip", "from": f["from"], "to": f["to"], "count": put,
                                                      "missing": missing})
    c.commit()
    return abm_send_zip(path, _fname(f, "zip"))


def rcl_zip_file(c, oid, hit):
    """-> (path of the ZIP, files put in, files missing). A receipt whose file cannot be read stays in the CSV without a
    file name."""
    from ..files.bulk import ABM_BUSY, ABM_ZIP_MAX_MB, abm_too_big
    from ..files.store import fs_read
    msg = abm_too_big(len(hit) + 1, sum(x["size"] for x in hit))
    if msg:
        raise Denied(413, msg)
    fd, path = tempfile.mkstemp(prefix="kalmido-receipts-", suffix=".zip")
    if not ABM_BUSY.acquire(blocking=False):
        os.close(fd)
        os.unlink(path)
        raise Denied(429, tr("Too many requests"))
    put, missing, size, cap = 0, 0, 0, ABM_ZIP_MAX_MB * 1024 * 1024
    stamp = local_now().timetuple()[:6]
    try:
        with os.fdopen(fd, "wb") as fh, zipfile.ZipFile(fh, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            for x in hit:
                try:
                    data = fs_read(c, x["node_id"])
                except (Denied, OSError, OrgCryptError):
                    missing += 1  # no content (a version locked by the virus scan, a lost file / key): the CSV row stays
                    x["zip_name"] = ""
                    continue
                size += len(data)
                if size > cap:
                    raise Denied(413, abm_too_big(0, size))
                x["zip_name"] = "belege/" + rcl_file_name(x)
                zi = zipfile.ZipInfo(x["zip_name"], date_time=stamp)
                zi.compress_type = zipfile.ZIP_STORED if x["mime"].startswith("image/") or x["mime"] == "application/pdf" else zipfile.ZIP_DEFLATED
                z.writestr(zi, data)
                put += 1
            z.writestr("belege.csv", rcl_csv_text(c, oid, hit).encode("utf-8"))
    except BaseException:
        os.unlink(path)
        raise
    finally:
        ABM_BUSY.release()
    return path, put, missing
