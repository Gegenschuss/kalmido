"""2.467.0 (#3456): the Anlage EUeR and the annual VAT return (USt 2 A) line by line, to type into ELSTER.

Nothing is filed (no ERiC) and nothing is booked here: the figures come from books.bk_euer and books.bk_ustva(period y), this
module only sorts them onto the lines of the official form of the year. The form changes every year, so the lines live in one
table per tax year, each with its source; a year without a table gets a clear note instead of lines of another year.

Rules of the sorting:
 - a line is only filled when Kalmido really knows the amount belongs there. Receipt categories are free text: only the exact
   names of TF_CATS reach a line of their own, everything else stands in "other expenses" (line of Kz 183).
 - the sums equal bk_euer: line of Kz 159 = income gross + VAT refunds, line of Kz 199 = expenses gross + VAT paid; the profit of
   the form differs from the profit of bk_euer (net) by the VAT balance, the answer names it.
 - VAT paid to and refunded by the tax office leaves no receipt: the office admin enters both per year (office setting
   tax_form_vat, set only by the route here). Advance payments of the annual return follow from the rhythm of the tax dates.
 - a small business has no VAT lines and no annual VAT return here (the note says so).
Labels are the wording of the form and stay German in every language: people compare them with ELSTER."""
import csv
import io
from decimal import Decimal, InvalidOperation

from flask import Response, jsonify, request

from ..core.config import app
from ..core.db import body, bump
from ..core.errors import BadInput
from ..core.i18n import N_, csv_dialect, lang, tr
from .books import BK_NOTE, _ctx, _year, bk_csv_cell, bk_euer, bk_ustva
from .calc import calc_lang, dec, dstr, money
from .ledger import ofx_company, ofx_log
from .model import ofx_name1, office_need_feature, office_settings, office_settings_lock, office_settings_save
from .pdf import pdf_paper_ns
from .taxdates import txd_clean
from .pdf import C_INK2, C_RULE, pdf_money, pdf_write

TF_FEATURE = "books.vat_return"
TF_MAX = Decimal("99999999.99")  # an entered amount
# key -> (line, Kz, wording of the form); sum lines without a Kz keep None
# 2026: BMF 01.09.2026, GZ IV C 6 - S 2142/00024/010/001, Anlage EUeR 2026 (Vordruck 2026AnlEUeR801-804), read from
# https://www.bundesfinanzministerium.de/Content/DE/Downloads/BMF_Schreiben/Steuerarten/Einkommensteuer/2026-09-01-anlage-EUER-2026.pdf
# 2025: BMF 29.08.2025, GZ IV C 6 - S 2142/00023/010/001, Anlage EUeR 2025, read from
# https://www.bundesfinanzministerium.de/Content/DE/Downloads/BMF_Schreiben/Steuerarten/Einkommensteuer/2025-08-29-anlage-EUER-2025.pdf
TF_EUER_TEXT = {
    "small": "Betriebseinnahmen als umsatzsteuerlicher Kleinunternehmer", "taxed": "Umsatzsteuerpflichtige Betriebseinnahmen",
    "free": "Umsatzsteuerfreie oder nicht steuerbare Betriebseinnahmen, § 13b UStG", "vat_in": "Vereinnahmte Umsatzsteuer",
    "vat_back": "Vom Finanzamt erstattete und ggf. verrechnete Umsatzsteuer", "sum_in": "Summe Betriebseinnahmen",
    "goods": "Waren, Rohstoffe und Hilfsstoffe einschließlich der Nebenkosten", "ext": "Bezogene Fremdleistungen",
    "afa": "AfA auf bewegliche Wirtschaftsgüter", "rent": "Miete/Pacht für Geschäftsräume und betrieblich genutzte Grundstücke",
    "tel": "Aufwendungen für Telekommunikation", "travel": "Übernachtungs- und Reisenebenkosten bei Geschäftsreisen",
    "edu": "Fortbildungskosten (ohne Reisekosten)", "legal": "Kosten für Rechts- und Steuerberatung, Buchführung",
    "edv": "Laufende EDV-Kosten", "work": "Arbeitsmittel (z. B. Bürobedarf, Porto, Fachliteratur)", "ads": "Werbekosten",
    "vat_pre": "Gezahlte und nach § 15 UStG abziehbare Vorsteuerbeträge", "vat_paid": "An das Finanzamt gezahlte und ggf. verrechnete Umsatzsteuer",
    "other": "Übrige unbeschränkt abziehbare Betriebsausgaben", "meals": "Verpflegungsmehraufwendungen",
    "fares": "Sonstige tatsächliche Fahrtkosten ohne AfA und Zinsen", "km": "Fahrtkosten für nicht zum Betriebsvermögen gehörende Fahrzeuge (Nutzungseinlage)",
    "sum_out": "Summe Betriebsausgaben"}
