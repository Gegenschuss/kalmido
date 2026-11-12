"""2.1026.0 (#5280, stage Q6c of the cross-cutting core, analysis #3563, decided 08.11.2026 / 09.11.2026): the ONE registry of
the searches and the one route of each side -- GET /api/search (the web) and GET /api/v1/search (tokens, agents).

Every area search registers its kind here (srch_register, at import of the area's module): what one search finds in the
area's own search field, the command palette's "Everywhere" finds too (decision of 09.11.2026), because both run the same
function. The routes /api/search/messages, /api/files/search, /api/wiki/search and /api/v1/files/search went with the stage
(no second way): ?kind= picks the area, its answer is the answer of the old route.

- web(): the answer of ?kind=<kind> (the area's own shape, from request.args).
- group(c, uid, q, n): at most n hits of the kind for the palette (`groups` of the first page of GET /api/search); the same
  entries the kind's own answer lists.
- v1(): the answer of GET /api/v1/search?kind=<kind>; v1group(c, uid, q, n): the kind's part of ?kind=all.
- scope: the token scope a kind needs on /api/v1/search (contacts, files:read, wiki:read, calendar); a token without it gets
  403 for the kind and no part of ?kind=all.
- gate: the path whose module / workspace switches cover the kind (accounts/modcards.py mc_gate, accounts/wsareas.py
  wsa_gate) -- the old route's path, so a switched-off area answers 403 as before (and is left out of the groups).
- office: never for agents or the API (question 16): it registers no v1.

Where the texts are: open texts -> obj_search (core/objsearch.py), sealed texts -> obj_search_words (core/objwords.py),
end-to-end -> the browser (static/js/ftsearch.js SEARCH_SOURCES: the server's answer plus the sources of the locked areas).
The rights stay each area's own (the registered functions check them per hit); this module only routes.
"""
from flask import g, jsonify, request

from .config import app
from .ctx import me
from .db import db
from .errors import BadInput, Denied
from .i18n import tr
from ..api.common import v1_view

SEARCH_KINDS = {}
# filled by the higher layers when they load (the pattern of core/objhooks.py, no upward import):
#   gates        accounts/modcards.py mc_gate, accounts/wsareas.py wsa_gate -- f(path) raises Denied for a switched-off area
#   scope_label  api/scopes.py -- f(scope) -> the scope's readable name
#   task_ids     core/objsearch.py osr_ids_sql -- for a reader below the domain layer (accounts/orgtasks.py)
SRCH_HOOKS = {"gates": [], "scope_label": lambda s: s, "task_ids": None}
SRCH_GROUP = 5          # hits per kind in the palette's groups (?glimit=, 1..20)
SRCH_GROUP_MAX = 20


def srch_register(kind, *, web=None, group=None, v1=None, v1group=None, scope=None, gate=None, order=None):
    """Register the search of kind (see the module's text); a second call of the same kind adds the parts it names (the web
    and the API side of an area may stand in two modules)."""
    s = SEARCH_KINDS.setdefault(kind, {"web": None, "group": None, "v1": None, "v1group": None, "scope": "read", "gate": None, "order": 50})
    for k, v in (("web", web), ("group", group), ("v1", v1), ("v1group", v1group), ("scope", scope), ("gate", gate), ("order", order)):
        if v is not None:
            s[k] = v


def _ordered(field):
    return [k for k, s in sorted(SEARCH_KINDS.items(), key=lambda x: (x[1]["order"], x[0])) if s.get(field)]


def srch_gate(kind):
    """Denied when the module / workspace switches of the kind's area refuse the person (the old route's before_request)."""
    p = SEARCH_KINDS[kind].get("gate")
    if not p:
        return
    for gate in SRCH_HOOKS["gates"]:
        r = gate(p)
        if r is not None:  # a gate that answers instead of raising
            raise Denied(403)


def srch_q(a, key="q"):
    q = (a.get(key) or "").strip()
    if not q or len(q) > 200:
        raise BadInput(tr("Invalid value: {0}", "q"))
    return q


