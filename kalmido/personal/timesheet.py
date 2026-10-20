"""2.125.0 B (#2119, #2120): monthly timesheets (close / approve / send back) and the person's own time zone for time tracking."""
import json
import re
from datetime import date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo, available_timezones

from flask import g, jsonify, request

from ..core.config import app, PUBLIC_URL, TZ
from ..core.db import body, bump, db, iso, now_utc, parse_iso, usettings
from ..core.i18n import tr
from ..core.access import Denied, need_time
from ..core.pg import insert_id
from ..core.schema import USER_DEFAULTS
from ..accounts.session import me


# ---------------------------------------------------------------- 2.125.0 B (#2120): the person's time zone
# usettings "tz": an IANA name (zoneinfo) or '' = the server's time zone (TZ) as before. It decides, for that person's time
# tracking only: the local day of an entry, the periods of the report / CSV / timesheet (from / to are their local dates), "today"
# and the month of the timesheet lock. Elsewhere (calendar, reminders, workload, absences, agents' default ranges) the
# server's time zone stays. A report with "All members" uses the viewer's time zone for everyone's entries.
# "time_split_midnight" (default on): an entry that runs over midnight (in that time zone) counts on each day with its share
# in the report's days, the CSV (one row per day) and the timesheet. The stored entry stays one entry; totals stay the same.
# The rounding stays per entry (rounded once as a whole); the day shares of the seconds and of the rounded seconds are split
# by the share of the elapsed time (integer, the parts add up exactly).
USER_DEFAULTS.setdefault("tz", "")
USER_DEFAULTS.setdefault("time_split_midnight", "1")
TZ_NAME_MAX = 64


@lru_cache(maxsize=1)
def tz_names():
    return frozenset(available_timezones())


@lru_cache(maxsize=128)
def tz_zone(name):
    """A stored name -> ZoneInfo; '' or unknown (e.g. removed from the system's tzdata) -> the server's TZ."""
    if not name or name not in tz_names():
        return TZ
    try:
        return ZoneInfo(name)
    except (KeyError, ValueError, OSError):
        return TZ


def tz_clean(sv):
    """The setting tz from the client -> the stored string; BadInput if it is no known IANA name."""
    from .timetrack import BadInput
    sv = (sv or "").strip()
    if sv and (len(sv) > TZ_NAME_MAX or sv not in tz_names()):
        raise BadInput(tr("Invalid value: {0}", "tz"))
    return sv


def tz_of_s(s):
    return tz_zone((s or {}).get("tz") or "")


def tz_of(c, uid):
    return tz_of_s(usettings(c, uid))


def tz_split_on(s):
    return (s or {}).get("time_split_midnight") != "0"


def tz_bounds(d1, d2, zone):
    """Local days d1..d2 (inclusive) in zone -> UTC ISO [lo, hi)."""
    d3 = d2 + timedelta(days=1)
    return iso(datetime(d1.year, d1.month, d1.day, tzinfo=zone)), iso(datetime(d3.year, d3.month, d3.day, tzinfo=zone))


def tz_split(start, end, sec, rnd, zone):
    """An entry [start, end) (aware) with its seconds / rounded seconds -> its parts per local day of zone:
    [{"day", "start", "end", "seconds", "rounded"}] (one part when it stays within a day)."""
    cuts, cur = [], start
    while cur < end and len(cuts) < 20:
        d = cur.astimezone(zone).date() + timedelta(days=1)
        nxt = min(end, datetime(d.year, d.month, d.day, tzinfo=zone))
        if nxt <= cur:
            break
        cuts.append((cur, nxt))
        cur = nxt
    if len(cuts) <= 1:
        return [{"day": start.astimezone(zone).date().isoformat(), "start": start, "end": end, "seconds": sec, "rounded": rnd}]
    span = (end - start).total_seconds()
    out, done, ps, pr = [], 0.0, 0, 0
    for a, b in cuts:
        done += (b - a).total_seconds()
        s1, r1 = int(round(sec * done / span)), int(round(rnd * done / span))
        out.append({"day": a.astimezone(zone).date().isoformat(), "start": a, "end": b, "seconds": s1 - ps, "rounded": r1 - pr})
        ps, pr = s1, r1
    return out


