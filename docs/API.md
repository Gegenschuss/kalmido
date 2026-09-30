# Kalmido REST API and webhooks

Kalmido has a small, versioned REST API under `/api/v1` for scripts and integrations (Home Assistant, n8n, a shell
script, your own tools) and outgoing **webhooks** that tell other systems when something changes. Both work as one user:
whatever that user can see and change in the app, and nothing more.

- [Personal access tokens](#personal-access-tokens)
- [Basics](#basics): URLs, formats, errors, pages, limits
- [Endpoints](#endpoints)
- [Roadmap](#roadmap): all lists on one timeline, moving a whole list
- [Examples](#examples): curl, Home Assistant, n8n, a shell script
- [Webhooks](#webhooks): events, payload, signature, retries
- [Behind a reverse proxy](#behind-a-reverse-proxy)
- AI agents and bots (events, long-polling, jobs, chat, approvals) and the MCP server: [AGENTS.md](AGENTS.md), [mcp/](../mcp/)

The machine-readable description is an OpenAPI 3.1 document at **`/api/v1/openapi.json`** on your server (it contains no
data and needs no token). Import it into Postman, Bruno, Insomnia or an n8n HTTP node, or read it with any OpenAPI viewer.

## Personal access tokens

Create a token under **Settings > Account > API tokens**:

- **Name**: what uses it ("Home Assistant", "backup script").
- **Access** (scopes):
  - `read` (always included): lists, tasks, subtasks, tags, comments, time entries, habits, search.
  - `write`: also create, change, complete, reopen and delete (to the trash) tasks, create lists, comment, add time
    entries, check in habits.
  - `admin-read` (admins only): `GET /api/v1/admin/users`, `GET /api/v1/admin/status` and (2.2.1) `GET /api/v1/admin/agents/{id}/audit`. Checked on every request:
    if the user stops being an admin, the scope stops working.
- **Expires**: in 30 days, 90 days, a year, or never.

The token looks like `abk_` followed by 43 random characters (256 bits). It is **shown once**; Kalmido only keeps its
SHA-256 hash, so a lost token cannot be shown again: revoke it and create a new one. The list shows the first
characters, the access, the expiry and when it was last used. Revoking works immediately. A disabled or deleted user's
tokens stop working at once.

Send it in every request:

```
Authorization: Bearer abk_...
```

Only the token counts: the API never accepts the app's login cookie or a proxy login header, so a web page on another
site cannot use your browser session for it, and API requests need no `X-Requested-With` header. There are no CORS
headers: call the API from a server, a script or an app, not from JavaScript on another website.

## Basics

| | |
|---|---|
| Base URL | `https://tasks.example.com/api/v1` |
| Format | JSON in and out (`Content-Type: application/json`) |
| Dates | `YYYY-MM-DD`, local dates in the server's time zone (`TZ`) |
| Times | `HH:MM`, local; `due_time: null` = all day |
| Timestamps | ISO 8601 in UTC (`2026-09-29T08:15:00+00:00`) |
| Priorities | `none`, `low`, `medium`, `high` (numbers 0, 1, 3, 5 are accepted on input) |
| Status | `open`, `done`, `wont_do` |

**Errors** always look the same, with a fitting HTTP status:

```json
{"error": {"code": "not_found", "message": "Not found"}}
```

`code` is one of `invalid` (400), `unknown_field` (400, see below), `unauthorized` (401: missing, invalid or expired
token), `forbidden` (403: scope, list role or a module that is switched off), `not_found` (404: also for things the user
cannot see, so their existence is not revealed), `method_not_allowed` (405), `conflict` (409), `rate_limited` (429, with
`Retry-After`). The message is in the user's language.

**Unknown fields and parameters are refused** (400) instead of being ignored, so a typo does not silently do nothing.
Since 2.2.1 an unknown JSON field answers with its own code and names every field the endpoint does not know; nothing
is changed:

```json
{"error": {"code": "unknown_field", "message": "Unknown field: colour", "fields": ["colour"]}}
```

The one alias: a task's description is `notes` here and `content` in the app's own web API (`/api`); each accepts the
other name too (both at once with different values: 400 `invalid`). The web API itself stays lenient so the app never
breaks: it ignores unknown fields as before, but names them in the response header `X-Kalmido-Unknown-Fields` and logs a
warning (once per endpoint and set of names per hour, never values).

**Pages**: endpoints that return lists answer `{"data": [...], "next_cursor": "..."}`. Pass `?cursor=<next_cursor>` for
the next page; `next_cursor: null` means there is no more. `?limit=` sets the page size (1-500, default 100).

**Limits**: 120 requests per token and minute (`KALMIDO_API_RATE`), then 429 with `Retry-After: 60`. Requests with an
invalid token count per client address: after 30 within 15 minutes that address gets 429 for a while, and the admins
get an alert.

**Switches**: time entries need time tracking, both on the server (admin) and in the user's own settings; otherwise
those endpoints answer 403. Since 2.0.6 comments no longer need collaboration: writing one needs the user's *Comments*
module (otherwise 409); `@mentions`, notifications and reactions need collaboration on the server. `KALMIDO_API=0` turns the whole API off (every `/api/v1`
request answers 404).
The other modules only change what the app shows: with *Dependencies* or *Custom fields* switched off, tasks still
carry `blocked` and `fields`, and `fields` can still be written (the same as the timeline, kanban or project progress
modules). `GET /me` reports all four under `features`: `collaboration`, `time_tracking`, `dependencies`,
`custom_fields`.

**List types**: every list has `kind` (`list`, `checklist` or `project`). Time entries, dependencies, custom field
values and a project status need a project list (both lists for a dependency): otherwise `409 conflict` with a message
such as *Make this list a project to track time*. Time entries of lists that are not projects (any more) are left out
of `GET /time/entries`. The older `checklist` boolean still works: it reads as `kind == "checklist"`, and
`checklist: true` when creating a list makes a checklist.

**Dependent tasks move along**: if a list has *Move dependent tasks along* switched on (list dialog in the app), a
`PATCH /tasks/{id}` that postpones a task's `due` also moves the open tasks of that list that wait on it and would now
start too early, by the same number of days (their history shows it). Moving a task earlier never moves anything.

**List roles** (1.10.0): a token sees exactly what its user sees. For a `participant` of a shared list every endpoint
returns only the tasks assigned to that user, their subtasks (all levels) and, read-only, the main task of an assigned
subtask with `context: true` (no `notes`, `url`, files, fields or comments; `GET /tasks/{id}/comments` answers 404 for
it). Other tasks of the list answer 404, never appear in `GET /tasks`, `/search`, `/tags`, `/roadmap` or
`/time/entries` (only the participant's own entries and those on their tasks), and a participant's webhooks fire only
for their own tasks. A participant can create tasks in the list (always assigned to themselves; `assignee_id` of
someone else: 403) and subtasks of their tasks, change and complete their tasks; `DELETE /tasks/{id}`, moving a task to
another list and changing `assignee_id` answer 403. Roles are set in the app (owner and list admins).

**History and notifications**: changes through the API go through the same code as the app. The task history shows
them with a small *via API* label, and assignments, mentions and completions notify people exactly as if the change
had been made in the app. Webhooks fire too.

## Endpoints

| Method and path | Scope | What it does |
|---|---|---|
| `GET /me` | read | The token's user, its scopes and expiry, which modules are on, and (2.1.0) `notifications`: `events` (per event `{news, push}`, `news` null = the event has no News) and `lists` (list id -> bell `all` / `mute`; lists on `default` are left out) |
| `PATCH /me/notifications` | write | 2.1.0: change them partially: `{events?: {event: {news?, push?}}, lists?: {list_id: "all" \| "default" \| "mute"}}`. Events: `comment`, `reply`, `follow`, `mention`, `assign`, `newtask`, `complete`, `status`, `share`, `unblock`, `approval`, `followup`, `reminder` (push only) |
| `GET /lists` | read | Lists the user can see: own and shared, with role (`owner`, `admin`, `edit` = member, `participant`, `view` = viewer), checklist flag, progress, `icon` (URL of the list's own picture, empty = none; set in the app), `agent_tidy`, and (2.0.8) its sections `[{id, name}]` |
| `POST /lists` | write | Create a list: `{name, color?, folder?, kind?, checklist?}` (`kind`: `list` default, `checklist`, `project`) |
| `GET /lists/{id}` | read | One list with its sections |
| `GET /lists/{id}/repos` | read | 2.2.0: repositories connected to a (project) list: `provider` (`github` / `gitea`), `base_url`, `web_url`, `owner`, `repo`, `full_name`, `default_branch`, `status` (`new` / `ok` / `error`), `error`, `polled_at`. Never a token; connecting is only in the app (list owner / list admins). Lists also carry `repos` |
| `POST /lists/{id}/owner` | write | 2.1.2: transfer the ownership `{user_id}` to another active person (never an agent); the old owner stays as a list admin. Admins may take over a list whose owner is an agent or a disabled user. Agent tokens always `403`, inboxes `409` |
| `GET /tasks` | read | Tasks (not in the trash), oldest first; filters below |
| `POST /tasks` | write | Create a task (default list: the user's inbox) |
| `GET /tasks/{id}` | read | One task |
| `PATCH /tasks/{id}` | write | Change the fields you send |
| `DELETE /tasks/{id}` | write | Move the task with its subtasks to the trash (204); restorable in the app |
| `POST /tasks/{id}/complete` | write | Complete; recurring tasks move to their next date (`next_due`) |
| `POST /tasks/{id}/reopen` | write | Reopen a completed task |
| `PUT /tasks/{id}/waiting` · `DELETE …` | write | 2.1.0: waiting on external: `{note?, until? (YYYY-MM-DD)}` sets / changes it, `DELETE` ends it. Every task has `waiting` (`null` or `{note, until, since, by}`); `GET /tasks?waiting=true` lists them |
| `GET /tasks/{id}/subtasks` | read | Subtasks |
| `POST /tasks/{id}/subtasks` | write | Add a subtask |
| `GET /tasks/{id}/comments` | read | Comments |
| `POST /tasks/{id}/comments` | write | Comment: `{body}`; mention someone with `<@user_id>`; agents may add a tidy `suggestion` (see [AGENTS.md](AGENTS.md)) |
| `POST /comments/{id}/reactions` | write | React: `{emoji}` = `up`, `down`, `heart` or any single emoji |
| `DELETE /comments/{id}/reactions/{emoji}` | write | Take your reaction back |
| `GET /roadmap` | read | All lists on one timeline: groups with summary spans, progress and dated tasks, see [Roadmap](#roadmap) |
| `POST /lists/{id}/shift` | write | Move every open dated task of a list by `{days}` in one transaction, see [Roadmap](#roadmap) |
| `GET /tags` | read | The user's personal tags (`kind: personal`) and the tags of the lists they see (`kind: list`, with `list_id`, `color`), with task counts |
| `GET /lists/{id}/tags` | read | The list tags of a list (shared by its members) |
| `POST /lists/{id}/tags` | write | Create a list tag `{name, color?}` (members with edit rights) |
| `PATCH /lists/{id}/tags/{tag_id}` · `DELETE …` | write | Rename / recolour · delete a list tag (removed from every task) |
| `GET /agents` | read | Agents you share a list with: status and job counts |
| `GET /agent` … `/agent/events` … `/agent/jobs` … `/agent/chats` · `PUT /agent/status` · `POST /tasks/{id}/tidy` | read / write | **Agent tokens only**: the agent protocol, see [AGENTS.md](AGENTS.md); the status may name the task it works on (`task_id`, shows "… is writing" there) |
| `POST /agent/usage` · `GET /agent/usage?from=&to=&group=` | write / read | **Agent tokens only** (2.1.1): report model usage (numbers and ids only), read it grouped by day, task, list or model; over its hard limit an agent gets `429` on every other call, see [AGENTS.md](AGENTS.md#usage-and-limits) |
| `GET /search?q=` | read | Search titles, notes, links and custom field values |
| `GET /time/entries` | read | Time entries (time tracking), newest first: `from`, `to`, `scope=mine|all`, `list_id`, `task_id` |
| `POST /time/entries` | write | Add one: `{task_id or list_id, start, end or minutes, note?}` |
| `GET /habits` | read | The user's habits with today's count and the last 30 days |
| `POST /habits/{id}/checkin` | write | `{date?, count?, note?}`: without `count` one more for the day |
| `POST /import/{source}` | write | Import an export file (multipart), see [Import](#import) |
| `POST /imports/{id}/undo` | write | Undo an import within 24 hours |
| `GET /admin/users` | admin-read | All users (no secrets) |
| `GET /admin/status` | admin-read | Version, counts, update available (`latest_version`, `update_checked_at`, `update_error`), last backup, pending webhooks |
| `GET /admin/agents/{id}/audit` | admin-read | 2.2.1: the agent's audit log, newest first: `{id, at, agent_id, agent_name, method, route, status, task_id, list_id, ms, denied}`; `?status=2xx\|3xx\|4xx\|5xx\|denied`, `?day=YYYY-MM-DD`, cursor pages (see [AGENTS.md](AGENTS.md#audit-log)) |
| `GET /openapi.json` | none | This API as OpenAPI 3.1 |

**Task filters** (`GET /tasks`): `list_id`, `status` (`open` default, `done`, `wont_do`, `all`), `due_from`, `due_to`,
`tag` (one of your tags or a list tag, without `#`), `list_tag` (only list tags), `assignee` (`me`, `none` or a user id), `updated_since` (ISO timestamp),
`parent_id`, `top_level=true`, `waiting=true|false` (2.1.0), `limit`, `cursor`.

**Compact tasks** (2.0.8): `GET /tasks?fields=compact` returns only `id`, `title`, `list_id`, `section_id`, `parent_id`,
`status`, `due`, `due_time`, `priority`, `tags`, `list_tags` and `assignee_id` per task, for scanning a large list
(an agent, a script). `fields=full` (the default) returns everything; any other value is a `400`.

**A task** (what the API returns):

```json
{
  "id": 42, "list_id": 7, "section_id": null, "parent_id": null,
  "title": "Dentist", "notes": "call **first**", "priority": "high", "status": "open",
  "due": "2026-10-01", "due_time": "15:00", "start": null, "duration": 30,
  "reminders": [0, 15], "repeat": "", "repeat_from": "due", "url": null,
  "tags": ["health"], "list_tags": ["urgent"], "pinned": false, "assignee_id": null,
  "created_by": 1, "completed_by": null,
  "created_at": "2026-09-29T08:15:00+00:00", "updated_at": "2026-09-29T08:15:00+00:00", "completed_at": null,
  "deleted": false, "fields": {"3": "opt2"}, "blocked": false, "comment_count": 0,
  "attachments": [{"id": 5, "name": "x-ray.pdf", "mime": "application/pdf", "size": 81234}]
}
```

Writable fields for `POST /tasks` and `PATCH /tasks/{id}`: `title` (required on create), `notes`, `list_id`,
`section_id`, `parent_id`, `priority`, `due`, `due_time`, `start`, `duration` (minutes), `reminders` (minutes before the
due time), `repeat` (an RRULE body such as `FREQ=WEEKLY;BYDAY=MO`, daily or longer), `repeat_from` (`due` / `done`),
`url`, `tags` (replaces your tags on the task), `list_tags` (replaces the list tags of the task; names, missing ones are
created when you may change the list), `assignee_id` (someone who can see the list), `pinned`, `fields`
(custom field values by field id); `content` is accepted as an alias of `notes` (2.2.1). `tags` are personal: every user has their own tags on a shared task; `list_tags`
belong to the list and everyone in it sees them. Attachments are
listed (name, type, size) but not transferred through the API.

**Code** (2.2.0, `GET /tasks/{id}` only): in a list connected to a repository a task also has `code` (the linked pull
requests `[{repo, n, title, state: open | merged | closed, ci: success | failure | pending | null, author, url, branch}]`,
open first, and the latest commits `[{repo, sha, short, message, author, url, branch, at}]`, at most 5 each) and `repo`
(the list's first repository: `provider`, `base_url`, `web_url`, `api_url`, `owner`, `repo`, `full_name`,
`default_branch`, a suggested `branch` `kalmido-<id>-<slug>`, `prs`, `commits`, and `others` when the list has more).
Tasks in `GET /tasks` carry `code` when something is linked. See *Git integration* in the README.

## Roadmap

`GET /roadmap` returns every list the user can see (not archived) as a group, in sidebar order (inbox, lists without
a folder, then folder by folder), with a summary span and the dated tasks inside a window.

| Parameter | Default | Meaning |
|---|---|---|
| `from`, `to` | 14 days ago, `from` + 194 days | Window for `tasks` (at most 1100 days); tasks overlapping it by start..due |
| `projects_only` | `false` | Only lists of the type `project` |
| `include_done` | `false` | Completed tasks too (`status: "done"`) |

```json
{
  "from": "2026-09-15", "to": "2027-03-28", "projects_only": false, "folders": ["Clients"],
  "groups": [{
    "list": {"id": 7, "name": "Website relaunch", "kind": "project", "folder": "Clients", "progress": {"done": 2, "total": 7, "overdue": 0, "next_due": "2026-10-03"}, "...": "as GET /lists"},
    "folder": "Clients", "can_edit": true,
    "span": {"start": "2026-09-25", "end": "2026-10-31"},
    "open_dated": 5, "undated": 1,
    "tasks": [{"id": 42, "parent_id": null, "title": "Wireframes", "start": "2026-09-25", "due": "2026-10-01",
               "status": "open", "priority": "medium", "assignee_id": 3}]
  }],
  "deps": [{"task_id": 43, "blocker_id": 42}]
}
```

`span` covers **all** open tasks with a date of the list (also outside the window): the earliest start (or due date
without a start) to the latest due date; `null` when there are none. `deps`: the returned tasks and what they wait on
(only blockers the user can see).

`POST /lists/{id}/shift` with `{"days": 7}` (-3650 to 3650, not 0) moves every open task with a date in the list,
subtasks included, by that many calendar days: `start` and `due`, so the length stays; the time of day, tasks without a
date, completed tasks and the trash stay as they are. Everything happens in one transaction. Moving later also moves
tasks in other lists that wait on a moved task and would now start too early, when their list has *Move dependent
tasks along* on (same rules as for a single task). Needs edit rights on the list (403 for viewers and participants, 404 when
the list is not visible); more than 500 dated tasks: 409 with a message. The answer lists the old and new dates:

```json
{"ok": true, "count": 5, "days": 7,
 "moved": [{"id": 42, "title": "Wireframes", "start": "2026-10-02", "due": "2026-10-08", "prev_start": "2026-09-25", "prev_due": "2026-10-01"}],
 "shifted": [{"id": 77, "title": "Campaign concept", "start": "2026-10-25", "due": "2026-11-01", "prev_start": "2026-10-18", "prev_due": "2026-10-25"}]}
```

To undo it, `PATCH` each task back to `prev_start` / `prev_due` (the app sends them in one batch request, with the
new dates as `_prev` so a change made in the meantime is kept).

```sh
curl -s -H "Authorization: Bearer $TOKEN" "$KALMIDO/api/v1/roadmap?projects_only=true" | jq '.groups[] | {name: .list.name, span}'
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"days": 7}' "$KALMIDO/api/v1/lists/7/shift"
```

## Import

The importers of *Settings > Data > Import* are available to scripts. `source` is one of `todoist`, `trello`,
`asana`, `mstodo` (Outlook / Microsoft To Do CSV or ICS) and `ics`. The body is `multipart/form-data` with the file
in `file` and these optional fields:

| Field | Values | |
|---|---|---|
| `dry_run` | `true` | Preview: runs the import and rolls it back; the answer shows exactly what would happen |
| `target` | `new` (default) or a list id | `new`: one list per source list (an own list with the same name is reused). A list id: everything into that list (you need edit rights); several source lists become sections |
| `mode` | `sections` (default), `lists` | Trello: the board's lists as sections of one list, or as lists in a folder |
| `archived` | `skip` (default), `done` | Trello: archived cards and lists |
| `completed` | `import` (default), `skip` | Completed tasks |
| `list_name` | text | Name of the new list when the file has only one |
| `priority_scale` | `auto` (default), `1`, `4` | Todoist CSV: which `PRIORITY` value means p1 |

```sh
# preview, then import
curl -s -H "Authorization: Bearer $TOKEN" -F file=@Groceries.csv -F dry_run=true "$KALMIDO/api/v1/import/todoist"
curl -s -H "Authorization: Bearer $TOKEN" -F file=@board.json -F mode=lists "$KALMIDO/api/v1/import/trello"
```

The answer: `created` (`tasks`, `subtasks`, `done`, `lists`, `sections`, `assigned`), `skipped` (already imported
before: the same id in the other app), `lists` (per target list: name, id, existing or new, counts), `samples` (the
first rows), `warnings` (`text`, `count`, `examples`: what could not be mapped exactly and where it went instead),
`import_id` and `undo_until`. Importing the same file again skips what is already there.
`POST /imports/{import_id}/undo` removes what that import created (tasks, sections, lists that are empty then) within
24 hours; answer `{tasks, lists, sections, kept_lists, kept_tasks}`, `409` when it was undone already or is too old.
Limits: 20 MB and 20,000 tasks per file, 30 imports (previews included) per user within 10 minutes. Nothing inside a
file is fetched; imports do not send one webhook per task.

## Examples

Replace `tasks.example.com` with your address and keep the token in a variable:

```sh
export KALMIDO=https://tasks.example.com
export TOKEN=abk_...
```

**Who am I?**

```sh
curl -s -H "Authorization: Bearer $TOKEN" "$KALMIDO/api/v1/me"
```

**Create a task**

```sh
curl -s -X POST "$KALMIDO/api/v1/tasks" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"title": "Buy milk", "due": "2026-10-01", "priority": "medium", "tags": ["shopping"]}'
```

**Complete it** (the answer is the task; for a recurring task `next_due` says where it moved)

```sh
curl -s -X POST -H "Authorization: Bearer $TOKEN" "$KALMIDO/api/v1/tasks/42/complete"
```

**Today's open tasks** (everything due today or earlier, like the *Today* view)

```sh
curl -s -H "Authorization: Bearer $TOKEN" \
  "$KALMIDO/api/v1/tasks?status=open&due_to=$(date +%F)&limit=500" | jq -r '.data[] | "\(.due) \(.title)"'
```

**Move a task to another list and change the date**

```sh
curl -s -X PATCH "$KALMIDO/api/v1/tasks/42" -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"list_id": 7, "due": "2026-10-03", "due_time": "09:30"}'
```

**All pages of a long result**

```sh
cursor=""
while :; do
  page=$(curl -s -H "Authorization: Bearer $TOKEN" "$KALMIDO/api/v1/tasks?status=all&limit=500${cursor:+&cursor=$cursor}")
  echo "$page" | jq -r '.data[].title'
  cursor=$(echo "$page" | jq -r '.next_cursor // empty')
  [ -z "$cursor" ] && break
done
```

**Log 45 minutes on a task, check in a habit**

```sh
curl -s -X POST "$KALMIDO/api/v1/time/entries" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"task_id": 42, "start": "2026-09-29T09:00", "minutes": 45, "note": "planning"}'
curl -s -X POST -H "Authorization: Bearer $TOKEN" "$KALMIDO/api/v1/habits/3/checkin"
```

### Home Assistant

A token with *write* access in `secrets.yaml`:

```yaml
kalmido_auth: "Bearer abk_..."
```

`configuration.yaml`: services to add and complete tasks, and a sensor with the number of tasks due today.

```yaml
rest_command:
  kalmido_add_task:
    url: "https://tasks.example.com/api/v1/tasks"
    method: POST
    headers:
      Authorization: !secret kalmido_auth
    content_type: "application/json"
    payload: '{"title": {{ title | tojson }}, "due": {{ (due | default(now().date() | string)) | tojson }}, "tags": ["home"]}'
  kalmido_complete_task:
    url: "https://tasks.example.com/api/v1/tasks/{{ task_id }}/complete"
    method: POST
    headers:
      Authorization: !secret kalmido_auth

sensor:
  - platform: rest
    name: Kalmido due today
    resource_template: "https://tasks.example.com/api/v1/tasks?status=open&due_to={{ now().date() }}&limit=500"
    headers:
      Authorization: !secret kalmido_auth
    value_template: "{{ value_json.data | length }}"
    json_attributes: [data]
    scan_interval: 300
```

Use it in an automation, for example when the washing machine is done:

```yaml
action:
  - service: rest_command.kalmido_add_task
    data:
      title: "Hang up the laundry"
```

For the other direction (Kalmido tells Home Assistant), add a Home Assistant webhook trigger and point an Kalmido
webhook at `https://homeassistant.example.com/api/webhook/<id>`. Home Assistant cannot check the signature, so use a
long random webhook id.

### n8n

**Calling the API**: an *HTTP Request* node with *Authentication: Generic Credential Type > Header Auth*, name
`Authorization`, value `Bearer abk_...`. For example *Method* `POST`, *URL* `https://tasks.example.com/api/v1/tasks`,
*Send Body* JSON `{"title": "{{ $json.subject }}", "notes": "{{ $json.from }}"}` turns incoming e-mails into tasks.
Or import `/api/v1/openapi.json` to get every operation.

**Receiving webhooks**: a *Webhook* node (POST, *Raw Body* on), then a *Code* node that checks the signature before
anything else (the secret in an n8n credential or variable):

```js
const crypto = require('crypto');
const secret = $env.KALMIDO_WEBHOOK_SECRET;            // whsec_...
const item = $input.first();
const raw = item.binary?.data ? Buffer.from(item.binary.data.data, 'base64').toString('utf8') : JSON.stringify(item.json.body);
const sig = Object.fromEntries(item.json.headers['x-kalmido-signature'].split(',').map(p => p.split('=')));
const want = crypto.createHmac('sha256', secret).update(`${sig.t}.${raw}`).digest('hex');
if (!crypto.timingSafeEqual(Buffer.from(want), Buffer.from(sig.v1)) || Math.abs(Date.now() / 1000 - sig.t) > 300) {
  throw new Error('bad signature');
}
return [{json: JSON.parse(raw)}];
```

### A shell script

`kalmido` (needs `curl` and `jq`): `kalmido add "Call the bank" tomorrow`, `kalmido today`, `kalmido done 42`.

```sh
#!/bin/sh
set -eu
: "${KALMIDO:?set KALMIDO=https://tasks.example.com}" "${TOKEN:?set TOKEN=abk_...}"
api() { curl -fsS -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" "$@"; }
case "${1:-today}" in
  add)   due=$(date -d "${3:-today}" +%F)
         api -X POST "$KALMIDO/api/v1/tasks" -d "$(jq -n --arg t "$2" --arg d "$due" '{title: $t, due: $d}')" | jq -r '"#\(.id) \(.title)"' ;;
  done)  api -X POST "$KALMIDO/api/v1/tasks/$2/complete" | jq -r '"done: \(.title)" + (if .next_due then " (next: \(.next_due))" else "" end)' ;;
  today) api "$KALMIDO/api/v1/tasks?status=open&due_to=$(date +%F)&limit=500" | jq -r '.data[] | "#\(.id)  \(.due) \(.due_time // "     ")  \(.title)"' ;;
  *)     echo "usage: kalmido add TITLE [DATE] | done ID | today" >&2; exit 2 ;;
esac
```

## Webhooks

Under **Settings > Integrations > Webhooks** every user can register up to 10 URLs. Kalmido then sends a `POST` with a
JSON body whenever one of the chosen events happens **in a list that user can see** (their own lists and lists shared
with them; with collaboration switched off only their own). What they cannot see is never sent.

| Event | When |
|---|---|
| `task.created` | a task (or subtask) was created |
| `task.updated` | title, notes, date, priority, assignee, list, section, repetition, link, a custom field, dependencies, ... changed; `data.changes` lists what |
| `task.completed` | a task was completed (also through a public list link) |
| `task.reopened` | a completed task was opened again |
| `task.deleted` | moved to the trash (`permanent: false`) or deleted for good (`permanent: true`) |
| `comment.created` | someone commented (only if the webhook's owner has collaboration on) |
| `list.shared` | a list was shared: sent to the owner and to the person it was shared with |
| `ping` | the *Send test* button |

The changes of one request are combined: creating a task sends `task.created` (not also `task.updated`); completing
sends `task.completed` only.

**Payload**

```json
{
  "id": "4f0d7e8e-1c1b-4b8f-a0a5-9f7d2c1e6a10",
  "event": "task.completed",
  "created_at": "2026-09-29T08:15:03+00:00",
  "webhook_id": 3,
  "actor": {"id": 1, "name": "Alice"},
  "via": "web",
  "data": {
    "task": {"id": 42, "title": "Buy milk", "status": "done", "tags": ["shopping"], "...": "same fields as the API"},
    "list": {"id": 7, "name": "Groceries"}
  }
}
```

- `id` = the delivery id, also in the `X-Kalmido-Delivery` header, **the same for every retry**: use it to ignore
  duplicates.
- `actor` = who made the change (`null` for someone using a public list link), `via` = `web` (the app), `api` or
  `public_link`.
- `data.task` has the same fields as the API, as the webhook's owner sees the task (their own tags). `data.changes`
  (for `task.updated`), `data.permanent` (for `task.deleted`), `data.comment` (`{id, author_id, text, created_at,
  files}` for `comment.created`), `data.member` and `data.role` (for `list.shared`).
- Never in a payload: passwords, tokens, secrets, attachment contents, Paperless data.

**Headers**

| Header | |
|---|---|
| `X-Kalmido-Event` | the event |
| `X-Kalmido-Delivery` | the delivery id (as in the body) |
| `X-Kalmido-Attempt` | 1 for the first try, 2-5 for retries |
| `X-Kalmido-Signature` | `t=<unix time>,v1=<hex HMAC-SHA256>` |
| `User-Agent` | `Kalmido/<version> (webhook)` |

**Checking the signature.** Every webhook has its own signing secret (`whsec_...`), shown once when you create it (and
when you create a new one). The signature is the HMAC-SHA256 with that secret over `<t>.<raw body>`, where `<t>` is the
number from the header. Check it **before** you parse the body, with a constant-time comparison, and reject requests
whose `t` is more than **5 minutes** away from your clock (the replay window): a captured request cannot be sent again
later. Deduplicate by the delivery id to also catch replays within the window.

Python:

```python
import hashlib, hmac, time

def verify(raw_body: bytes, header: str, secret: str, window=300) -> bool:
    parts = dict(p.split("=", 1) for p in header.split(","))
    if abs(time.time() - int(parts["t"])) > window:
        return False
    want = hmac.new(secret.encode(), parts["t"].encode() + b"." + raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, parts["v1"])
```

Node.js:

```js
const crypto = require('crypto');
function verify(rawBody, header, secret, window = 300) {
  const p = Object.fromEntries(header.split(',').map(x => x.split('=')));
  if (Math.abs(Date.now() / 1000 - Number(p.t)) > window) return false;
  const want = crypto.createHmac('sha256', secret).update(`${p.t}.${rawBody}`).digest('hex');
  return want.length === p.v1.length && crypto.timingSafeEqual(Buffer.from(want), Buffer.from(p.v1));
}
```

Shell (for a quick test with a saved body):

```sh
t=${SIG#t=}; t=${t%%,*}; v1=${SIG##*v1=}
printf '%s.' "$t" | cat - body.json | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}' | grep -qx "$v1" && echo ok
```

**Delivery.** Your endpoint should answer with any 2xx status within 10 seconds; the response body is ignored. Anything
else (another status, a redirect, a timeout, a refused connection) counts as a failure and is **retried after 1 minute,
5 minutes, 30 minutes and 2 hours**. If the fifth attempt fails as well, the webhook is **turned off** (*turned off after
failed deliveries* in the settings) and the admins get an alert; switch it back on once the receiver works. Deliveries
are not guaranteed to arrive in order (a retry can come after a newer event): use `created_at` and the task's
`updated_at`. The settings show the last 50 attempts per webhook (event, status, time, duration; never bodies) and have
a *Send test* button.

**Which URLs are allowed.** Only `https://` to public addresses. Every address the host name resolves to is checked when
connecting (so DNS tricks do not help): private networks (RFC 1918), loopback, link-local
(169.254.x, cloud metadata), CGNAT (100.64.0.0/10, e.g. VPN overlays), IPv6 unique-local and similar are refused. Servers in your
own network work once an admin lists them under *Settings > Administration > Advanced > Allowed internal hosts* (the same
list as for calendar subscriptions) or in `KALMIDO_WEBHOOK_ALLOW_HOSTS`; only those may also use plain `http://`.
Redirects are never followed. `KALMIDO_WEBHOOKS=0` turns webhooks off.

## Behind a reverse proxy

If your proxy puts a login (Authelia, Authentik, oauth2-proxy, ...) in front of Kalmido, API clients cannot pass it:
they have a token, not a login cookie. Let requests to `/api/v1/` **that carry an Kalmido token** bypass the login, and
keep everything else behind it. Send them to the app port where the proxy's user header is **not** trusted (if you use
`AUTH_PROXY_PORT`, the normal port 3040, not the proxy port), and keep stripping client-sent `Remote-*` headers. The API
ignores that header and cookies anyway, but this way a mistake in one place does not open anything.

Caddy (inside the `route` from the README's *Reverse proxy* example, before `forward_auth`):

```caddyfile
@kalmido_api {
	path /api/v1/*
	header_regexp Authorization ^Bearer\s+abk_[A-Za-z0-9_-]{20,}$
}
reverse_proxy @kalmido_api 127.0.0.1:3040
```

nginx:

```nginx
location /api/v1/ {
    if ($http_authorization !~ "^Bearer abk_[A-Za-z0-9_-]{20,}$") { return 401; }
    proxy_set_header Remote-User "";
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_read_timeout 90s;   # agents long-poll up to 60 s (GET /api/v1/agent/events?wait=60)
    proxy_pass http://127.0.0.1:3040;
}
```

Agents may **long-poll** (`GET /api/v1/agent/events?wait=60`, see [AGENTS.md](AGENTS.md)): the request stays open up to
60 seconds. Caddy and Traefik have no read timeout by default; nginx needs `proxy_read_timeout` above 60 s (default 60 s);
Cloudflare cuts requests after 100 s, which is enough.

Traefik: a router with ``PathPrefix(`/api/v1/`) && HeaderRegexp(`Authorization`, `^Bearer abk_`)`` and a higher
priority than the router with the forward-auth middleware, pointing at the app port.

Requests to `/api/v1/` without a token then still get the login page of your proxy.