def _glimit(a):
    try:
        n = int(a.get("glimit") or SRCH_GROUP)
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "glimit")) from None
    return max(1, min(SRCH_GROUP_MAX, n))


def srch_groups(c, uid, q, n, field="group", skip=("tasks",), scopes=None):
    """{kind: [hits]} of every registered kind with hits (not those in skip); a kind the person may not reach (switched off,
    no right, a token without the scope) is left out quietly."""
    out = {}
    for kind in _ordered(field):
        if kind in skip:
            continue
        s = SEARCH_KINDS[kind]
        if scopes is not None and s["scope"] not in scopes:
            continue
        try:
            if field == "group":
                srch_gate(kind)
            hits = s[field](c, uid, q, n)
        except (Denied, BadInput):
            continue
        if hits:
            out[kind] = list(hits)[:n]
    return out


def _err(e):
    if isinstance(e, Denied):
        return jsonify(error=e.text()), e.code
    return jsonify(error=str(e)), 400


@app.get("/api/search")
def srch_web():
    """?q, kind (default tasks) -- the one search route of the web. kind=tasks: {hits, next} and on the first page (no cursor)
    groups: {kind: [hits]} of every other kind with hits (at most ?glimit, default 5). Any other kind: that area's answer."""
    a = request.args
    kind = a.get("kind") or "tasks"
    s = SEARCH_KINDS.get(kind)
    if s is None or s["web"] is None:
        return jsonify(error=tr("Invalid value: {0}", "kind")), 400
    try:
        srch_gate(kind)
        r = s["web"]()
        if kind != "tasks" or a.get("cursor") or not isinstance(r, dict):
            return r if not isinstance(r, dict) else jsonify(r)
        groups = srch_groups(db(), me(), srch_q(a), _glimit(a))
    except (Denied, BadInput) as e:
        return _err(e)
    return jsonify({**r, **({"groups": groups} if groups else {})})


def srch_v1():
    """GET /api/v1/search: ?kind = tasks (default) | messages | contacts | notes | files | wiki | events | all (scope=messages
    stays the older name of kind=messages). all: {groups: {kind: [at most ?limit (default 5) entries]}} of the kinds the
    token may read; never the office (question 16)."""
    a = request.args
    if a.get("scope") not in (None, "", "tasks", "messages"):  # review 2.1026 F3: an unknown scope stays a 400
        raise BadInput(tr("Invalid value: {0}", "scope"))
    kind = a.get("kind") or ("messages" if a.get("scope") == "messages" else "tasks")
    tok = g.get("auth_via") == "token"
    scopes = set(g.get("scopes") or ()) if tok else None
    if kind == "all":
        extra = sorted(k for k in a if k not in ("q", "kind", "limit"))
        if extra:
            raise BadInput(tr("Unknown parameter: {0}", ", ".join(extra)[:200]))
        try:
            n = max(1, min(SRCH_GROUP_MAX, int(a.get("limit") or SRCH_GROUP)))
        except ValueError:
            raise BadInput(tr("Invalid value: {0}", "limit")) from None
        return jsonify(groups=srch_groups(db(), me(), srch_q(a), n, field="v1group", skip=(), scopes=scopes))
    s = SEARCH_KINDS.get(kind)
    if s is None or s["v1"] is None:
        raise BadInput(tr("Invalid value: {0}", "kind"))
    if tok and s["scope"] not in scopes:
        e = Denied(403, tr("This token lacks the permission “{0}”", SRCH_HOOKS["scope_label"](s["scope"])))
        e.v1_extra = {"required_scope": s["scope"]}
        raise e
    g.srch_kind = kind  # api/common.py v1_args: the area's own handler accepts kind / scope beside its parameters
    try:
        return s["v1"]()
    finally:
        g.pop("srch_kind", None)  # review 2.1026 F2: never beyond this call (in-process calls may share g)


app.add_url_rule("/api/v1/search", "v1_search", v1_view(srch_v1), methods=["GET"])
