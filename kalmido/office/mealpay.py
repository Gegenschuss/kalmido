"""2.603.0 (#4927): an entertainment receipt as the proof of its payment -- the bank booking, cash book entry or card position
that paid the meal (office_meals.pay_kind / pay_id). With the basis "bank and cash" of the income statement
(office/euerbasis.py) the meal counts only through that line and gives it the 70 / 30 split (books.bk_meals_strict): no second
expense. One meal per line; the link is bookkeeping, so it may change on an approved (locked) meal, but not while the line lies
in a locked month (GoBD).
Every route: the office admin (office_ctx_admin, like the bank) and the meal readable for the person (meals._meal); a line of
another office area 404."""
from datetime import date, timedelta

from flask import jsonify, request

from ..core.access import Denied
from ..core.config import app
from ..core.db import body, bump, local_now
from ..core.errors import BadInput
from ..core.i18n import tr
from ..core.orgcrypt import oc_dec_fields
from ..core.pg import write_lock
from .calc import dec, dstr, money
from .ledger import ofx_log
from .meals import _meal, bw_calc, _j
from .model import office_ctx_admin as _ctx
from .periodlock import period_need_open

MP_KINDS = ("bank", "cash", "card")
MP_WINDOW = 45  # days around the meal for the offered lines
MP_MAX = 30


def mp_line(c, oid, kind, lid):
    """(day, amount paid out as Decimal > 0, text) of a line of office area oid; 404 when it is none of this area / no money out."""
    if kind == "bank":
        r = c.execute("SELECT * FROM office_bank_tx WHERE id=? AND org_id=? AND deleted_at IS NULL", (lid, oid)).fetchone()
        if r is not None:
            d = oc_dec_fields(c, oid, "office_bank_tx", r)
            a = money(dec(d["amount"], "0"))
            if a < 0:
                return d["day"], -a, d.get("counterpart") or d.get("purpose") or ""
    elif kind == "cash":
        r = c.execute("SELECT * FROM office_cash_entries WHERE id=? AND org_id=? AND dir='out' AND storno_of IS NULL", (lid, oid)).fetchone()
        if r is not None:
            return r["day"], money(dec(r["amount"], "0")), oc_dec_fields(c, oid, "office_cash_entries", {"text": r["text"]})["text"] or ""
    elif kind == "card":
        r = c.execute("SELECT l.* FROM office_cc_lines l JOIN office_cc_statements s ON s.id=l.statement_id WHERE l.id=? AND l.org_id=? "
                      "AND s.deleted_at IS NULL", (lid, oid)).fetchone()
        if r is not None:
            d = oc_dec_fields(c, oid, "office_cc_lines", r)
            a = money(dec(d["amount"], "0"))
            if a > 0:
                return d["day"], a, d.get("merchant") or ""
    raise Denied(404)


def _taken(c, oid, mid=None):
    return {(r[0], r[1]) for r in c.execute("SELECT pay_kind, pay_id FROM office_meals WHERE org_id=? AND pay_kind<>'' AND deleted_at IS NULL AND id<>?",
                                            (oid, mid or 0))}


