"""2.51.0 (#1355): shoot planning by an agent -- event drafts in the project calendar, crew / equipment as options from the
disposition (2.50.0, hub/dispo.py), double bookings and absences as warnings. A person confirms; nothing is ever firm.

- An event draft = an event with status 'tentative' (iCalendar TENTATIVE, CalDAV keeps it) in the confirming person's own
  calendar (adz_event_draft, also for the other parts of 2.51). The calendar shows drafts pale and dashed with "Draft" and
  the buttons Confirm (-> confirmed) / Discard (delete, undo restores).
- The project calendar = the tasks of the project list by date plus their linked events: every shoot day of a proposal
  becomes a task of the project list (due = the day) with its draft event linked (events.task_id), crew / equipment become
  bookings with status option, list_id = the project and event_id = the draft. No new column.
- Agents read the disposition of their own workspace (GET /api/v1/dispo, /api/v1/dispo/free; scope calendar): an agent
  of an organisation (agents.org_id) that organisation, a personal agent its owner's personal area (#1360: freelancers
  without an organisation get the same). Absences only as "away", never the kind.
- Proposal kind shoot (POST /api/v1/agent/proposals/shoot, scope calendar): days (date, time, place, title; a second
  variant = a day row with alt_of) + crew rows (a resource of the area for a day). The server checks every row against the
  area's bookings and absences and stores the warnings with the row; "Apply" makes the drafts and options as the person,
  one undo step (drafts / tasks / options go again)."""
import contextlib
import json
import secrets
from datetime import date, timedelta

from flask import g, jsonify, request

from ..core.config import app
from ..core.pg import insert_id, system_ctx
from ..core.i18n import tr
from ..core.db import bump, db, iso, local_now, now_utc
from ..core.access import Denied, list_role, need_feat, WRITE_ROLES
from ..accounts.session import me
from ..personal.timetrack import BadInput
from ..api.v1 import v1_args, v1_err, v1_json, v1_view
from .dispo import DSP_DAYS_MAX, DSP_KINDS, dsp_conflicts, dsp_public, dsp_resources, dsp_units, _res_index, _ts
from .absence import abs_days, abs_holidays, abs_org, abs_state

ADZ_DAYS_MAX = 31          # shoot days of one proposal
ADZ_CREW_MAX = 120         # crew / equipment rows of one proposal
ADZ_TEXT_MAX = 200


# ---------------------------------------------------------------- the shared helper: an event draft
def adz_event_draft(c, uid, title, start, end, all_day=False, location="", task_id=None, note=""):
    """A tentative event in uid's own (first) calendar -> its id. start / end: YYYY-MM-DD (all_day) or YYYY-MM-DDTHH:MM
    (local wall time). Validated like every event (ev_fields); task_id must be visible to uid. The caller commits."""
    from ..events.model import default_cal, ev_fields, ev_store
    b = {"title": title, "start": start, "end": end, "all_day": bool(all_day), "location": location or "", "description": note or "",
         "status": "tentative"}
    if task_id:
        b["task_id"] = task_id
    f = ev_fields(c, uid, b)
    return ev_store(c, uid, default_cal(c, uid), f)


# ---------------------------------------------------------------- the area of a token
def adz_area(c, want=None):
    """(area id, personal) the token reads: an agent its organisation (agents.org_id) or, as a personal agent, its owner's
    personal area; a person like the web app (?org=). 404 when there is none."""
    from ..agents.core import is_agent
    from ..office.model import pb_personal
    u = g.user
    if is_agent(u):
        r = c.execute("SELECT org_id, owner_id FROM agents WHERE user_id=?", (u["id"],)).fetchone()
        if r and r["org_id"]:
            oid, personal = r["org_id"], False
        elif r and r["owner_id"]:
            oid, personal = pb_personal(c, r["owner_id"]), True
        else:
            oid, personal = None, False
        if not oid or (want is not None and want != oid):
            raise Denied(404)
        return oid, personal
    if u["kid"]:
        raise Denied(403)
    need_feat("dispo")  # a person's token: like the web app, only with the module on
    oid = abs_org(c, u["id"], want, create=False)
    if not oid:
        raise Denied(404)
    return oid, False


