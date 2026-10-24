"""2.200.0 A (#2747): knowledge pages in folders of the file store -- the reference kind 'wiki' of the folder system
(files/fsref.py) and the tree of the knowledge panel.

The folders of a workspace's knowledge pages are folders of its file store tree below the area root "Knowledge" (files/
fsroots.py, area 'wiki'); every page is ONE reference node (kind 'ref', ref_kind 'wiki', ref_id = wiki_pages.id, name = the
last part of its path). The page's text, history, word index and links stay in wiki_pages & co.

Path and tree (wiki_pages.path stays the truth for older versions, a rollback to 2.199 shows every page where it was):
- path = the names of the folders below the root + the page's own last part. Renaming / moving a folder or a page in the
  tree (the knowledge panel or the file store's routes, files/web.py -> fs_area_rule hooks) writes the new path of every page
  of the subtree, with the [[links]] of the other pages (wiki_relink) and the wiki_shares (wsh_repath) -- a taken name
  (same path, case ignored) is a 409 and changes nothing. A path changed the old way (a name with "/", POST /api/wiki/move,
  the ZIP import, a version without folders) moves the node at the next wkf_sync.
- wkf_sync = the migration: idempotent, it touches only pages without a node or whose node lies elsewhere than their path
  says; it never renames a page. It runs on the index of a space and after every change of a page's path (people who may
  write there; a read-only person reads the tree as it is and the pages without a node by their path).
- "Folder with its own page": page "A" and pages "A/B" -> the folder "A" and the page node "A" are siblings (the names of
  the knowledge area's nodes are exact, not made unique like the file store's).
- Empty folders exist (POST /api/wiki/folders, the file store's folder route); a folder going into the trash takes its pages
  into the knowledge trash (on_trash, marked on the node like the sheets), coming back restores only those.
- Only folders and pages lie below the root (fs_area_rule kinds), nothing crosses its border (409); moving pages to the
  other workspace stays wkmove.py (their nodes go, the target's sync makes new ones).
- Locked spaces (wiki_spaces.e2e, wikie2e.py): path and text are ciphertexts -- no nodes, no sync; nodes made before the
  lock give nothing any more (space None, hidden), nothing is deleted.

Rights (point 2 of the brief, the way chosen): the root of an organisation's knowledge folders belongs to one of its admins
(fsroots) and carries org_access 'edit'; every folder below inherits it (the file store's rules): members / admins see and
change every folder, read-only people read (files/store.py _fs_limited_role caps at 'view'), guests and accounting see no
part of it (fs_visible_sql leaves org_access out for them) -- exactly the knowledge area's rule (need_org_area). The rule is
org_open (files_list lists every folder below the root, not only the ones with a role of their own). Organisation access
never opens a page (fsref): the page's role is the higher one of the area's (wkf_base) and the explicit shares of its chain
(fs_ref_node_role: person, group, agent). A private space's root is its owner's.

Interface (signatures fixed; parts B / C use them):
  WKF_KIND = WKF_AREA = 'wiki'
  wkf_base(c, uid, r) -> None | 'view' | 'edit'    the area's own role on page row r (private: the owner edits; an
                                                   organisation: org_sees_all reads, org_writes edits; agents None)
  wkf_role(c, uid, r) -> None | 'view' | 'edit'    the higher one of wkf_base and the folder shares of its node (a locked
                                                   space: wkf_base only). wiki_need / wiki_may_read use it.
  wkf_locked(c, r) -> bool                         page row r lies in a locked space (or is a ciphertext)
  wkf_root(c, uid, oid, create=False) -> node id | None    the "Knowledge" root of space oid (None: uid's private one)
  wkf_sync(c, uid, oid) -> root id | None          the path <-> tree check (above); the caller commits
  wkf_tree(c, uid, oid, root, pages) -> {root, folders: [{id, parent_id, name, sort_no, path}]}; sets node_id, folder_id
                                                   (null: the root), sort_no on the page dicts of the index
  wkf_node_of(c, pid) -> the live node row of page pid or None
  wkf_folder_path(c, nid) -> the path of folder nid below the root ('' = the root) or None (not a knowledge folder)
  wkf_drop(c, ids)                                 the pages left the space / were deleted for good: their nodes go
  wkf_drop_space(c, uid, oid)                      the space gets the lock: its page nodes and empty folders go (review 3)
  wkf_name(c, parent_id, name, skip=None) -> name  a folder's name in the tree (fs_area_rule name hook): exact, 409 when a
                                                   folder of that name is there or the folder would be too deep
  wkf_repath(c, uid, oid, owner, refs, old_folder=None, new_folder=None)   [(page node, new folder path)]: paths, links,
                                                   shares follow; Denied(409) for a taken name (the tree hooks use it)
  wkf_folder_move(c, uid, oid, src, dst)           POST /api/wiki/move: the folder node at path src (if any) becomes dst
  POST /api/wiki/folders {space, parent_id? (a knowledge folder; default: the root), name} -> 201 {folder}
2.200.0 B (#2747), sharing (the file store's Share dialog, fs_shares on a folder or a page node; part C uses these):
  wkf_shared(c, uid) -> {page id: {"node", "top", "folder"}}   the pages uid reaches only through shares of the knowledge
                                                   trees (person / group shares, an agent only its own; live, not in the
                                                   trash, not of a locked space, the organisation boundary): node = the page's
                                                   node row, top = the shared node it comes through (the topmost one), folder
                                                   = its folder path from there (the shared folder's own name first, '' = the
                                                   page itself is shared). At most WKF_SHARED_MAX pages.
  wkf_shared_ids(c, uid) -> set of page ids         the keys of wkf_shared
  wkf_shown_path(c, uid, r, info=None, path=None)  the path of page r uid may see (F, review B3: from the shared node down)
  wkf_visible_sql(c, uid, alias='p') -> SQL         a condition on wiki_pages <alias> (ids inlined, no ? parameters): the pages
                                                   uid may read -- the area's own (private: theirs; an organisation that shows
                                                   uid all its content) or a share (wkf_shared). Agents: shares only.
  Who manages the shares of a knowledge folder / page: who may write in its space (as the wiki_shares), besides the file
  store's owners (fs_area_rule share hook); a locked space shares nothing (409), its old nodes give nothing (above).
"""
import re

