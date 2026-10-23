"""2.187.0 (#2476): office access rights -- groups (roles) with a level per office area.

    level    none | own | view | edit | manage   (own = only the person's own entries, in the areas with AREA_OWN)
    special  release (finalise + send invoices), pay (approve payments / bank), lock (lock periods), export (tax adviser /
             tax auditor exports), rights (manage the office rights of the others; never an agent)

One list of areas (OFFICE_AREAS) is the source for the checks, the rights page and the office menu (static/js/areas.js
OFM_ITEMS keys = area keys; tests/p2187_rights_guard_test.py: every /api/office route has an area, every office menu point
too). A person is in groups: built-in templates (TEMPLATES, fixed) and the organisation's own copies (office_rgroups);
the highest level of all groups counts, specials add up.

Who is not ruled by groups (the checks stay exactly as before 2.187):
- the organisation's admins (they always see everything: nobody can lock them out) and the owner of a personal office;
- an org member without any row in office_rgroup_members: the implicit group "Previous access" (TPL_LEGACY) -- an update
  changes nothing, restricting is done afterwards in the rights page.
Agents: no row = no office access (they start without one), never the special "rights".
The organisation role still caps everything (orgroles.office_allowed: guests nothing, read-only / accounting only read).

The check runs twice on the server: ofr_gate (before_request, every /api/office/* route by its path, also the routes that
resolve their area on their own) and office_org (model.py: the admin=True routes let a group with the level through).
Every change of a group or a membership is written to office_rights_log (who, whom, when, before / after)."""
import json

from flask import g, has_request_context, jsonify, request

from ..core.config import app
from ..core.db import body, db, iso, now_utc
from ..core.errors import BadInput, Denied
from ..core.i18n import N_, tr
from ..core.pg import insert_id, system_ctx
from ..accounts.orgs import org_role
from ..accounts.orgroles import office_allowed
from .model import office_gate, office_on, office_where, pb_owner

LEVELS = ("none", "own", "view", "edit", "manage")
LV = {k: i for i, k in enumerate(LEVELS)}
SPECIALS = (("release", N_("Finalise and send invoices")), ("pay", N_("Approve payments and bank")),
            ("lock", N_("Lock periods")), ("export", N_("Exports for tax adviser and tax auditor")),
            ("rights", N_("Manage office rights")))
SPECIAL_KEYS = tuple(k for k, _ in SPECIALS)

# key, name, menu group, path segments under /api/office/ (longest match wins), own (level "own" offered),
# legacy: what an org member had before 2.187 ("member" = the routes without the admin check, "admin" = none)
OFFICE_AREAS = (
    ("pipeline", N_("Pipeline"), "sell", ("deals", "leads"), False, "admin"),
    ("offers", N_("Quotes & invoices"), "sell", ("docs", "series", "signoffs", "number-preview", "trial", "mail-status",
                                                  "peppol", "undo", "catalog", "clients", "roles", "crew", "sets"), False, "member"),
    ("time", N_("Times to bill"), "sell", ("time-open",), True, "member"),
    ("gendocs", N_("Documents"), "sell", ("gen-docs", "doc-templates", "privacy-sheets"), False, "admin"),
    ("letters", N_("Correspondence"), "sell", ("letters", "letter-blocks"), False, "admin"),
    ("contracts", N_("Framework contracts"), "sell", ("contracts",), False, "member"),
    ("cashflow", N_("Cash flow"), "money", ("cashflow", "fixed-costs", "tax-dates"), False, "admin"),
    ("kpi", N_("Figures"), "money", ("kpi",), False, "admin"),
    ("bank", N_("Bank"), "money", ("bank", "pay-props"), False, "admin"),
    ("books", N_("Bookkeeping"), "money", ("books", "datev", "periods", "gobd", "procdoc"), False, "admin"),
    ("receipts", N_("Receipts"), "money", ("books/receipts", "receipts"), True, "admin"),
    ("subs", N_("Subscriptions & tools"), "money", ("subs",), False, "admin"),
    ("travel", N_("Travel expenses"), "money", ("trips",), True, "admin"),
    ("logbook", N_("Logbook"), "money", ("drives", "vehicles", "logbook"), True, "admin"),
    ("meals", N_("Entertainment receipts"), "money", ("meals",), True, "admin"),
    ("cashbook", N_("Cash book"), "money", ("cashbooks", "cashbook", "cash-entries"), False, "admin"),
    ("services", N_("Services"), "admin", ("services",), False, "member"),
    ("equipment", N_("Equipment"), "admin", ("equipment",), False, "member"),
    ("texts", N_("Text blocks"), "admin", ("texts",), False, "member"),
    ("agreements", N_("Contracts & insurance"), "admin", ("agreements",), False, "admin"),
    ("settings", N_("Settings"), "admin", ("settings", "logo", "packs", "pack-switch", "number-ranges", "terms",
                                           "letterhead", "import", "export", "legacy", "move", "move-space", "agents", "log"),
     False, "member"),
)
AREA_KEYS = tuple(a[0] for a in OFFICE_AREAS)
AREA_OWN = frozenset(a[0] for a in OFFICE_AREAS if a[4])
AREA_LEGACY = {a[0]: a[5] for a in OFFICE_AREAS}
SELL = tuple(a[0] for a in OFFICE_AREAS if a[2] == "sell")
MONEY = tuple(a[0] for a in OFFICE_AREAS if a[2] == "money")
ADMIN = tuple(a[0] for a in OFFICE_AREAS if a[2] == "admin")
_SEG = sorted(((s, a[0]) for a in OFFICE_AREAS for s in a[3]), key=lambda x: -len(x[0]))

