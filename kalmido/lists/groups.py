"""Groups of people (admin): materialized list memberships, tasks assigned to a group."""
import re
from flask import g, has_request_context, jsonify, request

from ..core.config import app, PUBLIC_URL
from ..core.pg import insert_id, st_ids, system_ctx
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, now_utc
from ..accounts.session import me
from ..core.access import Denied, dlg_gone, live_sql, my_max_sort, need_collab, need_list, qn_private, ROLES, task_visible
from ..lists.lists import clean_folder
from ..core.errors import BadInput  # 2.149.0 G (#2517): pulled up from functions
from ..accounts.orgroles import org_role_key  # 2.568.0 (#4739)
from ..lists.lists import _in_folder, member_folder_adopt  # 2.369.5 (#2517): pulled up from functions


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


# 2.958.0 (#5245, stage 7d of the shared core): group_shares is gone. A project's own share with a group is a row of the core on
# the project's node (fs_shares.group_id, list_own = 1, list_role = the project role; written by list_group_set through
# core/objects.py obj_share); a folder's share with a group is a share of the folder's nodes (list_own 0, lffolder.lf_folder_share),
# which reaches the projects below at runtime through the folders (lffolder.lf_want -> list_members.frole, like a person's).
GS_OWN = """SELECT n.ref_id AS list_id, s.group_id, s.role, s.list_role, s.id, s.node_id FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id
            WHERE n.kind='ref' AND n.ref_kind='list' AND s.group_id IS NOT NULL AND s.list_own=1"""


def _grole(s):
    return s["list_role"] if s["list_role"] in ROLE_RANK else ("edit" if s["role"] == "edit" else "view")


def grp_own_rows(c, lids=None, gid=None):
    """2.958.0 (#5245): [{list_id, group_id, role, share_id}] of the projects' own shares with groups (lids / group gid)."""
    q, a = GS_OWN, []
    if lids is not None:
        q += " AND n.ref_id = ANY(CAST(? AS BIGINT[]))"
        a.append(st_ids(sorted({int(x) for x in lids})))
    if gid is not None:
        q += " AND s.group_id=?"
        a.append(int(gid))
    with system_ctx(c):  # the node lies in the owner's tree, also when a list admin / another member asks
        return [{"list_id": r["list_id"], "group_id": r["group_id"], "role": _grole(r), "share_id": r["id"]}
                for r in c.execute(q + " ORDER BY s.id", a).fetchall()]


def grp_folder_rows(c, owner=None, gid=None, nids=None):
    """2.958.0 (#5245): [{owner_id, folder, group_id, role, node_id, share_id}] of the live group shares of projects folders
    (a folder not in the trash, not expired; its owner and path: lffolder.lf_node_folder)."""
    from .lffolder import lf_node_folder
    from ..files.store import _now
    q, a = ["n.kind='folder'", live_sql("n"), "s.group_id IS NOT NULL", "COALESCE(s.list_own, 0)=0",
            "(s.expires_at IS NULL OR s.expires_at > ?)"], [_now()]
    if owner is not None:
        q.append("n.owner_id=?")
        a.append(int(owner))
    if gid is not None:
        q.append("s.group_id=?")
        a.append(int(gid))
    if nids is not None:
        q.append("s.node_id = ANY(CAST(? AS BIGINT[]))")
        a.append(st_ids(sorted({int(x) for x in nids})))
    out, where = [], {}
    with system_ctx(c):
        for s in c.execute(f"""SELECT s.id, s.node_id, s.group_id, s.role, s.list_role FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id
                               WHERE {' AND '.join(q)} ORDER BY s.id""", a).fetchall():
            if s["node_id"] not in where:
                where[s["node_id"]] = lf_node_folder(c, s["node_id"])
            k = where[s["node_id"]]
            if k and k[1]:
                out.append({"owner_id": k[0], "folder": k[1], "group_id": s["group_id"], "role": _grole(s), "node_id": s["node_id"],
                            "share_id": s["id"]})
    return out


