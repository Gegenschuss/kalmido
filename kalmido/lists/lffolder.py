"""2.352.0 A (#2748): the folders of the lists (projects) are folders of the file store -- the reference kind 'list' of the
folder system (files/fsref.py) below the area root "Projects" of each workspace (files/fsroots.py, area 'lists').

Tree and path (lists.folder stays the truth for older versions and the routes of today's client):
- Every list (not the inbox) is ONE reference node (kind 'ref', ref_kind 'list', ref_id = lists.id, name = the list's name) in
  the tree of its workspace: an organisation's list in the organisation's tree, a private list in its owner's own tree. Its
  folder = the folders of its owner's path lists.folder below the root (owner_id = the list's owner); a path has any depth.
- A path written the old way (PATCH of a list, /api/folders/rename | delete, a new list) places the node at once (lf_place,
  called by grp_touch / grp_sync); a node moved in the tree (the file store's routes -> fs_area_rule hooks, or POST
  /api/lists/tree/move) writes the path of every list below it, and a folder's path moves the folder settings, the playbook,
  the colours ... with it (sections.folder_rename_do: they stay keyed by (owner, path)).
- The same path of one owner in two workspaces (a private and an organisation's list in "Clients") are two folder nodes, one
  per tree; renaming / moving one by its path moves the other one too (lf_folder_repath): the path is the folder of the person.
- Only folders and lists lie below the root (closed area), a list never goes into the trash by its node (protect: a folder in
  the trash leaves its lists one level up, like deleting a folder before).

Rights at runtime (no copy any more):
- A share of a folder (fs_shares: person, group, agent; list_role = the list role admin | edit | participant | view, else role
  view / edit) reaches every list below it, also the ones that come later; revoking it, an expiry, moving the list out or the
  folder into the trash take it away. The list's own members stay; the highest role counts.
- lf_want(c, lid) computes who gets which role through the folders (the file store's rules for the chain: the organisation
  boundary, a read-only member at most 'view', expiry, the trash; organisation access opens no list -- only explicit shares,
  like every reference node), with the rules a share of a list has (several agents like in the file store -- "the" agent of a list stays the one set
  on it, core/access.py list_other_agent --, no agent on a health / budget / read
  later list or an organisation's trip, the workspace, the agent bridge, a list with the lock, kids take part).
  lists/groups.py grp_sync writes it into list_members.frole (role = the highest of own_role, grole, frole), so every reader
  of list_members (visibility, delta, notifications, the lock, agents, row-level security) sees it. A person removed from a
  list by hand gets a row in list_folder_skip: the folder no longer reaches them there.
- Every change of a share / move / trash / restore in the area runs grp_sync for the lists below the node (files/store.py
  fs_change_hooks); expired shares are swept by the watchdog (lf_expire_tick).

Interface:
  LF_KIND = 'list', LF_AREA = 'lists'
  lf_root(c, uid, org_id, create=True) -> node id | None   the "Projects" root of a workspace
  lf_place(c, lid) -> node id | None      the list's node where its path says (created / moved); caller commits
  lf_want(c, lid, lr=None) -> {uid: role} the roles the folders give (filtered as above, without list_folder_skip)
  lf_lists_below(c, nid) -> [list ids]    the lists filed below node nid (nid itself when it is a list's node)
  lf_folder_repath(c, owner, old, new)    the folder nodes of owner at path old (every tree) move to path new
  lf_folder_dissolve(c, owner, path)      the folder nodes at path go, their content one level up (POST /api/folders/delete)
  lf_folder_nodes(c, owner, path) -> rows the live folder nodes of owner at path (every tree)
  lf_node_folder(c, nid) -> (owner, path) | None   a projects folder node -> its owner and path (the folder settings' key)
  lf_migrate(c) -> {...}                  the one-way move of 2.352.0 (core/db.py, once)
  GET /api/lists/tree, POST /api/lists/folders, POST /api/lists/tree/move (see the routes)
"""
import json
import threading

from flask import has_app_context, jsonify

from ..core.config import app
from ..core.access import Denied, acx_of, reading_ids, reading_sql
from ..core.db import body, bump, db, err, insert_id, iso, now_utc, uset, usettings
from ..core.i18n import N_, lang, tr
from ..core.pg import system_ctx
from ..accounts.orgroles import FULL_WRITE, org_role_key, org_writes
from ..accounts.orgs import user_orgs, ws_member_problem
from ..accounts.session import me
from ..files import store as fs_store
from ..files.fsref import fs_ref_may_file, fs_ref_need_move, fs_ref_node, fs_ref_node_role, fs_ref_register, fs_ref_role
from ..files.fsroots import fs_area_root, fs_area_root_of, fs_area_rule
from .groups import grp_sync
from .sections import folder_rename_do
from ..files.store import DEPTH_MAX, _now, fs_chain, fs_deleted, fs_height, fs_log_add, fs_role, safe_fs_name

LF_KIND = "list"
LF_AREA = "lists"
LIST_ROLES = ("admin", "edit", "participant", "view")
_RANK = {None: 0, "participant": 1, "view": 2, "edit": 3, "admin": 4}  # lists/groups.py ROLE_RANK
_busy = threading.local()  # our own node writes must not start the change hooks again


def _rmax(*roles):
    rs = [r for r in roles if r in _RANK and r]
    return max(rs, key=_RANK.get) if rs else None


