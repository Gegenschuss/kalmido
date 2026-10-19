"""2.56.0 A (#1791 / #1793): talking to one job of an agent -- a message from the job card (the 'job' event with
action 'message') and the job's own history in the person's chat with the agent (?job= on GET /api/agents/<id>/chat).

The history is the person's own conversation only, narrowed to: the agent's messages that belong to the job (job_id),
the person's messages addressed to it ("Clara: ...", "Job 82: ...", "#82: ..." -- the way the agent's service reads
them) and the agent's direct answers to those (reply_to)."""
import re

from flask import jsonify

from ..core.i18n import tr
from ..core.db import body, err, like_escape
from ..accounts.session import me
from ..core.access import Denied
from ..collab.comments import user_names
from ..agents.core import agent_emit, jc_job_name, JOB_MESSAGE_MAX, job_dict, job_visible



def jc_job_message(c, j):
    """POST /api/agents/jobs/<id>/action {action: message, text}: only the 'job' event {action: message, text, job, user};
    the job row stays untouched (no state, no action fields, no approval, no task history). Rights and the ended check
    are done by the caller (like stop)."""
    text = body().get("text")
    if not isinstance(text, str) or not text.strip():
        return err(tr("The message is empty"))
    if len(text) > JOB_MESSAGE_MAX:
        return err(tr("The message is too long (max. {0} characters)", JOB_MESSAGE_MAX))
    seq = agent_emit(c, j["agent_id"], "job", {"job": job_dict(c, j), "action": "message", "text": text.strip(),
                                               "user": {"id": me(), "name": user_names(c, [me()]).get(me(), "")}})
    if seq is None:  # review: a paused agent / one that does not hear the job's list gets nothing -- say so, never "sent"
        return err(tr("The agent does not get this message now (paused, or the job's list is not shared with it)"), 409)
    c.commit()
    return jsonify(ok=True, job=job_dict(c, j))


def jc_prefixes(j):
    """The lower-case starts of a person's message addressed to job j."""
    jid = int(j["id"])
    out = [f"job {jid}:", f"job #{jid}:", f"#{jid}:", f"@job {jid}:"]
    name = jc_job_name(j["title"], j["name"] if "name" in j.keys() else None)  # 2.58.0 (#1803)
    if name:
        out += [f"{name.lower()}:", f"@{name.lower()}:"]
    return out


def jc_chat_rows(c, aid, jid, before, limit, after=0):
    """(rows oldest first, has_more) of job jid in my conversation with agent aid; a job of another agent or one I
    cannot see = 404 (never someone else's conversation: every query is bound to agent_id + user_id = me)."""
    uid = me()
    j = c.execute("SELECT * FROM agent_jobs WHERE id=? AND agent_id=?", (jid, aid)).fetchone()
    if not j or not job_visible(c, j, uid):
        raise Denied(404)
    pre = jc_prefixes(j)
    # review: my addressed messages only from the job's start on (a reused first name must not pull in an older job's)
    q = ("SELECT * FROM agent_chat WHERE agent_id=? AND user_id=? AND (job_id=? OR (sender='user' AND created_at>=? AND ("
         + " OR ".join("body ILIKE ? ESCAPE '\\'" for _p in pre) + ")))")
    # 2.86.0 (N28): a job name with % or _ is matched literally
    args = [aid, uid, jid, j["created_at"] or "", *[like_escape(p) + "%" for p in pre]]
    if after:
        q += " AND id>?"
        args.append(after)
    if before:
        q += " AND id<?"
        args.append(before)
    rows = c.execute(q + " ORDER BY id DESC LIMIT ?", (*args, limit + 1)).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    asked = [r["id"] for r in rows if r["sender"] == "user"]
    if asked:  # the agent's direct answers to them (e.g. "delivered to Clara")
        have = {r["id"] for r in rows}
        rows += [r for r in c.execute(f"SELECT * FROM agent_chat WHERE agent_id=? AND user_id=? AND sender='agent' AND reply_to IN "
                                      f"({','.join('?' * len(asked))}) AND id>?", (aid, uid, *asked, after)).fetchall() if r["id"] not in have]
    rows.sort(key=lambda r: r["id"])
    return rows, more


# ---- 2.96.0 C (#2015): one card per job in the chat. A job message carries its kind (job_msg, set by the agent's chat
# post; NULL = unknown, the app derives it from the text) and the chat answer carries the jobs of its messages, so the
# app draws name, version and state of each card without an extra call.
JCD_KINDS = ("say", "question", "result", "error")
JCD_VERSION_RE = re.compile(r"\d+\.\d+(?:\.\d+)?[a-z]?")


def jcd_jobs(c, aid, msgs, uid):
    """{str(id): {id, agent_id, user_id, name, title, version, state, parent_id, parent_name, updated_at}} of the jobs of the chat messages
    msgs (dicts with job_id / job_parent) -- only jobs of agent aid that uid may see (job_visible), like the names."""
    ids = sorted({int(i) for m in msgs for i in (m.get("job_id"), m.get("job_parent")) if i})
    if not ids:
        return {}
    rows = {j["id"]: j for j in c.execute(f"SELECT * FROM agent_jobs WHERE agent_id=? AND id IN ({','.join('?' * len(ids))})", (aid, *ids))}
    pids = sorted({j["parent_id"] for j in rows.values() if j["parent_id"]} - set(rows))
    if pids:
        rows.update({j["id"]: j for j in c.execute(f"SELECT * FROM agent_jobs WHERE agent_id=? AND id IN ({','.join('?' * len(pids))})", (aid, *pids))})
    seen = {i: j for i, j in rows.items() if job_visible(c, j, uid)}
    out = {}
    for i in ids:
        j = seen.get(i)
        if not j:
            continue
        par = seen.get(j["parent_id"]) if j["parent_id"] else None
        v = JCD_VERSION_RE.search(j["title"] or "")
        out[str(i)] = {"id": i, "agent_id": j["agent_id"], "user_id": j["user_id"], "name": jc_job_name(j["title"], j["name"]), "title": j["title"], "version": v.group(0) if v else "",
                       "state": j["state"], "parent_id": par["id"] if par else None,
                       "parent_name": jc_job_name(par["title"], par["name"]) if par else None, "updated_at": j["updated_at"]}
    return out
