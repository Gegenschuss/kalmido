"""2.550.0 (#4528): what removing a member ends, remembered so that adding the person again brings it back.

Removing a member of a project (by the owner / a project admin) or leaving it (lists/lists.py member_remove) ends their
assignments there, their values in the project's person fields, the tasks delegated to them (an agent) and their watching.
mm_write keeps that as one member_memos row per project and person (detail = JSON of task ids), before the rows change;
mm_counts is the question's number (?dry=1, also delegations and watching). Adding the same person again (member_set) names
the memo in its answer (restore_offer) and GET /api/lists/<id>/member-memos lists them, both for the project's owner and
admins only; POST /api/lists/<id>/members/<uid>/restore puts back what is still free, within the trash period: the task
still exists in the project, no other assignee (person or group), no value in the person field (the field still exists),
no other delegation (and check_delegate allows it for the person restoring), watching only of tasks the person sees.
Nothing that was set meanwhile is overwritten. The memo goes after the restore; the trash run (files/trashpurge.py TP_PLAIN)
deletes it after the trash period. Agents never restore (a person's step in the app)."""
import json

from flask import g, jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.db import bump, db, iso, now_utc
from ..core.pg import insert_id, st_ids
from ..core.access import Denied, list_role, need_collab, need_list, task_visible
from ..core.retention import ret_trash_cut, ret_trash_days
from ..accounts.session import me
from ..tasks.watchers import check_delegate, dlg_events

MM_KEYS = ("assigned", "values", "delegate", "watch")


def mm_snap(c, lid, uid):
    """The task ids of what removing uid from list lid ends: {assigned, values: [[task, field]], delegate, watch}."""
    return {
        "assigned": [r[0] for r in c.execute("SELECT id FROM tasks WHERE list_id=? AND assignee_id=? ORDER BY id", (lid, uid))],
        "values": [[r[0], r[1]] for r in c.execute(
            "SELECT v.task_id, v.field_id FROM task_field_values v JOIN list_fields f ON f.id=v.field_id WHERE f.list_id=? "
            "AND f.type='person' AND v.value=? ORDER BY v.task_id, v.field_id", (lid, str(uid)))],
        "delegate": [r[0] for r in c.execute("SELECT id FROM tasks WHERE list_id=? AND delegate_agent_id=? ORDER BY id", (lid, uid))],
        "watch": [r[0] for r in c.execute("SELECT w.task_id FROM task_watchers w JOIN tasks t ON t.id=w.task_id WHERE t.list_id=? "
                                          "AND w.user_id=? ORDER BY w.task_id", (lid, uid))],
    }


def mm_counts(c, lid, uid):
    """The question's numbers (nothing changes): {assigned, values, delegate, watch}; tasks in the trash count too."""
    return {k: len(v) for k, v in mm_snap(c, lid, uid).items()}


def mm_write(c, lid, uid, by):
    """Before uid's rows in list lid change: keep them (merged with a memo of an earlier removal still in its period).
    Nothing to keep -> no row. The caller commits."""
    d = mm_snap(c, lid, uid)
    old = c.execute("SELECT id, data FROM member_memos WHERE list_id=? AND user_id=? AND deleted_at>=? ORDER BY id DESC LIMIT 1",
                    (lid, uid, ret_trash_cut())).fetchone()
    if old:
        o = json.loads(old["data"] or "{}")
        for k in MM_KEYS:
            have = {json.dumps(x) for x in d[k]}
            d[k] += [x for x in o.get(k) or [] if json.dumps(x) not in have]
    c.execute("DELETE FROM member_memos WHERE list_id=? AND user_id=?", (lid, uid))
    if not any(d[k] for k in MM_KEYS):
        return None
    return insert_id(c, "INSERT INTO member_memos(list_id,user_id,by_id,data,deleted_at) VALUES(?,?,?,?,?)",
                     (lid, uid, by, json.dumps(d, separators=(",", ":")), iso(now_utc())))


def mm_row(c, lid, uid):
    return c.execute("SELECT * FROM member_memos WHERE list_id=? AND user_id=? AND deleted_at>=? ORDER BY id DESC LIMIT 1",
                     (lid, uid, ret_trash_cut())).fetchone()


def mm_offer(c, lid, uid):
    """The memo of uid in list lid as numbers ({assigned, values, delegate, watch, at}), None without one in its period."""
    r = mm_row(c, lid, uid)
    if not r:
        return None
    d = json.loads(r["data"] or "{}")
    return {**{k: len(d.get(k) or []) for k in MM_KEYS}, "at": r["deleted_at"]}


