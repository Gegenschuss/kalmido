"""2.575.0 (#3778): own module cards (Settings > Modules), private and per organisation.

Beside the six fixed answers of "What do you use Kalmido for?" there are own cards: a name, an icon and a choice of single
modules (the client groups them by area).
  - Private cards (org_id NULL, user_id = the owner): any number; one click applies one like a fixed answer, but only for
    the workspace Private -- the organisations look as before (the modules it switches on are hidden there, the ones it
    leaves out are hidden in Private only: user setting "ws_mods_off", json {"private" | "org:<id>": [module]}).
  - Cards of an organisation (org_id): its admins make several, assign them to members (module_card_people) and mark one as
    the default for everybody without an assignment. A person's cap there = the union of their cards (no switcher); without
    an assignment the default card; an organisation without cards (or without a default for an unassigned person) has no
    cap, as before. The cap is an upper limit: the members switch modules off inside it (ws_mods_off "org:<id>"), never on
    beyond it; the server refuses the routes of a module outside the cap while the organisation is the workspace of the
    request (mc_gate, like accounts/wsareas.py wsa_gate). Nothing is ever deleted.
  - A card remembers the modules there were when it was saved (known): a module added by an update later is off on it and
    its admins see "new module available" until they save the card again.
The account's module switches (setting "features") stay the main switch: off = off everywhere."""
import json
import re

from flask import g, jsonify, request

from ..core.config import app
from ..core.srchreg import SRCH_HOOKS  # 2.1026.0 (#5280)
from ..core.conflict import ccf_check
from ..core.db import body, bump, db, iso_ms, now_utc, usettings
from ..core.errors import BadInput, Denied
from ..core.i18n import N_, tr
from ..core.pg import insert_id, write_lock
from ..core.schema import USER_DEFAULTS
from .orgs import is_org_admin, user_orgs
from .session import me
from .wsareas import WSA_KEY_RE, _req_org

# the modules a card can hold: every module of Settings > Modules (family/family.py PM_FULL = the client's FEATS, in that
# order) + the documents. A copy: accounts is a layer below the areas (tools/check_layers.py); tests/p2575_a_api_test.py
# fails when PM_FULL gains a module that is missing here
_MC_MODS = ("cal", "timeline", "matrix", "habits", "pomo", "kanban", "collab", "stats", "time", "progress", "deps", "fields",
            "agents", "comments", "family", "events", "contacts", "contracts", "home", "care", "health", "review", "travel",
            "reading", "budget", "feeds", "clients", "workload", "forms", "office", "wiki", "files", "dispo", "sheets", "videos", "docs")  # 2.623.0 (#4765): + videos


def mc_mods():
    return _MC_MODS


MC_NAME_MAX = 60
MC_MAX = 50  # cards per workspace (private: per person)
MC_PEOPLE_MAX = 2000
MC_ICON_RE = re.compile(r"[a-z][a-z0-9-]{0,23}")
MC_OFF_TEXT = N_("This module is not on your module card in this organisation.")
# 2.794.0 (#5392)
MC_PRIV_OFFICE_TEXT = N_("The office is switched off in the workspace Private. Switch it on under Settings > Modules > Office & finance > Also private.")
USER_DEFAULTS.setdefault("ws_mods_off", "{}")  # my modules hidden per workspace (below the main switch and a card's cap)

# the API paths of a module (prefix; the next character is "/" or "?" or the path ends there) -- refused outside the cap
MC_PATHS = (("/api/office/", "office"), ("/api/time", "time"), ("/api/pomo", "pomo"),
            ("/api/life/review", "review"), ("/api/life/journal", "review"), ("/api/stats", "stats"),
            ("/api/life/contracts", "contracts"), ("/api/life/devices", "home"), ("/api/life/device-links", "home"),
            ("/api/life/upkeep", "home"), ("/api/life/upkeep-presets", "home"), ("/api/life/health", "health"),
            ("/api/life/trips", "travel"), ("/api/reading", "reading"), ("/api/bookmarks", "reading"), ("/api/feeds", "feeds"),
            ("/api/files", "files"), ("/api/docs", "docs"), ("/api/wiki", "wiki"), ("/api/sheets", "sheets"),
            ("/api/clients", "clients"), ("/api/budget", "budget"), ("/api/workload", "workload"), ("/api/team/dispo", "dispo"), ("/api/forms", "forms"),
            ("/api/habits", "habits"))
