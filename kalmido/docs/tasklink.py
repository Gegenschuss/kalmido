"""2.154.0 A (#1111): a document linked with an EXISTING task (besides "Create task" of docs/web.py docs_task), and the
documents of a task ("Document: <title>" in the task, a tap opens it).

One task per document (doc_meta.task_id, as before). Linking needs 'edit' on the document and sight of the task; the
workspace boundary stays: a private document only with a task of a private list, an organisation's document with a task
of that organisation or of a private list (like "Create task", which files into the person's inbox). The task side shows
only the documents the person may see -- nothing about the others, not even that there are some. Agents never link
(no agent route; API v1 does not show the link)."""
from flask import g, jsonify

from ..core.config import app
from ..core.db import body, bump, db, err, iso, now_utc
from ..core.i18n import tr
from ..core.access import Denied, task_visible
from ..accounts.session import me
from ..files.store import fs_visible_sql


def _no_agent():
    from ..agents.core import is_agent
    if is_agent(g.user):
        raise Denied(403)


def dtl_task_row(c, tid):
    return c.execute("SELECT t.id, t.title, t.status, t.deleted_at, l.org_id FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.id=?",
                     (tid,)).fetchone() if tid else None


def dtl_task_view(c, tid, uid):
    """{id, title, done} of the linked task when uid sees it (not deleted), else None."""
    t = dtl_task_row(c, tid)
    if not t or t["deleted_at"] or not task_visible(c, tid, uid):
        return None
    return {"id": t["id"], "title": t["title"], "done": t["status"] != 0}


def dtl_link_ok(t, doc_org):
    """The workspace boundary of a link: private stays private, an organisation's document only with its own or private tasks."""
    return t["org_id"] is None or (doc_org is not None and t["org_id"] == doc_org)


@app.post("/api/docs/<int:nid>/task/link")
def docs_task_link(nid):
    """{task_id} -- link the document with an existing task (replaces a link it had). -> {task, prev_task_id}."""
    _no_agent()
    c = db()
    uid = me()
    from .web import _doc
    m, n = _doc(c, nid, write=True)
    tid = body().get("task_id")
    if not isinstance(tid, int) or isinstance(tid, bool):
        return err(tr("Invalid value: {0}", "task_id"))
    t = dtl_task_row(c, tid)
    if not t or t["deleted_at"] or not task_visible(c, tid, uid):
        return err(tr("Task not found"), 404)
    if not dtl_link_ok(t, n["org_id"]):
        return err(tr("Choose a task of this workspace"))
    prev = m["task_id"]
    c.execute("UPDATE doc_meta SET task_id=?, updated_at=? WHERE node_id=?", (tid, iso(now_utc()), nid))
    bump(c)
    c.commit()
    return jsonify(task=dtl_task_view(c, tid, uid), prev_task_id=prev)


@app.get("/api/tasks/<int:tid>/docs")
def task_docs(tid):
    """The documents linked with task tid that I may see: {docs: [{id, name}]}; 404 when I do not see the task (2.161.0,
    p2362_a route scan)."""
    _no_agent()
    c = db()
    uid = me()
    if not task_visible(c, tid, uid):
        return err(tr("Task not found"), 404)
    rows = c.execute(f"SELECT d.node_id, n.name FROM doc_meta d JOIN fs_nodes n ON n.id=d.node_id WHERE d.task_id=? AND n.deleted_at IS NULL "
                     f"AND d.node_id IN {fs_visible_sql(uid, c)} ORDER BY d.node_id LIMIT 20", (tid,)).fetchall()
    return jsonify(docs=[{"id": r["node_id"], "name": r["name"]} for r in rows])


def dtl_doc_extra(c, d, m, uid):
    """docs_get: the linked task as {id, title, done} (only when I see it)."""
    if m["task_id"]:
        d["task"] = dtl_task_view(c, m["task_id"], uid)

