"""2.199.0 C (#2742): the root folder of an area in a workspace's file store tree -- e.g. "Tables" at the top of an
organisation's tree (or a person's own tree) holds the folders of the sheets area. The area's folders and reference nodes
(files/fsref.py) lie below it; the area's panel shows that subtree.

fs_area_roots keeps one row per (ws, area): ws = 'o<org id>' | 'u<person id>' (like docs/store.py doc_ws), node_id = the
folder. The folder is an ordinary folder of the file store (2.198 shows it as such; since 2.199.0 F it cannot be shared,
renamed, moved or deleted in the app -- fs_area_root_need_free); renaming or moving it (2.198) keeps the mark;
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
  fs_area_root_need_free(c, nid)    Denied(409) for an area's root folder: no share, organisation access, rename, move, trash
      2.199.0 F (#2742, review G1): an organisation's root belongs to one of its admins (like the documents folder), not to
      the first person who adds a folder.

2.200.0 A (#2747): an area may close its subtree (the knowledge pages: only folders and its own reference nodes, a page
path that mirrors the tree). The file store's routes ask these generic hooks; the area's logic stays in the area:
  fs_area_rule(area, *, kinds, org_open=False, name=None, before=None, after=None)
      kinds     the (kind, ref_kind) pairs that may lie below the root, e.g. {("folder", None), ("ref", "wiki")}; a ref_kind
                named here never lies outside the area. Nothing moves between the area and the rest of the store (409).
      org_open  the root's organisation access opens the folders below it (files_list lists them all, not only the ones
                with a role of their own -- the knowledge area: every member as before)
      name      f(c, parent_id, name, skip) -> the name of a folder made / renamed (skip: its id) below the root, or raises
                (exact: no " (2)")
      before    f(c, uid, n) -> ctx, before node n (a row) of the area is renamed / moved
      after     f(c, uid, nid, ctx) after that (in the same transaction; raising Denied undoes the whole request)
  fs_area_of(c, nid) -> area | None             the area whose root lies at the top of nid's chain (the root itself too)
  fs_area_open(area) -> bool                    org_open of the area's rule
  fs_area_need_fit(c, parent_id, kind, ref_kind=None, node=None)   Denied(409) when a node of this kind (node: that row,
                                                moved) may not lie in folder parent_id (None: the top of a space)
  fs_area_need_stay(c, nid)                     Denied(409) for a node of a closed area (moving it to another workspace)
  fs_area_name(c, parent_id, name, skip=None) -> name   the rule's name hook (name unchanged outside a closed area)
  fs_area_folder_name(c, parent_id, owner, org, name, skip=None) -> name   every route that makes a folder: fit + name /
                                                _free_name (review 6)
  fs_area_ref_kind(ref_kind) -> area | None     a reference kind its closed area files itself (POST /api/files/refs: 409)
  fs_area_before(c, uid, n) -> ctx / fs_area_after(c, uid, nid, ctx)   the rule's hooks (no-ops outside)
  2.200.0 B (#2747): fs_area_rule(..., share=f) with f(c, uid, n, strict) -> bool: may uid manage the shares of node n (a row)
      of the area although the file store's rule (owners: need_node(manage=True)) says no -- the knowledge area: who may
      write in the space; strict = a share is being made: raise Denied(409) when the area forbids sharing n (a locked space)
  fs_area_share(c, uid, n, strict=False) -> bool   the rule's share hook (False outside / without one)
"""
import re

from ..core.access import Denied
from ..core.db import insert_id
from ..core.i18n import tr
from ..core.pg import system_ctx
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


def _org_owner(c, org, uid):
    """The owner of an organisation's area root: one of its admins (like the documents folder, docs/store.py root_folder) --
    the first person to add a folder would else own the root and through it reach (share, delete, list) everybody's
    folders below it."""
    with system_ctx(c):  # the organisation's admins (members list; uid is a member, _place checked it)
        a = c.execute("""SELECT m.user_id FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=?
                         AND COALESCE(u.kind, '')!='agent' ORDER BY (m.role='admin') DESC, (m.user_id=?) DESC, m.user_id
                         LIMIT 1""", (int(org), uid)).fetchone()
    return a[0] if a else uid


def fs_area_root_need_free(c, nid):
    """2.199.0 F (#2742, review G1): an area's root folder is the area's: it cannot be shared, opened to the organisation,
    renamed, moved or put into the trash (Denied 409); the folders below it can."""
    if fs_area_root_of(c, nid):
        raise Denied(409, tr("This folder belongs to an area: it cannot be shared, renamed, moved or deleted"))


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
    if org2:
        owner = _org_owner(c, org2, uid)  # 2.199.0 F (#2742, review G1): one of the organisation's admins, never who came first
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


