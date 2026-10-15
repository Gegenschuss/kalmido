"""Office & finance (2.47.3, #1652, part B): the cash flow -- per month what comes in and what goes out, actual (paid / past)
and planned (expected), with the entries behind every value. Released 2026-10-15. No bank access.

In:  payments of invoices on their day (actual); the open rest of finalised invoices on their due day (planned; overdue =
     the current month); accepted quotations not yet invoiced in full, the rest on the end of the period of service (else its
     start, else the day of the quotation; past = the current month; planned).
Out: purchases of accepted quotations (office_purchases, #1649), travel receipts (#1022) and fixed costs entered by hand
     (office_fixed_costs, once / monthly / quarterly / yearly) -- on or before today actual, later planned.
Amounts in the office currency (documents in another currency through their rate), gross for documents. The artists'
social insurance is not booked as an outflow by itself (an open question).
Every route: office_gate + office_org with the admin of the office area; fixed costs encrypted at rest (orgcrypt)."""
import json
import re
from datetime import date

from flask import jsonify, request

from ..core.config import app
from ..core.pg import insert_id
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields
from ..core.i18n import tr
from ..core.db import body, bump, db, iso, local_now, now_utc
from ..core.access import Denied
from ..personal.timetrack import BadInput
from .calc import dec, dstr, money
from .model import office_gate, office_org, office_settings

CF_REPEATS = ("once", "monthly", "quarterly", "yearly")
CF_STEP = {"monthly": 1, "quarterly": 3, "yearly": 12}
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_FIXED = 500


def _ctx():
    c = db()
    uid = office_gate(c)
    return c, uid, office_org(c, uid, admin=True)


def _j(s):
    try:
        v = json.loads(s) if s else {}
    except ValueError:
        return {}
    return v if isinstance(v, dict) else {}


def _add_months(ym, n):
    y, m = int(ym[:4]), int(ym[5:7]) - 1 + n
    return f"{y + m // 12:04d}-{m % 12 + 1:02d}"


def _fx(r, home):
    """The rate of document row r to the office currency (amount / rate = office currency)."""
    if (r["currency"] or home) == home:
        return dec(1)
    fx = dec(r["fx_rate"], "1.09" if r["currency"] == "USD" else "1")
    return fx if fx > 0 else dec(1)


def _date(v, name, required=False):
    if v in (None, ""):
        if required:
            raise BadInput(tr("Invalid value: {0}", name))
        return ""
    if isinstance(v, str) and DATE_RE.match(v.strip()):
        try:
            return date.fromisoformat(v.strip()).isoformat()
        except ValueError:
            pass
    raise BadInput(tr("Invalid value: {0}", name))


# ---------------------------------------------------------------- fixed costs
def rk_fixed_clean(b, cur=None):
    cur = cur or {}
    out = {}
    if "label" in b or not cur:
        v = b.get("label")
        if not isinstance(v, str) or not v.strip():
            raise BadInput(tr("Please enter a name"))
        out["label"] = re.sub(r"[\x00-\x1f\x7f]", "", v).strip()[:200]
    if "amount" in b or not cur:
        v = b.get("amount")
        if isinstance(v, bool) or not isinstance(v, (int, float, str)) or v == "":
            raise BadInput(tr("Invalid value: {0}", "amount"))
        a = dec(v, "NaN")
        if a.is_nan() or not a.is_finite() or a <= 0 or a > 10 ** 9:
            raise BadInput(tr("Invalid value: {0}", "amount"))
        out["amount"] = dstr(money(a))
    if "start" in b or not cur:
        out["start"] = _date(b.get("start"), "start", required=True)
    if "until" in b or not cur:
        out["until"] = _date(b.get("until"), "until")
    if "repeat" in b or not cur:
        rp = b.get("repeat") or "monthly"
        if rp not in CF_REPEATS:
            raise BadInput(tr("Invalid value: {0}", "repeat"))
        out["repeat"] = rp
    st, un = out.get("start", cur.get("start")), out.get("until", cur.get("until"))
    if st and un and un < st:
        raise BadInput(tr("The end is before the start"))
    return out


def _fixed_public(c, oid, r):
    d = oc_dec_fields(c, oid, "office_fixed_costs", r)
    return {k: d.get(k) for k in ("id", "label", "amount", "start", "until", "repeat")}


def rk_fixed(c, oid):
    return [_fixed_public(c, oid, r) for r in c.execute("SELECT * FROM office_fixed_costs WHERE org_id=? ORDER BY lower(label), id", (oid,))]


