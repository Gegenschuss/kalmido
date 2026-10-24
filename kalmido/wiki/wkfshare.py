"""2.200.0 B (#2747): knowledge pages for people who reach them only through a share of their folder / page node (a guest or the
accounting person of an organisation, another person's private pages) -- "Shared with me" in the pages view.

The shares themselves are the file store's (fs_shares on a folder or a page node of a knowledge tree, the one Share dialog
static/js/fsshare.js; who may share: wkfolder.py _share). Their rights apply at run time through the chain (wkfolder.py
wkf_role / wkf_shared): revoking the share or moving the page out of the shared folder takes the page away at once.
- wkfs_rows(c, uid) -> (rows, info): the page rows (wiki_pages.*) uid reaches only through such shares -- not the pages
  uid reads through the space anyway (wkf_base) -- and {page id: {"folder", "top", "node"}} (wkfolder.py wkf_shared).
- wkfs_folders(c, uid): the shared folders and the folders below them [{id, parent_id (null: a shared folder itself), name,
  path (from the shared folder's name), role, space, owner_name}] -- where uid may add pages / folders with 'edit'.
- POST /api/wiki/shared/pages {folder_id, name, body?} -> 201 the page: a new page IN a shared folder uid may edit; it
  belongs to the folder's space (org_id / owner_id of the tree, created_by = uid), its path = the folder path + name.
- POST /api/wiki/shared/folders {parent_id, name} -> 201 {folder}: a folder below a shared folder uid may edit.
The listing and the read-only dialog are wkshare.py's (/api/wiki/shared, /api/wiki/shared/pages/<id>): they add these rows.
Agents never use these routes (their way is the agents API, part C)."""
from flask import jsonify

from ..core.config import app
from ..core.access import Denied, acx_of
from ..core.db import body, bump, db, insert_id, iso_ms, now_utc
from ..core.errors import BadInput
from ..core.i18n import tr
from ..accounts.orgroles import org_sees_all
from ..accounts.session import me
from ..collab.comments import user_names
from ..files.store import ROLE_RANK, _now, fs_chain, fs_deleted, fs_log_add, fs_role
from .pages import WIKI_DEPTH, wiki_body, wiki_clean_path, wiki_dict, wiki_insert, wiki_space_key, wiki_taken
from .wkfolder import (WKF_KIND, _new_folder, _root_of_chain, _share_starts, _space_locked, _subtree, _walk, wkf_base,
                       wkf_folder_path, wkf_name, wkf_shared, wkf_shown_path)


def _own_space(c, uid, org_id, owner_id):
    """Does uid read the space anyway (their private one, an organisation that shows them all its content)?"""
    if org_id:
        return org_sees_all(c, uid, org_id)
    return owner_id == uid


def wkfs_rows(c, uid):
    """(page rows, {page id: info}) -- the pages uid reaches only through folder / page shares (module docstring)."""
    if not uid or acx_of(c, uid).role == "agent":
        return [], {}
    info = wkf_shared(c, uid)
    if not info:
        return [], {}
    q = ",".join(str(int(x)) for x in info)
    rows = [r for r in c.execute(f"SELECT * FROM wiki_pages WHERE id IN ({q}) AND deleted_at IS NULL ORDER BY lower(path)")
            if wkf_base(c, uid, r) is None]
    return rows, {r["id"]: info[r["id"]] for r in rows}


def _folder_role(c, uid, nid, chain):
    r = fs_role(c, nid, uid, chain=chain)
    return "edit" if r == "owner" else r


def wkfs_folders(c, uid):
    """The shared folders and the folders below them (module docstring)."""
    if not uid or acx_of(c, uid).role == "agent":
        return []
    starts = _share_starts(c, uid)
    ids = {n["id"] for n, _ in starts}
    out, owners = [], set()
    for n, chain in starts:
        if n["kind"] != "folder" or any(x["id"] in ids for x in chain[1:]):
            continue
        top = chain[-1]
        if _own_space(c, uid, top["org_id"], None if top["org_id"] else top["owner_id"]):
            continue
        role = _folder_role(c, uid, n["id"], chain)
        if not role:
            continue
        sp = wiki_space_key(top["org_id"]) if top["org_id"] else wiki_space_key(None)
        owners.add(top["owner_id"])
        out.append({"id": n["id"], "parent_id": None, "name": n["name"], "path": n["name"], "role": role, "space": sp,
                    "owner_id": None if top["org_id"] else top["owner_id"]})
        rows = _subtree(c, n["id"])
        fp = _walk(rows, n["id"])
        for r in rows:
            if r["id"] == n["id"] or r["kind"] != "folder" or r["id"] not in fp or fp[r["id"]][1]:
                continue
            out.append({"id": r["id"], "parent_id": r["parent_id"], "name": r["name"], "path": n["name"] + "/" + fp[r["id"]][0],
                        "role": role, "space": sp, "owner_id": None if top["org_id"] else top["owner_id"]})
    names = user_names(c, {o for o in owners if o})
    for f in out:
        o = f.pop("owner_id")
        f["owner_name"] = names.get(o, "") if o else ""
    return out