# ---------------------------------------------------------------- 2.125.0 B (#2119): monthly timesheets
# A person closes a month of their time tracking ("Close month"): from then on their entries that START in that month (local
# month in their time zone; an entry 31st 23:00 - 1st 01:00 belongs to the month of its start) are locked: creating, changing,
# deleting, timer start / stop with a device time in it, focus sessions becoming entries, an agent's proposal applied, "Delete all
# times of this project" (locked entries stay) -- 409 "month_closed", never 500. ONE check (tsl_check) serves every write path.
# States per person and month (table time_sheets; no row = open):
#   open      -- (again) open; after "send back" with the admin's note
#   closed    -- closed by the person; they reopen it themselves as long as nobody approved it
#   approved  -- an admin of the person's organisation approved it; only an admin of it reopens it (= send back)
# The sheet belongs to the organisation the person is in when closing (the first one, as for new objects; org_id NULL = no
# organisation: the person is their own admin, closing = locking, no approval step, they reopen it themselves). Admins of that
# organisation see the closed months of its members (and the time on the organisation's lists only, never private time),
# approve them or send them back with a note. Members get the decision, admins a closed month as a News item + push (event
# "timesheet" of the notification settings, both can be switched off). Every step is in the sheet's history (log, newest 50).
# Agents: never close or decide (a person's step); their writes into a locked month get the error code month_closed.
# 2.124 ignores the table: there the entries of a closed month are not locked (accepted for the switch-over).
TSL_STATES = ("open", "closed", "approved")
TSL_LOCKED = ("closed", "approved")
TSL_NOTE_MAX = 2000
TSL_LOG_MAX = 50
TSL_MONTH_RE = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


class TslClosed(Denied):
    """409 with the API code month_closed (api/v1.py v1_view reads v1_name)."""
    v1_name = "month_closed"

    def __init__(self, month):
        super().__init__(409, tr("The month {0} is closed. Reopen it to change its time entries.", tsl_label(month)))
        self.month = month


def tsl_label(month):
    return f"{month[5:7]}/{month[:4]}"


def tsl_month_of(when, zone):
    t = parse_iso(when) if isinstance(when, str) else when
    return t.astimezone(zone).strftime("%Y-%m")


def tsl_bounds(month, zone):
    y, m = int(month[:4]), int(month[5:7])
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return tz_bounds(date(y, m, 1), nxt - timedelta(days=1), zone)


def tsl_row(c, uid, month):
    return c.execute("SELECT * FROM time_sheets WHERE user_id=? AND month=?", (uid, month)).fetchone()


def tsl_locked_months(c, uid):
    """The months (YYYY-MM) of uid that are closed or approved."""
    return {r[0] for r in c.execute("SELECT month FROM time_sheets WHERE user_id=? AND state IN ('closed','approved')", (uid,))}


def tsl_check(c, uid, *whens, zone=None):
    """THE lock: TslClosed (409) when one of the times (aware datetimes / ISO strings; None skipped) lies in a closed month of uid."""
    whens = [w for w in whens if w]
    if not whens:
        return
    locked = tsl_locked_months(c, uid)
    if not locked:
        return
    zone = zone or tz_of(c, uid)
    for w in whens:
        m = tsl_month_of(w, zone)
        if m in locked:
            raise TslClosed(m)


def tsl_is_locked(c, uid, when):
    try:
        tsl_check(c, uid, when)
    except TslClosed:
        return True
    return False


def tsl_mark(c, uid, entries, zone=None):
    """Sets "locked" on my own entries (dicts of entry_out) in a closed month (the client hides edit / delete there)."""
    locked = tsl_locked_months(c, uid)
    if not locked:
        return entries
    zone = zone or tz_of(c, uid)
    for e in entries:
        if e.get("mine") and tsl_month_of(e["start"], zone) in locked:
            e["locked"] = True
    return entries


def tsl_locked_ids(c, rows):
    """The ids of rows (time entries with id, user_id, start) that lie in a closed month of their person."""
    out, seen = set(), {}
    for r in rows:
        u = r["user_id"]
        if u not in seen:
            lk = tsl_locked_months(c, u)
            seen[u] = (lk, tz_of(c, u) if lk else None)
        lk, zone = seen[u]
        if lk and tsl_month_of(r["start"], zone) in lk:
            out.add(r["id"])
    return out


