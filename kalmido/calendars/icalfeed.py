"""The subscribable ICS calendar feed of a user's tasks."""
import hmac
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from dateutil.rrule import rrulestr
from flask import jsonify, Response

from ..core.config import app, APP_NAME, PUBLIC_URL, TZ
from ..core.i18n import LANGS, tr
from ..core.db import body, db, err, inbox_default, local_now, now_utc, parse_iso, usettings
from ..accounts.session import _rate_blocked, _rate_fail, client_ip, me
from ..core.access import tvis, vis_sql
from ..tasks.validation import rr_feasible, rr_norm
from ..tasks.lifecycle import rr_count, rr_with_count


# ---------------------------------------------------------------- calendar feed (ICS subscription)
# GET /ical/<user id>.<secret>.ics — a subscribable calendar of the user's open tasks with a date (all
# visible lists, or only "mine": unassigned in my own lists + assigned to me). The token in the path is
# the only credential: this path must bypass a login proxy and never trusts the proxy header.
# Timed tasks are events with their duration (default 30 min) in the server time zone (VTIMEZONE
# included), all-day tasks all-day events (a start date makes it a range). Recurring tasks carry their
# RRULE, so calendars show every future occurrence of the open instance (completing it moves the
# series on); "repeat from completion date" tasks only show their next date. Reminders -> VALARM.
ICAL_FAIL_LIMIT = 30  # wrong tokens per client IP within FAIL_WINDOW, then 429
ICAL_MAX = 3000


