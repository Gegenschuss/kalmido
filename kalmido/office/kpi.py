"""Office & finance (2.50.0, #1197, part B): the business figures at a glance -- one route, the server computes, the view only
shows. Admins of the office area only (a personal office: its owner).
 - revenue = the money received on invoices (payments, net share of each payment; refunds on credit notes subtracted), per
   month of the year and the year before, this month and the year so far against the same span a year earlier
 - open and overdue invoices (count + open gross; overdue = inv_state)
 - per client: hours against budget (budget_h / budget_amount, hours of the client's projects as the admin sees them),
   invoiced net in the year (finalised invoices minus credit notes), costs in the year (purchases of accepted quotations,
   travel receipts of the client) and the margin = invoiced minus costs; per project (list of a client): hours against its
   "Budget h" field
 - the pipeline (#1196): open and weighted value
 - the cash flow (#1652): the next three months from rk_cashflow (not computed twice)
Amounts in the office currency (documents in another currency through their rate)."""
import json
from datetime import date

from flask import jsonify, request

from ..core.config import app
from ..core.i18n import tr
from ..core.db import db, local_now
from ..core.errors import BadInput
from .calc import dec, dstr, money
from .homecur import hc_doc_fx, hc_home
from .model import office_gate, office_org, office_settings, pb_cl_sql


from .model import office_ctx_admin as _ctx  # noqa: E402  2.149.0 G (#2517): was an own copy
from .invoices import inv_money_fields, inv_state  # 2.369.5 (#2517): pulled up from functions
from ..personal.timetrack import time_list_totals, time_report  # 2.369.5 (#2517): pulled up from functions
from ..team.clients import budget_state, client_lists_many  # 2.369.5 (#2517): pulled up from functions
from .costs import ek_purchases  # 2.369.5 (#2517): pulled up from functions
from .travel import rk_trips  # 2.369.5 (#2517): pulled up from functions
from .cashflow import rk_cashflow  # 2.369.5 (#2517): pulled up from functions
from .pipeline import pl2_weighted  # 2.369.5 (#2517): pulled up from functions


def _j(s):
    try:
        v = json.loads(s) if s else {}
    except ValueError:
        return {}
    return v if isinstance(v, dict) else {}


def _fx(r, home):
    return hc_doc_fx(r, home)  # 2.189.0 B (#2475): every foreign currency


def _net_share(r):
    """net / gross of a document (a payment's net part); 1 without VAT or without totals."""
    t = _j(r["totals"])
    g, n = dec(t.get("gross") or 0), dec(t.get("net") or 0)
    return n / g if g > 0 and n > 0 else dec(1)


def kpi_revenue(c, oid, home, docs, year, today):
    """{months: [{month, amount, prev}], month, month_prev, year, year_prev, to_date} (net received, office currency).
    The year shown = this year: year / year_prev = the year so far and the same span a year earlier (to_date true);
    an earlier year: the whole year and the one before."""
    by_id = {r["id"]: r for r in docs}
    to_date = year == int(today[:4])
    sums, ytd = {}, {}
    from .books import BK_PAY_DAY  # 2.355.0 C (#2841): a reversal line on the day of its payment, as the books
    for p in c.execute(f"SELECT p.doc_id, {BK_PAY_DAY} AS date, p.amount FROM office_payments p LEFT JOIN office_payments o "
                       f"ON o.id=p.reverses_id AND o.org_id=p.org_id WHERE p.org_id=? AND {BK_PAY_DAY}>=? AND {BK_PAY_DAY}<?",
                       (oid, f"{year - 1}-01-01", f"{year + 1}-01-01")):
        r = by_id.get(p["doc_id"])
        if r is None or not p["date"]:
            continue
        a = dec(p["amount"]) * _net_share(r) / _fx(r, home)
        if r["kind"] == "credit":
            a = -a  # a refund paid on a credit note
        y, mo = p["date"][:4], p["date"][:7]
        sums[mo] = sums.get(mo, dec(0)) + a
        if not to_date or p["date"][5:10] <= today[5:10]:
            ytd[y] = ytd.get(y, dec(0)) + a
    from .books import bk_fees_paid  # 2.545.0 (#4387): paid reminder fees count as money received, as in the books (no VAT)
    for f in bk_fees_paid(c, oid, f"{year - 1}-01-01", f"{year}-12-31", home):
        y, mo = f["date"][:4], f["date"][:7]
        sums[mo] = sums.get(mo, dec(0)) + f["amount"]
        if not to_date or f["date"][5:10] <= today[5:10]:
            ytd[y] = ytd.get(y, dec(0)) + f["amount"]
    g = lambda d, k: dstr(money(d.get(k, dec(0))))
    mm = today[5:7] if to_date else "12"
    return {"months": [{"month": f"{year}-{m:02d}", "amount": g(sums, f"{year}-{m:02d}"), "prev": g(sums, f"{year - 1}-{m:02d}")} for m in range(1, 13)],
            "month_key": f"{year}-{mm}", "month": g(sums, f"{year}-{mm}"), "month_prev": g(sums, f"{year - 1}-{mm}"),
            "year": g(ytd, str(year)), "year_prev": g(ytd, str(year - 1)), "to_date": to_date}


