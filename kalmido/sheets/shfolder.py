"""2.199.0 C (#2742): tables in folders -- the reference kind 'sheet' of the folder system (files/fsref.py) and the folder tree
of the tables' panel.

A table (its first sheet, book_id NULL; the further sheets follow it) can lie in ONE folder of its workspace's file store tree:
a reference node (kind 'ref', ref_kind 'sheet'). The tables' folders live below the area root "Tables" of the workspace
(files/fsroots.py, area 'sheets'), created on the first folder; a table gets its node only when it is put into a folder (none
for the existing ones). Like the file store's top level, a folder an organisation's person adds at the top of the tables is
theirs (owner_id = theirs, below the root; the root itself is the organisation admins'): nobody else sees it until it is
shared (people, groups, the whole organisation, agents). So a folder never opens a table to the whole organisation unless its
owner chose "every member".

Rights: sh_may (sheets/core.py) = the table's own right (space, project, sheet_shares) OR the role its folder gives
(fs_ref_node_role: folder shares with people / groups, agents only through a share with exactly them; since 2.199.0 F
not organisation access nor the folder's ownership);
the higher one counts. Taking the table out of the folder or revoking the share takes it away. A folder never makes anybody
the table's owner: deleting, restoring, attaching it to a project, moving it, managing its sheet_shares stay with who may
write it through its space / project (shs_need_own, share=False never asks the folder).
- hidden (agents only, like sheet_shares): a table of a project with a lock, a health / budget project or outside the agent's
  list limit is never opened by a folder; its node is left out of the agent's listings. A person: a folder share opens a
  project's table like a sheet share does (filing it needs the right to write it).
- protect: a folder going into the trash takes its tables into the tables' trash (on_trash) -- a table whose deleting is not
  the deleting person's (only who may write it through its space / project) moves one level up instead.
- A deleted table (in its trash) gives nothing through its node (space None); moving the table to another workspace or
  deleting it for good removes its node (shmove / trash purge).
"""
from flask import g, has_request_context, jsonify, request

from ..core.config import app
from ..core.access import health_hidden, need_feat, token_lists
from ..core.db import body, bump, db, insert_id, iso_ms, now_utc
from ..core.errors import BadInput, Denied
from ..core.i18n import N_, lang, tr
from ..accounts.orgroles import org_writes, user_orgs_full
from ..accounts.orgs import user_orgs
from ..accounts.session import me
from ..files.fsref import fs_ref_all_sql, fs_ref_drop, fs_ref_node, fs_ref_node_role, fs_ref_register, fs_ref_token_lacks
from ..files.fsroots import fs_area_folder_name, fs_area_root
from ..files.store import _now, _place, fs_chain, fs_log_add, fs_role, fs_visible_sql, safe_fs_name
from .core import sh_is_agent, sh_may, sh_space, sh_touch
from .shbook import shb_rights_row
from .vars import _agent_cap

SHF_KIND = "sheet"
SHF_AREA = "sheets"
SHF_ONLY_OWN = N_("Only who may change the table through its workspace can delete it")


def _row(c, rid):
    """The table (its first sheet) or None."""
    return c.execute("SELECT * FROM sheets WHERE id=? AND book_id IS NULL", (int(rid),)).fetchone()


def _base(c, uid, rid):
    r = _row(c, rid)
    if r is None:
        return None
    # 2.199.0 (#2742, Fable review): only the space / project right counts here -- a sheet share must not be passed on through a folder
    if sh_may(c, uid, r, write=True, share=False, fold=False):
        return "edit"
    return "view" if sh_may(c, uid, r, share=False, fold=False) else None


def _space(c, rid):
    r = _row(c, rid)
    if r is None or r["deleted_at"]:
        return None
    return (r["org_id"], r["owner_id"])


def _protect(c, rid):
    if not has_request_context():
        return None
    r = _row(c, rid)
    if r is None or r["deleted_at"]:
        return None
    if sh_may(c, me(), r, write=True, share=False):
        return None
    return tr(SHF_ONLY_OWN)


