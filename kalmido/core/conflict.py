"""2.269.0 C (#3017): the version check of the dialogs that save a whole object (client, master data, letter, budget, journal).
The body may carry expect_updated_at (the updated_at the client got last); set and different -> 409 with the current state
under its own key, like the wiki pages (wiki_update). Missing -> the old behaviour (agents, the API, old clients)."""
from flask import jsonify

from .config import app
from .errors import Denied
from .i18n import tr
from .pg import system_ctx, ts_canon  # 2.657.0 (#5052): kern_version_seed; 2.760.0 (#5311): ts_canon


class Conflict(Denied):
    """409 {"error", <key>: the current state}; the API answers code conflict (api/common.py v1_view reads v1_name)."""
    v1_name = "conflict"

    def __init__(self, key, cur, who=None, msg=None):
        super().__init__(409, msg or (tr("Changed in the meantime by {0}", who) if who else tr("Changed in the meantime")))
        self.key, self.cur = key, cur
        self.v1_extra = {"current": cur}  # 2.564.0 (#4702): the API's answer (v1_view) carries the current state too, as core/objweb.py


@app.errorhandler(Conflict)
def conflict_answer(e):
    return jsonify(error=e.text(), **{e.key: e.cur}), 409


def ccf_check(b, have, key, cur):
    """Call after write_lock(c, "<table>-<id>") and reading the row. b = the request body; have = the row's updated_at now;
    cur = a function -> the current state for the answer. 2.760.0 (#5311): both sides in the canonical form (pg.py ts_canon), so
    a TIMESTAMPTZ column and a TEXT one compare alike and the same instant written with Z or another offset is no conflict."""
    exp = b.get("expect_updated_at") if isinstance(b, dict) else None
    if exp and ts_canon(str(exp)) != ts_canon(have):
        raise Conflict(key, cur())


class VersionRequired(Denied):
    """2.564.0 (#4702): 400 {"error": {"code": "version_required", "message", "fields": [...]}} - an agent wrote without
    saying which version it read (the app always sends one; a person's change made after the agent read must not vanish
    silently)."""
    v1_name = "version_required"

    def __init__(self, fields, msg=None):  # msg: an own text (core/writes.py NEED_VERSION)
        super().__init__(400, msg or tr("Send the version you read: {0}", " / ".join(fields)))
        self.v1_extra = {"fields": list(fields)}


@app.errorhandler(VersionRequired)
def version_required_answer(e):
    return jsonify(error={"code": "version_required", "message": e.text(), "fields": e.v1_extra["fields"]}), 400


def need_version(b, *fields, header=True):
    """2.564.0 (#4702): the version check is required for agent accounts (g.user.kind == 'agent') on the write paths of
    /api/v1 and MCP. b = the request body (or a dict of the parameters that may carry a version); fields = the keys that
    carry one ("expect_updated_at", "_prev", "expect_rev" ...); header = the header If-Match counts too. People's tokens
    and the app stay as they were (old clients). Call it before the write; raises VersionRequired when nothing is given."""
    from flask import request
    if not version_rule():
        return
    # review 2.564.0: an empty _prev {} / [] says nothing about what was read -> as if missing
    if isinstance(b, dict) and any(b.get(k) not in (None, "") and b.get(k) != {} and b.get(k) != [] for k in fields):
        return
    if header and (request.headers.get("If-Match") or "").strip():
        return
    raise VersionRequired(fields + (("If-Match",) if header else ()))


def agent_account(u):
    """2.564.0 (#4702): u (a users row) is an agent account - the same test as agents.core.is_agent, here in the core so
    lower layers (core, tasks) need no upward import."""
    try:
        return bool(u) and (u["kind"] or "user") == "agent"
    except (KeyError, IndexError, TypeError):
        return False


def version_rule():
    """2.564.0 (#4702): True when the current request must carry a version: an agent account, or an agent acting as a
    person in the office (g.ofa_agent; office/agentdocs.py _as_person swaps g.user)."""
    from flask import g, has_request_context
    return has_request_context() and bool(agent_account(getattr(g, "user", None)) or g.get("ofa_agent"))


def take_version(b, key="expect_updated_at"):
    """2.564.0 (#4702): the version an API client read, under the name the area's own check reads (key): the body's key,
    expect_updated_at or the header If-Match (W/"..." stripped). Agents must send one of them (need_version). Returns b."""
    from flask import has_request_context, request
    need_version(b, *dict.fromkeys((key, "expect_updated_at")))
    if not isinstance(b, dict):
        return b
    alt = b.pop("expect_updated_at", None) if key != "expect_updated_at" else None
    if b.get(key) in (None, "") and alt not in (None, ""):
        b[key] = alt
    if b.get(key) in (None, "") and has_request_context():
        h = (request.headers.get("If-Match") or "").strip().removeprefix("W/").strip('"')
        if h:
            b[key] = h
    return b


KERN_SEED_TABLES = ("ev_cals", "books", "lists")  # 2.657.0 (#5052): the kinds whose old rows may still carry updated_at '' (lists: 5052_a.py)


def kern_version_seed(c, table, rid):
    """2.657.0 (#5052): a calendar / address book made before 2.566.0 (#4712) has updated_at '' (no version yet): its read shows
    created_at as its version (events/model.py cal_public, contacts/model.py book_public), so here -- under the object's
    write_lock, before the version check -- that row gets created_at as its updated_at. Returns the row."""
    if table not in KERN_SEED_TABLES:
        raise ValueError(table)
    with system_ctx(c):  # structure only (a copy of the row's own created_at): also for a member who may not write the row
        c.execute(f"UPDATE {table} SET updated_at=created_at WHERE id=? AND (updated_at IS NULL OR CAST(updated_at AS text)='')", (int(rid),))  # 2.1095.0 (#5306): TEXT or TIMESTAMPTZ
    return c.execute(f"SELECT * FROM {table} WHERE id=?", (int(rid),)).fetchone()  # the caller holds the write_lock