def ics_text(s):
    return (str(s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n"))


def ics_fold(line):
    """RFC 5545 folding: lines of at most 75 octets, never inside a UTF-8 sequence."""
    if len(line.encode("utf-8")) <= 75:
        return line
    out, cur, n, limit = [], "", 0, 75
    for ch in line:
        k = len(ch.encode("utf-8"))
        if n + k > limit:
            out.append(cur)
            cur, n, limit = "", 0, 74  # continuation lines start with a space
        cur += ch
        n += k
    out.append(cur)
    return "\r\n ".join(out)


def ics_utc(dt):
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ics_dur(minutes):
    sign, m = ("-" if minutes < 0 else ""), abs(int(minutes))
    d, m = divmod(m, 1440)
    h, m = divmod(m, 60)
    t = (f"{h}H" if h else "") + (f"{m}M" if m else "")
    return f"{sign}P{f'{d}D' if d else ''}{'T' + t if t else ''}" if d or t else "PT0S"


def ics_vtimezone(tz, year):
    """VTIMEZONE of tz, derived from its transitions in `year` (yearly rules like the EU / US ones)."""
    key = getattr(tz, "key", "UTC")

    def off(x):
        o = int(x.utcoffset().total_seconds() // 60)
        return f"{'+' if o >= 0 else '-'}{abs(o) // 60:02d}{abs(o) % 60:02d}"
    utc0 = datetime(year, 1, 1, tzinfo=timezone.utc)
    trans, prev = [], utc0.astimezone(tz)
    for h in range(1, 366 * 24):
        cur = (utc0 + timedelta(hours=h)).astimezone(tz)
        if cur.utcoffset() != prev.utcoffset():
            for m in range(60):  # to the minute
                x = (utc0 + timedelta(hours=h - 1, minutes=m + 1)).astimezone(tz)
                if x.utcoffset() != prev.utcoffset():
                    trans.append((prev, x))
                    break
        prev = cur
    lines = ["BEGIN:VTIMEZONE", f"TZID:{key}"]
    if not trans:
        o = off(utc0.astimezone(tz))
        return lines + ["BEGIN:STANDARD", "DTSTART:19700101T000000", f"TZOFFSETFROM:{o}", f"TZOFFSETTO:{o}",
                        f"TZNAME:{utc0.astimezone(tz).tzname()}", "END:STANDARD", "END:VTIMEZONE"]
    from dateutil.rrule import rrule, YEARLY, weekdays
    for before, after in trans[:2]:
        wall = (after.astimezone(timezone.utc) + before.utcoffset()).replace(tzinfo=None)  # old wall clock
        last = (wall.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        nth = -1 if wall.day + 7 > last.day else (wall.day - 1) // 7 + 1
        wd = weekdays[wall.weekday()]
        first = rrule(YEARLY, bymonth=wall.month, byweekday=wd(nth), dtstart=datetime(1970, 1, 1, wall.hour, wall.minute))[0]
        kind = "DAYLIGHT" if after.utcoffset() > before.utcoffset() else "STANDARD"
        lines += [f"BEGIN:{kind}", f"DTSTART:{first:%Y%m%dT%H%M%S}",
                  f"RRULE:FREQ=YEARLY;BYMONTH={wall.month};BYDAY={nth}{['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'][wall.weekday()]}",
                  f"TZOFFSETFROM:{off(before)}", f"TZOFFSETTO:{off(after)}", f"TZNAME:{after.tzname()}", f"END:{kind}"]
    return lines + ["END:VTIMEZONE"]


RRULE_OK = re.compile(r"[A-Z]+=[A-Za-z0-9,+\-]+(;[A-Z]+=[A-Za-z0-9,+\-]+)*")


def ics_rrule(rep, dtstart, timed):
    """-> (rule text for the calendar or None, first occurrence). The rule is only used when dateutil can
    parse it; UNTIL becomes a UTC date-time for timed events (RFC 5545)."""
    rep = rr_norm(rep)
    if not rep or not rr_feasible(rep, dtstart.date().isoformat()):
        return None, None
    parts = []
    for p in rep.split(";"):
        k, v = p.split("=", 1)
        if k == "UNTIL":
            try:
                d = date(int(v[:4]), int(v[4:6]), int(v[6:8]))
            except ValueError:
                return None, None
            v = ics_utc(datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=TZ)) if timed else f"{d:%Y%m%d}"
        parts.append(f"{k}={v}")
    rule = ";".join(parts)
    try:
        first = next(iter(rrulestr(rule.replace("Z", "") if timed else rule, dtstart=dtstart,
                                   ignoretz=True)), None)
    except (ValueError, TypeError, StopIteration):
        return None, None
    return rule, first


def ics_event(t, s, lg, host, key, stamp):
    """VEVENT lines (1 or 2: an occurrence that does not fit its own RRULE is split off)."""
    due = date.fromisoformat(t["due"])
    timed = bool(t["due_time"])
    if timed:
        hh, mm = map(int, t["due_time"].split(":"))
        start = datetime(due.year, due.month, due.day, hh, mm)
    else:
        start = datetime(due.year, due.month, due.day)
    lname = tr("Inbox", lg=lg) if t["list_inbox"] and inbox_default(t["list_name"]) else t["list_name"]
    deep = f"{PUBLIC_URL}/#t/{t['id']}"
    desc = ([t["content"].strip()] if (t["content"] or "").strip() else []) + \
        [tr("List: {0}", lname, lg=lg)] + ([tr("Link: {0}", t["url"], lg=lg)] if t["url"] else []) + \
        [tr("Open in Kalmido: {0}", deep, lg=lg)]
    rule, first = (None, None)
    if t["repeat"] and t["repeat_from"] != "done":
        rule, first = ics_rrule(t["repeat"], start, timed)

    def when(st):
        if timed:
            en = st + timedelta(minutes=max(5, t["duration"] or 30))
            return [f"DTSTART;TZID={key}:{st:%Y%m%dT%H%M%S}", f"DTEND;TZID={key}:{en:%Y%m%dT%H%M%S}"]
        s0 = st.date()
        if t["start"] and t["start"] < t["due"]:  # timeline range: same length for every occurrence
            s0 -= due - date.fromisoformat(t["start"])
        return [f"DTSTART;VALUE=DATE:{s0:%Y%m%d}", f"DTEND;VALUE=DATE:{st.date() + timedelta(days=1):%Y%m%d}"]

    def alarms():
        if s.get("ical_alarms") == "0" or not t["reminders"]:
            return []
        out = []
        base = 0 if timed else hm_minutes(s.get("allday_time") or "09:00")
        for off in t["reminders"].split(","):
            if off.strip().isdigit():
                out += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{ics_text(t['title'])}",
                        f"TRIGGER:{ics_dur(base - int(off))}", "END:VALARM"]
        return out

    def vevent(uid, st, rr):
        prio = {5: 1, 3: 5, 1: 9}.get(t["priority"])
        return (["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp}", f"CREATED:{ics_utc(parse_iso(t['created_at']))}",
                 f"LAST-MODIFIED:{ics_utc(parse_iso(t['updated_at']))}", f"SUMMARY:{ics_text(t['title'])}"] + when(st) +
                ([f"RRULE:{rr}"] if rr else []) +
                [f"DESCRIPTION:{ics_text(chr(10).join(desc))}", f"URL:{deep}", "TRANSP:TRANSPARENT"] +
                ([f"PRIORITY:{prio}"] if prio else []) + alarms() + ["END:VEVENT"])
    uid = f"task-{t['id']}@{host}"
    if not rule:
        return vevent(uid, start, None)
    if first == start:
        return vevent(uid, start, rule)
    # the open occurrence is not on the rule's pattern (moved by hand): own event + the series after it
    cnt = rr_count(rule)
    if cnt is not None:
        if cnt <= 1:
            return vevent(uid, start, None)
        rule = rr_with_count(rule, cnt - 1)
    return vevent(uid, start, None) + (vevent(f"task-{t['id']}-series@{host}", first, rule) if first else [])


def hm_minutes(s):
    try:
        h, m = map(int, s.split(":"))
        return h * 60 + m
    except ValueError:
        return 540


def ics_build(c, u):
    uid = u["id"]
    s = usettings(c, uid)
    lg = s.get("lang") if s.get("lang") in LANGS else "en"
    where, args = (f"t.status=0 AND t.deleted_at IS NULL AND t.due IS NOT NULL AND l.archived=0 AND t.list_id IN {vis_sql()} "
                   f"AND {tvis(c, uid, 't.', write=True)}"), [uid, uid]  # 1.10.0: participants only their own tasks
    if s.get("ical_scope") == "mine":
        where += " AND ((l.owner_id=? AND (t.assignee_id IS NULL OR t.assignee_id=?)) OR t.assignee_id=?)"
        args += [uid, uid, uid]
    rows = c.execute(f"""SELECT t.*, l.name AS list_name, l.is_inbox AS list_inbox FROM tasks t JOIN lists l ON l.id=t.list_id
                         WHERE {where} ORDER BY t.due, t.id LIMIT {ICAL_MAX}""", args).fetchall()
    host = urllib.parse.urlparse(PUBLIC_URL).hostname or "kalmido"
    key = getattr(TZ, "key", "UTC")
    stamp = ics_utc(now_utc())
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Kalmido//Tasks//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             f"X-WR-CALNAME:{ics_text(APP_NAME + ' · ' + (u['display_name'] or u['username']))}",
             f"X-WR-CALDESC:{ics_text(tr('Open tasks with a date', lg=lg))}", f"X-WR-TIMEZONE:{key}",
             "REFRESH-INTERVAL;VALUE=DURATION:PT15M", "X-PUBLISHED-TTL:PT15M"]
    if any(r["due_time"] for r in rows):
        lines += ics_vtimezone(TZ, local_now().year)
    for t in rows:
        try:
            lines += ics_event(t, s, lg, host, key, stamp)
        except (ValueError, TypeError) as e:  # one broken row never breaks the whole feed
            print("ical: skipping task", t["id"], e, flush=True)
    lines.append("END:VCALENDAR")
    return "\r\n".join(ics_fold(x) for x in lines) + "\r\n"


@app.get("/ical/<token>.ics")
def ical_feed(token):
    from ..notify.alerts import aa_count
    keys = [("ical:" + client_ip(), ICAL_FAIL_LIMIT)]
    if _rate_blocked(keys):
        return Response("Too many requests\n", 429, content_type="text/plain; charset=utf-8")
    c = db()
    uid_s, _, secret = token.partition(".")
    u = None
    if uid_s.isdigit() and secret:
        r = c.execute("SELECT * FROM users WHERE id=? AND disabled=0", (int(uid_s),)).fetchone()
        if r and r["ical_token"] and hmac.compare_digest(r["ical_token"].encode(), secret.encode()):
            u = r
    if not u:
        _rate_fail(keys)
        aa_count("security", "ics", client_ip())
        return Response("Not found\n", 404, content_type="text/plain; charset=utf-8")
    return Response(ics_build(c, u), content_type="text/calendar; charset=utf-8",
                    headers={"Cache-Control": "no-cache, private", "Content-Disposition": 'inline; filename="kalmido.ics"',
                             "X-Robots-Tag": "noindex"})


def ical_url(u):
    return f"{PUBLIC_URL}/ical/{u['id']}.{u['ical_token']}.ics" if u["ical_token"] else None


@app.get("/api/ical")
def ical_info():
    u = db().execute("SELECT id, ical_token FROM users WHERE id=?", (me(),)).fetchone()
    return jsonify(url=ical_url(u))


@app.post("/api/ical")
def ical_set():
    """{action: create | rotate | off}: create keeps an existing link, rotate replaces it (the old URL
    stops working at once), off removes it."""
    a = body().get("action")
    c = db()
    u = c.execute("SELECT id, ical_token FROM users WHERE id=?", (me(),)).fetchone()
    if a == "off":
        c.execute("UPDATE users SET ical_token=NULL WHERE id=?", (me(),))
    elif a == "rotate" or (a == "create" and not u["ical_token"]):
        c.execute("UPDATE users SET ical_token=? WHERE id=?", (secrets.token_urlsafe(32), me()))
    elif a != "create":
        return err(tr("unknown"))
    c.commit()
    return jsonify(url=ical_url(c.execute("SELECT id, ical_token FROM users WHERE id=?", (me(),)).fetchone()))
