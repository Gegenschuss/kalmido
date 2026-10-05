"""Events (module "events"): calendars, rights, validation, repeat expansion, attendees, reminders, the family migration."""
import json
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from dateutil.rrule import rrulestr
from flask import has_request_context

from ..core.config import PUBLIC_URL, TZ
from ..core.i18n import N_, short_day, tr
from ..core.db import bump, gset, gsetting, iso, iso_ms, now_utc, usettings
from ..accounts.session import me
from ..core.access import collab_all, Denied, task_visible
from ..core.pages import valid_url
from ..tasks.validation import (
    as_int, clean_reminders, rr_feasible, rr_norm, rr_problem, valid_date, valid_hm,
)
from ..collab.comments import user_names
from ..personal.timetrack import BadInput


# ---------------------------------------------------------------- 2.21.0 (#659): events
# Real appointments next to the tasks, in the same database. A person has calendars (ev_cals: name, colour), shares
# them like lists (ev_cal_members: view = read, edit = change events; the owner manages), and every calendar is a CalDAV
# collection of VEVENTs (events/dav.py) next to the task lists (VTODO), so the phone's calendar app syncs it directly.
# An event: title, from - to in the local wall time of its time zone (tz, '' = the server's; all day: dates, end
# exclusive like iCalendar), location, notes, repeat rule (RRULE) with left-out occurrences (exdates) and changed ones
# (overrides: {rid, title, start, end, ...} per original start), reminders (minutes before the start), status, busy,
# attendees (a person of this server, a contact or an e-mail address, each with a reply), a linked task ("preparation").
# Rights: the calendar's role; an invited PERSON sees only that one event (read, own reply), never the calendar.
# Occurrences are expanded per visible range (GET /api/calendars/events, the API), never stored.
EV_CALS_MAX = 50              # own calendars per person
EV_PER_CAL = 20000
EV_TITLE_MAX, EV_LOC_MAX, EV_DESC_MAX = 500, 500, 20000
EV_ATT_MAX = 100
EV_OCC_CAP = 2000             # occurrences per event and request
EV_RANGE_DAYS = 400
EV_SPAN_DAYS = 366 * 3        # longest single event
EV_STATUS = ("confirmed", "tentative", "cancelled")
EV_PARTSTAT = ("needs-action", "accepted", "declined", "tentative")
EV_ROLES = ("view", "edit")
EV_COLORS = ("#6d8cff", "#2dd4bf", "#f5b041", "#f87171", "#c084fc", "#4ade80", "#f472b6", "#94a3b8")
EV_PURGE_DAYS = 30            # deleted events stay restorable this long
WALL_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


def events_on(c, uid):
    return "events" in (usettings(c, uid).get("features") or "").split(",")


def ev_zone(name):
    if not name:
        return TZ
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return TZ


def tz_ok(name):
    if not isinstance(name, str) or len(name) > 64 or not re.fullmatch(r"[A-Za-z0-9_+\-/]*", name):
        return False
    if not name:
        return True
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return False


def wall(s):
    """'YYYY-MM-DDTHH:MM' -> naive datetime (None when invalid)."""
    if not isinstance(s, str) or not WALL_RE.fullmatch(s) or not valid_date(s[:10]) or not valid_hm(s[11:]):
        return None
    return datetime.fromisoformat(s)


def wall_s(dt):
    return dt.strftime("%Y-%m-%dT%H:%M")


# ---- calendars and rights
def ev_role(c, uid, cal):
    """owner | edit | view | None of uid for the calendar row (members only while collaboration is on)."""
    if cal is None:
        return None
    if cal["owner_id"] == uid:
        return "owner"
    if not collab_all() or c.execute("SELECT disabled FROM users WHERE id=?", (cal["owner_id"],)).fetchone()[0]:
        return None
    r = c.execute("SELECT role FROM ev_cal_members WHERE cal_id=? AND user_id=?", (cal["id"], uid)).fetchone()
    return r[0] if r else None


def can_write(role):
    return role in ("owner", "edit")


def need_evcal(c, cid, write=False, manage=False, uid=None):
    uid = uid or me()
    cal = c.execute("SELECT * FROM ev_cals WHERE id=?", (cid,)).fetchone()
    role = ev_role(c, uid, cal)
    if not role:
        raise Denied(404)
    if manage and role != "owner":
        raise Denied(403, tr("Only the owner of the calendar can do this"))
    if write and not can_write(role):
        raise Denied(403, tr("You can only read this calendar"))
    return cal, role


def my_cal_ids(c, uid, hidden=True):
    """{calendar id: role} of the calendars uid sees (hidden=False: without the ones uid hid)."""
    out = {r[0]: "owner" for r in c.execute("SELECT id FROM ev_cals WHERE owner_id=?", (uid,))}
    if collab_all():
        for r in c.execute("SELECT m.cal_id, m.role, m.hidden FROM ev_cal_members m JOIN ev_cals k ON k.id=m.cal_id "
                           "JOIN users u ON u.id=k.owner_id WHERE m.user_id=? AND u.disabled=0", (uid,)):
            if hidden or not r["hidden"]:
                out.setdefault(r[0], r[1])
    if not hidden:
        hid = set(json.loads(usettings(c, uid).get("evcals_hidden") or "[]") or [])
        out = {k: v for k, v in out.items() if k not in hid}
    return out


def cal_public(c, r, uid, names=None):
    role = ev_role(c, uid, r)
    d = {"id": r["id"], "name": r["name"], "color": r["color"], "description": r["description"], "owner_id": r["owner_id"],
         "role": role, "sort": r["sort"]}
    if names is not None:
        d["owner_name"] = names.get(r["owner_id"], "?")
    if role == "owner":
        d["members"] = [{"user_id": m["user_id"], "role": m["role"]} for m in
                        c.execute("SELECT user_id, role FROM ev_cal_members WHERE cal_id=? ORDER BY added_at", (r["id"],))]
    return d