def rk_fixed_days(f, first, last):
    """The due days of fixed cost f within [first, last] (ISO days): from its start every step of months (the day of the
    month kept, the 31st becomes the month's last day), up to its end; once = its start only."""
    st = f.get("start") or ""
    if not st:
        return []
    if f.get("repeat") == "once":
        return [st] if first <= st <= last else []
    step = CF_STEP.get(f.get("repeat"), 1)
    y, m, d = int(st[:4]), int(st[5:7]), int(st[8:10])
    out, i = [], 0
    end = min(last, f.get("until") or last)
    while True:
        mm = m - 1 + i * step
        yy, mo = y + mm // 12, mm % 12 + 1
        nxt = date(yy + (mo == 12), mo % 12 + 1, 1)
        day = date(yy, mo, min(d, (nxt - date(yy, mo, 1)).days)).isoformat()
        if day > end:
            break
        if day >= first:
            out.append(day)
        i += 1
        if i > 1200:
            break
    return out


@app.get("/api/office/fixed-costs")
def rk_fixed_get():
    c, uid, oid = _ctx()
    return jsonify(items=rk_fixed(c, oid))


@app.post("/api/office/fixed-costs")
def rk_fixed_post():
    """{label, amount, start, until?, repeat once|monthly|quarterly|yearly} -> 201 the entry."""
    c, uid, oid = _ctx()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    if c.execute("SELECT COUNT(*) FROM office_fixed_costs WHERE org_id=?", (oid,)).fetchone()[0] >= MAX_FIXED:
        raise BadInput(tr("Too many entries"))
    row = rk_fixed_clean(b)
    ts = iso(now_utc())
    row.update(org_id=oid, created_by=uid, created_at=ts, updated_at=ts)
    row = oc_enc_fields(c, oid, "office_fixed_costs", row)
    fid = insert_id(c, f"INSERT INTO office_fixed_costs({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    bump(c)
    c.commit()
    return jsonify(_fixed_public(c, oid, c.execute("SELECT * FROM office_fixed_costs WHERE id=?", (fid,)).fetchone())), 201


def _fixed_row(c, oid, fid):
    r = c.execute("SELECT * FROM office_fixed_costs WHERE id=? AND org_id=?", (fid, oid)).fetchone()
    if not r:
        raise Denied(404)
    return r


@app.patch("/api/office/fixed-costs/<int:fid>")
def rk_fixed_patch(fid):
    c, uid, oid = _ctx()
    cur = _fixed_public(c, oid, _fixed_row(c, oid, fid))
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    row = rk_fixed_clean(b, cur)
    if row:
        row["updated_at"] = iso(now_utc())
        row = oc_enc_fields(c, oid, "office_fixed_costs", row)
        c.execute(f"UPDATE office_fixed_costs SET {','.join(k + '=?' for k in row)} WHERE id=? AND org_id=?", list(row.values()) + [fid, oid])
        bump(c)
        c.commit()
    return jsonify(_fixed_public(c, oid, _fixed_row(c, oid, fid)))


@app.delete("/api/office/fixed-costs/<int:fid>")
def rk_fixed_delete(fid):
    """Deletes an entry; answers it as it was (the client's undo posts it again)."""
    c, uid, oid = _ctx()
    old = _fixed_public(c, oid, _fixed_row(c, oid, fid))
    c.execute("DELETE FROM office_fixed_costs WHERE id=? AND org_id=?", (fid, oid))
    bump(c)
    c.commit()
    return jsonify(ok=True, item=old)


# ---------------------------------------------------------------- the cash flow
def rk_cashflow(c, oid, first_month, months, today=None):
    """{from, months, currency, today, rows: [{month, in: {actual, plan}, out: {actual, plan}, balance}], entries: [...]}.
    An entry: {month, dir in|out, state actual|plan, kind payment|invoice|offer|purchase|trip|fixed, date, amount, label,
    number, doc_id | trip_id | fixed_id, overdue} (kind credit = a refund paid on a credit note, out)."""
    from .costs import ek_purchases
    from .invoices import inv_money_fields, inv_paid_map
    home = (office_settings(c, oid).get("currency") or "EUR").upper()
    today = today or local_now().date().isoformat()
    cur_month = today[:7]
    last_month = _add_months(first_month, months - 1)
    first, last = first_month + "-01", _add_months(last_month, 1) + "-01"  # last = exclusive
    ms = [_add_months(first_month, i) for i in range(months)]
    entries = []

    def put(day, dir_, state, kind, amount, label, **ref):
        amount = money(amount)
        if amount <= 0:
            return
        mo = day[:7]
        if mo not in ms:
            return
        entries.append(dict(month=mo, dir=dir_, state=state, kind=kind, date=day, amount=dstr(amount), label=label, **ref))

    def plan_day(day):
        """A planned day in the past = expected now (the current month)."""
        return today if not day or day < today else day

    docs = c.execute("SELECT * FROM office_docs WHERE org_id=? AND kind IN ('offer', 'invoice', 'credit')", (oid,)).fetchall()
    inv = [r for r in docs if r["kind"] == "invoice" and r["locked_at"] and r["status"] not in ("draft", "cancelled")]
    pm = inv_paid_map(c, oid, [r["id"] for r in inv])
    by_id = {r["id"]: r for r in docs}
    # in: payments of invoices (actual; out: refunds on credit notes)
    for p in c.execute("SELECT doc_id, date, amount FROM office_payments WHERE org_id=? AND date>=? AND date<?", (oid, first, last)):
        r = by_id.get(p["doc_id"])
        if r is None:
            continue
        cr = r["kind"] == "credit"  # a refund paid on a credit note goes out
        put(p["date"], "out" if cr else "in", "actual", "credit" if cr else "payment", dec(p["amount"]) / _fx(r, home), r["project_title"] or "",
            number=r["number"], doc_id=r["id"])
    # in: open rest of finalised invoices (plan, on the due day)
    for r in inv:
        open_ = dec(inv_money_fields(r, pm)["open"])
        if open_ <= 0:
            continue
        due = r["due_date"] or r["date"] or ""
        day = plan_day(due)
        put(day, "in", "plan", "invoice", open_ / _fx(r, home), r["project_title"] or "", number=r["number"], doc_id=r["id"],
            overdue=bool(due and due < today))
    # in: accepted quotations, the rest not yet invoiced (plan)
    billed = {}
    for r in inv:
        if r["source_doc_id"]:
            billed[r["source_doc_id"]] = billed.get(r["source_doc_id"], dec(0)) + dec(_j(r["totals"]).get("gross") or 0) / _fx(r, home)
    for r in docs:
        if r["kind"] != "offer" or r["status"] != "accepted":
            continue
        gross = dec(_j(r["totals"]).get("gross") or 0) / _fx(r, home)
        rest = gross - billed.get(r["id"], dec(0))
        if rest <= 0:
            continue
        day = plan_day(r["service_to"] or r["service_from"] or r["date"] or "")
        put(day, "in", "plan", "offer", rest, r["project_title"] or "", number=r["number"], doc_id=r["id"], partial=r["id"] in billed)
    # out: purchases of accepted quotations
    for p in ek_purchases(c, oid, first, _add_months(last_month, 1) + "-00"):
        put(p["date"], "out", "actual" if p["date"] <= today else "plan", "purchase", dec(p["amount"]),
            p["label"] or "", number=p["number"], doc_id=p["doc_id"])
    # out: travel receipts
    from .travel import rk_trips
    for t in rk_trips(c, oid):
        for it in t["items"]:
            day = it["date"] or t["date_from"]
            if first <= day < last:
                put(day, "out", "actual" if day <= today else "plan", "trip", dec(it["amount_home"]),
                    " · ".join(x for x in (t["dest"], it["text"]) if x), trip_id=t["id"], category=it["category"])
    # out: fixed costs
    for f in rk_fixed(c, oid):
        for day in rk_fixed_days(f, first, _add_months(last_month, 1) + "-00"):
            put(day, "out", "actual" if day <= today else "plan", "fixed", dec(f["amount"]), f["label"], fixed_id=f["id"], repeat=f["repeat"])
    entries.sort(key=lambda e: (e["month"], e["dir"], e["date"], e["kind"]))
    rows = []
    for mo in ms:
        s = {("in", "actual"): dec(0), ("in", "plan"): dec(0), ("out", "actual"): dec(0), ("out", "plan"): dec(0)}
        for e in entries:
            if e["month"] == mo:
                s[(e["dir"], e["state"])] += dec(e["amount"])
        bal = s[("in", "actual")] + s[("in", "plan")] - s[("out", "actual")] - s[("out", "plan")]
        rows.append({"month": mo, "past": mo < cur_month, "current": mo == cur_month,
                     "in": {"actual": dstr(s[("in", "actual")]), "plan": dstr(s[("in", "plan")])},
                     "out": {"actual": dstr(s[("out", "actual")]), "plan": dstr(s[("out", "plan")])}, "balance": dstr(bal)})
    return {"from": first_month, "months": months, "currency": home, "today": today, "rows": rows, "entries": entries}


@app.get("/api/office/cashflow")
def rk_cashflow_get():
    """?from=YYYY-MM (default: this month)&months=1..12 (the view offers 3 or 6; default 3) -> rk_cashflow."""
    c, uid, oid = _ctx()
    fm = request.args.get("from") or local_now().date().isoformat()[:7]
    if not MONTH_RE.match(fm):
        raise BadInput(tr("Invalid value: {0}", "from"))
    try:
        n = int(request.args.get("months") or 3)
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "months"))
    if not 1 <= n <= 12:
        raise BadInput(tr("Invalid value: {0}", "months"))
    return jsonify(rk_cashflow(c, oid, fm, n))