def mp_candidates(c, oid, m):
    """The lines that may have paid meal row m: money out within MP_WINDOW days, not taken by another meal, closest amount first."""
    x = oc_dec_fields(c, oid, "office_meals", {"amounts": m["amounts"], "tip": m["tip"]})  # encrypted at rest
    gross = dec(bw_calc(_j(x.get("amounts"), []), x.get("tip"))["gross"])
    try:
        d = date.fromisoformat(m["date"])
    except (TypeError, ValueError):
        d = local_now().date()
    d0, d1 = (d - timedelta(days=MP_WINDOW)).isoformat(), (d + timedelta(days=MP_WINDOW)).isoformat()
    taken, out = _taken(c, oid, m["id"]), []
    for r in c.execute("SELECT id FROM office_bank_tx WHERE org_id=? AND deleted_at IS NULL AND day>=? AND day<=? ORDER BY day", (oid, d0, d1)).fetchall():
        out.append(("bank", r[0]))
    for r in c.execute("SELECT id FROM office_cash_entries WHERE org_id=? AND dir='out' AND storno_of IS NULL AND day>=? AND day<=? ORDER BY day", (oid, d0, d1)).fetchall():
        out.append(("cash", r[0]))
    for r in c.execute("SELECT l.id FROM office_cc_lines l JOIN office_cc_statements s ON s.id=l.statement_id WHERE l.org_id=? AND s.deleted_at IS NULL "
                       "AND l.day>=? AND l.day<=? ORDER BY l.day", (oid, d0, d1)).fetchall():
        out.append(("card", r[0]))
    rows = []
    for k, i in out:
        if (k, i) in taken:
            continue
        try:
            day, a, txt = mp_line(c, oid, k, i)
        except Denied:
            continue  # money in, a credit on the card
        rows.append({"kind": k, "id": i, "day": day, "amount": dstr(a), "text": txt, "_d": abs(a - gross), "_t": abs((date.fromisoformat(day) - d).days) if day else 999})
    rows.sort(key=lambda x: (x["_d"], x["_t"]))
    return [{k: v for k, v in x.items() if k[0] != "_"} for x in rows[:MP_MAX]]


def mp_current(c, oid, m):
    if not m["pay_kind"] or not m["pay_id"]:
        return None
    try:
        day, a, txt = mp_line(c, oid, m["pay_kind"], m["pay_id"])
    except Denied:
        return {"kind": m["pay_kind"], "id": m["pay_id"], "gone": True}
    return {"kind": m["pay_kind"], "id": m["pay_id"], "day": day, "amount": dstr(a), "text": txt}


@app.get("/api/office/meals/<int:mid>/payment")
def mp_get(mid):
    """Office admin. -> {current: {kind, id, day, amount, text} | {kind, id, gone} | None, candidates: [...]}."""
    c, uid, oid = _ctx()
    m = _meal(c, oid, mid, mode="read")
    return jsonify({"current": mp_current(c, oid, m), "candidates": mp_candidates(c, oid, m) if request.args.get("candidates") != "0" else []})


@app.put("/api/office/meals/<int:mid>/payment")
def mp_put(mid):
    """Office admin. {kind: bank|cash|card, id} links the line, {kind: null} takes the link off -> {current}. 409: the line has
    another meal, or the line (old or new) lies in a locked month."""
    c, uid, oid = _ctx()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    write_lock(c, f"office_meal_pay_{oid}")
    m = _meal(c, oid, mid, mode="read")
    kind = b.get("kind")
    old_day = None
    if m["pay_kind"] and m["pay_id"]:
        try:
            old_day = mp_line(c, oid, m["pay_kind"], m["pay_id"])[0]
        except Denied:
            pass
    if kind in (None, ""):
        period_need_open(c, oid, old_day)
        c.execute("UPDATE office_meals SET pay_kind='', pay_id=NULL WHERE id=? AND org_id=?", (mid, oid))
    else:
        if kind not in MP_KINDS:
            raise BadInput(tr("Invalid value: {0}", "kind"))
        lid = b.get("id")
        if not isinstance(lid, int) or isinstance(lid, bool):
            raise BadInput(tr("Invalid value: {0}", "id"))
        day = mp_line(c, oid, kind, lid)[0]
        if (kind, lid) in _taken(c, oid, mid):
            raise Denied(409, tr("This booking is the proof of another entertainment receipt"))
        period_need_open(c, oid, old_day, day)
        c.execute("UPDATE office_meals SET pay_kind=?, pay_id=? WHERE id=? AND org_id=?", (kind, lid, mid, oid))
    ofx_log(c, oid, "update", target="meals", detail={"meal": mid, "pay": kind or None})
    bump(c)
    c.commit()
    m = _meal(c, oid, mid, mode="read")
    return jsonify({"current": mp_current(c, oid, m)})