# the file store: only its own views (like wsareas.py WSA_ABLAGE_VIEWS: the office, letters, pages use the file routes too)
MC_FILE_VIEWS = ("/api/files", "/api/files/folders", "/api/files/search", "/api/files/tagged")
# an object of an organisation opened by its id: its own organisation counts, whatever the workspace is
MC_OBJ = (("wiki", re.compile(r"/api/wiki/pages/(\d+)"), "wiki_pages"), ("sheets", re.compile(r"/api/sheets/(\d+)"), "sheets"),
          ("reading", re.compile(r"/api/bookmarks/(\d+)"), "bookmarks"), ("files", re.compile(r"/api/files/nodes/(\d+)"), "fs_nodes"),
          ("budget", re.compile(r"/api/budget/(\d+)"), "lists"))  # job 2963 review: the budget has its own routes too


def _csv(v):
    return [x for x in (v or "").split(",") if x]


def mc_clean_mods(v):
    """[module, ...] (or csv) -> the stored csv in the order of mc_mods(); an unknown module is a 400."""
    xs = v.split(",") if isinstance(v, str) else v
    if not isinstance(xs, list) or len(xs) > len(mc_mods()) or not all(isinstance(x, str) for x in xs):
        raise BadInput(tr("Invalid value: {0}", "mods"))
    xs = {x.strip() for x in xs if x.strip()}
    if any(x not in mc_mods() for x in xs):
        raise BadInput(tr("Invalid value: {0}", "mods"))
    return ",".join(x for x in mc_mods() if x in xs)


def mc_clean_own(v):
    """The user setting ws_mods_off -> stored json {"private" | "org:<id>": [module, ...]}; strict like wsa_clean_own."""
    bad = BadInput(tr("Invalid value: {0}", "ws_mods_off"))
    try:
        o = json.loads(v or "{}") if isinstance(v, str) else v
    except ValueError:
        raise bad from None
    if not isinstance(o, dict) or len(o) > 100:
        raise bad
    out = {}
    for k, xs in o.items():
        if not isinstance(k, str) or not WSA_KEY_RE.fullmatch(k) or not isinstance(xs, list) or len(xs) > len(mc_mods()):
            raise bad
        if any(not isinstance(x, str) or x not in mc_mods() for x in xs):
            raise bad
        if xs:
            out[k] = [x for x in mc_mods() if x in xs]
    return json.dumps(out, separators=(",", ":"))


def _in_req():
    from flask import has_request_context
    return has_request_context()


def _cards_seen(c, uid):
    """{org id: [(card id, mods csv, dflt)]} of every organisation card the person's context shows (the row-level policy:
    their organisations) and the set of card ids assigned to them -- two statements per request, whatever the number of
    organisations (/api/state asks for each of them)."""
    cache = g.setdefault("mc_seen", {}) if _in_req() else {}
    if uid not in cache:
        by = {}
        for r in c.execute("SELECT id, org_id, mods, dflt FROM module_cards WHERE org_id IS NOT NULL ORDER BY id"):
            by.setdefault(r[1], []).append((r[0], r[2], r[3]))
        mine = {r[0] for r in c.execute("SELECT card_id FROM module_card_people WHERE user_id=?", (uid,))} if by else set()
        cache[uid] = (by, mine)
    return cache[uid]


def mc_cap(c, uid, oid):
    """The modules person uid may use in organisation oid: a frozenset (their cards' union, else the default card), or None
    = no cap (no cards there, or no default for a person without an assignment). Read in the person's own context: the
    row-level policy shows the cards of their organisations only (the caller checks the membership)."""
    if not oid or not uid:
        return None
    by, mine = _cards_seen(c, uid)
    rows = by.get(oid) or []
    use = [r for r in rows if r[0] in mine] or [r for r in rows if r[2]]
    return frozenset(m for r in use for m in _csv(r[1])) if use else None


def mc_drop():
    """Forget the request's cache after a card changed (the answer reads the new cap)."""
    if _in_req():
        g.pop("mc_seen", None)


def mc_cap_list(c, uid, oid):
    """mc_cap as a list in the order of mc_mods() (None = no cap): what /api/me's workspaces carry (orgs.py workspaces_for)."""
    cap = mc_cap(c, uid, oid)
    return None if cap is None else [m for m in mc_mods() if m in cap]


def mc_private_office_off(c, uid):
    """2.794.0 (#5392): Settings > Modules > Office & finance > "Also private" is off: the module "office" stands in my
    ws_mods_off "private" (the same entry a private card writes). Hides my own personal office only; nothing is deleted."""
    try:
        off = json.loads(usettings(c, uid).get("ws_mods_off") or "{}").get("private") or []
    except (ValueError, AttributeError):
        return False
    return isinstance(off, list) and "office" in off


