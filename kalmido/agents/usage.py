"""Model usage of agents, limits and the agents' audit log."""
import csv
import io
import json
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone
from flask import g, jsonify, request, Response

from ..core.config import API_PREFIX, app, MAX_FILE_MB, PUBLIC_URL, TZ
from ..core.i18n import dec_comma, fmt_int, lang, tr
from ..core.db import bump, connect, db, inbox_default, iso, iso_ms, local_now, now_utc, parse_iso, usettings
from ..accounts.session import GATE, me
from ..accounts.pictures import avatar_url
from ..core.access import Denied, list_role, need_collab, need_list, task_visible
from ..tasks.validation import as_int, valid_date
from ..collab.comments import att_dicts, collab_on, comment_dict, lang_of, need_live_comment, user_names
from ..collab.news import news_add, notif_ok
from ..personal.timetrack import _csv_cell, BadInput, reject_unknown, UnknownFields
from ..accounts.users import need_admin
from ..lists.templates import PTYPES
from ..notify.push import push_prio, push_reachable
from ..notify.alerts import _env_int
from ..api.v1 import PRIO_VALUES, v1_args, v1_call, v1_comment, v1_err, v1_feature, v1_json, v1_view
from ..agents.core import (
    agent_active, AGENT_EVENTS, agent_row, agent_shares, AGENT_STATUSES, AGENT_TYPING_S, AGENT_WAIT_MAX, is_agent,
    JOB_ACTIONS, JOB_STATES, need_agent, TIDY_MODES,
)
from ..collab.reactions import clean_emoji, ltag_create, ltag_delete, ltag_update, react, with_reactions
from ..agents.chat import CHAT_FILES_MAX
from ..agents.admin import need_agent_admin
from ..agents.proposals import PROP_KINDS, PROP_MAX_BYTES, PROP_MAX_ITEMS, PROP_STATES, PROP_SUMMARY_MAX


# ---------------------------------------------------------------- 2.1.1 (#326): model usage of agents + limits
# Kalmido cannot see an agent's model usage, so the agent reports it (POST /api/v1/agent/usage, the MCP tool report_usage,
# or mcp/claude_usage_hook.py as a Claude Code Stop hook). A row holds numbers and ids only (model, token counts, the
# optional cost, the task / list / job it was for, an optional note of at most USAGE_NOTE_MAX characters), never prompt
# content. "Tokens" of a limit and of the dashboard = input + output + cache writes; cache reads (cheap, and huge in long
# sessions) are listed apart. LIMITS per agent (admins, agents.usage_limits json {period: day | month, metric: tokens |
# cost, soft?, hard?}; periods follow the server's time zone): the soft limit tells the admins (News + push, event
# "usage" of the notification settings) at 80 % and 100 %, the hard limit also tells them and then refuses the agent's
# API calls with 429 (except reporting usage, the status and GET /agent) until the period rolls over or an admin raises
# it; meanwhile the agent shows "limit reached". Each alert level fires once per period (agents.usage_alerted).
# WHO SEES WHAT (GET /api/agents/usage): admins every agent; others the agents they share a list with, and of their usage
# only what was reported for lists they see (participants: their tasks). Tasks and lists the viewer cannot see are
# counted without a name. The task panel shows "AI usage" on tasks with reported usage (only to who sees the task).
USAGE_NOTE_MAX, USAGE_MODEL_MAX = 200, 100
USAGE_INT_MAX, USAGE_COST_MAX = 10 ** 10, 10 ** 6       # per report and field
USAGE_KEEP_DAYS = _env_int("KALMIDO_USAGE_DAYS", 400)     # rows older than this are removed (watchdog, hourly)
USAGE_RANGE_MAX = 366                                    # days of GET /api/v1/agent/usage
USAGE_PERIODS, USAGE_METRICS, USAGE_GROUPS = ("day", "month"), ("tokens", "cost"), ("day", "task", "list", "model")
USAGE_FIELDS = ("model", "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "cost_usd", "task_id",
                "list_id", "job_id", "note")
USAGE_EXEMPT = {("POST", "agent/usage"), ("GET", "agent/usage"), ("PUT", "agent/status"), ("GET", "agent")}
USAGE_SUM = """COUNT(*) AS calls, COALESCE(SUM(input_tokens),0) AS input, COALESCE(SUM(output_tokens),0) AS output,
               COALESCE(SUM(cache_read_tokens),0) AS cache_read, COALESCE(SUM(cache_write_tokens),0) AS cache_write,
               SUM(cost_usd) AS cost"""
USAGE_CLEAN = {"at": 0.0}


