"""2.147.0 (#2461): the neutral bookkeeping export -- for any tax advisor, in every country pack (function books.export_csv).

A booking list of a period as CSV and, as a ZIP, the same list with the files behind it: the issued invoices / credit notes
(the stored PDF and e-invoice XML, as mailed) and the receipt files of the office's documents space. One row per tax rate of
a document, payments received, receipts and travel receipts; amounts in the office currency, signed (income and payments
received plus, credit notes / refunds, receipts and travel minus), so the rows of a type add up.

Same rights as the bookkeeping: admins of the office area only (a personal office: its owner), agents and kids 403
(office_gate). The CSV follows the pack's number format: decimal comma -> semicolon separated (as DE spreadsheets), else
comma separated with a decimal point. Nothing is booked or changed; the export is logged in the office log."""
import csv
import io
import os
import tempfile
import zipfile
from datetime import date

from flask import Response, jsonify, request

from ..core.access import Denied
from ..core.config import app
from ..core.db import db, local_now
from ..core.i18n import N_, tr
from ..core.errors import BadInput
from .calc import dec, dstr, money
from .model import office_gate, office_need_feature, office_org, office_settings

BX_COLS = ("type", "date", "number", "counterparty", "text", "category", "tax_pct", "net", "tax", "gross", "currency", "file")
BX_DAYS_MAX = 3 * 366  # one export covers at most three years
BX_TYPES = {"invoice": N_("Invoice"), "credit": N_("Credit note"), "payment": N_("Payment"), "receipt": N_("Receipt"), "travel": N_("Travel expenses")}


def _ctx():
    c = db()
    uid = office_gate(c)
    oid = office_org(c, uid, admin=True)
    office_need_feature(c, oid, "books.export_csv")
    return c, uid, oid


def _period():
    """?from / ?to (ISO days, both included); default: the current year up to today."""
    today = local_now().date()
    a = (request.args.get("from") or f"{today.year}-01-01").strip()
    b = (request.args.get("to") or today.isoformat()).strip()
    try:
        d0, d1 = date.fromisoformat(a), date.fromisoformat(b)
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "from / to"))
    if d1 < d0:
        raise BadInput(tr("The end lies before the start"))
    if (d1 - d0).days > BX_DAYS_MAX:
        raise BadInput(tr("Choose at most three years"))
    return d0.isoformat(), d1.isoformat()


def _j(s):
    import json
    try:
        v = json.loads(s) if s else {}
    except ValueError:
        return {}
    return v if isinstance(v, dict) else {}


def _fx(r, home):
    """The document's rate to the office currency: the frozen totals first, else as the bookkeeping (books._fx, USD 1.09)."""
    if (r["currency"] or home).upper() == home:
        return dec(1)
    f = dec(_j(r["totals"]).get("fx_rate") or 0)
    if f > 0:
        return f
    from .books import _fx as bk_fx
    return bk_fx(r, home)