def mc_check(c, uid, oid, mod):
    """403 when module mod is outside uid's cap in organisation oid."""
    cap = mc_cap(c, uid, oid)
    if cap is not None and mod in mc_mods() and mod not in cap:
        raise Denied(403, tr(MC_OFF_TEXT))


@app.before_request
def mc_gate(p=None):
    """The routes of a module outside the person's card cap answer 403 while that organisation is the workspace of the
    request (the office: the organisation of its own area; an object opened by id: its organisation). Agents and tokens are
    untouched as in wsa_gate: what they see is what is shared with them."""
    p = p or request.path  # 2.1026.0 (#5280): p = the path of a search kind (core/srchreg.py srch_gate)
    if not p.startswith("/api/") or p.startswith("/api/v1/"):
        return None
    mod = next((m for pre, m in MC_PATHS if p.startswith(pre) and (pre.endswith("/") or len(p) == len(pre) or p[len(pre)] in "/?")), None)
    if mod is None:
        return None
    u = getattr(g, "user", None)
    if u is None or ("kind" in u.keys() and u["kind"] == "agent") or g.get("auth_via") == "token":
        return None
    c = db()
    if mod == "office":  # the office's own area; the person's own office is never capped
        from ..office.model import office_on, office_where, pb_personal
        if not office_on(c, u["id"]):
            return None
        try:
            oid, _role = office_where(c, u["id"])
        except (BadInput, Denied):
            return None  # the route answers with its own text
        # 2.794.0 (#5392): "Also private" off -> my own personal office answers 403 with a readable text (no card needed:
        # before the fast way out); the offices of my organisations stay. Switched on again, the same data answers
        if oid and mc_private_office_off(c, u["id"]) and oid == pb_personal(c, u["id"], create=False):
            raise Denied(403, tr(MC_PRIV_OFFICE_TEXT))
        if oid and _cards_seen(c, u["id"])[0]:
            mc_check(c, u["id"], oid, mod)
        return None
    if not _cards_seen(c, u["id"])[0]:  # fast way out: none of my organisations has cards
        return None
    for m, rx, table in MC_OBJ:
        hit = rx.match(p)
        if m == mod and hit:
            r = c.execute(f"SELECT org_id FROM {table} WHERE id=?", (int(hit.group(1)),)).fetchone()  # noqa: S608 (fixed names)
            if r and r[0] and r[0] in user_orgs(c, u["id"]):
                cap = mc_cap(c, u["id"], r[0])
                if mod != "files" or (cap is not None and "office" not in cap):  # a file of the office stays while the office is on
                    mc_check(c, u["id"], r[0], mod)
            return None
    if mod == "files" and (request.method != "GET" or p.rstrip("/") not in MC_FILE_VIEWS):
        return None
    oid = _req_org(c, u["id"], "ablage" if mod == "files" else mod)
    if oid:
        mc_check(c, u["id"], oid, mod)
    return None


# ---------------------------------------------------------------- the cards
def _person():
    u = getattr(g, "user", None)
    if u is None or ("kind" in u.keys() and u["kind"] == "agent"):
        raise Denied(403)
    return me()


def _space(c, uid, v):
    """"private" -> None; "org:<id>" (or the bare id) of an organisation uid is in -> its id; else 400 / 404."""
    if isinstance(v, int) and not isinstance(v, bool):
        v = f"org:{v}"
    if not isinstance(v, str) or not WSA_KEY_RE.fullmatch(v):
        raise BadInput(tr("Invalid value: {0}", "space"))
    if v == "private":
        return None
    oid = int(v[4:])
    if oid not in user_orgs(c, uid):
        raise Denied(404)
    return oid


def _people_of(c, ids):
    out = {}
    for cid in ids:
        out[cid] = []
    if ids:
        q = ",".join("?" * len(ids))
        for r in c.execute(f"SELECT card_id, user_id FROM module_card_people WHERE card_id IN ({q}) ORDER BY user_id", list(ids)):  # noqa: S608
            out[r[0]].append(r[1])
    return out


def mc_json(r, people=None):
    known = set(_csv(r["known"]))
    d = {"id": r["id"], "space": f"org:{r['org_id']}" if r["org_id"] else "private", "name": r["name"], "icon": r["icon"],
         "mods": _csv(r["mods"]), "dflt": bool(r["dflt"]), "updated_at": r["updated_at"],
         "new_mods": [m for m in mc_mods() if m not in known]}  # added by an update after the card was saved: off on it
    if people is not None:
        d["people"] = people
    return d


