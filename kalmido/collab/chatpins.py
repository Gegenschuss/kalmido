"""2.62.0 (#1848): pinned chat messages (team chat and agent chat)."""
from flask import jsonify

from ..core.config import app
from ..core.db import body, bump, db, err, iso_ms, now_utc
from ..core.i18n import tr
from ..core.pg import write_lock
from ..core.access import Denied
from ..accounts.session import me
from ..api.v1 import v1_args, v1_call, v1_json, v1_view
from ..personal.timetrack import BadInput, reject_unknown, UnknownFields
from ..tasks.validation import as_int
from ..collab.comments import user_names


# ---------------------------------------------------------------- 2.62.0 (#1848): pinned chat messages
# A message of a team chat conversation or of an agent chat can be pinned: it shows in a bar at the top of the
# conversation (newest pin first), a tap jumps to it (also when it is older than the loaded page). At most CPIN_MAX per
# conversation; a deleted message leaves the bar (it keeps no pin in the count). Who: in the team chat everyone who may
# read the conversation (its members, agents of a list channel included, through REST v1), in the agent chat the
# person of the conversation (app) and the agent (REST v1, only in its own conversations). Pinning by the person sends
# the agent the event chat_pinned {message, pinned, user}; the agent's own pins send nothing. The person sees changes live
# through /api/version (team: tchat_sig counts the pins; agent chat: the area agentchat). Columns pinned_at / pinned_by of
# tchat_msgs and agent_chat (NULL = not pinned).
CPIN_MAX = 5


def cpin_want(b, have):
    """{pinned?: bool} -> True / False (omitted: the other way round of have); anything else is BadInput."""
    v = b.get("pinned") if isinstance(b, dict) else None
    if v is None:
        return not have
    if not isinstance(v, bool):
        raise BadInput(tr("Invalid value: {0}", "pinned"))
    return v


def cpin_full():
    return tr("At most {0} pinned messages. Unpin one first.", CPIN_MAX)


def cpin_who(c, uid):
    return {"id": uid, "name": user_names(c, [uid]).get(uid, "")} if uid else None


# ---- team chat
def cpin_team_list(c, rid):
    """The pinned messages of conversation rid (not deleted), newest pin first, as tchat_msg_dict."""
    from .teamchat import tchat_msg_dict, tchat_rx
    rows = c.execute("SELECT * FROM tchat_msgs WHERE room_id=? AND pinned_at IS NOT NULL AND deleted_at IS NULL ORDER BY pinned_at DESC, id DESC",
                     (rid,)).fetchall()
    rx = tchat_rx(c, [r["id"] for r in rows])
    return [tchat_msg_dict(c, r, rx) for r in rows]


@app.post("/api/team/messages/<int:mid>/pin")
def cpin_team(mid):
    """{pinned?: bool} -- pin / unpin a message of a conversation I belong to (omitted: toggles). 409: deleted, or CPIN_MAX
    are pinned already."""
    from .teamchat import need_tchat, need_tmsg, tchat_msg_dict, tchat_rx
    c = db()
    need_tchat(c)
    m, r = need_tmsg(c, mid)  # the room's members only (404 for everyone else)
    if m["deleted_at"]:
        return err(tr("The message was deleted"), 409)
    try:
        on = cpin_want(body(), bool(m["pinned_at"]))
    except BadInput as e:
        return err(str(e))
    write_lock(c, f"cpin:t:{r['id']}")
    have = c.execute("SELECT pinned_at FROM tchat_msgs WHERE id=?", (mid,)).fetchone()["pinned_at"]
    if on and not have:
        n = c.execute("SELECT COUNT(*) FROM tchat_msgs WHERE room_id=? AND pinned_at IS NOT NULL AND deleted_at IS NULL", (r["id"],)).fetchone()[0]
        if n >= CPIN_MAX:
            return err(cpin_full(), 409)
        c.execute("UPDATE tchat_msgs SET pinned_at=?, pinned_by=? WHERE id=?", (iso_ms(now_utc()), me(), mid))
    elif not on and have:
        c.execute("UPDATE tchat_msgs SET pinned_at=NULL, pinned_by=NULL WHERE id=?", (mid,))
    c.commit()
    m = c.execute("SELECT * FROM tchat_msgs WHERE id=?", (mid,)).fetchone()
    return jsonify(ok=True, message=tchat_msg_dict(c, m, tchat_rx(c, [mid])), pins=cpin_team_list(c, r["id"]))


@app.post("/api/v1/team/messages/<int:mid>/pin")
@v1_view
def v1_cpin_team(mid):
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("pinned",))
    return jsonify(v1_call(cpin_team, mid, body=b))


# ---- agent chat
def cpin_agent_list(c, aid, uid, api=False):
    """The pinned messages of the conversation of agent aid with person uid, newest pin first, as chat_dict."""
    from ..agents.chat import chat_dict, chat_files_of, chat_newest, chat_reactions_of
    rows = c.execute("SELECT * FROM agent_chat WHERE agent_id=? AND user_id=? AND pinned_at IS NOT NULL ORDER BY pinned_at DESC, id DESC",
                     (aid, uid)).fetchall()
    ids = [r["id"] for r in rows]
    nw = chat_newest(c, aid, uid)
    return [chat_dict(r, chat_reactions_of(c, ids), chat_files_of(c, ids), api=api, newest=nw) for r in rows]


