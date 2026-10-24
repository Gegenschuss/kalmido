"""2.120.0 D (#2089): delivery notes / proofs of service (office_docs kind "delivery") and the timesheet of an invoice.

POST /api/office/docs/<id>/delivery     {title?: "delivery" | "service"} a delivery note draft from quotation / invoice <id>
                                        (positions without prices, recipient, project, language taken over; source_doc_id)
GET  /api/office/docs/<id>/timesheet.pdf   the time entries of the invoice's client in its period of service as a PDF
                                        (invoices only; ?inline=1 shows it in the browser)
The delivery note itself is created / edited / finalised / sent through the normal document routes (office/docs.py,
ledger.py, invoices.py: kind "delivery", own number series, no tax, no e-invoice, no payment state); the print model
carries noprice (office/pdf.py draws no price columns, no totals and the receipt box "received / accepted").
The timesheet is made on demand (never stored): the same entries as the time report of the signed-in person (what they may
see, rounding of their settings); the main PDF / ZUGFeRD file of the invoice stays as it is, the sheet is a separate file."""
from flask import jsonify, request

from ..core.config import app
from ..core.db import body, bump, db
from ..core.access import Denied, vis_sql
from ..core.i18n import LANGS, tr
from ..core.errors import BadInput
from .model import office_gate, office_org, office_role, office_settings, pb_cl_sql
from .ledger import ofx_log
from .invoices import ofi_ref_doc, ofi_ref_keep  # 2.269.0 D (#3046)

LS_MAX_ENTRIES = 3000
LS_KINDS = ("offer", "invoice")  # what a delivery note is made from


from .model import office_ctx as _ctx  # noqa: E402  2.149.0 G (#2517): was an own copy


def ls_items(c, oid, src):
    """The positions of source document src without prices: titles, details, quantities and units (headings / texts as they
    are; automatic lines, discounts and percent positions have no meaning without prices and are left out)."""
    from .docs import doc_items
    from .parts import tp_inv_items
    rows = tp_inv_items(c, oid, src, "full", None) if src["kind"] == "offer" else None
    if rows is None:
        rows = doc_items(c, src["id"], oid)
    out = []
    for it in rows:
        if it.get("kind") not in ("service", "text", "heading") or it.get("unit") == "percent":
            continue
        out.append({"kind": it["kind"], "service_id": None, "title": it.get("title") or "", "detail": it.get("detail") or "", "qty": it.get("qty"),
                    "unit": it.get("unit") or "", "rate": 0, "tax": it.get("tax") or "standard", "intext": it.get("intext") or "intern", "cost": 0,
                    "raw_fee": 0, "producing": 0, "discountable": 1})
    return out


def ls_make(c, oid, uid, src, title=""):
    """A delivery note draft from quotation / invoice row src; its number comes at finalising (OFX_NUMBER_AT_FINALIZE)."""
    from .invoices import _insert_doc, _put_rows, inv_new_row
    row = inv_new_row(c, oid, office_settings(c, oid), "delivery", src["lang"], src)
    row["delivery_title"] = "service" if title == "service" else ""
    row["source_doc_id"] = src["id"]
    did = _insert_doc(c, oid, uid, row)
    _put_rows(c, oid, did, ls_items(c, oid, src))
    return did


@app.post("/api/office/docs/<int:did>/delivery")
def ls_from_doc_post(did):
    """A delivery note (or proof of service) draft from quotation / invoice did; 201 the new document."""
    from .docs import doc_public, doc_row, recalc
    c, uid, oid = _ctx()
    r = doc_row(c, oid, did)
    if r["kind"] not in LS_KINDS:
        raise Denied(409, tr("A delivery note can be made from a quotation or an invoice only"))
    b = body()
    b = b if isinstance(b, dict) else {}
    ref, hit = ofi_ref_doc(c, oid, uid, b)  # 2.269.0 D (#3046): sent again = the delivery note made the first time
    if hit:
        return jsonify(doc_public(c, oid, doc_row(c, oid, hit), office_role(c, uid, oid) == "admin"))
    nid = ls_make(c, oid, uid, r, b.get("title") if b.get("title") in ("delivery", "service") else "")
    ofi_ref_keep(c, nid, ref)
    recalc(c, oid, nid)
    ofx_log(c, oid, "create", doc_id=nid, detail={"kind": "delivery", "from_id": did, "from_number": r["number"]})
    bump(c)
    c.commit()
    return jsonify(doc_public(c, oid, doc_row(c, oid, nid), office_role(c, uid, oid) == "admin")), 201


# ---------------------------------------------------------------- the timesheet of an invoice
def ls_sheet_ok(r):
    """True when invoice row r can have a timesheet: a client and a period of service."""
    return r["kind"] == "invoice" and bool(r["client_id"]) and bool(r["service_from"] and r["service_to"])


