"""2.51.0 (#1351 #1358): two more kinds of agent proposals (see agents/proposals.py for the mechanism).

inquiry (#1351): a customer inquiry becomes a project in ONE proposal: the project list (name, client, project type,
sections, first tasks), shoot days as event drafts (events.status 'tentative' in the calendar of the person applying it)
and optionally a quotation draft (office/agentdocs.py ofa_draft_create, part A). With input.offer (an accepted
quotation, "the accepted offer becomes a project", from #1021) the project takes the offer's client and is bound to it
(a deal of the pipeline with this offer gets the list); the proposal then carries no new offer.
setup (#1358): the setup assistant: modules on / off, new lists (name, colour, sections) and a first project of a
project type, only for the person applying it (modules are personal settings; nothing organisation-wide).

The agent proposes, the person decides: nothing exists before "Apply", one undo step takes everything back (event
drafts go, a quotation only while it is still a draft, lists only while nobody added anything). Selection keys stay in
the format of prop_sel ("\\d{1,3}(.\\d{1,3})?"): inquiry tasks "i" / "i.k", shoot days "300+i", the offer "400" with its
items "400.j"; setup modules "i", lists "100+i", the project "200".
"""
import contextlib
import json

from flask import g, jsonify

from ..core.config import app
from ..core.db import bump, db, iso, now_utc
from ..core.i18n import N_, tr
from ..core.pg import insert_id, write_lock
from ..core.access import Denied, list_role, my_max_sort, list_other_agent
from ..accounts.session import me
from ..core.db import usettings, uset
from ..core.errors import BadInput, UnknownFields
from ..lists.lists import list_created, clean_color, clean_folder, FOLDER_MAX
from ..api.common import v1_err  # 2.149.0 G (#2517): pulled up from functions

PK2_KINDS = ("inquiry", "setup")
PK2_TITLES = {"inquiry": N_("Project from an inquiry"), "setup": N_("Set up Kalmido")}
PK2_SHOOT_MAX, PK2_OFFER_ITEMS_MAX, PK2_LISTS_MAX, PK2_CLIENTS_MAX = 30, 100, 20, 500
PK2_SHOOT_KEY, PK2_OFFER_KEY, PK2_LIST_KEY, PK2_PROJECT_KEY = 300, 400, 100, 200
# the modules a setup proposal may switch (the keys of the client's FEATS, static/js/core.js)
PK2_MODS = ("cal", "timeline", "matrix", "habits", "pomo", "kanban", "collab", "stats", "time", "progress", "deps", "fields",
            "agents", "comments", "family", "events", "contacts", "contracts", "home", "care", "health", "review", "travel",
            "reading", "clients", "workload", "forms", "office", "wiki", "files", "dispo",
            "sheets")  # 2.89.0 (#1916)
PK2_OPEN_MAX = 10   # open (ready, undecided) inquiry / setup proposals an agent made on its own per person
PK2_OPEN_AGENT_MAX = 50   # 2.51.0 (#1351) review: ... and per agent in all


# ---------------------------------------------------------------- where it lands, what the agent may see
@contextlib.contextmanager
def _pk2_as(c, uid):
    """Reads as person uid for the block (the connection's context hook follows g.user, core/access.py acx_conn_hook): an
    agent's own proposal needs the input the person would send (their office area, their clients) -- used only after
    prop_agent_ok, and office data only with both switches of part A (pk2_office). Never wider than that person."""
    prev = g.user
    g.user = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    try:
        yield c
    finally:
        g.user = prev


def pk2_area(c, uid, aid):
    """(org of the new list or None = private, office area id or None) for person uid applying a proposal of agent aid:
    the agent's organisation when the person is a member there, else the person's private space / personal office.
    Never another organisation."""
    from ..accounts.orgs import org_role
    from ..office.model import pb_personal
    r = c.execute("SELECT org_id FROM agents WHERE user_id=?", (aid,)).fetchone()
    org = r["org_id"] if r else None
    if org and org_role(c, uid, org) in ("admin", "member"):  # 2.143.0 A (#2151): not the limited roles
        return org, org
    return None, pb_personal(c, uid, create=False)


def pk2_office(c, uid, aid, oid):
    """May agent aid draft a quotation for person uid in office area oid? -> (ok, reason). Part A's rules
    (office/agentdocs.py): the agent's switch office_drafts, its office area (ofa_area: its organisation, a personal agent
    its owner's personal office) is oid, the area's privacy switch agents_read, the agent's scope office; and the person
    works in that office."""
    if not oid:
        return False, "no_office"
    try:
        from ..office.agentdocs import ofa_area
    except ImportError:  # part A not in this build
        return False, "no_office"
    from ..agents.core import agent_row
    from ..office.model import office_on, office_role, office_settings
    a = agent_row(c, aid)
    if not a or not ("office_drafts" in a.keys() and a["office_drafts"]) or ofa_area(c, a) != oid:
        return False, "agent_no_office"
    # 2.51.0 (#1351) review: office data only with the scope office too (like part A's v1 routes; agentdocs.py)
    from ..api.scopes import scopes_effective
    from ..api.v1 import SCOPES_AGENT_DEFAULT
    au = c.execute("SELECT * FROM users WHERE id=?", (aid,)).fetchone()
    if not au or "office" not in scopes_effective(c, {"scopes": a["scopes"] or ",".join(SCOPES_AGENT_DEFAULT)}, au):
        return False, "no_scope"
    if not office_on(c, uid) or office_role(c, uid, oid) not in ("admin", "member"):
        return False, "no_office_rights"
    if not office_settings(c, oid).get("agents_read"):
        return False, "privacy_off"
    return True, ""


