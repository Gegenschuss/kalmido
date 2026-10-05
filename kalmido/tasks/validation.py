"""Task activity log, input validation, repeat rules (RRULE) and task tree helpers."""
import functools
import json
import math
import re
from datetime import date, datetime
from dateutil.rrule import rrulestr
from flask import g, has_request_context

from ..core.schema import MAX_DEPTH
from ..core.i18n import N_, tr
from ..core.db import iso_ms, now_utc, parse_iso
from ..core.pages import valid_url


# ---------------------------------------------------------------- tasks

TASK_FIELDS = ("list_id", "section_id", "parent_id", "title", "content", "priority",
               "due", "due_time", "reminders", "repeat", "repeat_from", "sort",
               "pinned", "start", "duration", "assignee_id", "url", "ttype", "deadline", "nag",
               "assignee_group_id",  # 2.10.0 (#441): assigned to a group (whoever has time); excludes assignee_id
               "plan_start",  # 2.11.0: planned start "YYYY-MM-DDTHH:MM" (day plan), independent of the due date
               "ms", "milestone_id",  # 2.18.0 (#430): a milestone (1) / the milestone of the same list a task belongs to
               "fam", "rotation", "stars")  # 2.19.0 (#653): family data, household rotation, stars of a kid
# 2.4.0 (#340): ticket types of a task (API v1 / MCP / events: "type"); '' = none
TICKET_TYPES = ("bug", "feature", "task")


# ---------------------------------------------------------------- activity (task history)
# Structured events, rendered (and translated) by the client: kind + data. Logged by the mutation
# endpoints, never for noise (sort order, pin, reminders, private tags, view state). Repeated edits of
# the same kind by the same user within ACT_MERGE_S update the last entry instead of adding lines
# (typing in the title / description, clicking through dates).
ACT_MERGE = {"title", "content", "due", "snooze", "priority", "assign", "list", "section", "repeat", "link", "parent", "field"}
ACT_MERGE_S = 600


def log_act(c, tid, kind, data=None, uid=None):
    from ..api.v1 import act_via
    from ..integrations.webhooks import wh_note
    if uid is None and has_request_context() and getattr(g, "user", None):
        uid = g.user["id"] or None  # 0 = someone via a public link (no user)
    via = act_via()
    if via:  # package B: "via API" / "via the public link" in the history
        data = {**(data or {}), "via": via}
    if has_request_context():
        wh_note(c, tid, kind)  # webhooks: collected per request, queued after a successful response
    ts, js = iso_ms(now_utc()), json.dumps(data or {}, ensure_ascii=False)
    if kind in ACT_MERGE:
        last = c.execute("SELECT id, user_id, kind, data, created_at FROM activity WHERE task_id=? ORDER BY id DESC LIMIT 1",
                         (tid,)).fetchone()
        if last and last["kind"] == kind and last["user_id"] == uid \
                and (kind != "field" or json.loads(last["data"] or "{}").get("id") == (data or {}).get("id")) \
                and (now_utc() - parse_iso(last["created_at"])).total_seconds() < ACT_MERGE_S:
            c.execute("UPDATE activity SET data=?, created_at=? WHERE id=?", (js, ts, last["id"]))
            return
    c.execute("INSERT INTO activity(task_id,user_id,kind,data,created_at) VALUES(?,?,?,?,?)", (tid, uid, kind, js, ts))


