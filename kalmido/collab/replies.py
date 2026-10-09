"""2.33.0 (#1076): replies to one message -- task comments, team chat and agent chat.

Every message table has a nullable column reply_to (the id of the answered message of the SAME place: the same task, the
same team conversation, the same person-agent conversation; anything else is refused with 400). A message carries
reply_to + reply: a short quote of the original ({id, user_id, name, text, deleted}); a deleted / trimmed original shows as
deleted (no text). The author of the original gets a push "replied to your message" (it counts like an @mention for the
notification settings); agents get the reference in their events (message.reply) to understand the answer.
2.32 keeps running with the column (it never reads it)."""
import re

from ..core.i18n import tr

QUOTE_CHARS = 140
MENTION_RE = re.compile(r"<@(\d+)>")
_TABLES = {"c": "comments", "t": "tchat_msgs", "a": "agent_chat"}


def reply_id(v):
    """reply_to of a request body: None / '' / 0 = none, else a positive int (BadInput otherwise)."""
    from ..personal.timetrack import BadInput
    if v in (None, "", 0, "0"):
        return None
    if isinstance(v, bool):
        raise BadInput(tr("Invalid value: {0}", "reply_to"))
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", "reply_to"))
    if n < 1:
        raise BadInput(tr("Invalid value: {0}", "reply_to"))
    return n


def reply_check(c, art, v, **where):
    """The answered message (row) of the same place, else BadInput (400). where: task_id= | room_id= | agent_id= + user_id=.
    A deleted original cannot be answered."""
    from ..personal.timetrack import BadInput
    rid = reply_id(v)
    if rid is None:
        return None
    cond = " AND ".join(f"{k}=?" for k in where)
    r = c.execute(f"SELECT * FROM {_TABLES[art]} WHERE id=? AND {cond}", (rid, *where.values())).fetchone()
    if not r or ("deleted_at" in r.keys() and r["deleted_at"]):
        raise BadInput(tr("Invalid value: {0}", "reply_to"))
    return r


def _plain(c, body, names):
    from ..collab.teamchat import md_brief
    t = MENTION_RE.sub(lambda m: "@" + names.get(int(m.group(1)), "?"), md_brief(body or ""))
    t = re.sub(r"\s+", " ", t).strip()
    return t[:QUOTE_CHARS] + ("…" if len(t) > QUOTE_CHARS else "")


def reply_quotes(c, art, ids):
    """{original id: quote} for the reply_to ids of art ('c' | 't' | 'a'). Missing / deleted ones: {id, deleted: true}."""
    from ..collab.comments import user_names
    ids = sorted({int(i) for i in ids if i})
    if not ids:
        return {}
    rows = {r["id"]: r for r in c.execute(f"SELECT * FROM {_TABLES[art]} WHERE id IN ({','.join('?' * len(ids))})", ids)}
    uids = set()
    for r in rows.values():
        uids.add(r["agent_id"] if art == "a" and r["sender"] == "agent" else r["user_id"])
        uids |= {int(x) for x in MENTION_RE.findall(r["body"] or "")}
    names = user_names(c, uids)
    out = {}
    for i in ids:
        r = rows.get(i)
        if not r or ("deleted_at" in r.keys() and r["deleted_at"]):
            out[i] = {"id": i, "deleted": True, "user_id": None, "name": "", "text": ""}
            continue
        uid = r["agent_id"] if art == "a" and r["sender"] == "agent" else r["user_id"]
        text = _plain(c, r["body"], names)
        if not text and art in ("a", "c"):  # only files: the first file's name
            f = c.execute("SELECT name FROM chat_files WHERE message_id=? ORDER BY id LIMIT 1" if art == "a" else
                          "SELECT name FROM attachments WHERE comment_id=? ORDER BY id LIMIT 1", (i,)).fetchone()
            text = f["name"][:QUOTE_CHARS] if f else ""
        q = {"id": i, "deleted": False, "user_id": uid, "name": names.get(uid, ""), "text": text}
        if art == "a":
            q["from"] = r["sender"]
        out[i] = q
    return out


def with_replies(c, art, dicts, key="reply_to"):
    """Adds reply (the quote) to message dicts that have reply_to set (in place, returns dicts)."""
    qs = reply_quotes(c, art, [d.get(key) for d in dicts])
    for d in dicts:
        d["reply"] = qs.get(d.get(key)) if d.get(key) else None
    return dicts


def reply_of(c, art, row):
    """(reply_to, quote) of one row (for the single-message serializers)."""
    rt = row["reply_to"] if "reply_to" in row.keys() else None
    if not rt:
        return None, None
    return rt, reply_quotes(c, art, [rt]).get(rt)