def _pk2_log(c, oid, aid, uid, write, target, did=None):
    """One line in the office log (part A's ofa_log) per handing office data to the agent / drafting for it."""
    try:
        from ..office.agentdocs import ofa_log
    except ImportError:
        return
    ofa_log(c, oid, aid, write, target, doc_id=did, uid=uid)


def _pk2_clients(c, uid, oid):
    from ..office.model import pb_owner
    from ..team.clients import client_rows
    own = pb_owner(c, oid) == uid
    return [r for r in client_rows(c, uid, archived=False)
            if r["org_id"] == oid or (own and r["org_id"] is None and r["created_by"] == uid)][:PK2_CLIENTS_MAX]


def _pk2_offer(c, uid, oid, did):
    """The accepted quotation did of office area oid as job input (what part A lets the agent read anyway)."""
    r = c.execute("SELECT * FROM office_docs WHERE id=? AND org_id=? AND kind='offer'", (did, oid)).fetchone()
    if not r:
        raise Denied(404)
    if r["status"] != "accepted":
        raise BadInput(tr("Only an accepted quotation can become a project"))
    cl = c.execute("SELECT id, name FROM clients WHERE id=?", (r["client_id"],)).fetchone() if r["client_id"] else None
    items = c.execute("SELECT title, detail, qty, unit, kind FROM office_doc_items WHERE doc_id=? ORDER BY sort, id", (did,)).fetchall()
    try:
        total = (json.loads(r["totals"] or "{}") or {}).get("gross")
    except ValueError:
        total = None
    return {"id": did, "number": r["number"], "title": r["project_title"], "client": {"id": cl["id"], "name": cl["name"]} if cl else None,
            "currency": r["currency"], "total": total,
            "items": [{"title": x["title"], "detail": (x["detail"] or "")[:500], "qty": float(x["qty"] or 0), "unit": x["unit"], "kind": x["kind"]}
                      for x in items][:PK2_OFFER_ITEMS_MAX]}


def pk2_make_input(c, uid, aid, kind, text=None, file_name=None, offer_id=None):
    """The job input of an inquiry / setup proposal: only what the agent may see."""
    from ..lists.templates import PTYPES
    if kind == "setup":
        fs = set(x for x in (usettings(c, uid).get("features") or "").split(",") if x)
        return {"modules": [{"key": k, "on": k in fs} for k in PK2_MODS], "project_types": list(PTYPES)}
    org, oid = pk2_area(c, uid, aid)
    ok, why = pk2_office(c, uid, aid, oid)
    inp = {"text": text, "file_name": file_name, "area": "org" if org else "private", "project_types": list(PTYPES),
           "office": {"ok": ok, **({"reason": why} if why else {})}, "clients": []}
    if ok:
        inp["clients"] = [{"id": r["id"], "name": r["name"]} for r in _pk2_clients(c, uid, oid)]
        _pk2_log(c, oid, aid, uid, False, "clients")
    if offer_id is not None:
        if not ok:
            raise Denied(403, tr("The agent may not read office data here"))
        inp["offer"] = _pk2_offer(c, uid, oid, offer_id)
        _pk2_log(c, oid, aid, uid, False, "doc", offer_id)
    return inp


def pk2_input(c, uid, kind, b):
    """POST /api/proposals {agent_id, kind: inquiry, text, file_name?, offer_id?} | {agent_id, kind: setup, text?}
    -> (input, title, task_id, list_id) like prop_input."""
    from .proposals import _p_keys, _p_str, _p_int, PROP_TEXT_MAX
    aid = int(b.get("agent_id") or 0)
    if kind == "setup":
        _p_keys(b, "", ("agent_id", "kind", "text"))
        inp = pk2_make_input(c, uid, aid, kind)
        inp["text"] = _p_str(b.get("text"), "text", PROP_TEXT_MAX, line=False) or None
        return inp, tr(PK2_TITLES["setup"]), None, None
    _p_keys(b, "", ("agent_id", "kind", "text", "file_name", "offer_id"))
    oid = None if b.get("offer_id") in (None, "") else _p_int(b.get("offer_id"), "offer_id")
    text = _p_str(b.get("text"), "text", PROP_TEXT_MAX, oid is None, line=False) or None
    inp = pk2_make_input(c, uid, aid, kind, text, _p_str(b.get("file_name"), "file_name", 200) or None, oid)
    return inp, tr(PK2_TITLES["inquiry"]), None, None


# ---------------------------------------------------------------- validation (BadInput -> 400)
def _pk2_num(v, what, lo=0.0, hi=1e9, none=True):
    if v in (None, "") and none:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise BadInput(tr("Invalid value: {0}", what))
    return v


def _pk2_hm(v, what):
    from ..tasks.validation import valid_hm
    if v in (None, ""):
        return None
    if not isinstance(v, str) or not valid_hm(v):
        raise BadInput(tr("Invalid value: {0}", what))
    return v