from flask import g, has_request_context, jsonify

from ..core.config import app
from ..core.access import Denied, acx_of, collab_all
from ..core.db import body, bump, db, insert_id, iso_ms, now_utc
from ..core.errors import BadInput
from ..core.i18n import N_, tr
from ..core.pg import IntegrityError, system_ctx, write_lock
from ..accounts.orgroles import org_sees_all, org_writes
from ..accounts.orgs import user_orgs  # 2.200.0 B (#2747)
from ..accounts.session import me
from ..files.fsref import fs_ref_drop, fs_ref_node, fs_ref_node_role, fs_ref_register
from ..files.fsroots import fs_area_root, fs_area_rule
from ..files.store import ROLE_RANK, _now, fs_chain, fs_deleted, fs_log_add, fs_role
from .pages import WIKI_BAD_CHARS, WIKI_DEPTH, wiki_clean_path, wiki_relink, wiki_space, wiki_space_sql
from .wikie2e import wke_mode, wke_open_sql, wke_page_mode
from .wkhist import wkh_body
from .wkshare import wsh_repath

WKF_KIND = "wiki"
WKF_AREA = "wiki"
WKF_TREE_MAX = 50000  # nodes of one space's knowledge tree read at once
WKF_SEEN = {}  # review 7: (ws) -> the fingerprint (count, hash of ids + paths, root) of the pages this process found in order


def _row(c, rid):
    return c.execute("SELECT * FROM wiki_pages WHERE id=?", (int(rid),)).fetchone()


def wkf_locked(c, r):
    if str(r["path"] or "").startswith("e2e1:"):
        return True
    return bool(wke_page_mode(c, r))


def _space_locked(c, oid, uid):
    return bool(wke_mode(c, oid, uid)[0])


def wkf_base(c, uid, r):
    """The area's own role on page row r (module docstring)."""
    if not uid or r is None or acx_of(c, uid).role == "agent":
        return None
    if r["org_id"] is None:
        return "edit" if r["owner_id"] == uid else None
    if not org_sees_all(c, uid, r["org_id"]):
        return None  # guests / accounting / not a member (2.143.0 A, #2151)
    return "edit" if org_writes(c, uid, r["org_id"]) else "view"


def wkf_role(c, uid, r):
    """The higher one of the area's role and the folder shares (module docstring)."""
    base = wkf_base(c, uid, r)
    if base == "edit" or r is None or wkf_locked(c, r):
        return base
    n = fs_ref_node(c, WKF_KIND, r["id"])
    if n is None:
        return base
    x = fs_ref_node_role(c, uid, n)
    return x if ROLE_RANK[x] > ROLE_RANK[base] else base


# ---------------------------------------------------------------- the reference kind 'wiki'
def _base(c, uid, rid):
    """The folder system's base role: none for a page in the knowledge trash or of a locked space (2.200.0 A, review 3: else
    the file store's listings show their titles) -- wiki_need keeps wkf_base for those (restore, the browser's ciphertexts)."""
    r = _row(c, rid)
    if r is None or r["deleted_at"] or wkf_locked(c, r):
        return None
    return wkf_base(c, uid, r)


def _space(c, rid):
    r = _row(c, rid)
    if r is None or r["deleted_at"] or wkf_locked(c, r):
        return None  # a page in the knowledge trash / of a locked space gives nothing through its node
    return (r["org_id"], r["owner_id"])


