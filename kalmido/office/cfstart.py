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

from ..core.access import Denied, live_sql
from ..core.config import app
from ..core.db import body, bump, iso, local_now, now_utc, write_lock
from ..core.i18n import N_, tr
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields
from ..core.pg import insert_id
from ..core.errors import BadInput
from .calc import dec, dstr, money
from .cashflow import DATE_RE, MONTH_RE, _add_months, _ctx
from .model import office_settings  # 2.369.5 (#2517): pulled up from functions
from .otrash import OTB_UNDO, otb_put  # 2.567.0 (#4707): the start balance goes into the office trash
from .okern import ofk_register, ofk_trash  # 2.905.0 (#5414): a correction goes into the core's trash

CFS_TRASH_START, CFS_TRASH_ADJ = "cf_start", "cf_adjust"  # 2.567.0 (#4707): their kinds in the office trash (the app's names)
OTB_UNDO[CFS_TRASH_START] = _ctx  # the toast's undo: the office admin, as deleting it
# 2.905.0 (#5414): a correction lies in the core's trash (kind oadjust; toast's undo POST /api/office/trash/core/oadjust/<id>/restore?undo=1).
# The start balance stays on the office trash: office_cf_start has no id (one row per office, key org_id), the core's trash needs one.
CFS_ADJ_KIND = "oadjust"
ofk_register(CFS_ADJ_KIND, "office_cf_adjust", N_("Correction"), "cashflow", need="edit",
             view={"kind": CFS_TRASH_ADJ, "label": lambda c, oid, row: row.get("month") or "", "ctx": _ctx})
from .cashflow import rk_cashflow  # 2.369.5 (#2517): pulled up from functions
from .owrite import ow_history_answer, ow_kind, ow_write  # 2.567.0 D (#4711): the corrections save through the core's write layer

ow_kind("office_cf_adjust", "office_cf_adjust")

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
    """Office admin. Removes the start balance (the cash flow is as before it) -> {ok, prev, trash_id}. 2.567.0 (#4707): a
    copy goes into the office trash first (the undo: POST /api/office/trash/undo/cf_start/<trash_id>); none set: trash_id null."""
    c, uid, oid = _ctx()
    write_lock(c, f"office_cfs_{int(oid)}")
    prev = cfs_start(c, oid)
    tid = otb_put(c, oid, uid, CFS_TRASH_START, "office_cf_start", oid, (prev or {}).get("day") or "", key="org_id") if prev else None  # label: the day (the amount is sealed)
    c.execute("DELETE FROM office_cf_start WHERE org_id=?", (oid,))
    bump(c)
    c.commit()
    return jsonify(ok=True, prev=prev, trash_id=tid)


# ---------------------------------------------------------------- corrections by hand
def _adj_public(c, oid, r):
    d = oc_dec_fields(c, oid, "office_cf_adjust", r)
    return {"id": d["id"], "month": d["month"], "dir": d["dir"], "amount": dstr(dec(d["amount"])), "note": d["note"] or "", "manual": True,
            "updated_at": d.get("updated_at")}  # 2.560.0 C (#4700): the version the dialog sends back


def cfs_adjust(c, oid, first_month, last_month):
    rows = c.execute(f"SELECT * FROM office_cf_adjust WHERE org_id=? AND month>=? AND month<=? AND {live_sql()} ORDER BY month, id", (oid, first_month, last_month))
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
    r = c.execute(f"SELECT * FROM office_cf_adjust WHERE id=? AND org_id=? AND {live_sql()}", (aid, oid)).fetchone()  # 2.905.0 (#5414): the trash = 404
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
    if c.execute(f"SELECT COUNT(*) FROM office_cf_adjust WHERE org_id=? AND month=? AND {live_sql()}", (oid, row["month"])).fetchone()[0] >= CFS_MAX_MONTH:
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
    """2.567.0 D (#4711): through ow_write (409 with the correction under "current", only the fields sent, history)."""
    c, uid, oid = _ctx()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    ow_write(c, uid, "office_cf_adjust", aid, b, lambda c, b, cur: _adj_clean(b, cur), oid=oid,
             where=f"id=? AND org_id=? AND {live_sql()}",  # 2.905.0 (#5414): one in the trash is not saved (404)
             dec=lambda c, r: oc_dec_fields(c, oid, "office_cf_adjust", r), enc=lambda c, v: oc_enc_fields(c, oid, "office_cf_adjust", v),
             lock=f"office_cf_adjust-{int(aid)}",  # the same lock as the delete (#4707)
             public=lambda c, cur: _adj_public(c, oid, _adj_row(c, oid, aid)))
    c.commit()
    return jsonify(_adj_public(c, oid, _adj_row(c, oid, aid)))


@app.get("/api/office/cashflow/adjust/<int:aid>/history")
def cfs_adjust_history(aid):
    """2.570.0 (#4783): the history (office/owrite.py ow_history) with the rights of the save route."""
    c, uid, oid = _ctx()
    _adj_row(c, oid, aid)
    return ow_history_answer(c, "office_cf_adjust", aid, oid)


@app.delete("/api/office/cashflow/adjust/<int:aid>")
def cfs_adjust_delete(aid):
    """Deletes a correction; answers it as it was and 2.905.0 (#5414) where it lies in the core's trash (trash = {kind, id}:
    the client's undo POST /api/office/trash/core/oadjust/<id>/restore?undo=1; label in the trash: the month)."""
    c, uid, oid = _ctx()
    write_lock(c, f"office_cf_adjust-{int(aid)}")
    old = _adj_public(c, oid, _adj_row(c, oid, aid))
    ofk_trash(c, uid, CFS_ADJ_KIND, aid)  # 2.905.0 (#5414): the core's trash (deleted_at), an undo step of the person
    c.commit()
    return jsonify(ok=True, item=old, trash={"kind": CFS_ADJ_KIND, "id": aid})


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
