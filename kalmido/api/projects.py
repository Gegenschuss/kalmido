"""The project overview in the token API."""
from flask import jsonify

from ..core.config import app, MAX_FILE_MB
from ..core.db import db
from ..core.access import Denied
from ..tasks.validation import as_int
from ..collab.comments import user_names
from ..personal.timetrack import UnknownFields
from ..lists.projects import (
    list_file_delete, list_file_get, list_file_upload, ms_compat, ms_rows, need_overview, OV_DESC_MAX, ov_file_dict,
    OV_FILES_MAX, ov_link_add, ov_link_delete, ov_link_dict, ov_link_order, ov_link_update, ov_ms_add, ov_ms_delete,
    ov_ms_update, OV_TITLE_MAX, overview_get, overview_patch,
)
from ..api.v1 import v1_args, v1_call, v1_json, v1_view


# ---------------------------------------------------------------- 2.7.1 (#410): the project overview in the token API
# ---- the token API (scopes as usual: reads read, changes write)
@app.get("/api/v1/lists/<int:lid>/overview")
@v1_view
def v1_overview(lid):
    v1_args(())
    return jsonify(v1_call(overview_get, lid))


@app.patch("/api/v1/lists/<int:lid>/overview")
@v1_view
def v1_overview_patch(lid):
    v1_args(())
    b = v1_json()
    unknown = sorted(k for k in b if k != "description")
    if unknown:
        raise UnknownFields(unknown)
    return jsonify(v1_call(overview_patch, lid, body=b))


@app.get("/api/v1/lists/<int:lid>/links")
@v1_view
def v1_ov_links(lid):
    v1_args(())
    c = db()
    need_overview(c, lid)
    return jsonify(data=[ov_link_dict(r) for r in c.execute("SELECT * FROM list_links WHERE list_id=? ORDER BY sort, id", (lid,))],
                   next_cursor=None)


@app.post("/api/v1/lists/<int:lid>/links")
@v1_view
def v1_ov_link_add(lid):
    v1_args(())
    b = v1_json()
    unknown = sorted(k for k in b if k not in ("title", "url"))
    if unknown:
        raise UnknownFields(unknown)
    return jsonify(v1_call(ov_link_add, lid, body=b)), 201


@app.patch("/api/v1/lists/<int:lid>/links/<link_id>")  # not <int:>: the spec path keeps its own name
@v1_view
def v1_ov_link_update(lid, link_id):
    v1_args(())
    rid = as_int(link_id, "link_id", 1)
    b = v1_json()
    unknown = sorted(k for k in b if k not in ("title", "url"))
    if unknown:
        raise UnknownFields(unknown)
    return jsonify(v1_call(ov_link_update, lid, rid, body=b))


@app.delete("/api/v1/lists/<int:lid>/links/<link_id>")
@v1_view
def v1_ov_link_delete(lid, link_id):
    v1_args(())
    rid = as_int(link_id, "link_id", 1)
    v1_call(ov_link_delete, lid, rid)
    return "", 204


@app.put("/api/v1/lists/<int:lid>/links/order")
@v1_view
def v1_ov_link_order(lid):
    v1_args(())
    b = v1_json()
    unknown = sorted(k for k in b if k != "ids")
    if unknown:
        raise UnknownFields(unknown)
    return jsonify({**v1_call(ov_link_order, lid, body=b), "next_cursor": None})


@app.get("/api/v1/lists/<int:lid>/milestones")
@v1_view
def v1_ov_milestones(lid):
    v1_args(())
    c = db()
    need_overview(c, lid)
    return jsonify(data=[ms_compat(r) for r in ms_rows(c, [lid])], next_cursor=None)  # 2.18.0 (#430): ids = task ids


@app.post("/api/v1/lists/<int:lid>/milestones")
@v1_view
def v1_ov_ms_add(lid):
    v1_args(())
    b = v1_json()
    unknown = sorted(k for k in b if k not in ("name", "day", "done"))
    if unknown:
        raise UnknownFields(unknown)
    return jsonify(v1_call(ov_ms_add, lid, body=b)), 201


@app.patch("/api/v1/lists/<int:lid>/milestones/<milestone_id>")
@v1_view
def v1_ov_ms_update(lid, milestone_id):
    v1_args(())
    rid = as_int(milestone_id, "milestone_id", 1)
    b = v1_json()
    unknown = sorted(k for k in b if k not in ("name", "day", "done"))
    if unknown:
        raise UnknownFields(unknown)
    return jsonify(v1_call(ov_ms_update, lid, rid, body=b))


@app.delete("/api/v1/lists/<int:lid>/milestones/<milestone_id>")
@v1_view
def v1_ov_ms_delete(lid, milestone_id):
    v1_args(())
    rid = as_int(milestone_id, "milestone_id", 1)
    v1_call(ov_ms_delete, lid, rid)
    return "", 204