TF_EUER = {
    2025: {"small": (12, 111), "taxed": (15, 112), "free": (16, 103), "vat_in": (17, 140), "vat_back": (18, 141), "sum_in": (23, 159),
           "goods": (27, 100), "ext": (29, 110), "afa": (33, 130), "rent": (39, 150), "tel": (43, 280), "travel": (44, 221), "edu": (45, 281),
           "legal": (46, 194), "edv": (50, 228), "work": (51, 229), "ads": (54, 224), "vat_pre": (57, 185), "vat_paid": (58, 186),
           "other": (60, 183), "meals": (64, 171), "fares": (70, 146), "km": (71, 147), "sum_out": (75, 199)},
    2026: {"small": (12, 111), "taxed": (15, 112), "free": (16, 103), "vat_in": (17, 140), "vat_back": (18, 141), "sum_in": (23, 159),
           "goods": (29, 100), "ext": (30, 110), "afa": (34, 130), "rent": (40, 150), "tel": (44, 280), "travel": (45, 221), "edu": (46, 281),
           "legal": (47, 194), "edv": (51, 228), "work": (52, 229), "ads": (55, 224), "vat_pre": (58, 185), "vat_paid": (59, 186),
           "other": (61, 183), "meals": (65, 171), "fares": (71, 146), "km": (72, 147), "sum_out": (76, 199)}}
TF_EUER_IN = ("small", "taxed", "free", "vat_in", "vat_back")
TF_EUER_OUT = ("goods", "ext", "afa", "rent", "tel", "travel", "edu", "legal", "edv", "work", "ads", "vat_pre", "vat_paid", "other", "meals", "fares", "km")
TF_ALWAYS = ("vat_paid", "vat_back")  # shown at 0 as well: the reminder to enter them
# only exact names (casefolded): a free category is no proof for a line of the form
TF_CATS = {"waren": "goods", "wareneinkauf": "goods", "material": "goods", "fremdleistungen": "ext", "fremdleistung": "ext",
           "subunternehmer": "ext", "miete": "rent", "büromiete": "rent", "raummiete": "rent", "rent": "rent", "telefon": "tel",
           "internet": "tel", "telefon/internet": "tel", "telekommunikation": "tel", "fortbildung": "edu", "weiterbildung": "edu",
           "steuerberatung": "legal", "rechtsberatung": "legal", "buchführung": "legal", "edv": "edv", "edv-kosten": "edv",
           "bürobedarf": "work", "porto": "work", "fachliteratur": "work", "arbeitsmittel": "work", "werbung": "ads",
           "werbekosten": "ads", "marketing": "ads"}
# travel categories (travel.RK_CATS): fares of the form's line "Kosten für Flugstrecken, öffentliche Verkehrsmittel", the rest
TF_TRAVEL = {"hotel": "travel", "other": "travel", "meals": "meals"}

# key -> (line, Kz), the wording in TF_UST_TEXT
# 2026: BMF 29.12.2025, GZ III C 3 - S 7344/00040/008/034, Muster der Umsatzsteuererklaerung 2026, Vordruck USt 2 A (2026USt2A501-506), read from
# https://www.bundesfinanzministerium.de/Content/DE/Downloads/BMF_Schreiben/Steuerarten/Umsatzsteuer/2025-12-29-muster-USt-erklaerung-2026.pdf
# 2025 is missing on purpose: the official Muster was not found at the BMF, a line of this table comes only from an official source
TF_UST_TEXT = {
    "b19": "Lieferungen und sonstige Leistungen zu 19 %", "b7": "Lieferungen und sonstige Leistungen zu 7 %", "bx": "Umsätze zu anderen Steuersätzen",
    "sum_tax": "Summe der Steuer", "eu": "Innergemeinschaftliche Lieferungen an Abnehmer mit USt-IdNr.", "exp": "Ausfuhrlieferungen (§ 4 Nummer 1 Buchstabe a UStG)",
    "free": "Steuerfreie Umsätze ohne Vorsteuerabzug, zum Gesamtumsatz gehörend, nach § ... UStG", "r13b": "Steuerpflichtige Umsätze, für die der Leistungsempfänger die Steuer nach § 13b Absatz 5 UStG schuldet",
    "r18b": "Nicht steuerbare sonstige Leistungen gemäß § 18b Satz 1 Nummer 2 UStG", "abroad": "Übrige nicht steuerbare Umsätze (Leistungsort nicht im Inland)",
    "pre": "Vorsteuerbeträge aus Rechnungen von anderen Unternehmern", "sum_pre": "Summe der Vorsteuerbeträge",
    "calc_tax": "Umsatzsteuer auf steuerpflichtige Lieferungen, sonstige Leistungen und unentgeltliche Wertabgaben", "calc_sub": "Zwischensumme",
    "calc_pre": "Abziehbare Vorsteuerbeträge", "due": "Umsatzsteuer / Überschuss", "left": "Verbleibende Umsatzsteuer / Verbleibender Überschuss",
    "adv": "Vorauszahlungssoll (einschließlich Sondervorauszahlung)", "final": "Abschlusszahlung / Erstattungsanspruch"}