def _Ctx(c, personal):
    """Reading a personal agent's area: its owner's personal area is outside the agent's own row-level context (agents
    carry only agents.org_id), so these reads run as system -- every query inside filters by that one area id, which
    adz_area derived from the agent's own owner (never from the request)."""
    return system_ctx(c) if personal else contextlib.nullcontext(c)


def _resources(c, viewer, oid, personal):
    """The area's resources as the viewer may know them (contacts: address books the viewer reads)."""
    with _Ctx(c, personal):
        return dsp_resources(c, viewer, oid)


# ---------------------------------------------------------------- REST API v1: reading the disposition
@app.get("/api/v1/dispo")
@v1_view
def v1_adz_dispo():
    """?start=YYYY-MM-DD (today) &days=1..62 (7) &org=: bookings with conflicts, resources, who is away (never why), holidays."""
    a = v1_args(("start", "days", "org"))
    c = db()
    try:
        want = int(a["org"]) if a.get("org") else None
        first = date.fromisoformat(a["start"]) if a.get("start") else local_now().date()
        n = max(1, min(DSP_DAYS_MAX, int(a.get("days") or 7)))
    except ValueError:
        raise BadInput(tr("Invalid data")) from None
    oid, personal = adz_area(c, want)
    last = first + timedelta(days=n - 1)
    res = _resources(c, me(), oid, personal)
    with _Ctx(c, personal):
        rows = [dict(r) for r in c.execute("SELECT * FROM hub_bookings WHERE org_id=? AND deleted_at IS NULL AND start<=? AND \"end\">=? "
                                            "ORDER BY start, id", (oid, last.isoformat() + "T99", first.isoformat()))]
        conf = dsp_conflicts(c, oid, rows, first, last)
        gone = abs_days(c, [p["id"] for p in res["people"]], first, last, oid)
        hol = abs_holidays(abs_state(c, oid), first, last)
    return jsonify(org_id=oid, start=first.isoformat(), end=last.isoformat(), resources=res,
                   bookings=[{k: v for k, v in dsp_public(r, conf.get(r["id"])).items() if k != "note"} for r in rows],
                   away={str(k): sorted(v) if isinstance(v, (set, dict, list)) else v for k, v in gone.items()},
                   holidays=[{"date": k, "name": v} for k, v in sorted(hol.items())])


def adz_free(c, viewer, oid, personal, day):
    res = _resources(c, viewer, oid, personal)
    sets = {s["id"]: s["items"] for s in res["sets"]}
    busy = set()
    with _Ctx(c, personal):
        for b in c.execute("SELECT * FROM hub_bookings WHERE org_id=? AND deleted_at IS NULL AND start<=? AND \"end\">=?",
                           (oid, day.isoformat() + "T99", day.isoformat())):
            busy |= dsp_units(b, sets)
        gone = abs_days(c, [p["id"] for p in res["people"]], day, day, oid)
    free = lambda grp: [r for r in grp if (r["kind"], r["id"]) not in busy and not (r["kind"] == "user" and gone.get(r["id"]))]  # noqa: E731
    return {"date": day.isoformat(), "org_id": oid, "people": free(res["people"]), "contacts": free(res["contacts"]),
            "equipment": free(res["equipment"]),
            "sets": [s for s in res["sets"] if ("set", s["id"]) not in busy and not any(("equipment", e) in busy for e in s["items"])],
            "away": [p["id"] for p in res["people"] if gone.get(p["id"])]}


@app.get("/api/v1/dispo/free")
@v1_view
def v1_adz_free():
    """?date=YYYY-MM-DD &org=: who and what of the area is free that day."""
    a = v1_args(("date", "org"))
    c = db()
    try:
        want = int(a["org"]) if a.get("org") else None
        day = date.fromisoformat(a.get("date") or "")
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "date")) from None
    oid, personal = adz_area(c, want)
    return jsonify(adz_free(c, me(), oid, personal, day))


# ---------------------------------------------------------------- the proposal (kind shoot)
def _span(d):
    """A day row -> (start, end) in the booking format (YYYY-MM-DD or YYYY-MM-DDTHH:MM)."""
    if d["all_day"]:
        return d["date"], d["date"]
    return f"{d['date']}T{d['start']}", f"{d['date']}T{d['end']}"


