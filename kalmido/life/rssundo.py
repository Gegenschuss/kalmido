"""2.809.0 (#5476): undo across devices, the rest of stage 7 -- followed feeds in the core's step groups
(core/undoareas.py).

A feed (table rss_feeds) is the tracked kind "feed" (core/writes.py obj_track): unfollowing it (DELETE /api/feeds/<id>) and
following it again (POST …/restore) record a snap step of the person under its lock (rss_feeds-<id>), labelled with its title.
What the watchdog fetches (etag, times, errors, the title the feed gives) is not part of the copy nor of the fingerprint.
Taking back (core/undoweb.py): the person may change the sources of its space NOW (life/rss.py rss_own manage=True, the
feeds switched on); back out of the trash refuses (409) as the restore does: the same address followed again meanwhile, or
the space at its limit of feeds. Following a new feed records none (the browser's step unfollows it)."""
from ..core.access import live_sql
from ..core.errors import Denied
from ..core.i18n import tr
from ..core.objhooks import GONE
from ..core.undoareas import UA_DELETED, UA_RESTORED, ua_plain, ua_post, ua_pre
from ..core.undogroups import UG_LABEL
from ..core.undoweb import undo_need_reg
from ..core.writes import obj_track
from .rss import RSS_MAX_FEEDS, RSS_STEP, _count, _fw, rss_need, rss_own

RFU_KIND = "feed"
RFU_FETCH = {"title", "site_url", "etag", "last_modified", "last_fetch", "last_ok", "last_error", "fails"}
RFU_WHAT = {"delete": UA_DELETED, "restore": UA_RESTORED}


def rfu_label(r):
    return UG_LABEL, [ua_plain(r.get("title") or r.get("url"), r.get("id"))]


obj_track(RFU_KIND, "rss_feeds", undo_keep={"rss_feeds": {"user_id", "url", *RFU_FETCH}}, undo_nofp={"rss_feeds": {"deleted_by", *RFU_FETCH}},
          undo_label=rfu_label, undo_free=("deleted_at", "deleted_by"))  # 2.925.0 (#5367): deleted_by of the core's trash, not in the fingerprint (steps of before keep theirs)
GONE[RFU_KIND] = "rss_feeds"  # an account's deletion takes its history / undo rows (core/objhooks.py)


def rfu_pre(c, uid, fid, what):
    """The person's step before unfollowing / following again feed fid (after its lock rss_feeds-<id>)."""
    r = c.execute("SELECT title, url FROM rss_feeds WHERE id=?", (int(fid),)).fetchone()
    ua_pre(c, uid, RFU_KIND, fid, RFU_WHAT[what], ua_plain((r["title"] or r["url"]) if r else "", fid))


def rfu_post(c):
    ua_post(c)


def rfu_need(c, uid, rid, oid):
    """Who may take a feed's step back now: who may change the sources of its space; out of the trash only as the restore."""
    rss_need(c, uid)
    f = rss_own(c, uid, int(rid), manage=True)
    if f["deleted_at"]:  # the step brings it back (undo of an unfollow, redo of a restore): before the copy is written
        w, a = _fw(f["org_id"], uid, "rss_feeds")
        if c.execute(f"SELECT 1 FROM rss_feeds WHERE (({w}) OR user_id=?) AND url=? AND {live_sql()} AND id<>?",
                     (*a, f["user_id"], f["url"], int(rid))).fetchone():
            raise Denied(409, tr("You already follow this feed"))
        if _count(c, uid, f["org_id"]) >= RSS_MAX_FEEDS:
            raise Denied(409, tr("At most {0} feeds", RSS_MAX_FEEDS))
    return {"lock": f"rss_feeds-{int(rid)}"}


undo_need_reg(RFU_KIND, rfu_need)
RSS_STEP.update(pre=rfu_pre, post=rfu_post)  # life/rss.py rss_delete / rss_restore call them