def _lrow(c, lid):
    return c.execute("SELECT id, owner_id, org_id, name, folder, is_inbox, archived, life, e2e FROM lists WHERE id=?",
                     (int(lid),)).fetchone()


# ---------------------------------------------------------------- the reference kind 'list'
def _base(c, uid, lid):
    """The list's own role (owner, a personal or a group share -- not the folders') as the folder system counts it."""
    lr = _lrow(c, lid)
    if lr is None or lr["is_inbox"] or not uid:
        return None
    if lr["owner_id"] == uid:
        return "edit"
    m = c.execute("SELECT role, own_role, grole, frole FROM list_members WHERE list_id=? AND user_id=?", (int(lid), uid)).fetchone()
    if m is None:
        return None
    own = m["own_role"] if m["own_role"] is not None else (m["role"] if m["grole"] is None and m["frole"] is None else None)
    r = _rmax(own, m["grole"])
    # 2.352.0 F (#2748, review H1): 'edit' (file it, move it, share a folder holding it) only for its owner / an admin -- like
    # sharing the list itself (lists.py member_set); an editor of the list counts as 'view' here
    return None if r is None else ("edit" if r == "admin" else "view")


def _space(c, lid):
    lr = _lrow(c, lid)
    if lr is None or lr["is_inbox"]:
        return None
    return (lr["org_id"], lr["owner_id"])


def _title(c, lid):
    lr = _lrow(c, lid)
    return lr["name"] if lr else ""


def _protect(c, lid):
    return tr("A project is deleted in its own settings, not with a folder")


def _hidden(c, uid):
    """What a folder share never opens to an agent: health, budget, read later lists and an organisation's trips (the rules of a
    list's share); for people nothing. A read-later project ("Reading") is a list like the others: its node lies in the
    projects tree, a folder shares it with people."""
    if not uid or acx_of(c, uid).role != "agent":
        return ""
    return ("(SELECT l.id FROM lists l WHERE l.life IN ('health','budget') OR (l.life='travel' AND l.org_id IS NOT NULL) OR l.is_inbox=1 OR "
            + reading_sql("l") + ")")  # "Reading" follows the lists (#2742, decision 9): a read-later project, never an agent's


fs_ref_register(LF_KIND, label=N_("Project"), open_url=lambda lid: f"list/{int(lid)}", base_role=_base, space=_space,
                protect=_protect, hidden=_hidden, title=_title)


# ---------------------------------------------------------------- tree <-> path
def lf_root(c, uid, org_id, create=True):
    """The "Projects" root of workspace org_id (None: uid's own tree); None when it cannot be made (Denied)."""
    try:
        with system_ctx(c):
            # 2.409.0 (#3506): the language read on c - tr() alone opens a second connection outside a request, which waits
            # forever for the start's own transaction (the first start on an old database placing its lists hung there)
            return fs_area_root(c, uid, org_id, LF_AREA, tr("Projects", lg=lang(c, uid)), create=create)
    except Denied:
        return None


def _log(c, nid, action, detail=""):
    _busy.on = getattr(_busy, "on", 0) + 1
    try:
        fs_log_add(c, nid, action, detail)
    finally:
        _busy.on -= 1


def _parts(path):
    return [p for p in str(path or "").split("/") if p]


def _child_folder(c, parent, owner, name):
    r = c.execute("""SELECT id FROM fs_nodes WHERE parent_id=? AND kind='folder' AND deleted_at IS NULL AND owner_id=? AND name=?
                     ORDER BY id LIMIT 1""", (parent, owner, name)).fetchone()
    return r[0] if r else None


def _path_node(c, root, owner, org, path, create=True):
    """The folder node of owner's path below root (created when missing; None when missing and not create)."""
    cur = root
    for i, p in enumerate(_parts(path)[:DEPTH_MAX - 2]):
        nm = safe_fs_name(p) or "-"
        x = _child_folder(c, cur, owner, nm)
        if x is None:
            if not create:
                return None
            ts = _now()
            x = insert_id(c, """INSERT INTO fs_nodes(parent_id,kind,name,owner_id,org_id,created_by,created_at,updated_at)
                                VALUES(?,?,?,?,?,?,?,?)""", (cur, "folder", nm, owner, org, owner, ts, ts))
            _log(c, x, "create")
        cur = x
    return cur


def lf_node_path(c, n, chain=None):
    """The folder path of node n (a row) below its projects root (a folder: its own path; a list's node: its folder's) or None
    when it does not lie below one."""
    chain = chain if chain is not None else fs_chain(c, n["id"])
    if not chain or not fs_area_root_of(c, chain[-1]["id"]) or fs_area_root_of(c, chain[-1]["id"])[1] != LF_AREA:
        return None
    names = [x["name"] for x in reversed(chain[:-1])]
    if n["kind"] == "ref":
        names = names[:-1]
    return "/".join(names)


def lf_node_folder(c, nid):
    """(owner, path) of a projects folder node (the key of its folder settings) or None (not one, the root: path '')."""
    with system_ctx(c):
        chain = fs_chain(c, int(nid))
        if not chain or chain[0]["kind"] != "folder" or fs_deleted(chain):  # 2.352.0 F (#2748, review N11): not one in the trash
            return None
        p = lf_node_path(c, chain[0], chain)
    return None if p is None else (chain[0]["owner_id"], p)


