# Architecture

How Kalmido is built, where things live and how to add to it. For setting it up see the [README](../README.md); for the
development workflow see [CONTRIBUTING.md](../CONTRIBUTING.md).

## The big picture

```
 browser (PWA)                          server (one container)                      outside (optional)
 ---------------------------            -------------------------------------       ------------------------
 static/index.html                      app.py  (entry point)                       ntfy / Web Push services
 static/js/*.js   (web client)  --->    kalmido/  (Flask app, ~80 modules)  --->    Paperless-ngx, Git hosts,
 static/sw.js     (offline)     <---    SQLite database (one file)                  calendars, IMAP / SMTP,
 static/i18n/*.json                     background threads (watchdog ...)           webhooks, OIDC provider
                                              ^
 agents / scripts / MCP clients  ---------->  |  /api/v1 (tokens, scopes; mcp/kalmido_mcp.py is a thin bridge)
 calendar + contacts apps          ------->  |  /dav/ (CalDAV, CardDAV), /ical/
```

- **Server**: Python with Flask behind waitress, SQLite as the only storage (plus files below the attachments folder).
  No ORM: SQL with parameters in every module. `python app.py` starts it (the same command as always).
- **Web client**: plain JavaScript without a framework and without a build step, split into files that the browser
  loads in a fixed order. The service worker caches them, so the app opens offline.
- **API + agents**: `/api/v1` is the REST API for personal tokens and agents (scopes per operation, an OpenAPI 3.1
  document at `/api/v1/openapi.json`). The MCP server in `mcp/` translates MCP tool calls into that API.

## Data flow

1. **Start**: the browser loads `index.html`, the scripts and the language file, then `GET /api/state`
   (`kalmido/core/state.py`): every list, open task, section, habit, filter and setting the user may see, in one answer.
   The client keeps it in the object `S` (`static/js/core.js`) and renders every view from it (`render()` in
   `static/js/render.js`).
2. **A change**: the client applies it locally first, then sends it (`api()` in `static/js/core.js`; every change carries
   the header `X-Requested-With: kalmido` against CSRF). Offline, it waits in an outbox in `localStorage` and is sent
   later; a field changed elsewhere meanwhile comes back as a conflict the user resolves.
3. **On the server** a route checks the login (`accounts/session.py`: `authenticate`, `me()`), the access
   (`core/access.py`: `need_task`, `need_list`, `need_project` ...), validates (`tasks/validation.py`, `BadInput`),
   writes, logs the activity (`log_act`), queues News, pushes and webhooks (`news_add`, `notify`, `wh_note`), and calls
   `bump(c)`: the data version of the instance goes up.
4. **Other devices** poll `GET /api/version` every few seconds (`core/pages.py`) and reload the state when it changed.
5. **In the background** (`kalmido/startup.py` starts the threads): the watchdog (`notify/push.py`: reminders, nags,
   digests, rotations, clean-ups), the update check, calendar subscriptions, backups, webhook deliveries, mail and Git
   polling. Every thread and request passes the maintenance gate (`GATE` in `accounts/session.py`), so a restore can
   run alone.

Translations: English is the source language in the code. `tr("English text")` in both the client
(`static/i18n.js`) and the server (`kalmido/core/i18n.py`) looks the text up in `static/i18n/<code>.json`
(see [TRANSLATING.md](../TRANSLATING.md)).

## Server: the package `kalmido/`

`app.py` only imports the package and keeps the command line (`set-password`, `import`). Every name of every module is
also reachable as `app.<name>` (for example `python -c "import app; app.connect()"`), and `app:app` is the WSGI app.

The modules are grouped by area into folders. **Load order**: `kalmido/__init__.py` imports them in the fixed list
`ORDER`. Routes, request hooks and error handlers register in that order, and module-level code (constants, tables)
runs in that order.

**Imports between modules** follow one rule, which keeps the import graph free of cycles:

