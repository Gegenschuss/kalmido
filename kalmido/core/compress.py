"""2.65.0 (#1505): JSON answers of the app go out gzip-compressed when the browser accepts it (GET /api/state with many tasks:
a few MB of JSON shrink to a few hundred KB). Python's own gzip, no extra package.

Only JSON (application/json) from 1 KB on, never file downloads, streams (SSE) or answers that already carry a
Content-Encoding (a reverse proxy that compresses itself sees the header and leaves the answer alone), never HEAD, 204 or 304.
Registered before core.pages, so this hook runs after every other after_request hook (Flask calls them in reverse order):
they all see the plain answer."""
import gzip

from flask import request

from ..core.config import app

ST_GZIP_MIN = 1024  # bytes: smaller answers stay plain (gzip would barely help)
ST_GZIP_LEVEL = 5   # speed / size balance (level 9 costs much more time for a few per cent)


@app.after_request
def st_gzip(resp):
    if (request.method == "HEAD" or resp.status_code in (204, 304) or resp.status_code < 200 or resp.direct_passthrough
            or resp.is_streamed or resp.mimetype != "application/json" or "Content-Encoding" in resp.headers
            or "ETag" in resp.headers or request.accept_encodings["gzip"] <= 0):
        return resp
    data = resp.get_data()
    if len(data) < ST_GZIP_MIN:
        return resp
    resp.set_data(gzip.compress(data, ST_GZIP_LEVEL, mtime=0))
    resp.headers["Content-Encoding"] = "gzip"
    resp.vary.add("Accept-Encoding")
    return resp
