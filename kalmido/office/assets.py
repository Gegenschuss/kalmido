"""2.92.0 B (#1931): the value of equipment -- purchase, depreciation, current value, insurance list.

A device of the office master data (office_equipment, model.py MD "equipment") carries its purchase day and net price,
serial number, vendor, the receipt (a document of the office's document space), a useful life in months (NULL = the
suggestion of AST_LIFE by category / name), a new value and a current value for the insurance ('' = computed) and the
policy that covers it (office_agreements, #1925). Prices and values are encrypted at rest (orgcrypt FIELDS) and only the
office's admins ever get them (model.py admin_cols; members see the device without any of it).

Depreciation (no tax advice, figures without guarantee): net <= AST_GWG -> written off in full in the purchase year
(geringwertiges Wirtschaftsgut), else linear by the month from the purchase month on. The book value is what is left;
the current value for the insurance is the book value unless the admin enters an own one. ast_afa_year hands the
depreciation of a year to the profit statement (EUeR, #1921); ast_covered tells a policy (#1925) what it covers."""
import csv
import io
import re
from datetime import date
from decimal import Decimal

from flask import Response, jsonify, request

from ..core.config import app
from ..core.db import db, local_now
from ..core.i18n import N_, lang, tr
from ..core.access import Denied
from ..personal.timetrack import BadInput
from .calc import dec, dstr, money
from .model import ofx_name1, office_gate, office_org, office_rows, office_settings, pb_owner

AST_GWG = Decimal("800")  # low-value assets: written off at once up to this net price (DE, 2026; without guarantee)
# useful life in months by keyword of category / name (German AfA table, without guarantee; the admin may change it per
# device). First match wins; short words only as whole words.
AST_LIFE = (
    (84, ("drohne", "drone", "copter")),
    (72, ("fahrzeug", "vehicle", "transporter", "\\bauto\\b", "\\bcar\\b", "\\bpkw\\b", "\\bvan\\b")),
    (156, ("möbel", "moebel", "furniture", "schreibtisch", "\\bdesk\\b", "stuhl", "chair", "regal", "shelf", "schrank")),
    (60, ("smartphone", "handy", "telefon", "phone")),
    # digital assets (BMF 2021/2022): computer hardware, peripherals and software, one year
    (12, ("computer", "laptop", "notebook", "\\bpc\\b", "tablet", "ipad", "macbook", "imac", "rechner", "server", "\\bnas\\b",
          "drucker", "printer", "scanner", "software", "festplatte", "\\bssd\\b", "tastatur", "keyboard", "\\bmaus\\b", "mouse")),
    (84, ("kamera", "camera", "objektiv", "\\blens", "licht", "light", "leuchte", "lamp", "\\bton", "audio", "mikro", "micro",
          "\\bmic\\b", "recorder", "stativ", "tripod", "gimbal", "video", "speedlite", "blitz")),
)
AST_LIFE_DEFAULT = 60
AST_LIFE_MAX = 600
AST_DISCLAIMER = N_("No tax advice; figures without guarantee.")
_VAT_RE = re.compile(r"(?:mwst|ust|umsatzsteuer|mehrwertsteuer|vat|tva|iva|btw)\D{0,30}?(\d{1,2})(?:[.,]0{1,2})?\s*%"
                     r"|(\d{1,2})(?:[.,]0{1,2})?\s*%\s*(?:mwst|ust|umsatzsteuer|mehrwertsteuer|vat|tva|iva|btw)", re.I)


def _ctx():
    """-> (c, uid, oid): the value side of the equipment is the office admins' (members 403, agents / kids 403)."""
    c = db()
    uid = office_gate(c)
    return c, uid, office_org(c, uid, admin=True)


def _today():
    return local_now().date()


def _d(s):
    try:
        return date.fromisoformat(str(s or "")[:10])
    except ValueError:
        return None


def _money_or_none(v):
    return None if v in (None, "") else money(dec(v))


# ---------------------------------------------------------------- depreciation
def ast_life_suggest(category, name):
    """The suggested useful life in months for a device of category / name (AST_LIFE, without guarantee)."""
    s = f"{category or ''} {name or ''}".lower()
    for months, words in AST_LIFE:
        for w in words:
            if (re.search(w, s) if "\\b" in w else w in s):
                return months
    return AST_LIFE_DEFAULT