- a name of an **earlier** module (in `ORDER`) is imported at the top: `from ..core.db import db, bump, err`;
- a name of a **later** module is imported inside the function that needs it, at call time:
  ```python
  def task_complete(tid):
      from ..collab.comments import task_event  # later module: imported when the function runs
      ...
  ```
- module-level code (decorators, constants) may only use earlier modules.

The routes use the one Flask app object (`from ..core.config import app`, then `@app.get(...)`), not blueprints:
the endpoint names, the order of the request hooks and every URL stayed exactly as they were when the server was a
single file.

The most used helpers:

| Helper | Module | |
|---|---|---|
| `app` | `core/config.py` | the Flask app; the configuration from environment variables lives next to it |
| `db()`, `connect()` | `core/db.py` | the request's database connection / a new one (threads) |
| `bump(c)`, `err(msg, code)`, `body()` | `core/db.py` | data version +1, an error answer, the JSON body |
| `gsetting`, `usettings`, `uset` | `core/db.py` | instance / user settings |
| `tr`, `trn`, `N_` | `core/i18n.py` | translations |
| `me()` | `accounts/session.py` | the id of the logged-in user |
| `need_task`, `need_list`, `need_project`, `Denied` | `core/access.py` | access checks (403 / 404) |
| `task_dict`, `load_tasks` | `core/serializers.py` | the JSON shape of tasks |
| `log_act`, `clean_task`, `BadInput` | `tasks/validation.py`, `personal/timetrack.py` | activity log, input validation |
| `news_add` | `collab/news.py` | an item in someone's News |
| `notify` | `notify/push.py` | a push (Web Push / ntfy) to a user |
| `v1_view`, `v1_args`, `v1_json` | `api/v1.py` | REST API routes |