# routes every person with any office access reads (the office's settings carry the person's rights, the menu needs them)
ANY_READ = frozenset({"/api/office/settings", "/api/office/number-preview", "/api/office/mail-status"})
# routes whose writes need "manage" of their area ("the area's settings"); everything else writes with "edit"
MANAGE_ROUTES = frozenset({
    "/api/office/settings", "/api/office/logbook/settings", "/api/office/trips/purposes", "/api/office/trips/vma-rates",
    "/api/office/equipment/policies", "/api/office/cashflow/start", "/api/office/letters/profile",
    # 2.187.0 B (#2476): the set-up of the areas (purposes, vehicles, cash books, e-invoice transmission, tax dates, process doc)
    "/api/office/trips/purposes/<int:pid>", "/api/office/letters/profile/image", "/api/office/vehicles",
    "/api/office/vehicles/<int:vid>", "/api/office/cashbooks", "/api/office/cashbooks/<int:bid>", "/api/office/peppol",
    "/api/office/peppol/check", "/api/office/tax-dates", "/api/office/procdoc",
})
# routes whose reading needs "manage" too: the whole office log (every area's before / after) and the master data export
MANAGE_READ = frozenset({"/api/office/log", "/api/office/export"})
# "METHOD rule" -> the special a group needs for it (on top of the area's level). 2.187.0 B (#2476)
SPECIAL_ROUTES = {
    # release: finalise, take back, send (mail, e-invoice network, the DATEV inbox counts as export), make a series' invoice now
    "POST /api/office/docs/<int:did>/finalize": "release", "POST /api/office/docs/<int:did>/unlock": "release",
    "POST /api/office/docs/<int:did>/send": "release", "POST /api/office/docs/<int:did>/peppol": "release",
    "POST /api/office/series/<int:sid>/run": "release",
    # pay: payments of invoices, reminder fees, payment proposals, the bank matching that books
    "POST /api/office/docs/<int:did>/payments": "pay", "DELETE /api/office/docs/<int:did>/payments/<int:pid>": "pay",
    "POST /api/office/docs/<int:did>/fee": "pay", "POST /api/office/pay-props/<int:pid>": "pay",
    "POST /api/office/bank/tx/<int:tid>/match": "pay", "POST /api/office/bank/tx/<int:tid>/unmatch": "pay",
    # lock: periods, the cash book's daily closing, the logbook's month
    "POST /api/office/periods/lock": "lock", "POST /api/office/cashbooks/<int:bid>/closing": "lock",
    "POST /api/office/logbook/close": "lock",
    # export: the files for the tax adviser / tax auditor
    "GET /api/office/datev/extf": "export", "GET /api/office/datev/zip": "export", "GET /api/office/gobd/export": "export",
    "GET /api/office/books/export": "export", "GET /api/office/books/euer.csv": "export", "GET /api/office/books/euer.pdf": "export",
    "GET /api/office/books/receipts.csv": "export", "GET /api/office/books/receipts.zip": "export",
    "GET /api/office/cashbook.csv": "export", "GET /api/office/cashbook.pdf": "export", "GET /api/office/logbook.csv": "export",
    "GET /api/office/logbook.pdf": "export", "GET /api/office/trips/vma.csv": "export", "GET /api/office/trips/vma.xlsx": "export",
    "GET /api/office/trips/vma.pdf": "export", "GET /api/office/equipment/value.csv": "export",
    "GET /api/office/equipment/value.pdf": "export", "GET /api/office/subs.csv": "export", "GET /api/office/procdoc.md": "export",
    "GET /api/office/procdoc.pdf": "export", "POST /api/office/docs/<int:did>/datev": "export",
}
# "METHOD rule" of the areas with AREA_OWN that filter to the person's own entries when the level is "own" (g.ofr_own);
# every other route of such an area needs "view" / "edit" (fail closed: a route that does not filter never sees "own").
# 2.187.0 B (#2476): reports, exports and billing are never "own"; the meals' choices: only the person's own (review)
OWN_ROUTES = {
    "GET /api/office/books/receipts", "GET /api/office/time-open",
    "GET /api/office/trips", "POST /api/office/trips", "PATCH /api/office/trips/<int:tid>", "DELETE /api/office/trips/<int:tid>",
    "POST /api/office/trips/<int:tid>/items", "PATCH /api/office/trips/<int:tid>/items/<int:iid>",
    "DELETE /api/office/trips/<int:tid>/items/<int:iid>", "GET /api/office/trips/purposes",
    "GET /api/office/vehicles", "GET /api/office/drives", "POST /api/office/drives", "PATCH /api/office/drives/<int:did>",
    "DELETE /api/office/drives/<int:did>", "POST /api/office/drives/<int:did>/restore", "GET /api/office/drives/<int:did>/log",
    "GET /api/office/meals", "GET /api/office/meals/choices", "GET /api/office/meals/<int:mid>", "POST /api/office/meals",
    "PATCH /api/office/meals/<int:mid>", "DELETE /api/office/meals/<int:mid>", "POST /api/office/meals/<int:mid>/restore",
    "POST /api/office/meals/<int:mid>/approve", "POST /api/office/meals/<int:mid>/file",
    "GET /api/office/meals/<int:mid>/file/<int:fid>", "DELETE /api/office/meals/<int:mid>/file/<int:fid>",
    "POST /api/office/meals/<int:mid>/file/<int:fid>/restore", "GET /api/office/meals/<int:mid>/pdf",
}