def lf_path_arg(c, folder, node):
    """2.352.0 A (#2748): the folder routes of today (settings, agents) take node=<projects folder node id> instead of folder=<path>:
    -> the path of that folder of mine (Denied 404: not a projects folder, not mine); without node: folder as it came."""
    if node in (None, ""):
        return folder
    try:
        k = lf_node_folder(c, int(node))
    except (TypeError, ValueError):
        k = None
    if not k or not k[1] or k[0] != me():
        raise Denied(404)
    return k[1]


def lf_place(c, lid):
    """The list's node where its workspace and path say (module docstring) -> node id | None. Caller commits."""
    with system_ctx(c):
        lr = _lrow(c, lid)
        n = fs_ref_node(c, LF_KIND, lid)
        if lr is None or lr["is_inbox"]:
            if n is not None:
                c.execute("DELETE FROM fs_nodes WHERE id=?", (n["id"],))
            return None
        owner, org = lr["owner_id"], lr["org_id"]
        root = lf_root(c, owner, org)
        if root is None:
            return None
        path = lr["folder"] or ""
        if n is not None and not n["deleted_at"]:
            chain = fs_chain(c, n["id"])
            if chain and chain[-1]["id"] == root and not fs_deleted(chain) and lf_node_path(c, n, chain) == path:
                if n["name"] != (lr["name"] or "")[:200]:
                    c.execute("UPDATE fs_nodes SET name=? WHERE id=?", (safe_fs_name(lr["name"] or "") or "-", n["id"]))
                return n["id"]
        pid = _path_node(c, root, owner, org, path)
        p = c.execute("SELECT owner_id, org_id FROM fs_nodes WHERE id=?", (pid,)).fetchone()
        nm = safe_fs_name(lr["name"] or "") or "-"
        ts = _now()
        if n is None:
            nid = insert_id(c, """INSERT INTO fs_nodes(parent_id,kind,name,owner_id,org_id,ref_kind,ref_id,created_by,created_at,updated_at)
                                  VALUES(?,?,?,?,?,?,?,?,?,?)""", (pid, "ref", nm, p["owner_id"], p["org_id"], LF_KIND, int(lid), owner, ts, ts))
            _log(c, nid, "create")
            return nid
        c.execute("""UPDATE fs_nodes SET parent_id=?, owner_id=?, org_id=?, name=?, sort_no=NULL, deleted_at=NULL, deleted_by=NULL,
                     updated_at=? WHERE id=?""", (pid, p["owner_id"], p["org_id"], nm, ts, n["id"]))
        _log(c, n["id"], "move", str(pid))
        return n["id"]


def lf_lists_below(c, nid):
    """The ids of the lists whose nodes lie below node nid (or nid itself), the trash included."""
    with system_ctx(c):
        rows = c.execute("""WITH RECURSIVE dn(id, lvl) AS (SELECT id, 0 FROM fs_nodes WHERE id=?
                              UNION ALL SELECT n.id, dn.lvl + 1 FROM fs_nodes n JOIN dn ON n.parent_id=dn.id WHERE dn.lvl < 64)
                            SELECT n.ref_id FROM dn JOIN fs_nodes n ON n.id=dn.id WHERE n.kind='ref' AND n.ref_kind=?""",
                         (int(nid), LF_KIND)).fetchall()
    return sorted({r[0] for r in rows})


def lf_roots(c):
    # system_ctx: fs_area_roots is the server's own table of the area roots (no org_id / owner); reading the root ids grants nothing
    with system_ctx(c):
        return [r[0] for r in c.execute("SELECT node_id FROM fs_area_roots WHERE area=?", (LF_AREA,))]


def lf_folder_nodes(c, owner, path):
    """The live folder nodes of owner at path (one per tree that has it)."""
    out = []
    if not _parts(path):
        return out
    with system_ctx(c):
        for root in lf_roots(c):
            r = c.execute("SELECT org_id, owner_id, deleted_at FROM fs_nodes WHERE id=?", (root,)).fetchone()
            if r is None or r["deleted_at"]:
                continue
            x = _path_node(c, root, owner, r["org_id"], path, create=False)
            if x:
                out.append(c.execute("SELECT * FROM fs_nodes WHERE id=?", (x,)).fetchone())
    return out


def lf_folder_ensure(c, owner, path):
    """The folder nodes of owner at path; none yet: one in owner's own tree (a share of an empty folder of today's client)."""
    rows = lf_folder_nodes(c, owner, path)
    if rows or not _parts(path):
        return rows
    with system_ctx(c):
        root = lf_root(c, owner, None)
        if root is None:
            return []
        x = _path_node(c, root, owner, None, path)
        return [c.execute("SELECT * FROM fs_nodes WHERE id=?", (x,)).fetchone()]


def _merge_into(c, src, dst):
    """Folder src goes into folder dst of the same tree: its content and its shares (a share there already keeps the higher
    role), then src goes (an empty folder, its shares moved)."""
    for k in c.execute("SELECT id FROM fs_nodes WHERE parent_id=?", (src,)).fetchall():
        c.execute("UPDATE fs_nodes SET parent_id=?, updated_at=? WHERE id=?", (dst, _now(), k[0]))
        _log(c, k[0], "move", str(dst))  # 2.352.0 F (#2748, review H3): the history of every write
    for s in c.execute("SELECT * FROM fs_shares WHERE node_id=?", (src,)).fetchall():
        key = next((k for k in ("user_id", "group_id", "agent_id") if s[k]), None)
        if key and not c.execute(f"SELECT 1 FROM fs_shares WHERE node_id=? AND {key}=?", (dst, s[key])).fetchone():
            c.execute("UPDATE fs_shares SET node_id=? WHERE id=?", (dst, s["id"]))
            _log(c, dst, "share", f"merged:{s['id']}")
    c.execute("DELETE FROM fs_nodes WHERE id=?", (src,))


