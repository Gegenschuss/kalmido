"""Groups of people (admin): materialized list memberships, tasks assigned to a group."""
import re
from flask import g, has_request_context, jsonify, request

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, now_utc
from ..accounts.session import me
from ..core.access import Denied, my_max_sort, need_collab, need_list, ROLES, task_visible
from ..lists.lists import clean_folder, folder_under


# ---- 2.10.0 (#441): groups. An admin creates groups of people (Settings > Administration > Groups; optionally their
# members follow an OIDC group claim at every login: oidc_group set = synced, then read-only by hand). A list (owner /
# list admin) or a whole folder of own lists (its owner) is shared with a group with a role (same roles as people).
# Group access is MATERIALIZED into list_members: every member of a group gets a member row, so every read path that
# already respects sharing (state, search, CalDAV, API v1, MCP, News, webhooks, agents) needs no change. list_members
# keeps the personal role (own_role, NULL = only via groups) and the best role via groups (grole); role = the higher of
# both. grp_sync recomputes the rows of the affected lists after every change of groups, members, shares or folders.
# A task can also be assigned to a group (tasks.assignee_group_id, "whoever has time"): it shows in "Assigned to me" for
# every member until one of them takes it (POST /api/tasks/<id>/take -> assignee_id = them, the group is cleared).
GROUP_NAME_MAX = 60
GROUP_MAX = 200
ROLE_RANK = {"participant": 1, "view": 2, "edit": 3, "admin": 4}


def role_max(*roles):
    rs = [r for r in roles if r in ROLE_RANK]
    return max(rs, key=ROLE_RANK.get) if rs else None


def grp_members(c, gid):
    """Active persons of group gid (agents are never group members)."""
    return [r[0] for r in c.execute("""SELECT m.user_id FROM group_members m JOIN users u ON u.id=m.user_id
                                       WHERE m.group_id=? AND u.kind!='agent' ORDER BY m.user_id""", (gid,))]


def grp_of_user(c, uid):
    return [r[0] for r in c.execute("SELECT group_id FROM group_members WHERE user_id=? ORDER BY group_id", (uid,))]


def grp_shares_of_list(c, lid):
    """[(group_id, role, via)] of list lid: shared directly (via 'list') or through a folder of its owner (via the folder)."""
    lr = c.execute("SELECT owner_id, folder, is_inbox FROM lists WHERE id=?", (lid,)).fetchone()
    if not lr or lr["is_inbox"]:
        return []
    out = [(r["group_id"], r["role"], "list") for r in c.execute(
        "SELECT group_id, role FROM group_shares WHERE list_id=?", (lid,))]
    if lr["folder"]:
        for r in c.execute("SELECT group_id, role, folder FROM group_shares WHERE list_id IS NULL AND owner_id=?", (lr["owner_id"],)):
            if folder_under(lr["folder"], r["folder"]):
                out.append((r["group_id"], r["role"], r["folder"]))
    return out


def grp_list_ids(c, gid=None, owner=None):
    """Lists touched by the shares of group gid (or by the folder shares of owner): the ones grp_sync must look at."""
    ids = set()
    q, a = ("WHERE group_id=?", (gid,)) if gid is not None else ("WHERE owner_id=?", (owner,))
    for r in c.execute(f"SELECT list_id, owner_id, folder FROM group_shares {q}", a):
        if r["list_id"]:
            ids.add(r["list_id"])
        else:
            for x in c.execute("SELECT id, folder FROM lists WHERE owner_id=? AND folder!='' AND is_inbox=0", (r["owner_id"],)):
                if folder_under(x["folder"], r["folder"]):
                    ids.add(x["id"])
    if gid is not None or owner is not None:  # rows that came from groups before (a share was removed meanwhile)
        sql = ("SELECT DISTINCT m.list_id FROM list_members m JOIN group_members gm ON gm.user_id=m.user_id "
               "WHERE m.grole IS NOT NULL AND gm.group_id=?") if gid is not None else \
              "SELECT DISTINCT m.list_id FROM list_members m JOIN lists l ON l.id=m.list_id WHERE m.grole IS NOT NULL AND l.owner_id=?"
        ids.update(r[0] for r in c.execute(sql, (gid if gid is not None else owner,)))
    return ids