def _list_area_ok(c, lid, oid):
    from ..office.model import pb_cl_sql
    return bool(c.execute(f"SELECT 1 FROM lists WHERE id=? AND {pb_cl_sql(c, oid, 'org_id', 'owner_id')}", (lid,)).fetchone())


def adz_warnings(c, oid, personal, lid, days, crew):
    """Per row: what overlaps (other bookings of the resource, absences; for a day: other projects' bookings that day)."""
    with _Ctx(c, personal):
        for d in days:
            s, e = _span(d)
            other = c.execute("SELECT DISTINCT title FROM hub_bookings WHERE org_id=? AND deleted_at IS NULL AND start<=? AND \"end\">=? "
                              "AND (list_id IS NULL OR list_id!=?) ORDER BY title LIMIT 5", (oid, e[:10] + "T99", s[:10], lid or 0)).fetchall()
            d["warnings"] = [{"kind": "other_projects", "titles": [r[0] for r in other]}] if other else []
        if crew:
            rows = []
            for i, x in enumerate(crew):
                s, e = _span(days[x["day"]])
                rows.append({"id": -1 - i, "start": s, "end": e, "resource_kind": x["kind"], "resource_id": x["id"]})
            first = min(date.fromisoformat(r["start"][:10]) for r in rows)
            last = max(date.fromisoformat(r["end"][:10]) for r in rows)
            conf = dsp_conflicts(c, oid, rows, first, last)
            for i, x in enumerate(crew):
                cf = conf.get(-1 - i, {})
                w = []
                if cf.get("double"):
                    q = ",".join("?" * len(cf["double"]))
                    w.append({"kind": "double", "titles": [r[0] for r in c.execute(
                        f"SELECT DISTINCT title FROM hub_bookings WHERE id IN ({q}) LIMIT 5", cf["double"])]})
                if cf.get("away"):
                    w.append({"kind": "away"})
                x["warnings"] = w
    return sum(1 for d in days if d["warnings"]) + sum(1 for x in crew if x["warnings"])


def adz_validate(b, inp):
    """The agent's shoot proposal -> {list_id, days: [...], crew: [...], items: [...]} (items = days then crew, one key each)."""
    from ..agents.proposals import _p_int, _p_keys, _p_list, _p_str
    _p_keys(b, "", ("kind", "summary", "days", "crew"))
    c = db()
    oid, personal, lid = inp["org_id"], bool(inp.get("personal")), inp["list_id"]
    days = []
    for i, d in enumerate(_p_list(b.get("days"), "days", ADZ_DAYS_MAX)):
        w = f"days[{i}]"
        _p_keys(d, w, ("date", "start", "end", "all_day", "title", "location", "note", "alt_of"))
        try:
            day = date.fromisoformat(d.get("date") or "")
        except (TypeError, ValueError):
            raise BadInput(tr("Invalid value: {0}", w + ".date")) from None
        all_day = bool(d.get("all_day")) or not d.get("start")
        st = en = None
        if not all_day:
            from ..agents.agenttime import _hm_ok
            st, en = d.get("start"), d.get("end") or ""
            if not _hm_ok(st) or not _hm_ok(en) or en <= st:
                raise BadInput(tr("Invalid value: {0}", w + ".end"))
        alt = d.get("alt_of")
        alt = None if alt in (None, "") else _p_int(alt, w + ".alt_of", 0, ADZ_DAYS_MAX)
        if alt is not None and alt >= i:
            raise BadInput(tr("Invalid value: {0}", w + ".alt_of"))
        days.append({"date": day.isoformat(), "all_day": all_day, "start": st, "end": en,
                     "title": _p_str(d.get("title"), w + ".title", ADZ_TEXT_MAX, True),
                     "location": _p_str(d.get("location"), w + ".location", ADZ_TEXT_MAX),
                     "note": _p_str(d.get("note"), w + ".note", 1000, line=False), "alt_of": alt})
    if not days:
        raise BadInput(tr("Missing field: {0}", "days"))
    idx = _res_index(_resources(c, me(), oid, personal))
    crew, seen = [], set()
    for i, x in enumerate(_p_list(b.get("crew"), "crew", ADZ_CREW_MAX)):
        w = f"crew[{i}]"
        _p_keys(x, w, ("kind", "id", "day", "note"))
        k, rid = x.get("kind"), _p_int(x.get("id"), w + ".id")
        dy = _p_int(x.get("day", 0), w + ".day", 0, len(days) - 1)
        if k not in DSP_KINDS or (k, rid) not in idx:
            raise BadInput(tr("Invalid value: {0}", w + ".id"))
        if (k, rid, dy) in seen:
            continue
        seen.add((k, rid, dy))
        crew.append({"kind": k, "id": rid, "day": dy, "name": idx[(k, rid)]["name"], "note": _p_str(x.get("note"), w + ".note", 1000)})
    n = adz_warnings(c, oid, personal, lid, days, crew)
    items = [{"type": "day", "i": i} for i in range(len(days))] + [{"type": "crew", "i": i} for i in range(len(crew))]
    return {"list_id": lid, "days": days, "crew": crew, "items": items, "warnings": n}