def grp_shares_of_list(c, lid):
    """[(group_id, role, via)] of list lid: shared directly (via 'list') or through a folder above it (via the folder's path).
    2.958.0 (#5245): read from the shares of its node and of the folders of its chain (group_shares is gone)."""
    from .lffolder import LF_KIND
    from ..files.fsref import fs_ref_node
    from ..files.store import fs_chain
    lr = c.execute("SELECT owner_id, folder, is_inbox FROM lists WHERE id=?", (lid,)).fetchone()
    if not lr or lr["is_inbox"]:
        return []
    out = [(r["group_id"], r["role"], "list") for r in grp_own_rows(c, [lid])]
    with system_ctx(c):
        n = fs_ref_node(c, LF_KIND, lid)
        chain = fs_chain(c, n["id"]) if n is not None and not n["deleted_at"] else []
    fids = [x["id"] for x in chain[1:] if x["kind"] == "folder"]
    if fids:
        for r in grp_folder_rows(c, nids=fids):
            out.append((r["group_id"], r["role"], r["folder"]))
    return out


def grp_shares_of_lists(c, rows):
    """2.280.0 B (#3116): grp_shares_of_list for many lists (rows with id, owner_id, folder, is_inbox) and the groups' names ->
    ({list id: [(group_id, role, via)]}, {group id: name}). 2.958.0 (#5245): the own shares of all lists in one query, the
    folders' group shares once with the lists below them (lffolder.lf_lists_below)."""
    from .lffolder import lf_lists_below
    rows = [r for r in rows if not r["is_inbox"]]
    out, names = {}, {}
    if not rows:
        return out, names
    ids = {r["id"] for r in rows}
    for r in grp_own_rows(c, ids):
        out.setdefault(r["list_id"], []).append((r["group_id"], r["role"], "list"))
    below = {}
    # Fable review F8: only the folders above these lists (one upward walk from their nodes), not every folder group share of
    # the instance; lf_lists_below then maps each to the lists below it (the trash included, as before)
    with system_ctx(c):
        up = [x[0] for x in c.execute("""WITH RECURSIVE up(id, parent_id, kind, lvl) AS (
                                            SELECT id, parent_id, kind, 0 FROM fs_nodes WHERE kind='ref' AND ref_kind='list'
                                            AND ref_id = ANY(CAST(? AS BIGINT[]))
                                            UNION SELECT n.id, n.parent_id, n.kind, up.lvl + 1 FROM fs_nodes n JOIN up ON n.id=up.parent_id
                                            WHERE up.lvl < 64)
                                          SELECT DISTINCT id FROM up WHERE kind='folder'""", (st_ids(sorted(ids)),)).fetchall()]
    for r in (grp_folder_rows(c, nids=up) if up else []):
        if r["node_id"] not in below:
            below[r["node_id"]] = lf_lists_below(c, r["node_id"])
        for lid in below[r["node_id"]]:
            if lid in ids:
                out.setdefault(lid, []).append((r["group_id"], r["role"], r["folder"]))
    gids = sorted({x[0] for v in out.values() for x in v if x[0]})
    if gids:
        names = {r[0]: r[1] for r in c.execute("SELECT id, name FROM groups WHERE id = ANY(CAST(? AS BIGINT[]))", (st_ids(gids),))}
    return out, names


def grp_org_limited(c, org_id, uid):
    """2.568.0 (#4739, audit A-F10): a group's share never gives a guest / an accounting person of the list's organisation a
    role there (accounts/orgroles.py: they see in the organisation only what is shared with them personally); a private list
    (org_id None) keeps the group's share. Used by grp_sync (group_shares) and lffolder.lf_want (a group's folder share)."""
    if not org_id:
        return False
    return org_role_key(c, uid, org_id) in ("guest", "accounting")