def grp_sync(c, lids, actor=None):
    """Recomputes the member rows of lists lids from personal shares + group shares (caller commits). New access, a
    changed role and lost access give the person a News item (share / role / unshare) and the list webhook list.shared /
    list.unshared; lost access also clears their assignments in that list (as removing a member does)."""
    from ..collab.news import news_add
    from ..integrations.webhooks import wh_note_list
    from ..agents.core import agent_ids
    actor = actor if actor is not None else (me() if has_request_context() and getattr(g, "user", None) else None)
    agents = agent_ids(c)
    kids = {r[0] for r in c.execute("SELECT id FROM users WHERE kid=1")}
    for lid in sorted({int(x) for x in lids if x}):
        lr = c.execute("SELECT id, owner_id, name, is_inbox FROM lists WHERE id=?", (lid,)).fetchone()
        if not lr:
            continue
        want, gname = {}, {}
        if not lr["is_inbox"]:
            for gid, role, _via in grp_shares_of_list(c, lid):
                for uid in grp_members(c, gid):
                    if uid == lr["owner_id"] or uid in agents:
                        continue
                    if role_max(want.get(uid), role) != want.get(uid):
                        want[uid], gname[uid] = role_max(want.get(uid), role), gid
        rows = {r["user_id"]: r for r in c.execute("SELECT * FROM list_members WHERE list_id=?", (lid,))}
        for uid in sorted(set(rows) | set(want)):
            r, gr = rows.get(uid), want.get(uid)
            own = None
            if r is not None:
                own = r["own_role"] if r["own_role"] is not None else (r["role"] if r["grole"] is None else None)
            eff = role_max(own, gr)
            if eff and uid in kids:  # 2.19.0 (#653)
                eff, gr = "participant", ("participant" if gr else gr)
            if r is None:
                c.execute("INSERT INTO list_members(list_id,user_id,role,own_role,grole,sort,added_at) VALUES(?,?,?,?,?,?,?)",
                          (lid, uid, eff, None, gr, my_max_sort(c, uid) + 1, iso(now_utc())))
                news_add(c, uid, "share", list_id=lid, actor=actor,
                         data={"role": eff, "name": lr["name"], "group": grp_name(c, gname.get(uid))})
                wh_note_list(lid, "list.shared", {"member_id": uid, "role": eff, "group_id": gname.get(uid)})
            elif eff is None:
                c.execute("DELETE FROM list_members WHERE list_id=? AND user_id=?", (lid, uid))
                c.execute("UPDATE tasks SET assignee_id=NULL WHERE list_id=? AND assignee_id=?", (lid, uid))
                c.execute("DELETE FROM task_field_values WHERE value=? AND field_id IN (SELECT id FROM list_fields WHERE list_id=? AND type='person')",
                          (str(uid), lid))
                news_add(c, uid, "unshare", list_id=lid, actor=actor, data={"name": lr["name"]})
            elif (r["role"], r["own_role"], r["grole"]) != (eff, own, gr):
                c.execute("UPDATE list_members SET role=?, own_role=?, grole=? WHERE list_id=? AND user_id=?", (eff, own, gr, lid, uid))
                if r["role"] != eff:
                    news_add(c, uid, "role", list_id=lid, actor=actor, data={"role": eff, "old": r["role"], "name": lr["name"]})
        # a group assignment stays only while that group still has access to the list
        gids = {x[0] for x in grp_shares_of_list(c, lid)}
        for t in c.execute("SELECT id, assignee_group_id FROM tasks WHERE list_id=? AND assignee_group_id IS NOT NULL", (lid,)).fetchall():
            if t["assignee_group_id"] not in gids:
                c.execute("UPDATE tasks SET assignee_group_id=NULL WHERE id=?", (t["id"],))


def grp_touch(c, owner):
    """The lists of owner moved between folders / were created: re-sync them if one of their folders is shared."""
    if c.execute("SELECT 1 FROM group_shares WHERE owner_id=? AND list_id IS NULL", (owner,)).fetchone():
        grp_sync(c, grp_list_ids(c, owner=owner) | {r[0] for r in c.execute("SELECT id FROM lists WHERE owner_id=?", (owner,))})


def grp_name(c, gid):
    if not gid:
        return ""
    r = c.execute("SELECT name FROM groups WHERE id=?", (gid,)).fetchone()
    return r[0] if r else ""


