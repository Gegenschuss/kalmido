"""2.119.0 A (#2288): the PDFs of the entertainment receipts (office/meals.py) with the office's own PDF writer (office/pdf.py):
the receipt of one meal (Eigenbeleg: head, the details block, the amounts block, the host's confirmation, the approval log)
and the evaluation (one row per approved meal, the sums 70 / 30 and the input VAT per rate). No routes."""
from datetime import date, timezone

from ..core.config import TZ
from ..core.db import local_now, parse_iso
from ..core.i18n import lang, tr, trn
from .pdf import (C_INK, C_INK2, C_RULE, C_RULE2, MM, PDF_CW, PDF_L, PDF_LOGO_MAX_W, PDF_TOP, _Page, p3f_fit, p3f_foot_h, pdf_body_bottom,
                  pdf_date, pdf_draw_footer, pdf_footer_cols, pdf_image_object, pdf_money, pdf_wrap, pdf_write)
from .model import office_settings  # 2.357.0 A (#3156)
from .pdf import PAPER, pdf_paper, pdf_paper_bind

BW_KIND = {"food": "Food", "drinks": "Drinks"}


def bw_lg():
    return "de" if lang() == "de" else "en"


def bw_when(ts, lg):
    """A stored UTC timestamp -> the local date and time ("19.10.2026, 14:05")."""
    if not ts:
        return ""
    try:
        d = parse_iso(ts)
        d = (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(TZ)
    except (ValueError, TypeError):
        return str(ts)
    return f"{pdf_date(d.date().isoformat(), lg)}, {d.strftime('%H:%M')}"


def bw_rate_txt(r):
    return f"{str(r).replace('.', ',')} %" if bw_lg() == "de" else f"{r} %"


def bw_kind_line(ln):
    return f"{tr(BW_KIND.get(ln['kind'], 'Food'))} {bw_rate_txt(ln['rate'])}"


def bw_footer(c, oid, lg):
    """2.296.0 A (#3176): the footer of the receipts (the office PDFs' columns: company, address, contact, register, bank)
    -> (cols, fit, height, body bottom, logo). 2.357.0 D (#3183): logo = the company's logo as an image object (or None)."""
    from .doctpl import dt_company
    co = dt_company(c, oid, lg)
    cols = pdf_footer_cols(co)
    fit = p3f_fit(cols)
    h = p3f_foot_h(fit)
    logo = None
    if co.get("logo_path"):
        try:
            with open(co["logo_path"], "rb") as fh:
                logo = pdf_image_object(fh.read(16 * 1024 * 1024))
        except OSError:
            logo = None
    return cols, fit, h, pdf_body_bottom(h), logo


def bw_draw_footers(pages, foot, lg):
    """2.296.0 A (#3176): the footer on every page; bottom right "Created with Kalmido on ..." (was a line in the body that
    the approval log could cover) and the page count from two pages on."""
    cols, fit, h, _bottom = foot[:4]
    made = tr("Created with Kalmido on {0}", pdf_date(local_now().date().isoformat(), lg))
    for n, p in enumerate(pages, 1):
        pdf_draw_footer(p, cols, " · ".join([made] + ([tr("Page {0} of {1}", n, len(pages))] if len(pages) >= 2 else [])), fit, h)


def bw_paper(c, oid):
    """2.357.0 A (#3156): the office's paper size (a4 / letter)."""
    return pdf_paper(office_settings(c, oid).get("paper"))


def bw_meal_pdf_data(c, oid, m):
    """The Eigenbeleg of meal m (the public dict of meals.bw_public)."""
    if bw_paper(c, oid) != PAPER:  # 2.357.0 A (#3156): the same code with the sizes of the paper
        return pdf_paper_bind(bw_meal_pdf_data, bw_paper(c, oid))(c, oid, m)
    from .meals import BW_BILL_HINT, bw_company
    from .calc import dec
    lg, cur = bw_lg(), m["currency"] or "EUR"
    co = bw_company(c, oid)
    money = lambda v: pdf_money(v, lg, cur)  # noqa: E731
    foot = bw_footer(c, oid, lg)
    bottom = foot[3]
    p = _Page()
    pages = [p]
    y = 56.0
    logo, images = foot[4], {}
    if logo:  # 2.357.0 D (#3183): the logo top right as on the other office PDFs, the receipt begins below it
        sc = min(PDF_LOGO_MAX_W / logo[0], 12 * MM / logo[1])
        images["Logo"] = logo
        p.image("Logo", PDF_L + PDF_CW - logo[0] * sc, PDF_TOP, logo[0] * sc, logo[1] * sc)
        y = max(y, PDF_TOP + logo[1] * sc + 16)

    def need(h):  # 2.296.0 A (#3176): a new page when h does not fit above the footer
        nonlocal p, y
        if y + h > bottom:
            p = _Page()
            pages.append(p)
            y = 60.0

    title = tr("Entertainment receipt (own receipt)")
    p.text(PDF_L, y, title, 17, True)
    p.text(PDF_L + PDF_CW, y + 4, tr("No. {0}", m["id"]), 9, False, C_INK2, align="r")
    y += 24
    p.text(PDF_L, y, tr("Details according to section 4 (5) sentence 1 no. 2 EStG"), 8.6, False, C_INK2)
    if co:
        p.text(PDF_L + PDF_CW, y, co, 8.6, False, C_INK2, align="r")
    y += 14
    if m["status"] != "approved":
        p.rect(PDF_L, y, PDF_CW, 20, C_RULE2)
        p.text(PDF_L + 8, y + 5.5, tr("Draft: not approved yet"), 9, True, C_INK2)
        y += 28
    y += 6
    lw, vx = 150.0, PDF_L + 158
    vw = PDF_CW - 158

    def row(label, lines, bold=False):
        nonlocal y
        out = []
        for ln in lines:
            out += pdf_wrap(ln, 9.6, vw) or [""]
        out = out or ["–"]
        need(min(len(out), 3) * 13 + 7)  # 2.296.0 A (#3176): the label with up to three lines together, longer rows break
        p.text(PDF_L, y, label, 8.6, True, C_INK2, width=lw)
        for i, ln in enumerate(out):
            if i:
                need(13 + 7)
            p.text(vx, y, ln, 9.6, bold)
            y += 13
        y += 7
        p.line(PDF_L, y - 3, PDF_L + PDF_CW, y - 3, 0.4, C_RULE2)

    host = m["host"] or {}
    pname = lambda x: x["name"] + (f" – {x.get('extra') or (co if x.get('id') else '')}" if (x.get("extra") or (co if x.get("id") else "")) else "")  # noqa: E731
    p.line(PDF_L, y - 3, PDF_L + PDF_CW, y - 3, 0.6, C_RULE)
    y += 4
    row(tr("Date of the meal"), [pdf_date(m["date"], lg)])
    row(tr("Place of the meal"), [m["place_name"] or "–"] + [x for x in (m["place_address"] or "").splitlines() if x.strip()])
    row(tr("Occasion of the meal"), [m["occasion"] or "–"])
    row(tr("Host"), [pname(host)] if host.get("name") else ["–"])
    row(tr("Guests"), [pname(g) for g in m["guests"]] or ["–"])
    if m.get("note"):
        row(tr("Note"), m["note"].splitlines())
    y += 14
    # the amounts block
    k = m["calc"]
    need(18 + 19 + (len(k["lines"]) + (1 if dec(k["tip"]) else 0)) * 15 + 26 + 3 * 13)  # 2.296.0 A (#3176): the block stays together
    cols = [(tr("Amount"), 0.43, "l"), (tr("Gross"), 0.19, "r"), (tr("of which VAT"), 0.19, "r"), (tr("Net"), 0.19, "r")]
    xs, x = [], PDF_L
    for _h, f, _a in cols:
        xs.append((x, PDF_CW * f))
        x += PDF_CW * f
    p.text(PDF_L, y, tr("Amounts"), 11, True)
    y += 18
    for (h, _f, a), (cx, cw) in zip(cols, xs):
        p.text(cx + (0 if a == "l" else -4), y, h, 8.2, True, C_INK2, align=a, width=cw)
    p.line(PDF_L, y + 13, PDF_L + PDF_CW, y + 13, 0.6, C_RULE)
    y += 19

    def arow(vals, bold=False):
        nonlocal y
        for (_h, _f, a), (cx, cw), v in zip(cols, xs, vals):
            p.text(cx + (0 if a == "l" else -4), y, v, 9.4, bold, align=a, width=cw)
        y += 15

    for ln in k["lines"]:
        arow([bw_kind_line(ln), money(ln["gross"]), money(ln["vat"]), money(ln["net"])])
    if dec(k["tip"]):
        arow([tr("Tip (no VAT)"), money(k["tip"]), money(0), money(k["tip"])])
    p.line(PDF_L, y, PDF_L + PDF_CW, y, 0.6, C_RULE)
    y += 5
    arow([tr("Total"), money(k["gross"]), money(k["vat"]), money(k["net"])], True)
    y += 6
    for lab, v in ((tr("Deductible as business expense (70 % of net)"), k["deductible"]), (tr("Not deductible (30 % of net)"), k["not_deductible"]),
                   (tr("Input VAT (100 %)"), k["vat"])):
        p.text(PDF_L, y, lab, 8.8, False, C_INK2)
        p.text(xs[3][0] - 4, y, money(v), 8.8, False, C_INK2, align="r", width=xs[3][1])
        y += 13
    y += 8
    files = m.get("files") or []
    bill = tr("Restaurant bill: attached ({0})", files[0]["name"]) if files else tr("Restaurant bill: not attached in Kalmido")
    need(len(pdf_wrap(bill, 8.6, PDF_CW)) * 8.6 * 1.42)
    y += p.para(PDF_L, y, bill, 8.6, PDF_CW, color=C_INK2)
    if dec(k["bill"]) > BW_BILL_HINT:  # 2.296.0 A (#3176): above 250 EUR (a bill of exactly 250 EUR is a small-amount invoice)
        hint = tr("Above 250 € gross the restaurant bill must be made out to the company.")
        need(len(pdf_wrap(hint, 8.6, PDF_CW)) * 8.6 * 1.42)
        y += p.para(PDF_L, y, hint, 8.6, PDF_CW, color=C_INK2)
    y += 22
    # the host's confirmation (with the signature line for the print-out, 2.296.0 A (#3176)) stays together
    conf = tr("I confirm that the details are complete and correct and that the meal was held for business reasons.")
    need(18 + len(pdf_wrap(conf, 9.2, PDF_CW)) * 9.2 * 1.42 + 10 + 54 + 44)
    p.text(PDF_L, y, tr("Confirmation of the host"), 11, True)
    y += 18
    y += p.para(PDF_L, y, conf, 9.2, PDF_CW)
    y += 10
    p.rect(PDF_L, y, PDF_CW, 40, C_RULE, stroke=True, lw=0.6)
    if m["status"] == "approved":
        p.text(PDF_L + 10, y + 8, tr("Confirmed digitally by {0}", m["approved_name"] or "–"), 9.6, True)
        p.text(PDF_L + 10, y + 23, bw_when(m["approved_at"], lg), 8.8, False, C_INK2)
        p.text(PDF_L + PDF_CW - 10, y + 23, tr("Approved and locked in Kalmido"), 8.4, False, C_INK2, align="r")
    else:
        p.text(PDF_L + 10, y + 14, tr("Not confirmed yet (draft)"), 9.6, False, C_INK2)
    y += 54
    # 2.296.0 A (#3176): a line to sign the print-out (the paper receipt is signed by the host)
    sw = (PDF_CW - 28) / 2
    p.line(PDF_L, y + 22, PDF_L + sw, y + 22, 0.6, C_INK)
    p.text(PDF_L, y + 25, tr("Place, date, signature"), 7.6, False, C_INK2)
    y += 44
    log = m.get("log") or []
    if log:
        need(13 + 8.2 * 1.42)
        p.text(PDF_L, y, tr("Approval log"), 8.6, True, C_INK2)
        y += 13
        for e in log:
            t = tr("Approved on {0} by {1}", bw_when(e["at"], lg), e["user"] or "–") if e["action"] == "approve" else \
                tr("Approval undone on {0} by {1}", bw_when(e["at"], lg), e["user"] or "–") + (f" – {e['reason']}" if e["reason"] else "")
            need(len(pdf_wrap(t, 8.2, PDF_CW)) * 8.2 * 1.42)
            y += p.para(PDF_L, y, t, 8.2, PDF_CW, color=C_INK2)
    bw_draw_footers(pages, foot, lg)
    # 2.357.0 D (#3183): the date in the title as printed (was ISO)
    return pdf_write(pages, images, title=f"{title} {pdf_date(m['date'], lg)}", author=co)


def bw_report_pdf(c, oid, rep, df, dt, person, occ, cur):
    """The evaluation: head (company, period, filter), one row per approved meal, the totals, input VAT per rate."""
    if bw_paper(c, oid) != PAPER:  # 2.357.0 A (#3156)
        return pdf_paper_bind(bw_report_pdf, bw_paper(c, oid))(c, oid, rep, df, dt, person, occ, cur)
    from .meals import bw_company, bw_pname
    lg = bw_lg()
    co = bw_company(c, oid)
    money = lambda v: pdf_money(v, lg, cur)  # noqa: E731
    foot = bw_footer(c, oid, lg)  # 2.296.0 A (#3176): the shared footer, the body ends above it
    bottom = foot[3]
    cols = [(tr("Date"), 0.11, "l"), (tr("Place / occasion"), 0.33, "l"), (tr("Gross"), 0.14, "r"), (tr("Input VAT"), 0.13, "r"),
            (tr("Deductible 70 %"), 0.15, "r"), (tr("Not deductible 30 %"), 0.14, "r")]
    xs, x = [], PDF_L
    for _h, f, _a in cols:
        xs.append((x, PDF_CW * f))
        x += PDF_CW * f
    pages = []
    title = tr("Entertainment receipts")
    sz, lh = 8.4, 11.5

    def head(p, y):  # 2.296.0 A (#3176): a heading wider than its column wraps (they overlapped)
        n = 1
        for (h, _f, a), (cx, cw) in zip(cols, xs):
            hl = pdf_wrap(h, 8, cw - 6, True) or [h]
            n = max(n, len(hl))
            for i, ln in enumerate(hl):
                p.text(cx + (0 if a == "l" else -4), y + i * 10, ln, 8, True, C_INK2, align=a, width=cw)
        y += (n - 1) * 10
        p.line(PDF_L, y + 13, PDF_L + PDF_CW, y + 13, 0.6, C_RULE)
        return y + 18

    def new_page():
        p = _Page()
        pages.append(p)
        return p

    page, y = new_page(), 56.0
    page.text(PDF_L, y, title, 16, True)
    y += 24
    period = f"{pdf_date(df, lg)} – {pdf_date(dt, lg)}" if df or dt else tr("All years")
    page.text(PDF_L, y, " · ".join(v for v in (co, period) if v), 9, False, C_INK2)
    y += 14
    flt = []
    if person:
        from .travel import rka_pkey
        names = {}
        for m in rep["meals"]:
            for pp in [m["host"] or {}] + m["guests"]:
                if pp.get("name"):
                    names[rka_pkey(pp)] = pp["name"]
        flt.append(tr("Person: {0}", names.get(person) or person.split(":", 1)[-1].lstrip("u")))
    if occ:
        flt.append(tr("Occasion: {0}", occ))
    if flt:
        page.text(PDF_L, y, " · ".join(flt), 8.6, False, C_INK2)
        y += 13
    y += 10
    y = head(page, y)
    if not rep["meals"]:
        page.text(PDF_L, y, tr("No approved entertainment receipts in this period."), 9, False, C_INK2)
        y += 16
    for m in rep["meals"]:
        k = m["calc"]
        txt = []
        for ln in (m["place_name"], m["occasion"], ", ".join([bw_pname(m["host"] or {"name": ""}, co)] + [bw_pname(g, co) for g in m["guests"]]).strip(", ")):
            txt += pdf_wrap(ln, sz, xs[1][1] - 6) if ln else []
        h = max(1, len(txt)) * lh
        if y + h > bottom:
            page = new_page()
            y = head(page, 60.0)
        vals = [pdf_date(m["date"], lg), "", money(k["gross"]), money(k["vat"]), money(k["deductible"]), money(k["not_deductible"])]
        for (_h, _f, a), (cx, cw), v in zip(cols, xs, vals):
            page.text(cx + (0 if a == "l" else -4), y, v, sz, False, align=a, width=cw)
        for i, ln in enumerate(txt):
            page.text(xs[1][0], y + i * lh, ln, sz, i == 0, C_INK2 if i > 1 else C_INK)
        y += h + 5
    if y + 160 + 12 * len(rep["rates"]) > bottom:  # 2.296.0 A (#3176): the totals block above the footer (was a fixed 170 pt)
        page, y = new_page(), 60.0
    t = rep["total"]
    page.line(PDF_L, y, PDF_L + PDF_CW, y, 0.9, C_RULE)
    y += 6
    page.text(PDF_L, y, tr("Total") + " · " + trn("{0} meal", "{0} meals", rep["count"], rep["count"]), 9.2, True)
    for i, v in ((2, t["gross"]), (3, t["vat"]), (4, t["deductible"]), (5, t["not_deductible"])):
        page.text(xs[i][0] - 4, y, money(v), 9.2, True, align="r", width=xs[i][1])
    y += 22
    for lab, v in ((tr("Food"), t["food"]), (tr("Drinks"), t["drinks"]), (tr("Tip (no VAT)"), t["tip"]), (tr("Net incl. tip"), t["net"])):
        page.text(PDF_L, y, lab, 8.6, False, C_INK2)
        page.text(xs[2][0] - 4, y, money(v), 8.6, False, C_INK2, align="r", width=xs[2][1])
        y += 12
    if rep["rates"]:
        y += 8
        page.text(PDF_L, y, tr("Input VAT by rate"), 8.6, True, C_INK2)
        y += 13
        for g in rep["rates"]:
            page.text(PDF_L, y, bw_kind_line(g), 8.6, False, C_INK2)
            page.text(xs[2][0] - 4, y, money(g["gross"]), 8.6, False, C_INK2, align="r", width=xs[2][1])
            page.text(xs[3][0] - 4, y, money(g["vat"]), 8.6, False, C_INK2, align="r", width=xs[3][1])
            y += 12
    y += 14
    if rep["drafts"]:
        y += page.para(PDF_L, y, trn("{0} draft is not in the sums.", "{0} drafts are not in the sums.", rep["drafts"], rep["drafts"]), 8, PDF_CW, color=C_INK2)
    page.para(PDF_L, y, tr("Only approved entertainment receipts. 70 % of the net amount (incl. tip) is deductible, the input VAT in full. Kalmido does not replace tax advice."),
              8, PDF_CW, color=C_INK2)
    bw_draw_footers(pages, foot, lg)
    return pdf_write(pages, {}, title=title, author=co)
