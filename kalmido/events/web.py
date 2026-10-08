"""Events: the web API (calendars, sharing, events, single occurrences, replies, preparation tasks, export)."""
import json
from datetime import date, timedelta

from flask import jsonify, request, Response

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, iso_ms, now_utc, uset, usettings
from ..accounts.session import me
from ..core.access import Denied, need_feat
from ..tasks.validation import as_int, valid_date
from ..personal.timetrack import BadInput
from ..events.model import (
    att_clean, cal_create, cal_fields, cal_member_set, cal_public, cal_touch, cals_for, default_cal, ev_delete, ev_dict,
    ev_fields, ev_occ_change, ev_range, ev_store, EV_KEYS, EV_PARTSTAT, EV_RANGE_DAYS, EV_TITLE_MAX, need_event, need_evcal,
    wall,
)
from ..events.ics import ics_export


def _unknown(b, allowed):
    bad = sorted(k for k in b if k not in allowed)
    if bad:
        from ..personal.timetrack import UnknownFields
        raise UnknownFields(bad)


# ---- operations shared by the web routes and /api/v1 (they raise Denied / BadInput)
def op_cals(c, uid):
    return cals_for(c, uid)


def op_cal_new(c, uid, b):
    _unknown(b, ("name", "color", "description", "org_id"))  # 2.30.0 (#1036): org_id = its workspace
    cid = cal_create(c, uid, b)
    bump(c)
    c.commit()
    return cal_public(c, c.execute("SELECT * FROM ev_cals WHERE id=?", (cid,)).fetchone(), uid)