def lf_folder_repath(c, owner, old, new):
    """The folder nodes of owner at path old (every tree) become path new: renamed / moved, merged into an existing folder."""
    if not _parts(old) or not _parts(new) or old == new:
        return 0
    n = 0
    with system_ctx(c):
        for f in lf_folder_nodes(c, owner, old):
            chain = fs_chain(c, f["id"])
            root = chain[-1]["id"]
            parent = _path_node(c, root, owner, f["org_id"], "/".join(_parts(new)[:-1]))
            nm = safe_fs_name(_parts(new)[-1]) or "-"
            tgt = _child_folder(c, parent, owner, nm)
            if tgt and tgt != f["id"]:
                _merge_into(c, f["id"], tgt)
                _log(c, tgt, "move", str(parent))
            else:
                c.execute("UPDATE fs_nodes SET parent_id=?, name=?, updated_at=? WHERE id=?", (parent, nm, _now(), f["id"]))
                _log(c, f["id"], "move", str(parent))
            n += 1
    return n


def lf_folder_dissolve(c, owner, path):
    """POST /api/folders/delete: the folder nodes of owner at path go; their content moves one level up (their shares go,
    like the folder's people before)."""
    with system_ctx(c):
        for f in lf_folder_nodes(c, owner, path):
            for k in c.execute("SELECT id, kind FROM fs_nodes WHERE parent_id=?", (f["id"],)).fetchall():
                c.execute("UPDATE fs_nodes SET parent_id=?, updated_at=? WHERE id=?", (f["parent_id"], _now(), k[0]))
                _log(c, k[0], "move", str(f["parent_id"]))  # 2.352.0 F (#2748, review H3)
            c.execute("DELETE FROM fs_nodes WHERE id=?", (f["id"],))


def lf_sync_owner(c, owner):
    """Every list of owner where its path says, and the empty folders of the folder order in owner's own tree. -> the ids of
    the lists whose node was made / moved."""
    n = []
    for r in c.execute("SELECT id FROM lists WHERE owner_id=? AND is_inbox=0", (owner,)).fetchall():
        before = fs_ref_node(c, LF_KIND, r[0])
        nid = lf_place(c, r[0])
        with system_ctx(c):
            now = c.execute("SELECT parent_id, org_id FROM fs_nodes WHERE id=?", (nid,)).fetchone() if nid else None
        if now is not None and (before is None or before["parent_id"] != now["parent_id"] or before["org_id"] != now["org_id"]):
            n.append(r[0])
    try:
        arr = json.loads(usettings(c, owner).get("folders") or "[]")
    except (TypeError, ValueError):
        arr = []
    for p in [x for x in arr if isinstance(x, str) and x]:
        lf_folder_ensure(c, owner, p)
    return n


# ---------------------------------------------------------------- rights through the folders
def _share_rows(c, ids):
    q = ",".join("?" * len(ids))
    return c.execute(f"""SELECT user_id, group_id, agent_id, role, list_role FROM fs_shares WHERE node_id IN ({q})
                         AND (expires_at IS NULL OR expires_at > ?)""", (*ids, _now())).fetchall()


def lf_want(c, lid, lr=None):
    """{uid: list role} the folders of list lid give (module docstring)."""
    from ..family.family import is_kid
    lr = lr if lr is not None else _lrow(c, lid)
    if lr is None or lr["is_inbox"]:
        return {}
    with system_ctx(c):
        n = fs_ref_node(c, LF_KIND, lid)
        if n is None or n["deleted_at"]:
            return {}
        chain = fs_chain(c, n["id"])
        if not chain or fs_deleted(chain) or (n["org_id"] or None) != (lr["org_id"] or None):
            return {}
        rows = _share_rows(c, [x["id"] for x in chain])
        if not rows:
            return {}
        cand = {}
        for s in rows:
            role = s["list_role"] if s["list_role"] in LIST_ROLES else ("edit" if s["role"] == "edit" else "view")
            who = [s["user_id"]] if s["user_id"] else [s["agent_id"]] if s["agent_id"] else \
                [r[0] for r in c.execute("""SELECT m.user_id FROM group_members m JOIN users u ON u.id=m.user_id
                                            WHERE m.group_id=? AND u.kind!='agent'""", (s["group_id"],))]
            for u in who:
                if u and u != lr["owner_id"]:
                    cand[u] = _rmax(cand.get(u), role)
        out = {}
        agents = {r[0] for r in c.execute("SELECT id FROM users WHERE kind='agent' AND disabled=0")}
        for u, role in sorted(cand.items()):
            if not c.execute("SELECT 1 FROM users WHERE id=? AND disabled=0", (u,)).fetchone():
                continue
            x = fs_ref_node_role(c, u, n, chain)  # the file store's rules: organisation boundary, read-only, hidden, expiry
            if x is None:
                continue
            if x == "view" and role in ("admin", "edit"):
                role = "view"
            if u in agents:
                if lr["life"] in ("health", "budget") or (lr["life"] == "travel" and lr["org_id"]) or reading_ids(c, [lid]):
                    continue
                # several agents through folders like in the file store; "the" agent of the list stays the one set on it
                # (core/access.py list_other_agent ignores the folders' agents)
                role = "edit" if role == "admin" else role
            if ws_member_problem(c, lid, u):
                continue
            if is_kid(c, u):
                role = "participant"
            out[u] = role
    return out


