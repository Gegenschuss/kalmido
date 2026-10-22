"""Reading: the web API of the feeds (/api/feeds, life/rss.py). The person's own feeds or (2.172.0 B, #2677) those of an
organisation (?space= / {space}: private | org:<id>, default private); no agent, no API token."""
from flask import Response, jsonify, request

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, err
from ..accounts.session import me
from ..tasks.validation import as_int
from ..core.errors import BadInput
from ..life.rss import (
    RSS_OPML_MAX, rss_add, rss_delete, rss_feeds, rss_items, rss_later, rss_mark, rss_need, rss_opml_export, rss_opml_import,
    rss_restore, rss_space,
)


def _done(c, out, code=200, state=False):
    if state:
        bump(c)  # a new task ("Read later")
    c.commit()
    return jsonify(out), code


@app.get("/api/feeds")
def feeds_get():
    """?space=: the feeds of a space with their unread counts -> {feeds, unread, max, space, manage}."""
    c, uid = db(), me()
    rss_need(c, uid)
    return jsonify(rss_feeds(c, uid, rss_space(c, uid, request.args.get("space"))))


@app.post("/api/feeds")
def feeds_post():
    """{url, space?}: follow a feed (fetched once right away; refused with the reason when that fails) -> {feed, new}."""
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
    """?space=&feed=<id>&unread=1&offset=n: the articles of a space, newest first -> {items, more, unread, space}."""
    c, uid = db(), me()
    a = request.args
    rss_need(c, uid)
    oid = rss_space(c, uid, a.get("space"))
    feed = as_int(a["feed"], "feed", 1) if a.get("feed") else None
    off = as_int(a.get("offset") or 0, "offset", 0, 100000)
    return jsonify(rss_items(c, uid, feed, a.get("unread") in ("1", "true"), off, oid))


@app.post("/api/feeds/read")
def feeds_read():
    """{ids?, feed_id?, read, space?}: mark articles read / unread (without ids: all unread ones) -> {ids}."""
    c, uid = db(), me()
    return _done(c, rss_mark(c, uid, body()))


@app.post("/api/feeds/items/<int:iid>/later")
def feeds_later(iid):
    """"Read later": a task in the read-later project of the article's space (only once per article) -> {task_id, list_id,
    created, space}."""
    c, uid = db(), me()
    out = rss_later(c, uid, iid)
    return _done(c, out, 201 if out["created"] else 200, state=out["created"])


@app.get("/api/feeds/opml")
def feeds_opml_get():
    """?space=: the feeds of a space as an OPML file (download)."""
    c, uid = db(), me()
    rss_need(c, uid)
    return Response(rss_opml_export(c, uid, rss_space(c, uid, request.args.get("space"))), mimetype="text/x-opml",
                    headers={"Content-Disposition": 'attachment; filename="kalmido-feeds.opml"', "Cache-Control": "no-store"})


@app.post("/api/feeds/opml")
def feeds_opml_post():
    """An OPML file (multipart "file", field "space") -> {added, skipped, errors}; the new feeds are fetched in the background."""
    c, uid = db(), me()
    rss_need(c, uid)
    oid = rss_space(c, uid, request.form.get("space"), write=True)
    f = request.files.get("file")
    if not f:
        return err(tr("No file"))
    raw = f.read(RSS_OPML_MAX + 1)
    try:
        out = rss_opml_import(c, uid, raw, oid)
    except BadInput as e:
        return err(str(e))
    return _done(c, out)
