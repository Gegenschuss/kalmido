"""2.148.0 A (#2471): locking accounting periods (GoBD "Festschreibung") per month of an office area.

A locked month cannot be changed any more: no new, changed or deleted document, payment, bank match, cash entry, trip,
receipt or import with a date in it. Corrections go into an open month (a credit note / reversal dated today). Months are
locked in order only ("lock up to and including MM/YYYY" locks every earlier open month along) and never unlocked; every
lock is an entry "period_lock" in the office log (the GoBD protocol). office_period_locks holds one row per locked month;
the area is locked up to MAX(period).

period_need_open(c, oid, day) is the one check of every write path (409 with a readable reason); day may be a date,
a datetime or ISO text (only the first 7 characters count). New table only: 2.147 ignores it."""
from datetime import date, datetime

from flask import g, jsonify, request

from ..core.config import app
from ..core.i18n import N_, tr
from ..core.db import body, db, iso, local_now, now_utc
from ..core.pg import write_lock
from ..core.access import Denied
from ..personal.timetrack import BadInput
from .model import office_gate, office_org

PL_LOCKED = N_("{0} is locked (GoBD). Book corrections in an open month, e.g. as a credit note dated today.")
PL_MAX_MONTHS = 600  # 50 years in one lock call at most


def pl_month(day):
    """'YYYY-MM' of day (date, datetime, ISO text) or None."""
    if day is None or day == "":
        return None
    if isinstance(day, (date, datetime)):
        return f"{day.year:04d}-{day.month:02d}"
    s = str(day).strip()
    if len(s) < 7 or s[4] != "-" or not (s[:4] + s[5:7]).isdigit():
        return None
    return s[:7]


def pl_label(month):
    return f"{month[5:7]}/{month[:4]}"


def pl_through(c, oid):
    """The last locked month of office area oid ('YYYY-MM') or None (cached per request and area)."""
    if not oid:
        return None
    cache = g.setdefault("_pl_through", {})
    if oid not in cache:
        r = c.execute("SELECT MAX(period) AS p FROM office_period_locks WHERE org_id=?", (oid,)).fetchone()
        cache[oid] = r["p"] if r is not None else None
    return cache[oid]


def pl_is_locked(c, oid, day):
    m, t = pl_month(day), pl_through(c, oid)
    return bool(m and t and m <= t)


def period_need_open(c, oid, *days):
    """409 when any of days lies in a locked month of office area oid (None / '' are skipped). Holds the area's period
    lock shared until the commit, so a lock being written (pl_lock: exclusive) waits for this write or the other way round."""
    if not oid:
        return
    held = g.setdefault("_pl_shared", set())
    if oid not in held:
        c.execute("SELECT pg_advisory_xact_lock_shared(hashtext(?))", (f"office_period_{int(oid)}",))
        held.add(oid)
        g.setdefault("_pl_through", {}).pop(oid, None)  # read after the lock
    t = pl_through(c, oid)
    if not t:
        return
    for d in days:
        m = pl_month(d)
        if m and m <= t:
            raise Denied(409, tr(PL_LOCKED, pl_label(m)))


def _add_month(m, n=1):
    y, mo = int(m[:4]), int(m[5:7]) - 1 + n
    return f"{y + mo // 12:04d}-{mo % 12 + 1:02d}"


# where the dates of an office area live (table, date column); the first month to lock is the earliest of them
_DATED = (("office_docs", "date"), ("office_payments", "date"), ("office_bank_tx", "day"), ("office_cash_entries", "day"),
          ("office_trips", "date_from"))


def pl_first_month(c, oid):
    """The earliest month with data of the area (documents, payments, bank lines, cash entries, trips) or None."""
    best = None
    for tbl, col in _DATED:
        r = c.execute(f"SELECT MIN({col}) AS d FROM {tbl} WHERE org_id=? AND {col}<>''", (oid,)).fetchone()
        m = pl_month(r["d"]) if r is not None else None
        if m and (best is None or m < best):
            best = m
    return best


def pl_hints(c, oid, through):
    """What is still open up to and including month through (a hint list, locking stays possible):
    drafts with a date in it, receipts without amount or category, bank lines without a match."""
    end = _add_month(through) + "-01"
    out = []
    n = c.execute("SELECT COUNT(*) AS n FROM office_docs WHERE org_id=? AND locked_at IS NULL AND kind IN ('invoice','credit') "
                  "AND date<>'' AND date<?", (oid, end)).fetchone()["n"]
    if n:
        out.append({"kind": "drafts", "count": n, "text": tr("{0} invoice drafts are dated in this period", n)})
    n = c.execute("SELECT COUNT(*) AS n FROM office_bank_tx WHERE org_id=? AND day<>'' AND day<? AND match_kind IS NULL "
                  "AND deleted_at IS NULL", (oid, end)).fetchone()["n"]
    if n:
        out.append({"kind": "bank", "count": n, "text": tr("{0} bank lines are not matched", n)})
    return out


