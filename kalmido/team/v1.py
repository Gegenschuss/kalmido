"""Team, family, clients (#463): the REST API v1 (+ MCP) and its OpenAPI part: clients, workload, approvals, forms."""
from flask import jsonify

from ..core.config import app
from ..core.errors import reject_unknown
from ..api.common import v1_args, v1_call, v1_json, v1_view
from ..team.clients import CLIENT_FIELDS, client_create, client_delete, client_get, client_update, clients_list
from ..team.clients_bulk import clients_bulk
from ..team.workload import workload_get
from ..team.approvals import APPROVAL_ACTIONS, APPROVAL_STATES, task_approval
from ..team.forms import FORM_ACCESS, FRM_TTYPES, form_create, form_delete, form_update, forms_list


@app.get("/api/v1/clients")
@v1_view
def v1_clients():
    v1_args(("month", "archived"))
    return jsonify(v1_call(clients_list))


@app.post("/api/v1/clients")
@v1_view
def v1_client_create():
    v1_args(())
    b = v1_json()
    reject_unknown(b, CLIENT_FIELDS + ("contacts",))  # 2.59.0 (#1735): the contact persons (documented since 2.40.0, contact_id)
    return jsonify(v1_call(client_create, body=b)), 201


@app.get("/api/v1/clients/<int:cid>")
@v1_view
def v1_client(cid):
    v1_args(("month",))
    return jsonify(v1_call(client_get, cid))


@app.patch("/api/v1/clients/<int:cid>")
@v1_view
def v1_client_update(cid):
    v1_args(())
    b = v1_json()
    reject_unknown(b, CLIENT_FIELDS + ("contacts", "contacts_removed", "expect_updated_at"))  # 2.59.0 (#1735); 2.269.0 C (#3017)
    return jsonify(v1_call(client_update, cid, body=b))


@app.delete("/api/v1/clients/<int:cid>")
@v1_view
def v1_client_delete(cid):
    v1_args(())
    return jsonify(v1_call(client_delete, cid))


@app.post("/api/v1/clients/bulk")
@v1_view
def v1_clients_bulk():  # 2.47.3 (#1733)
    v1_args(())
    return jsonify(v1_call(clients_bulk, body=v1_json()))


@app.get("/api/v1/workload")
@v1_view
def v1_workload():
    v1_args(("start", "weeks", "org"))
    return jsonify(v1_call(workload_get))


@app.post("/api/v1/tasks/<int:tid>/approval")
@v1_view
def v1_task_approval(tid):
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("action", "approver_id", "note"))
    return jsonify(v1_call(task_approval, tid, body=b))


@app.get("/api/v1/lists/<int:lid>/forms")
@v1_view
def v1_forms(lid):
    v1_args(())
    return jsonify(v1_call(forms_list, lid))


@app.post("/api/v1/lists/<int:lid>/forms")
@v1_view
def v1_form_create(lid):
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("title", "intro", "access", "section_id", "ask_email", "ttype", "files", "portal", *FQ_V1))  # 2.63.0 (#1513), 2.98.0 B
    return jsonify(v1_call(form_create, lid, body=b)), 201


@app.patch("/api/v1/forms/<int:fid>")
@v1_view
def v1_form_update(fid):
    v1_args(())
    b = v1_json()
    reject_unknown(b, ("title", "intro", "access", "section_id", "ask_email", "enabled", "regenerate", "ttype", "files", "portal", *FQ_V1))
    return jsonify(v1_call(form_update, fid, body=b))


@app.delete("/api/v1/forms/<int:fid>")
@v1_view
def v1_form_delete(fid):
    v1_args(())
    return jsonify(v1_call(form_delete, fid))


# 2.63.0 (#1513): a form as a report form: the task type, one file, a status link for the sender
FRM_V1 = {"ttype": {"type": "string", "enum": list(FRM_TTYPES), "description": "2.63.0: the type of the task a sent form makes ('' = none, bug = bug report)"},
          "files": {"type": "boolean", "description": "2.63.0: the sender may add one file"},
          "portal": {"type": "boolean", "description": "2.63.0: a sender without an account gets a status link (page and one mail); turns ask_email on"}}
