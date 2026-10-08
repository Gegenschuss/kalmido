"""The OpenAPI 3.1 document of /api/v1 (served at /api/v1/openapi.json, built once)."""

from ..core.config import API_PREFIX, APP_NAME
from ..core.access import ROLES
from ..lists.lists import COL_DOC, COL_MAX, LIST_KIND_ALIASES, LIST_KINDS, LIST_NAME_MAX, LIST_VIEWS
from ..tasks.validation import NAG_VALUES, PRIORITIES, TICKET_TYPES
from ..tasks.tasks import WAIT_NOTE_MAX
from ..tasks.roadmap import ROADMAP_MAX_DAYS, SHIFT_MAX_DAYS, SHIFT_MAX_TASKS
from ..collab.comments import MAX_COMMENT
from ..collab.news import BELL_CUSTOM_ROWS, BELL_MODES, NOTIF_ROWS
from ..personal.timetrack import TIME_SOURCES
from ..lists.templates import PTYPES
from ..lists.projects import LIST_STATUSES
from ..calendars.caldav import APPPW_MAX
from ..integrations.importers import IMPORT_MAX_MB, IMPORT_MAX_TASKS, IMPORT_SOURCES, IMPORT_UNDO_HOURS
from ..api.v1 import (
    _SPEC, API_PAGE_DEFAULT, API_PAGE_MAX, API_SCOPES, API_VERSION, PRIO_VALUES, STATUS_NAMES, V1_CODES, V1_TASK_IN,
)
from ..tasks.dayplan import dayplan_spec


def groups_spec(paths, schemas, op, ok, errs, ref, pid, nul, page):
    G = "Groups"
    schemas["Group"] = {"type": "object", "properties": {
        "id": {"type": "integer"}, "name": {"type": "string"},
        "synced": {"type": "boolean", "description": "Members follow a group claim of the sign-in provider (OIDC)"},
        "mine": {"type": "boolean", "description": "The token's user is a member"},
        "members": {"type": "array", "items": {"type": "object", "properties": {"user_id": {"type": "integer"}, "name": {"type": "string"}}}}}}
    schemas["GroupPage"] = page("Group")
    schemas["ListGroup"] = {"type": "object", "properties": {
        "group_id": {"type": "integer"}, "name": {"type": "string"}, "role": {"type": "string", "enum": list(ROLES)},
        "via": {"type": "string", "description": "list = shared directly; otherwise the owner's folder that is shared"}}}
    schemas["ListGroupPage"] = page("ListGroup")
    gp = {"name": "group_id", "in": "path", "required": True, "description": "Group id", "schema": {"type": "integer"}}
    paths["/groups"] = {"get": op("Groups (admins create them; every person sees them with their members)", G, ok(ref("GroupPage")) | errs())}
    paths["/groups/{id}"] = {"get": op("One group", G, ok(ref("Group")) | errs("404"), [pid(desc="Group id")])}
    paths["/lists/{id}/groups"] = {"get": op("The groups a list is shared with (directly or through a folder)", G,
                                             ok(ref("ListGroupPage")) | errs("404"), [pid(desc="List id")])}
    paths["/lists/{id}/groups/{group_id}"] = {
        "put": op("Share a list with a group (or change its role); owner or list admin", G, ok(ref("ListGroupPage")) | errs("400", "403", "404"),
                  [pid(desc="List id"), gp], body={"type": "object", "properties": {"role": {"type": "string", "enum": list(ROLES)}}},
                  scope="write", desc="Every member of the group gets access; members who join later too. A person's role is the "
                                      "higher of their own and the one via groups."),
        "delete": op("Stop sharing a list with a group", G, ok({"type": "object"}) | errs("403", "404"), [pid(desc="List id"), gp], scope="write")}
    paths["/tasks/{id}/take"] = {"post": op("Take a task assigned to one of your groups", "Tasks", ok(ref("Task")) | errs("403", "404", "409"),
                                            [pid()], scope="write", desc="The task becomes yours (assignee_id) and is no longer assigned to the group.")}