def adz_run(c, j, sel, ed, rec):
    """Apply as the person: per selected day a task in the project (due = the day) + its draft event; per selected crew row
    (its day selected too) an option booking. rec["made"] = [["task"|"event"|"booking", id], ...]."""
    from ..agents.proposals import _p_keys, _p_str, prop_insert
    from ..agents.agenttime import _hm_ok
    need_feat("events")
    prop, inp = json.loads(j["proposal"]), json.loads(j["input"] or "{}")
    lid, oid = prop["list_id"], inp["org_id"]
    uid, ts = me(), iso(now_utc())
    if list_role(c, lid, uid) not in WRITE_ROLES or not _list_area_ok(c, lid, oid):
        raise Denied(404)
    rec.update(made=[], warnings=0, skipped_crew=0)
    picked = {int(k) for k in sel if k.isdigit() and int(k) < len(prop["items"])}
    ev_of = {}
    for k in sorted(picked):
        it = prop["items"][k]
        if it["type"] != "day":
            continue
        d = dict(prop["days"][it["i"]])
        e = ed.get(str(k)) or {}
        _p_keys(e, f"edits.{k}", ("title", "start", "end", "location"))
        if "title" in e:
            d["title"] = _p_str(e["title"], "title", ADZ_TEXT_MAX, True)
        if "location" in e:
            d["location"] = _p_str(e["location"], "location", ADZ_TEXT_MAX)
        if not d["all_day"] and ("start" in e or "end" in e):
            st, en = e.get("start", d["start"]), e.get("end", d["end"])
            if not _hm_ok(st) or not _hm_ok(en) or en <= st:
                raise BadInput(tr("Invalid value: {0}", "end"))
            d["start"], d["end"] = st, en
        prop["days"][it["i"]] = d
        tid = prop_insert(c, j["agent_id"], lid, ts, d["title"], d["note"], due=d["date"])
        if not d["all_day"]:
            c.execute("UPDATE tasks SET due_time=? WHERE id=?", (d["start"], tid))
        rec["made"].append(["task", tid])
        if d["all_day"]:
            s, en = d["date"], (date.fromisoformat(d["date"]) + timedelta(days=1)).isoformat()
        else:
            s, en = f"{d['date']}T{d['start']}", f"{d['date']}T{d['end']}"
        eid = adz_event_draft(c, uid, d["title"], s, en, d["all_day"], d["location"], tid, d["note"])
        rec["made"].append(["event", eid])
        ev_of[it["i"]] = eid
    if not ev_of:
        raise BadInput(tr("Select at least one shoot day"))
    crew = [prop["crew"][prop["items"][k]["i"]] for k in sorted(picked) if prop["items"][k]["type"] == "crew"]
    crew = [x for x in crew if x["day"] in ev_of]
    if crew:
        try:
            need_feat("dispo")
            abs_org(c, uid, oid, create=False)  # books only in an area the person belongs to (else: drafts without options)
        except Denied:
            rec["skipped_crew"] = len(crew)
            crew = []
    if crew:
        idx = _res_index(dsp_resources(c, uid, oid))
        jobs = {}
        made = []
        for x in crew:
            if (x["kind"], x["id"]) not in idx:
                rec["skipped_crew"] += 1
                continue
            d = prop["days"][x["day"]]
            s, e = _ts(_span(d)[0], "start"), _ts(_span(d)[1], "end")
            job = jobs.setdefault(x["day"], secrets.token_hex(8))
            bid = insert_id(c, "INSERT INTO hub_bookings(org_id,job,title,start,\"end\",resource_kind,resource_id,res_label,status,note,list_id,"
                               "event_id,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,'option',?,?,?,?,?,?)",
                            (oid, job, d["title"][:200], s, e, x["kind"], x["id"], idx[(x["kind"], x["id"])]["name"][:200], x["note"],
                             lid, ev_of[x["day"]], uid, ts, ts))
            rec["made"].append(["booking", bid])
            made.append(dict(c.execute("SELECT * FROM hub_bookings WHERE id=?", (bid,)).fetchone()))
        if made:
            first = min(date.fromisoformat(r["start"][:10]) for r in made)
            last = max(date.fromisoformat(r["end"][:10]) for r in made)
            conf = dsp_conflicts(c, oid, made, first, last)
            rec["warnings"] = sum(1 for r in made if conf.get(r["id"], {}).get("double") or conf.get(r["id"], {}).get("away"))
    rec["list"] = lid
    return rec