def bx_rows(c, oid, frm, to):
    """-> (rows, docs, receipts): rows = dicts of BX_COLS (amounts as Decimal), docs = [(doc id, row)] of the issued
    documents, receipts = [(node id, row)] of the receipt files."""
    from .books import _home, bk_payments, bk_receipts
    from .pdfweb import epdf_name
    from .travel import rk_cat_label, rk_trips
    s = office_settings(c, oid)
    home = _home(s)
    rows, docs, recs = [], [], []
    for r in c.execute("SELECT d.*, cl.name AS bx_client FROM office_docs d LEFT JOIN clients cl ON cl.id=d.client_id WHERE d.org_id=? "
                       "AND d.kind IN ('invoice','credit') AND d.locked_at IS NOT NULL AND d.number != '' AND d.date>=? AND d.date<=? "
                       "AND d.trial=0 ORDER BY d.date, d.number", (oid, frm, to)).fetchall():  # 2.144.10 B (#2576): no trial documents
        t, fx, sign = _j(r["totals"]), _fx(r, home), (-1 if r["kind"] == "credit" else 1)
        who = (_j(r["recipient"]).get("name") or r["bx_client"] or "").strip()
        f = "documents/" + epdf_name(r) + ".pdf"
        parts = []
        if (r["vat_mode"] or "vat") != "novat":
            for tl in t.get("tax_lines") or []:
                parts.append((dec(tl.get("pct") or 0), dec(tl.get("base") or 0), dec(tl.get("amount") or 0)))
        if not parts:
            parts.append((dec(0), dec(t.get("gross") or 0), dec(0)))
        for pct, base, tax in parts:
            net, tx = money(base / fx) * sign, money(tax / fx) * sign
            rows.append({"type": r["kind"], "date": r["date"], "number": r["number"], "counterparty": who, "text": r["project_title"] or "",
                         "category": "", "tax_pct": pct.normalize(), "net": net, "tax": tx, "gross": net + tx, "currency": home, "file": f})
        docs.append((r["id"], r))
    for p, r in bk_payments(c, oid, frm, to, home):
        a = money(dec(p["amount"]) / _fx(r, home)) * (-1 if r["kind"] == "credit" else 1)
        rows.append({"type": "payment", "date": p["date"], "number": r["number"], "counterparty": (_j(r["recipient"]).get("name") or "").strip(),
                     "text": "", "category": "", "tax_pct": "", "net": "", "tax": "", "gross": a, "currency": home, "file": ""})
    for rc in bk_receipts(c, oid, frm, to, by="doc"):
        rows.append({"type": "receipt", "date": rc["date"], "number": "", "counterparty": "", "text": rc["title"], "category": rc["category"],
                     "tax_pct": dec(rc["vat_pct"]) if rc["vat_pct"] is not None else "", "net": -rc["net"], "tax": -rc["vat"],
                     "gross": -rc["amount"], "currency": home, "file": rc["title"] or ""})
        recs.append((rc["node_id"], rows[-1]))
    seen = set()
    for y in range(int(frm[:4]), int(to[:4]) + 1):
        for tr_ in rk_trips(c, oid, year=str(y)):
            for it in tr_["items"]:
                day = it["date"] or tr_["date_from"] or ""
                if not (frm <= day <= to) or it["id"] in seen:
                    continue
                seen.add(it["id"])
                a = money(dec(it["amount_home"] or 0))
                rows.append({"type": "travel", "date": day, "number": "", "counterparty": "", "text": it["text"] or tr_.get("purpose") or "",
                             "category": rk_cat_label(it["category"] or "other"), "tax_pct": "", "net": -a, "tax": "", "gross": -a,
                             "currency": home, "file": ""})
    rows.sort(key=lambda x: (x["date"] or "", list(BX_TYPES).index(x["type"]), x["number"]))
    return rows, docs, recs


def _zip_part(name):
    from ..files.bulk import abm_zip_name
    return abm_zip_name(name)


def bx_csv(c, oid, rows):
    """The booking list as CSV text (BOM, CRLF), separator and decimal mark from the country pack."""
    from .books import bk_csv_cell
    from .packs import office_pack_for
    comma = ((office_pack_for(office_settings(c, oid)) or {}).get("formats") or {}).get("decimal") == ","
    num = (lambda v: "" if v == "" else dstr(money(dec(v))).replace(".", ",")) if comma else (lambda v: "" if v == "" else dstr(money(dec(v))))  # noqa: E731
    pct = (lambda v: "" if v == "" else format(dec(v).normalize(), "f").replace(".", ",")) if comma else (lambda v: "" if v == "" else format(dec(v).normalize(), "f"))  # noqa: E731
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";" if comma else ",", lineterminator="\r\n")
    w.writerow([tr("Type"), tr("Date"), tr("Number"), tr("Counterparty"), tr("Text"), tr("Category"), tr("VAT %"), tr("Net"), tr("VAT"),
                tr("Gross"), tr("Currency"), tr("File")])
    for r in rows:
        w.writerow([tr(BX_TYPES[r["type"]]), r["date"], bk_csv_cell(r["number"]), bk_csv_cell(r["counterparty"]), bk_csv_cell(r["text"]),
                    bk_csv_cell(r["category"]), pct(r["tax_pct"]), num(r["net"]), num(r["tax"]), num(r["gross"]), r["currency"], bk_csv_cell(r["file"])])
    return "﻿" + buf.getvalue()


