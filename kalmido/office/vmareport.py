"""2.95.0 A (#1932): the per diem (Verpflegungsmehraufwand) report per person and year -- JSON, PDF, Excel, CSV -- and the
rates of a year for the trip dialog. The amounts come from office/vma.vma_trip (the same function as the trip list).
Every route: office_gate + office_org with the admin of the office area (travel._ctx); a person without an organisation is
the admin of the personal office. (Filled by part A.)"""
import csv
import io
import re
import zipfile
from datetime import date
from decimal import Decimal
from xml.sax.saxutils import escape

from flask import Response, jsonify, request

from ..core.config import app
from ..core.i18n import lang, tr, trn
from ..personal.timetrack import BadInput
from .calc import dstr, money
from .ledger import ofx_log
from .model import office_settings
from .travel import _csv_safe, _ctx, rk_trips
from .vma import VMA_HOME, VMA_YEARS, vma_breakdown, vma_country_name, vma_places, vma_rate

VMR_CUR = "EUR"  # the BMF rates are in euros, whatever the office currency


def vmr_year():
    y = request.args.get("year") or str(date.today().year)
    if not re.fullmatch(r"\d{4}", y):
        raise BadInput(tr("Invalid value: {0}", "year"))
    return int(y)


def vmr_hint_text(h, lg="de"):
    """One hint of vma_trip as a sentence (PDF / Excel / CSV; the client has its own texts)."""
    k = h.get("key")
    if k == "off":
        return tr("No per diem for this trip")
    if k == "dates":
        return tr("The dates of the trip are not valid")
    if k == "times":
        return tr("Start and end time missing")
    if k == "short":
        return tr("8 hours or less: no per diem")
    if k == "year":
        return tr("No per diem rates for {0}", h.get("year"))
    if k in ("alias", "lu"):
        return tr("Rate of {0} used for {1}", vma_country_name(h.get("used"), lg), vma_country_name(h.get("country"), lg))
    return k or ""


def vmr_in_year(v, year):
    """The part of vma_trip result v that falls into year: (amount, cut, lines) -- a trip over the turn of the year counts
    its days per year. None when the trip has no amount."""
    if v.get("amount") is None:
        return None
    days = [d for d in v.get("days") or [] if d["date"][:4] == str(year)]
    if len(days) == len(v.get("days") or []):
        return Decimal(v["amount"]), Decimal(v["cut"]), v.get("lines") or []
    lines, amt, cut = {}, Decimal(0), Decimal(0)
    for d in days:
        amt += Decimal(d["amount"])
        cut += Decimal(d["cut"])
        if d["kind"] == "none":
            continue
        ln = lines.setdefault((d["rate_country"], d["place"], d["kind"], d["rate"]),
                              {"country": d["rate_country"], "place": d["place"], "kind": d["kind"], "n": 0, "rate": d["rate"], "sum": Decimal(0)})
        ln["n"] += 1
        ln["sum"] += Decimal(d["rate"])
    out = list(lines.values())
    for ln in out:
        ln["sum"] = dstr(ln["sum"])
    return amt, cut, out


def vmr_purpose(t, clients):
    """The trip's occasion like the spreadsheet: acquisition / research, else the project (else the client)."""
    if t["purpose"] == "acquisition":
        return tr("Acquisition / research")
    if t["purpose"] and t["purpose"] != "job":  # 2.117.0 A (#2292): an own purpose (+ the project)
        return " · ".join(x for x in (t["purpose"], t["project"]) if x)
    return t["project"] or clients.get(t["client_id"]) or ""


