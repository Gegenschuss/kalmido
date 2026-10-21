"""Office & finance (2.123.0 D, #2341): the account balance of the cash flow -- a rough orientation also when not everything
is entered in Kalmido. No bank access, never a booking of its own.

- Start balance: amount (may be negative) + day per office area (organisation or personal office). The running balance at
  the end of a month = start + money in - money out of every cash flow entry on or after that day (actual and planned,
  always gross: the account sees the gross amounts), + the corrections by hand from the day's month on. Also in the
  preview (coming months). Without a start balance the cash flow answers exactly as before.
- Corrections by hand per month: free rows "other income" / "other expense" with amount and a short note, for money
  outside Kalmido. They never change the computed values (rows[].in / out / balance stay); a month with corrections
  carries manual {in, out}, the list sits in adjust[].
- Reconciliation: optionally the real balance at the end of a month; the cash flow shows the difference to the computed
  balance (only shown).
Amounts and notes encrypted at rest (orgcrypt FIELDS). Every route: office_gate + office_org with the admin of the office
area, like the fixed costs (cashflow.py); a person without an organisation is the admin of the personal office."""
import re
from datetime import date, timedelta

from flask import jsonify

from ..core.access import Denied
from ..core.config import app
from ..core.db import body, bump, iso, local_now, now_utc, write_lock
from ..core.i18n import tr
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields
from ..core.pg import insert_id
from ..core.errors import BadInput
from .calc import dec, dstr, money
from .cashflow import DATE_RE, MONTH_RE, _add_months, _ctx

CFS_DIRS = ("in", "out")
CFS_MAX_MONTH = 50  # corrections per month
CFS_LIMIT = 10 ** 10


def cfs_amount(v, name, positive=False):
    """A money amount from a number or text ("1.234,56" / "-50"); positive = > 0 (corrections)."""
    if isinstance(v, bool) or not isinstance(v, (int, float, str)) or (isinstance(v, str) and not v.strip()):
        raise BadInput(tr("Invalid value: {0}", name))
    a = dec(v.strip() if isinstance(v, str) else v, "NaN")
    if a.is_nan() or not a.is_finite() or abs(a) >= CFS_LIMIT or (positive and a <= 0):
        raise BadInput(tr("Invalid value: {0}", name))
    return dstr(money(a))


def cfs_day(v):
    if isinstance(v, str) and DATE_RE.match(v.strip()):
        try:
            d = date.fromisoformat(v.strip())
            if d.year >= 2000 and d <= local_now().date() + timedelta(days=366):
                return d.isoformat()
        except ValueError:
            pass
    raise BadInput(tr("Invalid value: {0}", "day"))


def cfs_month(v):
    if not isinstance(v, str) or not MONTH_RE.match(v.strip()) or v.strip() < "2000-01":
        raise BadInput(tr("Invalid value: {0}", "month"))
    return v.strip()


# ---------------------------------------------------------------- the start balance
def cfs_start(c, oid):
    """{amount, day, updated_at} of office area oid or None."""
    r = c.execute("SELECT * FROM office_cf_start WHERE org_id=?", (oid,)).fetchone()
    if not r:
        return None
    d = oc_dec_fields(c, oid, "office_cf_start", r)
    if not d.get("day") or d.get("amount") in (None, ""):
        return None
    return {"amount": dstr(dec(d["amount"])), "day": d["day"], "updated_at": d["updated_at"]}


@app.get("/api/office/cashflow/start")
def cfs_start_get():
    """Office admin. {start: {amount, day, updated_at} | null, currency}."""
    from .model import office_settings
    c, uid, oid = _ctx()
    return jsonify(start=cfs_start(c, oid), currency=(office_settings(c, oid).get("currency") or "EUR").upper())


@app.put("/api/office/cashflow/start")
def cfs_start_put():
    """Office admin. {amount, day} -> {start, prev} (prev = the one before or null, for the client's undo)."""
    c, uid, oid = _ctx()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    amount, day = cfs_amount(b.get("amount"), "amount"), cfs_day(b.get("day"))
    write_lock(c, f"office_cfs_{int(oid)}")
    prev = cfs_start(c, oid)
    row = oc_enc_fields(c, oid, "office_cf_start", {"amount": amount})
    c.execute("INSERT INTO office_cf_start(org_id, amount, day, updated_by, updated_at) VALUES(?,?,?,?,?) ON CONFLICT(org_id) DO UPDATE SET "
              "amount=excluded.amount, day=excluded.day, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
              (oid, row["amount"], day, uid, iso(now_utc())))
    bump(c)
    c.commit()
    return jsonify(start=cfs_start(c, oid), prev=prev)


