"""2.809.0 (#5476): undo across devices, the rest of stage 7 -- bookmarks in the core's step groups (core/undoareas.py).

A bookmark (table bookmarks) is the tracked kind "bookmark" (core/writes.py obj_track): a change of its details
(PATCH /api/bookmarks/<id>: title, description, note, tags, read state, link), putting it into the trash and taking it out
record a snap step of the person under the bookmark's lock (bookmarks-<id>, life/bookmarks.py bm_patch), labelled with its
title. Saving a new bookmark records none (the browser's step deletes it). The preview the watchdog fetches (picture, text,
site) is not part of the copy nor of the fingerprint: a preview arriving after the step does not block its undo. Taking back
(core/undoweb.py): the person needs write on the bookmark NOW (life/bookmarks.py bm_get write=True: its owner or an admin of
its organisation, the bookmarks switched on); a link that goes back gets its preview fetched again (pending, the watchdog);
coming out of the trash refuses (409) when the same link is saved again meanwhile, like the restore route."""
from ..core.access import live_sql
from ..core.errors import Denied
from ..core.i18n import tr
from ..core.objhooks import GONE
from ..core.undoareas import UA_DELETED, UA_RESTORED, ua_plain, ua_post, ua_pre
from ..core.undogroups import UG_LABEL
from ..core.undoweb import undo_need_reg
from ..core.writes import obj_track
from .bookmarks import bm_get, bm_need, bm_site, BM_SITE_MAX

BMU_KIND = "bookmark"
BMU_PREVIEW = {"site", "image", "image_mime", "image_url", "text", "preview", "preview_error", "fetched_at"}
BMU_WHAT = {"delete": UA_DELETED, "restore": UA_RESTORED}


def bmu_label(r):
    return UG_LABEL, [ua_plain(r.get("title") or r.get("url"), r.get("id"))]


obj_track(BMU_KIND, "bookmarks", undo_keep={"bookmarks": {"user_id", "src", "src_id", "kk_arch", *BMU_PREVIEW}},
          undo_nofp={"bookmarks": {"kk_arch", "deleted_by", *BMU_PREVIEW}}, undo_label=bmu_label,
          undo_free=("deleted_at", "deleted_by"))  # 2.947.0 (#5367): deleted_by of the core's trash, not in the fingerprint (steps of before keep theirs)
GONE[BMU_KIND] = "bookmarks"  # an account's deletion takes its history / undo rows (core/objhooks.py)


def bmu_pre(c, uid, bid, what=None):
    """The person's step before a write of bookmark bid (after its lock bookmarks-<id>); an agent records none."""
    r = c.execute("SELECT title, url FROM bookmarks WHERE id=?", (int(bid),)).fetchone()
    key = BMU_WHAT.get(what or "")
    ua_pre(c, uid, BMU_KIND, bid, *((key, ua_plain((r["title"] or r["url"]) if r else "", bid)) if key else ()))


def bmu_post(c):
    ua_post(c)


def bmu_need(c, uid, rid, oid):
    """Who may take a bookmark's step back now: write on it (in the trash or not), the bookmarks on for the person."""
    bm_need(c, uid)
    r = c.execute("SELECT * FROM bookmarks WHERE id=?", (int(rid),)).fetchone()
    if r is None:
        raise Denied(404)
    bm_get(c, uid, rid, write=True, deleted=r["deleted_at"] is not None)
    old_url = r["url"]

    def fix(c):
        n = c.execute("SELECT * FROM bookmarks WHERE id=?", (int(rid),)).fetchone()
        if n["deleted_at"] is None and c.execute(
                f"SELECT 1 FROM bookmarks WHERE user_id=? AND org_id IS NOT DISTINCT FROM ? AND url_key=? AND {live_sql()} AND id<>?", (n["user_id"], n["org_id"], n["url_key"], int(rid))).fetchone():
            raise Denied(409, tr("This link is already saved"))  # out of the trash / back to a link saved again meanwhile
        if n["url"] != old_url:  # the link's preview: the watchdog fetches it again (and removes the picture it replaces)
            c.execute("UPDATE bookmarks SET site=?, preview='pending', preview_error='', text='', image_url='' WHERE id=?",
                      (bm_site(n["url"])[:BM_SITE_MAX], int(rid)))
    return {"fix": fix, "lock": f"bookmarks-{int(rid)}"}


undo_need_reg(BMU_KIND, bmu_need)