def _on_trash(c, uid, rid, restore):
    """2.199.0 F (#2742, review G3): a folder's trash takes the table into the tables' trash and notes it on the node (fs_log
    'trash', detail "area:<deleted_at>"); coming back it restores only a table that this mark still names (not one its
    owner deleted on their own before or after) and only for who may write it through its space / project -- 2.373.0 (#3335):
    without that right "stays" (the folder's restore tells the person: the table stays in the tables' trash)."""
    r = _row(c, rid)
    if r is None or bool(r["deleted_at"]) != bool(restore):
        return
    n = fs_ref_node(c, SHF_KIND, r["id"])
    if restore:
        m = c.execute("SELECT detail FROM fs_log WHERE node_id=? AND action='trash' AND detail ILIKE 'area:%' ORDER BY id DESC LIMIT 1",
                      (n["id"],)).fetchone() if n is not None else None
        if not m or m[0] != f"area:{r['deleted_at']}":
            return
        if not sh_may(c, uid, r, write=True, share=False):
            return "stays"
        c.execute("UPDATE sheets SET deleted_at=NULL WHERE id=?", (r["id"],))
    else:
        ts = iso_ms(now_utc())
        c.execute("UPDATE sheets SET deleted_at=? WHERE id=?", (ts, r["id"]))
        if n is not None:
            fs_log_add(c, n["id"], "trash", f"area:{ts}")
    sh_touch(c, r["id"], uid)


def _hidden(c, uid):
    """Agents only (like sheet_shares, shshare.py shs_fits): the tables of a project with a lock, a health / budget project or
    outside the agent's list limit. A person: none (a folder share opens a project's table like a sheet share does) --
    2.199.0 F (#2742, review G5): through an API token the token's limits (its lists, health only with the scope private,
    no locked project)."""
    agent = sh_is_agent(c, uid)
    tok = (not agent and has_request_context() and g.get("auth_via") == "token" and getattr(g, "user", None) is not None
           and g.user["id"] == uid)  # 2.199.0 F (#2742, review G5): a person's API token keeps its limits on the folder way too
    if not agent and not tok:
        return ""
    if fs_ref_token_lacks(uid, "sheets:read"):
        return fs_ref_all_sql(SHF_KIND)  # 2.238.0 A (#2863): a token without sheets:read reaches no table through a folder
    key = ("shf_hidden", int(uid))
    if has_request_context() and key in g.setdefault("shf_cache", {}):
        return g.shf_cache[key]
    cap = _agent_cap(c, uid) if agent else token_lists()
    life = ("health", "budget") if agent else (("health",) if health_hidden(c, uid) else ())
    bad = []
    for l in c.execute("SELECT id, life, e2e FROM lists WHERE id IN (SELECT DISTINCT list_id FROM sheets WHERE list_id IS NOT NULL "
                       "AND book_id IS NULL)").fetchall():
        if l["e2e"] is not None or (l["life"] or "") in life or (cap is not None and l["id"] not in cap):
            bad.append(l["id"])
    out = f"(SELECT id FROM sheets WHERE list_id IN ({','.join(str(int(x)) for x in bad)}))" if bad else ""
    if has_request_context():
        g.shf_cache[key] = out
    return out


def _title(c, rid):
    r = _row(c, rid)
    return r["title"] if r else ""


def _content(c, uid, rid):
    """The table's values as CSV (evaluated for the asker, like /api/sheets/<id>/export.csv): an agent reads a filed table
    through the file store's content route too."""
    r = _row(c, rid)
    if r is None or r["deleted_at"]:
        return None
    from .io import shx_csv, shx_file_name  # a later module (ORDER)
    return shx_csv(c, r).encode("utf-8"), shx_file_name(r["title"], "csv"), "text/csv"


def _gate(c, uid, rid):
    """2.238.0 A (#2863): the file store's content routes read a table only with the token's sheets:read, like
    /api/v1/sheets."""
    if fs_ref_token_lacks(uid, "sheets:read"):
        raise Denied(403, tr("This token lacks the permission “{0}”", "sheets:read"))


fs_ref_register(SHF_KIND, label=N_("Table"), open_url=lambda rid: f"sheets/{int(rid)}", base_role=_base, space=_space,
                protect=_protect, hidden=_hidden, on_trash=_on_trash, title=_title, content=_content, content_gate=_gate)


def shf_pchain(c, pid):
    """2.351.0 A (#2823): the chain of folder pid, read once per GET request (the tables' index asks it per table and per
    folder: N+1 statements with many folders); a writing request reads it fresh (a move in between)."""
    if not pid or not has_request_context() or request.method != "GET":
        return fs_chain(c, pid) if pid else []
    cache = g.setdefault("shf_chains", {})
    if pid not in cache:
        cache[pid] = fs_chain(c, pid)
    return cache[pid]