def adz_undo(c, rec, back=True):
    """Undo: drafts that are still drafts go (deleted_at: restorable), tasks to the trash, option bookings go; what a person
    confirmed or changed since stays (skipped). Redo brings them back."""
    from ..tasks.lifecycle import do_delete, restore_task
    n, skipped, ts = 0, [], iso(now_utc())
    for kind, i in rec.get("made") or []:
        if kind == "event":
            r = c.execute("SELECT status, deleted_at, title FROM events WHERE id=?", (i,)).fetchone()
            if not r:
                continue
            if back and not r["deleted_at"] and r["status"] == "tentative":
                c.execute("UPDATE events SET deleted_at=? WHERE id=?", (ts, i))
                n += 1
            elif not back and r["deleted_at"] and r["deleted_at"] >= rec.get("undone_at", ""):
                c.execute("UPDATE events SET deleted_at=NULL WHERE id=?", (i,))
                n += 1
            elif back and not r["deleted_at"]:
                skipped.append(r["title"][:40])
        elif kind == "task":
            r = c.execute("SELECT deleted_at FROM tasks WHERE id=?", (i,)).fetchone()
            if r and back and not r["deleted_at"]:
                do_delete(c, i)
            elif r and not back and r["deleted_at"] and r["deleted_at"] >= rec.get("undone_at", ""):
                restore_task(c, i)
        elif kind == "booking":
            r = c.execute("SELECT status, deleted_at FROM hub_bookings WHERE id=?", (i,)).fetchone()
            if r and back and not r["deleted_at"] and r["status"] == "option":
                c.execute("UPDATE hub_bookings SET deleted_at=? WHERE id=?", (ts, i))
            elif r and not back and r["deleted_at"] and r["deleted_at"] >= rec.get("undone_at", ""):
                c.execute("UPDATE hub_bookings SET deleted_at=NULL WHERE id=?", (i,))
    if back:
        rec["undone_at"] = ts
    bump(c)
    return n, skipped[:8]