def _card(c, uid, cid, write=True):
    """The card cid uid may see (private: their own; an organisation's: a member) -> (row, oid); writing an organisation's
    card needs its admin (403 for a member, 404 for anybody else)."""
    r = c.execute("SELECT * FROM module_cards WHERE id=?", (cid,)).fetchone()
    if not r:
        raise Denied(404)
    if r["org_id"] is None:
        if r["user_id"] != uid:
            raise Denied(404)
        return r, None
    if r["org_id"] not in user_orgs(c, uid):
        raise Denied(404)
    if write and not is_org_admin(c, uid, r["org_id"]):
        raise Denied(403, tr("Only an admin of the organisation can change this."))
    return r, r["org_id"]


def _org_members(c, oid):
    return [{"id": r[0], "name": r[1]} for r in c.execute(
        "SELECT u.id, COALESCE(NULLIF(u.display_name,''), u.username) FROM org_members m JOIN users u ON u.id=m.user_id "
        "WHERE m.org_id=? AND NOT u.disabled AND COALESCE(u.kind,'')!='agent' ORDER BY 2, 1", (oid,))]


def _clean_people(c, oid, v):
    if not isinstance(v, list) or len(v) > MC_PEOPLE_MAX or any(isinstance(x, bool) or not isinstance(x, int) for x in v):
        raise BadInput(tr("Invalid value: {0}", "people"))
    # members incl. disabled ones (review job 2963): a card that names a person disabled later must stay savable as it is
    ok = {r[0] for r in c.execute("SELECT m.user_id FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? "
                                  "AND COALESCE(u.kind,'')!='agent'", (oid,))}
    if any(x not in ok for x in v):
        raise BadInput(tr("Invalid value: {0}", "people"))
    return list(dict.fromkeys(v))


def _clean_fields(b, new):
    out = {}
    if new or "name" in b:
        n = b.get("name")
        if not isinstance(n, str) or not n.strip() or len(n.strip()) > MC_NAME_MAX:
            raise BadInput(tr("Invalid value: {0}", "name"))
        out["name"] = n.strip()
    if new or "icon" in b:
        i = b.get("icon") or "grid"
        if not isinstance(i, str) or not MC_ICON_RE.fullmatch(i):
            raise BadInput(tr("Invalid value: {0}", "icon"))
        out["icon"] = i
    if new or "mods" in b:
        out["mods"] = mc_clean_mods(b.get("mods") if b.get("mods") is not None else [])
    if "dflt" in b:
        if not isinstance(b["dflt"], bool):
            raise BadInput(tr("Invalid value: {0}", "dflt"))
        out["dflt"] = 1 if b["dflt"] else 0
    return out


def _set_people(c, cid, people):
    c.execute("DELETE FROM module_card_people WHERE card_id=?", (cid,))
    for p in people:
        c.execute("INSERT INTO module_card_people(card_id,user_id) VALUES(?,?)", (cid, p))


@app.get("/api/modcards")
def modcards_list():
    """?space=private | org:<id> -> {space, mods (every module a card can hold), cards, admin, cap, members?}. Private: my
    own cards. An organisation: its admins see every card with its people and the members to assign; a member sees only
    the cards that apply to them (theirs, else the default) and their cap (null = none)."""
    c, uid = db(), _person()
    oid = _space(c, uid, request.args.get("space") or "private")
    if oid is None:
        rows = c.execute("SELECT * FROM module_cards WHERE org_id IS NULL AND user_id=? ORDER BY id", (uid,)).fetchall()
        return jsonify(space="private", mods=list(mc_mods()), admin=True, cap=None, cards=[mc_json(r) for r in rows])
    adm = is_org_admin(c, uid, oid)
    rows = c.execute("SELECT * FROM module_cards WHERE org_id=? ORDER BY id", (oid,)).fetchall()
    ppl = _people_of(c, [r["id"] for r in rows])
    out = dict(space=f"org:{oid}", mods=list(mc_mods()), admin=adm, cap=mc_cap_list(c, uid, oid))
    if adm:
        out["cards"] = [mc_json(r, ppl[r["id"]]) for r in rows]
        out["members"] = _org_members(c, oid)
    else:
        mine = [r for r in rows if uid in ppl[r["id"]]] or [r for r in rows if r["dflt"]]
        out["cards"] = [{k: v for k, v in mc_json(r).items() if k != "new_mods"} for r in mine]
    return jsonify(**out)


