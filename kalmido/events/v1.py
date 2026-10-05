"""Events: the REST API v1 (+ MCP) and its OpenAPI part (scope "calendar")."""
from flask import jsonify, Response

from ..core.config import app
from ..core.i18n import tr
from ..core.db import db
from ..accounts.session import me
from ..core.access import need_feat
from ..tasks.validation import as_int
from ..personal.timetrack import BadInput, reject_unknown
from ..api.v1 import v1_args, v1_json, v1_view
from ..events.model import EV_PARTSTAT, EV_ROLES, EV_STATUS, need_evcal
from ..events.ics import ics_export, import_ics, IMPORT_MAX_BYTES
from ..events.web import (
    occ_arg, op_cal_delete, op_cal_edit, op_cal_new, op_cals, op_event, op_event_delete, op_event_edit, op_event_new,
    op_event_restore, op_member_remove, op_member_set, op_prep_task, op_range, op_rsvp, op_task_events,
)


def _page(items):
    return jsonify(data=items, next_cursor=None)


@app.get("/api/v1/event-calendars")
@v1_view
def v1_evcals():
    v1_args(())
    return _page(op_cals(db(), me()))


@app.post("/api/v1/event-calendars")
@v1_view
def v1_evcal_new():
    v1_args(())
    need_feat("events")
    return jsonify(op_cal_new(db(), me(), v1_json())), 201


@app.patch("/api/v1/event-calendars/<int:cid>")
@v1_view
def v1_evcal_edit(cid):
    v1_args(())
    need_feat("events")
    return jsonify(op_cal_edit(db(), me(), cid, v1_json()))


@app.delete("/api/v1/event-calendars/<int:cid>")
@v1_view
def v1_evcal_delete(cid):
    v1_args(())
    need_feat("events")
    op_cal_delete(db(), me(), cid)
    return Response(status=204)


@app.put("/api/v1/event-calendars/<int:cid>/members/<user_id>")
@v1_view
def v1_evcal_member(cid, user_id):
    v1_args(())
    uid = as_int(user_id, "user_id", 1)
    need_feat("events")
    b = v1_json()
    reject_unknown(b, ("role",))
    return jsonify(op_member_set(db(), me(), cid, {"user_id": uid, "role": b.get("role") or "view"}))


@app.delete("/api/v1/event-calendars/<int:cid>/members/<user_id>")
@v1_view
def v1_evcal_member_rm(cid, user_id):
    v1_args(())
    uid = as_int(user_id, "user_id", 1)
    need_feat("events")
    op_member_remove(db(), me(), cid, uid)
    return Response(status=204)