def is_admin_id(c, uid):
    r = c.execute("SELECT is_admin, kind, disabled FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    return bool(r and r["is_admin"] and not r["disabled"] and (r["kind"] or "user") != "agent")


def usage_totals(r):
    """{tokens, input, output, cache_read, cache_write, cost (None = never reported), calls} of a USAGE_SUM row."""
    if not r:
        return {"tokens": 0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "cost": None, "calls": 0}
    return {"tokens": r["input"] + r["output"] + r["cache_write"], "input": r["input"], "output": r["output"],
            "cache_read": r["cache_read"], "cache_write": r["cache_write"],
            "cost": round(r["cost"], 6) if r["cost"] is not None else None, "calls": r["calls"]}


def usage_limits(a):
    """The agent's limits {period, metric, soft, hard} or None."""
    try:
        v = json.loads((a["usage_limits"] if a else "") or "null")
    except (ValueError, KeyError, IndexError):
        return None
    if not isinstance(v, dict) or v.get("period") not in USAGE_PERIODS or v.get("metric") not in USAGE_METRICS:
        return None
    if v.get("soft") is None and v.get("hard") is None:
        return None
    return {"period": v["period"], "metric": v["metric"], "soft": v.get("soft"), "hard": v.get("hard")}


def usage_limits_clean(v):
    """A limits object from an admin -> the stored json ('' = no limits). BadInput otherwise."""
    if v in (None, "", {}):
        return ""
    bad = BadInput(tr("Invalid value: {0}", "limits"))
    if not isinstance(v, dict) or any(k not in ("period", "metric", "soft", "hard") for k in v):
        raise bad
    if v.get("period", "day") not in USAGE_PERIODS or v.get("metric", "tokens") not in USAGE_METRICS:
        raise bad
    metric = v.get("metric", "tokens")
    out = {"period": v.get("period", "day"), "metric": metric}
    for k in ("soft", "hard"):
        x = v.get(k)
        if x in (None, ""):
            out[k] = None
            continue
        if isinstance(x, bool) or not isinstance(x, (int, float)) or x != x or x <= 0 or x > (USAGE_COST_MAX if metric == "cost" else USAGE_INT_MAX):
            raise BadInput(tr("Invalid value: {0}", k))
        out[k] = round(float(x), 2) if metric == "cost" else int(x)
    if out["soft"] is None and out["hard"] is None:
        return ""
    if out["soft"] is not None and out["hard"] is not None and out["soft"] > out["hard"]:
        raise BadInput(tr("The soft limit must not be above the hard limit"))
    return json.dumps(out, separators=(",", ":"))


def usage_period(period, now=None):
    """(key, first local day, end as an aware local datetime) of the current day / month."""
    now = now or local_now()
    d = now.date()
    if period == "month":
        first = d.replace(day=1)
        nxt = (first + timedelta(days=32)).replace(day=1)
        return first.strftime("%Y-%m"), first.isoformat(), datetime.combine(nxt, datetime.min.time(), TZ)
    return d.isoformat(), d.isoformat(), datetime.combine(d + timedelta(days=1), datetime.min.time(), TZ)


def usage_state(c, a):
    """Where agent a stands against its limits in the current period, or None without limits."""
    lim = usage_limits(a)
    if not lim:
        return None
    key, first, end = usage_period(lim["period"])
    r = c.execute(f"SELECT {USAGE_SUM} FROM agent_usage WHERE agent_id=? AND day>=?", (a["user_id"], first)).fetchone()
    t = usage_totals(r)
    used = round(t["cost"] or 0, 6) if lim["metric"] == "cost" else t["tokens"]
    pct = lambda x: round(100 * used / x, 1) if x else None  # noqa: E731
    return {**lim, "key": key, "used": used, "soft_pct": pct(lim["soft"]), "hard_pct": pct(lim["hard"]),
            "soft_reached": lim["soft"] is not None and used >= lim["soft"],
            "reached": lim["hard"] is not None and used >= lim["hard"], "resets_at": iso(end.astimezone(timezone.utc))}


def usage_fmt(v, metric, lg=None):
    """1234567 tokens -> "1,234,567 tokens" (German: 1.234.567 Tokens); cost -> "$1.23"."""
    if metric == "cost":
        return "$" + ("%.2f" % (v or 0))
    return tr("{0} tokens", fmt_int(v, lg), lg=lg)


def usage_block(c, aid):
    """The limit state when agent aid's hard limit is reached (its calls are refused), else None."""
    a = c.execute("SELECT user_id, usage_limits FROM agents WHERE user_id=?", (aid,)).fetchone()
    if not a or not a["usage_limits"]:
        return None
    st = usage_state(c, a)
    return st if st and st["reached"] else None


def usage_refused(c, aid):
    """api_authenticate: a 429 response for an agent over its hard limit (the exempt paths pass), else None."""
    if (request.method, request.path[len(API_PREFIX):].rstrip("/")) in USAGE_EXEMPT:
        return None
    st = usage_block(c, aid)
    if not st:
        return None
    end = parse_iso(st["resets_at"])
    wait = max(60, int((end - now_utc()).total_seconds()))
    until = end.astimezone(TZ).strftime("%Y-%m-%d %H:%M")
    used, lim = usage_fmt(st["used"], st["metric"]), usage_fmt(st["hard"], st["metric"])
    msg = (tr("Usage limit reached: {0} of {1} today. Calls are refused until {2} or until an admin raises the limit; reporting usage and the status still work.", used, lim, until)  # noqa: E501
           if st["period"] == "day" else
           tr("Usage limit reached: {0} of {1} this month. Calls are refused until {2} or until an admin raises the limit; reporting usage and the status still work.", used, lim, until))  # noqa: E501
    return v1_err(429, msg, {"Retry-After": str(wait)})


def usage_alerts(c, aid):
    """After a report: News + push to the admins when the agent crosses 80 % / 100 % of its soft limit or its hard limit
    (the highest new level only, each level once per period)."""
    a = c.execute("SELECT a.*, u.username, u.display_name FROM agents a JOIN users u ON u.id=a.user_id WHERE a.user_id=?",
                  (aid,)).fetchone()
    st = usage_state(c, a) if a else None
    if not st:
        return
    try:
        done = json.loads(a["usage_alerted"] or "{}")
    except ValueError:
        done = {}
    if not isinstance(done, dict) or done.get("period") != st["key"]:
        done = {"period": st["key"], "levels": []}
    levels = []
    if st["soft"] is not None:
        levels += [x for x, f in (("soft80", .8), ("soft100", 1.0)) if st["used"] >= st["soft"] * f]
    if st["reached"]:
        levels.append("hard")
    new = [x for x in levels if x not in done["levels"]]
    if not new:
        return
    done["levels"] = sorted(set(done["levels"]) | set(new))
    c.execute("UPDATE agents SET usage_alerted=? WHERE user_id=?", (json.dumps(done, separators=(",", ":")), aid))
    level = "hard" if "hard" in new else "soft100" if "soft100" in new else "soft80"
    name = a["display_name"] or a["username"]
    lim = st["hard"] if level == "hard" else st["soft"]
    data = {"agent_id": aid, "name": name, "level": level, "used": st["used"], "limit": lim, "metric": st["metric"],
            "period": st["period"]}
    print("agent", aid, "usage", level, st["used"], "/", lim, st["metric"], st["period"], flush=True)
    for r in c.execute("SELECT id FROM users WHERE is_admin=1 AND disabled=0 AND kind!='agent'").fetchall():
        uid = r["id"]
        s = usettings(c, uid)
        news_add(c, uid, "usage", data=data, actor=aid, row="usage", s=s if collab_on(s) else None)
        if not notif_ok(c, uid, s, "usage", "push") or not push_reachable(c, uid, s):
            continue
        lg = lang_of(s)
        used, lims = usage_fmt(st["used"], st["metric"], lg), usage_fmt(lim, st["metric"], lg)
        per = tr("today", lg=lg) if st["period"] == "day" else tr("this month", lg=lg)
        title = (tr("{0}: usage limit reached, calls blocked", name, lg=lg) if level == "hard" else
                 tr("{0}: soft usage limit reached", name, lg=lg) if level == "soft100" else
                 tr("{0}: 80 % of the usage limit", name, lg=lg))
        g.pushes.append((uid, title, f"{used} / {lims} · {per}", f"{PUBLIC_URL}/#agents", push_prio(s)))


def usage_cleanup(c, force=False):
    """Watchdog, at most hourly: usage rows older than USAGE_KEEP_DAYS go."""
    if not force and time.time() - USAGE_CLEAN["at"] < 3600:
        return 0
    USAGE_CLEAN["at"] = time.time()
    n = c.execute("DELETE FROM agent_usage WHERE day<?", ((local_now().date() - timedelta(days=USAGE_KEEP_DAYS)).isoformat(),)).rowcount
    c.commit()
    return n


def usage_int(b, k, required=False):
    if k not in b or b[k] is None:
        if required:
            raise BadInput(tr("Missing field: {0}", k))
        return 0
    v = b[k]
    if isinstance(v, bool) or not isinstance(v, int) or v < 0 or v > USAGE_INT_MAX:
        raise BadInput(tr("Invalid value: {0}", k))
    return v


@app.post("/api/v1/agent/usage")
@v1_view
def v1_agent_usage_post():
    """{model, input_tokens, output_tokens, cache_read_tokens?, cache_write_tokens?, cost_usd?, task_id?, list_id?, job_id?,
    note?} -- one usage report of the agent itself (numbers and ids only). list_id is taken from the task when missing."""
    v1_args(())
    aid = need_agent()
    b = v1_json()
    unknown = sorted(k for k in b if k not in USAGE_FIELDS)
    if unknown:
        raise UnknownFields(unknown)
    model = b.get("model")
    if not isinstance(model, str) or not model.strip() or len(model.strip()) > USAGE_MODEL_MAX or \
            any(ord(ch) < 32 for ch in model):
        raise BadInput(tr("Invalid value: {0}", "model"))
    f = {k: usage_int(b, k, k in ("input_tokens", "output_tokens"))
         for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")}
    cost = b.get("cost_usd")
    if cost is not None and (isinstance(cost, bool) or not isinstance(cost, (int, float)) or cost != cost or cost < 0 or cost > USAGE_COST_MAX):
        raise BadInput(tr("Invalid value: {0}", "cost_usd"))
    note = b.get("note") or ""
    if not isinstance(note, str) or len(note) > USAGE_NOTE_MAX:
        raise BadInput(tr("The note may have at most {0} characters", USAGE_NOTE_MAX))
    c = db()
    tid, lid, jid = b.get("task_id"), b.get("list_id"), b.get("job_id")
    for k, v in (("task_id", tid), ("list_id", lid), ("job_id", jid)):
        if v is not None and (isinstance(v, bool) or not isinstance(v, int) or v < 1):
            raise BadInput(tr("Invalid value: {0}", k))
    if tid is not None:
        t = c.execute("SELECT list_id FROM tasks WHERE id=?", (tid,)).fetchone()
        if not t or not task_visible(c, tid, aid):
            raise BadInput(tr("Invalid value: {0}", "task_id"))
        if lid is not None and lid != t["list_id"]:
            raise BadInput(tr("The task is not in this list"))
        lid = t["list_id"]
    elif lid is not None and not list_role(c, lid, aid):
        raise BadInput(tr("Invalid value: {0}", "list_id"))
    if jid is not None and not c.execute("SELECT 1 FROM agent_jobs WHERE id=? AND agent_id=?", (jid, aid)).fetchone():
        raise BadInput(tr("Invalid value: {0}", "job_id"))
    ts = iso(now_utc())
    day = local_now().date().isoformat()
    rid = c.execute("""INSERT INTO agent_usage(agent_id,model,input_tokens,output_tokens,cache_read_tokens,cache_write_tokens,
                       cost_usd,task_id,list_id,job_id,note,day,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (aid, model.strip(), f["input_tokens"], f["output_tokens"], f["cache_read_tokens"], f["cache_write_tokens"],
                     None if cost is None else float(cost), tid, lid, jid, note.strip(), day, ts)).lastrowid
    usage_alerts(c, aid)
    if tid:
        bump(c)  # the task panel's "AI usage" line
    c.commit()
    return jsonify(id=rid, created_at=ts, day=day, model=model.strip(), **f, cost_usd=cost, task_id=tid, list_id=lid, job_id=jid,
                   note=note.strip(), limit=usage_state(c, agent_row(c, aid))), 201


@app.get("/api/v1/agent/usage")
@v1_view
def v1_agent_usage_get():
    """?from=&to= (local days YYYY-MM-DD, default the last 30 days) &group=day|task|list|model -- the agent's own usage."""
    a = v1_args(("from", "to", "group"))
    aid = need_agent()
    c = db()
    grp = a.get("group", "day")
    if grp not in USAGE_GROUPS:
        raise BadInput(tr("Invalid value: {0}", "group"))
    to = a.get("to") or local_now().date().isoformat()
    if not valid_date(to):
        raise BadInput(tr("Invalid value: {0}", "to"))
    frm = a.get("from") or (date.fromisoformat(to) - timedelta(days=29)).isoformat()
    if not valid_date(frm) or frm > to or (date.fromisoformat(to) - date.fromisoformat(frm)).days >= USAGE_RANGE_MAX:
        raise BadInput(tr("Invalid value: {0}", "from"))
    col = {"day": "day", "task": "task_id", "list": "list_id", "model": "model"}[grp]
    rows = c.execute(f"""SELECT {col} AS k, {USAGE_SUM} FROM agent_usage WHERE agent_id=? AND day>=? AND day<=?
                         GROUP BY {col} ORDER BY {col}""", (aid, frm, to)).fetchall()
    out = []
    for r in rows:
        d = {grp if grp in ("day", "model") else grp + "_id": r["k"], **usage_totals(r)}
        if grp in ("task", "list"):
            d["title" if grp == "task" else "name"] = None
        if grp == "task" and r["k"]:
            t = c.execute("SELECT title FROM tasks WHERE id=?", (r["k"],)).fetchone()
            d["title"] = t["title"] if t and task_visible(c, r["k"], aid) else None
        if grp == "list" and r["k"]:
            lr = c.execute("SELECT name FROM lists WHERE id=?", (r["k"],)).fetchone()
            d["name"] = lr["name"] if lr and list_role(c, r["k"], aid) else None
        out.append(d)
    if grp in ("task", "list"):
        out.sort(key=lambda d: -d["tokens"])
    tot = c.execute(f"SELECT {USAGE_SUM} FROM agent_usage WHERE agent_id=? AND day>=? AND day<=?", (aid, frm, to)).fetchone()
    return jsonify(data=out, totals=usage_totals(tot), group=grp, **{"from": frm, "to": to},
                   limit=usage_state(c, agent_row(c, aid)))


# ---- 2.2.1 (#358): the agents' audit log. Every request made with an AGENT's token (/api/v1: the REST API, the agent
# endpoints and whatever an MCP server calls on its behalf) is one row: time, agent, method, the ROUTE TEMPLATE
# (/api/v1/tasks/{tid}, never the query or a body), status code, task / list id when the path or the JSON body names one,
# duration. Denied calls (401 / 403 / 429) are logged too, e.g. while the agent is paused (kill switch). The request only
# appends a tuple to a list in memory; a writer thread stores them in batches every AUDIT_FLUSH_S seconds (cheap on a
# small board), reading the log stores what is pending first. Rows older than KALMIDO_AUDIT_DAYS days go (watchdog,
# hourly; 0 = no log at all). Admins read it: Settings > AI colleague > Activity log, GET /api/admin/agents/audit (all),
# GET /api/admin/agents/{id}/audit, ?format=csv, and GET /api/v1/admin/agents/{id}/audit (token scope admin-read).
AUDIT_DAYS = _env_int("KALMIDO_AUDIT_DAYS", 90, lo=0)
AUDIT_FLUSH_S = 2.0
AUDIT_PAGE, AUDIT_PAGE_MAX, AUDIT_CSV_MAX = 100, 500, 20000
AUDIT_DENIED = (401, 403, 429)
AUDIT_STATUS = ("2xx", "3xx", "4xx", "5xx", "denied")
AUDIT_POLL = ("GET", "/api/v1/agent/events")            # 2.5.1 (#393): event polling, hidden in the web log by default (hide_poll=1)
_AUDIT = {"rows": [], "lock": threading.Lock(), "wlock": threading.Lock(), "thread": None, "clean_at": 0.0}
_AUDIT_EVT = threading.Event()
_RULE_ARG = re.compile(r"<(?:[^:<>]+:)?([^<>]+)>")


def audit_route(rule):
    """/api/v1/tasks/<int:tid> -> /api/v1/tasks/{tid}"""
    return _RULE_ARG.sub(r"{\1}", rule.rule)[:120] if rule is not None else "(no route)"


def _audit_id(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and 0 < v < 2 ** 53 else None


@app.after_request
def audit_after(resp):
    aid = g.get("audit_aid")
    if not aid or AUDIT_DAYS <= 0:
        return resp
    try:
        va = request.view_args or {}
        b = request.get_json(silent=True) if request.is_json else None
        b = b if isinstance(b, dict) else {}
        tid = _audit_id(va.get("tid")) or _audit_id(b.get("task_id"))
        lid = _audit_id(va.get("lid")) or _audit_id(b.get("list_id"))
        t = now_utc()
        row = (aid, iso_ms(t), t.astimezone(TZ).date().isoformat(), request.method[:8], audit_route(request.url_rule),
               resp.status_code, tid, lid, int((time.monotonic() - g.get("audit_t0", time.monotonic())) * 1000),
               str(g.get("scope_need") or "")[:20])  # 2.15.0 (#479): the scope the request needed
        with _AUDIT["lock"]:
            _AUDIT["rows"].append(row)
            n = len(_AUDIT["rows"])
            if _AUDIT["thread"] is None:
                _AUDIT["thread"] = threading.Thread(target=audit_loop, daemon=True)
                _AUDIT["thread"].start()
        if n >= 200:
            _AUDIT_EVT.set()
    except Exception as e:  # noqa: BLE001  the log must never break a request
        print("audit log error:", type(e).__name__, e, flush=True)
    return resp


def audit_flush():
    """Stores the pending rows (own connection, one transaction). Returns how many."""
    with _AUDIT["wlock"]:
        with _AUDIT["lock"]:
            rows, _AUDIT["rows"] = _AUDIT["rows"], []
        if not rows:
            return 0
        c = connect()
        try:
            c.executemany("INSERT INTO agent_audit(agent_id,at,day,method,route,status,task_id,list_id,ms,scope) VALUES(?,?,?,?,?,?,?,?,?,?)", rows)
            c.commit()
        finally:
            c.close()
        return len(rows)


def audit_loop():
    while True:
        _AUDIT_EVT.wait(AUDIT_FLUSH_S)
        _AUDIT_EVT.clear()
        try:
            with GATE.bg():
                audit_flush()
        except Exception as e:  # noqa: BLE001
            print("audit log writer error:", type(e).__name__, e, flush=True)
            time.sleep(5)


def audit_cleanup(c, force=False):
    """Watchdog, at most hourly: rows older than AUDIT_DAYS days go (all of them with AUDIT_DAYS 0)."""
    if not force and time.time() - _AUDIT["clean_at"] < 3600:
        return 0
    _AUDIT["clean_at"] = time.time()
    first = (local_now().date() - timedelta(days=max(AUDIT_DAYS, 0))).isoformat()
    n = c.execute("DELETE FROM agent_audit WHERE day<?" if AUDIT_DAYS > 0 else "DELETE FROM agent_audit", (first,) if AUDIT_DAYS > 0 else ()).rowcount
    c.commit()
    return n


def audit_query(c, a, aid=None, csv_out=False):
    """Rows of the log for the filters in a (agent_id, status, day, cursor / before, limit). aid fixes the agent."""
    where, args = [], []
    if aid is None and a.get("agent_id"):
        aid = as_int(a.get("agent_id"), "agent_id", 1)
    if aid is not None:
        where.append("agent_id=?")
        args.append(aid)
    st = a.get("status") or ""
    if st:
        if st not in AUDIT_STATUS:
            raise BadInput(tr("Invalid value: {0}", "status"))
        if st == "denied":
            where.append(f"status IN ({','.join(map(str, AUDIT_DENIED))})")
        else:
            where.append("status>=? AND status<?")
            args += [int(st[0]) * 100, int(st[0]) * 100 + 100]
    if a.get("day"):
        if not valid_date(a.get("day")):
            raise BadInput(tr("Invalid value: {0}", "day"))
        where.append("day=?")
        args.append(a.get("day"))
    if a.get("hide_poll") in ("1", "true"):  # 2.5.1 (#393): without the event polling (most of the rows)
        where.append("NOT (method=? AND route=?)")
        args += list(AUDIT_POLL)
    before = a.get("before") or a.get("cursor")
    if before and not csv_out:
        where.append("id<?")
        args.append(as_int(before, "cursor", 1))
    limit = AUDIT_CSV_MAX if csv_out else as_int(a.get("limit", AUDIT_PAGE), "limit", 1, AUDIT_PAGE_MAX)
    audit_flush()
    rows = c.execute(f"SELECT * FROM agent_audit {'WHERE ' + ' AND '.join(where) if where else ''} ORDER BY id DESC LIMIT ?",
                     (*args, limit + 1)).fetchall()
    more = len(rows) > limit
    return rows[:limit], more


def audit_names(c):
    return {r["id"]: r["display_name"] or r["username"] for r in c.execute("SELECT id, username, display_name FROM users WHERE kind='agent'")}


def audit_dict(r, names):
    return {"id": r["id"], "at": r["at"], "agent_id": r["agent_id"], "agent_name": names.get(r["agent_id"], f"#{r['agent_id']}"),
            "method": r["method"], "route": r["route"], "status": r["status"], "task_id": r["task_id"], "list_id": r["list_id"],
            "ms": r["ms"], "denied": r["status"] in AUDIT_DENIED,
            "scope": (r["scope"] if "scope" in r.keys() else "") or None}  # 2.15.0 (#479): the permission the request needed


def audit_csv(rows, names, aid=None):
    lg = lang()
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";" if dec_comma(lg) else ",", lineterminator="\r\n")
    w.writerow([tr("Time"), tr("Agent"), tr("Method"), tr("Route"), tr("Status"), tr("Task"), tr("List"), tr("Duration (ms)"), tr("Permission")])
    for r in rows:
        w.writerow([parse_iso(r["at"]).astimezone(TZ).strftime("%Y-%m-%d %H:%M:%S"), _csv_cell(names.get(r["agent_id"], f"#{r['agent_id']}")),
                    r["method"], _csv_cell(r["route"]), r["status"], r["task_id"] or "", r["list_id"] or "", r["ms"],
                    (r["scope"] if "scope" in r.keys() else "") or ""])
    name = re.sub(r"[^A-Za-z0-9._-]", "_", f"{tr('agent-activity|file')}-{aid or 'all'}-{local_now().date().isoformat()}.csv")
    return Response("\ufeff" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@app.get("/api/admin/agents/audit")
@app.get("/api/admin/agents/<int:aid>/audit")
def admin_agents_audit(aid=None):
    """The audit log (admins): ?agent_id= (all agents: the first route), status= 2xx|3xx|4xx|5xx|denied, day=YYYY-MM-DD,
    hide_poll=1 (2.5.1: without GET /api/v1/agent/events), before= (id of the last row seen), limit= 1-500 (default 100),
    format=csv (up to AUDIT_CSV_MAX rows, all pages). JSON rows carry task_title / list_name where the admin sees them,
    the first page `today` {requests, denied, polls}."""
    c = db()
    if aid is not None:
        need_agent_admin(c, aid)
    else:
        need_admin()
    csv_out = request.args.get("format") == "csv"
    rows, more = audit_query(c, request.args, aid, csv_out)
    names = audit_names(c)
    if csv_out:
        return audit_csv(rows, names, aid or request.args.get("agent_id"))
    data = [audit_dict(r, names) for r in rows]
    # 2.5.1 (#393): task / list titles for the rows, only where the viewing admin sees that task / list themselves
    uid, tt, ln = me(), {}, {}
    for d in data:
        tid, lid = d["task_id"], d["list_id"]
        if tid and tid not in tt:
            tt[tid] = None
            if task_visible(c, tid, uid):
                r = c.execute("SELECT title FROM tasks WHERE id=?", (tid,)).fetchone()
                tt[tid] = r["title"] if r else None
        if lid and lid not in ln:
            ln[lid] = None
            if list_role(c, lid, uid):
                r = c.execute("SELECT name FROM lists WHERE id=?", (lid,)).fetchone()
                ln[lid] = r["name"] if r else None
        d["task_title"], d["list_name"] = tt.get(tid) if tid else None, ln.get(lid) if lid else None
    out = dict(data=data, next_before=rows[-1]["id"] if more and rows else None,
               agents=[{"id": k, "name": v} for k, v in sorted(names.items())], days=AUDIT_DAYS, statuses=list(AUDIT_STATUS))
    if not request.args.get("before"):  # 2.5.1 (#393): today's summary (the selected agent), polling counted apart
        w, wa = "day=?", [local_now().date().isoformat()]
        sel = aid if aid is not None else (as_int(request.args["agent_id"], "agent_id", 1) if request.args.get("agent_id") else None)
        if sel is not None:
            w += " AND agent_id=?"
            wa.append(sel)
        r = c.execute(f"""SELECT COUNT(*) n, COALESCE(SUM(status IN ({','.join(map(str, AUDIT_DENIED))})), 0) den,
                                 COALESCE(SUM(method=? AND route=?), 0) poll FROM agent_audit WHERE {w}""", (*AUDIT_POLL, *wa)).fetchone()
        out["today"] = {"requests": r["n"], "denied": r["den"], "polls": r["poll"]}
    return jsonify(**out)


@app.get("/api/v1/admin/agents/<int:aid>/audit")
@v1_view
def v1_admin_agent_audit(aid):
    """The same for a token with scope admin-read (checked in api_authenticate): {data, next_cursor}."""
    a = v1_args(("status", "day", "cursor", "limit"))
    c = db()
    if not agent_row(c, aid):
        raise Denied(404)
    rows, more = audit_query(c, a, aid)
    names = audit_names(c)
    return jsonify(data=[audit_dict(r, names) for r in rows], next_cursor=str(rows[-1]["id"]) if more and rows else None)


@app.get("/api/agents/usage")
def agents_usage_get():
    """The usage dashboard (Settings > AI colleague, the Agents view). ?agent_id= one agent (default all), ?days= 7-90 for
    the chart, the top tasks, the lists and the models (default 30). Admins: every agent; others: the agents they share a
    list with, counting only what was reported for lists they see (participants: tasks they see)."""
    if is_agent(g.user):
        raise Denied(403)
    c = db()
    uid = me()
    adm = is_admin_id(c, uid)
    days = as_int(request.args.get("days", 30), "days", 7, 90)
    sel = as_int(request.args["agent_id"], "agent_id", 1) if request.args.get("agent_id") else None
    ags = [a for a in c.execute("""SELECT a.*, u.username, u.display_name, u.avatar, u.disabled FROM agents a JOIN users u
                                   ON u.id=a.user_id WHERE u.kind='agent' ORDER BY u.id""").fetchall()
           if adm or agent_shares(c, a["user_id"], uid)]
    ids = [a["user_id"] for a in ags]
    today = local_now().date()
    d_win, d30, d7 = (today - timedelta(days=days - 1)).isoformat(), (today - timedelta(days=29)).isoformat(), \
        (today - timedelta(days=6)).isoformat()
    rows = c.execute(f"""SELECT agent_id, task_id, list_id, model, day, input_tokens, output_tokens, cache_read_tokens,
                                cache_write_tokens, cost_usd FROM agent_usage
                         WHERE agent_id IN ({','.join('?' * len(ids)) or 'NULL'}) AND day>=?""",
                     (*ids, min(d_win, d30))).fetchall() if ids else []
    roles, tvis = {}, {}

    def role(lid):
        if lid not in roles:
            roles[lid] = list_role(c, lid, uid) if lid else None
        return roles[lid]

    def sees_task(tid):
        if tid not in tvis:
            tvis[tid] = bool(tid) and task_visible(c, tid, uid)
        return tvis[tid]
    if not adm:  # only what was reported for lists I see (a participant: for tasks I see)
        rows = [r for r in rows if r["list_id"] and role(r["list_id"]) and (role(r["list_id"]) != "participant" or sees_task(r["task_id"]))]

    def acc(dst, r):
        dst["input"] += r["input_tokens"]
        dst["output"] += r["output_tokens"]
        dst["cache_read"] += r["cache_read_tokens"]
        dst["cache_write"] += r["cache_write_tokens"]
        dst["tokens"] += r["input_tokens"] + r["output_tokens"] + r["cache_write_tokens"]
        dst["calls"] += 1
        if r["cost_usd"] is not None:
            dst["cost"] = round((dst["cost"] or 0) + r["cost_usd"], 6)
    zero = lambda: {"tokens": 0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "cost": None, "calls": 0}  # noqa: E731
    tot = {i: {"today": zero(), "d7": zero(), "d30": zero()} for i in ids}
    td = today.isoformat()
    for r in rows:
        t = tot[r["agent_id"]]
        if r["day"] >= d30:
            acc(t["d30"], r)
        if r["day"] >= d7:
            acc(t["d7"], r)
        if r["day"] == td:
            acc(t["today"], r)
    win = [r for r in rows if r["day"] >= d_win and (sel is None or r["agent_id"] == sel)]
    per_day = {(today - timedelta(days=days - 1 - i)).isoformat(): zero() for i in range(days)}
    tasks, lists, models = {}, {}, {}
    for r in win:
        acc(per_day[r["day"]], r) if r["day"] in per_day else None
        tk = r["task_id"] if r["task_id"] and sees_task(r["task_id"]) else (-1 if r["task_id"] else None)
        if tk is not None:
            acc(tasks.setdefault(tk, zero()), r)
        lk = r["list_id"] if r["list_id"] and role(r["list_id"]) else (-1 if r["list_id"] else 0)
        acc(lists.setdefault(lk, zero()), r)
        acc(models.setdefault(r["model"], zero()), r)
    trows = []
    for tk, v in sorted(tasks.items(), key=lambda x: -x[1]["tokens"])[:10]:
        if tk == -1:
            trows.append({"task_id": None, "hidden": True, "title": None, "list_id": None, **v})
        else:
            t = c.execute("SELECT title, list_id FROM tasks WHERE id=?", (tk,)).fetchone()
            trows.append({"task_id": tk, "title": t["title"] if t else None, "list_id": t["list_id"] if t else None, **v})
    lrows = []
    for lk, v in sorted(lists.items(), key=lambda x: -x[1]["tokens"]):
        if lk > 0:
            lr = c.execute("SELECT name, is_inbox FROM lists WHERE id=?", (lk,)).fetchone()
            lrows.append({"list_id": lk, "name": (tr("Inbox") if lr and lr["is_inbox"] and inbox_default(lr["name"]) else lr["name"]) if lr else None, **v})
        else:
            lrows.append({"list_id": None, "hidden": lk == -1, "none": lk == 0, "name": None, **v})
    out = []
    for a in ags:
        d = {"id": a["user_id"], "name": a["display_name"] or a["username"], "enabled": agent_active(a),
             "avatar": avatar_url(c.execute("SELECT * FROM users WHERE id=?", (a["user_id"],)).fetchone()),
             "totals": tot[a["user_id"]], "limit_reached": bool(usage_block(c, a["user_id"]))}
        if adm:
            d["limit"] = usage_state(c, a)
        out.append(d)
    return jsonify(agents=out, admin=adm, days=days, agent_id=sel,
                   per_day=[{"day": k, **v} for k, v in per_day.items()], tasks=trows, lists=lrows,
                   models=[{"model": k, **v} for k, v in sorted(models.items(), key=lambda x: -x[1]["tokens"])],
                   cost=any(r["cost_usd"] is not None for r in rows))


@app.post("/api/v1/comments/<int:cid>/reactions")
@v1_view
def v1_comment_react(cid):
    """{emoji: up|down|heart or any single emoji} -- adds my reaction (idempotent)."""
    v1_args(())
    need_collab()
    v1_feature("collab")
    c = db()
    k, _ = need_live_comment(c, cid)
    b = v1_json()
    if set(b) - {"emoji"}:
        raise BadInput(tr("Expected {0}", '{"emoji": "up"}'))
    if k["user_id"] == me():  # 2.23.0 (#823)
        raise BadInput(tr("You cannot react to your own message"))
    react(c, k, me(), clean_emoji(b.get("emoji")), True)
    bump(c)
    c.commit()
    return jsonify(v1_comment_one(c, cid))


@app.delete("/api/v1/comments/<int:cid>/reactions/<emoji>")
@v1_view
def v1_comment_unreact(cid, emoji):
    v1_args(())
    need_collab()
    v1_feature("collab")
    c = db()
    k, _ = need_live_comment(c, cid)
    react(c, k, me(), clean_emoji(emoji), False)
    bump(c)
    c.commit()
    return jsonify(v1_comment_one(c, cid))


def v1_comment_one(c, cid):
    r = c.execute("SELECT * FROM comments WHERE id=?", (cid,)).fetchone()
    d = with_reactions(c, [{**comment_dict(r, att_dicts(c, "comment_id=?", (cid,))), "task_id": r["task_id"]}])[0]
    return v1_comment(c, d, user_names(c, [r["user_id"]]))


def v1_ltag(c, r):
    n = c.execute("""SELECT COUNT(*), COALESCE(SUM(CASE WHEN t.status=0 THEN 1 ELSE 0 END),0) FROM task_list_tags x JOIN tasks t ON t.id=x.task_id
                     WHERE x.tag_id=? AND t.deleted_at IS NULL AND t.list_id=?""", (r["id"], r["list_id"])).fetchone()
    return {"id": r["id"], "list_id": r["list_id"], "name": r["name"], "color": r["color"], "tasks": n[0], "open": n[1]}


@app.get("/api/v1/lists/<int:lid>/tags")
@v1_view
def v1_list_tags(lid):
    v1_args(())
    c = db()
    need_list(c, lid, write=False)
    return jsonify(data=[v1_ltag(c, r) for r in c.execute("SELECT * FROM list_tags WHERE list_id=? ORDER BY sort, name COLLATE NOCASE", (lid,))],
                   next_cursor=None)


@app.post("/api/v1/lists/<int:lid>/tags")
@v1_view
def v1_list_tag_create(lid):
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("name", "color"))
    j = v1_call(ltag_create, lid, body=b)
    c = db()
    return jsonify(v1_ltag(c, c.execute("SELECT * FROM list_tags WHERE id=?", (j["id"],)).fetchone())), 201


@app.patch("/api/v1/lists/<int:lid>/tags/<tag_id>")  # not <int:>: the spec path keeps its own name
@v1_view
def v1_list_tag_update(lid, tag_id):
    v1_args(())
    tag_id = as_int(tag_id, "tag_id", 1)
    b = v1_json()
    reject_unknown(b, ("name", "color"))
    c = db()
    if not c.execute("SELECT 1 FROM list_tags WHERE id=? AND list_id=?", (tag_id, lid)).fetchone():
        raise Denied(404)
    v1_call(ltag_update, tag_id, body=b)
    return jsonify(v1_ltag(c, c.execute("SELECT * FROM list_tags WHERE id=?", (tag_id,)).fetchone()))


@app.delete("/api/v1/lists/<int:lid>/tags/<tag_id>")  # not <int:>: the spec path keeps its own name
@v1_view
def v1_list_tag_delete(lid, tag_id):
    v1_args(())
    tag_id = as_int(tag_id, "tag_id", 1)
    c = db()
    if not c.execute("SELECT 1 FROM list_tags WHERE id=? AND list_id=?", (tag_id, lid)).fetchone():
        raise Denied(404)
    v1_call(ltag_delete, tag_id, body={})
    return Response(status=204)


def agent_spec(paths, schemas, op, ok, errs, ref, q, pid, nul, page):
    """2.0.0 additions to the OpenAPI document."""
    ev = {"type": "object", "properties": {"id": {"type": "string"}, "seq": {"type": "integer"}, "event": {"type": "string", "enum": list(AGENT_EVENTS)},
                                           "created_at": {"type": "string", "format": "date-time"}, "agent_id": {"type": "integer"},
                                           "actor": {"oneOf": [{"type": "null"}, {"type": "object"}]}, "via": {"type": "string"},
                                           "data": {"type": "object"}}}
    job = {"type": "object", "properties": {k: {"type": "integer"} for k in ("id", "agent_id")} | {
        "task_id": nul("integer"), "user_id": nul("integer"), "title": {"type": "string"}, "state": {"type": "string", "enum": list(JOB_STATES)},
        "log": {"type": "string"}, "action": nul("string", enum=[*JOB_ACTIONS, None]), "created_at": {"type": "string"}, "updated_at": {"type": "string"},
        "kind": nul("string", enum=[*PROP_KINDS, None]), "proposal_state": nul("string", enum=[*PROP_STATES, None])}}
    agent = {"type": "object", "properties": {"id": {"type": "integer"}, "name": {"type": "string"}, "status": {"type": "string", "enum": list(AGENT_STATUSES)},
                                              "status_text": {"type": "string"}, "status_task": nul("integer"),
                                              "job_tasks": {"type": "array", "items": {"type": "integer"}}, "running": {"type": "integer"}, "waiting": {"type": "integer"},
                                              "enabled": {"type": "boolean"}}}
    msg = {"type": "object", "properties": {"id": {"type": "integer"}, "user_id": {"type": "integer"}, "from": {"type": "string", "enum": ["user", "agent"]},
                                            "body": {"type": "string"}, "task_id": nul("integer"), "created_at": {"type": "string"},
                                            "delivered_at": nul("string", description="2.7.2 (#422): when the agent fetched the person's message (event poll, MCP, webhook, chat read); null = not yet / an agent message"),
                                            "asks": {"type": "boolean", "description": "2.13.0: an agent message that asks something (a question mark outside code and links); only there a 👍 / 👎 of the person is an approval / rejection"},
                                            "choices": nul("object", description="2.28.0 (#1005): answer buttons of an agent message: {choices: [{id, label, style?: primary | danger}], multi}"),
                                            "choice": nul("object", description="2.28.0 (#1005): the person's answer {ids, at, user_id}; null while open. The agent gets the event chat_choice"),
                                            "choice_state": nul("string", enum=["open", "answered", "expired", "withdrawn", None],
                                                                description="2.30.0 (#1037): open = the buttons can be pressed; expired = a newer message came (a permission "
                                                                            "question: its expires_at passed); withdrawn = the agent took them back. choices.permission: a "
                                                                            "permission question (#1041), choices.expires_at, choices.outcome"),
                                            "attachments": {"type": "array", "description": "2.13.1 (#465): images / files of the message; download with GET /chat-attachments/{id}",
                                                            "items": {"type": "object", "properties": {"id": {"type": "integer"}, "name": {"type": "string"},
                                                                                                       "mime": {"type": "string"}, "size": {"type": "integer"},
                                                                                                       "url": {"type": "string"}}}},
                                            "reactions": {"type": "array", "description": "2.7.2 (#421)", "items": {"type": "object", "properties": {
                                                "emoji": {"type": "string"}, "count": {"type": "integer"},
                                                "users": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "integer"}, "name": {"type": "string"}}}}}}}}}
    chat_rx_in = {"type": "object", "required": ["emoji"], "additionalProperties": False, "properties": {
        "emoji": {"type": "string", "description": "up, down, heart or one emoji"}, "on": {"type": "boolean", "description": "Set (true) / remove (false); missing = toggle"}}}
    chat_rx_out = {"type": "object", "properties": {"ok": {"type": "boolean"}, "message_id": {"type": "integer"}, "reactions": {"type": "array", "items": {"type": "object"}},
                                                    "approval": nul("string", enum=["approved", "rejected", None])}}
    ltag = {"type": "object", "properties": {"id": {"type": "integer"}, "list_id": {"type": "integer"}, "name": {"type": "string"},
                                             "color": {"type": "string"}, "tasks": {"type": "integer"}, "open": {"type": "integer"}}}
    sug = {"type": "object", "additionalProperties": False, "properties": {
        "title": {"type": "string"}, "notes": {"type": "string"}, "section_id": {"type": "integer"},
        "list_tags": {"type": "array", "items": {"type": "string"}}, "priority": {"type": "string", "enum": list(PRIO_VALUES)}}}
    agent["properties"]["limit_reached"] = {"type": "boolean", "description": "Its hard usage limit is reached (2.1.1)"}
    agent["properties"].update(  # 2.4.1 (#375 / #377)
        online=nul("boolean", description="false: no event poll for 5 minutes; null: unknown (webhook, never polled)"),
        last_poll_at=nul("string"), typing={"type": "number", "description": "Seconds left of its typing signal to you in the chat"},
        host={"type": "object", "description": "2.32.0 (#1079): what the host last reported (PUT /agent/status): model, permission_mode, "
                                              "host_permission_mode, at"},
        runtime={"type": "object", "description": "GET /agent only: what the agent host applies (docs/AGENTS.md, Runtime settings)",
                 "properties": {"model": {"type": "string"}, "autocompact": {"type": "boolean"}, "autocompact_pct": nul("integer"),
                                "nightly_reset": {"type": "string", "description": "HH:MM in the server time zone, empty = off"},
                                "permission_mode": {"type": "string", "enum": ["", "ask", "auto"],
                                                    "description": "2.29.0: actions outside the allow list: ask the person in the chat / the host's safety check decides; empty = host default"},
                                "reset_seq": {"type": "integer", "description": "Raised by Reset now (event reset)"},
                                "timezone": {"type": "string"}}})
    tot = {"type": "object", "properties": {k: {"type": "integer"} for k in ("tokens", "input", "output", "cache_read", "cache_write", "calls")}
           | {"cost": nul("number")}}
    lim = {"oneOf": [{"type": "null"}, {"type": "object", "properties": {
        "period": {"type": "string", "enum": list(USAGE_PERIODS)}, "metric": {"type": "string", "enum": list(USAGE_METRICS)},
        "soft": nul("number"), "hard": nul("number"), "used": {"type": "number"}, "reached": {"type": "boolean"},
        "soft_reached": {"type": "boolean"}, "resets_at": {"type": "string", "format": "date-time"}}}]}
    schemas.update({"UsageReport": {"type": "object", "properties": {"id": {"type": "integer"}, "day": {"type": "string"},
                                                                     "created_at": {"type": "string"}, "limit": lim}},
                    "UsagePage": {"type": "object", "properties": {"data": {"type": "array", "items": tot}, "totals": tot,
                                                                   "group": {"type": "string"}, "from": {"type": "string"},
                                                                   "to": {"type": "string"}, "limit": lim}}})
    schemas.update({"AgentEvent": ev, "Job": job, "Agent": agent, "ChatMessage": msg, "ListTag": ltag, "TidyInput": sug,
                    "JobPage": page("Job"), "AgentPage": page("Agent"), "ListTagPage": page("ListTag"),
                    "EventPage": {"type": "object", "properties": {"data": {"type": "array", "items": ref("AgentEvent")}, "cursor": {"type": "integer"},
                                                                   "has_more": {"type": "boolean"}, "busy": {"type": "boolean"}, "waited": {"type": "number"}}},
                    "ChatPage": {"type": "object", "properties": {"data": {"type": "array", "items": ref("ChatMessage")}, "cursor": {"type": "integer"},
                                                                  "has_more": {"type": "boolean"}}}})
    schemas["Task"]["properties"]["list_tags"] = {"type": "array", "items": {"type": "string"}, "description": "Tags of the list, shared by its members"}
    schemas["TaskInput"]["properties"]["list_tags"] = {"type": "array", "items": {"type": "string"},
                                                       "description": "List tags by name; missing ones are created when you may change the list"}
    schemas["List"]["properties"]["tags"] = {"type": "array", "items": {"type": "object"}}
    schemas["List"]["properties"]["agent_tidy"] = {"type": "string", "enum": list(TIDY_MODES)}
    schemas["List"]["properties"]["tidy_agent_id"] = nul("integer", description="The one agent that tidies up the list (2.4.1)")
    schemas["List"]["properties"]["listen_agent_ids"] = {"type": "array", "items": {"type": "integer"}, "description":
                                                         "2.13.1 (#471) / 2.30.0 (#1034): agents that listen in: every comment of a person and every task "
                                                         "created in / moved into this list (task_added, tasks_added). Default: every agent in software lists, none elsewhere"}
    schemas["List"]["properties"]["listen_default"] = {"type": "boolean", "description": "2.30.0 (#1034): agents listen in here by default "
                                                       "(project type software); the owner can switch it per list"}
    schemas["List"]["properties"]["icon"] = {"type": "string", "description": "URL of the list's own icon (2.0.2), empty = none"}
    schemas["List"]["properties"]["project_type"] = nul("string", enum=[*PTYPES, None],
                                                        description="2.18.0 (#408): agency | software | private; null = none (a plain list or project)")
    schemas["Comment"]["properties"]["reactions"] = {"type": "array", "items": {"type": "object"}}
    schemas["Comment"]["properties"]["suggestion"] = {"oneOf": [{"type": "null"}, {"type": "object"}]}
    schemas["CommentInput"]["properties"]["suggestion"] = {"oneOf": [ref("TidyInput"), {"type": "object", "description":
        "2.2.0 merge request {kind: merge_request, pr_url, summary?}; 2.26.0 (#949) approval requests without a pull request: "
        "{kind: integrate, source, target? (main), summary?, evidence} / {kind: deploy, summary?, evidence, integrations?: "
        "[comment ids of approved integrate requests]} -- deploy also carries the checklist (open tasks with the list tag deploy). "
        "An approver decides with 👍 / 👎 (POST /comments/{id}/decide in the app); the result arrives as a reaction event with data.gate"}]}
    schemas["Tag"]["properties"].update(kind={"type": "string", "enum": ["personal", "list"]}, list_id={"type": "integer"},
                                         id={"type": "integer"}, color={"type": "string"})
    AG, W = "Agents", "write"
    lp = pid("id", "List id")
    paths.update({
        "/agent": {"get": op("The agent itself: status, jobs, event cursor (agent tokens only)", AG, ok(ref("Agent")) | errs("403"))},
        "/agent/status": {"put": op("Report the agent's status", AG, ok(ref("Agent")) | errs("400", "403"), scope=W, body={
            "type": "object", "required": ["status"], "properties": {"status": {"type": "string", "enum": list(AGENT_STATUSES)}, "text": {"type": "string"},
                                                                  "task_id": nul("integer"),
                                                                  # 2.32.0 (#1079)
                                                                  "model": {"type": "string", "maxLength": 80, "description": "2.32.0: the model the host really runs, "
                                                                            "as people know it (e.g. \"Opus 5.5\"); shown in the chat header"},
                                                                  "permission_mode": {"type": "string", "enum": ["", "ask", "auto"], "description":
                                                                                      "2.32.0: the permission mode the current run really uses"},
                                                                  "host_permission_mode": {"type": "string", "enum": ["", "ask", "auto"], "description":
                                                                                           "2.32.0: the host's own default (shown as \"Host default (Auto)\")"}}})},
        # 2.32.0 (#1081): steps (prose between tool calls), only for the person of the chat run / the job
        "/agent/progress": {"post": op(
            "2.32.0 (#1081): one step of your work -- the short prose you write between tool calls (\"I look at the tests first\"). "
            "chat_user_id: a chat run for that person (shows live under the typing dots; your next chat answer to them keeps the "
            "steps); job_id: a job that is for a person (user_id; its history \"Verlauf\"). Only that person ever sees them. "
            "Prose only: NEVER tool output (file contents, logs, database rows) and no secrets -- the server folds it into one line, "
            "cuts it (500 characters, live 200) and replaces recognisable secrets with [entfernt]. At most 60 per minute (429).",
            AG, ok({"type": "object", "properties": {"id": {"type": "integer"}, "text": {"type": "string"}, "redacted": {"type": "boolean"}}},
                   "Created", "201") | errs("400", "403", "404", "409", "429"), scope=W,
            body={"type": "object", "required": ["text"], "additionalProperties": False, "properties": {
                "text": {"type": "string"}, "chat_user_id": {"type": "integer"}, "job_id": {"type": "integer"}}})},
        "/agent/events": {"get": op("Events for the agent after a cursor; long-polling with wait", AG, ok(ref("EventPage")) | errs("400", "403"),
                                    [q("since", "seq of the last event you processed (0 = from the start)", {"type": "integer"}),
                                     q("limit", "At most 500", {"type": "integer"}),
                                     q("wait", f"0-{AGENT_WAIT_MAX} s: wait for the next event when there is none", {"type": "integer"})])},
        "/agent/jobs": {"get": op("The agent's jobs", AG, ok(ref("JobPage")) | errs("403"), [q("state", "all, open or a state")]),
                        "post": op("Report a new job", AG, ok(ref("Job"), "Created", "201") | errs("400", "403", "404"), scope=W, body={
                            "type": "object", "required": ["title"], "properties": {"title": {"type": "string"}, "task_id": {"type": "integer"},
                                                                                    "state": {"type": "string", "enum": list(JOB_STATES)}, "log": {"type": "string"},
                                                                                    "user_id": {"type": "integer"}}})},
        "/agent/jobs/{id}": {"patch": op("Update a job (state, log)", AG, ok(ref("Job")) | errs("400", "403", "404"), [pid("id", "Job id")], scope=W, body={
            "type": "object", "properties": {"title": {"type": "string"}, "state": {"type": "string", "enum": list(JOB_STATES)},
                                             "log": {"type": "string"}, "append_log": {"type": "string"}}}),
                             # 2.3.0: one job; a proposal job also with input (what the person sent), proposal and limits
                             "get": op("One job of the agent (proposal jobs: kind, input, proposal, limits)", AG, ok(ref("Job")) | errs("403", "404"),
                                       [pid("id", "Job id")])},
        # 2.26.0 (#949): a proposal to another topic (a list the agent cannot see)
        "/agent/proposals": {"post": op(
            "Propose tasks for a list you cannot see (another topic). Lands as a proposal with the list's owner (no event for the "
            "agents there); only when a person applies it do tasks exist. Allowed: lists owned by a person you already work with; "
            "others answer 404", AG, ok(ref("Job"), "Created", "201") | errs("400", "403", "404", "429"), scope=W,
            body={"type": "object", "required": ["list_id", "title", "reason", "tasks"], "properties": {
                "list_id": {"type": "integer"}, "title": {"type": "string", "maxLength": 300}, "reason": {"type": "string", "maxLength": 5000},
                "summary": {"type": "string"},
                "tasks": {"type": "array", "items": {"type": "object", "required": ["title"], "properties": {
                    "title": {"type": "string"}, "notes": {"type": "string"}, "due": {"type": "string", "format": "date"}}}}}})},
        "/agent/jobs/{id}/proposal": {"post": op(
            "Submit the structured proposal for a job_request (kind project | subtasks | triage | extract | dayplan; see docs/AGENTS.md). "
            "Validated; replaces an earlier one until the person applied or discarded it", AG,
            ok(ref("Job"), "Created", "201") | errs("400", "403", "404", "409", "413"), [pid("id", "Job id")], scope=W,
            body={"type": "object", "properties": {"kind": {"type": "string", "enum": list(PROP_KINDS)},
                                                   "summary": {"type": "string", "maxLength": PROP_SUMMARY_MAX}},
                  "description": f"project: {{name, folder?, sections[], tasks[{{title, notes?, section?, due?, start?, priority?, subtasks[], "
                                 f"depends_on[]}}]}}; subtasks: {{items[{{title, notes?, due?, estimate?}}], dependencies[[a, b]]?}}; triage: "
                                 f"{{items[{{task_id, list_id?, section_id?, tags[], priority?, due?, rewrite_title?}}]}}; extract: {{tasks[{{title, "
                                 f"notes?, assignee_id?, due?, section?}}]}}; dayplan (2.10.0): {{items[{{task_id, start (HH:MM), duration?, note?}}], nofit[{{task_id, "
                                 f"note?}}]}} (2.11.0: applying sets plan_start + duration, never due dates; task ids from input.tasks). At most {PROP_MAX_ITEMS} entries, {PROP_MAX_BYTES // 1024} KB."})},
        "/agent/chats": {"get": op("Chat messages after a cursor", AG, ok(ref("ChatPage")) | errs("400", "403"),
                                   [q("since", "Message id", {"type": "integer"}), q("user_id", "One person", {"type": "integer"}), q("limit", "At most 500", {"type": "integer"})])},
        "/tasks/{id}/typing": {"post": op("2.22.0 (#693): \"<name> is writing …\" in the task's comments for 8 s (send it again while writing; "
                                          "people and agents alike, before a comment answer)", AG, ok({"type": "object"}) | errs("404"),
                                          [pid()], scope="comments")},
        "/agent/typing": {"post": op(f"Typing dots in one person's chat for {AGENT_TYPING_S} s (2.4.1)", AG, ok({"type": "object"}) | errs("400", "403", "404"),
                                     scope=W, body={"type": "object", "required": ["chat_user_id"], "properties": {"chat_user_id": {"type": "integer"}}})},
        "/agent/chats/{id}": {"post": {**op("Answer in the chat with a person. 2.13.1 (#465): as multipart/form-data with `file` (repeatable, "
                                            f"at most {CHAT_FILES_MAX} files of {MAX_FILE_MB} MB) to send images / files; body may then be empty", AG,
                                            ok(ref("ChatMessage"), "Created", "201") | errs("400", "403", "404", "413"), [pid("id", "User id")], scope=W),
                                         "requestBody": {"required": True, "content": {
                                             "application/json": {"schema": {"type": "object", "required": ["body"], "properties": {
                                                 "body": {"type": "string"}, "task_id": {"type": "integer"},
                                                 "job_id": {"type": "integer", "description": "2.32.0 (#1081): this message is the result of your job "
                                                            "(for this person): its history shows under it"},
                                                 "choices": {"type": "array", "maxItems": 8, "description": "2.28.0 (#1005): answer buttons; the person's answer comes as the event chat_choice (message_id, choice_ids, labels)",
                                                             "items": {"type": "object", "required": ["id", "label"], "properties": {"id": {"type": "string", "maxLength": 40}, "label": {"type": "string", "maxLength": 80},
                                                                                                                                    "style": {"type": "string", "enum": ["default", "primary", "danger"]}}}},
                                                 "multi": {"type": "boolean", "description": "several buttons may be chosen"},
                                                 "permission": {"type": "boolean", "description": "2.30.0 (#1041): a permission question: buttons Allow / Deny "
                                                                "(ids allow / deny, added when missing); the answer comes as chat_choice (approval) and as reaction (via button)"},
                                                 "expires_in": {"type": "integer", "minimum": 10, "maximum": 604800, "description": "2.30.0 (#1041): seconds a permission "
                                                                "question stays open; then it shows as not answered (denied)"}}}},
                                             "multipart/form-data": {"schema": {"type": "object", "properties": {
                                                 "body": {"type": "string"}, "task_id": {"type": "integer"},
                                                 "file": {"type": "array", "items": {"type": "string", "format": "binary"}}}}}}}}},
        "/agent/usage": {  # 2.1.1 (#326)
            "post": op("Report model usage (numbers and ids only; allowed also over the hard limit)", AG,
                       ok(ref("UsageReport"), "Created", "201") | errs("400", "403"), scope=W, body={
                           "type": "object", "required": ["model", "input_tokens", "output_tokens"], "additionalProperties": False,
                           "properties": {"model": {"type": "string", "maxLength": USAGE_MODEL_MAX},
                                          **{k: {"type": "integer", "minimum": 0} for k in ("input_tokens", "output_tokens", "cache_read_tokens",
                                                                                           "cache_write_tokens")},
                                          "cost_usd": nul("number"), "task_id": {"type": "integer"},
                                          "list_id": {"type": "integer", "description": "Taken from the task when missing"},
                                          "job_id": {"type": "integer"}, "note": {"type": "string", "maxLength": USAGE_NOTE_MAX}}}),
            "get": op("The agent's own usage, grouped", AG, ok(ref("UsagePage")) | errs("400", "403"),
                      [q("from", "First local day (YYYY-MM-DD), default 29 days before `to`"), q("to", "Last local day, default today"),
                       q("group", "day (default), task, list or model", {"type": "string", "enum": list(USAGE_GROUPS)})])},
        "/agent/chats/{id}/messages/{mid}/reactions": {"post": op("React to a message of the chat with a person (2.7.2; never an approval)", AG,
                                                                  ok(chat_rx_out) | errs("400", "403", "404"), [pid("id", "User id"), pid("mid", "Message id")],
                                                                  scope=W, body=chat_rx_in)},
        "/agent/chats/{id}/messages/{mid}/withdraw": {"post": op("2.30.0 (#1037): withdraw the open answer buttons of one of your chat messages (they disappear, "
                                                                 "a press answers 409). outcome (permission questions only): allowed | denied | expired -- the host "
                                                                 "decided another way (an answer in words, its time limit)", AG, ok(ref("ChatMessage")) | errs("400", "403", "404", "409"),
                                                                 [pid("id", "User id"), pid("mid", "Message id")], scope=W,
                                                                 body={"type": "object", "properties": {"outcome": {"type": "string", "enum": ["allowed", "denied", "expired"]}}})},
        "/agents": {"get": op("Agents you share lists with (an agent: itself)", AG, ok(ref("AgentPage")) | errs())},
        "/agents/{id}/chat/{mid}/choice": {"post": op("2.28.0 (#1005): answer an agent's question with one of its buttons ({choice_ids}); once per message; "
                                                      "the agent gets the event chat_choice. 2.30.0 (#1037): 409 when the buttons are no longer current", AG, ok(ref("ChatMessage")) | errs("400", "403", "404", "409"),
                                                      [pid("id", "Agent id"), pid("mid", "Message id")], scope=W,
                                                      body={"type": "object", "required": ["choice_ids"], "properties": {"choice_ids": {"type": "array", "items": {"type": "string"}}}})},
        "/agents/{id}/chat/{mid}/reactions": {"post": op("React to a message of your chat with an agent (2.7.2): 👍 / 👎 on an agent's message "
                                                         "that asks something (asks, 2.13.0) = approval / rejection; the agent gets the event reaction", AG, ok(chat_rx_out) | errs("400", "403", "404"),
                                                         [pid("id", "Agent id"), pid("mid", "Message id")], scope=W, body=chat_rx_in)},
        "/tasks/{id}/tidy": {"post": op("Tidy a task (agents; list set to automatic). 2.27.0: also base_updated_at (the task's updated_at "
                                        "the agent read); 409 while a person edits the task or changed it since the tidy event", AG, ok(ref("Task")) | errs("400", "403", "404", "409"),
                                        [pid()], scope=W, body=ref("TidyInput"))},
        "/comments/{id}/reactions": {"post": op("React to a comment", C_ := "Comments", ok(ref("Comment")) | errs("400", "403", "404"),
                                                [pid("id", "Comment id")], scope=W, body={"type": "object", "required": ["emoji"], "properties": {
                                                    "emoji": {"type": "string", "description": "up, down, heart or any single emoji; "
                                                              "up / down on an agent's comment = approval / rejection"}}})},
        "/comments/{id}/reactions/{emoji}": {"delete": op("Remove your reaction", C_, ok(ref("Comment")) | errs("400", "403", "404"),
                                                          [pid("id", "Comment id"), {"name": "emoji", "in": "path", "required": True,
                                                                                    "schema": {"type": "string"}}], scope=W)},
        "/lists/{id}/tags": {"get": op("Tags of a list (shared by its members)", "Lists", ok(ref("ListTagPage")) | errs("404"), [lp]),
                             "post": op("Create a list tag", "Lists", ok(ref("ListTag"), "Created", "201") | errs("400", "403", "404", "409"), [lp], scope=W,
                                        body={"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}, "color": {"type": "string"}}})},
        "/lists/{id}/tags/{tag_id}": {
            "patch": op("Rename / recolour a list tag", "Lists", ok(ref("ListTag")) | errs("400", "403", "404", "409"),
                        [lp, {"name": "tag_id", "in": "path", "required": True, "schema": {"type": "integer"}}], scope=W,
                        body={"type": "object", "properties": {"name": {"type": "string"}, "color": {"type": "string"}}}),
            "delete": op("Delete a list tag (removed from every task)", "Lists", {"204": {"description": "Deleted"}} | errs("403", "404"),
                         [lp, {"name": "tag_id", "in": "path", "required": True, "schema": {"type": "integer"}}], scope=W)},
    })