def cals_for(c, uid):
    ids = my_cal_ids(c, uid)
    if not ids:
        return []
    q = ",".join("?" * len(ids))
    rows = c.execute(f"SELECT * FROM ev_cals WHERE id IN ({q}) ORDER BY owner_id!=?, sort, id", [*ids, uid]).fetchall()
    names = user_names(c, [r["owner_id"] for r in rows])
    hid = set(json.loads(usettings(c, uid).get("evcals_hidden") or "[]") or [])
    return [{**cal_public(c, r, uid, names), "hidden": r["id"] in hid} for r in rows]


def ev_next_color(c, uid):
    used = [r[0] for r in c.execute("SELECT color FROM ev_cals WHERE owner_id=?", (uid,))]
    return next((x for x in EV_COLORS if x not in used), EV_COLORS[len(used) % len(EV_COLORS)])


def cal_fields(b, create=False):
    out = {}
    if "name" in b or create:
        n = b.get("name")
        if not isinstance(n, str) or not n.strip():
            raise BadInput(tr("Name missing"))
        out["name"] = re.sub(r"[\x00-\x1f\x7f]", " ", n).strip()[:100]
    if "color" in b:
        v = b["color"]
        if not isinstance(v, str) or not (v == "" or re.fullmatch(r"#[0-9a-fA-F]{6}", v)):
            raise BadInput(tr("Invalid value: {0}", tr("Color")))
        out["color"] = v.lower()
    if "description" in b:
        if not isinstance(b["description"], str):
            raise BadInput(tr("Invalid value: {0}", "description"))
        out["description"] = b["description"][:2000]
    return out


def cal_create(c, uid, b):
    f = cal_fields(b, True)
    if c.execute("SELECT COUNT(*) FROM ev_cals WHERE owner_id=?", (uid,)).fetchone()[0] >= EV_CALS_MAX:
        raise Denied(409, tr("At most {0} calendars", EV_CALS_MAX))
    ts = iso_ms(now_utc())
    srt = (c.execute("SELECT MAX(sort) FROM ev_cals WHERE owner_id=?", (uid,)).fetchone()[0] or 0) + 1
    return c.execute("INSERT INTO ev_cals(owner_id,name,color,description,sort,created_at,changed_at) VALUES(?,?,?,?,?,?,?)",
                     (uid, f["name"], f.get("color") or ev_next_color(c, uid), f.get("description", ""), srt, ts, ts)).lastrowid


def default_cal(c, uid, create=True):
    """The person's first own calendar (created as "Calendar" when there is none)."""
    from ..core.i18n import lang
    r = c.execute("SELECT id FROM ev_cals WHERE owner_id=? ORDER BY sort, id LIMIT 1", (uid,)).fetchone()
    if r:
        return r[0]
    if not create:
        return None
    return cal_create(c, uid, {"name": tr("Calendar", lg=lang(c, uid))})


def cal_touch(c, cid):
    c.execute("UPDATE ev_cals SET changed_at=? WHERE id=?", (iso_ms(now_utc()), cid))


def cal_member_set(c, cid, uid, role):
    from ..collab.news import news_add
    from ..agents.admin import personal_agent_foreign
    if not collab_all():
        raise Denied(409, tr("Collaboration is turned off on this server"))
    if role not in EV_ROLES:
        raise BadInput(tr("Invalid value: {0}", "role"))
    u = c.execute("SELECT id FROM users WHERE id=? AND disabled=0", (uid,)).fetchone()
    cal = c.execute("SELECT * FROM ev_cals WHERE id=?", (cid,)).fetchone()
    if not u or uid == cal["owner_id"] or personal_agent_foreign(c, uid, me()):
        raise Denied(404, tr("unknown user"))
    old = c.execute("SELECT role FROM ev_cal_members WHERE cal_id=? AND user_id=?", (cid, uid)).fetchone()
    if old:
        c.execute("UPDATE ev_cal_members SET role=? WHERE cal_id=? AND user_id=?", (role, cid, uid))
    else:
        c.execute("INSERT INTO ev_cal_members(cal_id,user_id,role,added_at) VALUES(?,?,?,?)", (cid, uid, role, iso(now_utc())))
        news_add(c, uid, "evshare", data={"cal_id": cid, "name": cal["name"], "role": role}, row="share")
    cal_touch(c, cid)


# ---- validation of an event body (web + API)
EV_KEYS = ("title", "location", "description", "all_day", "start", "end", "tz", "rrule", "exdates", "reminders", "status",
           "busy", "url", "task_id", "attendees", "cal_id")


def _txt(b, k, n, single=True):
    v = b.get(k)
    if v is None:
        return ""
    if not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", k))
    v = v.replace("\r\n", "\n").replace("\x00", "")
    if single:
        v = one_line(v)
    return v[:n]


def one_line(v):
    """A one-line field (title, location): line breaks become ", " (an address from a phone), other control characters a space."""
    v = re.sub(r"\s*\n+\s*", ", ", str(v or "").replace("\r", "\n").strip())
    return re.sub(r"[\x00-\x1f\x7f]", " ", v).strip()


def rule_local(rule, zone, all_day=False):
    """RRULE with UNTIL as a UTC date-time (what clients send next to a TZID) -> UNTIL in the event's local wall time
    (how Kalmido stores it; rule_out() writes it as UTC again). All day: the date as it is (floating). A value that cannot
    be converted stays as it came (rr_problem refuses it)."""
    parts = []
    for p in (rule or "").split(";"):
        k, _, v = p.partition("=")
        if k == "UNTIL" and re.fullmatch(r"\d{8}T\d{6}Z", v):
            if all_day:
                v = v[:8]
            else:
                try:
                    v = datetime.strptime(v, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).astimezone(zone).strftime("%Y%m%dT%H%M%S")
                except (ValueError, OverflowError):
                    pass
        parts.append(f"{k}={v}" if p else p)
    return ";".join(parts)


