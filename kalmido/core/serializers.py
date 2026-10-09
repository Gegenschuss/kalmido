"""JSON shapes of database rows (tasks, lists, users ...) as the web client and the API see them."""
import os
from flask import g, has_request_context

from ..core.config import ATT_DIR
from ..core.i18n import tr
from ..accounts.session import me
from ..core.access import plists, PROJ_SQL, pvis


# ---------------------------------------------------------------- serializers

def task_dict(r, tags, full_snips=False):
    from ..family.family import fam_task_out
    d = dict(r)
    d.pop("reminded", None)
    d.pop("nag_at", None)
    # 2.18.0 (#430): ms only on milestones, milestone_id only when set (keeps every other task's dict as it was)
    if not d.get("ms"):
        d.pop("ms", None)
    if d.get("milestone_id") is None:
        d.pop("milestone_id", None)
    if not d.get("approval"):  # 2.23.0 (#463): only on tasks that wait for / had an approval
        d.pop("approval", None)
        d.pop("approver_id", None)
    fam_task_out(d)  # 2.19.0 (#653): fam / rotation as objects, only when set
    if "snippets" in d:  # 2.35.0 (#1095): lists / state only the number (snippets_n, when > 0); the snippets themselves
        from ..tasks.snippets import snip_out  # with full_snips (one task: GET /api/tasks/<id>, the answer of a change, API)
        sn = snip_out(d.pop("snippets"))
        if full_snips:
            d["snippets"] = sn
        if sn or full_snips:
            d["snippets_n"] = len(sn)
    d["tags"] = tags.get(r["id"], [])
    return d


def tags_for(c, ids=None, uid=None):
    out = {}
    uid = uid or me()
    for r in c.execute("SELECT task_id, tag FROM task_tags WHERE user_id=? ORDER BY tag", (uid,)):
        if ids is None or r["task_id"] in ids:
            out.setdefault(r["task_id"], []).append(r["tag"])
    return out


