"""2.958.0 (#5245, stage 7d of the shared core, one-way, decided 08.11.2026): the projects' old share tables go.

- folder_people (2.22.0: a folder of an owner shared with a person) was a mirror of the folder nodes' shares since 2.352.0
  (lists/lffolder.py _people_mirror); its readers now read the shares themselves (lffolder.lf_people_rows / lf_people), so an
  expiry ends a folder share at once, without the watchdog's tick.
- group_shares (2.10.0: a project or a folder of its owner shared with a group) is a share of the node: a project's own group
  share = fs_shares.group_id on the project's node with list_own = 1 and list_role (lists/groups.py grp_shares_of_list, the
  group's role grole); a folder's group share = fs_shares.group_id on the owner's folder nodes at that path (list_own 0), which
  reaches the projects below through the folders (lffolder.lf_want, the folders' role frole -- like a person's folder share).

At a start (core/db.py init_db's one transaction, core/objhooks.START):
1. lk_grp_copy, at every start until no row is left (then flag migr_grp5245; Fable review F6): every row of group_shares
   without its share on the node gets one (a project's node is placed where its path says, a folder's nodes are made where
   missing, like lffolder.lf_migrate did for folder_people; a share there already keeps the higher role, F5); the rows the core
   holds then leave group_shares at once (the writers of this version no longer write it, so a later copy of them could reopen
   a share taken away since), and the back limit rises already here (F3).
2. lk_retire at every start while a table exists (core/kernretire.py kern_retire, lock kalmido-kern5069), each table on its own:
   the start check counts old rows the core does not hold; not 0: the table stays, a line in the log, the admins' alert;
   0: DROP TABLE and its rows of obj_revoked, the database's back limit rises to this minor (an older image would rebuild the
   tables empty and lose every group share, or read folder_people without the rows of folders shared since).

Interface:
  lk_fp_left(c) -> n       folder_people rows without a share of that person / agent on a folder node of the owner
  lk_grp_left(c) -> n      group_shares rows without their share on the node (a project's, or one of the folder's nodes at its path)
  lk_grp_copy(c) -> {...}  the forward copy (above)
  lk_retire(c) -> {...}    the start check and DROP of both tables
"""
from ..core import objhooks
from ..core.i18n import N_
from ..core.db import gset, gsetting
from ..core.kernretire import kern_retire, kern_retire_floor
from ..core.pg import st_ids, system_ctx, table_exists
from ..notify.alerts import aa_now
from .groups import grp_list_ids, grp_sync
from .lffolder import LF_KIND, LIST_ROLES, _RANK, _now, _parts, lf_folder_ensure, lf_folder_nodes, lf_place

FP_OLD = "folder_people"
GS_OLD = "group_shares"
GS_COPY_FLAG = "migr_grp5245"


def lk_fp_left(c):
    """The start check of folder_people: rows (a folder path, another person than its owner, an account that still exists)
    without any share of that person / agent on a folder node of the owner (any role, also an expired one or a folder in the
    trash: the core has it, it decides). lffolder.lf_migrate (2.352.0) copied every row forward once; the mirror only wrote
    what the shares said since."""
    return c.execute("""SELECT COUNT(*) FROM folder_people p JOIN users u ON u.id=p.user_id
                        WHERE p.folder <> '' AND p.user_id <> p.owner_id AND NOT EXISTS (
                          SELECT 1 FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id
                          WHERE n.kind='folder' AND n.owner_id=p.owner_id AND COALESCE(s.user_id, s.agent_id)=p.user_id)""").fetchone()[0]


def _grp_left_ids(c):
    """2.958.0 (#5245, Fable review F6): the ids of the group_shares rows the core does not hold yet -- a project's row (not the
    basket) without a group share of its own (list_own 1) on the project's node; a folder's row (a path) without a share of the
    group on one of the owner's folder nodes AT THAT PATH (lf_folder_nodes; was: on any folder node of the owner, so a folder
    whose nodes could not be made counted as held when another folder of the owner was shared with the same group)."""
    out = [r[0] for r in c.execute("""SELECT g.id FROM group_shares g JOIN lists l ON l.id=g.list_id
                     WHERE NOT l.is_inbox AND NOT EXISTS (SELECT 1 FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id
                       WHERE n.kind='ref' AND n.ref_kind=? AND n.ref_id=g.list_id AND s.group_id=g.group_id AND s.list_own=1)""",
                                   (LF_KIND,)).fetchall()]
    for g in c.execute("""SELECT id, owner_id, folder, group_id FROM group_shares WHERE list_id IS NULL AND COALESCE(folder, '') <> ''
                          AND owner_id IS NOT NULL ORDER BY id""").fetchall():
        if not _parts(g["folder"]):
            continue  # no path (only slashes): nothing to keep (the copy skips it too)
        nids = [f["id"] for f in lf_folder_nodes(c, g["owner_id"], g["folder"])]
        if not nids or not c.execute("""SELECT 1 FROM fs_shares WHERE node_id = ANY(CAST(? AS BIGINT[])) AND group_id=?
                                        AND COALESCE(list_own, 0)=0 LIMIT 1""", (st_ids(nids), g["group_id"])).fetchone():
            out.append(g["id"])
    return out


def lk_grp_left(c):
    """The start check of group_shares: the number of its rows without their share on the node (_grp_left_ids)."""
    return len(_grp_left_ids(c))