| Module | What it holds |
|---|---|
| `core/config.py` | Configuration from the environment, the outbound-HTTP guard, proxy and login settings, the Flask app object. |
| `core/schema.py` | Database schema, migrations, indexes and the default settings (user + instance). |
| `core/i18n.py` | Server-side translations (tr / trn / N_) and locale helpers (static/i18n/<code>.json, see TRANSLATING.md). |
| `core/db.py` | Time helpers, the database connection, start-up checks and migrations (init_db, repair_data), settings storage. |
| `accounts/session.py` | Who is asking: sessions, the proxy login, trusted proxies, the maintenance gate, login rate limits. |
| `accounts/pictures.py` | Profile pictures and list icons (presets or own images, re-encoded, served with login). |
| `accounts/login.py` | Password login, first setup, logout and two-factor authentication (TOTP, recovery codes, passkeys). |
| `accounts/oidc.py` | Login with a generic OpenID Connect provider (authorization code flow with PKCE). |
| `core/access.py` | Access control: who sees / changes which list and task, module switches, list roles. |
| `core/serializers.py` | JSON shapes of database rows (tasks, lists, users ...) as the web client and the API see them. |
| `core/pages.py` | HTML pages, security headers, /api/version, the share target, quick capture, /drop and the ntfy share inbox. |
| `core/instance.py` | Version, update check and instance settings (admins). |
| `core/state.py` | GET /api/state: everything the web client loads at start and after a change. |
| `lists/lists.py` | Lists: create, change, share (people + agents), members, sidebar order. |
| `lists/groups.py` | Groups of people (admin): materialized list memberships, tasks assigned to a group. |
| `lists/ownership.py` | Transferring the ownership of a list; orphaned lists (owner disabled or an agent). |
| `lists/sections.py` | Saved filters, folders and sections (kanban columns). |
| `tasks/validation.py` | Task activity log, input validation, repeat rules (RRULE) and task tree helpers. |
| `tasks/tasks.py` | Creating and changing tasks: milestones, moving subtrees, tags, assignees, waiting on external. |
| `tasks/roadmap.py` | The roadmap and shifting a list's dates (dependent tasks move along). |
| `tasks/lifecycle.py` | Applying changes, completing (repeats), undo, skip, reopen, delete, trash and restore. |
| `tasks/attachments.py` | Files of tasks (upload, download, delete). |
| `integrations/paperless.py` | Paperless-ngx: linking documents, sending attachments, personal and server connections, polling. |
| `tasks/batch.py` | Reordering and batch changes of tasks, occurrences of repeating tasks, deleting attachments. |
| `collab/comments.py` | Comments, mentions, the activity timeline and collaboration pushes. |
| `collab/news.py` | The News feed and the notification settings (matrix + list bells). |
| `personal/habits.py` | Habits and focus sessions (pomodoro), private per user. |
| `personal/timetrack.py` | Time tracking (module "time") and the unknown-JSON-field check of the REST API. |
| `accounts/settings.py` | Per-user settings, the data export and Web Push subscriptions. |
| `accounts/onboarding.py` | Onboarding and the sample project. |
| `accounts/users.py` | Users and the own account (admin user management, passwords, deletion). |
| `lists/templates.py` | Task and list templates, built-in project types. |
| `tasks/dependencies.py` | Dependencies between tasks ("waiting on"). |
| `lists/projects.py` | Project lists: status, progress, the overview (description, links, files, Paperless), milestone reports. |
| `lists/fields.py` | Custom fields of a list. |
| `personal/stats.py` | Statistics (module "stats"). |
| `calendars/icalfeed.py` | The subscribable ICS calendar feed of a user's tasks. |
| `calendars/caldav.py` | CalDAV server for tasks (VTODO) with app passwords; the /dav/ entry point for event calendars and CardDAV too. |
| `integrations/importers.py` | Importers: TickTick, Todoist, Trello, Asana, Microsoft To Do, ICS / VTODO (preview, dry run, undo). |
| `notify/push.py` | Notifications: ntfy, Web Push (RFC 8030 / 8291 / 8292), reminders and nags, the watchdog tick and loop. |
| `notify/alerts.py` | Admin alerts via ntfy (recording, sending, settings). |
| `calendars/subscriptions.py` | External calendars (read-only subscriptions): SSRF guard, ICS / CalDAV sync, API. |
| `admin/backup.py` | Backups and restore (admins). |
| `api/v1.py` | REST API /api/v1 with personal access tokens: token management, authentication, the routes, errors, groups. |
| `tasks/dayplan.py` | Day planning ("Plan my day") and the evening review. |
| `api/openapi.py` | The OpenAPI 3.1 document of /api/v1 (served at /api/v1/openapi.json, built once). |
| `integrations/webhooks.py` | Webhooks per user: collecting events during a request, delivery, settings. |
| `agents/core.py` | Agents: accounts, event queue + long polling, runtime settings, permissions of people towards agents. |
| `collab/reactions.py` | Reactions on comments, tidy suggestions and shared list tags. |
| `agents/chat.py` | What people see of agents: state, chat (files, reactions), jobs, wake. |
| `agents/admin.py` | Agent administration and personal agents. |
| `agents/api.py` | The REST API of an agent itself (token of an agent account). |
| `agents/proposals.py` | Agent proposals, validation helpers, requests from people to agents. |
| `agents/usage.py` | Model usage of agents, limits and the agents' audit log. |
| `lists/public.py` | Public links of lists and checklist mode. |
| `integrations/git.py` | Git integration of project lists (GitHub, GitLab, Gitea / Forgejo, Bitbucket) and tickets for agents. |
| `integrations/errorreports.py` | Error reports (Sentry, GlitchTip ...) -> tickets. |
| `api/projects.py` | The project overview in the token API. |
| `api/scopes.py` | Token scopes, approvals and the complete agent API (the routes the web client has). |
| `collab/notes.py` | Notes of a list / project. |
| `collab/teamchat.py` | Team chat (rooms and direct messages). |
| `integrations/mail.py` | Tasks by e-mail (IMAP) and the daily summary by e-mail (SMTP). |
| `accounts/orgs.py` | Organisations (#752): people in 1..n organisations and whom a person may see (all / own organisation / own contacts). |
| `accounts/invite.py` | Invitations and reset links (#697): a one-time link by e-mail with which a person sets their own password. |
| `family/family.py` | The module "Family": family fields of tasks, kid stars, occasions, shopping, packing lists, setup purpose, overview. |
| `family/web.py` | Family: the web API. |
| `family/carddav.py` | Family: birthdays and anniversaries from CardDAV contacts. |
| `family/v1.py` | Family: the weekly rotation and the REST API v1 (+ MCP). |
| `events/model.py` | Events (module "events"): calendars, rights, validation, repeat expansion, attendees, reminders, the family migration. |
| `events/ics.py` | Events as iCalendar (VEVENT): rendering for CalDAV + export, reading what clients send, importing an ICS file. |
| `events/web.py` | Events: the web API (calendars, sharing, events, single occurrences, replies, preparation tasks, export). |
| `events/dav.py` | Events over CalDAV: every event calendar (and the invitations) as a VEVENT collection next to the task lists. |
| `events/v1.py` | Events: the REST API v1 (+ MCP) and its OpenAPI part (scope "calendar"). |
| `contacts/model.py` | Contacts (module "contacts"): address books, rights, vCard 3 / 4 reading + writing, search, links to tasks, birthdays. |
| `contacts/carddav.py` | CardDAV server: every address book a person sees as a collection of vCards. |
| `contacts/web.py` | Contacts: the web API (address books, sharing, contacts, search, vCard import / export, links to tasks). |
| `contacts/v1.py` | Contacts: the REST API v1 (+ MCP) and its OpenAPI part (scope "contacts"). |
| `life/model.py` | Home & life (modules contracts, home, care, health, review, travel, reading): contracts, devices + upkeep, staying in touch, the private health list, review + journal, trips. |
| `life/karakeep.py` | Home & life: "Read later" from Karakeep (a person's own connection, sealed API key, bookmarks -> tasks, archive back). |
| `life/web.py` | Home & life: the web API (overview, contracts, devices, upkeep, health, trips, review + journal, staying in touch, Karakeep). |
| `life/v1.py` | Home & life: the REST API v1 (+ MCP) and its OpenAPI part (health + journal: scope "private"). |
| `team/clients.py` | Clients (module "clients"): clients of an organisation above the lists, hours, budget, estimate vs. actual. |
| `team/workload.py` | Workload (module "workload"): planned hours per person and week against their capacity. |
| `team/approvals.py` | Approvals as a step of a task: request, approve / changes / reject, withdraw. |
| `team/forms.py` | Forms (module "forms"): a link whose page (/f/<token>) creates a task in a list. |
| `team/v1.py` | Clients, workload, approvals, forms: the REST API v1 (+ MCP) and its OpenAPI part. |
| `accounts/signup.py` | Self-registration on the login page and sign-in links (QR) for people without e-mail. |
| `admin/hosting.py` | Running Kalmido for others (2.24.0): storage quota per person, the notice / maintenance banner, daily e-mail limits, the "agent joined" notice, `KALMIDO_HOSTED`. |
| `startup.py` | Start-up: init_db() and the background threads (watchdog, update check, calendars, backups, webhooks, mail, git). |

### Adding a route

1. Find the module of the area (the tables above; `grep -rn '"/api/tasks/<int:tid>/complete"' kalmido` finds any route).
2. Write the route like its neighbours: `@app.post("/api/...")`, `c = db()`, the access check, validation, the change,
   `bump(c)`, `c.commit()`, `jsonify(...)`. User-visible texts with `tr()` (add the keys to the language files,
   `python3 tools/i18n_check.py` lists them).
3. If agents / scripts need it too: the `/api/v1` twin with `@v1_view` (next to the web route or in `api/scopes.py`),
   its scope in the scope table (`v1_scope_need`, `api/scopes.py`), the operation in the OpenAPI document
   (`api/openapi.py` or the `*_spec` helper of the area) and the MCP tool in `mcp/kalmido_mcp.py`. `tests/parity_test.py`
   checks that web routes, API routes and MCP tools stay in step.
4. A test in `tests/` (API suites are Python, UI suites jsdom / Firefox).

### Adding a module

1. Create the file in the folder of its area with a one-line docstring (what it holds).
2. Add it to `ORDER` in `kalmido/__init__.py` **after** every module it imports at the top; names of later modules are
   imported inside functions (see above). The folder `__init__.py` files stay empty.
3. Database changes are additive migrations (`MIGRATIONS` in `core/schema.py`, run by `init_db` in `core/db.py`).
4. `python3 tools/check_layout.py` checks that `ORDER` and the files agree (CI runs it).

## Web client: `static/js/`

The client is split into **classic scripts** that share one global scope: a function or constant of one file is
visible in all others, exactly as when it was one file. `static/index.html` loads them in a fixed order with plain
`<script src>` tags; `main.js` comes last and starts the app. There is no build step, no bundler and no framework;
the Content-Security-Policy stays `script-src 'self'`.

Why not ES modules (`import` / `export`): the app and its test suites rely on the shared global scope (the jsdom
suites evaluate expressions like `openDetail(12)` in the page), jsdom does not run module scripts, and every file
would need explicit import lists for hundreds of shared helpers. Classic scripts give the same split without that.

Rules that follow from it:

- **Nothing runs before its file is loaded.** Code that runs while a file loads (top level, not inside a function)
  may only call functions of the same or an earlier file. Event handlers and everything after start-up may use
  any file. Start-up code belongs in `main.js`.
- Top-level names are unique across all files (they share one scope).
- Every file starts with a one-line comment (what it holds) and `'use strict';`.

The most used helpers: `S` (the client state) and `api()` in `core.js`, `$`, `$$`, `esc` (escape everything that goes
into HTML) and `ic()` (icons) in `icons.js`, `render()` / `renderView()` in `render.js`, `tr()` in `static/i18n.js`.
Clicks, keys and inputs are handled by delegated listeners on `document` (`data-act="..."` attributes), each file
registering the ones of its area.

| File | What it holds |
|---|---|
| `icons.js` | Icons (the "Punkt" set) and the app name; the first file (`'use strict'`, shared helpers like `$`, `esc`). |
| `core.js` | Dates, the client state, the API + offline outbox, edit conflicts, routing. |
| `quickadd.js` | The quick-add parser (six languages) and small task helpers: ticket types, milestones, links, repeat rules, reminders, deadlines. |
| `views.js` | Which tasks a view shows (smart lists, filters, sorting, grouping). |
| `render.js` | Rendering: the shell (sidebar, header, tabs) and task rows. |
| `calendar.js` | Kanban, the calendar views and external calendar events. |
| `timeline.js` | The timeline (Gantt). |
| `roadmap.js` | The roadmap. |
| `habits.js` | The Eisenhower matrix, habits and the pomodoro timer. |
| `detail.js` | The detail panel of a task. |
| `collab.js` | News and comments + activity (module "collab"). |
| `attachments.js` | Attachments, Paperless documents and the share target. |
| `undo.js` | Undo / redo history. |
| `popovers.js` | Popovers (date, priority, list, tags, reminders, repeat ...). |
| `dialogs.js` | Modals: the app's own dialogs, the list dialog and the share dialog. |
| `settings.js` | Settings: notifications, Web Push, autosave settings, personal agents, import, Paperless. |
| `integrations.js` | API tokens + scopes, webhooks, public links, calendar apps (CalDAV). |
| `account.js` | Account, users (admin), login, groups, passkeys, two-factor, sign-in policy, backups, the sample project. |
| `templates.js` | Templates and statistics. |
| `time.js` | Time tracking (module "time"). |
| `projects.js` | Projects: status, progress, overview, dependencies, custom fields. |
| `events.js` | Toasts, quick add wiring and the global event handlers. |
| `sidebar.js` | Multi-select bar, filter lists and the list order in the sidebar. |
| `dnd.js` | Drag & drop (desktop) and swipe (touch). |
| `palette.js` | Keyboard shortcuts, the command palette, the welcome tour. |
| `agents.js` | Agents, reactions, shared list tags, tidy suggestions. |
| `dayplan.js` | Day planning and the evening review. |
| `agentchat.js` | The chat with an agent (side panel / view) and Settings > Agents: lists, setup guides, behaviour rules, activity log, usage, runtime. |
| `listedit.js` | List editing, keyboard reordering, recent lists. |
| `git.js` | Git integration of project lists: repositories, pull requests + CI, agents' merge requests. |
| `chat.js` | Team chat and notes of a list / project. |
| `dashboard.js` | News bundled per task, the dashboard and Settings > Tasks by e-mail. |
| `family.js` | The module "Family". |
| `calevents.js` | Events (module "events"): the editor and popover, the agenda, creating in the week grid, calendars, the phone setup. |
| `contacts.js` | Contacts (module "contacts"): the view, the editor, the card, links between contacts and tasks, import / export. |
| `clients.js` | Clients, the workload view, approvals in the task panel, forms of a list, sign-in links with a QR code. |
| `life.js` | Home & life: the view, its dialogs (contract, device, upkeep, health, trip, Karakeep), the review + journal, staying in touch on a contact's card. |
| `main.js` | Start-up: loading the state, polling, the service worker. Loaded last. |

### Adding a client file

1. Create `static/js/<name>.js` with the header comment and `'use strict';`.
2. Add its `<script>` tag to `static/index.html` (before `main.js`, after the files whose functions it calls while it
   loads), add it to `SHELL` in `static/sw.js` in the same order and bump `CACHE` there.
3. `python3 tools/check_layout.py` compares the three lists; `node --check` runs on every file in CI.

## Tests and checks

- `tests/run_all.sh`: the API, UI (jsdom and Firefox), security and calendar suites against a fresh test container
  (see [tests/README.md](../tests/README.md)).
- CI (`.github/workflows/ci.yml`): Python and JavaScript syntax of every file, `tools/check_layout.py`, translations,
  the MCP bridge, bandit (high severity), pip-audit, the browser demo, semgrep and the test shards.

## Organisations and who sees whom (2.22.0)

People belong to one or more **organisations** (`accounts/orgs.py`; tables `orgs`, `org_members`). The instance setting
`people_visibility` decides whom a person sees at all; `visible_people(c, uid)` is the one place that answers it and every
place that lists or picks people uses it (GET /api/users, sharing a list or a folder, attendees, new owners); admins see
everyone. The modes match the two ways Kalmido is run:

- **own organisation** (`org`, the default): one company or family per instance, as on a self-hosted server.
- **own contacts** (`contacts`): a shared, hosted instance of many households and companies: no directory; a person sees
  only the people they are connected with (a list or group in common, their kids / parents, their own agents) and shares
  by e-mail address (the answer never says whether the address has an account); new people come by invitation (#697).

A new account joins the instance's first organisation (or the ones the admin picks); on the update to 2.22 one
organisation named after the instance's domain was created with every existing account.


2.23.0 (#799): the kind of instance is configuration (`KALMIDO_INSTANCE_MODE`, `instance_mode()` in `accounts/orgs.py`):
`organisation` (one organisation, every account in it, synced at start by `instance_sync`), `shared` (no organisations,
visibility fixed to "own contacts") or, without the variable on an instance that kept several organisations, `multi`.
The app never creates or deletes organisations; `user_orgs()` / `vis_mode()` answer by the mode.