def _token_lacks(uid, scope):
    """2.200.0 F (#1781, review 1): the request's own token (uid = its account) lacks scope (False for the app's session)."""
    if not has_request_context() or g.get("auth_via") != "token" or not g.get("user") or g.user["id"] != uid:
        return False
    return scope not in (g.get("scopes") or set())


def wkf_agent_private_sql(c, uid, alias="p"):
    """2.200.0 F (#1781, review 1): for an agent, the private pages (wiki_pages <alias>) a share must never open -- every one
    not of the person who owns the agent (a team agent: every private page); '' for people."""
    if not uid or acx_of(c, uid).role != "agent":
        return ""
    a = c.execute("SELECT owner_id FROM agents WHERE user_id=?", (int(uid),)).fetchone()
    own = int(a["owner_id"]) if a and a["owner_id"] else None
    return f"({alias}.org_id IS NULL" + (f" AND {alias}.owner_id<>{own})" if own else ")")


def _hidden(c, uid):
    """What a folder share never opens: the pages of locked spaces; 2.200.0 F (#1781, review 1): for a token without
    wiki:read every page (the file store's API shows no page title, gives no text), for an agent the private pages of
    other people ('' when nothing)."""
    parts = []
    if c.execute("SELECT 1 FROM wiki_spaces WHERE e2e IS NOT NULL LIMIT 1").fetchone():
        parts.append(f"NOT ({wke_open_sql('p')})")
    if _token_lacks(uid, "wiki:read"):
        parts.append("TRUE")
    else:
        x = wkf_agent_private_sql(c, uid)
        if x:
            parts.append(x)
    if not parts:
        return ""
    return f"(SELECT p.id FROM wiki_pages p WHERE {' OR '.join(parts)})"


def _title(c, rid):
    r = _row(c, rid)
    return r["path"].rsplit("/", 1)[-1] if r else ""


def _content(c, uid, rid):
    """The page as a Markdown file (the file store's content routes; a token needs wiki:read, 2.200.0 F review 1)."""
    if _token_lacks(uid, "wiki:read"):
        raise Denied(403, tr("This token lacks the permission “{0}”", "wiki:read"))
    r = _row(c, rid)
    if r is None or r["deleted_at"] or wkf_locked(c, r):
        return None
    return wkh_body(c, r).encode("utf-8"), r["path"].rsplit("/", 1)[-1] + ".md", "text/markdown"


def _on_trash(c, uid, rid, restore):
    """A folder of the tree went into the file store's trash (restore False) / came back: its pages into the knowledge trash
    and back -- back only a page this mark still names (not one deleted on its own before or after), and only when its name
    is still free (else it stays in the trash)."""
    r = _row(c, rid)
    if r is None or bool(r["deleted_at"]) != bool(restore) or wkf_locked(c, r):
        return
    n = fs_ref_node(c, WKF_KIND, r["id"])
    if restore:
        m = c.execute("SELECT detail FROM fs_log WHERE node_id=? AND action='trash' AND detail LIKE 'area:%' ORDER BY id DESC LIMIT 1",
                      (n["id"],)).fetchone() if n is not None else None
        if not m or m[0] != f"area:{r['deleted_at']}" or wkf_base(c, uid, r) != "edit":
            return
        try:
            with c.savepoint():
                c.execute("UPDATE wiki_pages SET deleted_at=NULL WHERE id=?", (r["id"],))
        except IntegrityError:
            return  # its name was taken meanwhile: it stays in the knowledge trash
    else:
        ts = iso_ms(now_utc())
        c.execute("UPDATE wiki_pages SET deleted_at=? WHERE id=?", (ts, r["id"]))
        if n is not None:
            fs_log_add(c, n["id"], "trash", f"area:{ts}")


fs_ref_register(WKF_KIND, label=N_("Page"), open_url=lambda rid: f"wiki/{int(rid)}", base_role=_base, space=_space,
                hidden=_hidden, on_trash=_on_trash, title=_title, content=_content)


# ---------------------------------------------------------------- the tree
def wkf_root(c, uid, oid, create=False):
    """The "Knowledge" root of space oid (None: uid's private one); an organisation's opens to its members (org_access)."""
    return fs_area_root(c, uid, oid, WKF_AREA, tr("Knowledge|area"), create=create, org_access="edit")


def _subtree(c, root):
    """Every node below root (also the ones in the trash), parents first."""
    return c.execute("""WITH RECURSIVE t(id, depth) AS (SELECT id, 0 FROM fs_nodes WHERE id=?
                          UNION ALL SELECT n.id, t.depth + 1 FROM fs_nodes n JOIN t ON n.parent_id=t.id WHERE t.depth < 40)
                        SELECT n.*, t.depth FROM fs_nodes n JOIN t ON t.id=n.id ORDER BY t.depth, n.id LIMIT ?""",
                     (int(root), WKF_TREE_MAX)).fetchall()


