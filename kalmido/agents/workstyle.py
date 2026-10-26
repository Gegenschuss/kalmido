"""2.236.0 (#2904-#2911): how an agent works and reports - the "Arbeitsweise und Meldungen" section of an agent's settings.

Kalmido never runs the agent and never formulates for it: it stores what the owner of a personal agent (a person without
an organisation is their own admin) or an instance admin (team agent) wants, hands it to the agent (GET /api/v1/agent
"work_style", event work_style_changed) and enforces what a server can enforce itself: the
budget (agents/usage.py), the pushes of the agent (quiet window, "when may it disturb") and the order of its queue.

Stored as JSON in agents.work_style (flat keys, '' = nothing set). An agent whose work_style is '' (made before 2.236.0)
keeps today's pushes (push "results"); a new agent starts with push "limits" (agents/admin.py make_agent)."""
import json
import re
from datetime import timedelta
from flask import g, has_request_context, jsonify

from ..core.config import app, PUBLIC_URL, TZ
from ..core.i18n import tr, trn
from ..core.db import body, bump, db, now_utc, iso
from ..core.access import Denied
from ..core.errors import BadInput, UnknownFields
from ..tasks.validation import valid_hm
from ..accounts.session import me
from ..agents.core import agent_emit, agent_row, is_agent, may_set_runtime
from ..agents.chat import CHOICES_MAX
from ..collab.comments import PUSH_BURST_SKIP, PUSH_FILTERS
from ..notify.push import notify, push_prio

WS_DEFAULTS = {
    # #2904 budget: period '' = none, day | week; metric tokens | cost; limit = pause from this amount; warn_pct = the notice before
    "budget_period": "", "budget_metric": "tokens", "budget_limit": None, "budget_warn_pct": 80,
    # #2905 work window: always | office (only from-to on the chosen weekdays, 1 = Monday)
    "work_mode": "always", "work_from": "08:00", "work_to": "18:00", "work_days": [1, 2, 3, 4, 5],
    # #2905 quiet window for messages: off | on (keeps working, no push; one summary when it ends)
    "quiet_mode": "off", "quiet_from": "22:00", "quiet_to": "07:00",
    # #2906 at most this many tasks at once (0 = no limit), the rest waits in the queue
    "max_parallel": 0,
    # #2907 the priority rule in the owner's words, given with every choice of the next task
    "priority_rule": "",
    # #2908 report style
    "report_length": "short", "report_lang": "", "report_tables": True, "report_jargon": False,
    # #2909 when the agent may disturb (push): limits | results | never
    "push": "limits",
    # #2910 where results go: comment | chat | both (comment on the task + one line in the chat)
    "results_to": "both",
    # #2911 the next step as one button at the end of every answer
    "next_step": True,
}
WS_CHOICES = {"budget_period": ("", "day", "week"), "budget_metric": ("tokens", "cost"), "work_mode": ("always", "office"),
              "quiet_mode": ("off", "on"), "report_length": ("line", "short", "long"), "push": ("limits", "results", "never"),
              "results_to": ("comment", "chat", "both")}
WS_BOOLS = ("report_tables", "report_jargon", "next_step")
WS_HM = ("work_from", "work_to", "quiet_from", "quiet_to")
WS_LEGACY = {"push": "results"}  # an agent made before 2.236.0 keeps the pushes it had
WS_NEW = {"push": "limits"}  # what a new agent stores at creation
WS_RULE_MAX = 500
WS_PARALLEL_MAX = 20
WS_LANG_RE = re.compile(r"^[a-z]{2}$")


def ws_load(a):
    """The stored dict of agent row a (None = nothing stored yet, an agent from before 2.236.0)."""
    raw = a["work_style"]
    if not raw:
        return None
    try:
        d = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return d if isinstance(d, dict) else None


def ws_get(a):
    """The effective work style of agent row a: defaults, the stored keys over them (invalid / unknown dropped)."""
    d = ws_load(a)
    base = {**WS_DEFAULTS, **(WS_LEGACY if d is None else {})}
    if not d:
        return base
    try:
        return ws_clean(base, d, strict=False)
    except BadInput:
        return base


def ws_clean(cur, b, strict=True):
    """Validates a (partial) dict b over the effective dict cur; returns the new full dict. strict=False drops bad keys."""
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid value: {0}", "work_style"))
    unknown = sorted(k for k in b if k not in WS_DEFAULTS)
    if unknown and strict:
        raise UnknownFields(unknown)
    out = {k: cur.get(k, v) for k, v in WS_DEFAULTS.items()}
    for k, v in b.items():
        if k not in WS_DEFAULTS:
            continue
        try:
            out[k] = ws_value(k, v)
        except BadInput:
            if strict:
                raise
    return out