# 2.98.0 B (#1954): a questionnaire: own questions instead of subject / description, one per step, the client by e-mail
FQ_V1 = {"questions": {"type": "array", "maxItems": 30, "description": "2.98.0: own questions (empty = the classic form with subject / "
                       "description). A known id keeps the answers of earlier submissions mapped; the list replaces the old one",
                       "items": {"type": "object", "properties": {
                           "id": {"type": "string", "description": "Kept when given (6-16 a-z0-9), else made up"},
                           "kind": {"type": "string", "enum": ["short", "long", "choice", "multi", "date", "number", "file", "yesno"]},
                           "label": {"type": "string", "maxLength": 300}, "help": {"type": "string", "maxLength": 500},
                           "required": {"type": "boolean"},
                           "options": {"type": "array", "items": {"type": "string", "maxLength": 120}, "maxItems": 20,
                                       "description": "choice / multi: at least two"}}, "required": ["kind", "label"]}},
         "one_per_step": {"type": "boolean", "description": "2.98.0: the page shows one question per step (else all on one page)"},
         "client_match": {"type": "boolean", "description": "2.98.0: the sender's e-mail is matched to a client of the list's space; "
                          "the task names it (else 'client unknown')"},
         "client_new": {"type": "boolean", "description": "2.98.0: an unknown address becomes a new client in the list's space (default off)"}}


