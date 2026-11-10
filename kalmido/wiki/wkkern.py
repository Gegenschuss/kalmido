"""2.809.0 (#5365, stage 3 of the core's trash): knowledge pages on the ONE trash of the core (core/writes.py obj_trash /
obj_restore / obj_purge / obj_trash_prune, docs/dev/kern.md). The page is registered as a core object without routes,
folder node or listing (the pattern of office/okern.py): the knowledge routes (wiki/pages.py) check their rights as before
and then put the page into the core's trash (wkk_trash: deleted_at / deleted_by, its files as children with the same time),
take it back (wkk_restore: only the files that went with it) and delete it for good (wkk_purge: the routes' "Delete
permanently" / "Empty trash"; the core's hourly retention run obj_trash_tick after the trash period, trash_prune=True). The
area's own purge (wiki_purge) and its run (wiki_trash_tick) are gone; what only the knowledge area knows -- the stored files,
their scan / text rows, the move records, the shares of exactly this page, its renames in obj_history (kind "wiki") and its
node in the tree -- is the hook of obj_on_purge (_wkk_purge).
The core's role of a page (the second floor under the route's own check): 'manage' for who edits it through its space
(wkfolder.wkf_base: deleting / restoring stay the space's, never an edit share), nothing for anyone else -- no shares, no
agents (the area's own role has none for them). Its space hook names no organisation: wkf_base checks the organisation itself.
The kind's name differs from the reference kind of the tree ("wiki", wkfolder.WKF_KIND): the folders keep their own rules."""
from datetime import datetime

from ..core.access import live_sql, trash_sql
from ..core.db import iso, now_utc
from ..core.i18n import N_
from ..core.objects import obj_register
from ..core.pg import ts_canon
from ..core.writes import obj_on_purge, obj_purge, obj_restore, obj_trash
from .wikiatt import wka_page_files
from .wkfolder import wkf_base, wkf_drop

WKK_KIND = "wiki_page"


def _row(c, rid):
    return c.execute("SELECT * FROM wiki_pages WHERE id=?", (int(rid),)).fetchone()


def _base(c, uid, rid):
    r = _row(c, rid)
    return "manage" if r is not None and wkf_base(c, uid, r) == "edit" else None


def _visible(c, uid):  # the candidates only (cap hook: obj_role decides each row)
    u = int(uid)
    return (f"(SELECT id FROM wiki_pages WHERE (org_id IS NULL AND owner_id = {u}) "
            f"OR org_id IN (SELECT org_id FROM org_members WHERE user_id = {u}))")


def _space(c, rid):
    return (None, None) if _row(c, rid) is not None else None


def _wkk_purge(c, rid):
    """The knowledge area's part of the delete for good of page rid (core/writes.py obj_on_purge; was wiki_purge): the rows
    the core does not know, before the page row goes (links, files, versions, word index cascade). -> the stored files no
    other row names (unlinked after the commit)."""
    r = _row(c, rid)
    if r is None:
        return None
    files = wka_page_files(c, [rid])
    fids = [x[0] for x in c.execute("SELECT id FROM wiki_files WHERE page_id=?", (int(rid),))]
    if fids:
        c.execute("DELETE FROM upload_scan WHERE kind='wiki' AND ref_id = ANY(CAST(? AS BIGINT[]))", (fids,))
        c.execute("DELETE FROM file_text WHERE kind='wiki' AND ref_id = ANY(CAST(? AS BIGINT[]))", (fids,))
    c.execute("DELETE FROM space_moves WHERE kind='wiki' AND obj_id=?", (int(rid),))
    # a share of exactly this page ends with it (a later page of the same name is not shared by the old link); folder shares stay
    c.execute("UPDATE wiki_shares s SET revoked_at=? FROM wiki_pages p WHERE p.id=? AND s.is_folder=0 AND s.revoked_at IS NULL "
              "AND COALESCE(s.org_id,0)=COALESCE(p.org_id,0) AND COALESCE(s.owner_id,0)=COALESCE(p.owner_id,0) AND lower(s.path)=lower(p.path) "
              f"AND NOT EXISTS (SELECT 1 FROM wiki_pages x WHERE {live_sql('x')} AND COALESCE(x.org_id,0)=COALESCE(p.org_id,0) "
              "AND COALESCE(x.owner_id,0)=COALESCE(p.owner_id,0) AND lower(x.path)=lower(p.path))", (iso(now_utc()), int(rid)))
    c.execute("DELETE FROM obj_history WHERE kind='wiki' AND ref_id=?", (int(rid),))  # 2.571.0 (#4766): its renames (no FK)
    wkf_drop(c, [rid])  # 2.200.0 A (#2747): its node in the tree
    if files:  # a stored file another page's row still names stays on disk
        used = {x[0] for x in c.execute("SELECT path FROM wiki_files WHERE path = ANY(CAST(? AS TEXT[])) AND page_id<>?",
                                        (files, int(rid)))}
        files = [p for p in files if p not in used]
    return files


