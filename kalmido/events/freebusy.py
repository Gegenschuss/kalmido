"""2.155.0 B (#2077): free / busy of the people one invites, for the event editor's availability bar.

GET /api/events/freebusy?day=YYYY-MM-DD&users=1,2,3[&tz=Europe/Berlin][&skip=<event id>] answers per person ONLY time
spans of that day: {start, end ("HH:MM", local in tz), kind: busy | away} -- never a title, a place, a calendar name or
which calendar a span comes from. Who may be asked: oneself, and the people who are full members (not guests /
accounting) of an organisation one is a full member of oneself -- the colleagues one invites from the people field.
Anyone else is left out of the answer (no error, so the answer tells nothing about who exists); a person without an
organisation therefore only ever gets their own bar.
busy = timed events marked busy (an event shown as free, TRANSP:TRANSPARENT / busy=0, never counts; nor cancelled ones)
of the calendars the person sees and did not hide, events they accepted, timed events of their visible subscriptions
(the same sources as the booking page, calendars/apptbook.py apb_busy). All-day events never block (a birthday, a
reminder), as in the day plan. away = an approved absence (half days: the morning or the afternoon) or a public holiday
of the person's state (hub/abscal.py). skip = the event being edited (it should not collide with itself).
The colleagues' calendars are read as "system" (core/pg.py system_ctx) because they lie outside one's own rights; only
the merged spans leave this module. Agents get 403 (not opened for them yet)."""
import re
from datetime import date, datetime, timedelta

from flask import g, jsonify, request

from ..core.config import app
from ..core.i18n import tr
from ..core.db import db, parse_iso
from ..core.pg import system_ctx
from ..core.access import Denied, need_feat
from ..personal.timetrack import BadInput

EFB_USERS_MAX = 20


def efb_allowed(c, uid, ids):
    """The ids of `ids` uid may ask about: uid, and the full members of the organisations uid is a full member of (no
    agents, children or disabled accounts)."""
    from ..accounts.orgs import user_orgs
    from ..accounts.orgroles import user_orgs_full
    with system_ctx(c):  # memberships of other people (structure, ids only)
        mine = set(user_orgs(c, uid)) & set(user_orgs_full(c, uid))
        out = []
        for t in ids:
            if t == uid:
                out.append(t)
                continue
            u = c.execute("SELECT disabled, kid, kind FROM users WHERE id=?", (t,)).fetchone()
            if not u or u["disabled"] or u["kid"] or (u["kind"] or "user") == "agent" or not mine:
                continue
            if mine & set(user_orgs(c, t)) & set(user_orgs_full(c, t)):
                out.append(t)
    return out


def efb_spans(c, uid, day, zone, skip=None):
    """[(start minute, end minute, kind)] of person uid on day (0..1440 in zone), merged per kind. Run as system."""
    from ..events.model import ev_expand, my_cal_ids
    from ..hub.absence import abs_holidays_year
    from ..hub.abscal import abc_state
    d0 = datetime(day.year, day.month, day.day, tzinfo=zone)
    d1 = d0 + timedelta(days=1)
    lo, hi = day - timedelta(days=1), day + timedelta(days=1)
    busy, away = [], []

    def clip(s, e, out):
        a, b = max(s, d0), min(e, d1)
        if b > a:
            out.append((int((a - d0).total_seconds() // 60), int((b - d0).total_seconds() // 60)))
    cals = list(my_cal_ids(c, uid, hidden=False))
    rows = []
    if cals:
        q = ",".join("?" * len(cals))
        rows = c.execute(f"""SELECT * FROM events WHERE cal_id IN ({q}) AND deleted_at IS NULL AND busy=1 AND status<>'cancelled'
                             AND all_day=0 AND first_day<=? AND (last_day='' OR last_day>=?)""", [*cals, hi.isoformat(), lo.isoformat()]).fetchall()
    rows += c.execute("""SELECT e.* FROM events e JOIN event_attendees a ON a.event_id=e.id AND a.user_id=? WHERE a.partstat='accepted'
                         AND e.deleted_at IS NULL AND e.busy=1 AND e.status<>'cancelled' AND e.all_day=0 AND e.first_day<=?
                         AND (e.last_day='' OR e.last_day>=?)""", (uid, hi.isoformat(), lo.isoformat())).fetchall()
    seen = set()
    for r in rows:
        if r["id"] in seen or (skip and r["id"] == skip):
            continue
        seen.add(r["id"])
        for o in ev_expand(r, lo, hi):
            if not o["all_day"]:  # an occurrence moved to a whole day does not block either
                clip(o["s"], o["e"], busy)
    from ..calendars.subscriptions import CAL_ON
    if CAL_ON:
        for r in c.execute("""SELECT e.start, e."end" FROM cal_events e JOIN cal_subs s ON s.id=e.sub_id WHERE s.user_id=? AND s.visible=1
                              AND e.all_day=0 AND e.d1>=? AND e.d0<=?""", (uid, lo.isoformat(), hi.isoformat())):
            s, e = parse_iso(r[0]), parse_iso(r[1])
            if s and e:
                clip(s, e, busy)
    for r in c.execute("SELECT half_day FROM hub_absences WHERE user_id=? AND deleted_at IS NULL AND status='approved' "
                       "AND start_date<=? AND end_date>=?", (uid, day.isoformat(), day.isoformat())):
        away.append((720, 1440) if r[0] == "pm" else (0, 720) if r[0] == "am" else (0, 1440))
    if abs_holidays_year(day.year, abc_state(c, uid)).get(day.isoformat()):
        away.append((0, 1440))
    return [(a, b, "away") for a, b in efb_merge(away)] + [(a, b, "busy") for a, b in efb_merge(busy)]


def efb_merge(spans):
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def efb_hm(m):
    return "24:00" if m >= 1440 else f"{m // 60:02d}:{m % 60:02d}"


@app.get("/api/events/freebusy")
def efb_get():
    u = g.user
    if u is None:
        raise Denied(401)
    if (u["kind"] or "user") == "agent" or u["kid"]:
        raise Denied(403, tr("Agents cannot use this endpoint"))
    need_feat("events")
    a = request.args
    try:
        day = date.fromisoformat((a.get("day") or "").strip())
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "day")) from None
    raw = [x for x in (a.get("users") or "").split(",") if x.strip()]
    if not raw or len(raw) > EFB_USERS_MAX or not all(re.fullmatch(r"\d{1,12}", x.strip()) for x in raw):
        raise BadInput(tr("Invalid value: {0}", "users"))
    ids = list(dict.fromkeys(int(x) for x in raw))
    skip = None
    if a.get("skip"):
        if not re.fullmatch(r"\d{1,12}", a["skip"].strip()):
            raise BadInput(tr("Invalid value: {0}", "skip"))
        skip = int(a["skip"])
    from ..events.model import ev_zone, tz_ok
    tz = (a.get("tz") or "").strip()
    zone = ev_zone(tz if tz_ok(tz) else "")
    c, uid = db(), u["id"]
    people = []
    allowed = efb_allowed(c, uid, ids)
    with system_ctx(c):  # the colleagues' calendars lie outside my rights; only merged spans leave this block
        for t in allowed:
            people.append({"user_id": t, "slots": [{"start": efb_hm(s), "end": efb_hm(e), "kind": k}
                                                   for s, e, k in efb_spans(c, t, day, zone, skip)]})
    return jsonify(day=day.isoformat(), tz=getattr(zone, "key", ""), people=people)
