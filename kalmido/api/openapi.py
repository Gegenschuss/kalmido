"""The OpenAPI 3.1 document of /api/v1 (served at /api/v1/openapi.json, built once)."""

from ..core.config import API_PREFIX, APP_NAME
from ..core.access import ROLES
from ..lists.lists import COL_DOC, COL_MAX, LIST_KIND_ALIASES, LIST_KINDS, LIST_NAME_MAX, LIST_VIEWS, SORT_MODE_DOC
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
from ..api.v1 import _SPEC, API_PAGE_DEFAULT, API_PAGE_MAX, API_SCOPES, API_VERSION, PRIO_VALUES, STATUS_NAMES, V1_TASK_IN
from ..api.common import V1_CODES
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
        "via": {"type": "string", "description": "list = the project is shared directly; otherwise the owner's folder that is shared"}}}
    schemas["ListGroupPage"] = page("ListGroup")
    gp = {"name": "group_id", "in": "path", "required": True, "description": "Group id", "schema": {"type": "integer"}}
    paths["/groups"] = {"get": op("Groups (admins create them; every person sees them with their members)", G, ok(ref("GroupPage")) | errs())}
    paths["/groups/{id}"] = {"get": op("One group", G, ok(ref("Group")) | errs("404"), [pid(desc="Group id")])}
    paths["/lists/{id}/groups"] = {"get": op("The groups a project is shared with (directly or through a folder)", G,
                                             ok(ref("ListGroupPage")) | errs("404"), [pid(desc="Project id")])}
    paths["/lists/{id}/groups/{group_id}"] = {
        "put": op("Share a project with a group (or change its role); owner or project admin", G, ok(ref("ListGroupPage")) | errs("400", "403", "404"),
                  [pid(desc="Project id"), gp], body={"type": "object", "properties": {"role": {"type": "string", "enum": list(ROLES)}}},
                  scope="write", desc="Every member of the group gets access; members who join later too. A person's role is the "
                                      "higher of their own and the one via groups."),
        "delete": op("Stop sharing a project with a group", G, ok({"type": "object"}) | errs("403", "404"), [pid(desc="Project id"), gp], scope="write")}
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
    from ..collab.msgsearch import msgsearch_spec
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
                "429": "Rate limit reached (see Retry-After)", "503": "Not available on this server"}
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
        "repeat": {"type": "string", "description": "RRULE body (FREQ=WEEKLY;BYDAY=MO) or empty. 2.116.0: FREQ=DAILY;TIMES=0800,1300,2000 = daily at several times (HHMM, at most 12; completing moves the due time to the next one, after the last to the first of the next day)"},
        "repeat_from": {"type": "string", "enum": ["due", "done"]}, "url": nul("string", format="uri"),
        "tags": {"type": "array", "items": {"type": "string"}, "description": "The token user's own tags"},
        "pinned": {"type": "boolean"}, "assignee_id": nul("integer"), "created_by": nul("integer"), "completed_by": nul("integer"),
        "assignee_group_id": nul("integer", description="2.10.0: assigned to a group (whoever has time takes it, POST /tasks/{id}/take); "
                                 "setting it clears assignee_id and the other way round; the project must be shared with the group"),
        "created_at": {"type": "string", "format": "date-time"}, "updated_at": {"type": "string", "format": "date-time"},
        "completed_at": nul("string", format="date-time"), "deleted": {"type": "boolean"},
        "fields": {"type": "object", "additionalProperties": {"type": "string"}, "description": "Custom field values by field id"},
        "waiting": {"oneOf": [{"type": "null"}, ref("Waiting")], "description": "Waiting on someone outside (a client, an office, a delivery) with a follow-up day (2.1.0; called waiting on external before 2.25.0); null = not waiting"},
        "type": nul("string", enum=[*TICKET_TYPES, None], description="Ticket type (2.4.0); a new bug / feature in a project with ticket "
                    "types on gets the project's note template when its notes are empty"),
        "deadline": {"type": "boolean", "description": "2.7.0: the due date is a deadline (countdown, highlighted from the first reminder on)"},
        "deadline_in_today": {"type": "boolean", "description": "2.7.0: a deadline that shows on Today from its first reminder on "
                              "(setting it true also sets deadline)"},
        "nag": {"type": "string", "enum": list(NAG_VALUES), "description": "2.7.0: repeat the reminder until done: 5 / 10 / 15 / 30 / 60 "
                "minutes or 1d (daily), from the first reminder on; off = never; empty = the project's default"},
        "plan_start": nul("string", pattern="^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-2][0-9]:[0-5][0-9]$",
                          description="2.11.0: planned start YYYY-MM-DDTHH:MM (local; set by the day plan, see /dayplan); "
                                      "independent of due / deadline, which planning never changes; null = not planned"),
        "milestone": {"type": "boolean", "description": "2.18.0: the task is a milestone (a diamond with a date, checkable, top level, "
                      "no subtasks); see GET /tasks/{id}/milestone for its progress, burndown and release notes"},
        "milestone_id": nul("integer", description="2.18.0: the milestone (a task of the same project with milestone true) this task "
                            "belongs to, e.g. the release it ships in; cleared when the task moves to another project or the milestone "
                            "is deleted / no milestone any more"),
        # 2.19.0 (#653): the module Family
        "family": {"type": ["object", "null"], "description": "2.19.0: a birthday / anniversary {kind: birthday | anniversary, name, year?, lead?} "
                   "(a yearly task; age = due year - year) or a household deadline {kind: deadline, type, who, expires, notice (months), lead}; "
                   "2.140.0: a shopping item {kind: shop, qty?, unit?, price?} (amount + unit of the line, its price in the "
                   "user's currency; the title stays the name), a recipe {kind: recipe, serves?} (notes = ingredients under a heading "
                   "\"Ingredients\" + the method), a meal {kind: meal, recipe? (task id), serves?}; "
                   "null = none. Easier: POST /family/occasions and /family/deadlines"},
        "rotation": {"type": ["object", "null"], "description": "2.19.0: household rotation {who: [user ids of people sharing the project, "
                     "at least 2], mode: done (the next person after each completion) | week (every Monday), i (whose turn, index; "
                     "optional)}; sets the assignee; null = none"},
        "stars": nul("integer", minimum=0, maximum=STARS_MAX, description="2.19.0: stars a kid account gets for completing it (null = 1)"),
        "people": {"type": "array", "items": {"type": "integer"}, "description": "2.19.0: who comes along (user ids of people sharing "
                   "the project): they see the task, also as participants, and get its reminders"},
        "approval": nul("string", enum=["pending", "approved", "changes", "rejected", None], description="2.23.0: the task waits for / "
                        "had an approval (POST /tasks/{id}/approval); null = no approval"),
        "approver_id": nul("integer", description="2.23.0: who decides on the approval (a person of the project)"),
        # 2.35.0 (#1095): code snippets (plain code, no Markdown)
        "snippets": {"type": "array", "maxItems": 20, "items": ref("Snippet"), "description": "2.35.0: code snippets of the task "
                     "(code, logs, diffs; plain code with a language, no Markdown). Only in one task (GET /tasks/{id} and the answers of "
                     "changes); lists carry only snippets_n. Writing sends the whole list (a snippet with its "
                     "id stays that snippet; [] removes all); POST /tasks/{id}/snippets appends one. Task events carry at most 10, "
                     "code cut to 4000 characters (truncated: true) and snippets_total; get_task has the full code"},
        "snippets_n": {"type": "integer", "description": "2.35.0: the number of code snippets (also in lists)"},
        # 2.36.0 (#1118): the lock
        "locked": {"type": "boolean", "description": "2.36.0: locked in the app: title, notes, dates, priority, project, tags, repeat "
                   "and assignee are read-only there until a person with write access unlocks it (comments, checkboxes in the "
                   "notes, completing and subtasks stay free). Tasks created with an agent token start locked (send "
                   "locked: false to create an open one); the API itself is not bound by the lock and can set or clear it"}}
    # 2.60.0 (#1511): story points
    task_props["points"] = nul("integer", enum=[1, 2, 3, 5, 8, 13, None], description="2.60.0: story points (Fibonacci); "
                               "null = none. Always stored; the app shows them where the project has story points on (points_on)")
    # 2.111.0 C (#2057): a reminder at a fixed local time, with or without a due date
    task_props["remind_at"] = nul("string", pattern="^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-2][0-9]:[0-5][0-9]$",
                                  description="2.111.0: a reminder at a fixed local date and time (server time zone, like due / "
                                  "due_time), with or without a due date; null = none. Fires once, like the reminders before the "
                                  "due time; on a recurring task it moves along with the due date")
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
                                                  "attachments": {"type": "array", "items": ref("Attachment")},
                                                  # 2.81.0 (#1856)
                                                  "file_hit": {"type": "string", "description": "Search only: the name of the file whose recognised text matched (absent otherwise). The recognised text of files counts only for a token with attachments:read"}}},
        "TaskCompleted": {"allOf": [ref("Task"), {"type": "object", "properties": {"next_due": nul("string", format="date", description="Recurring: the next date the task moved to"),
                                                                                  "skipped": {"type": "boolean", "description": "2.270.0: expect_due differed -- already ticked, not advanced again"}}}]},
        "TaskInput": {"type": "object", "additionalProperties": False, "properties": task_in},
        # 2.67.0 B (#1865): a later due date moves the tasks waiting on it along (list setting); shift_chain false = not
        "TaskUpdate": {"type": "object", "additionalProperties": False, "properties": {**task_in, "shift_chain": {
            "type": "boolean", "default": True, "description": "false: the tasks waiting on this one stay where they are"},
            # 2.270.0 D (#3028): write conflicts (another person / device changed the task since you read it)
            "expect_updated_at": {"type": "string", "description": "The task's updated_at as you read it (recommended): changed since = 409 {error, current: the task now}; also as the header If-Match"},
            "_prev": {"type": "object", "description": "{field: the value you read} for the fields you send: a field changed since stays as it is and is listed in conflicts"}}},
        "TaskChanged": {"allOf": [ref("Task"), {"type": "object", "properties": {"chain": ref("Chain"), "conflicts": {
            "type": "array", "description": "2.270.0: only with _prev -- fields not written because someone changed them since you read them",
            "items": {"type": "object", "properties": {"field": {"type": "string"}, "server": {}, "mine": {}}}}}}]},
        "Chain": {"type": "object", "description": "Only when the change moved dependent tasks along (or left some in place)", "properties": {
            "days": {"type": "integer", "description": "Days the chain moved (negative = earlier)"},
            "moved": {"type": "array", "items": {"type": "object", "properties": {
                "id": {"type": "integer"}, "title": {"type": "string"}, "start": nul("string", format="date"), "due": {"type": "string", "format": "date"},
                "old_start": nul("string", format="date"), "old_due": {"type": "string", "format": "date"}}}},
            "skipped": {"type": "array", "description": "Left in place; the chain behind them did not move either", "items": {"type": "object", "properties": {
                "id": nul("integer", description="null for a task you cannot see"), "title": nul("string"), "hidden": {"type": "boolean"},
                "reason": {"type": "string", "enum": ["done", "milestone", "no_date", "no_access", "limit", "error"]}}}}}},
        "Snippet": {"type": "object", "required": ["code"], "properties": {  # 2.35.0 (#1095)
            "id": {"type": "string", "description": "Set by the server (keep it when you send the list back)"},
            "lang": {"type": "string", "maxLength": 20, "description": "Language (py, js, ts, sh, sql, diff, json, …); empty = recognised by the app"},
            "path": nul("string", maxLength=300, description="Optional file path, e.g. src/app.py"),
            "line": nul("integer", minimum=1, description="Optional line in that file"),
            "code": {"type": "string", "maxLength": 20000, "description": "The code itself (plain text, kept as it is)"},
            "by": nul("integer", description="Read only: who changed it last"), "updated_at": {"type": "string", "description": "Read only"},
            "truncated": {"type": "boolean", "description": "Only in task events: the code is cut (get_task has all of it)"}}},
        "TaskCreate": {"type": "object", "additionalProperties": False, "required": ["title"], "properties": {**task_in, "client_ref": {  # 2.270.0 D (#3028)
            "type": "string", "maxLength": 64, "description": "Your id of the new task: sent again (a retry after a lost answer) = the task created the first time (200 instead of 201)"}}},
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
        "AttachmentText": {"type": "object", "properties": {  # 2.34.0 (#368)
            "id": {"type": "integer"}, "task_id": {"type": "integer"}, "comment_id": nul("integer"), "name": {"type": "string"},
            "mime": {"type": "string"}, "size": {"type": "integer"}, "url": {"type": "string", "description": "/api/v1/attachments/{id} (the file itself)"},
            "kind": {"type": "string", "enum": ["pdf", "text", "image", "docx", "xlsx", "other"]},  # 2.92.0 C (#1926): + docx, xlsx
            "text": nul("string", description="The text (PDF: the text layer, pages separated by a blank line; docx: paragraphs, '# ' headings, "
                                              "'- ' list items, table rows as 'a | b'; xlsx: '## <sheet>' then one line per row, cells as 'a | b'); "
                                              "null for images, other files and errors"),
            "chars": {"type": "integer"}, "truncated": {"type": "boolean", "description": "true = cut at max_chars (at most 200000) or after 1000 pages"},
            "pages": {"type": "integer", "description": "PDF: number of pages"}, "pages_read": {"type": "integer"},
            "no_text_layer": {"type": "boolean", "description": "PDF: a scanned PDF without a text layer: text is empty unless source is ocr"},
            "source": {"type": "string", "enum": ["ocr"], "description": "2.61.0: the text was recognised in the background (scanned PDF, photo)"},
            "error": {"type": "string", "enum": ["encrypted", "unreadable", "too_complex", "too_large", "unsafe", "busy"],
                      "description": "PDF / docx / xlsx: why it could not be read (2.92.0: too_large = the archive unpacks too big, unsafe = DOCTYPE / entities)"},
            "sheets": {"type": "integer", "description": "2.92.0 xlsx: sheets read (at most 5)"}, "sheets_total": {"type": "integer"},
            "message": nul("string", description="A hint in the user's language (scanned PDF, image, error)")}},
        "Progress": {"type": "object", "properties": {"done": {"type": "integer"}, "total": {"type": "integer"}, "overdue": {"type": "integer"},
                                                      "next_due": nul("string", format="date")}},
        "List": {"type": "object", "properties": {
            "id": {"type": "integer"}, "name": {"type": "string"}, "color": {"type": "string"},
            "folder": {"type": "string", "description": "Your folder path, at most 30 levels (2.352.0; before: 2): \"Clients/Company X\"; empty = none"},
            "tickets": {"type": "boolean", "description": "Ticket types bug / feature / task on (2.4.0)"},
            "time_tracking": {"type": "boolean", "description": "2.41.0 (#1471): time tracking on for this project (any type; default off; owner). New time entries need it; tracked time stays visible when it is switched off"},
            "modules_on": {"type": "array", "items": {"type": "string"}, "description": "2.39.1 (#1293): only in the answer of a PATCH with "
                           "columns or project_type: the modules it switched on (custom field columns: [\"fields\"] for the project's owner)"},
            "is_inbox": {"type": "boolean"}, "archived": {"type": "boolean"},
            "done_at_bottom": {"type": "boolean", "description": "2.7.2: \"Show completed at the bottom\": completed tasks stay visible below the open ones and come back with one tap"},
            "sort_mode": {"type": "string", "description": "2.144.0 (#2414): the project's sort, the same for every member (\"\" = default; " + SORT_MODE_DOC + ")"},
            "group_field": {"type": "string", "description": "2.144.0 (#2414): the list view grouped by a custom field: \"cf:<field id>\" (a text "
                            "or select field of the project: one group per value, select fields in the order of their options, \"No value\" last; "
                            "sections stay and come back when it is off), \"\" = by sections"},
            "checklist": {"type": "boolean", "deprecated": True, "description": "Deprecated (2.7.2): same as done_at_bottom"},
            "kind": {"type": "string", "enum": list(LIST_KINDS), "description": "Stored list type, no longer evaluated (2.352.0): every list but the inbox is a project with project page, progress, dependencies and status; tracked = has a status (status not null). Still returned and accepted for compatibility"},
            "view": {"type": "string", "enum": list(LIST_VIEWS)}, "role": {"type": "string", "enum": ["owner", "admin", "edit", "participant", "view"]},
            "owner_id": {"type": "integer"}, "owner_name": {"type": "string"}, "shared": {"type": "boolean"},
            "status": nul("string", enum=[*LIST_STATUSES, None]), "progress": ref("Progress"), "created_at": {"type": "string", "format": "date-time"},
            "nag": {"type": "string", "enum": [x for x in NAG_VALUES if x != "off"], "description": "2.7.0: default nag interval of the project's tasks; empty = none"},
            "day_hours": nul("number", description="2.7.0: hours of a working day / shift for this project's time sums; null = the server's value"),
            "columns": {"type": ["array", "null"], "items": {"type": "string"}, "description": COL_DOC},
            "agent_members": {"type": "boolean", "description": "2.26.0 (#928): members may see and use the project's agents (default false)"},
            "agent_peers": {"type": "boolean", "deprecated": True, "description": "2.40.0 (#1373): deprecated, always false -- agents never address each other"},
            "stale_days": nul("integer", description="2.34.0 (#266): an open task counts as stale (GET /stale) after this many idle days; null = the default (7), 0 = never"),
            "agent_followup": {"type": "boolean", "description": "2.34.0 (#266): \"Agent follows up\": the project's agents get its stale tasks once a day (event stale_tasks; default false)"},
            "family": nul("string", enum=[*[x for x in FAM_LIST_KINDS if x], None], description="2.19.0: what the project is for in the Family module: "
                          "shopping (sections = shop areas, a new item goes to its area of last time, a shopping mode in the app), meals "
                          "(the meal plan: due = the day, notes = ingredients), birthdays, household, packing, recipes (2.140.0: a task per recipe); null = an ordinary project"),
            "life": nul("string", enum=["contracts", "home", "health", "travel", "reading", "budget", None], description="2.22.0: what the project is for in "
                        "Home & life (health projects are private: never visible to agents, tokens need the scope private); null = none"),
            "trip": {"type": ["object", "null"], "description": "2.22.0: a trip project's {from, to, where?}", "properties": {
                "from": {"type": "string", "format": "date"}, "to": {"type": "string", "format": "date"}, "where": {"type": "string"}}},
            "client_id": nul("integer", description="2.23.0: the client the project belongs to (GET /clients); null = none")}},
        "ListDetail": {"allOf": [ref("List"), {"type": "object", "properties": {"sections": {"type": "array", "items": ref("Section")},
            "fields": {"type": "array", "description": "2.14.0: the project's custom fields (ids for the columns f:<id>)",
                       "items": {"type": "object", "properties": {"id": {"type": "integer"}, "name": {"type": "string"}, "type": {"type": "string"}}}},
            "favorite": {"type": "boolean", "description": "2.46.1 (#1361): a favourite of the person (an agent: of the person it belongs to; a team agent: always false)"}}}]},
        "ListInput": {"type": "object", "additionalProperties": False, "required": ["name"], "properties": {
            "name": {"type": "string"}, "color": {"type": "string", "description": "#rgb / #rrggbb or empty"},
            "folder": {"type": "string", "description": "Folder path, at most 30 levels (\"Clients/Company X\", 2.352.0; before: 2); deeper: 400"},
            "done_at_bottom": {"type": "boolean", "description": "2.7.2: show completed tasks at the bottom"},
            "checklist": {"type": "boolean", "deprecated": True, "description": "Deprecated (2.7.2): same as done_at_bottom"},
            "kind": {"type": "string", "enum": [*LIST_KINDS, *LIST_KIND_ALIASES], "description": "list | project: stored only, no longer evaluated (2.352.0, every list but the inbox is a project); \"checklist\" is a deprecated alias of list + done_at_bottom"},
            "tickets": {"type": "boolean", "description": "Ticket types on (2.4.0)"},
            "time_tracking": {"type": "boolean", "description": "2.41.0 (#1471): time tracking on for this project (any type; default off; owner). New time entries need it; tracked time stays visible when it is switched off"},
            "project_type": {"type": "string", "enum": list(PTYPES), "description": "2.4.0: a project of a built-in type (sections, "
                             "custom fields, view, ticket types; switches the modules it needs on for you); kind / checklist / tickets are ignored"},
            "sections": {"type": "boolean", "default": False, "description": "2.27.0: with project_type: create the type's standard sections "
                         "(e.g. Backlog … Done); without it the project starts without sections"},
            "family": nul("string", enum=[*[x for x in FAM_LIST_KINDS if x], None], description="2.19.0: what the project is for in the Family module: "
                          "shopping (sections = shop areas, a new item goes to its area of last time, a shopping mode in the app), meals "
                          "(the meal plan: due = the day, notes = ingredients), birthdays, household, packing, recipes (2.140.0: a task per recipe); null = an ordinary project"),
            "nag": {"type": "string", "enum": list(NAG_VALUES), "description": "2.7.0: default nag interval of the project's tasks (owner)"},
            "day_hours": nul("number", minimum=1, maximum=24, description="2.7.0: hours per day / shift (owner); null = the server's value"),
            "org_id": nul("integer", description="2.28.0: the workspace: an organisation you belong to, null = private (default: the folder's, else private)")}},
        "ListPatch": {"type": "object", "additionalProperties": False, "properties": {
            "org_id": nul("integer", description="2.28.0: the project's workspace (the owner; 409 while people / agents in it do not fit, for family / Home & life projects and the inbox)"),
            "client_id": nul("integer", description="2.23.0: the client of the project (owner / project admins; a client you see); null = none"),
            "life": nul("string", enum=["contracts", "home", "health", "travel", "reading", "budget", None], description="2.22.0: what the project is for in "
                        "Home & life (health projects are private: never visible to agents, tokens need the scope private); null = none"),
            "trip": {"type": ["object", "null"], "description": "2.22.0: a trip project's {from, to, where?}", "properties": {
                "from": {"type": "string", "format": "date"}, "to": {"type": "string", "format": "date"}, "where": {"type": "string"}}},
            "family": nul("string", enum=[*[x for x in FAM_LIST_KINDS if x], None], description="2.19.0: what the project is for in the Family module: "
                          "shopping (sections = shop areas, a new item goes to its area of last time, a shopping mode in the app), meals "
                          "(the meal plan: due = the day, notes = ingredients), birthdays, household, packing, recipes (2.140.0: a task per recipe); null = an ordinary project"),
            "name": {"type": "string"}, "color": {"type": "string"}, "folder": {"type": "string"},
            "view": {"type": "string", "enum": list(LIST_VIEWS)},
            "kind": {"type": "string", "enum": [*LIST_KINDS, *LIST_KIND_ALIASES], "description": "list | project: stored only, no longer evaluated (2.352.0, every list but the inbox is a project); \"checklist\" is a deprecated alias of list + done_at_bottom"},
            "done_at_bottom": {"type": "boolean", "description": "2.7.2: show completed tasks at the bottom (owner)"},
            "sort_mode": {"type": "string", "description": "2.144.0 (#2414): the project's sort for every member (owner / project admins); \"\" = default; " + SORT_MODE_DOC},
            "group_field": {"type": ["string", "integer", "null"], "description": "2.144.0 (#2414): group the list view by a custom field for every "
                            "member (owner / project admins): \"cf:<field id>\" or the id of a text / select field of this project; \"\" / null = by sections "
                            "again (the sections themselves never change)"},
            "time_tracking": {"type": "boolean", "description": "2.41.0 (#1471): time tracking on for this project (any type; default off; owner). New time entries need it; tracked time stays visible when it is switched off"},
            "checklist": {"type": "boolean", "deprecated": True, "description": "Deprecated (2.7.2): same as done_at_bottom"},
            "nag": {"type": "string", "enum": list(NAG_VALUES), "description": "Default nag interval of the project's tasks (owner); off / empty = none"},
            "day_hours": nul("number", minimum=1, maximum=24, description="Hours per day / shift (owner); null = the server's value"),
            "listen_agent_ids": {"type": "array", "items": {"type": "integer"},
                                 "description": "2.13.1 (#471): agents of the project that get a 'comment' event for EVERY comment of a person "
                                                "in this project (only on tasks they can see); 2.30.0 (#1034): they listen in, also task_added / "
                                                "tasks_added for created and moved tasks; [] = none. Owner / project admins, never an agent token"},
            "agent_members": {"type": "boolean", "description": "2.26.0 (#928): members may see and use the project's agents (chat, "
                              "mention, assign, comment to them). Off (default): only the owner, project admins and instance admins can; "
                              "members still see what the agents do. Owner / project admins, never an agent token"},
            "agent_peers": {"type": "boolean", "deprecated": True, "description": "2.40.0 (#1373): deprecated and ignored -- agents never "
                            "address each other (no events between agents); still accepted so older clients get no error"},
            "stale_days": nul("integer", minimum=0, maximum=365, description="2.34.0 (#266): stale after this many idle days (null = the default, 0 = never). Owner / project admins, never an agent token"),
            "agent_followup": {"type": "boolean", "description": "2.34.0 (#266): \"Agent follows up\" (event stale_tasks once a day). Owner / project admins, never an agent token"},
            "folder_adopt": {"type": "boolean", "description": "2.39.1 (#1188): with a new folder: the project takes the folder's settings "
                             "(workspace, agent); without it the project keeps its own (they then differ from the folder)"},
            "columns": {"type": ["array", "null"], "items": {"type": "string"}, "maxItems": COL_MAX,
                        "description": COL_DOC + " Owner / project admins; null = back to the default. 2.39.1 (#1293): custom field "
                                       "columns (f:<id>) switch the module Custom fields on for the project's owner; the answer's modules_on names it."},
            "project_type": {"type": ["string", "null"], "enum": [*PTYPES, "", None],
                             "description": "2.18.0 (#408): the project type (owner / project admins); null / \"\" = none. Switches on what the "
                                            "type needs (Progress and status, ticket types for software, the type's view while the project has no "
                                            "tasks, its modules for you) and never deletes anything; sections are not added"}}},
        "ListPage": page("ListDetail"),  # 2.0.8: the list page carries each list's sections too
        "Roadmap": {"type": "object", "properties": {
            "from": {"type": "string", "format": "date"}, "to": {"type": "string", "format": "date"}, "projects_only": {"type": "boolean"},
            "folders": {"type": "array", "items": {"type": "string"}, "description": "Folder order (your sidebar order)"},
            "groups": {"type": "array", "items": ref("RoadmapGroup"), "description": "One per project: inbox, projects without a folder, then folder by folder"},
            "deps": {"type": "array", "items": {"type": "object", "properties": {"task_id": {"type": "integer"}, "blocker_id": {"type": "integer"}}},
                     "description": "task_id waits on blocker_id (for the returned tasks; blockers you can see)"}}},
        "RoadmapGroup": {"type": "object", "properties": {
            "list": ref("List"), "folder": {"type": "string"}, "can_edit": {"type": "boolean"},
            "span": {"oneOf": [{"type": "null"}, {"type": "object", "properties": {"start": date_s, "end": date_s}}],
                     "description": "Earliest start (or due without a start) to the latest due of ALL open dated tasks of the project; null = none"},
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
            "moved": {"type": "array", "items": ref("Moved"), "description": "The project's tasks"},
            "shifted": {"type": "array", "items": ref("Moved"), "description": "Dependent tasks in other projects moved along"}}},
        "Moved": {"type": "object", "properties": {
            "id": {"type": "integer"}, "title": {"type": "string"}, "start": nul("string", format="date"), "due": {"type": "string", "format": "date"},
            "prev_start": nul("string", format="date"), "prev_due": {"type": "string", "format": "date"}}},
        "Section": {"type": "object", "properties": {"id": {"type": "integer"}, "name": {"type": "string"}, "sort": {"type": "number"}}},
        "Tag": {"type": "object", "properties": {"name": {"type": "string"}, "tasks": {"type": "integer"}, "open": {"type": "integer"}}},
        "TagPage": page("Tag"),
        "Comment": {"type": "object", "properties": {
            "id": {"type": "integer"}, "task_id": {"type": "integer"},
            "author": {"type": "object", "properties": {"id": nul("integer"), "name": {"type": "string"},
                                                        "customer": {"type": "boolean", "description": "2.50.0: written by a customer through a public link (no account; name = what they typed)"}}},
            "body": {"type": "string", "description": "Markdown; mentions as <@user_id>"}, "text": {"type": "string", "description": "Plain text, mentions as @name"},
            "mentions": {"type": "array", "items": {"type": "integer"}}, "created_at": {"type": "string", "format": "date-time"},
            "edited_at": nul("string", format="date-time"), "attachments": {"type": "array", "items": ref("Attachment")},
            "reply_to": nul("integer", description="2.33.0 (#1076): the answered comment of the same task"),
            "reply": {"anyOf": [ref("ReplyQuote"), {"type": "null"}]},
            # 2.41.0 (#1383): an agent's answer buttons / approval card, the person's answer and the state
            "choices": {"type": ["object", "null"], "description": "2.41.0 (#1383): {choices: [{id, label, style?}], multi, approval?: {title, what, std?}, "
                        "expires_at?, withdrawn_at?, outcome?}"},
            "choice": {"type": ["object", "null"], "description": "2.41.0: the answer {ids, at, user_id, user_name, via}, written once"},
            "choice_state": nul("string", description="2.41.0: open | answered | expired | withdrawn"),
            "portal": {"type": "boolean", "description": "2.63.0 (#1513): the customer sees it: a public answer, or the customer's own comment "
                       "(author id null, author.customer true)"}}},
        # 2.33.0 (#1076): the short quote of an answered message (comments, team chat, agent chat)
        "ReplyQuote": {"type": "object", "description": "2.33.0 (#1076): a short quote of the answered message; deleted = the original is gone "
                       "(deleted or trimmed: no text then)", "properties": {
            "id": {"type": "integer"}, "deleted": {"type": "boolean"}, "user_id": nul("integer", description="Its author (an agent's message: the agent)"),
            "name": {"type": "string"}, "text": {"type": "string", "description": "Plain text, at most 140 characters (+ …)"},
            "from": {"type": "string", "enum": ["user", "agent"], "description": "Agent chat only"}}},
        "CommentInput": {"type": "object", "additionalProperties": False, "required": ["body"], "properties": {"body": {"type": "string", "maxLength": MAX_COMMENT},
                         "reply_to": {"type": "integer", "description": "2.33.0 (#1076): answer this comment of the same task (else 400); its author is notified like a mention"},
                         "portal": {"type": "boolean", "description": "2.63.0 (#1513): a public answer the customer sees on the status page and by mail "
                                    "(only on a task with a customer report and with write access; default false = internal)"},
                         # 2.41.0 (#1383): answer buttons / an approval card like in the agent chat (agents only)
                         "choices": {"type": "array", "description": "2.41.0 (#1383, agents): answer buttons [{id, label, style?}] (or strings); only the newest "
                                     "comment's buttons stay live", "items": {"anyOf": [{"type": "string"}, {"type": "object"}]}},
                         "multi": {"type": "boolean", "description": "2.41.0: several buttons may be picked"},
                         "approval": {"type": "object", "description": "2.41.0 (#1383, agents): an approval card {title, what?, yes_label?, no_label?} with Yes / No; "
                                      "stays open until answered, expired or withdrawn"},
                         "expires_in": {"type": "integer", "description": "2.41.0: seconds an approval card stays open"}}},
        "CommentPage": page("Comment"),
        "TimeEntry": {"type": "object", "properties": {
            "id": {"type": "integer"}, "user_id": {"type": "integer"}, "user_name": {"type": "string"}, "task_id": nul("integer"),
            "list_id": nul("integer"), "title": {"type": "string"}, "start": {"type": "string", "format": "date-time"},
            "end": nul("string", format="date-time"), "seconds": {"type": "integer"}, "rounded": {"type": "integer"},
            "note": {"type": "string"}, "source": {"type": "string", "enum": list(TIME_SOURCES)}, "running": {"type": "boolean"},
            # 2.144.6 A (#2053)
            "billable": {"type": "boolean", "description": "may go onto an invoice (default true)"},
            "billed": {"type": "boolean", "description": "an invoice took it: only the note can change"}}},
        "TimeEntryInput": {"type": "object", "additionalProperties": False, "required": ["start"], "properties": {
            "task_id": {"type": "integer"}, "list_id": {"type": "integer"}, "start": {"type": "string", "description": "ISO date-time (local time if no offset)"},
            "end": {"type": "string"}, "minutes": {"type": "number"}, "note": {"type": "string", "maxLength": 500},
            "billable": {"type": "boolean", "description": "2.144.6: may go onto an invoice (default true)"}}},
        "TimeEntryPage": page("TimeEntry"),
        "Habit": {"type": "object", "properties": {
            "id": {"type": "integer"}, "name": {"type": "string"}, "color": {"type": "string"}, "goal": {"type": "integer"},
            "days": {"type": "string", "description": "Weekdays 1 (Mon) - 7 (Sun)"}, "per_week": {"type": "integer"}, "archived": {"type": "boolean"},
            "remind_at": {"type": "string"}, "remind_times": {"type": "array", "items": {"type": "string"}, "description": "Reminder times HH:MM (up to 6)"},
            "today": {"type": "integer"}, "last_30_days": {"type": "object", "additionalProperties": {"type": "integer"}}}},
        "HabitCheckedIn": {"allOf": [ref("Habit"), {"type": "object", "properties": {"date": date_s, "count": {"type": "integer"}}}]},
        "CheckinInput": {"type": "object", "additionalProperties": False, "properties": {
            "date": date_s, "count": {"type": "integer", "minimum": 0, "maximum": 1000, "description": "Absolute count for the day; default: one more"},
            "note": {"type": "string", "maxLength": 500}}},
        "HabitPage": page("Habit"),
        "ImportInput": {"type": "object", "required": ["file"], "properties": {
            "file": {"type": "string", "format": "binary", "description": f"The export file (at most {IMPORT_MAX_MB} MB, {IMPORT_MAX_TASKS} tasks)"},
            "dry_run": {"type": "boolean", "description": "true = preview only: runs the import and rolls it back"},
            "target": {"type": "string", "description": "new (default: one project per source list; an own project with the same name is reused) or the id of a project you can edit"},
            "mode": {"type": "string", "enum": ["sections", "lists"], "description": "Trello: one project with the Trello lists as sections (default) or one project per Trello list"},
            "archived": {"type": "string", "enum": ["skip", "done"], "description": "Trello: archived cards / lists skipped (default) or imported as done"},
            "completed": {"type": "string", "enum": ["import", "skip"], "description": "Completed tasks imported as done (default) or skipped"},
            "list_name": {"type": "string", "maxLength": LIST_NAME_MAX, "description": "Name of the new project (only when the file has one list)"},
            "priority_scale": {"type": "string", "enum": ["auto", "1", "4"], "description": "Todoist CSV: which PRIORITY value is p1 (auto = detected)"},
            # 2.87.9 (#1940)
            "space": {"type": "string", "description": "Workspace of the new projects: private or org:<id> of an own organisation (default: the default workspace of a new project); a project of the same name is reused only inside it"}}},
        "ImportReport": {"type": "object", "properties": {
            "source": {"type": "string"}, "dry_run": {"type": "boolean"}, "import_id": nul("integer", description="For the undo; null for a dry run"),
            "undo_until": nul("string", format="date-time"),
            "created": {"type": "object", "properties": {k: {"type": "integer"} for k in ("tasks", "subtasks", "done", "skipped", "lists", "sections", "assigned")}},
            "skipped": {"type": "integer", "description": "Already imported earlier (same source ids)"},
            "lists": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "list_id": {"type": "integer"}, "existing": {"type": "boolean"},
                                                                                "tasks": {"type": "integer"}, "skipped": {"type": "integer"}, "sections": {"type": "integer"}}}},
            "samples": {"type": "array", "items": {"type": "object"}},
            "warnings": {"type": "array", "items": {"type": "object", "properties": {"text": {"type": "string"}, "count": {"type": "integer"},
                                                                                   "examples": {"type": "array", "items": {"type": "string"}}}}},
            # 2.142.0 B (#2147)
            "columns": {"type": "array", "description": "Only source csv: which column of the file went into which field (notes = unknown columns)",
                        "items": {"type": "object", "properties": {"column": {"type": "string"}, "field": {"type": "string"}}}}}},
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
            "lists": {"type": "object", "description": "Project id -> bell (projects on default are left out)",
                      "additionalProperties": {"type": "string", "enum": list(BELL_MODES)}},
            "custom": {"type": "object", "description": "Project id -> the own event choice of projects on custom (events: "
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
        "AdminOrgActivityRow": {"type": "object", "properties": {
            "members": {"type": "integer"}, "last_login": nul("string", description="Date (YYYY-MM-DD) of the latest sign-in"),
            "storage_bytes": {"type": "integer"}, "lists": {"type": "integer"}, "tasks": {"type": "integer"}}},
        "AdminOrgActivity": {"type": "object", "description": "2.143.0: numbers only, no people or contents", "properties": {
            "orgs": {"type": "array", "items": {"allOf": [ref("AdminOrgActivityRow"), {"type": "object", "properties": {
                "id": {"type": "integer"}, "name": {"type": "string"}}}]}},
            "private": ref("AdminOrgActivityRow")}},
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
    tasks_filters = [q("list_id", "Only this project", {"type": "integer"}),
                     q("status", "open (default), done, wont_do or all", {"type": "string", "enum": ["open", "done", "wont_do", "all"]}),
                     q("due_from", "Due on or after (YYYY-MM-DD)", date_s), q("due_to", "Due on or before (YYYY-MM-DD)", date_s),
                     q("tag", "One of your tags or a project tag (without #)"), q("list_tag", "A project tag (without #)"),
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
        "/me/notifications": {"patch": op("Change your notification settings (events x News / push, the bell per project)", "Account",
                                          ok(ref("Notifications")) | errs("400", "404"), body=ref("NotificationsInput"), scope="write",
                                          desc="Partial: only the events / projects you send. A project bell: all = every event of that project, "
                                               "default = the events matrix, mute = only mentions of you and assignments to you, custom = your own choice "
                                               "per event ({mode: \"custom\", events: {comment: {news: true, push: false}, …}}; "
                                               "a ticked event comes from every task of the project, an unticked one never).")},
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
        "/lists": {"get": op("Projects you can see (own and shared)", L, ok(ref("ListPage")) | errs()),
                   "post": op("Create a project", L, ok(ref("List"), "Created", "201") | errs("400"), body=ref("ListInput"), scope="write")},
        "/lists/{id}": {"get": op("One project with its sections", L, ok(ref("ListDetail")) | errs("404"), [pid("id", "Project id")]),
                        "patch": op("Change a project (2.7.0)", L, ok(ref("List")) | errs("400", "403", "404"), [pid("id", "Project id")],
                                    body=ref("ListPatch"), scope="write",
                                    desc="Owner: name, color, kind, nag (default nag interval of its tasks), day_hours (hours per day / "
                                         "shift for the time sums). Owner and project admins: columns (2.14.0), archived (2.39.1). Members change only "
                                         "their own folder and view.")},
        "/lists/{id}/shift": {"post": op("Move a whole project in time", L, ok(ref("ShiftResult")) | errs("400", "403", "404", "409"),
                                         [pid("id", "Project id")], body=ref("ShiftInput"), scope="write",
                                         desc=f"Every open task with a date (subtasks too) moves by `days`, start and due, in one transaction; "
                                              f"tasks without a date stay. Moving later also moves dependent tasks in other projects whose project has "
                                              f"\"Move dependent tasks along\" on. Edit rights on the project. More than {SHIFT_MAX_TASKS} dated tasks: 409.")},
        "/lists/{id}/owner": {"post": op("Transfer the ownership of a project", L, ok(ref("OwnerResult")) | errs("400", "403", "404", "409"),
                                         [pid("id", "Project id")], body=ref("OwnerInput"), scope="write",
                                         desc="The owner hands the project to another active person (not an agent); the old owner stays "
                                              "as a project admin. An admin may take over a project whose owner is an agent or a disabled "
                                              "user (for themselves or another person). Agent tokens always get 403; inboxes 409.")},
        "/roadmap": {"get": op("All projects on one timeline: groups with summary spans, progress and dated tasks", "Roadmap",
                               ok(ref("Roadmap")) | errs("400"),
                               [q("from", "First day (default: 14 days ago)", date_s), q("to", f"Last day (default: from + 194 days, at most {ROADMAP_MAX_DAYS} days)", date_s),
                                q("projects_only", "true = no inbox (2.352.0: every other list is a project)", {"type": "boolean"}),
                                q("include_done", "true = completed tasks too", {"type": "boolean"})])},
        "/tasks": {"get": op("Tasks you can see (not in the trash), filtered, oldest first", T, ok(ref("TaskPage")) | errs("400", "404"), tasks_filters),
                   "post": op("Create a task (default: your inbox)", T, ok(ref("Task"), "Created", "201") | ok(ref("Task"), "Already created with this client_ref") | errs("400", "403", "404"),
                              body=ref("TaskCreate"), scope="write")},
        "/tasks/{id}": {"get": op("One task", T, ok(ref("Task")) | errs("404"), [pid()]),
                        "patch": op("Change a task (only the fields you send; send expect_updated_at)", T, ok(ref("TaskChanged")) | errs("400", "403", "404", "409"), [pid()],
                                    body=ref("TaskUpdate"), scope="write"),
                        "delete": op("Move a task (with its subtasks) to the trash", T,
                                     {"204": {"description": "In the trash (restorable in the app)"}} | errs("403", "404"), [pid()], scope="write")},
        "/tasks/{id}/complete": {"post": {**op("Complete a task", T, ok(ref("TaskCompleted")) | errs("400", "403", "404"), [pid(), {
            "name": "Idempotency-Key", "in": "header", "required": False, "schema": {"type": "string", "maxLength": 100},
            "description": "Optional, any write call: a repeat with the same key gets the first answer back and changes nothing"}], scope="write",
                                            desc="Recurring tasks move to their next date (next_due) and a completed copy stays in the history. "
                                                 "Completing a done task changes nothing. Recommended for recurring tasks: send expect_due (the due "
                                                 "date you read) -- a repeat of the call (or a tick elsewhere meanwhile) then does not advance the task "
                                                 "twice; the answer says skipped true."),
                                 # 2.270.0 C (#3022): optional body (old agents send none)
                                 "requestBody": {"required": False, "content": {"application/json": {"schema": {
                                     "type": "object", "additionalProperties": False, "properties": {
                                         "expect_due": nul("string", format="date", description="The due date you read; another date = not advanced again"),
                                         "expect_time": nul("string", description="Several times a day (TIMES=): the due_time you read")}}}}}}},
        "/tasks/{id}/waiting": {"put": op("Mark a task as waiting on someone outside (or change note / follow-up day)", T, ok(ref("Task")) | errs("400", "403", "404"),
                                          [pid()], body=ref("WaitingInput"), scope="write",
                                          desc="On the follow-up day the person it is for gets a reminder + News, following agents the event followup_due."),
                                "delete": op("Clear the waiting state", T, ok(ref("Task")) | errs("403", "404"), [pid()], scope="write")},
        "/tasks/{id}/reopen": {"post": op("Reopen a completed task", T, ok(ref("Task")) | errs("403", "404"), [pid()], scope="write")},
        # 2.35.0 (#1095): append one code snippet (a diff, a log, a proposal) without sending the whole list
        "/tasks/{id}/snippets": {"post": op("Add a code snippet to a task", T, ok({"type": "object", "properties": {"snippet": ref("Snippet"), "task": ref("Task")}},
                                                                                  "Created", "201") | errs("400", "403", "404"), [pid()],
                                            body={"type": "object", "additionalProperties": False, "required": ["code"], "properties": {
                                                "code": {"type": "string", "maxLength": 20000}, "lang": {"type": "string", "maxLength": 20},
                                                "path": nul("string", maxLength=300), "line": nul("integer", minimum=1)}},
                                            scope="write", desc="At most 20 snippets per task, 20000 characters each. Plain code, no Markdown.")},
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
        "/attachments/{id}/text": {"get": op("Read a task / comment file as text (2.34.0): PDF text layer, text files, 2.92.0: Word .docx / Excel .xlsx", C,
                                             ok(ref("AttachmentText")) | errs("400", "403", "404", "413", "503"),
                                             [pid("id", "Attachment id"), q("max_chars", "At most this many characters (1-200000, default 200000)", {"type": "integer"})],
                                             desc="Same rights as GET /attachments/{id}: agents only see files of projects shared with them (else 404). "
                                                  "PDFs are read on the server in a limited process (at most 20 MB, 1000 pages, 20 seconds); a scanned "
                                                  "PDF without a text layer answers no_text_layer: true; since 2.61.0 a scan or photo whose text the server "
                                                  "recognised in the background brings that text with source: ocr. Images answer kind image and the url "
                                                  "of the file; other files kind other. Results are cached per file content. 413 = larger than 20 MB, "
                                                  "503 = several PDFs are being read right now (Retry-After).")},
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
        "/search": {"get": op("Search titles, notes, links and custom fields of tasks; 2.33.0 (#1080) scope=messages: task comments, "
                              "team chat and agent chats you may read (MessageHit pages, newest first; agents: their own chats and the "
                              "projects shared with them)", S_,
                              ok({"oneOf": [ref("TaskPage"), page("MessageHit")]}) | errs("400", "503"),
                              [{**q("q", "Search text (words; case, accents and ä/ae do not matter; each word matches word beginnings)"), "required": True},
                               q("scope", "tasks (default) or messages", {"type": "string", "enum": ["tasks", "messages"]}),
                               q("fulltext", "2.116.0: 1 = ranked full-text search of tasks (title before notes) and their comments; "
                                 "each task once with match {where: title|notes|comment|field|file, snippet {text, marks}, comment_id}",
                                 {"type": "string", "enum": ["0", "1"]}),
                               q("art", "messages: only these kinds, comma-separated: c (comments), t (team chat), a (agent chat)"),
                               q("sender", "messages: only from this user id", {"type": "integer"}),
                               q("room", "messages: only this team chat room", {"type": "integer"}),
                               q("agent", "messages: only the chat with this agent (an agent: with this person)", {"type": "integer"}),
                               q("task", "messages: only the comments of this task", {"type": "integer"}), limit, cursor])},
        "/time/entries": {"get": op("Time entries (needs time tracking), newest first", TI, ok(ref("TimeEntryPage")) | errs("400", "403"),
                                    [q("from", "First day (default: 6 days ago)", date_s), q("to", "Last day (default: today)", date_s),
                                     q("scope", "mine (default) or all (everyone in shared projects)", {"type": "string", "enum": ["mine", "all"]}),
                                     q("list_id", "Only this project", {"type": "integer"}), q("task_id", "Only this task", {"type": "integer"}), limit, cursor]),
                          "post": op("Add a time entry", TI, ok(ref("TimeEntry"), "Created", "201") | errs("400", "403", "404"),
                                     body=ref("TimeEntryInput"), scope="write")},
        "/habits": {"get": op("Your habits with today's count and the last 30 days", H, ok(ref("HabitPage")) | errs())},
        "/habits/{id}/checkin": {"post": op("Check in a habit", H, ok(ref("HabitCheckedIn")) | errs("400", "404"), [pid("id", "Habit id")],
                                            body=ref("CheckinInput"), scope="write")},
        "/import/{source}": {"post": {**op("Import an export of another app", "Import", ok(ref("ImportReport")) | errs("400", "404", "409"),
                                           [{"name": "source", "in": "path", "required": True, "description": "Source format",
                                             "schema": {"type": "string", "enum": list(IMPORT_SOURCES)}}], scope="write",
                                           desc="Todoist (CSV, backup ZIP, Sync API JSON), Trello (board JSON), Asana (CSV), mstodo (Outlook / Microsoft To Do CSV or ICS), "
                                                "ics (VTODO), "
                                                # 2.142.0 B (#2147)
                                                "notion (export ZIP Markdown & CSV, also a single CSV / Markdown file), gtasks (Google Takeout ZIP or Tasks.json), "
                                                "clickup (CSV), jira (CSV), csv (any CSV, columns detected, see columns in the answer), markdown (checklists). "
                                                "People in a file are never matched to accounts by these six (their names go into the notes). "
                                                "Idempotent: tasks imported before are skipped. Nothing inside the file is fetched."),
                                        "requestBody": {"required": True, "content": {"multipart/form-data": {"schema": ref("ImportInput")}}}}},
        "/imports/{id}/undo": {"post": op(f"Undo an import (within {IMPORT_UNDO_HOURS} hours): removes what it created", "Import",
                                          ok(ref("ImportUndone")) | errs("404", "409"), [pid("id", "Import id")], scope="write")},
        "/admin/users": {"get": op("All users (admins, scope admin-read)", A, ok(ref("AdminUserPage")) | errs("403"), scope="admin-read")},
        "/admin/orgs/activity": {"get": op("2.143.0: activity per organisation and for people without one: members, last sign-in date, storage, projects, tasks (admins, scope admin-read)", A, ok(ref("AdminOrgActivity")) | errs("403"), scope="admin-read")},
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
    msgsearch_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q)  # 2.33.0 (#1080)
    from ..collab.chatpins import cpin_spec
    cpin_spec(paths, op, ok, errs, pid)  # 2.62.0 (#1848)
    from ..agents.schedules import sched_spec
    sched_spec(paths, schemas, op, ok, errs, ref, pid, nul)  # 2.34.0 (#272)
    from ..lists.playbook import pb_spec
    pb_spec(paths, schemas, op, ok, errs, ref, pid, nul)  # 2.39.0 (#1168)
    from ..lists.kpis import fx_spec
    fx_spec(paths, schemas, op, ok, errs, ref, pid)  # 2.43.0 (#1328)
    from ..lists.orgvis import ov_spec
    ov_spec(paths, schemas, op, ok, errs, ref, pid)  # 2.46.0 (#1603)
    from ..docs.v1 import docs_spec
    docs_spec(paths, schemas, op, ok, errs, ref, pid, q)  # 2.48.0 (#1111)
    from ..sheets.v1 import sheets_spec
    sheets_spec(paths, schemas, op, ok, errs, ref, pid, q)  # 2.89.0 C (#1916)
    from ..wiki.wkv1 import wkv_spec
    wkv_spec(paths, schemas, op, ok, errs, ref, pid, q)  # 2.200.0 C (#1781)
    from ..personal.v1focus import v1f_spec
    v1f_spec(paths, schemas, op, ok, errs, ref, pid, q)  # 2.116.0 D (#2067)
    from ..videos.v1 import vdr_v1_spec
    vdr_v1_spec(paths, schemas, op, ok, errs, ref, pid, q)  # 2.99.1 C (#1959)
    pkgc_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q)  # 2.23.0 (#463)
    from ..lists.envs import env_spec
    env_spec(paths, schemas, op, ok, errs, ref, pid)  # 2.60.0 D (#1514)
    from ..office.agentdocs import ofa_spec
    ofa_spec(paths, schemas, op, ok, errs, ref, pid, q)  # 2.51.0 A (#1348, #1350)
    from ..office.leads import lead_spec
    lead_spec(paths, schemas, op, ok, errs, ref, pid, q)  # 2.94.0 A (#1930): leads for agents
    from ..office.letteragent import lta_spec
    lta_spec(paths, schemas, op, ok, errs, ref, pid, q)  # 2.153.0 (#2031): letter drafts of agents
    from ..hub.absence import abs_spec
    abs_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q)  # 2.50.0 (#1195)
    hosting_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q)  # 2.24.0 (#907 #910)
    from ..notify.caps import notif_tpl_spec
    notif_tpl_spec(paths, schemas, op, ok, errs, ref, pid, nul, page)  # 2.33.0 (#927)
    from ..tasks.briefing import briefing_spec
    briefing_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q)  # 2.34.0 (#264)
    from ..lists.report import report_spec
    report_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q)  # 2.34.0 (#265)
    from ..tasks.stale import stale_spec
    stale_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q)  # 2.34.0 (#266)
    from ..personal.timegaps import timegaps_spec
    timegaps_spec(paths, schemas, op, ok, errs, ref, pid, nul, page, q)  # 2.34.0 (#269)
    from ..agents.agentpin import apin_spec
    apin_spec(paths, schemas, op, ok, errs, ref, pid, q)  # 2.51.0 C (#1352)
    from ..agents.agenttime import atm_spec
    atm_spec(paths, schemas, op, ok, errs, ref, pid, q)  # 2.51.0 C (#1353)
    from ..agents.lyprop import lyp_spec
    lyp_spec(paths, schemas, op, ok, errs, ref, pid, q)  # 2.55.0 B (#1066)
    from ..agents.importprop import aim_spec
    aim_spec(paths, schemas, op, ok, errs, ref, pid, q)  # 2.68.0 A (#1839)
    from ..agents.sheetprop import sht_spec
    sht_spec(paths, schemas, op, ok, errs, ref, pid, q)  # 2.126.1 B (#2125)
    from ..hub.agentdispo import adz_spec
    adz_spec(paths, schemas, op, ok, errs, ref, pid, q)  # 2.51.0 C (#1355)
    from ..files.v1 import files_spec
    files_spec(paths, schemas, op, ok, errs, ref, pid, q)  # 2.48.0 (#1207)
    from ..receipts.suggest import rc_spec
    rc_spec(paths, schemas, op, ok, errs, ref, pid, q)  # 2.48.0 (#1356)
    from ..tasks.related import rt9_spec
    rt9_spec(paths, schemas, op, ok, errs, ref, pid, q)  # 2.59.0 B (#1375)
    from ..tasks.review import rvw_spec
    rvw_spec(paths, schemas, op, ok, errs, ref, pid, nul)  # 2.60.0 C (#1512)
    from ..lists.points import spt_spec
    spt_spec(paths, schemas, op, ok, errs, ref, pid, nul)  # 2.60.0 B (#1511)
    from ..lists.sprints import spr_spec
    spr_spec(paths, schemas, op, ok, errs, ref, pid)  # 2.60.0 (#343)
    from ..agents.contractprop import ctr_spec
    ctr_spec(paths)  # 2.70.0 C (#1359): the kind notice of POST /agent/proposals
    from ..tasks.multilist import ml_spec
    ml_spec(paths, schemas, op, ok, errs, ref, pid)  # 2.71.0 B (#1459)
    from ..lists.rules import rul_spec
    rul_spec(paths, schemas, op, ok, errs, ref, pid)  # 2.71.0 A (#1457)
    scope_refine(paths)
    _SPEC["s"] = {
        "openapi": "3.1.0",
        "info": {"title": f"{APP_NAME} REST API", "version": API_VERSION,
                 "description": "Personal access tokens (Settings > Account > API tokens) as `Authorization: Bearer abk_...`. "
                                "Every request acts as the token's user and sees exactly what that user sees. Dates are local dates "
                                "of the server's time zone (YYYY-MM-DD), times HH:MM, timestamps ISO 8601 in UTC. Projects are called lists in the API (list_id, /lists; kind=list|project is stored but no longer evaluated, tracked projects have a status). Collections come in pages: "
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
