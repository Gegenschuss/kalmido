"""2.60.0 (#1511): story points and velocity. tasks.points holds a task's estimate (1, 2, 3, 5, 8, 13; tasks/validation.py
spt_clean), lists.points_on switches their display on. The velocity = the completed points of the list's last closed
sprints (table sprints, written by lists/sprints.py): the sprint's close-out (review json points_done / count_done) when
there is one, else counted from its completed tasks. Participants only count the tasks they see."""
import json
from flask import jsonify

from ..core.config import app
from ..core.db import db
from ..core.access import list_role, need_list, pvis
from ..accounts.session import me
from ..api.v1 import v1_args, v1_view

SPT_SPRINTS = 6  # closed sprints in the velocity (the newest ones)


def spt_velocity(c, lid, uid):
    """{sprints: [{id, num, name, start, end_day, points, count}] oldest first, average (points per sprint, one decimal;
    null without a closed sprint), points_on}. The caller checks that uid sees list lid."""
    part = list_role(c, lid, uid) == "participant"
    seen = pvis(c, uid, lid)[0] if part else None
    rows = c.execute("SELECT id, num, name, start, end_day, review FROM sprints WHERE list_id=? AND state='closed' "
                     "ORDER BY num DESC, id DESC LIMIT ?", (lid, SPT_SPRINTS)).fetchall()
    out = []
    for r in reversed(rows):
        try:
            rv = json.loads(r["review"] or "null")
        except (TypeError, ValueError):
            rv = None
        if not part and isinstance(rv, dict) and isinstance(rv.get("points_done"), int):
            pts, n = rv["points_done"], rv.get("count_done") if isinstance(rv.get("count_done"), int) else 0
        else:  # no close-out (yet) or a participant: count the sprint's completed tasks (milestones do not count)
            done = [t for t in c.execute("SELECT id, points FROM tasks WHERE sprint_id=? AND list_id=? AND status=2 AND "
                                         "deleted_at IS NULL AND COALESCE(ms, 0)=0", (r["id"], lid)).fetchall()
                    if seen is None or t["id"] in seen]
            pts, n = sum(t["points"] or 0 for t in done), len(done)
        out.append({"id": r["id"], "num": r["num"], "name": r["name"] or "", "start": r["start"], "end_day": r["end_day"],
                    "points": pts, "count": n})
    on = c.execute("SELECT points_on FROM lists WHERE id=?", (lid,)).fetchone()
    return {"sprints": out, "average": round(sum(s["points"] for s in out) / len(out), 1) if out else None,
            "points_on": bool(on and on["points_on"])}


@app.get("/api/lists/<int:lid>/velocity")
def spt_velocity_get(lid):
    c = db()
    need_list(c, lid, write=False)
    return jsonify(spt_velocity(c, lid, me()))


@app.get("/api/v1/lists/<int:lid>/velocity")
@v1_view
def spt_v1_velocity(lid):
    """2.60.0 (#1511): the list's velocity (read scope; lists the token sees)."""
    v1_args(())
    c = db()
    need_list(c, lid, write=False)
    return jsonify(spt_velocity(c, lid, me()))


def spt_spec(paths, schemas, op, ok, errs, ref, pid, nul):
    """OpenAPI: story points / velocity (called from openapi_spec)."""
    pon = {"type": "boolean", "description": "2.60.0 (#1511): story points shown in the app (the owner; default off). Tasks keep "
           "their points (field points) either way"}
    for k in ("List", "ListDetail", "ListInput", "ListPatch"):
        if k in schemas and "properties" in schemas[k]:
            schemas[k]["properties"]["points_on"] = pon
    schemas["Velocity"] = {"type": "object", "properties": {
        "sprints": {"type": "array", "description": "The last (up to 6) closed sprints of the list, oldest first", "items": {
            "type": "object", "properties": {"id": {"type": "integer"}, "num": {"type": "integer"},
                                             "name": {"type": "string", "description": "Empty = \"Sprint <num>\""},
                                             "start": {"type": "string", "format": "date"}, "end_day": {"type": "string", "format": "date"},
                                             "points": {"type": "integer", "description": "Story points of its completed tasks"},
                                             "count": {"type": "integer", "description": "Its completed tasks"}}}},
        "average": nul("number", description="Completed points per sprint (one decimal); null = no closed sprint yet"),
        "points_on": {"type": "boolean", "description": "Story points are switched on for the list"}}}
    paths["/lists/{id}/velocity"] = {"get": op(
        "Velocity: completed story points of the last sprints (2.60.0)", "Lists", ok(ref("Velocity")) | errs("404"),
        [pid("id", "List id")],
        desc="The completed story points (and tasks) of the list's last up to 6 closed sprints and their average, a planning aid "
             "for the next sprint. Participants count only the tasks they see.")}