obj_register(WKK_KIND, "wiki_pages", label=N_("Knowledge page"), fields={}, area="other", routes=False, listed=False, fsref=False,
             space=_space, base_role=_base, visible=_visible, cap=lambda c, uid, rid: None,
             children=(("wiki_files", "page_id"),), trash_prune=True)
obj_on_purge(WKK_KIND, _wkk_purge)


def wkk_trash(c, uid, pid):
    """Into the core's trash (the route checked the rights): the page and its live files with the same time. No step of the
    core's list: the app's own Undo brings it back (POST /api/wiki/restore)."""
    return obj_trash(c, uid, WKK_KIND, pid, step=False)


def wkk_restore(c, uid, pid):
    """Out of the core's trash with the files that went with it (a file deleted on its own before stays in the trash). A file
    held when the space's lock went on (wkx_held_at, 2.528.0 D #4306) stays in the trash here: only wikiatt.wkx_files_back
    brings it back, for who could read the space then."""
    held = c.execute(f"SELECT id, deleted_at FROM wiki_files WHERE page_id=? AND wkx_held_at IS NOT NULL AND {trash_sql()}",
                     (int(pid),)).fetchall()
    _wkk_align_old(c, pid)
    out = obj_restore(c, uid, WKK_KIND, pid, step=False)
    for f in held:
        c.execute(f"UPDATE wiki_files SET deleted_at=? WHERE id=? AND {live_sql()}", (f["deleted_at"], f["id"]))
    return out


def _wkk_when(v):
    t = ts_canon(v)
    try:
        return datetime.fromisoformat(t) if t else None
    except ValueError:
        return None


def _wkk_align_old(c, pid):
    """2.809.0 (#5365, review): a page trashed BEFORE 2.809 kept the old rule of wiki/pages.py - its files came back when they
    went into the trash at the page's time OR LATER (wiki_bulk stamped the files a moment after the page). The core brings
    back only the same time (core/writes.py _kids_restore), so such files get the page's time first; held ones stay."""
    r = _row(c, pid)
    gone = _wkk_when(r["deleted_at"]) if r is not None else None
    if gone is None:
        return
    rows = c.execute(f"SELECT id, deleted_at FROM wiki_files WHERE page_id=? AND wkx_held_at IS NULL AND {trash_sql()}",
                     (int(pid),)).fetchall()
    ids = [f["id"] for f in rows if (_wkk_when(f["deleted_at"]) or gone) > gone]
    if ids:
        c.execute("UPDATE wiki_files SET deleted_at=? WHERE id = ANY(CAST(? AS BIGINT[]))", (r["deleted_at"], ids))


def wkk_with_page(c, pid, fids):
    """2.809.0 (#5365): files fids of page pid put into the trash in the same request before it (wiki_bulk: an import's undo)
    get the page's time: they went with it and come back with it (core/writes.py children)."""
    r = _row(c, pid)
    if fids and r is not None and r["deleted_at"]:
        c.execute("UPDATE wiki_files SET deleted_at=? WHERE page_id=? AND id = ANY(CAST(? AS BIGINT[])) AND wkx_held_at IS NULL "
                  f"AND {trash_sql()}", (r["deleted_at"], int(pid), [int(x) for x in fids]))


def wkk_purge(c, uid, pid):
    """For good (only from the trash; the route checked the rights and runs it inside core/writes.py obj_purge_after)."""
    return obj_purge(c, uid, WKK_KIND, pid)