@app.delete("/api/office/cashflow/start")
def cfs_start_delete():
    """Office admin. Removes the start balance (the cash flow is as before it) -> {ok, prev}."""
    c, uid, oid = _ctx()
    prev = cfs_start(c, oid)
    c.execute("DELETE FROM office_cf_start WHERE org_id=?", (oid,))
    bump(c)
    c.commit()
    return jsonify(ok=True, prev=prev)


# ---------------------------------------------------------------- corrections by hand
def _adj_public(c, oid, r):
    d = oc_dec_fields(c, oid, "office_cf_adjust", r)
    return {"id": d["id"], "month": d["month"], "dir": d["dir"], "amount": dstr(dec(d["amount"])), "note": d["note"] or "", "manual": True}


def cfs_adjust(c, oid, first_month, last_month):
    rows = c.execute("SELECT * FROM office_cf_adjust WHERE org_id=? AND month>=? AND month<=? ORDER BY month, id", (oid, first_month, last_month))
    return [_adj_public(c, oid, r) for r in rows.fetchall()]


def _adj_clean(b, cur=None):
    out = {}
    if "month" in b or not cur:
        out["month"] = cfs_month(b.get("month"))
    if "dir" in b or not cur:
        if b.get("dir") not in CFS_DIRS:
            raise BadInput(tr("Invalid value: {0}", "dir"))
        out["dir"] = b["dir"]
    if "amount" in b or not cur:
        out["amount"] = cfs_amount(b.get("amount"), "amount", positive=True)
    if "note" in b or not cur:
        v = b.get("note")
        out["note"] = re.sub(r"[\x00-\x1f\x7f]", "", v).strip()[:200] if isinstance(v, str) else ""
    return out


def _adj_row(c, oid, aid):
    r = c.execute("SELECT * FROM office_cf_adjust WHERE id=? AND org_id=?", (aid, oid)).fetchone()
    if not r:
        raise Denied(404)
    return r


