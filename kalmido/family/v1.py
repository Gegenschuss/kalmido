"""Family: the weekly rotation and the REST API v1 (+ MCP)."""
import json
from flask import jsonify, Response

from ..core.config import app, PUBLIC_URL
from ..core.i18n import tr
from ..core.db import bump, db, iso, iso_ms, now_utc
from ..accounts.session import me
from ..core.access import task_visible
from ..collab.news import notif_ok
from ..personal.timetrack import reject_unknown
from ..notify.push import _wd_fail, notify, push_prio
from ..api.v1 import _v1_live, v1_args, v1_call, v1_json, v1_one, v1_view
from ..family.family import (
    _jparse, deadline_create, FAM_DL, FAM_LEAD_MAX, FAM_OCC, iso_week, kids_for, occ_create, PACKING, PURPOSES,
    REWARD_COST_MAX, rot_next,
)
from ..family.web import (
    family_dl_types, family_get, family_kid_stars, family_packing_list, family_packing_new, family_reward_decide,
    family_reward_delete, family_reward_edit, family_reward_new, family_reward_request, list_shop_areas, me_purpose,
    task_to_shopping,
)


# ---- the weekly rotation (watchdog) + reminders for everyone who comes along
def _wd_rotations(c, users, S, LG, now):
    """Mode week: the turn moves on every Monday (missed weeks are skipped over); the next person gets a push."""
    wk = iso_week(now.date())
    for t in c.execute("""SELECT t.* FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.rotation LIKE '%"week"%' AND t.status=0
                          AND t.deleted_at IS NULL AND l.archived=0""").fetchall():
        try:
            r = _jparse(t["rotation"]) or {}
            if r.get("mode") != "week" or r.get("wk") == wk or not r.get("who"):
                continue
            nxt = rot_next(c, t)
            r2 = _jparse(nxt[1]) if nxt else r
            r2["wk"] = wk
            new = nxt[0] if nxt else t["assignee_id"]
            c.execute("UPDATE tasks SET rotation=?, assignee_id=?, assignee_group_id=NULL, reminded='[]', updated_at=? WHERE id=?",
                      (json.dumps(r2, separators=(",", ":")), new, iso(now_utc()), t["id"]))
            if new != t["assignee_id"]:
                c.execute("INSERT INTO activity(task_id,user_id,kind,data,created_at) VALUES(?,?,?,?,?)",
                          (t["id"], None, "rotation", json.dumps({"to": new}), iso_ms(now_utc())))
                s = S.get(new)
                if new in users and s and notif_ok(c, new, s, "assign", "push", t["list_id"]):
                    lg = LG.get(new, "en")
                    notify(new, t["title"], tr("Your turn this week", lg=lg), push_prio(s), f"{PUBLIC_URL}/#t/{t['id']}", s=s, task=t["id"])
            bump(c)
            c.commit()
        except Exception as e:  # noqa: BLE001
            _wd_fail(c, "rotation of task", t["id"], e)


def reminder_people(c, t, users, rcpt):
    """Who else gets the reminder of task t: everyone who comes along (task_people) and can still see it."""
    return [u for u in (r[0] for r in c.execute("SELECT user_id FROM task_people WHERE task_id=? ORDER BY user_id", (t["id"],)))
            if u != rcpt and u in users and task_visible(c, t["id"], u)]


# ---- REST API v1 (+ MCP)
@app.get("/api/v1/family")
@v1_view
def v1_family():
    v1_args(("week",))
    return jsonify(v1_call(family_get))


@app.post("/api/v1/family/occasions")
@v1_view
def v1_family_occasion():
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("name", "kind", "date", "year", "lead_days", "list_id", "gifts"))
    c = db()
    tid = occ_create(c, me(), b)
    bump(c)
    c.commit()
    return jsonify(v1_one(c, tid)), 201


@app.get("/api/v1/family/deadline-types")
@v1_view
def v1_family_dl_types():
    v1_args(())
    return jsonify(v1_call(family_dl_types))


@app.post("/api/v1/family/deadlines")
@v1_view
def v1_family_deadline():
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("type", "expires", "who", "notice_months", "lead_days", "title", "list_id"))
    c = db()
    tid = deadline_create(c, me(), b)
    bump(c)
    c.commit()
    return jsonify(v1_one(c, tid)), 201