TPL_LEGACY = "legacy"
TPL_NONE = "none"


def _all(lv):
    return {k: lv for k in AREA_KEYS}


def _mix(base, **areas):
    d = dict(base)
    for lv, keys in areas.items():
        for k in keys:
            d[k] = lv
    return d


# the built-in groups (fixed; own groups are copies of one of them): key -> (name, hint, levels, specials)
TEMPLATES = {
    "orgadmin": (N_("Office admin"), N_("Manages every office area and the office rights"),
                 _all("manage"), SPECIAL_KEYS),
    "finance": (N_("Finance admin / controlling"), N_("Manages the finance areas and the office rights, reads the rest; invites nobody"),
                _mix(_all("view"), manage=MONEY + ("settings", "offers", "equipment")), SPECIAL_KEYS),
    "bookkeeping": (N_("Bookkeeping"), N_("Works in the finance areas and the invoices, exports for the tax adviser"),
                    _mix(_all("view"), edit=MONEY + ("offers",)), ("pay", "lock", "export")),
    "projects": (N_("Project management"), N_("Quotes, invoices, documents and correspondence; own expenses like everybody"),
                 _mix(_all("none"), edit=SELL + ("receipts", "travel", "logbook", "meals"), view=("kpi", "services", "equipment", "texts", "settings")),
                 ("release",)),
    "staff": (N_("Staff"), N_("Only their own receipts, travel expenses, drives, entertainment receipts and times"),
              _mix(_all("none"), own=tuple(AREA_OWN), view=("services", "equipment")), ()),
    "readonly": (N_("Read only"), N_("Sees every office area, changes nothing"), _all("view"), ()),
    TPL_NONE: (N_("No office access"), N_("Sees nothing of the office"), _all("none"), ()),
    TPL_LEGACY: (N_("Previous access"), N_("Exactly what members could do before the office rights existed"), None, ()),
}
TPL_ORDER = ("orgadmin", "finance", "bookkeeping", "projects", "staff", "readonly", TPL_NONE, TPL_LEGACY)


def ofr_legacy_levels(role):
    """What the group "Previous access" means for an org member of role (display and comparison only: these people keep the
    exact checks of before, office_org)."""
    if role == "member":
        return {k: ("edit" if AREA_LEGACY[k] == "member" else "none") for k in AREA_KEYS}
    if role == "readonly":
        return {k: ("view" if AREA_LEGACY[k] == "member" else "none") for k in AREA_KEYS}
    if role == "accounting":  # 2.143.0 A (#2151): reads the whole office incl. the admins' bookkeeping, exports
        return _all("view")
    return _all("none")


# ---------------------------------------------------------------- areas of a request
def ofr_area_of(path):
    """The area of an office path (None: not an office route or the rights page itself)."""
    if not path.startswith("/api/office/"):
        return None
    rest = path[len("/api/office/"):]
    for seg, key in _SEG:
        head = rest[:len(seg)]
        tail = rest[len(seg):len(seg) + 1]
        if head == seg and tail in ("", "/", "."):
            return key
    return None


def ofr_rule():
    """'METHOD /rule' of the request (the route's pattern, not the path)."""
    r = request.url_rule
    return f"{request.method} {r.rule if r is not None else request.path}"


def ofr_need(admin=False):
    """(level, special) the request needs from a group. admin: the route was for admins only before 2.187 (office_org
    admin=True) -- reading such a route of an area members could use (its admins-only figures, e.g. the equipment's value)
    needs "manage" (review)."""
    rule = request.url_rule.rule if request.url_rule is not None else request.path
    read = request.method in ("GET", "HEAD", "OPTIONS")
    if read:
        area = ofr_area_of(request.path)
        need = "manage" if rule in MANAGE_READ or (admin and AREA_LEGACY.get(area) == "member") else "view"
    else:
        need = "manage" if rule in MANAGE_ROUTES or ofr_area_of(request.path) == "settings" else "edit"
    return need, SPECIAL_ROUTES.get(ofr_rule())


# ---------------------------------------------------------------- what a person may
def _is_agent(c, uid):
    with system_ctx(c):
        r = c.execute("SELECT kind FROM users WHERE id=?", (uid,)).fetchone()
    return bool(r) and r[0] == "agent"


def ofr_groups_of(c, oid, uid):
    """The group refs of uid in office area oid: 'tpl:<key>' / 'g:<id>' ([] = no row)."""
    with system_ctx(c):  # structure of the area's rights (also asked for other people on the rights page)
        rows = c.execute("SELECT tpl, group_id FROM office_rgroup_members WHERE org_id=? AND user_id=? ORDER BY id", (oid, uid)).fetchall()
    return [f"g:{r[1]}" if r[1] else f"tpl:{r[0]}" for r in rows]