def grp_list_ids(c, gid=None, owner=None):
    """Lists touched by the shares of group gid (or by the folder shares of owner): the ones grp_sync must look at."""
    ids = set()
    from .lffolder import lf_lists_below
    if gid is not None:  # 2.958.0 (#5245): the projects' own shares with the group (group_shares is gone)
        ids.update(r["list_id"] for r in grp_own_rows(c, gid=gid))
    if owner is not None:  # 2.958.0 (#5245): the lists below owner's folders shared with a group
        for r in grp_folder_rows(c, owner=owner):
            ids.update(lf_lists_below(c, r["node_id"]))
    if gid is not None:  # 2.352.0 A (#2748): the lists below projects folders shared with the group
        with system_ctx(c):
            for r in c.execute("SELECT node_id FROM fs_shares WHERE group_id=?", (gid,)).fetchall():
                ids.update(lf_lists_below(c, r[0]))
            ids.update(r[0] for r in c.execute("SELECT DISTINCT m.list_id FROM list_members m JOIN group_members gm ON gm.user_id=m.user_id "
                                               "WHERE m.frole IS NOT NULL AND gm.group_id=?", (gid,)))
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
    from ..agents.safety import bridge_blocks
    from .lffolder import lf_own_expired, lf_own_stale, lf_place, lf_skips, lf_want  # 2.352.0 A (#2748): the roles through the list's folders (frole)
    actor = actor if actor is not None else (me() if has_request_context() and getattr(g, "user", None) else None)
    agents = agent_ids(c)
    kids = {r[0] for r in c.execute("SELECT id FROM users WHERE kid=1")}
    for lid in sorted({int(x) for x in lids if x}):
        lr = c.execute("SELECT id, owner_id, org_id, name, is_inbox, e2e FROM lists WHERE id=?", (lid,)).fetchone()
        if not lr:
            continue
        want, gname = {}, {}
        from ..accounts.orgs import ws_member_problem
        if not lr["is_inbox"]:
            for gid, role, via in grp_shares_of_list(c, lid):
                if via != "list":  # 2.958.0 (#5245): a folder's group share is a folder role (lf_want -> frole), not grole
                    continue
                for uid in grp_members(c, gid):
                    if uid == lr["owner_id"] or uid in agents or ws_member_problem(c, lid, uid):  # 2.28.0 (#935): of the list's workspace only
                        continue
                    if grp_org_limited(c, lr["org_id"], uid):  # 2.568.0 (#4739, A-F10): a guest / accounting person: no role via a group
                        continue
                    if role_max(want.get(uid), role) != want.get(uid):
                        want[uid], gname[uid] = role_max(want.get(uid), role), gid
        rows = {r["user_id"]: r for r in c.execute("SELECT * FROM list_members WHERE list_id=?", (lid,))}
        if not lr["is_inbox"]:
            lf_place(c, lid)
        skips = lf_skips(c, lid)
        gone = lf_own_expired(c, lid)  # 2.568.0 (#4739): a member share of the core that ran out ends the own role
        fwant = {u: r for u, r in lf_want(c, lid).items() if u not in skips}
        for uid in [u for u in fwant if u not in rows and u not in want]:
            if bridge_blocks(c, lid, uid):  # 2.30.0 (#919) for a folder's share too
                fwant.pop(uid, None)
        if want and not lr["is_inbox"]:  # 2.30.0 (#919): a group never adds a person who would connect lists with different
            # people through the list's agent (skipped like another workspace)
            for uid in [u for u in want if u not in rows and bridge_blocks(c, lid, u)]:
                want.pop(uid, None)
        for uid in sorted(set(rows) | set(want) | set(fwant)):
            r, gr, fr = rows.get(uid), want.get(uid), fwant.get(uid)
            own = None
            if r is not None:  # 2.352.0 A (#2748): a row only through folders (frole) has no own role either
                own = r["own_role"] if r["own_role"] is not None else (r["role"] if r["grole"] is None and r["frole"] is None else None)
                if uid in gone:
                    own = None
            eff = role_max(own, gr, fr)
            if eff and uid in kids:  # 2.19.0 (#653)
                eff, gr, fr = "participant", ("participant" if gr else gr), ("participant" if fr else fr)
            if eff == "participant" and lr["e2e"]:  # 2.64.1 (#1817): a list with the lock has no participants (no access)
                eff = None
                if r is None:
                    continue
            if r is None and fr and not gr:  # 2.352.0 A (#2748): a folder's share follows the rules of a list's share (lock)
                from ..collab.liste2e import le2a_member_problem
                if le2a_member_problem(c, lid, uid, eff):
                    continue
            if r is None:
                if not c.execute("INSERT INTO list_members(list_id,user_id,role,own_role,grole,frole,sort,added_at) VALUES(?,?,?,?,?,?,?,?) "
                                 "ON CONFLICT(list_id,user_id) DO NOTHING",  # 2.352.0 F (#2748, review N10): a second share at the same time
                                 (lid, uid, eff, None, gr, fr, my_max_sort(c, uid) + 1, iso(now_utc()))).rowcount:
                    continue
                member_folder_adopt(c, lid, uid)
                news_add(c, uid, "share", list_id=lid, actor=actor,
                         data={"role": eff, "name": lr["name"], "group": grp_name(c, gname.get(uid))})
                wh_note_list(lid, "list.shared", {"member_id": uid, "role": eff, "group_id": gname.get(uid),
                                                  **({"via_folder": True} if fr and not gr else {})})  # 2.352.0 A (#2748)
                if fr and not gr and uid in agents:
                    from ..admin.hosting import agent_joined_notice
                    agent_joined_notice(c, lid, uid, actor)  # 2.352.0 A (#2748): like _folder_member_add
            elif eff is None:
                c.execute("DELETE FROM list_members WHERE list_id=? AND user_id=?", (lid, uid))
                c.execute("UPDATE tasks SET assignee_id=NULL WHERE list_id=? AND assignee_id=?", (lid, uid))
                dlg_gone(c, lid, uid)  # 2.473.0 (#3357): delegated tasks and watching of this list end
                # 2.352.0 F (#2748, review N7): like removing a member by hand (lists.py member_remove)
                c.execute("DELETE FROM task_bell WHERE user_id=? AND task_id IN (SELECT id FROM tasks WHERE list_id=?)", (uid, lid))
                c.execute("DELETE FROM user_task_order WHERE user_id=? AND task_id IN (SELECT id FROM tasks WHERE list_id=?)", (uid, lid))
                c.execute("DELETE FROM task_field_values WHERE value=? AND field_id IN (SELECT id FROM list_fields WHERE list_id=? AND type='person')",
                          (str(uid), lid))
                news_add(c, uid, "unshare", list_id=lid, actor=actor, data={"name": lr["name"]})
            elif (r["role"], r["own_role"], r["grole"], r["frole"]) != (eff, own, gr, fr):
                c.execute("UPDATE list_members SET role=?, own_role=?, grole=?, frole=? WHERE list_id=? AND user_id=?", (eff, own, gr, fr, lid, uid))
                if r["role"] != eff:
                    news_add(c, uid, "role", list_id=lid, actor=actor, data={"role": eff, "old": r["role"], "name": lr["name"]})
        lf_own_stale(c, lid)  # 2.568.0 (#4739): the core's member rows follow list_members (the role table)
        # a group assignment stays only while that group still has access to the list
        gids = {x[0] for x in grp_shares_of_list(c, lid)}
        for t in c.execute("SELECT id, assignee_group_id FROM tasks WHERE list_id=? AND assignee_group_id IS NOT NULL", (lid,)).fetchall():
            if t["assignee_group_id"] not in gids:
                c.execute("UPDATE tasks SET assignee_group_id=NULL WHERE id=?", (t["id"],))


