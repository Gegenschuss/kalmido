"""2.147.0 (#2461): the neutral bookkeeping export -- for any tax advisor, in every country pack (function books.export_csv).

A booking list of a period as CSV and, as a ZIP, the same list with the files behind it: the issued invoices / credit notes
(the stored PDF and e-invoice XML, as mailed) and the receipt files of the office's documents space. One row per tax rate of
a document, payments received, receipts, travel receipts and (2.534.0, #4333) entertainment receipts (70 % / 30 %); amounts in the office currency, signed (income and payments
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

from ..core.access import Denied, live_sql
from ..core.config import app
from ..core.db import db, local_now
from ..core.i18n import N_, tr
from ..core.errors import BadInput
from .books import bk_gaps_text, ofc_meals_euer  # 2.534.0 (#4333): ofc_meals_*; 2.764.0 (#5313): ofc_meals_home through bk_meals_receipts
from .books import bk_meals_receipts, bk_meals_strict, bk_receipts_basis  # 2.610.0 (#4932); 2.764.0 (#5313): bk_meals_receipts
from .euerbasis import EB_NORC_LABEL, eb_income_payment_ids, eb_segments  # 2.610.0 (#4932)
from .calc import dec, dstr, money
from .model import office_gate, office_need_feature, office_org, office_settings
from .books import _fx as bk_fx, _home, _split, bk_payments, bk_csv_cell  # 2.369.5 (#2517): pulled up from functions
from .pdfweb import epdf_name, epdf_doc_files  # 2.369.5 (#2517): pulled up from functions
from .travel import rk_cat_label, rk_trips  # 2.369.5 (#2517): pulled up from functions
from ..files.bulk import abm_zip_name, abm_send_zip, ABM_BUSY, ABM_ZIP_MAX_FILES, ABM_ZIP_MAX_MB, abm_too_big, abm_unique  # 2.369.5 (#2517): pulled up from functions
from .packs import office_pack_for  # 2.369.5 (#2517): pulled up from functions
from .ledger import ofx_log  # 2.369.5 (#2517): pulled up from functions
from ..files.store import fs_read  # 2.369.5 (#2517): pulled up from functions
from .meals import BW_SHARE  # 2.616.0 (#4563): bx_meal_parts

BX_COLS = ("type", "date", "number", "counterparty", "text", "category", "tax_pct", "net", "tax", "gross", "currency", "file")
BX_DAYS_MAX = 3 * 366  # one export covers at most three years
BX_TYPES = {"invoice": N_("Invoice"), "credit": N_("Credit note"), "payment": N_("Payment"), "receipt": N_("Receipt"), "travel": N_("Travel expenses"),
            "card": N_("Credit card"), "meal": N_("Entertainment receipt"),  # 2.444.0 (#3447): positions of the statements (the total leaves the bank account, office/cardnorc.py)
            "booking": N_("Booking")}  # 2.610.0 (#4932): a year "bank and cash": bank / cash lines without receipt, money received without invoice
BX_OPEN = N_("Receipts without a bank, cash or card booking (basis bank and cash: they do not count and are not in the export):")
BX_OUTSIDE = N_("Payments without a bank or cash booking (basis bank and cash: they do not count and are not in the export):")


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
        raise BadInput(tr("Select at most three years"))
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
    return bk_fx(r, home)


def bx_rows(c, oid, frm, to, gaps=None):
    """-> (rows, docs, receipts): rows = dicts of BX_COLS (amounts as Decimal), docs = [(doc id, row, [its list rows])] of the
    issued documents, receipts = [(node id, row)] of the receipt files. gaps: see books.bk_receipts (2.356.0, #3097).
    2.610.0 (#4932): each year by the basis of the income statement (office/euerbasis.py), as books.bk_euer counts it: in a
    year "bank and cash" only payments of a bank / cash booking, the receipts with their line (its day and amount), the
    entertainment receipts through their line, the bank / cash lines without receipt and the money received without invoice
    as rows of their own (type booking); what does not count is named in gaps (open, outside) -> missing.txt."""
    s = office_settings(c, oid)
    home = _home(s)
    gx = {} if gaps is None else gaps  # what a strict year does not count (open, outside); gaps itself stays as the caller gave it
    segs = eb_segments(s, frm, to)
    strict = any(x[2] for x in segs)
    inc_ids = eb_income_payment_ids(c, oid) if strict else None
    small = bool(s.get("small_business"))
    meals, lines, meal_cards = [], [], set()

    def prep(a, b, flows):  # a strict year: the meals leave their lines first (no second expense), then the rest of the lines
        cards = {x["ref"] for x in flows["norc"] if x["src"] == "card"}
        meals.extend(bk_meals_strict(c, oid, flows, a, b, s))
        meal_cards.update(cards - {x["ref"] for x in flows["norc"] if x["src"] == "card"})  # review M1: a meal on an open card position
        lines.extend(x for x in flows["norc"] if x["src"] != "card")  # card positions: cardnorc.cc_bk_rows has them
        lines.extend(dict(x, income=True) for x in flows["income_open"])
    rows, docs, recs = [], [], []
    for r in c.execute("SELECT d.*, cl.name AS bx_client FROM office_docs d LEFT JOIN clients cl ON cl.id=d.client_id WHERE d.org_id=? "
                       "AND d.kind IN ('invoice','credit') AND d.locked_at IS NOT NULL AND d.number != '' AND d.date>=? AND d.date<=? "
                       f"AND d.trial=0 AND {live_sql('d')} ORDER BY d.date, d.number", (oid, frm, to)).fetchall():  # 2.144.10 B (#2576): no trial documents
        t, fx, sign = _j(r["totals"]), _fx(r, home), (-1 if r["kind"] == "credit" else 1)
        who = (_j(r["recipient"]).get("name") or r["bx_client"] or "").strip()
        f = "documents/" + epdf_name(r) + ".pdf"
        parts, mine = [], []
        if (r["vat_mode"] or "vat") != "novat":
            for tl in t.get("tax_lines") or []:
                parts.append((dec(tl.get("pct") or 0), dec(tl.get("base") or 0), dec(tl.get("amount") or 0)))
        if not parts:
            parts.append((dec(0), dec(t.get("gross") or 0), dec(0)))
        for pct, base, tax in parts:
            net, tx = money(base / fx) * sign, money(tax / fx) * sign
            rows.append({"type": r["kind"], "date": r["date"], "number": r["number"], "counterparty": who, "text": " ".join((r["project_title"] or "").split()),  # 2.431.0 B (#3594): the subject on one line
                         "category": "", "tax_pct": pct.normalize(), "net": net, "tax": tx, "gross": net + tx, "currency": home, "file": f})
            mine.append(rows[-1])
        docs.append((r["id"], r, mine))
    for p, r in bk_payments(c, oid, frm, to, home):
        if inc_ids is not None and p["id"] not in inc_ids and any(a_ <= p["date"] <= b_ for a_, b_, x in segs if x):
            gx.setdefault("outside", []).append(f"{p['date']} {r['number']}")  # 2.610.0 (#4932): typed by hand, no bank / cash booking
            continue
        a = money(dec(p["amount"]) / _fx(r, home)) * (-1 if r["kind"] == "credit" else 1)
        rows.append({"type": "payment", "date": p["date"], "number": r["number"], "counterparty": (_j(r["recipient"]).get("name") or "").strip(),
                     "text": "", "category": "", "tax_pct": "", "net": "", "tax": "", "gross": a, "currency": home, "file": ""})
    opened = []
    for rc in bk_receipts_basis(c, oid, frm, to, by="doc", gaps=gaps, open_=opened, prep=prep):  # 2.610.0 (#4932)
        rows.append({"type": "receipt", "date": rc["date"], "number": "", "counterparty": "", "text": rc["title"], "category": rc["category"],
                     "tax_pct": dec(rc["vat_pct"]) if rc["vat_pct"] is not None else "", "net": -rc["net"], "tax": -rc["vat"],
                     "gross": -rc["amount"], "currency": home, "file": rc["title"] or ""})
        recs.append((rc["node_id"], rows[-1]))
    if opened:
        gx["open"] = [f"{rc['date']} {rc['title']}" for rc in opened]
    for x in lines:  # 2.610.0 (#4932): the bank / cash lines of a strict year without receipt (gross, no input tax)
        a = money(x["amount"]) * (1 if x.get("income") else -1)
        txt = tr("Money received without invoice") if x.get("income") else tr(EB_NORC_LABEL) if x.get("missing") else tr("No receipt needed")
        rows.append({"type": "booking", "date": x["day"], "number": "", "counterparty": x.get("text") or "",
                     "text": f"{tr('Cash book') if x.get('src') == 'cash' else tr('Bank booking')}: {txt}", "category": x.get("category") or "",
                     "tax_pct": "", "net": a, "tax": "", "gross": a, "currency": home, "file": ""})
    seen = set()
    for y in range(int(frm[:4]) - 1, int(to[:4]) + 2):  # 2.764.0 (#5313): + the neighbour years (an item of a trip of the next year)
        for tr_ in rk_trips(c, oid, year=str(y)):
            for it in tr_["items"]:
                day = it["date"] or tr_["date_from"] or ""
                if not (frm <= day <= to) or it["id"] in seen:
                    continue
                seen.add(it["id"])
                a = money(dec(it["amount_home"] or 0))
                vp = None if s.get("small_business") else it.get("vat_pct")  # 2.545.0 (#4387): a travel receipt with a VAT rate: net + input tax
                n_, t_ = _split(a, vp)
                rows.append({"type": "travel", "date": day, "number": "", "counterparty": "", "text": it["text"] or tr_.get("purpose") or "",
                             "category": rk_cat_label(it["category"] or "other"), "tax_pct": dec(vp) if vp else "", "net": -n_, "tax": -t_ if vp else "",
                             "gross": -a, "currency": home, "file": ""})
    # 2.534.0 (#4333): the approved entertainment receipts, two rows each: the deductible 70 % with the full input tax and
    # the 30 % that are not deductible (a small business: 70 / 30 of the gross amount, no input tax) -- gross adds up to the bill
    if strict:  # 2.610.0 (#4932): the years by receipts as before, the strict ones through their lines (prep)
        meals += [m for a_, b_, x in segs if not x for m in bk_meals_receipts(c, oid, a_, b_, s)]  # 2.764.0 (#5313): + the edge
    else:
        meals = bk_meals_receipts(c, oid, frm, to, s)  # 2.764.0 (#5313): a receipts year next to a strict one has an edge
    for m in meals:
        v, sm = ofc_meals_euer([m], small)
        nd = dec(sm["not_deductible"])
        ded = [(tr("Entertainment (70 % deductible)"), pct, net, tax) for pct, net, tax in bx_meal_parts(m, v)]  # 2.616.0 (#4563): per VAT rate
        for cat, pct, net, tax in ded + [(tr("Entertainment (30 % not deductible)"), "", nd, dec(0))]:
            rows.append({"type": "meal", "date": m["date"], "number": "", "counterparty": "", "text": m["title"], "category": cat, "tax_pct": pct,
                         "net": -net, "tax": -tax if tax else "", "gross": -(net + tax), "currency": home, "file": ""})
    from .cardnorc import cc_bk_rows
    rows += cc_bk_rows(c, oid, frm, to, meals=meal_cards)  # 2.444.0 (#3447); review M1: the meal's position without its amount
    rows.sort(key=lambda x: (x["date"] or "", list(BX_TYPES).index(x["type"]), x["number"]))
    return rows, docs, recs


def bx_meal_parts(m, v):
    """2.616.0 (#4563): the deductible part of meal m (ofc_meals_home row) as [(tax_pct | "", net, tax)]: v = ofc_meals_euer's
    [net, vat, gross]. A small business (no input tax) or a meal without lines: one row without a rate. Else one row per VAT
    rate of its lines (70 % of their net, their full input tax) and the tip (no VAT) at 0 %; the last row takes the rounding
    cents so the rows add up to v exactly (the EUeR line)."""
    if not v[1] or not m.get("rates"):
        return [("", v[0], v[1])]
    by = {}
    for pct, net, tax in m["rates"]:
        n0, t0 = by.get(pct, (dec(0), dec(0)))
        by[pct] = (n0 + net, t0 + tax)
    if m.get("tip"):
        n0, t0 = by.get(dec(0), (dec(0), dec(0)))
        by[dec(0)] = (n0 + m["tip"], t0)
    out = [(pct.normalize(), money(net * BW_SHARE), money(tax)) for pct, (net, tax) in sorted(by.items(), key=lambda x: -x[0])]
    pct, net, tax = out[-1]
    out[-1] = (pct, net + v[0] - sum((x[1] for x in out), dec(0)), tax + v[1] - sum((x[2] for x in out), dec(0)))
    return out


def _zip_part(name):
    return abm_zip_name(name)


def bx_csv(c, oid, rows):
    """The booking list as CSV text (BOM, CRLF), separator and decimal mark from the country pack."""
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
    c, uid, oid = _ctx()
    frm, to = _period()
    gaps = {}
    rows, docs, recs = bx_rows(c, oid, frm, to, gaps)
    if request.args.get("check"):  # 2.356.0 (#3097): + what the export leaves out
        return jsonify(**{"from": frm, "to": to}, rows=len(rows), documents=len(docs), receipts=len(recs),
                       no_date=len(gaps.get("no_date") or ()), no_amount=len(gaps.get("no_amount") or ()), hidden=gaps.get("hidden", 0),
                       open=len(gaps.get("open") or ()), outside=len(gaps.get("outside") or ()))  # 2.610.0 (#4932)
    stem = f"{tr('bookings')}-{frm}-{to}"
    want_zip = request.args.get("zip") == "1"
    ofx_log(c, oid, "export", target="books", detail={"what": "export.zip" if want_zip else "export.csv", "from": frm, "to": to, "rows": len(rows)})
    if not want_zip:
        data = bx_csv(c, oid, rows)
        c.commit()
        return Response(data, mimetype="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{stem}.csv"', "Cache-Control": "no-store"})
    path = bx_zip(c, oid, rows, docs, recs, stem, gaps)
    c.commit()
    return abm_send_zip(path, stem + ".zip")


def bx_zip(c, oid, rows, docs, recs, stem, gaps=None):
    """The ZIP in a temporary file (the limits of the files ZIP; Denied(413) before anything is sent, no half ZIP).
    2.356.0 (#3097): the list's "file" column is the name inside the ZIP; files that cannot be read and receipts left out
    (gaps) are named in missing.txt instead of being skipped silently."""
    cards = [r for r in rows if r.get("_node")]  # 2.444.0 (#3447): the statements' PDFs and the receipts of the positions
    if len(docs) * 2 + len(recs) + len(cards) + 2 > ABM_ZIP_MAX_FILES:  # + the list and missing.txt
        raise Denied(413, abm_too_big(len(docs) * 2 + len(recs) + len(cards) + 2, 0))
    fd, path = tempfile.mkstemp(prefix="kalmido-books-", suffix=".zip")
    if not ABM_BUSY.acquire(blocking=False):
        os.close(fd)
        os.unlink(path)
        raise Denied(429, tr("Too many requests"))
    size, cap = 0, ABM_ZIP_MAX_MB * 1024 * 1024
    try:
        with os.fdopen(fd, "wb") as f, zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            taken = {"documents": set(), "receipts": set(), "cards": set()}
            missing = []
            for did, r, mine in docs:
                try:
                    files = epdf_doc_files(c, oid, did, zugferd_xml=True)  # 2.434.0 (#3616): the books ZIP keeps the XML
                except (OSError, Denied, BadInput):
                    missing.append((tr("Invoice"), r["number"]))  # a damaged stored file: named in missing.txt, the rest still comes
                    for row in mine:
                        row["file"] = ""
                    continue
                for name, data, _mime in files:
                    size += len(data)
                    if size > cap:
                        raise Denied(413, abm_too_big(0, size))
                    zn = "documents/" + abm_unique(_zip_part(name), taken["documents"])
                    z.writestr(zn, data)
                    if name.endswith(".pdf"):
                        for row in mine:
                            row["file"] = zn
            for nid, row in recs:  # 2.306.0 D2 (#2875): recs = bk_receipts of the signed-in person (fs_role filtered there)
                try:
                    data = fs_read(c, nid)  # sc_guard inside: a file found infected stays out, the list keeps the line
                except (OSError, Denied):
                    missing.append((tr("Receipt"), row["file"] or str(nid)))
                    row["file"] = ""
                    continue
                n = c.execute("SELECT name FROM fs_nodes WHERE id=?", (nid,)).fetchone()
                name = abm_unique(_zip_part(f"{row['date'] or ''} {(n['name'] if n else '') or nid}"), taken["receipts"])
                row["file"] = "receipts/" + name
                size += len(data)
                if size > cap:
                    raise Denied(413, abm_too_big(0, size))
                z.writestr(row["file"], data)
            done = {}
            for row in cards:  # 2.444.0 (#3447): one file once, however many rows point at it
                nid = row["_node"]
                if nid not in done:
                    try:
                        data = fs_read(c, nid)
                    except (OSError, Denied):
                        missing.append((tr(BX_TYPES["card"]), row["number"]))
                        done[nid] = ""
                        continue
                    n = c.execute("SELECT name FROM fs_nodes WHERE id=?", (nid,)).fetchone()
                    done[nid] = "cards/" + abm_unique(_zip_part(f"{row['date'] or ''} {(n['name'] if n else '') or nid}"), taken["cards"])
                    size += len(data)
                    if size > cap:
                        raise Denied(413, abm_too_big(0, size))
                    z.writestr(done[nid], data)
                row["file"] = done[nid]
            z.writestr(stem + ".csv", bx_csv(c, oid, rows).encode("utf-8"))
            note = bk_gaps_text(gaps or {}, missing)
            for key, head in (("open", BX_OPEN), ("outside", BX_OUTSIDE)):  # 2.610.0 (#4932): a year "bank and cash"
                if (gaps or {}).get(key):
                    note += "\r\n".join([tr(head)] + [f"- {n}" for n in gaps[key]]) + "\r\n"
            if note:
                z.writestr(tr("missing") + ".txt", note.encode("utf-8"))
    except BaseException:
        os.unlink(path)
        raise
    finally:
        ABM_BUSY.release()
    return path
