"""2.409.0 (#3490): areas switched on and off per workspace.

The module switches (user setting "features") stay the main switch of the whole account: off = off everywhere. Below it
  - every person switches areas off per own workspace (user setting "ws_areas_off", json {"private" | "org:<id>": [area]});
    in an organisation this only hides them for the person,
  - an organisation's admins switch areas off for all its members (orgs.areas_off, csv of area ids); the members cannot
    switch them on there, and the server refuses the routes of such an area while the organisation is the workspace the
    request works in (the setting "workspace", or the request's explicit space "org:<id>"; the office: its own area).
Switching off never deletes anything; switched on again everything is as before. The client decides what the views show
(areas.js wsa_*); "All workspaces" shows an area that is on in at least one workspace."""
import json
import re

from flask import g, request

from ..core.config import app
from ..core.db import db, usettings
from ..core.errors import BadInput, Denied
from ..core.i18n import N_, tr

# the areas that can be switched per workspace (the ids of MG_AREAS / SBB_RAIL in areas.js); review is private only
WSA_AREAS = ("office", "time", "review", "life", "reading", "ablage", "wiki", "sheets")
WSA_ORG_AREAS = tuple(a for a in WSA_AREAS if a != "review")  # what an organisation's admin may switch off
WSA_KEY_RE = re.compile(r"private|org:[1-9][0-9]{0,11}")
# the API paths of an area (prefix match on the path); only these are refused for an organisation that has the area off
WSA_PATHS = (("/api/office/", "office"), ("/api/time", "time"), ("/api/pomo", "time"), ("/api/life", "life"),
             ("/api/reading", "reading"), ("/api/feeds", "reading"), ("/api/bookmarks", "reading"),
             ("/api/files", "ablage"), ("/api/docs", "ablage"), ("/api/wiki", "wiki"), ("/api/sheets", "sheets"))
# an object of an organisation opened by its id (a link): its own organisation counts, whatever the workspace is
WSA_OBJ = (("wiki", re.compile(r"/api/wiki/pages/(\d+)"), "wiki_pages"), ("sheets", re.compile(r"/api/sheets/(\d+)"), "sheets"),
           ("reading", re.compile(r"/api/bookmarks/(\d+)"), "bookmarks"), ("ablage", re.compile(r"/api/files/nodes/(\d+)"), "fs_nodes"))
WSA_OFF_TEXT = N_("This area is switched off in this organisation by its admin.")


def wsa_clean_own(v):
    """The user setting ws_areas_off -> stored json {"private" | "org:<id>": [area, ...]}. Strict: an unknown workspace key
    or area is a 400; empty lists are dropped. A key of an organisation I left stays harmless (nothing reads it)."""
    bad = BadInput(tr("Invalid value: {0}", "ws_areas_off"))
    try:
        o = json.loads(v or "{}") if isinstance(v, str) else v
    except ValueError:
        raise bad from None
    if not isinstance(o, dict) or len(o) > 100:
        raise bad
    out = {}
    for k, xs in o.items():
        if not isinstance(k, str) or not WSA_KEY_RE.fullmatch(k) or not isinstance(xs, list) or len(xs) > len(WSA_AREAS):
            raise bad
        if any(x not in WSA_AREAS for x in xs):
            raise bad
        if xs:
            out[k] = sorted(set(xs), key=WSA_AREAS.index)
    return json.dumps(out, separators=(",", ":"))


def wsa_clean_org(v):
    """orgs.areas_off from a request ([area, ...] or csv) -> stored csv; an unknown area is a 400."""
    xs = v.split(",") if isinstance(v, str) else v
    if not isinstance(xs, list) or not all(isinstance(x, str) for x in xs):
        raise BadInput(tr("Invalid value: {0}", "areas_off"))
    xs = [x.strip() for x in xs if x.strip()]
    if any(x not in WSA_ORG_AREAS for x in xs):
        raise BadInput(tr("Invalid value: {0}", "areas_off"))
    return ",".join(sorted(set(xs), key=WSA_AREAS.index))


def wsa_org_off(c, oid):
    """The areas the admins of organisation oid switched off (a list; [] = all on)."""
    if not oid:
        return []
    cache = g.setdefault("wsa_org", {}) if _in_req() else {}
    if oid not in cache:
        r = c.execute("SELECT areas_off FROM orgs WHERE id=?", (oid,)).fetchone()
        cache[oid] = [x for x in ((r[0] if r else "") or "").split(",") if x in WSA_AREAS]
    return cache[oid]


def wsa_org_check(c, oid, area):
    """403 when the admins of organisation oid switched area off (the office calls it for the office area it resolved)."""
    if area in wsa_org_off(c, oid):
        raise Denied(403, tr(WSA_OFF_TEXT))


def _in_req():
    from flask import has_request_context
    return has_request_context()


def _req_org(c, uid, area):
    """The organisation a request works in: its explicit space ("org:<id>" / "private"; the knowledge pages also take the
    bare id) first, else the setting workspace; None = Private / All / not a member."""
    sp = request.args.get("space")
    if sp is None and request.is_json:
        b = request.get_json(silent=True)
        sp = b.get("space") if isinstance(b, dict) else None
    if isinstance(sp, int) and not isinstance(sp, bool):
        sp = str(sp)
    if area == "wiki" and isinstance(sp, str) and sp.isdigit():
        sp = "org:" + sp if sp != "0" else "private"
    ws = sp if isinstance(sp, str) and sp else str(usettings(c, uid).get("workspace") or "")
    m = re.fullmatch(r"org:(\d{1,12})", ws.strip())
    if not m:
        return None
    from .orgs import user_orgs
    oid = int(m.group(1))
    return oid if oid in user_orgs(c, uid) else None


@app.before_request
def wsa_gate():
    """The routes of an area its organisation's admins switched off answer 403 while that organisation is the workspace of
    the request. Agents (their tokens / the REST API) are untouched: what they see is what is shared with them."""
    p = request.path
    area = next((a for pre, a in WSA_PATHS if p.startswith(pre) and (pre.endswith("/") or len(p) == len(pre) or p[len(pre)] in "/?")), None)
    if area is None:
        return None
    u = getattr(g, "user", None)
    if u is None or ("kind" in u.keys() and u["kind"] == "agent") or g.get("auth_via") == "token":
        return None
    c = db()
    if area == "office":  # the office's own area (also "All" with one organisation); the person's own office is never off
        from ..office.model import office_on, office_where
        if not office_on(c, u["id"]):
            return None
        try:
            oid, _role = office_where(c, u["id"])
        except (BadInput, Denied):
            return None  # the route answers with its own text
        wsa_org_check(c, oid, area)
        return None
    for a, rx, table in WSA_OBJ:
        m = rx.match(p)
        if a == area and m:
            r = c.execute(f"SELECT org_id FROM {table} WHERE id=?", (int(m.group(1)),)).fetchone()  # noqa: S608 (fixed names)
            if r and r[0]:
                wsa_org_check(c, r[0], area)
                return None
    oid = _req_org(c, u["id"], area)
    if oid:
        wsa_org_check(c, oid, area)
    return None