def openapi_spec():
    from ..integrations.webhooks import WH_EVENTS
    from ..agents.usage import agent_spec, AUDIT_STATUS
    from ..integrations.errorreports import git_spec
    from ..api.projects import overview_spec
    from ..api.scopes import api479_spec, scope_refine
    from ..collab.notes import notes_spec
    from ..collab.teamchat import team_spec
    from ..family.family import FAM_LIST_KINDS, STARS_MAX
    from ..family.v1 import family_spec
    from ..events.v1 import events_spec
    from ..contacts.v1 import contacts_spec
    from ..life.v1 import life_spec
    from ..team.v1 import pkgc_spec
    from ..admin.hosting import hosting_spec
    if "s" in _SPEC:
        return _SPEC["s"]

    def ref(n):
        return {"$ref": f"#/components/schemas/{n}"}

    def nul(t, **k):
        return {"type": [t, "null"], **k}

    def page(n):
        return {"type": "object", "required": ["data", "next_cursor"],
                "properties": {"data": {"type": "array", "items": ref(n)}, "next_cursor": nul("string", description="Pass as ?cursor= for the next page; null = last page")}}

    def ok(schema, desc="OK", code="200"):
        return {code: {"description": desc, "content": {"application/json": {"schema": schema}}}}

    def errs(*codes):
        text = {"400": "Invalid input", "401": "Missing, invalid or expired token", "403": "Not allowed (scope, role or a switched-off module)",
                "404": "Not found or not visible to the token's user", "409": "Conflict", "410": "The file is damaged or missing on the server", "413": "Too large",
                "429": "Rate limit reached (see Retry-After)"}
        return {c: {"description": text[c], "content": {"application/json": {"schema": ref("Error")}}} for c in ("401", "429") + codes}

    def op(summary, tag, responses, params=(), body=None, desc=None, scope="read"):
        o = {"summary": summary, "tags": [tag], "responses": responses, "x-kalmido-scope": scope}
        if desc:
            o["description"] = desc
        if params:
            o["parameters"] = list(params)
        if body:
            o["requestBody"] = {"required": True, "content": {"application/json": {"schema": body}}}
        return o

    def q(name, desc, schema=None):
        return {"name": name, "in": "query", "required": False, "description": desc, "schema": schema or {"type": "string"}}

    def pid(name="id", desc="Task id"):
        return {"name": name, "in": "path", "required": True, "description": desc, "schema": {"type": "integer"}}
    date_s = {"type": "string", "format": "date"}
    limit, cursor = q("limit", f"Page size (1-{API_PAGE_MAX}, default {API_PAGE_DEFAULT})", {"type": "integer", "minimum": 1, "maximum": API_PAGE_MAX}), \
        q("cursor", "next_cursor of the previous page")
    prio = {"type": "string", "enum": list(PRIO_VALUES)}
    task_props = {
        "id": {"type": "integer"}, "list_id": {"type": "integer"}, "section_id": nul("integer"), "parent_id": nul("integer"),
        "title": {"type": "string"}, "notes": {"type": "string", "description": "Markdown"}, "priority": prio,
        "status": {"type": "string", "enum": list(STATUS_NAMES.values())}, "due": nul("string", format="date"),
        "due_time": nul("string", pattern="^[0-2][0-9]:[0-5][0-9]$", description="HH:MM, local time of the server; null = all day"),
        "start": nul("string", format="date", description="First day (timeline)"), "duration": nul("integer", description="Minutes"),
        "reminders": {"type": "array", "items": {"type": "integer"}, "description": "Minutes before the due time"},
        "repeat": {"type": "string", "description": "RRULE body (FREQ=WEEKLY;BYDAY=MO) or empty"},
        "repeat_from": {"type": "string", "enum": ["due", "done"]}, "url": nul("string", format="uri"),
        "tags": {"type": "array", "items": {"type": "string"}, "description": "The token user's own tags"},
        "pinned": {"type": "boolean"}, "assignee_id": nul("integer"), "created_by": nul("integer"), "completed_by": nul("integer"),
        "assignee_group_id": nul("integer", description="2.10.0: assigned to a group (whoever has time takes it, POST /tasks/{id}/take); "
                                 "setting it clears assignee_id and the other way round; the list must be shared with the group"),
        "created_at": {"type": "string", "format": "date-time"}, "updated_at": {"type": "string", "format": "date-time"},
        "completed_at": nul("string", format="date-time"), "deleted": {"type": "boolean"},
        "fields": {"type": "object", "additionalProperties": {"type": "string"}, "description": "Custom field values by field id"},
        "waiting": {"oneOf": [{"type": "null"}, ref("Waiting")], "description": "Waiting on someone outside (a client, an office, a delivery) with a follow-up day (2.1.0; called waiting on external before 2.25.0); null = not waiting"},
        "type": nul("string", enum=[*TICKET_TYPES, None], description="Ticket type (2.4.0); a new bug / feature in a list with ticket "
                    "types on gets the list's note template when its notes are empty"),
        "deadline": {"type": "boolean", "description": "2.7.0: the due date is a deadline (countdown, highlighted from the first reminder on)"},
        "deadline_in_today": {"type": "boolean", "description": "2.7.0: a deadline that shows on Today from its first reminder on "
                              "(setting it true also sets deadline)"},
        "nag": {"type": "string", "enum": list(NAG_VALUES), "description": "2.7.0: repeat the reminder until done: 5 / 10 / 15 / 30 / 60 "
                "minutes or 1d (daily), from the first reminder on; off = never; empty = the list's default"},
        "plan_start": nul("string", pattern="^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-2][0-9]:[0-5][0-9]$",
                          description="2.11.0: planned start YYYY-MM-DDTHH:MM (local; set by the day plan, see /dayplan); "
                                      "independent of due / deadline, which planning never changes; null = not planned"),
        "milestone": {"type": "boolean", "description": "2.18.0: the task is a milestone (a diamond with a date, checkable, top level, "
                      "no subtasks); see GET /tasks/{id}/milestone for its progress, burndown and release notes"},
        "milestone_id": nul("integer", description="2.18.0: the milestone (a task of the same list with milestone true) this task "
                            "belongs to, e.g. the release it ships in; cleared when the task moves to another list or the milestone "
                            "is deleted / no milestone any more"),
        # 2.19.0 (#653): the module Family
        "family": {"type": ["object", "null"], "description": "2.19.0: a birthday / anniversary {kind: birthday | anniversary, name, year?, lead?} "
                   "(a yearly task; age = due year - year) or a household deadline {kind: deadline, type, who, expires, notice (months), lead}; "
                   "null = none. Easier: POST /family/occasions and /family/deadlines"},
        "rotation": {"type": ["object", "null"], "description": "2.19.0: household rotation {who: [user ids of people sharing the list, "
                     "at least 2], mode: done (the next person after each completion) | week (every Monday), i (whose turn, index; "
                     "optional)}; sets the assignee; null = none"},
        "stars": nul("integer", minimum=0, maximum=STARS_MAX, description="2.19.0: stars a kid account gets for completing it (null = 1)"),
        "people": {"type": "array", "items": {"type": "integer"}, "description": "2.19.0: who comes along (user ids of people sharing "
                   "the list): they see the task, also as participants, and get its reminders"},
        "approval": nul("string", enum=["pending", "approved", "changes", "rejected", None], description="2.23.0: the task waits for / "
                        "had an approval (POST /tasks/{id}/approval); null = no approval"),
        "approver_id": nul("integer", description="2.23.0: who decides on the approval (a person of the list)")}
    task_in = {k: v for k, v in task_props.items() if k in V1_TASK_IN}
    task_in["priority"] = {"oneOf": [prio, {"type": "integer", "enum": list(PRIORITIES)}]}
    task_in["reminders"] = {"oneOf": [{"type": "array", "items": {"type": "integer"}}, {"type": "string"}]}
    for k in ("list_id", "section_id", "parent_id", "assignee_id", "assignee_group_id"):
        task_in[k] = nul("integer")
    task_in["content"] = {"type": "string", "description": "Alias of notes (the web API's name, 2.2.1); not together with a different notes"}
    schemas = {
        "Error": {"type": "object", "required": ["error"], "properties": {"error": {"type": "object", "required": ["code", "message"], "properties": {
            "code": {"type": "string", "enum": sorted(set(V1_CODES.values()) | {"unknown_field"})}, "message": {"type": "string"},
            "fields": {"type": "array", "items": {"type": "string"},
                       "description": "code unknown_field (2.2.1): the body fields this endpoint does not know (nothing was changed)"}}}}},
        "Task": {"type": "object", "properties": {**task_props, "blocked": {"type": "boolean", "description": "Blocked by an open task (dependencies, shown as Blocked by)"},
                                                  "comment_count": {"type": "integer"},
                                                  "context": {"type": "boolean", "description": "Participant view: the parent of one of your "
                                                              "subtasks, read-only, without notes, link, files and comments"},
                                                  "attachments": {"type": "array", "items": ref("Attachment")}}},
        "TaskCompleted": {"allOf": [ref("Task"), {"type": "object", "properties": {"next_due": nul("string", format="date", description="Recurring: the next date the task moved to")}}]},
        "TaskInput": {"type": "object", "additionalProperties": False, "properties": task_in},
        "TaskCreate": {"allOf": [ref("TaskInput"), {"type": "object", "required": ["title"]}]},
        "TaskPage": page("Task"),
        "AuditEntry": {"type": "object", "properties": {
            "id": {"type": "integer"}, "at": {"type": "string", "format": "date-time"}, "agent_id": {"type": "integer"},
            "agent_name": {"type": "string"}, "method": {"type": "string"},
            "route": {"type": "string", "description": "Route template, e.g. /api/v1/tasks/{tid} (no query values, no body)"},
            "status": {"type": "integer"}, "task_id": nul("integer"), "list_id": nul("integer"), "ms": {"type": "integer"},
            "denied": {"type": "boolean", "description": "401, 403 or 429"}}},
        "AuditPage": page("AuditEntry"),
        "Attachment": {"type": "object", "properties": {"id": {"type": "integer"}, "name": {"type": "string"}, "mime": {"type": "string"}, "size": {"type": "integer"}}},
        "AttachmentInfo": {"type": "object", "properties": {  # 2.13.1 (#465)
            "id": {"type": "integer"}, "task_id": {"type": "integer"}, "comment_id": nul("integer", description="null = a file of the task itself"),
            "name": {"type": "string"}, "mime": {"type": "string"}, "size": {"type": "integer"}, "created_at": {"type": "string"},
            "url": {"type": "string", "description": "/api/v1/attachments/{id}"}}},
        "Progress": {"type": "object", "properties": {"done": {"type": "integer"}, "total": {"type": "integer"}, "overdue": {"type": "integer"},
                                                      "next_due": nul("string", format="date")}},
        "List": {"type": "object", "properties": {
            "id": {"type": "integer"}, "name": {"type": "string"}, "color": {"type": "string"},
            "folder": {"type": "string", "description": "Your folder path, at most 2 levels: \"Clients/Company X\" (2.4.0); empty = none"},
            "tickets": {"type": "boolean", "description": "Ticket types bug / feature / task on (2.4.0)"},
            "is_inbox": {"type": "boolean"}, "archived": {"type": "boolean"},
            "done_at_bottom": {"type": "boolean", "description": "2.7.2: \"Show completed at the bottom\": completed tasks stay visible below the open ones and come back with one tap"},
            "checklist": {"type": "boolean", "deprecated": True, "description": "Deprecated (2.7.2): same as done_at_bottom"},
            "kind": {"type": "string", "enum": list(LIST_KINDS), "description": "List type; project lists have time tracking, dependencies, custom fields and progress (2.7.2: the type checklist is gone, see done_at_bottom)"},
            "view": {"type": "string", "enum": list(LIST_VIEWS)}, "role": {"type": "string", "enum": ["owner", "admin", "edit", "participant", "view"]},
            "owner_id": {"type": "integer"}, "owner_name": {"type": "string"}, "shared": {"type": "boolean"},
            "status": nul("string", enum=[*LIST_STATUSES, None]), "progress": ref("Progress"), "created_at": {"type": "string", "format": "date-time"},
            "nag": {"type": "string", "enum": [x for x in NAG_VALUES if x != "off"], "description": "2.7.0: default nag interval of the list's tasks; empty = none"},
            "day_hours": nul("number", description="2.7.0: hours of a working day / shift for this list's time sums; null = the server's value"),
            "columns": {"type": ["array", "null"], "items": {"type": "string"}, "description": COL_DOC},
            "agent_members": {"type": "boolean", "description": "2.26.0 (#928): members may see and use the list's agents (default false)"},
            "agent_peers": {"type": "boolean", "description": "2.26.0 (#928): agents may address each other in this list (default false)"},
            "family": nul("string", enum=[*[x for x in FAM_LIST_KINDS if x], None], description="2.19.0: what the list is for in the Family module: "
                          "shopping (sections = shop areas, a new item goes to its area of last time, a shopping mode in the app), meals "
                          "(the meal plan: due = the day, notes = ingredients), birthdays, household, packing; null = an ordinary list"),
            "life": nul("string", enum=["contracts", "home", "health", "travel", "reading", None], description="2.22.0: what the list is for in "
                        "Home & life (health lists are private: never visible to agents, tokens need the scope private); null = none"),
            "trip": {"type": ["object", "null"], "description": "2.22.0: a trip list's {from, to, where?}", "properties": {
                "from": {"type": "string", "format": "date"}, "to": {"type": "string", "format": "date"}, "where": {"type": "string"}}},
            "client_id": nul("integer", description="2.23.0: the client the list belongs to (GET /clients); null = none")}},
        "ListDetail": {"allOf": [ref("List"), {"type": "object", "properties": {"sections": {"type": "array", "items": ref("Section")},
            "fields": {"type": "array", "description": "2.14.0: the list's custom fields (ids for the columns f:<id>)",
                       "items": {"type": "object", "properties": {"id": {"type": "integer"}, "name": {"type": "string"}, "type": {"type": "string"}}}}}}]},
        "ListInput": {"type": "object", "additionalProperties": False, "required": ["name"], "properties": {
            "name": {"type": "string"}, "color": {"type": "string", "description": "#rgb / #rrggbb or empty"},
            "folder": {"type": "string", "description": "Folder path, at most 2 levels (\"Clients/Company X\"); deeper: 400"},
            "done_at_bottom": {"type": "boolean", "description": "2.7.2: show completed tasks at the bottom"},
            "checklist": {"type": "boolean", "deprecated": True, "description": "Deprecated (2.7.2): same as done_at_bottom"},
            "kind": {"type": "string", "enum": [*LIST_KINDS, *LIST_KIND_ALIASES], "description": "list | project; \"checklist\" is a deprecated alias of list + done_at_bottom"},
            "tickets": {"type": "boolean", "description": "Ticket types on (2.4.0)"},
            "project_type": {"type": "string", "enum": list(PTYPES), "description": "2.4.0: a project of a built-in type (sections, "
                             "custom fields, view, ticket types; switches the modules it needs on for you); kind / checklist / tickets are ignored"},
            "sections": {"type": "boolean", "default": False, "description": "2.27.0: with project_type: create the type's standard sections "
                         "(e.g. Backlog … Done); without it the project starts without sections"},
            "family": nul("string", enum=[*[x for x in FAM_LIST_KINDS if x], None], description="2.19.0: what the list is for in the Family module: "
                          "shopping (sections = shop areas, a new item goes to its area of last time, a shopping mode in the app), meals "
                          "(the meal plan: due = the day, notes = ingredients), birthdays, household, packing; null = an ordinary list"),
            "nag": {"type": "string", "enum": list(NAG_VALUES), "description": "2.7.0: default nag interval of the list's tasks (owner)"},
            "day_hours": nul("number", minimum=1, maximum=24, description="2.7.0: hours per day / shift (owner); null = the server's value"),
            "org_id": nul("integer", description="2.28.0: the workspace: an organisation you belong to, null = private (default: the folder's, else private)")}},
        "ListPatch": {"type": "object", "additionalProperties": False, "properties": {
            "org_id": nul("integer", description="2.28.0: the list's workspace (the owner; 409 while people / agents in it do not fit, for family / Home & life lists and the inbox)"),
            "client_id": nul("integer", description="2.23.0: the client of the list (owner / list admins; a client you see); null = none"),
            "life": nul("string", enum=["contracts", "home", "health", "travel", "reading", None], description="2.22.0: what the list is for in "
                        "Home & life (health lists are private: never visible to agents, tokens need the scope private); null = none"),
            "trip": {"type": ["object", "null"], "description": "2.22.0: a trip list's {from, to, where?}", "properties": {
                "from": {"type": "string", "format": "date"}, "to": {"type": "string", "format": "date"}, "where": {"type": "string"}}},
            "family": nul("string", enum=[*[x for x in FAM_LIST_KINDS if x], None], description="2.19.0: what the list is for in the Family module: "
                          "shopping (sections = shop areas, a new item goes to its area of last time, a shopping mode in the app), meals "
                          "(the meal plan: due = the day, notes = ingredients), birthdays, household, packing; null = an ordinary list"),
            "name": {"type": "string"}, "color": {"type": "string"}, "folder": {"type": "string"},
            "view": {"type": "string", "enum": list(LIST_VIEWS)},
            "kind": {"type": "string", "enum": [*LIST_KINDS, *LIST_KIND_ALIASES], "description": "list | project; \"checklist\" is a deprecated alias of list + done_at_bottom"},
            "done_at_bottom": {"type": "boolean", "description": "2.7.2: show completed tasks at the bottom (owner)"},
            "checklist": {"type": "boolean", "deprecated": True, "description": "Deprecated (2.7.2): same as done_at_bottom"},
            "nag": {"type": "string", "enum": list(NAG_VALUES), "description": "Default nag interval of the list's tasks (owner); off / empty = none"},
            "day_hours": nul("number", minimum=1, maximum=24, description="Hours per day / shift (owner); null = the server's value"),
            "listen_agent_ids": {"type": "array", "items": {"type": "integer"},
                                 "description": "2.13.1 (#471): agents of the list that get a 'comment' event for EVERY comment of a person "
                                                "in this list (only on tasks they can see); [] = none. Owner / list admins, never an agent token"},
            "agent_members": {"type": "boolean", "description": "2.26.0 (#928): members may see and use the list's agents (chat, "
                              "mention, assign, comment to them). Off (default): only the owner, list admins and instance admins can; "
                              "members still see what the agents do. Owner / list admins, never an agent token"},
            "agent_peers": {"type": "boolean", "description": "2.26.0 (#928): agents may address each other in this list (an agent's "
                            "mention / assignment / comment reaches another agent as an event). Off (default): no events between agents. "
                            "Owner / list admins, never an agent token"},
            "columns": {"type": ["array", "null"], "items": {"type": "string"}, "maxItems": COL_MAX,
                        "description": COL_DOC + " Owner / list admins; null = back to the default."},
            "project_type": {"type": ["string", "null"], "enum": [*PTYPES, "", None],
                             "description": "2.18.0 (#408): the project type (owner / list admins); null / \"\" = none. Switches on what the "
                                            "type needs (type project, ticket types for software, the type's view while the list has no "
                                            "tasks, its modules for you) and never deletes anything; sections are not added"}}},
        "ListPage": page("ListDetail"),  # 2.0.8: the list page carries each list's sections too
        "Roadmap": {"type": "object", "properties": {
            "from": {"type": "string", "format": "date"}, "to": {"type": "string", "format": "date"}, "projects_only": {"type": "boolean"},
            "folders": {"type": "array", "items": {"type": "string"}, "description": "Folder order (your sidebar order)"},
            "groups": {"type": "array", "items": ref("RoadmapGroup"), "description": "One per list: inbox, lists without a folder, then folder by folder"},
            "deps": {"type": "array", "items": {"type": "object", "properties": {"task_id": {"type": "integer"}, "blocker_id": {"type": "integer"}}},
                     "description": "task_id waits on blocker_id (for the returned tasks; blockers you can see)"}}},
        "RoadmapGroup": {"type": "object", "properties": {
            "list": ref("List"), "folder": {"type": "string"}, "can_edit": {"type": "boolean"},
            "span": {"oneOf": [{"type": "null"}, {"type": "object", "properties": {"start": date_s, "end": date_s}}],
                     "description": "Earliest start (or due without a start) to the latest due of ALL open dated tasks of the list; null = none"},
            "open_dated": {"type": "integer"}, "undated": {"type": "integer", "description": "Open tasks without a date (not in tasks)"},
            "tasks": {"type": "array", "items": ref("RoadmapTask"), "description": "Dated tasks overlapping from..to, by start"}}},
        "RoadmapTask": {"type": "object", "properties": {
            "id": {"type": "integer"}, "parent_id": nul("integer"), "title": {"type": "string"}, "start": nul("string", format="date"),
            "due": {"type": "string", "format": "date"}, "status": {"type": "string", "enum": list(STATUS_NAMES.values())}, "priority": prio,
            "assignee_id": nul("integer")}},
        "OwnerInput": {"type": "object", "additionalProperties": False, "required": ["user_id"], "properties": {
            "user_id": {"type": "integer", "description": "The new owner (an active person)"}}},
        "OwnerResult": {"type": "object", "properties": {
            "ok": {"type": "boolean"}, "id": {"type": "integer"}, "owner_id": {"type": "integer"}, "owner_name": {"type": "string"},
            "previous_owner_id": {"type": "integer"}}},
        "ShiftInput": {"type": "object", "additionalProperties": False, "required": ["days"], "properties": {
            "days": {"type": "integer", "minimum": -SHIFT_MAX_DAYS, "maximum": SHIFT_MAX_DAYS, "description": "Negative = earlier; not 0"}}},
        "ShiftResult": {"type": "object", "properties": {
            "ok": {"type": "boolean"}, "count": {"type": "integer"}, "days": {"type": "integer"},
            "moved": {"type": "array", "items": ref("Moved"), "description": "The list's tasks"},
            "shifted": {"type": "array", "items": ref("Moved"), "description": "Dependent tasks in other lists moved along"}}},
        "Moved": {"type": "object", "properties": {
            "id": {"type": "integer"}, "title": {"type": "string"}, "start": nul("string", format="date"), "due": {"type": "string", "format": "date"},
            "prev_start": nul("string", format="date"), "prev_due": {"type": "string", "format": "date"}}},
        "Section": {"type": "object", "properties": {"id": {"type": "integer"}, "name": {"type": "string"}, "sort": {"type": "number"}}},
        "Tag": {"type": "object", "properties": {"name": {"type": "string"}, "tasks": {"type": "integer"}, "open": {"type": "integer"}}},
        "TagPage": page("Tag"),
        "Comment": {"type": "object", "properties": {
            "id": {"type": "integer"}, "task_id": {"type": "integer"},
            "author": {"type": "object", "properties": {"id": nul("integer"), "name": {"type": "string"}}},
            "body": {"type": "string", "description": "Markdown; mentions as <@user_id>"}, "text": {"type": "string", "description": "Plain text, mentions as @name"},
            "mentions": {"type": "array", "items": {"type": "integer"}}, "created_at": {"type": "string", "format": "date-time"},
            "edited_at": nul("string", format="date-time"), "attachments": {"type": "array", "items": ref("Attachment")}}},
        "CommentInput": {"type": "object", "additionalProperties": False, "required": ["body"], "properties": {"body": {"type": "string", "maxLength": MAX_COMMENT}}},
        "CommentPage": page("Comment"),
        "TimeEntry": {"type": "object", "properties": {
            "id": {"type": "integer"}, "user_id": {"type": "integer"}, "user_name": {"type": "string"}, "task_id": nul("integer"),
            "list_id": nul("integer"), "title": {"type": "string"}, "start": {"type": "string", "format": "date-time"},
            "end": nul("string", format="date-time"), "seconds": {"type": "integer"}, "rounded": {"type": "integer"},
            "note": {"type": "string"}, "source": {"type": "string", "enum": list(TIME_SOURCES)}, "running": {"type": "boolean"}}},
        "TimeEntryInput": {"type": "object", "additionalProperties": False, "required": ["start"], "properties": {
            "task_id": {"type": "integer"}, "list_id": {"type": "integer"}, "start": {"type": "string", "description": "ISO date-time (local time if no offset)"},
            "end": {"type": "string"}, "minutes": {"type": "number"}, "note": {"type": "string", "maxLength": 500}}},
        "TimeEntryPage": page("TimeEntry"),
        "Habit": {"type": "object", "properties": {
            "id": {"type": "integer"}, "name": {"type": "string"}, "color": {"type": "string"}, "goal": {"type": "integer"},
            "days": {"type": "string", "description": "Weekdays 1 (Mon) - 7 (Sun)"}, "per_week": {"type": "integer"}, "archived": {"type": "boolean"},
            "today": {"type": "integer"}, "last_30_days": {"type": "object", "additionalProperties": {"type": "integer"}}}},
        "HabitCheckedIn": {"allOf": [ref("Habit"), {"type": "object", "properties": {"date": date_s, "count": {"type": "integer"}}}]},
        "CheckinInput": {"type": "object", "additionalProperties": False, "properties": {
            "date": date_s, "count": {"type": "integer", "minimum": 0, "maximum": 1000, "description": "Absolute count for the day; default: one more"},
            "note": {"type": "string", "maxLength": 500}}},
        "HabitPage": page("Habit"),
        "ImportInput": {"type": "object", "required": ["file"], "properties": {
            "file": {"type": "string", "format": "binary", "description": f"The export file (at most {IMPORT_MAX_MB} MB, {IMPORT_MAX_TASKS} tasks)"},
            "dry_run": {"type": "boolean", "description": "true = preview only: runs the import and rolls it back"},
            "target": {"type": "string", "description": "new (default: one list per source list; an own list with the same name is reused) or the id of a list you can edit"},
            "mode": {"type": "string", "enum": ["sections", "lists"], "description": "Trello: one list with the Trello lists as sections (default) or one list per Trello list"},
            "archived": {"type": "string", "enum": ["skip", "done"], "description": "Trello: archived cards / lists skipped (default) or imported as done"},
            "completed": {"type": "string", "enum": ["import", "skip"], "description": "Completed tasks imported as done (default) or skipped"},
            "list_name": {"type": "string", "maxLength": LIST_NAME_MAX, "description": "Name of the new list (only when the file has one list)"},
            "priority_scale": {"type": "string", "enum": ["auto", "1", "4"], "description": "Todoist CSV: which PRIORITY value is p1 (auto = detected)"}}},
        "ImportReport": {"type": "object", "properties": {
            "source": {"type": "string"}, "dry_run": {"type": "boolean"}, "import_id": nul("integer", description="For the undo; null for a dry run"),
            "undo_until": nul("string", format="date-time"),
            "created": {"type": "object", "properties": {k: {"type": "integer"} for k in ("tasks", "subtasks", "done", "skipped", "lists", "sections", "assigned")}},
            "skipped": {"type": "integer", "description": "Already imported earlier (same source ids)"},
            "lists": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "list_id": {"type": "integer"}, "existing": {"type": "boolean"},
                                                                                "tasks": {"type": "integer"}, "skipped": {"type": "integer"}, "sections": {"type": "integer"}}}},
            "samples": {"type": "array", "items": {"type": "object"}},
            "warnings": {"type": "array", "items": {"type": "object", "properties": {"text": {"type": "string"}, "count": {"type": "integer"},
                                                                                   "examples": {"type": "array", "items": {"type": "string"}}}}}}},
        "ImportUndone": {"type": "object", "properties": {k: {"type": "integer"} for k in ("tasks", "lists", "sections", "kept_lists", "kept_tasks")}},
        "AppPassword": {"type": "object", "properties": {
            "id": {"type": "integer"}, "name": {"type": "string"}, "created_at": {"type": "string", "format": "date-time"},
            "last_used_at": nul("string", format="date-time"), "last_client": {"type": "string", "description": "User agent of the last use"}}},
        "CalDAV": {"type": "object", "properties": {
            "enabled": {"type": "boolean"}, "url": {"type": "string", "description": "CalDAV base address (/dav/)"},
            "server": {"type": "string", "description": "Host name (iOS / macOS: discovery via /.well-known/caldav)"},
            "username": {"type": "string"}, "principal": {"type": "string"}, "home": {"type": "string"},
            "done_days": {"type": "integer", "description": "Completed tasks stay in the calendar apps this many days"}}},
        "Me": {"type": "object", "properties": {
            "id": {"type": "integer"}, "username": {"type": "string"}, "display_name": {"type": "string"}, "is_admin": {"type": "boolean"},
            "token": {"type": "object", "properties": {"id": {"type": "integer"}, "name": {"type": "string"},
                                                       "scopes": {"type": "array", "items": {"type": "string", "enum": list(API_SCOPES)}},
                                                       "expires_at": nul("string", format="date-time")}},
            "features": {"type": "object", "description": "Modules switched on for the user. Only collaboration, time tracking and comments (writing) limit the API; "
                                                        "dependencies and custom fields are hidden in the app when off, the API keeps them",
                         "properties": {"collaboration": {"type": "boolean"}, "time_tracking": {"type": "boolean"}, "comments": {"type": "boolean"},
                                        "dependencies": {"type": "boolean"}, "custom_fields": {"type": "boolean"}}},
            "api_version": {"type": "string"}, "rate_limit_per_minute": {"type": "integer"}, "notifications": ref("Notifications")}},
        "Waiting": {"type": "object", "properties": {
            "note": {"type": "string", "description": "Who / what the task waits for"}, "until": nul("string", format="date", description="Follow-up day"),
            "since": {"type": "string", "format": "date-time"}, "by": nul("integer", description="Who set it")}},
        "WaitingInput": {"type": "object", "additionalProperties": False, "properties": {
            "note": {"type": "string", "maxLength": WAIT_NOTE_MAX}, "until": nul("string", format="date", description="Follow-up day (reminder, News, agent event followup_due)")}},
        "Notifications": {"type": "object", "properties": {
            "events": {"type": "object", "description": "Per event: news (null = the event has no News) and push. Events: " + ", ".join(NOTIF_ROWS),
                       "additionalProperties": {"type": "object", "properties": {"news": nul("boolean"), "push": {"type": "boolean"}}}},
            "lists": {"type": "object", "description": "List id -> bell (lists on default are left out)",
                      "additionalProperties": {"type": "string", "enum": list(BELL_MODES)}},
            "custom": {"type": "object", "description": "List id -> the own event choice of lists on custom (events: "
                       + ", ".join(BELL_CUSTOM_ROWS) + "; a missing one follows the events matrix)",
                       "additionalProperties": {"type": "object", "additionalProperties": {
                           "type": "object", "properties": {"news": {"type": "integer", "enum": [0, 1]}, "push": {"type": "integer", "enum": [0, 1]}}}}}}},
        "NotificationsInput": {"type": "object", "additionalProperties": False, "properties": {
            "events": {"type": "object", "additionalProperties": {"type": "object", "additionalProperties": False,
                                                                  "properties": {"news": {"type": "boolean"}, "push": {"type": "boolean"}}}},
            "lists": {"type": "object", "additionalProperties": {"oneOf": [
                {"type": "string", "enum": list(BELL_MODES)},
                {"type": "object", "additionalProperties": False, "required": ["mode"], "properties": {
                    "mode": {"type": "string", "enum": ["custom"]},
                    "events": {"type": "object", "additionalProperties": {"type": "object", "additionalProperties": False,
                                                                          "properties": {"news": {"type": "boolean"}, "push": {"type": "boolean"}}}}}}]}}}},
        "AdminUser": {"type": "object", "properties": {
            "id": {"type": "integer"}, "username": {"type": "string"}, "display_name": {"type": "string"}, "is_admin": {"type": "boolean"},
            "disabled": {"type": "boolean"}, "created_at": {"type": "string", "format": "date-time"}, "has_password": {"type": "boolean"},
            "sso": {"type": "boolean"}, "two_factor": {"type": "boolean"}, "api_tokens": {"type": "integer"}}},
        "AdminUserPage": page("AdminUser"),
        "AdminStatus": {"type": "object", "properties": {
            "version": {"type": "string"}, "users": {"type": "integer"}, "lists": {"type": "integer"}, "open_tasks": {"type": "integer"},
            "update_available": {"type": "boolean"}, "latest_version": nul("string"),
            "update_checked_at": nul("string"), "update_error": nul("string"),
            "backups": {"type": "object", "properties": {"enabled": {"type": "boolean"}, "last_ok": nul("string")}},
            "webhooks_pending": {"type": "integer"}}},
        "WebhookPayload": {"type": "object", "description": "Body of a webhook delivery (POST to your URL). Verify X-Kalmido-Signature first.",
                           "properties": {"id": {"type": "string", "description": "Delivery id (also X-Kalmido-Delivery; the same for every retry)"},
                                          "event": {"type": "string", "enum": [*WH_EVENTS, "ping"]},
                                          "created_at": {"type": "string", "format": "date-time"}, "webhook_id": {"type": "integer"},
                                          "actor": {"oneOf": [{"type": "null"}, {"type": "object", "properties": {"id": {"type": "integer"}, "name": {"type": "string"}}}]},
                                          "via": {"type": "string", "enum": ["web", "api", "public_link"]},
                                          "data": {"type": "object", "properties": {
                                              "task": ref("Task"), "list": {"type": "object", "properties": {"id": {"type": "integer"}, "name": {"type": "string"}}},
                                              "changes": {"type": "array", "items": {"type": "string"}}, "permanent": {"type": "boolean"},
                                              "comment": {"type": "object"}, "member": {"type": "object"}, "role": {"type": "string"}}}}},
    }
    T, L, C, TI, H, S_, A = "Tasks", "Lists", "Comments", "Time tracking", "Habits", "Search and tags", "Admin"
    tasks_filters = [q("list_id", "Only this list", {"type": "integer"}),
                     q("status", "open (default), done, wont_do or all", {"type": "string", "enum": ["open", "done", "wont_do", "all"]}),
                     q("due_from", "Due on or after (YYYY-MM-DD)", date_s), q("due_to", "Due on or before (YYYY-MM-DD)", date_s),
                     q("tag", "One of your tags or a list tag (without #)"), q("list_tag", "A list tag (without #)"),
                     q("assignee", "me, none or a user id"),
                     q("assignee_group", "2.10.0: mine (assigned to one of your groups) or a group id"),
                     q("updated_since", "Changed since (ISO date-time)", {"type": "string", "format": "date-time"}),
                     q("parent_id", "Subtasks of this task", {"type": "integer"}), q("top_level", "true = no subtasks", {"type": "boolean"}),
                     q("fields", "compact = only id, title, list_id, section_id, parent_id, status, due, due_time, priority, tags, "
                                 "list_tags, assignee_id (default full)", {"type": "string", "enum": ["full", "compact"]}),
                     q("waiting", "true = only tasks waiting on someone, false = only the others", {"type": "boolean"}),
                     q("pinned", "2.16.0: true = only pinned tasks, false = only the others", {"type": "boolean"}),
                     q("milestone", "2.18.0: true = only milestones, false = only the other tasks", {"type": "boolean"}),
                     q("milestone_id", "2.18.0: only the tasks of this milestone", {"type": "integer"}),
                     q("type", "Ticket type: bug, feature, task or none (2.4.0)", {"type": "string", "enum": [*TICKET_TYPES, "none"]}),
                     limit, cursor]
    paths = {
        "/me": {"get": op("The token's user, scopes and switched-on modules", "Account", ok(ref("Me")) | errs())},
        "/me/notifications": {"patch": op("Change your notification settings (events x News / push, the bell per list)", "Account",
                                          ok(ref("Notifications")) | errs("400", "404"), body=ref("NotificationsInput"), scope="write",
                                          desc="Partial: only the events / lists you send. A list bell: all = every event of that list, "
                                               "default = the events matrix, mute = only mentions of you and assignments to you, custom = your own choice "
                                               "per event ({mode: \"custom\", events: {comment: {news: true, push: false}, …}}; "
                                               "a ticked event comes from every task of the list, an unticked one never).")},
        "/me/app-passwords": {
            "get": op("Your app passwords for calendar apps (CalDAV) and the server's CalDAV address", "Account",
                      ok({"type": "object", "properties": {"data": {"type": "array", "items": ref("AppPassword")}, "caldav": ref("CalDAV")}})
                      | errs("403"), desc="Persons only (2.9.0); an agent's token gets 403."),
            "post": op("Create an app password (shown once in the answer)", "Account",
                       ok({"allOf": [ref("AppPassword"), {"type": "object", "properties": {"password": {"type": "string",
                           "description": "Shown only this once; Kalmido keeps only a hash"}}}]}, "Created", "201") | errs("400", "403", "409"),
                       body={"type": "object", "required": ["name"], "additionalProperties": False,
                             "properties": {"name": {"type": "string", "maxLength": 60, "description": "e.g. the device: iPhone, Thunderbird"}}},
                       scope="write", desc=f"At most {APPPW_MAX} per person. Log in to /dav/ with your user name and this password (HTTP Basic, HTTPS)."),
        },
        "/me/app-passwords/{id}": {"delete": op("Revoke an app password (the calendar app using it stops at once)", "Account",
                                                ok({"type": "object", "properties": {"ok": {"type": "boolean"}}}) | errs("403", "404"),
                                                params=[pid(desc="App password id")], scope="write")},
        "/lists": {"get": op("Lists you can see (own and shared)", L, ok(ref("ListPage")) | errs()),
                   "post": op("Create a list", L, ok(ref("List"), "Created", "201") | errs("400"), body=ref("ListInput"), scope="write")},
        "/lists/{id}": {"get": op("One list with its sections", L, ok(ref("ListDetail")) | errs("404"), [pid("id", "List id")]),
                        "patch": op("Change a list (2.7.0)", L, ok(ref("List")) | errs("400", "403", "404"), [pid("id", "List id")],
                                    body=ref("ListPatch"), scope="write",
                                    desc="Owner: name, color, kind, nag (default nag interval of its tasks), day_hours (hours per day / "
                                         "shift for the time sums). Owner and list admins: columns (2.14.0). Members change only their own "
                                         "folder and view.")},
        "/lists/{id}/shift": {"post": op("Move a whole list (project) in time", L, ok(ref("ShiftResult")) | errs("400", "403", "404", "409"),
                                         [pid("id", "List id")], body=ref("ShiftInput"), scope="write",
                                         desc=f"Every open task with a date (subtasks too) moves by `days`, start and due, in one transaction; "
                                              f"tasks without a date stay. Moving later also moves dependent tasks in other lists whose list has "
                                              f"\"Move dependent tasks along\" on. Edit rights on the list. More than {SHIFT_MAX_TASKS} dated tasks: 409.")},
        "/lists/{id}/owner": {"post": op("Transfer the ownership of a list", L, ok(ref("OwnerResult")) | errs("400", "403", "404", "409"),
                                         [pid("id", "List id")], body=ref("OwnerInput"), scope="write",
                                         desc="The owner hands the list to another active person (not an agent); the old owner stays "
                                              "as a list admin. An admin may take over a list whose owner is an agent or a disabled "
                                              "user (for themselves or another person). Agent tokens always get 403; inboxes 409.")},
        "/roadmap": {"get": op("All lists on one timeline: groups with summary spans, progress and dated tasks", "Roadmap",
                               ok(ref("Roadmap")) | errs("400"),
                               [q("from", "First day (default: 14 days ago)", date_s), q("to", f"Last day (default: from + 194 days, at most {ROADMAP_MAX_DAYS} days)", date_s),
                                q("projects_only", "true = only lists of the type project", {"type": "boolean"}),
                                q("include_done", "true = completed tasks too", {"type": "boolean"})])},
        "/tasks": {"get": op("Tasks you can see (not in the trash), filtered, oldest first", T, ok(ref("TaskPage")) | errs("400", "404"), tasks_filters),
                   "post": op("Create a task (default list: your inbox)", T, ok(ref("Task"), "Created", "201") | errs("400", "403", "404"),
                              body=ref("TaskCreate"), scope="write")},
        "/tasks/{id}": {"get": op("One task", T, ok(ref("Task")) | errs("404"), [pid()]),
                        "patch": op("Change a task (only the fields you send)", T, ok(ref("Task")) | errs("400", "403", "404"), [pid()],
                                    body=ref("TaskInput"), scope="write"),
                        "delete": op("Move a task (with its subtasks) to the trash", T,
                                     {"204": {"description": "In the trash (restorable in the app)"}} | errs("403", "404"), [pid()], scope="write")},
        "/tasks/{id}/complete": {"post": op("Complete a task", T, ok(ref("TaskCompleted")) | errs("403", "404"), [pid()], scope="write",
                                            desc="Recurring tasks move to their next date (next_due) and a completed copy stays in the history. "
                                                 "Completing a done task changes nothing.")},
        "/tasks/{id}/waiting": {"put": op("Mark a task as waiting on someone outside (or change note / follow-up day)", T, ok(ref("Task")) | errs("400", "403", "404"),
                                          [pid()], body=ref("WaitingInput"), scope="write",
                                          desc="On the follow-up day the person it is for gets a reminder + News, following agents the event followup_due."),
                                "delete": op("Clear the waiting state", T, ok(ref("Task")) | errs("403", "404"), [pid()], scope="write")},
        "/tasks/{id}/reopen": {"post": op("Reopen a completed task", T, ok(ref("Task")) | errs("403", "404"), [pid()], scope="write")},
        # 2.18.0 (#430): a milestone's progress, tasks, burndown and release notes
        "/tasks/{id}/milestone": {"get": op("A milestone: progress, its tasks, burndown, release notes", T, ok(ref("MilestoneReport")) | errs("403", "404"),
                                            [pid()], desc="Only for milestone tasks (milestone: true), else 404. Progress counts closed "
                                            "(done or won't do) tasks of the milestone (milestone_id); burndown.days = open tasks per local day "
                                            "from the first task's creation (at most 180 days) to today, burndown.ideal = a line from all tasks "
                                            "to 0 on the due date; release_notes = Markdown of its completed tasks grouped by ticket type.")},
        "/tasks/{id}/subtasks": {"get": op("Subtasks of a task", T, ok(ref("TaskPage")) | errs("404"), [pid()]),
                                 "post": op("Add a subtask", T, ok(ref("Task"), "Created", "201") | errs("400", "403", "404"), [pid()],
                                            body=ref("TaskInput"), scope="write")},
        # 2.13.1 (#465): files of a task and its comments, and their binary (agents: only tasks they see with comments)
        "/tasks/{id}/attachments": {"get": op("Files of a task and of its comments (comment_id); download each with GET /attachments/{id}", C,
                                              ok({"type": "object", "properties": {"data": {"type": "array", "items": ref("AttachmentInfo")},
                                                                                   "next_cursor": nul("string")}}) | errs("403", "404"), [pid()])},
        "/attachments/{id}": {"get": op("The binary of a task / comment file (images, PDF and text inline, everything else as a download; "
                                        "?dl=1 always a download). 410 = damaged on the server", C,
                                        {"200": {"description": "The file", "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}}}
                                        | errs("403", "404", "410"), [pid("id", "Attachment id"), q("dl", "1 = download"), q("v", "Cache key (the size)")])},
        "/chat-attachments/{id}": {
            "get": op("The binary of a file in an agent chat (2.13.1): the agent of the conversation or the person", C,
                      {"200": {"description": "The file", "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}}}
                      | errs("403", "404", "410"), [pid("id", "Chat file id"), q("dl", "1 = download"), q("v", "Cache key (the size)")]),
            "delete": op("Remove a chat file you sent (a message left without text and files goes too)", C,
                         ok({"type": "object"}) | errs("403", "404"), [pid("id", "Chat file id")], scope="write")},
        "/tasks/{id}/comments": {"get": op("Comments of a task", C, ok(ref("CommentPage")) | errs("403", "404"), [pid()]),
                                 "post": op("Comment on a task (needs the Comments module; @mentions and notifications need collaboration)", C, ok(ref("Comment"), "Created", "201") | errs("400", "403", "404"),
                                            [pid()], body=ref("CommentInput"), scope="write")},
        "/tags": {"get": op("Your tags with task counts", S_, ok(ref("TagPage")) | errs())},
        "/search": {"get": op("Search titles, notes, links and custom fields", S_, ok(ref("TaskPage")) | errs("400"),
                              [{**q("q", "Search text"), "required": True}, limit, cursor])},
        "/time/entries": {"get": op("Time entries (needs time tracking), newest first", TI, ok(ref("TimeEntryPage")) | errs("400", "403"),
                                    [q("from", "First day (default: 6 days ago)", date_s), q("to", "Last day (default: today)", date_s),
                                     q("scope", "mine (default) or all (everyone in shared lists)", {"type": "string", "enum": ["mine", "all"]}),
                                     q("list_id", "Only this list", {"type": "integer"}), q("task_id", "Only this task", {"type": "integer"}), limit, cursor]),
                          "post": op("Add a time entry", TI, ok(ref("TimeEntry"), "Created", "201") | errs("400", "403", "404"),
                                     body=ref("TimeEntryInput"), scope="write")},
        "/habits": {"get": op("Your habits with today's count and the last 30 days", H, ok(ref("HabitPage")) | errs())},
        "/habits/{id}/checkin": {"post": op("Check in a habit", H, ok(ref("HabitCheckedIn")) | errs("400", "404"), [pid("id", "Habit id")],
                                            body=ref("CheckinInput"), scope="write")},
        "/import/{source}": {"post": {**op("Import an export of another app", "Import", ok(ref("ImportReport")) | errs("400", "404", "409"),
                                           [{"name": "source", "in": "path", "required": True, "description": "Source format",
                                             "schema": {"type": "string", "enum": list(IMPORT_SOURCES)}}], scope="write",
                                           desc="Todoist (CSV, backup ZIP, Sync API JSON), Trello (board JSON), Asana (CSV), mstodo (Outlook / Microsoft To Do CSV or ICS), "
                                                "ics (VTODO). Idempotent: tasks imported before are skipped. Nothing inside the file is fetched."),
                                        "requestBody": {"required": True, "content": {"multipart/form-data": {"schema": ref("ImportInput")}}}}},
        "/imports/{id}/undo": {"post": op(f"Undo an import (within {IMPORT_UNDO_HOURS} hours): removes what it created", "Import",
                                          ok(ref("ImportUndone")) | errs("404", "409"), [pid("id", "Import id")], scope="write")},
        "/admin/users": {"get": op("All users (admins, scope admin-read)", A, ok(ref("AdminUserPage")) | errs("403"), scope="admin-read")},
        "/admin/status": {"get": op("Server status (admins, scope admin-read)", A, ok(ref("AdminStatus")) | errs("403"), scope="admin-read")},
        "/admin/agents/{id}/audit": {"get": op(  # 2.2.1 (#358)
            "Audit log of an agent: every API request made with its token, newest first (admins, scope admin-read)", A,
            ok(ref("AuditPage")) | errs("400", "403", "404"),
            [pid("id", "Agent (user) id"), q("status", "2xx, 3xx, 4xx, 5xx or denied (401 / 403 / 429)", {"type": "string", "enum": list(AUDIT_STATUS)}),
             q("day", "Local day YYYY-MM-DD", date_s), limit, cursor], scope="admin-read")},
    }
    agent_spec(paths, schemas, op, ok, errs, ref, q, pid, nul, page)
    git_spec(paths, schemas, op, ok, errs, ref, pid, nul, page)
    overview_spec(paths, schemas, op, ok, errs, ref, pid, nul, page)
    groups_spec(paths, schemas, op, ok, errs, ref, pid, nul, page)  # 2.10.0 (#441)
    dayplan_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q)  # 2.10.0 (#440)
    api479_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q)  # 2.15.0 (#479)
    notes_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q)  # 2.17.0 (#442)
    family_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q)  # 2.19.0 (#653)
    events_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q)  # 2.21.0 (#659)
    contacts_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q)  # 2.21.0 (#658)
    life_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q)  # 2.22.0 (#663)
    team_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q)  # 2.17.0 (#419)
    pkgc_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q)  # 2.23.0 (#463)
    hosting_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q)  # 2.24.0 (#907 #910)
    scope_refine(paths)
    _SPEC["s"] = {
        "openapi": "3.1.0",
        "info": {"title": f"{APP_NAME} REST API", "version": API_VERSION,
                 "description": "Personal access tokens (Settings > Account > API tokens) as `Authorization: Bearer abk_...`. "
                                "Every request acts as the token's user and sees exactly what that user sees. Dates are local dates "
                                "of the server's time zone (YYYY-MM-DD), times HH:MM, timestamps ISO 8601 in UTC. Lists come in pages: "
                                "{data, next_cursor}. Errors: {error: {code, message}}. See docs/API.md for examples and webhooks.",
                 "license": {"name": "AGPL-3.0-only", "identifier": "AGPL-3.0-only"}},
        "servers": [{"url": API_PREFIX.rstrip("/")}],
        "security": [{"bearerAuth": []}],
        "tags": [{"name": n} for n in ("Account", T, L, "Structure", "Roadmap", C, S_, TI, H, "Import", A, "Agents", "Groups", "Day plan", "Notes", "Team chat", "Family", "Events", "Contacts", "Home & life", "Clients", "Workload", "Forms")],
        "paths": paths,
        "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "abk_ token"}},
                       "schemas": schemas},
    }
    return _SPEC["s"]