def _walk(rows, root):
    """{id: (path below the root, in the trash)} for root and the folders below it; the reference nodes as {id: (folder path
    of their parent, in the trash)}."""
    fp = {int(root): ("", False)}
    for n in rows:
        if n["id"] == root or n["parent_id"] not in fp:
            continue
        pp, dead = fp[n["parent_id"]]
        dead = dead or bool(n["deleted_at"])
        if n["kind"] == "folder":
            fp[n["id"]] = (f"{pp}/{n['name']}" if pp else n["name"], dead)
        elif n["kind"] == "ref":
            fp[n["id"]] = (pp, dead)
    return fp


def _new_folder(c, uid, parent, name):
    ts = _now()
    nid = insert_id(c, "INSERT INTO fs_nodes(parent_id,kind,name,owner_id,org_id,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (parent["id"], "folder", name, parent["owner_id"], parent["org_id"], uid, ts, ts))
    fs_log_add(c, nid, "create")
    return nid


def wkf_sync(c, uid, oid):
    """The path <-> tree check of space oid (module docstring) -> the root id (None: no tree yet / a locked space)."""
    if _space_locked(c, oid, uid):
        return None
    if oid and not org_writes(c, uid, oid):
        return wkf_root(c, uid, oid)  # read-only: the tree as it is
    w, a = wiki_space_sql(oid, uid)
    ws = f"o{int(oid)}" if oid else f"u{int(uid)}"
    fp0 = (*c.execute(f"SELECT COUNT(*), md5(string_agg(id::text || '/' || path, '|' ORDER BY id)) FROM wiki_pages "
                      f"WHERE deleted_at IS NULL AND {w}", a).fetchone(), wkf_root(c, uid, oid))
    if WKF_SEEN.get(ws) == fp0:  # review 7: the live pages and their paths as this process last found them in order: nothing to do
        return fp0[-1]
    write_lock(c, f"wkf:{ws}")  # review 7: one sync per space at a time (parallel indexes made no folder twice)
    pages = c.execute(f"SELECT id, path FROM wiki_pages WHERE deleted_at IS NULL AND {w} AND left(path, 5)<>'e2e1:'", a).fetchall()
    root = wkf_root(c, uid, oid, create=bool(pages))
    if not root:
        return None
    rows = _subtree(c, root)
    if len(rows) >= WKF_TREE_MAX:
        return root  # review 7: a tree larger than one read -- never make folders from a partial view
    by = {n["id"]: n for n in rows}
    fp = _walk(rows, root)
    refs = {n["ref_id"]: n for n in rows if n["kind"] == "ref" and n["ref_kind"] == WKF_KIND}
    folders = {(n["parent_id"], n["name"]): n["id"] for n in rows
               if n["kind"] == "folder" and n["id"] != root and n["id"] in fp and not fp[n["id"]][1]}
    live = {p["id"] for p in pages}
    stale = [rid for rid in refs if rid not in live]
    if stale:  # pages deleted for good / moved to another space under an older version: their nodes go (a trashed page keeps its node)
        q = ",".join(str(int(x)) for x in stale)
        keep = {r[0] for r in c.execute(f"SELECT id FROM wiki_pages WHERE id IN ({q}) AND deleted_at IS NOT NULL AND {w}", a)}
        for rid in stale:
            if rid not in keep:
                c.execute("DELETE FROM fs_nodes WHERE id=?", (refs[rid]["id"],))
    top = by[root]
    ts = _now()
    for p in pages:
        parts = p["path"].split("/")
        want, name = "/".join(parts[:-1]), parts[-1]
        n = refs.get(p["id"])
        if n is not None and n["id"] in fp and not fp[n["id"]][1] and fp[n["id"]][0] == want and n["name"] == name:
            continue
        cur = root
        for part in parts[:-1]:
            nxt = folders.get((cur, part))
            if nxt is None:
                nxt = _new_folder(c, uid, by[cur], part)
                by[nxt] = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nxt,)).fetchone()
                folders[(cur, part)] = nxt
            cur = nxt
        if n is None:
            with system_ctx(c):  # a node an older version left in another tree (rows we cannot see): it goes with its shares (review 8)
                c.execute("DELETE FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND ref_id=?", (WKF_KIND, p["id"]))
            nid = insert_id(c, """INSERT INTO fs_nodes(parent_id,kind,name,owner_id,org_id,ref_kind,ref_id,created_by,created_at,updated_at)
                                  VALUES(?,?,?,?,?,?,?,?,?,?)""", (cur, "ref", name, top["owner_id"], top["org_id"], WKF_KIND,
                                                                   p["id"], uid, ts, ts))
            fs_log_add(c, nid, "create")
            continue
        moved = n["parent_id"] != cur
        c.execute(f"""UPDATE fs_nodes SET parent_id=?, name=?, {'sort_no=NULL, ' if moved else ''}deleted_at=NULL, deleted_by=NULL,
                      updated_at=? WHERE id=?""", (cur, name, ts, n["id"]))
        if moved:
            fs_log_add(c, n["id"], "move", str(cur))
    WKF_SEEN[ws] = (*fp0[:-1], root)  # (the caller commits; a rollback only costs one more check)
    return root


