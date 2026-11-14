"""2.1130.0 (#6057): the in-app pop-up for new chat messages (static/js/msgpop.js).

A new message of a person (team chat: a project's conversation, a channel, a group, a direct message, a thread I take part
in) or a finished answer / question of an agent in my own chat with it shows as a small card at the edge of the app, wherever
the person is. It is no bell entry (the bell stays "waiting for you"). The app asks GET /api/msgpop when the poll says the
team chat or the agent chat moved, with the highest ids it knows; the first call of a window (no ids) only answers where
it starts. Nothing is marked read here (unlike GET /api/agents/<id>/chat). Only people: an agent never gets pop-ups.

Agent messages: only an answer or a question - a notice line, a job's brief, a job's progress line ("say", the start line)
never; a job's result / error / question does. Its own messages of the person never (sender 'user')."""
from flask import jsonify, request

from ..core.config import app
from ..core.db import db
from ..core.access import Denied
from ..accounts.session import me
from ..accounts.pictures import avatar_url
from ..tasks.validation import as_int
from ..collab.teamchat import tchat_new_for, tchat_rooms
from ..collab.liste2eguard import le2b_net
from .core import need_person
from .chat import chat_agent_or_org, chat_asks, chat_is_final, JCB_NOT_SQL

MP_MAX = 20  # at most this many messages per source and answer (the app bundles them per sender anyway)
MP_TEXT = 140  # the first line, cut


def mp_first_line(s):
    s = le2b_net(str(s or "")).strip()
    return (s.split("\n", 1)[0].strip() or s)[:MP_TEXT]


def mp_agent_new(c, uid, after):
    """(my agents' new answers / questions above `after`, newest first; the highest id of my agent chats)."""
    top = c.execute("SELECT COALESCE(MAX(id),0) FROM agent_chat WHERE user_id=?", (uid,)).fetchone()[0]
    if after is None:
        return [], top
    rows = c.execute(f"""SELECT * FROM agent_chat WHERE user_id=? AND sender='agent' AND read_at IS NULL AND id>?
                         AND COALESCE(kind,'') IN ('', 'message', 'unshared') AND {JCB_NOT_SQL}
                         ORDER BY id DESC LIMIT ?""", (uid, after, MP_MAX * 3)).fetchall()
    rows = [r for r in rows if chat_is_final(r)]
    # review 2.1130.0: only agents the person may still chat with (as GET /api/agents/<id>/chat), not just rows of her own
    ok = set()
    for aid in {r["agent_id"] for r in rows}:
        try:
            chat_agent_or_org(c, aid)
            ok.add(aid)
        except Denied:
            pass
    out = [{"src": "agent", "id": r["id"], "agent_id": r["agent_id"], "from": r["agent_id"], "text": mp_first_line(r["body"]),
            "asks": bool(chat_asks(r["body"])), "at": r["created_at"]} for r in rows if r["agent_id"] in ok]
    return out[:MP_MAX], max([top, after] + [r["id"] for r in rows])


@app.get("/api/msgpop")
def msgpop_get():
    """?t=<highest team chat message id known> &a=<highest agent chat message id known> -> {t, a, items}: the new messages of
    others for the pop-up, newest first ({src team|agent, id, from, name, avatar, text, room_id, room, kind, thread, enc,
    file, mention | agent_id, asks; at); t / a = what to send next time. Without t / a: the window's start (the team chat's
    overlap below the cursor still comes, the app only takes note of it). ?only=team|agent: the side that moved (the other
    keeps its cursor, nothing of it is read)."""
    need_person(403)
    c = db()
    uid = me()
    first = "t" not in request.args and "a" not in request.args
    t = None if first else as_int(request.args.get("t", 0), "t", 0)
    a = None if first else as_int(request.args.get("a", 0), "a", 0)
    only = request.args.get("only", "") if not first else ""
    tm, t2 = tchat_new_for(c, uid, t, MP_MAX) if only != "agent" else ([], t)
    am, a2 = mp_agent_new(c, uid, a) if only != "team" else ([], a)
    rooms = {r["id"]: r for r in tchat_rooms(c, uid, full=True)} if tm else {}
    tm = [m for m in tm if m["room_id"] in rooms]
    ids = sorted({m["user_id"] for m in tm if m["user_id"]} | {m["from"] for m in am})
    users = {r["id"]: r for r in c.execute("SELECT id, username, display_name, avatar, kind FROM users WHERE id = ANY(CAST(? AS BIGINT[]))",
                                            (ids,))} if ids else {}
    who = lambda i: (users[i]["display_name"] or users[i]["username"]) if i in users else "?"  # noqa: E731
    items = []
    for m in tm:
        r = rooms[m["room_id"]]
        items.append({"src": "team", "id": m["id"], "from": m["user_id"], "name": who(m["user_id"]),
                      "avatar": avatar_url(users[m["user_id"]]) if m["user_id"] in users else "",
                      "text": mp_first_line(m["text"]), "room_id": m["room_id"], "kind": r["kind"],
                      "room": "" if r["kind"] == "dm" else le2b_net(r.get("name") or ""), "thread": m["thread"],
                      "enc": m["enc"], "file": m["file"], "mention": m["mention"], "at": m["at"]})
    for m in am:
        items.append({**m, "name": who(m["from"]), "avatar": avatar_url(users[m["from"]]) if m["from"] in users else ""})
    return jsonify(t=t2, a=a2, items=items)