def ls_sheet_report(c, oid, uid, r):
    """The report (personal.timetrack.time_report) of the lists of the invoice's client in its period: exactly what the
    signed-in person sees in the time report (visibility, rounding); BadInput without entries."""
    from ..personal.timetrack import n43_admin_lists, time_report
    if not ls_sheet_ok(r):
        raise BadInput(tr("The timesheet needs an invoice with a client and a period of service"))
    lists = [x[0] for x in c.execute(
        f"SELECT l.id FROM lists l WHERE l.client_id=? AND {pb_cl_sql(c, oid, 'l.org_id', 'l.owner_id')} AND l.id IN {vis_sql()}", (r["client_id"], uid, uid))]
    rep = time_report(c, uid, {"from": r["service_from"], "to": r["service_to"], "scope": "all", "lists": ",".join(str(x) for x in lists) or "-1"},
                      own=n43_admin_lists(c, uid)) if lists else None
    if not rep or not rep["entries"]:
        raise BadInput(tr("There are no time entries for this client in the period of service"))
    if len(rep["entries"]) > LS_MAX_ENTRIES:
        raise BadInput(tr("Too many time entries for one timesheet (at most {0})", LS_MAX_ENTRIES))
    return rep


def ls_hours(sec, lang, fmt=None):
    from .pdf import pdf_num
    return pdf_num(round(sec / 3600, 2), lang, fmt) + " h"


def ls_sheet_model(c, oid, uid, r):
    """The print model of the timesheet of invoice row r: the invoice's letterhead and recipient, one table row per entry
    (date | person and activity | hours, grouped by list), the total hours below."""
    from .pdf import pdf_date
    from .pdfweb import _model
    rep = ls_sheet_report(c, oid, uid, r)
    m = _model(c, oid, r["id"])
    lang = m.get("lang") if m.get("lang") in LANGS else "de"  # 2.185.0 C (#2520): the model's language (docs.odoc_render: doc_lg)
    fmt = m.get("formats") or {}
    order = {x["id"]: i for i, x in enumerate(rep["lists"])}
    names = {x["id"]: x["name"] for x in rep["lists"]}
    ents = sorted(rep["entries"], key=lambda e: (order.get(e["list_id"] or 0, 0), e["start"], e["id"]))
    lines, cur = [], object()
    for e in ents:
        lid = e["list_id"] or 0
        if lid != cur:
            cur = lid
            lines.append({"kind": "heading", "title": names.get(lid) or tr("No project", lg=lang)})
        what = " · ".join(x for x in (e["title"], (e["note"] or "").strip()) if x)
        who = e["user_name"] or ""
        lines.append({"kind": "item", "pos": pdf_date(e["day"], lang, fmt), "title": f"{who}: {what}" if who and what else (who or what),
                      "detail": "", "qty_text": ls_hours(e["rounded"], lang, fmt), "unit": ""})
    total = rep["total"]["rounded"]
    ml = dict(m.get("labels") or {})
    ml.update(pos=tr("Date", lg=lang), service=tr("Person and activity", lg=lang), qty=tr("Hours", lg=lang))
    sf, st = r["service_from"], r["service_to"]
    per = pdf_date(sf, lang, fmt) if sf == st else f"{pdf_date(sf, lang, fmt)} – {pdf_date(st, lang, fmt)}"
    m.update(title=tr("Timesheet", lg=lang), intro=tr("Time entries to invoice {0}", r["number"] or "", lg=lang), closing="", signature="", signature_name="",
             lines=lines, labels=ml, noprice=True, pos_w=62, payment=None, reminder=None, vat_note_text="", valid_note="", fx_note="", accepted=None,
             rights={"title": "", "rows": [], "exceptions": "", "exclusive": 0, "note": ""}, fields=[],
             meta=[[tr("Invoice no.", lg=lang), r["number"] or ""], [tr("Period of service", lg=lang), per]],
             totals={"rows": [[tr("Total hours", lg=lang), ls_hours(total, lang, fmt)]], "show_tax_lines": False})
    return m


def ls_sheet_file(c, oid, uid, r):
    """(file name, PDF bytes, mime) of the timesheet of invoice row r (for the PDF menu and the invoice mail)."""
    from .pdf import office_pdf
    from .pdfweb import epdf_name
    return ("timesheet-" + epdf_name(r) + ".pdf", office_pdf(ls_sheet_model(c, oid, uid, r)), "application/pdf")


@app.get("/api/office/docs/<int:did>/timesheet.pdf")
def ls_sheet_get(did):
    from .docs import doc_row
    from .pdfweb import _file_response
    c, uid, oid = _ctx()
    r = doc_row(c, oid, did)
    name, data, mime = ls_sheet_file(c, oid, uid, r)
    ofx_log(c, oid, "pdf", doc_id=did, detail={"file": "timesheet"}, dedupe_min=10)
    c.commit()
    return _file_response(data, name, mime, inline=request.args.get("inline") == "1")