def ev_fields(c, uid, b, old=None):
    """A request body -> the stored columns of an event (all of them for a new one: old None). BadInput when invalid."""
    f = {}
    o = dict(old) if old is not None else {}
    if old is None or "title" in b:
        f["title"] = _txt(b, "title", EV_TITLE_MAX) or (tr("(no title)") if old is None and "title" not in b else "")
        if not f["title"]:
            raise BadInput(tr("Title missing"))
    for k, n in (("location", EV_LOC_MAX), ("description", EV_DESC_MAX)):
        if k in b or old is None:
            f[k] = _txt(b, k, n, single=(k == "location"))
    if "tz" in b or old is None:
        tz = b.get("tz") or ""
        if not tz_ok(tz):
            raise BadInput(tr("Invalid value: {0}", "tz"))
        f["tz"] = "" if tz == getattr(TZ, "key", "") else tz
    all_day = o.get("all_day", 0)
    if "all_day" in b:
        if not isinstance(b["all_day"], bool):
            raise BadInput(tr("Invalid value: {0}", "all_day"))
        all_day = 1 if b["all_day"] else 0
    f["all_day"] = all_day
    start, end = b.get("start", o.get("start")), b.get("end", o.get("end"))
    if old is not None and "start" in b and "end" not in b and "all_day" not in b:  # moved: keeps its length
        if o["all_day"] and valid_date(b["start"]):
            end = (date.fromisoformat(b["start"]) + (date.fromisoformat(o["end"]) - date.fromisoformat(o["start"]))).isoformat()
        elif not o["all_day"] and wall(b["start"]) and wall(o["start"]) and wall(o["end"]):
            end = wall_s(wall(b["start"]) + (wall(o["end"]) - wall(o["start"])))
        else:
            end = None
    if "all_day" in b and old is not None and "start" not in b:  # switched kind: derive from the stored start
        start = o["start"][:10] if all_day else o["start"][:10] + "T09:00"
        end = None
    if all_day:
        if isinstance(start, str) and len(start) > 10 and wall(start):
            start = start[:10]
        if isinstance(end, str) and len(end) > 10 and wall(end):
            e = wall(end)
            end = (e.date() + timedelta(days=0 if e.time() == datetime.min.time() else 1)).isoformat()
        if not valid_date(start):
            raise BadInput(tr("Invalid value: {0}", "start"))
        if end in (None, ""):
            end = (date.fromisoformat(start) + timedelta(days=1)).isoformat()
        if not valid_date(end) or end <= start or (date.fromisoformat(end) - date.fromisoformat(start)).days > EV_SPAN_DAYS:
            raise BadInput(tr("The end must be after the start"))
    else:
        if isinstance(start, str) and valid_date(start):
            start += "T09:00"
        s = wall(start)
        if not s:
            raise BadInput(tr("Invalid value: {0}", "start"))
        if isinstance(end, str) and valid_date(end):
            end += "T" + start[11:]
        e = wall(end) if end not in (None, "") else s + timedelta(hours=1)
        if not e:
            raise BadInput(tr("Invalid value: {0}", "end"))
        if e < s or (e - s).days > EV_SPAN_DAYS:
            raise BadInput(tr("The end must be after the start"))
        start, end = wall_s(s), wall_s(e)
    f["start"], f["end"] = start, end
    if "rrule" in b or old is None:
        rule = rule_local(rr_norm(b.get("rrule") or ""), ev_zone(f.get("tz", o.get("tz", ""))), bool(all_day))
        if rule:
            p = rr_problem(rule)
            if p:
                raise BadInput(tr(p))
            if not rr_feasible(rule, start[:10]):
                raise BadInput(tr("Repeat: the rule never matches"))
        f["rrule"] = rule
    elif "start" in b and o.get("rrule") and not rr_feasible(o["rrule"], start[:10]):
        raise BadInput(tr("Repeat: the rule never matches"))
    if "exdates" in b:
        v = b["exdates"]
        if not isinstance(v, list) or len(v) > 2000 or any(not isinstance(x, str) or not (valid_date(x) or wall(x)) for x in v):
            raise BadInput(tr("Invalid value: {0}", "exdates"))
        f["exdates"] = ",".join(sorted(set(v)))
    if "reminders" in b or old is None:
        f["reminders"] = clean_reminders(b.get("reminders"))
    if "status" in b or old is None:
        st = b.get("status") or "confirmed"
        if st not in EV_STATUS:
            raise BadInput(tr("Invalid value: {0}", "status"))
        f["status"] = st
    if "busy" in b:
        if not isinstance(b["busy"], bool):
            raise BadInput(tr("Invalid value: {0}", "busy"))
        f["busy"] = 1 if b["busy"] else 0
    if "url" in b:
        u = b["url"] or None
        if u is not None and (not isinstance(u, str) or not valid_url(u.strip())):
            raise BadInput(tr("Invalid value: {0}", "url"))
        f["url"] = u.strip() if u else None
    if "task_id" in b:
        t = b["task_id"]
        if t in (None, ""):
            f["task_id"] = None
        else:
            t = as_int(t, "task_id", 1)
            if t != o.get("task_id") and not task_visible(c, t, uid):  # unchanged: the owner's link stays, also for an editor
                raise Denied(404)
            f["task_id"] = t
    return f


# ---- repeat expansion
def _until_utc(rule, zone, all_day):
    """UNTIL of a rule in the form dateutil wants for the start used (aware for timed events, naive date-time for all day)."""
    parts = []
    for p in rule.split(";"):
        k, _, v = p.partition("=")
        if k == "UNTIL":
            try:
                if all_day:
                    v = v[:8] + "T235959"
                elif len(v) == 8:
                    d = datetime(int(v[:4]), int(v[4:6]), int(v[6:8]), 23, 59, 59, tzinfo=zone)
                    v = d.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                elif not v.endswith("Z"):
                    d = datetime.strptime(v[:15], "%Y%m%dT%H%M%S").replace(tzinfo=zone)
                    v = d.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            except ValueError:
                continue
        parts.append(f"{k}={v}")
    return ";".join(parts)


def ev_rule(r):
    """dateutil rule of the series (None: not repeating / not expandable) -- start: naive (all day) or aware (timed)."""
    rule = r["rrule"]
    if not rule or rr_problem(rule):
        return None
    zone = ev_zone(r["tz"])
    try:
        if r["all_day"]:
            st = datetime.fromisoformat(r["start"][:10])
            return rrulestr(_until_utc(rule, zone, True), dtstart=st)
        st = wall(r["start"]).replace(tzinfo=zone)
        return rrulestr(_until_utc(rule, zone, False), dtstart=st)
    except (ValueError, TypeError, OverflowError):
        return None


