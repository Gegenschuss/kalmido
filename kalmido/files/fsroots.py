"""2.199.0 C (#2742): the root folder of an area in a workspace's file store tree -- e.g. "Tables" at the top of an
organisation's tree (or a person's own tree) holds the folders of the sheets area. The area's folders and reference nodes
(files/fsref.py) lie below it; the area's panel shows that subtree.

fs_area_roots keeps one row per (ws, area): ws = 'o<org id>' | 'u<person id>' (like docs/store.py doc_ws), node_id = the
folder. The folder is an ordinary folder of the file store (2.198 shows it as such): renaming or moving it keeps the mark;
a folder in the trash (itself or above), purged, moved into another workspace or not at the top any more counts as missing
-- the next fs_area_root(create=True) makes a new one (the old one stays an ordinary folder / goes with its trash).

Interface (2.199 sheets; 2.200 / 2.201 knowledge and projects may use it):
  fs_area_root(c, uid, org_id, area, name, create=True, org_access="") -> node id | None
      org_id     the workspace (None: uid's own tree)
      area       the area's key ([a-z][a-z0-9_]*, at most 20 characters), e.g. 'sheets'
      name       the folder's name when it is created (translated by the caller, e.g. tr("Tables"))
      create     False: only look it up (None when missing)
      org_access an organisation's new root folder: '' | 'view' | 'edit' for every person of the organisation (files/store.py
                 org_access; agents never); the area decides what fits its own rule
      Creating checks the right to add at the top of the workspace (files/store.py _place: an agent never, an organisation's
      top level only for who may write there) and raises Denied. The caller commits.
  fs_area_root_of(c, nid) -> (ws, area) | None   is node nid an area's root folder?
"""
import re

from ..core.access import Denied
from ..core.db import insert_id
from .store import _free_name, _now, _place, fs_chain, fs_deleted, fs_log_add, safe_fs_name


def fs_area_ws(org_id, owner_id):
    return f"o{int(org_id)}" if org_id else f"u{int(owner_id)}"


def _alive(c, nid, org_id, uid):
    """Is folder nid still the area's root of workspace (org_id, uid): at the top of that workspace, not in the trash?"""
    if not nid:
        return False
    chain = fs_chain(c, nid)
    if not chain or fs_deleted(chain) or len(chain) != 1:
        return False
    n = chain[0]
    if n["kind"] != "folder":
        return False
    return (n["org_id"] or None) == (int(org_id) if org_id else None) and (org_id or n["owner_id"] == uid)


def fs_area_root(c, uid, org_id, area, name, create=True, org_access=""):
    """The root folder of area in workspace org_id (None: uid's own tree) -- module docstring."""
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,19}", area or ""):
        raise ValueError(f"fs_area_root: invalid area {area!r}")
    if not uid:
        raise Denied(404)
    org = int(org_id) if org_id else None
    ws = fs_area_ws(org, uid)
    r = c.execute("SELECT node_id FROM fs_area_roots WHERE ws=? AND area=?", (ws, area)).fetchone()
    if r and _alive(c, r[0], org, uid):
        return r[0]
    if not create:
        return None
    owner, org2 = _place(c, uid, None, org)
    nm = safe_fs_name(str(name or "").strip() or area)
    ts = _now()
    acc = org_access if org2 and org_access in ("view", "edit") else ""
    nid = insert_id(c, "INSERT INTO fs_nodes(parent_id,kind,name,owner_id,org_id,org_access,created_by,created_at,updated_at) "
                       "VALUES(?,?,?,?,?,?,?,?,?)", (None, "folder", _free_name(c, None, owner, org2, nm), owner, org2, acc, uid, ts, ts))
    fs_log_add(c, nid, "create")
    c.execute("""INSERT INTO fs_area_roots(ws, area, org_id, owner_id, node_id, updated_at) VALUES(?,?,?,?,?,?)
                 ON CONFLICT (ws, area) DO UPDATE SET node_id=excluded.node_id, updated_at=excluded.updated_at""",
              (ws, area, org2, None if org2 else uid, nid, ts))
    return nid


def fs_area_root_of(c, nid):
    """(ws, area) when node nid is marked as an area's root folder, else None."""
    r = c.execute("SELECT ws, area FROM fs_area_roots WHERE node_id=?", (int(nid),)).fetchone()
    return (r[0], r[1]) if r else None