def vmr_report(c, oid, year, person=None, lg="de"):
    """{year, currency, people: [{key, label, trips: [...], total, open}], total, open, source} -- the per diem of every trip
    with a day in year, per participant (a trip without participants under "No person"). Trips with "no per diem" are left
    out; trips without an amount (times missing, a year without rates) are listed with their hints but not summed."""
    from .travel import rk_cl_where
    w, wa = rk_cl_where(c, oid)
    clients = {r["id"]: r["name"] for r in c.execute(f"SELECT id, name FROM clients WHERE {w}", wa)}
    y0, y1 = f"{year}-01-01", f"{year}-12-31"
    groups, sources = {}, set()
    trips = [t for t in rk_trips(c, oid) if t["date_from"] <= y1 and (t["date_to"] or t["date_from"]) >= y0]
    trips.sort(key=lambda t: (t["date_from"], t["id"]))
    for t in trips:
        v = t["vma"]
        if t["vma_off"]:
            continue
        part = vmr_in_year(v, year)
        row = {"id": t["id"], "date_from": t["date_from"], "date_to": t["date_to"] or t["date_from"], "t_start": t["t_start"], "t_end": t["t_end"],
               "dest": t["dest"], "purpose": vmr_purpose(t, clients), "amount": None, "cut": "0.00", "breakdown": [], "hints": v["hints"],
               "hint_texts": [vmr_hint_text(h, lg) for h in v["hints"]]}
        if part is not None:
            amt, cut, lines = part
            row["amount"], row["cut"] = dstr(money(amt)), dstr(money(cut))
            row["breakdown"] = vma_breakdown({"lines": lines}, lg, VMR_CUR)
            if cut:
                row["breakdown"].append(tr("Meals provided: -{0}", vmr_num(cut, lg) + " €"))
            sources.add(VMA_YEARS[year])
        ppl = t["people"] or [{"name": ""}]
        for p in ppl:
            k = ("u%s" % p["id"]) if p.get("id") else ("n:" + (p.get("name") or "").lower() if p.get("name") else "")
            if person is not None and k != person:
                continue
            g = groups.setdefault(k, {"key": k, "label": p.get("name") or tr("No person"), "trips": [], "total": Decimal(0), "open": 0})
            g["trips"].append(row)
            if row["amount"] is None:
                g["open"] += 1
            else:
                g["total"] += Decimal(row["amount"])
    people = sorted(groups.values(), key=lambda g: (g["key"] == "", g["label"].casefold()))
    total = sum((g["total"] for g in people), Decimal(0))
    for g in people:
        g["total"] = dstr(money(g["total"]))
    return {"year": year, "currency": VMR_CUR, "people": people, "total": dstr(money(total)), "open": sum(g["open"] for g in people),
            "source": sorted(sources) or ([VMA_YEARS[year]] if year in VMA_YEARS else []), "rates": year in VMA_YEARS}


def vmr_num(v, lg):
    d = Decimal(v)
    t = format(d.quantize(Decimal(1)) if d == d.to_integral() else d.quantize(Decimal("0.01")), "f")
    return t.replace(".", ",") if lg == "de" else t


def vmr_args():
    c, uid, oid = _ctx()
    year = vmr_year()
    person = request.args.get("person")
    if person is not None and len(person) > 200:
        raise BadInput(tr("Invalid value: {0}", "person"))
    lg = "de" if lang(c, uid) == "de" else "en"
    return c, uid, oid, year, person, lg


def vmr_fname(year, person, ext):
    return f"per-diem-{year}{'-' + re.sub(r'[^a-z0-9]+', '-', person.lower()).strip('-') if person else ''}.{ext}"


