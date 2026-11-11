"""2.925.0 (#5367, stage 5 of the core's trash): bookmarks and feeds on the ONE trash of the core (core/writes.py obj_trash /
obj_restore / obj_trash_prune, docs/dev/kern.md).

Both are registered here as core objects without routes, folder node or listing (like the office kinds, office/okern.py):
their own routes check their rules as before and then put the row into the core's trash (obj_trash: deleted_at /
deleted_by, history) and take it back (obj_restore) -- without a step of the core (step=False): their step of the person
is their own snap step (life/bmundo.py kind "bookmark", life/rssundo.py kind "feed", 2.809.0 #5476), which checks first
what the core does not know (the same link saved again, the same feed followed again, the feeds' limit). The core kinds
have names of their own ("bookmark_link", "rss_feed") so the tracked undo kinds stay as they are.
- bookmark_link (life/bookmarks.py): the core's role is the route's -- 'manage' for who may change it (bm_get write: its
  owner, an admin of its organisation), 'view' for who sees it. Its picture is a stored file the core does not know: the
  purge hook (obj_on_purge, #5365) hands its path to the core, which removes it after the commit.
- rss_feed (life/rss.py): 'manage' for who may change the sources of its space (rss_own manage: the person, an
  organisation's admins), 'view' for who reads them; its articles and read marks go by FK cascade.
Both are trash_prune kinds: the core's hourly run deletes them after the trash period; the bookmarks' and feeds' own runs
are gone. The rows already in the trash before 2.925.0 are the core's trash as they are (deleted_at; deleted_by NULL)."""
from ..core.errors import Denied
from ..core.i18n import N_
from ..core.objects import obj_register, obj_row
from ..core.pg import qi
from ..core.writes import obj_on_purge
from .bookmarks import BM_KIND, bm_get, bm_may_write
from .rss import RSS_KIND, rss_may_manage, rss_own

_TABLES = {"bookmarks", "rss_feeds"}  # the allowlist of the table names for SQL text (core/pg.py qi)


def _space(table):
    def space(c, rid):
        r = c.execute(f"SELECT org_id, user_id FROM {qi(table, _TABLES)} WHERE id=?", (int(rid),)).fetchone()
        return (r["org_id"] or None, r["user_id"]) if r is not None else None
    return space


def _visible(table):
    def visible(c, uid):  # the candidates only (the base role decides each row)
        u = int(uid)
        return (f"(SELECT id FROM {qi(table, _TABLES)} WHERE (org_id IS NULL AND user_id = {u}) "
                f"OR org_id IN (SELECT org_id FROM org_members WHERE user_id = {u}))")
    return visible


def _bm_base(c, uid, bid):
    """The bookmark's role: the route's own check (life/bookmarks.py bm_get: seeing it) and bm_may_write ('manage')."""
    r = obj_row(c, BM_KIND, bid)
    if r is None:
        return None
    try:
        bm_get(c, uid, int(bid), deleted=r["deleted_at"] is not None)
    except Denied:
        return None
    return "manage" if bm_may_write(c, uid, r) else "view"


def _feed_base(c, uid, fid):
    """The feed's role: the route's own check (life/rss.py rss_own: seeing it) and rss_may_manage ('manage')."""
    try:
        r = rss_own(c, uid, int(fid))
    except Denied:
        return None
    return "manage" if rss_may_manage(c, uid, r["org_id"]) else "view"


def _bm_purge(c, rid):
    """The bookmarks' part of the delete for good of bookmark rid (core/writes.py obj_on_purge): its stored picture, removed
    after the commit (a path below the attachments folder, core/serializers.py unlink_files)."""
    r = c.execute("SELECT image FROM bookmarks WHERE id=?", (int(rid),)).fetchone()
    img = (r["image"] or "") if r is not None else ""
    return [img] if img.startswith("bookmarks/") and ".." not in img else None


obj_register(BM_KIND, "bookmarks", label=N_("Bookmark"), fields={}, area="other", routes=False, listed=False, fsref=False,
             space=_space("bookmarks"), base_role=_bm_base, visible=_visible("bookmarks"), cap=lambda c, uid, rid: None,
             title=lambda c, rid: ((obj_row(c, BM_KIND, rid) or {"title": ""})["title"] or ""),
             open_url=lambda rid: "bookmarks", trash_prune=True)
obj_on_purge(BM_KIND, _bm_purge)
obj_register(RSS_KIND, "rss_feeds", label=N_("Feed"), fields={}, area="other", routes=False, listed=False, fsref=False,
             space=_space("rss_feeds"), base_role=_feed_base, visible=_visible("rss_feeds"), cap=lambda c, uid, rid: None,
             title=lambda c, rid: ((obj_row(c, RSS_KIND, rid) or {"title": ""})["title"] or ""),
             open_url=lambda rid: "feeds", trash_prune=True)