def lf_skips(c, lid):
    return {r[0] for r in c.execute("SELECT user_id FROM list_folder_skip WHERE list_id=?", (int(lid),))}


def lf_skip(c, lid, uid, on=True):
    """uid's row in list_folder_skip of list lid set / removed -> True when it changed."""
    if on:
        return c.execute("INSERT INTO list_folder_skip(list_id,user_id,created_at) VALUES(?,?,?) ON CONFLICT DO NOTHING",
                         (int(lid), int(uid), iso(now_utc()))).rowcount > 0
    return c.execute("DELETE FROM list_folder_skip WHERE list_id=? AND user_id=?", (int(lid), int(uid))).rowcount > 0


def lf_resync(c, lids, actor=None):
    """grp_sync for lists lids (their roles through the folders); actor 0 = no person (a background round)."""
    lids = sorted({int(x) for x in lids if x})
    if lids:
        grp_sync(c, lids, actor)


def lf_folder_share(c, owner, path, uid, role):
    """The old route /api/folders/people: owner's folder at path (every tree; none yet: one in owner's own tree) is shared with
    person / agent uid with list role role (None: the share goes). folder_people follows (_people_mirror), the lists below
    get their roles anew. Caller commits."""
    agent = bool(c.execute("SELECT 1 FROM users WHERE id=? AND kind='agent'", (uid,)).fetchone())
    key = "agent_id" if agent else "user_id"
    nodes = lf_folder_ensure(c, owner, path) if role else lf_folder_nodes(c, owner, path)
    lids = set()
    with system_ctx(c):
        for f in nodes:
            old = c.execute(f"SELECT id FROM fs_shares WHERE node_id=? AND {key}=?", (f["id"], uid)).fetchone()
            if role is None:
                if old:
                    c.execute("DELETE FROM fs_shares WHERE id=?", (old[0],))
                    _log(c, f["id"], "unshare", str(old[0]))
            elif old:
                c.execute("UPDATE fs_shares SET role=?, list_role=? WHERE id=?", ("edit" if role in ("admin", "edit") else "view", role, old[0]))
                _log(c, f["id"], "share_change", f"{old[0]}:{role}")
            else:
                c.execute(f"INSERT INTO fs_shares(node_id,{key},role,list_role,created_by,created_at) VALUES(?,?,?,?,?,?)",
                          (f["id"], uid, "edit" if role in ("admin", "edit") else "view", role, owner, _now()))
                _log(c, f["id"], "share", f"{key[:-3]}:{uid}:{role}")
            lids.update(lf_lists_below(c, f["id"]))
    _people_mirror(c, owner, path)
    lf_resync(c, lids)


def _people_mirror(c, owner, path):
    """folder_people of (owner, path) = the person / agent shares of owner's folder nodes at path (the readers of folder_people
    -- notification templates, the lock's checks, the sidebar's marks, older versions -- see the folder's shares)."""
    if not _parts(path):
        return
    want = {}
    with system_ctx(c):
        for f in lf_folder_nodes(c, owner, path):
            for s in c.execute("SELECT user_id, agent_id, role, list_role FROM fs_shares WHERE node_id=? AND group_id IS NULL", (f["id"],)):
                u = s["user_id"] or s["agent_id"]
                if u and u != owner:
                    want[u] = _rmax(want.get(u), s["list_role"] if s["list_role"] in LIST_ROLES else ("edit" if s["role"] == "edit" else "view"))
    have = {r[0]: r[1] for r in c.execute("SELECT user_id, role FROM folder_people WHERE owner_id=? AND folder=?", (owner, path))}
    for u in set(have) - set(want):
        c.execute("DELETE FROM folder_people WHERE owner_id=? AND folder=? AND user_id=?", (owner, path, u))
    for u, r in want.items():
        if have.get(u) != r:
            c.execute("INSERT INTO folder_people(owner_id,folder,user_id,role,created_at) VALUES(?,?,?,?,?) ON CONFLICT(owner_id,folder,user_id) "
                      "DO UPDATE SET role=excluded.role", (owner, path, u, r, iso(now_utc())))


# ---------------------------------------------------------------- hooks of the file store
_CHANGE = {"share", "share_change", "unshare", "trash", "restore", "move", "org_access", "moved_space"}


def _on_change(c, nid, action):
    """files/store.py fs_change_hooks: a share / move / trash in the projects area -> the lists below get their roles anew."""
    if action not in _CHANGE or getattr(_busy, "on", 0):
        return
    with system_ctx(c):
        chain = fs_chain(c, int(nid))
        r = fs_area_root_of(c, chain[-1]["id"]) if chain else None
    if not r or r[1] != LF_AREA:
        return
    _busy.on = getattr(_busy, "on", 0) + 1
    try:
        lids = lf_lists_below(c, nid)
        if action in ("move", "restore", "trash"):
            _paths_follow(c, lids)
        if action in ("share", "share_change", "unshare"):
            k = lf_node_folder(c, nid)
            if k and k[1]:
                _people_mirror(c, *k)
        lf_resync(c, lids)
    finally:
        _busy.on -= 1


