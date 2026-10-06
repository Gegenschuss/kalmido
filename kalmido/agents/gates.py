"""2.26.0 (#949): approval requests of coding agents WITHOUT a pull request, in two steps.

"Ready to integrate" (suggestion kind integrate): an agent working in its own branch / worktree asks to bring source into
target (e.g. feat/x -> main) and attaches its evidence (build, start, logs, tests -- free text). "Ready to deploy" (kind
deploy): bundles approved integrations (the comment ids) and a checklist: every open task of the list with the list tag
"deploy" (KALMIDO_DEPLOY_TAG). Like a merge request (#339) only an approver decides (list owner / admin, the task's
assignee, an instance admin; never an agent): 👍 approves, 👎 rejects. A deploy request with open checklist items is NOT
approved by 👍: the approver either finishes those tasks first or approves on purpose with "Approve anyway" (POST
/api/comments/<id>/decide {decision: approve, skip_checklist: true}); the skipped tasks are recorded in the request.
Kalmido never integrates or deploys anything: the agent does, after the approval event ("reaction" with data.gate).
"""
import json
import os
from flask import g, jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, iso_ms, now_utc
from ..accounts.session import me
from ..core.access import Denied, need_collab
from ..personal.timetrack import BadInput, UnknownFields

GATE_KINDS = ("integrate", "deploy")
DEPLOY_TAG = (os.environ.get("KALMIDO_DEPLOY_TAG") or "deploy").strip() or "deploy"
GATE_REF_MAX, GATE_TEXT_MAX, GATE_INTEGRATIONS_MAX, CHECKLIST_MAX = 200, 4000, 50, 100


def deploy_checklist(c, lid):
    """Open (not completed, not deleted) tasks of list lid with the list tag DEPLOY_TAG: [{id, title}]."""
    rows = c.execute("""SELECT t.id, t.title FROM tasks t JOIN task_list_tags x ON x.task_id=t.id JOIN list_tags lt ON lt.id=x.tag_id
                        WHERE t.list_id=? AND lt.list_id=? AND lt.name=? COLLATE NOCASE AND t.deleted_at IS NULL
                        AND t.completed_at IS NULL ORDER BY t.id LIMIT ?""", (lid, lid, DEPLOY_TAG, CHECKLIST_MAX)).fetchall()
    return [{"id": r["id"], "title": r["title"]} for r in rows]


def _text(s, k, mx, need=False):
    v = s.get(k)
    if v is None and not need:
        return ""
    if not isinstance(v, str) or (need and not v.strip()):
        raise BadInput(tr("Invalid value: {0}", k))
    return v.strip()[:mx]


def gate_clean(c, t, s):
    """Validates an agent's integrate / deploy request (comment suggestion) on task t; returns the stored suggestion."""
    kind = s.get("kind")
    allowed = {"integrate": ("kind", "source", "target", "summary", "evidence"),
               "deploy": ("kind", "summary", "evidence", "integrations")}[kind]
    unknown = sorted(k for k in s if k not in allowed)
    if unknown:
        raise UnknownFields(unknown)
    out = {"kind": kind, "summary": _text(s, "summary", GATE_TEXT_MAX), "evidence": _text(s, "evidence", GATE_TEXT_MAX, need=True),
           "state": "open"}
    if kind == "integrate":
        out["source"] = _text(s, "source", GATE_REF_MAX, need=True)
        out["target"] = _text(s, "target", GATE_REF_MAX) or "main"
        return out
    ids = s.get("integrations") or []
    if not isinstance(ids, list) or len(ids) > GATE_INTEGRATIONS_MAX or not all(isinstance(x, int) and not isinstance(x, bool) for x in ids):
        raise BadInput(tr("Invalid value: {0}", "integrations"))
    items = []
    for cid in dict.fromkeys(ids):
        k = c.execute("""SELECT k.id, k.suggestion, k.task_id FROM comments k JOIN tasks t ON t.id=k.task_id
                         WHERE k.id=? AND k.deleted_at IS NULL AND t.list_id=?""", (cid, t["list_id"])).fetchone()
        sg = json.loads(k["suggestion"]) if k and k["suggestion"] else None
        if not sg or sg.get("kind") != "integrate":
            raise BadInput(tr("{0} is not an integration request of this list", cid))
        if sg.get("state") != "approved":
            raise BadInput(tr("The integration {0} is not approved yet", cid))
        items.append({"comment_id": cid, "task_id": k["task_id"], "source": sg.get("source"), "target": sg.get("target")})
    out["integrations"] = items
    out["checklist"] = deploy_checklist(c, t["list_id"])
    out["tag"] = DEPLOY_TAG
    return out