def vmr_send(raw, mime, name):
    return Response(raw, mimetype=mime, headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


# ---------------------------------------------------------------- routes
@app.get("/api/office/trips/vma-rates")
def vmr_rates_get():
    """?year=YYYY -> {years, year, source, home: {full, partial}, countries: [{code, places: ['', 'Athen', ...], full, partial}]}
    (full / partial of the whole country); a year without a table: countries [] and hint "year"."""
    _ctx()
    year = vmr_year()
    places = vma_places(year)
    out = {"years": sorted(VMA_YEARS), "year": year, "source": VMA_YEARS.get(year, ""), "home": None, "countries": [], "hint": None}
    if places is None:
        out["hint"] = {"key": "year", "year": year}
        return jsonify(out)
    f, p = VMA_HOME[year]
    out["home"] = {"full": f, "partial": p}
    for code, pl in places.items():
        r = vma_rate(year, code, "")
        out["countries"].append({"code": code, "places": pl, "full": r[0], "partial": r[1]})
    return jsonify(out)


@app.get("/api/office/trips/vma")
def vmr_get():
    """?year=YYYY[&person=KEY] -> the per diem report (vmr_report)."""
    c, uid, oid, year, person, lg = vmr_args()
    return jsonify(vmr_report(c, oid, year, person, lg))


def vmr_head():
    return [tr("From"), tr("to"), tr("Start"), tr("End"), tr("Destination / route"), tr("Occasion"), tr("Per diem"), tr("Breakdown")]


def vmr_row_note(r):
    return "\n".join(r["breakdown"] if r["amount"] is not None else r["hint_texts"])


@app.get("/api/office/trips/vma.csv")
def vmr_csv():
    """The report as CSV (semicolon, decimal comma, one row per person and trip, a total per person and overall)."""
    c, uid, oid, year, person, lg = vmr_args()
    rep = vmr_report(c, oid, year, person, lg)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([tr("Person")] + vmr_head()[:6] + [tr("Per diem") + f" ({VMR_CUR})", tr("Breakdown")])
    for g in rep["people"]:
        for r in g["trips"]:
            w.writerow([_csv_safe(g["label"]), r["date_from"], r["date_to"], r["t_start"], r["t_end"], _csv_safe(r["dest"]), _csv_safe(r["purpose"]),
                        r["amount"].replace(".", ",") if r["amount"] is not None else "", _csv_safe(" | ".join(vmr_row_note(r).split("\n")))])
        w.writerow([_csv_safe(g["label"]), "", "", "", "", "", tr("Total"), g["total"].replace(".", ","), ""])
    w.writerow([tr("Total"), "", "", "", "", "", "", rep["total"].replace(".", ","), "; ".join(rep["source"])])
    ofx_log(c, oid, "export", target="travel", detail={"what": "vma.csv", "year": year})
    c.commit()
    return vmr_send("﻿" + buf.getvalue(), "text/csv; charset=utf-8", vmr_fname(year, person, "csv"))


def vmr_cell(ref, v):
    if isinstance(v, (int, float)):
        return f'<c r="{ref}"><v>{v}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(str(v))}</t></is></c>'


def vmr_xlsx(sheets):
    """A minimal .xlsx with one sheet per entry of sheets [(name, rows)] (inline strings, no styles; like fixedimport.fci_xlsx)."""
    ns = "http://schemas.openxmlformats.org"
    names, seen = [], set()
    for name, _rows in sheets:
        n = re.sub(r"[\[\]:*?/\\]", " ", str(name or "")).strip()[:28] or "-"
        base, i = n, 2
        while n.casefold() in seen:
            n = f"{base[:25]} {i}"
            i += 1
        seen.add(n.casefold())
        names.append(n)
    parts = {
        "[Content_Types].xml": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="{ns}/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        + "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                  for i in range(len(sheets))) + "</Types>",
        "_rels/.rels": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{ns}/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{ns}/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="{ns}/spreadsheetml/2006/main" '
        f'xmlns:r="{ns}/officeDocument/2006/relationships"><sheets>'
        + "".join(f'<sheet name="{escape(n, {chr(34): "&quot;"})}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, n in enumerate(names)) + "</sheets></workbook>",
        "xl/_rels/workbook.xml.rels": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{ns}/package/2006/relationships">'
        + "".join(f'<Relationship Id="rId{i + 1}" Type="{ns}/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i + 1}.xml"/>'
                  for i in range(len(sheets))) + "</Relationships>",
    }
    for i, (_n, rows) in enumerate(sheets):
        data = "".join(f'<row r="{r + 1}">' + "".join(vmr_cell(f"{chr(65 + j)}{r + 1}", v) for j, v in enumerate(row) if v not in ("", None)) + "</row>"
                       for r, row in enumerate(rows))
        parts[f"xl/worksheets/sheet{i + 1}.xml"] = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="{ns}/spreadsheetml/2006/main">'
                                                    f'<sheetData>{data}</sheetData></worksheet>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in parts.items():
            z.writestr(k, v)
    return buf.getvalue()


def vmr_dd(s):
    return f"{s[8:10]}.{s[5:7]}.{s[:4]}" if s and len(s) == 10 else s or ""


@app.get("/api/office/trips/vma.xlsx")
def vmr_xlsx_get():
    """The report as Excel: one sheet per person (columns like the spreadsheet template: From, to, Start, End, Destination,
    Occasion, Per diem, Breakdown; amounts as numbers, dates as text DD.MM.YYYY) with a total row."""
    c, uid, oid, year, person, lg = vmr_args()
    rep = vmr_report(c, oid, year, person, lg)
    sheets = []
    for g in rep["people"]:
        rows = [vmr_head()]
        for r in g["trips"]:
            rows.append([vmr_dd(r["date_from"]), vmr_dd(r["date_to"]), r["t_start"], r["t_end"], r["dest"], r["purpose"],
                         float(r["amount"]) if r["amount"] is not None else "", vmr_row_note(r)])
        rows.append(["", "", "", "", "", tr("Total"), float(g["total"]), ""])
        sheets.append((g["label"], rows))
    if not sheets:
        sheets.append((str(year), [vmr_head(), ["", "", "", "", "", tr("Total"), 0.0, ""]]))
    ofx_log(c, oid, "export", target="travel", detail={"what": "vma.xlsx", "year": year})
    c.commit()
    return vmr_send(vmr_xlsx(sheets), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", vmr_fname(year, person, "xlsx"))


@app.get("/api/office/trips/vma.pdf")
def vmr_pdf():
    """The report as PDF: a section per person (head: company, person, year, source of the rates), a table From / To /
    Destination / Occasion / Breakdown / Amount, the total per person and overall (the office's own PDF writer)."""
    from .pdf import A4_H, C_INK, C_INK2, C_RULE, PDF_CW, PDF_L, _Page, pdf_date, pdf_money, pdf_text_width, pdf_wrap, pdf_write
    c, uid, oid, year, person, lg = vmr_args()
    rep = vmr_report(c, oid, year, person, lg)
    from .model import ofx_name1
    co = ofx_name1((office_settings(c, oid).get("company") or {}).get("name") or "")  # 2.99.0 (#2188): up to three lines -> one
    cols = [(tr("From"), 0.11, "l"), (tr("to"), 0.11, "l"), (tr("Destination / route"), 0.18, "l"), (tr("Occasion"), 0.17, "l"),
            (tr("Breakdown"), 0.31, "l"), (tr("Per diem"), 0.12, "r")]
    xs, x = [], PDF_L
    for _h, f, _a in cols:
        xs.append((x, PDF_CW * f))
        x += PDF_CW * f
    pages = []
    title = tr("Per diem allowances {0}", year)
    sz, lh = 8.4, 11.5

    def cut(v, cw):
        v = str(v or "")
        while v and pdf_text_width(v, sz) > cw - 6:
            v = v[:-2] + "…" if len(v) > 2 else ""
        return v

    def head(p, y):
        for (h, _f, a), (cx, cw) in zip(cols, xs):
            p.text(cx + (0 if a == "l" else -4), y, h, 8.2, True, C_INK2, align=a, width=cw)
        p.line(PDF_L, y + 13, PDF_L + PDF_CW, y + 13, 0.6, C_RULE)
        return y + 18

    def new_page():
        p = _Page()
        pages.append(p)
        return p

    page, y = new_page(), 60.0
    page.text(PDF_L, y, title, 16, True)
    y += 24
    page.text(PDF_L, y, " · ".join(v for v in (co, pdf_date(date.today().isoformat(), lg)) if v), 9, False, C_INK2)
    y += 14
    if rep["source"]:
        y += page.para(PDF_L, y, tr("Rates: {0}", "; ".join(rep["source"])), 8, PDF_CW, color=C_INK2)
    elif not rep["rates"]:
        y += page.para(PDF_L, y, tr("No per diem rates for {0}", year), 8, PDF_CW, color=C_INK2)
    y += 10
    if not rep["people"]:
        page.text(PDF_L, y, tr("No trips with a per diem in {0}.", year), 9, False, C_INK2)
    for g in rep["people"]:
        if y > A4_H - 160:
            page, y = new_page(), 60.0
        page.text(PDF_L, y, g["label"], 12, True)
        page.text(PDF_L + PDF_CW, y + 2, f"{title}", 8, False, C_INK2, align="r")
        y = head(page, y + 22)
        for r in g["trips"]:
            note = []
            for ln in vmr_row_note(r).split("\n"):
                note += pdf_wrap(ln, sz, xs[4][1] - 6)
            h = max(1, len(note)) * lh
            if y + h > A4_H - 70:
                page = new_page()
                y = head(page, 60.0)
            vals = [pdf_date(r["date_from"], lg), pdf_date(r["date_to"], lg), cut(r["dest"], xs[2][1]), cut(r["purpose"], xs[3][1]), "",
                    pdf_money(r["amount"], lg, VMR_CUR) if r["amount"] is not None else "–"]
            for (_h, _f, a), (cx, cw), v in zip(cols, xs, vals):
                page.text(cx + (0 if a == "l" else -4), y, v, sz, False, align=a, width=cw)
            for i, ln in enumerate(note):
                page.text(xs[4][0], y + i * lh, ln, sz, False, C_INK2 if r["amount"] is None else C_INK)
            y += h + 4
        page.line(PDF_L, y, PDF_L + PDF_CW, y, 0.6, C_RULE)
        y += 6
        page.text(PDF_L, y, tr("Total") + " " + g["label"], sz, True)
        page.text(xs[5][0] - 4, y, pdf_money(g["total"], lg, VMR_CUR), sz, True, align="r", width=xs[5][1])
        y += 16
        if g["open"]:
            y += page.para(PDF_L, y, trn("{0} trip without an amount is not in the total.", "{0} trips without an amount are not in the total.", g["open"], g["open"]), 8, PDF_CW, color=C_INK2)
        y += 18
    if len(rep["people"]) > 1:
        if y > A4_H - 90:
            page, y = new_page(), 60.0
        page.line(PDF_L, y, PDF_L + PDF_CW, y, 0.9, C_RULE)
        y += 6
        page.text(PDF_L, y, tr("Total"), 9.4, True)
        page.text(xs[5][0] - 4, y, pdf_money(rep["total"], lg, VMR_CUR), 9.4, True, align="r", width=xs[5][1])
        y += 22
    if y > A4_H - 70:
        page, y = new_page(), 60.0
    page.para(PDF_L, y, tr("Flat rates for additional meal expenses per participant. Kalmido does not replace tax advice."), 8, PDF_CW, color=C_INK2)
    data = pdf_write(pages, {}, title=title, author=co)
    ofx_log(c, oid, "export", target="travel", detail={"what": "vma.pdf", "year": year})
    c.commit()
    return vmr_send(data, "application/pdf", vmr_fname(year, person, "pdf"))