def pk2_validate(kind, b, inp):
    """The kind-specific part of prop_validate (b: the agent's proposal)."""
    from .proposals import _p_keys, _p_str, _p_int, _p_list, _p_date, prop_validate, PROP_TITLE_MAX, PROP_NOTES_MAX, PROP_NAME_MAX, PROP_SECTIONS_MAX
    from ..lists.templates import PTYPES
    common = ("kind", "summary")
    if kind == "setup":
        _p_keys(b, "", (*common, "modules", "lists", "project"))
        have = {m["key"]: m["on"] for m in inp.get("modules", [])}
        mods, seen = [], set()
        for i, m in enumerate(_p_list(b.get("modules"), "modules", len(PK2_MODS))):
            w = f"modules[{i}]"
            _p_keys(m, w, ("key", "on"))
            k = m.get("key")
            if k not in PK2_MODS or k in seen or not isinstance(m.get("on"), bool):
                raise BadInput(tr("Invalid value: {0}", w))
            seen.add(k)
            if have.get(k) != m["on"]:  # only real changes
                mods.append({"key": k, "on": m["on"]})
        lists = []
        for i, x in enumerate(_p_list(b.get("lists"), "lists", PK2_LISTS_MAX)):
            w = f"lists[{i}]"
            _p_keys(x, w, ("name", "color", "folder", "sections"))
            secs = []
            for k, s in enumerate(_p_list(x.get("sections"), w + ".sections", PROP_SECTIONS_MAX)):
                s = _p_str(s, f"{w}.sections[{k}]", 100, True)
                if s.casefold() not in (y.casefold() for y in secs):
                    secs.append(s)
            lists.append({"name": _p_str(x.get("name"), w + ".name", PROP_NAME_MAX, True), "color": clean_color(x.get("color")),
                          "folder": clean_folder(_p_str(x.get("folder"), w + ".folder", FOLDER_MAX)) or "", "sections": secs})
        proj = None
        if b.get("project") not in (None, {}):
            p = _p_keys(b.get("project"), "project", ("type", "name"))
            if p.get("type") not in PTYPES:
                raise BadInput(tr("Invalid value: {0}", "project.type"))
            proj = {"type": p["type"], "name": _p_str(p.get("name"), "project.name", PROP_NAME_MAX, True)}
        if not mods and not lists and not proj:
            raise BadInput(tr("Missing field: {0}", "modules / lists / project"))
        return {"modules": mods, "lists": lists, "project": proj}
    # inquiry
    _p_keys(b, "", (*common, "name", "folder", "project_type", "client", "sections", "tasks", "shoot_days", "offer"))
    base = prop_validate("project", {k: b[k] for k in ("name", "folder", "sections", "tasks") if k in b}, {})
    out = {k: base[k] for k in ("name", "folder", "sections", "tasks")}
    pt = b.get("project_type")
    if pt not in (None, "") and pt not in PTYPES:
        raise BadInput(tr("Invalid value: {0}", "project_type"))
    out["project_type"] = pt or None
    cl = None
    if b.get("client") not in (None, {}):
        x = _p_keys(b.get("client"), "client", ("id", "name"))
        if x.get("id") not in (None, ""):
            cid = _p_int(x["id"], "client.id")
            hit = next((y for y in inp.get("clients", []) if y["id"] == cid), None)
            if not hit:
                raise BadInput(tr("Invalid value: {0}", "client.id"))
            cl = {"id": cid, "name": hit["name"]}
        else:
            cl = {"id": None, "name": _p_str(x.get("name"), "client.name", PROP_NAME_MAX, True)}
    if inp.get("offer"):
        if cl and cl["id"] is not None and cl["id"] != (inp["offer"].get("client") or {}).get("id"):
            raise BadInput(tr("Invalid value: {0}", "client.id"))
        cl = inp["offer"].get("client") and {**inp["offer"]["client"]}
    out["client"] = cl
    shoots = []
    for i, s in enumerate(_p_list(b.get("shoot_days"), "shoot_days", PK2_SHOOT_MAX)):
        w = f"shoot_days[{i}]"
        _p_keys(s, w, ("title", "date", "end_date", "start_time", "end_time", "location", "notes"))
        d = _p_date(s.get("date"), w + ".date")
        if not d:
            raise BadInput(tr("Missing field: {0}", w + ".date"))
        ed = _p_date(s.get("end_date"), w + ".end_date")
        if ed and ed < d:
            raise BadInput(tr("Invalid value: {0}", w + ".end_date"))
        st, et = _pk2_hm(s.get("start_time"), w + ".start_time"), _pk2_hm(s.get("end_time"), w + ".end_time")
        if et and not st:
            raise BadInput(tr("Missing field: {0}", w + ".start_time"))
        if st and et and (ed or d) == d and et <= st:
            raise BadInput(tr("Invalid value: {0}", w + ".end_time"))
        shoots.append({"title": _p_str(s.get("title"), w + ".title", PROP_TITLE_MAX, True), "date": d, "end_date": ed if ed != d else None,
                       "start_time": st, "end_time": et, "location": _p_str(s.get("location"), w + ".location", 200),
                       "notes": _p_str(s.get("notes"), w + ".notes", PROP_NOTES_MAX, line=False)})
    out["shoot_days"] = shoots
    offer = None
    if b.get("offer") not in (None, {}):
        if inp.get("offer"):
            raise BadInput(tr("This project comes from an accepted quotation: it gets no new one"))
        o = _p_keys(b.get("offer"), "offer", ("title", "intro", "items"))
        items = []
        raw = _p_list(o.get("items"), "offer.items", PK2_OFFER_ITEMS_MAX)
        if not raw:
            raise BadInput(tr("Missing field: {0}", "offer.items"))
        for i, it in enumerate(raw):
            w = f"offer.items[{i}]"
            _p_keys(it, w, ("service_id", "text", "qty", "unit", "price", "discount"))
            sid = it.get("service_id")
            items.append({"service_id": None if sid in (None, "") else _p_int(sid, w + ".service_id"),
                          "text": _p_str(it.get("text"), w + ".text", PROP_TITLE_MAX, True),
                          "qty": _pk2_num(it.get("qty"), w + ".qty", 0, 1e6, none=False),
                          "unit": _p_str(it.get("unit"), w + ".unit", 20) or None,
                          "price": _pk2_num(it.get("price"), w + ".price", -1e9, 1e9),
                          "discount": _pk2_num(it.get("discount"), w + ".discount", 0, 100)})
        offer = {"title": _p_str(o.get("title"), "offer.title", PROP_TITLE_MAX) or out["name"],
                 "intro": _p_str(o.get("intro"), "offer.intro", PROP_NOTES_MAX, line=False), "items": items}
    out["offer"] = offer
    return out