def shf_folder_may(c, uid, r, write=False):
    """sh_may's hook: does the folder of r's table give uid the right to read (write: change) it?"""
    rr = shb_rights_row(c, r)
    if rr is None:
        return False
    n = fs_ref_node(c, SHF_KIND, rr["id"])
    if n is None or n["deleted_at"]:
        return False
    role = fs_ref_node_role(c, uid, n, chain=[n] + shf_pchain(c, n["parent_id"]))
    return role == "edit" or (role == "view" and not write)


def shf_root(c, uid, org_id, create=False):
    """The tables' root folder of workspace org_id (None: uid's own tree); create: make it (needs the right to add at the top)."""
    return fs_area_root(c, uid, org_id, SHF_AREA, tr("Tables", lg=lang(c, uid)), create=create)


def shf_reached_ids(c, uid):
    """Ids of the tables (first sheets, not in the trash) whose node lies in a folder uid sees."""
    if not c.execute("SELECT 1 FROM fs_nodes WHERE kind='ref' AND ref_kind='sheet' AND deleted_at IS NULL LIMIT 1").fetchone():
        return []  # no table in any folder (yet): no tree walk per index
    return [r[0] for r in c.execute(f"SELECT n.ref_id FROM fs_nodes n JOIN sheets s ON s.id=n.ref_id WHERE n.kind='ref' AND "
                                    f"n.ref_kind='sheet' AND n.deleted_at IS NULL AND s.deleted_at IS NULL AND s.book_id IS NULL "
                                    f"AND n.id IN {fs_visible_sql(uid, c)}").fetchall()]


def shf_index(c, uid, space, rows):
    """sh_index's hook: + the tables a folder opens to uid (space "all" / "shared"; an organisation: its tables)."""
    ids = shf_reached_ids(c, uid)
    have = {r["id"] for r in rows}
    ids = [i for i in ids if i not in have]
    if not ids:
        return rows
    more = c.execute(f"SELECT * FROM sheets WHERE id IN ({','.join(str(int(i)) for i in ids)}) ORDER BY lower(title), id").fetchall()
    if space in (None, "", "all"):
        return rows + list(more)
    if space == "shared":
        return rows + [r for r in more if not sh_may(c, uid, r, share=False)]
    if space == "private":
        return rows + [r for r in more if r["org_id"] is None and r["owner_id"] == uid]
    if isinstance(space, str) and space.startswith("org:"):
        try:
            oid = int(space[4:])
        except ValueError:
            return rows
        return rows + [r for r in more if r["org_id"] == oid]
    return rows


def shf_marks(c, uid, rows, out):
    """sh_brief's hook: folder_id = the folder the table lies in (null: none / in the trash), fnode / fsort = its node and
    place sorted by hand; shared_in also for a table uid
    reaches only through a folder (share_role then = read | write)."""
    ids = [r["id"] for r in rows]
    nodes = {}
    if ids:
        for n in c.execute(f"SELECT * FROM fs_nodes WHERE kind='ref' AND ref_kind='sheet' AND deleted_at IS NULL AND ref_id IN "
                           f"({','.join(str(int(i)) for i in ids)})").fetchall():
            nodes[n["ref_id"]] = n
    seen = {}  # 2.306.0 D3 (#2875): folder -> may uid see it (fs_role), asked once per folder

    def _sees(pid):
        if pid not in seen:
            seen[pid] = bool(fs_role(c, pid, uid, chain=shf_pchain(c, pid) or None))
        return seen[pid]
    for r, d in zip(rows, out):
        n = nodes.get(r["id"])
        if n is not None and not _sees(n["parent_id"]):
            n = None  # 2.306.0 D3 (#2875): folder / node only for who sees the folder
        d["folder_id"] = n["parent_id"] if n is not None else None
        d["fnode"], d["fsort"] = (n["id"], n["sort_no"]) if n is not None else (None, None)  # its node (sorting by hand)
        if n is not None and not d.get("shared_in") and not sh_may(c, uid, r, fold=False):
            role = fs_ref_node_role(c, uid, n, chain=[n] + shf_pchain(c, n["parent_id"]))
            if role:
                d["shared_in"], d["share_role"], d["folder_in"] = True, "write" if role == "edit" else "read", True
    return out