def bnk_plan(net, pdate, life):
    """The depreciation of one device: (method, [{year, afa, book}]) with method 'gwg' | 'linear'; ('', []) without a
    purchase day or a positive net price. Linear: by the month from the purchase month on; the cumulated amount is
    rounded per year so the years add up to the net price exactly."""
    if net is None or net <= 0 or pdate is None:
        return "", []
    if net <= AST_GWG:
        return "gwg", [{"year": pdate.year, "afa": dstr(net), "book": "0.00"}]
    life = max(1, int(life or AST_LIFE_DEFAULT))
    first = 12 - pdate.month + 1  # months of the purchase year (the purchase month counts)
    out, done, y = [], Decimal(0), pdate.year
    while done < net:
        k = min(first + (y - pdate.year) * 12, life)
        cum = money(net * k / life) if k < life else net
        out.append({"year": y, "afa": dstr(cum - done), "book": dstr(net - cum)})
        done, y = cum, y + 1
    return "linear", out


def bnk_book_value(net, pdate, life, method, today):
    """The book value on day today (linear: the months up to and including the current one are written off)."""
    if not method:
        return None
    if today < pdate:
        return net
    if method == "gwg":
        return Decimal(0)
    life = max(1, int(life or AST_LIFE_DEFAULT))
    k = min((today.year - pdate.year) * 12 + today.month - pdate.month + 1, life)
    return net - (money(net * k / life) if k < life else net)


def ast_values(r, today=None):
    """The computed value fields of a decrypted equipment row (dict): life_suggest, life_eff, method, afa_plan, afa_year
    (the depreciation of the current year), book_value, new_value_eff, current_value_eff (money texts or None)."""
    today = today or _today()
    net = _money_or_none(r.get("purchase_net"))
    pdate = _d(r.get("purchase_date"))
    sug = ast_life_suggest(r.get("category"), r.get("name"))
    life = r.get("life_months") or sug
    method, plan = bnk_plan(net, pdate, life)
    book = bnk_book_value(net, pdate, life, method, today)
    afa_y = next((p["afa"] for p in plan if p["year"] == today.year), "0.00" if method else None)
    new = _money_or_none(r.get("new_value"))
    new = new if new is not None else net
    cur = _money_or_none(r.get("current_value"))
    cur = cur if cur is not None else book
    return {"life_suggest": sug, "life_eff": int(life), "method": method, "afa_plan": plan, "afa_year": afa_y, "year": today.year,
            "book_value": dstr(book) if book is not None else None, "new_value_eff": dstr(new) if new is not None else None,
            "current_value_eff": dstr(cur) if cur is not None else None}


def ast_enrich(c, oid, rows):
    """Admin rows of GET /api/office/equipment[/<id>] with the computed value fields and the policy's name (in place)."""
    today = _today()
    names = {a["id"]: a["name"] for a in bnk_policies(c, oid, archived=True)} if any(r.get("agreement_id") for r in rows) else {}
    for r in rows:
        r.update(ast_values(r, today))
        r["agreement_name"] = names.get(r.get("agreement_id")) or ""
    return rows


def ast_afa_year(c, oid, year):
    """The depreciation of office oid in year (for the profit statement, #1921): {"rows": [{equipment_id, name, amount
    (Decimal, net), method}], "receipt_ids": {node ids}}. Archived devices count as well (archived = no longer offered,
    the asset still is one). receipt_ids: the receipts of the devices listed -- the statement must not count them as an
    expense as well (the depreciation replaces it; their input tax stays)."""
    rows, rids = [], set()
    for r in office_rows(c, oid, "equipment"):
        v = ast_values(r, date(int(year), 12, 31))
        amt = next((dec(p["afa"]) for p in v["afa_plan"] if p["year"] == int(year)), None)
        if amt:
            rows.append({"equipment_id": r["id"], "name": r["name"], "amount": amt, "method": v["method"]})
        if v["method"] and r.get("receipt_node_id"):
            rids.add(int(r["receipt_node_id"]))
    return {"rows": rows, "receipt_ids": rids}


def ast_covered(c, oid, aid):
    """What policy aid of office oid covers (#1925): {"count": live devices, "new_value": their summed new value}."""
    n, total = 0, Decimal(0)
    for r in office_rows(c, oid, "equipment", archived=False):
        if r.get("agreement_id") == aid:
            n += 1
            v = ast_values(r)
            total += dec(v["new_value_eff"] or 0)
    return {"count": n, "new_value": dstr(total)}