def _group_def(c, oid, ref):
    """(levels, specials) of a group ref (None: unknown / deleted)."""
    if ref.startswith("tpl:"):
        t = TEMPLATES.get(ref[4:])
        return (t[2], tuple(t[3])) if t and t[2] is not None else None
    try:
        gid = int(ref[2:])
    except ValueError:
        return None
    with system_ctx(c):  # structure of the area's rights (also asked for other people and agents)
        r = c.execute("SELECT rights, specials FROM office_rgroups WHERE id=? AND org_id=?", (gid, oid)).fetchone()
    if not r:
        return None
    return _levels_clean(_load(r[0], {})), tuple(_specials_clean(_load(r[1], [])))


def _load(v, d):
    try:
        x = json.loads(v or "")
    except (TypeError, ValueError):
        return d
    return x if isinstance(x, type(d)) else d


def _levels_clean(d):
    out = {}
    for k in AREA_KEYS:
        lv = d.get(k) if isinstance(d, dict) else None
        lv = lv if lv in LV else "none"
        if lv == "own" and k not in AREA_OWN:
            lv = "view"
        out[k] = lv
    return out


def _specials_clean(v):
    return [k for k in SPECIAL_KEYS if isinstance(v, (list, tuple)) and k in v]


def ofr_rights(c, uid, oid, role=None):
    """The rights of uid in office area oid: None = not ruled by groups (admin, personal office owner, an org member in
    "Previous access"); else {"levels": {area: level}, "specials": set, "agent": bool} (cached per request)."""
    cache = g.setdefault("ofr_rights", {}) if has_request_context() else {}
    key = (uid, oid)
    if key in cache:
        return cache[key]
    res = None
    owner = pb_owner(c, oid)
    agent = _is_agent(c, uid)
    if owner is not None:
        res = None if uid == owner else (_rights_from(c, oid, uid, agent) if agent else _none())
    else:
        if role is None:
            role = org_role(c, uid, oid)
        if role == "admin" and not agent:
            res = None
        elif agent:
            res = _rights_from(c, oid, uid, True)
        else:
            refs = ofr_groups_of(c, oid, uid)
            res = None if not refs or refs == [f"tpl:{TPL_LEGACY}"] else _rights_from(c, oid, uid, False, refs)
    cache[key] = res
    return res


def _none():
    return {"levels": _all("none"), "specials": set(), "agent": False}


def _rights_from(c, oid, uid, agent, refs=None):
    refs = ofr_groups_of(c, oid, uid) if refs is None else refs
    lv, sp = _all("none"), set()
    for ref in refs:
        if ref == f"tpl:{TPL_LEGACY}":
            if agent:
                continue  # agents never had "previous" office access through a membership
            d = (ofr_legacy_levels(org_role(c, uid, oid) or ""), ())
        else:
            d = _group_def(c, oid, ref)
        if not d:
            continue
        for k, v in d[0].items():
            if LV[v] > LV[lv[k]]:
                lv[k] = v
        sp |= set(d[1])
    if agent:
        sp.discard("rights")  # decision 6: an agent never manages rights
    return {"levels": lv, "specials": sp, "agent": agent}


def ofr_level(c, uid, oid, area):
    """The level of uid in area (admins / personal owner: manage; "Previous access": its display level)."""
    r = ofr_rights(c, uid, oid)
    if r is None:
        if pb_owner(c, oid) is not None or org_role(c, uid, oid) == "admin":
            return "manage"
        return ofr_legacy_levels(org_role(c, uid, oid) or "").get(area, "none")
    return r["levels"].get(area, "none")


def office_can(c, uid, oid, area, level="view", special=None):
    """2.187.0 (#2476): may uid work in office area oid's area with at least level (and the special)? The one check the
    areas outside /api/office ask (contacts, projects, files, agents' API)."""
    r = ofr_rights(c, uid, oid)
    if r is None:
        lv = ofr_level(c, uid, oid, area)
        if lv == "none":
            return False
        return LV[lv] >= LV[level] or (level == "own" and lv != "none")
    lv = r["levels"].get(area, "none")
    if LV[lv] < LV[level]:
        return False
    return special is None or special in r["specials"]


def ofr_allows(c, uid, oid, area, level="view", special=None):
    """office_can for the places outside /api/office that had their own checks before 2.187: a person not ruled by groups
    keeps exactly those (True here), a person ruled by groups needs the level (2.187.0 C)."""
    if ofr_rights(c, uid, oid) is None:
        return True
    return office_can(c, uid, oid, area, level, special)


def ofr_admin_or(c, uid, oid, area, level="edit", special=None):
    """2.187.0 B (#2476): the admin checks inside the office routes: a person ruled by groups needs level (+ special) in
    area; everybody else exactly as before (the office area's admin role)."""
    if ofr_rights(c, uid, oid) is None:
        return ofr_level(c, uid, oid, area) == "manage"  # not ruled by groups: "manage" = the admin role / the personal owner
    return office_can(c, uid, oid, area, level, special)