TF_UST = {
    2026: {"b19": (24, 177), "b7": (27, 275), "bx": (33, 155), "sum_tax": (41, None), "eu": (42, 741), "exp": (45, 752), "free": (54, 240),
           "r13b": (76, 209), "r18b": (80, 721), "abroad": (81, 205), "pre": (85, 320), "sum_pre": (93, None), "calc_tax": (109, None),
           "calc_sub": (114, None), "calc_pre": (115, None), "due": (122, None), "left": (124, 816), "adv": (125, None), "final": (126, 820)}}
TF_UST_SUMS = ("sum_tax", "sum_pre", "calc_sub", "due", "left", "final")
TF_NO_YEAR = N_("There is no line assignment for the tax year {0} yet: the official form is not in Kalmido. Please use the figures of the income/expense statement.")
# 2.545.0 (#4387): receipts with reverse charge (UStVA 46 / 84, 67) have no lines in TF_UST yet (the tax advisor, #1153)
TF_13B = N_("Receipts with reverse charge (section 13b): base {0} / {1}, tax and input tax {2} each. They are not on the lines above yet; please enter them in the section 13b part of the form.")
TF_NOTE = N_("Please check the figures before filing. Nothing is sent to ELSTER.")


def _dec2(v):
    return money(dec(v or 0))


def tf_vat_year(s, year):
    """(VAT paid to the tax office, VAT refunded) of a year as entered by the office admin, Decimals."""
    d = s.get("tax_form_vat")
    y = d.get(str(year)) if isinstance(d, dict) else None
    y = y if isinstance(y, dict) else {}
    return _dec2(y.get("paid")), _dec2(y.get("refund"))