def tsl_no_agent():
    from ..agents.core import is_agent
    if is_agent(getattr(g, "user", None)):
        raise Denied(403, tr("Not available for agent accounts"))


def tsl_admin_orgs(c, uid):
    from ..accounts.orgs import is_org_admin, user_orgs
    return [o for o in user_orgs(c, uid) if is_org_admin(c, uid, o)]


def tsl_member(c, uid, oid):
    from ..accounts.orgs import user_orgs
    return bool(oid) and oid in user_orgs(c, uid)


def tsl_clean_month(v, zone):
    v = str(v or "").strip()
    if not v:
        return now_utc().astimezone(zone).strftime("%Y-%m")
    if not TSL_MONTH_RE.fullmatch(v):
        from .timetrack import BadInput
        raise BadInput(tr("Invalid value: {0}", "month"))
    return v


def tsl_log_add(r, action, by, note="", prev=None):
    try:
        log = json.loads(r["log"] or "[]") if r else []
    except ValueError:
        log = []
    x = {"at": iso(now_utc()), "by": by, "action": action}
    if note:
        x["note"] = note[:300]
    if prev:
        x["from"] = prev
    return json.dumps((log + [x])[-TSL_LOG_MAX:], ensure_ascii=False)


def tsl_can_reopen(c, uid, r):
    """The person reopens a closed month; an approved one only without the organisation (none / left it / deleted)."""
    return bool(r) and (r["state"] == "closed" or (r["state"] == "approved" and not tsl_member(c, uid, r["org_id"])))


def tsl_out(c, r, uid):
    from ..collab.comments import user_names
    from ..accounts.orgs import _org_name
    if not r:
        return {"state": "open", "note": "", "closed_at": None, "decided_at": None, "decided_by": None, "decided_by_name": "",
                "org_id": None, "org_name": "", "log": []}
    try:
        log = json.loads(r["log"] or "[]")
    except ValueError:
        log = []
    names = user_names(c, [r["decided_by"], *[x.get("by") for x in log]])
    return {"state": r["state"], "note": r["note"], "closed_at": r["closed_at"], "decided_at": r["decided_at"],
            "decided_by": r["decided_by"], "decided_by_name": names.get(r["decided_by"], "") if r["decided_by"] else "",
            "org_id": r["org_id"], "org_name": _org_name(c, r["org_id"]) if r["org_id"] else "",
            "log": [{**x, "by_name": names.get(x.get("by"), "")} for x in log[-10:]], "user_id": uid}


def tsl_org_seconds(c, uid, month, oid):
    """Tracked seconds of uid in month on the lists of organisation oid (an admin never sees private time)."""
    lo, hi = tsl_bounds(month, tz_of(c, uid))
    r = c.execute("""SELECT COALESCE(SUM(seconds),0) FROM time_entries WHERE user_id=? AND start>=? AND start<? AND "end" IS NOT NULL
                     AND list_id IN (SELECT id FROM lists WHERE org_id=?)""", (uid, lo, hi, oid)).fetchone()
    return int(r[0] or 0)


def tsl_review(c, uid, month):
    """For admins: the closed months of the members of their organisations (all months) + the decided ones of `month`."""
    from ..collab.comments import user_names
    orgs = tsl_admin_orgs(c, uid)
    if not orgs:
        return None
    q = ",".join("?" * len(orgs))
    rows = c.execute(f"""SELECT * FROM time_sheets WHERE org_id IN ({q}) AND (state='closed' OR (month=? AND (state='approved' OR decided_by IS NOT NULL)))
                         ORDER BY month DESC, closed_at""", (*orgs, month)).fetchall()
    rows = [r for r in rows if tsl_member(c, r["user_id"], r["org_id"])][:200]
    names = user_names(c, [r["user_id"] for r in rows])
    return [{"user_id": r["user_id"], "name": names.get(r["user_id"], ""), "month": r["month"], "state": r["state"],
             "closed_at": r["closed_at"], "decided_at": r["decided_at"], "note": r["note"], "org_id": r["org_id"],
             "seconds": tsl_org_seconds(c, r["user_id"], r["month"], r["org_id"])} for r in rows]