def ov_list(r):
    try:
        v = json.loads(r["overrides"] or "[]")
        return v if isinstance(v, list) else []
    except ValueError:
        return []


def occ_key(r, dt):
    return dt.date().isoformat() if r["all_day"] else wall_s(dt.astimezone(ev_zone(r["tz"])) if dt.tzinfo else dt)


def _span(r, s_key, e_key=None, all_day=None):
    """(start, end) of an occurrence: dates (all day, end exclusive) or aware datetimes."""
    ad = r["all_day"] if all_day is None else all_day
    zone = ev_zone(r["tz"])
    if ad:
        s = date.fromisoformat(s_key[:10])
        if e_key:
            e = date.fromisoformat(e_key[:10])
        else:
            e = s + (date.fromisoformat(r["end"][:10]) - date.fromisoformat(r["start"][:10]))
        return s, max(e, s + timedelta(days=1))
    s = (wall(s_key) or datetime.fromisoformat(s_key[:10])).replace(tzinfo=zone)
    if e_key:
        e = (wall(e_key) or s.replace(tzinfo=None)).replace(tzinfo=zone)
    else:
        e = s + (wall(r["end"]) - wall(r["start"]))
    return s, max(e, s)


def _days(s, e, all_day):
    """Local first / last day (server zone) of an occurrence."""
    if all_day:
        return s, e - timedelta(days=1)
    d0 = s.astimezone(TZ).date()
    d1 = (e - timedelta(microseconds=1)).astimezone(TZ).date() if e > s else d0
    return d0, max(d0, d1)


def ev_expand(r, lo, hi, cap=EV_OCC_CAP):
    """The occurrences of an event whose local days overlap [lo, hi] (dates): [{occ, s, e, ov}] sorted by start.
    occ = the original start key (exdates / overrides refer to it); ov = the override dict of a changed one."""
    out = []
    ex = set(x for x in (r["exdates"] or "").split(",") if x)
    ovs = {o.get("rid"): o for o in ov_list(r) if isinstance(o, dict) and o.get("rid")}

    def add(key, ov=None):
        if key in ex:
            return
        if ov is not None:
            if ov.get("status") == "cancelled":
                return
            s, e = _span(r, ov.get("start") or key, ov.get("end"), ov.get("all_day", r["all_day"]) and 1 or 0)
            ad = 1 if ov.get("all_day", r["all_day"]) else 0
        else:
            s, e = _span(r, key)
            ad = r["all_day"]
        d0, d1 = _days(s, e, ad)
        if d1 >= lo and d0 <= hi:
            out.append({"occ": key, "s": s, "e": e, "ov": ov, "all_day": ad})
    rule = ev_rule(r)
    if rule is None:
        add(r["start"], ovs.get(r["start"]))
    else:
        zone = ev_zone(r["tz"])
        dur = _span(r, r["start"])
        span = (dur[1] - dur[0]) if not r["all_day"] else timedelta(days=(dur[1] - dur[0]).days)
        a = datetime(lo.year, lo.month, lo.day) - span - timedelta(days=2)
        b = datetime(hi.year, hi.month, hi.day) + timedelta(days=2)
        if not r["all_day"]:
            a, b = a.replace(tzinfo=zone), b.replace(tzinfo=zone)
        seen = set()
        try:
            for dt in rule.xafter(a, count=cap * 2, inc=True):
                if dt > b:
                    break
                key = occ_key(r, dt)
                seen.add(key)
                add(key, ovs.get(key))
                if len(out) >= cap:
                    break
        except (ValueError, TypeError, OverflowError):
            pass
        for key, ov in ovs.items():  # changed occurrences moved into the range from outside of it
            if key not in seen and isinstance(key, str):
                add(key, ov)
    out.sort(key=lambda o: (o["s"] if isinstance(o["s"], datetime) else datetime(o["s"].year, o["s"].month, o["s"].day, tzinfo=TZ)))
    return out[:cap]


def ev_span_days(r):
    """(first_day, last_day) of a series in the server's zone ('' last day = open end), stored for the range query."""
    s, e = _span(r, r["start"], r["end"])
    d0, d1 = _days(s, e, r["all_day"])
    first, last = d0, d1
    rule = ev_rule(r)
    if rule is not None:
        rr = r["rrule"]
        if "COUNT=" in rr or "UNTIL=" in rr:
            try:
                lastdt, i = None, 0
                for i, dt in enumerate(rule):
                    lastdt = dt
                    if i >= 3000:
                        break
                if i >= 3000:  # a very long series: open end (its later dates must not go missing)
                    return min([first] + [_ov_day(r, o) for o in ov_list(r) if _ov_day(r, o)]).isoformat(), ""
                if lastdt is not None:
                    ls, le = _span(r, occ_key(r, lastdt))
                    last = max(last, _days(ls, le, r["all_day"])[1])
            except (ValueError, TypeError, OverflowError):
                return first.isoformat(), ""
        else:
            return min([first] + [_ov_day(r, o) for o in ov_list(r) if _ov_day(r, o)]).isoformat(), ""
    for o in ov_list(r):
        d = _ov_day(r, o)
        if d:
            first, last = min(first, d), max(last, d + timedelta(days=1))
    return first.isoformat(), last.isoformat()


def _ov_day(r, o):
    try:
        k = o.get("start") or o.get("rid")
        return date.fromisoformat(k[:10])
    except (AttributeError, TypeError, ValueError):
        return None


# ---- rows -> JSON
def att_rows(c, ids):
    out = {}
    if not ids:
        return out
    q = ",".join("?" * len(ids))
    for a in c.execute(f"""SELECT a.*, u.display_name, u.username, '' AS c_fn FROM event_attendees a LEFT JOIN users u ON u.id=a.user_id
                           WHERE a.event_id IN ({q}) ORDER BY a.id""", list(ids)):  # a contact: its name + address as invited
        out.setdefault(a["event_id"], []).append({
            "id": a["id"], "user_id": a["user_id"], "contact_id": a["contact_id"], "email": a["email"],
            "name": a["name"] or (a["display_name"] or a["username"] if a["user_id"] else "") or a["c_fn"] or a["email"],
            "partstat": a["partstat"], "role": a["role"]})
    return out