def mm_person():
    """The way back is a person's step (the owner / a project admin); an agent gets 403."""
    u = getattr(g, "user", None)
    if u is not None and (u["kind"] if "kind" in u.keys() else "user") == "agent":
        raise Denied(403, tr("Not available for agent accounts"))


def mm_need(c, lid):
    mm_person()
    need_collab()
    need_list(c, lid, write=False, manage=True)


@app.get("/api/lists/<int:lid>/member-memos")
def member_memos_list(lid):
    """The memos of the people removed from list lid within the trash period (owner and project admins): {memos: [{user_id,
    name, member, assigned, values, delegate, watch, at}], days}. member = the person is in the project again."""
    c = db()
    mm_need(c, lid)
    out = []
    for r in c.execute("""SELECT m.user_id, m.data, m.deleted_at, u.display_name FROM member_memos m JOIN users u ON u.id=m.user_id
                          WHERE m.list_id=? AND m.deleted_at>=? ORDER BY m.deleted_at DESC, m.id DESC LIMIT 200""",
                       (lid, ret_trash_cut())).fetchall():
        d = json.loads(r["data"] or "{}")
        out.append({"user_id": r["user_id"], "name": r["display_name"] or "", "member": bool(list_role(c, lid, r["user_id"])),
                    "at": r["deleted_at"], **{k: len(d.get(k) or []) for k in MM_KEYS}})
    return jsonify(memos=out, days=ret_trash_days())


@app.post("/api/lists/<int:lid>/members/<int:uid>/restore")
def member_memo_restore(lid, uid):
    """Puts back what removing uid ended (see the module): only while uid is in the project again; answer {restored: {assigned,
    values, delegate, watch}, skipped}: skipped = what stays as it is (taken meanwhile, task gone or moved, field gone)."""
    c = db()
    mm_need(c, lid)
    r = mm_row(c, lid, uid)
    if not r:
        raise Denied(404)
    role = list_role(c, lid, uid)
    if not role:
        raise Denied(409, tr("Add the person to the project first"))
    d = json.loads(r["data"] or "{}")
    ids = sorted({int(x) for k in ("assigned", "delegate", "watch") for x in d.get(k) or []} | {int(x[0]) for x in d.get("values") or []})
    tasks = {t["id"]: t for t in c.execute("SELECT id, assignee_id, assignee_group_id, delegate_agent_id FROM tasks WHERE list_id=? "
                                           "AND id = ANY(CAST(? AS BIGINT[]))", (lid, st_ids(ids)))} if ids else {}
    done = {k: 0 for k in MM_KEYS}
    for x in d.get("assigned") or []:
        t = tasks.get(x)
        if t and not t["assignee_id"] and not t["assignee_group_id"]:
            c.execute("UPDATE tasks SET assignee_id=?, assigned_by=? WHERE id=? AND assignee_id IS NULL AND assignee_group_id IS NULL",
                      (uid, me(), x))
            done["assigned"] += 1
    pf = {f[0] for f in c.execute("SELECT id FROM list_fields WHERE list_id=? AND type='person'", (lid,))}
    for x, fid in d.get("values") or []:
        if x in tasks and fid in pf:
            done["values"] += c.execute("INSERT INTO task_field_values(task_id,field_id,value) VALUES(?,?,?) ON CONFLICT DO NOTHING",
                                        (x, fid, str(uid))).rowcount
    dl_ok = None
    for x in d.get("delegate") or []:
        t = tasks.get(x)
        if not t or t["delegate_agent_id"]:
            continue
        if dl_ok is None:
            try:
                dl_ok = check_delegate(c, lid, uid) is None
            except Denied:  # collaboration off for the person restoring
                dl_ok = False
        if dl_ok:
            c.execute("UPDATE tasks SET delegate_agent_id=? WHERE id=? AND delegate_agent_id IS NULL", (uid, x))
            dlg_events(c, x, None, uid)  # the agent hears of it again, as on a delegation
            done["delegate"] += 1
    for x in d.get("watch") or []:
        if x in tasks and task_visible(c, x, uid):
            done["watch"] += c.execute("INSERT INTO task_watchers(task_id,user_id,created_at) VALUES(?,?,?) ON CONFLICT DO NOTHING",
                                       (x, uid, iso(now_utc()))).rowcount
    total = sum(len(d.get(k) or []) for k in MM_KEYS)
    c.execute("DELETE FROM member_memos WHERE list_id=? AND user_id=?", (lid, uid))
    bump(c)
    c.commit()
    return jsonify(ok=True, restored=done, skipped=total - sum(done.values()))