def pl_months(c, oid):
    rows = c.execute("SELECT l.period, l.locked_at, u.display_name, u.username FROM office_period_locks l "
                     "LEFT JOIN users u ON u.id=l.locked_by WHERE l.org_id=? ORDER BY l.period", (oid,)).fetchall()
    return [{"period": r["period"], "locked_at": r["locked_at"], "by": r["display_name"] or r["username"] or ""} for r in rows]


def pl_lock(c, oid, uid, through):
    """Lock every open month up to and including through (from the month after the last locked one, else from the
    earliest month with data). -> the list of newly locked months. Only finished months (before the current one)."""
    m = pl_month(through)
    if not m or not 1 <= int(m[5:7]) <= 12:
        raise BadInput(tr("Invalid value: {0}", "through"))
    today = pl_month(local_now().date())
    if m >= today:
        raise BadInput(tr("Only finished months can be locked"))
    write_lock(c, f"office_period_{int(oid)}")
    g.setdefault("_pl_through", {}).pop(oid, None)
    last = pl_through(c, oid)
    if last and m <= last:
        return []
    start = _add_month(last) if last else (pl_first_month(c, oid) or m)
    if start > m:
        start = m
    months, cur = [], start
    while cur <= m:
        months.append(cur)
        cur = _add_month(cur)
        if len(months) > PL_MAX_MONTHS:
            raise BadInput(tr("Too many months at once"))
    at = iso(now_utc())
    for p in months:
        c.execute("INSERT INTO office_period_locks(org_id, period, locked_by, locked_at) VALUES(?,?,?,?) ON CONFLICT DO NOTHING",
                  (oid, p, uid, at))
    g.setdefault("_pl_through", {})[oid] = m
    from .ledger import ofx_log
    ofx_log(c, oid, "period_lock", target="period", detail={"from": months[0], "to": months[-1], "months": len(months)})
    return months


@app.get("/api/office/periods")
def pl_get():
    """Members: {through, months: [{period, locked_at, by}], first, hints?}; ?check=YYYY-MM adds the hints for locking up
    to that month (admin)."""
    c = db()
    uid = office_gate(c)
    chk = (request.args.get("check") or "").strip()
    oid = office_org(c, uid, admin=bool(chk))
    out = {"through": pl_through(c, oid), "months": pl_months(c, oid), "first": pl_first_month(c, oid), "current": pl_month(local_now().date())}
    if chk:
        m = pl_month(chk)
        if not m:
            raise BadInput(tr("Invalid value: {0}", "check"))
        out["hints"] = pl_hints(c, oid, m)
    return jsonify(out)


@app.post("/api/office/periods/lock")
def pl_lock_post():
    """Admin: {through: 'YYYY-MM', confirm: 'MM/YYYY'} -> locks every open month up to through; confirm must repeat the
    month (the client asks the person to type it: there is no way back)."""
    c = db()
    uid = office_gate(c)
    oid = office_org(c, uid, admin=True)
    b = body()
    m = pl_month(b.get("through"))
    if not m:
        raise BadInput(tr("Invalid value: {0}", "through"))
    if (b.get("confirm") or "").strip() != pl_label(m):
        raise BadInput(tr("Please type {0} to confirm", pl_label(m)))
    months = pl_lock(c, oid, uid, m)
    c.commit()
    return jsonify(ok=True, locked=months, through=pl_through(c, oid))


def pl_ws_office(c, ws):
    """The office area of documents space ws ('o<org>' -> org, 'u<uid>' -> that person's personal office if any)."""
    if not ws or len(ws) < 2 or not ws[1:].isdigit():
        return None
    if ws[0] == "o":
        return int(ws[1:])
    r = c.execute("SELECT id FROM orgs WHERE personal_of=? LIMIT 1", (int(ws[1:]),)).fetchone()
    return r["id"] if r is not None else None


def pl_receipt_need_open(c, nid, *new_days, becoming=False):
    """409 when document nid is a receipt (or becomes one: becoming=True) whose document date or payment day - or one of
    new_days - lies in a locked month of its office area. Not a receipt / no office: nothing."""
    r = c.execute("SELECT d.ws, d.doc_date, r.paid_at, r.node_id AS rc FROM doc_meta d LEFT JOIN rc_receipts r ON r.node_id=d.node_id "
                  "WHERE d.node_id=?", (nid,)).fetchone()
    if r is None or (r["rc"] is None and not becoming):
        return
    oid = pl_ws_office(c, r["ws"])
    if oid:
        period_need_open(c, oid, r["doc_date"], r["paid_at"], *new_days)


def pl_tree_need_open(c, nid):
    """409 when file / folder nid or anything below it is a receipt of a locked month (trash, restore, move, new version)."""
    rows = c.execute("WITH RECURSIVE t(id) AS (SELECT ?::bigint UNION ALL SELECT n.id FROM fs_nodes n JOIN t ON n.parent_id=t.id) "
                     "SELECT r.node_id FROM rc_receipts r JOIN t ON t.id=r.node_id LIMIT 5000", (nid,)).fetchall()
    for r in rows:
        pl_receipt_need_open(c, r["node_id"])