def gate_decide(c, k, t, uid, approve, skip=False):
    """An approver's decision on a gate comment (the caller checked is_approver and commits). Returns the new state:
    approved | rejected | blocked (deploy with open checklist items and no skip: stays open)."""
    sug = json.loads(k["suggestion"])
    if sug.get("state") != "open":
        return sug.get("state")
    new = {**sug}
    if approve and sug["kind"] == "deploy":
        left = deploy_checklist(c, t["list_id"])
        new["checklist"] = left
        if left and not skip:
            c.execute("UPDATE comments SET suggestion=? WHERE id=?", (json.dumps(new, ensure_ascii=False), k["id"]))
            return "blocked"
        if left:
            new["skipped"] = left
    new.update(state="approved" if approve else "rejected", by=uid, at=iso(now_utc()))
    c.execute("UPDATE comments SET suggestion=? WHERE id=?", (json.dumps(new, ensure_ascii=False), k["id"]))
    return new["state"]


def gate_event(sug):
    """The part of the agent's reaction event about the request (data.gate)."""
    out = {"kind": sug["kind"], "state": sug.get("state")}
    for k in ("source", "target", "integrations", "checklist", "skipped"):
        if k in sug:
            out[k] = sug[k]
    return out


@app.post("/api/comments/<int:cid>/decide")
def gate_decide_route(cid):
    """{decision: approve | reject, skip_checklist?: bool} -- an approver decides on an agent's integrate / deploy request
    (the same as 👍 / 👎; skip_checklist approves a deploy request although tasks tagged deploy are still open)."""
    from ..collab.comments import comment_plain, need_live_comment, user_names
    from ..agents.core import agent_emit, agent_task_data, is_agent, is_approver
    from ..tasks.validation import log_act
    need_collab()
    c, b = db(), body()
    k, _ = need_live_comment(c, cid)
    t = c.execute("SELECT * FROM tasks WHERE id=?", (k["task_id"],)).fetchone()
    sug = json.loads(k["suggestion"]) if k["suggestion"] else None
    if not sug or sug.get("kind") not in GATE_KINDS:
        raise Denied(404)
    if b.get("decision") not in ("approve", "reject") or not isinstance(b.get("skip_checklist", False), bool):
        return err(tr("Invalid value: {0}", "decision"))
    if is_agent(g.user) or not is_approver(c, t, me()):
        return err(tr("Only the list owner, a list admin, the assignee or an admin can decide"), 403)
    if sug.get("state") != "open":
        return err(tr("This request was already decided"), 409)
    approve = b["decision"] == "approve"
    st = gate_decide(c, k, t, me(), approve, b.get("skip_checklist", False))
    if st != "blocked":
        c.execute("INSERT OR IGNORE INTO comment_reactions(comment_id,user_id,emoji,created_at) VALUES(?,?,?,?)",
                  (cid, me(), "up" if approve else "down", iso_ms(now_utc())))
        log_act(c, t["id"], "approval", {"agent": k["user_id"], "comment": cid, "ok": approve})
        author = c.execute("SELECT * FROM users WHERE id=?", (k["user_id"],)).fetchone()
        k2 = c.execute("SELECT * FROM comments WHERE id=?", (cid,)).fetchone()
        s2 = json.loads(k2["suggestion"])
        if is_agent(author):
            agent_emit(c, author["id"], "reaction", agent_task_data(
                c, t["id"], author["id"], comment={"id": cid, "text": comment_plain(c, k2["body"]), "suggestion": s2},
                reaction={"emoji": "up" if approve else "down", "user": {"id": me(), "name": user_names(c, [me()]).get(me(), "")}},
                approval="approved" if approve else "rejected", applied=False, gate=gate_event(s2)))
    bump(c)
    c.commit()
    k2 = c.execute("SELECT suggestion FROM comments WHERE id=?", (cid,)).fetchone()
    return jsonify(state=st, suggestion=json.loads(k2["suggestion"]))