def grp_dict(c, r, full=True):
    from ..collab.comments import user_names
    mem = grp_members(c, r["id"])
    names = user_names(c, mem)
    d = {"id": r["id"], "name": r["name"], "oidc_group": r["oidc_group"] or "", "synced": bool(r["oidc_group"]),
         "members": [{"user_id": u, "name": names.get(u, "?")} for u in mem], "created_at": r["created_at"]}
    if full:
        d["shares"] = [{"list_id": s["list_id"], "folder": s["folder"], "owner_id": s["owner_id"], "role": s["role"]}
                       for s in c.execute("SELECT * FROM group_shares WHERE group_id=? ORDER BY id", (r["id"],))]
    return d


def groups_for(c, uid=None, full=False):
    """Every group with its members (names only; persons see all groups to share with them)."""
    return [grp_dict(c, r, full) for r in c.execute("SELECT * FROM groups ORDER BY name COLLATE NOCASE, id")]


def grp_clean_name(v):
    from ..personal.timetrack import BadInput
    if not isinstance(v, str) or not v.strip():
        raise BadInput(tr("Name missing"))
    return re.sub(r"\s+", " ", v).strip()[:GROUP_NAME_MAX]


def grp_set_members(c, gid, ids, actor=None):
    """Replaces the members of group gid with ids (active persons only); re-syncs the lists the group reaches."""
    from ..personal.timetrack import BadInput
    want = set()
    for x in ids or []:
        try:
            x = int(x)
        except (TypeError, ValueError):
            raise BadInput(tr("unknown user")) from None
        u = c.execute("SELECT kind FROM users WHERE id=?", (x,)).fetchone()
        if not u or u["kind"] == "agent":
            raise BadInput(tr("Only people can be group members"))
        want.add(x)
    before = grp_list_ids(c, gid)
    cur = set(grp_members(c, gid))
    for x in cur - want:
        c.execute("DELETE FROM group_members WHERE group_id=? AND user_id=?", (gid, x))
    for x in sorted(want - cur):
        c.execute("INSERT OR IGNORE INTO group_members(group_id,user_id,added_at) VALUES(?,?,?)", (gid, x, iso(now_utc())))
    if cur != want:
        grp_sync(c, before | grp_list_ids(c, gid), actor)


def grp_oidc_sync(c, uid, claim_groups):
    """At an OIDC login: the person is a member of exactly the synced groups whose oidc_group is among their claims."""
    for r in c.execute("SELECT id, oidc_group FROM groups WHERE oidc_group!=''").fetchall():
        has = bool(c.execute("SELECT 1 FROM group_members WHERE group_id=? AND user_id=?", (r["id"], uid)).fetchone())
        want = r["oidc_group"] in claim_groups
        if has != want:
            mem = set(grp_members(c, r["id"]))
            grp_set_members(c, r["id"], sorted(mem | {uid} if want else mem - {uid}), actor=uid)


def need_group(c, gid):
    r = c.execute("SELECT * FROM groups WHERE id=?", (gid,)).fetchone()
    if not r:
        raise Denied(404, tr("unknown group"))
    return r


@app.get("/api/groups")
def groups_get():
    c = db()
    return jsonify(groups=groups_for(c, full=bool(g.user["is_admin"])), mine=grp_of_user(c, me()))


@app.post("/api/admin/groups")
def group_create():
    """{name, members?: [user ids], oidc_group?} -- admins only."""
    from ..accounts.users import need_admin
    need_admin()
    need_collab()
    b = body()
    c = db()
    name = grp_clean_name(b.get("name"))
    if c.execute("SELECT COUNT(*) FROM groups").fetchone()[0] >= GROUP_MAX:
        return err(tr("At most {0} groups", GROUP_MAX), 409)
    if c.execute("SELECT 1 FROM groups WHERE name=? COLLATE NOCASE", (name,)).fetchone():
        return err(tr("A group with this name exists already"), 409)
    og = str(b.get("oidc_group") or "").strip()[:200]
    gid = c.execute("INSERT INTO groups(name,oidc_group,created_at,created_by) VALUES(?,?,?,?)",
                    (name, og, iso(now_utc()), me())).lastrowid
    if b.get("members") and not og:
        grp_set_members(c, gid, b["members"])
    bump(c)
    c.commit()
    return jsonify(grp_dict(c, need_group(c, gid)))