def wkf_tree(c, uid, oid, root, pages):
    """The index's tree (module docstring); pages = the index's page dicts (get node_id, folder_id, sort_no)."""
    for d in pages:
        d["node_id"], d["folder_id"], d["sort_no"] = None, None, None
    if not root:
        return {"root": None, "folders": []}
    rows = _subtree(c, root)
    fp = _walk(rows, root)
    folders, nodes = [], {}
    for n in rows:
        if n["id"] == root or n["id"] not in fp or fp[n["id"]][1]:
            continue
        if n["kind"] == "folder":
            folders.append({"id": n["id"], "parent_id": None if n["parent_id"] == root else n["parent_id"], "name": n["name"],
                            "sort_no": n["sort_no"], "path": fp[n["id"]][0]})
        elif n["kind"] == "ref" and n["ref_kind"] == WKF_KIND:
            nodes[n["ref_id"]] = n
    for d in pages:
        n = nodes.get(d["id"])
        if n is not None:
            d["node_id"], d["folder_id"], d["sort_no"] = n["id"], (None if n["parent_id"] == root else n["parent_id"]), n["sort_no"]
    return {"root": root, "folders": folders}


def wkf_node_of(c, pid):
    n = fs_ref_node(c, WKF_KIND, pid)
    return n if n is not None and not fs_deleted(fs_chain(c, n["id"])) else None


def _root_of_chain(c, chain):
    """(root row, space org id, owner id) when the chain lies in a knowledge tree, else None."""
    if not chain:
        return None
    top = chain[-1]
    r = c.execute("SELECT ws, area FROM fs_area_roots WHERE node_id=?", (top["id"],)).fetchone()
    if not r or r["area"] != WKF_AREA:
        return None
    return top


def wkf_folder_path(c, nid):
    chain = fs_chain(c, int(nid))
    if not chain or chain[0]["kind"] != "folder" or _root_of_chain(c, chain) is None:
        return None
    return "/".join(x["name"] for x in reversed(chain[:-1]))


def wkf_drop(c, ids):
    for pid in ids:
        fs_ref_drop(c, WKF_KIND, pid)


def wkf_drop_space(c, uid, oid):
    """The space gets the lock (wikie2e start): its tree is derived data with plain names -- the page nodes go, then every
    folder left empty (bottom up; their shares and history rows with them), the root too when nothing else lies below it
    (a file an older version put there keeps its folders). The next sync after the lock is lifted builds it anew."""
    w, a = wiki_space_sql(oid, uid)
    with system_ctx(c):  # also nodes of the space's pages an older version left in another tree
        c.execute(f"DELETE FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND ref_id IN (SELECT id FROM wiki_pages WHERE {w})", [WKF_KIND, *a])
    root = wkf_root(c, uid, oid)
    if not root:
        return
    rows = _subtree(c, root)
    for n in reversed(rows):  # children first
        if n["kind"] == "folder" and not c.execute("SELECT 1 FROM fs_nodes WHERE parent_id=? LIMIT 1", (n["id"],)).fetchone():
            c.execute("DELETE FROM fs_nodes WHERE id=?", (n["id"],))
    if not c.execute("SELECT 1 FROM fs_nodes WHERE id=?", (root,)).fetchone():
        c.execute("DELETE FROM fs_area_roots WHERE node_id IS NULL OR node_id=?", (root,))


def wkf_folder_move(c, uid, oid, src, dst):
    """POST /api/wiki/move renamed the folder src to dst: its node (with its shares) follows -- unless dst is a folder already
    (then the pages go into that one at wkf_sync and src stays, empty)."""
    root = wkf_root(c, uid, oid)
    if not root or _space_locked(c, oid, uid):
        return
    rows = _subtree(c, root)
    fp = _walk(rows, root)
    live = {fp[n["id"]][0].lower(): n for n in rows if n["kind"] == "folder" and n["id"] in fp and not fp[n["id"]][1] and n["id"] != root}
    f = live.get(src.lower())
    if f is None or dst.lower() in live:
        return
    parts = dst.split("/")
    cur = c.execute("SELECT * FROM fs_nodes WHERE id=?", (root,)).fetchone()
    for i, part in enumerate(parts[:-1]):
        x = live.get("/".join(parts[:i + 1]).lower())
        if x is None:
            nid = _new_folder(c, uid, cur, part)
            x = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
            live["/".join(parts[:i + 1]).lower()] = x
        cur = x
    if cur["id"] == f["id"] or any(r["id"] == f["id"] for r in fs_chain(c, cur["id"])):
        return  # into itself: the pages follow by their paths
    c.execute("UPDATE fs_nodes SET parent_id=?, name=?, sort_no=CASE WHEN parent_id=? THEN sort_no END, updated_at=? WHERE id=?",
              (cur["id"], parts[-1], cur["id"], _now(), f["id"]))
    fs_log_add(c, f["id"], "move", str(cur["id"]))