@app.post("/api/office/cashflow/adjust")
def cfs_adjust_post():
    """Office admin. {month YYYY-MM, dir in|out, amount > 0, note?} -> 201 the correction."""
    c, uid, oid = _ctx()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    row = _adj_clean(b)
    write_lock(c, f"office_cfs_{int(oid)}")
    if c.execute("SELECT COUNT(*) FROM office_cf_adjust WHERE org_id=? AND month=?", (oid, row["month"])).fetchone()[0] >= CFS_MAX_MONTH:
        raise BadInput(tr("Too many entries"))
    ts = iso(now_utc())
    row.update(org_id=oid, created_by=uid, created_at=ts, updated_at=ts)
    row = oc_enc_fields(c, oid, "office_cf_adjust", row)
    aid = insert_id(c, f"INSERT INTO office_cf_adjust({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    bump(c)
    c.commit()
    return jsonify(_adj_public(c, oid, _adj_row(c, oid, aid))), 201


@app.patch("/api/office/cashflow/adjust/<int:aid>")
def cfs_adjust_patch(aid):
    c, uid, oid = _ctx()
    old = _adj_public(c, oid, _adj_row(c, oid, aid))
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    row = _adj_clean(b, old)
    if row:
        row["updated_at"] = iso(now_utc())
        row = oc_enc_fields(c, oid, "office_cf_adjust", row)
        c.execute(f"UPDATE office_cf_adjust SET {','.join(k + '=?' for k in row)} WHERE id=? AND org_id=?", list(row.values()) + [aid, oid])
        bump(c)
        c.commit()
    return jsonify(_adj_public(c, oid, _adj_row(c, oid, aid)))


@app.delete("/api/office/cashflow/adjust/<int:aid>")
def cfs_adjust_delete(aid):
    """Deletes a correction; answers it as it was (the client's undo posts it again)."""
    c, uid, oid = _ctx()
    old = _adj_public(c, oid, _adj_row(c, oid, aid))
    c.execute("DELETE FROM office_cf_adjust WHERE id=? AND org_id=?", (aid, oid))
    bump(c)
    c.commit()
    return jsonify(ok=True, item=old)


# ---------------------------------------------------------------- the real balance at the end of a month
def cfs_actual(c, oid, first_month, last_month):
    out = {}
    for r in c.execute("SELECT * FROM office_cf_actual WHERE org_id=? AND month>=? AND month<=?", (oid, first_month, last_month)).fetchall():
        d = oc_dec_fields(c, oid, "office_cf_actual", r)
        if d.get("amount") not in (None, ""):
            out[d["month"]] = dstr(dec(d["amount"]))
    return out


@app.put("/api/office/cashflow/actual")
def cfs_actual_put():
    """Office admin. {month, amount} (amount null / '' = removed) -> {month, amount, prev} (prev for the client's undo)."""
    c, uid, oid = _ctx()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    mo = cfs_month(b.get("month"))
    v = b.get("amount")
    amount = None if v is None or (isinstance(v, str) and not v.strip()) else cfs_amount(v, "amount")
    write_lock(c, f"office_cfs_{int(oid)}")
    prev = cfs_actual(c, oid, mo, mo).get(mo)
    if amount is None:
        c.execute("DELETE FROM office_cf_actual WHERE org_id=? AND month=?", (oid, mo))
    else:
        row = oc_enc_fields(c, oid, "office_cf_actual", {"amount": amount})
        c.execute("INSERT INTO office_cf_actual(org_id, month, amount, updated_by, updated_at) VALUES(?,?,?,?,?) ON CONFLICT(org_id, month) DO UPDATE SET "
                  "amount=excluded.amount, updated_by=excluded.updated_by, updated_at=excluded.updated_at", (oid, mo, row["amount"], uid, iso(now_utc())))
    bump(c)
    c.commit()
    return jsonify(month=mo, amount=amount, prev=prev)


# ---------------------------------------------------------------- into the cash flow
def _flow(entries, since, month=None):
    """Money in - money out of the entries on or after day since (of one month)."""
    s = dec(0)
    for e in entries:
        if e["date"] >= since and (month is None or e["month"] == month):
            s += dec(e["amount"]) if e["dir"] == "in" else -dec(e["amount"])
    return s


def _manual(adj, month):
    return sum((dec(a["amount"]) if a["dir"] == "in" else -dec(a["amount"]) for a in adj if a["month"] == month), dec(0))


def cfs_apply(c, oid, out, today):
    """Called at the end of cashflow.rk_cashflow: adds adjust[] and per month manual {in, out} (corrections), real (the
    real balance entered); with a start balance also start {amount, day} and per month account (the running balance at
    the end of the month, from the start day's month on) and diff (real - account). Never changes a computed value."""
    from .cashflow import rk_cashflow
    rows = out["rows"]
    if not rows:
        return out
    fm, lm = rows[0]["month"], rows[-1]["month"]
    adj, real, st = cfs_adjust(c, oid, fm, lm), cfs_actual(c, oid, fm, lm), cfs_start(c, oid)
    if adj:
        out["adjust"] = adj
    for r in rows:
        mine = [a for a in adj if a["month"] == r["month"]]
        if mine:
            r["manual"] = {k: dstr(sum((dec(a["amount"]) for a in mine if a["dir"] == k), dec(0))) for k in CFS_DIRS}
        if r["month"] in real:
            r["real"] = real[r["month"]]
    if not st:
        return out
    out["start"] = {"amount": st["amount"], "day": st["day"]}
    day, dm = st["day"], st["day"][:7]
    # the account sees gross amounts: on the net basis the same window again on gross
    ents = out["entries"] if out.get("basis") != "net" else rk_cashflow(c, oid, fm, len(rows), today, "gross", cfs=False)["entries"]
    bal = dec(st["amount"])
    if dm < fm:  # the months from the start day up to the first one shown
        n, m = 0, dm
        while m < fm:
            n, m = n + 1, _add_months(m, 1)
        bal += _flow(rk_cashflow(c, oid, dm, n, today, "gross", cfs=False)["entries"], day)
        pre = cfs_adjust(c, oid, dm, _add_months(fm, -1))
        bal += sum((_manual(pre, _add_months(dm, i)) for i in range(n)), dec(0))
    for r in rows:
        if r["month"] < dm:
            continue
        bal += _flow(ents, day, r["month"]) + _manual(adj, r["month"])
        r["account"] = dstr(bal)
        if r["month"] in real:
            r["diff"] = dstr(dec(real[r["month"]]) - bal)
    return out