def ofr_need_area(c, uid, oid, area, level="view", special=None):
    """403 when a person ruled by groups lacks level in a second area a route touches (e.g. billing receipts onto an
    invoice); everybody else as before (2.187.0, review)."""
    if not ofr_allows(c, uid, oid, area, level, special):
        raise Denied(403, tr(NO_RIGHT))


def ofr_own_only(c, uid, oid, area):
    """True when uid sees only their own entries of area (level "own" through groups)."""
    r = ofr_rights(c, uid, oid)
    return r is not None and r["levels"].get(area) == "own"


def ofr_own_uid(area):
    """2.187.0 B (#2476): the person whose entries this request may touch when it runs on the level "own" of area (the
    routes in OWN_ROUTES filter by it: lists, 404 for anybody else's entry), else None (everything as before)."""
    if not has_request_context() or g.get("ofr_own") != area:
        return None
    u = getattr(g, "user", None)
    return u["id"] if u is not None else -1


def ofr_check(c, uid, oid, area=None, admin=False):
    """Raise 403 when uid's groups do not allow this request (area: by the path when None). True = groups decided (the
    caller skips its old admin check); False = not ruled by groups (the old checks stay)."""
    r = ofr_rights(c, uid, oid)
    if r is None:
        return False
    if request.path.startswith("/api/office/rights"):
        return True  # the rights page checks on its own (ofr_manager)
    area = area or ofr_area_of(request.path)
    if area is None:
        raise Denied(403, tr(NO_AREA))
    need, special = ofr_need(admin)
    lv = r["levels"].get(area, "none")
    if request.url_rule is not None and request.url_rule.rule in ANY_READ and request.method == "GET":
        if any(v != "none" for v in r["levels"].values()):
            return True
    if lv == "own":
        if ofr_rule() not in OWN_ROUTES or need == "manage":
            raise Denied(403, tr(NO_RIGHT))
        g.ofr_own = area
    elif LV[lv] < LV[need]:
        raise Denied(403, tr(NO_RIGHT))
    if special and special not in r["specials"]:
        raise Denied(403, tr(NO_SPECIAL))
    return True


NO_RIGHT = N_("Your office rights do not include this area")
NO_SPECIAL = N_("Your office rights do not include this step")
NO_AREA = N_("This office function is not assigned to an area yet")


@app.before_request
def ofr_gate():
    """Every /api/office/* request of a person ruled by groups is checked by its path before the route runs (also the
    routes that resolve their office area on their own)."""
    if not request.path.startswith("/api/office/") or request.path.startswith("/api/office/rights"):
        return None
    u = getattr(g, "user", None)
    if u is None or ("kind" in u.keys() and u["kind"] == "agent"):
        return None  # no account / an agent token: office_gate refuses it in the route
    c = db()
    if not office_on(c, u["id"]):
        return None
    try:
        oid, role = office_where(c, u["id"])
    except (BadInput, Denied):
        return None  # the route answers with its own text
    if oid and role != "admin":
        ofr_check(c, u["id"], oid)
    return None


# ---------------------------------------------------------------- the rights page
def ofr_manager(c, uid, oid):
    """'admin' (org admin / personal owner), 'group' (the special "rights" through a group) or None."""
    r = ofr_rights(c, uid, oid)
    if r is None:
        return "admin" if ofr_level(c, uid, oid, "settings") == "manage" else None
    return "group" if "rights" in r["specials"] and not r["agent"] else None


def _ctx_rights(write=False):
    c = db()
    uid = office_gate(c)
    oid, role = office_where(c, uid)
    no = office_allowed(c, uid, oid, write=write)
    if no:
        raise Denied(403, tr(no))
    mg = ofr_manager(c, uid, oid)
    return c, uid, oid, mg


def _people(c, oid):
    """[(uid, name, role, agent)] of office area oid: the organisation's members and agents (personal office: the owner
    and the owner's agents)."""
    from .agentdocs import ofa_area_agents
    owner = pb_owner(c, oid)
    with system_ctx(c):  # who works in the area (names for the rights page)
        if owner is not None:
            rows = [(owner, "admin")]
        else:
            rows = [(r[0], r[1]) for r in c.execute("SELECT user_id, role FROM org_members WHERE org_id=? ORDER BY user_id", (oid,))]
        rows += [(a, "agent") for a, _ in ofa_area_agents(c, oid)]
        out = []
        for u, role in rows:
            n = c.execute("SELECT display_name, username, kind FROM users WHERE id=?", (u,)).fetchone()
            if n:
                out.append((u, n[0] or n[1], role, n[2] == "agent"))
    return out


def _caps(c, uid, oid, mg):
    """(levels, specials) a manager may hand out: an admin everything, a group manager at most their own."""
    if mg == "admin":
        return _all("manage"), set(SPECIAL_KEYS)
    r = ofr_rights(c, uid, oid)
    return dict(r["levels"]), set(r["specials"])


def _within(levels, specials, caps):
    cl, cs = caps
    return all(LV[levels.get(k, "none")] <= LV[cl.get(k, "none")] for k in AREA_KEYS) and set(specials) <= cs


def _group_rows(c, oid):
    with system_ctx(c):  # the area's own groups (rights page of a manager, org_id bound)
        return [dict(r) for r in c.execute("SELECT id, name, base, rights, specials FROM office_rgroups WHERE org_id=? ORDER BY lower(name), id", (oid,))]


