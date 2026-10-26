"""2.235.0 C (#2903): the standing rules of an agent ("from now on always ..."), visible and editable.

Kalmido never formulates for the agent: the agent itself recognises a standing instruction in a chat message or a comment,
stores it as a rule with its source (POST /api/v1/agent/rules) and confirms it in ONE line. The owner of a personal agent (a
person without an organisation is their own admin) or an instance admin (team agent) reads, rewords, pauses and deletes the
rules in the agent's settings (agents/workstyle.py ws_need_editor, everyone else 404) and may add one by hand. The agent reads
its ACTIVE rules in GET /api/v1/agent "rules" and gets the event rules_changed when a person changed them (never for its own
POST: agent_emit skips the agent's own actions).

Table agent_rules (new, additive): body, state active | paused, source kind chat | comment | manual + id (+ the task of a
comment, the person of a chat message) + a short excerpt taken from the source at creation."""
import re
from flask import g, jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, iso, now_utc
from ..core.pg import insert_id, write_lock
from ..core.access import Denied, task_visible
from ..core.errors import BadInput, UnknownFields
from ..api.common import v1_args, v1_json, v1_view
from ..agents.core import agent_emit, agent_row, agent_shares, need_agent
from ..agents.workstyle import ws_need_editor

AR_TEXT_MAX = 500  # characters of one rule
AR_MAX = 100  # rules per agent (active + paused)
AR_EXCERPT = 120  # characters of the source kept as its excerpt
AR_STATES = ("active", "paused")
AR_KINDS = ("chat", "comment")  # what an agent may name as the source; "manual" = added by a person in the settings
_MENTION = re.compile(r"<@(\d+)>")


def _excerpt(s):
    s = " ".join(_MENTION.sub("@", s or "").split())
    return s if len(s) <= AR_EXCERPT else s[:AR_EXCERPT - 1].rstrip() + "…"


def _text(v):
    if not isinstance(v, str) or not v.strip() or len(v.strip()) > AR_TEXT_MAX:
        raise BadInput(tr("Invalid value: {0}", "text"))
    return v.strip()


def _rows(c, aid, active_only=False):
    return c.execute("SELECT * FROM agent_rules WHERE agent_id=?" + (" AND state='active'" if active_only else "") + " ORDER BY id",
                     (aid,)).fetchall()


def _source(r):
    return {"kind": r["source_kind"] or "manual", "id": r["source_id"], "task_id": r["source_task_id"],
            "user_id": r["source_user_id"]}


def ar_dict(r, excerpt=True):
    d = {"id": r["id"], "text": r["body"], "state": r["state"], "created_at": r["created_at"], "updated_at": r["updated_at"],
         "created_by": r["created_by"], "source": _source(r)}
    if excerpt:
        d["source"]["excerpt"] = r["source_excerpt"] or ""
    return d


def ar_public(c, a):
    """What agent row a reads in GET /api/v1/agent "rules" (and the event rules_changed): its ACTIVE rules, oldest first
    (paused ones are left out)."""
    return [{k: v for k, v in ar_dict(r, excerpt=False).items() if k in ("id", "text", "created_at", "source")}
            for r in _rows(c, a["user_id"], active_only=True)]


def ar_changed(c, aid, what):
    """Event rules_changed to the agent (a person changed its rules; the caller commits)."""
    a = agent_row(c, aid)
    agent_emit(c, aid, "rules_changed", {"change": what, "rules": ar_public(c, a)})
    print("agent", aid, "rules", what, "by", g.user["username"], flush=True)


def _source_of_agent(c, aid, src):
    """The checked source of a rule the agent stores: {kind: chat | comment, id} it can see -> the row values; 404 otherwise."""
    if not isinstance(src, dict) or set(src) - {"kind", "id"} or src.get("kind") not in AR_KINDS \
            or isinstance(src.get("id"), bool) or not isinstance(src.get("id"), int):
        raise BadInput(tr("Invalid value: {0}", "source"))
    sid = src["id"]
    if src["kind"] == "chat":
        m = c.execute("SELECT id, user_id, sender, body FROM agent_chat WHERE id=? AND agent_id=?", (sid, aid)).fetchone()
        # a message of a person to this agent (its own answers are no instruction), in a conversation it still has
        if not m or m["sender"] != "user" or not agent_shares(c, aid, m["user_id"]):
            raise Denied(404)
        return ("chat", sid, None, m["user_id"], _excerpt(m["body"]))
    m = c.execute("SELECT id, task_id, user_id, body FROM comments WHERE id=? AND deleted_at IS NULL", (sid,)).fetchone()
    if not m or m["user_id"] == aid or not task_visible(c, m["task_id"], aid, full=True):
        raise Denied(404)
    return ("comment", sid, m["task_id"], m["user_id"], _excerpt(m["body"]))