def ws_value(k, v):
    bad = BadInput(tr("Invalid value: {0}", k))
    if k in WS_CHOICES:
        v = "" if v is None and "" in WS_CHOICES[k] else v
        if v not in WS_CHOICES[k]:
            raise bad
        return v
    if k in WS_BOOLS:
        if not isinstance(v, bool):
            raise bad
        return v
    if k in WS_HM:
        if not valid_hm(v):
            raise bad
        return v
    if k == "budget_limit":
        if v is None:
            return None
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 < v <= 10 ** 12:
            raise bad
        return round(v, 2) if isinstance(v, float) else v
    if k == "budget_warn_pct":
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 99:
            raise bad
        return v
    if k == "work_days":
        if not isinstance(v, list) or not v or any(isinstance(x, bool) or not isinstance(x, int) or not 1 <= x <= 7 for x in v):
            raise bad
        return sorted(set(v))
    if k == "max_parallel":
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= WS_PARALLEL_MAX:
            raise bad
        return v
    if k == "priority_rule":
        if v is None:
            return ""
        if not isinstance(v, str) or len(v.strip()) > WS_RULE_MAX:
            raise bad
        return v.strip()
    if k == "report_lang":
        v = v or ""
        if not isinstance(v, str) or (v and not WS_LANG_RE.fullmatch(v)):
            raise bad
        return v
    raise bad


def _hm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def ws_in_window(frm, to, minute):
    """minute of the day inside [frm, to) (over midnight when frm > to; frm == to = the whole day)."""
    a, b = _hm(frm), _hm(to)
    if a == b:
        return True
    return a <= minute < b if a < b else (minute >= a or minute < b)


def ws_working(ws, now=None):
    """#2905: may the agent work now (work_mode always, or office: weekday + window, local time of the instance)."""
    if ws["work_mode"] != "office":
        return True
    t = (now or now_utc()).astimezone(TZ)
    return t.isoweekday() in ws["work_days"] and ws_in_window(ws["work_from"], ws["work_to"], t.hour * 60 + t.minute)


def ws_quiet(ws, now=None):
    """#2905: is the quiet window for messages on now (no push from this agent; results are collected)."""
    if ws["quiet_mode"] != "on":
        return False
    t = (now or now_utc()).astimezone(TZ)
    return ws_in_window(ws["quiet_from"], ws["quiet_to"], t.hour * 60 + t.minute)