def tf_euer(c, oid, year):
    """The Anlage EUeR of a year: {year, known, small_business, rows: [{key, line, kz, label, amount, sum, from: [names]}], profit,
    profit_books, vat_balance, vat_paid, vat_refund, notes}; known False (no rows, the note says why) for a year without a table."""
    d = bk_euer(c, oid, year)
    head = {"year": year, "currency": d["currency"], "small_business": d["small_business"]}
    notes = [tr(BK_NOTE), tr(TF_NOTE)]
    if year not in TF_EUER:
        return dict(head, known=False, rows=[], notes=[tr(TF_NO_YEAR, year)] + notes)
    small = d["small_business"]
    amt, src = {k: Decimal(0) for k in TF_EUER_IN + TF_EUER_OUT}, {}
    for r in d["income"]:
        gross, vat = dec(r["gross"]), dec(r["vat"])
        if small or r["key"] == "small":
            amt["small"] += gross
        elif r["key"] in ("exempt", "fee"):  # 2.545.0 (#4387): paid reminder fees are not taxable (Kz 103)
            amt["free"] += gross
        else:
            amt["taxed"] += gross - vat
            amt["vat_in"] += vat
    for r in d["expenses"]:
        k = r["key"]
        line = "afa" if k == "a:" else "km" if k == "km" else TF_TRAVEL.get(k[2:], "fares") if k[:2] == "t:" else TF_CATS.get(k[2:], "other")
        gross, vat = dec(r["gross"]), dec(r["vat"])
        amt[line] += gross if small else gross - vat  # gross - VAT, not "net": the device of a depreciation counts with VAT only
        if not small:
            amt["vat_pre"] += vat
        src.setdefault(line, []).append(r["label"])
    s = office_settings(c, oid)
    paid, refund = (Decimal(0), Decimal(0)) if small else tf_vat_year(s, year)
    amt["vat_paid"], amt["vat_back"] = paid, refund
    t = TF_EUER[year]
    sum_in = dec(d["income_total"]["gross"]) + refund
    sum_out = dec(d["expense_total"]["gross"]) + paid
    rows = []

    def row(k, v, is_sum=False):
        rows.append({"key": k, "line": t[k][0], "kz": str(t[k][1]), "label": TF_EUER_TEXT[k], "amount": dstr(money(v)), "sum": is_sum, "from": src.get(k, [])})

    for k in TF_EUER_IN:
        if amt[k] or (k in TF_ALWAYS and not small):
            row(k, amt[k])
    row("sum_in", sum_in, True)
    for k in sorted(TF_EUER_OUT, key=lambda x: t[x][0]):
        if amt[k] or (k in TF_ALWAYS and not small):
            row(k, amt[k])
    row("sum_out", sum_out, True)
    profit = sum_in - sum_out
    books = dec(d["profit"])
    if not small and not (paid or refund):
        notes.append(tr("VAT paid to the tax office and refunds are not entered yet: both change the sums."))
    notes.append(tr("Business meals and gifts are only partly deductible: they stand under other expenses, please move them by hand."))
    notes.append(tr("Travel costs of employees belong to the line for personnel costs: Kalmido does not separate them."))
    if d["currency"] != "EUR":
        notes.append(tr("The amounts are in {0}; the form asks for euros.", d["currency"]))
    notes += d["notes"][2:]
    return dict(head, known=True, rows=rows, profit=dstr(money(profit)), profit_books=dstr(money(books)), vat_balance=dstr(money(profit - books)),
                vat_paid=dstr(paid), vat_refund=dstr(refund), missing_vat=d["missing_vat"], notes=notes)


def tf_periods(c, oid, year, s):
    """2.589.0 (#3458): (rhythm of the tax dates, [bk_ustva of each month / quarter]) -- the advance returns of a year as Kalmido
    computes them, shared by tf_advance and the tax check (office/taxcheck.py); "year" and "none" have none."""
    mode = txd_clean(s)["ustva"]
    if s.get("small_business"):
        return mode, []
    periods = {"month": [f"m{m:02d}" for m in range(1, 13)], "quarter": ["q1", "q2", "q3", "q4"]}.get(mode, [])
    return mode, [bk_ustva(c, oid, year, p) for p in periods]


def tf_advance(c, oid, year, s, vas=None):
    """(sum of the advance payments of a year, rhythm of the tax dates): the figures of each month / quarter as Kalmido computes
    them; the rhythm "year" has none, "none" is unknown (0, the note says so). vas: tf_periods computed before (2.589.0, #3458)."""
    mode, vas = (txd_clean(s)["ustva"], vas) if vas is not None else tf_periods(c, oid, year, s)
    return sum((dec(v["kz"]["83"]) for v in vas), Decimal(0)), mode