def pk2_keys(kind, prop, inp):
    """All selection keys of a proposal (the offer only when it is possible)."""
    if kind == "setup":
        return [str(i) for i in range(len(prop["modules"]))] + [str(PK2_LIST_KEY + i) for i in range(len(prop["lists"]))] \
            + ([str(PK2_PROJECT_KEY)] if prop.get("project") else [])
    ks = [k for i, t in enumerate(prop["tasks"]) for k in [str(i), *(f"{i}.{j}" for j in range(len(t["subtasks"])))]]
    ks += [str(PK2_SHOOT_KEY + i) for i in range(len(prop["shoot_days"]))]
    if prop.get("offer") and (inp.get("office") or {}).get("ok"):
        ks += [str(PK2_OFFER_KEY)] + [f"{PK2_OFFER_KEY}.{j}" for j in range(len(prop["offer"]["items"]))]
    return ks


def pk2_edit(kind, key, e, prop):
    """One edited entry of the review dialog: title (a task, a shoot day, a list, the project), due (a task's due date,
    a shoot day's date), section (a task)."""
    from .proposals import _p_keys, _p_str, _p_date, PROP_TITLE_MAX
    _p_keys(e, f"edits.{key}", ("title", "due", "section"))
    out = {}
    if "title" in e:
        out["title"] = _p_str(e["title"], "title", PROP_TITLE_MAX, True)
    if "due" in e:
        out["due"] = _p_date(e["due"], "due")
        if kind == "inquiry" and key.isdigit() and PK2_SHOOT_KEY <= int(key) < PK2_OFFER_KEY and not out["due"]:
            raise BadInput(tr("Missing field: {0}", "date"))
    if kind == "inquiry" and "section" in e:
        out["section"] = _p_str(e["section"], "section", 100) or None
        if out["section"] and out["section"].casefold() not in (s.casefold() for s in prop["sections"]):
            raise BadInput(tr("Unknown section: {0}", out["section"]))
    return out


# ---------------------------------------------------------------- apply / undo / redo
def _pk2_features(c, uid):
    return [x for x in (usettings(c, uid).get("features") or "").split(",") if x]


def _pk2_mod_on(c, uid, k, rec):
    fs = _pk2_features(c, uid)
    if k not in fs:
        uset(c, uid, "features", ",".join(fs + [k]))
        rec["modules_on"].append(k)


def _pk2_new_list(c, uid, name, color="", folder="", kind="list", org="auto"):
    """A new list of uid (owner), in organisation org (None = private, "auto" = the default workspace)."""
    from ..accounts.orgs import ws_default_org
    ts = iso(now_utc())
    lid = insert_id(c, "INSERT INTO lists(name,color,folder,sort,view,created_at,owner_id,checklist,kind,org_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (name, color or "", folder or "", my_max_sort(c, uid) + 1, "list", ts, uid, 0, kind,
                     ws_default_org(c, uid, folder) if org == "auto" else org))
    list_created(c, uid, lid)
    return lid


def _pk2_share(c, aid, lid, rec):
    """The box "Share the new list with <agent>" (the same checks as kind project)."""
    from ..accounts.orgs import ws_member_problem
    from ..agents.core import agent_active, agent_row
    from ..agents.safety import bridge_blocks
    if agent_active(agent_row(c, aid)) and not list_other_agent(c, lid, aid) and not ws_member_problem(c, lid, aid) \
            and not bridge_blocks(c, lid, aid):
        c.execute("INSERT INTO list_members(list_id,user_id,role,sort,added_at) VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING",
                  (lid, aid, "edit", my_max_sort(c, aid) + 1, iso(now_utc())))
        rec["shared"] = True


def _pk2_event(c, uid, s, e, lid):
    """A shoot day -> an event draft (status tentative) in uid's own calendar."""
    from ..events.model import default_cal, ev_fields, ev_store
    from datetime import date, timedelta
    d = e.get("due") or s["date"]
    end_d = s["end_date"] if s["end_date"] and s["end_date"] >= d else d
    if s["start_time"]:
        # 2.51.0 (#1351) review: an end date without an end time keeps the end date (until the end of that day)
        f = {"title": e.get("title", s["title"]), "all_day": False, "start": f"{d}T{s['start_time']}",
             "end": f"{end_d}T{s['end_time']}" if s["end_time"] else f"{end_d}T23:59" if end_d > d else None}
    else:
        f = {"title": e.get("title", s["title"]), "all_day": True, "start": d,
             "end": (date.fromisoformat(end_d) + timedelta(days=1)).isoformat()}
    f.update(location=s["location"], description=s["notes"], status="tentative")
    return ev_store(c, uid, default_cal(c, uid), ev_fields(c, uid, f))


def _pk2_events_at(c, rec):
    """2.51.0 (#1351) review: each event draft's updated_at as it stands now (undo compares with it; rec["at"] has seconds
    and is taken before the drafts are written)."""
    ids = rec.get("events") or []
    rec["events_at"] = {str(r["id"]): r["updated_at"] for r in c.execute(
        f"SELECT id, updated_at FROM events WHERE id IN ({','.join('?' * len(ids)) or 'NULL'})", ids)}