@app.post("/api/v1/agent/proposals/shoot")
@v1_view
def v1_adz_proposal():
    """{list_id, user_id?, title?, summary?, days: [...], crew: [...]} -- the agent proposes shoot days (event drafts) and
    crew / equipment (options) for a project list to a person who may write in it. Nothing is booked until they apply it."""
    from ..agents.core import need_agent
    from ..agents.proposals import _p_int, _p_str, PROP_MAX_BYTES, PROP_OPEN_MAX, PROP_TITLE_MAX, prop_validate
    from ..agents.agenttime import atm_person, atm_prop_create
    v1_args(())
    aid = need_agent()
    if len(request.data or b"") > PROP_MAX_BYTES:
        return v1_err(413, tr("The proposal is too large (at most {0} KB)", PROP_MAX_BYTES // 1024))
    b = v1_json()
    c = db()
    lid = _p_int(b.get("list_id"), "list_id")
    lst = c.execute("SELECT owner_id, life, archived, is_inbox FROM lists WHERE id=?", (lid,)).fetchone()
    if not lst or lst["life"] == "health" or not list_role(c, lid, aid):
        raise Denied(404)
    if list_role(c, lid, aid) not in WRITE_ROLES or lst["archived"] or lst["is_inbox"]:
        raise Denied(403)
    pid, _ = atm_person(c, {"user_id": b.get("user_id") or (lst["owner_id"] if lst["owner_id"] != aid else None)})
    if list_role(c, lid, pid) not in WRITE_ROLES:
        raise BadInput(tr("Invalid value: {0}", "user_id"))
    oid, personal = adz_area(c)
    if not _list_area_ok(c, lid, oid):
        raise Denied(404)
    title = _p_str(b.get("title"), "title", PROP_TITLE_MAX) or tr("Shoot planning")
    inp = {"user_id": pid, "list_id": lid, "org_id": oid, "personal": personal}
    p = prop_validate("shoot", {k: v for k, v in b.items() if k not in ("user_id", "title", "list_id")}, inp)
    out = atm_prop_create(c, aid, pid, "shoot", title, inp, p, list_id=lid)
    if out is None:
        return v1_err(429, tr("You have {0} open proposals for this person: wait until they decided on them", PROP_OPEN_MAX))
    return jsonify(out), 201


def adz_spec(paths, schemas, op, ok, errs, ref, pid, q):
    """OpenAPI of the disposition routes for agents and the shoot proposal (2.51.0, #1355)."""
    T = "Workload"
    org = q("org", "Area id (people only; an agent always reads its own workspace)", {"type": "integer"})
    paths["/dispo"] = {"get": op(
        "2.51.0 (#1355): the disposition of your workspace: bookings with conflicts, resources, who is away (never why), holidays", T,
        ok({"type": "object"}) | errs("400", "403", "404"),
        [q("start", "First day (YYYY-MM-DD, default today)"), q("days", f"1-{DSP_DAYS_MAX} (default 7)", {"type": "integer"}), org],
        scope="calendar", desc="An agent of an organisation reads that organisation, a personal agent its owner's personal area; "
                               "booking notes are left out.")}
    paths["/dispo/free"] = {"get": op(
        "2.51.0 (#1355): who and what of your workspace is free on a day", T, ok({"type": "object"}) | errs("400", "403", "404"),
        [q("date", "YYYY-MM-DD"), org], scope="calendar")}
    paths["/agent/proposals/shoot"] = {"post": op(
        "2.51.0 (#1355): propose shoot days (event drafts) and crew / equipment (options) for a project", "Agents",
        ok({"type": "object"}, "Created", "201") | errs("400", "403", "404", "413", "429"),
        body={"type": "object", "required": ["list_id", "days"], "properties": {
            "list_id": {"type": "integer", "description": "A project list you may write in, of your workspace"},
            "user_id": {"type": "integer", "description": "The person who decides (default: the list owner); must write in the list"},
            "title": {"type": "string"}, "summary": {"type": "string", "description": "Markdown: why, conflicts you saw, the solution"},
            "days": {"type": "array", "maxItems": ADZ_DAYS_MAX, "items": {"type": "object", "required": ["date", "title"], "properties": {
                "date": {"type": "string", "format": "date"}, "start": {"type": "string", "description": "HH:MM local; none = all day"},
                "end": {"type": "string"}, "all_day": {"type": "boolean"}, "title": {"type": "string"}, "location": {"type": "string"},
                "note": {"type": "string"}, "alt_of": {"type": "integer", "description": "This day is a second variant of days[alt_of]"}}}},
            "crew": {"type": "array", "maxItems": ADZ_CREW_MAX, "items": {"type": "object", "required": ["kind", "id"], "properties": {
                "kind": {"type": "string", "enum": list(DSP_KINDS)}, "id": {"type": "integer", "description": "From GET /dispo resources"},
                "day": {"type": "integer", "description": "Index into days (default 0)"}, "note": {"type": "string"}}}}}},
        scope="calendar",
        desc="Agents only. The server checks double bookings and absences per row (warnings, never a block). Applying makes per day a "
             "task of the project (due = the day) with a draft event (tentative) and per crew row a booking with status option; never "
             "firm. The answer comes as the event job.")}