def _insert(c, aid, text, src):
    """Stores a new active rule (limit AR_MAX per agent, under a lock: two parallel requests never pass it); -> its row."""
    write_lock(c, f"agent_rules:{aid}")
    if c.execute("SELECT COUNT(*) FROM agent_rules WHERE agent_id=?", (aid,)).fetchone()[0] >= AR_MAX:
        raise BadInput(tr("At most {0} standing rules per agent.", AR_MAX))
    kind, sid, tid, uid, ex = src
    ts = iso(now_utc())
    rid = insert_id(c, """INSERT INTO agent_rules(agent_id, body, state, source_kind, source_id, source_task_id, source_user_id,
                          source_excerpt, created_by, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (aid, text, "active", kind, sid, tid, uid, ex, g.user["id"], ts, ts))
    return c.execute("SELECT * FROM agent_rules WHERE id=?", (rid,)).fetchone()


# ---------------------------------------------------------------- the agent (its own token)
@app.get("/api/v1/agent/rules")
@v1_view
def v1_agent_rules():
    """The agent's standing rules, active and paused: {data: [{id, text, state, created_at, updated_at, created_by, source:
    {kind, id, task_id, user_id, excerpt}}], max, text_max}. Only the active ones apply."""
    v1_args(())
    aid = need_agent()
    return jsonify(data=[ar_dict(r) for r in _rows(db(), aid)], max=AR_MAX, text_max=AR_TEXT_MAX)


@app.post("/api/v1/agent/rules")
@v1_view
def v1_agent_rule_add():
    """{text, source: {kind: chat | comment, id}} -- stores a standing rule the agent recognised ("from now on always ...") in
    a chat message of a person to it or a comment it can see (404 otherwise). The same text as an existing rule = that rule
    (200, duplicate: true); a new one 201. At most 100 rules, 500 characters each."""
    v1_args(())
    aid = need_agent()
    b = v1_json()
    unknown = sorted(k for k in b if k not in ("text", "source"))
    if unknown:
        raise UnknownFields(unknown)
    text = _text(b.get("text"))
    c = db()
    src = _source_of_agent(c, aid, b.get("source"))
    old = next((r for r in _rows(c, aid) if r["body"].casefold() == text.casefold()), None)
    if old:
        return jsonify(rule=ar_dict(old), duplicate=True)
    r = _insert(c, aid, text, src)
    c.commit()
    print("agent", aid, "rule", r["id"], "from", src[0], src[1], flush=True)
    return jsonify(rule=ar_dict(r), duplicate=False), 201


# ---------------------------------------------------------------- the owner / an instance admin (agent settings)
def _view(c, r, uid):
    """A rule for the settings: the excerpt and the link only when the person may see the source themselves."""
    d = ar_dict(r)
    s = d["source"]
    if s["kind"] == "chat":
        s["visible"] = s["user_id"] == uid
    elif s["kind"] == "comment":
        s["visible"] = bool(s["task_id"]) and task_visible(c, s["task_id"], uid, full=True)
    else:
        s["visible"] = True
    if not s["visible"]:
        s["excerpt"] = ""
    return d


def _list(c, aid):
    uid = g.user["id"]
    return jsonify(rules=[_view(c, r, uid) for r in _rows(c, aid)], max=AR_MAX, text_max=AR_TEXT_MAX)


def _need_rule(c, aid, rid):
    r = c.execute("SELECT * FROM agent_rules WHERE id=? AND agent_id=?", (rid, aid)).fetchone()
    if not r:
        raise Denied(404)
    return r


@app.get("/api/agents/<int:aid>/rules")
def ar_route_list(aid):
    c = db()
    ws_need_editor(c, aid)
    return _list(c, aid)


@app.post("/api/agents/<int:aid>/rules")
def ar_route_add(aid):
    """{text} -- a rule added by hand (source manual)."""
    c = db()
    ws_need_editor(c, aid)
    b = body()
    unknown = sorted(k for k in b if k != "text")
    if unknown:
        raise UnknownFields(unknown)
    r = _insert(c, aid, _text(b.get("text")), ("", None, None, None, ""))
    ar_changed(c, aid, "added")
    bump(c)
    c.commit()
    return jsonify(rule=_view(c, r, g.user["id"])), 201


@app.patch("/api/agents/<int:aid>/rules/<int:rid>")
def ar_route_patch(aid, rid):
    """{text?, state?: active | paused} -- rewords / pauses / resumes one rule."""
    c = db()
    ws_need_editor(c, aid)
    b = body()
    unknown = sorted(k for k in b if k not in ("text", "state"))
    if unknown:
        raise UnknownFields(unknown)
    r = _need_rule(c, aid, rid)
    text = _text(b["text"]) if "text" in b else r["body"]
    state = b.get("state", r["state"])
    if state not in AR_STATES:
        raise BadInput(tr("Invalid value: {0}", "state"))
    if (text, state) != (r["body"], r["state"]):
        c.execute("UPDATE agent_rules SET body=?, state=?, updated_at=? WHERE id=?", (text, state, iso(now_utc()), rid))
        ar_changed(c, aid, "paused" if state != r["state"] and state == "paused" else
                   "resumed" if state != r["state"] else "edited")
        bump(c)
        c.commit()
    return jsonify(rule=_view(c, _need_rule(c, aid, rid), g.user["id"]))


@app.delete("/api/agents/<int:aid>/rules/<int:rid>")
def ar_route_delete(aid, rid):
    c = db()
    ws_need_editor(c, aid)
    _need_rule(c, aid, rid)
    c.execute("DELETE FROM agent_rules WHERE id=?", (rid,))
    ar_changed(c, aid, "deleted")
    bump(c)
    c.commit()
    return jsonify(ok=True)


def ar_spec(paths, schemas, op, ok, errs, ref):
    """OpenAPI of the agent's standing rules (2.235.0 C, #2903; called from agents/usage.py agent_spec)."""
    AG = "Agents"
    src = {"type": "object", "properties": {
        "kind": {"type": "string", "enum": ["chat", "comment", "manual"], "description": "a chat message of a person to you, a comment, or added by a person in your settings"},
        "id": {"type": ["integer", "null"], "description": "the chat message / comment id"},
        "task_id": {"type": ["integer", "null"], "description": "the task of a comment"},
        "user_id": {"type": ["integer", "null"], "description": "the person of the chat / the author of the comment"},
        "excerpt": {"type": "string", "description": "the start of the source text, taken at creation"}}}
    schemas["AgentRule"] = {"type": "object", "properties": {
        "id": {"type": "integer"}, "text": {"type": "string"}, "state": {"type": "string", "enum": list(AR_STATES), "description": "only active rules apply"},
        "created_at": {"type": "string", "format": "date-time"}, "updated_at": {"type": "string", "format": "date-time"},
        "created_by": {"type": ["integer", "null"]}, "source": src}}
    paths["/agent/rules"] = {
        "get": op("2.235.0 (#2903): your standing rules, active and paused (only the active ones apply; they also come in GET /agent "
                  "rules and with the event rules_changed)", AG,
                  ok({"type": "object", "properties": {"data": {"type": "array", "items": ref("AgentRule")}, "max": {"type": "integer"},
                                                       "text_max": {"type": "integer"}}}) | errs("403")),
        "post": op("2.235.0 (#2903): save a standing rule you recognised (\"from now on always ...\") with its source: a chat message of a "
                   "person to you or a comment you can see (else 404). The same text as an existing rule returns that one (200, "
                   "duplicate: true). At most 100 rules, 500 characters each. Confirm it in ONE line", AG,
                   ok({"type": "object", "properties": {"rule": ref("AgentRule"), "duplicate": {"type": "boolean"}}}, code="201")
                   | ok({"type": "object", "properties": {"rule": ref("AgentRule"), "duplicate": {"type": "boolean"}}}) | errs("400", "403", "404"),
                   scope="write", body={"type": "object", "required": ["text", "source"], "additionalProperties": False, "properties": {
                       "text": {"type": "string", "minLength": 1, "maxLength": AR_TEXT_MAX},
                       "source": {"type": "object", "required": ["kind", "id"], "additionalProperties": False, "properties": {
                           "kind": {"type": "string", "enum": list(AR_KINDS)}, "id": {"type": "integer"}}}}})}
