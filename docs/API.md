# Kalmido REST API and webhooks

Kalmido has a small, versioned REST API under `/api/v1` for scripts and integrations (Home Assistant, n8n, a shell
script, your own tools) and outgoing **webhooks** that tell other systems when something changes. Both work as one user:
whatever that user can see and change in the app, and nothing more.

Projects are called lists in the API (`list_id`, `/lists`, `kind=list|project`): every list is a project in the app, so
the prose below says project and the technical names keep saying list.

- [Personal access tokens](#personal-access-tokens)
- [Basics](#basics): URLs, formats, errors, pages, limits
- [Endpoints](#endpoints)
- [Roadmap](#roadmap): all projects on one timeline, moving a whole project
- [Examples](#examples): curl, Home Assistant, n8n, a shell script
- [Webhooks](#webhooks): events, payload, signature, retries
- [Behind a reverse proxy](#behind-a-reverse-proxy)
- [Folders: sharing and settings](#folders-sharing-and-settings-2290), [Projects, people and agents](#lists-people-and-agents-2300)
- AI agents and bots (events, long-polling, jobs, chat, approvals) and the MCP server: [AGENTS.md](AGENTS.md), [mcp/](../mcp/)

The machine-readable description is an OpenAPI 3.1 document at **`/api/v1/openapi.json`** on your server (it contains no
data and needs no token). Import it into Postman, Bruno, Insomnia or an n8n HTTP node, or read it with any OpenAPI viewer.

## Personal access tokens

Create a token under **Settings > Access** (API tokens, webhooks and the tokens of your agents in one place):

- **Name**: what uses it ("Home Assistant", "backup script").
- **Permissions** (scopes, 2.15.0). Each request needs exactly one; the OpenAPI document names it per operation
  (`x-kalmido-scope`) and the server enforces that very table:

  | Scope | What it allows |
  |---|---|
  | `read` (always on) | every `GET`: projects, tasks, subtasks, tags, comments, time entries, habits, search, trash, News |
  | `tasks:write` | create, change, complete, reopen, move and batch-change tasks and subtasks; dependencies, waiting, habits, the day plan |
  | `comments` | write, edit and delete comments, reactions, mark News read |
  | `structure` | projects (create, change, archive, share), sections, custom fields, project tags, templates, saved filters, folders, project pages and status, import |
  | `delete` | move tasks to the trash, restore, empty the trash, undo an import; delete sections, projects, fields, templates, habits, filters (project tags, links and milestones: `structure`) |
  | `attachments:read` | download files of tasks, comments and projects (their names come with `read`) |
  | `attachments:write` | upload and remove them |
  | `files:read` (2.48.0) | the file store: list and read the folders and files shared with the token's account (agents: plus their own result folder) |
  | `files:write` (2.48.0) | the file store: add files and folders, upload new versions where the account may edit; new agents get both `files:` scopes |
  | `time` | the timer and time entries |
  | `export` | `GET /export` (2.148.1: a personal token also needs `account`) |
  | `calendar` (2.21.0) | events and event calendars, reading included: `/event-calendars…`, `/events…`, `/tasks/{id}/events` |
  | `contacts` (2.21.0) | address books and contacts, reading included (personal data of other people: never part of the old `write`, never an agent's default) |
  | `private` (2.22.0) | health projects and the journal, reading included (never part of the old `write`; an agent never gets it and never sees a health project) |
  | `account` | your notification settings and app passwords (never for agents) |
  | `admin-read` (admins only) | `GET /api/v1/admin/users`, `/admin/status`, `/admin/orgs/activity`, `/admin/agents/{id}/audit`; checked on every request: if the user stops being an admin, it stops working (never for agents) |

  A new token starts with `read`. A request without the needed scope gets `403` with `error.required_scope`. 2.190.0: the
  agent channel (`/agent/*`) needs no scope, but a read-only token (only `read`, `attachments:read`, `files:read`,
  `sheets:read`) may not post chat messages, reactions, pins or proposals there (`403`, `required_scope: comments`). Tokens
  created before 2.15.0 keep what they could do: `write` stands for every scope but `admin-read`, and old read-only
  tokens got `attachments:read` once. `POST /api/me/tokens` still accepts `write` (scripts).
- **Only from** (optional): IP addresses or networks (`203.0.113.0/24`); requests from anywhere else get `403`. Behind a
  reverse proxy the client address comes from `X-Forwarded-For` of the trusted proxies (`KALMIDO_TRUSTED_PROXIES`), so
  it is only as reliable as that setup: the proxy must replace or append the header, never pass on the client's own.
- **Expires**: in 30 days, 90 days, a year, or never.

The token looks like `abk_` followed by 43 random characters (256 bits). It is **shown once**; Kalmido only keeps its
SHA-256 hash, so a lost token cannot be shown again: revoke it and create a new one. The list shows the first
characters, the permissions, the expiry and when it was last used; its lock button changes the permissions and the
addresses later (`PATCH /api/me/tokens/{id}` `{scopes?, allowed_ips?, name?}`). Revoking works immediately. A disabled or deleted user's
tokens stop working at once.

An admin can **limit** what personal tokens and agents may get at all (Settings > Administration > Agents > Permission limit,
`PUT /api/admin/agent-policy` `{scope_limit: {agents?, tokens?}}`); a scope outside the limit stops counting at once for
every token and comes back when it is allowed again. `GET /api/v1/me` shows `token.effective_scopes` (what counts now).

**Only these projects (2.30.0).** A token can be limited to selected projects (the token dialog, `list_ids` on
`POST /api/me/tokens` and `PATCH /api/me/tokens/{id}`; empty = every project its user sees). Every `/api/v1` request checks
it: other projects and their tasks answer `404` as if they did not exist and are left out of every query. `GET /api/v1/me`
shows it as `token.list_ids`. Agents get the same restriction in their dialog, see
[Projects, people and agents](#lists-people-and-agents-2300). 2.86.0: such a token never creates projects on
`POST /api/v1/import/{source}`: without `target` every list of the file must match one of its allowed projects (by name, or
the inbox), else `403`; with `target` = an allowed project it imports as usual.

**A Kalmido app on another server (2.73.0).** *Settings > Account > Servers* shows the accounts of a person on several
Kalmido servers in one app; the home server reads and changes the tasks over there through this API with a personal token
of the person's account there. That token needs `read`, `tasks:write`, `delete`, `calendar` and `comments` (the
connection code of 2.73 creates it with exactly these, named "Kalmido-App: …"); with fewer scopes the matching actions
answer `403` with `error.required_scope`, and the app names the missing one. See
[SELF-HOSTING.md](SELF-HOSTING.md#several-servers-in-one-app-273).

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
| Compression | 2.65: with `Accept-Encoding: gzip` JSON answers from 1 KB on come gzip-compressed (`curl --compressed`, most HTTP libraries decode it on their own); without the header they stay plain |
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
token), `forbidden` (403: scope, project role or a module that is switched off), `not_found` (404: also for things the user
cannot see, so their existence is not revealed), `method_not_allowed` (405), `conflict` (409), `month_closed` (409, 2.125.0: a time entry in a month the person closed
in the timesheet: creating, changing, deleting, the timer), `rate_limited` (429, with `Retry-After`). The message is in the
user's language.

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

**Project types**: `kind` (`list` or `project`) is the switch *Progress and status* of the project dialog. Dependencies and a project status need `kind: "project"` (both
projects for a dependency; 2.39.1: custom fields work in every project): otherwise `409 conflict` with a message such as *Switch on progress and status in both projects to link their tasks*. **Time tracking** (2.41.0) is a switch of every project, of any type: `time_tracking`
(boolean, default `false`, the owner sets it with `POST` / `PATCH /lists`; a folder can give it as a default). New time
entries and timers need it (`409` *Switch on time tracking in the project settings to track time*); time tracked already stays
in `GET /time/entries`, the reports and the totals when it is switched off. Projects that held time entries when 2.41.0 started
got it switched on once. 2.7.2: the separate type *Shopping & packing list* (`kind: "checklist"`) is gone; every project
has the display option `done_at_bottom` (*Show completed at the bottom*: completed tasks stay visible at the bottom and
come back with one tap). Existing checklists became `kind: "list"` with `done_at_bottom: true`. **Deprecated aliases**
(still accepted): `kind: "checklist"` = `kind: "list"` + `done_at_bottom: true`; the boolean `checklist` = `done_at_bottom`.

**Dependent tasks move along** (2.67.0: the whole chain): if the list of a task has *Move dependent tasks along* switched
on (project dialog in the app; on by default in a new project), a `PATCH /tasks/{id}` that postpones the task's `due`
by n days moves every task waiting on it by the same n days (`start` and `due`, so the gaps stay), and so on down the
whole chain (each task once, at most 500). The setting of the changed task's project counts for the whole chain. Completed
tasks, milestones, tasks without a date and tasks you may not change stay where they are, and so does the chain behind
them. Every move is a normal date change (history, reminders, events, webhooks). Moving a task earlier never moves
anything back (the app has a button *Pull the chain in* for that). Send `"shift_chain": false` to leave the waiting tasks
where they are. When something moved or stayed, the answer carries `chain`:

```json
{"id": 41, "due": "2026-10-28", "chain": {"days": 3,
  "moved": [{"id": 77, "title": "Campaign concept", "start": "2026-10-29", "due": "2026-11-04", "old_start": "2026-10-26", "old_due": "2026-11-01"}],
  "skipped": [{"id": null, "title": null, "hidden": true, "reason": "no_access"}]}}
```

`reason` is `done`, `milestone`, `no_date`, `no_access`, `limit` or `error`; a task you cannot see comes without id and
title. To undo, `PATCH` the task and every moved one back to its old dates.

**Project roles** (1.10.0): a token sees exactly what its user sees. For a `participant` of a shared project every endpoint
returns only the tasks assigned to that user, their subtasks (all levels) and, read-only, the main task of an assigned
subtask with `context: true` (no `notes`, `url`, files, fields or comments; `GET /tasks/{id}/comments` answers 404 for
it). Other tasks of the project answer 404, never appear in `GET /tasks`, `/search`, `/tags`, `/roadmap` or
`/time/entries` (only the participant's own entries and those on their tasks), and a participant's webhooks fire only
for their own tasks. A participant can create tasks in the project (always assigned to themselves; `assignee_id` of
someone else: 403) and subtasks of their tasks, change and complete their tasks; `DELETE /tasks/{id}`, moving a task to
another project and changing `assignee_id` answer 403. Roles are set in the app (owner and project admins).

**History and notifications**: changes through the API go through the same code as the app. The task history shows
them with a small *via API* label, and assignments, mentions and completions notify people exactly as if the change
had been made in the app. Webhooks fire too.

## Endpoints

| Method and path | Scope | What it does |
|---|---|---|
| `GET /me` | read | The token's user, its scopes and expiry, which modules are on, and (2.1.0) `notifications`: `events` (per event `{news, push}`, `news` null = the event has no News) and `lists` (list id -> bell `all` / `mute` / `custom`; lists on `default` are left out), (2.6.1) `custom` (list id -> the own event choice of lists on `custom`, `{event: {news: 0\|1, push: 0\|1}}`, an event not listed follows `events`) |
| `PATCH /me/notifications` | account | 2.1.0: change them partially: `{events?: {event: {news?, push?}}, lists?: {list_id: "all" \| "default" \| "mute" \| "custom" \| {mode: "custom", events: {event: {news?, push?}}}}}` (2.6.1: `custom` = your own choice per event for that list, events `newtask`, `comment`, `mention`, `assign`, `complete`, `status`, `unblock`, `approval`; a ticked one comes from every task of the list, an unticked one never; `"custom"` alone brings back the stored choice). Events: `comment`, `reply`, `follow`, `mention`, `assign`, `newtask`, `complete`, `status`, `share`, `unblock`, `approval`, `followup`, `reminder` (push only), `nag` (2.7.0, push only: reminders repeated until done; a muted list bell stops them) |
| `GET /lists/{id}/notify-template` | read | 2.33.0: the list owner's notification template, a ceiling for the pushes of everyone else in the list (they can be quieter, never louder; the News list stays complete): `read` (pushes only for mentions, assignments, direct replies and approvals), `work` (+ comments on own / assigned tasks and due reminders), `all` (no limit), `custom` (the ticked events). The owner gets the whole setting (`own`, `inherited` from a shared folder, `people` with their own template); everyone else, agents included, `effective`, `by` (the owner) and `allowed` (the events that may push). Read only: only the owner changes it, in the app (*Share > Notifications for members*); agents never. A share without a template starts with `read` (server setting `KALMIDO_NOTIF_TEMPLATE`) |
| `GET /me/app-passwords` | read | 2.9.0: your app passwords for calendar apps (`id`, `name`, `created_at`, `last_used_at`, `last_client`; never the password) and `caldav` (`url`, `server`, `username`, `principal`, `home`, `done_days`). Persons only: an agent's token gets `403` |
| `POST /me/app-passwords` | account | 2.9.0: `{name}` -> `201` with `password` (shown only in this answer; Kalmido keeps a hash). At most 20. 2.79.0: only a token for all lists that also has `calendar` and `contacts` (an app password opens CalDAV / CardDAV without limits), else `403`. Log in to `/dav/` with your user name and it (see [CALDAV.md](CALDAV.md)) |
| `DELETE /me/app-passwords/{id}` | account | 2.9.0: revoke it; the calendar app using it stops at once |
| `GET /lists` | read | Lists the user can see: own and shared, with role (`owner`, `admin`, `edit` = member, `participant`, `view` = viewer), `done_at_bottom` (2.7.2; `checklist` = the same, deprecated), progress, `icon` (URL of the list's own picture, empty = none; set in the app), `agent_tidy`, (2.0.8) its sections `[{id, name}]` and (2.41.0) `time_tracking` (boolean: time tracking on for this list) and (2.144.0) `sort_mode` / `group_field` (the list's shared sort and grouping by a custom field, see `PATCH /lists/{id}`) and (2.83.0) `header_style` (the list's header strip in the app: `""` = none, `gradient`, `dots`, `lines`, `grid`, `image`; read only, set in the app) |
| `POST /lists` | structure | Create a list: `{name, color?, folder?, kind?, done_at_bottom?, nag?, day_hours?, time_tracking?}` (2.41.0: `time_tracking` boolean, default `false`) (`kind`: `list` default or `project`; `checklist` (deprecated) = `list` + `done_at_bottom`). `project_type` (`agency`, `software`, `private`) creates a project of that built-in type; 2.27.0: its standard sections only with `sections: true` (a boolean, only together with `project_type`) |
| `GET /lists/{id}` | read | One list with its sections and (2.14.0) its custom `fields` `[{id, name, type}]` (also on `GET /lists`); 2.39.0: `playbook` = the list's effective Playbook (null = none) |
| `GET /lists/{id}/playbook` | read | 2.39.0 (#1168): the list's Playbook, the owner's working rules for agents: `{list_id, text` (effective: the folders' parts, then the list's own)`, list_text, folders [{folder, text}], version` (a short marker)`, list_version, updated_at}`; health lists `404`. See [AGENTS.md](AGENTS.md#playbook-2390) |
| `POST /lists/{id}/playbook/proposals` | agent | 2.39.0: **agent tokens only**, members of the list: propose a new text of the list's own Playbook `{text, note?}` -> `201 {id, state, base_version}`; at most 3 open per agent and list (`409`); people apply or discard it in the app (event `playbook_proposal`) |
| `PATCH /lists/{id}` | structure | 2.144.0: `sort_mode` (the list's sort, the same for every member: `""` = default, `prio`, `prio_asc`, `custom`, `date`, `date_desc`, `title`, `creator`, `flow`, `created`, `created_asc`, `cf:<field id>[_desc]`, `col:who|tags|time|progress|deps[_desc]`) and `group_field` (the list view grouped by a custom field for every member: `"cf:<field id>"` or the id of a **text or select** field of this list: one group per value, select fields in the order of their options, *No value* last; `""` / `null` = by sections again, the sections themselves never change), owner / list admins (others `403`, an unknown value or a field of another list `400`); lists carry both. 2.46.0: `org_visibility` (`""` = only the people the list is shared with, default; `"org"` = everyone in the list's organisation: members who are not shared with it see it read-only, `org_reader: true`, role `view`) and `org_edit` (boolean: they may edit without joining, role `edit`; 2.83.0: then they can also be the `assignee_id` of its tasks without joining, the assignment goes when `org_edit` is switched off), owner / list admins, only for lists of an organisation and never for health / Home & life / family lists (409); a list that becomes private is reset; an agent opening a list waits for approval (202). 2.41.0: `time_tracking` (the owner, boolean): time tracking on for this list. 2.40.0: `name` and `color` also by list admins (a rename puts a News entry at the owner; the rest stays the owner's, `403`). 2.28.0: `org_id` (the owner): the list's workspace, an organisation you belong to or `null` = private (`409` while people / agents in it do not fit, for family / Home & life lists and the inbox); lists carry `org_id`. 2.18.0: `project_type` (owner / list admins): `agency`, `software`, `private` or `null` / `""` (none); switching turns on what the type needs, nothing is deleted; lists carry `project_type`. 2.15.0: `archived` (true / false; the owner). 2.14.0: `columns` (owner / list admins; others `403`): the row columns of the list in order, the same for every member: `id` (task number in front of the title), `due`, `prio`, `who`, `tags`, `time`, `progress`, `deps`, `created`, `f:<field id>`; a key that is not listed is not shown; `null` = the default layout; unknown keys or fields of another list `400`. A new custom field joins configured columns at the end. 2.39.1 (#1293): `f:<id>` columns switch the module *Custom fields* on for the list's owner; the answer then carries `modules_on` (`["fields"]`, also with `project_type`: the modules it switched on). 2.13.1: `listen_agent_ids` (owner / list admins): the agents that read every comment of a person in the list ([AGENTS.md](AGENTS.md#agent-reads-every-comment-2131)). 2.7.0: change a list. The owner: `name`, `color`, `kind`, `done_at_bottom` (2.7.2), `nag` (default nag interval of its tasks: `5`, `10`, `15`, `30`, `60` minutes, `1d`; empty / `off` = none), `day_hours` (hours per day / shift for the time sums, 1 to 24; `null` = the server's value). Members change only their own `folder` and `view` |
| `GET /lists/{id}/repos` | read | 2.2.0: repositories connected to a (project) list: `provider` (`github` / `gitea` / `gitlab` / `bitbucket`, 2.18.0), `base_url`, `web_url`, `owner`, `repo`, `full_name`, `default_branch`, `status` (`new` / `ok` / `error`), `error`, `polled_at`. Never a token; connecting is only in the app (list owner / list admins). Lists also carry `repos`. 2.33.0: a list without repositories of its own lists the ones of its folder that it uses (`folder` = the folder's path for the folder's owner, `""` for everyone else and for agents, `null` = the list's own repository; connected by the folder's owner in the folder settings, switchable off per list); `#id` / `fixes #id` then work for the tasks of every project list in that folder |
| `GET /lists/{id}/build-status` | read | 2.151.0 (#2558): the build state of a list with a repository: `data` = the OPEN tasks that need a look, each `{id, title, build}` (`build.stale` = open although its package or code is released, or work only on a branch not in the default branch), `latest` (the highest version tag), `repos`, `checked_at`. A version tag is a tag of digits with dots (optional `v`); per new tag Kalmido compares it with the version before it, so the first version that holds a commit is known (an existing connection: the newest 10 tags once). Once the newest version tag or the default branch moved, one compare newest tag...default branch tells which untagged default-branch commits are in an earlier version (`version: null`). Only the tasks the caller sees (not a participant's context tasks); branch names carry `origin: "git"`, `untrusted: true` |
| `POST /lists/{id}/join` | structure | 2.46.0: join a list you see through `org_visibility: "org"` (`org_reader`): you become a member with the role `edit` and get its notifications; 409 when you are a member already, 404 for anybody else (agents never see lists this way). Leave again with `DELETE /lists/{id}/members/{your id}`. Readers find the list's tasks in search and in `GET /lists`, but not in the calendar feed, CalDAV, the briefing or the list's channel, and get no notifications until they join |
| `POST /lists/{id}/owner` | structure | 2.1.2: transfer the ownership `{user_id}` to another active person (never an agent); the old owner stays as a list admin. Admins may take over a list whose owner is an agent or a disabled user. Agent tokens always `403`, inboxes `409` |
| `GET /tasks` | read | Tasks (not in the trash), oldest first; filters below |
| `POST /tasks` | tasks:write | Create a task (default list: the user's inbox) |
| `GET /tasks/{id}` | read | One task |
| `PATCH /tasks/{id}` | tasks:write | Change the fields you send |
| `DELETE /tasks/{id}` | delete | Move the task with its subtasks to the trash (204); restorable in the app |
| `POST /tasks/{id}/complete` | tasks:write | Complete; recurring tasks move to their next date (`next_due`) |
| `POST /tasks/{id}/reopen` | tasks:write | Reopen a completed task |
| `PUT /tasks/{id}/waiting` · `DELETE …` | tasks:write | 2.1.0: waiting on someone (outside; *waiting on external* before 2.25.0): `{note?, until? (YYYY-MM-DD)}` sets / changes it, `DELETE` ends it. Every task has `waiting` (`null` or `{note, until, since, by}`); `GET /tasks?waiting=true` lists them |
| `GET /tasks/{id}/subtasks` | read | Subtasks |
| `POST /tasks/{id}/subtasks` | tasks:write | Add a subtask |
| `GET /tasks/{id}/comments` | read | Comments |
| `GET /tasks/{id}/related` | read | 2.59.0 (#1375): up to 5 tasks close in meaning, only tasks you may see: `{enabled, pending, items: [{id, title, list_id, done, score, dup, ref}]}`: up to 5 similar ones (local text vectors, ordered together with the similarity of the titles; never the task's own parent / subtasks), `score` 0..1 = the order, `dup` = probably a duplicate; then, with `ref: true`, up to 5 tasks named by `#id` in either direction. `enabled: false` = the server runs without the optional embedding service or an admin switched it off; `pending: true` = this task is not computed yet. MCP `related_tasks` |
| `POST /tasks/{id}/comments` | comments | Comment: `{body}`; mention someone with `<@user_id>`; agents may add a tidy `suggestion` (see [AGENTS.md](AGENTS.md)); 2.63.0 (#1513): `portal: true` = a public answer the customer of a customer report sees (only on a task with a ticket and with write access; comments carry `portal`); 2.126.0: from an agent it waits for a person's approval (`202` + a waiting job) |
| `POST /comments/{id}/choice` · `POST /comments/{id}/withdraw` | comments | 2.41.0 (#1383): agents post comments with answer buttons (`choices`, `multi`) or an approval card (`approval: {title, what?, yes_label?, no_label?}`, `expires_in`); comments carry `choices`, `choice` (`{ids, at, user_id, user_name, via}`, written once) and `choice_state` (open, answered, expired, withdrawn). A person (own token, may edit the task and instruct the agent; an approval card only an approver: list manager, assignee or admin, 2.144.5 #2001, else 403) answers `{choice_ids}` (a plain button is also posted as the person's comment: `answer_comment_id`); the agent withdraws its open buttons `{outcome?: denied \| expired}`. The app: `POST /api/comments/{id}/choice`, `GET /api/comments/{id}/choice` (the state); tasks carry `approvals_open` when an agent's approval card waits in their comments |
| `GET /tasks/{id}/attachments` | read | 2.13.1: the files of a task and of its comments: `id`, `task_id`, `comment_id` (`null` = the task's own), `name`, `mime`, `size`, `created_at`, `url` |
| `GET /attachments/{id}` | attachments:read | 2.13.1: the file itself (images, PDF and text inline, everything else as a download; `?dl=1` always a download; `410` = damaged on the server). Same rights as in the app |
| `GET /chat-attachments/{id}` · `DELETE …` | read · comments | 2.15.0: chat files need only `read` (the conversation itself is the access). 2.13.1: a file of an agent chat (the person or the agent of that conversation); `DELETE`: only its sender |
| `POST /comments/{id}/reactions` | comments | React: `{emoji}` = `up`, `down`, `heart` or any single emoji |
| `DELETE /comments/{id}/reactions/{emoji}` | comments | Take your reaction back |
| `GET /roadmap` | read | All lists on one timeline: groups with summary spans, progress and dated tasks, see [Roadmap](#roadmap) |
| `GET /groups` · `GET /groups/{id}` | read | 2.10.0: groups of people (admins create them in the app): `id`, `name`, `members [{user_id, name}]`, `synced` (members follow a sign-in group), `mine` |
| `GET /lists/{id}/groups` | read | 2.10.0: the groups a list is shared with: `group_id`, `name`, `role`, `via` (`list` = directly, else the owner's folder) |
| `PUT /lists/{id}/groups/{group_id}` · `DELETE …` | structure | 2.10.0: share a list with a group `{role}` (owner / list admin) or stop it. Every member (also later ones) gets access; a person's role is the higher of their own and the group's |
| `POST /tasks/{id}/take` | tasks:write | 2.10.0: take a task assigned to one of your groups (`assignee_group_id`): it becomes yours (also for participants) |
| `GET /dayplan?date=&mode=` | read | 2.10.0: the built-in day plan (a preview, nothing changes): working hours, calendar events, fixed timed tasks, `plan [{task_id, start, end, duration, estimated, reason}]`, `nofit [...]` (tasks of the day that do not fit; 2.11.0: listed only), `free_min`; `mode=day` (default) or `fill`. Apply with `PATCH /tasks/{id}` `plan_start` + `duration`: planning never changes due dates |
| `GET /dayplan/review?date=` | read | 2.10.0: the daily review: `done`, `open`, `moved` (tasks moved away that day) and `tomorrow` (a plan for the next working day) |
| `POST /lists/{id}/shift` | tasks:write | Move every open dated task of a list by `{days}` in one transaction, see [Roadmap](#roadmap) |
| `GET /tags` | read | The user's personal tags (`kind: personal`) and the tags of the lists they see (`kind: list`, with `list_id`, `color`), with task counts |
| `GET /lists/{id}/tags` | read | The list tags of a list (shared by its members) |
| `POST /lists/{id}/tags` | structure | Create a list tag `{name, color?}` (members with edit rights) |
| `PATCH /lists/{id}/tags/{tag_id}` · `DELETE …` | structure | Rename / recolour · delete a list tag (removed from every task) |
| `GET /lists/{id}/overview` | read | 2.7.1: the overview of a project list: description, key links, milestones, project files, the files of its tasks, members, status history, tracked time (409 for other list types) |
| `PATCH /lists/{id}/overview` | structure | The description `{description}` (Markdown, at most 20000 characters; owner, list admins, members) |
| `GET` · `POST /lists/{id}/links` | read · structure | Key links `{title?, url}` (http / https; at most 50) |
| `PATCH` · `DELETE /lists/{id}/links/{link_id}`, `PUT /lists/{id}/links/order` | structure | Change · remove a link, reorder `{ids}` |
| `GET` · `POST /lists/{id}/milestones`, `PATCH` · `DELETE /lists/{id}/milestones/{milestone_id}` | read · structure | Milestones `{name, day, done?}` (at most 100). 2.18.0: a compatibility layer on top of milestone tasks; the ids are task ids |
| `GET /tasks/{id}/milestone` | read | 2.18.0: a milestone task's report: `progress` (closed / total / percent), its `tasks` (open first), `burndown` (open tasks per day + ideal line), `release_notes` (Markdown: Features / Fixes / Other). Tasks carry `milestone` (bool) and `milestone_id`; `GET /tasks?milestone=true` / `?milestone_id=` |
| `GET /lists/{id}/environments` · `POST /lists/{id}/deployments` | read · write | 2.60.0 (#1514): the environments of a project list (Staging, Live, ...) with the latest deployment of each; `POST {environment: id or name, version?, milestone_id?}` records that a version / milestone runs there now (the milestone is found by `version` against the milestone titles: exact, with or without a leading `v`, or as a word of the title; a version without a milestone is kept as text). With "complete tasks on arrival" on for the environment the milestone's open tasks are completed. Agents with write access to the list may; the environment's deploy webhook and its token stay with people. Agents hear `deployed` |
| Task field `points` | tasks:write | 2.60.0: story points `1, 2, 3, 5, 8, 13` or `null` (other values: 400) with `POST /tasks`, `PATCH /tasks/{id}` and `POST /tasks/batch`. Always stored; the app shows them in lists with `points_on: true` (`PATCH /lists/{id}`, owner) |
| `GET /lists/{id}/sprints` | read | 2.60.0 (#343): the sprints of a project list (newest first): `id`, `num`, `title`, `start`, `end`, `goal`, `state` (planned \| active \| closed), `progress` (`done`, `total`, `points_done`, `points_total`), `review` of closed sprints; plus `settings` `{on, weeks, dow, carry}`, `points_on`, `active_id` |
| `GET /sprints/{id}` | read | 2.60.0: one sprint with its `tasks` (open first) and `burndown` (`?unit=count\|points`: open work per day, `ideal` line from the start to 0 on the last day) |
| `POST /lists/{id}/sprints/assign` | write | 2.60.0: `{ids, sprint_id \| null}` puts tasks of the list into one of its open sprints or back to the backlog (edit rights; milestones and other lists' tasks come back in `skipped`); answers `moved`, `skipped`, `prev` |
| `GET` · `PATCH /lists/{id}/error-hook` | read · structure | 2.18.0: the error-report webhook of a project list `{state: on \| rotate \| off}`; `on` / `rotate` return the secret URL once. People only (agents: 403). 2.138.4 (#2381): the answer also carries `hook_url` and `token`: `POST hook_url` with `Authorization: Bearer <token>` (or `X-Kalmido-Token`) keeps the token out of proxy logs; the URL with the token in the path keeps working |
| `GET` · `POST /lists/{id}/files`, `GET` · `DELETE /lists/{id}/files/{file_id}` | read · attachments:write · attachments:read | Project files (multipart `file`, the attachment size limit; images / PDFs inline, everything else as a download) |
| `GET /agents` | read | Agents you share a list with: status and job counts. 2.28.0: + `org_id` (the agent's workspace, null = private), `owner_id` (a personal agent's owner) |
| `POST /agents/{id}/chat/{message_id}/choice` | comments | 2.28.0 (#1005): answer an agent's question with one of its buttons `{choice_ids: [...]}` (several with `multi`); once per message; the agent gets the event `chat_choice`, see [AGENTS.md](AGENTS.md#answer-buttons-2280) |
| `POST /agents/{id}/chat/{message_id}/reactions` | comments | 2.7.2: react to a message in your chat with the agent: `{emoji: up \| down \| heart, on?}` (toggles without `on`); your 👍 / 👎 on an agent message that asks something (`asks`, 2.13.0) is sent to it as an approval (`reaction` event, see [AGENTS.md](AGENTS.md#chat-reactions-and-delivery-272)) |
| (app) `PATCH /api/agents/{id}/chat/{message_id}` | session | 2.39.0 (#1179): a person edits the text of their own message to an agent `{body}` (in the app, not with a token; the agent's messages 403, others' 404, same limits as sending, same text = no change); the answer carries `edited_at` and `edits` (the earlier versions `[{body, at}]`, only for the person). The agent sees `edited_at` + the current text in `GET /agent/chats` and gets the event `message_edited` once it had the message, see [AGENTS.md](AGENTS.md) |
| (app) `DELETE /api/agents/{id}/chat/{message_id}` · `DELETE /api/agents/{id}/chat` | session | 2.152.0 (#2175): a person deletes one message of their own conversation with an agent (theirs or the agent's answer in it), or the whole conversation, for good; the chat files leave the disk (`{ok, message_id}` / `{ok, deleted}`). Only the own conversation: another person's message or an agent not shared with the person is 404. Not with a token, no event for the agent. The optional day limit `KALMIDO_CHAT_KEEP_DAYS` (0 = none) trims old messages while the retention switch `chat` is on |
| (app) `POST /api/agents/{id}/chat/{message_id}/pin` · `POST /api/team/messages/{id}/pin` | session | 2.62.0 (#1848): pin / unpin a chat message `{pinned?}` (toggles without; at most 5 per conversation, else 409); messages carry `pinned_at` / `pinned_by`, the conversation's page `pins`. The agent gets `chat_pinned`. 2.62.0 (#1530): the app sends `client_id` with a new chat message; the same text with the same `client_id` within 10 seconds returns the stored message (200) instead of a new one |
| (app) `GET /api/agents/jobs?limit=&before=` · `GET /api/tasks?scope=done\|trash&limit=&before=` · `GET /api/news?limit=&before=` | session | 2.40.0 (#1432): "Load more" pages in the app (not with a token). The answer carries `next` (null = the end); pass it as `before` for the following page. Jobs: `limit` 20 by default (at most 200), the first page also brings every running / waiting job, the pages hold the ended ones (newest change first, cursor = change time + id); without `limit` / `before` the list is unchanged (up to 200 visible jobs), `id=` still returns one job. Completed / trash: `limit` as before (default 300, at most 2000), cursor = completion resp. deletion time + id; the first trash page also says `deletable` and `kept` for the whole trash; 2.138.1: every trash page says `days` (the trash period) (`DELETE /api/trash` empties all of it, not only the loaded page). News: the pages count read items (`limit` at most 500); the first page also brings every unread item; `unread`, `unread_me`, "mark all as read" and `filter=` always cover the whole feed; without `limit` the whole feed as before |
| (app) `POST /api/agents/jobs/{id}/action` · `GET /api/agents/{id}/chat?job=` | session | 2.56.0 (#1791 / #1793): `{action: message, text}` writes to a running job (the agent gets the `job` event, the job does not change; the same people as Stop, empty 400, ended 409); `?job=<job id>` = only that job's messages in my chat with the agent (its `job_id` messages, mine addressed to it, the agent's answers to those); jobs carry `name`. 2.96.0 (#2015): the chat answer also has `jobs: {<id>: {id, name, title, version, state, parent_id, parent_name, updated_at}}` (the jobs of the delivered messages, only those I may see; also with `?job=` / `?after=`), and each message `job_msg` (`say` \| `question` \| `result` \| `error`, `null` = unknown); the app shows one card per job |
| (app) `POST /api/agents/{id}/abort` · `POST /agent/aborted` | session · write | 2.144.0 (#2412): **Stop** in the agent chat `{job_id?}`: the agent gets the event `abort` (whoever may write the agent; with `job_id` only who may stop that job, ended 409, 30 per 10 minutes); the agent confirms with `POST /api/v1/agent/aborted {seq?, job_id?}` (agent tokens only; without `job_id` the status goes back to idle), see [AGENTS.md](AGENTS.md#stopping-a-running-answer-21440) |
| (app) `POST /api/agents/{id}/chat {job_id}` · `GET /api/agents/{id}/chat?job=` | session | 2.153.0 (#1962): a chat of its own per job: `job_id` (a job of this agent I may see, else 400; only who may stop it, else 403, ended jobs too; also as a form field with files) stores my message with that job and the agent gets the usual `chat` event with `message.job_id` and `job`; `?job=` also returns `progress: [{text, at}]` (the job's progress lines, only for the person it is for, the newest 300). A job created for a person starts with a notice in that person's chat (`kind` notice, `job_msg` start, the title as text). |
| `GET /agent` … `/agent/events` … `/agent/jobs` … `/agent/chats` · `PUT /agent/status` · `POST /tasks/{id}/tidy` | read | **Agent tokens only**: the agent protocol, see [AGENTS.md](AGENTS.md); `POST /agent/jobs/{id}/proposal` answers a `job_request` (2.39.0: kind `cleanup` = tidy up a list, see AGENTS.md *Tidy up a list*; 2.51.0: kinds `inquiry` and `setup`, also as the agent's own proposal `POST /agent/proposals {kind, user_id, proposal}`, see AGENTS.md *An inquiry becomes a project, the setup assistant*; 2.70.0: kind `merge` = groups of duplicate contacts `{groups: [{target_id, ids, reason}]}`, see AGENTS.md *Tidy up contacts*; 2.126.1: kinds `office_text` `{field, text}`, `doc_summary` `{text}` and `report` `{text}` = texts a person asked for, see AGENTS.md *Texts worded by an agent*; the contact routes stay refused for agent tokens); the status may name the task it works on (`task_id`, shows "… is writing" there); 2.37.0: a chat message with `offer_save: true` offers the person "Save as task" (saving itself is a click in the app, never an API call of an agent); 2.41.0: `kind: "notice"` on `POST /agent/chats/{user_id}` = a small grey line in the chat (e.g. a new session of the agent), no push, never unread, see AGENTS.md *Notices in the chat*; 2.44.0: `host` in `PUT /agent/status` names the computer (kept on the token in use, see AGENTS.md *Set up on a computer with one command*); 2.47.3: `job_parent` (with `job_id`) on `POST /agent/chats/{user_id}` = the leading job of a part job, the chat colours a message `Job #N: …` by its job (AGENTS.md *Chat*); 2.58.0: `name` on `POST /agent/jobs` = the job's own short name (AGENTS.md *Jobs*); 2.82.0: `GET /agent/chats?user_id=` also returns the conversation's `pins` |
| `POST /agent/usage` · `GET /agent/usage?from=&to=&group=` | agent | **Agent tokens only** (2.1.1): report model usage (numbers and ids only), read it grouped by day, task, list or model; over its hard limit an agent gets `429` on every other call, see [AGENTS.md](AGENTS.md#usage-and-limits) |
| `GET /search?q=` | read | Search titles, notes, links and custom field values. 2.59.0 (#1375): `&semantic=1` adds, after the text hits, tasks of similar meaning (each with `"similar": true`; only on servers with the embedding service, otherwise nothing is added; at most 6 such queries per account in 10 seconds, more add nothing). 2.81.0: a task found only through the recognised text of one of its files carries `file_hit` (the file name). 2.138.1 (#2065): `&fulltext=1` = ranked full-text search (Postgres, word beginnings; case, accents and ä/ae do not matter): title hits before note hits, then tasks found by a comment, a custom field or a file text; each task once with `match: {where, snippet: {text, marks}, comment_id}` (plain text, never HTML), completed tasks included, the trash and lists with the lock never; at most 50 per page (`cursor`) |
| `GET /search?scope=messages&q=&art=&sender=&room=&agent=&task=&limit=&cursor=` | read | 2.33.0 (#1080): search task comments, team chat (channels, direct messages) and agent chats -- only what you may read (comments of tasks you see, rooms you are in, your own agent chats; an agent: the lists shared with it, their channels, its own chats, never direct messages). Words match word beginnings; case, accents and ä / ae do not matter. Newest first, `{data, total, next_cursor}`; a hit `{art: c \| t \| a, chat_type: task \| list \| dm \| agent, id, task_id?, list_id?, room_id?, agent_id?, user_id?, chat_name, sender {id, name, agent}, created_at, snippet, marks}`: `snippet` is plain text (never HTML) around the hit, `marks` the `[start, end)` ranges of the hits in it (characters = Unicode code points). Filters: `art` (comma-separated), `sender` (user id), `room`, `agent` (an agent: the person), `task`; a foreign id simply finds nothing |
| `GET /time/entries` | read | Time entries (time tracking), newest first: `from`, `to`, `scope=mine|all`, `list_id`, `task_id`. 2.63.0: with `scope=all` a person's token gets other people's entries only in lists the person owns or administers (list admin, admin of the list's organisation); elsewhere only their own. With `task_id` everyone's entries of that task as before; agents unchanged |
| `POST /time/entries` | time | Add one: `{task_id or list_id, start, end or minutes, note?, billable?}`. 2.144.6: every entry carries `billable` (default `true`: may go onto an invoice) and `billed` (an invoice took it) |
| `GET /habits` | read | The user's habits with today's count and the last 30 days |
| `GET /habits/{id}/stats` | read | 2.138.1 (#2067): current and best streak (`streak_unit` days or weeks), `rate_percent` of the last 30 scheduled days (last 4 full weeks for "x times a week"), `total_days` |
| `GET /focus` · `GET /focus/stats` | read | 2.138.1 (#2067): focus sessions (pomodoro, breaks, stopwatch), newest first with the running one (`running`, `paused`, `elapsed_minutes`), `limit` / `cursor`; the statistics are the app's (today, 7 days, per day, per task, recent). **Private to a person:** only a person's own token, an agent token (team or personal) always gets `403` |
| `POST /focus/start` · `POST /focus/{id}/stop` · `/pause` · `/resume` | time | 2.138.1 (#2067): `{kind?: focus\|short\|long\|stopwatch, minutes?, task_id?}`; a running session ends first; a session on a task becomes a time entry when it ends. Same rule as above: persons only |
| `POST /habits/{id}/checkin` | tasks:write | `{date?, count?, note?}`: without `count` one more for the day |
| `POST /import/{source}` | structure | Import an export file (multipart), see [Import](#import) |
| `POST /imports/{id}/undo` | delete | Undo an import within 24 hours |
| `GET /admin/users` | admin-read | All users (no secrets) |
| `GET /admin/orgs/activity` | admin-read | Numbers per organisation (members, last sign-in date, storage in bytes, lists, tasks) and one row for people without an organisation; no names or contents |
| `GET /admin/status` | admin-read | Version, counts, update available (`latest_version`, `update_checked_at`, `update_error`), last backup, pending webhooks |
| `GET /admin/agents/{id}/audit` | admin-read | 2.2.1: the agent's audit log, newest first: `{id, at, agent_id, agent_name, method, route, status, task_id, list_id, ms, denied}`; `?status=2xx\|3xx\|4xx\|5xx\|denied`, `?day=YYYY-MM-DD`, cursor pages (see [AGENTS.md](AGENTS.md#audit-log)) |
| `GET /lists/{id}/sections` · `POST …` | read · structure | 2.15.0: sections in order; create `{name, before_id?}` (at the end or in front of a section) |
| `PATCH /sections/{id}` · `DELETE …` | structure · delete | 2.15.0: rename `{name}`; delete (its tasks stay in the list without a section) |
| `PUT /lists/{id}/sections/order` | structure | 2.15.0: `{ids}`: every section of the list exactly once, in the new order |
| `PATCH /sections/{id}` `{wip_limit}` | structure | 2.60.0: the WIP limit of a kanban column (the most open tasks it should hold; `null` / `0` = none). A hint only: the app shows "2/3" in the column head and marks it above the limit, moving stays allowed. Sections carry `wip_limit`; `POST /lists/{id}/sections` takes it too |
| `GET /lists/{id}/velocity` | read | 2.60.0: the completed story points (`points`) and tasks (`count`) of the list's last up to 6 closed sprints, oldest first, and their `average` (null = no closed sprint yet). Participants count only the tasks they see |
| `POST /tasks/{id}/move` | tasks:write | 2.15.0: `{list_id?, section_id?, parent_id?, before_id? \| after_id? \| position?: top \| bottom}`: another list / section / parent and a place among the siblings; subtasks move along; the same rights as in the app (into a list you may edit, out of a shared list only as its owner) |
| `POST /tasks/{id}/links` · `DELETE /tasks/{id}/links/{list_id}` | tasks:write | 2.71.0 (#1459): show a task also in another list `{list_id, section_id?}` (no copy) / remove it from that list (the task stays). Rights stay with the task's own list; edit rights on the task and the list, same workspace, no health / locked lists, top-level tasks, at most 10 further lists. Tasks carry `also: [{list_id, section_id, sort}]` = the further lists you see (absent when none) |
| `POST /tasks/batch` | tasks:write (+ delete) | 2.15.0: `{ids (1-500), action: update \| complete \| reopen \| wont_do \| delete \| restore, changes? (update)}`: one transaction; tasks you may not change are skipped (`errors`). `delete` / `restore` also need `delete`. Agents: 10 or more tasks wait for approval (`202`); 2.190.0: a team agent's batch over projects of different people needs one person who manages all of them, else `409` (one batch per project) |
| `POST /tasks/{id}/skip` | tasks:write | 2.15.0: skip this occurrence of a repeating task (next date, no completed copy) |
| `GET /trash` · `DELETE /trash` | read · delete | 2.15.0: tasks in the trash (`list_id`, pages); empty it for good (lists you own; admins also shared lists they may edit; agents: approval). 2.138.1: the server deletes a task for good once it has been in the trash for the trash period (`KALMIDO_TRASH_DAYS`, 30 days; while the operator's retention switch is off it only counts) |
| `POST /tasks/{id}/restore` | delete | 2.15.0: restore a task from the trash (`409` if it is not there) |
| `GET /tasks/{id}/dependencies` · `POST …` · `DELETE …/{blocker_id}` | read · tasks:write | 2.15.0: `blocked_by` / `blocking`; add `{blocked_by}` (project lists, no cycles), remove |
| `GET /lists/{id}/fields` · `POST …` | read · structure | 2.15.0: custom field definitions; create `{name, type, options?, pinned?}` (2.39.1: any list, owner / list admins; switches the module *Custom fields* on for the list's owner, the answer's `modules_on` names it: `["fields"]` or `[]`). Values: the task's `fields` |
| Field types | structure | `text`, `number`, `select`, `date`, `checkbox`, `person`, `url`, `formula`; 2.156.0 B (#2069): `multiselect` (`options.options` like `select`; value = option ids joined by `,`, a list is accepted; a removed option leaves the values), `currency` (`options.currency`, ISO code, default `EUR`; value like a number), `rating` (`options.max` 3-10, default 5; value `"1"`..max, `0` / `null` clears), `task` (value = the id of a task you may see, else `400`; the web app shows its title only to people who may see that task, `GET /api/fields/task-refs?ids=` answers only those; agents read it with `GET /tasks/{id}`). Rules cannot set multiselect or task fields; a customer view never shows task fields |
| `PATCH /fields/{id}` · `DELETE …` | structure · delete | 2.15.0: change `{name?, options?, pinned?, sort?}` (the type stays); delete with its values (agents: approval) |
| Formula fields | structure | 2.43.0 (#1328): `type: "formula"` with `formula` (create / change): `+ - * /`, brackets, numbers, `{Field name}` of number, formula or checkbox fields and `round(x, n)` (n 0-6). Stored with field ids (`options.expr`, `{#12}`), shown with today's names (`options.formula`), so renaming a field keeps it working; no field may use itself, circular references -> `400` naming the field, syntax errors -> `400` with the character. The server computes the value into the task's `fields` (as text like a number); empty fields count as 0 (`options.empty: "blank"`: the result stays empty), division by 0 = empty. Writing a formula value -> `400`. 2.156.0 B (#2070): the formula engine of tables: comparisons (`= <> < > <= >=`), `WENN/IF`, `SUMME/SUM`, `RUNDEN/ROUND`, `MIN`, `MAX`, `MITTELWERT/AVERAGE`, `ANZAHL/COUNT` (German and English names, `;` or `,` between arguments), `currency` / `rating` fields as numbers; an unknown function -> `400`; a calculation that fails gives `"#div0"` / `"#type"` in `fields` (empty while none of the fields it reads has a value) |
| `GET /lists/{id}/kpis` | read | 2.43.0 (#1328): the key figures of a list (tiles of its project page): `{data: [{id, title, agg: sum\|count\|avg\|ratio, value, unit, n}]}` over the tasks you may see; `value` null = nothing to compute. Health lists: `404` for agents. Set up by people (web: `PATCH /api/lists/{id}` `{kpis: [{title, agg, field?, field2?, state: all\|open\|done, cond_field?, cond_value?}]}`, owner / list admins; the sum row of a list: `{col_sums: {"f:<id>": sum\|avg\|count\|min\|max}}`) |
| `GET /templates` · `POST …` | read · structure | 2.15.0: your templates; create from `{task_id}`, `{list_id, relative?}` or `{kind, data}`, `name?` |
| `PATCH /templates/{id}` · `DELETE …` · `POST …/apply` | structure · delete · structure | 2.15.0: rename / replace data; delete; use it (task template: `{list_id?, section_id?}`; list template: `{name?, folder?, start?, end?}`) |
| `POST /lists/{id}/duplicate` | structure | 2.78.0: a copy of the list as a new list of yours `{name?, done?, folder?}` -> `{list_id}`: sections, tasks with their dates (done = also the completed ones), subtasks, fields, dependencies, milestones, Playbook, notepads, page arrangement; no members, shares or assignees; not for participants; 2.126.0: only who may edit the list (view only = 403) |
| `POST /tasks/{id}/attachments` | attachments:write | 2.15.0: upload files (multipart, field `file`, repeatable; the server's size limit, no empty files) |
| `POST /tasks/{id}/attachments/text` | attachments:write | 2.30.0: a text file from JSON `{name, content}` (Markdown, plain text, HTML / CSS / JS, JSON / CSV, code; UTF-8, at most 1 MB). An ending that is not a text type (`.sh`, `.ps1`, `.bat`, `.exe` …) gets `.txt` appended; a name the task already has becomes a new version next to it (`report (v2).md`, the old file stays). Answer `201` `{id, task_id, name, mime, size, created_at, version, replaces, url}` |
| `DELETE /attachments/{id}` | attachments:write | 2.15.0: remove a file of a task (or of your comment) |
| `GET /files` · `GET /files/{id}` | files:read | 2.48.0 (#1207): the file store: without `parent_id` the top of what is shared with you (agents: plus their own result folder), `?parent_id=` a folder's children; one node with `children` (folder) or `versions` (file) and `path`. Each item: `{id, parent_id, kind: folder \| file \| link, name, org_id, owner_id, agent_id, mime, size, version, role: owner \| edit \| view, url, content_url}` |
| `GET /files/search?q=` | files:read | 2.61.0: files whose name or text matches (PDF text layer, text recognised in scans / photos), only what you may open; `hit: name \| text`, at most 100, `?space=private \| org:<id> \| shared` |
| `GET /files/{id}/content` · `GET /files/{id}/text` | files:read | 2.48.0: the bytes (`?version=` an older one; always a download) / the text (UTF-8, the text layer of a PDF, 2.92.0: Word .docx / Excel .xlsx; like `/attachments/{id}/text`) |
| `POST /files` · `POST /files/{id}/versions` | files:write | 2.48.0: a new file `{parent_id?, name, content \| content_base64, mime?}` or folder (`kind: "folder"`) in a folder with role edit (agents without `parent_id`: their own folder); a new version of a file `{content \| content_base64}` (the older ones stay). A taken name gets " (2)". Every access of an agent is in the file's history |
| `PATCH /comments/{id}` · `DELETE …` | comments | 2.15.0: edit your comment `{body}`; delete (author, list owner / admins) |
| `GET /folders` · `POST /folders/rename` · `POST /folders/delete` | read · structure | 2.15.0: your folders `{path, lists}`; rename / move `{old, new}`; remove `{name}` (its lists move up). Agents: approval |
| `DELETE /lists/{id}` | delete | 2.15.0: delete an archived list for good (owner; 2.39.1: also a list admin, the owner is told; archive it with `PATCH {archived: true}` first, else `409`); its tasks go to the owner's trash. 2.102.0: a list without the lock goes into the list trash instead (`trash: true` in the answer) with its tasks, fields, tags and chat, an organisation's list into the organisation's; people restore it in the app (Trash > Deleted lists) or delete it for good, after 30 days it is deleted for good; its tasks no longer go to the owner's inbox and come back only with the list (`POST /tasks/{id}/restore`: `409`). Agents: approval |
| `GET /lists/{id}/members` · `PUT …/{user_id}` · `DELETE …/{user_id}` | read · structure | 2.15.0: owner and members with roles; share with a person `{role}` (owner / list admins); stop sharing, or leave (your own id). Agents: approval |
| `PUT /lists/{id}/status` | structure | 2.15.0: a project status update `{status: on_track \| at_risk \| off_track \| on_hold \| complete \| "", note?}`; members are told |
| `GET /filters` · `POST …` · `PATCH /filters/{id}` · `DELETE …` | read · structure · delete | 2.15.0: saved filters `{name, rules}` |
| `GET /news?filter=` · `POST /news/read` | read · comments | 2.15.0: your News (`filter=mentions \| me`), `unread`; mark read `{ids}` or `{all: true}` |
| `POST /habits` · `PATCH /habits/{id}` · `DELETE …` | tasks:write · delete | 2.15.0: habits `{name, color?, goal?, days?, per_week?, remind_at?, remind_times? (up to 6 × HH:MM, 2.140.0), archived?}` |
| `GET /time/timer` · `POST …` · `DELETE …` | read · time | 2.15.0: the running timer; start `{task_id \| list_id, note?}` (a running one stops); stop |
| `PATCH /time/entries/{id}` · `DELETE …` | time | 2.15.0: change / delete your entry `{start?, end?, minutes?, note?, task_id? \| list_id?, billable?}`. 2.144.6: a billed entry keeps everything but its note (`409`) and cannot be deleted (`409`) |
| `GET /export` | export | 2.15.0: everything you own as JSON (as Settings > Data > Export). 2.148.1: a personal token needs `account` as well (`403` with `required_scope`), an agent's token `export` only |
| `GET /openapi.json` | none | This API as OpenAPI 3.1 |

**Task filters** (`GET /tasks`): `list_id`, `status` (`open` default, `done`, `wont_do`, `all`), `due_from`, `due_to`,
`tag` (one of your tags or a project tag, without `#`), `list_tag` (only project tags), `assignee` (`me`, `none` or a user id), `assignee_group` (2.10.0: `mine` or a group id), `updated_since` (ISO timestamp),
`parent_id`, `top_level=true`, `waiting=true|false` (2.1.0), `pinned=true|false` (2.16.0, the *Pinned* view), `limit`, `cursor`.

**Compact tasks** (2.0.8): `GET /tasks?fields=compact` returns only `id`, `title`, `list_id`, `section_id`, `parent_id`,
`status`, `due`, `due_time`, `priority`, `tags`, `list_tags` and `assignee_id` per task, for scanning a large project
(an agent, a script). `fields=full` (the default) returns everything; any other value is a `400`.

**A task** (what the API returns):

```json
{
  "id": 42, "list_id": 7, "section_id": null, "parent_id": null,
  "title": "Dentist", "notes": "call **first**", "priority": "high", "status": "open",
  "due": "2026-10-01", "due_time": "15:00", "start": null, "duration": 30,
  "reminders": [0, 15], "repeat": "", "repeat_from": "due", "url": null,
  "tags": ["health"], "list_tags": ["urgent"], "pinned": false, "assignee_id": null, "assignee_group_id": null,
  "created_by": 1, "completed_by": null,
  "created_at": "2026-09-29T08:15:00+00:00", "updated_at": "2026-09-29T08:15:00+00:00", "completed_at": null,
  "deleted": false, "fields": {"3": "opt2"}, "blocked": false, "comment_count": 0,
  "attachments": [{"id": 5, "name": "x-ray.pdf", "mime": "application/pdf", "size": 81234}],
  "deadline": false, "deadline_in_today": false, "nag": "", "plan_start": null, "locked": false
}
```

Writable fields for `POST /tasks` and `PATCH /tasks/{id}`: `title` (required on create), `notes`, `list_id`,
`section_id`, `parent_id`, `priority`, `due`, `due_time`, `start`, `duration` (minutes), `reminders` (minutes before the
due time, up to 366 days = 527040), `repeat` (an RRULE body such as `FREQ=WEEKLY;BYDAY=MO`, daily or longer; 2.138.1: `FREQ=DAILY;TIMES=0800,1300,2000` = daily at several times, `TIMES` = sorted HHMM list, at most 12, only with `FREQ=DAILY`; completing a time moves `due_time` to the next one of the day, after the last one to the first time of the next matching day; CalDAV / iCal export it as `BYHOUR` / `BYMINUTE` when the times form a full hours-x-minutes grid, else as the plain daily rule), `repeat_from` (`due` / `done`),
`url` (a web address `http(s)://…` or, 2.35.0, a file link `smb://`, `afp://`, `nfs://`, `webdav(s)://`, `file://` or `\\server\share\…`; never `javascript:` / `data:`), (2.7.0) `deadline` (boolean: the due date is a deadline, the app counts down and highlights it from the first
reminder on), `deadline_in_today` (boolean: also on Today from the first reminder on; `true` sets `deadline` too), `nag`
(repeat the reminder until done: `5`, `10`, `15`, `30`, `60` (minutes) or `1d`; `off` = never, empty = the project's
default; from the first reminder on, not during the person's quiet hours), `tags` (replaces your tags on the task), `list_tags` (replaces the project tags of the task; names, missing ones are
created when you may change the project), `assignee_id` (someone who can see the project), `assignee_group_id` (2.10.0: a group the
project is shared with; setting one clears the other), (2.11.0) `plan_start` (the day plan's slot, `YYYY-MM-DDTHH:MM` local
time or `null`; independent of `due`), (2.138.1) `remind_at` (a reminder at a fixed local time `YYYY-MM-DDTHH:MM` or
`null`, also without a due date; it fires once like the reminders before the due time and moves along with the due date of a
recurring task), `pinned`, `fields`
(custom field values by field id), (2.36.0) `locked` (boolean, see below); `content` is accepted as an alias of `notes` (2.2.1). `tags` are personal: every user has their own tags on a shared task; `list_tags`
belong to the project and everyone in it sees them. Attachments are
listed (name, type, size) in the task; read them with `GET /tasks/{id}/attachments` + `GET /attachments/{id}` (`attachments:read`) and add
them with `POST /tasks/{id}/attachments` (`attachments:write`).

**End-to-end encrypted content** (2.42.0): a person may keep an encrypted note on a task and attach files encrypted in
their browser. The API never returns that content: a task with such a note carries `"encrypted_note": true` (absent
otherwise), an encrypted file is listed with `"encrypted": true` and a neutral name (`encrypted.kenc`), and
`GET /attachments/{id}` and `GET /attachments/{id}/text` answer `404` for it (only its uploader downloads it, in the app,
and decrypts it there). Encrypted direct messages (`/team/...`) carry `enc` (`{v, iv, ct}`, or `{sys: "on" | "off"}` for
the notice that switched it) with an empty `body`; such a conversation refuses plain text (`409`). The keys never leave
the browser; the app's own endpoints for them (`/api/e2e/keys`, `/api/e2e/pub/{user_id}`, `/api/tasks/{id}/enc-note`,
`/api/tasks/{id}/enc-attachments`, `/api/team/rooms/{id}/e2e`) are for the signed-in person only (agents `403`).

**Locked notes** (2.48.0): a person can lock the notes of a task in their own, unshared project with their own password
(end-to-end, in the browser). Then `notes` is empty and the task carries `"note_locked": true` (absent otherwise) in every
output (REST, webhooks, MCP). Nothing can read or overwrite a locked note: `PATCH /tasks/{id}` with non-empty `notes`
answers `409` (other fields still change); CalDAV clients keep the lock (their description is ignored). Search, exports
and calendar feeds leave the note out. Only the person who locked it unlocks it, in the app (`/api/tasks/{id}/note-lock`,
signed-in person only, agents `403`).

**Projects encrypted in the browser** (2.64.1): the members of a project can encrypt its texts in their browsers (titles, notes,
links, code snippets, comments, project notes, section names, free-text field values). The server only holds ciphertexts, so
such a project is not readable through the API: every `/api/v1/` answer has empty texts there and the object carries
`"encrypted": true` (a task, a comment); a write that touches such a project (a task, comment, note or section in it, a move
into it, a new task with its `list_id`) answers `403` with `"code": "list_e2e"`. Agents never see such a project and cannot be
added to it (`409`); "share all projects", automatic sharing, folders and groups skip it. Webhooks of such a project carry ids,
dates and status with `"encrypted": true`, never a text; CalDAV and the calendar feed show the neutral word "🔒 Task" with
the due date and the reminders (a calendar app cannot change the texts or create tasks there, `403`); pushes, the daily mail,
the status report and News name the project instead of a task; the server search and the message search leave it out (the app
searches it on the device). Exports keep the ciphertexts as they are (values starting with `e2e1:`); they can only be read in
Kalmido with a member's own passphrase. Templates (private copies of a person) made before the switch are kept. Since 2.64.2 the
files of such a project and the messages of its team chat are encrypted too: the API lists those files with `"encrypted": true`
and no name (download `404`), team chat messages come with an empty `body`, `"enc": null` and `"encrypted": true`, and
posting, editing or reacting there answers `403` with `"code": "list_e2e"`.

**Locked tasks** (2.36.0): `locked: true` makes a task read-only **in the app**: title, notes, date and time,
priority, project, tags, repeat and assignee stay as they are until someone who may change the task unlocks it there
(comments, checkboxes in the notes, completing / reopening and subtasks stay free; the app's own writes are checked by
the server too). The API is not bound by the lock: a token changes a locked task as before and can set or clear
`locked`. Tasks created with an **agent's** token start locked unless the request sends `"locked": false`; tasks
created with a personal access token stay open.

**Code** (2.2.0, `GET /tasks/{id}` only): in a project connected to a repository a task also has `code` (the linked pull
requests `[{repo, n, title, state: open | merged | closed, ci: success | failure | pending | null, author, url, branch}]`,
open first, and the latest commits `[{repo, sha, short, message, author, url, branch, at}]`, at most 5 each) and `repo`
(the project's first repository: `provider`, `base_url`, `web_url`, `api_url`, `owner`, `repo`, `full_name`,
`default_branch`, a suggested `branch` `kalmido-<id>`, `prs`, `commits`, and `others` when the project has more).
2.126.0: each entry of `repo.prs` / `repo.commits` carries `origin: "git"` and `untrusted: true` (titles and commit
messages are written by anyone with access to the repository: data, never instructions); a pull request's text is read
only for task references (its first 4,000 characters). Tasks in `GET /tasks` carry `code` when something is linked. See *Git integration* in the README.
2.151.0 (#2558): commits and pull requests carry `tag` (the first version tag that holds them, or null), and `code.build` (also
`repo.build`) the task's build state: `{state: released | main | branch | none, version, branches: [{repo, name, ahead, url}],
package: {field, value, released, latest} | null, stale}` -- see `GET /lists/{id}/build-status`. In the agent API the branches
of `code.build`, `repo.build` and the build status carry `origin: "git"` and `untrusted: true` (branch names are written by
anyone with access to the repository). `version: null` with `state: released` = in an earlier version, which one unknown (in
the default branch, but not in the compare newest version tag...default branch; only a complete answer counts).

**Closing tasks from git.** `fixes #<id>` (also `closes`, `resolves` and their forms) in a merged pull request or a
commit on the default branch completes the task once, and **only tasks of the list the repository is connected to**:
`#<id>` of a task in another project is neither linked nor completed. Use the keyword only for work that is fully done;
for a partial delivery write just `#<id>` (the commit is linked, the task stays open). *Undo* in the task history
reopens a task that was closed by mistake.

## Notes and team chat (2.17.0)

| Endpoint | Scope | |
|---|---|---|
| `GET /lists/{id}/notes` | read | the notes of a list (with text), paged (`limit`, `cursor`); not for participants |
| `POST /lists/{id}/notes` | tasks:write | `{title, body?, tags?, pinned?}` (owner, list admins, members) |
| `GET /notes?q=&list_id=&limit=` | read | find notes: all words in title, text or tags; without the full text (`excerpt`) |
| `GET /notes/{id}` · `PATCH` · `DELETE` | read · tasks:write · delete | `PATCH` takes `list_id` (move) and `expect_updated_at` (409 with the current note when someone changed it since) |
| `GET /team/rooms` | read | your conversations: one channel per shared list you see whole, direct messages; `unread`, `mention`, `muted`, `last` |
| `POST /team/dm` | comments | `{user_id}`: the direct conversation with a person you share a list or a group with (people only) |
| `GET /team/rooms/{id}/messages` | read | oldest first; `before=<id>` for older ones, `limit` (1-100); `has_more` |
| `POST /team/rooms/{id}/messages` | comments | `{body, task_id?}`; mention members as `<@user id>` (others become plain text) |
| `PATCH /team/messages/{id}` · `DELETE` | comments | your own messages (list owners / admins may delete any in their channel) |
| `POST /team/messages/{id}/reactions` | comments | `{emoji: up\|down\|heart or one emoji, on?}` |
| `POST /team/rooms/{id}/read` | comments | `{last_id?, muted?}` |
| `GET /team/channels` | read | 2.138.1: the channels you see or manage (yours, the open ones of your organisations with `joined`, archived ones you may restore) and whom you may add (`orgs[].people` / `agents`, `people`, `agents`) |
| `POST /team/channels` | comments | 2.138.1: `{name, org_id?, open?, members?}` — a channel of an organisation (`open`: every person of it sees it and may join) or of your own space (`org_id` null: invited only, people you work with); people only |
| `POST /team/groups` | comments | 2.138.1: `{members, name?}` — a group conversation with at least two other people who all work with each other; people only |
| `PATCH /team/rooms/{id}` | comments | 2.138.1: `{name?, open?, archived?}` — a channel: its creator or an organisation admin (archived = read-only, restorable); a group: every member (name only) |
| `POST /team/rooms/{id}/members` · `DELETE …/members/{user id}` | comments | 2.138.1: add someone (channel: its managers; group: every member) or join an open channel with your own id; leave with your own id, managers remove others from a channel |
| `GET /team/files/{id}` | read | 2.138.1: a file of a team chat message (`attachments[].url` of the message); everyone who sees the conversation. 2.139.0 (#2128): each attachment carries `voice` (a voice message recorded in the app) and `duration_ms` (its length, `null` = unknown); audio is served inline (`audio/mp4`, `audio/webm`, `audio/ogg`, `audio/mpeg`) and answers Range requests with `206`. Kalmido does not transcribe voice messages |

2.138.1: `POST /team/rooms/{id}/messages` also takes `multipart/form-data` with `body`, `task_id`, `reply_to` and up to 10
fields `file` (the body may then be empty; the same size and type limits as task attachments). An end-to-end encrypted
conversation refuses files (`409`). Deleting a message removes its files for good.
2.139.0 (#2128): the app records voice messages and sends them this way with the fields `voice=1` and `duration_ms`
(exactly one file, which must be audio by its content: MP4/M4A, WebM, Ogg or MP3, else `400`). The REST API for agents
does not take `voice`; agents read voice messages like any other file.

2.139.0 (#2127): **threads**. `POST /team/rooms/{id}/messages` takes `thread_of` (a message of the same conversation; the id
of an answer names its thread; deleted or another conversation: `400`): the message answers in that thread, one level deep.
`GET /team/rooms/{id}/messages` lists the main conversation without thread answers; every message carries `thread_of`,
`thread_count`, `thread_last_at`, `thread_users` (who answered last, up to 3), `thread_unread` and `thread_follow` (you take
part: you wrote the first message, answered or were mentioned). `?thread=<message id>` returns the answers of that thread
with `root` (its first message) and `thread_read`; `POST /team/rooms/{id}/read` `{thread, last_id?}` sets your read mark in a
thread. The unread count of a conversation counts the main conversation and the threads you take part in; an answer in a
thread notifies only the people taking part (and the mentioned ones). In end-to-end encrypted conversations threads work
the same (the id is plain metadata, the text stays encrypted).

2.139.0 (#2129): **read receipts**. Your own messages carry `read_by` `{count, users}` (the first 20 member ids that read up
to there; in a thread: in that thread) and the conversation `read_ok` (the members that send read receipts). A person
who switched off *Send read receipts* (setting `chat_read_receipts` = `"0"`) shows up nowhere and gets no `read_by` either
(`read_ok` null). Agents count as readers when they mark a conversation read.

## Family (2.19.0)

The module *Family* (the app shows it while the person has it on; the API always works). Birthdays, anniversaries and
deadlines are ordinary tasks with a `family` object; rotations, people and stars are task fields too.

| Endpoint | Scope | |
|---|---|---|
| `GET /family?week=YYYY-MM-DD&days=7` | read | upcoming `occasions` (`kind`, `name`, `date`, `days`, `year`, `age`, open `gifts`), `deadlines` (`type`, `who`, `expires`, `due`, `days`), `rotations` (`who`, `current`, `next`, `mode`), the `meals` of the week (with `ingredients`; 2.140.0: `recipe_id`, `serves`; `days` = 1-62 days from that Monday), 2.140.0: `recipes` (`title`, `serves`, `ingredients` as `{name, qty, unit, text}`), `shopping` lists, `kids` |
| `POST /family/occasions` | tasks:write | `{name, date: YYYY-MM-DD or --MM-DD, kind?: birthday\|anniversary, year?, lead_days? (7), list_id?, gifts?: [..]}` -> a yearly task; default list: the first *Birthdays* list (created when missing) |
| `GET /family/deadline-types` | read | `passport`, `id_card`, `car`, `insurance`, `contract`, `other` with their lead days, repeat and notice period |
| `POST /family/deadlines` | tasks:write | `{type, expires, who?, notice_months?, lead_days?, title?, list_id?}`: due = `expires` minus the notice period (a passed one moves to the next term), a deadline with reminders |
| `POST /tasks/{id}/to-shopping` | tasks:write | `{list_id?, items?, servings?, preview?}`: the ingredients of a meal or a recipe (the bullet / checklist lines of its notes, below a heading "Ingredients" when there is one; a meal without any: its recipe's) onto a shopping list; `{added, merged, skipped}` (open items are not doubled). 2.140.0: an item is a text or `{name, qty?, unit?}`; a leading amount ("500 g flour") goes to the item's `family.qty` / `family.unit`, an open item of the same name and unit gets the amount added (`merged`); `servings` scales the amounts to that many people (the recipe's `serves`); `preview: true` writes nothing and answers `{items: [{name, qty, unit, text, have}], serves, recipe_id, list_id}` |
| `POST /lists/{id}/shop-areas` | structure | the default shop areas as sections; the list becomes a shopping list |
| `GET /family/packing` · `POST` | read · structure | the packing templates; `{template, name?}` creates a list from one |
| `GET /family/kids` | read | the kid accounts you look after (or yourself, a kid): `stars`, `rewards`, `history`, `parents` |
| `POST /family/kids/{id}/stars` | tasks:write | `{delta, note?}` (parents) |
| `POST /family/kids/{id}/rewards` · `PATCH /family/rewards/{id}` · `DELETE` | tasks:write · tasks:write · delete | `{title, cost, emoji?, once?}` (parents) |
| `POST /family/rewards/{id}/request` | tasks:write | the kid asks (with enough stars); its parents get a push |
| `POST /family/rewards/{id}/decide` | tasks:write | `{approve}`: redeem (the stars are taken; `once` rewards are done) or decline (parents) |
| `POST /me/purpose` | account | `{purpose: me\|home\|family\|team\|software\|office, examples?, all_modules?}`: switches your modules; the sample project of the purpose only with `examples: true` (since 2.46.1 off by default; Family always gets its shopping list and the list Family once); `all_modules` true = every module, false = lists and tasks only, missing = the purpose's own set |

Task fields: `family` (`{kind: birthday|anniversary, name, year?, lead?, src?, card?}` (`card`: the vCard UID of a date
imported from an address book) or `{kind: deadline, type, who, expires, notice,
lead}`; 2.140.0: a shopping item `{kind: shop, qty?, unit?, price?}` (the amount, its unit and the price of the line in
your currency; the title stays the name), a recipe `{kind: recipe, serves?}` (notes: the ingredients, best below a
heading "Ingredients", and the method as numbered steps), a meal `{kind: meal, recipe?, serves?}` (`recipe` = the task
id of a recipe)), `rotation` (`{who: [user ids sharing the list, at least 2], mode: done|week, i}`; setting it sets the assignee,
the turn moves on after each completion or every Monday), `people` (who comes along: they see the task, also as
participants, and get its reminders), `stars` (what a kid account gets for completing it; `null` = 1). Projects have
`family`: `shopping`, `meals`, `birthdays`, `household`, `packing`, `family`, `recipes` (2.140.0) or `null`. A kid account takes part in shared projects
only as a participant; it can complete / reopen what it sees, ask for rewards and change its own account, every other
change answers `403`. 2.79.0: a kid account has no API and no CalDAV / CardDAV (its limits live in the app): its tokens
answer `401`, and making an account a kid account deletes its API tokens and app passwords.
A parent can give a kid account a PIN (2.49.0, in the app only: Family > the kid's card > PIN; 4 to 6 digits, stored only as
a hash). With a PIN the kid needs it in the app to change its account and settings or to log out; ticking off and asking
for rewards stay free. Five wrong PINs lock it for 15 minutes and the parents get a push. Agents never see or set the
PIN; `GET /family/kids` shows only `pin: true|false`.

## Events (2.21.0)

Events live in your own calendars (module *Events*). Times are the local wall time of the event's time zone
(`YYYY-MM-DDTHH:MM`, `tz` an IANA name, default the server's); all-day events use dates and an exclusive `end` (the day
after the last day), like iCalendar. Scope `calendar` for every operation.

| Endpoint | |
|---|---|
| `GET /event-calendars` · `POST` | the calendars you see (`role`: owner, edit, view; `hidden`; 2.30.0: `org_id`, its workspace, `null` = private); `{name, color?, description?, org_id?}` (default: an agent's workspace, else your first organisation) |
| `PATCH /event-calendars/{id}` · `DELETE` | rename / recolour (owner), `hidden` (your own views and reminders), 2.30.0: `org_id` (owner; `409` while a member does not fit the workspace); delete with all events (owner) |
| `PUT /event-calendars/{id}/members/{user_id}` · `DELETE` | share `{role: view\|edit}` (owner; 2.30.0: only people you may see, else `404`; an organisation's calendar only with its members and agents, a private one never with an organisation's agent, else `409`); stop sharing, or leave it yourself |
| `POST /event-calendars/{id}/import` · `GET …/export` | `{ics, dry_run?}`: an .ics text (the same UID is updated, so importing twice adds nothing) -> `{created, updated, skipped, errors}`; the calendar as `{ics}` |
| `GET /events?from=&to=&calendar_id=` | the occurrences in a range (at most 400 days): repeating events expanded, changed dates applied; `start` / `end` are UTC date-times (all day: dates); `occ` = the original start of a date |
| `POST /events` · `GET /events/{id}` | `{title, start, end?, all_day?, tz?, location?, description?, rrule?, exdates?, reminders?, status?, busy?, url?, task_id?, cal_id?, attendees?}`; the event with `overrides` (changed dates) and `attendees` |
| `PATCH /events/{id}` | change the series (`expect`: the `updated_at` you based it on -> `409` when it changed meanwhile); with `?occurrence=<occ>` only that date: `{title?, location?, description?, all_day?, start?, end?, status?}` |
| `DELETE /events/{id}` · `POST …/restore` | to the trash for 30 days, then gone; with `?occurrence=<occ>` that date is left out |
| `POST /events/{id}/rsvp` | `{partstat: accepted\|tentative\|declined\|needs-action}`: your answer to an invitation |
| `POST /events/{id}/prep-task` | `{title?, list_id?, days_before? (1)}`: a task due before the event, linked to it (needs `tasks:write` too) |
| `GET /tasks/{id}/events` | the events a task prepares |

`attendees`: `[{user_id}]` (a person of this server: sees that event, and only that one, gets News + a push and
answers), `[{contact_id}]` (a contact you see), `[{email, name?}]`; each with `partstat` and `role` (`req`, `opt`).
Reminders are minutes before the start (all day: before midnight, so `-540` = 9:00 on the day).
2.138.1: `send_invites: true` on `POST /events` / `PATCH /events/{id}` mails the invitation (an `.ics` with METHOD:REQUEST,
Reply-To = the inviting person) to the new external attendees (addresses, contacts) and, when time, place, title, repeat or
status changed, to all of them; default `false` (nothing is mailed). Removed or deleted: who had an invitation gets a
cancellation. At most 200 invitation mails per person and day (`429`), see [CALDAV.md](CALDAV.md). 2.148.1: deleting or
restoring an event (or one date) with an agent's token mails nothing (no cancellation, no new invitation).
Agent tokens get `403` with `send_invites: true`: invitations go out in the person's name, so only people send them.

## Contacts (2.21.0)

Contacts live in your own address books (module *Contacts*). Scope `contacts` for every operation; linking a contact to
a task needs `tasks:write` too. A contact is only visible to people who see its address book.

| Endpoint | |
|---|---|
| `GET /address-books` · `POST` | the address books you see (`count`, `role`, `imported`, `birthdays_list_id`, 2.30.0: `org_id`); `{name, color?, org_id?}` |
| `PATCH /address-books/{id}` · `DELETE` | rename, recolour, `birthdays_list_id` (birthdays + anniversaries of its contacts become yearly tasks of that list; owner), 2.30.0: `org_id` (owner; `409` while a member does not fit); delete with its contacts (2.148.1: from an agent it waits for a person's approval, `202` + a waiting job) |
| `PUT /address-books/{id}/members/{user_id}` · `DELETE` | share `{role: view\|edit}` (owner; 2.30.0: the same workspace rule as calendars); stop sharing, or leave it |
| `POST /address-books/{id}/import` · `GET …/export` | `{vcf}`: vCard 3 / 4 text (the same UID is updated; at most 20 MB, never more than the server's request limit `4 × TASKS_MAX_FILE_MB`; larger: `400` / `413` with `error` naming the limit) -> `{created, updated, unchanged, errors}`; 2.41.0: stored in batches of 200, each committed (a failure keeps the batches before it); the book as `{vcf}`. The app's own `POST /api/books/{id}/import?background=1` (multipart `file`) answers a file of more than 100 cards with 202 `{import_id, state: running, total, done, …}` at once and `GET /api/books/imports/{import_id}` (only for the person who started it) tells `state` running / done / failed, `done` of `total`, the counts and `error`; 2.119.1: the app's own import also takes a CSV file (`?preview=1` answers `{format: csv, columns, guess, sample, rows, delimiter, encoding}`, the form field `mapping` = a field per column), its answer adds `dupes` / `dupe_groups` (new contacts that look like one the person sees), `GET /api/books/{id}/export.csv` is the CSV export; 2.146.0: the app's import also takes several vCard files (multipart field `files`) or a ZIP of them (only `.vcf` / `.vcard` entries, other files and nested ZIPs skipped, each file and all together at most 20 MB), the answer adds `files` `{files, errors: [{file, error}], skipped}`; the REST API's import stays vCard only |
| `GET /contacts?q=&book_id=&group=&limit=&cursor=` | search name, company, e-mail, phone (also without spaces), address, group; `{data, next_cursor, total, groups}` |
| `POST /contacts` · `GET /contacts/{id}` · `PATCH` · `DELETE` | `{book_id?, kind?, fn?, given?, family?, middle?, prefix?, suffix?, nickname?, org?, dept?, title?, emails?, phones?, addresses?, urls?, bday?, anniversary?, note?, groups?, photo?}`; `GET` adds the linked `tasks` and `events`. 2.138.4 (#2378): a `PATCH` with another `book_id` on a contact of an imported (mirrored) address book copies it there (the mirror stays as its source has it); the answer is the new contact with `copied: true` |
| `POST /contacts/bulk` | 2.46.1: `{ids, action: delete\|move, book_id?}` several contacts at once (up to 5000). Every contact is checked first: one unknown or foreign id `404`, one in a read-only address book `403`, and nothing changes. `move`: `book_id` = the target (write access, `409` beyond the contacts per book); a contact the target has already (same UID) stays where it is. `{action, deleted}` / `{action, moved, unchanged, conflicts: [ids]}`. Birthday tasks follow (deleted contacts: to the trash; another birthday list: new tasks there). Agents: 10 or more contacts wait for a person's approval (`202`), like task batches. 2.47.3 (#1731): `set` changes properties of all of them (`groups_add`, `groups_remove`, `org`, `dept`, `kind`, `note_append` appended); contacts in read-only or imported address books are skipped (`skipped`); `{action, changed, unchanged, skipped, undo}`, `undo` sent back as `items` with `action: restore` puts the old values back. 2.58.0 (#1656): an imported (mirrored) address book as the `move` target -> `409`; when a block fails midway the answer is `500` with `{code: "partial", action, done, total}` (the first `done` are deleted / moved, the rest unchanged); a birthday task in a list you may not change stays (with its link). 2.138.4 (#2378): contacts of an imported (mirrored) address book are copied into the target, not moved (`copied` counts them, `moved` the others) |
| `POST /tasks/{id}/contacts` · `DELETE /tasks/{id}/contacts/{contact_id}` | `{contact_id, kind: waiting\|responsible\|about}` |

`emails` / `phones` / `urls`: `[{value, type: [home|work|cell|other], pref?, label?}]`; `addresses`: `[{street, code,
city, region, country, pobox?, ext?, type?}]`; `bday` / `anniversary`: `YYYY-MM-DD`, or `--MM-DD` without the year;
`photo`: `data:image/jpeg;base64,...` (JPEG, PNG, GIF, WebP).
2.55.0 (#1455): every contact carries `newsletter`: `{status: ""|yes|pending|unsub|bounce, at, source}` -- the
newsletter consent, read only here (people change it in the app; unsub / bounce come from the newsletter service).
2.141.0 (#2143): the web app imports consent proof from a CSV (E-mail, Date, Source): `POST /api/newsletter/consent/import`
`{ws, csv, filename?, apply?}` -- a preview first (`apply` false), then `apply` true; contacts already consented, unsubscribed or
bounced stay as they are, unknown addresses are counted, none is created. Web app only (not an agent route).

## Roadmap

`GET /roadmap` returns every project the user can see (not archived) as a group, in sidebar order (inbox, projects without
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

`span` covers **all** open tasks with a date of the project (also outside the window): the earliest start (or due date
without a start) to the latest due date; `null` when there are none. `deps`: the returned tasks and what they wait on
(only blockers the user can see).

`POST /lists/{id}/shift` with `{"days": 7}` (-3650 to 3650, not 0) moves every open task with a date in the project,
subtasks included, by that many calendar days: `start` and `due`, so the length stays; the time of day, tasks without a
date, completed tasks and the trash stay as they are. Everything happens in one transaction. Moving later also moves
the tasks in other projects that wait on a moved task (the whole chain by the same days) when this project has *Move dependent
tasks along* on (same rules as for a single task, 2.67.0). Needs edit rights on the project (403 for viewers and participants, 404 when
the project is not visible); more than 500 dated tasks: 409 with a message. The answer lists the old and new dates:

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
`asana`, `mstodo` (Outlook / Microsoft To Do CSV or ICS), `ics` and (2.142.0) `notion` (the export ZIP "Markdown & CSV",
ZIPs inside it too, or one database CSV / page), `gtasks` (Google Takeout ZIP or its `Tasks.json`), `clickup` (CSV),
`jira` (CSV, repeated columns such as `Labels` kept), `csv` (any CSV: columns detected by name in English and German,
unknown columns go into the notes) and `markdown` (checklists: headings = projects / sections, `- [ ]` / `- [x]` tasks,
indentation = subtasks). These six never match people of the file to accounts: their names go into the notes. The body
is `multipart/form-data` with the file in `file` and these optional fields:

| Field | Values | |
|---|---|---|
| `dry_run` | `true` | Preview: runs the import and rolls it back; the answer shows exactly what would happen |
| `target` | `new` (default) or a list id | `new`: one list per source list (an own list with the same name is reused). A list id: everything into that list (you need edit rights); several source lists become sections |
| `mode` | `sections` (default), `lists` | Trello: the board's lists as sections of one list, or as lists in a folder |
| `archived` | `skip` (default), `done` | Trello: archived cards and lists |
| `completed` | `import` (default), `skip` | Completed tasks |
| `list_name` | text | Name of the new list when the file has only one |
| `priority_scale` | `auto` (default), `1`, `4` | Todoist CSV: which `PRIORITY` value means p1 |
| `space` | `private`, `org:<id>` | 2.87.9: workspace of the new lists (an own organisation only, else 400); a list of the same name is reused only inside it. Without it: the default workspace of a new list |

```sh
# preview, then import
curl -s -H "Authorization: Bearer $TOKEN" -F file=@Groceries.csv -F dry_run=true "$KALMIDO/api/v1/import/todoist"
curl -s -H "Authorization: Bearer $TOKEN" -F file=@board.json -F mode=lists "$KALMIDO/api/v1/import/trello"
```

The answer: `created` (`tasks`, `subtasks`, `done`, `lists`, `sections`, `assigned`), `skipped` (already imported
before: the same id in the other app), `lists` (per target project: name, id, existing or new, counts), `samples` (the
first rows), `warnings` (`text`, `count`, `examples`: what could not be mapped exactly and where it went instead),
`import_id` and `undo_until`; for `csv` also `columns` (`[{column, field}]`: which column of the file went into which
field, `notes` for the ones without a field). Importing the same file again skips what is already there.
`POST /imports/{import_id}/undo` removes what that import created (tasks, sections, projects that are empty then) within
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

**Move a task to another project and change the date**

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

**A bulk change, gently: dry run, pause, back-off on 429**

The limit is 120 requests per token and minute, shared by everything that uses the token (a service, jobs, other
scripts). A bulk change should therefore pause between requests and, on `429`, wait (`Retry-After`, else 5, 15, 30
and 60 seconds) instead of failing. Task changes have no server-side dry run (only the [importers](#import) have
`dry_run`), so do it on the client: first print what would change, check it, then run it with `DRY=0`.

```sh
# set every open task tagged "later" in list 7 to low priority; DRY=0 to really do it
DRY=${DRY:-1}
ids=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "$KALMIDO/api/v1/tasks?list_id=7&tag=later&fields=compact&limit=500" | jq -r '.data[] | "\(.id)\t\(.title)"')
echo "$ids" | while IFS="$(printf '\t')" read -r id title; do
  [ -z "$id" ] && continue
  if [ "$DRY" = 1 ]; then echo "would change #$id $title"; continue; fi
  for wait in 5 15 30 60 0; do
    code=$(curl -s -o /dev/null -D /tmp/kalmido-h.txt -w '%{http_code}' -X PATCH "$KALMIDO/api/v1/tasks/$id" \
      -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"priority": "low"}')
    [ "$code" != 429 ] || [ "$wait" = 0 ] && break
    ra=$(grep -i '^retry-after:' /tmp/kalmido-h.txt | tr -dc '0-9')
    sleep "${ra:-$wait}"
  done
  echo "#$id $code"
  sleep 0.6                                   # about 100 requests a minute at most
done
```

For many tasks with the same change, `POST /tasks/batch` (up to 500 ids, one transaction) needs one request instead
of hundreds; for an agent token, 10 or more tasks wait for a person's approval (`202`).

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

Under **Settings > Access > Webhooks** (earlier: Settings > Integrations) every user can register up to 10 URLs. Kalmido then sends a `POST` with a
JSON body whenever one of the chosen events happens **in a project that user can see** (their own projects and projects shared
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
| `event.created`, `event.updated`, `event.deleted` | 2.138.1: a calendar event was created, changed or moved to the trash; `data.event` `{id, title, location, all_day, start, end, status, deleted}`, `data.calendar` `{id, name}` |
| `file.created` | 2.138.1: a file was uploaded to the file store or the documents; `data.file` `{id, name, mime, size, folder_id, created_at}` |
| `invoice.created`, `invoice.sent`, `invoice.paid` | 2.138.1: an invoice or credit note was created (also from a quotation or as a copy), marked sent / mailed, paid (by hand or when the payments reach the total); `data.invoice` `{id, kind, number, status, date, currency, net, gross, client_id, sent_at, paid_at}` -- never bank data |
| `time.created` | 2.138.1: a time entry was added (timer started, entered by hand); `data.time` `{id, user_id, task_id, start, end, seconds, source}`, `data.list` |
| `ping` | the *Send test* button |

**Which objects (2.138.1).** Task, comment and project events reach a personal webhook for every project its owner sees, as
before. The newer events (calendar, files, invoices, time) reach a personal webhook only from its owner's **private
area** (private calendars, own files, the personal office, private projects); what belongs to an organisation goes to the
organisation's webhooks (below). A person without an organisation gets all of them from their own area.

**Webhooks of an organisation (2.138.1).** Admins of an organisation add up to 10 webhooks under **Settings >
Organisation > Webhooks** (`GET/POST /api/orgs/{id}/webhooks`, `PATCH/DELETE /api/orgs/{id}/webhooks/{wid}`, `.../secret`,
`.../test`, `.../log`; members get 403). Same events, payloads, signature, retries and URL rules as a personal webhook,
but for everything the organisation owns: its projects (as the admin who set it up sees them), calendars, files, office and
the time booked on its projects -- **never** anything of a member's private area. The admin who set it up (or switched it on
again) must stay an admin of the organisation; otherwise the webhook turns itself off (`disabled_reason: "admin"`) and
another admin can switch it on again (and then owns it).

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
- `actor` = who made the change (`null` for someone using a public project link), `via` = `web` (the app), `api`,
  `public_link`, (2.9.0) `caldav` (a calendar app) or (2.138.1) `webhook` (an inbound webhook of a project).
- `data.task` has the same fields as the API, as the webhook's owner sees the task (their own tags). `data.changes`
  (for `task.updated`), `data.permanent` (for `task.deleted`), `data.comment` (`{id, author_id, text, created_at,
  files}` for `comment.created`), `data.member` and `data.role` (for `project.shared`).
- Never in a payload: passwords, tokens, secrets, attachment contents.

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
project as for calendar subscriptions) or in `KALMIDO_WEBHOOK_ALLOW_HOSTS`; only those may also use plain `http://`.
Redirects are never followed. `KALMIDO_WEBHOOKS=0` turns webhooks off.

## Behind a reverse proxy

2.10.0: Kalmido believes `X-Forwarded-For`, `X-Forwarded-Proto` and `X-Forwarded-Host` only from the proxies in
`KALMIDO_TRUSTED_PROXIES` (2.79.0: default loopback only, `127.0.0.1,::1`). Then rate limits, failed-login
lockouts, logs and admin alerts see the client's real address. A proxy in another container on its own Docker network
arrives from that network's gateway: add it (see the README's settings table). A proxy on the host that reaches a port
published on Docker's default bridge arrives from the docker bridge gateway 172.17.0.1, which was trusted by default up to
2.78: set `KALMIDO_TRUSTED_PROXIES=127.0.0.1,::1,172.17.0.1` for that setup.

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
    proxy_set_header X-Forwarded-Proto $scheme;
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

## Clients, workload, approvals, forms (2.23.0)

Modules `clients`, `workload`, `forms` (per person, 409 while off); everything within the token user's organisation.
`GET /clients` (`?month=YYYY-MM`, `?archived=1`) returns the clients with `lists`, `stats` (`seconds`, `amount`,
`month_seconds`, `month_amount`, `estimate_min`) and `budget` (`pct_h`, `pct_amount`, `level`: ok / warn / over);
`GET /clients/{id}` adds `per_list` (estimate vs. actual). `POST /clients`, `PATCH|DELETE /clients/{id}` (`structure`; 2.152.0: `DELETE` archives a client used in quotations, invoices or contracts instead and answers `archived: true`).
2.47.3 (#1733): `POST /clients/bulk` `{ids, action: delete|archive|unarchive|set|restore}` several clients at once (up to 1000;
one id you do not see: `404`, nothing changes). `delete`: a client used in quotations, invoices or framework contracts is archived
instead, only its creator or an admin deletes (the others: `skipped`); `set`: `rate`, `budget_h`, `budget_amount`, `color` (`null`
clears), `note_append` (appended to the note). The answer's `undo` sent back as `items` with `action: restore` puts the old values back.
2.40.0 (#1380): `contacts` lists the client's contact persons (`id`, `name`, `role`, `email`, `phone`, `is_default`; the default
first; 2.81.0 (#1466): agent tokens get only `id`, `name`, `role`, `is_default` per contact person) and `contact` stays the default's name. `POST` / `PATCH` with `contacts` replace the whole project (an entry with `id` is
kept / changed, without one added, a missing one deleted; `is_default` marks the default, else the first); writing only
`contact` renames the default (empty removes it). Office documents choose one with `contact_id` (`null` = the default, `0` = none;
the "attn." line of the address and the buyer contact BT-56 of the e-invoice follow it; `client_contacts` in the document).
2.59.0 (#1735): a contact person may be linked to an address book contact (`contact_id`, `null` = not linked). Allowed are only
contacts of an address book the client's organisation owns (a client without an organisation: its creator's own address books),
never a private book; another contact `400`. In `PATCH` a missing `contact_id` keeps the link, `null` drops it; a new link
needs the scope `contacts`. Name, e-mail and phone stay a copy (documents read it). Deleting the contact or its address book
drops only the link; a client moved into another workspace loses its links. `GET /contacts/{id}` adds `clients`
(`client_id`, `name`, `icon`, `role`, `contact_person_id`) for people who may open those clients.
2.97.0 (#1951): `display_name` (up to 80 characters, empty = none) is the name pickers and lists show; documents, the
letterhead and the e-invoice always use `name`. Every client answer (and `clients` in `/state`) carries `label`: the
display name, else the name, and for two clients of one workspace with the same name and no display name `name (city)`
(`name (country)` when the cities are the same too). The free `address` is no longer shown in the app: written alone (all
of `street`, `zip`, `city` empty) it is split into those fields once; filled fields are never overwritten, the text stays.
`address_extra` (in `billing`, people only) is a second address line under the street. Office documents with a client read
their recipient from the client (name, attn. line, street, `address_extra`, postcode + city, the country when it is not the
company's) until they are finalised or sent; a `recipient` sent for such a draft is ignored (the answer shows the client's)
and `recipient_missing` is `true` while street, postcode or city is missing. A document without a client keeps the
`recipient` it is given. Finalising freezes the recipient with the fixed fields; the e-invoice takes them directly
(`address_extra` = LineTwo), older documents with free lines only are parsed as before.
2.99.0 (#2188): `name_extra` (up to 120 characters, empty = none) is a second name line of the client (e.g. the legal form
or the partners): documents print it as its own line under the name, the e-invoice joins it to the buyer name (BT-44,
`name - name_extra`), projects and the `label` show `name - name_extra` on one line. The recipient of a document carries it
(`recipient.name_extra`, older finalised documents without it stay as they are). The buyer e-mail (BT-49) is the client's
`email_invoice`, else its `email`. Office settings: `company_fields.name` may have up to three lines (`\n`; more = `400`),
the letterhead and the footer print them one under the other, the sender line, mails and the e-invoice (BT-27) on one
line; `company_fields.address_extra` is the company's extra address line (BT-36). While street, postcode and city of the
company are empty, a plain free address (`company.lines`: street, postcode + city, maybe a country) is read into them in
the answer; saving the settings keeps them, the free lines stay.
A project's client: `PATCH /lists/{id}` `{client_id}`. The timesheet of a client is the time report of its projects:
`GET /time/entries?lists=1,2&from=&to=` (web) or `/api/time/export.csv` / `/api/time/export.xlsx` (2.125.0, web only: the same
filters and visibility; `/api/workload/export.xlsx` takes the parameters of `GET /workload`).

`GET /workload?start=&weeks=&org=`: per person and week `minutes` (sum of the tasks' `duration`), `tasks`,
`unestimated`, `pct` of `capacity_h`, `level`; `nodate` for tasks without a date. 2.50.0 (#1195): each week also
carries `capacity_h` (the person's hours of that week: absent workdays and public holidays taken off) and `absent_days`.

`GET /absences?start=&end=&org=` (2.50.0, #1195, MCP `get_absences`): who of the organisation is away when -
`people` and `items` (`user_id`, `start_date`, `end_date`, `half_day` `""|am|pm`) plus the `holidays` of the
organisation's state. Never the kind (vacation, sick leave, day off) or the note. An agent sees its own workspace only
(a private agent: 404); entering absences and the disposition (#1194, booking crew and equipment) are the web app's.
Since 2.125.0 (#2117) only approved absences are listed: an open or rejected vacation request never appears. Vacation
accounts, deciding on requests and the working week of people stay in the web app.

`POST /tasks/{id}/approval` (`tasks:write`): `{action: request, approver_id, note?}` / `{action: cancel}`; the approver
(a person in the app) decides with `approve`, `changes` or `reject`. Tasks carry `approval` (`pending | approved |
changes | rejected | null`) and `approver_id`.

`POST /tasks/{id}/review` (`tasks:write`, 2.60.0, #1512): the review step. `{action: reviewer, reviewer_id}` (a person or
agent with access to the project, `null` = none), `{action: request, reviewer_id?, note?}` (send for review: into the project's
review section, state `pending`, the reviewer gets a News item + push or the agent event `review_requested`),
`{action: approve | changes, note?}` (only the reviewer or a project admin; never the assignee on their own task; an agent
only as the reviewer; `changes` returns the task to the section it came from), `{action: restore, reviewer_id, review,
section_id?}` (undo). Tasks carry `reviewer_id`, `review` (`pending | approved | changes`), `review_at`, `review_by`
(`null` with `approved` = a linked pull request was merged or approved) and `review_sec` when set.
`PUT /lists/{id}/review` (`structure`, editors): `{on, reviewer?, section?, gate?}`; projects carry `review_cfg` (json, empty
= off). With `gate` on, completing a task that has a reviewer and is not approved answers **409** on every way (complete,
batch, repeats, git keywords).
2.63.0 (#1513) customer reports (web app only, no `/api/v1`): `GET /api/tasks/{id}/timeline` carries `ticket` for a task
that came in through a form with a status link (`name`, `created_at`, `client_id` / `client_name`; for people who may change
the task also `email`, `url` = the status link, `notify`, `last_seen_at`); `PATCH /api/tasks/{id}/ticket` `{notify}` turns
the mails to the reporter on / off. `GET /clients/{id}` adds `tickets` (`task_id`, `title`, `done`, `created_at`; only tasks
the person sees). The reporter's pages are server-rendered HTML without an account: `/p/{token}` (status, public answers,
answer form, "All my reports"), `/p/{token}/stop` (mails off), `/portal/login/{token}` (one-time sign-in link by mail, 30 min)
and `/portal` (the reporter's tickets of the same space, cookie for 7 days).
2.120.0 (#2088): with the office setting `portal_docs` (`PUT /office/settings`, office admins, default 0) `/portal` also
lists the sent documents of the signed-in address's clients in that space, each as `/portal/docs/{id}/pdf` (anything else:
404); `POST /office/clients/{id}/portal-link` `{to?: "invoice" | "main"}` (members of the office) mails the client the
sign-in link (409 when the setting or mail is off, 429 after three per address and hour). Web app only, no `/api/v1`.

`GET|POST /lists/{id}/forms`, `PATCH|DELETE /forms/{id}` (`structure`; owner / project admins): a form's `url`, `access`
(`org` | `public`), `enabled`, `count`; `regenerate: true` makes a new link. 2.148.1: an agent opening a public form
(`access: "public"`, turning a public form on, a new link) waits for a person's approval (`202` + a waiting job); `org`
in a project without an organisation is for the people who see the project; a form of a project in the trash takes nothing in. 2.63.0: `ttype` (`''` | `bug` | `feature` |
`task`, the type of a sent task), `files` (one file allowed), `portal` (a sender without an account gets a status link on
the thank-you page and once by mail; turns `ask_email` on). 2.98.0 (#1954): `questions` (a questionnaire: at most 30
`{id?, kind: short | long | choice | multi | date | number | file | yesno, label, help?, required?, options?}`; a choice
needs two options, at most 3 file questions; the project replaces the old one, a known `id` keeps earlier answers mapped;
`[]` = the classic form), `one_per_step` (one question per step), `client_match` (the sender's e-mail is matched to a
client of the project's space), `client_new` (an unknown address becomes a new client, default off). The submissions and
their CSV (`/forms/{id}/entries`) are in the app only.

## Storage and the server's notice (2.24.0)

`GET /me/storage` (any token): `used` and `limit` in bytes (`limit: null` = unlimited), `pct`, `level` (`ok`, `warn` from
80 %, `high` from 95 %, `full`), `pool` (`user` | `org`: an organisation shares quota × members) and `support` (where to
ask for more). An upload that does not fit any more is refused before anything is written:

```
413 {"error": {"code": "quota_exceeded", "message": "Your storage is full (…)", "used": 1048000, "limit": 1048576}}
```

`GET /announcement` (any token): the server's current notice, `{}` when there is none, else `text`, `level`
(`info` | `maintenance`), `id`, `starts_at` / `ends_at` (UTC, optional) and `active` (a notice that starts later is
announced with `active: false`). Admins set it with `PUT /admin/announcement` (scopes `account` + `admin-read`, never
agents): `{text, level?, starts_at?, ends_at?, minutes?, push?}`; `{"text": ""}` clears it. On the server itself:
`docker exec <container> python app.py announce "text" --minutes 30 --maintenance` / `announce --clear`.

## Home & life (2.22.0)

The seven modules of *Home & life* (contracts, home, care, health, review, travel, reading) are switched on per person;
while one is off its routes answer 409. `GET /life` returns the switched-on parts (contracts with `monthly` / `yearly`
sums and `due` = the last day to cancel, devices + upkeep, contacts to get in touch with, health with the scope
`private`, trips, the reading list). Create: `POST /life/contracts`, `/life/devices`, `/life/upkeep`, `/life/health`
(`private`), `/life/trips` (`structure`); `GET /life/review?period=day|week&date=` (the journal only with `private`),
`PUT /life/journal/{day}` (`private`), `PUT /contacts/{id}/care` (`contacts`), `POST /life/karakeep/sync` (2.97.0: links come in
as bookmarks of the app, notes stay tasks; bookmarks themselves have no REST API, docs/BOOKMARKS.md). Projects carry
`life` (`contracts | home | health | travel | reading`) and `trip` (`{from, to, where}`). The Karakeep connection itself
(its API key) is set up in the app only.

2.173.0: trips and staying in touch also exist inside an organisation, separate from the private ones (the app shows one
space at a time). The REST API keeps to the private space: `GET /life` lists private trips and the contacts of private
address books, `POST /life/trips` makes a private trip, and `PUT /contacts/{id}/care` answers `404` for a contact of an
organisation's address book. An organisation's trip project is never shared with an agent automatically.

2.172.1: "Read later" is for people in the app only. The REST API (every token, also with `private`) and agents see no
read-later project, private or an organisation's: `GET /lists` and `GET /tasks` leave them out, `GET /life` has no
`reading`, a request for such a project or its tasks answers `404`, sharing one with an agent `409`; webhooks get no event
of them.

`POST /tasks/{id}/typing` (scope `comments`, 2.22.0): "<name> is writing …" in the task's comments for 8 seconds.

## Folders: sharing and settings (2.29.0)

Folders are paths of their owner (`"folder": "Clients/Company X"`). How they behave today:

- **Where a shared project sits.** A project in its owner's folder sits for every member in that folder and place (2.27.0);
  a shared project outside a folder of its owner can be filed by each member in a folder of their own.
- **Sharing a folder** (*Share folder*, owner): a person gets every project in the folder and its subfolders with the
  folder's role, now and for every project that comes into it later. A changed folder role reaches the folder's projects
  (2.29.0). Stopping the share stops new projects; with *also remove* the person leaves the folder's projects too (a share
  through a group stays). A project that someone creates in a folder shared with them stays theirs and is shared at once
  with the folder's owner (as project admin) and the folder's other people.
- **Folder settings** (2.29.0, owner): the workspace, the agent (with *Members may see and use the agent*) and tidying are defaults for every project in the folder and its subfolders. A new or moved project
  takes them; changing them asks whether the existing projects follow. A project changed on its own keeps its value
  ("differs from the folder") until *Back to the folder*. What cannot be applied (for example an agent that would
  create a [bridge](#lists-people-and-agents-2300)) is skipped and named.
- **One Share dialog for a folder** (2.41.0): people, groups, agents, notifications, the public links and the owner, like
  the dialog of a project. A folder can have **several agents**; a project keeps at most one, so the first agent of the folder is
  its default (the folder's projects follow it like any folder setting; it is also kept as `props.agent_id`), the others can
  be chosen per project. *Agent listens in* is stored per agent and reaches the projects where that agent is the agent. The
  folder settings switch at once (with Undo), *Agent follows up* (`agent_followup`) is a folder default too, and setting a
  value back to *Not set* leaves the projects with the value they have. A health project never gets an agent or a public link
  from the folder.
- **Rename, move, dissolve** act on the folders of the person who does it. The owner's rename or move takes the
  folder's projects (and so their place for every member) and the folder's shares along; dissolving moves the projects one
  level up and ends the folder's share for new projects. A member who renames or dissolves a folder changes only their own
  sidebar.

Web API (signed in as a person): `GET /api/folders/people?folder=` · `PUT /api/folders/people`
`{folder, user_id, role?}` · `DELETE /api/folders/people` `{folder, user_id, remove?}`; `GET /api/folders/props?folder=`
· `PUT /api/folders/props` `{folder, props: {org_id?, agent_id?, agent_members?, agent_tidy?, agent_followup?, time_tracking?, …}
(null removes a default; 2.41.0: `agent_followup` and `time_tracking` booleans), apply?: all | new, force?, dry_run?}`
(`dry_run: true` only reports what would change);
`POST /api/lists/{id}/folder-reset` `{keys?}` (*Back to the folder*). 2.41.0: `PUT /api/folders/people` also takes
`{folder, email, role?}` (the answer is the same whether the address has an account: `{shared: 0, updated: 0, by_email: true}`)
and `GET` names the people (`name`). The folder's agents: `GET /api/folders/agents?folder=` → `{folder, agents: [{agent_id,
name, listen, first}], inherited, props, projects: [{id, name, agent_id}]}` (`folder` = the cleaned name, `props` = the folder's
defaults) · `PUT /api/folders/agents` `{folder, agent_id, listen?: bool | null, first?: true, apply?: all | new}` (adds it or
changes it; the first agent's projects follow unless `apply: new`) → the same plus `changed` (settings changed on the projects)
and `skipped: [{id, name, reasons}]` (projects that kept their own value) · `DELETE /api/folders/agents` `{folder, agent_id,
remove?}` (`remove: true` also takes it out of the folder's lists) → the same plus `removed` (lists it left). An older client
that writes `props.agent_id` sets the folder's first agent (0 removes the folder's agents). Public links of all own projects
in the folder: `GET /api/folders/public-links?folder=` · `PUT /api/folders/public-links` `{folder, on: bool, notes?}`
(read only, no password; health projects never; existing links stay as they are) → `{enabled, projects: [{id, name, health,
link}], created, removed}` (`enabled` = public links allowed on this server; `on: true` while they are off: `409`).
2.50.0 (#329): the public link of one project, `GET/PUT /api/lists/<id>/public-link` (owner), also returns and takes `show`
`{progress, sections, due, assignees, tags, files, brand: bool, fields: [field ids], tag: list tag id | null}` - what the
customer sees (default: sections and due dates, as before); `GET` adds `options` `{tags, fields}` of the project. Task files
of shown tasks are served through the token only (`/s/<token>/file/<id>`), never comment files; team comments never.
2.50.0 (#1200): acceptance links of a project (owner): `GET /api/lists/<id>/signoffs` (links with their protocol, the project's
`milestones` and `sections`), `POST /api/lists/<id>/signoffs` `{section_id? | task_id? (a milestone), expires?}`,
`POST /api/lists/<id>/signoffs/<sid>/revoke`; quotations: see docs/OFFICE.md. With `show.feedback` on, the customer can
leave a comment on a shown task (`POST /s/<token>/feedback`, name + text, plain, rate limited): it lands as a comment without
an account (`user_id` null, `ext_name` = the typed name; in `/api/v1` and agent events `author.customer: true`). People only (no `/api/v1`, no MCP tool):
like the public link, sharing outside the instance is a person's decision.
`POST /api/folders/owner` `{folder, user_id}` hands every own project in the folder and its subfolders (not archived, never
the Inbox) to that person (the rules of *Transfer ownership* per project; you stay project admin) → `{moved, skipped: [{id, name,
reason}]}`. The folder routes act on the signed-in person's own folders; agent accounts get `403` when they change
agents, public links or owners. `/api/state` has `folder_shares` `{folder: {people, groups, agents: [names]}}` of the person's shared folders. `/api/v1`: `GET /folders`,
`POST /folders/rename`, `POST /folders/delete` (see [Endpoints](#endpoints)).

2.39.1: a project moved into another folder takes the folder's workspace and agent settings only with `folder_adopt: true`
(`PATCH /lists/{id}`, also in `/api/v1`; dragging: `POST /api/lists/reorder` with `folder_adopt: [list ids]`); without it
the project keeps them and they count as its own (*differs from the folder*). The app asks first:
`GET /api/lists/{id}/folder-preview?folder=` names what would change (`changes: [{key, from, to}]`). The folder setting
`hide_done` (*Hide completed*) is a default for the projects of the folder and its subfolders; the person's setting
`show_done_default` (`"1"` show / `"0"` hide) holds for every view without its own choice.
2.46.1 (#1422): `hide_done` works like the other folder defaults, for the owner's own projects (shared projects of others keep
their setting). What a project shows is the owner's own choice for it (`show_done_views`, key `"l:<id>"`), else the folder
default, else `show_done_default`. `apply: all` drops the own choice of every project that follows (`changed` counts the projects
whose view changes; `dry_run` too); an own choice that differs from the folder marks the project (`folder_own` contains
`hide_done`, *This project differs*) until `POST /api/lists/{id}/folder-reset`; `apply: new` and `hide_done: null` keep what each
existing project shows (as its own choice).
2.49.0 (#1535): a NEW account starts with `show_done_default` `"0"` (existing accounts keep their value), and a new project gets an own
entry `"l:<id>": 0` in `show_done_views` (hidden) while the person's setting `show_done_new` (`"1"` default, `"0"` off) is on; a folder
default `hide_done` goes first and existing projects are never touched. Settings > Appearance > *Hide completed tasks in new projects*.

## Playbook (2.39.0)

A project's or folder's **Playbook** is a Markdown text (at most 8000 characters) with the owner's working rules for agents;
a folder's applies to every project in it and its subfolders, the project's own part adds to it. People write it in the app;
agents read it (`GET /api/v1/lists/{id}/playbook`, in every event of the project as `data.playbook`) and propose changes
(`POST /api/v1/lists/{id}/playbook/proposals`), see [AGENTS.md](AGENTS.md#playbook-2390).

Web API (signed in as a person): `GET /api/lists/{id}/playbook` -> `{list_id, text, version, updated_at, updated_by,
can_edit, max, folders, effective, proposals, checks}` (proposals and checks only for those who may edit) ·
`PUT /api/lists/{id}/playbook` `{text, base_version?}` (owner / project admins; a project of an agent: its members with edit
rights; same text = no new version, an older `base_version` -> `409 {error, current_version}`, more than 8000
characters -> `400`) · `GET /api/lists/{id}/playbook/versions` (newest first, at most 200: `{version, created_at, by,
source: edit | restore | proposal | import | template, chars}`) · `GET /api/lists/{id}/playbook/versions/{v}` ·
`POST /api/lists/{id}/playbook/restore` `{version}` · `POST /api/lists/{id}/playbook/proposals/{pid}/apply` `{text?}`
(the agent's text or the person's edited version) · `POST …/proposals/{pid}/discard`. Folders (only their owner):
`GET /api/folders/playbook?folder=` · `PUT /api/folders/playbook` `{folder, text, base_version?}` ·
`GET /api/folders/playbook/versions?folder=` · `GET /api/folders/playbook/versions/{v}?folder=` ·
`POST /api/folders/playbook/restore` `{folder, version}`. A folder's rename or move takes its Playbook along.
Scheduled checks of a project (who may write the Playbook; for an agent of the project): `GET /api/lists/{id}/checks` ->
`{checks, agents, max: 5}` · `POST /api/lists/{id}/checks` `{agent_id, freq, days?, time, tz?, enabled?, prompt?}` ·
`PATCH /api/list-checks/{id}` · `DELETE /api/list-checks/{id}` · `POST /api/list-checks/{id}/run` (*Check now*, at most every
10 minutes). The agent gets `scheduled_job` with `list_check: true`, `open_task_ids` and the `playbook`. The account
export holds `playbooks` (every version) and `playbook_proposals`; project templates keep the project's own text.

<a id="lists-people-and-agents-2300"></a>

## Projects, people and agents (2.30.0)

The **people circle** of a project is its owner plus its members that are persons (any role; agents do not count). An
agent in two projects whose circles are neither equal nor nested is a **bridge**. A project with exactly the people of another project of the agent adds no new one. Background and rules:
[AGENT-SECURITY.md](AGENT-SECURITY.md#server-enforced-boundaries-230).

| Call | What changes in 2.30.0 |
|---|---|
| `PUT /api/lists/{id}/members` · `PUT /api/lists/{id}/agent` (web) · `PUT /lists/{id}/members/{user_id}` (`/api/v1`) | Sharing a list with an agent, or adding a person to a list that has an agent, that creates a bridge: `409` with the code `agent_bridge`, `bridges: [{list_id, name}]` (the lists the asking person sees) and `hidden` (how many others); in `/api/v1` inside `error`, in the web API next to `error`. Also `GET /api/agents/{id}/bridges` lists the pairs. Again with `"bridge_ok": true` from a person who manages every list involved (owner or list admin) or owns the personal agent: allowed and stored. Never from an agent. |
| `PATCH /tasks/{id}` with `list_id` · `POST /tasks/{id}/move` · `POST /tasks/batch` with `changes.list_id` | An **agent** moving tasks into a list whose people circle is not a subset of the source list's circle: `202` with a waiting job until a person approves (see [AGENTS.md](AGENTS.md#requests-that-wait-for-a-person-2150)). |
| `POST /api/me/tokens` · `PATCH /api/me/tokens/{id}` | `list_ids`: limit a personal token to these lists (`[]` = all). |
| `PATCH /api/admin/agents/{id}` · `PATCH /api/my/agents/{id}` | `list_ids`: limit an agent to these of its lists (`[]` = all). |
| `GET /me` (`/api/v1`) | `token.list_ids`: the restriction of the token in use. |
| `GET /api/lists/{id}/agent-access` | Every member of the list: `{days: 30, data: [{agent_id, name, day, read, write}]}`, one counter per agent, day and kind (read / write), kept 30 days. In the app: list menu *Agent access*. |

*Share all existing projects* skips projects that would create a bridge and names them (`bridge`, `bridge_reason`); *Share new
projects automatically*, shared folders, a folder's agent setting, groups and sharing by e-mail address skip them silently
(an address share never reveals whether an account exists). `PATCH /api/admin/agents/{id}` / `PATCH /api/my/agents/{id}`
with `list_ids` that would switch on an unapproved bridge: `409 agent_bridge`, `bridge_ok: true` confirms it. A limited
token gets `403` on `GET /export` and only the News of its projects. Bridges from before 2.30 stay, flagged in the agent's
settings ("connects projects with different people").

## Favourites (2.40.0)

Every person can star the projects they really work on. The stars are **personal**: other members of a project
never see them, and agents cannot set any (`403`). 2.46.1 (#1361): the person's own agents (personal agents, `owner`)
see the flag `favorite` on the projects they see anyway (`GET /api/v1/lists`, `GET /api/v1/lists/{id}`); a team agent
without an owner sees `false` everywhere.

| Call | What it does |
|---|---|
| `PUT /api/lists/{id}/favorite` | Web API (the signed-in person): `{on: true}` (default) stars list `{id}`, `{on: false}` removes the star; `404` for a list you cannot see. Answer `{ok, favorite, fav_lists, fav_items}` (2.57.0) |
| `DELETE /api/lists/{id}/favorite` | Removes the star |

The stars travel with the person's settings in `GET /api/state` (`settings.fav_lists`: comma list of project ids, in the
order they were starred). Two more settings belong to them (`PATCH /api/settings`): `fav_only` (`"1"` = the sidebar shows
the favourites and folds every other project under *More projects*) and `fav_views` (comma list of the views that show only tasks
of favourites: `today`, `tomorrow`, `week`, `doable`, `assigned`). With and without an organisation alike.

2.46.1 (#1361), two more settings and one call:

- `fav_quiet` (`"1"`, default `"0"`): while the person has at least one favourite, projects without a star send **pushes**
  only for @mentions, assignments and what must not be missed (reminders, approvals, shares, follow-ups); comments,
  replies, new / completed tasks, status changes, unblocked tasks and team chat messages of those projects stay in the News
  without a push. A project bell set to *All* or *Custom* wins. No new kind of push.
- `fav_suggest` (`"1"` = default, `"0"` = off): the app offers a busy project as a favourite once.
- `POST /api/favorites/suggestion` (web API, the signed-in person; agents `403`): answers `{list_id, name}` for ONE project
  without a star, not archived, not the Basket, that the person changed on at least 5 different days with at least 20
  changes during the last 14 days -- or `{list_id: null}`. Each project is offered only once (`fav_asked`, kept by the
  server); a star is never set by itself.

2.57.0 (#1798): **favourites of every kind** as icon tiles in the sidebar's fixed head, in one order the person arranges.
The setting `fav_items` (`PATCH /api/settings`, a json list, at most 200 keys) holds that order: `l:<list id>`,
`folder:<path>`, `v:<view>` (`inbox`, `assigned`, `today`, `tomorrow`, `week`, `doable`, `pinned`, `waiting`, `stale`,
`byme`, `all`, `done`, `trash`, `archived`), `m:<view or area>` (e.g. `cal`, `timeline`, `office`), `f:<filter id>`,
`tag:<name>`, `p:<user id>`, `g:<group id>`, `a:<agent id>`. An unknown key is `400`, doubles are dropped. Projects keep their
star in `fav_lists` (pushes, agents and *Only favourites* read only that); `PUT / DELETE /api/lists/{id}/favorite` puts the
project's `l:` key at the end of `fav_items` / takes it out and answers `fav_items` too. A key whose target the person cannot
see (any more) stays stored and is simply not shown. Agents do not see `fav_items`.

2.156.0 D (#2186): **saved views of the sidebar** (e.g. "On the road", "Planning"), per person and the same on every device.
The setting `side_views` (`PATCH /api/settings`, a json list of at most 20 views) holds them: `{id, name, icon, open, fclosed,
hide, start}` with `id` = 1-16 lowercase letters / digits, `name` up to 60 characters, `icon` = the name of an app icon
(default `panel`), `open` = the groups shown open (`focus`, `lists`, `views`, `areas`, `filters`, `tags`, `team`, `more`),
`fclosed` = closed folders, `hide` = the hidden entries (`g:<group>` or a `fav_items` key; they wait under "Others (N)" in the
sidebar) and `start` = an optional start page (a route such as `today` or `l/12`). `side_view` is the id of the active view
(`''` = "Everything"); switching on one device switches every device. An invalid value is `400` and nothing is stored;
doubles in the projects are dropped. No route of its own, nothing for agents.

## My tasks in an own order (2.40.0)

*My tasks* can be put in a personal order by dragging (the default view; *Grouped by project* shows the project groups as before).
The order belongs to the person: it never changes the order of the shared projects (`sort` of the tasks), nobody else sees it,
agents have none (`403`).

| Call | What it does |
|---|---|
| `PUT /api/lists/{id}/in-mine` | 2.41.0 (#1365), web API (the signed-in person): `{on: true \| false}` shows the list's tasks in the person's *My tasks* or not (only for that person; `404` for a list the person cannot see, agents `404`). Answer `{ok, on, mine_hidden}`; `GET /api/state` carries `mine_hidden` (list ids). The app puts the tasks of such a list into the folded group *Hidden* at the end of *My tasks*, the person's tasks of it due today or overdue into *From hidden lists* |
| `GET /api/state` (lists) | 2.46.6 (#1680), web API: in `lists[].members` an agent carries `agent: true`, a personal agent also `agent_owner` (its owner's name). Only its owner can address a personal agent, whatever *Members may see and use the agent* says; the app says so at that switch |
| `GET /api/me/wait-suggestions` | 2.41.0 (#1205), web API: the person's earlier *Waiting on* texts, newest first (at most 50): `{items: [{note, at}]}` -- only texts the person wrote (also on completed tasks), never another person's text of a shared list |
| `DELETE /api/me/wait-suggestions` | 2.41.0 (#1205), web API: `{note}` takes the text out of the person's suggestions (the tasks keep it; using it again brings it back). Answer `{ok, items}` |
| `PUT /api/tasks/mine-order` | Web API (the signed-in person): `{ids: [task ids, top first]}` replaces the person's order; ids of tasks the person cannot see are skipped (at most 5000). Answer `{ok, count}` |
| `GET /api/state/delta?since={v}` | 2.42.0 (#1376), web API (the signed-in person, the app's live updates): the tasks changed since the state with version `v`, in the serialization of `GET /api/state` (same visibility): `{v, full: false, tasks, gone: [ids to drop], progress: {list id: ...}, counts (2.149.0: only when a task the person sees changed; else keep the previous ones), mine_order, mine_hidden, evlinks, tcontacts, timer, time_totals, time_lists}`. `{v, full: true}` when it is not certain (a list, share, section or field changed, more than 200 changed tasks, `since` older than the server's start or newer than its `v`, a change touching a list the person is a participant in (2.149.0; before: any change for a participant), a token limited to lists): load `GET /api/state` instead. `gone` names only tasks that were or are in a list the person sees. Agents work with `/api/v1` and its events, not with this |
| `POST /api/chat-save` with `kind: "comment"` | 2.42.0 (#1383), web API (a person, never an agent): `{kind: "comment", msg_id: comment id, as?: "sub" (default) \| "list", title?, due?}` saves an agent's comment on a task as a subtask of that task (`sub`) or as a new task in the same list (`list`; no `list_id`): the comment's text, its files (copies) and a link back to the task. `400` for a comment of a person, `403` without the right to add tasks in the list, `404` for a comment the person cannot see; saving again answers `{already: true, task_id}`. The task timeline carries `saved_task_id` on such comments (for the person asking) |

`GET /api/state` carries it as `mine_order` (`{task id: position}`, 0 = on top). A task without a position (new, or newly
assigned) stands above the placed ones, newest first; assigning a task to a person takes its old position away. The setting
`mine_view` (`PATCH /api/settings`) is `own` (default) or `lists`.

2.156.0 C (#2072): "My tasks" as a board: `mine_board` is `0` (the project, default) or `1`; `mine_board_by` names its columns:
`due` (Overdue / Today / This week / Later / No date, default), `prio` or `list`. Dropping a card on a column is a plain task
change (date, priority or project). 2.156.0 C (#2071): a project's `view` may also be `calendar` (the calendar with only that project's
tasks; owner for everyone, a member for themself, like `kanban`). 2.156.0 C (#2073): `sections_closed` is a JSON list of the
section ids the person folded in list views (at most 2000; all devices).

2.156.0 C (#2073), web API (a person in the app, never an agent or an API token): section templates -- a name and the ordered
names of a project's sections, the person's own (`space: "private"`) or an organisation's (`"org:<id>"`: every member reads it,
its creator and the organisation's admins change it; another organisation / person gets 404).

| Route | Meaning |
|---|---|
| `GET /api/section-templates` | the templates the person sees: `{templates: [{id, name, sections: [names], space, org_id, mine, can_edit, updated_at}]}` |
| `POST /api/section-templates` | `{name, space?, list_id \| sections}`: `list_id` = that list's section names (who may write the list; a list with the lock: 409), `sections` = names (blanks and doubles dropped, at most 50) |
| `PATCH /api/section-templates/{id}` | `{name?, sections?}` (its creator or an admin of its organisation, else 403) |
| `DELETE /api/section-templates/{id}` | the same people; lists made with it keep their sections |
| `POST /api/lists/{id}/sections/from-template` | `{template_id}`: the template's names the list lacks (any case) are added at the end in the template's order; nothing is removed or renamed. Answer `{added: [section rows], skipped: [names already there]}` |

2.56.1 (#1799): the symbols of a task row and the sidebar's markers are settings too (`PATCH /api/settings`): `row_icons`
is `all`, `key` (default), `calm` or `custom`; `row_icons_custom` is a comma list of the symbols shown with `custom` (`due`,
`repeat`, `remind`, `deadline`, `occ`, `note`, `attach`, `link`, `sub`, `cmt`, `code`, `tracked`, `plan`, `ttype`, `ms`, `blocked`,
`wait`, `stale`, `pin`, `list`, `tags`, `fields`, `created`, `num`, `person`, `turns`; `none` = none, `""` = the `key` set); an
unknown value is a 400. `side_count`, `side_dots`, `side_share` (`"0"` = hidden, default `"1"`) switch the sidebar's task
counts, the status dots of projects and the share marks. Only the web app's display changes; the API returns every field.

## Office: drafts of agents (2.51.0)

Scope `office` (never in the legacy `write` or a new agent's default). Agents only, and only with their switch *May draft
office documents* and the area's privacy switch *Agents may read office data* on (else `403`). `requested_by` (query or
body) = the person the agent acts for (default: its owner; a team agent must name one). Drafts only: no route sets a
number, a status, finalises, sends, deletes or books. Details: [AGENTS.md](AGENTS.md#office-drafts-only-2510).

| Call | Scope | What it does |
|---|---|---|
| `GET /office` | office | The area (`{id, personal}`), `person_id`, `role`, currency, language, the rules |
| `GET /office/{services\|texts\|contracts\|clients}` | office | Master data of the area (`q` = search); never purchase prices or markups |
| `GET /office/docs` | office | `?kind=offer\|invoice\|credit\|reminder&client_id=&status=&open=1&trial=1\|0` -> `{data: [brief documents]}` (2.88: quotations with `version_of` = the first quotation of their chain of versions, `cashflow`; 2.144.10: every document carries `trial`, `trial=1` only trial documents, `0` only real ones) |
| `GET /office/docs/{id}` | office | One document with positions (`agent_flag` per position: `free`, `price`, `discount:<pct>`), sums, `agent_id`; 2.88: a quotation also `version_of`, `cashflow` and `cf_chain` (which version counts in the cash flow); 2.91: an invoice made by an invoice series carries `series_id` and `series_period` (the start of its period; null / empty otherwise); 2.154: an invoice / credit note carries `peppol` = its newest send over the Peppol network `{status: sending\|sent\|delivered\|rejected\|error, status_text, message, at}` or null (read only: agents never send) |
| `GET /office/docs/{id}/pdf` | office | The PDF preview of a draft (2.138.2: DRAFT / ENTWURF in bold at the number and on every page); `409` for others |
| `POST /office/offers` | office | `{client_id?, title, intro?, items: [{service_id?, text?, detail?, qty?, unit?, price?, discount?, kind?}], list_id?, notify?, trial?}` -> `201 {doc, chat_message_id?}` (2.144.10: `trial: true` = a trial quotation: TEST number, SAMPLE on the PDF, never in bookkeeping; only at creation) |
| `PATCH /office/offers/{id}` | office | The agent's own draft while it is a draft (`items` replaces the list; 2.88: `cashflow` auto / yes / no = its share in the cash flow plan once sent); `403` for a person's draft, `409` once sent |
| `POST /office/offers/{id}/invoice` | office | An accepted quotation -> `201 {doc}` an invoice draft (`parts_mode?`, `notify?`; 2.120.0: `inv_type?` `progress` with `amount?` (net) or `pct?` of the quotation's net, or `final` = the whole quotation less its finalised progress invoices; 2.168.0: the invoice keeps the quotation's project `list_id`) |
| `POST /office/reminders` | office | `{invoice_ids, level?: 1-3, notify?}` -> `201 {doc}` a reminder draft over open invoices of one client |
| `POST /office/payment-suggestions` | office | `{invoice_id, amount, date?, reference?, confidence?: high\|medium\|low, note?}` -> `201` an open suggestion; `409` for a trial invoice (trial documents never reach the books); 2.148: `409` when `date` lies in a locked month of the office (GoBD); 2.149.0: `409` above the invoice's open amount (like a person's payment; `exceeds_open` stays in the answer, always `false`) |
| `GET /office/payment-suggestions` | office | `?state=open` (default) `\| accepted \| rejected \| all`: the agent's own suggestions |
| `GET /office/leads` | office | 2.94.0: the leads of the area by follow-up day (`?due=1` = the day has come) -> `{data: [{id, title, contact, company, email, phone, source, next_step, follow_up, note, app_url}]}`; the person (`requested_by`) must be an admin of the office |
| `POST /office/leads` | office | 2.94.0: `{title?, contact?, company?, email?, phone?, source?, next_step?, follow_up?, note?}` -> `201` a lead (stage lead; `source` default `agent`) |
| `PATCH /office/leads/{id}` | office | 2.94.0: `{next_step?, follow_up?, note?}` only, only while it is a lead (`409` once converted). Agents never convert, delete or set another stage |
| `GET /office/letters` | office | 2.153.0: the letters the agent made, newest first (`?status=draft` default \| `sent` \| `delivered` \| `all`) -> `{data: [letter]}`; the person (`requested_by`) must be an admin of the office |
| `POST /office/letters` | office | 2.153.0: `{answers?, client_id?, rcpt_name?, rcpt_address?, rcpt_email?, letter_date?, subject, body, ref_line?, greeting?, lang?, notify?}` -> `201` a letter draft (`agent_id` set; subject or text required; `answers` = a document shared with the agent in the office's documents space, else `404`; `chat_message_id` with `notify`, default true) |
| `GET /office/letters/{id}` | office | 2.153.0: one letter the agent made (`404` for any other) with `links` (documents it sees) and `app_url` |
| `PATCH /office/letters/{id}` | office | 2.153.0: the agent's own draft, the fields of the create call except `answers`; `400` once a person sent it |
| `POST /office/letters/{id}/links` | office | 2.153.0: `{node_id, kind?: answers\|reply}` links the agent's own draft with a document shared with it (`404` otherwise, `400` once sent) |

2.153.0 (#2031): the event `letter_draft_requested` comes when an office admin asks the agent for a draft answer (`POST /api/office/letters/doc/{node_id}/ask-agent` `{agent_id, note?}`; `GET /api/office/letters/doc/{node_id}/agents` names the agents the document is shared with; nothing is shared on their behalf).

The people's side (web app, signed in): `GET` / `PATCH /api/office/agents/{id}` (`{office_drafts: bool}`, an admin of the
agent's office area), `GET /api/office/pay-props`, `POST /api/office/pay-props/{id}` `{action: accept|reject}` (admins;
accept books the payment like *Record payment*), the settings key `agents_read` of `PUT /api/office/settings`.

2.154.0 (#1960), e-invoices over the Peppol network (people only, details in [OFFICE.md](OFFICE.md#e-invoices-over-the-peppol-network-2154)):
`GET` / `PUT /api/office/peppol` (`{provider: storecove|custom|"", endpoint_url?, account?, sandbox?, sender_id?, api_key?}`, admins;
the key is never returned, `key_set` only), `POST /api/office/peppol/check`, `GET /api/office/docs/{id}/ubl` (the UBL file),
`GET /api/office/docs/{id}/peppol` (`?refresh=1`: what is missing, the client's id or a suggestion, the sends), `POST
/api/office/docs/{id}/peppol/lookup` (`{reachable}`), `POST /api/office/docs/{id}/peppol` (`{again?: 1}` -> `201`; `409` when
something is missing or it went already, `502` when the provider failed). The client's billing field `peppol_id`.

2.168.0 (#2665), a quotation / invoice / credit note bound to a project (people only, also finalised or sent documents: an
internal mark, the document stays as it is): `POST /api/office/docs/{id}/project` `{list_id: id|null}` (a project you see in
the office's workspace; `404` otherwise, `400` for another workspace) or `{create: {name}}` (`201`: a new project of the
office's workspace with the document's client, only you a member; a deal's quotation also gives it to the deal without a
project) -> the document with `list_id`, `modules_on`. Invoices from a quotation (also progress / final), credit notes and
new quotation versions keep the project; a copy of an invoice does not. `GET /api/lists/{id}/office-docs` -> `{office,
docs: [{id, kind, number, status, state, status_text, date, gross_text, project_title, trial}]}` (newest first, at most 100):
only with office rights in the project's own area, everybody else `{office: false, docs: []}`.

## Documents (2.48.0)

Documents are files of the file store (`/files`) with recognised text and fields. Scopes `files:read` / `files:write`;
a token sees only the documents whose file it may see (an agent: shared with it).

| Call | Scope | What it does |
|---|---|---|
| `GET /documents` | files:read | `?q=` words of the text (whole words; words of 4+ letters also as a prefix), `review=1`, `state=wait\|run\|done\|failed`, `from` / `to` (document date), `limit`, `cursor` -> `{data: [Document], next_cursor}`, newest document date first. 2.122.0: `q` takes a search syntax (`tag:Name` - several = every one, `sender:` / `absender:`, `type:` / `typ:`, `date:` / `datum:` `2025` \| `2025-03` \| `2025-01..2025-06` \| `>2025-01-01`, `added:` / `eingang:` = date of arrival, `"exact phrase"`, `-word`, `-tag:Name`; names without regard to case, the whole name first, else a part); filters by id: `tag` (`1,7;3` = two tags, each with its ids in several workspaces), `tag_mode=all\|any`, `not_tag`, `sender`, `type`, `folder`, `added_from` / `added_to`, `no_tag=1`, `no_sender=1`, `no_type=1`, `ftype=pdf,image,office,text,other` |
| `GET /documents/{id}` | files:read | One document: `date`, `due`, `amount` (decimal text), `currency`, `sender` / `type` / `folder` (`{id, name}` or null), `tags`, `auto` (feature -> `rule` \| `learn` \| `agent` \| `import` \| `code` \| `photo`), `taken_at` (2.61.0: the capture time of a photo from its EXIF, or null), `suggest` (feature -> a suggestion waiting for review), `review`, `state`, `error`, `method` (`pdf` \| `ocr` \| `text` \| `import`), `text` (the recognised text), `extracted` (2.121.0: what the recognition read off an invoice / receipt, or null: `supplier`, `vat_id`, `tax_no`, `invoice_no`, `vat_pct` `19` \| `7` \| `0`, `vat_rates` `[{pct, net, vat}]`, `net`, `vat`, `gross`, `currency`; `new` = the fields a person's take-over would change, `hidden` = dismissed. Read only: a person takes it over in the app) |
| `POST /documents` | files:write | 2.122.0 (#2098): a new document, recognised like an upload. JSON `{name, content_base64, mime?}` or multipart (`file`), plus optional `title`, `parent_id` (a folder you may edit), `ws` (`private` \| `org:<id>`, people without `parent_id` only), `sender`, `type`, `tags` (names), `date`, `due`, `amount`, `currency` (taken as given; an agent's `sender`/`type`/`tags` follow the levels like `PATCH`: on level *agent* they wait as suggestions in *To review*). An agent without `parent_id` writes into its own result folder. -> `201` the document |
| `PATCH /documents/{id}` | files:write | Role *edit*: `{date?, due?, amount?, currency?, sender?, type?, tags?: [names], text?, custom_fields?}` (`text` only while none was recognised; 2.153.0 `custom_fields` = `{field id or name: value \| null}`, only fields of the document's workspace, select by option id or name, money `"12.50 EUR"`, checkbox `true`; the single document lists them as `custom_fields: [{id, name, type, options?, value, label}]`). An agent's values are marked `agent`; a feature the workspace leaves to an agent becomes a suggestion in *To review*. Unknown fields: `400` |
| `POST /documents/{id}/receipt-suggestion` | files:read | 2.48.0 (#1356), agents only, the document shared with you: `{project_id?, category?, amount?, currency?, vat_pct?, note?}` (at least one of project, category, amount, vat_pct; 2.121.0 (#2096): `amount` = gross, more than 0, at most two decimals, `currency` = 3 letters, `vat_pct` = `"19"`, `"7"` or `"0"`; `project_id` = a project you can see in the document's workspace) -> `201` ReceiptSuggestion `{id, document_id, agent, state, project, category, amount, currency, vat_pct, note, created_at, decided_at}`. A person accepts or rejects it in the app; your open suggestion of the same document is replaced |
| `GET /receipt-suggestions` | files:read | `?state=open` (default) `\| accepted \| rejected \| all` -> `{data: [ReceiptSuggestion]}`: an agent's own suggestions |

The web app's own routes (`/api/docs`, a signed-in person, never an agent): `GET /api/docs` (list with filters, the counter
*To review*, the filter labels of visible documents), `POST /api/docs` (multipart `files`, `ws` = `private` \| `org:<id>`),
`GET` / `PATCH /api/docs/{id}`, `POST /api/docs/{id}/accept` (take suggestions), `POST /api/docs/{id}/review`
(`{done: true}` = checked; the models learn the current values), `POST /api/docs/{id}/redo`, `GET /api/docs/{id}/thumb`,
`GET /api/docs/{id}/file`, `POST` / `DELETE /api/docs/{id}/task` (a task for the due date), `GET` / `PUT /api/docs/settings`
(levels per feature, the inbox folder), `POST` / `PATCH` / `DELETE /api/docs/rules`, `PATCH` / `DELETE /api/docs/labels/{kind}/{id}` (the delete answers the documents it touched; `POST /api/docs/labels/{kind}` `{ws, name, ids}` is its undo),
`POST` / `DELETE /api/docs/mail` (the forwarding address). Deleting and restoring use the file store
(`DELETE /api/files/nodes/{id}`, `POST /api/files/nodes/{id}/restore`).
2.146.0 (#2451): an e-invoice (XRechnung UBL / CII as `.xml`, ZUGFeRD / Factur-X PDF) is recognised from its data: `method`
`e-invoice`, `auto` marks the fields taken from it with `e-invoice`, `GET /api/docs/{id}` carries `einvoice` `{format: ubl|cii, kind:
invoice|credit_note, source: xml|pdf, number}` and `extracted` the values of the invoice; `GET /api/docs/{id}/einvoice` answers the
readable view (HTML, CSP sandbox, no script; `404` for a document that is no e-invoice). Agents read the same values through
`extracted` of `GET /api/v1/documents/{id}`.
2.122.0 (#2294): `GET /api/docs` takes the filters of `GET /api/v1/documents` (several `tag` / `sender` / `type` / `folder` values,
each `1,7` = one name) and answers the folders of the visible documents in `facets.folders`; `POST /api/docs/bulk` `{ids, add_tags?,
remove_tags?, type?, sender?}` changes the chosen documents one may change (at most 500 per request; answers `{changed, denied,
before}`, `{restore: before}` is the undo); `POST /api/docs/zip` `{ids}` checks a ZIP of the visible ones (at most
`KALMIDO_DOCS_ZIP_MAX_FILES` files, default 2000, and `KALMIDO_DOCS_ZIP_MAX_MB`, default 1024; over it: `413` with the limits)
and answers `{files, size, url}`; `GET` that url sends it once, within five minutes, to the same account (a damaged file is left
out). 2.122.0 (#2099): files and folders of the file store carry the tags of their workspace's documents: `GET` / `PUT
/api/files/nodes/{id}/tags` (`{tags: [names | ids]}`, write access), `GET /api/files/tags?space=` (the tags used there, merged by
name), `GET /api/files/tagged?space=&tag=1,7&tag=3&mode=all|any&not=4` (the matching files and folders of the space with their
`path`); the lists and the details of the file store carry `tags`.

## Arrangements of views for agents (2.55.0)

New scope `layouts` (agents only; off for new agents and not part of the legacy `write`). The agent reads and proposes, the
person accepts or declines (see docs/AGENTS.md *Arrangements of views*).

```bash
curl -s -H "Authorization: Bearer $TOKEN" "https://kalmido.example/api/v1/layouts/blocks?view=dashboard&user_id=3"
curl -s -H "Authorization: Bearer $TOKEN" "https://kalmido.example/api/v1/layouts/dashboard?user_id=3"
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"view": "dashboard", "user_id": 3, "name": "Focus", "summary": "Today and the projects first",
       "layout": {"order": ["today", "projects", "news"], "hidden": ["search"], "widths": {"today": 4}}}' \
  https://kalmido.example/api/v1/layouts/proposals
```

| Route | Scope | |
|---|---|---|
| `GET /layouts/blocks?view=&user_id=` | layouts | the blocks of a view: `key`, `name`, `width`, `fixed`; the views |
| `GET /layouts/{view}?user_id=` | layouts | `source` own / standard / default, `layout` {order, hidden, widths, heights, mobile} |
| `POST /layouts/proposals` | layouts | `view`, `name`, `layout`, `summary`, `title`, `user_id`; 201 = a ready proposal job (kind `layout`) |

The answer comes as the event `job`. A proposal job can be replaced with `POST /agent/jobs/{id}/proposal` (scope `layouts`)
while it is open. People decide with `POST /api/proposals/{id}/apply` (`{"select": ["0"], "use": true}`) or `.../discard`.

## Import proposals of agents (2.68.0)

New scope `import` (agents only; off for new agents and not part of the legacy `write`). The agent sends old data in one
JSON shape, the person checks the preview and takes it over into the office (see docs/AGENTS.md *Importing old data into the
office*). Nothing of the office comes back to the agent.

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"area": "fixed_costs", "user_id": 3, "summary": "From the old spreadsheet Kosten 2025",
       "note": "Row 14 (phone) had no amount, left out",
       "items": [{"label": "Office rent", "amount": 950, "repeat": "monthly", "start": "2026-01-01", "category": "Rooms"},
                 {"label": "Liability insurance", "amount": "240,00", "repeat": "yearly", "start": "2026-03-01", "category": "Insurances", "vat_rate": 0},
                 {"label": "Software subscription", "amount": 29.9, "start": "2026-01-01", "vat_rate": 19}]}' \
  https://kalmido.example/api/v1/agent/proposals/import

## Tables (2.89.0)

New scopes `sheets:read` and `sheets:write` (off for new agents, not part of the legacy `write`; a personal token also needs
the module *Tables* switched on to write). Routes: `GET /api/v1/sheets` (`?space=private|org:<id>|all`, `?list_id=`),
`POST /api/v1/sheets` (a whole table in one call), `GET` / `PATCH /api/v1/sheets/{id}`, `PUT /api/v1/sheets/{id}/cells`,
`POST /api/v1/sheets/{id}/rows`, `POST /api/v1/sheets/{id}/columns`, `GET /api/v1/sheets/{id}/vars`,
`POST /api/v1/sheets/{id}/batches/{batch}/undo`. 2.124.0: a person shares one table with single people / agents
(`GET|POST /api/sheets/{id}/shares`, `PATCH|DELETE /api/sheets/{id}/shares/{share}`, session only, role `read` | `write`);
the list then holds it with `shared_in: true` and `share_role`, `?space=shared` lists only such tables. Formulas are stored with ids and shown with the current names; every
value is calculated with the token's visibility (`error: "denied"` for a source it does not see). An agent's write call is
one batch (`batch` in the answer) a person can take back. The app also exports a table as CSV / .xlsx and imports both
(`GET /api/sheets/{id}/export.csv|xlsx`, `POST /api/sheets/import`, session only).

2.124.0: column kinds `checkbox` (`1` / `0`), `person` (an account id of someone who may see the table), `link`
(`http(s)://` / `mailto:` only, 400 otherwise) and `file` (read only through the API: raw `file:<id>`, display = the file
name). A table answer has `freeze_rows` / `freeze_cols` (rows / columns kept in view). Session only (the app): the people a
person cell may name (`GET /api/sheets/{id}/people`), a file into a cell (`POST /api/sheets/{id}/files`, multipart
`file`, `row_id`, `col_id`) and its download (`GET /api/sheets/{id}/files/{file_id}`), the rows / columns kept in view
(`POST /api/sheets/{id}/fixed` `{rows, cols}`), the history of the table (`GET /api/sheets/{id}/history`) and of one cell
(`GET /api/sheets/{id}/cells/{cell_id}/history`).

2.124.0: several sheets in one table. Each sheet has its own id and is read / changed with the routes above; a table answer
has `book_id` (the id of the table's first sheet), `book_title`, `tab_name` and `tabs` (`[{id, name, pos, first}]`), the
list of tables shows each table once with `sheets` (its number of sheets). `GET /api/v1/sheets/{id}/tabs` lists the sheets,
`POST /api/v1/sheets/{id}/tabs` `{name?, columns?, rows?}` adds one (one batch). Session only (the app): rename / move
(`PATCH /api/sheets/{id}/tabs/{tab}` `{name?, pos?}`), the trash (`DELETE /api/sheets/{id}/tabs/{tab}`,
`POST /api/sheets/{id}/tabs/{tab}/restore`; the first sheet: 409), a new or copied sheet (`POST /api/sheets/{id}/tabs`
`{name?, after_id?, copy_of?}`). Shares and the list belong to the first sheet (409 on a further one). Formulas reach into
another sheet with `Name!A1` / `'Sheet name'!A1:B5`; the .xlsx export / import carries all sheets.

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"title": "Angebot Dreh", "space": "private",
       "columns": [{"title": "Posten"}, {"title": "Stunden", "kind": "number"}, {"title": "Satz", "kind": "currency"},
                   {"title": "Betrag", "kind": "currency"},
                   {"title": "Status", "kind": "select", "options": [{"label": "Offen", "color": "#f5b041"}, {"label": "Fix", "color": "#58d68d"}]}],
       "rows": [["Kamera", 10, 95, "=B1*C1", "Offen"], ["Schnitt", 16, 80, "=B2*C2", "Fix"], ["Summe", "", "", "=SUMME(D1:D2)", ""]]}' \
  https://kalmido.example/api/v1/sheets
```

## Video sign-offs (2.99.1)

Scopes `read` and `comments`. Routes: `GET /api/v1/videos?task_id=` (the sign-offs at a task) or `?list_id=` (at the list
and its tasks), `GET /api/v1/videos/{id}` (versions = links, `state` open | approved | changes, comments by version and
timecode with `timecode`, `customer`, `agent`, `done` and their `replies`), `POST /api/v1/videos/{id}/comments`
`{body, at_sec?, version_id?, parent_id?}` (201 `{comment, review}`) and `PATCH /api/v1/videos/{id}/comments/{comment_id}`
`{done}`. Only sign-offs at a task / list the token's account sees (an agent: shared with it); those only at a client are
for people in the app; the customer link never comes through the API. An answer to a customer's comment shows on the
customer page and needs the right to change the task / list.

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"body": "Logo zwei Sekunden früher einblenden", "at_sec": 83.5}' https://kalmido.example/api/v1/videos/12/comments
```

## Rules of a list (2.71.0)

Read only for tokens; agents propose (see docs/AGENTS.md *Rules of a list*). People manage rules in the app (list
settings > Rules: `GET` / `POST /api/lists/{id}/rules`, `PATCH` / `DELETE /api/rules/{id}`, `POST /api/rules/{id}/restore`).

```bash
curl -s -H "Authorization: Bearer $TOKEN" https://kalmido.example/api/v1/lists/12/rules
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name": "Review", "trigger": {"kind": "section", "section_id": 40}, "action": {"kind": "assign", "user_id": 3},
       "summary": "Everything in Review goes to the reviewer"}' \
  https://kalmido.example/api/v1/lists/12/rules/proposals
```

| Route | Scope | |
|---|---|---|
| `POST /agent/proposals/import` | import | `area` (`fixed_costs`), `items` [{`label`, `amount`, `repeat`, `start`, `until`, `category`, `vat_rate`}] (1-500), `title`, `summary`, `note`, `user_id`; 201 = a ready proposal job (kind `import`) with `rows` and `expires_at` |

Errors: 400 (the office module off for the person, another area, no rows, more than 500 rows), 403 (scope), 404 (not your
person / not in your organisation), 409 (usage limit), 413 (body over 256 KB), 429 (5 open import proposals, 20 per person and day). People see
the judged rows in `GET /api/proposals/{id}` (`import`: `version`, `office`, `problem`, `rows` with `status` new / dup / error,
`counts`) and decide with `POST /api/proposals/{id}/apply` (`{"select": ["0", "2"], "edits": {"2": {"vat_rate": 7}}, "version": "…"}`;
`version` optional: 409 when the agent replaced the rows since),
`.../discard`, `.../undo`, `.../redo`. A card stays bound to the organisation its agent had when it sent it.
## Tidy up contacts (2.70.0)

A person asks with `POST /api/proposals {agent_id, kind: "merge", book_id}` (web session; an address book they may change,
read-only 403, unknown 404; an organisation's book only for an agent of that organisation, an agent limited to selected
lists 403; more than 2,000 contacts 400). The event `job_request` carries `input.contacts` (id, fn, given, family, org,
emails, phones) of that book only. The agent answers with `POST /agent/jobs/{id}/proposal`
`{groups: [{target_id, ids, reason?}]}` (ids from the input, 2-10 per group with the target, each once, at most 200
groups, reason at most 300 characters; `{groups: []}` = none found). `GET /api/proposals/{id}` adds `dup_groups`
(`key, target_id, reason, ok, contacts: [{id, fn, org, emails, phones, state: "" | changed | gone}]`, loaded fresh);
`POST /api/proposals/{id}/apply {select: ["0", ...], edits: {"0": {target_id}}}` merges the ticked groups as the person
(`merged`, `skipped`), `.../undo` and `.../redo` take all of them back / again.

## Texts worded by an agent (2.126.1)

Who may be asked: `GET /api/proposals/agents?kind=office_text&doc_id=` (an office document of the person's office area,
an agent of that area with its office switch on, the area's *Agents may read office data* on), `?kind=doc_summary&doc_id=`
(a document the person may change, the same office agents, and only those that see the file themselves) and
`?kind=report&list_id=` (agents the list is shared with) -> `{agents: [{id, name, avatar, limit_reached, online}]}` (empty
when none may). A person asks with `POST /api/proposals {agent_id, kind: "office_text", doc_id, field: "intro" | "closing",
wish?}` (a draft that is not finalised or sent, else 409), `{agent_id, kind: "doc_summary", doc_id, wish?}` or `{agent_id,
kind: "report", list_id, from?, to?, days?, lang?, wish?}` (wish at most 500 characters; an agent the person may not ask:
404). The agent answers `POST /agent/jobs/{id}/proposal` with `{field, text}` / `{text}` (AGENTS.md *Texts worded by an
agent*). `GET /api/proposals/{id}` adds `target` (the field / summary / report as it is now, `editable`);
`POST /api/proposals/{id}/apply {select: ["0"], edits?: {"0": {text}}}` writes the (edited) text as the person (office
draft: 409 once finalised or sent; document: the right edit), `.../undo` / `.../redo` put the text before back (skipped
when someone changed it since). `GET /api/lists/{id}/status-report` (web) also carries `agents` and `agent_text`
(`{job, text, at}` of the report taken over for exactly this period, else null); the fixed `markdown` stays as it is.
`GET /api/docs/{id}` and `GET /api/v1/documents/{id}` carry `summary` (the text taken over, '' without one).

## Ideas for the mind map (2.156.0)

Who may be asked: `GET /api/proposals/agents?kind=ideas&list_id=` (agents the list is shared with and that the person may
address there) -> `{agents: [...]}` as above. A person who may change the list asks with `POST /api/proposals {agent_id,
kind: "ideas", list_id, branch: "r" | "s<section id>" | "t<task id>", hint?}` (a task on the deepest level: 400; hint at
most 2000 characters). The agent answers `{items: [{title, children?: [{title}]}]}` (AGENTS.md *Ideas for a branch*).
`GET /api/lists/{id}/ideas` (the person who asked) -> `{jobs: [{id, state: requested | ready, agent {id, name}, target,
path, items, taken {key: task id}, dropped [keys], created_at, updated_at}]}` of the open requests in that list.
`POST /api/proposals/{id}/ideas {take: ["0", "0.1", ...], drop: [...]}` creates the taken ideas as tasks of the person
under the branch (a sub-idea brings its idea along) and marks the dropped ones -> `{state, taken, dropped, open, tasks}`;
once nothing is open the job ends (applied / discarded). `POST /api/proposals/{id}/apply {select}` takes the selected ones
over and discards the rest; `.../discard`, `.../undo`, `.../redo` as for other proposals. `GET /api/state` carries
`max_depth` (2.156.0, #1949: the levels of tasks, 5).
| `GET /lists/{id}/rules` | read | people: owner / list admin (like the web), agents: write access to the list (else 403); `trigger` {kind section / done / reopen / ltag / due / created / assigned / field (2.138.0), section_id, tag_id, user_id (assigned: null = anybody), field_id + value (field: option id, "1" / "0" for a checkbox, null = any change)}, `action` {kind assign / due / comment / move / priority / tag / field (2.138.0), user_id, days, text, list_id, section_id, priority (none / low / medium / high), tag_id (a list tag), field_id + value (null clears)}, `names`, `active`, `paused_reason`, `created_by` |
| `POST /lists/{id}/rules/proposals` | structure | agents only: `name`, `trigger`, `action`, `summary`, `title`, `user_id`; 201 = a ready proposal job (kind `rule`) |
| `POST /agent/proposals/sheet-tasks` | sheets:read | 2.126.1: agents only: `sheet_id`, `rows` (row ids or `{row_id, title}`, at most 200), `list_id`, `title_col`, `due_col`, `notes_col`, `summary`, `for_user_id`; the table and the list shared with the agent, same space; 201 = a ready proposal job (kind `sheet_tasks`) + `skipped` (rows carried over before; all of them = 409). `GET /api/proposals/{id}` adds `sheet`, `list`, `sheet_rows` (`key, row_id, n, title, cell_title, due, notes, state: "" \| done \| gone \| empty`); apply `{select, edits: {"0": {title, due}}}` runs the table's rows -> tasks as the person (`created`, `skipped`), undo / redo = that batch; 2.190.0: a read-only token (only `read` / `sheets:read` and the like) gets `403` (`required_scope: comments`) |
| `GET /agent/schedules` | read | 2.126.1: each plan has `action` `chat` (event `scheduled_job`) \| `triage` (a planned *Sort the basket*: event `job_request` kind `triage` with `scheduled: true`, `schedule_id`); `last_state` also `empty` / `pending` / `busy` |

## Pin board, time check and shoot planning for agents (2.51.0)

New scope `pinboard` (write notepads on project pages; an agent changes only its own, at most 3 per project). Off for new agents and not part of the legacy `write`.

```bash
curl -s -H "Authorization: Bearer $TOKEN" https://kalmido.example/api/v1/lists/12/weekly-status
curl -s -X PUT -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"body": "## Status\n- 4 done, 1 overdue"}' https://kalmido.example/api/v1/lists/12/status-pad
curl -s -H "Authorization: Bearer $TOKEN" "https://kalmido.example/api/v1/time/check?user_id=3&from=2026-10-05&to=2026-10-11"
```

| Route | Scope | |
|---|---|---|
| `GET /lists/{id}/notepads`, `POST /lists/{id}/notepads`, `PATCH` / `DELETE /notepads/{id}` | read / pinboard | an agent: only its own notepads |
| `PUT /lists/{id}/status-pad` | pinboard | agents: one status block per list, overwritten |
| `GET /lists/{id}/weekly-status?days=7` | read | done, overdue, blocked, waiting, `waits` (who waits on whom) |
| `GET /time/check`, `GET /time/from-events` | time (+ calendar) | `user_id`, `from`, `to` (at most 62 days) |
| `POST /agent/proposals/time` | time | items `date`, `start`, `end` (local HH:MM), `task_id` or `list_id`, `note`, `event_id` |
| `GET /dispo`, `GET /dispo/free` | calendar | the agent's workspace; absences only as away |
| `POST /agent/proposals/shoot` | calendar | `list_id`, `days`, `crew`; applied = tentative events + option bookings |

Event drafts are events with `status: "tentative"`; CalDAV sends them as `STATUS:TENTATIVE`.

## The bell of one task (2.53.0)

Next to the bell of a list (`list_bell`) every person has a bell per task: **As the list** (default), **Muted** (no pushes
about the task; the News stay) or **Urgent** (every change and every comment of the task by someone else is a push at the
highest priority: ntfy 5 / Web Push urgency high, whatever the list bell, the matrix or the burst rule say). An urgency ends
on a chosen day (`until`, inclusive) or when the task is completed; afterwards the list counts again. It is a level of the
existing pushes, not a new kind. Web API only (the signed-in person; agents `403`), no `/api/v1` route and no MCP tool:
agents get no pushes and never mark people urgent.

- `GET /api/tasks/{id}/bell` (read access to the task): `{mine: {level, until, set_by, by_name, active}, accept, can_others}`;
  the list's owner and admins also get `people` (the owner and members of the list who see the task, without agents).
- `PUT /api/tasks/{id}/bell` `{level: "list" | "mute" | "urgent", until?: "YYYY-MM-DD"}` sets the own bell. With
  `users: [ids] | "all"` (owner / admins of the list only, `403` otherwise) it marks people of the list `urgent` or takes back an
  urgency someone else set (`level: "list"`; a person's own choice stays). People outside the list, agents and people who do
  not see the task: `404`. Marked people get a News item (`tbl_urgent`) and a push. The answer carries `act`, the token of
  this change.
- `POST /api/tasks/{id}/bell/undo` `{act}` puts back the rows of that change (only the person who made it).
- Setting `tbl_accept` (`"1"` default, `"0"` = urgency set by others counts as *As the list*; it stays visible on the task).
- The task history gets a line `bell` for urgency set for others (`{level, until, n}`, a count, no names) and when a person
  switches off an urgency someone else set (`{level, self: 1}`).

## Virus scan of uploads (2.61.0)

Every upload (`POST /api/v1/tasks/{id}/attachments`, `.../attachments/text`, project files, the file store, chat files) is
checked by the server's virus scanner when the operator runs one ([SELF-HOSTING.md](SELF-HOSTING.md#virus-scan-of-uploads)).

- A find: `400` with `error` = "<name>: malware found (<signature>), not uploaded"; nothing is stored.
- File lists carry `up` only for files with a mark: `{"scan": "unchecked"}` (the scanner was not reachable or the file is too
  large for it; `scan_why: "size"`), `{"scan": "infected", "sig": "<signature>"}` (found later: the file is locked).
- Reading a locked file (`GET /api/v1/attachments/{id}`, `.../text`, `GET /api/v1/files/{id}/content`, project / chat files)
  answers `403`; deleting it works as before. 2.79.0: with the scanner's strict mode (the default when a scanner is
  configured) the same `403` holds for an unchecked file until the later scan found it clean.
- A file whose content does not match its type (a program or HTML page named `.png`) is stored as
  `application/octet-stream`.
## A meeting becomes tasks (2.70.0)

The app's routes for the guided *Tasks from notes* (session of a person, never an agent token):

- `POST /api/agents/{id}/meeting-images` (multipart, `file` 1 to 4 times, images only) stores the photos as the person's
  files in their chat with that agent (only an agent they may chat with and ask for proposals; no `chat` event) ->
  `201 {images: [{id, name, mime, size}], message_id}`.
- `POST /api/proposals` with `kind: "extract"` takes `image_ids` (at most 4; only the person's own files of their chat
  with that agent, images only, else 400); `text` may then be empty. A health list answers 400. The job input carries
  `images: [{id, name, mime, size, url}]` (`url` = `/api/v1/chat-attachments/{id}`, readable by the agent of that chat).
- `GET /api/agents/{id}/meeting-proposals` -> `{proposals: [{id, title, list: {id, name}, images, summary, tasks:
  [{title, due, assignee_id, assignee}]}]}`: the person's own ready `extract` proposals of that agent (at most 5, newest
  first), the cards in the chat. Apply / discard as every proposal (`POST /api/proposals/{id}/apply` `{select}`, `.../discard`).
## Contracts: notice deadlines for agents (2.70.0)

| Endpoint | Scope | Notes |
|---|---|---|
| `POST /agent/proposals` `{kind: "notice", task_id, text}` | write | agent tokens only; after the event `contract_notice` for that contract's current deadline (else `409`), a contract the agent cannot see `404`; `text` one sentence, at most 300 characters; 201 = a ready proposal job (kind `notice`) for the person whose contract it is |

Accepting is a click of the person (`POST /api/proposals/{id}/apply`, optionally `remind: true` = also a reminder 3 days
before the last day to cancel): a comment on the contract task as that person, one undo step (`POST /api/proposals/{id}/undo`).
OpenAPI: the third body variant of `POST /agent/proposals` (`x-kalmido-scope` write). Nothing is cancelled or sent.

## Built-in assistant (2.75.0)

Kalmido calls no language model itself, with one exception: the built-in assistant, which exists only when the server
operator configured an OpenAI-compatible endpoint (`KALMIDO_AI_BASE_URL` + `KALMIDO_AI_MODEL`, see SELF-HOSTING.md). Without
that configuration every route below answers `404` and `/api/state` has no field `assistant`. Web API only (the signed-in
person, session or sign-on proxy): no `/api/v1` route, no MCP tool, agents and API tokens never reach it (agents are models
themselves and have their own proposals API); child accounts get `403`.

- `/api/state` field `assistant`: `{enabled, provider, host, model, on, list_ids}` -- `on` is the person's setting
  `assistant_on` (`"0"` default, `PATCH /api/settings`), `list_ids` the lists they shared with it. The key is never shown.
- `GET /api/assistant` -> `{enabled, provider, host, model, on, lists: [{id, name}], limits: {max_chars, max_items, open_max}}`.
- `PUT /api/assistant/lists` `{list_ids: [..]}` replaces the shared lists. Kept are only lists the person sees right now;
  the basket, health lists, archived lists and unknown ids are left out without an error. Shares the person may no longer
  use (left the list, list archived) are removed on the next `GET`.
- `POST /api/assistant/run` `{kind, task_id?, task_ids?, text?, instruction?, list_id?, day?}` -- one synchronous call
  (time limit `KALMIDO_AI_TIMEOUT_S`):
  - `summary` (`task_id` and / or `text`), `draft` (`task_id` and / or `text`, `instruction`) -> `{kind, text, truncated, log_id}`
  - `extract` (`text` or `task_id`, `list_id` = target, shared) -> a ready proposal of kind `extract`
  - `tags` (`task_id`) -> a ready proposal of kind `triage` with one item (tags, due date, priority; never a move)
  - `triage` (`task_ids`, at most 30; the person's own basket items or tasks of shared lists; targets = shared lists)
  - `dayplan` (`day`, default today; only tasks of shared lists, events as busy times without titles)

  Proposals answer `{kind, job_id, job, proposal, truncated}`: a proposal job of the person themself (`input.assistant` =
  `true`, `input.provider`), shown, applied, discarded and undone with the existing `/api/proposals/{id}` routes; no agent
  gets an event about it. A task must be visible to the person (`404` otherwise) and lie in a shared list or their own
  basket (`403` "Share this list with the assistant first"). Never sent: locked notes, health lists, attachments, files,
  office documents, other people's e-mail addresses. Errors: `403` while the person has it off, `400` input, `429` too many
  open proposals, `502` provider unreachable or no usable answer, `504` time limit; the texts never carry the provider's
  answer, its address or the key.
- `GET /api/assistant/log?limit=50` (up to 500) -> `{items: [{id, kind, task_id, list_id, job_id, status, ms, chars_in,
  chars_out, at}]}`: the person's own calls, numbers only (`status` ok | error | timeout | denied | truncated), never a prompt
  or an answer; kept `KALMIDO_AUDIT_DAYS` days.
- `GET /api/admin/assistant` (admins) -> `{provider, host, model, timeout_s, max_chars, today: {calls, errors}, days: [{day,
  calls, errors, chars_in, chars_out}]}` for 30 days, without people.

## Inbound webhook of a list (2.138.1)

Tools like n8n, Make, Zapier or Home Assistant create tasks through a secret URL, without a login. The owner or an
admin of a list adds one under **List settings > Inbound webhook** (up to 10 per list; not in the basket, health,
budget or locked lists). The URL `https://kalmido.example.com/api/hooks/in/<token>` is shown **once** (Kalmido stores
only its SHA-256); *New URL* stops the old one at once, *Delete* too (undo brings the same URL back for 30 days).

Each `POST` creates **one task in exactly this list**, through the normal way of creating a task (history line "via
webhook", pushes, agent events, outgoing webhooks, list rules), with the rights of the person who set the webhook up.
If that person can no longer write in the list (left it, became a viewer, was deactivated), the webhook answers `403`
and pauses itself; the owner or a list admin resumes it with their own rights (`PATCH /api/hooks-in/{id}`
`{"resume": true}`).

| Body | |
|---|---|
| `application/json` | `{"title": "..." (required), "notes", "due": "YYYY-MM-DD" or an ISO date-time (with an offset: converted to the server's time zone), "priority": "none" \| "low" \| "medium" \| "high", "tags": [list tags], "fields": {"field name or id": value}}` |
| form fields | the same names, `tags` comma separated |
| `text/plain` (or anything else) | the first line is the title, the rest the notes |

Answers: `201 {"id", "url", "ignored"?}`; `400` with a short message (no title, an invalid date / priority / field
value); `404` for an unknown, rotated or deleted token; `403` paused; `409` archived list; `413` above 64 KB; `429`
above 60 requests per minute or 1000 per day and webhook. Keys Kalmido does not know, tags the list does not have and
fields of other lists are **ignored** (never created) and named in `ignored`, so a flow keeps running when the list
changes.

```bash
curl -X POST -H 'Content-Type: application/json' \
  -d '{"title": "Washing machine done", "due": "2026-11-02", "priority": "high", "tags": ["Home"]}' \
  'https://kalmido.example.com/api/hooks/in/khi_...'
```

Home Assistant (`configuration.yaml`):

```yaml
rest_command:
  kalmido_task:
    url: "https://kalmido.example.com/api/hooks/in/khi_..."
    method: POST
    content_type: "application/json"
    payload: '{"title": "{{ title }}"}'
```

n8n: an *HTTP Request* node, method POST, the URL, body JSON with `title` (and the other keys). Behind a login proxy
(forward auth, single sign-on) the path `/api/hooks/` must bypass the proxy login, like the other inbound hooks.
