"""Office & finance (2.47.3, #1652, part B): the cash flow -- per month what comes in and what goes out, actual (paid / past)
and planned (expected), with the entries behind every value. Released 2026-10-15. No bank access.

In:  payments of invoices on their day (actual); the open rest of finalised invoices on their due day (planned; overdue =
     the current month); quotations (2.88.0, #1915: sent = an open quotation, and accepted ones; one version per chain, see
     cf8_counting; a chain with a finalised invoice is left out) on the end of the period of service (else its start, else
     the day of the quotation; past = the current month; planned).
Out: purchases of accepted quotations (office_purchases, #1649), travel receipts (#1022), fixed costs entered by hand
     (office_fixed_costs, once / monthly / quarterly / yearly) and receipts of the books (2.114.1, #2018: on their payment
     day, else their document date, as the EUeR; matched to a bank booking = its amount) -- on or before today actual,
     later planned.
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
from ..core.errors import BadInput
from .calc import dec, dstr, money
from .model import office_gate, office_org, office_settings

CF_REPEATS = ("once", "monthly", "quarterly", "yearly")
CF_STEP = {"monthly": 1, "quarterly": 3, "yearly": 12}
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_FIXED = 500
CF_VAT_RATES = (0, 7, 19)  # 2.67.0 (#1838)
CF_BASES = ("gross", "net")


from .model import office_ctx_admin as _ctx  # noqa: E402  2.149.0 G (#2517): was an own copy


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
def rk_fixed_clean(b, cur=None, c=None, oid=None):
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
    # 2.67.0 (#1838): a free category (the list groups by it) and the VAT rate of the net amount (0 / 7 / 19; 0 before)
    if "category" in b or not cur:
        v = b.get("category")
        out["category"] = re.sub(r"[\x00-\x1f\x7f]", "", v).strip()[:100] if isinstance(v, str) else ""
    if "vat_rate" in b or not cur:
        v = b.get("vat_rate", 0)
        if isinstance(v, bool) or v in (None, ""):
            v = 0
        try:
            v = int(v)
        except (TypeError, ValueError):
            raise BadInput(tr("Invalid value: {0}", "vat_rate")) from None
        if v not in CF_VAT_RATES:
            raise BadInput(tr("Invalid value: {0}", "vat_rate"))
        out["vat_rate"] = v
    st, un = out.get("start", cur.get("start")), out.get("until", cur.get("until"))
    if st and un and un < st:
        raise BadInput(tr("The end is before the start"))
    from .subs import abo_clean
    out.update(abo_clean(c, oid, b, cur))  # 2.91.0 B (#1924): the subscription fields (sub, notice_days, seats, ...)
    return out


def _fixed_public(c, oid, r):
    d = oc_dec_fields(c, oid, "office_fixed_costs", r)
    out = {k: d.get(k) for k in ("id", "label", "amount", "start", "until", "repeat", "category", "vat_rate")}
    out["category"], out["vat_rate"] = out["category"] or "", int(out["vat_rate"] or 0)  # 2.67.0 (#1838)
    out["gross"] = dstr(fci_gross(out["amount"], out["vat_rate"]))
    from .subs import abo_public
    out.update(abo_public(d, out))  # 2.91.0 B (#1924): the subscription fields + next_renewal, cancel_by, per_month / per_year
    return out


def fci_gross(amount, rate):
    """2.67.0 (#1838): the gross of a net fixed cost (rounded to the cent)."""
    return money(dec(amount) * (100 + int(rate or 0)) / 100)


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
    """{items, agreements (2.92.0 A, #1925: the contributions of business contracts in the cash flow, read-only here)}."""
    from .agreements import agr_cashflow_items
    c, uid, oid = _ctx()
    return jsonify(items=rk_fixed(c, oid), agreements=agr_cashflow_items(c, oid))


@app.post("/api/office/fixed-costs")
def rk_fixed_post():
    """{label, amount, start, until?, repeat once|monthly|quarterly|yearly} -> 201 the entry."""
    c, uid, oid = _ctx()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    if c.execute("SELECT COUNT(*) FROM office_fixed_costs WHERE org_id=?", (oid,)).fetchone()[0] >= MAX_FIXED:
        raise BadInput(tr("Too many entries"))
    row = rk_fixed_clean(b, c=c, oid=oid)  # 2.91.0 B (#1924): c, oid for seats / remind_user
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
    row = rk_fixed_clean(b, cur, c=c, oid=oid)  # 2.91.0 B (#1924)
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
CF8_CHOICES = ("auto", "yes", "no")  # 2.88.0 (#1915): office_docs.cashflow of a quotation
CF8_COUNTS = ("sent", "accepted")  # the statuses a quotation can count with


def cf8_key(r):
    """2.88.0 (#1915): the chain of quotation row r = (the chain's first quotation, the client). Duplicating sets version_of
    (office/docs.py odoc_duplicate); a copy moved to another client is a quotation of its own, not a version."""
    return (r["version_of"] or r["id"], r["client_id"])


def cf8_invoiced(inv):
    """The quotations with a finalised invoice (not a draft, not cancelled: the rows of rk_cashflow's inv) by source_doc_id."""
    # 2.120.0 (#2087, review M1): a progress invoice does not settle its quotation -- the rest stays in the plan (rk_cashflow)
    return {r["source_doc_id"] for r in inv if r["source_doc_id"] and (r["inv_type"] or "") != "progress"}


def cf8_counting(docs, invoiced):
    """2.88.0 (#1915): the ids of the quotations that count in the cash flow plan. Per chain (cf8_key):
    - a chain with an invoice of any of its versions (invoiced) counts not at all (the invoice is in the plan instead);
    - only sent and accepted versions can count (drafts and declined ones never);
    - cashflow no: this version never counts;
    - cashflow yes: when at least one version of the chain says yes, exactly the yes versions count (several are possible);
    - else (all auto): only the newest version counts (the highest id, i.e. the last copy)."""
    chains = {}
    for r in docs:
        if r["kind"] == "offer":
            chains.setdefault(cf8_key(r), []).append(r)
    out = set()
    for rows in chains.values():
        if any(r["id"] in invoiced for r in rows):
            continue
        cand = [r for r in rows if r["status"] in CF8_COUNTS and (r["cashflow"] or "auto") != "no"]
        yes = [r["id"] for r in cand if r["cashflow"] == "yes"]
        if yes:
            out.update(yes)
        elif cand:
            out.add(max(r["id"] for r in cand))
    return out


def cf8_chain(c, oid, r):
    """2.88.0 (#1915): the chain of quotation r for its editor: {cashflow, versions: [{id, number, status, cashflow, counts}]
    (oldest first), counts (r itself), counting: [ids], invoiced (a version has an invoice)}."""
    root = r["version_of"] or r["id"]
    rows = c.execute("SELECT id, kind, number, status, cashflow, version_of, client_id FROM office_docs WHERE org_id=? AND kind='offer' "
                     "AND (id=? OR version_of=?) ORDER BY id", (oid, root, root)).fetchall()
    rows = [x for x in rows if cf8_key(x) == cf8_key(r)]
    inv = c.execute("SELECT source_doc_id FROM office_docs WHERE org_id=? AND kind='invoice' AND locked_at IS NOT NULL AND locked_at<>'' "
                    "AND status NOT IN ('draft', 'cancelled') AND COALESCE(inv_type, '')<>'progress' AND source_doc_id IN (%s)" % ",".join("?" * len(rows)),
                    (oid, *[x["id"] for x in rows])).fetchall() if rows else []
    invoiced = {x["source_doc_id"] for x in inv}
    counting = cf8_counting(rows, invoiced)
    return {"cashflow": r["cashflow"] or "auto", "counts": r["id"] in counting, "counting": sorted(counting), "invoiced": bool(invoiced),
            "versions": [{"id": x["id"], "number": x["number"], "status": x["status"], "cashflow": x["cashflow"] or "auto",
                          "counts": x["id"] in counting} for x in rows]}


def rk_cashflow(c, oid, first_month, months, today=None, basis="gross", cfs=True):
    """{from, months, currency, today, basis, rows: [{month, in: {actual, plan}, out: {actual, plan}, balance}], entries: [...]}.
    An entry: {month, dir in|out, state actual|plan, kind payment|invoice|offer|series|purchase|trip|fixed|agreement|receipt, date, amount,
    label, number, doc_id | trip_id | fixed_id | agreement_id (2.92.0 A, #1925) | node_id (receipt, 2.114.1 B, #2018), overdue} (kind credit = a refund paid on a credit note, out; kind offer carries
    open_offer: true for a sent quotation not yet accepted, 2.88.0, #1915).
    2.67.0 (#1838): basis gross (default; the start page too) | net. Fixed costs are entered net with a VAT rate: gross adds
    it. Documents (payments, open invoices, quotations, credit notes) are gross; net takes their share net / gross of the
    document's totals. Purchases (purchase prices of quotations) and travel receipts have no rate here: the same amount on
    both bases.
    2.123.0 D (#2341): cfs (default on) adds the account balance of office/cfstart.py cfs_apply (start, account, manual, real,
    diff, adjust); off for its own inner runs."""
    from .costs import ek_purchases
    from .invoices import inv_money_fields, inv_paid_map
    st = office_settings(c, oid)
    home = (st.get("currency") or "EUR").upper()
    reserve_pct = int(st.get("tax_reserve_pct") or 0)  # 2.90.0 A (#1921): tax reserve on the net money coming in
    res_in = {}
    today = today or local_now().date().isoformat()
    cur_month = today[:7]
    last_month = _add_months(first_month, months - 1)
    first, last = first_month + "-01", _add_months(last_month, 1) + "-01"  # last = exclusive
    ms = [_add_months(first_month, i) for i in range(months)]
    entries = []
    net = basis == "net"

    def nf(r):
        """2.67.0 (#1838): the factor of a document's amounts on the chosen basis (net / gross of its totals)."""
        if not net:
            return dec(1)
        t = _j(r["totals"])
        g_, n_ = dec(t.get("gross") or 0), dec(t.get("net") or 0)
        return n_ / g_ if g_ > 0 and n_ > 0 else dec(1)

    def put(day, dir_, state, kind, amount, label, res=None, **ref):
        amount = money(amount)
        if amount <= 0:
            return
        mo = day[:7]
        if mo not in ms:
            return
        entries.append(dict(month=mo, dir=dir_, state=state, kind=kind, date=day, amount=dstr(amount), label=label, **ref))
        if res is not None:  # 2.90.0 A (#1921): the net part of money coming in, for the tax reserve
            res_in[mo] = res_in.get(mo, dec(0)) + res

    def netf(r):
        """2.90.0 A (#1921): net / gross of a document, whatever the basis shown."""
        t = _j(r["totals"])
        g_, n_ = dec(t.get("gross") or 0), dec(t.get("net") or 0)
        return n_ / g_ if g_ > 0 and n_ > 0 else dec(1)

    def plan_day(day):
        """A planned day in the past = expected now (the current month)."""
        return today if not day or day < today else day

    # 2.144.10 B (#2576): trial documents never enter the forecast (their payments drop out through by_id)
    docs = c.execute("SELECT * FROM office_docs WHERE org_id=? AND kind IN ('offer', 'invoice', 'credit') AND trial=0", (oid,)).fetchall()
    inv = [r for r in docs if r["kind"] == "invoice" and r["locked_at"] and r["status"] not in ("draft", "cancelled")]
    pm = inv_paid_map(c, oid, [r["id"] for r in inv])
    by_id = {r["id"]: r for r in docs}
    # in: payments of invoices (actual; out: refunds on credit notes). 2.161.0 (#2016 after #2168): a reversed payment and its
    # reversal line stay in the books (GoBD), but no money moved: both leave the cash flow
    for p in c.execute("SELECT doc_id, date, amount FROM office_payments p WHERE org_id=? AND date>=? AND date<? AND reverses_id IS NULL "
                       "AND NOT EXISTS (SELECT 1 FROM office_payments x WHERE x.org_id=p.org_id AND x.reverses_id=p.id)", (oid, first, last)):
        r = by_id.get(p["doc_id"])
        if r is None:
            continue
        cr = r["kind"] == "credit"  # a refund paid on a credit note goes out
        put(p["date"], "out" if cr else "in", "actual", "credit" if cr else "payment", dec(p["amount"]) / _fx(r, home) * nf(r), r["project_title"] or "",
            res=(-1 if cr else 1) * dec(p["amount"]) / _fx(r, home) * netf(r), number=r["number"], doc_id=r["id"])
    # in: open rest of finalised invoices (plan, on the due day)
    for r in inv:
        open_ = dec(inv_money_fields(r, pm)["open"])
        if open_ <= 0:
            continue
        due = r["due_date"] or r["date"] or ""
        day = plan_day(due)
        put(day, "in", "plan", "invoice", open_ / _fx(r, home) * nf(r), r["project_title"] or "", res=open_ / _fx(r, home) * netf(r),
            number=r["number"], doc_id=r["id"], overdue=bool(due and due < today))
    # in: quotations (plan). 2.88.0 (#1915): sent ones too (open quotation), one version per chain (cf8_counting); a chain with
    # an invoice is left out as a whole (was: the rest after the invoiced part; the invoice is in the plan by itself)
    counting = cf8_counting(docs, cf8_invoiced(inv))
    prog = {}  # 2.120.0 (#2087, review M1): finalised progress invoices per quotation, deducted from its planned amount
    for x in inv:
        if (x["inv_type"] or "") == "progress" and x["source_doc_id"]:
            prog[x["source_doc_id"]] = prog.get(x["source_doc_id"], 0) + dec(_j(x["totals"]).get("gross") or 0) / _fx(x, home)
    for r in docs:
        if r["id"] not in counting:
            continue
        gross = dec(_j(r["totals"]).get("gross") or 0) / _fx(r, home) - prog.get(r["id"], 0)
        day = plan_day(r["service_to"] or r["service_from"] or r["date"] or "")
        put(day, "in", "plan", "offer", gross * nf(r), r["project_title"] or "", res=gross * netf(r), number=r["number"], doc_id=r["id"],
            open_offer=r["status"] == "sent")
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
    # out: 2.114.1 B (#2018): the receipts of the books as the statement counts them (books.bk_receipts: the payment day --
    # set by the bank match -- else the document date); one matched to a bank booking with the booking's amount. Travel
    # receipts are no documents (never twice); a purchase or fixed cost entered as well for the same thing does count twice
    from .books import bk_receipts
    bfb_paid = {}
    for t in c.execute("SELECT match_id, amount, currency FROM office_bank_tx WHERE org_id=? AND deleted_at IS NULL AND match_kind='receipt'", (oid,)):
        t = oc_dec_fields(c, oid, "office_bank_tx", t)
        if (t["currency"] or home).upper() == home:
            bfb_paid[t["match_id"]] = abs(dec(t["amount"], "0"))
    for rc in bk_receipts(c, oid, first, _add_months(last_month, 1) + "-00"):
        g_ = bfb_paid.get(rc["node_id"]) or rc["amount"]
        put(rc["date"], "out", "actual" if rc["date"] <= today else "plan", "receipt", g_ * rc["net"] / rc["amount"] if net and rc["amount"] else g_,
            " · ".join(x for x in (rc["title"], rc["category"]) if x), node_id=rc["node_id"], category=rc["category"])
    # out: fixed costs
    for f in rk_fixed(c, oid):
        for day in rk_fixed_days(f, first, _add_months(last_month, 1) + "-00"):
            put(day, "out", "actual" if day <= today else "plan", "fixed", dec(f["amount"] if net else f["gross"]), f["label"], fixed_id=f["id"],
                repeat=f["repeat"], category=f["category"], vat_rate=f["vat_rate"])
    from .recurring import rin_cashflow
    rin_cashflow(c, oid, put, first, _add_months(last_month, 1) + "-00", today, nf)  # 2.91.0 A (#1923): in: the coming periods of invoice series (plan)
    # out: 2.92.0 A (#1925): contributions of business contracts and insurances (cashflow on) -- like a fixed cost, never copied
    from .agreements import agr_cashflow_items
    for f in agr_cashflow_items(c, oid, today):
        for day in rk_fixed_days(f, first, _add_months(last_month, 1) + "-00"):
            put(day, "out", "actual" if day <= today else "plan", "agreement", dec(f["amount"] if net else f["gross"]), f["label"],
                agreement_id=f["id"], repeat=f["repeat"], vat_rate=f["vat_rate"])
    entries.sort(key=lambda e: (e["month"], e["dir"], e["date"], e["kind"]))
    rows = []
    cum_bal = cum_res = dec(0)
    for mo in ms:
        s = {("in", "actual"): dec(0), ("in", "plan"): dec(0), ("out", "actual"): dec(0), ("out", "plan"): dec(0)}
        for e in entries:
            if e["month"] == mo:
                s[(e["dir"], e["state"])] += dec(e["amount"])
        bal = s[("in", "actual")] + s[("in", "plan")] - s[("out", "actual")] - s[("out", "plan")]
        rows.append({"month": mo, "past": mo < cur_month, "current": mo == cur_month,
                     "in": {"actual": dstr(s[("in", "actual")]), "plan": dstr(s[("in", "plan")])},
                     "out": {"actual": dstr(s[("out", "actual")]), "plan": dstr(s[("out", "plan")])}, "balance": dstr(bal)})
        if reserve_pct:  # 2.90.0 A (#1921): reserve = pct x net money in (actual + planned); free = balance so far minus reserve so far
            res = money(max(res_in.get(mo, dec(0)), dec(0)) * reserve_pct / 100)
            cum_bal, cum_res = cum_bal + bal, cum_res + res
            rows[-1].update(reserve=dstr(res), free=dstr(money(cum_bal - cum_res)))
    out = {"from": first_month, "months": months, "currency": home, "today": today, "basis": "net" if net else "gross", "rows": rows, "entries": entries,
           "tax_reserve_pct": reserve_pct}
    if cfs:  # 2.123.0 D (#2341): start balance, corrections by hand, real balances (office/cfstart.py; nothing set = as before)
        from .cfstart import cfs_apply
        cfs_apply(c, oid, out, today)
        from .cfbank import cfb_apply
        cfb_apply(c, oid, out, today)  # 2.124.0 D (#2342): the balances of the bank statements (none = as before)
    return out


@app.get("/api/office/cashflow")
def rk_cashflow_get():
    """?from=YYYY-MM (default: this month)&months=1..12 (the view offers 3 or 6; default 3)&basis=gross|net (2.67.0, #1838;
    default gross) -> rk_cashflow."""
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
    basis = request.args.get("basis") or "gross"
    if basis not in CF_BASES:
        raise BadInput(tr("Invalid value: {0}", "basis"))
    return jsonify(rk_cashflow(c, oid, fm, n, basis=basis))


@app.post("/api/office/docs/<int:did>/cashflow")
def cf8_doc_cashflow_post(did):
    """2.88.0 (#1915): {cashflow: auto|yes|no} of a quotation -> {id, cashflow, cf_chain}. Planning, not the document's content
    (not printed, not in the approval hash): the same right as editing the quotation (a member of the office area), also when
    it is sent or finalised. Logged."""
    from .docs import doc_row
    from .ledger import ofx_log
    c = db()
    uid = office_gate(c)
    oid = office_org(c, uid)
    r = doc_row(c, oid, did)
    if r["kind"] != "offer":
        raise BadInput(tr("Invalid value: {0}", "kind"))
    b = body()
    v = (b if isinstance(b, dict) else {}).get("cashflow")
    if v not in CF8_CHOICES:
        raise BadInput(tr("Invalid value: {0}", "cashflow"))
    before = r["cashflow"] or "auto"
    if v != before:
        c.execute("UPDATE office_docs SET cashflow=? WHERE id=? AND org_id=?", (v, did, oid))
        ofx_log(c, oid, "cashflow", doc_id=did, detail={"before": {"cashflow": before}, "after": {"cashflow": v}})
        bump(c)
    c.commit()
    return jsonify(id=did, cashflow=v, cf_chain=cf8_chain(c, oid, doc_row(c, oid, did)))