def tf_ust(c, oid, year, vas=None, yd=None):
    """The annual VAT return of a year: {year, known, small_business, basis, basis_code (Kz 133), rows: [{key, line, kz, label, amount,
    base (whole euros) and tax where the form has both, sum}], notes}; a small business or a year without a table: no rows, a note.
    2.589.0 (#3458): vas (tf_periods) and yd (bk_ustva of the year) when the caller computed them already (the tax check)."""
    s = office_settings(c, oid)
    d = yd if yd is not None else bk_ustva(c, oid, year, "y")
    head = {"year": year, "currency": d["currency"], "small_business": bool(d.get("small_business")), "basis": d["basis"]}
    notes = [tr(BK_NOTE), tr(TF_NOTE)]
    if year not in TF_UST:
        return dict(head, known=False, rows=[], notes=[tr(TF_NO_YEAR, year)] + notes)
    if d.get("small_business"):
        return dict(head, known=True, rows=[], notes=[tr("Small business: no annual VAT return is needed here.")] + notes)
    z, t = d["kz"], TF_UST[year]
    tax = dec(d["tax"]["19"]) + dec(d["tax"]["7"]) + dec(z["36"])
    pre = dec(z["66"])
    adv, mode = tf_advance(c, oid, year, s, vas)
    due = tax - pre
    rows = []

    def row(k, amount=None, base=None, tx=None, is_sum=False):
        rows.append({"key": k, "line": t[k][0], "kz": str(t[k][1]) if t[k][1] else "", "label": TF_UST_TEXT[k], "amount": amount, "base": base,
                     "tax": tx, "sum": is_sum})

    for k, kz, tx in (("b19", "81", d["tax"]["19"]), ("b7", "86", d["tax"]["7"]), ("bx", "35", z["36"])):
        if k != "bx" or int(z[kz]) or dec(tx):
            row(k, base=z[kz], tx=tx)
    row("sum_tax", amount=dstr(tax), is_sum=True)
    for k, kz in (("eu", "41"), ("exp", "43"), ("free", "48"), ("r13b", "60"), ("r18b", "21"), ("abroad", "45")):
        if int(z[kz]):
            row(k, base=z[kz])
    row("pre", amount=z["66"])
    row("sum_pre", amount=z["66"], is_sum=True)
    row("calc_tax", amount=dstr(tax))
    row("calc_sub", amount=dstr(tax), is_sum=True)
    row("calc_pre", amount=z["66"])
    row("due", amount=dstr(due), is_sum=True)
    row("left", amount=dstr(due), is_sum=True)
    row("adv", amount=dstr(adv))
    row("final", amount=dstr(due - adv), is_sum=True)
    if mode in ("month", "quarter"):
        notes.append(tr("Advance payments: the sum of the advance returns as Kalmido computes them, without a special advance payment. Please compare with what you filed."))
    elif mode == "none":
        notes.append(tr("Advance payments are 0 because no rhythm is set under tax dates. Please enter what you filed."))
    if int(z["46"]) or int(z["84"]):  # 2.545.0 (#4387): no lines of the annual return for them yet (the tax advisor, #1153)
        notes.append(tr(TF_13B, z["46"], z["84"], z["67"]))
    if int(z["48"]):
        notes.append(tr("Tax-free sales: please check the line and enter the section of the law on the form."))
    if d["currency"] != "EUR":
        notes.append(tr("The amounts are in {0}; the form asks for euros.", d["currency"]))
    return dict(head, known=True, basis_code="2" if d["basis"] == "ist" else "1", rows=rows, advance_mode=mode, missing_vat=d["missing_vat"], notes=notes)


def _form(kind, c, oid, year):
    return tf_euer(c, oid, year) if kind == "euer" else tf_ust(c, oid, year)


def _title(kind, year):
    return tr("Anlage EÜR {0}", year) if kind == "euer" else tr("Annual VAT return {0}", year)


def _need_rows(d):
    if not d["known"]:
        raise BadInput(d["notes"][0])
    return d


def _down(kind):
    return f'{tr("euer|file name")}-anlage' if kind == "euer" else tr("annual-vat-return|file name")


def tf_csv(d, kind):
    buf = io.StringIO()
    sep, num = csv_dialect()
    w = csv.writer(buf, delimiter=sep, lineterminator="\r\n")
    w.writerow([tr("Line"), tr("Field"), tr("Description"), tr("Base"), tr("Amount")])
    for r in d["rows"]:
        val = r["tax"] if r.get("tax") is not None else r["amount"]
        w.writerow([r["line"], r["kz"], bk_csv_cell(r["label"]), r["base"] if r.get("base") is not None else "", num(val) if val is not None else ""])
    if kind == "euer":
        w.writerow(["", "", bk_csv_cell(tr("Line sum income minus line sum expenses")), "", num(d["profit"])])
    for n in d["notes"]:
        w.writerow(["", "", bk_csv_cell(n), "", ""])
    return buf.getvalue()