def ev_role_of(c, uid, r, cals=None):
    """The person's role for an event: the calendar's, else 'attendee' (invited person), else None."""
    role = (cals or {}).get(r["cal_id"]) if cals is not None else None
    if role is None:
        role = ev_role(c, uid, c.execute("SELECT * FROM ev_cals WHERE id=?", (r["cal_id"],)).fetchone())
    if role:
        return role
    if collab_all() and c.execute("SELECT 1 FROM event_attendees WHERE event_id=? AND user_id=?", (r["id"], uid)).fetchone():
        return "attendee"
    return None


def need_event(c, eid, write=False, uid=None, deleted=False):
    uid = uid or me()
    r = c.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone()
    if not r or (bool(r["deleted_at"]) != deleted):
        raise Denied(404)
    role = ev_role_of(c, uid, r)
    if not role:
        raise Denied(404)
    if write and not can_write(role):
        raise Denied(403, tr("You can only read this event"))
    return r, role


def ev_dict(c, r, uid, role=None, att=None):
    role = role or ev_role_of(c, uid, r)
    atts = att if att is not None else att_rows(c, [r["id"]]).get(r["id"], [])
    hide = role == "attendee"
    d = {"id": r["id"], "cal_id": None if hide else r["cal_id"], "uid": r["uid"], "title": r["title"], "location": r["location"],
         "description": r["description"], "all_day": bool(r["all_day"]), "start": r["start"], "end": r["end"],
         "tz": r["tz"] or getattr(TZ, "key", "UTC"), "rrule": r["rrule"], "exdates": [x for x in (r["exdates"] or "").split(",") if x],
         "overrides": [{k: o.get(k) for k in ("rid", "title", "start", "end", "all_day", "location", "description", "status")
                        if k in o} for o in ov_list(r)],
         "reminders": [int(x) for x in (r["reminders"] or "").split(",") if x.strip()], "status": r["status"], "busy": bool(r["busy"]),
         "url": r["url"], "task_id": None if hide else r["task_id"], "attendees": atts, "role": role, "created_by": r["created_by"],
         "created_at": r["created_at"], "updated_at": r["updated_at"]}
    mine = next((a for a in atts if a["user_id"] == uid), None)
    if mine:
        d["partstat"] = mine["partstat"]
    return d


def occ_out(r, o, role, att_n=0, partstat=None):
    """One occurrence for the calendar views: like an external event (start / end: dates or UTC), plus what the editor needs."""
    ov = o["ov"] or {}
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    if o["all_day"]:
        st, en = o["s"].isoformat(), o["e"].isoformat()
    else:
        st, en = o["s"].astimezone(timezone.utc).strftime(fmt), o["e"].astimezone(timezone.utc).strftime(fmt)
    d = {"eid": r["id"], "occ": o["occ"], "cal": None if role == "attendee" else r["cal_id"], "title": ov.get("title") or r["title"],
         "location": ov.get("location", r["location"]), "description": (ov.get("description", r["description"]) or "")[:2000],
         "all_day": bool(o["all_day"]), "start": st, "end": en, "recurring": bool(r["rrule"]), "changed": bool(o["ov"]),
         "status": ov.get("status") or r["status"], "role": role, "task_id": None if role == "attendee" else r["task_id"], "att": att_n}
    if partstat:
        d["partstat"] = partstat
    return d


def ev_range(c, uid, lo, hi, cal=None):
    """Every occurrence uid sees in [lo, hi] (dates): own + shared calendars (not hidden) and events uid is invited to."""
    cals = my_cal_ids(c, uid, hidden=False)
    if cal is not None:
        cals = {k: v for k, v in cals.items() if k == cal}
    rows = []
    if cals:
        q = ",".join("?" * len(cals))
        rows = c.execute(f"""SELECT * FROM events WHERE cal_id IN ({q}) AND deleted_at IS NULL AND first_day<=?
                             AND (last_day='' OR last_day>=?) ORDER BY start, id""",
                         [*cals, (hi + timedelta(days=1)).isoformat(), (lo - timedelta(days=1)).isoformat()]).fetchall()
    inv = []
    if cal is None and collab_all():
        inv = c.execute("""SELECT e.*, a.partstat AS my_ps FROM events e JOIN event_attendees a ON a.event_id=e.id AND a.user_id=?
                           WHERE e.deleted_at IS NULL AND e.first_day<=? AND (e.last_day='' OR e.last_day>=?)""",
                        (uid, (hi + timedelta(days=1)).isoformat(), (lo - timedelta(days=1)).isoformat())).fetchall()
    allc = my_cal_ids(c, uid)
    out, seen = [], set()
    nat = {}
    ids = [r["id"] for r in rows] + [r["id"] for r in inv]
    if ids:
        for i in range(0, len(ids), 900):
            part = ids[i:i + 900]
            q = ",".join("?" * len(part))
            for a in c.execute(f"SELECT event_id, user_id, partstat FROM event_attendees WHERE event_id IN ({q})", part):
                n, ps = nat.get(a[0], (0, None))
                nat[a[0]] = (n + 1, a[2] if a[1] == uid else ps)
    for r, role in [(r, cals[r["cal_id"]]) for r in rows] + [(r, "attendee") for r in inv if r["cal_id"] not in allc]:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        n, ps = nat.get(r["id"], (0, None))
        for o in ev_expand(r, lo, hi):
            out.append(occ_out(r, o, role, n, ps))
            if len(out) >= 20000:
                return out
    return out


# ---- writing (web, API and CalDAV all end here)
def ev_new_uid():
    return f"kalmido-ev-{secrets.token_hex(10)}"