def kpi_open(docs, pm, home, today):
    """{open: {count, amount}, overdue: {count, amount}} of the finalised invoices."""
    out = {"open": [0, dec(0)], "overdue": [0, dec(0)]}
    for r in docs:
        if r["kind"] != "invoice" or not r["locked_at"] or r["status"] in ("draft", "cancelled", "paid"):
            continue
        o = dec(inv_money_fields(r, pm)["open"])
        if o <= 0:
            continue
        a = o / _fx(r, home)
        out["open"][0] += 1
        out["open"][1] += a
        if inv_state(r, pm, today) == "overdue":
            out["overdue"][0] += 1
            out["overdue"][1] += a
    return {k: {"count": v[0], "amount": dstr(money(v[1]))} for k, v in out.items()}


def kpi_clients(c, uid, oid, home, docs, year):
    """[{id, name, hours, budget_h, amount, budget_amount, pct_h, pct_amount, level, invoiced, costs, margin, projects:
    [{id, name, hours, budget_h, pct_h}]}] -- clients with hours, a budget or documents in the year, biggest first."""
    y0, y1 = f"{year}-01-01", f"{year}-12-31"
    cls = [r for r in c.execute(f"SELECT id, name, budget_h, budget_amount, archived FROM clients WHERE {pb_cl_sql(c, oid)} AND deleted_at IS NULL ORDER BY lower(name), id")]
    inv, cost = {}, {}
    gone = {r["id"] for r in docs if r["kind"] == "invoice" and r["status"] == "cancelled"}  # 2.354.0 B (#2842)
    for r in docs:
        if r["kind"] == "credit" and r["cancels_id"] in gone:
            continue  # 2.354.0 B (#2842): the credit note of a skipped (cancelled) invoice is skipped too, like books.py
        if r["kind"] in ("invoice", "credit") and r["locked_at"] and r["status"] != "cancelled" and r["client_id"] and y0 <= (r["date"] or "") <= y1:
            n = dec(_j(r["totals"]).get("net") or 0) / _fx(r, home)
            inv[r["client_id"]] = inv.get(r["client_id"], dec(0)) + (-n if r["kind"] == "credit" else n)
    purchases = ek_purchases(c, oid, y0, y1)
    doc_client = kpi_doc_clients(c, oid, {p["doc_id"] for p in purchases})  # 2.525.0 (#4187): only the quotations of the purchases
    for p in purchases:
        k = doc_client.get(p["doc_id"])
        if k:
            cost[k] = cost.get(k, dec(0)) + dec(p["amount"] or 0)
    for t in rk_trips(c, oid, year=str(year)):
        if t.get("client_id"):
            cost[t["client_id"]] = cost.get(t["client_id"], dec(0)) + sum((dec(it["amount_home"] or 0) for it in t["items"]), dec(0))
    lids = client_lists_many(c, uid, [cl["id"] for cl in cls])  # 2.525.0 (#4187): one query, was one per client
    every = sorted({x for v in lids.values() for x in v})
    per_list, names = {}, {}
    if every:
        rep = time_report(c, uid, {"scope": "all", "lists": ",".join(str(x) for x in every)})
        for g in rep["lists"]:
            per_list[g["id"]] = g
    if every:
        q = ",".join("?" * len(every))
        names = {r[0]: r[1] for r in c.execute(f"SELECT id, name FROM lists WHERE id IN ({q})", every)}
    lbud = time_list_totals(c, uid) if every else {}
    out = []
    for cl in cls:
        ls = lids[cl["id"]]
        st = {"rounded": sum(per_list.get(x, {}).get("rounded", 0) for x in ls), "amount": sum(per_list.get(x, {}).get("amount", 0.0) for x in ls)}
        i, k = inv.get(cl["id"], dec(0)), cost.get(cl["id"], dec(0))
        if not (st["rounded"] or cl["budget_h"] or cl["budget_amount"] or i or k):
            continue
        b = budget_state(st, cl)
        projects = []
        for x in ls:
            h = per_list.get(x, {}).get("rounded", 0) / 3600
            bh = (lbud.get(x) or {}).get("b")
            if h or bh:
                projects.append({"id": x, "name": names.get(x, ""), "hours": round(h, 2), "budget_h": bh,
                                 "pct_h": round(h / bh * 100) if bh else None})
        out.append({"id": cl["id"], "name": cl["name"], "archived": bool(cl["archived"]), "hours": round(st["rounded"] / 3600, 2), "budget_h": cl["budget_h"],
                    "amount": round(st["amount"], 2), "budget_amount": cl["budget_amount"], "pct_h": b["pct_h"], "pct_amount": b["pct_amount"],
                    "level": b["level"], "invoiced": dstr(money(i)), "costs": dstr(money(k)), "margin": dstr(money(i - k)),
                    "margin_pct": round(float((i - k) / i * 100)) if i > 0 else None, "projects": projects})
    out.sort(key=lambda x: (-float(x["invoiced"]), -x["hours"], x["name"].casefold()))
    return out