# ---------------------------------------------------------------- policies (#1925) and receipts
def bnk_policies(c, oid, archived=False):
    """The office's contracts for the choice "insured by": agreements.agr_list when part A is there, else the table."""
    from . import agreements as A
    f = getattr(A, "agr_list", None)
    if f:
        rows = [dict(a) for a in f(c, oid, kind="insurance")]
    else:
        rows = [dict(a) for a in c.execute("SELECT id, kind, name, provider, archived FROM office_agreements WHERE org_id=? AND kind='insurance' "
                                           "ORDER BY lower(name), id", (oid,))]
    return [a for a in rows if archived or not a.get("archived")]


def ast_agreement_ok(c, oid, aid):
    """True when aid is a live contract of office oid (an archived one only stays where it is set already)."""
    from . import agreements as A
    f = getattr(A, "agr_exists", None)
    if f and not f(c, oid, aid):
        return False
    r = c.execute("SELECT archived FROM office_agreements WHERE id=? AND org_id=?", (aid, oid)).fetchone()
    return bool(r) and not r["archived"]


def bnk_ws(c, oid):
    """The document space of office oid: a personal office -> its owner's own documents, an organisation -> its own."""
    owner = pb_owner(c, oid)
    return f"u{owner}" if owner else f"o{oid}"


def ast_receipt_meta(c, oid, nid):
    """The doc_meta row of document nid when it lies in the office's document space and the signed-in person sees it;
    404 otherwise (another organisation, another person's private document, the trash, no document)."""
    from ..files.store import need_node
    from ..docs import store as S
    try:
        nid = int(nid)
    except (TypeError, ValueError):
        raise Denied(404)
    m = S.meta_row(c, nid)
    if not m or m["ws"] != bnk_ws(c, oid):
        raise Denied(404)
    n = need_node(c, nid)
    if n["kind"] != "file":
        raise Denied(404)
    return m


def ast_receipt_check(c, oid, v):
    """model.py _clean_col of receipt_node_id: None or a document of the office space (400 otherwise, no hint whose)."""
    if v in (None, "", 0, "0"):
        return None
    try:
        ast_receipt_meta(c, oid, v)
    except Denied:
        raise BadInput(tr("Invalid value: {0}", "receipt_node_id"))
    return int(v)


def bnk_vat(text):
    """The VAT rate of a receipt's text when exactly one of 19 / 7 % shows up next to a VAT word, else None."""
    rates = {int(a or b) for a, b in _VAT_RE.findall(text or "")[:50]} & {19, 7}
    return rates.pop() if len(rates) == 1 else None


def bnk_receipt_suggest(c, oid, m):
    """What a receipt proposes for a device: date, gross amount, VAT rate (when the text tells it), net, vendor."""
    from ..docs import store as S
    ws = m["ws"]
    gross = _money_or_none(S.doc_open(c, ws, "doc_meta.amount", m["amount"]) or None)
    home = office_settings(c, oid).get("currency") or "EUR"
    cur = m["currency"] or home
    vat = bnk_vat(S.meta_text(c, m)) if gross is not None else None
    net, hint = None, ""
    if gross is None:
        hint = tr("The receipt has no amount; enter the net price yourself.")
    elif cur != home:
        hint = tr("The receipt is in {0}; enter the net price in {1} yourself.", cur, home)
    elif vat is None:
        hint = tr("The VAT rate of the receipt is unknown; enter the net price yourself (gross {0}).", dstr(gross))
    else:
        net = money(gross * 100 / (100 + vat))
    vendor = S.label_name(c, ws, "sender", m["sender_id"]) if m["sender_id"] else ""
    name = c.execute("SELECT name FROM fs_nodes WHERE id=?", (m["node_id"],)).fetchone()[0]
    return {"id": m["node_id"], "name": name, "date": m["doc_date"] or "", "gross": dstr(gross) if gross is not None else None,
            "currency": cur, "vat_pct": vat, "net": dstr(net) if net is not None else None, "vendor": vendor or "", "hint": hint}


@app.get("/api/office/equipment/receipts")
def ast_receipts_get():
    """Office admin: ?q= -- documents of the office's document space to take a purchase from (newest first, 40)."""
    from ..docs.web import doc_query
    from ..docs import store as S
    c, uid, oid = _ctx()
    ws = bnk_ws(c, oid)
    rows, _total, _rev = doc_query(c, uid, {"ws": "private" if ws[0] == "u" else f"org:{oid}", "q": request.args.get("q") or "", "limit": 40})
    rc = {r[0] for r in c.execute("SELECT node_id FROM rc_receipts WHERE ws=?", (ws,))}
    out = []
    for m in rows:
        if m["ws"] != ws:
            continue
        name = c.execute("SELECT name FROM fs_nodes WHERE id=?", (m["node_id"],)).fetchone()[0]
        out.append({"id": m["node_id"], "name": name, "date": m["doc_date"] or "", "currency": m["currency"] or "",
                    "amount": S.doc_open(c, ws, "doc_meta.amount", m["amount"]) or None,
                    "sender": S.label_name(c, ws, "sender", m["sender_id"]) if m["sender_id"] else "", "receipt": m["node_id"] in rc})
    return jsonify(items=out)


