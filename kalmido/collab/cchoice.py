"""2.41.0 (#1383): answer buttons, approval cards and suggestions in task comments, like in the agent chat.

An agent's comment may carry `choices` in the same format as a chat message (agents/chat.py): frei benannte buttons
[{id, label, style?}] (+ multi), an approval card (approval = {title, what?, yes_label?, no_label?} -> buttons yes / no,
choices.approval = {title, what, std?}) and expires_in. States as in the chat: open | answered | expired | withdrawn.
#1037: only the newest question of a task is live -- plain buttons expire as soon as a newer comment comes (an approval
card does not, nor does it expire others); an approval card stays open until answered, its time ran out or the agent
withdraws it. The answer {ids, at, user_id, via} is written once (never changed) and logged in the task's history
(activity "choice"). Only people who may edit the task answer (never an agent account); the answer reaches the agent
that wrote the comment as a `comment` event with `answer` (a pressed suggestion first becomes the person's comment with
that text, as if typed). A 👍 / 👎 on the comment keeps working as before (the short form)."""
import json

from flask import g, jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.pg import insert_id
from ..core.db import body, bump, db, iso_ms, now_utc
from ..accounts.session import me
from ..core.access import Denied, need_feat, need_task, task_visible
from ..core.errors import BadInput, reject_unknown
from ..api.common import v1_args, v1_json, v1_view

CHOICE_KEYS = ("choices", "multi", "approval", "expires_in")


def lv_jload(v):
    if v is None or isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v) if v else None
    except ValueError:
        return None


def lv_choices_in(b, agent):
    """The stored json of choices / multi / approval / expires_in of a new comment, or None. Only agents (else 403)."""
    from ..agents.chat import chat_approval_clean, chat_choices_clean
    if not any(b.get(k) not in (None, "", [], False) for k in CHOICE_KEYS):
        return None
    if not agent:
        raise Denied(403, tr("Only agents can post answer buttons"))
    if b.get("approval") not in (None, "", {}):
        if any(b.get(k) not in (None, "", [], False) for k in ("choices", "multi")):
            raise BadInput(tr("Invalid value: {0}", "choices"))
        return chat_approval_clean(b["approval"], b.get("expires_in"))
    v = chat_choices_clean(b.get("choices"), b.get("multi"), None, None)
    if b.get("expires_in") not in (None, ""):
        raise BadInput(tr("Invalid value: {0}", "expires_in"))
    if v and json.loads(v).get("permission"):  # a permission question belongs to the chat (its host waits there)
        raise BadInput(tr("Invalid value: {0}", "choices"))
    return v


def lv_newest(c, tid):
    """Id of the task's newest comment that is no approval card (#1037: it makes older buttons expire)."""
    r = c.execute("""SELECT MAX(id) FROM comments WHERE task_id=? AND deleted_at IS NULL
                     AND (choices IS NULL OR choices->>'approval' IS NULL)""", (tid,)).fetchone()
    return (r[0] or 0) if r else 0


def lv_state(r, ch, ans, newest):
    """open | answered | expired | withdrawn of a comment with buttons (None without)."""
    if not ch:
        return None
    if ans:
        return "answered"
    if ch.get("withdrawn_at"):
        return "withdrawn" if not ch.get("outcome") else "expired"
    if ch.get("approval"):
        return "expired" if ch.get("expires_at") and ch["expires_at"] <= iso_ms(now_utc()) else "open"
    return "expired" if newest and newest > r["id"] else "open"


def lv_with_choices(c, tid, rows, dicts):
    """Adds choices, choice, choice_state (and choice.user_name) to the comment dicts of rows (same order)."""
    from ..collab.comments import user_names
    newest = None
    anss = [lv_jload(r["choice"]) if "choice" in r.keys() else None for r in rows]
    # 2.41.0 (#1383): the answerers' names in one query (was one per answered comment)
    names = user_names(c, [a.get("user_id") for a in anss if isinstance(a, dict)])
    for r, d, ans in zip(rows, dicts, anss):
        ch = lv_jload(r["choices"]) if "choices" in r.keys() else None
        if ch and newest is None:
            newest = lv_newest(c, tid)
        if ans and ans.get("user_id"):
            ans = {**ans, "user_name": names.get(ans["user_id"], "")}
        d.update(choices=ch, choice=ans, choice_state=lv_state(r, ch, ans, newest or 0))
    return dicts