def ev_store(c, uid, cal_id, f, eid=None, uid_=None, href=None, attendees=None, via=None):
    """Creates (eid None) or changes an event with the validated columns f; attendees (list of dicts) replaces them.
    Returns the event id. The caller commits; the data version goes up."""
    ts = iso_ms(now_utc())  # ms: two changes in one second still differ (expect)
    if eid is None:
        if c.execute("SELECT COUNT(*) FROM events WHERE cal_id=? AND deleted_at IS NULL", (cal_id,)).fetchone()[0] >= EV_PER_CAL:
            raise Denied(409, tr("At most {0} events per calendar", EV_PER_CAL))
        uid_ = uid_ or ev_new_uid()
        href = href or (re.sub(r"[^A-Za-z0-9._-]", "_", uid_)[:180] + ".ics")
        cols = {"cal_id": cal_id, "uid": uid_, "href": href, "title": f.get("title") or tr("(no title)"), "location": f.get("location", ""),
                "description": f.get("description", ""), "all_day": f.get("all_day", 0), "start": f["start"], "end": f["end"],
                "tz": f.get("tz", ""), "rrule": f.get("rrule", ""), "exdates": f.get("exdates", ""), "overrides": f.get("overrides", ""),
                "reminders": f.get("reminders", ""), "status": f.get("status", "confirmed"), "busy": f.get("busy", 1), "url": f.get("url"),
                "task_id": f.get("task_id"), "extra": f.get("extra", ""), "created_by": uid, "created_at": ts, "updated_at": ts}
        eid = c.execute(f"INSERT INTO events({','.join(cols)}) VALUES({','.join('?' * len(cols))})", list(cols.values())).lastrowid
    else:
        f = {k: v for k, v in f.items() if k not in ("id", "uid", "created_by", "created_at")}
        if f:
            f["updated_at"] = ts
            c.execute(f"UPDATE events SET {','.join(k + '=?' for k in f)}, seq=seq+1 WHERE id=?", [*f.values(), eid])
    r = c.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone()
    a, b_ = ev_span_days(r)
    c.execute("UPDATE events SET first_day=?, last_day=? WHERE id=?", (a, b_, eid))
    if attendees is not None:
        att_set(c, eid, attendees, r)
    if "start" in f or "reminders" in f or "rrule" in f:
        c.execute("DELETE FROM ev_reminded WHERE event_id=?", (eid,))
    cal_touch(c, r["cal_id"])
    bump(c)
    return eid


def att_clean(c, items, eid=None):
    """[{user_id} | {contact_id} | {email, name?}, partstat?, role?] -> rows (dicts) for event_attendees. Only a person's own
    reply is taken (the others keep theirs); a contact already invited stays without a check (an editor may not see it)."""
    from ..contacts.model import contact_visible
    from ..agents.admin import personal_agent_foreign
    me_ = me() if has_request_context() else None
    had = {r[0]: r for r in c.execute("SELECT contact_id, email, name FROM event_attendees WHERE event_id=? AND contact_id IS NOT NULL",
                                      (eid,))} if eid else {}
    if not isinstance(items, list) or len(items) > EV_ATT_MAX:
        raise BadInput(tr("Invalid value: {0}", "attendees"))
    out, seen = [], set()
    for a in items:
        if not isinstance(a, dict):
            raise BadInput(tr("Invalid value: {0}", "attendees"))
        ps = a.get("partstat") or "needs-action"
        role = a.get("role") or "req"
        if ps not in EV_PARTSTAT or role not in ("req", "opt"):
            raise BadInput(tr("Invalid value: {0}", "attendees"))
        row = {"user_id": None, "contact_id": None, "email": "", "name": "", "partstat": ps, "role": role}
        if a.get("user_id") not in (None, ""):
            if not collab_all():
                raise Denied(409, tr("Collaboration is turned off on this server"))
            u = as_int(a["user_id"], "user_id", 1)
            from ..accounts.orgs import may_see
            if not c.execute("SELECT 1 FROM users WHERE id=? AND disabled=0", (u,)).fetchone() or (me_ and personal_agent_foreign(c, u, me_)) \
                    or (me_ and eid is None and not may_see(c, me_, u)):  # 2.22.0 (#752): only people one may see (new events)
                raise BadInput(tr("unknown user"))
            row["user_id"], key = u, ("u", u)
            if u != me_:
                row["partstat"] = "needs-action"  # = keep their own reply (att_set)
        elif a.get("contact_id") not in (None, ""):
            k = as_int(a["contact_id"], "contact_id", 1)
            ct = contact_visible(c, k, me_) if me_ else None
            if ct:
                mails = json.loads(ct["emails"] or "[]")
                row["contact_id"], row["name"] = k, ct["fn"]
                row["email"] = (mails[0].get("value") if mails and isinstance(mails[0], dict) else "") or ""
            elif k in had:
                row["contact_id"], row["email"], row["name"] = k, had[k]["email"], had[k]["name"]
            else:
                raise Denied(404)
            key = ("c", k)
        else:
            em = str(a.get("email") or "").strip()[:200]
            if not re.fullmatch(r"[^@\s<>\"]+@[^@\s<>\"]+", em):
                raise BadInput(tr("Invalid value: {0}", "email"))
            row["email"], key = em, ("e", em.lower())
        if isinstance(a.get("name"), str) and a["name"].strip():
            row["name"] = re.sub(r"[\x00-\x1f\x7f]", " ", a["name"]).strip()[:200]
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def att_set(c, eid, rows, r=None):
    """Replaces the attendees; newly invited people get News + a push; a person's own reply is kept unless given."""
    from ..collab.news import news_add
    old = {a["user_id"]: a for a in c.execute("SELECT * FROM event_attendees WHERE event_id=? AND user_id IS NOT NULL", (eid,))}
    c.execute("DELETE FROM event_attendees WHERE event_id=?", (eid,))
    r = r or c.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone()
    actor = me() if has_request_context() else None
    for a in rows:
        if a["user_id"] and a["user_id"] in old and a["partstat"] == "needs-action":
            a = {**a, "partstat": old[a["user_id"]]["partstat"]}
        c.execute("INSERT INTO event_attendees(event_id,user_id,contact_id,email,name,partstat,role) VALUES(?,?,?,?,?,?,?)",
                  (eid, a["user_id"], a["contact_id"], a["email"], a["name"], a["partstat"], a["role"]))
        if a["user_id"] and a["user_id"] not in old and a["user_id"] != actor:
            news_add(c, a["user_id"], "evinvite", data={"event_id": eid, "title": r["title"][:200], "start": r["start"],
                                                         "all_day": bool(r["all_day"])}, row="assign")
            invite_push(c, a["user_id"], r)