@app.get("/api/office/equipment/receipts/<int:nid>")
def ast_receipt_get(nid):
    """Office admin: the proposal of one receipt (404 outside the office's document space)."""
    c, uid, oid = _ctx()
    return jsonify(bnk_receipt_suggest(c, oid, ast_receipt_meta(c, oid, nid)))


@app.get("/api/office/equipment/policies")
def ast_policies_get():
    """Office admin: the insurance contracts for the choice "insured by" (live ones; #1925)."""
    c, uid, oid = _ctx()
    return jsonify(items=[{k: a.get(k) for k in ("id", "kind", "name", "provider", "archived")} for a in bnk_policies(c, oid, archived=True)])


# ---------------------------------------------------------------- the insurance list (sums, CSV, PDF)
def ast_value(c, oid, aid=None):
    """The live devices with their values (?agreement_id filters by policy; 0 = none) + the sums."""
    today = _today()
    pol = {a["id"]: a["name"] for a in bnk_policies(c, oid, archived=True)}
    rows, s_new, s_cur, s_afa, s_net = [], Decimal(0), Decimal(0), Decimal(0), Decimal(0)
    for r in office_rows(c, oid, "equipment", archived=False):
        if aid is not None and (r.get("agreement_id") or 0) != aid:
            continue
        v = ast_values(r, today)
        rows.append({"id": r["id"], "name": r["name"], "category": r.get("category") or "", "serial_no": r.get("serial_no") or "",
                     "purchase_date": r.get("purchase_date") or "", "purchase_net": dstr(r["purchase_net"]) if r.get("purchase_net") not in (None, "") else None,
                     "new_value": v["new_value_eff"], "current_value": v["current_value_eff"], "book_value": v["book_value"],
                     "afa_year": v["afa_year"], "method": v["method"], "agreement_id": r.get("agreement_id"),
                     "agreement_name": pol.get(r.get("agreement_id")) or ""})
        s_new += dec(v["new_value_eff"] or 0)
        s_cur += dec(v["current_value_eff"] or 0)
        s_afa += dec(v["afa_year"] or 0)
        s_net += dec(r.get("purchase_net") or 0)
    cur = office_settings(c, oid).get("currency") or "EUR"
    return {"rows": rows, "year": today.year, "currency": cur, "policies": [{"id": k, "name": n} for k, n in pol.items()],
            "sums": {"count": len(rows), "purchase_net": dstr(s_net), "new_value": dstr(s_new), "current_value": dstr(s_cur), "afa_year": dstr(s_afa)},
            "disclaimer": tr(AST_DISCLAIMER)}


def _aid_arg():
    v = request.args.get("agreement_id")
    if v in (None, ""):
        return None
    try:
        return int(v)
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "agreement_id"))


@app.get("/api/office/equipment/value")
def ast_value_get():
    """Office admin: the insurance list -- rows (new value, current value, depreciation of the year) + sums."""
    c, uid, oid = _ctx()
    return jsonify(ast_value(c, oid, _aid_arg()))


def bnk_csv_cell(s):
    """No formula injection in spreadsheet programs (like travel.py _csv_safe)."""
    from ..core.serializers import csv_cell  # 2.122.4 B (#2317): one shared helper
    return csv_cell(s)


def _de(v):
    return "" if v in (None, "") else str(v).replace(".", ",")