def log_changes(c, tid, old, act=None):
    """Compares the task row before a change (old) with the stored row now and logs what a person
    would care about."""
    from ..tasks.lifecycle import _norm
    new = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    if not old or not new:
        return
    ch = lambda k: _norm(old[k]) != _norm(new[k])  # noqa: E731
    if ch("title"):
        log_act(c, tid, "title", {"to": new["title"][:200]})
    if ch("content"):
        log_act(c, tid, "content")
    if ch("due") or ch("due_time") or ch("start"):
        log_act(c, tid, "snooze" if act == "snooze" and new["due"] else "dep_shift" if act == "dep_shift" else "due",
                {"due": new["due"], "time": new["due_time"], "start": new["start"]})
    if ch("priority"):
        log_act(c, tid, "priority", {"p": new["priority"]})
    if ch("assignee_id"):
        log_act(c, tid, "assign", {"to": new["assignee_id"], "from": old["assignee_id"]})
    if ch("list_id"):
        lst = c.execute("SELECT name, is_inbox FROM lists WHERE id=?", (new["list_id"],)).fetchone()
        log_act(c, tid, "list", {"name": lst["name"] if lst else "", "inbox": bool(lst and lst["is_inbox"])})
    elif ch("section_id") and not ch("parent_id"):  # indenting follows the parent's section: not a move
        sec = c.execute("SELECT name FROM sections WHERE id=?", (new["section_id"],)).fetchone() if new["section_id"] else None
        log_act(c, tid, "section", {"name": sec["name"] if sec else None})
    if ch("parent_id"):
        par = c.execute("SELECT title FROM tasks WHERE id=?", (new["parent_id"],)).fetchone() if new["parent_id"] else None
        log_act(c, tid, "parent", {"title": par["title"][:200] if par else None})
    if ch("repeat"):
        log_act(c, tid, "repeat", {"rule": new["repeat"]})
    if ch("url"):
        log_act(c, tid, "link", {"url": new["url"]})
    if ch("ttype"):  # 2.4.0 (#340)
        log_act(c, tid, "ttype", {"to": new["ttype"] or None})
    if ch("ms"):  # 2.18.0 (#430): turned into a milestone / back into a task
        log_act(c, tid, "ms", {"on": bool(new["ms"])})
    if ch("milestone_id"):  # 2.18.0 (#430): the milestone the task belongs to (title kept: it may be renamed later)
        m = c.execute("SELECT title FROM tasks WHERE id=?", (new["milestone_id"],)).fetchone() if new["milestone_id"] else None
        log_act(c, tid, "milestone", {"id": new["milestone_id"], "title": m["title"][:200] if m else None})


def check_url(f):
    """Normalizes f['url'] ('' -> NULL); error message if it is not an http(s) link."""
    if "url" not in f:
        return None
    u = (f["url"] or "").strip() if isinstance(f["url"], (str, type(None))) else ""
    f["url"] = u or None
    return tr("The link must start with http:// or https://") if u and not valid_url(u) else None


# ---- input validation (security audit 2026-09-28): the watchdog and the calendar code parse these
# fields for every user, so nothing malformed may be stored (one bad row used to stop all reminders).
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
HM_RE = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")
DATE_MIN_Y, DATE_MAX_Y = 1900, 2999
REM_MIN, REM_MAX, REM_COUNT = -1440, 366 * 1440, 10   # reminder offsets (minutes before due)
# 2.7.0 (#413): nag intervals ('' on a task = its list's default, '' on a list = none, 'off' = none on this task)
NAG_VALUES = ("", "off", "5", "10", "15", "30", "60", "1d")
NAG_MINUTES = {"5": 5, "10": 10, "15": 15, "30": 30, "60": 60, "1d": 1440}
NAG_HOUR_CAP = 30   # at most this many nag pushes per person and hour, all tasks together (the rest waits a round)
DAY_HOURS_DEFAULT = 8.0  # 2.7.0 (#407): hours of a working day / shift (admin: time_day_h, a list: lists.day_hours)
DURATION_MAX = 7 * 1440
TITLE_MAX, CONTENT_MAX = 2000, 200000
PRIORITIES = (0, 1, 3, 5)


def valid_date(v):
    if not isinstance(v, str) or not DATE_RE.fullmatch(v):
        return False
    try:
        return DATE_MIN_Y <= date.fromisoformat(v).year <= DATE_MAX_Y
    except ValueError:
        return False


def valid_plan_start(v):
    """2.11.0: a day plan slot, local "YYYY-MM-DDTHH:MM"."""
    return isinstance(v, str) and len(v) == 16 and v[10] == "T" and valid_date(v[:10]) and valid_hm(v[11:])


def valid_hm(v):
    return isinstance(v, str) and bool(HM_RE.fullmatch(v))


def as_int(v, what, lo=None, hi=None):
    """int from a client value (int or digit string, never bool / float text); BadInput otherwise."""
    from ..personal.timetrack import BadInput
    if isinstance(v, bool) or not isinstance(v, (int, str)) or (isinstance(v, str) and not re.fullmatch(r"-?\d{1,12}", v.strip())):
        raise BadInput(tr("Invalid value: {0}", what))
    v = int(v)
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        raise BadInput(tr("Invalid value: {0}", what))
    return v