@app.patch("/api/admin/groups/<int:gid>")
def group_update(gid):
    """{name?, members?, oidc_group?} -- members cannot be changed by hand while the group follows an OIDC group."""
    from ..accounts.users import need_admin
    need_admin()
    b = body()
    c = db()
    r = need_group(c, gid)
    if "name" in b:
        name = grp_clean_name(b["name"])
        if c.execute("SELECT 1 FROM groups WHERE name=? COLLATE NOCASE AND id!=?", (name, gid)).fetchone():
            return err(tr("A group with this name exists already"), 409)
        c.execute("UPDATE groups SET name=? WHERE id=?", (name, gid))
    og = r["oidc_group"]
    if "oidc_group" in b:
        og = str(b.get("oidc_group") or "").strip()[:200]
        c.execute("UPDATE groups SET oidc_group=? WHERE id=?", (og, gid))
    if "members" in b:
        if og:
            return err(tr("The members of this group come from the sign-in provider"), 409)
        if not isinstance(b["members"], list):
            return err(tr("Invalid value: {0}", "members"))
        grp_set_members(c, gid, b["members"])
    bump(c)
    c.commit()
    return jsonify(grp_dict(c, need_group(c, gid)))


@app.delete("/api/admin/groups/<int:gid>")
def group_delete(gid):
    from ..accounts.users import need_admin
    need_admin()
    c = db()
    need_group(c, gid)
    lids = grp_list_ids(c, gid)
    c.execute("UPDATE tasks SET assignee_group_id=NULL WHERE assignee_group_id=?", (gid,))
    c.execute("DELETE FROM group_shares WHERE group_id=?", (gid,))
    c.execute("DELETE FROM group_members WHERE group_id=?", (gid,))
    c.execute("DELETE FROM groups WHERE id=?", (gid,))
    grp_sync(c, lids)
    bump(c)
    c.commit()
    return jsonify(ok=True)


def grp_role(b):
    from ..personal.timetrack import BadInput
    role = b.get("role", "edit")
    if role not in ROLES:
        raise BadInput(tr("Role must be admin, edit, participant or view"))
    return role


@app.get("/api/lists/<int:lid>/groups")
def list_groups_get(lid):
    c = db()
    need_list(c, lid, write=False)
    return jsonify(groups=[{"group_id": gid, "name": grp_name(c, gid), "role": role, "via": via}
                           for gid, role, via in grp_shares_of_list(c, lid)])


@app.put("/api/lists/<int:lid>/groups/<int:gid>")
def list_group_set(lid, gid):
    """{role} -- the owner or a list admin shares the list with group gid (or changes its role)."""
    need_collab()
    c = db()
    need_list(c, lid, write=False, manage=True)
    need_group(c, gid)
    if c.execute("SELECT is_inbox FROM lists WHERE id=?", (lid,)).fetchone()[0]:
        return err(tr("The inbox cannot be shared"))
    role = grp_role(body())
    if c.execute("SELECT 1 FROM group_shares WHERE list_id=? AND group_id=?", (lid, gid)).fetchone():
        c.execute("UPDATE group_shares SET role=? WHERE list_id=? AND group_id=?", (role, lid, gid))
    else:
        c.execute("INSERT INTO group_shares(group_id,list_id,role,added_by,added_at) VALUES(?,?,?,?,?)",
                  (gid, lid, role, me(), iso(now_utc())))
    grp_sync(c, [lid])
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.delete("/api/lists/<int:lid>/groups/<int:gid>")
def list_group_del(lid, gid):
    need_collab()
    c = db()
    need_list(c, lid, write=False, manage=True)
    if not c.execute("DELETE FROM group_shares WHERE list_id=? AND group_id=?", (lid, gid)).rowcount:
        return err(tr("unknown"), 404)
    grp_sync(c, [lid])
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.get("/api/folders/groups")
def folder_groups_get():
    """?folder=<path>: the groups my folder (and its subfolders) is shared with."""
    c = db()
    f = clean_folder(str(request.args.get("folder") or ""), False)
    return jsonify(groups=[{"group_id": r["group_id"], "name": grp_name(c, r["group_id"]), "role": r["role"]}
                           for r in c.execute("SELECT group_id, role FROM group_shares WHERE owner_id=? AND list_id IS NULL AND folder=?",
                                              (me(), f))])