def grp_touch(c, owner):
    """The lists of owner moved between folders / were created: re-sync them if one of their folders is shared. 2.352.0 A
    (#2748): their nodes follow their paths (lf_sync_owner); a list that got a new place gets its roles through the folders anew."""
    from .lffolder import lf_sync_owner
    moved = set(lf_sync_owner(c, owner))
    if grp_folder_rows(c, owner=owner):  # 2.958.0 (#5245): a folder of owner shared with a group
        grp_sync(c, grp_list_ids(c, owner=owner) | {r[0] for r in c.execute("SELECT id FROM lists WHERE owner_id=?", (owner,))})
    elif moved:
        grp_sync(c, moved)


def grp_name(c, gid):
    if not gid:
        return ""
    r = c.execute("SELECT name FROM groups WHERE id=?", (gid,)).fetchone()
    return r[0] if r else ""


def grp_dict(c, r, full=True):
    from ..collab.comments import user_names
    mem = grp_members(c, r["id"])
    names = user_names(c, mem)
    from ..lists.grouppics import fg_avatar_url
    d = {"id": r["id"], "name": r["name"], "oidc_group": r["oidc_group"] or "", "synced": bool(r["oidc_group"]),
         "avatar": fg_avatar_url(r),  # 2.46.0 (#1605)
         "members": [{"user_id": u, "name": names.get(u, "?")} for u in mem], "created_at": r["created_at"]}
    if full:
        # 2.958.0 (#5245): the shares of the projects' and folders' nodes (group_shares is gone), the same shape as before
        d["shares"] = [{"list_id": s["list_id"], "folder": None, "owner_id": None, "role": s["role"]} for s in grp_own_rows(c, gid=r["id"])] + \
                      [{"list_id": None, "folder": s["folder"], "owner_id": s["owner_id"], "role": s["role"]} for s in grp_folder_rows(c, gid=r["id"])]
    return d