# ---------------------------------------------------------------- the file store's hooks (fs_area_rule)
def wkf_name(c, parent_id, name, skip=None):
    """A folder's name in the tree = a part of a page path: the link characters go, no "/" (409 when nothing is left); exact
    (a page of that name beside it is fine, no " (2)"), 409 for a folder of that name (case ignored) or a folder too deep
    for a page inside it (WIKI_DEPTH). parent_id None: not known yet (the route checks)."""
    v = re.sub(r"\s+", " ", WIKI_BAD_CHARS.sub("", str(name or "").replace("/", " "))).strip()
    if not v or v in (".", "..") or v.startswith(".") or v.lower().startswith("e2e1:"):
        raise Denied(409, tr("Name missing"))
    v = v[:150]
    if parent_id:
        pp = wkf_folder_path(c, parent_id)
        if pp is not None and (len(pp.split("/")) if pp else 0) + 2 > WIKI_DEPTH:
            raise Denied(409, tr("Too many folder levels (at most {0})", WIKI_DEPTH))
        x = c.execute("SELECT id FROM fs_nodes WHERE parent_id=? AND kind='folder' AND lower(name)=lower(?) AND deleted_at IS NULL",
                      (int(parent_id), v)).fetchone()
        if x and x[0] != skip:
            raise Denied(409, tr("A folder with this name already exists"))
    return v


def _before(c, uid, n):
    """Before a node of the tree is renamed / moved / goes into the trash (files/web.py). 2.200.0 F (#2747, review B4): a
    knowledge FOLDER changes only with the area's own right (who writes in its space), never through a share of it or
    of a folder above (a new subfolder in a shared folder stays possible): else its pages would leave the share."""
    if n["kind"] == "folder":
        top = _root_of_chain(c, fs_chain(c, n["id"]))
        if top is not None and wkf_base(c, uid, {"org_id": top["org_id"] or None,
                                                 "owner_id": None if top["org_id"] else top["owner_id"]}) != "edit":
            raise Denied(403)
    return {"folder": wkf_folder_path(c, n["id"]) if n["kind"] == "folder" else None}


def _after(c, uid, nid, ctx):
    """A node of the tree was renamed / moved: the paths of the pages below it follow (module docstring)."""
    chain = fs_chain(c, int(nid))
    top = _root_of_chain(c, chain)
    if top is None:
        return
    oid, owner = top["org_id"], (None if top["org_id"] else top["owner_id"])
    if _space_locked(c, oid, owner):
        return  # ciphertexts: the browser keeps the names
    n = chain[0]
    base = "/".join(x["name"] for x in reversed(chain[1:-1]))  # the folder path of n's parent
    if n["kind"] == "folder":
        rows = _subtree(c, n["id"])
        fp = _walk(rows, n["id"])
        own = f"{base}/{n['name']}" if base else n["name"]
        refs = [(r, own + ("/" + fp[r["id"]][0] if fp[r["id"]][0] else "")) for r in rows
                if r["kind"] == "ref" and r["ref_kind"] == WKF_KIND and r["id"] in fp and not fp[r["id"]][1]]
    elif n["kind"] == "ref" and n["ref_kind"] == WKF_KIND:
        own, refs = None, [(n, base)]
    else:
        return
    wkf_repath(c, uid, oid, owner, refs, (ctx or {}).get("folder"), own)


