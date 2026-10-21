"""Home & life: the web API of the feeds (/api/feeds, life/rss.py). Only the person's own feeds; no agent, no API token."""
from flask import Response, jsonify, request

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, err
from ..accounts.session import me
from ..tasks.validation import as_int
from ..core.errors import BadInput
from ..life.rss import (
    RSS_OPML_MAX, rss_add, rss_delete, rss_feeds, rss_items, rss_later, rss_mark, rss_need, rss_opml_export, rss_opml_import,
    rss_restore,
)


def _done(c, out, code=200, state=False):
    if state:
        bump(c)  # a new task ("Read later")
    c.commit()
    return jsonify(out), code


@app.get("/api/feeds")
def feeds_get():
    """My feeds with their unread counts -> {feeds, unread, max}."""
    c, uid = db(), me()
    rss_need(c, uid)
    return jsonify(rss_feeds(c, uid))


@app.post("/api/feeds")
def feeds_post():
    """{url}: follow a feed (fetched once right away; refused with the reason when that fails) -> {feed, new}."""
    c, uid = db(), me()
    out = rss_add(c, uid, body())
    return _done(c, out, 201)


@app.delete("/api/feeds/<int:fid>")
def feeds_delete(fid):
    """Unfollow (undo: POST /api/feeds/<id>/restore)."""
    c, uid = db(), me()
    return _done(c, rss_delete(c, uid, fid))


@app.post("/api/feeds/<int:fid>/restore")
def feeds_restore(fid):
    c, uid = db(), me()
    return _done(c, rss_restore(c, uid, fid))


@app.get("/api/feeds/items")
def feeds_items():
    """?feed=<id>&unread=1&offset=n: the articles, newest first -> {items, more, unread}."""
    c, uid = db(), me()
    a = request.args
    feed = as_int(a["feed"], "feed", 1) if a.get("feed") else None
    off = as_int(a.get("offset") or 0, "offset", 0, 100000)
    return jsonify(rss_items(c, uid, feed, a.get("unread") in ("1", "true"), off))


@app.post("/api/feeds/read")
def feeds_read():
    """{ids?, feed_id?, read}: mark articles read / unread (without ids: all unread ones) -> {ids}."""
    c, uid = db(), me()
    return _done(c, rss_mark(c, uid, body()))


@app.post("/api/feeds/items/<int:iid>/later")
def feeds_later(iid):
    """"Read later": a task in my reading list (only once per article) -> {task_id, list_id, created}."""
    c, uid = db(), me()
    out = rss_later(c, uid, iid)
    return _done(c, out, 201 if out["created"] else 200, state=out["created"])


@app.get("/api/feeds/opml")
def feeds_opml_get():
    """My feeds as an OPML file (download)."""
    c, uid = db(), me()
    return Response(rss_opml_export(c, uid), mimetype="text/x-opml",
                    headers={"Content-Disposition": 'attachment; filename="kalmido-feeds.opml"', "Cache-Control": "no-store"})


@app.post("/api/feeds/opml")
def feeds_opml_post():
    """An OPML file (multipart "file") -> {added, skipped, errors}; the new feeds are fetched in the background."""
    c, uid = db(), me()
    rss_need(c, uid)
    f = request.files.get("file")
    if not f:
        return err(tr("No file"))
    raw = f.read(RSS_OPML_MAX + 1)
    try:
        out = rss_opml_import(c, uid, raw)
    except BadInput as e:
        return err(str(e))
    return _done(c, out)