def groups_for(c, uid=None, full=False):
    """Every group with its members (names only; persons see all groups to share with them). 2.28.0 (#935): in the mode
    workspaces only the members one may see."""
    from ..accounts.orgs import instance_mode, visible_people
    out = [grp_dict(c, r, full) for r in c.execute("SELECT * FROM groups ORDER BY lower(name), id")]
    if has_request_context() and getattr(g, "user", None) is not None and (
            instance_mode(c) == "workspaces" or (g.user["kind"] or "user") == "agent"):  # 2.223.7 A (#2917): agents always
        vis = visible_people(c, me())
        if vis is not None:
            # 2.30.0 (#1036, B1): a group is known only to its creator, its members and the people of an organisation one of
            # its members is in (its name stays inside the organisation; a private connection to one member is not enough)
            ok = {d["id"] for d in out if grp_visible(c, d)}
            out = [d for d in out if d["id"] in ok]
            for d in out:
                d["members"] = [m for m in d["members"] if m["user_id"] in vis]
    return out


def grp_clean_name(v):
    if not isinstance(v, str) or not v.strip():
        raise BadInput(tr("Name missing"))
    return re.sub(r"\s+", " ", v).strip()[:GROUP_NAME_MAX]


def grp_set_members(c, gid, ids, actor=None):
    """Replaces the members of group gid with ids (active persons only); re-syncs the lists the group reaches."""
    want = set()
    for x in ids or []:
        try:
            x = int(x)
        except (TypeError, ValueError):
            raise BadInput(tr("unknown person")) from None
        u = c.execute("SELECT kind FROM users WHERE id=?", (x,)).fetchone()
        if not u or u["kind"] == "agent":
            raise BadInput(tr("Only people can be group members"))
        from ..accounts.users import admin_sees
        if has_request_context() and getattr(g, "user", None) is not None and not admin_sees(c, x):  # 2.28.0 (#935): mode workspaces
            raise BadInput(tr("unknown person"))
        want.add(x)
    before = grp_list_ids(c, gid)
    cur = set(grp_members(c, gid))
    for x in cur - want:
        c.execute("DELETE FROM group_members WHERE group_id=? AND user_id=?", (gid, x))
    for x in sorted(want - cur):
        c.execute("INSERT INTO group_members(group_id,user_id,added_at) VALUES(?,?,?) ON CONFLICT DO NOTHING", (gid, x, iso(now_utc())))
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


def grp_visible(c, r):
    """2.30.0 (#1036, B1): in the mode workspaces a group is visible to its creator, its members and the members of the
    organisations its members belong to -- not to somebody who only knows one member privately."""
    from ..accounts.orgs import instance_mode
    agent = has_request_context() and getattr(g, "user", None) is not None and (g.user["kind"] or "user") == "agent"
    if not agent and (instance_mode(c) != "workspaces" or not has_request_context() or getattr(g, "user", None) is None):
        return True
    uid = me()
    if c.execute("SELECT created_by FROM groups WHERE id=?", (r["id"],)).fetchone()[0] == uid:
        return True
    mem = grp_members(c, r["id"])
    if uid in mem:
        return True
    if agent:
        return False  # 2.223.7 A (#2917): an agent knows only the groups it is in, not those of its whole organisation
    from ..accounts.orgroles import user_orgs_full
    mine = user_orgs_full(c, uid)  # 2.143.0 A (#2151, review): not through an organisation where uid is guest / accounting
    if not mine or not mem:
        return False
    return bool(c.execute(f"SELECT 1 FROM org_members WHERE org_id IN ({','.join('?' * len(mine))}) AND user_id IN ({','.join('?' * len(mem))}) LIMIT 1",
                          [*mine, *mem]).fetchone())