def _paths_follow(c, lids):
    """The lists' paths follow their nodes (a node moved in the tree); a member's copy of the owner's folder too."""
    with system_ctx(c):
        for lid in lids:
            n = fs_ref_node(c, LF_KIND, lid)
            lr = _lrow(c, lid)
            if n is None or lr is None:
                continue
            chain = fs_chain(c, n["id"])
            if fs_deleted(chain):
                continue
            p = lf_node_path(c, n, chain)
            if p is None or p == (lr["folder"] or ""):
                continue
            c.execute("UPDATE lists SET folder=? WHERE id=?", (p, lid))
            c.execute("UPDATE list_members SET folder=? WHERE list_id=? AND folder=?", (p, lid, lr["folder"] or ""))


def _before(c, uid, n):
    """Before a node of the area is renamed / moved: a folder's (owner, path)."""
    if n["kind"] != "folder":
        return None
    with system_ctx(c):
        p = lf_node_path(c, n)
    if p and uid != n["owner_id"]:  # 2.352.0 F (#2748, review H3): its path is the owner's (settings, every tree): only the owner
        raise Denied(403, tr("Only the owner of the folder can change it."))
    return {"owner": n["owner_id"], "path": p} if p else None


def _merges(c, owner, old, new, nid):
    """2.352.0 F (#2748, review H3): would moving owner's path old to new (lf_folder_repath) merge a folder of another tree into
    an existing one there (a tree holding both paths; node nid -- the one moved -- not counted)?"""
    with system_ctx(c):
        at_new = {fs_chain(c, f["id"])[-1]["id"] for f in lf_folder_nodes(c, owner, new) if f["id"] != nid}
        return bool(at_new & {fs_chain(c, f["id"])[-1]["id"] for f in lf_folder_nodes(c, owner, old) if f["id"] != nid})


def _after(c, uid, nid, ctx):
    """After: a folder's settings, playbook, colour ... follow its new path (sections.folder_rename_do), the lists' paths
    follow their nodes, the roles are computed anew."""
    _busy.on = getattr(_busy, "on", 0) + 1
    try:
        lids = lf_lists_below(c, nid)
        if ctx and ctx.get("path"):
            with system_ctx(c):
                n = c.execute("SELECT * FROM fs_nodes WHERE id=?", (int(nid),)).fetchone()
                new = lf_node_path(c, n) if n is not None else None
            if new and new != ctx["path"]:
                if _merges(c, ctx["owner"], ctx["path"], new, int(nid)):
                    raise Denied(409, tr("Folder already exists"))  # 2.352.0 F (#2748, review H3): 409, never mixed into another tree's folder
                folder_rename_do(c, ctx["owner"], ctx["path"], new)
        _paths_follow(c, lids)
        lf_resync(c, lids)
    finally:
        _busy.on -= 1


fs_area_rule(LF_AREA, kinds={("folder", None), ("ref", LF_KIND)}, before=_before, after=_after)


def _register_change_hook():
    hooks = getattr(fs_store, "fs_change_hooks", None)
    if hooks is not None and _on_change not in hooks:
        hooks.append(_on_change)


_register_change_hook()