# 2.525.0 (#4187): the columns the figures read (kpi_revenue, kpi_open, kpi_clients, inv_state / inv_money_fields, hc_doc_fx);
# the texts, recipient and fields of a document stay in the database
KPI_COLS = "id, kind, status, locked_at, client_id, date, totals, currency, fx_rate, cancels_id, due_date, skonto_pct"


def kpi_docs(c, oid, year):
    """2.525.0 (#4187): the documents the figures of year need, filtered in SQL (was every document of every year):
    the open finalised invoices (kpi_open, any year), the invoices / credit notes dated in the year (kpi_clients), the
    documents paid in the year or the one before (kpi_revenue, the same payment filter) and the cancelled invoices a
    credit note of the year refers to (kpi_clients skips that credit note). The Python checks behind stay as they were:
    the rows here are a superset of the ones they count, so every sum stays the same to the cent."""
    from .books import BK_PAY_DAY
    y = str(year)
    # 2.144.10 B (#2576): no trial documents in the figures (their payments drop out through by_id)
    return c.execute(
        f"SELECT {KPI_COLS} FROM office_docs WHERE org_id=? AND kind IN ('invoice', 'credit', 'offer') AND trial=0 AND ("
        "(kind='invoice' AND locked_at IS NOT NULL AND status NOT IN ('draft', 'cancelled', 'paid'))"
        " OR (kind IN ('invoice', 'credit') AND substr(date, 1, 4)=?)"
        f" OR id IN (SELECT p.doc_id FROM office_payments p LEFT JOIN office_payments o ON o.id=p.reverses_id AND o.org_id=p.org_id"
        f" WHERE p.org_id=? AND {BK_PAY_DAY}>=? AND {BK_PAY_DAY}<?)"
        " OR (kind='invoice' AND status='cancelled' AND id IN (SELECT x.cancels_id FROM office_docs x WHERE x.org_id=? AND x.kind='credit'"
        " AND x.cancels_id IS NOT NULL AND substr(x.date, 1, 4)=?)))",
        (oid, y, oid, f"{year - 1}-01-01", f"{year + 1}-01-01", oid, y)).fetchall()