def ws_next_change(pred, ws, now=None):
    """The next moment (UTC iso, minute steps, at most 8 days ahead) at which pred(ws, t) turns True; None = never / already."""
    t = (now or now_utc()).replace(second=0, microsecond=0)
    if pred(ws, t):
        return None
    for _ in range(8 * 24 * 60 // 15):
        t += timedelta(minutes=15)
        if pred(ws, t):
            # step back to the exact minute
            for _ in range(15):
                p = t - timedelta(minutes=1)
                if not pred(ws, p):
                    break
                t = p
            return iso(t)
    return None


def ws_state(ws, now=None):
    """What holds right now: working (inside the work window), quiet (messages held), when work resumes / quiet ends."""
    now = now or now_utc()
    working, quiet = ws_working(ws, now), ws_quiet(ws, now)
    return {"working": working, "work_resumes_at": None if working else ws_next_change(ws_working, ws, now),
            "quiet": quiet, "quiet_until": ws_next_change(lambda w, t: not ws_quiet(w, t), ws, now) if quiet else None,
            "timezone": str(TZ)}


def ws_budget(c, a):
    """2.236.0 B (#2904): where the agent's budget stands (agents/usage.py budget_state; one local import: usage sits higher)."""
    from ..agents.usage import budget_state
    return budget_state(c, a)


def ws_public(c, a):
    """What the agent reads (GET /api/v1/agent "work_style", the event work_style_changed): the settings + the state now."""
    ws = ws_get(a)
    return {**ws, "state": ws_state(ws), "budget_state": ws_budget(c, a)}  # 2.236.0 B (#2904): where its budget stands


def ws_set(c, a, b):
    """Validates and stores a partial dict b for agent row a; event work_style_changed when something changed."""
    cur = ws_get(a)
    new = ws_clean(cur, b)
    if new != cur or ws_load(a) is None:
        c.execute("UPDATE agents SET work_style=? WHERE user_id=?", (json.dumps(new, ensure_ascii=False), a["user_id"]))
        if any(new[k] != cur[k] for k in ("budget_period", "budget_metric", "budget_limit", "budget_warn_pct")):
            ws_budget_reset(c, a)  # review (#2904): a changed budget warns again in the same period
        a2 = agent_row(c, a["user_id"])
        agent_emit(c, a["user_id"], "work_style_changed", {"work_style": ws_public(c, a2)})
        print("agent", a["user_id"], "work style", ",".join(sorted(k for k in new if new[k] != cur.get(k))) or "-",
              "by", g.user["username"], flush=True)
    return new


def ws_budget_reset(c, a):
    """Forgets the budget notices already sent this period (agents.usage_alerted "budget", agents/usage.py budget_alerts)."""
    try:
        done = json.loads(a["usage_alerted"] or "{}")
    except (ValueError, TypeError):
        return
    if isinstance(done, dict) and done.pop("budget", None) is not None:
        c.execute("UPDATE agents SET usage_alerted=? WHERE user_id=?", (json.dumps(done, separators=(",", ":")), a["user_id"]))


def ws_need_editor(c, aid):
    """The agent row when the signed-in person may set its work style (owner of a personal agent, an instance admin for a
    team agent); everyone else gets 404 (the priority rule and budget are the owner's business)."""
    a = agent_row(c, aid)
    if not a or is_agent(g.user) or not may_set_runtime(c, a, me()):
        raise Denied(404)
    return a


@app.get("/api/agents/<int:aid>/work-style")
def ws_route_get(aid):
    c = db()
    a = ws_need_editor(c, aid)
    return jsonify(work_style=ws_get(a), defaults=WS_DEFAULTS, state=ws_state(ws_get(a)), budget_state=ws_budget(c, a))


@app.patch("/api/agents/<int:aid>/work-style")
def ws_route_patch(aid):
    """{any keys of WS_DEFAULTS} -- changes only the given keys (autosave per field)."""
    c = db()
    a = ws_need_editor(c, aid)
    new = ws_set(c, a, body())
    bump(c)
    c.commit()
    return jsonify(work_style=new, defaults=WS_DEFAULTS, state=ws_state(new), budget_state=ws_budget(c, agent_row(c, aid)))


# ---------------------------------------------------------------- 2.236.0 B (#2909, #2905): the pushes of an agent
# Every push queued while an AGENT's own request runs (g.pushes, sent after the request: collab/comments.py
# send_queued_pushes) passes ws_push_filter: push "results" = as before, "never" = none, "limits" = only the ones marked
# {"ws": "limit"} in their extra (approval / permission questions, chat messages with limit: true, a job waiting for an
# approval). {"ws": "system"} (usage / budget alerts to admins and owners) always passes. The person's own settings
# (agent_push, the notification matrix) were applied before (the stricter one wins). Inside the agent's quiet window the
# remaining pushes are only counted (agent_push_held); ws_held_tick sends each person ONE summary once it ends.
WS_HELD_GONE_DAYS = 8  # a count older than this (the agent's window never ended, e.g. quiet all day) is sent anyway


def ws_push_filter(c, actor, pushes):
    """The pushes of this request that may go out (the "ws" mark taken out of the extras)."""
    a = agent_row(c, actor["id"]) if is_agent(actor) else None
    ws = ws_get(a) if a else None
    quiet = bool(ws) and ws_quiet(ws)
    out, held = [], {}
    for x in pushes:
        mark = None
        if len(x) > 5 and isinstance(x[5], dict) and "ws" in x[5]:
            mark = x[5]["ws"]
            x = (*x[:5], {k: v for k, v in x[5].items() if k != "ws"})
        if ws is None or mark == "system":
            out.append(x)
        elif ws["push"] == "never" or (ws["push"] == "limits" and mark != "limit"):
            continue
        elif quiet and mark != "limit":  # review: approvals / permission questions (they expire) pass the quiet window
            held[x[0]] = held.get(x[0], 0) + 1
        else:
            out.append(x)
    if held:
        for uid, n in held.items():
            ws_hold(c, a["user_id"], uid, n)
        c.commit()
        print("agent", a["user_id"], "quiet window: held", sum(held.values()), "push(es)", flush=True)
    return out


def ws_hold(c, aid, uid, n=1):
    """Counts n held pushes of agent aid for person uid (the caller commits)."""
    ts = iso(now_utc())
    c.execute("""INSERT INTO agent_push_held(agent_id,user_id,n,first_at,last_at) VALUES(?,?,?,?,?)
                 ON CONFLICT(agent_id,user_id) DO UPDATE SET n=agent_push_held.n+excluded.n, last_at=excluded.last_at""",
              (aid, uid, n, ts, ts))


def ws_burst_skip(c, uid):
    """review (#2909 #2905): collab/comments.py burst_gate - a comment / event push of an agent's request inside the burst
    window would be counted for the watchdog's summary (task_push_tick), past ws_push_filter. Push "never" / "limits" (these
    pushes carry no limit mark) = neither pushed nor counted; inside the quiet window = counted as held. True = skip."""
    actor = g.get("user") if has_request_context() else None
    if not actor or not is_agent(actor):
        return False
    a = agent_row(c, actor["id"])
    if not a:
        return False
    ws = ws_get(a)
    if ws["push"] != "results":
        return True
    if ws_quiet(ws):
        ws_hold(c, a["user_id"], uid)
        return True
    return False


def ws_held_tick(c, users, S, LG):
    """Watchdog: once an agent's quiet window has ended, each person gets ONE push "<agent>: N messages during the quiet
    hours" (opens the chat with it); the count goes. Push "never" meanwhile = the count goes without a push."""
    rows = c.execute("SELECT * FROM agent_push_held ORDER BY agent_id, user_id").fetchall()
    old = iso(now_utc() - timedelta(days=WS_HELD_GONE_DAYS))
    for h in rows:
        a = agent_row(c, h["agent_id"])
        ws = ws_get(a) if a else None
        if ws and ws_quiet(ws) and h["first_at"] > old:
            continue
        c.execute("DELETE FROM agent_push_held WHERE agent_id=? AND user_id=? AND last_at<=?",  # newer counts wait for the next tick
                  (h["agent_id"], h["user_id"], h["last_at"]))
        c.commit()  # before sending: never twice
        uid = h["user_id"]
        if not ws or ws["push"] == "never" or uid not in users or not h["n"]:
            continue
        lg, name = LG.get(uid, "en"), a["display_name"] or a["username"]
        notify(uid, name, trn("{0} message during the quiet hours", "{0} messages during the quiet hours", h["n"], lg=lg),
               push_prio(S[uid]), f"{PUBLIC_URL}/#agents/{h['agent_id']}", s=S[uid], kind="other")


PUSH_FILTERS.append(ws_push_filter)
PUSH_BURST_SKIP.append(ws_burst_skip)


# ---------------------------------------------------------------- 2.236.0 B (#2911): the next step as one button
WS_NEXT_MAX, WS_NEXT_LOOKBACK = 80, 20


def ws_next_step(c, aid, uid, b):
    """next_step of POST /api/v1/agent/chats/<uid> (popped from b): appends it as ONE answer button {id: next, label} to
    b["choices"] -> (button id or None, why dropped or None). Dropped (the message stays): "off" (next_step off in the work
    style), "repeat" (the same text was a next button in the last 20 agent messages of this conversation), "conflict" (an
    approval / permission question / multiple choice), "full" (already 8 buttons)."""
    v = b.pop("next_step", None)
    if v in (None, ""):
        return None, None
    if not isinstance(v, str) or not v.strip() or len(v.strip()) > WS_NEXT_MAX:
        raise BadInput(tr("Invalid value: {0}", "next_step"))
    label = " ".join(v.split())
    if not ws_get(agent_row(c, aid))["next_step"]:
        return None, "off"
    if b.get("approval") not in (None, "") or b.get("permission") in (True, 1, "1", "true") or \
            b.get("multi") in (True, 1, "1", "true"):
        return None, "conflict"
    ch = b.get("choices")
    if isinstance(ch, str) and ch.strip():
        try:
            ch = json.loads(ch)
        except ValueError:
            return None, None  # chat_choices_clean refuses it
    if ch not in (None, "") and not isinstance(ch, list):
        return None, None  # review: chat_choices_clean refuses it (400), never replaced by the next button alone
    ch = ch or []
    if {x if isinstance(x, str) else x.get("id") for x in ch if isinstance(x, (str, dict))} == {"allow", "deny"}:
        return None, "conflict"  # review: a permission question of an older host (only the buttons allow / deny)
    key = label.casefold()
    for r in c.execute("""SELECT choices FROM agent_chat WHERE agent_id=? AND user_id=? AND sender='agent'
                          ORDER BY id DESC LIMIT ?""", (aid, uid, WS_NEXT_LOOKBACK)).fetchall():
        try:
            old = json.loads(r["choices"]) if r["choices"] else None
        except (ValueError, TypeError):
            old = None
        if isinstance(old, dict) and any(isinstance(x, dict) and x.get("next") and str(x.get("label", "")).casefold() == key
                                         for x in old.get("choices") or []):
            return None, "repeat"
    if len(ch) >= CHOICES_MAX:
        return None, "full"
    ids = {x if isinstance(x, str) else x.get("id") for x in ch if isinstance(x, (str, dict))}
    nid = next(x for x in ("next", "next_step", "next_1") if x not in ids)
    b["choices"] = [*ch, {"id": nid, "label": label}]
    return nid, None


def ws_next_mark(c, r, nid):
    """Marks the appended button {next: true} in the stored message r; -> the fresh row."""
    ch = json.loads(r["choices"]) if r["choices"] else None
    if not isinstance(ch, dict):
        return r
    for x in ch.get("choices") or []:
        if x.get("id") == nid:
            x["next"] = True
    c.execute("UPDATE agent_chat SET choices=? WHERE id=?", (json.dumps(ch, ensure_ascii=False), r["id"]))
    return c.execute("SELECT * FROM agent_chat WHERE id=?", (r["id"],)).fetchone()