def _role(r):
    role = r if r in LIST_ROLES else "edit"
    return role, ("edit" if role in ("admin", "edit") else "view")


def _raise(c, sid, have, role):
    """F5: the share there already keeps the higher of both roles (the old row's role reaches it). True when raised."""
    old = have["list_role"] if have["list_role"] in LIST_ROLES else ("edit" if have["role"] == "edit" else "view")
    if _RANK.get(role, 0) <= _RANK.get(old, 0):
        return False
    c.execute("UPDATE fs_shares SET role=?, list_role=? WHERE id=?", ("edit" if role in ("admin", "edit") else "view", role, sid))
    return True


def lk_grp_copy(c):
    """The forward copy of group_shares (module docstring). {own, folder, raised}; {} without the old table or once done (flag).
    2.958.0 Fable review: F6 - it runs at every start until the start check finds no row left (then the flag); a later run copies
    only the rows without their core row: the rows the core holds leave group_shares right after this step, so a share taken
    away since is never reopened from the old table. F5 - a share already there keeps the higher role; grp_sync runs over the
    lists of every group the old rows name (also when nothing was copied: grole rows of folder shares become folder roles).
    F3 - once the old table was read, the database's back limit rises (kernretire.kern_retire_floor): an older image would
    read group_shares as the truth, which no writer of this version keeps up to date."""
    if not table_exists(c, GS_OLD) or gsetting(c, GS_COPY_FLAG) == "1":
        return {}
    out = {"own": 0, "folder": 0, "raised": 0}
    gids = set()
    with system_ctx(c):
        for g in c.execute("""SELECT g.* FROM group_shares g JOIN lists l ON l.id=g.list_id WHERE NOT l.is_inbox
                              ORDER BY g.list_id, g.id""").fetchall():
            gids.add(g["group_id"])
            nid = lf_place(c, g["list_id"])
            if not nid:
                continue
            role, fr = _role(g["role"])
            have = c.execute("SELECT id, role, list_role FROM fs_shares WHERE node_id=? AND group_id=? AND list_own=1",
                             (nid, g["group_id"])).fetchone()
            if have:
                out["raised"] += _raise(c, have["id"], have, role)
                continue
            c.execute("""INSERT INTO fs_shares(node_id,group_id,role,list_role,list_own,created_by,created_at)
                         VALUES(?,?,?,?,1,?,?)""", (nid, g["group_id"], fr, role, g["added_by"], g["added_at"] or _now()))
            out["own"] += 1
        for g in c.execute("""SELECT * FROM group_shares WHERE list_id IS NULL AND owner_id IS NOT NULL AND COALESCE(folder, '') <> ''
                              ORDER BY owner_id, folder, id""").fetchall():
            gids.add(g["group_id"])
            if not _parts(g["folder"]):
                continue
            role, fr = _role(g["role"])
            for f in lf_folder_nodes(c, g["owner_id"], g["folder"]) or lf_folder_ensure(c, g["owner_id"], g["folder"]):
                have = c.execute("SELECT id, role, list_role FROM fs_shares WHERE node_id=? AND group_id=? AND COALESCE(list_own, 0)=0",
                                 (f["id"], g["group_id"])).fetchone()
                if have:
                    out["raised"] += _raise(c, have["id"], have, role)
                    continue
                c.execute("""INSERT INTO fs_shares(node_id,group_id,role,list_role,created_by,created_at) VALUES(?,?,?,?,?,?)""",
                          (f["id"], g["group_id"], fr, role, g["added_by"] or g["owner_id"], g["added_at"] or _now()))
                out["folder"] += 1
        if gids:  # the folders' group shares are folder roles now (frole instead of grole)
            lids = set()
            for gid in sorted(gids):
                lids |= grp_list_ids(c, gid=gid)
            grp_sync(c, sorted(lids), actor=0)
        still = _grp_left_ids(c)
        c.execute("DELETE FROM group_shares WHERE NOT (id = ANY(CAST(? AS BIGINT[])))", (st_ids(still),))  # held by the core now
        kern_retire_floor(c)  # F3
        if not still:
            gset(c, GS_COPY_FLAG, "1")
    if any(out.values()):
        print("project / folder shares with groups into the shared core (#5245):", out, flush=True)
    return out


objhooks.START.append(("lk_grp_copy_5245", False, lk_grp_copy))  # 2.958.0 (#5245): until done (F6: lk_grp_copy sets the flag itself)


LK_RETIRE_WAITS = N_("Shared core clean-up waits: {0} old member rows of {1} have no share yet, the old table stays. See the server log.")


def _alert(n, tables):
    aa_now("storage", "kern5245:" + ",".join(tables), LK_RETIRE_WAITS, (int(n), ", ".join(tables)))


def lk_retire(c):
    """Every start while folder_people / group_shares exist: the start check, then DROP TABLE (one-way, migrations.d/5245_a.py)."""
    out = {}
    with system_ctx(c):
        for t, left in ((FP_OLD, lk_fp_left), (GS_OLD, lk_grp_left)):
            r = kern_retire(c, (t,), left, f"projects, stage 7d (#5245): {t}", alert=_alert)
            if r:
                out[t] = r
    return out


objhooks.START.append(("lk_retire_5245", False, lk_retire))  # 2.958.0 (#5245): every start until both tables are gone