def tf_pdf_bytes(c, oid, d, kind, lg_name):
    """A plain page of the form's lines: line, field, wording, amount; the notes at the end (bk_euer_pdf_bytes as the pattern)."""
    s = office_settings(c, oid)
    ppr = pdf_paper_ns(s.get("paper"))
    H, W, Page = ppr.A4_H, ppr.A4_W, ppr._Page
    company = ofx_name1(ofx_company(c, oid).get("name") or (s.get("company") or {}).get("name"))
    lg = calc_lang(lg_name)
    m = lambda v: pdf_money(v, lg, d["currency"])  # noqa: E731
    x0, x1 = 56, W - 56
    pages, pg, y = [], None, 0

    def need(h):
        nonlocal pg, y
        if pg is None or y + h > H - 56:
            pg = Page()
            pages.append(pg)
            y = 56

    need(60)
    if company:
        pg.text(x0, y, company, 10, color=C_INK2)
        y += 18
    title = _title(kind, d["year"])
    pg.text(x0, y, title, 16, bold=True)
    y += 30
    for h, xx in ((tr("Line"), x0), (tr("Field"), x0 + 34)):
        pg.text(xx, y, h, 9, color=C_INK2)
    y += 16
    pg.line(x0, y, x1, y, color=C_RULE)
    y += 5
    for r in d["rows"]:
        need(16)
        b = bool(r["sum"])
        pg.text(x0, y, str(r["line"]), 9, bold=b)
        pg.text(x0 + 34, y, r["kz"], 9, bold=b)
        pg.text(x0 + 68, y, r["label"] if len(r["label"]) <= 62 else r["label"][:61].rsplit(" ", 1)[0] + "…", 9, bold=b)  # never mid-word
        if r.get("base") is not None:
            pg.text(x1 - 170, y, r["base"], 9, align="r", width=80)
        val = r["tax"] if r.get("tax") is not None else r["amount"]
        if val is not None:
            pg.text(x1 - 80, y, m(val), 9, bold=b, align="r", width=80)
        y += 14
    y += 12
    for n in d["notes"]:
        need(30)
        y += pg.para(x0, y, n, 8, x1 - x0, color=C_INK2) + 4
    return pdf_write(pages, {}, title=title, author=company)


def _out(kind, ext):
    c, uid, oid = _ctx()
    office_need_feature(c, oid, TF_FEATURE)
    d = _need_rows(_form(kind, c, oid, _year(request.args.get("year"))))
    data = tf_pdf_bytes(c, oid, d, kind, lang()) if ext == "pdf" else "﻿" + tf_csv(d, kind)
    ofx_log(c, oid, "export", target="books", detail={"what": f"taxform-{kind}.{ext}", "year": d["year"]})
    c.commit()
    mime = "application/pdf" if ext == "pdf" else "text/csv; charset=utf-8"
    return Response(data, mimetype=mime, headers={"Content-Disposition": f'attachment; filename="{_down(kind)}-{d["year"]}.{ext}"', "Cache-Control": "no-store"})


@app.get("/api/office/books/taxform/euer")
def tf_euer_get():
    """?year=YYYY -> tf_euer."""
    c, uid, oid = _ctx()
    office_need_feature(c, oid, TF_FEATURE)
    return jsonify(tf_euer(c, oid, _year(request.args.get("year"))))


@app.get("/api/office/books/taxform/ust")
def tf_ust_get():
    """?year=YYYY -> tf_ust."""
    c, uid, oid = _ctx()
    office_need_feature(c, oid, TF_FEATURE)
    return jsonify(tf_ust(c, oid, _year(request.args.get("year"))))


@app.get("/api/office/books/taxform/euer.csv")
def tf_euer_csv():
    return _out("euer", "csv")


@app.get("/api/office/books/taxform/euer.pdf")
def tf_euer_pdf():
    return _out("euer", "pdf")


@app.get("/api/office/books/taxform/ust.csv")
def tf_ust_csv():
    return _out("ust", "csv")


@app.get("/api/office/books/taxform/ust.pdf")
def tf_ust_pdf():
    return _out("ust", "pdf")


def _amount(v, name):
    try:
        a = Decimal(str(v if v not in (None, "") else "0").strip().replace(",", "."))
    except InvalidOperation:
        raise BadInput(tr("Invalid value: {0}", name))
    if not a.is_finite() or a < 0 or a > TF_MAX:
        raise BadInput(tr("Invalid value: {0}", name))
    return dstr(money(a))


@app.put("/api/office/books/taxform/vat")
def tf_vat_put():
    """Office admin. {year, paid, refund}: the VAT paid to and refunded by the tax office in a year (lines of Kz 186 / 141) -> tf_euer."""
    c, uid, oid = _ctx()
    office_need_feature(c, oid, TF_FEATURE)
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    year = _year(b.get("year"))
    paid, refund = _amount(b.get("paid"), "paid"), _amount(b.get("refund"), "refund")
    office_settings_lock(c, oid)
    s = office_settings(c, oid)
    d = s.get("tax_form_vat") if isinstance(s.get("tax_form_vat"), dict) else {}
    s["tax_form_vat"] = dict(d, **{str(year): {"paid": paid, "refund": refund}})
    office_settings_save(c, oid, s)
    ofx_log(c, oid, "update", target="settings", detail={"tax_form_vat": year})
    bump(c)
    c.commit()
    return jsonify(tf_euer(c, oid, year))