@app.put("/api/folders/groups/<int:gid>")
def folder_group_set(gid):
    """{folder, role}: share every own list in that folder (and its subfolders, also lists moved there later) with gid."""
    need_collab()
    b = body()
    c = db()
    need_group(c, gid)
    f = clean_folder(str(b.get("folder") or ""), False)
    if not f:
        return err(tr("Name missing"))
    role = grp_role(b)
    if c.execute("SELECT 1 FROM group_shares WHERE owner_id=? AND folder=? AND group_id=? AND list_id IS NULL", (me(), f, gid)).fetchone():
        c.execute("UPDATE group_shares SET role=? WHERE owner_id=? AND folder=? AND group_id=? AND list_id IS NULL", (role, me(), f, gid))
    else:
        c.execute("INSERT INTO group_shares(group_id,owner_id,folder,role,added_by,added_at) VALUES(?,?,?,?,?,?)",
                  (gid, me(), f, role, me(), iso(now_utc())))
    grp_sync(c, grp_list_ids(c, owner=me()))
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.delete("/api/folders/groups/<int:gid>")
def folder_group_del(gid):
    need_collab()
    c = db()
    f = clean_folder(str(request.args.get("folder") or ""), False)
    before = grp_list_ids(c, owner=me())
    if not c.execute("DELETE FROM group_shares WHERE owner_id=? AND folder=? AND group_id=? AND list_id IS NULL", (me(), f, gid)).rowcount:
        return err(tr("unknown"), 404)
    grp_sync(c, before)
    bump(c)
    c.commit()
    return jsonify(ok=True)


def check_group_assignee(c, lid, gid):
    """None if group gid may be assigned in list lid (the list is shared with it), else an error message."""
    if gid is None:
        return None
    need_collab()
    return None if gid in {x[0] for x in grp_shares_of_list(c, lid)} else tr("Share the list with this group first")


def grp_assign_events(c, tid, gid):
    """News (+ the usual assignment push gate) for every member of the group the task was just assigned to."""
    from ..collab.news import news_add
    actor = me() if has_request_context() and getattr(g, "user", None) else None
    t = c.execute("SELECT title, list_id FROM tasks WHERE id=?", (tid,)).fetchone()
    if not t:
        return
    gname = grp_name(c, gid)
    for uid in grp_members(c, gid):
        if uid != actor and task_visible(c, tid, uid, full=True):
            news_add(c, uid, "assign", task_id=tid, actor=actor, data={"group": gname, "group_id": gid})


def task_take(c, tid, uid):
    """uid takes a task assigned to one of their groups: assignee = uid, the group is cleared. Error text or None."""
    from ..tasks.validation import log_act
    from ..collab.news import news_add
    from ..agents.core import agent_assign_event
    t = c.execute("SELECT * FROM tasks WHERE id=? AND deleted_at IS NULL", (tid,)).fetchone()
    if not t or not task_visible(c, tid, uid):
        raise Denied(404)
    if not t["assignee_group_id"] or t["assignee_group_id"] not in grp_of_user(c, uid):
        return tr("This task is not assigned to one of your groups")
    c.execute("UPDATE tasks SET assignee_id=?, assignee_group_id=NULL, assigned_by=?, reminded='[]', updated_at=? WHERE id=?",
              (uid, uid, iso(now_utc()), tid))
    log_act(c, tid, "take", {"group": grp_name(c, t["assignee_group_id"])})
    for m in grp_members(c, t["assignee_group_id"]):
        if m != uid and task_visible(c, tid, m, full=True):
            news_add(c, m, "take", task_id=tid, data={"group": grp_name(c, t["assignee_group_id"])})
    agent_assign_event(c, tid, "assigned", uid)
    return None


@app.post("/api/tasks/<int:tid>/take")
def task_take_web(tid):
    """"Take it": a task assigned to my group becomes mine (also for participants of the list)."""
    from ..tasks.tasks import one_task
    c = db()
    e = task_take(c, tid, me())
    if e:
        return err(e, 409)
    bump(c)
    c.commit()
    return jsonify(one_task(c, tid))