def pk2_run(c, j, sel, ed, extra, rec):
    """Applies the selected entries as the current person; fills rec (the undo record of prop_run)."""
    from .proposals import prop_insert, _p_str, PROP_NAME_MAX
    kind, aid, uid = j["kind"], j["agent_id"], me()
    prop, inp = json.loads(j["proposal"]), json.loads(j["input"] or "{}")
    edits = {k: pk2_edit(kind, k, v, prop) for k, v in ed.items()}
    selected = set(sel) & set(pk2_keys(kind, prop, inp))
    if not selected:
        raise BadInput(tr("Select at least one entry"))
    rec.update(events=[], offer=None, deals=[], modules_on=[], lists=[], parts_skipped=[])
    ts = rec["at"]
    if kind == "setup":
        return _pk2_setup(c, uid, prop, selected, edits, rec)
    org, oid = pk2_area(c, uid, aid)
    name = _p_str(extra.get("name") or prop["name"], "name", PROP_NAME_MAX, True)
    folder = clean_folder(extra.get("folder") if extra.get("folder") is not None else prop.get("folder") or "", False)
    if prop.get("project_type"):
        from ..lists.templates import ptype_create
        lid, on = ptype_create(c, uid, prop["project_type"], name, folder, sections=not prop["sections"], org_id=org)
        rec["modules_on"] += on
    else:
        lid = _pk2_new_list(c, uid, name, folder=folder, kind="project", org=org)
    rec["list"] = lid
    have = {r["name"].casefold(): r["id"] for r in c.execute("SELECT id, name FROM sections WHERE list_id=?", (lid,))}
    secs = {}
    for i, s in enumerate(prop["sections"]):
        secs[s.casefold()] = have.get(s.casefold()) or insert_id(c, "INSERT INTO sections(list_id,name,sort) VALUES(?,?,?)", (lid, s, len(have) + i + 1))
        rec["sections"].append(secs[s.casefold()])
    ids = {}
    for i, t in enumerate(prop["tasks"]):
        if str(i) not in selected:
            continue
        e = edits.get(str(i), {})
        sec = e.get("section", t["section"])
        ids[i] = prop_insert(c, aid, lid, ts, e.get("title", t["title"]), t["notes"], secs.get((sec or "").casefold()), None,
                             e.get("due", t["due"]), t["start"], t["priority"], sort=i + 1)
        rec["tasks"].append(ids[i])
        for k, s in enumerate(t["subtasks"]):
            if f"{i}.{k}" not in selected:
                continue
            se = edits.get(f"{i}.{k}", {})
            rec["tasks"].append(prop_insert(c, aid, lid, ts, se.get("title", s["title"]), s["notes"], secs.get((sec or "").casefold()),
                                            ids[i], se.get("due", s["due"]), sort=k + 1))
    for i, t in enumerate(prop["tasks"]):
        for d in t["depends_on"]:
            if i in ids and d in ids:
                c.execute("INSERT INTO task_deps(task_id,blocker_id,created_by,created_at) VALUES(?,?,?,?) ON CONFLICT DO NOTHING", (ids[i], ids[d], uid, ts))
    cl = prop.get("client") or {}
    cid = cl.get("id")
    if cid is None and cl.get("name") and oid:  # a name: an existing client of the area with exactly that name
        cid = next((r["id"] for r in _pk2_clients(c, uid, oid) if r["name"].strip().casefold() == cl["name"].strip().casefold()), None)
    if cid:
        from ..team.clients import list_client_set
        try:
            with c.savepoint():
                list_client_set(c, lid, cid)
            rec["client"] = cid
        except (Denied, BadInput):
            rec["parts_skipped"].append("client")
    shoot = [i for i in range(len(prop["shoot_days"])) if str(PK2_SHOOT_KEY + i) in selected]
    if shoot:
        _pk2_mod_on(c, uid, "events", rec)
        for i in shoot:
            rec["events"].append(_pk2_event(c, uid, prop["shoot_days"][i], edits.get(str(PK2_SHOOT_KEY + i), {}), lid))
        _pk2_events_at(c, rec)
    if str(PK2_OFFER_KEY) in selected:
        _pk2_offer_make(c, uid, aid, oid, lid, prop, selected, cid, rec)
    if inp.get("offer"):  # the accepted quotation: its deal (pipeline) gets the project, like pl2_make_project
        try:
            with c.savepoint():
                rec["deals"] = [r[0] for r in c.execute(
                    "UPDATE office_deals SET list_id=?, updated_at=? WHERE org_id=? AND offer_id=? AND list_id IS NULL AND deleted_at IS NULL RETURNING id",
                    (lid, ts, oid, inp["offer"]["id"])).fetchall()]
        except Exception:  # noqa: BLE001 -- no pipeline in this area: the project stands on its own
            rec["deals"] = []
    if extra.get("share_agent"):
        _pk2_share(c, aid, lid, rec)
    return rec


