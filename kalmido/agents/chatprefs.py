"""2.233.0 A (#2848): the chat settings of a person for one agent's chat and the collected suggestions.

Settings (table agent_chat_prefs, one row per agent and person, every device): sugg latest | collect | keep (what happens to
an agent's answer buttons once a newer message came), jobs full | line (a job's result in the chat), pin on | off (open
approvals pinned at the top), notices full | line (the agent's notices after a wake-up). Only the person sees and changes
their own; an agent not shared with them answers 404.

Collected suggestions: an agent message with answer buttons that ended only because a newer message came (chat.choice_state
-> "collected") stays answerable for SUGG_HOURS, at most SUGG_MAX per conversation (the newest), unless the person dismissed
it (choices.dismissed_at, older versions ignore the key), the agent withdrew it or the setting is "latest". Permission
questions and approval requests keep their own rules."""
import json
from datetime import timedelta
from flask import jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, iso_ms, now_utc
from ..accounts.session import me
from ..core.access import Denied
from ..core.errors import BadInput, UnknownFields
from ..agents.core import need_chat_agent
from ..agents.chat import _jload, _newer_than, chat_newest, chat_one, choice_state

CP_DEFAULTS = {"sugg": "keep", "jobs": "full", "pin": "on", "notices": "full"}  # 2.331.0 (#3309): suggestions stay at their message by default (was collect)
CP_VALUES = {"sugg": ("latest", "collect", "keep"), "jobs": ("full", "line"), "pin": ("on", "off"), "notices": ("full", "line")}
SUGG_HOURS = 24
SUGG_MAX = 10


def cp_get(c, aid, uid):
    """The person's chat settings for agent aid (defaults filled in, unknown / old values dropped)."""
    r = c.execute("SELECT prefs FROM agent_chat_prefs WHERE agent_id=? AND user_id=?", (aid, uid)).fetchone()
    try:
        p = json.loads(r["prefs"]) if r and isinstance(r["prefs"], str) else (r["prefs"] if r else None)
    except ValueError:
        p = None
    p = p if isinstance(p, dict) else {}
    return {k: p[k] if p.get(k) in CP_VALUES[k] else d for k, d in CP_DEFAULTS.items()}


def cp_collected(c, aid, uid, newest):
    """The ids of the collected suggestions of the conversation (newest first, at most SUGG_MAX). newest = chat_newest."""
    if cp_get(c, aid, uid)["sugg"] == "latest":
        return ()
    cut = iso_ms(now_utc() - timedelta(hours=SUGG_HOURS))
    out = []
    for r in c.execute("""SELECT id, job_id, choices FROM agent_chat WHERE agent_id=? AND user_id=? AND sender='agent' AND kind IS NULL
                          AND choice IS NULL AND choices IS NOT NULL AND created_at>=? AND choices->>'withdrawn_at' IS NULL
                          AND choices->>'dismissed_at' IS NULL AND choices->>'approval' IS NULL
                          AND COALESCE(choices->>'permission', '0') IN ('0', 'false')
                          ORDER BY id DESC LIMIT 200""", (aid, uid, cut)):
        ch = _jload(r["choices"]) or {}
        cs = ch.get("choices") or []
        if not cs or all(x.get("href") for x in cs):  # link buttons (office cards) never answer
            continue
        if _newer_than(newest, r):
            out.append(r["id"])
            if len(out) >= SUGG_MAX:
                break
    return tuple(out)


@app.get("/api/agents/<int:aid>/chat-prefs")
def cp_route_get(aid):
    c = db()
    need_chat_agent(c, aid)
    return jsonify(prefs=cp_get(c, aid, me()), defaults=CP_DEFAULTS)


@app.put("/api/agents/<int:aid>/chat-prefs")
def cp_route_put(aid):
    """{sugg?, jobs?, pin?, notices?} -- changes only the given keys (autosave per field)."""
    c = db()
    need_chat_agent(c, aid)
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid value: {0}", "prefs"))
    unknown = sorted(k for k in b if k not in CP_DEFAULTS)
    if unknown:
        raise UnknownFields(unknown)
    for k, v in b.items():
        if v not in CP_VALUES[k]:
            raise BadInput(tr("Invalid value: {0}", k))
    # merged in the database: two fields saved at the same moment (autosave) both stay
    c.execute("""INSERT INTO agent_chat_prefs(agent_id,user_id,prefs,updated_at) VALUES(?,?,?,?)
                 ON CONFLICT (agent_id, user_id) DO UPDATE SET prefs=agent_chat_prefs.prefs || EXCLUDED.prefs, updated_at=EXCLUDED.updated_at""",
              (aid, me(), json.dumps(b), iso_ms(now_utc())))
    bump(c)
    c.commit()
    return jsonify(prefs=cp_get(c, aid, me()), defaults=CP_DEFAULTS)


@app.post("/api/agents/<int:aid>/chat/<int:mid>/dismiss")
def cp_route_dismiss(aid, mid):
    """X on a collected suggestion: it leaves the collection on every device (choices.dismissed_at); a press then answers 409."""
    c = db()
    need_chat_agent(c, aid)
    m = c.execute("SELECT * FROM agent_chat WHERE id=? AND agent_id=? AND user_id=?", (mid, aid, me())).fetchone()
    ch = _jload(m["choices"]) if m else None
    if not m or m["sender"] != "agent" or not ch:
        raise Denied(404)
    if choice_state(m, ch, _jload(m["choice"]), chat_newest(c, aid, me())) != "collected":
        raise Denied(409, tr("This suggestion is no longer current"))
    ch = {**ch, "dismissed_at": iso_ms(now_utc())}
    c.execute("UPDATE agent_chat SET choices=? WHERE id=?", (json.dumps(ch, ensure_ascii=False), mid))
    bump(c)
    c.commit()
    return jsonify(chat_one(c, c.execute("SELECT * FROM agent_chat WHERE id=?", (mid,)).fetchone()))