def load_tasks(c, where, args=(), full_snips=False):
    from ..personal.timetrack import vis_ids
    from ..collab.reactions import ltags_for
    from ..integrations.git import git_code_for
    from ..family.family import people_of
    rows = c.execute(f"SELECT * FROM tasks WHERE {where}", args).fetchall()
    # 1.10.0 safety net: a participant never gets a task of that list they must not see, whatever the caller's query;
    # context tasks (parents of an assigned subtask) come without notes, link, files, fields and comments
    ctx, pl, pv = set(), set(), set()
    viewer = g.user["id"] if has_request_context() and getattr(g, "user", None) else None
    if viewer and rows:
        pl = set(plists(c, viewer))
        if pl:
            pv, _, ctx = pvis(c, viewer)
            rows = [r for r in rows if r["list_id"] not in pl or r["id"] in pv]
    ids = {r["id"] for r in rows}
    tags = tags_for(c, ids)
    ltags = ltags_for(c, ids) if ids else {}
    atts = {}  # the task's own files; files of comments are shown inside their comment (timeline)
    # 2.30.0 (#380): agent = the name of the agent that stored the file ("Created by agent" in the app), else absent
    for a in c.execute("""SELECT a.id, a.task_id, a.name, a.mime, a.size, a.created_at, u.kind, u.display_name, u.username
                          FROM attachments a LEFT JOIN users u ON u.id=a.user_id WHERE a.comment_id IS NULL ORDER BY a.id"""):
        if a["task_id"] in ids:
            d = {k: a[k] for k in ("id", "name", "mime", "size", "created_at")}
            if a["kind"] == "agent":
                d["agent"] = a["display_name"] or a["username"]
            atts.setdefault(a["task_id"], []).append(d)
    # comment count + unread (comments of others newer than the last one I have seen)
    cms, uid = {}, (g.user["id"] if has_request_context() and getattr(g, "user", None) else None)
    if uid and ids:
        for r in c.execute("""SELECT k.task_id, COUNT(*) AS n,
                                     SUM(CASE WHEN k.id > COALESCE(s.seen_id, 0) AND k.user_id IS NOT ? THEN 1 ELSE 0 END) AS u
                              FROM comments k LEFT JOIN task_seen s ON s.task_id=k.task_id AND s.user_id=?
                              WHERE k.deleted_at IS NULL GROUP BY k.task_id""", (uid, uid)):
            if r["task_id"] in ids:
                cms[r["task_id"]] = (r["n"], r["u"] or 0)
    # custom field values (fields of the task's current list) and dependencies: blocked = open blockers
    # (also ones I cannot see), blockers = the open ones I can see, blocking = open tasks waiting on it
    fvs, blk, bing = {}, {}, {}
    if ids:
        for r in c.execute("""SELECT v.task_id, v.field_id, v.value FROM task_field_values v JOIN list_fields f ON f.id=v.field_id
                              JOIN tasks t ON t.id=v.task_id WHERE f.list_id=t.list_id"""):
            if r["task_id"] in ids:
                fvs.setdefault(r["task_id"], {})[str(r["field_id"])] = r["value"]
        for r in c.execute(f"""SELECT d.task_id, d.blocker_id, b.list_id FROM task_deps d JOIN tasks b ON b.id=d.blocker_id
                              JOIN tasks w ON w.id=d.task_id
                              WHERE b.status=0 AND b.deleted_at IS NULL AND b.list_id IN {PROJ_SQL} AND w.list_id IN {PROJ_SQL}"""):
            if r["task_id"] in ids:
                blk.setdefault(r["task_id"], []).append((r["blocker_id"], r["list_id"]))
        for r in c.execute(f"""SELECT d.blocker_id, COUNT(*) AS n FROM task_deps d JOIN tasks t ON t.id=d.task_id
                              JOIN tasks b ON b.id=d.blocker_id
                              WHERE t.status=0 AND t.deleted_at IS NULL AND t.list_id IN {PROJ_SQL} AND b.list_id IN {PROJ_SQL}
                              GROUP BY d.blocker_id"""):
            if r["blocker_id"] in ids:
                bing[r["blocker_id"]] = r["n"]
    vis = vis_ids(c, uid) if blk and uid else set()
    aiu = {}  # 2.1.1 (#326): model usage agents reported for the task ("AI usage" in the task panel)
    if ids and uid and c.execute("SELECT 1 FROM agent_usage WHERE task_id IS NOT NULL LIMIT 1").fetchone():
        for r in c.execute("""SELECT task_id, COUNT(*) AS n, SUM(input_tokens+output_tokens+cache_write_tokens) AS tok,
                                     SUM(cost_usd) AS cost FROM agent_usage WHERE task_id IS NOT NULL GROUP BY task_id"""):
            if r["task_id"] in ids:
                aiu[r["task_id"]] = {"tokens": r["tok"] or 0, "cost": round(r["cost"], 4) if r["cost"] is not None else None,
                                     "calls": r["n"]}
    gcode = git_code_for(c, ids) if ids else {}  # 2.2.0 (#271): linked pull requests + commits
    ppl = people_of(c, ids)  # 2.19.0 (#653): who comes along
    out = []
    for r in rows:
        d = task_dict(r, tags, full_snips)
        d["ltags"] = ltags.get(r["id"], [])
        if r["id"] in gcode and r["id"] not in ctx:
            d["code"] = gcode[r["id"]]
        d["attachments"] = atts.get(r["id"], [])
        d["comment_count"], d["unread"] = cms.get(r["id"], (0, 0))
        d["fields"] = fvs.get(r["id"], {})
        d["blocked"] = len(blk.get(r["id"], []))
        d["blockers"] = [b for b, lid in blk.get(r["id"], []) if lid in vis and (lid not in pl or b in pv)]
        d["blocking"] = bing.get(r["id"], 0)
        if r["id"] in ppl:
            d["people"] = ppl[r["id"]]
        if r["id"] in aiu and r["id"] not in ctx:
            d["ai_usage"] = aiu[r["id"]]
        if r["id"] in ctx:
            d.update(content="", url=None, attachments=[], comment_count=0, unread=0, fields={},
                     blockers=[], blocked=0, blocking=0, context=True)
            d.pop("snippets", None)  # 2.35.0 (#1095)
            d.pop("snippets_n", None)
        out.append(d)
    return out


def attachment_files(c, task_ids):
    """Paths of all attachments of these tasks (and their subtasks), to unlink after a hard delete."""
    from ..tasks.validation import descendants
    ids = set(task_ids)
    for t in list(ids):
        ids.update(descendants(c, t))
    if not ids:
        return []
    q = ",".join("?" * len(ids))
    return [r[0] for r in c.execute(f"SELECT path FROM attachments WHERE task_id IN ({q})", list(ids))]


def unlink_files(paths):
    for p in paths:
        try:
            full = os.path.join(ATT_DIR, p)
            os.remove(full)
            d = os.path.dirname(full)
            if d != ATT_DIR and not os.listdir(d):
                os.rmdir(d)
        except OSError:
            pass


def running_pomo(c, uid=None):
    r = c.execute("SELECT * FROM pomos WHERE end IS NULL AND user_id=? ORDER BY id DESC LIMIT 1", (uid or me(),)).fetchone()
    return dict(r) if r else None