def need_group(c, gid):
    r = c.execute("SELECT * FROM groups WHERE id=?", (gid,)).fetchone()
    if not r or not grp_visible(c, r):
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
    if c.execute("SELECT 1 FROM groups WHERE lower(name)=lower(?)", (name,)).fetchone():
        return err(tr("A group with this name exists already"), 409)
    og = str(b.get("oidc_group") or "").strip()[:200]
    gid = insert_id(c, "INSERT INTO groups(name,oidc_group,created_at,created_by) VALUES(?,?,?,?)",
                    (name, og, iso(now_utc()), me()))
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
        if c.execute("SELECT 1 FROM groups WHERE lower(name)=lower(?) AND id!=?", (name, gid)).fetchone():
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
    # 2.958.0 (#5245): the group's shares of projects and folders are fs_shares rows: they go with the group (ON DELETE CASCADE)
    c.execute("DELETE FROM group_members WHERE group_id=?", (gid,))
    old = c.execute("SELECT avatar FROM groups WHERE id=?", (gid,)).fetchone()
    c.execute("DELETE FROM groups WHERE id=?", (gid,))
    grp_sync(c, lids)
    bump(c)
    c.commit()
    from ..lists.grouppics import fg_drop_file
    fg_drop_file(gid, old[0] if old else "")  # 2.46.0 (#1605)
    return jsonify(ok=True)


def grp_role(b):
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
        return err(tr("The basket cannot be shared"))
    qn_private(c, lid)  # 2.477.0 (#3881)
    role = grp_role(body())
    from ..collab.liste2e import le2e_mode
    if role == "participant" and le2e_mode(c, lid):  # 2.64.1 (#1817)
        return jsonify(error=tr("Projects encrypted in the browser have no participants. Select another role."), code="list_e2e_member"), 409
    from ..accounts.orgs import ws_member_problem
    for uid in grp_members(c, gid):  # 2.28.0 (#935): everyone in the group must belong to the list's workspace
        p = ws_member_problem(c, lid, uid)
        if p:
            return err(p, 409)
    grp_own_put(c, me(), lid, gid, role)  # 2.958.0 (#5245): the core's row on the project's node (group_shares is gone)
    grp_sync(c, [lid])
    bump(c)
    c.commit()
    return jsonify(ok=True)


def grp_dl_full(c, lids=(), uids=()):
    """2.958.0 (#5245, Fable review F4): a share of a node with a group / a folder's share changes what the projects show (the
    group / folder marks of /api/state) also when no row of list_members changes (a group whose members are there already, an
    empty group, an empty folder) -- fs_shares has no delta trigger (tasks/delta.py DL_TABLES). The delta's own "full" rows of
    dl_changes (as its trigger writes them): one for whoever sees each list of lids, one for each person of uids."""
    for col, ids in (("list_id", lids), ("user_id", uids)):
        for x in sorted({int(i) for i in ids if i}):
            c.execute(f"""INSERT INTO dl_changes(task_id, {col}) SELECT NULL, ? WHERE NOT EXISTS (SELECT 1 FROM dl_changes
                          WHERE ver IS NULL AND task_id IS NULL AND {col}=? AND {'user_id' if col == 'list_id' else 'list_id'} IS NULL)""",
                      (x, x))


def grp_own_put(c, actor, lid, gid, role):
    """2.958.0 (#5245): project lid's own share with group gid (the route checked the right, the group and the project's rules):
    the core's row on the project's node (core/objects.py obj_share, list_own 1, list_role = role); the same group again changes
    its role. -> share id | None (the basket)."""
    from ..core.objects import obj_share
    from .lffolder import lf_place
    if not lf_place(c, int(lid)):
        return None
    with system_ctx(c):  # the node may lie in a folder the actor does not see (another person's path)
        sid = obj_share(c, actor, "list", int(lid), "group_id", int(gid), "edit" if role in ("admin", "edit") else "view", None,
                        extra={"list_role": role, "list_own": 1}, checked=True)
    grp_dl_full(c, [lid])  # F4
    return sid


