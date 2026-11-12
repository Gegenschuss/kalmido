"""2.1045.0 (#5823): a whole knowledge area shared at once -- the facts the knowledge panel's "Share…" on "Knowledge" needs.

The share itself is the file store's (fs_shares on the area's root node "Knowledge", the one Share dialog static/js/fsshare.js,
POST /api/files/nodes/<root>/shares): files/fsroots.py lets the knowledge root be shared with agents only (fs_area_rule
root_share), wiki/wkfolder.py _share_starts / wkf_shared read it like any folder share -- every page below it, also later
ones; never a locked space (_share: 409), never across the organisation boundary (_share_targets: a private area only with
its person's own agents, an organisation's area only with its agents). Single folders are kept out per agent in its data lock
(agents.data_lock wiki_folders, core/dlock.py dl_chain_cut).

  GET /api/wiki/area-share?space=private|org:<id>[&agent_id=] -> {root, locked, may, limit, folders, pages,
      shares: [{id, agent_id, name, role, expires_at, editable, excluded: [folder ids of this tree]}],
      preview?: {agent_id, folders, pages, excluded}}
      root     the area's root node (null: no tree yet -- the first folder / page makes it)
      may      the asker may manage the area's shares (else only {root, locked, may: false})
      folders / pages   how many the tree holds; limit: the tree is larger than one read (WKF_TREE_MAX) -- some pages left out
      shares   the agent shares on the root; editable: the asker may change that agent's data lock (its exclusions)
      preview  what agent_id would see through an area share now: folders / pages visible, excluded folders of this tree
"""
from flask import jsonify, request

from ..core.config import app
from ..core.access import Denied, live_sql
from ..core.db import db
from ..core.dlock import dl_wiki_folders
from ..core.errors import BadInput
from ..core.i18n import tr
from ..accounts.session import me
from ..files.store import _now
from .pages import wiki_space
from .wkfolder import WKF_KIND, WKF_TREE_MAX, _share, _space_locked, _subtree, _walk, wkf_root


def _visible(rows, root, ex, own):
    """(folders, pages) an agent sees through the root's share: a node counts unless an excluded folder lies on its way down
    from the root -- a share of its own (own: node ids shared with the agent) on the way wins (dl_chain_cut)."""
    fp = _walk(rows, root)
    vis = {root: True}
    nf = np = 0
    for r in rows:
        if r["id"] == root or r["parent_id"] not in vis or r["id"] not in fp or fp[r["id"]][1]:
            continue
        v = r["id"] in own or (vis[r["parent_id"]] and r["id"] not in ex)
        vis[r["id"]] = v
        if not v:
            continue
        if r["kind"] == "folder":
            nf += 1
        elif r["kind"] == "ref" and r["ref_kind"] == WKF_KIND:
            np += 1
    return nf, np


def _live_pages(c, rows):
    """The page nodes of rows whose page is live (not in the knowledge trash)."""
    ids = [r["ref_id"] for r in rows if r["kind"] == "ref" and r["ref_kind"] == WKF_KIND]
    if not ids:
        return set()
    live = set()
    for i in range(0, len(ids), 1000):
        part = ids[i:i + 1000]
        live |= {x[0] for x in c.execute(f"SELECT id FROM wiki_pages WHERE id IN ({','.join('?' * len(part))}) AND {live_sql()}", part)}
    return live


def _editable(c, aid):
    from ..agents.workstyle import ws_need_editor
    try:
        ws_need_editor(c, aid)
        return True
    except Denied:
        return False


@app.get("/api/wiki/area-share")
def wka_get():
    """The facts of a whole area's share (module docstring)."""
    c = db()
    uid = me()
    oid = wiki_space(c, uid, request.args.get("space"))
    locked = _space_locked(c, oid, uid)
    root = None if locked else wkf_root(c, uid, oid)
    out = {"root": root, "locked": locked, "may": False}
    if locked:
        return jsonify(out)
    rn = c.execute("SELECT * FROM fs_nodes WHERE id=?", (root,)).fetchone() if root else None
    if rn is None:
        return jsonify(out)  # no tree yet: nothing to share (the first folder / page makes the root)
    if not _share(c, uid, rn, False):
        return jsonify(out)
    rows = _subtree(c, root)
    live = _live_pages(c, rows)
    rows = [r for r in rows if not (r["kind"] == "ref" and r["ref_kind"] == WKF_KIND and r["ref_id"] not in live)]
    ids = {r["id"] for r in rows}
    fp = _walk(rows, root)
    out.update(may=True, limit=len(rows) >= WKF_TREE_MAX,
               folders=sum(1 for r in rows if r["kind"] == "folder" and r["id"] != root and r["id"] in fp and not fp[r["id"]][1]),
               pages=sum(1 for r in rows if r["kind"] == "ref" and r["id"] in fp and not fp[r["id"]][1]))
    sh = c.execute("""SELECT s.id, s.agent_id, s.role, s.expires_at, u.display_name FROM fs_shares s JOIN users u ON u.id=s.agent_id
                      WHERE s.node_id=? AND s.agent_id IS NOT NULL AND COALESCE(s.list_own, 0)=0 ORDER BY lower(u.display_name), s.id""",
                   (root,)).fetchall()
    out["shares"] = [{"id": s["id"], "agent_id": s["agent_id"], "name": s["display_name"], "role": s["role"],
                      "expires_at": s["expires_at"], "editable": _editable(c, s["agent_id"]),
                      "excluded": sorted(x for x in dl_wiki_folders(c, s["agent_id"]) if x in ids)} for s in sh]
    aid = request.args.get("agent_id")
    if aid not in (None, ""):
        try:
            aid = int(aid)
        except ValueError:
            raise BadInput(tr("Invalid value: {0}", "agent_id")) from None
        ex = {x for x in dl_wiki_folders(c, aid) if x in ids}
        own = {r[0] for r in c.execute("""SELECT node_id FROM fs_shares WHERE agent_id=? AND node_id<>? AND COALESCE(list_own, 0)=0
                                           AND (expires_at IS NULL OR expires_at > ?)""", (aid, root, _now()))} & ids
        nf, np = _visible(rows, root, ex, own)
        out["preview"] = {"agent_id": aid, "folders": nf, "pages": np, "excluded": len(ex)}
    return jsonify(out)