def _ref_def(c, oid, ref, uid_role=""):
    if ref == f"tpl:{TPL_LEGACY}":
        return ofr_legacy_levels(uid_role), ()
    return _group_def(c, oid, ref)


def ofr_log(c, oid, by, action, target_user=None, group=None, before=None, after=None):
    insert_id(c, "INSERT INTO office_rights_log(org_id, by_user, target_user, group_ref, action, before, after, at) VALUES(?,?,?,?,?,?,?,?)",
              (oid, by, target_user, group or "", action, json.dumps(before, ensure_ascii=False) if before is not None else "",
               json.dumps(after, ensure_ascii=False) if after is not None else "", iso(now_utc())))


def _logv(v):
    """A before / after value of the log (a dict of a group, a list of group refs; _load would drop both)."""
    try:
        return json.loads(v) if v else None
    except (TypeError, ValueError):
        return None


def ofr_log_rows(c, oid, limit=500):
    """The rights log of office area oid, newest first (also for the tax auditor's export)."""
    with system_ctx(c):
        rows = c.execute("SELECT * FROM office_rights_log WHERE org_id=? ORDER BY id DESC LIMIT ?", (oid, int(limit))).fetchall()
        names = {}
        for r in rows:
            for u in (r["by_user"], r["target_user"]):
                if u and u not in names:
                    n = c.execute("SELECT display_name, username FROM users WHERE id=?", (u,)).fetchone()
                    names[u] = (n[0] or n[1]) if n else ""
    return [{"id": r["id"], "at": r["at"], "action": r["action"], "by": r["by_user"], "by_name": names.get(r["by_user"], ""),
             "user": r["target_user"], "user_name": names.get(r["target_user"], ""), "group": r["group_ref"],
             "before": _logv(r["before"]), "after": _logv(r["after"])}
            for r in rows]


def ofr_mine(c, uid, oid, mg=None):
    """2.187.0 A (#2476): my rights in office area oid -- {levels {area: level}, specials [], groups [], manager ''|'admin'|'group',
    legacy (not ruled by groups, the checks of before)}; the rights page (mine) and the office's settings (rights: menu, buttons)."""
    lv = {k: ofr_level(c, uid, oid, k) for k in AREA_KEYS}
    r = ofr_rights(c, uid, oid)
    mg = ofr_manager(c, uid, oid) if mg is None else mg
    return {"levels": lv, "specials": sorted(r["specials"]) if r else (list(SPECIAL_KEYS) if lv["settings"] == "manage" else []),
            "groups": ofr_groups_of(c, oid, uid), "manager": mg or "", "legacy": r is None and lv["settings"] != "manage"}


@app.get("/api/office/rights")
def ofr_get():
    """The rights page: areas, levels, specials, templates, the area's own groups, the people with their groups, what I may
    hand out. Everybody with office access reads their own rights (mine); the rest only a manager."""
    c, uid, oid, mg = _ctx_rights()
    mine = ofr_mine(c, uid, oid, mg)
    out = {"areas": [{"key": a[0], "name": tr(a[1]), "group": a[2], "own": a[4]} for a in OFFICE_AREAS],
           "levels": list(LEVELS), "specials": [{"key": k, "name": tr(n)} for k, n in SPECIALS], "mine": mine,
           "personal": 1 if pb_owner(c, oid) is not None else 0}
    if not mg:
        return jsonify(out)
    caps = _caps(c, uid, oid, mg)
    out["templates"] = [{"ref": f"tpl:{k}", "key": k, "name": tr(TEMPLATES[k][0]), "hint": tr(TEMPLATES[k][1]),
                         "levels": TEMPLATES[k][2], "specials": list(TEMPLATES[k][3]),
                         "can_give": k == TPL_LEGACY or k == TPL_NONE or _within(TEMPLATES[k][2], TEMPLATES[k][3], caps)}
                        for k in TPL_ORDER]
    out["groups"] = []
    for gr in _group_rows(c, oid):
        levels, sp = _levels_clean(_load(gr["rights"], {})), _specials_clean(_load(gr["specials"], []))
        out["groups"].append({"ref": f"g:{gr['id']}", "id": gr["id"], "name": gr["name"], "base": gr["base"], "levels": levels,
                              "specials": sp, "can_give": _within(levels, sp, caps),
                              "can_edit": mg == "admin" or f"g:{gr['id']}" not in mine["groups"]})
    out["people"] = []
    from .agentdocs import ofa_area_agents
    drafts = dict(ofa_area_agents(c, oid))  # 2.187.0 C: an agent without a group row keeps its switch office_drafts (previous access)
    for u, name, role, agent in _people(c, oid):
        refs = ofr_groups_of(c, oid, u)
        fixed = role == "admin" and not agent
        out["people"].append({"id": u, "name": name, "role": role, "agent": agent, "fixed": fixed,
                              "groups": refs or ([f"tpl:{TPL_NONE}"] if agent and not drafts.get(u) else [f"tpl:{TPL_LEGACY}"]),
                              "can_edit": not fixed and (mg == "admin" or u != uid) and _person_within(c, oid, u, caps, mg)})
    out["caps"] = {"levels": caps[0], "specials": sorted(caps[1])}
    out["log_count"] = c.execute("SELECT count(*) FROM office_rights_log WHERE org_id=?", (oid,)).fetchone()[0]
    return jsonify(out)