def wkf_repath(c, uid, oid, owner, refs, old_folder=None, new_folder=None):
    """refs = [(page node row, its new folder path)]: every page gets folder path + its own last part -- 409 for a taken name
    or a path too deep / too long (nothing changes), else the paths, the links of the other pages and the shares follow."""
    if not refs:
        if old_folder is not None and new_folder is not None and old_folder != new_folder:
            wsh_repath(c, oid, owner, old_folder, new_folder, True)  # an empty folder's share follows too
        return 0
    ids = [r["ref_id"] for r, _ in refs]
    q = ",".join(str(int(x)) for x in ids)
    w, a = wiki_space_sql(oid, owner)
    pages = {p["id"]: p for p in c.execute(f"SELECT * FROM wiki_pages WHERE id IN ({q}) AND deleted_at IS NULL AND {w}", a)}
    moves = []
    for r, folder in refs:
        p = pages.get(r["ref_id"])
        if p is None:
            continue
        new = (folder + "/" if folder else "") + p["path"].rsplit("/", 1)[-1]
        if new == p["path"]:
            continue
        if len(new.split("/")) > WIKI_DEPTH:
            raise Denied(409, tr("Too many folder levels (at most {0})", WIKI_DEPTH))
        try:
            ok = wiki_clean_path(new) == new
        except BadInput as e:
            raise Denied(409, str(e)) from None
        if not ok:
            raise Denied(409, tr("Invalid value: {0}", "path"))
        moves.append((p, new))
    if old_folder is not None and new_folder is not None and old_folder != new_folder:
        wsh_repath(c, oid, owner, old_folder, new_folder, True)
    if not moves:
        return 0
    mine = {p["id"] for p, _ in moves}
    seen, taken = set(), []
    for p, new in moves:
        k = new.lower()
        x = c.execute(f"SELECT id FROM wiki_pages WHERE deleted_at IS NULL AND {w} AND lower(path)=?", [*a, k]).fetchone()
        if k in seen or (x and x["id"] not in mine):
            taken.append(new)
        seen.add(k)
    if taken:
        raise Denied(409, tr("A page with this name already exists") + ": " + ", ".join(taken[:5]))
    ts = iso_ms(now_utc())
    for p, new in moves:  # first to a free name, then to the target (pages of the folder may swap names among themselves)
        c.execute("UPDATE wiki_pages SET path=? WHERE id=?", (f".moving/{p['id']}", p["id"]))
    for p, new in moves:
        c.execute("UPDATE wiki_pages SET path=?, updated_by=?, updated_at=? WHERE id=?", (new, uid, ts, p["id"]))
    for p, new in moves:
        wiki_relink(c, p, p["path"], new, owner or uid, ts)
        wsh_repath(c, oid, owner, p["path"], new, False)  # a page share (one inside the folder followed above already)
    return len(moves)


def _share(c, uid, n, strict):
    """2.200.0 B (#2747): may uid manage the shares of node n (module docstring)? strict: a locked space raises 409."""
    top = _root_of_chain(c, fs_chain(c, n["id"]))
    if top is None:
        return False
    oid, owner = top["org_id"], (None if top["org_id"] else top["owner_id"])
    r = _row(c, n["ref_id"]) if n["kind"] == "ref" and n["ref_kind"] == WKF_KIND else None
    if _space_locked(c, oid, owner) or (r is not None and wkf_locked(c, r)):
        if strict:
            raise Denied(409, tr("Pages of a space encrypted in the browser cannot be shared."))
        return False
    if acx_of(c, uid).role == "agent":
        return False
    if oid:
        return org_sees_all(c, uid, oid) and org_writes(c, uid, oid)
    return owner == uid


fs_area_rule(WKF_AREA, kinds={("folder", None), ("ref", WKF_KIND)}, org_open=True, name=wkf_name, before=_before, after=_after,
             share=_share)  # 2.200.0 B (#2747): share


# ---------------------------------------------------------------- routes
@app.post("/api/wiki/folders")
def wkf_folder_new():
    """{space, parent_id? (a folder of the space's knowledge tree; default: its root), name} -> 201 {folder: {id, parent_id
    (null: the root), name, sort_no, path}}. An empty folder; needs the right to write in the space / edit on the folder.
    409: a locked space, a folder of that name (case ignored) in the same place, too deep."""
    c = db()
    uid = me()
    b = body()
    oid = wiki_space(c, uid, b.get("space"), write=True)
    if _space_locked(c, oid, uid):
        raise Denied(409, tr("This space is end-to-end encrypted: its folders come from the page names"))
    wkf_name(c, None, b.get("name"))  # the name's shape before anything is made
    root = wkf_sync(c, uid, oid) or wkf_root(c, uid, oid, create=True)
    pid = b.get("parent_id")
    if pid in (None, "", 0):
        pid = root
    elif isinstance(pid, bool) or not isinstance(pid, int):
        raise BadInput(tr("Invalid value: {0}", "parent_id"))
    chain = fs_chain(c, pid)
    if not chain or chain[-1]["id"] != root or chain[0]["kind"] != "folder" or fs_deleted(chain):
        raise Denied(404)
    if ROLE_RANK[fs_role(c, pid, uid, chain=chain)] < ROLE_RANK["edit"]:
        raise Denied(403)
    path = "/".join(x["name"] for x in reversed(chain[:-1]))
    name = wkf_name(c, pid, b.get("name"))  # depth, a taken name: 409
    nid = _new_folder(c, uid, chain[0], name)
    bump(c)
    c.commit()
    return jsonify(folder={"id": nid, "parent_id": None if pid == root else pid, "name": name, "sort_no": None,
                           "path": f"{path}/{name}" if path else name}), 201


# ---------------------------------------------------------------- 2.200.0 B (#2747): what shares give (module docstring)
WKF_SHARED_MAX = 5000  # pages one person reaches through shares, listed at once


