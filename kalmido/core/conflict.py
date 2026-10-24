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