@app.get("/api/office/equipment/value.csv")
def ast_value_csv():
    """Office admin: the insurance list as CSV (semicolon, decimal comma, like the other office CSVs)."""
    c, uid, oid = _ctx()
    d = ast_value(c, oid, _aid_arg())
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([tr("Device"), tr("Category"), tr("Serial number"), tr("Purchase date"), tr("Purchase price (net)"), tr("New value"),
                tr("Current value"), tr("Depreciation {0}", d["year"]), tr("Insured by")])
    for r in d["rows"]:
        w.writerow([bnk_csv_cell(r["name"]), bnk_csv_cell(r["category"]), bnk_csv_cell(r["serial_no"]), r["purchase_date"], _de(r["purchase_net"]),
                    _de(r["new_value"]), _de(r["current_value"]), _de(r["afa_year"]), bnk_csv_cell(r["agreement_name"])])
    s = d["sums"]
    w.writerow([tr("Total"), "", "", "", _de(s["purchase_net"]), _de(s["new_value"]), _de(s["current_value"]), _de(s["afa_year"]), ""])
    w.writerow([bnk_csv_cell(d["disclaimer"])])
    return Response("﻿" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="equipment-value.csv"'})


@app.get("/api/office/equipment/value.pdf")
def ast_value_pdf():
    """Office admin: the insurance list as PDF (the office's own PDF writer: one table, as many A4 pages as needed)."""
    from .pdf import A4_H, C_INK2, C_RULE, PDF_CW, PDF_L, _Page, pdf_date, pdf_money, pdf_write
    c, uid, oid = _ctx()
    d = ast_value(c, oid, _aid_arg())
    lg = "de" if lang(c, uid) == "de" else "en"
    cur = d["currency"]
    co = ofx_name1((office_settings(c, oid).get("company") or {}).get("name"))  # 2.99.0 D (#2188): one line
    pol = next((p["name"] for p in d["policies"] if p["id"] == _aid_arg()), "") if _aid_arg() else ""
    cols = [(tr("Device"), 0.25, "l"), (tr("Serial number"), 0.15, "l"), (tr("Purchase date"), 0.12, "l"), (tr("New value"), 0.14, "r"),
            (tr("Current value"), 0.14, "r"), (tr("Insured by"), 0.20, "l")]
    xs, x = [], PDF_L
    for _h, f, _a in cols:
        xs.append((x, PDF_CW * f))
        x += PDF_CW * f
    pages, page, y = [], None, 0.0

    def head(p, y):
        for (h, _f, a), (cx, cw) in zip(cols, xs):
            p.text(cx + (0 if a == "l" else -4), y, h, 8.4, True, C_INK2, align=a, width=cw)
        p.line(PDF_L, y + 13, PDF_L + PDF_CW, y + 13, 0.6, C_RULE)
        return y + 18

    def new_page():
        p = _Page()
        pages.append(p)
        return p

    page = new_page()
    y = 60.0
    page.text(PDF_L, y, tr("Equipment value"), 16, True)
    y += 24
    sub = " · ".join(v for v in (co, pdf_date(_today().isoformat(), lg), tr("Insured by") + ": " + pol if pol else "") if v)
    page.text(PDF_L, y, sub, 9, False, C_INK2)
    y = head(page, y + 22)
    for r in d["rows"]:
        if y > A4_H - 90:
            page = new_page()
            y = head(page, 60.0)
        vals = [r["name"], r["serial_no"], pdf_date(r["purchase_date"], lg) if r["purchase_date"] else "",
                pdf_money(r["new_value"], lg, cur) if r["new_value"] else "", pdf_money(r["current_value"], lg, cur) if r["current_value"] else "",
                r["agreement_name"]]
        for (h, _f, a), (cx, cw), v in zip(cols, xs, vals):
            v = str(v or "")
            while v and bnk_pdf_w(v) > cw - 6:
                v = v[:-2] + "…" if len(v) > 2 else ""
            page.text(cx + (0 if a == "l" else -4), y, v, 8.6, False, align=a, width=cw)
        y += 15
    page.line(PDF_L, y, PDF_L + PDF_CW, y, 0.6, C_RULE)
    y += 6
    s = d["sums"]
    page.text(PDF_L, y, bnk_devices(s["count"]), 8.6, True)
    page.text(xs[3][0] - 4, y, pdf_money(s["new_value"], lg, cur), 8.6, True, align="r", width=xs[3][1])
    page.text(xs[4][0] - 4, y, pdf_money(s["current_value"], lg, cur), 8.6, True, align="r", width=xs[4][1])
    y += 26
    page.para(PDF_L, y, tr("Current value = book value, unless you enter an own value.") + " " + d["disclaimer"], 8, PDF_CW, color=C_INK2)
    data = pdf_write(pages, {}, title=tr("Equipment value"), author=co)
    return Response(data, mimetype="application/pdf", headers={"Content-Disposition": 'attachment; filename="equipment-value.pdf"'})


def bnk_pdf_w(s):
    from .pdf import pdf_text_width
    return pdf_text_width(s, 8.6)


def bnk_devices(n):
    from ..core.i18n import trn
    return trn("{0} device", "{0} devices", n, n)