def _need_folder(c, uid, nid):
    """(folder chain, org id, owner) of a knowledge folder uid may add to through a share ('edit'); 404 / 403 / 409."""
    if acx_of(c, uid).role == "agent":
        raise Denied(403)
    if isinstance(nid, bool) or not isinstance(nid, int):
        raise BadInput(tr("Invalid value: {0}", "folder_id"))
    chain = fs_chain(c, nid)
    if not chain or chain[0]["kind"] != "folder" or fs_deleted(chain) or _root_of_chain(c, chain) is None:
        raise Denied(404)
    role = _folder_role(c, uid, nid, chain)
    if not role:
        raise Denied(404)
    if ROLE_RANK[role] < ROLE_RANK["edit"]:
        raise Denied(403)
    top = chain[-1]
    oid, owner = (top["org_id"] or None), (None if top["org_id"] else top["owner_id"])
    if _space_locked(c, oid, owner):
        raise Denied(409, tr("This space is end-to-end encrypted: its folders come from the page names"))
    return chain, oid, owner


@app.post("/api/wiki/shared/pages")
def wkfs_page_new():
    """{folder_id, name, body?} -> 201 the page (module docstring). 409: the name is taken in the space, too deep."""
    c = db()
    uid = me()
    b = body()
    chain, oid, owner = _need_folder(c, uid, b.get("folder_id"))
    name = wkf_name(c, None, b.get("name"))
    folder = wkf_folder_path(c, chain[0]["id"]) or ""
    path = f"{folder}/{name}" if folder else name
    if len(path.split("/")) > WIKI_DEPTH:
        raise Denied(409, tr("Too many folder levels (at most {0})", WIKI_DEPTH))
    if wiki_clean_path(path) != path:
        raise BadInput(tr("Invalid value: {0}", "name"))
    ts = iso_ms(now_utc())
    pid = wiki_insert(c, oid, owner or uid, path, wiki_body(b), ts)  # the space's page: a private one is its owner's
    if pid is None:
        return wiki_taken()
    if owner and owner != uid:
        c.execute("UPDATE wiki_pages SET created_by=?, updated_by=? WHERE id=?", (uid, uid, pid))
    p = chain[0]
    t = _now()
    nid = insert_id(c, """INSERT INTO fs_nodes(parent_id,kind,name,owner_id,org_id,ref_kind,ref_id,created_by,created_at,updated_at)
                          VALUES(?,?,?,?,?,?,?,?,?,?)""", (p["id"], "ref", name, p["owner_id"], p["org_id"], WKF_KIND, pid, uid, t, t))
    fs_log_add(c, nid, "create")
    bump(c)
    c.commit()
    r = c.execute("SELECT * FROM wiki_pages WHERE id=?", (pid,)).fetchone()
    d = wiki_dict(r, names=user_names(c, [uid]))
    d["node_id"], d["folder_id"], d["role"] = nid, p["id"], "edit"
    d["path"] = wkf_shown_path(c, uid, r)  # 2.200.0 (#2747, review): from the shared folder down, nothing above it
    return jsonify(d), 201


@app.post("/api/wiki/shared/folders")
def wkfs_folder_new():
    """{parent_id, name} -> 201 {folder: {id, parent_id, name, path}} (module docstring). 409: a folder of that name (case
    ignored) in the same place, too deep."""
    c = db()
    uid = me()
    b = body()
    chain, _oid, _owner = _need_folder(c, uid, b.get("parent_id"))
    name = wkf_name(c, None, b.get("name"))
    path = wkf_folder_path(c, chain[0]["id"]) or ""
    if (len(path.split("/")) if path else 0) + 2 > WIKI_DEPTH:  # the new folder + a page in it
        raise Denied(409, tr("Too many folder levels (at most {0})", WIKI_DEPTH))
    if c.execute("SELECT 1 FROM fs_nodes WHERE parent_id=? AND kind='folder' AND lower(name)=lower(?) AND deleted_at IS NULL",
                 (chain[0]["id"], name)).fetchone():
        raise Denied(409, tr("A folder with this name already exists"))
    nid = _new_folder(c, uid, chain[0], name)
    bump(c)
    c.commit()
    return jsonify(folder={"id": nid, "parent_id": chain[0]["id"], "name": name, "path": f"{path}/{name}" if path else name}), 201