def grp_own_drop(c, lid, gid):
    """2.958.0 (#5245): project lid's own share with group gid goes (the node's log names it; a group's row is not restorable
    through the core, docs/dev/kern.md) -> True when there was one."""
    from .lffolder import _log
    rows = [r for r in grp_own_rows(c, [lid], gid=gid)]
    with system_ctx(c):
        for r in rows:
            nid = c.execute("SELECT node_id FROM fs_shares WHERE id=?", (r["share_id"],)).fetchone()
            c.execute("DELETE FROM fs_shares WHERE id=?", (r["share_id"],))
            if nid:
                _log(c, nid[0], "unshare", str(r["share_id"]))
    if rows:
        grp_dl_full(c, [lid])  # F4
    return bool(rows)


@app.delete("/api/lists/<int:lid>/groups/<int:gid>")
def list_group_del(lid, gid):
    need_collab()
    c = db()
    need_list(c, lid, write=False, manage=True)
    if not grp_own_drop(c, lid, gid):  # 2.958.0 (#5245)
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
    return jsonify(groups=[{"group_id": gid, "name": grp_name(c, gid), "role": role}
                           for gid, role in sorted(_fgroups(c, me(), f).items())])  # 2.958.0 (#5245): the folder nodes' shares


def _fgroups(c, owner, f):
    """2.958.0 (#5245): {group id: role} of owner's folder at path f (the highest of its nodes' group shares)."""
    out = {}
    for r in grp_folder_rows(c, owner=owner):
        if r["folder"] == f:
            out[r["group_id"]] = role_max(out.get(r["group_id"]), r["role"])
    return out


def fg_group_diff(c, owner, f, gid, role):
    """2.46.0 (#1606): [{list_id, name, role}] of owner's lists in folder f shared with group gid directly with another role than
    `role` -- only when the folder is shared with the group already and its role changes (a first share touches no list)."""
    prev = _fgroups(c, owner, f).get(gid)  # 2.958.0 (#5245): the folder nodes' and the projects' nodes' shares
    if not prev or prev == role:
        return []
    own = {r["list_id"]: r["role"] for r in grp_own_rows(c, gid=gid)}
    return [{"list_id": r["id"], "name": r["name"], "role": own[r["id"]]} for r in c.execute(
        """SELECT l.id, l.name, l.folder FROM lists l WHERE l.owner_id=? AND l.archived=0 AND l.is_inbox=0
           ORDER BY lower(l.name), l.id""", (owner,)).fetchall()
        if r["id"] in own and _in_folder(r["folder"], f) and own[r["id"]] != role]


@app.get("/api/folders/groups/<int:gid>/diff")
def folder_group_diff(gid):
    """?folder=&role=: the lists of my folder where that group role would replace the group's own role in the list (#1606)."""
    need_collab()
    c = db()
    need_group(c, gid)
    f = clean_folder(str(request.args.get("folder") or ""), False)
    if not f:
        return err(tr("Name missing"))
    role = grp_role(request.args)
    return jsonify(lists=fg_group_diff(c, me(), f, gid, role))


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
    from ..collab.liste2e import le2a_folder_problem
    p = le2a_folder_problem(c, me(), f, role)  # 2.64.1 (#1817): no participants in lists with the lock
    if p:
        return jsonify(error=p, code="list_e2e_member"), 409
    from ..accounts.orgs import ws_member_problem
    for l in c.execute("SELECT id, folder FROM lists WHERE owner_id=? AND is_inbox=0", (me(),)).fetchall():  # 2.28.0 (#935)
        if _in_folder(l["folder"], f):
            for uid in grp_members(c, gid):
                p = ws_member_problem(c, l["id"], uid)
                if p:
                    return err(p, 409)
    before = grp_list_ids(c, owner=me())
    if gid in _fgroups(c, me(), f):
        # 2.46.0 (#1606): a changed folder role also replaces the group's own role in the lists of the folder, unless apply: false
        if b.get("apply", True) is not False:
            for x in fg_group_diff(c, me(), f, gid, role):
                grp_own_put(c, me(), x["list_id"], gid, role)  # 2.958.0 (#5245)
    from .lffolder import lf_folder_share
    lf_folder_share(c, me(), f, gid, role, group=True)  # 2.958.0 (#5245): the share of the folder's nodes (group_shares is gone)
    grp_sync(c, before | grp_list_ids(c, owner=me()))
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.delete("/api/folders/groups/<int:gid>")
def folder_group_del(gid):
    need_collab()
    c = db()
    f = clean_folder(str(request.args.get("folder") or ""), False)
    before = grp_list_ids(c, owner=me())
    if gid not in _fgroups(c, me(), f):  # 2.958.0 (#5245): the folder nodes' shares (group_shares is gone)
        return err(tr("unknown"), 404)
    from .lffolder import lf_folder_share
    lf_folder_share(c, me(), f, gid, None, group=True)
    grp_sync(c, before)
    bump(c)
    c.commit()
    return jsonify(ok=True)