def op_cal_edit(c, uid, cid, b):
    _unknown(b, ("name", "color", "description", "hidden", "org_id"))
    cal, role = need_evcal(c, cid)
    if "org_id" in b:  # 2.30.0 (#1036): the owner moves it into another workspace (409 while a member does not fit)
        from ..accounts.orgs import obj_org_set
        if obj_org_set(c, "ev_cals", "cal_id", "ev_cal_members", cid, b["org_id"], "cal"):
            cal_touch(c, cid)
    f = {k: b[k] for k in ("name", "color", "description") if k in b}
    if f:
        if role != "owner":
            raise Denied(403, tr("Only the owner of the calendar can do this"))
        f = cal_fields(f)
        c.execute(f"UPDATE ev_cals SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), cid])
        cal_touch(c, cid)
    if "hidden" in b:  # per person: the calendar's events are left out of my views (and reminders); data stays
        if not isinstance(b["hidden"], bool):
            raise BadInput(tr("Invalid value: {0}", "hidden"))
        hid = set(json.loads(usettings(c, uid).get("evcals_hidden") or "[]") or [])
        hid = (hid | {cid}) if b["hidden"] else (hid - {cid})
        uset(c, uid, "evcals_hidden", json.dumps(sorted(hid)))
    bump(c)
    c.commit()
    return {**cal_public(c, c.execute("SELECT * FROM ev_cals WHERE id=?", (cid,)).fetchone(), uid),
            "hidden": cid in set(json.loads(usettings(c, uid).get("evcals_hidden") or "[]") or [])}


def op_cal_delete(c, uid, cid):
    need_evcal(c, cid, manage=True)
    c.execute("DELETE FROM ev_cals WHERE id=?", (cid,))
    bump(c)
    c.commit()


def op_member_set(c, uid, cid, b):
    _unknown(b, ("user_id", "role"))
    need_evcal(c, cid, manage=True)
    cal_member_set(c, cid, as_int(b.get("user_id"), "user_id", 1), b.get("role") or "view")
    bump(c)
    c.commit()
    return cal_public(c, c.execute("SELECT * FROM ev_cals WHERE id=?", (cid,)).fetchone(), uid)


def op_member_remove(c, uid, cid, who):
    cal, role = need_evcal(c, cid)
    if who != uid and role != "owner":
        raise Denied(403, tr("Only the owner of the calendar can do this"))
    if not c.execute("DELETE FROM ev_cal_members WHERE cal_id=? AND user_id=?", (cid, who)).rowcount:
        raise Denied(404)
    cal_touch(c, cid)
    bump(c)
    c.commit()


def op_range(c, uid, a):
    if not valid_date(a.get("from")) or not valid_date(a.get("to")):
        raise BadInput(tr("from/to missing"))
    lo, hi = date.fromisoformat(a["from"]), date.fromisoformat(a["to"])
    if hi < lo or (hi - lo).days > EV_RANGE_DAYS:
        raise BadInput(tr("Date range too large"))
    cal = None
    if a.get("calendar_id") not in (None, ""):
        cal = as_int(a["calendar_id"], "calendar_id", 1)
        need_evcal(c, cal)
    return ev_range(c, uid, lo, hi, cal)


def op_event(c, uid, eid):
    r, role = need_event(c, eid)
    return ev_dict(c, r, uid, role)


def op_event_new(c, uid, b):
    _unknown(b, EV_KEYS)
    cid = b.get("cal_id")
    cid = as_int(cid, "cal_id", 1) if cid not in (None, "") else default_cal(c, uid)
    need_evcal(c, cid, write=True)
    f = ev_fields(c, uid, b)
    att = att_clean(c, b["attendees"]) if "attendees" in b else None
    eid = ev_store(c, uid, cid, f, attendees=att)
    c.commit()
    return ev_dict(c, c.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone(), uid)


def op_event_edit(c, uid, eid, b, occ=None):
    r, role = need_event(c, eid, write=True)
    if occ:
        ev_occ_change(c, r, occ, b)
        c.commit()
        return ev_dict(c, c.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone(), uid)
    _unknown(b, EV_KEYS + ("expect",))
    if b.get("expect") and b["expect"] != r["updated_at"]:  # the editor's copy is older: refuse instead of overwriting
        raise Denied(409, tr("The event was changed meanwhile"))
    if "cal_id" in b and b["cal_id"] not in (None, "") and as_int(b["cal_id"], "cal_id", 1) != r["cal_id"]:
        nc = as_int(b["cal_id"], "cal_id", 1)
        need_evcal(c, nc, write=True)
        if c.execute("SELECT 1 FROM events WHERE cal_id=? AND (uid=? OR href=?) AND deleted_at IS NULL", (nc, r["uid"], r["href"])).fetchone():
            raise Denied(409, tr("The calendar has this event already"))
        c.execute("UPDATE events SET cal_id=? WHERE id=?", (nc, eid))
        cal_touch(c, r["cal_id"])
        r = c.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone()
    f = ev_fields(c, uid, {k: v for k, v in b.items() if k not in ("attendees", "cal_id", "expect")}, r)
    if "rrule" in f and not f["rrule"]:
        f["overrides"], f["exdates"] = "", ""
    att = att_clean(c, b["attendees"], eid) if "attendees" in b else None
    ev_store(c, uid, r["cal_id"], f, eid=eid, attendees=att)
    c.commit()
    return ev_dict(c, c.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone(), uid)


def op_event_delete(c, uid, eid, occ=None):
    r, role = need_event(c, eid, write=True)
    if occ:
        ev_occ_change(c, r, occ, {"delete": True})
    else:
        ev_delete(c, r)
    c.commit()


def op_event_restore(c, uid, eid):
    r, role = need_event(c, eid, write=True, deleted=True)
    c.execute("UPDATE events SET deleted_at=NULL, updated_at=? WHERE id=?", (iso_ms(now_utc()), eid))
    cal_touch(c, r["cal_id"])
    bump(c)
    c.commit()
    return ev_dict(c, c.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone(), uid)


def op_rsvp(c, uid, eid, b):
    _unknown(b, ("partstat",))
    r, role = need_event(c, eid)
    ps = b.get("partstat")
    if ps not in EV_PARTSTAT:
        raise BadInput(tr("Invalid value: {0}", "partstat"))
    if not c.execute("UPDATE event_attendees SET partstat=? WHERE event_id=? AND user_id=?", (ps, eid, uid)).rowcount:
        raise Denied(409, tr("You are not invited to this event"))
    c.execute("UPDATE events SET updated_at=? WHERE id=?", (iso_ms(now_utc()), eid))
    cal_touch(c, r["cal_id"])
    bump(c)
    c.commit()
    return ev_dict(c, c.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone(), uid)


def op_prep_task(c, uid, eid, b):
    """A task to prepare the event: due the given days before its (next) start, in the inbox or a list, linked both ways."""
    from ..api.v1 import v1_call
    from ..tasks.tasks import task_create
    _unknown(b, ("title", "list_id", "days_before"))
    r, role = need_event(c, eid, write=True)
    if r["task_id"] and c.execute("SELECT 1 FROM tasks WHERE id=? AND deleted_at IS NULL", (r["task_id"],)).fetchone():
        raise Denied(409, tr("The event has a preparation task already"))
    days = as_int(b.get("days_before", 1), "days_before", 0, 365)
    d0 = date.fromisoformat(r["start"][:10]) - timedelta(days=days)
    tb = {"title": (b.get("title") or tr("Prepare: {0}", r["title"]))[:EV_TITLE_MAX], "due": d0.isoformat()}
    if b.get("list_id") not in (None, ""):
        tb["list_id"] = as_int(b["list_id"], "list_id", 1)
    t = v1_call(task_create, body=tb)
    c.execute("UPDATE events SET task_id=?, updated_at=? WHERE id=?", (t["id"], iso_ms(now_utc()), eid))
    cal_touch(c, r["cal_id"])
    bump(c)
    c.commit()
    return {"task": t, "event": ev_dict(c, c.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone(), uid)}


def op_task_events(c, uid, tid):
    """The events a task prepares (that the person sees)."""
    from ..core.access import need_task
    need_task(c, tid, write=False)
    out = []
    for r in c.execute("SELECT * FROM events WHERE task_id=? AND deleted_at IS NULL ORDER BY start", (tid,)):
        try:
            rr, role = need_event(c, r["id"], uid=uid)
        except Denied:
            continue
        out.append(ev_dict(c, rr, uid, role))
    return out


def occ_arg():
    o = request.args.get("occ") or request.args.get("occurrence") or ""
    if o and not (valid_date(o) or wall(o)):
        raise BadInput(tr("Invalid value: {0}", "occurrence"))
    return o or None


# ---- web routes
@app.get("/api/evcals")
def evcals_get():
    return jsonify(items=op_cals(db(), me()))


@app.post("/api/evcals")
def evcals_new():
    need_feat("events")
    return jsonify(op_cal_new(db(), me(), body())), 201


@app.patch("/api/evcals/<int:cid>")
def evcals_edit(cid):
    need_feat("events")
    return jsonify(op_cal_edit(db(), me(), cid, body()))


@app.delete("/api/evcals/<int:cid>")
def evcals_delete(cid):
    need_feat("events")
    op_cal_delete(db(), me(), cid)
    return jsonify(ok=True)


@app.put("/api/evcals/<int:cid>/members")
def evcals_member(cid):
    need_feat("events")
    return jsonify(op_member_set(db(), me(), cid, body()))


@app.delete("/api/evcals/<int:cid>/members/<int:uid>")
def evcals_member_rm(cid, uid):
    need_feat("events")
    op_member_remove(db(), me(), cid, uid)
    return jsonify(ok=True)


@app.get("/api/evcals/<int:cid>/export.ics")
def evcals_export(cid):
    c = db()
    cal, role = need_evcal(c, cid)
    r = Response(ics_export(c, cid), 200, content_type="text/calendar; charset=utf-8")
    r.headers["Content-Disposition"] = 'attachment; filename="calendar-%d.ics"' % cid
    return r


@app.get("/api/events")
def events_range():
    return jsonify(items=op_range(db(), me(), request.args))


@app.get("/api/events/<int:eid>")
def event_get(eid):
    return jsonify(op_event(db(), me(), eid))


@app.post("/api/events")
def event_new():
    need_feat("events")
    return jsonify(op_event_new(db(), me(), body())), 201


@app.patch("/api/events/<int:eid>")
def event_edit(eid):
    need_feat("events")
    return jsonify(op_event_edit(db(), me(), eid, body(), occ_arg()))


@app.delete("/api/events/<int:eid>")
def event_delete(eid):
    need_feat("events")
    op_event_delete(db(), me(), eid, occ_arg())
    return jsonify(ok=True)


@app.post("/api/events/<int:eid>/restore")
def event_restore(eid):
    need_feat("events")
    return jsonify(op_event_restore(db(), me(), eid))


@app.post("/api/events/<int:eid>/rsvp")
def event_rsvp(eid):
    return jsonify(op_rsvp(db(), me(), eid, body()))


@app.post("/api/events/<int:eid>/prep-task")
def event_prep(eid):
    need_feat("events")
    return jsonify(op_prep_task(db(), me(), eid, body())), 201


@app.get("/api/tasks/<int:tid>/events")
def task_events(tid):
    return jsonify(items=op_task_events(db(), me(), tid))