def clean_reminders(v):
    """'0,15' / [0, 15] -> '0,15' (minutes before due, ints within bounds); BadInput otherwise."""
    from ..personal.timetrack import BadInput
    if v in (None, ""):
        return ""
    items = v if isinstance(v, list) else str(v).split(",") if isinstance(v, (str, int)) and not isinstance(v, bool) else None
    if items is None:
        raise BadInput(tr("Invalid value: {0}", tr("Reminder")))
    out = []
    for x in items:
        if isinstance(x, str) and not x.strip():
            continue
        out.append(str(as_int(x.strip() if isinstance(x, str) else x, tr("Reminder"), REM_MIN, REM_MAX)))
    out = list(dict.fromkeys(out))
    if len(out) > REM_COUNT:
        raise BadInput(tr("Invalid value: {0}", tr("Reminder")))
    return ",".join(out)


# RRULE: only what the calendar code can expand cheaply. No SECONDLY / MINUTELY / HOURLY and no
# BYHOUR / BYMINUTE / BYSECOND (the UI offers daily and longer; sub-daily rules made the occurrence
# expansion explode). Expansion is additionally capped (count + time window) where it is used.
RR_FREQS = ("DAILY", "WEEKLY", "MONTHLY", "YEARLY")
RR_KEYS = ("FREQ", "INTERVAL", "COUNT", "UNTIL", "BYDAY", "BYMONTHDAY", "BYMONTH", "BYSETPOS", "WKST",
           "BYYEARDAY", "BYWEEKNO")
RR_MAX_LEN = 300
RR_PROBE_DAYS = 3660          # a rule must have a date within ~10 years of its start
RR_OCC_PER_TASK, RR_OCC_TOTAL, RR_OCC_SECONDS = 120, 5000, 3.0


def rr_norm(rep):
    return (rep or "").strip().removeprefix("RRULE:").strip().rstrip(";") if isinstance(rep, str) else ""


@functools.lru_cache(maxsize=4096)
def rr_problem(rep):
    """None if the (normalized) rule is acceptable, else an error text. Structural check + parse."""
    from ..calendars.icalfeed import RRULE_OK
    if len(rep) > RR_MAX_LEN or not RRULE_OK.fullmatch(rep):
        return N_("Repeat: invalid rule")
    parts = dict(p.split("=", 1) for p in rep.split(";"))
    if len(parts) != rep.count(";") + 1 or any(k not in RR_KEYS for k in parts):
        return N_("Repeat: invalid rule")
    if parts.get("FREQ") not in RR_FREQS:
        return N_("Repeat: only daily, weekly, monthly or yearly rules")
    if "INTERVAL" in parts and not (parts["INTERVAL"].isdigit() and 1 <= int(parts["INTERVAL"]) <= 999):
        return N_("Repeat: invalid rule")
    if "COUNT" in parts and not (parts["COUNT"].isdigit() and 1 <= int(parts["COUNT"]) <= 9999):
        return N_("Repeat: invalid rule")
    if "UNTIL" in parts and not re.fullmatch(r"\d{8}(T\d{6}Z?)?", parts["UNTIL"]):
        return N_("Repeat: invalid rule")
    try:
        rrulestr(rep, dtstart=datetime(2026, 1, 1))
    except (ValueError, TypeError, OverflowError):
        return N_("Repeat: invalid rule")
    return None