def cpin_agent_set(c, m, b, by_agent):
    """Pins / unpins chat row m ({pinned?}); the person's change sends the agent chat_pinned. Returns the response
    dict or raises BadInput / Denied (caller commits nothing: done here)."""
    from ..agents.chat import chat_one
    from ..agents.core import agent_emit
    if "kind" in m.keys() and m["kind"] == "notice":
        raise BadInput(tr("Invalid value: {0}", "message"))
    on = cpin_want(b, bool(m["pinned_at"]))
    aid, uid = m["agent_id"], m["user_id"]
    write_lock(c, f"cpin:a:{aid}:{uid}")
    have = c.execute("SELECT pinned_at FROM agent_chat WHERE id=?", (m["id"],)).fetchone()["pinned_at"]
    changed = False
    if on and not have:
        if c.execute("SELECT COUNT(*) FROM agent_chat WHERE agent_id=? AND user_id=? AND pinned_at IS NOT NULL", (aid, uid)).fetchone()[0] >= CPIN_MAX:
            raise Denied(409, cpin_full())
        c.execute("UPDATE agent_chat SET pinned_at=?, pinned_by=? WHERE id=?", (iso_ms(now_utc()), me(), m["id"]))
        changed = True
    elif not on and have:
        c.execute("UPDATE agent_chat SET pinned_at=NULL, pinned_by=NULL WHERE id=?", (m["id"],))
        changed = True
    m = c.execute("SELECT * FROM agent_chat WHERE id=?", (m["id"],)).fetchone()
    if changed and not by_agent:
        agent_emit(c, aid, "chat_pinned", {"message": chat_one(c, m, api=True), "pinned": on, "user": cpin_who(c, uid)})
    if changed:
        bump(c)  # the open chat of the person follows (area agentchat)
    c.commit()
    return {"ok": True, "message": chat_one(c, m, api=by_agent), "pins": cpin_agent_list(c, aid, uid, api=by_agent)}


@app.post("/api/agents/<int:aid>/chat/<int:mid>/pin")
def cpin_agent(aid, mid):
    """{pinned?: bool} -- I pin / unpin a message of my chat with agent aid (omitted: toggles)."""
    from ..agents.core import need_chat_agent
    c = db()
    need_chat_agent(c, aid)
    m = c.execute("SELECT * FROM agent_chat WHERE id=? AND agent_id=? AND user_id=?", (mid, aid, me())).fetchone()
    if not m:
        raise Denied(404)
    try:
        return jsonify(cpin_agent_set(c, m, body(), False))
    except BadInput as e:
        return err(str(e))


@app.post("/api/v1/agent/chats/<int:uid>/messages/<mid>/pin")
@v1_view
def v1_cpin_agent(uid, mid):
    """The agent pins / unpins a message of its chat with person uid ({pinned?}); no event to itself."""
    from ..agents.core import agent_shares, need_agent
    v1_args(())
    aid = need_agent()
    c = db()
    mid = as_int(mid, "mid", 1)  # a named path segment, so the OpenAPI path can call it {mid}
    b = v1_json()
    unknown = sorted(k for k in b if k != "pinned")
    if unknown:
        raise UnknownFields(unknown)
    m = c.execute("SELECT * FROM agent_chat WHERE id=? AND agent_id=? AND user_id=?", (mid, aid, uid)).fetchone()
    if not m or not agent_shares(c, aid, uid):
        raise Denied(404)
    return jsonify(cpin_agent_set(c, m, b, True))


def cpin_spec(paths, op, ok, errs, pid):
    """2.62.0 (#1848): the pin routes in the OpenAPI document (the fields pinned_at / pinned_by sit in TeamMessage and
    ChatMessage, the list pins in the conversation's answers)."""
    pin_body = {"type": "object", "properties": {"pinned": {"type": "boolean", "description": "true = pin, false = unpin; omitted = toggle"}}}
    res = {"type": "object", "properties": {"ok": {"type": "boolean"}, "message": {"type": "object"},
                                            "pins": {"type": "array", "items": {"type": "object"}, "description": "The pinned messages of the conversation, newest pin first"}}}
    paths["/team/messages/{id}/pin"] = {"post": op(f"2.62.0 (#1848): pin / unpin a message of a conversation you belong to (at most {CPIN_MAX} per "
                                                   "conversation, else 409; a deleted message 409)", "Team chat", ok(res) | errs("400", "404", "409"),
                                                   [pid(desc="Message id")], body=pin_body, scope="comments")}
    paths["/agent/chats/{id}/messages/{mid}/pin"] = {"post": op(f"2.62.0 (#1848): pin / unpin a message of your chat with a person (at most {CPIN_MAX} per "
                                                                "conversation, else 409). Pins of the person reach you as the event chat_pinned", "Agents",
                                                                ok(res) | errs("400", "403", "404", "409"), [pid("id", "User id"), pid("mid", "Message id")],
                                                                body=pin_body, scope="write")}