@app.post("/api/v1/event-calendars/<int:cid>/import")
@v1_view
def v1_evcal_import(cid):
    """{ics: "<the text of an .ics file>", dry_run?}"""
    v1_args(())
    need_feat("events")
    b = v1_json()
    reject_unknown(b, ("ics", "dry_run"))
    if not isinstance(b.get("ics"), str) or not b["ics"].strip():
        raise BadInput(tr("Invalid value: {0}", "ics"))
    c = db()
    need_evcal(c, cid, write=True)
    raw = b["ics"].encode("utf-8")
    if len(raw) > IMPORT_MAX_BYTES:
        raise BadInput(tr("The file is too large (at most {0} MB)", IMPORT_MAX_BYTES // (1024 * 1024)))
    res = import_ics(c, me(), cid, raw, dry=b.get("dry_run") is True)
    c.commit()
    return jsonify(res)


@app.get("/api/v1/event-calendars/<int:cid>/export")
@v1_view
def v1_evcal_export(cid):
    v1_args(())
    c = db()
    need_evcal(c, cid)
    return jsonify(ics=ics_export(c, cid))


@app.get("/api/v1/events")
@v1_view
def v1_events():
    a = v1_args(("from", "to", "calendar_id"))
    return _page(op_range(db(), me(), a))


@app.post("/api/v1/events")
@v1_view
def v1_event_new():
    v1_args(())
    need_feat("events")
    return jsonify(op_event_new(db(), me(), v1_json())), 201


@app.get("/api/v1/events/<int:eid>")
@v1_view
def v1_event(eid):
    v1_args(())
    return jsonify(op_event(db(), me(), eid))


@app.patch("/api/v1/events/<int:eid>")
@v1_view
def v1_event_edit(eid):
    v1_args(("occurrence",))
    need_feat("events")
    return jsonify(op_event_edit(db(), me(), eid, v1_json(), occ_arg()))


@app.delete("/api/v1/events/<int:eid>")
@v1_view
def v1_event_delete(eid):
    v1_args(("occurrence",))
    need_feat("events")
    op_event_delete(db(), me(), eid, occ_arg())
    return Response(status=204)


@app.post("/api/v1/events/<int:eid>/restore")
@v1_view
def v1_event_restore(eid):
    v1_args(())
    need_feat("events")
    return jsonify(op_event_restore(db(), me(), eid))


@app.post("/api/v1/events/<int:eid>/rsvp")
@v1_view
def v1_event_rsvp(eid):
    v1_args(())
    return jsonify(op_rsvp(db(), me(), eid, v1_json()))


@app.post("/api/v1/events/<int:eid>/prep-task")
@v1_view
def v1_event_prep(eid):
    from ..api.scopes import need_scope
    v1_args(())
    need_feat("events")
    need_scope("tasks:write")
    return jsonify(op_prep_task(db(), me(), eid, v1_json())), 201


@app.get("/api/v1/tasks/<int:tid>/events")
@v1_view
def v1_task_events(tid):
    v1_args(())
    return _page(op_task_events(db(), me(), tid))


def events_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q):
    E, S = "Events", "calendar"
    schemas["EventCalendar"] = {"type": "object", "properties": {
        "id": {"type": "integer"}, "name": {"type": "string"}, "color": {"type": "string"}, "description": {"type": "string"},
        "owner_id": {"type": "integer"}, "owner_name": {"type": "string"}, "role": {"type": "string", "enum": ["owner", *EV_ROLES]},
        "hidden": {"type": "boolean", "description": "Left out of the token user's views and reminders"},
        "members": {"type": "array", "items": {"type": "object", "properties": {"user_id": {"type": "integer"},
                                                                             "role": {"type": "string", "enum": list(EV_ROLES)}}},
                    "description": "Only for the owner"}}}
    schemas["EventCalendarPage"] = page("EventCalendar")
    att = {"type": "object", "properties": {
        "id": {"type": "integer"}, "user_id": nul("integer", description="A person of this server (sees this event)"),
        "contact_id": nul("integer"), "email": {"type": "string"}, "name": {"type": "string"},
        "partstat": {"type": "string", "enum": list(EV_PARTSTAT)}, "role": {"type": "string", "enum": ["req", "opt"]}}}
    schemas["Event"] = {"type": "object", "properties": {
        "id": {"type": "integer"}, "cal_id": nul("integer", description="null for an event the user is only invited to"),
        "uid": {"type": "string"}, "title": {"type": "string"}, "location": {"type": "string"}, "description": {"type": "string"},
        "all_day": {"type": "boolean"},
        "start": {"type": "string", "description": "All day: YYYY-MM-DD; else YYYY-MM-DDTHH:MM, local time of tz"},
        "end": {"type": "string", "description": "All day: the day AFTER the last day (exclusive, like iCalendar)"},
        "tz": {"type": "string", "description": "IANA time zone"}, "rrule": {"type": "string", "description": "RRULE body or empty"},
        "exdates": {"type": "array", "items": {"type": "string"}, "description": "Left-out occurrences (their original start)"},
        "overrides": {"type": "array", "items": {"type": "object"}, "description": "Changed occurrences {rid, title, start, end, ...}"},
        "reminders": {"type": "array", "items": {"type": "integer"}, "description": "Minutes before the start"},
        "status": {"type": "string", "enum": list(EV_STATUS)}, "busy": {"type": "boolean"}, "url": nul("string"),
        "task_id": nul("integer", description="The linked preparation task"), "attendees": {"type": "array", "items": att},
        "role": {"type": "string", "enum": ["owner", "edit", "view", "attendee"]}, "partstat": {"type": "string", "enum": list(EV_PARTSTAT)},
        "created_by": nul("integer"), "created_at": {"type": "string"}, "updated_at": {"type": "string"}}}
    schemas["EventPage"] = page("Event")
    schemas["Occurrence"] = {"type": "object", "properties": {
        "eid": {"type": "integer"}, "occ": {"type": "string", "description": "The original start (key for occurrence=)"},
        "cal": nul("integer"), "title": {"type": "string"}, "location": {"type": "string"}, "description": {"type": "string"},
        "all_day": {"type": "boolean"}, "start": {"type": "string", "description": "All day: date; else UTC date-time"},
        "end": {"type": "string"}, "recurring": {"type": "boolean"}, "changed": {"type": "boolean"}, "status": {"type": "string"},
        "role": {"type": "string"}, "task_id": nul("integer"), "att": {"type": "integer", "description": "Number of attendees"},
        "partstat": {"type": "string"}}}
    schemas["OccurrencePage"] = page("Occurrence")
    ev_in = {"type": "object", "properties": {
        "cal_id": {"type": "integer", "description": "Default: the first own calendar (created when missing)"},
        "title": {"type": "string"}, "location": {"type": "string"}, "description": {"type": "string"}, "all_day": {"type": "boolean"},
        "start": {"type": "string"}, "end": {"type": "string"}, "tz": {"type": "string"}, "rrule": {"type": "string"},
        "exdates": {"type": "array", "items": {"type": "string"}}, "reminders": {"type": "array", "items": {"type": "integer"}},
        "status": {"type": "string", "enum": list(EV_STATUS)}, "busy": {"type": "boolean"}, "url": nul("string"), "task_id": nul("integer"),
        "attendees": {"type": "array", "items": {"type": "object", "properties": {
            "user_id": {"type": "integer"}, "contact_id": {"type": "integer"}, "email": {"type": "string"}, "name": {"type": "string"},
            "partstat": {"type": "string", "enum": list(EV_PARTSTAT)}, "role": {"type": "string", "enum": ["req", "opt"]}}}}}}
    cal_in = {"type": "object", "properties": {"name": {"type": "string"}, "color": {"type": "string"}, "description": {"type": "string"}}}
    cid_p, eid_p, uid_p = pid("id", "Calendar id"), pid("id", "Event id"), pid("user_id", "User id")
    occ_q = q("occurrence", "Only this occurrence of a repeating event (its original start, see Occurrence.occ)")
    paths["/event-calendars"] = {
        "get": op("2.21.0 (module Events): the event calendars the token's user sees (own + shared)", E, ok(ref("EventCalendarPage")), scope=S),
        "post": op("A new own calendar", E, ok(ref("EventCalendar"), "Created", "201") | errs("400", "409"),
                   body={**cal_in, "required": ["name"]}, scope=S)}
    paths["/event-calendars/{id}"] = {
        "patch": op("Rename / recolour a calendar (owner) or hide it from the own views (anyone who sees it)", E,
                    ok(ref("EventCalendar")) | errs("400", "403", "404"), [cid_p],
                    body={**cal_in, "properties": {**cal_in["properties"], "hidden": {"type": "boolean"}}}, scope=S),
        "delete": op("Delete a calendar with all its events (owner)", E, {"204": {"description": "Deleted"}} | errs("403", "404"), [cid_p], scope=S)}
    paths["/event-calendars/{id}/members/{user_id}"] = {
        "put": op("Share a calendar with a person: view (read) or edit (owner)", E, ok(ref("EventCalendar")) | errs("400", "403", "404", "409"),
                  [cid_p, uid_p], body={"type": "object", "properties": {"role": {"type": "string", "enum": list(EV_ROLES)}}}, scope=S),
        "delete": op("Stop sharing (owner) or leave a shared calendar (the person itself)", E, {"204": {"description": "Removed"}} | errs("403", "404"),
                     [cid_p, uid_p], scope=S)}
    paths["/event-calendars/{id}/import"] = {"post": op(
        "Import an ICS file (e.g. the export of another calendar): the same UID is updated, so importing twice changes nothing", E,
        ok({"type": "object", "properties": {k: {"type": "integer"} for k in ("created", "updated", "skipped", "errors")}}) | errs("400", "403", "404"),
        [cid_p], body={"type": "object", "required": ["ics"], "properties": {"ics": {"type": "string"}, "dry_run": {"type": "boolean"}}}, scope=S)}
    paths["/event-calendars/{id}/export"] = {"get": op("The calendar as an ICS text", E, ok({"type": "object", "properties": {"ics": {"type": "string"}}})
                                                       | errs("404"), [cid_p], scope=S)}
    paths["/events"] = {
        "get": op("Occurrences in a date range (repeating events expanded, at most 400 days): own + shared calendars and invitations", E,
                  ok(ref("OccurrencePage")) | errs("400", "404"),
                  [q("from", "First day YYYY-MM-DD", {"type": "string", "format": "date"}), q("to", "Last day YYYY-MM-DD", {"type": "string", "format": "date"}),
                   q("calendar_id", "Only this calendar", {"type": "integer"})], scope=S),
        "post": op("Create an event", E, ok(ref("Event"), "Created", "201") | errs("400", "403", "404", "409"),
                   body={**ev_in, "required": ["title", "start"]}, scope=S)}
    paths["/events/{id}"] = {
        "get": op("One event (the series with its rule, changed and left-out occurrences, attendees)", E, ok(ref("Event")) | errs("404"), [eid_p], scope=S),
        "patch": op("Change an event (the whole series), or with ?occurrence= only that occurrence (title, location, description, all_day, "
                    "start, end, status)", E, ok(ref("Event")) | errs("400", "403", "404", "409"), [eid_p, occ_q],
                    body={**ev_in, "properties": {**ev_in["properties"], "expect": {"type": "string", "description": "updated_at of the copy "
                                                                                  "the change is based on (409 when it changed meanwhile)"}}}, scope=S),
        "delete": op("Delete an event (restorable for 30 days), or with ?occurrence= leave out that occurrence", E,
                     {"204": {"description": "Deleted"}} | errs("400", "403", "404"), [eid_p, occ_q], scope=S)}
    paths["/events/{id}/restore"] = {"post": op("Restore a deleted event", E, ok(ref("Event")) | errs("403", "404"), [eid_p], scope=S)}
    paths["/events/{id}/rsvp"] = {"post": op("Reply to an invitation (the token's user is an attendee)", E, ok(ref("Event")) | errs("400", "404", "409"),
                                             [eid_p], body={"type": "object", "required": ["partstat"], "properties": {
                                                 "partstat": {"type": "string", "enum": list(EV_PARTSTAT)}}}, scope=S)}
    paths["/events/{id}/prep-task"] = {"post": op(
        "A task to prepare the event (due days_before its start, linked to it; needs tasks:write too)", E,
        ok({"type": "object", "properties": {"task": ref("Task"), "event": ref("Event")}}, "Created", "201") | errs("400", "403", "404", "409"),
        [eid_p], body={"type": "object", "properties": {"title": {"type": "string"}, "list_id": {"type": "integer"},
                                                         "days_before": {"type": "integer", "minimum": 0, "maximum": 365}}}, scope=S)}
    paths["/tasks/{id}/events"] = {"get": op("The events a task prepares", E, ok(ref("EventPage")) | errs("404"), [pid()], scope=S)}