@app.post("/api/v1/tasks/<int:tid>/to-shopping")
@v1_view
def v1_task_to_shopping(tid):
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("list_id", "items"))
    _v1_live(db(), tid, write=False, full=True)
    return jsonify(v1_call(task_to_shopping, tid, body=b))


@app.post("/api/v1/lists/<int:lid>/shop-areas")
@v1_view
def v1_list_shop_areas(lid):
    v1_args(())
    reject_unknown(v1_json(), ())
    return jsonify(v1_call(list_shop_areas, lid, body={}))


@app.get("/api/v1/family/packing")
@v1_view
def v1_family_packing():
    v1_args(())
    return jsonify(v1_call(family_packing_list))


@app.post("/api/v1/family/packing")
@v1_view
def v1_family_packing_new():
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("template", "name"))
    return jsonify(v1_call(family_packing_new, body=b)), 201


@app.get("/api/v1/family/kids")
@v1_view
def v1_family_kids():
    v1_args(())
    return jsonify(data=kids_for(db(), me()), next_cursor=None)


@app.post("/api/v1/family/kids/<int:kid>/stars")
@v1_view
def v1_family_kid_stars(kid):
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("delta", "note"))
    return jsonify(v1_call(family_kid_stars, kid, body=b))


@app.post("/api/v1/family/kids/<int:kid>/rewards")
@v1_view
def v1_family_reward_new(kid):
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("title", "cost", "emoji", "once"))
    return jsonify(v1_call(family_reward_new, kid, body=b)), 201


@app.patch("/api/v1/family/rewards/<int:rid>")
@v1_view
def v1_family_reward_edit(rid):
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("title", "cost", "emoji", "once"))
    return jsonify(v1_call(family_reward_edit, rid, body=b))


@app.delete("/api/v1/family/rewards/<int:rid>")
@v1_view
def v1_family_reward_delete(rid):
    v1_args(())
    v1_call(family_reward_delete, rid, body={})
    return Response(status=204)


@app.post("/api/v1/family/rewards/<int:rid>/request")
@v1_view
def v1_family_reward_request(rid):
    v1_args(())
    reject_unknown(v1_json(), ())
    return jsonify(v1_call(family_reward_request, rid, body={}))


@app.post("/api/v1/family/rewards/<int:rid>/decide")
@v1_view
def v1_family_reward_decide(rid):
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("approve",))
    return jsonify(v1_call(family_reward_decide, rid, body=b))


@app.post("/api/v1/me/purpose")
@v1_view
def v1_me_purpose():
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("purpose", "examples"))
    return jsonify(v1_call(me_purpose, body=b))