def _person_within(c, oid, u, caps, mg):
    """May a manager with caps change person u's groups (a group manager never touches somebody with more than they have)?"""
    if mg == "admin":
        return True
    r = ofr_rights(c, u, oid)
    if r is None:
        role = org_role(c, u, oid) or ""
        if role == "admin":
            return False
        return _within(ofr_legacy_levels(role), (), caps)
    return _within(r["levels"], r["specials"], caps)


def _need_manager(c, uid, oid, mg):
    if not mg:
        raise Denied(403, tr(N_("Only a person who manages the office rights can do this")))


def _clean_group_body(b, caps, cur=None):
    name = b.get("name", cur["name"] if cur else "")
    if not isinstance(name, str) or not name.strip() or len(name) > 80:
        raise BadInput(tr("Please enter a name (at most 80 characters)"))
    levels = _levels_clean(b["levels"]) if isinstance(b.get("levels"), dict) else (cur["levels"] if cur else _all("none"))
    if isinstance(b.get("levels"), dict) and cur:  # a partial change keeps the other areas
        levels = _levels_clean({**cur["levels"], **{k: v for k, v in b["levels"].items() if k in AREA_KEYS}})
    sp = _specials_clean(b["specials"]) if isinstance(b.get("specials"), list) else (cur["specials"] if cur else [])
    if not _within(levels, sp, caps):
        raise Denied(403, tr(N_("You cannot hand out more rights than you have yourself")))
    return name.strip(), levels, sp