def kpi_doc_clients(c, oid, ids):
    """2.525.0 (#4187): {doc id: client id} of the documents ids (the quotations of the purchases), the same kinds as the figures."""
    ids = sorted(int(x) for x in ids if x)
    if not ids:
        return {}
    return {r[0]: r[1] for r in c.execute(f"SELECT id, client_id FROM office_docs WHERE org_id=? AND kind IN ('invoice', 'credit', 'offer') "
                                          f"AND trial=0 AND id IN ({','.join('?' * len(ids))})", [oid, *ids])}


# 2.525.0 (#4187): the tile Figures (start page, office start) asks every minute; the answer is kept per office, person
# and day for KPI_TTL seconds while nothing changed: kpi_mark = the data version of the instance (every write through the
# app moves it: time entries, clients, purchases ...) plus a short fingerprint of the office's documents and payments
# (writes past the version too), so nobody sees the old figures after an own change; every worker process checks it itself.
KPI_TTL = 45
KPI_CACHE_MAX = 256
_KPI_CACHE = {}


def kpi_mark(c, oid):
    """The fingerprint of kpi_cached: one query over small columns (no texts, no totals JSON). 2.525.0 review (#4187): also the
    office settings (a new home currency or tax reserve is not served from the cache; saving them bumps no data version)."""
    r = c.execute("SELECT (SELECT value FROM settings WHERE key='version'), "
                  "(SELECT md5(string_agg(id || ':' || status || ':' || COALESCE(locked_at, '') || ':' || updated_at || ':' || date, ',' ORDER BY id)) "
                  "FROM office_docs WHERE org_id=?), "
                  "(SELECT md5(string_agg(id || ':' || doc_id || ':' || amount || ':' || date, ',' ORDER BY id)) FROM office_payments WHERE org_id=?), "
                  "(SELECT md5(data) FROM office_settings WHERE org_id=?)",  # 2.525.0 review (#4187): home currency, tax reserve
                  (oid, oid, oid)).fetchone()
    return tuple(str(x) for x in r)


def kpi_cached(c, uid, oid, year=None, now=None):
    """kpi_build through the short cache (see KPI_TTL)."""
    import time
    now = time.monotonic() if now is None else now
    today = local_now().date().isoformat()
    key = (oid, uid, year, today)
    mark = kpi_mark(c, oid)
    hit = _KPI_CACHE.get(key)
    if hit and hit[1] == mark and now - hit[0] < KPI_TTL:
        return hit[2]
    out = kpi_build(c, uid, oid, year, today)
    if len(_KPI_CACHE) >= KPI_CACHE_MAX:
        for k in [k for k, v in _KPI_CACHE.items() if now - v[0] >= KPI_TTL] or list(_KPI_CACHE)[:KPI_CACHE_MAX // 2]:
            _KPI_CACHE.pop(k, None)
    _KPI_CACHE[key] = (now, mark, out)
    return out


def kpi_build(c, uid, oid, year=None, today=None):
    from .invoices import inv_paid_map
    home = hc_home(office_settings(c, oid))  # 2.189.0 B (#2475): the home currency
    today = today or local_now().date().isoformat()
    year = year or int(today[:4])
    docs = kpi_docs(c, oid, year)
    # 2.525.0 (#4187): the paid map only of the invoices kpi_open counts (the open ones; it is its only reader)
    pm = inv_paid_map(c, oid, [r["id"] for r in docs if r["kind"] == "invoice" and r["locked_at"] and r["status"] not in ("draft", "cancelled", "paid")])
    cf = rk_cashflow(c, oid, today[:7], 3, today)
    return {"currency": home, "today": today, "year": year, "revenue": kpi_revenue(c, oid, home, docs, year, today),
            "invoices": kpi_open(docs, pm, home, today), "clients": kpi_clients(c, uid, oid, home, docs, year),
            "pipeline": pl2_weighted(c, oid), "cashflow": cf["rows"]}


@app.get("/api/office/kpi")
def kpi_get():
    """?year=YYYY (default: this one) -> kpi_build."""
    c, uid, oid = _ctx()
    y = request.args.get("year") or ""
    if y and not (y.isdigit() and len(y) == 4 and 2000 <= int(y) <= local_now().year + 1):
        raise BadInput(tr("Invalid value: {0}", "year"))
    return jsonify(kpi_cached(c, uid, oid, int(y) if y else None))