def tsl_notify(c, rcpt, data, title_fn, msg_fn):
    """News item "tsheet" + push (event "timesheet") to rcpt."""
    from ..collab.news import news_add, notif_ok
    from ..collab.comments import collab_user, lang_of
    from ..notify.push import push_prio, push_reachable
    if not rcpt or rcpt == me():
        return
    news_add(c, rcpt, "tsheet", data=data, row="timesheet")
    s = collab_user(c, rcpt, None)
    if s and notif_ok(c, rcpt, s, "timesheet", "push") and push_reachable(c, rcpt, s):
        lg = lang_of(s)
        g.setdefault("pushes", []).append((rcpt, title_fn(lg), msg_fn(lg), f"{PUBLIC_URL}/#time", push_prio(s)))


def tsl_news_live(c, uid, data):
    """A News item "tsheet" shows while it still applies: the admin's "closed" while the month waits and they are its admin."""
    try:
        d = json.loads(data or "{}")
        who, month = int(d.get("user_id") or 0), str(d.get("month") or "")
    except (ValueError, TypeError, AttributeError):
        return False
    r = tsl_row(c, who, month) if who and month else None
    if not r:
        return False
    if d.get("act") == "closed":
        return r["state"] == "closed" and r["org_id"] in tsl_admin_orgs(c, uid) and tsl_member(c, who, r["org_id"])
    return who == uid


@app.get("/api/time/sheets")
def tsl_get():
    """?month=YYYY-MM (default: this month in my time zone) -> my sheet of that month, what I may do, the admins' review list."""
    need_time()
    tsl_no_agent()
    c, uid = db(), me()
    zone = tz_of(c, uid)
    month = tsl_clean_month(request.args.get("month"), zone)
    r = tsl_row(c, uid, month)
    st = r["state"] if r else "open"
    cur = now_utc().astimezone(zone).strftime("%Y-%m")
    return jsonify(month=month, sheet=tsl_out(c, r, uid), locked=sorted(tsl_locked_months(c, uid)),
                   can={"close": st == "open" and month <= cur, "reopen": tsl_can_reopen(c, uid, r)},
                   org=bool(tsl_admin_orgs(c, uid)) or bool(r and r["org_id"]), review=tsl_review(c, uid, month))


@app.post("/api/time/sheets")
def tsl_set():
    """{month, action: close | reopen} -- my own month."""
    from ..accounts.orgs import ws_obj_default
    from ..collab.comments import user_names
    need_time()
    tsl_no_agent()
    c, uid, b = db(), me(), body()
    zone = tz_of(c, uid)
    month = tsl_clean_month(b.get("month"), zone)
    act = b.get("action")
    if act not in ("close", "reopen"):
        raise Denied(400, tr("Invalid value: {0}", "action"))
    r = tsl_row(c, uid, month)
    st, ts = (r["state"] if r else "open"), iso(now_utc())
    if act == "close":
        if st != "open":
            raise Denied(409, tr("This month is already closed"))
        if month > now_utc().astimezone(zone).strftime("%Y-%m"):
            raise Denied(400, tr("A month in the future cannot be closed"))
        run = c.execute("SELECT start FROM time_entries WHERE user_id=? AND \"end\" IS NULL", (uid,)).fetchone()
        if run and tsl_month_of(run["start"], zone) == month:
            raise Denied(409, tr("Stop the running timer first"))
        oid = ws_obj_default(c, uid)
        if r:
            c.execute("UPDATE time_sheets SET state='closed', org_id=?, closed_at=?, decided_by=NULL, decided_at=NULL, note='', log=?, updated_at=? WHERE id=?",
                      (oid, ts, tsl_log_add(r, "close", uid), ts, r["id"]))
        else:
            insert_id(c, """INSERT INTO time_sheets(org_id,user_id,month,state,closed_at,note,log,created_at,updated_at)
                            VALUES(?,?,?,'closed',?,'',?,?,?)""", (oid, uid, month, ts, tsl_log_add(None, "close", uid), ts, ts))
        if oid:
            who = user_names(c, [uid]).get(uid, "?")
            for (aid,) in c.execute("SELECT user_id FROM org_members WHERE org_id=? AND role='admin'", (oid,)).fetchall():
                tsl_notify(c, aid, {"act": "closed", "user_id": uid, "month": month},
                           lambda lg: tr("Timesheet closed", lg=lg), lambda lg: tr("{0} closed {1} and waits for your approval", who, tsl_label(month), lg=lg))
    else:
        if not tsl_can_reopen(c, uid, r):
            raise Denied(403 if r and r["state"] == "approved" else 409,
                         tr("Only an admin of the organisation can reopen an approved month") if r and r["state"] == "approved"
                         else tr("This month is open"))
        c.execute("UPDATE time_sheets SET state='open', log=?, updated_at=? WHERE id=?", (tsl_log_add(r, "reopen", uid), ts, r["id"]))
    bump(c)
    c.commit()
    return jsonify(ok=True, month=month, sheet=tsl_out(c, tsl_row(c, uid, month), uid))