@app.get("/api/v1/lists/<int:lid>/files")
@v1_view
def v1_list_files(lid):
    v1_args(())
    c = db()
    need_overview(c, lid)
    rows = c.execute("SELECT * FROM list_files WHERE list_id=? ORDER BY id DESC", (lid,)).fetchall()
    names = user_names(c, [r["user_id"] for r in rows])
    return jsonify(data=[ov_file_dict(r, names) for r in rows], next_cursor=None)


@app.post("/api/v1/lists/<int:lid>/files")
@v1_view
def v1_list_file_upload(lid):
    v1_args(())
    j = v1_call(list_file_upload, lid)
    return jsonify(data=j["files"], next_cursor=None), 201


@app.get("/api/v1/lists/<int:lid>/files/<file_id>")
@v1_view
def v1_list_file_get(lid, file_id):
    v1_args(("dl",))
    fid = as_int(file_id, "file_id", 1)
    c = db()
    r = c.execute("SELECT list_id FROM list_files WHERE id=?", (fid,)).fetchone()
    if not r or r["list_id"] != lid:
        raise Denied(404)
    return list_file_get(fid)


@app.delete("/api/v1/lists/<int:lid>/files/<file_id>")
@v1_view
def v1_list_file_delete(lid, file_id):
    v1_args(())
    fid = as_int(file_id, "file_id", 1)
    c = db()
    r = c.execute("SELECT list_id FROM list_files WHERE id=?", (fid,)).fetchone()
    if not r or r["list_id"] != lid:
        raise Denied(404)
    v1_call(list_file_delete, fid)
    return "", 204