def lv_approvals_open(c, tid):
    """The open approval cards of a task (newest last) -- the task's badge / its notification."""
    rows = c.execute("""SELECT * FROM comments WHERE task_id=? AND deleted_at IS NULL AND choice IS NULL AND choices IS NOT NULL
                        AND choices->>'approval' IS NOT NULL AND choices->>'withdrawn_at' IS NULL ORDER BY id""", (tid,)).fetchall()
    return [r for r in rows if lv_state(r, lv_jload(r["choices"]), None, 0) == "open"]


def lv_answer(c, r, uid, ids, via="button"):
    """The person uid answers comment r with ids: stored once, logged, the agent hears it. -> (row, the person's comment id
    of a suggestion or None). Denied / BadInput."""
    from ..agents.core import agent_comment, agent_emit, agent_task_data, is_agent
    from ..tasks.validation import log_act
    from ..collab.comments import user_names
    ch = lv_jload(r["choices"])
    au = c.execute("SELECT kind FROM users WHERE id=?", (r["user_id"],)).fetchone() if r["user_id"] else None
    if not ch or not au or au["kind"] != "agent":
        raise Denied(404)
    if is_agent(c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()):
        raise Denied(403, tr("Agents cannot answer"))
    if not task_visible(c, r["task_id"], uid, write=True):
        raise Denied(403, tr("Only people who can edit the task can answer"))
    from ..agents.core import agent_usable
    lid = c.execute("SELECT list_id FROM tasks WHERE id=?", (r["task_id"],)).fetchone()[0]
    if not agent_usable(c, r["user_id"], uid, lid):  # #928: the agent would never hear it (a silent answer helps nobody)
        raise Denied(403, tr("This agent does not take instructions from you in this list"))
    if r["choice"]:
        raise Denied(409, tr("This question was answered already"))
    if lv_state(r, ch, None, lv_newest(c, r["task_id"])) != "open":
        raise Denied(409, tr("This suggestion is no longer current"))
    valid = [x["id"] for x in ch["choices"]]
    if not isinstance(ids, list) or not ids or not all(isinstance(x, str) and x in valid for x in ids) or len(set(ids)) != len(ids) \
            or (len(ids) > 1 and not ch.get("multi")):
        raise BadInput(tr("Invalid value: {0}", "choice_ids"))
    ids = [x for x in valid if x in ids]
    ans = {"ids": ids, "at": iso_ms(now_utc()), "user_id": uid, "via": via}
    c.execute("UPDATE comments SET choice=? WHERE id=? AND choice IS NULL", (json.dumps(ans), r["id"]))
    labels = [x["label"] for x in ch["choices"] if x["id"] in ids]
    ap = ch.get("approval")
    approval = ("approved" if ids == ["yes"] else "rejected") if ap else None
    log_act(c, r["task_id"], "choice", {"comment": r["id"], "ids": ids, "labels": labels,
                                        **({"approval": approval, "title": ap.get("title", "")} if ap else {})}, uid=uid)
    said = None
    if not ap:  # a suggestion / answer button: the person's comment with that text, as if typed (the thread shows it)
        said = insert_id(c, "INSERT INTO comments(task_id,user_id,body,mentions,created_at,reply_to) VALUES(?,?,?,?,?,?)",
                         (r["task_id"], uid, ", ".join(labels), "", iso_ms(now_utc()), r["id"]))
        c.execute("INSERT INTO task_seen(user_id,task_id,seen_id) VALUES(?,?,?) "
                  "ON CONFLICT(user_id,task_id) DO UPDATE SET seen_id=GREATEST(task_seen.seen_id, excluded.seen_id)", (uid, r["task_id"], said))
    r2 = c.execute("SELECT * FROM comments WHERE id=?", (r["id"],)).fetchone()
    aid = r["user_id"]
    if task_visible(c, r["task_id"], aid, full=True):  # agent_emit keeps health lists away from agents
        k = c.execute("SELECT * FROM comments WHERE id=?", (said or r["id"],)).fetchone()
        answer = {"comment_id": r["id"], "choice_ids": ids, "labels": labels, "via": via,
                  "user": {"id": uid, "name": user_names(c, [uid]).get(uid, "")},
                  **({"approval": approval, "approval_request": {"title": ap.get("title", ""), "what": ap.get("what", "")}} if ap else {})}
        agent_emit(c, aid, "comment", agent_task_data(c, r["task_id"], aid, comment=agent_comment(c, k), answer=answer))
    return r2, said