# ---------------------------------------------------------------- 2.200.0 A (#2747): closed areas (module docstring)
FS_AREA_RULES = {}


def fs_area_rule(area, *, kinds, org_open=False, name=None, before=None, after=None, share=None):
    """Register the rule of a closed area (module docstring); again = replace (a module reload)."""
    FS_AREA_RULES[area] = {"kinds": {(k, r) for k, r in kinds}, "org_open": bool(org_open), "name": name, "before": before,
                           "after": after, "share": share}


def fs_area_of(c, nid):
    """The area of node nid (its chain's top is an area's root) or None."""
    if not nid or not FS_AREA_RULES:
        return None
    chain = fs_chain(c, int(nid))
    if not chain:
        return None
    r = fs_area_root_of(c, chain[-1]["id"])
    return r[1] if r else None


def fs_area_open(area):
    r = FS_AREA_RULES.get(area or "")
    return bool(r and r["org_open"])


def _ref_area(ref_kind):
    for a, r in FS_AREA_RULES.items():
        if ref_kind and ("ref", ref_kind) in r["kinds"]:
            return a
    return None


def fs_area_ref_kind(ref_kind):
    """2.200.0 A (#2747, review 5): the closed area a reference kind belongs to (its objects are filed by the area) or None."""
    return _ref_area(ref_kind)


def fs_area_need_fit(c, parent_id, kind, ref_kind=None, node=None):
    """Denied(409) when a node of kind / ref_kind (node: the row that moves) may not lie in folder parent_id."""
    if not FS_AREA_RULES:
        return
    dst = fs_area_of(c, parent_id) if parent_id else None
    if node is not None:
        src = fs_area_of(c, node["id"])
    else:  # a new node: only an area's own reference kind is bound to it (the kinds check below rules the rest)
        src = _ref_area(ref_kind if kind == "ref" else None) or dst
    closed = dst in FS_AREA_RULES or src in FS_AREA_RULES
    foreign = node is not None and src in FS_AREA_RULES and (kind, ref_kind if kind == "ref" else None) not in FS_AREA_RULES[src]["kinds"]
    if foreign and dst not in FS_AREA_RULES:
        return  # review 9: what an older version put into the area (a file, a link) may leave it
    if closed and src != dst:
        raise Denied(409, tr("This entry belongs to another area and cannot be moved there"))
    if dst in FS_AREA_RULES and (kind, ref_kind if kind == "ref" else None) not in FS_AREA_RULES[dst]["kinds"]:
        raise Denied(409, tr("Only the entries of this area can lie in its folders"))


def fs_area_need_stay(c, nid):
    a = fs_area_of(c, nid)
    n = c.execute("SELECT kind, ref_kind FROM fs_nodes WHERE id=?", (int(nid),)).fetchone() if a in FS_AREA_RULES else None
    if n is not None and (n["kind"], n["ref_kind"] if n["kind"] == "ref" else None) in FS_AREA_RULES[a]["kinds"]:  # review 9: foreign kinds may leave
        raise Denied(409, tr("This entry belongs to another area and cannot be moved there"))


def fs_area_name(c, parent_id, name, skip=None):
    r = FS_AREA_RULES.get(fs_area_of(c, parent_id) or "") if parent_id else None
    return r["name"](c, parent_id, name, skip) if r and r["name"] else name


def fs_area_folder_name(c, parent_id, owner, org, name, skip=None):
    """2.200.0 A (#2747, review 6): the name of a folder made / renamed below parent_id -- every way that makes a folder asks
    here: a closed area checks kind and name (its own rule: exact names, 409 when taken), elsewhere a taken name gets " (2)"."""
    fs_area_need_fit(c, parent_id, "folder")
    r = FS_AREA_RULES.get(fs_area_of(c, parent_id) or "") if parent_id else None
    if r and r["name"]:
        return r["name"](c, parent_id, name, skip)
    return _free_name(c, parent_id, owner, org, name, skip=skip)


def fs_area_before(c, uid, n):
    a = fs_area_of(c, n["id"])
    r = FS_AREA_RULES.get(a or "")
    return (a, r["before"](c, uid, n) if r["before"] else None) if r else None


def fs_area_after(c, uid, nid, ctx):
    if ctx is None:
        return
    r = FS_AREA_RULES.get(ctx[0])
    if r and r["after"]:
        r["after"](c, uid, nid, ctx[1])


def fs_area_share(c, uid, n, strict=False):
    """2.200.0 B (#2747): the rule's share hook (module docstring); False outside a closed area or without one."""
    r = FS_AREA_RULES.get(fs_area_of(c, n["id"]) or "")
    return bool(r and r["share"] and r["share"](c, uid, n, strict))
