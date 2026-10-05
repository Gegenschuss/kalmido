"""Home & life: the REST API v1 (+ MCP) and its OpenAPI part (health + journal: scope "private")."""
from flask import jsonify

from ..core.config import app
from ..core.db import bump, db
from ..accounts.session import me
from ..personal.timetrack import reject_unknown
from ..api.v1 import v1_args, v1_call, v1_json, v1_one, v1_view
from ..life.model import (
    care_set, contract_create, device_create, HEALTH_TYPES, health_create, journal_set, LEAD_MAX, LIFE_MODS, NOTICE_UNITS, PERIODS,
    trip_create, upkeep_create,
)
from ..life.web import life_get, life_review, life_upkeep_presets
from ..life.karakeep import kk_sync
from ..life.model import need_life


def _ok(c, out, code=200):
    bump(c)
    c.commit()
    return jsonify(out), code


@app.get("/api/v1/life")
@v1_view
def v1_life():
    v1_args(())
    return jsonify(v1_call(life_get))


@app.get("/api/v1/life/upkeep-presets")
@v1_view
def v1_life_upkeep_presets():
    v1_args(())
    return jsonify(v1_call(life_upkeep_presets))


@app.post("/api/v1/life/contracts")
@v1_view
def v1_life_contract():
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("name", "ends", "provider", "cost", "per", "notice", "notice_unit", "renew_months", "lead_days", "start", "account", "list_id"))
    c = db()
    tid = contract_create(c, me(), b)
    bump(c)
    c.commit()
    return jsonify(v1_one(c, tid)), 201


@app.post("/api/v1/life/devices")
@v1_view
def v1_life_device():
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("name", "model", "bought", "warranty", "lead_days", "list_id"))
    c = db()
    tid = device_create(c, me(), b)
    bump(c)
    c.commit()
    return jsonify(v1_one(c, tid)), 201


@app.post("/api/v1/life/upkeep")
@v1_view
def v1_life_upkeep():
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("title", "every_months", "next", "item", "lead_days", "list_id"))
    c = db()
    tid = upkeep_create(c, me(), b)
    bump(c)
    c.commit()
    return jsonify(v1_one(c, tid)), 201


@app.post("/api/v1/life/health")
@v1_view
def v1_life_health():
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("type", "title", "who", "date", "time", "every_months", "times", "lead_days", "list_id"))
    c = db()
    ids = health_create(c, me(), b)
    bump(c)
    c.commit()
    return jsonify(data=[v1_one(c, x) for x in ids], next_cursor=None), 201


@app.post("/api/v1/life/trips")
@v1_view
def v1_life_trip():
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("name", "from", "to", "where", "packing", "event", "folder"))
    c = db()
    return _ok(c, trip_create(c, me(), b), 201)


@app.get("/api/v1/life/review")
@v1_view
def v1_life_review():
    v1_args(("period", "date"))
    return jsonify(v1_call(life_review))


@app.put("/api/v1/life/journal/<day>")
@v1_view
def v1_life_journal(day):
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("text", "mood"))
    c = db()
    return _ok(c, journal_set(c, me(), day, b))


@app.put("/api/v1/contacts/<int:cid>/care")
@v1_view
def v1_contact_care(cid):
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("every_days", "last", "note"))
    c = db()
    return _ok(c, care_set(c, me(), cid, b))


@app.post("/api/v1/life/karakeep/sync")
@v1_view
def v1_life_kk_sync():
    v1_args(())
    reject_unknown(v1_json(), ())
    c, uid = db(), me()
    need_life(c, uid, "reading")
    return _ok(c, kk_sync(c, uid))