@app.post("/api/time/sheets/decide")
def tsl_decide():
    """Admins of the sheet's organisation: {user_id, month, action: approve | return | unapprove | restore, note?}.
    unapprove (Undo of approve) = closed again; restore (Undo of my send back) = the state before it."""
    from ..collab.comments import user_names
    need_time()
    tsl_no_agent()
    c, uid, b = db(), me(), body()
    act, note = b.get("action"), str(b.get("note") or "").strip()[:TSL_NOTE_MAX]
    if act not in ("approve", "return", "unapprove", "restore"):
        raise Denied(400, tr("Invalid value: {0}", "action"))
    try:
        who = int(b.get("user_id"))
    except (TypeError, ValueError):
        raise Denied(404) from None
    month = str(b.get("month") or "")
    if not TSL_MONTH_RE.fullmatch(month):
        raise Denied(400, tr("Invalid value: {0}", "month"))
    r = tsl_row(c, who, month)
    if not r or not r["org_id"] or not tsl_member(c, who, r["org_id"]) or not tsl_member(c, uid, r["org_id"]):
        raise Denied(404)  # no sheet, a private one or another organisation's: nothing to see
    if r["org_id"] not in tsl_admin_orgs(c, uid):
        raise Denied(403, tr("Only an admin of the organisation can approve timesheets"))
    st, ts = r["state"], iso(now_utc())
    if act == "approve":
        if st != "closed":
            raise Denied(409, tr("Only a closed month can be approved"))
        c.execute("UPDATE time_sheets SET state='approved', decided_by=?, decided_at=?, note=?, log=?, updated_at=? WHERE id=?",
                  (uid, ts, note, tsl_log_add(r, "approve", uid, note), ts, r["id"]))
    elif act == "return":
        if st not in TSL_LOCKED:
            raise Denied(409, tr("This month is open"))
        c.execute("UPDATE time_sheets SET state='open', decided_by=?, decided_at=?, note=?, log=?, updated_at=? WHERE id=?",
                  (uid, ts, note, tsl_log_add(r, "return", uid, note, prev=st), ts, r["id"]))
    elif act == "unapprove":
        if st != "approved":
            raise Denied(409, tr("This month is not approved"))
        c.execute("UPDATE time_sheets SET state='closed', decided_by=NULL, decided_at=NULL, note='', log=?, updated_at=? WHERE id=?",
                  (tsl_log_add(r, "unapprove", uid), ts, r["id"]))
    else:
        try:
            last = (json.loads(r["log"] or "[]") or [{}])[-1]
        except ValueError:
            last = {}
        if st != "open" or last.get("action") != "return" or last.get("by") != uid or last.get("from") not in TSL_LOCKED:
            raise Denied(409, tr("This step can no longer be undone"))
        c.execute("UPDATE time_sheets SET state=?, note='', log=?, updated_at=? WHERE id=?",
                  (last["from"], tsl_log_add(r, "restore", uid), ts, r["id"]))
    if act in ("approve", "return"):
        actor = user_names(c, [uid]).get(uid, "?")
        lab = tsl_label(month)
        tsl_notify(c, who, {"act": act, "user_id": who, "month": month, "note": note[:300]},
                   lambda lg: tr("Timesheet approved", lg=lg) if act == "approve" else tr("Timesheet sent back", lg=lg),
                   lambda lg: (tr("{0} approved your timesheet {1}", actor, lab, lg=lg) if act == "approve"
                               else tr("{0} sent your timesheet {1} back", actor, lab, lg=lg)) + (" · " + note[:200] if note else ""))
    bump(c)
    c.commit()
    return jsonify(ok=True, review=tsl_review(c, uid, month))