def invite_push(c, uid, r):
    from ..collab.comments import lang_of
    from ..collab.news import notif_ok
    from ..notify.push import push_prio
    if not has_request_context():
        return
    s = usettings(c, uid)
    if not notif_ok(c, uid, s, "assign", "push"):  # an invitation is like an assignment: News + push by default
        return
    lg = lang_of(s)
    who = user_names(c, [me()]).get(me(), "?")
    from flask import g
    g.pushes.append((uid, tr("{0} invited you", who, lg=lg), f"{r['title']} · {when_text(r, lg)}", f"{PUBLIC_URL}/#ev/{r['id']}",
                     push_prio(s)))


def when_text(r, lg=None, occ=None):
    from ..core.i18n import short_day
    s, _ = _span(r, occ or r["start"])
    if r["all_day"]:
        return short_day(s, lg)
    loc = s.astimezone(TZ)
    return f"{short_day(loc.date(), lg)} {loc:%H:%M}"


def ev_delete(c, r):
    c.execute("UPDATE events SET deleted_at=?, updated_at=? WHERE id=?", (iso(now_utc()), iso_ms(now_utc()), r["id"]))
    cal_touch(c, r["cal_id"])
    bump(c)


def is_occ(r, occ):
    """occ is a date the series really has (its original start)."""
    rule = ev_rule(r)
    if rule is None:
        return occ == r["start"]
    try:
        dt = datetime.fromisoformat(occ[:10]) if r["all_day"] else wall(occ).replace(tzinfo=ev_zone(r["tz"]))
        hit = rule.after(dt - timedelta(seconds=1))
    except (ValueError, TypeError, OverflowError, AttributeError):
        return False
    return hit is not None and occ_key(r, hit) == occ


def ev_occ_change(c, r, occ, b):
    """Only this occurrence: {"delete": true} leaves it out, else its own title / times / place (an override)."""
    from ..events.ics import OV_KEYS
    if not r["rrule"]:
        raise BadInput(tr("The event does not repeat"))
    if not (valid_date(occ) if r["all_day"] else wall(occ)) or not is_occ(r, occ):
        raise BadInput(tr("Invalid value: {0}", "occurrence"))
    ovs = [o for o in ov_list(r) if o.get("rid") != occ]
    if len(ovs) >= 500 or len([x for x in (r["exdates"] or "").split(",") if x]) >= 2000:
        raise Denied(409, tr("At most {0} events per calendar", 500))
    if b.get("delete") is True:
        ex = set(x for x in (r["exdates"] or "").split(",") if x) | {occ}
        return ev_store(c, me(), r["cal_id"], {"exdates": ",".join(sorted(ex)), "overrides": json.dumps(ovs, ensure_ascii=False)}, r["id"])
    old = next((o for o in ov_list(r) if o.get("rid") == occ), {})
    base = {"title": old.get("title", r["title"]), "location": old.get("location", r["location"]),
            "description": old.get("description", r["description"]), "all_day": bool(old.get("all_day", r["all_day"])),
            "start": old.get("start") or occ, "end": old.get("end") or wall_s(_span(r, occ)[1].replace(tzinfo=None)) if not r["all_day"]
            else old.get("end") or _span(r, occ)[1].isoformat(), "status": old.get("status", r["status"])}
    unknown = [k for k in b if k not in OV_KEYS]
    if unknown:
        raise BadInput(tr("Unknown field: {0}", ", ".join(unknown)[:200]))
    tmp = ev_fields(c, me(), {k: v for k, v in {**base, **b}.items() if k in ("title", "location", "description", "all_day", "start", "end", "status")},
                    {**dict(r), "rrule": "", "all_day": 1 if base["all_day"] else 0})
    ov = {"rid": occ, "title": tmp["title"], "location": tmp["location"], "description": tmp["description"],
          "all_day": bool(tmp["all_day"]), "start": tmp["start"], "end": tmp["end"], "status": tmp.get("status", "confirmed"),
          "extra": old.get("extra", "")}
    return ev_store(c, me(), r["cal_id"], {"overrides": json.dumps(ovs + [ov], ensure_ascii=False)}, r["id"])