def lv_withdraw(c, r, aid, outcome=None):
    """The agent takes back the open buttons of its comment (outcome on an approval card: denied | expired)."""
    ch = lv_jload(r["choices"])
    if not ch or r["user_id"] != aid:
        raise Denied(404)
    if outcome not in (None, "", "denied", "expired") or (outcome and not ch.get("approval")):
        raise BadInput(tr("Invalid value: {0}", "outcome"))
    if r["choice"]:
        raise Denied(409, tr("This question was answered already"))
    ch = {**ch, "withdrawn_at": iso_ms(now_utc()), **({"outcome": outcome} if outcome else {})}
    c.execute("UPDATE comments SET choices=? WHERE id=?", (json.dumps(ch, ensure_ascii=False), r["id"]))
    return c.execute("SELECT * FROM comments WHERE id=?", (r["id"],)).fetchone()


def lv_one(c, r):
    from ..collab.comments import att_dicts, comment_dict
    from ..collab.reactions import with_reactions
    from ..collab.replies import with_replies
    d = with_replies(c, "c", with_reactions(c, [comment_dict(r, att_dicts(c, "comment_id=?", (r["id"],)))]))
    return lv_with_choices(c, r["task_id"], [r], d)[0]


@app.post("/api/comments/<int:cid>/choice")
def comment_choice(cid):
    """{choice_ids: [...]} -- I answer an agent's comment with its buttons (yes / no of an approval card, a suggestion)."""
    c = db()
    need_feat("comments")
    r = c.execute("SELECT * FROM comments WHERE id=? AND deleted_at IS NULL", (cid,)).fetchone()
    if not r:
        raise Denied(404)
    need_task(c, r["task_id"], write=False, full=True)
    r2, said = lv_answer(c, r, me(), body().get("choice_ids"))
    bump(c)
    c.commit()
    return jsonify({**lv_one(c, r2), "answer_comment_id": said})


@app.get("/api/comments/<int:cid>/choice")
def comment_choice_get(cid):
    """The state of a comment's buttons: {choices, choice, choice_state}."""
    c = db()
    need_feat("comments")  # 2.41.0 (#1383): like the other comment routes
    r = c.execute("SELECT * FROM comments WHERE id=? AND deleted_at IS NULL", (cid,)).fetchone()
    if not r:
        raise Denied(404)
    need_task(c, r["task_id"], write=False, full=True)
    d = lv_one(c, r)
    return jsonify({k: d[k] for k in ("id", "choices", "choice", "choice_state")})


def lv_v1_dict(c, d):
    from ..api.v1 import v1_comment
    from ..collab.comments import user_names
    return v1_comment(c, d, user_names(c, [d["user_id"]] if d.get("user_id") else []))


@app.post("/api/v1/comments/<int:cid>/withdraw")
@v1_view
def v1_comment_withdraw(cid):
    """{outcome?} -- the agent takes back the open buttons / approval card of its own comment (MCP withdraw_comment_choices)."""
    from ..agents.core import is_agent
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("outcome",))
    c = db()
    r = c.execute("SELECT * FROM comments WHERE id=? AND deleted_at IS NULL", (cid,)).fetchone()
    if not r or not task_visible(c, r["task_id"], me(), full=True):
        raise Denied(404)
    if not is_agent(g.user):  # 2.41.1 (#1383): after the lookup, like the neighbours (an unknown comment is 404, not 403)
        raise Denied(403)
    r2 = lv_withdraw(c, r, me(), b.get("outcome"))
    bump(c)
    c.commit()
    return jsonify(lv_v1_dict(c, {**lv_one(c, r2), "task_id": r2["task_id"]}))


@app.post("/api/v1/comments/<int:cid>/choice")
@v1_view
def v1_comment_choice(cid):
    """{choice_ids: [...]} -- a person (own token) answers an agent's comment with its buttons; agents never answer (403)."""
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("choice_ids",))
    c = db()
    r = c.execute("SELECT * FROM comments WHERE id=? AND deleted_at IS NULL", (cid,)).fetchone()
    if not r:
        raise Denied(404)
    need_task(c, r["task_id"], write=False, full=True)
    r2, said = lv_answer(c, r, me(), b.get("choice_ids"))
    bump(c)
    c.commit()
    return jsonify({**lv_v1_dict(c, {**lv_one(c, r2), "task_id": r2["task_id"]}), "answer_comment_id": said})