def overview_spec(paths, schemas, op, ok, errs, ref, pid, nul, page):
    """2.7.1 (#410) additions to the OpenAPI document."""
    W, L = "write", "Lists"
    lp = pid("id", "List id (a project list)")
    sub = lambda n, d: {"name": n, "in": "path", "required": True, "description": d, "schema": {"type": "integer"}}  # noqa: E731
    link = {"type": "object", "properties": {"id": {"type": "integer"}, "title": {"type": "string"}, "url": {"type": "string", "format": "uri"},
                                             "sort": {"type": "number"}}}
    ms = {"type": "object", "description": "A milestone in the overview's shape. Since 2.18.0 milestones are tasks (milestone: true): "
                                          "id is the task id, name its title, day its due date (null when it has none), done = not open.",
          "properties": {"id": {"type": "integer"}, "name": {"type": "string"}, "day": {"type": "string", "format": "date", "nullable": True},
                         "done": {"type": "boolean"}}}
    lfile = {"type": "object", "properties": {"id": {"type": "integer"}, "name": {"type": "string"}, "mime": {"type": "string"},
                                              "size": {"type": "integer"}, "created_at": {"type": "string", "format": "date-time"},
                                              "user_id": nul("integer"), "user_name": {"type": "string"}}}
    schemas.update({
        "KeyLink": link, "KeyLinkPage": page("KeyLink"), "Milestone": ms, "MilestonePage": page("Milestone"),
        "MilestoneReport": {"type": "object", "properties": {  # 2.18.0 (#430)
            "milestone": {"type": "object", "properties": {"id": {"type": "integer"}, "title": {"type": "string"}, "list_id": {"type": "integer"},
                                                           "due": {"type": ["string", "null"], "format": "date"}, "status": {"type": "string"}}},
            "progress": {"type": "object", "properties": {"done": {"type": "integer"}, "total": {"type": "integer"}, "percent": {"type": "integer"}}},
            "tasks": {"type": "array", "items": {"type": "object", "properties": {
                "id": {"type": "integer"}, "title": {"type": "string"}, "status": {"type": "string"}, "type": {"type": ["string", "null"]},
                "due": {"type": ["string", "null"]}, "assignee_id": {"type": ["integer", "null"]}, "completed_at": {"type": ["string", "null"]}}}},
            "burndown": {"type": "object", "properties": {
                "start": {"type": "string", "format": "date"}, "end": {"type": "string", "format": "date"}, "due": {"type": ["string", "null"]},
                "days": {"type": "array", "items": {"type": "object", "properties": {"day": {"type": "string"}, "open": {"type": "integer"}}}},
                "ideal": {"type": "array", "items": {"type": "object", "properties": {"day": {"type": "string"}, "open": {"type": "integer"}}}}}},
            "release_notes": {"type": "string", "description": "Markdown"}}},
        "ProjectFile": lfile, "ProjectFilePage": page("ProjectFile"),
        "ProjectOverview": {"type": "object", "description": "The overview of a project list (2.7.1). Task files and Paperless "
                                                             "documents of tasks are read-only here (change them on the task).",
                            "properties": {
                                "list_id": {"type": "integer"}, "name": {"type": "string"}, "role": {"type": "string"},
                                "can_edit": {"type": "boolean"}, "description": {"type": "string", "description": "Markdown"},
                                "links": {"type": "array", "items": ref("KeyLink")}, "milestones": {"type": "array", "items": ref("Milestone")},
                                "files": {"type": "array", "items": ref("ProjectFile")},
                                "paperless": {"type": "array", "items": {"type": "object"}, "description": "Documents linked to the list "
                                              "(hidden: true = a connection the token's user cannot use)"},
                                "task_files": {"type": "array", "items": {"type": "object"}, "description": "Files of the list's tasks, "
                                               "each with task_id + task_title (download: GET /tasks/{id} ... the web app's file URL)"},
                                "task_paperless": {"type": "array", "items": {"type": "object"}},
                                "members": {"type": "array", "items": {"type": "object"}, "description": "Owner + members with role "
                                            "(empty while collaboration is off)"},
                                "status": {"type": "object", "description": "current, note, at, history (newest first, at most 10)"},
                                "time": nul("object", description="seconds, budget_h, day_hours (null while time tracking is off)")}},
    })
    body_link = {"type": "object", "required": ["url"], "additionalProperties": False,
                 "properties": {"title": {"type": "string", "maxLength": OV_TITLE_MAX}, "url": {"type": "string", "format": "uri"}}}
    body_ms = {"type": "object", "required": ["name", "day"], "additionalProperties": False,
               "properties": {"name": {"type": "string", "maxLength": OV_TITLE_MAX}, "day": {"type": "string", "format": "date"},
                              "done": {"type": "boolean"}}}
    paths.update({
        "/lists/{id}/overview": {
            "get": op("The overview of a project list: description, key links, milestones, files, members, status, time", L,
                      ok(ref("ProjectOverview")) | errs("403", "404", "409"), [lp]),
            "patch": op("Change the project description (Markdown; owner, list admins, members)", L,
                        ok(ref("ProjectOverview")) | errs("400", "403", "404", "409"), [lp], scope=W,
                        body={"type": "object", "additionalProperties": False,
                              "properties": {"description": {"type": "string", "maxLength": OV_DESC_MAX}}})},
        "/lists/{id}/links": {
            "get": op("Key links of a project list, in their order", L, ok(ref("KeyLinkPage")) | errs("404", "409"), [lp]),
            "post": op("Add a key link (at the end)", L, ok(ref("KeyLink"), "Created", "201") | errs("400", "403", "404", "409"), [lp],
                       scope=W, body=body_link)},
        "/lists/{id}/links/order": {
            "put": op("Reorder the key links (every link id exactly once)", L, ok(ref("KeyLinkPage")) | errs("400", "403", "404", "409"),
                      [lp], scope=W, body={"type": "object", "required": ["ids"], "properties": {
                          "ids": {"type": "array", "items": {"type": "integer"}}}})},
        "/lists/{id}/links/{link_id}": {
            "patch": op("Change a key link", L, ok(ref("KeyLink")) | errs("400", "403", "404", "409"), [lp, sub("link_id", "Link id")],
                        scope=W, body={**body_link, "required": []}),
            "delete": op("Remove a key link", L, {"204": {"description": "Deleted"}} | errs("403", "404", "409"),
                         [lp, sub("link_id", "Link id")], scope=W)},
        "/lists/{id}/milestones": {
            "get": op("Milestones of a project list (by day; the milestone tasks of the list, ids are task ids since 2.18.0)", L, ok(ref("MilestonePage")) | errs("404", "409"), [lp]),
            "post": op("Add a milestone (creates a milestone task at the end of the list)", L, ok(ref("Milestone"), "Created", "201") | errs("400", "403", "404", "409"), [lp],
                       scope=W, body=body_ms)},
        "/lists/{id}/milestones/{milestone_id}": {
            "patch": op("Change a milestone (name, day, done; milestone_id = its task id)", L, ok(ref("Milestone")) | errs("400", "403", "404", "409"),
                        [lp, sub("milestone_id", "Milestone id")], scope=W, body={**body_ms, "required": []}),
            "delete": op("Remove a milestone (moves its task to the trash)", L, {"204": {"description": "Deleted"}} | errs("403", "404", "409"),
                         [lp, sub("milestone_id", "Milestone id")], scope=W)},
        "/lists/{id}/files": {
            "get": op("Project files of a list (uploaded on the list itself, newest first)", L, ok(ref("ProjectFilePage")) | errs("404", "409"), [lp]),
            "post": {**op(f"Upload project files (multipart field `file`, repeatable; at most {MAX_FILE_MB} MB each, "
                          f"{OV_FILES_MAX} per list)", L, ok(ref("ProjectFilePage"), "Created", "201") | errs("400", "403", "404", "409", "413"),
                          [lp], scope=W),
                     "requestBody": {"required": True, "content": {"multipart/form-data": {"schema": {
                         "type": "object", "properties": {"file": {"type": "array", "items": {"type": "string", "format": "binary"}}}}}}}}},
        "/lists/{id}/files/{file_id}": {
            "get": op("Download a project file (images and PDFs inline unless ?dl=1, everything else as a download)", L,
                      {"200": {"description": "The file"}} | errs("404", "409"), [lp, sub("file_id", "File id")]),
            "delete": op("Delete a project file", L, {"204": {"description": "Deleted"}} | errs("403", "404", "409"),
                         [lp, sub("file_id", "File id")], scope=W)},
    })