@app.get("/api/office/books/export")
def bx_export():
    """Office admin. ?from=YYYY-MM-DD&to=YYYY-MM-DD (default: this year) -> the booking list as CSV; &zip=1 -> a ZIP with the
    list and the files (documents/: PDF + XML of the issued invoices and credit notes, receipts/: the receipt files);
    &check=1 -> {from, to, rows, documents, receipts} only (the page shows it before the download)."""
    from .ledger import ofx_log
    c, uid, oid = _ctx()
    frm, to = _period()
    rows, docs, recs = bx_rows(c, oid, frm, to)
    if request.args.get("check"):
        return jsonify(**{"from": frm, "to": to}, rows=len(rows), documents=len(docs), receipts=len(recs))
    stem = f"{tr('bookings')}-{frm}-{to}"
    want_zip = request.args.get("zip") == "1"
    ofx_log(c, oid, "export", target="books", detail={"what": "export.zip" if want_zip else "export.csv", "from": frm, "to": to, "rows": len(rows)})
    if not want_zip:
        data = bx_csv(c, oid, rows)
        c.commit()
        return Response(data, mimetype="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{stem}.csv"', "Cache-Control": "no-store"})
    path = bx_zip(c, oid, rows, docs, recs, stem)
    c.commit()
    from ..files.bulk import abm_send_zip
    return abm_send_zip(path, stem + ".zip")


def bx_zip(c, oid, rows, docs, recs, stem):
    """The ZIP in a temporary file (the limits of the files ZIP; Denied(413) before anything is sent, no half ZIP)."""
    from ..files.bulk import ABM_BUSY, ABM_ZIP_MAX_FILES, ABM_ZIP_MAX_MB, abm_too_big, abm_unique
    from ..files.store import fs_read
    from .pdfweb import epdf_doc_files
    if len(docs) * 2 + len(recs) + 1 > ABM_ZIP_MAX_FILES:
        raise Denied(413, abm_too_big(len(docs) * 2 + len(recs) + 1, 0))
    fd, path = tempfile.mkstemp(prefix="kalmido-books-", suffix=".zip")
    if not ABM_BUSY.acquire(blocking=False):
        os.close(fd)
        os.unlink(path)
        raise Denied(429, tr("Too many requests"))
    size, cap = 0, ABM_ZIP_MAX_MB * 1024 * 1024
    try:
        with os.fdopen(fd, "wb") as f, zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            taken = {"documents": set(), "receipts": set()}
            for did, r in docs:
                try:
                    files = epdf_doc_files(c, oid, did)
                except (OSError, Denied, BadInput):
                    continue  # a damaged stored file: the list names it, the rest still comes
                for name, data, _mime in files:
                    size += len(data)
                    if size > cap:
                        raise Denied(413, abm_too_big(0, size))
                    z.writestr("documents/" + abm_unique(_zip_part(name), taken["documents"]), data)
            for nid, row in recs:
                try:
                    data = fs_read(c, nid)
                except (OSError, Denied):
                    row["file"] = ""
                    continue
                n = c.execute("SELECT name FROM fs_nodes WHERE id=?", (nid,)).fetchone()
                name = abm_unique(_zip_part(f"{row['date'] or ''} {(n['name'] if n else '') or nid}"), taken["receipts"])
                row["file"] = "receipts/" + name
                size += len(data)
                if size > cap:
                    raise Denied(413, abm_too_big(0, size))
                z.writestr(row["file"], data)
            z.writestr(stem + ".csv", bx_csv(c, oid, rows).encode("utf-8"))
    except BaseException:
        os.unlink(path)
        raise
    finally:
        ABM_BUSY.release()
    return path