def life_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q):
    T = "Home & life"
    num = {"type": ["number", "null"]}
    schemas["LifeContract"] = {"type": "object", "properties": {
        "task_id": {"type": "integer"}, "list_id": {"type": "integer"}, "title": {"type": "string"}, "name": {"type": "string"},
        "provider": {"type": "string"}, "cost": num, "per": {"type": "string", "enum": list(PERIODS)},
        "monthly": {**num, "description": "The cost per month"}, "yearly": num,
        "notice": {"type": "integer"}, "notice_unit": {"type": "string", "enum": list(NOTICE_UNITS), "description": "d days, w weeks, m months"},
        "due": nul("string", format="date", description="The last day to cancel"), "ends": nul("string", format="date", description="The end of the current term"),
        "renew_months": {"type": "integer", "description": "0 = it ends, else it renews by this many months"},
        "days": nul("integer"), "account": {"type": "string"}, "start": nul("string", format="date"), "documents": {"type": "integer"}}}
    schemas["Life"] = {"type": "object", "properties": {
        "modules": {"type": "array", "items": {"type": "string", "enum": list(LIFE_MODS)}, "description": "The switched-on modules"},
        "contracts": {"type": "object", "properties": {"items": {"type": "array", "items": ref("LifeContract")}, "monthly": {"type": "number"},
                                                       "yearly": {"type": "number"}}},
        "home": {"type": "object", "properties": {"devices": {"type": "array", "items": {"type": "object"}}, "upkeep": {"type": "array", "items": {"type": "object"}}}},
        "care": {"type": "object", "properties": {"contacts": {"type": "boolean"}, "items": {"type": "array", "items": {"type": "object"}}}},
        "health": {"type": "object", "description": "Only for tokens with the scope private", "properties": {"items": {"type": "array", "items": {"type": "object"}}}},
        "travel": {"type": "object", "properties": {"trips": {"type": "array", "items": {"type": "object"}}}},
        "reading": {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object"}}, "count": {"type": "integer"},
                                                     "karakeep": {"type": "object"}}}}}
    lead = {"type": "integer", "minimum": 0, "maximum": LEAD_MAX}
    d = {"type": "string", "format": "date"}
    created = ok(ref("Task"), "Created", "201") | errs("400", "403", "404", "409")
    paths["/life"] = {"get": op("2.22.0 (Home & life): contracts with the cost per month / year, devices + upkeep, contacts to get in touch with, "
                                "health (scope private), trips and the reading list of the switched-on modules", T, ok(ref("Life")))}
    paths["/life/upkeep-presets"] = {"get": op("Suggested upkeep tasks (heating, smoke detectors, tyres ...)", T,
                                               ok({"type": "object", "properties": {"presets": {"type": "array", "items": {"type": "object"}}}}))}
    paths["/life/contracts"] = {"post": op("A contract or subscription: a task due on the last day to cancel (the end of the term minus the "
                                           "notice period), repeating with the renewal, reminders lead_days before and on the day", T, created,
                                           body={"type": "object", "required": ["name", "ends"], "properties": {
                                               "name": {"type": "string"}, "ends": {**d, "description": "End of the current term"},
                                               "provider": {"type": "string"}, "cost": {"type": "number"}, "per": {"type": "string", "enum": list(PERIODS)},
                                               "notice": {"type": "integer", "minimum": 0, "maximum": 365},
                                               "notice_unit": {"type": "string", "enum": list(NOTICE_UNITS)},
                                               "renew_months": {"type": "integer", "minimum": 0, "maximum": 120}, "lead_days": lead,
                                               "start": d, "account": {"type": "string"},
                                               "list_id": nul("integer", description="Default: the first Contracts list (created when missing)")}},
                                           scope="tasks:write")}
    paths["/life/devices"] = {"post": op("A device with its warranty (a task due when the warranty ends; link the receipt from Paperless)", T, created,
                                         body={"type": "object", "required": ["name"], "properties": {
                                             "name": {"type": "string"}, "model": {"type": "string"}, "bought": d, "warranty": d, "lead_days": lead,
                                             "list_id": nul("integer")}}, scope="tasks:write")}
    paths["/life/upkeep"] = {"post": op("A repeating upkeep task (every n months)", T, created,
                                        body={"type": "object", "required": ["title", "every_months"], "properties": {
                                            "title": {"type": "string"}, "every_months": {"type": "integer", "minimum": 1, "maximum": 120},
                                            "next": d, "item": {"type": "string"}, "lead_days": lead, "list_id": nul("integer")}}, scope="tasks:write")}
    paths["/life/health"] = {"post": op("A health entry in a private health list: an appointment, a check-up or vaccination (repeating "
                                        "every_months) or medication (a daily task per time)", T,
                                        ok(ref("TaskPage"), "Created", "201") | errs("400", "403", "404", "409"),
                                        body={"type": "object", "required": ["type", "title"], "properties": {
                                            "type": {"type": "string", "enum": list(HEALTH_TYPES)}, "title": {"type": "string"},
                                            "who": {"type": "string"}, "date": d, "time": {"type": "string", "description": "HH:MM"},
                                            "every_months": {"type": "integer", "minimum": 0, "maximum": 240},
                                            "times": {"type": "array", "items": {"type": "string"}, "description": "Medication: HH:MM"},
                                            "lead_days": lead, "list_id": nul("integer")}}, scope="private")}
    paths["/life/trips"] = {"post": op("A trip: a list with bookings, things to do before leaving and a packing list (optionally an all-day "
                                       "event)", T, ok({"type": "object", "properties": {"list_id": {"type": "integer"}, "event_id": nul("integer")}},
                                                       "Created", "201") | errs("400", "409"),
                                       body={"type": "object", "required": ["name", "from", "to"], "properties": {
                                           "name": {"type": "string"}, "from": d, "to": d, "where": {"type": "string"},
                                           "packing": {"type": "string", "description": "A packing template key, '' for none"},
                                           "event": {"type": "boolean"}, "folder": {"type": "string"}}}, scope="structure")}
    paths["/life/review"] = {"get": op("The day / week in review: done, still open, moved, the next seven days (the journal only with "
                                       "the scope private)", T, ok({"type": "object"}) | errs("400", "409"),
                                       [q("period", "day (default) or week", {"type": "string", "enum": ["day", "week"]}), q("date", "A day (default today)", d)])}
    paths["/life/journal/{day}"] = {"put": op("Write the journal entry of a day (private; empty = deleted)", T, ok({"type": "object"}) | errs("400", "409"),
                                              [{"name": "day", "in": "path", "required": True, "schema": d}],
                                              body={"type": "object", "properties": {"text": {"type": "string"},
                                                                                     "mood": nul("integer", minimum=1, maximum=5)}}, scope="private")}
    paths["/contacts/{id}/care"] = {"put": op("Stay in touch with a contact: every n days (0 = off), the last time (or \"today\"), a note", T,
                                              ok({"type": "object"}) | errs("400", "404", "409"), [pid(desc="Contact id")],
                                              body={"type": "object", "properties": {"every_days": {"type": "integer", "minimum": 0},
                                                                                     "last": {"type": "string"}, "note": {"type": "string"}}},
                                              scope="contacts")}
    paths["/life/karakeep/sync"] = {"post": op("Fetch new bookmarks from the own Karakeep connection now (and archive the ticked ones)", T,
                                               ok({"type": "object", "properties": {"added": {"type": "integer"}, "archived": {"type": "integer"},
                                                                                    "list_id": {"type": "integer"}}}) | errs("400", "409"),
                                               scope="tasks:write")}