def family_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q):
    F = "Family"
    schemas["FamilyOccasion"] = {"type": "object", "properties": {
        "task_id": {"type": "integer"}, "list_id": {"type": "integer"}, "title": {"type": "string"}, "kind": {"type": "string", "enum": list(FAM_OCC)},
        "name": {"type": "string"}, "date": {"type": "string", "format": "date", "description": "The next date"},
        "days": {"type": "integer", "description": "Days from today"}, "year": nul("integer", description="Year of birth / of the wedding"),
        "age": nul("integer", description="Age on that date (birthday) / years (anniversary)"), "gifts": {"type": "integer", "description": "Gift ideas (subtasks)"}}}
    schemas["FamilyDeadline"] = {"type": "object", "properties": {
        "task_id": {"type": "integer"}, "list_id": {"type": "integer"}, "title": {"type": "string"}, "type": {"type": "string", "enum": list(FAM_DL)},
        "who": {"type": "string"}, "expires": nul("string", format="date"), "due": {"type": "string", "format": "date",
                                                                                    "description": "expires minus the notice period"},
        "days": {"type": "integer"}}}
    schemas["FamilyRotation"] = {"type": "object", "properties": {
        "task_id": {"type": "integer"}, "list_id": {"type": "integer"}, "title": {"type": "string"}, "mode": {"type": "string", "enum": ["done", "week"]},
        "who": {"type": "array", "items": {"type": "object", "properties": {"user_id": {"type": "integer"}, "name": {"type": "string"}}}},
        "current": nul("integer"), "next": {"type": "integer"}, "due": nul("string", format="date")}}
    schemas["Reward"] = {"type": "object", "properties": {
        "id": {"type": "integer"}, "kid_id": {"type": "integer"}, "title": {"type": "string"}, "emoji": {"type": "string"},
        "cost": {"type": "integer", "description": "Stars"}, "once": {"type": "boolean", "description": "Gone after it was redeemed once"},
        "state": {"type": "string", "enum": ["open", "requested", "redeemed"]}, "requested_at": nul("string"), "decided_at": nul("string"),
        "decided_by": nul("integer")}}
    schemas["Kid"] = {"type": "object", "properties": {
        "id": {"type": "integer"}, "username": {"type": "string"}, "display_name": {"type": "string"}, "kid": {"type": "boolean"},
        "stars": {"type": "integer", "description": "The balance"}, "parents": {"type": "array", "items": {"type": "integer"}},
        "rewards": {"type": "array", "items": ref("Reward")}, "requests": {"type": "integer"},
        "history": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "integer"}, "delta": {"type": "integer"}, "kind": {"type": "string", "enum": ["task", "bonus", "reward"]},
            "title": {"type": "string"}, "task_id": nul("integer"), "by": nul("integer"), "at": {"type": "string"}}}}}}
    schemas["KidPage"] = page("Kid")
    schemas["Family"] = {"type": "object", "properties": {
        "occasions": {"type": "array", "items": ref("FamilyOccasion")}, "deadlines": {"type": "array", "items": ref("FamilyDeadline")},
        "rotations": {"type": "array", "items": ref("FamilyRotation")}, "week": {"type": "string", "format": "date", "description": "Monday of the meal plan"},
        "meals": {"type": "array", "items": {"type": "object", "properties": {
            "task_id": {"type": "integer"}, "list_id": {"type": "integer"}, "title": {"type": "string"}, "day": {"type": "string", "format": "date"},
            "time": nul("string"), "ingredients": {"type": "array", "items": {"type": "string"}}}}},
        "shopping": {"type": "array", "items": {"type": "object", "properties": {
            "list_id": {"type": "integer"}, "name": {"type": "string"}, "open": {"type": "integer"}, "role": {"type": "string"}}}},
        "kids": {"type": "array", "items": ref("Kid")}, "kid": {"type": "boolean", "description": "The token's user is a kid account"}}}
    kid_p, rid_p = pid("id", "Kid (user) id"), pid("id", "Reward id")
    paths["/family"] = {"get": op("2.19.0 (module Family): upcoming birthdays + anniversaries, deadlines, rotations, the week's meal plan, "
                                  "shopping lists, kids", F, ok(ref("Family")) | errs("400"),
                                  [q("week", "A day of the week whose meal plan to show (default: this week)", {"type": "string", "format": "date"})])}
    paths["/family/occasions"] = {"post": op("A birthday or anniversary: a yearly task with the age, reminders lead_days before and on the day, "
                                             "gift ideas as subtasks", F, ok(ref("Task"), "Created", "201") | errs("400", "403", "404"),
                                             body={"type": "object", "required": ["name", "date"], "properties": {
                                                 "name": {"type": "string"}, "kind": {"type": "string", "enum": list(FAM_OCC)},
                                                 "date": {"type": "string", "description": "YYYY-MM-DD (with the year) or --MM-DD"},
                                                 "year": nul("integer"), "lead_days": {"type": "integer", "minimum": 0, "maximum": FAM_LEAD_MAX},
                                                 "list_id": nul("integer", description="Default: the first Birthdays list (created when missing)"),
                                                 "gifts": {"type": "array", "items": {"type": "string"}}}}, scope="tasks:write")}
    paths["/family/deadline-types"] = {"get": op("The built-in household deadline types (passport, ID card, car inspection, insurance, contract, other)",
                                                 F, ok({"type": "object", "properties": {"types": {"type": "array", "items": {"type": "object"}}}}))}
    paths["/family/deadlines"] = {"post": op("A household deadline (due = expires minus the notice period, a deadline with reminders)", F,
                                             ok(ref("Task"), "Created", "201") | errs("400", "403", "404"),
                                             body={"type": "object", "required": ["expires"], "properties": {
                                                 "type": {"type": "string", "enum": list(FAM_DL)}, "expires": {"type": "string", "format": "date"},
                                                 "who": {"type": "string"}, "notice_months": {"type": "integer", "minimum": 0, "maximum": 24},
                                                 "lead_days": {"type": "integer", "minimum": 0, "maximum": FAM_LEAD_MAX}, "title": {"type": "string"},
                                                 "list_id": nul("integer", description="Default: the first Household list (created when missing)")}},
                                             scope="tasks:write")}
    paths["/tasks/{id}/to-shopping"] = {"post": op("Put the ingredients of a meal (the lists in its notes, or items) on a shopping list; open "
                                                   "items with the same name are not added twice", F,
                                                   ok({"type": "object", "properties": {"list_id": {"type": "integer"}, "added": {"type": "array", "items": {"type": "object"}},
                                                                                        "skipped": {"type": "array", "items": {"type": "string"}}}}) | errs("400", "403", "404"),
                                                   [pid()], body={"type": "object", "properties": {"list_id": nul("integer"),
                                                                                                    "items": {"type": "array", "items": {"type": "string"}}}},
                                                   scope="tasks:write")}
    paths["/lists/{id}/shop-areas"] = {"post": op("Make a list a shopping list and add the default shop areas as sections", F,
                                                  ok({"type": "object", "properties": {"added": {"type": "integer"}}}) | errs("403", "404"),
                                                  [pid(desc="List id")], scope="structure")}
    paths["/family/packing"] = {
        "get": op("The built-in packing list templates", F, ok({"type": "object", "properties": {"templates": {"type": "array", "items": {"type": "object"}}}})),
        "post": op("A new packing list from a template", F, ok({"type": "object", "properties": {"list_id": {"type": "integer"}}}, "Created", "201") | errs("400"),
                   body={"type": "object", "required": ["template"], "properties": {"template": {"type": "string", "enum": list(PACKING)},
                                                                                     "name": {"type": "string"}}}, scope="structure")}
    paths["/family/kids"] = {"get": op("The kids the token's user looks after (or the kid itself) with stars, rewards and history", F, ok(ref("KidPage")))}
    paths["/family/kids/{id}/stars"] = {"post": op("Give (or correct) stars by hand (parents)", F, ok(ref("Kid")) | errs("400", "404", "409"), [kid_p],
                                                   body={"type": "object", "required": ["delta"], "properties": {"delta": {"type": "integer"}, "note": {"type": "string"}}},
                                                   scope="tasks:write")}
    rin = {"type": "object", "properties": {"title": {"type": "string"}, "cost": {"type": "integer", "minimum": 1, "maximum": REWARD_COST_MAX},
                                            "emoji": {"type": "string"}, "once": {"type": "boolean"}}}
    paths["/family/kids/{id}/rewards"] = {"post": op("Offer a reward (parents)", F, ok(ref("Reward"), "Created", "201") | errs("400", "404", "409"), [kid_p],
                                                     body={**rin, "required": ["title", "cost"]}, scope="tasks:write")}
    paths["/family/rewards/{id}"] = {
        "patch": op("Change a reward (parents)", F, ok(ref("Reward")) | errs("400", "404"), [rid_p], body=rin, scope="tasks:write"),
        "delete": op("Delete a reward (parents)", F, {"204": {"description": "Deleted"}} | errs("404"), [rid_p], scope="delete")}
    paths["/family/rewards/{id}/request"] = {"post": op("Ask for a reward (the kid itself, with enough stars)", F, ok(ref("Kid")) | errs("403", "404", "409"),
                                                        [rid_p], scope="tasks:write")}
    paths["/family/rewards/{id}/decide"] = {"post": op("Approve (stars are taken) or decline a reward (parents)", F, ok(ref("Kid")) | errs("400", "404", "409"),
                                                       [rid_p], body={"type": "object", "required": ["approve"], "properties": {"approve": {"type": "boolean"}}},
                                                       scope="tasks:write")}
    paths["/me/purpose"] = {"post": op("What the token's user uses Kalmido for: switches the modules and creates the starter lists once", F,
                                       ok({"type": "object", "properties": {"features": {"type": "string"}, "created": {"type": "array", "items": {"type": "integer"}}}}) | errs("400"),
                                       body={"type": "object", "required": ["purpose"], "properties": {"purpose": {"type": "string", "enum": list(PURPOSES)},
                                                                                                       "examples": {"type": "boolean"}}}, scope="account")}
