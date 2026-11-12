"""2.1039.0 (#5804 #5805): what an agent asks the person in its chat stands in the bell's "For you" and counts.

Two kinds of News entries (notifications), written when the agent's message is posted and judged again when the feed is read:
- approval (#5804): an open approval request or permission question of the agent chat (the same cards chat_approvals_open
  lists). One entry per card (data.chat = the message id). An approval counts once: a card of a job whose waiting job
  already has its unread approval entry writes none, and a job that starts waiting after its card writes none
  (acn_job_has_entry); data.job lets news_read_job close it with the job. It stays "For you" until it is decided, withdrawn
  or expired (opening it in the bell or the chat does not end it: it still waits).
- agentask (#5805): a question of the agent to the person. Recognised only by structure, never by the text: a job message
  of kind "question" (job_msg, #2015 / #3382), or a message with answer buttons that are not links. Results, status lines,
  notices, briefs and plain messages never count. Read as soon as the person opens the agent's chat (agent_chat.read_at),
  answers it (a button, or the person's own message after it) or the agent takes the buttons back. The feed shows one row
  per agent ("Claude asks you: ..." + how many), like the row of direct messages.
Both: row "approval" of the notification settings (News on by default: an agent waits for the person), collab on only
(news_put), never for the agent's own account.
"""
import json

from ..core.db import iso, now_utc
from ..core.pg import st_ids

ACN_EXCERPT = 300


def _jl(v):
    if not v:
        return {}
    if isinstance(v, dict):
        return v
    try:
        d = json.loads(v)
    except (TypeError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def acn_kind(r):
    """'approval' | 'agentask' | None for agent chat row r (sender agent)."""
    if not r or r["sender"] != "agent" or (r["kind"] if "kind" in r.keys() else None):
        return None
    ch = _jl(r["choices"])
    if ch.get("approval") or ch.get("permission") not in (None, False, 0, "0", "false"):
        return "approval"
    jm = r["job_msg"] if "job_msg" in r.keys() else None
    if jm == "question":
        return "agentask"
    if any(isinstance(x, dict) and not x.get("href") for x in (ch.get("choices") or [])):
        return "agentask"
    return None


def acn_job_has_entry(c, uid, jid):
    """An unread approval entry of job jid for uid exists already (from the waiting job or from one of its cards)."""
    return bool(jid) and bool(c.execute("SELECT 1 FROM notifications WHERE user_id=? AND kind='approval' AND read_at IS NULL "
                                        "AND data->>'job' = ? LIMIT 1", (uid, str(jid))).fetchone())


def acn_news(c, r, s=None):
    """After agent chat message r was posted (caller commits): the News entry of an approval card or a question."""
    from ..collab.news import news_add
    k = acn_kind(r)
    if not k:
        return
    uid, aid = r["user_id"], r["agent_id"]
    ch = _jl(r["choices"])
    jid = r["job_id"] if "job_id" in r.keys() else None
    if k == "approval":
        if acn_job_has_entry(c, uid, jid):
            return
        title = ((ch.get("approval") or {}).get("title") if isinstance(ch.get("approval"), dict) else None) or (r["body"] or "")
        data = {"title": " ".join(title.split())[:200], "chat": r["id"], "agent": aid, **({"job": jid} if jid else {}),
                **({"permission": 1} if not ch.get("approval") else {})}
    else:
        data = {"text": " ".join((r["body"] or "").split())[:ACN_EXCERPT], "chat": r["id"], "agent": aid}
    news_add(c, uid, k, data=data, actor=aid, row="approval", s=s)


def acn_read(c, uid, aid=None, mids=None):
    """Marks uid's entries read (caller commits): of messages mids (approval + agentask), or with aid the questions of that
    agent (its chat was opened)."""
    ts = iso(now_utc())
    if mids:
        c.execute("UPDATE notifications SET read_at=? WHERE user_id=? AND kind IN ('approval','agentask') AND read_at IS NULL "
                  "AND data->>'chat' = ANY(CAST(? AS TEXT[]))", (ts, uid, st_ids(mids)))
        # a card of a job counted as the job's entry (acn_job_has_entry): deciding the card takes that entry along
        jids = [r[0] for r in c.execute("SELECT DISTINCT job_id FROM agent_chat WHERE id = ANY(CAST(? AS BIGINT[])) AND job_id IS NOT NULL "
                                        "AND choices->>'approval' IS NOT NULL", (st_ids(mids),))]
        if jids:
            c.execute("UPDATE notifications SET read_at=? WHERE user_id=? AND kind='approval' AND read_at IS NULL "
                      "AND data->>'job' = ANY(CAST(? AS TEXT[]))", (ts, uid, st_ids(jids)))
    if aid:
        c.execute("UPDATE notifications SET read_at=? WHERE user_id=? AND kind='agentask' AND read_at IS NULL AND actor_id=?",
                  (ts, uid, aid))


def acn_feed(c, uid, out):
    """news_items: judges the entries of chat messages again (a message gone = no item; a card no longer open, a question
    seen / answered = read) and folds the questions into one item per agent (newest first). Returns the new list."""
    from ..agents.chat import choice_state
    mids = sorted({int(x["data"]["chat"]) for x in out if x["kind"] in ("approval", "agentask")
                   and str((x.get("data") or {}).get("chat") or "").isdigit()})
    if not mids:
        return out
    rows = {r["id"]: r for r in c.execute("SELECT * FROM agent_chat WHERE id = ANY(CAST(? AS BIGINT[])) AND user_id=?", (st_ids(mids), uid))}
    last_user = {}
    for r in c.execute("SELECT agent_id, MAX(id) FROM agent_chat WHERE user_id=? AND sender='user' AND agent_id = ANY(CAST(? AS BIGINT[])) "
                       "GROUP BY agent_id", (uid, st_ids({r["agent_id"] for r in rows.values()}))):
        last_user[r[0]] = r[1]
    res, ask = [], {}
    for x in out:
        mid = (x.get("data") or {}).get("chat") if x["kind"] in ("approval", "agentask") else None
        if mid is None or not str(mid).isdigit():
            res.append(x)
            continue
        r = rows.get(int(mid))
        if not r:
            continue
        ch = _jl(r["choices"])
        if x["kind"] == "approval":  # waits until it is decided (opening it in the bell or the chat does not end it)
            x["read"] = choice_state(r, ch, r["choice"]) != "open"
            res.append(x)
            continue
        if r["read_at"] or r["choice"] or ch.get("withdrawn_at") or (last_user.get(r["agent_id"]) or 0) > r["id"]:
            x["read"] = True
        x["excerpt"] = x["data"].get("text") or ""
        key = (r["agent_id"], x["read"])
        if key in ask:  # one row per agent: the newest question, the count of all
            p = ask[key]
            p["ids"] += x["ids"]
            p["count"] += x["count"]
            continue
        ask[key] = x
        res.append(x)
    return res