def check_group_assignee(c, lid, gid):
    """None if group gid may be assigned in list lid (the list is shared with it), else an error message."""
    if gid is None:
        return None
    need_collab()
    return None if gid in {x[0] for x in grp_shares_of_list(c, lid)} else tr("Share the project with this group first")


def grp_assign_events(c, tid, gid):
    """News, 2.367.2 (#2968) push + mail with the rules of a plain assignment for every member of the group the task was just
    assigned to (only the group's name differs in the text)."""
    from ..agents.core import agent_ids
    from ..collab.comments import burst_gate, lang_of, user_names
    from ..collab.news import KIND_ROW
    from ..core.objnotify import obj_notify
    from ..notify.channels import evm_note
    from ..notify.push import push_prio, push_reachable
    from ..notify.taskbell import tbl_level
    actor = me() if has_request_context() and getattr(g, "user", None) else None
    t = c.execute("SELECT title, list_id FROM tasks WHERE id=?", (tid,)).fetchone()
    if not t:
        return
    gname = grp_name(c, gid)
    bots = agent_ids(c)
    who = user_names(c, [actor]).get(actor, "?") if actor else None
    for uid in grp_members(c, gid):
        if uid == actor or uid in bots:
            continue
        # 2.891.0 (#5270): who may still read the task decides the core's send decision (obj_role >= view), no check of its own
        got = obj_notify(c, "task", tid, [uid], row=KIND_ROW["assign"], lid=t["list_id"],
                         news={"kind": "assign", "task_id": tid, "actor": actor, "data": {"group": gname, "group_id": gid}},
                         follow=lambda u, s: bool(actor) and not tbl_level(c, u, tid, s))
        if uid not in got:
            continue
        s = got[uid]
        evm_note(c, uid, "assign", tid, actor, s)
        if push_reachable(c, uid, s) and burst_gate(c, uid, tid, event=True):
            lg = lang_of(s)
            g.pushes.append((uid, tr("{0} assigned {1}: {2}", who, gname, t["title"], lg=lg), tr("Whoever has time takes it", lg=lg),
                             f"{PUBLIC_URL}/#t/{tid}", push_prio(s), {"kind": "assign"}))


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
    from .rules import rul_fire, rul_snap
    rb = rul_snap(c, tid)  # 2.138.0 D (#2060): taking it = assigned (rule trigger)
    c.execute("UPDATE tasks SET assignee_id=?, assignee_group_id=NULL, assigned_by=?, reminded='[]', updated_at=? WHERE id=?",
              (uid, uid, iso(now_utc()), tid))
    log_act(c, tid, "take", {"group": grp_name(c, t["assignee_group_id"])})
    for m in grp_members(c, t["assignee_group_id"]):
        if m != uid:  # 2.891.0 (#5270): news_add asks the core's send decision (obj_role >= view of the task)
            news_add(c, m, "take", task_id=tid, data={"group": grp_name(c, t["assignee_group_id"])})
    agent_assign_event(c, tid, "assigned", uid)
    rul_fire(c, tid, rb)
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