# ---- reminders (watchdog): the calendar's owner and members who see it (not hidden) + attendees who accepted /
# have not answered, once per occurrence and offset, missed by more than 6 h = skipped
def _wd_events(c, users, S, LG, now):
    from ..collab.news import notif_ok
    from ..notify.push import notify, push_prio
    lo = now.date() - timedelta(days=1)
    hi = now.date() + timedelta(days=8)
    rows = c.execute("""SELECT * FROM events WHERE deleted_at IS NULL AND reminders!='' AND status!='cancelled' AND first_day<=?
                        AND (last_day='' OR last_day>=?)""", (hi.isoformat(), lo.isoformat())).fetchall()
    for r in rows:
        try:
            cal = c.execute("SELECT * FROM ev_cals WHERE id=?", (r["cal_id"],)).fetchone()
            who = {cal["owner_id"]} | ({m[0] for m in c.execute("SELECT user_id FROM ev_cal_members WHERE cal_id=?", (cal["id"],))}
                                         if collab_all() else set())
            if collab_all():
                who |= {a[0] for a in c.execute("SELECT user_id FROM event_attendees WHERE event_id=? AND user_id IS NOT NULL "
                                                "AND partstat!='declined'", (r["id"],))}
            who = [u for u in who if u in users and "events" in (S.get(u, {}).get("features") or "").split(",")
                   and r["cal_id"] not in set(json.loads(S.get(u, {}).get("evcals_hidden") or "[]") or [])]
            if not who:
                continue
            offs = [int(x) for x in r["reminders"].split(",") if x.strip()]
            for o in ev_expand(r, lo, hi, 200):
                if (o["ov"] or {}).get("status") == "cancelled":
                    continue
                st = o["s"] if isinstance(o["s"], datetime) else datetime(o["s"].year, o["s"].month, o["s"].day, tzinfo=TZ)
                for off in offs:
                    at = st - timedelta(minutes=off)
                    if at > now:
                        continue
                    key = f"{o['occ']}|{off}"
                    for u in who:
                        if c.execute("SELECT 1 FROM ev_reminded WHERE event_id=? AND user_id=? AND k=?", (r["id"], u, key)).fetchone():
                            continue
                        c.execute("INSERT INTO ev_reminded(event_id,user_id,k,at) VALUES(?,?,?,?)", (r["id"], u, key, iso(now_utc())))
                        c.commit()
                        if now - at > timedelta(hours=6) or not notif_ok(c, u, S[u], "reminder", "push"):
                            continue
                        lg = LG.get(u, "en")
                        title = (o["ov"] or {}).get("title") or r["title"]
                        when = tr("all day", lg=lg) if o["all_day"] else st.astimezone(TZ).strftime("%H:%M")
                        d0 = st.astimezone(TZ).date() if isinstance(o["s"], datetime) else o["s"]
                        day = tr("today", lg=lg) if d0 == now.date() else short_day(d0, lg)
                        loc = (o["ov"] or {}).get("location", r["location"])
                        notify(u, title, " · ".join(x for x in (f"{day} {when}".strip(), loc) if x), push_prio(S[u]),
                               f"{PUBLIC_URL}/#ev/{r['id']}", s=S[u], tag=f"ev-{r['id']}")
        except Exception as e:  # noqa: BLE001  (one broken event never stops the others)
            from ..notify.push import _wd_fail
            _wd_fail(c, "reminder of event", r["id"], e)
    cut = iso(now_utc() - timedelta(days=EV_PURGE_DAYS))
    old = c.execute("SELECT id, cal_id FROM events WHERE deleted_at IS NOT NULL AND deleted_at<?", (cut,)).fetchall()
    if old:
        c.executemany("DELETE FROM events WHERE id=?", [(r[0],) for r in old])
        c.commit()
    c.execute("DELETE FROM ev_reminded WHERE at<?", (iso(now_utc() - timedelta(days=60)),))
    c.commit()


# ---- 2.19 family events -> events (once): every task with people who come along ("task_people") and a date becomes an
# event in its creator's calendar (the people as attendees, the time, duration, reminders, repeat and notes), linked to
# the task as its preparation. The task stays as it was (nothing is lost); a task that is still open and has no
# subtasks is marked done (it is the event now) and its reminders stop, so nothing comes twice.
def migrate_family_events(c):
    if gsetting(c, "migr_ev221") == "1":
        return 0
    from ..core.i18n import lang
    n = 0
    rows = c.execute("""SELECT t.*, l.owner_id AS l_owner FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.deleted_at IS NULL
                        AND t.due IS NOT NULL AND EXISTS (SELECT 1 FROM task_people p WHERE p.task_id=t.id)
                        AND NOT EXISTS (SELECT 1 FROM events e WHERE e.task_id=t.id)""").fetchall()
    for t in rows:
        owner = t["created_by"] or t["l_owner"]
        if not owner or not c.execute("SELECT 1 FROM users WHERE id=?", (owner,)).fetchone():
            continue
        cid = c.execute("SELECT id FROM ev_cals WHERE owner_id=? ORDER BY sort, id LIMIT 1", (owner,)).fetchone()
        cid = cid[0] if cid else cal_create(c, owner, {"name": tr("Calendar", lg=lang(c, owner))})
        if t["due_time"]:
            s = datetime.fromisoformat(f"{t['due']}T{t['due_time']}")
            f = {"all_day": 0, "start": wall_s(s), "end": wall_s(s + timedelta(minutes=t["duration"] or 60))}
        else:
            d = date.fromisoformat(t["due"])
            f = {"all_day": 1, "start": d.isoformat(), "end": (d + timedelta(days=1)).isoformat()}
        rule = rr_norm(t["repeat"] or "")
        f.update({"title": t["title"][:EV_TITLE_MAX], "description": (t["content"] or "")[:EV_DESC_MAX], "location": "",
                  "rrule": rule if rule and not rr_problem(rule) and rr_feasible(rule, t["due"]) else "",
                  "reminders": t["reminders"] or "", "task_id": t["id"], "url": t["url"]})
        ts = iso_ms(now_utc())
        uid_ = ev_new_uid()
        eid = c.execute("""INSERT INTO events(cal_id,uid,href,title,location,description,all_day,start,end,tz,rrule,reminders,url,task_id,
                           created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,'',?,?,?,?,?,?,?)""",
                        (cid, uid_, uid_ + ".ics", f["title"], "", f["description"], f["all_day"], f["start"], f["end"], f["rrule"],
                         f["reminders"], f["url"], t["id"], owner, ts, ts)).lastrowid
        r = c.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone()
        a, b_ = ev_span_days(r)
        c.execute("UPDATE events SET first_day=?, last_day=? WHERE id=?", (a, b_, eid))
        for (pu,) in c.execute("SELECT user_id FROM task_people WHERE task_id=? ORDER BY user_id", (t["id"],)).fetchall():
            if pu != owner:
                c.execute("INSERT INTO event_attendees(event_id,user_id,partstat) VALUES(?,?,'accepted')", (eid, pu))
        if t["status"] == 0 and not c.execute("SELECT 1 FROM tasks WHERE parent_id=? AND deleted_at IS NULL", (t["id"],)).fetchone():
            c.execute("UPDATE tasks SET status=2, completed_at=?, completed_by=?, updated_at=? WHERE id=?", (ts, owner, ts, t["id"]))
            c.execute("INSERT INTO activity(task_id,user_id,kind,data,created_at) VALUES(?,?,?,?,?)",
                      (t["id"], None, "event", json.dumps({"event_id": eid}), ts))
        n += 1
    gset(c, "migr_ev221", "1")
    if n:
        bump(c)
        print("events:", n, "family events (tasks with people) became events", flush=True)
    c.commit()
    return n


N_("Calendar")
N_("Events")
