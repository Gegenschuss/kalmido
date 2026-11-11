"""2.958.0 (#5245, stage 7d of the shared core, one-way, decided 08.11.2026): the projects' old share tables go.

- folder_people (2.22.0: a folder of an owner shared with a person) was a mirror of the folder nodes' shares since 2.352.0
  (lists/lffolder.py _people_mirror); its readers now read the shares themselves (lffolder.lf_people_rows / lf_people), so an
  expiry ends a folder share at once, without the watchdog's tick.
- group_shares (2.10.0: a project or a folder of its owner shared with a group) is a share of the node: a project's own group
  share = fs_shares.group_id on the project's node with list_own = 1 and list_role (lists/groups.py grp_shares_of_list, the
  group's role grole); a folder's group share = fs_shares.group_id on the owner's folder nodes at that path (list_own 0), which
  reaches the projects below through the folders (lffolder.lf_want, the folders' role frole -- like a person's folder share).

At a start (core/db.py init_db's one transaction, core/objhooks.START):
1. lk_grp_copy, once (flag migr_grp5245; the writers of this version no longer write group_shares, so a second copy could
   reopen a share taken away since): every row of group_shares without its share on the node gets one (a project's node is
   placed where its path says, a folder's nodes are made where missing, like lffolder.lf_migrate did for folder_people).
2. lk_retire at every start while a table exists (core/kernretire.py kern_retire, lock kalmido-kern5069), each table on its own:
   the start check counts old rows the core does not hold; not 0: the table stays, a line in the log, the admins' alert;
   0: DROP TABLE and its rows of obj_revoked, the database's back limit rises to this minor (an older image would rebuild the
   tables empty and lose every group share, or read folder_people without the rows of folders shared since).

Interface:
  lk_fp_left(c) -> n       folder_people rows without a share of that person / agent on a folder node of the owner
  lk_grp_left(c) -> n      group_shares rows without their share on the node (a project's or one of the folder's)
  lk_grp_copy(c) -> {...}  the forward copy (above)
  lk_retire(c) -> {...}    the start check and DROP of both tables
"""
from ..core import objhooks
from ..core.i18n import N_
from ..core.kernretire import kern_retire
from ..core.pg import system_ctx, table_exists
from ..notify.alerts import aa_now
from .groups import grp_sync
from .lffolder import LF_KIND, LIST_ROLES, _now, _parts, lf_folder_ensure, lf_folder_nodes, lf_place

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


def lk_grp_left(c):
    """The start check of group_shares: a project's row (not the basket) without a group share of its own (list_own 1) on the
    project's node; a folder's row (a path) without a share of the group on a folder node of the owner (any role / state)."""
    a = c.execute("""SELECT COUNT(*) FROM group_shares g JOIN lists l ON l.id=g.list_id
                     WHERE l.is_inbox=0 AND NOT EXISTS (SELECT 1 FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id
                       WHERE n.kind='ref' AND n.ref_kind=? AND n.ref_id=g.list_id AND s.group_id=g.group_id AND s.list_own=1)""",
                  (LF_KIND,)).fetchone()[0]
    b = c.execute("""SELECT COUNT(*) FROM group_shares g WHERE g.list_id IS NULL AND COALESCE(g.folder, '') <> ''
                     AND g.owner_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id
                       WHERE n.kind='folder' AND n.owner_id=g.owner_id AND s.group_id=g.group_id AND COALESCE(s.list_own, 0)=0)""").fetchone()[0]
    return a + b


def _role(r):
    role = r if r in LIST_ROLES else "edit"
    return role, ("edit" if role in ("admin", "edit") else "view")


def lk_grp_copy(c):
    """The forward copy of group_shares (module docstring, once). {own, folder}; {} without the old table."""
    if not table_exists(c, GS_OLD):
        return {}
    out = {"own": 0, "folder": 0}
    with system_ctx(c):
        for g in c.execute("""SELECT g.* FROM group_shares g JOIN lists l ON l.id=g.list_id WHERE l.is_inbox=0
                              ORDER BY g.list_id, g.id""").fetchall():
            nid = lf_place(c, g["list_id"])
            if not nid or c.execute("SELECT 1 FROM fs_shares WHERE node_id=? AND group_id=? AND list_own=1",
                                    (nid, g["group_id"])).fetchone():
                continue
            role, fr = _role(g["role"])
            c.execute("""INSERT INTO fs_shares(node_id,group_id,role,list_role,list_own,created_by,created_at)
                         VALUES(?,?,?,?,1,?,?)""", (nid, g["group_id"], fr, role, g["added_by"], g["added_at"] or _now()))
            out["own"] += 1
        for g in c.execute("""SELECT * FROM group_shares WHERE list_id IS NULL AND owner_id IS NOT NULL AND COALESCE(folder, '') <> ''
                              ORDER BY owner_id, folder, id""").fetchall():
            if not _parts(g["folder"]):
                continue
            role, fr = _role(g["role"])
            for f in lf_folder_nodes(c, g["owner_id"], g["folder"]) or lf_folder_ensure(c, g["owner_id"], g["folder"]):
                if c.execute("SELECT 1 FROM fs_shares WHERE node_id=? AND group_id=? AND COALESCE(list_own, 0)=0",
                             (f["id"], g["group_id"])).fetchone():
                    continue
                c.execute("""INSERT INTO fs_shares(node_id,group_id,role,list_role,created_by,created_at) VALUES(?,?,?,?,?,?)""",
                          (f["id"], g["group_id"], fr, role, g["added_by"] or g["owner_id"], g["added_at"] or _now()))
                out["folder"] += 1
        if out["own"] or out["folder"]:
            lids = [r[0] for r in c.execute("SELECT id FROM lists WHERE is_inbox=0 ORDER BY id")]
            grp_sync(c, lids, actor=0)  # the folders' group shares are folder roles now (frole instead of grole)
    if any(out.values()):
        print("project / folder shares with groups into the shared core (#5245):", out, flush=True)
    return out


objhooks.START.append((GS_COPY_FLAG, True, lk_grp_copy))  # 2.958.0 (#5245): once (core/db.init_db sets the flag)


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