@functools.lru_cache(maxsize=4096)
def rr_feasible(rep, d0):
    """True if the rule (without COUNT / UNTIL) has a date within RR_PROBE_DAYS after the local date d0.
    dateutil scans up to the year 9999 for a rule that never matches (seconds of CPU): the probe runs
    shifted by whole 400-year Gregorian cycles (same weekdays, same calendar) close to 9999, so a rule that
    never matches costs a fraction of a second, once (cached)."""
    if rr_problem(rep):
        return False
    try:
        d = date.fromisoformat(d0)
        base = ";".join(p for p in rep.split(";") if not p.startswith(("COUNT=", "UNTIL=")))
        k = max(0, (9800 - d.year) // 400)
        st = datetime(d.year + 400 * k, d.month, d.day)
        nxt = rrulestr(base, dtstart=st).after(st, inc=True)
        return bool(nxt) and (nxt - st).days <= RR_PROBE_DAYS
    except (ValueError, TypeError, OverflowError):
        return False


def rr_rule(rep, d0):
    """Parsed rrule for expansion from the local date d0 (datetime at midnight), or None if the rule is
    not acceptable / never matches (such rows are treated as not recurring)."""
    rep = rr_norm(rep)
    if not rep or not valid_date(d0) or not rr_feasible(rep, d0):
        return None
    d = date.fromisoformat(d0)
    return rrulestr(rep, dtstart=datetime(d.year, d.month, d.day))


def clean_repeat(v):
    from ..personal.timetrack import BadInput
    rep = rr_norm(v) if isinstance(v, str) else None
    if rep is None:
        raise BadInput(tr("Repeat: invalid rule"))
    if rep:
        e = rr_problem(rep)
        if e:
            raise BadInput(tr(e))
    return rep


# 2.4.0 (#340): the built-in note templates of new tickets (in the language of the person creating the ticket); a list
# can have its own (lists.ticket_tpl, json {bug, feature}; Markdown, at most TICKET_TPL_MAX characters each)
TICKET_TPL = {"bug": N_("**Steps to reproduce**\n1. \n\n**Expected**\n\n**Actual**\n\n**Environment**\n\n**Version / found in**\n"),
              "feature": N_("**Goal**\n\n**Acceptance criteria**\n- [ ] \n")}
TICKET_TPL_MAX = 5000


def clean_ticket_tpl(v):
    """{bug?, feature?} from a client -> the stored json ('' = both built-in)."""
    from ..personal.timetrack import BadInput
    if v in (None, ""):
        return ""
    if not isinstance(v, dict) or any(k not in TICKET_TPL for k in v):
        raise BadInput(tr("Invalid value: {0}", "ticket_tpl"))
    out = {}
    for k, x in v.items():
        if x is not None and not isinstance(x, str):
            raise BadInput(tr("Invalid value: {0}", "ticket_tpl"))
        x = (x or "").replace("\r\n", "\n")[:TICKET_TPL_MAX]
        if x.strip():
            out[k] = x
    return json.dumps(out, ensure_ascii=False) if out else ""


def ticket_template(c, lid, kind):
    """The note template of a new ticket of this kind in list lid ('' when the list has ticket types off, or for "task")."""
    if kind not in TICKET_TPL:
        return ""
    r = c.execute("SELECT tickets, ticket_tpl FROM lists WHERE id=?", (lid,)).fetchone()
    if not r or not r["tickets"]:
        return ""
    try:
        own = json.loads(r["ticket_tpl"] or "{}").get(kind)
    except (ValueError, AttributeError):
        own = None
    return own if isinstance(own, str) and own.strip() else tr(TICKET_TPL[kind])


def clean_task(b):
    """Client values -> column values (validated; BadInput with a message otherwise)."""
    from ..personal.timetrack import BadInput
    from ..family.family import clean_fam, clean_rotation, STARS_MAX
    out = {}
    for k in TASK_FIELDS:
        if k in b:
            v = b[k]
            if k in ("due", "due_time", "section_id", "parent_id", "start", "duration", "list_id", "plan_start") and v in ("", None):
                v = None
            if k in ("assignee_id", "assignee_group_id") and v in ("", None, 0):
                v = None
            if k == "title":
                if v is not None and not isinstance(v, str):
                    raise BadInput(tr("Invalid value: {0}", tr("Title")))
                v = (v or "").strip()[:TITLE_MAX]
            if k == "content":
                if v is not None and not isinstance(v, str):
                    raise BadInput(tr("Invalid value: {0}", tr("Description")))
                v = (v or "")[:CONTENT_MAX]
            if k in ("list_id", "section_id", "parent_id", "assignee_id", "assignee_group_id") and v is not None:
                v = as_int(v, k, 1)
            if k == "priority":
                v = as_int(v or 0, tr("Priority"))
                if v not in PRIORITIES:
                    raise BadInput(tr("Invalid value: {0}", tr("Priority")))
            if k == "pinned":
                v = 1 if as_int(int(v) if isinstance(v, bool) else (v or 0), tr("Pinned")) else 0
            if k in ("due", "start") and v is not None and not valid_date(v):
                raise BadInput(tr("Invalid value: {0}", tr("Date") if k == "due" else tr("Start|date")))
            if k == "due_time" and v is not None and not valid_hm(v):
                raise BadInput(tr("Invalid value: {0}", tr("Time")))
            if k == "plan_start" and v is not None and not valid_plan_start(v):
                raise BadInput(tr("Invalid value: {0}", "plan_start"))
            if k == "duration" and v is not None:
                v = as_int(v, tr("Duration"), 1, DURATION_MAX)
            if k == "reminders":
                v = clean_reminders(v)
            if k == "repeat":
                v = "" if v is None else clean_repeat(v)
            if k == "repeat_from":
                v = "done" if v == "done" else "due"
            if k == "deadline":  # 2.7.0 (#412): 0 no, 1 deadline, 2 deadline + on Today from the first reminder on
                v = 1 if v is True else 0 if v in (False, None) else as_int(v, tr("Deadline"), 0, 2)
            if k == "nag":  # 2.7.0 (#413)
                v = "" if v is None else v
                if v not in NAG_VALUES:
                    raise BadInput(tr("Invalid value: {0}", tr("Repeat reminder")))
            if k == "ms":  # 2.18.0 (#430): true / false / 0 / 1
                if v not in (True, False, 0, 1, None):
                    raise BadInput(tr("Invalid value: {0}", tr("Milestone")))
                v = 1 if v else 0
            if k == "milestone_id":
                v = None if v in ("", None, 0) else as_int(v, tr("Milestone"), 1)
            if k == "fam":  # 2.19.0 (#653)
                v = clean_fam(v)
            if k == "rotation":
                v = clean_rotation(v)
            if k == "stars":
                v = None if v in ("", None) else as_int(v, tr("Stars"), 0, STARS_MAX)
            if k == "ttype":
                v = "" if v in (None, "") else v
                if v and v not in TICKET_TYPES:
                    raise BadInput(tr("Invalid value: {0}", tr("Type")))
            if k == "sort":
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                    try:
                        v = float(v)
                    except (TypeError, ValueError):
                        raise BadInput(tr("Invalid value: {0}", "sort")) from None
                    if not math.isfinite(v):
                        raise BadInput(tr("Invalid value: {0}", "sort"))
            out[k] = v
    if out.get("due") is None and "due" in out:
        out["due_time"] = None
        out["start"] = None
        out["reminders"] = out.get("reminders", "")
    if out.get("start") and out.get("due") and out["start"] > out["due"]:
        out["start"] = out["due"]
    return out


def descendants(c, tid):
    """All subtasks (all levels). Cycle-safe: UNION drops rows already produced and the depth is capped,
    so a parent_id cycle in old / imported data can never make this run forever."""
    return [r[0] for r in c.execute("""WITH RECURSIVE d(id, lvl) AS (
        SELECT id, 1 FROM tasks WHERE parent_id=? UNION
        SELECT t.id, d.lvl + 1 FROM tasks t JOIN d ON t.parent_id=d.id WHERE d.lvl < ?)
        SELECT DISTINCT id FROM d WHERE id != ?""", (tid, MAX_DEPTH + 7, tid))]


def depth(c, tid):
    """0 = top level. Walks up the parent chain."""
    n, cur = 0, tid
    while n < 10:
        r = c.execute("SELECT parent_id FROM tasks WHERE id=?", (cur,)).fetchone()
        if not r or not r[0]:
            return n
        cur, n = r[0], n + 1
    return n


def subtree_height(c, tid):
    h, level = 0, [tid]
    while level and h < 10:
        q = ",".join("?" * len(level))
        level = [r[0] for r in c.execute(f"SELECT id FROM tasks WHERE parent_id IN ({q})", level)]
        if level:
            h += 1
    return h


def ancestors(c, tid, limit=MAX_DEPTH + 7):
    """Parent chain of tid (nearest first); stops at a cycle / after limit steps."""
    out, cur = [], tid
    while len(out) < limit:
        r = c.execute("SELECT parent_id FROM tasks WHERE id=?", (cur,)).fetchone()
        if not r or not r[0] or r[0] in out or r[0] == tid:
            break
        out.append(r[0])
        cur = r[0]
    return out


def check_parent(c, tid, parent):
    """None if tid may become a child of parent, else an error message."""
    if parent is None:
        return None
    try:
        parent, tid = int(parent), (int(tid) if tid is not None else None)
    except (TypeError, ValueError):
        return tr("unknown")
    if tid is not None and (parent == tid or parent in descendants(c, tid) or tid in ancestors(c, parent)):
        return tr("A task cannot be nested under itself")
    # 2.18.0 (#430): milestones are top-level tasks without subtasks
    if (c.execute("SELECT ms FROM tasks WHERE id=?", (parent,)).fetchone() or [0])[0]:
        return tr("A milestone cannot have subtasks")
    if tid is not None and (c.execute("SELECT ms FROM tasks WHERE id=?", (tid,)).fetchone() or [0])[0]:
        return tr("A milestone cannot be a subtask")
    if depth(c, parent) + 1 + (subtree_height(c, tid) if tid else 0) >= MAX_DEPTH:
        return tr("At most {0} levels", MAX_DEPTH)
    return None
