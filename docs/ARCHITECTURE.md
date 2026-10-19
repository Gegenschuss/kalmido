# Architecture

How Kalmido is built, where things live and how to add to it. For setting it up see the [README](../README.md); for the
development workflow see [CONTRIBUTING.md](../CONTRIBUTING.md).

## The big picture

```
 browser (PWA)                          server (one container)                      outside (optional)
 ---------------------------            -------------------------------------       ------------------------
 static/index.html                      app.py  (entry point)                       ntfy / Web Push services
 static/js/*.js   (web client)  --->    kalmido/  (Flask app, ~80 modules)  --->    Git hosts, Karakeep,
 static/sw.js     (offline)     <---    PostgreSQL 17 (own container)               calendars, IMAP / SMTP,
 static/i18n/*.json                     background threads (watchdog ...)           webhooks, OIDC provider
                                              ^
 agents / scripts / MCP clients  ---------->  |  /api/v1 (tokens, scopes; mcp/kalmido_mcp.py is a thin bridge)
 calendar + contacts apps          ------->  |  /dav/ (CalDAV, CardDAV), /ical/
```

- **Server**: Python with Flask behind waitress, PostgreSQL 17 as the only database since 2.37.0 (plus files below the
  attachments folder). No ORM: SQL with parameters in every module (see [Database](#database-postgresql-237)). `python app.py` starts it (the same command as always).
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
   2.41.0 (#1376): besides the total `v` it carries a change counter per area (`a`: tasks, comments, agentchat, team, office,
   calendar, news, other; `bump()` takes the area from the request's route, background work counts as other). A change of
   comments, chats, news or calendars only fetches those parts and redraws only the counters that moved (`static/js/liveparts.js`);
   tasks / lists / other reload the state as before. Office views are never redrawn by someone else's change, and unsaved
   form input (`formguard.js`) holds redraws back.
   2.42.0 (#1376): a change of the tasks area fetches only the tasks changed since the client's `v` (`GET /api/state/delta`,
   `tasks/delta.py`): database triggers write the id of every task whose serialization changes into `dl_changes`, `bump()`
   stamps them with the new version; a change of what someone sees (lists, shares, sections, fields) or too many / too old
   changes answer `full` and the client loads the whole state as before. The view is morphed (unchanged rows keep their
   nodes), the sidebar is redrawn only when a counter moved.
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
| `core/compress.py` | 2.65.0 (#1505): JSON answers from 1 KB on go out gzip-compressed when the client accepts it (not files, streams, HEAD, 304 or answers that already carry a Content-Encoding). |
| `core/pages.py` | HTML pages, security headers, /api/version, the share target, quick capture, /drop and the ntfy share inbox. |
| `core/instance.py` | Version, update check and instance settings (admins). |
| `core/state.py` | GET /api/state: everything the web client loads at start and after a change. |
| `lists/lists.py` | Lists: create, change, share (people + agents), members, sidebar order. |
| `lists/groups.py` | Groups of people (admin): materialized list memberships, tasks assigned to a group. |
| `lists/grouppics.py` | Group pictures: a preset or an own photo per group, served with login to who may see the group (2.46.0). |
| `lists/ownership.py` | Transferring the ownership of a list; orphaned lists (owner disabled or an agent). |
| `lists/sections.py` | Saved filters, folders and sections (kanban columns). |
| `tasks/validation.py` | Task activity log, input validation, repeat rules (RRULE) and task tree helpers. |
| `tasks/tasks.py` | Creating and changing tasks: milestones, moving subtrees, tags, assignees, waiting on someone (outside). |
| `tasks/roadmap.py` | The roadmap and shifting a list's dates (dependent tasks move along). |
| `tasks/lifecycle.py` | Applying changes, completing (repeats), undo, skip, reopen, delete, trash and restore. |
| `tasks/attachments.py` | Files of tasks (upload, download, delete). |
| `tasks/batch.py` | Reordering and batch changes of tasks, occurrences of repeating tasks, deleting attachments. |
| `tasks/delta.py` | 2.42.0 (#1376): the delta state `GET /api/state/delta?since=v` (change triggers into `dl_changes`, stamped by `bump()`; `full` when unsure). |
| `collab/comments.py` | Comments, mentions, the activity timeline and collaboration pushes. |
| `collab/news.py` | The News feed and the notification settings (matrix + list bells). |
| `personal/habits.py` | Habits and focus sessions (pomodoro), private per user. |
| `personal/timetrack.py` | Time tracking (module "time") and the unknown-JSON-field check of the REST API. |
| `accounts/settings.py` | Per-user settings, the data export and Web Push subscriptions. |
| `accounts/layouts.py` | 2.32.0: views built from blocks: the layout format, the project page arrangement (standard + own); people only, never agents. |
| `accounts/onboarding.py` | Onboarding and the sample project. |
| `accounts/users.py` | Users and the own account (admin user management, passwords, deletion). |
| `accounts/useradmin.py` | 2.88.0 (#1980): the user management in pages (search, filter), several accounts at once, deleting an account with its lists handed over or deleted along. |
| `lists/templates.py` | Task and list templates, built-in project types. |
| `tasks/dependencies.py` | Dependencies between tasks ("blocked by"). |
| `tasks/depchain.py` | The dependency chain moving along with a later due date, and "Pull the chain in" (2.67.0). |
| `lists/projects.py` | Project lists: status, progress, the overview (description, links, files), milestone reports. |
| `lists/fields.py` | Custom fields of a list. |
| `lists/playbook.py` | The Playbook of a list or folder (2.39.0): versions, rights, the agents' proposals, the playbook in agent events, the scheduled checks of a list. |
| `personal/stats.py` | Statistics (module "stats"). |
| `calendars/icalfeed.py` | The subscribable ICS calendar feed of a user's tasks. |
| `calendars/caldav.py` | CalDAV server for tasks (VTODO) with app passwords; the /dav/ entry point for event calendars and CardDAV too. |
| `integrations/importers.py` | Importers: TickTick, Todoist, Trello, Asana, Microsoft To Do, ICS / VTODO (preview, dry run, undo). |
| `notify/push.py` | Notifications: ntfy, Web Push (RFC 8030 / 8291 / 8292), reminders and nags, the watchdog tick and loop. |
| `notify/alerts.py` | Admin alerts via ntfy (recording, sending, settings). |
| `notify/caps.py` | 2.33.0 (#927): the owner's notification template of a list / shared folder (read, work, all, custom; per person), a ceiling for pushes checked in `notif_ok`; the one-time question to owners of lists shared before. |
| `calendars/subscriptions.py` | External calendars (read-only subscriptions): SSRF guard, ICS / CalDAV sync, API. |
| `calendars/polls.py` | 2.98.0: scheduling polls -- proposed times, the public vote page `/s/v/<token>`, the chosen time becomes an event. |
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
| `agents/gates.py` | 2.26.0: approval requests without a pull request (ready to integrate / ready to deploy with its checklist). |
| `agents/safety.py` | 2.30.0: agents stay inside one circle of people: bridges between lists with different people (409 + approval), moving tasks across circles waits for approval, the list restriction of agents / tokens, the agents' list access log. |
| `agents/usage.py` | Model usage of agents, limits and the agents' audit log. |
| `lists/public.py` | Public links of lists and checklist mode. |
| `lists/custview.py` | 2.50.0 (#329): the customer view of a public link (`public_links.cv_show`: what the customer sees, filtered on the server). |
| `office/signoff.py` | 2.50.0 (#1200): approval links with a simple electronic signature (`office_signoffs`): accept / decline a sent quotation, acceptance of a list, section or milestone; the customer page `/s/q/<token>`. |
| `integrations/git.py` | Git integration of project lists (GitHub, GitLab, Gitea / Forgejo, Bitbucket) and tickets for agents. |
| `integrations/errorreports.py` | Error reports (Sentry, GlitchTip ...) -> tickets. |
| `api/projects.py` | The project page in the token API. |
| `api/scopes.py` | Token scopes, approvals and the complete agent API (the routes the web client has). |
| `collab/notes.py` | Notes of a list / project. |
| `wiki/pages.py` | 2.49.0 (#1199): knowledge pages per organisation or private (path = name, `[[links]]` + backlinks in `wiki_links`, rename relinks, trash / restore, ZIP export / import). See docs/WIKI.md. |
| `wiki/outline.py` | 2.49.0 (#1201): parses an outline (Markdown list, OPML, FreeMind `.mm`; no DOCTYPE / entities) for the mind map import; stores nothing. |
| `collab/teamchat.py` | Team chat (rooms and direct messages). |
| `collab/msgsearch.py` | 2.33.0: search in comments, team chat and agent chats; since 2.37.0 a trigram index (`pg_trgm`) on `kalmido_fold(body)` (unaccent + umlaut folding) per message table, visibility, snippets. |
| `wiki/wikie2e.py` | 2.64.3 (#1817): the lock per knowledge space -- path and text of the pages of a space encrypted in the browser; routes `/api/wiki/e2e...`, the write guard `wke_guard` of the page routes. See *Lock per list* below. |
| `wiki/wikiatt.py` | 2.99.0 (#2182): files of knowledge pages (PDF / PNG / JPEG / GIF / WebP, SVG cleaned; type from the content) in `wiki_files` -- upload to a page, the ZIP import (SilverBullet export: links `[[x.pdf]]`, `![[_attachments/x.png]]`, `![](x.png)` resolved and rewritten to `/api/wiki/files/<id>/<name>`, unlinked files on "Imported files" of their folder, 25 MB per file, 500 MB per ZIP streamed into a temporary file) and the export (`_attachments/<page>/<name>`, links back as `[[…]]`). Rights = the page's; stored sealed like attachments; none in a locked space |
| `collab/liste2e.py` | 2.64.1 (#1817): the lock per list -- texts of a list encrypted in the browser with a list key. Helpers (`le2e_mode`, `le2e_parse`, ...), the routes `/api/lists/<id>/e2e` (info, start, todo, bulk, finish, stop, keys), the one write guard `le2e_guard` (in every web write of a task, comment, note, section and text field), moves only with re-encrypted texts, memberships without agents / participants. See *Lock per list* below. |
| `collab/notelock.py` | 2.48.0 (#1642): a task's note locked with its owner's password (`task_note_locks`, ciphertext only, `tasks.content` emptied; only own unshared lists); `ln_guard` keeps every other write (app, API, agents, proposals, CalDAV) off a locked note; flags `note_locked` / `note_locked_mine`. |
| `collab/e2e.py` | 2.42.0 (#828, #909): end-to-end encryption in the browser: the person's public key + wrapped key bundle (`e2e_keys`), the encrypted note of a task (`task_enc_notes`), encrypted task files (`attachments.enc`), the switch of an encrypted DM (`tchat_rooms.e2e`, `tchat_msgs.enc`). Stores ciphertext only; see *End-to-end encryption* below. |
| `collab/chatsave.py` | 2.37.0 (#1159): a chat message (agent chat, team chat) saved as a task by a person: text, file copies, link back (`#msg/...`); `chat_saves` per person, `saved_task_id` in the chat pages. 2.42.0 (#1383): also an agent's comment on a task (kind `comment`: a subtask of the task or a new task in its list). |
| `collab/replies.py` | 2.33.0: replies to one message (comments, team chat, agent chat): `reply_to` checks and the short quotes. |
| `integrations/mail.py` | Tasks by e-mail (IMAP) and the daily summary by e-mail (SMTP). |
| `integrations/mailtrim.py` | 2.49.0 (#971): `md_trim_forward(text)`, a pure function: a forwarded mail becomes one line "From <sender>, <date>" + the message without signature, legal notice and older quoted replies. Used by *Tasks by e-mail* when the person switches *Shorten forwarded mails* on (`mail_trim_fwd`, off by default; the original stays as `.eml` unless `mail_trim_eml` is `0`). |
| `accounts/orgs.py` | Organisations (#752): people in 1..n organisations and whom a person may see (all / own organisation / own contacts). |
| `accounts/invite.py` | Invitations and reset links (#697): a one-time link by e-mail with which a person sets their own password. |
| `accounts/pwreset.py` | 2.49.0 (#1531): *Forgot your password?* on the login page: the reset link of `invite.py` by e-mail, the same answer for every address, rate limited. |
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
| `life/budget.py` | 2.72.0 (#1333) Home & life: the household budget (a list of kind `budget`): categories with monthly limits, entries, recurring items + taking them over from contracts, the month (planned / actual), the bank import (CSV), receipts; fields encrypted with the list's space key, `bud_settle` reseals after a move. |
| `life/budget_web.py` | 2.72.0 (#1333): the web API of the household budget (`/api/budget...`; no REST v1 / MCP, never for agents). |
| `life/rss.py` | 2.85.0 (#1162): feeds of a person (module `feeds`): fetch through the SSRF guard of the calendar subscriptions (`cal_http`), RSS 2.0 / Atom / RSS 1.0 parsed without DTDs (`xml_no_dtd`), plain text only, "Read later" -> a task in the reading list, OPML, the watchdog step (hourly, 30 days). |
| `life/rss_web.py` | 2.85.0 (#1162): the web API of the feeds (`/api/feeds...`; no REST v1 / MCP, never for agents or API tokens). |
| `life/v1.py` | Home & life: the REST API v1 (+ MCP) and its OpenAPI part (health + journal: scope "private"). |
| `team/clients.py` | Clients (module "clients"): clients of an organisation above the lists, hours, budget, estimate vs. actual. |
| `team/workload.py` | Workload (module "workload"): planned hours per person and week against their capacity. |
| `hub/absence.py` | 2.50.0 (#1195): absences per person and area (the team sees "away", the kind only the person and the admins; kind + note encrypted at rest), German public holidays per state, the effect on workload, day plan and assigning, `GET /api/v1/absences`. See docs/TEAM.md. |
| `hub/dispo.py` | 2.50.0 (#1194): resources and disposition (module "dispo"): bookings of members, contacts, equipment and sets (option / firm), double bookings and absences as warnings, "who is free", my bookings. See docs/TEAM.md. |
| `team/approvals.py` | Approvals as a step of a task: request, approve / changes / reject, withdraw. |
| `team/forms.py` | Forms (module "forms"): a link whose page (/f/<token>) creates a task in a list. |
| `team/v1.py` | Clients, workload, approvals, forms: the REST API v1 (+ MCP) and its OpenAPI part. |
| `accounts/signup.py` | Self-registration on the login page and sign-in links (QR) for people without e-mail. |
| `admin/hosting.py` | Running Kalmido for others (2.24.0): storage quota per person, the notice / maintenance banner, daily e-mail limits, the "agent joined" notice, `KALMIDO_HOSTED`. |
| `admin/clientip.py` | 2.33.0 (#834): does the client's address arrive? Private sign-in addresses (14 days), the warning when many accounts sign in from one private address (log + Administration > Server), "Your IP". |
| `admin/supporter.py` | 2.74.0 (#338): the supporter licence (self-hosted only): Ed25519 keys checked offline, server / personal licence, the badge and the yearly admin hint; unlocks nothing. |
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
5. Layers (2.102.0): every package sits in one of five layers, lowest first -- `core`, `accounts`, `domain` (tasks,
   lists, calendars, office, ...), `integrations` (api, admin, mail, webhooks, importers, ...) and `agents` (`LAYERS` in
   `kalmido/__init__.py`, `LAYER_OF` for a single module). At module level a module imports only from its own or a lower
   layer; a higher one inside the function. `python3 tools/check_layers.py -v` checks it in CI; the upward imports the
   code already had stand in its `KNOWN` list, which may only shrink.

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
| `vlist.js` | Long lists (2.65.0): a view with more than 300 rows draws only the rows near the visible part (see below). |
| `calendar.js` | Kanban, the calendar events' data and what other views show of the calendar. |
| `calview.js` | 2.65.0 (#1823): the calendar views month / week / day and Settings > Calendars. Loaded on demand (module `calendar`). |
| `timeline.js` | The timeline (Gantt). |
| `depchain.js` | The chain moving along: drag preview, the not-moved note, "Pull the chain in" (2.67.0). |
| `roadmap.js` | The roadmap. |
| `habits.js` | The Eisenhower matrix, habits and the pomodoro timer. |
| `detail.js` | The detail panel of a task. |
| `multiedit.js` | 2.26.0: several selected tasks edited at once in the task panel (common values, "Mixed", one undo step). |
| `sheetdrag.js` | 2.39.1: bottom sheets on phones (menus, date picker, quick add, dialogs) dragged taller / shorter at their grip and swiped down to close (2.102.0: on `drag.js`). |
| `drag.js` | 2.102.0 (#1998): the shared core of dragging (touch, mouse, pen; threshold, long press, ghost, auto-scroll, Esc), see "Dragging" below. |
| `clienterr.js` | 2.102.0 (#1999): the browser's own unhandled errors to `POST /api/client-errors` (only when the server operator chose a list), loaded right after `reloadguard.js`. |
| `notelock.js` | 2.48.0 (#1642): lock a task's note with one's own password (the keys of `e2e.js`): "Lock note" under the description (own, unshared lists), the locked placeholder, unlocked editing (saved as ciphertext), "Remove lock"; drops undo steps that still hold the old text. |
| `e2e.js` | 2.42.0 (#828, #909): end-to-end encryption with WebCrypto: set up / unlock / lock / change / reset the keys (Settings > Account), the encrypted note in the task detail, encrypted files (*Attach encrypted*), encrypted DMs (lock in the DM head, safety number). |
| `miniwin.js` | 2.39.1: a list in its own small browser window (double / middle click in the sidebar, list menu); the window (`/?mini=1#l/<id>`) shows only the list and keeps its UI state to itself. 2.43.0 (#1500): a task in its own window too (`/?mini=1#t/<id>`, middle click on the row, task menu, button in the task panel). |
| `chatwins.js` | 2.47.1 (#1720): several chats at once in the chat side panel, one above the other (agents, team chats, direct messages): Ctrl / Cmd + click or *Open in split window*, a divider between them, fold, close, reorder, remembered per device; one window holds the usual ids and state (`S.chat` / `S.tc`), the others are parked. Phones: a row of the open chats above the chat. |
| `favorites.js` | 2.40.0: favourite lists (#1361): the star, the *Favourites* section of the sidebar, *Only favourites* and the favourites filter of views. |
| `favtiles.js` | 2.57.0 (#1798): favourites of every kind (lists, folders, views, areas, filters, tags, people, groups, agents) as icon tiles in the sidebar's fixed head: the star in the row menus, one order (`fav_items`), the tile menu (Move left / right) and dragging. |
| `mineorder.js` | 2.40.0: your own order of *My tasks* (#1344), kept per person on the server (`user_task_order`). |
| `mdtitle.js` | 2.40.0: inline Markdown in task titles (`mdTitle`) and the plain text for attributes, tabs and notifications (`mdPlain`). |
| `formguard.js` | 2.40.0: keeps unsaved form input in Office & finance across redraws and view switches, *Save / Discard*, a question before leaving (#1371). |
| `countries.js` | 2.40.0: the country picker (names from the browser, ISO 3166 alpha-2 codes) of the client card, company data and import preview. |
| `collab.js` | News and comments + activity (module "collab"). |
| `attachments.js` | Attachments and the share target. |
| `pdfview.js` | 2.48.0 (#1367): the PDF preview `pdfView({url, name, size, dlUrl})` (lightbox: pages drawn on demand, turn pages, zoom, swipe, a clear message offline or for a damaged file) for attachments, project files, office documents and archive PDFs; links carry `data-pview`. Uses the bundled pdf.js (`static/vendor/pdfjs/`, loaded on first use, `isEvalSupported: false`, no scripting). |
| `undo.js` | Undo / redo history. |
| `popovers.js` | Popovers (date, priority, list, tags, reminders, repeat ...). |
| `dialogs.js` | Modals: the app's own dialogs, the list dialog and the share dialog. |
| `settings.js` | Settings: the dialog, notifications, autosave settings, personal agents, import. Loaded on demand (2.53.0). |
| `integrations.js` | API tokens + scopes, webhooks, public links, calendar apps (CalDAV). |
| `custview.js` | 2.50.0 (#329): Share dialog > Public link > *What does the customer see?* |
| `signoff.js` | 2.50.0 (#1200): approval links on a sent quotation and in the Share dialog (acceptance), with their protocol. |
| `account.js` | Account, users (admin), login, groups, passkeys, two-factor, sign-in policy, backups, the sample project. |
| `templates.js` | Templates and the charts (statistics, time tracking, agent usage). |
| `stats.js` | 2.65.0 (#1823): the statistics view. Loaded on demand (module `stats`). |
| `time.js` | Time tracking (module "time"). |
| `projects.js` | Projects: status, progress, overview, dependencies, custom fields. |
| `events.js` | Toasts, quick add wiring and the global event handlers. |
| `sidebar.js` | Multi-select bar, filter lists and the list order in the sidebar. |
| `dnd.js` | Drag & drop (desktop) and swipe (touch). |
| `dragmulti.js` | Dependencies by dragging (Alt + drop, drop fields in the task panel) and dragging several selected tasks (block, subtasks, sections). |
| `palette.js` | Keyboard shortcuts, the command palette, the welcome tour. |
| `agents.js` | Agents, reactions, shared list tags, tidy suggestions. |
| `cleanup.js` | "Tidy up the list": the request to the list's tidy agent and the review of its cleanup proposal (2.39.0). |
| `dayplan.js` | Day planning and the evening review. |
| `agentchat.js` | The chat with an agent (side panel / view) and Settings > Agents: lists, setup guides, behaviour rules, activity log, usage, runtime. Loaded on demand (2.65.0, module `agentchat`). |
| `chatbase.js` | 2.65.0 (#1823): what the start uses of the agent chat: the phone / desktop switch, the pop-up button, reaction rows, `patchKids`, the task panel's usage line. |
| `listedit.js` | List editing, keyboard reordering, recent lists. |
| `playbook.js` | The Playbook of a list or folder (2.39.0): the area in the list and folder dialogs, editor with preview, versions with a line diff and restore, agents' proposals, regular checks, the help examples. |
| `git.js` | Git integration of project lists: repositories, pull requests + CI, agents' merge requests. |
| `chat.js` | Team chat and notes of a list / project. |
| `sheetgrid.js` | 2.43.0 (#1331): lists with columns work like a spreadsheet: active cell, arrow keys / Tab / Enter, paste ranges with a preview, fill down, select several cells, column filter. |
| `formula.js` | 2.43.0 (#1328): formula fields in the client, the totals row under number columns and the key figures on the project page (server side `kalmido/lists/formula.py`, `kalmido/lists/kpis.py`). |
| `widgets.js` | 2.43.0 (#1452): blocks adjusted in place (… menu, width 1/3 to full, height, resize handle, move by the header, default for everyone / reset). |
| `lyopts.js` | 2.55.0 (#1065): the settings of a block (registry `lyo_reg(view, block, defs)`, read with `lyo_get`, gear in Customize, popover / phone sheet; stored in the arrangement's `opts`). Loads right after `core.js` so every view file can register. |
| `pinboard.js` | 2.43.0 (#1346): project page as a pinboard: a colour per block and notepads (Markdown) for everyone in the project. |
| `lysets.js` | 2.55.0 (#1069, #1068): several saved arrangements per view (switch in the header, manage, save as; server `kalmido/accounts/layoutsets.py`, table `view_layouts`) and arrangements sent to people as templates (`view_layout_offers`, News item `lytpl`). |
| `projtime.js` | 2.43.0 (#1434): tracked time of a project in a window (by person and task, period, CSV) and deleting all of its times with Undo. |
| `dashboard.js` | News bundled per task, the view builder (2.32.0: blocks per view, "Customize", project page standard + own arrangement; server side `kalmido/accounts/layouts.py`), the start page (dashboard) and Settings > Tasks by e-mail. |
| `family.js` | The module "Family". |
| `calevents.js` | Events (module "events"): the editor and popover, the agenda, creating in the week grid, calendars, the phone setup. |
| `contacts.js` | Contacts (module "contacts"): the view, the editor, the card, import / export. Loaded on demand (2.53.0). |
| `clients.js` | Clients, the workload view, approvals in the task panel, forms of a list, sign-in links with a QR code. |
| `absence.js` | 2.50.0 (#1195): the tabs of the workload view, the absences tab (month grid, list, "Enter an absence" sheet, public holidays), the day plan hint, the warning when assigning to somebody away. |
| `dispo.js` | 2.50.0 (#1194): the disposition tab (week grid per resource, a day list on phones, booking sheet, who is free, my bookings). |
| `life.js` | Home & life: the view, its dialogs (contract, device, upkeep, health, trip, Karakeep), the review + journal, staying in touch on a contact's card. |
| `budget.js` | 2.72.0 (#1333): the household budget (`#budget/<list id>`, a tab of the area Home): month view with totals, six-month bars, categories with their limit, "Open this month" (recurring entries to book), entries per day; the dialogs entry (+ receipts), categories, recurring entries, taking over contracts, CSV import with column mapping; the card on Home & life; reloads on the area `budget` of `/api/version`. |
| `feeds.js` | 2.85.0 (#1162): feeds (`#feeds`, a tab of the area Home, loaded on demand): follow a feed by its address, OPML import / export, the articles newest first (unread marked, plain text, links with noopener) with Open / Read later / Read, all read, manage feeds; the card on Home & life. |
| `areas.js` | 2.44.0 (#1187): the areas Office, Time, Review and Home: one sidebar row / tab each, the tabs of their parts on top of the page (each part keeps its route), one switch per area in Settings > Modules. |
| `sbnav.js` | 2.45.0 (#1509): the messenger in the sidebar: "Messages" with the unread count, the last five conversations, a speech bubble at every person for a direct message. |
| `wiki.js` | 2.49.0 (#1199): `#wiki` / `#wiki/<id>` = the knowledge pages of a space (an organisation or private): tree from the paths, editor with `[[` suggestions and autosave, backlinks, templates, ZIP export / import. |
| `mindmap.js` | 2.49.0 (#1201): the list view "Mind map" (SVG, keys like Mindjet, drag to rehang, pan / pinch, outline, export Markdown / SVG / PNG, outline import) and the ```mindmap block of knowledge pages. |
| `notesall.js` | 2.45.0 (#1516): `#notes` = the notes of all lists and projects (pinned first, a filter by list, a search in title and text, a new note in a picked list). |
| `lazyload.js` | 2.53.0 (#1410): modules loaded on demand (`loadModule`, the stand-ins of their functions, `officeOn`), see below. |
| `setcore.js` | 2.53.0 (#1410): the parts of the settings needed from the start: Web Push on this device, the app badge, the service worker's messages, the settings sections and modules, the project links. |
| `ctlinks.js` | 2.53.0 (#1410): the contacts in the task panel ("People and dates", linking a contact). |
| `main.js` | Start-up: loading the state, polling, the service worker. Loaded last. |

### Adding a client file

1. Create `static/js/<name>.js` with `// @ts-check` as its first line (2.102.0), the header comment and `'use strict';`.
2. Add its `<script>` tag to `static/index.html` (before `main.js`, after the files whose functions it calls while it
   loads), add it to `SHELL` in `static/sw.js` in the same order and bump `CACHE` there.
3. `python3 tools/check_layout.py` compares the three lists; `node --check` runs on every file in CI.

### Type check (2.102.0)

TypeScript checks the client without a build step and without changing the code: `jsconfig.json` makes every file of
`static/js/` (and `static/i18n.js`) one program in the global scope, exactly as the browser runs the classic scripts, but
only files whose first line is `// @ts-check` are checked. `tools/tsc/kalmido.d.ts` types the shared globals (`S`, the
answer of `api()`, `about`, `window` stand-ins); `S`, `api()` and `tr()` carry JSDoc types in `core.js` / `i18n.js`. The
app never loads the `.d.ts`. CI runs `python tools/check_tscheck.py` (every file not in its `BASE` list, so every new file,
must start with `// @ts-check`) and `npx -p typescript@6.0.3 tsc -p jsconfig.json`. Locally the same in the repo root:

```bash
python3 tools/check_tscheck.py && npx --yes -p typescript@6.0.3 tsc -p jsconfig.json
```

Switching an older file on: add `// @ts-check` as its first line, fix what tsc reports (mostly a JSDoc type or cast
`/** @type {HTMLElement} */ (e.target)`; never a change of behaviour), remove the name from `BASE`.

### Dragging (2.102.0)

`drag.js` is the shared core of dragging: `drg_attach(root, opts)` lets presses inside `root` start drags (`opts.start`
decides per press), `drg_begin(el, x, y, opts)` starts one at once after a long press the caller detected. The core
follows the input (touch events for fingers -- a pointer would be cancelled once the browser pans --, pointer events with
capture for mouse and pen), waits for the threshold (`threshold`, or `accept` for an own rule), moves a ghost by
`transform`, scrolls the scroller at its top / bottom edge (`scroll`, also while the pointer stays still), cancels on Esc,
a second finger or a cancel event, and swallows the click after a drag. The caller keeps what is its own: `onStart`,
`onMove`, `onDrop`, `onCancel`, `onTap` (let go before the drag started). Sections (`secdrag.js`, the long press of
`dnd.js`) and bottom sheets (`sheetdrag.js`) use it; caldrag, roadmap, timeline, dnd / dragmulti and mindmap follow.

### Long lists (2.65.0)

A list view, Completed / Trash and the search results with more than `VL_MIN` (300) rows, and an address book of that
size, are windowed by `vlist.js`: each group is drawn as a top spacer, the rows near the visible part (plus one and a half
screens above and below) and a bottom spacer. Scrolling moves the window once per frame; measured row heights (an average
for rows not drawn yet) keep the scroll height, and a spacer takes over the height of rows that leave or come above the
visible part, so nothing visible moves. Code that needs the order of all rows of the view (Shift-click, Ctrl+A, j / k,
the neighbours of a drop, swiping between tasks in the panel) calls `vl_ids()` instead of reading `.trow` from the DOM;
`vl_reveal(id)` scrolls a row that is not drawn into the window. Shorter views are drawn as before.

### Modules loaded on demand (2.53.0)

Rarely opened areas have no `<script>` tag: `static/js/lazyload.js` loads them the first time they are used
(`loadModule(name)` -> a promise; each module once, a failure shows a toast with "Try again"). Today: the settings dialog
(`settings.js`), the contacts view (`contacts.js`) and Office & finance (`office*.js`, `officeagents.js`, run one after the
other). What the start needs from them stays in files loaded at start: `setcore.js` (Web Push, the app badge, the
settings sections), `ctlinks.js` (the contacts in the task panel) and `officeOn` in `lazyload.js`.

- `LD_MODS` in `lazyload.js` names the files of each module; `LAZY` in `static/sw.js` lists the same files in the same
  order (cached right after the shell, so they open offline); `tools/check_layout.py` compares both and checks that none
  of them has a script tag.
- Code loaded at start calls a module's functions only through the stand-ins in `lazyload.js` (`LD_CALL`: load, then
  call; `LD_VIEW`: draw "Loading…", load, draw the view again) or after `await loadModule(...)`. Constants of an
  on-demand module do not exist before it is loaded (`typeof X` to ask).
- Moving a file to on demand: check with `grep` which of its globals other files use, keep those in a file loaded at
  start or give them a stand-in, then move the file from the script tags / `SHELL` to `LD_MODS` / `LAZY`.
- Tests: `tests/boot.js` (jsdom) and `tests/ff.js` (Firefox) load every on-demand module right after the start, so suites
  may call their functions directly; `lazy: true` leaves them to the app (`tests/p253_a_ui.js`).

2.65.0 (#1823, #1824): more modules, and modules carry their styles.

| Module | Files | Opens with |
|---|---|---|
| `agentchat` | `agentchat.js`, `agentsetup.js` | the agent chat, Settings (needs `integrations`) |
| `calendar` | `calview.js` (month / week / day, Settings > Calendars), `caldrag.js` | the calendar view, Settings |
| `stats` | `stats.js` (the statistics view; the charts stay in `templates.js`) | the statistics view |
| `wiki`, `mindmap` | `wiki.js`, `mindmap.js` | knowledge pages (need `mindmap`), a list as mind map, a task's "Mentioned in" |
| `pdf` | `pdfview.js` | a click on a preview link (`data-pview`, the listener is in `lazyload.js`) |
| `docs` | `docs.js`, `paperless.js`, `receipts.js` | the documents view, the share sheet's "File as document" |
| `life` | `life.js` | Home & life, the daily review, a life list's bar / a life task's details |
| `integrations` | `integrations.js` | Settings, the agent chat (tokens, webhooks, CalDAV) |
| `playbook` | `playbook.js` | the playbook area of a list / folder dialog, Settings |
| `timeline` | `timeline.js`, `roadmap.js` | a list's timeline, the roadmap, the calendar's timeline |
| `feeds` | `feeds.js` (+ `css/feeds.css`) | 2.85.0 (#1162): the view Feeds, the card Feeds on Home & life |

`contacts` now also loads `newsletter.js`, `settings` first `acctset.js` (the settings sections of `account.js`; sign-in,
invitations and logout stay in `account.js`). What the start needs of them stays at start: `chatbase.js` (the phone /
desktop switch of the chat, the pop-up button, reaction rows, `patchKids`, the task panel's usage line), `calendar.js`
(the events' data, the kanban board, the agenda's bar, `calReq`), `templates.js` (the charts) and small parts in
`lazyload.js` (`pv_attr`, the documents switch, `lifeOn` / `fmtMoney`, `pbOn` / `pbMenuItem`, `isRoadmap` / `tlReaches`,
`API_DOCS`).

- `LD_NEED`: modules a module needs before its own files (Settings: agent chat, calendar, integrations, playbook).
- `LD_NOP`: stand-ins that do nothing before the module is loaded (they only update what the module drew, e.g. `chatPatch`).
- Styles: `LD_CSS` names each module's stylesheets in `static/css/<name>.css`; `loadModule` loads them next to the
  scripts and resolves only once both apply (no unstyled flash); `loadCss(name)` loads one alone. `LAZY_CSS` in
  `static/sw.js` precaches them (offline); `tools/check_layout.py` checks `LAZY_CSS` = `LD_CSS` = `static/css/*.css`. A
  module stylesheet comes after `app.css` in the cascade: only rules whose every selector names a class / id that only the
  module's scripts use move there, and none that a later rule of `app.css` for the same class would override. Suites that
  read rules use `allCss()` / `allCssSync()` of `tests/boot.js` (app.css + the module stylesheets).
- Idle preload: 5 s after the start, one per idle moment, Settings (with what it needs), then the areas this person has
  switched on (calendar, timeline, knowledge pages, documents, home & life); not office, contacts, statistics, PDF.

## Database: PostgreSQL (2.37)

Since 2.37.0 Kalmido runs on PostgreSQL 17 only (`DATABASE_URL`); SQLite is gone.

- **One driver module.** `kalmido/core/pg.py` is the only place that knows psycopg 3. It translates the `?` placeholders
  of the existing SQL (literals, comments and `$$` bodies are left alone), returns rows that behave like before (index,
  name, `keys()`, `dict()`), and offers `insert_id()` (`RETURNING id`), `write_lock()` (advisory lock for check-then-write),
  `savepoint()`, `heal()` (rollback after an aborted transaction), `like_escape()` and `system_ctx()`.
  `db()` / `connect()` in `core/db.py` lend a connection from a pool (4 to 56, `KALMIDO_DB_POOL_MAX`; every lend is
  checked, so a restarted database costs no errors). 2.102: the pool follows `KALMIDO_THREADS` (threads x 3 + 8), a
  wait that runs out is logged with the pool's counters, `GET /api/admin/health` shows them (`admin/worker.py`).
- **Migrations (2.102).** `MIGRATIONS` in `core/schema.py` stays a list of additive steps (append at the end). Each step
  gets a stable id from table + column (`tasks.pinned`, a second step for the same column `lists.tap_done#2`), so its
  place in the list does not matter. `init_db` (`mig_apply`) runs the steps whose column is missing and records every step
  in the table `kalmido_migrations` (applied / present / again, with the time). The one-shot data migrations keep their
  settings flag (`migr_*`, read by older versions after a rollback) and are recorded there as `flag:migr_*`.
  `SCHEMA_VERSION` only gates restores of newer backups.
- **Process roles (2.102).** `KALMIDO_ROLE=all` (default) runs web and background loops in one process; `web` runs no
  loop; `worker` (`python app.py worker`) runs only the loops. Every loop thread (by its name, `admin/worker.py`
  `WRK_LOOPS`) takes a session-level `pg_try_advisory_lock` of its own before its rounds -- the check sits in
  `GATE.bg()` -- so one process of the instance runs each loop. New loops: start them with `wrk_start(name, fn)` in
  `startup.py`, or give an on-demand queue thread a name and add it to `WRK_LAZY`.
- **Session limits.** Every connection runs with `statement_timeout` 30 s, `idle_in_transaction_session_timeout`
  5 min and `jit=off`. Network calls (mail, calendar and contact sync, Web Push) run outside open transactions.
  `init_db` and the backup lift the statement limit for themselves.
- **Schema.** `core/schema.py` in the PostgreSQL dialect (one source): identity ids, integers as `BIGINT`, booleans
  stay 0/1, timestamps stay ISO text, office amounts `NUMERIC(14,4)`, four `jsonb` columns. `init_db` runs in one
  transaction under an advisory lock, creates the extensions `unaccent` and `pg_trgm`, adds missing columns and keeps the
  schema version in `kalmido_meta`; a database newer than the image refuses the start.
- **Errors.** Postgres aborts the whole transaction on an error: code that catches a database error and goes on uses
  `with c.savepoint():`. An uncaught invalid value answers 400 (`DbError` handler, with rollback) instead of storing it.
- **Row-level security (stage 1).** On top of the access layer (below), every table with `org_id` (lists, calendars,
  address books, agents, clients, the office tables, the organisation log) and `orgs` / `org_members` has a policy with
  `ENABLE` + `FORCE` (`kalmido/core/rls.py`, applied by `init_db`): a row of an organisation leaves the database only for a
  transaction whose context holds that organisation. The context (`app.user_id`, `app.org_ids`, `app.role`) is set at the
  start of every transaction from the request (`user`, `agent`; `anon` for public links and forms, bound to exactly the
  organisation of the resolved link) or `system` outside requests (background threads). Admin overviews count across
  organisations in a visible `with system_ctx(c):` block (each with a reason comment; `tests/rls_static_test.py` checks
  it), never reading contents. When the login role bypasses row-level security (the superuser of the official image), the
  pooled connections switch to the role `kalmido_app` (`NOLOGIN`, no bypass), which `init_db` creates and grants.
  Tests: `rls_static` (every org table has a policy) and `rls_direct` (other organisations give 0 rows, writes are
  refused, also via CalDAV and public links).
- **Static guards.** `tests/pg_dialect_test.py` (no SQLite dialect left, psycopg only in `pg.py`) and
  `tests/pg_prepare_test.py` (every SQL string of the server is `PREPARE`d against the real schema).

## Tests and checks

- `tests/run_all.sh`: the API, UI (jsdom and Firefox), security and calendar suites against a fresh test container
  (see [tests/README.md](../tests/README.md)).
- CI (`.github/workflows/ci.yml`): Python and JavaScript syntax of every file, `tools/check_layout.py`, translations,
  the MCP bridge, bandit (high severity), pip-audit, the browser demo, semgrep and the test shards.

### Performance budget (2.65.0)

`python tools/perf_budget.py` measures, statically from `static/index.html`, what the browser loads before the app shows
anything: every script tag (raw and gzip size, count) and the stylesheets, and lists the files loaded on demand (`LAZY` /
`LAZY_CSS` in `static/sw.js`) for comparison. The limits are in `tools/perf_budget.json` (`start_js_bytes`, `start_js_gzip`,
`start_css_bytes`, `start_css_gzip`, `start_scripts`, and `start_ms`, the load time until the list shows, which
`tests/perf_ui.js` checks in the browser). CI runs the tool in the lint job; a value over its limit prints
`Budget exceeded: <key> <actual> > <limit>` and fails the build. `tests/perf_budget_test.py` proves that an oversized state fails.

To raise a limit on purpose, change the value in `tools/perf_budget.json` in the same commit as the growth and say why;
otherwise move the code into a module loaded on demand (see "Modules loaded on demand"). `--json` prints machine-readable
output, `--budget FILE` and `--root DIR` are for tests.

## Browser demo (2.12.0, rebuilt per release since 2.74.0)

`tools/build_demo.py OUT_DIR` turns the current client (`static/`) into a static folder that runs without a server:
`tools/demo/shim.js` replaces `fetch` and answers the API from the visitor's `localStorage`, `tools/demo/texts.js` holds
the demo's own texts and the sample data in the six languages. The page allows no network connection at all
(`Content-Security-Policy: connect-src 'none'`, also as `.htaccess`), has no service worker and no analytics.

- It starts like a new account: Basket, the "Getting started" list and the welcome tour; the sample project only when the
  visitor asks for it (tour or Settings > Data). Old browser storage of an earlier demo is migrated, not thrown away.
- Office & finance works locally (clients, services, quotations, invoices, payments; totals and VAT like the server).
  Instead of the server's PDF the demo opens a print view of the document (`window.print()`, no PDF library). Office
  features that need a server (DATEV, e-invoice XML, mail, agents, imports, cash flow …) show the calm "not available in
  the demo" notice.
- **Release step:** build the demo from the release's sources with `python3 tools/build_demo.py <folder>` and upload the
  folder to the website's `/demo/`. The build fails when a text replacement no longer matches the app, so a changed
  client never ships a demo that talks to a server. `tests/demo_test.js` (suite `demo`, CI job "demo") checks the build.

## Organisations and who sees whom (2.22.0)

People belong to one or more **organisations** (`accounts/orgs.py`; tables `orgs`, `org_members`). The instance setting
`people_visibility` decides whom a person sees at all; `visible_people(c, uid)` is the one place that answers it and every
place that lists or picks people uses it (GET /api/users, sharing a list or a folder, attendees, new owners); admins see
everyone. The modes match the two ways Kalmido is run:

- **own organisation** (`org`, the default): one company or family per instance, as on a self-hosted server.
- **own contacts** (`contacts`): a shared, hosted instance of many households and companies: no directory; a person sees
  only the people they are connected with (a list or group in common, their kids / parents, their own agents, an accepted
  connection request -- `conn_links`, 2.49.0, `accounts/discover.py`) and shares
  by e-mail address (the answer never says whether the address has an account); new people come by invitation (#697).

A new account joins the instance's first organisation (or the ones the admin picks); on the update to 2.22 one
organisation named after the instance's domain was created with every existing account.


2.23.0 (#799): the kind of instance is configuration (`KALMIDO_INSTANCE_MODE`, `instance_mode()` in `accounts/orgs.py`):
`organisation` (one organisation, every account in it, synced at start by `instance_sync`), `shared` (no organisations,
visibility fixed to "own contacts") or, without the variable on an instance that kept several organisations, `multi`.
The app never creates or deletes organisations; `user_orgs()` / `vis_mode()` answer by the mode.
2.28.0 (#935): + `workspaces` (several organisations as workspaces on a shared server; `visible_people()` = the members of
one's organisations + connections, admins included; the instance admin creates organisations, `org_members.role` admins
manage them). Every list / agent has a workspace (`lists.org_id`, `agents.org_id`, NULL = private); the one check is
`ws_member_problem()` / `ws_check_member()` in `accounts/orgs.py`, called on every way into a list (members, folder people,
agent shares, groups, ownership) and when the owner moves a list (`list_org_set`). The web client only decides what it
shows (`static/js/workspace.js`, setting `workspace`); `ws_migrate()` assigns the workspaces once on the update.
2.30.0 (#1036): calendars and address books have a workspace too (`ev_cals.org_id`, `books.org_id`); the rule for every
shared object is `ws_fit_problem(c, org_id, user_id)` (lists use it through `ws_member_problem`), the owner moves one with
`obj_org_set`, `ws_migrate_objs()` (`accounts/tenancy.py`) assigns them once. The boundary is guarded three ways: the
cross-tenant matrix (`tests/p2280_api_test.py`, `tests/p2300_tenant_test.py`) with `tests/tenant_coverage_test.py`, which
fails for every route that is neither in the matrix nor listed with a reason; the nightly boundary check in the watchdog
(`boundary_tick`: every membership across the boundary, an admin alert, the count in `GET /api/admin/orgs`); and the schema
rule in `tools/check_layout.py` (a new table with a person in it carries `org_id` / `list_id` or a reason in `TENANT_EXEMPT`).
2.46.0 (#1592): one kind of instance. `instance_mode()` is `workspaces` unless `KALMIDO_INSTANCE_MODE=shared`; the modes
`organisation` / `multi` are gone (`organisation` is ignored with a start-up hint). `instance_sync` puts nobody into an
organisation any more (once, `migr_om2460`, it repeats the former start-up sync on a server that was in the automatic mode
organisation); `create_user` joins no organisation (#1562), `POST /api/users` takes `orgs: [{id, role}]` (#1561). The
boundary (`_boundary_on` / `_boundary_sql` in `core/access.py`, `_org_boundary` for clients) applies on every instance but
a shared one. `visible_people()`: the members of one's organisations + connections; an instance without any organisation:
everyone. The instance admin's user management (`GET /api/users?all=1`, `om_admin_all`) lists every account and changes
the admin's own people, accounts outside all organisations and pending registrations. An agent placed in an organisation is
one of its members (`org_members`).

## Access layer and request context (2.36.2)

Who may see what is decided in one module, `kalmido/core/access.py`:

- **Request context.** Every request carries one `AccessCtx` (`acx()`): the account, the organisations it belongs to
  (`user_orgs()`; an agent only its own workspace `agents.org_id`), its role (`user`, `agent`, `system`, `anon`) and, for an
  API token limited to lists, those list ids. It is built once per request from the signed-in account and its memberships,
  never from the workspace switch: there is no "current organisation" per request, so the shared view across all workspaces
  still answers in one response. Background work (watchdog, reminders, migrations) runs as `system_ctx()`.
  Since 2.37.0 these values reach the database in every transaction and row-level security enforces the organisation
  boundary there too (see [Database](#database-postgresql-237)).
- **One list scope.** `acx_lists_sql()` is the single subquery for "lists this account may see / change" (owner, members and
  roles, the collaboration switch, the organisation boundary, health lists and token allowlists). `vis_sql()`, `wr_sql()`,
  the state (`visible_lists`) and CalDAV (`dav_lists`) all use it. It is standard SQL.
- **Second floor.** `list_role`, `ev_role` and `book_role` (and the calendar / address book lists) also require membership of
  the object's organisation (`acx_org_ok()`); private objects follow their own sharing as before.
- **Side channels.** News entries and agent events that carry a task are only created for someone who may see the task
  (`acx_task_ok()`), whatever triggered them.
- **Repair.** The nightly boundary check (`accounts/tenancy.py`) removes memberships in an organisation's list, calendar or
  address book of people outside it and reports counts and ids as a security alert; other findings are counted as before.
- **Invitations (2.87.0).** Leaving an organisation also ends the invitations to the events of its calendars (the person's
  and their agents'). An invitation counts only while the person may see the calendar's workspace (`ev_att_ok()`: event
  view, range, reply, CalDAV invitations, reminders); an organisation's event invites only its people, and a calendar moves
  into an organisation only while every invited person fits. The boundary check counts left-over invitations
  (`att_person`, removed; `att_agent`, counted). A list is handed over only to a person the owner may see or a member of it;
  anyone else gets the same 404 as an unknown id.
- **Tests.** `tests/p2362_a_api_test.py` checks leaving an organisation, people in two organisations, side channels,
  token allowlists, the layer directly against the database, and scans every route with a numeric id for a refusal.

## End-to-end encryption (2.42.0)

Optional, per person, done in the browser with WebCrypto (`static/js/e2e.js`); the server (`kalmido/collab/e2e.py`) only
stores what the browser encrypted. Separate from the server-side keys per organisation (encryption at rest).

**Keys.** Each person who sets it up gets an ECDH P-256 key pair and a random 256-bit *content key* (AES-GCM). Both
together form the key bundle, which the browser encrypts twice with AES-256-GCM (the AAD binds the user id, the version
and which wrapping it is):

| Wrapping | Key derivation | Stored |
|---|---|---|
| passphrase (at least 10 characters) | PBKDF2-SHA256, 16-byte random salt, 600 000 rounds | `e2e_keys.bundle_pass` `{v, kdf, iter, salt, iv, ct}` |
| recovery code (160 random bits, shown once as 8 groups of 4 Base32 characters) | HKDF-SHA256, 16-byte random salt | `e2e_keys.bundle_rec` `{v, kdf, salt, iv, ct}` |

The server also keeps the public key (JWK). It never sees the passphrase, the code, the private key or the content key.
Unlocking (passphrase) imports the keys as non-extractable `CryptoKey`s that live in the tab; *Remember on this device*
keeps those non-extractable keys in IndexedDB until logout. Changing the passphrase or resetting it with the code
re-wraps the same bundle. Removing the keys deletes the person's encrypted notes and switches their encrypted DMs off.
**Passphrase and recovery code lost = the encrypted content is lost**; nobody, not even an admin, can restore it.

**What is encrypted with what.**

| Content | Key | AAD | Who reads it |
|---|---|---|---|
| Task note (`task_enc_notes.body` = `{v, iv, ct}`) | content key | `kalmido-note:v1:<task_id>:<user_id>` | only its author |
| Locked task note, 2.48.0 (`task_note_locks.body` = `{v, iv, ct}`, `tasks.content` empty) | content key | `kalmido-locknote:v1:<task_id>:<user_id>` | only the person who locked it |
| Task file (`attachments.enc = 1`, blob `KENC` 0x01, IV, ciphertext of header length + `{name, type, size}` + bytes) | content key | `kalmido-file:v1:<task_id>:<user_id>` | only its uploader |
| Direct message in an encrypted DM (`tchat_msgs.enc` = `{v, iv, ct}`, `body` empty) | AES-256-GCM from HKDF-SHA256(ECDH(own private, other public), salt = room id, info `kalmido-dm:v1`) | `kalmido-dm:v1:<room_id>:<sender_id>` | the two people of the DM |

Every nonce is random (12 bytes). The formats carry a version (`v: 1`, `KENC` 0x01) for later changes.

**What the rest of the app sees.** Task outputs carry only `encrypted_note: true` (+ `encrypted_note_mine` for the
author in the app); encrypted files are listed as such with a neutral name, never previewed, never text-extracted,
never served to agents or to anyone but the uploader. Encrypted DMs: the server refuses plain text in them (and
ciphertext in plain rooms), pushes say only "New message from …", search and *Save as task* skip them, edits are new
ciphertext. A DM is switched by either person, only when both have keys; the switch leaves a notice in the
conversation. Both sides can compare a safety number (SHA-256 over both public keys, 8 groups of 5 digits); the own
public key in it comes from the unlocked key bundle, never from the server. If the server's copy of the own public key
differs from the bundle, the app warns and refuses to encrypt DMs (changing the passphrase stores the right key again).
When the other person's key changes, the conversation says so. The browser remembers that a DM was encrypted: if the
server later reports it as plain without a "switched off" notice in the conversation, a warning shows and plain text is
sent only after a confirmation. Replacing or removing one's keys asks for the account password.

**Limits.** This protects against the server operator, a reader of the database and the backups. A web app cannot
protect against a changed script delivered by the server itself. Encrypted DMs have no forward secrecy (a static key
pair per person): whoever gets the keys later can read older messages too. A task copy does not take the note along.

### Lock per list (2.64.1, server side)

A list with the lock (`lists.e2e` = `encrypting` | `on` | `decrypting`) keeps its texts as ciphertexts in the usual columns:
`"e2e1:" + {"v": 1, "g": <generation>, "iv", "ct"}` in `tasks.title / content / url`, `tasks.snippets` (as one JSON string),
`comments.body`, `notes.title / body`, `sections.name` and text values of custom fields (other field types stay readable).
The browser encrypts with a random list key per generation (AES-256-GCM, AAD `kalmido-list:v1:<list>:<gen>:<field>`, texts
padded to 64-byte steps) and wraps that key for every member with ECDH between the two people's key pairs
(`list_keys`: wrapped key, who wrapped it, the wrapper's public key as the server knows it). The server checks shapes only.

- **Switching on**: owner or list admin with their own keys; nothing may block (an agent in the list, a public link,
  "Everyone in the organisation", the role participant directly / via a group / via a folder share, locked notes, notepads
  with text). `start` stores one wrapped key per person with encryption set up; the others wait on `list_key_pending`.
  `todo` / `bulk` (at most 200 values a call, no history, one live update) rewrite every text incl. the trash; `finish`
  turns the lock on once nothing plain is left and removes copies of the texts elsewhere. The way back (`stop`) is the
  owner's, with the account password, and runs the same way the other direction; at its end the keys are deleted.
- **Writing**: `le2e_guard` lets only people in the web app write ciphertexts of a known generation into a list with the
  lock (plain text: 409 `list_e2e`; agents and API tokens: 403); during a switch texts wait (409 `list_e2e_busy`);
  ciphertexts never go into an open list (400). Moving a task (with its subtasks, comments and text fields) or a note into
  or out of such a list needs the texts re-encrypted by the browser in the same request (`le2e_move`), else 409
  `list_e2e_move`. Notepads and the note of "Waiting on external" are not encrypted and therefore not available there.
- **Members**: the database trigger `list_e2e_members` puts every new member without a key on the waiting list (also from
  groups and folder shares), drops the keys of a member who leaves and marks the rotation as pending (`e2e_rotate`; the
  rotation itself comes later), and refuses agents and participants (the app answers before with a clear text). Owners and
  list admins hand out keys from the waiting list (`/e2e/keys`, the server stores the wrapper's public key itself and tells
  the recipient). A new owner must hold the key.

- **Other ways** (`collab/liste2eguard.py`): agents can never be members (share-all, automatic sharing, folder agents, tidy
  and proposals skip such lists); the REST API / MCP refuse writes that touch such a list and answer with empty texts plus
  `encrypted: true`; CalDAV / iCal show "🔒 Task" with dates and reminders and ignore text changes; the list's mail address
  is switched off; templates from or into it, imports, forms and the shopping memory refuse or skip it; pushes, mail
  digests, briefing, report, news and webhooks carry no texts of it; server search skips it. Switching on removes the
  plain copies the server kept elsewhere (history texts, time entry title snapshots, news and queued webhook / agent
  event payloads, shopping memory, proposals, an agent's chat answers and step texts about the list's tasks). Kept on
  purpose: the person's own chat messages to an agent (their own words), the note of a time entry (`time_entries.note`)
  and the ids of people mentioned in a comment (metadata for the notification). Imports keep only ids and counts,
  the webhook log never bodies. Lists of the Family and Household & Life modules (and lists a contact sync
  writes birthdays into) cannot be locked.

### Lock per list (2.64.1, browser side)

`static/js/liste2e.js` (data layer) and `liste2eui.js` (dialogs and display), built on `e2e.js`:
- **Keys.** The list keys are unwrapped with the person's private key into non-extractable `CryptoKey`s that live only in
  the tab. For a key the browser wrapped itself the own public key comes from the unlocked bundle, never from the server;
  for keys wrapped by others, and before wrapping for a member, the member's public key is compared with the one this
  browser saw before (trust on first use, as in encrypted DMs): a changed key is shown as a warning and not used until
  the person confirms it. Every member has a safety number (SHA-256 over both public keys) to compare in person.
- **In and out.** Every answer passes one hook: ciphertexts go to `o._enc`, the fields hold the plain text (or stay empty
  with a lock placeholder until decrypted in the background). Every write of a text of such a list is encrypted in
  `api()` before the offline outbox and the network; moving a task in or out carries its texts, subtasks, comments and
  text fields in the target format (`le2e_move`, also for drag and drop and undo).
- **Device storage.** What goes to `localStorage` (state cache, outbox, conflicts, other windows) holds only ciphertext;
  plain text exists only in memory and is wiped (with the undo steps of such lists) when the encryption is locked or on
  logout. The list keys are not stored on the device: offline, a locked list stays unreadable until the next unlock.
- **Switching** runs in the browser of the owner / list admin with a progress bar (`le2eStart`, `le2eStop`, resumable).
  On the way back, texts no key of this browser opens (a broken or foreign ciphertext) are listed; the owner can take them
  over as empty texts, otherwise the list stays locked. A text a person types that merely begins with `e2e1:` is a text
  (encrypted in a locked list; refused with a clear message in an open one).
- **Search** for such lists runs over the decrypted texts in memory (search page, command palette, message search).

**Limits.** No protection against a changed script delivered by the server itself (a web app loads its code from the
server), against members who saw the texts, or against metadata (who writes when and how much, dates, assignees, text
lengths in steps of 64 bytes). The AAD binds list, generation and field but no task id: the server can copy a ciphertext
inside a list (repeating tasks) and could therefore swap two of the same field (integrity, not confidentiality); a task
title and a note title, or a comment and a note text, can be swapped the same way (the browser tries both field names).
Trust on first use: on every device the first public key seen for a member counts unchecked until the safety numbers
are compared; a server that hands out a forged key (or a forged list key wrapped with it) before that comparison is not
noticed by the key check. The browser then counts texts that do not open with the list key it holds and says so
("compare the safety numbers") instead of leaving silent placeholders. A member
who leaves keeps what they saw; since 2.64.2 the list key changes and the older ciphertexts are encrypted again (below). Exports keep the ciphertexts; they are readable again only in Kalmido with
a member's passphrase (`tools/kalmido_export_decrypt.py` says so). Going back to a version before 2.64.1 needs every
lock opened first.

### Lock per list, stage 2 (2.64.2): key change, files, list channel

- **Key change (rotation).** A member who held a key and leaves (also by leaving the organisation) marks the list
  (`e2e_rotate`). The next owner / list admin whose browser is unlocked creates a new list key, wraps it for every person
  who still holds one and sends it (`POST /api/lists/<id>/e2e/rotate` `{gen, keys}`; the generation moves up atomically, a
  second browser that was faster gets 409 `list_e2e_gen`; a person left out, e.g. because of an unconfirmed key change, goes
  on the waiting list). New texts use the new generation at once; `e2e_reenc` marks the background work: the same `todo` /
  `bulk` / `finish` steps as switching on re-encrypt texts, files and channel messages of older generations, resumable.
  Older generations stay with the members (backups, not yet re-encrypted rows); a person released later gets every
  generation. Until the re-encryption is done the member dialog keeps the honest hint. A waiting person without a key who
  leaves changes nothing. The automatic change does not wrap for a member key this device sees for the first time in the
  current page (trust on first use without a look at it); then the owner / admin uses *Change the key now*. A ciphertext of
  an older generation written after the run (a tab that was not reloaded) makes the re-encryption due again. Texts that no
  key held opens stop the run with a message; by hand they can be taken over as empty. Limits: the re-encryption by an
  admin writes no history entry (an admin could replace texts unnoticed, as the server could); one call wraps for at most
  200 people.
- **Files** (`collab/liste2efile.py`). In a list with the lock attachments of tasks and comments are encrypted with the list
  key: `KENC\x02 | gen | iv | AES-GCM(list key, AAD kalmido-lfile:v1:<list>:<gen>, header {name, type, size} + bytes)`,
  `attachments.enc = 2`, the file name as a list ciphertext. Every other way to add a file there is refused; downloads go
  to people in the web app only (agents and API tokens 404), no text extract, no preview. Switching on, the key change and
  the way back convert existing files in the browser; files encrypted per person (2.42) are converted when their uploader
  runs the switch, else they stay readable for that person only. A task with list files cannot move to another list
  (409 `list_e2e_files`); project files cannot be added to such a list.
- **List channel** (`collab/liste2echan.py`). Messages in the team chat of such a list are `tchat_msgs.enc = {v, g, iv, ct}`
  with the list key (AAD `kalmido-chan:v1:<room>:<gen>:<sender>`, padded like the texts); plain text is refused, the browser
  names @mentioned members for their push. Agents and API tokens read no text (`encrypted: true`) and cannot write;
  search and "save as task" skip it. Re-encryption by an admin keeps the original sender in the AAD.
- **Pushes** of such lists use the neutral word in the recipient's language; a comment push names the list, not the words.
- **Safety numbers** of all members are reachable from the head of the list channel and of the attachments.
- **Lock per knowledge space** (2.64.3, `wiki/wikie2e.py`). A whole space ("Private" or an organisation) can be encrypted:
  `wiki_pages.path` and `.body` hold `e2e1:` ciphertexts with the space key (AAD `kalmido-wiki:v1:<space_id>:<g>:path|body`),
  wrapped per member in `wiki_keys` (salt `wiki:<space_id>:<gen>`, info `kalmido-wikikey:v1`); `wiki_spaces` holds mode,
  generation, rotation and re-encryption like the list columns. Managers: the owner of a private space, the admins of an
  organisation. Routes `/api/wiki/e2e` (info), `/start` (`prepare: true` first creates the row: its id is in salt and AAD),
  `/todo`, `/bulk`, `/finish`, `/stop` (password), `/keys` (release to members who joined; News `wiki_e2e_key`), `/rotate`.
  The page routes call `wke_guard`: in such a space only ciphertexts from a person in the web app, no template copy, no
  `wiki_links` / frontmatter on the server; move, export and import answer 409 `wiki_e2e` (the browser does them); search and
  mentions leave such spaces out; `GET /api/wiki?bodies=1` hands the ciphertexts to the local search. Members who join the
  organisation wait for their key (trigger `wiki_e2e_members`; the waiting list is also computed from the members); a key
  holder who leaves marks the rotation. The organisation export keeps the ciphertexts (`client_encrypted.locked_wiki_pages`).