@app.post("/api/modcards")
def modcards_new():
    """{space, name, icon?, mods: [module], dflt? (organisation), people? (organisation: member ids)} -> 201 the card.
    An organisation's cards only by its admins."""
    c, uid = db(), _person()
    b = body()
    oid = _space(c, uid, b.get("space") or "private")
    if oid is not None and not is_org_admin(c, uid, oid):
        raise Denied(403, tr("Only an admin of the organisation can change this."))
    f = _clean_fields(b, True)
    people = _clean_people(c, oid, b.get("people") or []) if oid is not None else []
    if oid is None and (f.get("dflt") or b.get("people")):
        raise BadInput(tr("Invalid value: {0}", "dflt" if f.get("dflt") else "people"))
    write_lock(c, f"module_cards-org-{oid}" if oid else f"module_cards-u{uid}")  # own names: card 5 is not organisation 5
    n = c.execute("SELECT COUNT(*) FROM module_cards WHERE " + ("org_id=?" if oid else "org_id IS NULL AND user_id=?"),
                  (oid or uid,)).fetchone()[0]
    if n >= MC_MAX:
        raise BadInput(tr("At most {0} module cards", MC_MAX))
    ts = iso_ms(now_utc())
    if f.get("dflt"):
        c.execute("UPDATE module_cards SET dflt=0 WHERE org_id=?", (oid,))
    cid = insert_id(c, "INSERT INTO module_cards(org_id,user_id,name,icon,mods,known,dflt,created_by,created_at,updated_at) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (oid, None if oid else uid, f["name"], f["icon"], f["mods"], ",".join(mc_mods()), f.get("dflt", 0), uid, ts, ts))
    if oid is not None:
        _set_people(c, cid, people)
    bump(c)
    c.commit()
    mc_drop()
    r = c.execute("SELECT * FROM module_cards WHERE id=?", (cid,)).fetchone()
    return jsonify(card=mc_json(r, people if oid is not None else None)), 201


@app.patch("/api/modcards/<int:cid>")
def modcards_edit(cid):
    """{name?, icon?, mods?, dflt?, people?, expect_updated_at?} -- a changed card (409 with the current card when it changed
    since expect_updated_at). Saving takes the modules there are now as known: "new module available" goes away."""
    c, uid = db(), _person()
    b = body()
    _r0, oid0 = _card(c, uid, cid)
    if oid0 is not None:  # review job 2963: the organisation's lock first (as modcards_new) - two admins setting two
        write_lock(c, f"module_cards-org-{oid0}")  # different default cards at once left two defaults
    write_lock(c, f"module_cards-{cid}")
    r, oid = _card(c, uid, cid)
    ccf_check(b, r["updated_at"], "card", lambda: mc_json(r, _people_of(c, [cid])[cid] if oid else None))
    f = _clean_fields(b, False)
    if oid is None and (f.get("dflt") or "people" in b):
        raise BadInput(tr("Invalid value: {0}", "dflt" if f.get("dflt") else "people"))
    people = _clean_people(c, oid, b["people"]) if oid is not None and "people" in b else None
    f["known"] = ",".join(mc_mods())
    f["updated_at"] = iso_ms(now_utc())
    if f.get("dflt"):
        c.execute("UPDATE module_cards SET dflt=0 WHERE org_id=? AND id!=?", (oid, cid))
    c.execute(f"UPDATE module_cards SET {', '.join(k + '=?' for k in f)} WHERE id=?", (*f.values(), cid))  # noqa: S608 (fixed keys)
    if people is not None:
        _set_people(c, cid, people)
    bump(c)
    c.commit()
    mc_drop()
    r = c.execute("SELECT * FROM module_cards WHERE id=?", (cid,)).fetchone()
    return jsonify(card=mc_json(r, _people_of(c, [cid])[cid] if oid else None))


@app.delete("/api/modcards/<int:cid>")
def modcards_delete(cid):
    """Removes the card (its assignments go with it); the modules, data and settings stay as they are."""
    c, uid = db(), _person()
    _card(c, uid, cid)
    write_lock(c, f"module_cards-{cid}")
    _card(c, uid, cid)
    c.execute("DELETE FROM module_cards WHERE id=?", (cid,))
    bump(c)
    c.commit()
    return jsonify(ok=True)


SRCH_HOOKS["gates"].append(mc_gate)  # 2.1026.0 (#5280): the one search asks the gate for a kind's area (core/srchreg.py)