def lf_expire_tick(c):
    """Watchdog: the lists below an expired share of the area that still have folder roles get their roles anew (an expiry is
    no change the hooks see). -> number of lists. The watchdog runs outside the app's context: the access rules need one."""
    if not has_app_context():
        with app.app_context():
            return lf_expire_tick(c)
    now = _now()
    with system_ctx(c):
        rows = c.execute("SELECT DISTINCT node_id FROM fs_shares WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,)).fetchall()
        lids = set()
        for r in rows:
            lids.update(lf_lists_below(c, r[0]))
        if lids:
            q = ",".join(str(int(x)) for x in sorted(lids))
            lids = {r[0] for r in c.execute(f"SELECT DISTINCT list_id FROM list_members WHERE frole IS NOT NULL AND list_id IN ({q})")}
    lf_resync(c, lids, actor=0)
    if lids:
        bump(c)  # 2.352.0 F (#2748, review N1): the clients drop the lists at once
    c.commit()
    return len(lids)


# ---------------------------------------------------------------- the one-way move (core/db.py, once)
def lf_migrate(c):
    """2.352.0 A (#2748): the path folders and their people go into the file store. Idempotent; nothing is deleted
    (folder_people stays readable). -> counts. Caller commits.
    1. every list gets its node where its path says; the empty folders of the folder order get folders (own tree)
    2. every folder_people row becomes a share (list_role = its role) of the owner's folder nodes at that path
    3. a member row the folder gave (its own role = the folder's role) becomes a folder role (own_role NULL, frole); a person
       removed from such a list by hand, or set lower there, gets a list_folder_skip row -- who sees what stays the same
    4. grp_sync of every list (frole of the rows the folders give)."""
    out = {"nodes": 0, "shares": 0, "folder_rows": 0, "skips": 0}
    with system_ctx(c):
        owners = [r[0] for r in c.execute("SELECT DISTINCT owner_id FROM lists WHERE is_inbox=0 ORDER BY owner_id")]
        owners += [r[0] for r in c.execute("SELECT DISTINCT user_id FROM user_settings WHERE key='folders' ORDER BY user_id") if r[0] not in owners]
        for o in owners:
            out["nodes"] += len(lf_sync_owner(c, o))
        agents = {r[0] for r in c.execute("SELECT id FROM users WHERE kind='agent'")}
        for fp in c.execute("SELECT owner_id, folder, user_id, role, created_at FROM folder_people ORDER BY owner_id, folder, user_id").fetchall():
            role = fp["role"] if fp["role"] in LIST_ROLES else "edit"
            key = "agent_id" if fp["user_id"] in agents else "user_id"
            for f in lf_folder_ensure(c, fp["owner_id"], fp["folder"]):
                if c.execute(f"SELECT 1 FROM fs_shares WHERE node_id=? AND {key}=?", (f["id"], fp["user_id"])).fetchone():
                    continue
                c.execute(f"INSERT INTO fs_shares(node_id,{key},role,list_role,created_by,created_at) VALUES(?,?,?,?,?,?)",
                          (f["id"], fp["user_id"], "edit" if role in ("admin", "edit") else "view", role, fp["owner_id"], fp["created_at"] or _now()))
                out["shares"] += 1
        lids = [r[0] for r in c.execute("SELECT id FROM lists WHERE is_inbox=0 ORDER BY id")]
        for lid in lids:
            lr = _lrow(c, lid)
            want = lf_want(c, lid, lr)
            if not want:
                continue
            rows = {r["user_id"]: r for r in c.execute("SELECT * FROM list_members WHERE list_id=?", (lid,))}
            skips = lf_skips(c, lid)
            for u, fr in want.items():
                r = rows.get(u)
                if u in skips:
                    continue
                if r is None:
                    lf_skip(c, lid, u)  # removed by hand before: the folder must not bring them back
                    out["skips"] += 1
                    continue
                if r["frole"] is not None:
                    continue
                own = r["own_role"] if r["own_role"] is not None else (r["role"] if r["grole"] is None else None)
                if own == fr:
                    c.execute("UPDATE list_members SET own_role=NULL, frole=? WHERE list_id=? AND user_id=?", (fr, lid, u))
                    out["folder_rows"] += 1
                elif own is not None and _RANK[own] < _RANK[fr]:
                    lf_skip(c, lid, u)  # set lower by hand: stays so
                    out["skips"] += 1
        grp_sync(c, lids, actor=0)
    return out


# ---------------------------------------------------------------- routes for the client (part E)
def _tree_space(c, uid, org, root):
    """{org_id, root, folders, lists} of one projects tree as uid sees it: the folders uid has a role on (own, shared) and the
    nodes of the lists uid sees; a folder whose parent uid does not see hangs at the root."""
    with system_ctx(c):
        rows = c.execute("""WITH RECURSIVE dn(id, lvl) AS (SELECT id, 0 FROM fs_nodes WHERE id=?
                              UNION ALL SELECT n.id, dn.lvl + 1 FROM fs_nodes n JOIN dn ON n.parent_id=dn.id
                              WHERE dn.lvl < 64 AND n.deleted_at IS NULL)
                            SELECT n.* FROM dn JOIN fs_nodes n ON n.id=dn.id WHERE dn.lvl > 0 ORDER BY dn.lvl, n.sort_no, lower(n.name), n.id""",
                         (root,)).fetchall()
    seen = {root}
    folders, lists = [], []
    vis_lists = {r[0] for r in c.execute("SELECT id FROM lists WHERE owner_id=? UNION SELECT list_id FROM list_members WHERE user_id=?",
                                         (uid, uid))}
    byid = {r["id"]: r for r in rows}

    def up(pid):
        while pid and pid not in seen:
            pid = byid[pid]["parent_id"] if pid in byid else None
        return pid or root
    shared = {r[0] for r in c.execute(f"SELECT DISTINCT node_id FROM fs_shares WHERE node_id IN ({','.join(str(int(x)) for x in byid) or '0'})")}
    for r in rows:
        if r["kind"] == "folder":
            if r["owner_id"] == uid or fs_role(c, r["id"], uid):
                seen.add(r["id"])
                folders.append({"id": r["id"], "parent_id": up(r["parent_id"]), "name": r["name"], "sort_no": r["sort_no"],
                                "path": lf_node_path(c, r), "owner_id": r["owner_id"], "mine": r["owner_id"] == uid,
                                "shared": r["id"] in shared})
        elif r["kind"] == "ref" and r["ref_kind"] == LF_KIND and (r["ref_id"] in vis_lists or fs_ref_role(c, uid, LF_KIND, r["ref_id"])):
            lists.append({"list_id": r["ref_id"], "node_id": r["id"], "parent_id": up(r["parent_id"])})
    return {"org_id": org, "root": root, "folders": folders, "lists": lists}


@app.get("/api/lists/tree")
def lf_tree_get():
    """The projects trees of my workspaces (own tree + each organisation of mine): {spaces: [{org_id, root, folders: [{id,
    parent_id, name, sort_no, path, owner_id, mine, shared}], lists: [{list_id, node_id, parent_id}]}]}. parent_id = root:
    the top level. My lists are placed first (lf_sync_owner)."""
    c = db()
    uid = me()
    if acx_of(c, uid).role == "agent":
        raise Denied(403)
    lf_sync_owner(c, uid)
    out = []
    for org in [None] + sorted({int(o["id"] if isinstance(o, dict) else o) for o in (user_orgs(c, uid) or [])}):
        root = lf_root(c, uid, org, create=org is None)
        if root:
            out.append(_tree_space(c, uid, org, root))
    c.commit()  # the nodes placed / the own root made on the way
    return jsonify(spaces=out)


def _need_folder(c, uid, nid):
    """A projects folder (or root) uid may add to ('edit'; the root of a workspace: who may add projects there)."""
    with system_ctx(c):
        chain = fs_chain(c, int(nid))
    if not chain or fs_deleted(chain) or chain[0]["kind"] != "folder":
        raise Denied(404)
    r = fs_area_root_of(c, chain[-1]["id"])
    if not r or r[1] != LF_AREA:
        raise Denied(404)
    if len(chain) == 1:  # the root: my own tree / an organisation I may write in
        org = chain[0]["org_id"]
        if org:
            if not org_writes(c, uid, org) or org_role_key(c, uid, org) not in FULL_WRITE:  # 2.352.0 F (#2748, review N9): members only
                raise Denied(403)
        elif chain[0]["owner_id"] != uid:
            raise Denied(404)
        return chain
    role = fs_role(c, chain[0]["id"], uid, chain=chain)
    if not role:
        raise Denied(404)
    if role == "view":
        raise Denied(403)
    if len(chain) >= DEPTH_MAX - 1:
        raise Denied(409, tr("Folders can be nested at most {0} levels deep", DEPTH_MAX - 1))
    return chain


@app.post("/api/lists/folders")
def lf_folder_new():
    """{parent_id (a projects folder or root), name}: a new folder of mine there -> 201 {id, path}."""
    c, b = db(), body()
    uid = me()
    if acx_of(c, uid).role == "agent":
        raise Denied(403)
    try:
        pid = int(b.get("parent_id"))
    except (TypeError, ValueError):
        return err(tr("Invalid value: {0}", "parent_id"))
    nm = safe_fs_name(str(b.get("name") or "").replace("/", " ").strip())
    if not nm:
        return err(tr("Name missing"))
    chain = _need_folder(c, uid, pid)
    # 2.352.0 F (#2748, review M2): a subfolder belongs to the owner of its folder (like the file store), at the root to me
    owner = chain[0]["owner_id"] if len(chain) > 1 else uid
    with system_ctx(c):
        x = _child_folder(c, pid, owner, nm)
        if x is None:
            ts = _now()
            x = insert_id(c, """INSERT INTO fs_nodes(parent_id,kind,name,owner_id,org_id,created_by,created_at,updated_at)
                                VALUES(?,?,?,?,?,?,?,?)""", (pid, "folder", nm, owner, chain[0]["org_id"], uid, ts, ts))
            _log(c, x, "create")
        n = c.execute("SELECT * FROM fs_nodes WHERE id=?", (x,)).fetchone()
        path = lf_node_path(c, n)
    if n["owner_id"] == uid and path:  # today's client: the folder in my folder order
        try:
            arr = json.loads(usettings(c, uid).get("folders") or "[]")
        except (TypeError, ValueError):
            arr = []
        if path not in arr:
            uset(c, uid, "folders", json.dumps(arr + [path], ensure_ascii=False))
    bump(c)
    c.commit()
    return jsonify(id=x, path=path), 201


@app.post("/api/lists/tree/move")
def lf_tree_move():
    """{node_id (a projects folder or list node), parent_id (a projects folder or root of the same tree)}: moves it. A list
    needs 'edit' on it from the list itself (its owner / an admin), a folder 'edit' on it and on every list in it (the
    folder's shares go along); the target needs 'edit'. Paths, folder settings and roles follow. -> {ok, path}"""
    c, b = db(), body()
    uid = me()
    if acx_of(c, uid).role == "agent":
        raise Denied(403)
    try:
        nid, pid = int(b.get("node_id")), int(b.get("parent_id"))
    except (TypeError, ValueError):
        return err(tr("Invalid value: {0}", "node_id"))
    # system_ctx: the node may lie in another person's tree (shared folder); access is checked right below (404 / 403)
    with system_ctx(c):
        n = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
        nchain = fs_chain(c, nid) if n is not None else []
    if n is None or fs_deleted(nchain) or len(nchain) < 2 or not fs_area_root_of(c, nchain[-1]["id"]) \
            or fs_area_root_of(c, nchain[-1]["id"])[1] != LF_AREA:
        raise Denied(404)
    pchain = _need_folder(c, uid, pid)
    if pchain[-1]["id"] != nchain[-1]["id"]:
        raise Denied(409, tr("Files can only be moved within the same space"))
    if any(x["id"] == nid for x in pchain):
        return err(tr("A folder cannot go into itself"))
    if n["kind"] == "ref":
        if not fs_ref_may_file(c, uid, LF_KIND, n["ref_id"]):
            raise Denied(403)
        if n["parent_id"] != pid and len(nchain) > 2 and (fs_role(c, n["parent_id"], uid) or "view") == "view":
            raise Denied(403)  # 2.352.0 F (#2748, review M1): taking it out of a folder takes the folder's shares away (fs_ref_place)
    else:
        if (fs_role(c, nid, uid, chain=nchain) or "view") == "view":
            raise Denied(403)
        fs_ref_need_move(c, uid, n)
    if len(pchain) + 1 + fs_height(c, nid) > DEPTH_MAX:  # 2.352.0 F (#2748, review M1): like the file store's move
        raise Denied(409, tr("Folders can be nested at most {0} levels deep", DEPTH_MAX))
    ctx = _before(c, uid, n)
    with system_ctx(c):
        if n["parent_id"] != pid:
            c.execute("UPDATE fs_nodes SET parent_id=?, sort_no=NULL, updated_at=? WHERE id=?", (pid, _now(), nid))
            _log(c, nid, "move", str(pid))
    _after(c, uid, nid, ctx)
    # system_ctx: the path runs through folders of the tree's owner that this person may not see by RLS (checked above)
    with system_ctx(c):
        path = lf_node_path(c, c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone())
    bump(c)
    c.commit()
    return jsonify(ok=True, path=path)