def shf_after_move(c, sid):
    """The table moved to another workspace: its node (in the old workspace's tree) goes."""
    fs_ref_drop(c, SHF_KIND, sid)


# ---------------------------------------------------------------- the panel's folder tree
def _spaces(c, uid):
    """The workspaces of uid's tables: "private" and the organisations whose tables uid sees (like sh_index)."""
    full = user_orgs_full(c, uid)
    return [(None, "private")] + [(o, f"org:{int(o)}") for o in user_orgs(c, uid) if o in full]


def _below(c, root):
    """The folders below root (not in the trash), parents first."""
    return c.execute("""WITH RECURSIVE t(id, depth) AS (SELECT id, 0 FROM fs_nodes WHERE id=?
                          UNION ALL SELECT n.id, t.depth + 1 FROM fs_nodes n JOIN t ON n.parent_id=t.id
                          WHERE n.kind='folder' AND n.deleted_at IS NULL AND t.depth < 32)
                        SELECT n.* FROM fs_nodes n JOIN t ON t.id=n.id WHERE n.id<>? ORDER BY t.depth, n.id LIMIT 2000""",
                     (int(root), int(root))).fetchall()


@app.get("/api/sheets/folders")
def sheets_folders():
    """The tables' folders per workspace: {spaces: [{space, root (null: none yet), can_add (a folder at the top)}], folders:
    [{id, parent_id, name, sort_no, role (owner | edit | view), shared, space}]} -- only the folders uid sees (a folder at the
    top has parent_id = root; a table in a folder: sheets_index folder_id)."""
    need_feat("sheets")  # 2.199.0 F (#2742, review G6)
    c = db()
    uid = me()
    spaces, folders = [], []
    for oid, key in _spaces(c, uid):
        root = shf_root(c, uid, oid)
        spaces.append({"space": key, "root": root, "can_add": oid is None or bool(org_writes(c, uid, oid))})
        if not root:
            continue
        rows = _below(c, root)
        shared = set()
        if rows:
            q = ",".join(str(int(r["id"])) for r in rows)
            shared = {x[0] for x in c.execute(f"SELECT DISTINCT node_id FROM fs_shares WHERE node_id IN ({q})")}
        for r in rows:
            role = fs_role(c, r["id"], uid)
            if not role:
                continue
            folders.append({"id": r["id"], "parent_id": r["parent_id"], "name": r["name"], "sort_no": r["sort_no"],
                            "role": role, "shared": r["id"] in shared, "space": key})
    return jsonify(spaces=spaces, folders=folders)


@app.post("/api/sheets/folders")
def sheets_folder_new():
    """{space, parent_id?, name} -> {folder}: a folder of the tables -- below parent_id, else at the top of the workspace's
    tables (its root folder "Tables" is made on the first one). Needs the right to add there (like the file store)."""
    need_feat("sheets")
    c = db()
    uid = me()
    b = body()
    raw = str(b.get("name") or "").strip()
    if not raw:
        raise BadInput(tr("Name missing"))
    pid = b.get("parent_id")
    if pid is not None:
        if isinstance(pid, bool) or not isinstance(pid, int):
            raise BadInput(tr("Invalid value: {0}", "parent_id"))
        owner, org = _place(c, uid, pid, None)
    else:  # at the top: below the root, but the person's own (like a folder at the top of the file store)
        oid = sh_space(c, uid, b.get("space"))
        owner, org = _place(c, uid, None, oid)
        pid = shf_root(c, uid, oid, create=True)
    ts = _now()
    nid = insert_id(c, "INSERT INTO fs_nodes(parent_id,kind,name,owner_id,org_id,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (pid, "folder", fs_area_folder_name(c, pid, owner, org, safe_fs_name(raw)), owner, org, uid, ts, ts))  # 2.200.0 A (#2747, review 6)
    fs_log_add(c, nid, "create")
    bump(c)
    c.commit()
    r = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    role = fs_role(c, nid, uid)
    return jsonify(folder={"id": nid, "parent_id": pid, "name": r["name"], "sort_no": None, "role": role,
                           "shared": False, "space": f"org:{int(org)}" if org else "private"}), 201