def _pk2_offer_make(c, uid, aid, oid, lid, prop, selected, cid, rec):
    """The quotation draft (part A's ofa_draft_create checks the person's office right, the agent's switches are checked
    here again: they may have changed since the proposal came)."""
    ok, why = pk2_office(c, uid, aid, oid)
    if not ok:
        rec["parts_skipped"].append("offer")
        return
    from ..office.agentdocs import ofa_draft_create
    o = prop["offer"]
    data = {"client_id": cid, "title": o["title"], "intro": o["intro"], "list_id": lid,
            "items": [{"service_id": x["service_id"], "text": x["text"], "qty": x["qty"], "unit": x["unit"], "price": x["price"],
                       "discount": x["discount"]} for j, x in enumerate(o["items"]) if f"{PK2_OFFER_KEY}.{j}" in selected]}
    if not data["items"]:
        rec["parts_skipped"].append("offer")
        return
    try:
        with c.savepoint():
            rec["offer"] = ofa_draft_create(c, uid, oid, data, agent_id=aid)
            rec["offer_area"] = oid
            _pk2_log(c, oid, aid, uid, True, "offer", rec["offer"])
            # 2.51.0 (#1351) review: undo deletes only this very draft (no number, unchanged since)
            rec["offer_at"] = c.execute("SELECT updated_at FROM office_docs WHERE id=? AND org_id=?", (rec["offer"], oid)).fetchone()[0]
            rec["offer_log"] = c.execute("SELECT COALESCE(MAX(id), 0) FROM office_doc_log WHERE org_id=?", (oid,)).fetchone()[0]
    except (PermissionError, Denied, BadInput, UnknownFields):
        rec["parts_skipped"].append("offer")


def _pk2_setup_list(c, uid, x, name):
    lid = _pk2_new_list(c, uid, name, x["color"], x["folder"])
    for i, s in enumerate(x["sections"]):
        insert_id(c, "INSERT INTO sections(list_id,name,sort) VALUES(?,?,?)", (lid, s, i + 1))
    return lid


def _pk2_setup(c, uid, prop, selected, edits, rec):
    from ..lists.templates import ptype_create
    fs = _pk2_features(c, uid)
    rec["features_before"] = ",".join(fs)
    for i, m in enumerate(prop["modules"]):
        if str(i) in selected:
            fs = [x for x in fs if x != m["key"]] + ([m["key"]] if m["on"] else [])
    if ",".join(fs) != rec["features_before"]:
        uset(c, uid, "features", ",".join(fs))
    rec["features_after"] = ",".join(fs)
    for i, x in enumerate(prop["lists"]):
        k = str(PK2_LIST_KEY + i)
        if k in selected:
            rec["lists"].append(_pk2_setup_list(c, uid, x, edits.get(k, {}).get("title", x["name"])))
    p = prop.get("project")
    if p and str(PK2_PROJECT_KEY) in selected:
        lid, on = ptype_create(c, uid, p["type"], edits.get(str(PK2_PROJECT_KEY), {}).get("title", p["name"]), sections=True)
        rec["lists"].append(lid)
        rec["list"] = lid
        rec["modules_on"] += [m for m in on if m not in rec["features_before"].split(",")]
        rec["features_after"] = ",".join(_pk2_features(c, uid))
    return rec


def pk2_result(rec):
    """Counts for the apply answer / the agent's event."""
    return {"events": len(rec.get("events") or []), "offer_id": rec.get("offer"), "lists": len(rec.get("lists") or []), "project_list_id": rec.get("list"),
            "modules": len([x for x in (rec.get("features_after") or "").split(",") if x not in (rec.get("features_before") or "").split(",")])
            + len([x for x in (rec.get("features_before") or "").split(",") if x and x not in (rec.get("features_after") or "").split(",")]),
            "parts_skipped": rec.get("parts_skipped") or []}


def _pk2_list_empty(c, lid, ids, at, keep_members=()):
    """Nobody added or changed anything in list lid since `at` (only the tasks ids of this proposal, unchanged).
    2.51.0 (#1351) review: purging the list cascades, so also no files, sign-offs, office documents (this proposal's draft
    is already gone when undo deleted it) and no members besides keep_members (the person, the agent shared with)."""
    q = ",".join("?" * len(ids)) or "NULL"
    others = c.execute(f"SELECT COUNT(*) FROM tasks WHERE list_id=? AND id NOT IN ({q})", (lid, *ids)).fetchone()[0]
    changed = c.execute(f"SELECT COUNT(*) FROM tasks WHERE id IN ({q}) AND (deleted_at IS NOT NULL OR updated_at>?)", (*ids, at)).fetchone()[0]
    own = c.execute("SELECT 1 FROM lists WHERE id=? AND owner_id=?", (lid, me())).fetchone()
    if others or changed or not own:
        return False
    km = list(keep_members) or [0]
    for sql, args in (("SELECT 1 FROM list_files WHERE list_id=? LIMIT 1", (lid,)),
                      ("SELECT 1 FROM office_signoffs WHERE list_id=? LIMIT 1", (lid,)),
                      ("SELECT 1 FROM office_docs WHERE list_id=? LIMIT 1", (lid,)),
                      (f"SELECT 1 FROM list_members WHERE list_id=? AND user_id NOT IN ({','.join('?' * len(km))}) LIMIT 1", (lid, *km))):
        if c.execute(sql, args).fetchone():
            return False
    return True


