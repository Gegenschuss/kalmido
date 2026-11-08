"""2.674.0 (#4190): the size limit of JSON request bodies.

The request limit of the app (core/config.py MAX_CONTENT_LENGTH) is made for uploads (several files at once); a JSON body
that large would be read and parsed into memory in one piece. So a request whose body is JSON (Content-Type
application/json or ...+json) may carry at most JSON_MAX bytes - 413 with a plain text before the body is read. The few
routes that take larger JSON on purpose stand in JSON_BIG with their own limit (never above MAX_CONTENT_LENGTH).
Uploads (multipart, application/octet-stream, text/calendar, ...) are not JSON and keep their own limits.
Registered right after core.errors (kalmido/__init__.py ORDER): its hook runs before every hook that reads the body.
"""
from flask import request

from .config import app, MAX_FILE_MB
from .db import err
from .i18n import tr

JSON_MAX_MB = 10
JSON_MAX = JSON_MAX_MB * 1024 * 1024
_MB = 1024 * 1024

# (method, URL rule) -> bytes: the routes with a larger JSON body on purpose (tests/p2674_a_exports_test.py checks every rule exists)
JSON_BIG = {
    # a document as content_base64 (docs/v1.py: up to TASKS_MAX_FILE_MB, base64 is a third larger)
    ("POST", "/api/v1/documents"): MAX_FILE_MB * _MB * 4 // 3 + _MB,
    # a file / a new version as content or content_base64 (files/v1.py V1_TEXT_MAX = 20 MB, base64 a third larger)
    ("POST", "/api/v1/files"): 28 * _MB,
    ("POST", "/api/v1/files/<int:nid>/versions"): 28 * _MB,
    # a repository host's webhook (integrations/git.py GIT_HOOK_MAX_BYTES: GitHub sends up to 25 MB)
    ("POST", "/api/hooks/git/<int:cid>"): 26 * _MB,
    # switching the end-to-end encryption on / off: up to 200 encrypted texts / pages per call (collab/liste2e.py,
    # wiki/wikie2e.py); the browser does not split by bytes, so these keep the app's request limit
    ("POST", "/api/lists/<int:lid>/e2e/bulk"): None,
    ("POST", "/api/wiki/e2e/bulk"): None,
}


def jl_cap(method, rule):
    """The JSON limit in bytes of a route (None in JSON_BIG = the app's request limit), never above the app's limit."""
    app_max = app.config.get("MAX_CONTENT_LENGTH") or 0
    cap = JSON_BIG.get((method, rule), JSON_MAX) or app_max or JSON_MAX
    return min(cap, app_max) if app_max else cap


@app.before_request
def jl_guard():
    """413 for a JSON body above the route's limit; a body without a length (chunked) is cut there by werkzeug (413)."""
    if not request.is_json:
        return None
    cap = jl_cap(request.method, request.url_rule.rule if request.url_rule is not None else "")
    if (request.content_length or 0) > cap:
        return err(tr("The request is too large (at most {0} MB)", max(1, cap // _MB)), 413)
    request.max_content_length = min(request.max_content_length or cap, cap)
    return None