def _share_starts(c, uid):
    """The live shared nodes of the knowledge trees for uid: [(node row, chain)], not in the trash, the boundary applied."""
    ctx = acx_of(c, uid)
    agent = ctx.role == "agent"
    if not agent and not collab_all():
        return []
    who = "(s.agent_id=? OR s.user_id=?)" if agent else "(s.user_id=? OR s.group_id IN (SELECT group_id FROM group_members WHERE user_id=?))"
    rows = c.execute(f"""SELECT DISTINCT n.* FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id WHERE {who}
                         AND (s.expires_at IS NULL OR s.expires_at > ?) AND n.deleted_at IS NULL
                         AND (n.kind='folder' OR (n.kind='ref' AND n.ref_kind=?)) ORDER BY n.id LIMIT 2000""",
                     (uid, uid, _now(), WKF_KIND)).fetchall()
    out = []
    for n in rows:
        chain = fs_chain(c, n["id"])
        if not chain or fs_deleted(chain) or _root_of_chain(c, chain) is None or chain[-1]["id"] == n["id"]:
            continue
        if not fs_role(c, n["id"], uid, chain=chain):
            continue  # the organisation boundary (an agent of another organisation, a person who left it)
        out.append((n, chain))
    return out


def wkf_shared(c, uid):
    """{page id: {node, top, folder}} -- the pages uid reaches through shares (module docstring)."""
    if not uid:
        return {}
    starts = _share_starts(c, uid)
    ids = {n["id"] for n, _ in starts}
    out = {}
    for n, chain in starts:
        if any(x["id"] in ids for x in chain[1:]):
            continue  # a folder above is shared too: its pages come through that one
        if n["kind"] == "ref":
            refs = [(n, "")]
        else:
            rows = _subtree(c, n["id"])
            fp = _walk(rows, n["id"])
            refs = [(r, n["name"] + ("/" + fp[r["id"]][0] if fp[r["id"]][0] else "")) for r in rows
                    if r["kind"] == "ref" and r["ref_kind"] == WKF_KIND and r["id"] in fp and not fp[r["id"]][1]]
        for r, folder in refs:
            if r["ref_id"] not in out:
                out[r["ref_id"]] = {"node": r, "top": n, "folder": folder}
    if not out:
        return {}
    q = ",".join(str(int(x)) for x in out)
    pages = {p["id"]: p for p in c.execute(f"SELECT id, org_id, owner_id FROM wiki_pages p WHERE p.id IN ({q}) AND p.deleted_at IS NULL "
                                           f"AND {wke_open_sql('p')}")}
    keep = {}
    agent_own = None
    if acx_of(c, uid).role == "agent":
        a = c.execute("SELECT owner_id FROM agents WHERE user_id=?", (int(uid),)).fetchone()
        agent_own = int(a["owner_id"]) if a and a["owner_id"] else 0
    for pid, x in out.items():
        p, nd = pages.get(pid), x["node"]
        if p is None or len(keep) >= WKF_SHARED_MAX:
            continue
        if p["org_id"] and (nd["org_id"] or None) != p["org_id"]:
            continue  # a node left in another workspace's tree gives nothing (fsref _same_space)
        if not p["org_id"] and (nd["org_id"] or nd["owner_id"] != p["owner_id"]):
            continue
        if not p["org_id"] and agent_own is not None and p["owner_id"] != agent_own:
            continue  # 2.200.0 F (#1781, review 1): an agent gets a private page only of the person who owns it
        keep[pid] = x
    return keep


def wkf_shown_path(c, uid, r, info=None, path=None):
    """2.200.0 F (#2747, review B3): the path of page row r (or an older path of it) uid may see: the full one with the
    area's own role, else from the shared node down (the shared folder's name ... the page's name; the page shared alone:
    its name) -- nothing about the folders above a share. info: wkf_shared(c, uid) when the caller has it."""
    path = r["path"] if path is None else path
    if wkf_base(c, uid, r) is not None:
        return path
    x = (wkf_shared(c, uid) if info is None else info).get(r["id"])
    name = path.rsplit("/", 1)[-1]
    return f"{x['folder']}/{name}" if x and x["folder"] else name


def wkf_shared_ids(c, uid):
    return set(wkf_shared(c, uid))


def wkf_visible_sql(c, uid, alias="p"):
    """A condition on wiki_pages <alias>: the pages uid may read (module docstring); ids inlined."""
    a = alias
    parts = []
    if uid and acx_of(c, uid).role != "agent":
        parts.append(f"({a}.org_id IS NULL AND {a}.owner_id={int(uid)})")
        orgs = [int(o) for o in user_orgs(c, uid) if org_sees_all(c, uid, o)]
        if orgs:
            parts.append(f"{a}.org_id IN ({','.join(map(str, orgs))})")
    ids = wkf_shared_ids(c, uid)
    if ids:
        parts.append(f"{a}.id IN ({','.join(str(int(x)) for x in sorted(ids))})")
    return "(" + " OR ".join(parts) + ")" if parts else "FALSE"