def pk2_undo(c, j, rec):
    """One undo step -> (n, skipped titles). What someone changed since stays (named in skipped)."""
    from .proposals import prop_titles
    from ..lists.projects import list_row_purge
    from ..tasks.lifecycle import do_delete
    from ..tasks.validation import log_act
    from ..events.model import ev_delete
    uid, n, skipped = me(), 0, []
    if j["kind"] == "setup":
        if _pk2_features(c, uid) == [x for x in (rec.get("features_after") or "").split(",") if x]:
            uset(c, uid, "features", rec.get("features_before") or "")
            n += 1
        elif rec.get("features_after") != rec.get("features_before"):
            skipped.append(tr("Modules"))
        rec["lists_deleted"] = []
        for lid in rec.get("lists") or []:
            r = c.execute("SELECT name FROM lists WHERE id=?", (lid,)).fetchone()
            if not r:
                continue
            if not c.execute("SELECT 1 FROM tasks WHERE list_id=? LIMIT 1", (lid,)).fetchone() and \
                    c.execute("SELECT 1 FROM lists WHERE id=? AND owner_id=?", (lid, uid)).fetchone():
                list_row_purge(c, lid, g.setdefault("purge_lists", []))
                rec["lists_deleted"].append(lid)
                n += 1
            else:
                skipped.append(r["name"][:40])
        return n, skipped
    ev_stayed = False
    for eid in rec.get("events") or []:  # event drafts: only while still a draft nobody changed
        r = c.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone()
        if not r or r["deleted_at"]:
            continue
        at = (rec.get("events_at") or {}).get(str(eid))  # 2.51.0 (#1351) review: the draft's own updated_at
        if r["status"] == "tentative" and (r["updated_at"] == at if at else (r["updated_at"] or "")[:19] <= rec["at"][:19]):
            ev_delete(c, r)
            rec.setdefault("events_deleted", []).append(eid)
            n += 1
        else:
            skipped.append(r["title"][:40])
            ev_stayed = True
    if rec.get("offer"):  # the quotation draft goes while it is a draft without a number nobody changed since applying
        oid = rec.get("offer_area")
        from ..office.docs import bga_offer_block
        from ..office.model import office_role
        write_lock(c, f"office_mail_{int(oid or 0)}")  # 2.149.0 A (#2521): the same locks and checks as deleting it in the office (docs.odoc_delete)
        write_lock(c, f"office_doc_{int(rec['offer'])}")
        r = c.execute("SELECT id, kind, status, number, sent_at, updated_at, project_title FROM office_docs WHERE id=? AND org_id=?", (rec["offer"], oid)).fetchone()
        if r and r["status"] == "draft" and not r["number"] and rec.get("offer_at") and r["updated_at"] == rec["offer_at"] \
                and office_role(c, uid, oid) == "admin" and bga_offer_block(c, oid, r) is None \
                and not c.execute("SELECT 1 FROM office_signoffs WHERE doc_id=? LIMIT 1", (rec["offer"],)).fetchone() \
                and not c.execute("SELECT 1 FROM office_doc_log WHERE org_id=? AND doc_id=? AND id>? AND action IN ('update','items','number','status') LIMIT 1",
                                  (oid, rec["offer"], rec.get("offer_log") or 0)).fetchone():  # changes within the same second
            from ..office.ledger import ofx_log
            c.execute("DELETE FROM office_docs WHERE id=? AND org_id=? AND status='draft' AND number=''", (rec["offer"], oid))
            ofx_log(c, oid, "delete", doc_id=rec["offer"], detail={"number": "", "status": "draft", "undo": "proposal"})
            rec["offer_deleted"] = True
            n += 1
        elif r:
            skipped.append((r["project_title"] or "")[:40] or tr("Quotation"))
    if rec.get("deals"):
        q = ",".join("?" * len(rec["deals"]))
        c.execute(f"UPDATE office_deals SET list_id=NULL WHERE id IN ({q}) AND list_id=?", (*rec["deals"], rec["list"]))
    ids, lid = rec["tasks"], rec.get("list")
    if lid and _pk2_list_empty(c, lid, ids, rec["at"], [uid] + ([j["agent_id"]] if rec.get("shared") else [])):
        list_row_purge(c, lid, g.setdefault("purge_lists", []))
        rec["list_deleted"] = True
        n += len(ids) or 1
    else:
        q = ",".join("?" * len(ids)) or "NULL"
        mine = {r[0] for r in c.execute(f"SELECT id FROM tasks WHERE id IN ({q}) AND deleted_at IS NULL AND updated_at<=?", (*ids, rec["at"]))}
        skipped += prop_titles(c, [i for i in ids if i not in mine and c.execute("SELECT 1 FROM tasks WHERE id=? AND deleted_at IS NULL", (i,)).fetchone()])
        for tid in ids:
            if tid in mine:
                do_delete(c, tid)
                log_act(c, tid, "delete")
        rec["trashed"] = sorted(mine)
        n += len(mine)
    # modules this apply switched on go off again -- 2.51.0 (#1351) review: not while event drafts stayed
    if rec.get("modules_on") and not ev_stayed:
        fs = [x for x in _pk2_features(c, uid) if x not in rec["modules_on"]]
        uset(c, uid, "features", ",".join(fs))
    return n, skipped


def pk2_redo(c, j, rec):
    """The way forward again -> (rec, n, skipped)."""
    from .proposals import prop_run
    from ..tasks.lifecycle import restore_task
    uid, n, skipped = me(), 0, []
    if j["kind"] == "inquiry" and rec.get("list_deleted") or j["kind"] == "setup" and rec.get("lists") \
            and len(rec.get("lists_deleted") or []) == len(rec["lists"]):
        rec = prop_run(c, j, rec["sel"], rec["edits"], rec.get("extra") or {})
        return rec, len(rec["tasks"]) + len(rec.get("events") or []) + len(rec.get("lists") or []) + (1 if rec.get("offer") else 0), []
    if j["kind"] == "setup":
        if _pk2_features(c, uid) == [x for x in (rec.get("features_before") or "").split(",") if x]:
            uset(c, uid, "features", rec.get("features_after") or "")
            n += 1
        rec["undone"] = False
        return rec, n, skipped
    back = rec.get("trashed") or []
    for tid in back:
        r = c.execute("SELECT deleted_at FROM tasks WHERE id=?", (tid,)).fetchone()
        if r and r["deleted_at"] and r["deleted_at"] >= rec.get("undone_at", ""):
            restore_task(c, tid)
    n += c.execute(f"SELECT COUNT(*) FROM tasks WHERE id IN ({','.join('?' * len(back)) or 'NULL'}) AND deleted_at IS NULL", back).fetchone()[0]
    ev = rec.get("events_deleted") or []
    if ev:
        n += c.execute(f"UPDATE events SET deleted_at=NULL, updated_at=? WHERE id IN ({','.join('?' * len(ev))}) AND deleted_at IS NOT NULL",
                       (iso(now_utc()), *ev)).rowcount
        rec["events_deleted"] = []
        _pk2_events_at(c, rec)
    if rec.get("offer_deleted"):  # a new draft from the same proposal
        prop = json.loads(j["proposal"])
        cid = rec.get("client")
        rec["offer"], rec["offer_deleted"] = None, False
        _pk2_offer_make(c, uid, j["agent_id"], rec.get("offer_area"), rec["list"], prop, set(rec["sel"]), cid, rec)
        n += 1 if rec.get("offer") else 0
    if rec.get("deals"):
        q = ",".join("?" * len(rec["deals"]))
        c.execute(f"UPDATE office_deals SET list_id=? WHERE id IN ({q}) AND list_id IS NULL", (rec["list"], *rec["deals"]))
    if rec.get("modules_on"):
        fs = _pk2_features(c, uid)
        uset(c, uid, "features", ",".join(fs + [x for x in rec["modules_on"] if x not in fs]))
    rec["undone"] = False
    return rec, n, skipped


