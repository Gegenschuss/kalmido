"""2.269.0 C (#3017): the version check of the dialogs that save a whole object (client, master data, letter, budget, journal).
The body may carry expect_updated_at (the updated_at the client got last); set and different -> 409 with the current state
under its own key, like the wiki pages (wiki_update). Missing -> the old behaviour (agents, the API, old clients)."""
from flask import jsonify

from .config import app
from .errors import Denied
from .i18n import tr


class Conflict(Denied):
    """409 {"error", <key>: the current state}; the API answers code conflict (api/common.py v1_view reads v1_name)."""
    v1_name = "conflict"

    def __init__(self, key, cur, who=None):
        super().__init__(409, tr("Changed in the meantime by {0}", who) if who else tr("Changed in the meantime"))
        self.key, self.cur = key, cur


@app.errorhandler(Conflict)
def conflict_answer(e):
    return jsonify(error=e.text(), **{e.key: e.cur}), 409


def ccf_check(b, have, key, cur):
    """Call after write_lock(c, "<table>-<id>") and reading the row. b = the request body; have = the row's updated_at now;
    cur = a function -> the current state for the answer."""
    exp = b.get("expect_updated_at") if isinstance(b, dict) else None
    if exp and str(exp) != str(have or ""):
        raise Conflict(key, cur())


class VersionRequired(Denied):
    """2.564.0 (#4702): 400 {"error": {"code": "version_required", "message", "fields": [...]}} - an agent wrote without
    saying which version it read (the app always sends one; a person's change made after the agent read must not vanish
    silently)."""
    v1_name = "version_required"

    def __init__(self, fields):
        super().__init__(400, tr("Send the version you read: {0}", " / ".join(fields)))
        self.v1_extra = {"fields": list(fields)}


@app.errorhandler(VersionRequired)
def version_required_answer(e):
    return jsonify(error={"code": "version_required", "message": e.text(), "fields": e.v1_extra["fields"]}), 400


def need_version(b, *fields, header=True):
    """2.564.0 (#4702): the version check is required for agent accounts (g.user.kind == 'agent') on the write paths of
    /api/v1 and MCP. b = the request body (or a dict of the parameters that may carry a version); fields = the keys that
    carry one ("expect_updated_at", "_prev", "expect_rev" ...); header = the header If-Match counts too. People's tokens
    and the app stay as they were (old clients). Call it before the write; raises VersionRequired when nothing is given."""
    from flask import g, has_request_context, request
    from ..agents.core import is_agent
    if not has_request_context() or not is_agent(getattr(g, "user", None)):
        return
    if isinstance(b, dict) and any(b.get(k) not in (None, "") for k in fields):
        return
    if header and (request.headers.get("If-Match") or "").strip():
        return
    raise VersionRequired(fields + (("If-Match",) if header else ()))