def pkgc_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q):
    C, W, F = "Clients", "Workload", "Forms"
    num = {"type": ["number", "null"]}
    stats = {"type": "object", "properties": {
        "seconds": {"type": "integer", "description": "Tracked time you can see (all of the client's lists you see)"},
        "rounded": {"type": "integer"}, "amount": {"type": "number", "description": "Rounded hours x the list's rate, else the client's"},
        "month": {"type": "string"}, "month_seconds": {"type": "integer"}, "month_amount": {"type": "number"},
        "estimate_min": {"type": "integer", "description": "Sum of the tasks' durations (estimate) in minutes"},
        "estimated": {"type": "integer"}, "open": {"type": "integer"}, "done": {"type": "integer"}}}
    kin = {"type": "object", "properties": {"id": {"type": "integer"}, "name": {"type": "string", "maxLength": 120}, "role": {"type": "string"},
                                            "email": {"type": "string"}, "phone": {"type": "string"}, "is_default": {"type": "boolean"},
                                            "contact_id": {"type": ["integer", "null"], "description": "2.59.0 (#1735): the linked address book contact (a book of the "
                                                           "client's organisation; null = not linked, missing in PATCH = unchanged; a new link needs the scope contacts)"}}}
    schemas["Client"] = {"type": "object", "properties": {
        "id": {"type": "integer"}, "name": {"type": "string"}, "icon": {"type": "string"}, "color": {"type": "string"},
        "contact": {"type": "string", "description": "Contact person (2.40.0: the name of the default one of contacts)"}, "email": {"type": "string"}, "phone": {"type": "string"},
        "contacts": {"type": "array", "items": kin, "description": "2.40.0 (#1380): the contact persons, the default first"},
        "address": {"type": "string"}, "note": {"type": "string"}, "rate": {**num, "description": "Hourly rate for lists without their own"},
        "budget_h": num, "budget_amount": num, "org_id": nul("integer"), "org_name": {"type": "string"}, "archived": {"type": "boolean"},
        "lists": {"type": "array", "items": {"type": "integer"}, "description": "Ids of the client's lists you see"},
        "can_delete": {"type": "boolean"}, "stats": stats, "updated_at": {"type": "string", "description": "2.269.0: send it back as expect_updated_at"},
        "budget": {"type": "object", "properties": {"pct_h": nul("integer"), "pct_amount": nul("integer"),
                                                    "level": {"type": "string", "enum": ["none", "ok", "warn", "over"]}}},
        "per_list": {"type": "array", "items": {"type": "object"}, "description": "GET /clients/{id}: estimate vs. actual per list"}}}
    cin = {"type": "object", "additionalProperties": False, "properties": {
        "name": {"type": "string", "maxLength": 80}, "icon": {"type": "string"}, "color": {"type": "string", "description": "#rrggbb"},
        "contact": {"type": "string"}, "email": {"type": "string"}, "phone": {"type": "string"}, "address": {"type": "string"},
        "contacts": {"type": "array", "items": kin, "description": "2.40.0 (#1380): the contact persons (with id = keep / change, "
                     "without = new; is_default marks the default, else the first). 2.269.0 (#3017): missing ones stay, "
                     "PATCH deletes only the ids in contacts_removed"},
        "note": {"type": "string"}, "rate": num, "budget_h": num, "budget_amount": num,
        "org_id": nul("integer", description="One of your organisations (default: your first)"), "archived": {"type": "boolean"}}}
    cup = {**cin, "properties": {**cin["properties"],  # 2.269.0 C (#3017)
                                 "contacts_removed": {"type": "array", "items": {"type": "integer"}, "description": "Ids of contact persons to delete"},
                                 "expect_updated_at": {"type": "string", "description": "The updated_at you read last: someone else saved "
                                                       "in between -> 409 with the current client under client (missing = no check)"}}}
    month = q("month", "YYYY-MM: the month of month_seconds / month_amount (default: this month)")
    paths["/clients"] = {
        "get": op("2.23.0 (module clients): the clients of your organisations with their lists, hours, amounts and budget", C,
                  ok({"type": "object", "properties": {"clients": {"type": "array", "items": ref("Client")}}}) | errs("409"),
                  [month, q("archived", "1 = with the archived ones")]),
        "post": op("Add a client (a person, not an agent or kid)", C, ok(ref("Client"), "Created", "201") | errs("400", "403", "409"),
                   body={**cin, "required": ["name"]}, scope="structure")}
    paths["/clients/{id}"] = {
        "get": op("A client with estimate vs. actual per list", C, ok(ref("Client")) | errs("404", "409"), [pid("id", "Client id"), month]),
        "patch": op("Change a client", C, ok(ref("Client")) | errs("400", "403", "404", "409"), [pid("id", "Client id")], body=cup, scope="structure"),
        "delete": op("Delete a client (its creator or an admin); its lists stay", C, ok({"type": "object"}) | errs("403", "404"),
                     [pid("id", "Client id")], scope="structure")}
    paths["/clients/bulk"] = {"post": op(  # 2.47.3 (#1733)
        "Several clients at once (up to 1000 ids; one you do not see -> 404, nothing changes). delete: a client used in quotations, "
        "invoices or framework contracts is archived instead; only its creator or an admin deletes (others: skipped). archive / unarchive; "
        "set: rate, budget_h, budget_amount, color (null clears), note_append; restore: items = the undo of an answer", C,
        ok({"type": "object", "properties": {"action": {"type": "string"}, "deleted": {"type": "integer"}, "archived": {"type": "integer"},
                                             "changed": {"type": "integer"}, "unchanged": {"type": "integer"}, "skipped": {"type": "integer"},
                                             "undo": {"type": "array", "items": {"type": "object"}}}}) | errs("400", "403", "404"),
        body={"type": "object", "additionalProperties": False, "required": ["action"], "properties": {
            "ids": {"type": "array", "items": {"type": "integer"}},
            "action": {"type": "string", "enum": ["delete", "archive", "unarchive", "set", "restore"]},
            "rate": num, "budget_h": num, "budget_amount": num, "color": {"type": "string", "description": "#rrggbb, empty = none"},
            "note_append": {"type": "string"}, "items": {"type": "array", "items": {"type": "object"}}}}, scope="structure")}
    cell = {"type": "object", "properties": {"minutes": {"type": "integer"}, "tasks": {"type": "integer"},
                                             "unestimated": {"type": "integer"}, "ids": {"type": "array", "items": {"type": "integer"}},
                                             "pct": nul("integer"), "level": {"type": "string", "enum": ["none", "ok", "warn", "over"]},
                                             # 2.50.0 (#1195): the week's capacity after absences / public holidays
                                             "capacity_h": {"type": "number"}, "absent_days": {"type": "number"}}}
    paths["/workload"] = {"get": op(
        "2.23.0 (module workload): planned hours per person of your organisation and week (open assigned tasks, weighed with their "
        "duration as the estimate; by planned start, else due, else start; overdue in this week) against their capacity. 2.86.0: "
        "an agent sees only the people who share a list with it", W,
        ok({"type": "object", "properties": {
            "weeks": {"type": "array", "items": {"type": "object", "properties": {"start": {"type": "string"}, "end": {"type": "string"}}}},
            "people": {"type": "array", "items": {"type": "object", "properties": {
                "id": {"type": "integer"}, "display_name": {"type": "string"}, "capacity_h": {"type": "number"},
                "weeks": {"type": "array", "items": cell}, "nodate": cell}}},
            "org_id": nul("integer"), "orgs": {"type": "array", "items": {"type": "object"}}}}) | errs("400", "404", "409"),
        [q("start", "A day of the first week (YYYY-MM-DD, default today)"), q("weeks", "1-12 (4)", {"type": "integer"}),
         q("org", "Organisation id (default: your first)", {"type": "integer"})])}
    paths["/tasks/{id}/approval"] = {"post": op(
        "2.23.0: approvals. request (approver_id: a person of the list; assigns the task to them) / cancel; the approver decides with "
        "approve (completes the task), changes (back to whoever asked) or reject (won't do). Agents can request and cancel, never decide.",
        "Tasks", ok(ref("Task")) | errs("400", "403", "404"), [pid()],
        body={"type": "object", "required": ["action"], "additionalProperties": False, "properties": {
            "action": {"type": "string", "enum": list(APPROVAL_ACTIONS)}, "approver_id": {"type": "integer"},
            "note": {"type": "string", "maxLength": 2000}}}, scope="tasks:write")}
    schemas["Form"] = {"type": "object", "properties": {
        "id": {"type": "integer"}, "list_id": {"type": "integer"}, "title": {"type": "string"}, "intro": {"type": "string"},
        "access": {"type": "string", "enum": list(FORM_ACCESS), "description": "org = signed-in people of the owner's organisations; public = anyone with the link"},
        "section_id": nul("integer"), "ask_email": {"type": "boolean"}, "enabled": {"type": "boolean"}, "count": {"type": "integer"},
        "last_at": nul("string"), "created_at": {"type": "string"}, "url": {"type": "string", "description": "The form's link"},
        "live": {"type": "boolean", "description": "Enabled and allowed (public forms need the switch Public links)"}, **FRM_V1, **FQ_V1}}
    fin = {"type": "object", "additionalProperties": False, "properties": {
        "title": {"type": "string"}, "intro": {"type": "string"}, "access": {"type": "string", "enum": list(FORM_ACCESS)},
        "section_id": nul("integer"), "ask_email": {"type": "boolean"}, **FRM_V1, **FQ_V1}}
    paths["/lists/{id}/forms"] = {
        "get": op("2.23.0 (module forms): the forms of a list (owner / list admins)", F,
                  ok({"type": "object", "properties": {"forms": {"type": "array", "items": ref("Form")}, "public_links": {"type": "boolean"}}})
                  | errs("403", "404", "409"), [pid("id", "List id")]),
        "post": op("Create a form: a link whose page creates a task in the list (subject, description, name, e-mail)", F,
                   ok(ref("Form"), "Created", "201") | errs("400", "403", "404", "409"), [pid("id", "List id")],
                   body={**fin, "required": ["title"]}, scope="structure")}
    paths["/forms/{id}"] = {
        "patch": op("Change a form (regenerate: true = a new link, the old one stops)", F, ok(ref("Form")) | errs("400", "403", "404", "409"),
                    [pid("id", "Form id")], body={**fin, "properties": {**fin["properties"], "enabled": {"type": "boolean"},
                                                                        "regenerate": {"type": "boolean"}}}, scope="structure"),
        "delete": op("Delete a form", F, ok({"type": "object"}) | errs("403", "404"), [pid("id", "Form id")], scope="structure")}
    return APPROVAL_STATES