# ---------------------------------------------------------------- the agent proposes on its own (chat, offer_accepted)
def pk2_agent_proposal(aid, b):
    """POST /api/v1/agent/proposals {kind: inquiry | setup, user_id, title?, offer_id?, proposal: {...}}: the agent turns a
    chat request (an inquiry, "set me up") or an accepted quotation into a ready proposal for that person. Only for a
    person who may ask this agent for proposals (agents.proposals); the person applies or discards it."""
    from .proposals import _p_keys, _p_int, _p_str, prop_agent_ok, prop_ready_notify, prop_validate, PROP_TITLE_MAX, PROP_MAX_BYTES
    from ..agents.core import agent_row, agent_shares, job_dict, JOB_TITLE_MAX
    from ..agents.usage import usage_block
    from ..collab.comments import user_names
    from flask import request
    _p_keys(b, "", ("kind", "user_id", "title", "offer_id", "proposal"))
    kind = b["kind"]
    uid = _p_int(b.get("user_id"), "user_id")
    title = _p_str(b.get("title"), "title", PROP_TITLE_MAX)
    if len(request.data or b"") > PROP_MAX_BYTES:
        return v1_err(413, tr("The proposal is too large (at most {0} KB)", PROP_MAX_BYTES // 1024))
    c = db()
    a = agent_row(c, aid)
    if not a or not prop_agent_ok(c, a, uid):
        raise Denied(404)
    # 2.51.0 (#1351) review: only a person the agent works with (like office/agentdocs.py _v1ctx), also in the mode "all"
    u = c.execute("SELECT kind, kid FROM users WHERE id=?", (uid,)).fetchone()
    if not u or u["kind"] != "user" or u["kid"] or not agent_shares(c, aid, uid):
        raise Denied(404)
    if usage_block(c, aid):
        return v1_err(409, tr("{0} reached its usage limit", a["display_name"] if "display_name" in a.keys() else "?"))
    if c.execute("SELECT COUNT(*) FROM agent_jobs WHERE agent_id=? AND user_id=? AND kind IN ('inquiry','setup') AND prop_state='ready'",
                 (aid, uid)).fetchone()[0] >= PK2_OPEN_MAX:
        return v1_err(429, tr("You have {0} open proposals for this person: wait until they decided on them", PK2_OPEN_MAX))
    if c.execute("SELECT COUNT(*) FROM agent_jobs WHERE agent_id=? AND kind IN ('inquiry','setup') AND prop_state='ready'",
                 (aid,)).fetchone()[0] >= PK2_OPEN_AGENT_MAX:
        return v1_err(429, tr("You have {0} open proposals: wait until people decided on them", PK2_OPEN_AGENT_MAX))
    if kind == "setup" and b.get("offer_id") not in (None, ""):
        raise UnknownFields(["offer_id"])
    offer_id = None if b.get("offer_id") in (None, "") else _p_int(b.get("offer_id"), "offer_id")
    with _pk2_as(c, uid):
        inp = pk2_make_input(c, uid, aid, kind, offer_id=offer_id)
        inp["via"] = "agent"
        prop = b.get("proposal")
        if isinstance(prop, dict) and prop.get("kind") not in (None, kind):
            raise BadInput(tr("This job expects a proposal of kind {0}", kind))
        p = prop_validate(kind, prop, inp)
    ts = iso(now_utc())
    aname = user_names(c, [aid]).get(aid, "?")
    jt = tr("Proposal from {0}: {1}", aname, title or tr(PK2_TITLES[kind]))
    jid = insert_id(c, """INSERT INTO agent_jobs(agent_id,task_id,user_id,title,state,log,created_at,updated_at,kind,input,prop_state,list_id,proposal)
                       VALUES(?,NULL,?,?,'waiting','',?,?,?,?,'ready',NULL,?)""",
                    (aid, uid, jt[:JOB_TITLE_MAX], ts, ts, kind, json.dumps(inp, ensure_ascii=False), json.dumps(p, ensure_ascii=False)))
    j = c.execute("SELECT * FROM agent_jobs WHERE id=?", (jid,)).fetchone()
    prop_ready_notify(c, j)
    bump(c)
    c.commit()
    print("agent proposal", jid, kind, "agent", aid, "for user", uid, flush=True)
    return jsonify({**job_dict(c, j), "proposal": p, "input": inp}), 201