@app.post("/api/office/rights/groups")
def ofr_group_post():
    """A new own group, a copy of a template or of an own group (from: 'tpl:<key>' / 'g:<id>'), optionally renamed."""
    c, uid, oid, mg = _ctx_rights(True)
    _need_manager(c, uid, oid, mg)
    b = body()
    b = b if isinstance(b, dict) else {}
    src = b.get("from") if isinstance(b.get("from"), str) else f"tpl:{TPL_NONE}"
    d = _ref_def(c, oid, src) if src != f"tpl:{TPL_LEGACY}" else (ofr_legacy_levels("member"), ())
    if not d:
        raise BadInput(tr("Unknown group"))
    base_name = tr(TEMPLATES[src[4:]][0]) if src.startswith("tpl:") and src[4:] in TEMPLATES else ""
    if not base_name:
        gr = next((x for x in _group_rows(c, oid) if f"g:{x['id']}" == src), None)
        base_name = gr["name"] if gr else ""
    nb = {"name": b.get("name") or tr("Copy of {0}", base_name), "levels": d[0], "specials": list(d[1])}
    name, levels, sp = _clean_group_body(nb, _caps(c, uid, oid, mg))
    at = iso(now_utc())
    gid = insert_id(c, "INSERT INTO office_rgroups(org_id, name, base, rights, specials, created_by, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (oid, name, src, json.dumps(levels), json.dumps(sp), uid, at, at))
    ofr_log(c, oid, uid, "group_create", group=f"g:{gid}", after={"name": name, "levels": levels, "specials": sp})
    c.commit()
    return jsonify(id=gid, ref=f"g:{gid}", name=name, levels=levels, specials=sp), 201


def _group_cur(c, oid, gid):
    with system_ctx(c):  # one own group of the area (org_id bound)
        r = c.execute("SELECT id, name, rights, specials FROM office_rgroups WHERE id=? AND org_id=?", (gid, oid)).fetchone()
    if not r:
        raise Denied(404)
    return {"name": r["name"], "levels": _levels_clean(_load(r["rights"], {})), "specials": _specials_clean(_load(r["specials"], []))}


def _not_own_group(c, uid, oid, mg, gid):
    if mg != "admin" and f"g:{gid}" in ofr_groups_of(c, oid, uid):
        raise Denied(403, tr(N_("You cannot change a group you are in yourself")))


@app.patch("/api/office/rights/groups/<int:gid>")
def ofr_group_patch(gid):
    """Change an own group (name, levels per area -- also only some, specials). Autosave of the rights page."""
    c, uid, oid, mg = _ctx_rights(True)
    _need_manager(c, uid, oid, mg)
    _not_own_group(c, uid, oid, mg, gid)
    cur = _group_cur(c, oid, gid)
    b = body()
    name, levels, sp = _clean_group_body(b if isinstance(b, dict) else {}, _caps(c, uid, oid, mg), cur)
    c.execute("UPDATE office_rgroups SET name=?, rights=?, specials=?, updated_at=? WHERE id=? AND org_id=?",
              (name, json.dumps(levels), json.dumps(sp), iso(now_utc()), gid, oid))
    after = {"name": name, "levels": levels, "specials": sp}
    if after != cur:
        ofr_log(c, oid, uid, "group_change", group=f"g:{gid}", before=cur, after=after)
    c.commit()
    return jsonify(id=gid, ref=f"g:{gid}", **after)


@app.delete("/api/office/rights/groups/<int:gid>")
def ofr_group_delete(gid):
    """Delete an own group; its members keep their other groups (none left: "No office access", never "Previous access")."""
    c, uid, oid, mg = _ctx_rights(True)
    _need_manager(c, uid, oid, mg)
    _not_own_group(c, uid, oid, mg, gid)
    cur = _group_cur(c, oid, gid)
    if mg != "admin" and not _within(cur["levels"], cur["specials"], _caps(c, uid, oid, mg)):
        raise Denied(403, tr(N_("You cannot hand out more rights than you have yourself")))
    with system_ctx(c):  # the members of the group being deleted (org_id bound)
        users = [r[0] for r in c.execute("SELECT user_id FROM office_rgroup_members WHERE org_id=? AND group_id=?", (oid, gid))]
    _keep_a_manager(c, oid, drop_group=gid)
    c.execute("DELETE FROM office_rgroup_members WHERE org_id=? AND group_id=?", (oid, gid))
    for u in users:
        if not c.execute("SELECT 1 FROM office_rgroup_members WHERE org_id=? AND user_id=?", (oid, u)).fetchone():
            c.execute("INSERT INTO office_rgroup_members(org_id, user_id, tpl, created_at) VALUES(?,?,?,?)", (oid, u, TPL_NONE, iso(now_utc())))
    c.execute("DELETE FROM office_rgroups WHERE id=? AND org_id=?", (gid, oid))
    ofr_log(c, oid, uid, "group_delete", group=f"g:{gid}", before={**cur, "members": users})
    c.commit()
    return jsonify(ok=True)


def _keep_a_manager(c, oid, drop_group=None, user=None, new_refs=None):
    """Decision 5: at least one person keeps the rights management. The organisation's admins always have it, so this only
    refuses where an area has no admin (never in practice) -- kept as the explicit rule."""
    if pb_owner(c, oid) is not None:
        return
    with system_ctx(c):
        if c.execute("SELECT 1 FROM org_members WHERE org_id=? AND role='admin' LIMIT 1", (oid,)).fetchone():
            return
    raise Denied(409, tr(N_("At least one person must keep the management of the office rights")))


@app.put("/api/office/rights/people/<int:pid>")
def ofr_person_put(pid):
    """The groups of person pid: {"groups": ["tpl:<key>" | "g:<id>", ...]} (["tpl:legacy"] = previous access again; agents
    never; [] = no office access)."""
    c, uid, oid, mg = _ctx_rights(True)
    _need_manager(c, uid, oid, mg)
    people = {p[0]: p for p in _people(c, oid)}
    if pid not in people:
        raise Denied(404)
    _, _, role, agent = people[pid]
    if role == "admin" and not agent:
        raise Denied(409, tr(N_("Admins of the organisation always see the whole office")))
    if pid == uid and mg != "admin":
        raise Denied(403, tr(N_("You cannot change your own office rights")))
    caps = _caps(c, uid, oid, mg)
    if not _person_within(c, oid, pid, caps, mg):
        raise Denied(403, tr(N_("You cannot hand out more rights than you have yourself")))
    b = body()
    refs = b.get("groups") if isinstance(b, dict) else None
    if not isinstance(refs, list) or len(refs) > 20 or not all(isinstance(x, str) for x in refs):
        raise BadInput(tr("Invalid data"))
    refs = list(dict.fromkeys(refs)) or [f"tpl:{TPL_NONE}"]
    if agent and f"tpl:{TPL_LEGACY}" in refs:
        raise BadInput(tr(N_("Agents start without office access: choose a group")))
    if len(refs) > 1 and f"tpl:{TPL_LEGACY}" in refs:
        refs = [r for r in refs if r != f"tpl:{TPL_LEGACY}"]
    if len(refs) > 1 and f"tpl:{TPL_NONE}" in refs:
        refs = [r for r in refs if r != f"tpl:{TPL_NONE}"]
    prole = org_role(c, pid, oid) or ""
    for ref in refs:
        d = _ref_def(c, oid, ref, prole)
        if d is None:
            raise BadInput(tr("Unknown group"))
        if agent and "rights" in d[1]:
            raise BadInput(tr(N_("An agent never manages office rights")))
        if ref != f"tpl:{TPL_NONE}" and not _within(d[0], d[1], caps):  # also "previous access": never more than the manager has
            raise Denied(403, tr(N_("You cannot hand out more rights than you have yourself")))
    before = ofr_groups_of(c, oid, pid)
    at = iso(now_utc())
    c.execute("DELETE FROM office_rgroup_members WHERE org_id=? AND user_id=?", (oid, pid))
    for ref in refs:
        if ref.startswith("g:"):
            c.execute("INSERT INTO office_rgroup_members(org_id, user_id, tpl, group_id, created_at) VALUES(?,?,?,?,?)", (oid, pid, "", int(ref[2:]), at))
        else:
            c.execute("INSERT INTO office_rgroup_members(org_id, user_id, tpl, created_at) VALUES(?,?,?,?)", (oid, pid, ref[4:], at))
    if before != refs:
        ofr_log(c, oid, uid, "member_groups", target_user=pid, before=before, after=refs)
    g.pop("ofr_rights", None)
    c.commit()
    return jsonify(id=pid, groups=refs)


@app.get("/api/office/rights/log")
def ofr_log_get():
    """The rights log (managers only), newest first."""
    c, uid, oid, mg = _ctx_rights()
    _need_manager(c, uid, oid, mg)
    return jsonify(items=ofr_log_rows(c, oid))
