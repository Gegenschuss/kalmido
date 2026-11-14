# Glossary of module and function names

Kalmido's file and function names are short on purpose, and some are cryptic until you know the idea behind them. This page
says in one line what each Python module under `kalmido/` and each script under `static/js/` is for, and what the
function prefixes mean. The text of each line comes from the module's own header comment, so when in doubt the header
is the longer answer. The big picture is in [ARCHITECTURE.md](ARCHITECTURE.md).

`tools/check_glossar.py` (a step of the Lint job) fails when a module or script has no line here, so a new file
needs its line in the same pull request. Rule: every `kalmido/**/*.py` file except `__init__.py` and the
one-per-task migration fragments in `kalmido/core/migrations.d/`, and every `static/js/*.js` file, appears below as
`` `path` `` at the start of a list item.

## How to read the names

- **Prefix = module.** Most modules give their functions, classes and global names a short prefix of their own
  (for example `hub/hmv1.py` and `hmv_...`, `office/oftref.py` and `oft_...`). The prefix is shown in brackets after the
  module name, taken from what the file really uses; modules that only hold a few unrelated helpers have none.
  A JavaScript script shares the global scope with all others, so its prefix is what keeps names apart
  (a name outside the prefix is rare). Look a function up by its prefix:
  `grep -n "^def ofd_" -r kalmido/` or the same on `static/js/`.
- **`e2e`** = end-to-end encryption in the browser: the key never leaves the browser, the server stores ciphertext.
  `kalmido/collab/e2e.py` with `static/js/e2e.js` are the basis; `liste2e*` (a list) and `wikie2e` (a knowledge space)
  are the "locks" built on it. Not to be confused with `orgcrypt` (server-side keys per organisation) - the server can
  read those.
- **`v1`** = the REST API version 1 (and MCP) of the module: `files/v1.py` is the file store for agents and scripts.
- **`web.py`** = the module's routes for the app itself; **`model.py`** = its data helpers.
- **A number at the end** (`sheetprop`, `propkinds2`, `sprints2`) is a second file of the same topic that was split
  off to keep files small, not a second version.
- **`*prop`** (`asstprop`, `dupprop`, `lyprop`, ...) = an agent *proposal* kind: an agent suggests, the person decides.
- **`gdpdudtd`** = the GDPdU / GoBD DTD (data carrier handover to the tax auditor), shipped as a module.
- **`oftref`**, **`docref`** = the "reference kinds" of the folder system: an office object filed into a folder.
- Migrations: new tables and columns only as fragments `kalmido/core/migrations.d/<task>_<x>.py`; they are not listed here.


## Python modules (`kalmido/`)

### `kalmido/accounts/`

People and organisations: sign-in, sessions, workspaces, roles, invitations, per-person settings and layouts.

- `kalmido/accounts/bgjobs.py` (`bgj`) - The short background work a request starts (mails right after an action, "Back up now", the organisation keys' passes after a move)
- `kalmido/accounts/colors.py` (`ac`) - A fixed colour per account (agents and people)
- `kalmido/accounts/colwidths.py` - The column widths of the lists, per person on every device (setting col_widths)
- `kalmido/accounts/discover.py` (`disc`) - Finding people by e-mail like in a messenger
- `kalmido/accounts/invite.py` (`invite`) - Invitations and reset links a one-time link by e-mail with which a person sets their own password
- `kalmido/accounts/layouts.py` (`wg`) - Views built from blocks ("Customize")
- `kalmido/accounts/layouts_more.py` - The blocks of the views that came to the builder late (statistics, client card, family)
- `kalmido/accounts/layoutsets.py` (`lyv`) - Several saved arrangements per view and person (table view_layouts)
- `kalmido/accounts/login.py` (`auth`) - Password login, first setup, logout and two-factor authentication (TOTP, recovery codes, passkeys)
- `kalmido/accounts/mailtok.py` (`mtk`) - The secret tokens of the plus addresses (mail_tokens, hub_tokens, doc_mail)
- `kalmido/accounts/modcards.py` (`mc`) - Own module cards (Settings > Modules)
- `kalmido/accounts/navmenus.py` (`nav`) - The menus of the areas, arranged by each person
- `kalmido/accounts/oidc.py` (`oidc`) - Login with a generic OpenID Connect provider (authorization code flow with PKCE)
- `kalmido/accounts/onboarding.py` (`sample`) - Onboarding, the sample project and the app
- `kalmido/accounts/orgback.py` (`olb`) - Leaving an organisation (or being removed)
- `kalmido/accounts/orginvite.py` (`ojn`) - An organisation's admins invite people by e-mail
- `kalmido/accounts/orgleave.py` (`olv`) - What leaving or deleting an organisation means for its members
- `kalmido/accounts/orglists.py` (`ole`) - Organisation admins manage the lists of their organisation (in the workspace settings)
- `kalmido/accounts/orgout.py` (`oo`) - Data of an organisation leaves it (into the private space or another organisation)
- `kalmido/accounts/orgoutreq.py` (`oor`) - The way back out of an organisation for a member (decided the member asks, an admin releases it with one click; nothing goes back silently)
- `kalmido/accounts/orgretain.py` (`odl`) - What an organisation (or a person's personal office)
- `kalmido/accounts/orgroles.py` (`org`) - Organisation roles beyond member / admin
- `kalmido/accounts/orgs.py` (`org`) - Organisations and workspaces
- `kalmido/accounts/orgtasks.py` - An organisation admin
- `kalmido/accounts/pictures.py` (`list`) - Profile pictures and list icons (presets or own images, re-encoded, served with login)
- `kalmido/accounts/pwreset.py` (`pw`) - "Forgot your password?" on the login page
- `kalmido/accounts/secmail.py` (`sec`) - Security mails to the person whose account changed - so a taken-over account does not stay unnoticed
- `kalmido/accounts/servers.py` (`msv`) - Several Kalmido servers in one app (stage 1, no sync, no federation)
- `kalmido/accounts/session.py` (`rate`) - Who is asking: sessions, the proxy login, trusted proxies, the maintenance gate, login rate limits
- `kalmido/accounts/sessions.py` (`ses`) - Active sessions -- Settings > Account > Active sessions
- `kalmido/accounts/settings.py` (`push`) - Per-user settings, the data export and Web Push subscriptions
- `kalmido/accounts/setupcode.py` (`sh`) - One-time code for the first setup
- `kalmido/accounts/sharedefs.py` (`sd`) - The sharing defaults of a workspace
- `kalmido/accounts/setundo.py` (`su`) - Undo across devices, stage 6 rest -- a person's settings in the core's step groups (core/undoareas.py)
- `kalmido/accounts/sideviews.py` - Saved views of the sidebar ("On the road", "Planning")
- `kalmido/accounts/signup.py` (`signup`) - Self-registration on the login page and sign-in links / QR codes for family members without e-mail
- `kalmido/accounts/spacemove.py` (`smv`) - The shared rules for moving data between the private space and an organisation (both ways)
- `kalmido/accounts/supportgrant.py` (`sga`) - Support access only with the client
- `kalmido/accounts/tenancy.py` (`boundary`) - The boundary between workspaces beyond lists
- `kalmido/accounts/useradmin.py` (`ua8`) - The admin user management for hundreds of accounts
- `kalmido/accounts/users.py` (`user`) - Users and the own account (admin user management, passwords, deletion)
- `kalmido/accounts/whatsnew.py` (`wn`) - "New for you" -- after an update every person sees once the sentences written for users of the versions since the version they saw last
- `kalmido/accounts/wsareas.py` (`wsa`) - Areas switched on and off per workspace

### `kalmido/admin/`

Operator tools: backup, export / import of accounts and organisations, retention, hosting and the worker.

- `kalmido/admin/acctexport.py` (`umz`) - Account export -- everything of one person as ONE file
- `kalmido/admin/acctimport.py` (`umz`) - Account import -- takes over a file of the account export (admin/acctexport.py)
- `kalmido/admin/backup.py` (`bk`) - Backups and restore (admins)
- `kalmido/admin/bkstore.py` (`refs`) - The shared file store of the backups
- `kalmido/admin/clientip.py` (`ip`) - Does the client's real address reach Kalmido? Behind a reverse proxy in Docker with published ports (docker-proxy)
- `kalmido/admin/dataretention.py` (`orf`) - The daily clean-up of old logs and expired credentials, and the weekly orphan-file sweep (no routes; the watchdog starts both, see notify/push.py watchdog_tick)
- `kalmido/admin/exportleft.py` - What stays out of the exports on purpose, with the reason
- `kalmido/admin/hosting.py` (`quota`) - Running Kalmido for others
- `kalmido/admin/offsite.py` (`bko`) - An off-site target for the backups (instance admins)
- `kalmido/admin/oi_office.py` (`p`) - Organisation import -- the clients and the office
- `kalmido/admin/oi_store.py` (`finish`) - Organisation import -- file store, documents, knowledge pages, tables and video sign-offs (admin/orgimport.py OiT)
- `kalmido/admin/oi_team.py` (`rule`) - Organisation import -- the tables of this area (admin/orgimport.py OiT)
- `kalmido/admin/oilock.py` (`oil`) - #4300: locked folders of the file store (files/fslock.py)
- `kalmido/admin/operator.py` (`operator`) - The hosting operator's interface
- `kalmido/admin/orgcrypt_cli.py` (`rot`) - The organisation keys' bulk work
- `kalmido/admin/orgexport.py` (`ox`) - Organisation export, stage 1
- `kalmido/admin/orgimport.py` (`oi`) - Organisation import, stage 2
- `kalmido/admin/purgeshare.py` (`ush`) - An account's deletion and what it shares privately
- `kalmido/admin/retexport.py` (`rx`) - The retention export before an account or an organisation is deleted
- `kalmido/admin/selfdelete.py` (`sdl`) - A person deletes their own account (GDPR Art. 17)
- `kalmido/admin/supporter.py` (`sup`) - The supporter licence (like Immich)
- `kalmido/admin/umz_more.py` (`umz`) - The account import takes over the rest of the person
- `kalmido/admin/umz_undoplan.py` (`undo`) - What the undo of an account import may still take back
- `kalmido/admin/wkimport.py` (`wki`) - The ZIP import of knowledge pages for large archives
- `kalmido/admin/worker.py` (`wrk`) - The server's capacity in numbers

### `kalmido/agents/`

Connected agents: the agent API, proposals, quotas, locks, schedules, chat and the server-run agent.

- `kalmido/agents/admin.py` (`agent`) - Agent administration and personal agents
- `kalmido/agents/agentpin.py` (`apin`) - Agents on the pin board of a project page + the weekly status of a project
- `kalmido/agents/agentrules.py` (`ar`) - The standing rules of an agent ("from now on always ...")
- `kalmido/agents/agenttime.py` (`atm`) - An agent checks time tracking and proposes entries from calendar events
- `kalmido/agents/agsees.py` (`ags`) - What an agent sees right now - the section "Sees now" of the dialog "Edit agent" (#5822)
- `kalmido/agents/api.py` (`v1`) - The REST API of an agent itself (token of an agent account)
- `kalmido/agents/apvdiff.py` (`apvd`) - What the Yes of an approval card changes in a text -- the lines it removes and the lines it adds
- `kalmido/agents/asstprop.py` (`ast`) - Texts drafted by a CONNECTED agent, on request of a person
- `kalmido/agents/ccsread.py` (`ccs`) - A connected agent reads a credit card statement (kind card_statement_read, a request of agents/asstprop.py)
- `kalmido/agents/chat.py` (`chat`) - What people see of agents: state, chat (files, reactions)
- `kalmido/agents/chatprefs.py` (`cp`) - The chat settings of a person for one agent
- `kalmido/agents/chatnews.py` (`acn`) - Approval cards and questions of the agent chat in the bell's "For you"
- `kalmido/agents/cleanup.py` (`cln`) - "Tidy up this list" -- the list
- `kalmido/agents/contractprop.py` (`ctr`) - Contracts in view -- an agent reminds a person of a notice deadline, the person decides
- `kalmido/agents/control.py` (`ctl`) - The control level of an agent (Kontrolle)
- `kalmido/agents/core.py` (`agent`) - Agents: accounts, event queue + long polling, runtime settings, permissions of people towards agents
- `kalmido/agents/datalock.py` (`dl`) - Data an agent may never see - the section "
- `kalmido/agents/dupprop.py` (`dup`) - Tidy up contacts -- an agent finds duplicates, the person merges them
- `kalmido/agents/gates.py` (`gate`) - Approval requests of coding agents WITHOUT a pull request, in two steps
- `kalmido/agents/ideaprop.py` (`idp`) - "Add ideas" on a branch of the mind map
- `kalmido/agents/importprop.py` (`aim`) - Old data into the office with the person
- `kalmido/agents/jobchat.py` (`jc`) - Talking to one job of an agent
- `kalmido/agents/lyprop.py` (`lyp`) - Agents propose how a view is arranged
- `kalmido/agents/mcpremote.py` (`mcpr`) - The hosted MCP access -- an MCP client (a chat app's connector, an editor)
- `kalmido/agents/meetprop.py` (`mtg`) - A meeting becomes tasks -- the guided flow of the proposal kind "
- `kalmido/agents/msgpop.py` - the in-app pop-up for new chat messages (static/js/msgpop.js)
- `kalmido/agents/objprop.py` (`objp`) - An agent's change of a core object as a PROPOSAL a person accepts (proposal kind 'obj_patch')
- `kalmido/agents/propkinds2.py` (`pk2`) - Two more kinds of agent proposals (see agents/proposals.py for the mechanism)
- `kalmido/agents/proposals.py` (`prop`) - Agent proposals, validation helpers, requests from people to agents
- `kalmido/agents/quota.py` (`quota`) - The usage ring -- how much of its plan
- `kalmido/agents/rcread.py` (`rcr`) - A connected agent reads a receipt (kind receipt_read, a request of agents/asstprop.py)
- `kalmido/agents/safety.py` (`agent`) - The server keeps an agent inside one circle of people
- `kalmido/agents/schedules.py` (`sched`) - Planned agent jobs -- "every Monday at 9
- `kalmido/agents/setup.py` (`ains`) - Set up an agent on a computer with one command
- `kalmido/agents/sheetprop.py` (`sht`) - Table rows -> tasks, proposed by an agent, applied by the person
- `kalmido/agents/srvagent.py` (`srv`) - The server agent ("Kalmido-KI")
- `kalmido/agents/srvagent_run.py` (`srv`) - The runs of a server agent (agents/srvagent.py)
- `kalmido/agents/srvstarter.py` (`srv`) - The setup of a server agent ("Kalmido AI")
- `kalmido/agents/srvteam.py` (`srv`) - The Kalmido AI (the server agent, agents/srvagent.py)
- `kalmido/agents/srvweb.py` (`srv`) - Read-only web research of the Kalmido AI (server agent, agents/srvagent*.py)
- `kalmido/agents/steps.py` (`steps`) - What an agent says between its tool calls, and what its host really runs with
- `kalmido/agents/taskdec.py` (`irr`) - The yes to a task marked irreversible, and the routes of a task decision
- `kalmido/agents/usage.py` (`usage`) - Model usage of agents, limits and the agents
- `kalmido/agents/waiting.py` - What waits for a person, over every workspace
- `kalmido/agents/watch.py` (`watch`) - The server's watchdog over agent jobs
- `kalmido/agents/workqueue.py` (`wq`) - The queue of an agent - the open tasks assigned or delegated to it that it may see, in the order it set last (agents.queue_order, a JSON list of task ids)
- `kalmido/agents/workstyle.py` (`ws`) - How an agent works and reports - the "

### `kalmido/api/`

The REST API v1: shared helpers, scopes (token rights) and the OpenAPI description.

- `kalmido/api/common.py` (`v1`) - The helpers of the /api/v1 routes (error format, view wrapper, body and argument checks, cursors, rate counter)
- `kalmido/api/helpdocs.py` (`hlp`) - The help for agents: the user documentation (docs/*.md) as search kind help, one section by its key, the overview (2.1067.0)
- `kalmido/api/helpuser.py` (`uh`) - The help for people in the app: the "How to" sections per area in the person's language, one section, the web side of search kind help (2.1086.0)
- `kalmido/api/openapi.py` - The OpenAPI 3.1 document of /api/v1 (served at /api/v1/openapi.json, built once)
- `kalmido/api/projects.py` (`v1`) - The project overview in the token API
- `kalmido/api/scopes.py` (`v1`) - Token scopes, approvals and the complete agent API (the routes the web client has)
- `kalmido/api/showme.py` (`shw`) - "Show me": the named places of the app an agent's chat message may point at (docs/help-targets.json) (2.1086.0)
- `kalmido/api/v1.py` (`v1`) - REST API /api/v1 with personal access tokens
- `kalmido/api/v1setup.py` (`v1s`) - Setting up integrations through the REST API

### `kalmido/assistant/`

The built-in assistant.

- `kalmido/assistant/core.py` (`asst`) - The built-in assistant -- configuration, the model call, the prompts and what goes into them
- `kalmido/assistant/web.py` (`asst`) - The routes of the built-in assistant (assistant/core.py explains the rules; docs/API.md "Built-in assistant")

### `kalmido/calendars/`

CalDAV, iCal feeds, appointment booking and polls.

- `kalmido/calendars/apptbook.py` (`apb`) - Appointment booking by customers ("Booking page")
- `kalmido/calendars/apptundo.py` - Undo across devices for the booking page's appointment types (change, delete, restore as steps of the core's step groups)
- `kalmido/calendars/caldav.py` (`dav`) - CalDAV server for tasks (VTODO)
- `kalmido/calendars/davwrite.py` (`cdw`) - Writing events into CalDAV subscriptions (new, change, delete)
- `kalmido/calendars/icalfeed.py` (`ics`) - The subscribable ICS calendar feed of a user
- `kalmido/calendars/polls.py` (`tpo`) - Scheduling polls -- several proposed times, people vote through a public link (yes / maybe / no)
- `kalmido/calendars/pollsv1.py` (`v1`) - Scheduling polls over REST v1 (+ MCP)
- `kalmido/calendars/pollundo.py` - Undo across devices for scheduling polls (dialog changes, link switch, trash and restore as steps)
- `kalmido/calendars/subscriptions.py` (`cal`) - External calendars (read-only subscriptions)

### `kalmido/collab/`

News, comments, the team chat and the browser encryption ("e2e") of lists and chat.

- `kalmido/collab/cchoice.py` (`lv`) - Answer buttons, approval cards and suggestions in task comments, like in the agent chat
- `kalmido/collab/chatpins.py` (`cpin`) - Pinned chat messages (team chat and agent chat)
- `kalmido/collab/chatsave.py` (`chat`) - Save a chat message as a task to look at later
- `kalmido/collab/cmttrash.py` (`tcx`) - The trash of comments and team chat messages
- `kalmido/collab/comments.py` (`comment`) - Comments, mentions, the activity timeline and collaboration pushes
- `kalmido/collab/duebell.py` (`due`) - The bell's deadline lines (due today / overdue) and their "seen for today"
- `kalmido/collab/e2e.py` (`e2e`) - "e2e" = end-to-end encryption in the browser: the server stores only ciphertext and never sees the key (basis of the locks below)
- `kalmido/collab/e2eresv.py` (`e2r`) - Id reservations for records encrypted in the browser
- `kalmido/collab/integfail.py` - An integration stopped working
- `kalmido/collab/liste2e.py` (`le2a`) - The lock per list -- texts of a list encrypted in the browser (stage 1 of the browser encryption)
- `kalmido/collab/liste2echan.py` (`le2c`) - The list channel (team chat room kind 'list')
- `kalmido/collab/liste2efile.py` (`le2f`) - Files of lists with the lock, encrypted in the browser with the list key
- `kalmido/collab/liste2eguard.py` (`le2b`) - The lock per list -- the other ways out of the server (findings H2, M4, M5, M7, L6)
- `kalmido/collab/msgsearch.py` (`msg`) - Search in conversations -- task comments, team chat (channels + direct messages)
- `kalmido/collab/news.py` (`news`) - The News feed and the notification settings (matrix + list bells)
- `kalmido/collab/notelock.py` (`ln`) - Lock the note of a task with one
- `kalmido/collab/notes.py` (`note`) - Notes of a list / project
- `kalmido/collab/reactions.py` (`ltag`) - Reactions on comments, tidy suggestions and shared list tags
- `kalmido/collab/recent.py` - "Recently edited" over Knowledge, Files and Reading: one read-only route GET /api/recent for the overview and the start page block
- `kalmido/collab/replies.py` (`reply`) - Replies to one message -- task comments, team chat and agent chat
- `kalmido/collab/tcxcore.py` (`tcx`) - The shared core, stage 5 -- the team chat
- `kalmido/collab/teamchan.py` (`tcx`) - Team chat channels anyone may open, group conversations of three or more people, files in team chat messages
- `kalmido/collab/teamchat.py` (`tchat`) - Team chat (rooms and direct messages)

### `kalmido/contacts/`

Contacts and address books (CardDAV, merge, history).

- `kalmido/contacts/bulk.py` (`ms`) - Contacts: several at once. One request deletes or moves a selection of contacts (the web client's selection mode, /api/v1 + the MCP tool bulk_contacts)
- `kalmido/contacts/carddav.py` (`ab`) - CardDAV server: every address book a person sees as a collection of vCards (iOS / macOS Contacts, DAVx5, Thunderbird)
- `kalmido/contacts/ctfolder.py` (`ctf`) - Address books and contacts in folders
- `kalmido/contacts/ctkern.py` - Address books on the shared core, stage 3
- `kalmido/contacts/ctundo.py` - Undo across devices, stage 6 -- contacts in the core's step groups (core/undoareas.py)
- `kalmido/contacts/ctxlist.py` (`ctx`) - Contacts: the list's tools
- `kalmido/contacts/history.py` (`ctk`) - The history on a contact's card
- `kalmido/contacts/merge.py` (`ctm`) - Merging duplicate contacts by hand (reversible, core/merges.py)
- `kalmido/contacts/model.py` (`vc`) - Contacts (module "contacts")
- `kalmido/contacts/orgbooks.py` (`obk`) - Address books an organisation owns (books.owner_org_id)
- `kalmido/contacts/v1.py` (`v1`) - Contacts: the REST API v1 (+ MCP)
- `kalmido/contacts/web.py` (`op`) - Contacts: the web API (address books, sharing, contacts, search, vCard import / export, links to tasks)

### `kalmido/core/`

The foundation: database, schema, access layer, request context, conflicts (409), i18n, retention, encryption keys.

- `kalmido/core/access.py` (`acx`) - Access control: who sees / changes which list and task, module switches, list roles
- `kalmido/core/addrshare.py` (`ads`) - Open shares by e-mail address in the shared core: obj_addr_shares, redeemed when the account of the address signs in with it proved (projects, folders, knowledge pages)
- `kalmido/core/codemanifest.py` - Code integrity: the web manifest, the full SHA-256 of every file the browser gets (GET /api/code-manifest, tools/web_manifest.py)
- `kalmido/core/colbool.py` - the old yes / no columns as BOOLEAN instead of BIGINT / INTEGER 0/1
- `kalmido/core/coltime.py` - the other old time columns (*_at / *_on / *_until) onto TIMESTAMPTZ / DATE, area by area
- `kalmido/core/coltype.py` - the old time columns created_at / updated_at / deleted_at as TIMESTAMPTZ instead of ISO text
- `kalmido/core/compress.py` - JSON answers of the app go out gzip-compressed when the browser accepts it (GET /api/state with many tasks: a few MB of JSON shrink to a few hundred KB)
- `kalmido/core/config.py` - Configuration from the environment, the outbound-HTTP guard, proxy and login settings, the Flask app object
- `kalmido/core/conflict.py` - The version check of the dialogs that save a whole object (client, master data, letter, budget, journal)
- `kalmido/core/csvimport.py` (`csv`) - The one reader of bank statements
- `kalmido/core/ctx.py` - The request context of the signed-in person
- `kalmido/core/db.py` (`skfp`) - Time helpers, the database connection, start-up checks and migrations (init_db, repair_data)
- `kalmido/core/mdedit.py` - Change a Markdown text in a targeted way: append (at the end or under a heading) and replace the section below a heading; shared by knowledge pages, task notes and project descriptions (#5830)
- `kalmido/core/dlock.py` (`dl`) - THE check "data an agent may never see"
- `kalmido/core/env.py` (`env`) - The registry of the environment variables the server reads (name, default, one English sentence, group)
- `kalmido/core/ephem.py` (`eph`) - Short-lived state in the database, so every web process of an instance sees it (later KALMIDO_WEB_PROCS, KALMIDO_REPLICAS, the roles of 2.102)
- `kalmido/core/errors.py` - The error types and input checks every package uses
- `kalmido/core/filters.py` (`kflt`) - The filter of the shared core on the server: rules {op, conds} of an area's catalog -> one SQL condition or a match (2.846.0, #5520)
- `kalmido/core/fkeys.py` (`fk`) - Foreign keys for references that had none (GDPR art. 17: no reference to a deleted person / object)
- `kalmido/core/i18n.py` - Server-side translations (tr / trn / N_)
- `kalmido/core/i18nkeys.py` (`key`) - The translation keys of the code and their split per module loaded on demand
- `kalmido/core/i18nparts.py` (`i18np`) - The web client's texts per module
- `kalmido/core/idem.py` (`idem`) - Idempotency keys of write requests (header Idempotency-Key)
- `kalmido/core/instance.py` (`update`) - Version, update check and instance settings (admins)
- `kalmido/core/ipallow.py` - The optional address rule of a key
- `kalmido/core/jsonlimit.py` - The size limit of JSON request bodies
- `kalmido/core/kernretire.py` - Stage 7 of the shared core: the start check and DROP of an area's old member table once the core alone decides (2.924.0, #5069)
- `kalmido/core/mailframe.py` - The one HTML frame of every Kalmido mail (invitation, findability, appointment booking, portal, event invitation, security, notification and daily mails)
- `kalmido/core/merges.py` (`mg`) - Merging duplicate records by hand (contacts: contacts/merge.py, clients: team/clientmerge.py)
- `kalmido/core/moneycol.py` - Moves the plain office money columns from TEXT to NUMERIC(14,2) at start when every value fits, and reads them back as two-place text
- `kalmido/core/mt940.py` - SWIFT MT940 / MT942 statements (the German bank dialects: Sparkasse, Volksbank, Deutsche Bank, Commerzbank ...)
- `kalmido/core/numtext.py` - ONE reader for numbers typed by people - the same rules as parseNum in static/js/core.js
- `kalmido/core/objects.py` (`obj`) - The shared core, stage 1 -- ONE register of object kinds and ONE role function for every new area (docs/dev/kern.md "So baut man einen neuen Bereich")
- `kalmido/core/objfollow.py` (`ofl`) - Following exists once, in the shared core: one table obj_follow for the watchers and the bell of a task (stage Q9a) and the bell of a project (stage Q9b)
- `kalmido/core/objnotifcap.py` (`ncap`) - The owner's notification ceilings of projects and folders in the shared core: one table obj_notif_cap; list_notif and folder_notif moved here and went (stage Q9b)
- `kalmido/core/objhooks.py` (`obj`) - The two things of the shared core that the layer accounts needs, without importing upward
- `kalmido/core/objcmtweb.py` (`ocw`) - The generic routes of the comments' core (/api/obj/<kind>/<id>/comments, /api/obj/comments/<cid>; 2.981.0)
- `kalmido/core/objlinks.py` (`olnk`) - Links exist once, in the shared core: one table obj_links (src / dst kind and id, rel) with the E2E lock, "target deleted", undo of a removal and the area relations (2.1076.0)
- `kalmido/core/objlinkweb.py` (`olw`) - The generic routes of the links' core (/api/obj/<kind>/<id>/links, /api/obj/links/<lid>, API v1 /agent/objects/<kind>/<id>/links; 2.1076.0)
- `kalmido/core/objcomments.py` (`ocm`) - Comments exist once, in the shared core: one table obj_comments (kind, ref_id) with its trash obj_comment_trash, one mention parser, one say rule, one delete rule (stage Q4a)
- `kalmido/core/objexport.py` - the export register of the core
- `kalmido/core/objsearch.py` (`osr`) - The search index exists once, in the shared core: one table obj_search (kind, ref_id, tsv over kalmido_fold) for tasks, comments, notes, contacts, page names and messages, filled by triggers; rights per hit in the areas (stage Q6a)
- `kalmido/core/objwords.py` (`osw`) - The keyed word index of the sealed texts exists once, in the shared core: one table obj_search_words (kind, ref_id, HMAC prefix hash per workspace) for documents, recognised file texts, knowledge pages and filed mails; rights per hit in the areas (stage Q6b)
- `kalmido/core/srchreg.py` (`srch`) - The search exists once: one registry of the areas' searches (each area registers its kind) and one route per side, GET /api/search?kind= and GET /api/v1/search?kind=; the command palette's "Everywhere" finds what each area search finds (stage Q6c)
- `kalmido/core/objlight.py` (`obj`) - The light kinds of the shared core (task, event, hub_mail, client): kind and role only, no node, no shares, no write path
- `kalmido/core/objnotify.py` (`obj`) - The one send decision of the shared core: every recipient of a News entry or push is cut with obj_role >= view first (stage Q2)
- `kalmido/core/objseen.py` (`osn`) - Read marks exist once, in the shared core: one table obj_seen (task: the highest comment id a person has seen); task_seen moved here and went (stage Q8a); the team chat's rooms / threads and the read feed articles too (stage Q8b)
- `kalmido/core/objparts.py` (`part`) - The shared core, stage 6b -- the side objects of a project on the core
- `kalmido/core/objreact.py` (`orx`) - Reactions exist once, in the shared core: one table obj_reactions for comments, team chat and the agent chat
- `kalmido/core/objretype.py` - the core's own tables obj_history, obj_undo and obj_revoked (core/migrations.d/4709_a.py, docs/dev/kern.md "history / undo / revoked") ta...
- `kalmido/core/objtags.py` (`otg`) - Tags exist once, in the shared core: obj_tags (scope user / list / org / ws) and obj_tag_links; project tags and organisation labels since 2.947
- `kalmido/core/objversions.py` (`obj_version`) - Versions exist once, in the shared core: one table obj_versions for numbered whole states (knowledge pages since 2.958, stage Q7a)
- `kalmido/core/objweb.py` (`obj`) - The generic routes of the core objects (core/objects.py, core/writes.py)
- `kalmido/core/orgcrypt.py` (`oc`) - Server-side keys per organisation
- `kalmido/core/orgrows.py` (`orw`) - The organisation of tasks, comments, events and contacts (column org_id, migrations.d/4602_a.py)
- `kalmido/core/pages.py` (`st`) - HTML pages, security headers, /api/version, the share target, quick capture and /drop
- `kalmido/core/pg.py` (`pool`) - The Postgres driver layer. The only module that imports psycopg
- `kalmido/core/pgbus.py` (`bus`) - Signals between the processes of one instance over Postgres
- `kalmido/core/ratedb.py` (`rate`) - 2.306.0 D1 the rate limits that guard rare, sensitive actions
- `kalmido/core/reqtime.py` (`rt`) - Measuring instead of guessing
- `kalmido/core/retention.py` (`ret`) - Deletion periods and the switch of the retention runs
- `kalmido/core/rls.py` (`enter`) - Row-level security, stage 1
- `kalmido/core/schema.py` - Database schema, migrations, indexes and the default settings (user + instance)
- `kalmido/core/serializers.py` - JSON shapes of database rows (tasks, lists, users ...)
- `kalmido/core/state.py` (`st`) - GET /api/state: everything the web client loads at start and after a change
- `kalmido/core/stmtfiles.py` (`stmt`) - The uploaded statements of one request
- `kalmido/core/strip.py` (`strip`) - The client's JavaScript and CSS go out without comments (the files in the repo keep them: they are the documentation)
- `kalmido/core/tokenhash.py` (`tkh`) - The personal upload token (POST /drop)
- `kalmido/core/tplmove.py` (`tpm`) - Templates onto the shared core at the start: owner_id, real types, section templates moved into templates (#5288)
- `kalmido/core/undoareas.py` - Undo across devices, stage 6 -- what the areas outside the office share to record and take back their steps
- `kalmido/core/undodiff.py` (`undo`) - Undo across devices, stage 3 -- diff parts of the step groups: an area keeps only what a step changed and takes it back through its own write path
- `kalmido/core/undogroups.py` (`ug`) - Undo across devices, stage 1 -- the core's undo steps grouped per account (table undo_groups)
- `kalmido/core/undoweb.py` (`undo`) - Undo across devices -- a person's step groups listed and taken back (/api/undo)
- `kalmido/core/usertz.py` (`tz`) - A person's own clock. The setting "
- `kalmido/core/writes.py` (`obj`) - The shared core, stage 1 -- ONE write path for core objects (core/objects.py, docs/dev/kern.md)
- `kalmido/core/zipread.py` - The one in-memory ZIP reader of the importers

### `kalmido/docs/`

Documents: upload and ingest, recognition, classification, fields, search, folders and flows.

- `kalmido/docs/area.py` (`ar`) - The office and the private file store apart
- `kalmido/docs/areamove.py` (`amv`) - The old receipts of the private file store into the office
- `kalmido/docs/batch.py` (`dsr`) - The chosen documents at once
- `kalmido/docs/classify.py` - A small, locally learning classifier for documents ("learns from your documents")
- `kalmido/docs/csvx.py` - The documents list as a CSV (";" and decimal comma in German, UTF-8 with BOM, like the other table exports)
- `kalmido/docs/dfilter.py` (`dvf`) - The filter of the saved views of the documents on the shared core's filter (each condition from the search's own pieces)
- `kalmido/docs/dsearch.py` (`dsr`) - The documents search, combinable like an archive
- `kalmido/docs/dups.py` (`dup`) - Duplicates of documents (receipts above all: the same invoice by mail and as a photo, a PDF uploaded twice -- otherwise both go into the DATEV batch)
- `kalmido/docs/dviews.py` (`dv`) - Saved views of the documents search
- `kalmido/docs/extract.py` (`ex`) - Date, due date and amount of a document from its text
- `kalmido/docs/fetcher.py` (`fx`) - Receipt fetchers -- a helper program on the person
- `kalmido/docs/fields.py` (`df`) - Custom fields of documents ("Eigene Felder")
- `kalmido/docs/flows.py` (`fl`) - Document flows ("Abläufe")
- `kalmido/docs/ingest.py` (`docs`) - Documents in -- docs_ingest and the background queue that recognises them
- `kalmido/docs/mailaddr.py` (`dmn`) - Named document addresses (doc_mail rows with an aid)
- `kalmido/docs/maillink.py` (`ml`) - Invoice mails without a PDF, only a link "
- `kalmido/docs/mailnamed.py` (`dmn`) - The settings routes of the named document addresses (docs/mailaddr.py)
- `kalmido/docs/notes.py` (`dn`) - Notes on a document
- `kalmido/docs/ocr.py` (`ocr`) - The text of a document and its preview image
- `kalmido/docs/pagesize.py` (`pg`) - The size of a document's first page, so the document view's preview stands where the full page will stand
- `kalmido/docs/pages.py` - Pages of a PDF document deleted, turned by 90 degrees or reordered, saved as a new version of its file
- `kalmido/docs/docmerge.py` (`dm`) - Several PDF documents merged into a new version of the first one, the others into the trash
- `kalmido/docs/dtags.py` - the move of the file store's tags (doc_tags / doc_node_tags) into the core (obj_tags scope ws, obj_tag_links kind fs_entry; core/objtags....
- `kalmido/docs/pdfopt.py` (`po`) - "Optimise PDF", the tools: a scan's pages measured, made black and white / grey / colour, a text layer (Tesseract)
- `kalmido/docs/pdfoptq.py` (`po`) - "Optimise PDF" as a new version of the file: routes, the queue step, "Optimise new scans automatically"
- `kalmido/docs/rcheck.py` (`rck`) - The fixed check of a receipt
- `kalmido/docs/recog.py` (`rc`) - Recognition per folder or file
- `kalmido/docs/rules.py` (`clean`) - Rules that sort documents ("contains word X -> sender Y, type Z, tag T, folder F")
- `kalmido/docs/scankeys.py` (`sk`) - Scan inboxes for the folder watcher
- `kalmido/docs/scanmark.py` - Is a document a scan? Decides whether the document view shows the archive number field for a document without a number
- `kalmido/docs/split.py` (`sp`) - A stack scan (one PDF of several letters)
- `kalmido/docs/store.py` (`doc`) - Documents -- the data side (no routes)
- `kalmido/docs/tasklink.py` (`dtl`) - A document linked with an EXISTING task (besides "Create task" of docs/web.py docs_task)
- `kalmido/docs/thumbfill.py` - Catch-up of the preview images of documents imported with their text (Paperless, ZIP import)
- `kalmido/docs/unpack.py` - The files inside a ZIP or a winmail.dat (Outlook's TNEF)
- `kalmido/docs/v1.py` (`v1`) - Documents for agents (API v1; scopes files:read / files:write of the file store)
- `kalmido/docs/web.py` (`docs`) - The routes of the documents area ("Dokumente", static/js/docs.js)

### `kalmido/events/`

Calendar events: model, invitations, free / busy, ICS and CalDAV routes.

- `kalmido/events/dav.py` (`ev`) - Events over CalDAV: every event calendar (and the person's invitations)
- `kalmido/events/evfeed.py` (`evf`) - A subscription link (ICS feed)
- `kalmido/events/evkern.py` (`ev`) - Calendars on the shared core, stage 3
- `kalmido/events/evundo.py` - Undo across devices, stage 6 -- calendar events in the core's step groups (core/undoareas.py)
- `kalmido/events/freebusy.py` (`efb`) - Free / busy of the people one invites, for the event editor
- `kalmido/events/ics.py` (`ics`) - Events as iCalendar (VEVENT)
- `kalmido/events/invite.py` (`evi`) - Invitations to an event by e-mail for attendees outside the server (iMIP, RFC 6047)
- `kalmido/events/model.py` (`ev`) - Events (module "events"): calendars, rights, validation, repeat expansion, attendees, reminders, the family migration
- `kalmido/events/v1.py` (`v1`) - Events: the REST API v1 (+ MCP)
- `kalmido/events/web.py` (`op`) - Events: the web API (calendars, sharing, events, single occurrences, replies, preparation tasks, export)

### `kalmido/family/`

Family / household: members, PIN and the family address book.

- `kalmido/family/carddav.py` (`family`) - Family: birthdays and anniversaries from CardDAV contacts
- `kalmido/family/family.py` (`shop`) - The module "Family": family fields of tasks, kid stars, occasions, shopping, packing lists, setup purpose, overview
- `kalmido/family/pin.py` (`pin`) - Family: the parents' PIN of a kid account
- `kalmido/family/v1.py` (`v1`) - Family: the weekly rotation and the REST API v1 (+ MCP)
- `kalmido/family/web.py` (`family`) - Family: the web API

### `kalmido/files/`

The file store ("Ablage"): folders, files, shares, locks, scan, tags, views and trash.

- `kalmido/files/bulk.py` (`abm`) - Actions on several nodes of the file store at once, the ZIP download and the phone scan
- `kalmido/files/extlinks.py` (`xl`) - External share links of the file store ("Ablage")
- `kalmido/files/filereq.py` (`frq`) - File requests ("Dateien anfordern")
- `kalmido/files/fskern.py` - File-store nodes on the one trash of the core (stage 3): registration, purge hook, receipts under legal retention stay locked
- `kalmido/files/fslock.py` (`fsl`) - Locked folders of the file store ("Ablage")
- `kalmido/files/fsmove.py` (`fsm`) - Files, folders (with everything in them)
- `kalmido/files/fsreceipts.py` - the point "Receipts" below the folder tree of the file store -- a list of references, no copies
- `kalmido/files/fsref.py` (`fs`) - Reference nodes -- an object of another area (an office document, a sheet ...)
- `kalmido/files/fsroots.py` (`fs`) - The root folder of an area in a workspace
- `kalmido/files/fsshnames.py` - The short list "Shared with Anna, Ben · agent X"
- `kalmido/files/fstags.py` (`dt`) - Tags in the file store ("Ablage")
- `kalmido/files/fsundo.py` - Undo across devices, stage 6 -- the file store's metadata and content versions in the core's step groups
- `kalmido/files/fsviews.py` (`fsv`) - The file store ("Ablage") shows only its own folders
- `kalmido/files/officeprev.py` (`dpv`) - The preview and the text of Word (.docx)
- `kalmido/files/photometa.py` (`pm`) - Photo metadata (GPS, camera)
- `kalmido/files/scan.py` (`sc`) - Virus scan of uploads (ClamAV clamd)
- `kalmido/files/store.py` (`fs`) - The file store ("Ablage") -- folders and files of a person (org_id NULL)
- `kalmido/files/textscan.py` (`ts`) - Text recognition for normal stored files in the background
- `kalmido/files/trashpurge.py` (`tp`) - The trash periods of the areas without one
- `kalmido/files/upsafe.py` (`h6d`) - The shared upload path. Every writer of uploaded bytes
- `kalmido/files/v1.py` (`v1`) - The file store in the REST API (agents and personal tokens; scopes files:read / files:write)
- `kalmido/files/web.py` (`files`) - The routes of the file store ("Ablage")

### `kalmido/hub/`

The mail hub: filed e-mails, mailboxes and rules, absences, holidays and dispatching.

- `kalmido/hub/abscal.py` (`abc`) - Public holidays and absences in the calendar views + the absences as a subscription link
- `kalmido/hub/absence.py` (`abs`) - Absences -- vacation, sick leave, days off, other
- `kalmido/hub/absundo.py` - Undo across devices for team absences (change, delete, restore; a holiday decision since makes the step a conflict)
- `kalmido/hub/agentdispo.py` (`adz`) - Shoot planning by an agent
- `kalmido/hub/callsheet.py` (`cs`) - The call sheet of a shoot day (Film & Video): day details per disposition job, saved sealed, and the PDF for everybody on the day
- `kalmido/hub/dispo.py` (`dsp`) - Resources and disposition -- booking crew and equipment for shoot days, seeing who and what is free per day, spotting double bookings
- `kalmido/hub/dspkern.py` (`dsk`) - The disposition on the shared core: the shoot day (light kind) and its call sheet (kind with history, undo and trash)
- `kalmido/hub/dspundo.py` - Undo across devices for dispatch bookings (one part per booking, delete and restore)
- `kalmido/hub/hmv1.py` (`hmv`) - The filed e-mails in the REST API v1 + MCP
- `kalmido/hub/holidays.py` (`hol`) - 2.461 public holidays per country
- `kalmido/hub/hubmail.py` (`hbm`) - E-mail as an input of the hub
- `kalmido/hub/leave.py` (`lv`) - Working days per person and leave
- `kalmido/hub/mailbox.py` (`mbx`) - The own mailbox of a workspace and sending from the e-mail filing (hub/hubmail.py)
- `kalmido/hub/mailrules.py` (`mbr`) - Documents from the own mailbox of a workspace (hub/mailbox.py)
- `kalmido/hub/mailview.py` (`mh`) - The HTML view of a filed e-mail and a task / an event made from it (hub/hubmail.py files the mails)

### `kalmido/integrations/`

Outbound and inbound connections: e-mail, webhooks, git, importers and exporters.

- `kalmido/integrations/delivery.py` (`delivery`) - The delivery report of a list for a day or since a moment (GET /api/v1/lists/<id>/delivery-report)
- `kalmido/integrations/docflowhook.py` (`dfh`) - The background part of the document flows (docs/flows.py)
- `kalmido/integrations/errorreports.py` (`cer`) - Error reports (Sentry, GlitchTip ...)
- `kalmido/integrations/exporters.py` (`ex`) - Export into other tools' formats
- `kalmido/integrations/git.py` (`git`) - Git integration of project lists (GitHub, GitLab, Gitea / Forgejo, Bitbucket)
- `kalmido/integrations/git_issues.py` (`gis`) - The issues of a repository connection (GitHub, GitLab)
- `kalmido/integrations/git_sync.py` (`gsy`) - The two-way sync of GitHub / GitLab issues with the tasks of a repository connection
- `kalmido/integrations/gitbuild.py` (`gb`) - The build state of a task -- the list
- `kalmido/integrations/gitfolder.py` (`gf`) - A repository connected to a FOLDER
- `kalmido/integrations/hookin.py` (`whi`) - Inbound webhooks of a list
- `kalmido/integrations/imp_linear.py` (`lin`) - Import from Linear -- with the person
- `kalmido/integrations/importers.py` (`imp`) - Importers: TickTick, Todoist, Trello, Asana, Microsoft To Do, ICS / VTODO (preview, dry run, undo)
- `kalmido/integrations/mail.py` (`mail`) - Tasks by e-mail (IMAP) and the daily summary by e-mail (SMTP)
- `kalmido/integrations/mailproof.py` (`eproof`) - A person proves the own e-mail address: a mailed one-time link, wakes the silent organisation invitations of that address
- `kalmido/integrations/mailtrim.py` (`md`) - Shorten a forwarded mail. A pure text function (no database, no request)
- `kalmido/integrations/mailtrim_html.py` - The shortened HTML view of a filed mail
- `kalmido/integrations/reqmail.py` (`rq`) - Requests by e-mail -- a customer
- `kalmido/integrations/taskbrief.py` (`brief`) - A work package as one document
- `kalmido/integrations/taskmail.py` (`tmr`) - The mail thread of a task -- replies by e-mail become comments, a comment can go back to the reporter
- `kalmido/integrations/webhooks.py` (`wh`) - Webhooks per user: collecting events during a request, delivery, settings

### `kalmido/life/`

Home & life: bookmarks, household budget, feeds (RSS), reading list, trips.

- `kalmido/life/bmundo.py` - Undo across devices for bookmarks (details, trash, restore)
- `kalmido/life/bookmarks.py` (`bm`) - Bookmarks -- links with a preview (title, description, picture)
- `kalmido/life/budget.py` (`bud`) - The household budget of "At home"
- `kalmido/life/budget_web.py` (`budget`) - The household budget -- the web API (the model is life/budget.py)
- `kalmido/life/budundo.py` (`bdu`) - Undo across devices -- budget entries in the core's step groups (core/undoareas.py)
- `kalmido/life/devlink.py` (`dl`) - A private device <-> a piece of office equipment
- `kalmido/life/karakeep.py` (`kk`) - Home & life: "Read later" from Karakeep (a person's own connection: bookmarks -> tasks of a reading list, archive back)
- `kalmido/life/lfkern.py` - Bookmarks and feeds on the one trash of the core (kinds bookmark_link / rss_feed, no routes, node or listing)
- `kalmido/life/model.py` (`journal`) - Home & life contracts, devices + upkeep, staying in touch, health, the review + journal, trips (the model)
- `kalmido/life/reading.py` (`rl`) - Reading -- the view "Read later"
- `kalmido/life/rss.py` (`rss`) - Reading: feeds (RSS 2.0, Atom 1.0, RSS 1.0 / RDF)
- `kalmido/life/rss_web.py` (`feeds`) - Reading: the web API of the feeds (/api/feeds, life/rss.py)
- `kalmido/life/rssundo.py` - Undo across devices for followed feeds (unfollow and follow again)
- `kalmido/life/tripcost.py` (`ltc`) - From a trip (a project of Home & life, lists.life 'travel')
- `kalmido/life/v1.py` (`v1`) - Home & life: the REST API v1 (+ MCP)
- `kalmido/life/web.py` (`life`) - Home & life: the web API (overview, contracts, devices, upkeep, health, trips, review + journal, staying in touch, Karakeep)

### `kalmido/lists/`

Lists and projects: folders, sections, fields, formulas, templates, sprints, sharing, reports.

- `kalmido/lists/custview.py` (`cv`) - The customer view of a public list link - what the owner lets the customer see (public_links.cv_show, JSON)
- `kalmido/lists/envs.py` (`env`) - Environments of a project list (Staging, Live, ...)
- `kalmido/lists/envundo.py` - Undo across devices for a project's environments (change, removal, restore; the webhook secret never goes back)
- `kalmido/lists/favorites.py` (`fv2`) - Favourite lists and projects, personal per person (the user setting fav_lists)
- `kalmido/lists/fields.py` (`field`) - Custom fields of a list
- `kalmido/lists/fieldundo.py` - Undo across devices for a project's custom fields (create, change, delete into the core's copy trash, restore)
- `kalmido/lists/filterrules.py` (`cf`) - The rules of a saved filter on the server
- `kalmido/lists/flow.py` (`flw`) - Flow figures of a project, computed on read from the task history (no own storage)
- `kalmido/lists/folders.py` (`folder`) - Folder settings. A folder of its owner carries defaults for every list in it and in its subfolders (the owner's lists; members see the lists in their own folders)
- `kalmido/lists/folderdefs.py` (`fdf`) - More folder defaults (view, columns, custom fields, project tags, repeat reminder, hours per day, rate, progress bar) handed to the lists in a folder
- `kalmido/lists/foldershare.py` (`sh`) - Sharing a whole folder in one dialog, like a list
- `kalmido/lists/foldundo.py` - Undo across devices for renaming / moving a sidebar folder (a diff part of the person's step group)
- `kalmido/lists/formula.py` (`fx`) - Formula fields -- a small calculator over the number fields of a list, computed on the server
- `kalmido/lists/grouppics.py` (`fg`) - Group pictures: a preset or an own photo per group, like the profile pictures of people
- `kalmido/lists/groups.py` (`grp`) - Groups of people (admin): materialized list memberships, tasks assigned to a group
- `kalmido/lists/kpis.py` (`fx`) - Calculating with custom fields
- `kalmido/lists/lffolder.py` (`lf`) - The folders of the lists (projects)
- `kalmido/lists/listexport.py` (`lex`) - A list or project as a CSV file (GET /api/lists/<id>/export.csv)
- `kalmido/lists/listhead.py` (`o3c`) - The header strip of a list (and of an owner's folder)
- `kalmido/lists/lists.py` (`agent`) - Lists: create, change, share (people + agents)
- `kalmido/lists/listtrash.py` (`otr`) - The trash of deleted lists
- `kalmido/lists/lkretire.py` (`lk`) - Stage 7d of the shared core: folder_people and group_shares go at the start
- `kalmido/lists/lmcore.py` (`lmc`) - Stage 6 of the shared core
- `kalmido/lists/lmove.py` - A project into another workspace
- `kalmido/lists/lpside.py` - Undo across devices for a project's settings with side effects (folder, workspace, type, agents ...): diff steps taken back through list_apply
- `kalmido/lists/lpundo.py` - Undo across devices for a project's plain settings (PATCH /api/lists/<id>)
- `kalmido/lists/otrundo.py` - Undo across devices for a project moved into the list trash (DELETE /api/lists/<id>)
- `kalmido/lists/membermemo.py` (`mm`) - What removing a member ends, remembered so that adding the person again brings it back
- `kalmido/lists/orgfields.py` (`of`) - The field schema of an organisation
- `kalmido/lists/orglabels.py` (`olb`) - Labels of an organisation -- project tags defined once for every project of the organisation (obj_tags scope org since 2.947)
- `kalmido/lists/orgvis.py` (`ov`) - Who sees an organisation list
- `kalmido/lists/ownership.py` (`owner`) - Transferring the ownership of a list
- `kalmido/lists/padundo.py` - Undo across devices for the notepads of a project's pin board (title and text)
- `kalmido/lists/parttrash.py` (`lpt`) - The trash of a list's sections and planned sprints, and the one trash view of everything else 2.567.0 moved from the hard delete into a trash
- `kalmido/lists/playbook.py` (`pb`) - The Playbook of a list or folder
- `kalmido/lists/points.py` (`spt`) - Story points and velocity. tasks.points holds a task
- `kalmido/lists/projects.py` (`ov`) - Project lists: status, progress, the overview (description, links, files)
- `kalmido/lists/public.py` (`pub`) - Public links of lists and checklist mode
- `kalmido/lists/report.py` - The status report of a project (or any list)
- `kalmido/lists/rules.py` (`rul`) - Rules of a list ("When ... then ...")
- `kalmido/lists/ruleundo.py` - Undo across devices for a project's rules (change, trash, restore; checked with the rights of the person taking it back)
- `kalmido/lists/seckind.py` (`sk`) - The meaning of a column (sections.kind)
- `kalmido/lists/sections.py` (`folder`) - Saved filters, folders and sections (kanban columns)
- `kalmido/lists/sectpl.py` (`sct`) - Section templates -- a name and the ordered names of a list (templates of kind sections since #5288)
- `kalmido/lists/secundo.py` - Undo across devices for creating, deleting and restoring a project's section (diff parts)
- `kalmido/lists/shoot.py` (`sht`) - The shot list of a shoot (project type "shoot", lists/templates.py PTYPES)
- `kalmido/lists/sprints.py` (`spr`) - Sprints of a project list -- time boxes with a goal, a burndown and a close-out review
- `kalmido/lists/sprundo.py` - Undo across devices for a project's sprints (plan, change, remove, restore)
- `kalmido/lists/templates.py` (`tpl`) - Task, list and section templates (a kind of the shared core, lists/tplkind.py), built-in project types
- `kalmido/lists/tplextra.py` (`tx`) - What a duplicate and a template carry beyond the plain task nodes (lists/templates.py)
- `kalmido/lists/tplkind.py` (`tk`) - Task, project and section templates as one kind of the shared core: its register and the role checks (#5288)
- `kalmido/lists/tplundo.py` - Undo across devices for the person's templates (rename, trash, restore)

### `kalmido/newsletter/`

Newsletter sync and adapters.

- `kalmido/newsletter/adapters.py` - The adapters of the newsletter services
- `kalmido/newsletter/sync.py` (`nwl`) - The newsletter connection of a workspace and the sync with the service (no own mass mailing)
- `kalmido/newsletter/web.py` (`nwl`) - The routes of the newsletter connection (contacts settings, static/js/newsletter.js)

### `kalmido/notify/`

Notifications: alerts, channels, Web Push, severity and the task bell.

- `kalmido/notify/alerts.py` (`aa`) - Admin alerts via ntfy (recording, sending, settings)
- `kalmido/notify/caps.py` (`folder`) - Notification templates of a shared list / folder, set by its owner
- `kalmido/notify/channels.py` (`chn`) - Notification channels (Slack, Matrix, Telegram, Signal)
- `kalmido/notify/push.py` (`wd`) - Notifications: ntfy, Web Push (RFC 8030 / 8291 / 8292)
- `kalmido/notify/sev.py` (`sev`) - Security alerts of the app itself
- `kalmido/notify/taskbell.py` (`tbl`) - The bell of ONE task, per person

### `kalmido/office/`

Office & finance: quotations, invoices, bank, books, tax, DATEV, e-invoices, letters, contracts, travel.

- `kalmido/office/abschlag.py` (`abs`) - Progress and final invoices, cash discount (Skonto)
- `kalmido/office/agentdeals.py` (`v1`) - Agents read and add inquiries and deals of the sales pipeline (office/pipeline.py, office_deals, the stages inquiry | offer | won | lost)
- `kalmido/office/agentdocs.py` (`ofa`) - Agents in the office -- drafts only, a person confirms
- `kalmido/office/agentinvoice.py` (`ofv`) - An agent (e.g. the Kalmido AI, a server agent)
- `kalmido/office/agreements.py` (`bk`) - Business contracts and insurances of an office area (insurance, rent, leasing, service provider, other)
- `kalmido/office/agrref.py` - Contracts in folders -- the reference kinds
- `kalmido/office/archiveedit.py` (`r81b`) - Correct an archived document of the office (office_archive, legacyimport.py)
- `kalmido/office/assets.py` (`ast`) - The value of equipment -- purchase, depreciation, current value, insurance list
- `kalmido/office/bank.py` (`bnk`) - Bank reconciliation -- CSV / CAMT.053 import, matching bookings to invoices and receipts
- `kalmido/office/bankacc.py` (`bka`) - The bank accounts of an office as master data (table office_bank_accounts)
- `kalmido/office/banknorc.py` (`bnr`) - Bank bookings without a receipt
- `kalmido/office/bankrules.py` (`br`) - Bank rules -- bookings of a statement marked by rules, and rules learned from what people confirm
- `kalmido/office/bankvend.py` (`bv`) - Recurring providers of the bank bookings
- `kalmido/office/bkexport.py` (`bx`) - The neutral bookkeeping export
- `kalmido/office/bookarch.py` (`ba`) - The booking archive -- the complete DATEV data of past years, read-only, next to the bookkeeping
- `kalmido/office/books.py` (`bk`) - Bookkeeping light -- income/expense statement (EUeR)
- `kalmido/office/bpread.py` (`bp`) - A small PDF reader for the own letterhead (office.letterhead)
- `kalmido/office/calc.py` (`calc`) - The quotation calculator of Office & Finance
- `kalmido/office/candthumb.py` - The preview of a receipt on the candidate cards: the address of an existing preview (document thumb or file thumb), no new file processing
- `kalmido/office/cardlines.py` (`cl`) - The positions of a credit card statement
- `kalmido/office/cardnorc.py` (`ccn`) - Credit card positions without a receipt
- `kalmido/office/cards.py` (`cc`) - Credit card statements in the office
- `kalmido/office/cashbook.py` (`cb`) - The cash book of an office area
- `kalmido/office/cashflow.py` (`rk`) - Office & finance: the cash flow
- `kalmido/office/catacct.py` (`ca`) - Receipt categories with an account of the chart SKR03 / SKR04
- `kalmido/office/catalog.py` (`pkc`) - The pack catalogue -- country packs (kind country, office/packs.py)
- `kalmido/office/ccread.py` (`ccr`) - Reading a credit card statement (PDF)
- `kalmido/office/cfbank.py` (`cfb`) - Office & finance: the account balance from the bank reconciliation
- `kalmido/office/cfstart.py` (`cfs`) - Office & finance: the account balance of the cash flow
- `kalmido/office/chain.py` (`hch`) - The hash chain over finalised documents
- `kalmido/office/clientlink.py` - The address book search of the client dialog
- `kalmido/office/contacts_cl.py` (`fk`) - Several contact persons per client (office_client_contacts)
- `kalmido/office/contractfiles.py` (`dma`) - PDF files of a framework contract (Office > Framework contracts: the signed contract, addenda)
- `kalmido/office/costs.py` (`ek`) - 2.47.0 (part D): the purchase side of quotations
- `kalmido/office/countries.py` (`fk`) - The country of a client / of the company is an ISO 3166-1 alpha-2 code from this list (the 249 officially assigned codes)
- `kalmido/office/datev.py` (`dx`) - Office & finance: the DATEV booking batch (EXTF "Buchungsstapel", format 700, category 21)
- `kalmido/office/datevimp.py` (`di`) - The DATEV import -- master data and booking batches the tax advisor sends (the other way round of office/datev.py)
- `kalmido/office/datevin.py` (`dv`) - The input side of the DATEV booking batch (office/datev.py)
- `kalmido/office/datevzip.py` (`dz`) - The receipts go to the tax advisor together with the bookings, as with DATEV Unternehmen online
- `kalmido/office/delivery.py` (`ls`) - Delivery notes / proofs of service (office_docs kind "delivery")
- `kalmido/office/doclang.py` (`doc`) - Office & finance 2.40.0: switching the language (or the reminder level)
- `kalmido/office/docproject.py` (`dpj`) - Quotations, invoices and credit notes bound to a project (office_docs.list_id)
- `kalmido/office/docref.py` (`ofd`) - Quotations and invoices (office_docs)
- `kalmido/office/docs.py` (`odoc`) - Office & finance, part C: quotations (documents of kind "offer")
- `kalmido/office/doctpl.py` (`dt`) - Document templates with variables, documents as PDF filed with client / project, signature by customer link
- `kalmido/office/doctpl_samples.py` - More samples for the document templates (letters next to the three contract samples of doctpl.DT_STARTERS)
- `kalmido/office/doctpl_samples_es.py` - The samples in Spanish, translated when they were built (Kalmido never calls a language model)
- `kalmido/office/doctpl_samples_fr.py` - The samples in French, translated when they were built (Kalmido never calls a language model)
- `kalmido/office/doctpl_samples_it.py` - The samples in Italian, translated when they were built (Kalmido never calls a language model)
- `kalmido/office/doctpl_samples_nl.py` - The samples in Dutch, translated when they were built (Kalmido never calls a language model)
- `kalmido/office/dunning.py` (`dun`) - Payment reminders suggested for overdue invoices (drafts only; nothing is sent automatically)
- `kalmido/office/einvoice.py` (`ein`) - The e-invoice XML of a finalised invoice / credit note
- `kalmido/office/einvoice_in.py` (`ei`) - Incoming e-invoices -- XRechnung / EN 16931 as UBL (Invoice, CreditNote)
- `kalmido/office/eqcare.py` (`eqc`) - Warranty end and maintenance of office equipment
- `kalmido/office/euerbasis.py` (`eb`) - The basis of the income / expense statement (EUeR)
- `kalmido/office/euercmp.py` (`ec`) - The comparison of the income/expense statement (EUeR)
- `kalmido/office/fints.py` (`fnt`) - The direct bank fetch over FinTS (PIN/TAN)
- `kalmido/office/fixedimport.py` (`fci`) - Fixed costs of the cash flow from a spreadsheet, and the optional monthly task "
- `kalmido/office/gdpdudtd.py` - The official DTD of the GDPdU / GoBD description standard, text unchanged
- `kalmido/office/girocode.py` (`gcq`) - The GiroCode (EPC QR code, EPC069-12 version 002)
- `kalmido/office/gobdexport.py` (`gx`) - The export for a tax auditor (GoBD "Datenträgerüberlassung", Z3 access)
- `kalmido/office/homecur.py` (`hc`) - The office's own home currency (ISO 4217)
- `kalmido/office/invoices.py` (`inv`) - Office & finance, stage 2: invoices, credit notes and reminders (kinds invoice / credit / reminder of office_docs)
- `kalmido/office/kpi.py` (`kpi`) - Office & finance: the business figures at a glance
- `kalmido/office/leads.py` (`lead`) - Leads before the sales pipeline
- `kalmido/office/ledger.py` (`ofx`) - Office & finance foundation
- `kalmido/office/ledger_dbl.py` (`ld`) - Double-entry bookkeeping and the balance sheet for organisations that must draw one up (GmbH, UG)
- `kalmido/office/legacyimport.py` (`fi`) - Office & finance: the legacy import
- `kalmido/office/letteragent.py` (`lta`) - Agents and letters: "Let the agent draft an answer"
- `kalmido/office/letterhead.py` (`bp`) - The own letterhead of the office documents (a PDF behind every page of quotations, invoices, credit notes, reminders and every later kind of office.docs)
- `kalmido/office/letterlinks.py` (`ltl`) - Letters <-> documents of the documents space (links of the core: obj_links rel answers | reply, since 2.1076.0 #5271)
- `kalmido/office/lettermail.py` (`ltm`) - A letter sent by e-mail (its PDF attached, the Message-ID kept)
- `kalmido/office/letters.py` (`lt`) - Letters of an office area ("Korrespondenz")
- `kalmido/office/logbook.py` (`lb`) - The logbook: vehicles, drives, change log, year report, mileage allowance into the EUeR (filled by part B)
- `kalmido/office/mailsig.py` (`ofm`) - What a person adds to the office
- `kalmido/office/mealpay.py` (`mp`) - An entertainment receipt as the proof of its payment
- `kalmido/office/mealpdf.py` (`bw`) - The PDFs of the entertainment receipts (office/meals.py)
- `kalmido/office/meals.py` (`bw`) - Entertainment receipts (Bewirtungsbelege, section 4 (5) no. 2 EStG)
- `kalmido/office/model.py` (`office`) - Office & finance: the gate, the organisation one works in, the module
- `kalmido/office/numranges.py` (`onum`) - Office & finance, the number ranges
- `kalmido/office/offerdispo.py` (`odp`) - Shoot days from a quotation as pencilled-in bookings of the disposition
- `kalmido/office/offerexp.py` (`ofe`) - A sent quotation without an answer rings the bell before and after its "valid until"; extend its validity
- `kalmido/office/offerlink.py` (`oil`) - The link between a quotation and the invoices made from it (office_docs.source_doc_id)
- `kalmido/office/offertasks.py` (`otk`) - Tasks in the project from a quotation, with a time budget per position
- `kalmido/office/officemove.py` (`ofm`) - Office data between the personal office and an organisation
- `kalmido/office/oftree.py` (`oft`) - The office's document areas as trees in the panel
- `kalmido/office/oftref.py` (`rc`) - Generated documents, letters and receipts filed in folders
- `kalmido/office/okern.py` - Office kinds on the one trash of the core (ofk_register / ofk_trash / ofk_restore); the area's own purge runs are gone
- `kalmido/office/olock.py` (`olk`) - Legal retention locks of the office
- `kalmido/office/otrash.py` (`otb`) - 2.272.0 E2 the office trash (2.1005.0: its routes; copies only for the start balance and orphaned sign-off records)
- `kalmido/office/oubar.py` (`oub`) - Undo across devices, stage 4 -- the office's steps in the core's step groups: labels and barriers (finalising, sending, payments)
- `kalmido/office/outlays.py` (`au`) - Bill receipts (documents with a row in rc_receipts, the bookkeeping's receipt sheet)
- `kalmido/office/owrite.py` (`ow`) - The shared core, stage 2 -- ONE write call for an office row (and a client)
- `kalmido/office/packs.py` (`office`) - Office & finance: country packs
- `kalmido/office/parts.py` (`tp`) - Parts of a quotation (Teilangebote)
- `kalmido/office/payonline.py` (`pol`) - Online payment of invoices
- `kalmido/office/pbtransfer.py` (`pbt`) - The personal office into an existing organisation the person is an admin of (one way, no undo)
- `kalmido/office/pdf.py` (`pdf`) - The PDF of an office document (quotation)
- `kalmido/office/pdfweb.py` (`epdf`) - The PDF of a quotation and the company logo of the office module
- `kalmido/office/peppol.py` (`pep`) - E-invoices over the Peppol network, through the office
- `kalmido/office/periodlock.py` (`pl`) - Locking accounting periods (GoBD "Festschreibung")
- `kalmido/office/pipeline.py` (`pl2`) - Office & finance: the sales pipeline
- `kalmido/office/portaldocs.py` (`kp`) - The customer's documents in the customer portal (module "portal" + office)
- `kalmido/office/privacy.py` (`dsb`) - Data protection sheets of a client
- `kalmido/office/procdoc.py` (`pd`) - The procedure documentation (Verfahrensdokumentation, GoBD)
- `kalmido/office/rcfolder.py` (`rcf`) - Receipts of the credit cards and of the bank file themselves into month folders (Receipts / Credit card or Bank / card or account / year / month)
- `kalmido/office/rcsubmit.py` (`rsb`) - Members hand in receipts to the bookkeeping ("Submit receipt")
- `kalmido/office/receiptlist.py` (`rcl`) - The receipts list of the bookkeeping over all months, with filters, and the export of exactly that list
- `kalmido/office/recurring.py` (`rin`) - Invoice series -- a template invoice repeated every month / quarter / year (drafts or sent)
- `kalmido/office/repcalc.py` (`orp`) - Repricing a quotation (Nachkalkulieren), the pure calculation: one factor on the unit prices, found through the real sums
- `kalmido/office/reprice.py` (`orp`) - Repricing a quotation: the route POST /api/office/docs/<id>/reprice (preview / apply, one undo step)
- `kalmido/office/rethold.py` (`rth`) - The switch "Extend the lock"
- `kalmido/office/rights.py` (`ofr`) - Office access rights -- groups (roles)
- `kalmido/office/search.py` - The office hits of the web search (GET /api/search, tasks/ftsearch.py)
- `kalmido/office/sheet.py` (`dk`) - The calculation sheet of a quotation part of kind
- `kalmido/office/signoff.py` (`sig`) - Approvals with a simple electronic signature through a customer link (table office_signoffs)
- `kalmido/office/storefill.py` (`osf`) - Catch-up of the stored files of finalised office documents (all kinds but quotations)
- `kalmido/office/subs.py` (`abo`) - Subscriptions and tools -- fixed costs with a notice period, users and a reminder before they renew
- `kalmido/office/taxcheck.py` (`tc`) - The tax check before filing the Anlage EUeR and the annual VAT return
- `kalmido/office/taxdates.py` (`txd`) - Tax dates as recurring tasks (VAT return, income tax prepayments, trade tax)
- `kalmido/office/taxforms.py` (`tf`) - The Anlage EUeR and the annual VAT return (USt 2 A)
- `kalmido/office/terms.py` (`agb`) - The office's terms and conditions (AGB)
- `kalmido/office/timebill.py` (`tbill`) - Time entries to an invoice
- `kalmido/office/travel.py` (`rk`) - Office & finance: travel expenses
- `kalmido/office/undo.py` (`oun`) - Undo for the office editors that save every field at once (documents with their parts, clients, the master data like services)
- `kalmido/office/undogrp.py` (`ugo`) - Who may take an office step back from the core's step groups (core/undoweb.py undo_need_reg)
- `kalmido/office/vma.py` (`vma`) - The per diem (Verpflegungsmehraufwand, VMA)
- `kalmido/office/vmaimport.py` (`vmi`) - The import of a per diem spreadsheet
- `kalmido/office/vmareport.py` (`vmr`) - The per diem (Verpflegungsmehraufwand)
- `kalmido/office/web.py` (`office`) - Office & finance: the web routes of the module
- `kalmido/office/years.py` (`ofc`) - The years with data of an office list (travel, meals, logbook, cash book, books / VAT return)

### `kalmido/paperless/`

Import from Paperless-ngx.

- `kalmido/paperless/learn.py` (`pll`) - What a Paperless-ngx import teaches Kalmido
- `kalmido/paperless/ngx.py` (`pl`) - The Paperless-ngx connection of a workspace and the import of its documents into the Kalmido documents
- `kalmido/paperless/web.py` (`pl`) - The routes of the Paperless-ngx connection (documents settings, static/js/paperless.js)
- `kalmido/paperless/zipimp.py` (`plh`) - The import of a Paperless-ngx export (document_exporter, as a ZIP)

### `kalmido/personal/`

Personal tools: habits, statistics and time tracking.

- `kalmido/personal/budgetwarn.py` (`bw`) - The budget warning of projects and tasks (decision of only a display, no lock)
- `kalmido/personal/habits.py` (`pomo`) - Habits and focus sessions (pomodoro)
- `kalmido/personal/habitundo.py` - Undo across devices, stage 6 -- habits in the core's step groups (core/undoareas.py)
- `kalmido/personal/stats.py` - Statistics (module "stats")
- `kalmido/personal/statslife.py` (`stl`) - The statistics blocks of Home & life
- `kalmido/personal/timegaps.py` - Time-tracking helper. "Maybe forgotten"
- `kalmido/personal/timesheet.py` (`tsl`) - Monthly timesheets (close / approve / send back)
- `kalmido/personal/timetrack.py` (`time`) - Time tracking (module "time")
- `kalmido/personal/timeundo.py` - Undo across devices for a person's own time entries (change, delete)
- `kalmido/personal/timewipe.py` (`tz`) - "Delete all times of this project"
- `kalmido/personal/timexlsx.py` (`tx`) - Excel (.xlsx) export of the time report and of the workload view
- `kalmido/personal/v1focus.py` (`v1`) - Focus sessions (pomodoro) and habit statistics over API v1

### `kalmido/receipts/`

Receipt data: extraction, checks and suggestions.

- `kalmido/receipts/extracted.py` (`rx`) - What the recognition read off a receipt
- `kalmido/receipts/rchecks.py` (`rck`) - The fixed check of a receipt (docs/rcheck.py rck_check)
- `kalmido/receipts/suggest.py` (`rc`) - Agents suggest the project and category of a receipt

### `kalmido/sheets/`

Tables (spreadsheets): formulas, charts, pivot, printing, sharing, import / export.

- `kalmido/sheets/core.py` (`sh`) - Tables ("Excel in simple")
- `kalmido/sheets/formula.py` (`sh`) - The formula engine of tables ("Excel in simple")
- `kalmido/sheets/io.py` (`shx`) - Tables to and from files. Export (reading the sheet is enough; values evaluated for the person exporting, so a file never holds a value they could not see)
- `kalmido/sheets/shbook.py` (`shb`) - Several sheets in one table (a "book", like the sheets of a spreadsheet file)
- `kalmido/sheets/shchart.py` - The simple chart of a table
- `kalmido/sheets/shfmt.py` (`shfm`) - The format of a table
- `kalmido/sheets/shfolder.py` (`shf`) - Tables in folders -- the reference kind
- `kalmido/sheets/shfuncs.py` (`shf`) - The newer formula functions of tables
- `kalmido/sheets/shfuncs2.py` (`shf`) - The everyday formula functions of tables that were still missing next to sheets/shfuncs.py
- `kalmido/sheets/shhist.py` (`shh`) - The change history of a table
- `kalmido/sheets/shkern.py` - Tables on the one trash of the core (stage 3): registration, purge hook with the further sheets and their files
- `kalmido/sheets/shkinds.py` (`shk`) - More column kinds of a table and the rows / columns that stay in view
- `kalmido/sheets/shmove.py` (`shm`) - A table to the other workspace (private <-> organisation)
- `kalmido/sheets/shorder.py` (`sho`) - Ranges of formulas when rows or columns are moved (dragged in the grid, "Move up / down / left / right")
- `kalmido/sheets/shpivot.py` (`shp`) - The pivot sheet of a table
- `kalmido/sheets/shprint.py` (`shp`) - The print view of a table as a PDF
- `kalmido/sheets/shshare.py` (`shs`) - One table shared with single people or agents (read | write)
- `kalmido/sheets/shundo.py` - Undo across devices for tables: a person's writes to cells, rows and columns as pointer steps to their batch (sh_undo_batch / shu_redo)
- `kalmido/sheets/shustep.py` - Undo across devices for tables, stage 5 rest: a person's other table changes (rows / columns deleted, column settings, order, chart, colour rules, cell names, frozen values, rows in view, the sheets of the bar) as steps of their batch
- `kalmido/sheets/step2.py` (`sh2`) - Step 2 of the tables
- `kalmido/sheets/v1.py` (`v1`) - Tables for agents and scripts (API v1; scopes sheets:read / sheets:write)
- `kalmido/sheets/vars.py` (`sh`) - Kalmido variables of table formulas
- `kalmido/sheets/web.py` (`sheets`) - The routes of the tables area (/api/sheets)

### `kalmido/tasks/`

Tasks: lifecycle, dependencies, attachments, trash, relations, reminders, review, roadmap.

- `kalmido/tasks/attachments.py` (`text`) - Files of tasks (upload, download, delete)
- `kalmido/tasks/attachtext.py` (`cache`) - The text of an attachment for agents ("read attachment")
- `kalmido/tasks/atttrash.py` (`atr`) - 2.272.0 E2 the trash of task / comment files (attachments)
- `kalmido/tasks/batch.py` - Reordering and batch changes of tasks, occurrences of repeating tasks, deleting attachments
- `kalmido/tasks/briefing.py` (`brief`) - The morning briefing per person
- `kalmido/tasks/dayplan.py` (`dayplan`) - Day planning ("Plan my day")
- `kalmido/tasks/deliver.py` (`dv`) - The delivery state of a task
- `kalmido/tasks/delta.py` (`dl`) - The delta state -- only the tasks that changed since the client
- `kalmido/tasks/depchain.py` (`dch`) - The dependency chain moves along ("Move dependent tasks along", list setting dep_shift)
- `kalmido/tasks/dependencies.py` (`dep`) - Dependencies between tasks ("waiting on")
- `kalmido/tasks/ftsearch.py` (`fts`) - Full-text search on the server
- `kalmido/tasks/lifecycle.py` (`task`) - Applying changes, completing (repeats)
- `kalmido/tasks/mineorder.py` (`ms`) - "My tasks" in the person's own order (table user_task_order: user_id, task_id, pos)
- `kalmido/tasks/minerules.py` (`mr`) - The person's own rules of "My tasks": move a task into an own section, once per occasion
- `kalmido/tasks/movememo.py` (`tmm`) - What a move of a task ends, remembered so that moving it back brings it back
- `kalmido/tasks/multilist.py` (`ml`) - A task in several lists without a copy
- `kalmido/tasks/oneway.py` (`irr`) - The mark "irreversible" of a task and the task
- `kalmido/tasks/related.py` (`emb`) - Related tasks, stage 1 -- local text vectors of every task, "
- `kalmido/tasks/relations.py` (`rel`) - Saved relations between tasks
- `kalmido/tasks/remindat.py` (`rat`) - A reminder at a fixed time ("remind me Tue 9:00")
- `kalmido/tasks/review.py` (`rvw`) - The review step of a list -- a reviewer per task, "
- `kalmido/tasks/roadmap.py` - The roadmap and shifting a list
- `kalmido/tasks/snippets.py` (`snip`) - Code snippets of a task -- plain code (no Markdown)
- `kalmido/tasks/stale.py` (`stale`) - Stale tasks ("Liegt") -- open tasks nobody touched for a while, and tasks waiting on someone without a follow-up day
- `kalmido/tasks/tasks.py` (`task`) - Creating and changing tasks
- `kalmido/tasks/tasktrash.py` (`ttp`) - The trash period of tasks. The watchdog (at most hourly)
- `kalmido/tasks/ticketkey.py` (`tk`) - Readable ticket keys "APP-123"
- `kalmido/tasks/ttypes.py` (`tt`) - Own ticket types per workspace, next to the built-in bug / feature / task
- `kalmido/tasks/tundo.py` (`tu`) - Undo across devices, stage 3 -- the tasks' steps on the server (diff parts, core/undodiff.py)
- `kalmido/tasks/validation.py` (`clean`) - Task activity log, input validation, repeat rules (RRULE)
- `kalmido/tasks/watchers.py` (`wat`) - A second responsibility on a task

### `kalmido/team/`

Teams and customers: clients, forms and questionnaires, approvals, portal, workload.

- `kalmido/team/approvals.py` (`approval`) - Approvals as a task type ask someone to approve a task
- `kalmido/team/clientmerge.py` (`clm`) - Merging duplicate clients by hand (Office > Clients, the selection mode)
- `kalmido/team/clients.py` (`cl`) - Clients: customers of an organisation above the lists, hours + budget, estimate vs
- `kalmido/team/clients_bulk.py` (`ms`) - Clients: several at once. One request deletes, archives, restores or changes a selection of clients (Office > Clients, the selection mode)
- `kalmido/team/formq.py` (`fq`) - Questionnaires -- the forms (team/forms.py)
- `kalmido/team/forms.py` (`form`) - Forms: a link with a small form that creates a task in a list (requests, bug reports)
- `kalmido/team/portal.py` (`pt`) - Customer reports and the customer portal (module "portal")
- `kalmido/team/v1.py` (`v1`) - Team, family, clients the REST API v1 (+ MCP)
- `kalmido/team/workload.py` - Workload: planned hours per person and week against their capacity, within the organisation

### `kalmido/videos/`

Video sign-offs (review links and media).

- `kalmido/videos/review.py` (`vdr`) - Video sign-off with comments at a timecode (tables video_reviews / video_versions; the comments: obj_comments kind video, 2.981.0)
- `kalmido/videos/v1.py` (`vdr`) - Video sign-offs for agents and scripts (API v1; scopes read / comments)
- `kalmido/videos/vdkern.py` - Video sign-offs on the one trash of the core (kind video_review, no routes, node or listing)
- `kalmido/videos/vdlink.py` (`vdl`) - The customer link of a sign-off for clients without an account, on the approval links of office/signoff.py (kind video; no table and no token way of its own)
- `kalmido/videos/vdmedia.py` (`vdm`) - The sign-off (videos/review.py)
- `kalmido/videos/vdrescue.py` - Video sign-offs survive the hard delete of their task, project or client

### `kalmido/wiki/`

Knowledge pages (wiki): pages, history, sharing, search, tags, folders and the lock.

- `kalmido/wiki/outline.py` (`mm`) - The import of the mind map
- `kalmido/wiki/pages.py` (`wiki`) - Knowledge pages -- a small wiki per organisation
- `kalmido/wiki/wikiatt.py` (`wka`) - Files of knowledge pages (PDFs and pictures)
- `kalmido/wiki/wikie2e.py` (`wke`) - The lock per knowledge space
- `kalmido/wiki/wkembed.py` (`wem`) - Files of the file store ("Ablage")
- `kalmido/wiki/wkfolder.py` (`wkf`) - Knowledge pages in folders of the file store
- `kalmido/wiki/wkarea.py` (`wka`) - A whole knowledge area shared with an agent at once: the facts of its Share dialog (GET /api/wiki/area-share; #5823)
- `kalmido/wiki/wkfshare.py` (`wkfs`) - Knowledge pages for people who reach them only through a share of their folder / page node
- `kalmido/wiki/wkhist.py` (`wkh`) - Knowledge pages -- the text sealed at rest and the history of a page
- `kalmido/wiki/wkkern.py` - Knowledge pages on the one trash of the core (stage 3): registration, their files as children
- `kalmido/wiki/wkmove.py` (`wkm`) - Wiki pages and folders (with their sub-pages)
- `kalmido/wiki/wksearch.py` (`wks`) - The search of the knowledge pages over a word index instead of ILIKE on the text
- `kalmido/wiki/wkshare.py` (`wsh`) - Read-only shares of a knowledge page or a folder
- `kalmido/wiki/wkstyle.py` - The reading style of a knowledge space
- `kalmido/wiki/wktags.py` (`wkt`) - 2.371 tags of knowledge pages and the `
- `kalmido/wiki/wkundo.py` - Undo across devices for knowledge pages: a save as a pointer step to the page's own version history
- `kalmido/wiki/wkv1.py` (`wkv`) - Knowledge pages for agents and scripts (API v1; scopes wiki:read / wiki:write)

### `kalmido/`

The start-up module.

- `kalmido/startup.py` - Start-up: init_db() and the background threads (watchdog, update check, calendars, backups, webhooks, mail, git)

## Scripts (`static/js/`)

- `static/js/abdocs.js` (`abd`) - File store and documents are ONE area "
- `static/js/ablage.js` (`ab`) - The file store "Ablage". Folders and files per person and per organisation, shared with people, groups and agents
- `static/js/ablinks.js` (`xl`) - External share links of the file store
- `static/js/abscan.js` - The phone scan -- photograph pages with the camera (on a computer: choose pictures)
- `static/js/absence.js` (`ab2`) - Absences -- a tab of the workload view
- `static/js/account.js` (`auth`) - Account, users (admin), login, groups, passkeys, two-factor, sign-in policy, backups, the sample project
- `static/js/acctset.js` (`ua8`) - The settings sections of account.js that only the settings dialog draws (account, users, groups, organisations, notifications, two-factor, backups, the sample project)
- `static/js/agentchat.js` (`chat`) - The chat with an agent (side panel / view)
- `static/js/agentcontrol.js` (`awc`) - The section "Control" of the agent dialog "
- `static/js/agentlock.js` - The section "Data the agent never sees"
- `static/js/agentplan.js` (`ap`) - What agents plan for a person
- `static/js/agentrotate.js` - The agent runtime section "
- `static/js/agentrules.js` (`awr`) - The section "Standing rules"
- `static/js/agents.js` (`prop`) - Agents, reactions, shared list tags, tidy suggestions
- `static/js/agentsees.js` (`ags`) - The section "Sees now" of the agent dialog, "Share…" and the hints at permissions without a share
- `static/js/agentsetup.js` (`ains`) - Pick Mac / Windows / Linux and the project folder, Kalmido makes a one-time code (15 minutes, works once)
- `static/js/agentview.js` (`av`) - Personal agents and the switch "
- `static/js/agentwork.js` (`aw`) - The dialog "Work style and notifications"
- `static/js/apptbook.js` (`apb`) - The booking page ("Terminbuchung")
- `static/js/areas.js` (`sbb`) - The areas . Modules that belong together are ONE entry in the sidebar, the tab bar and Settings > Modules, and one page with tabs for their parts
- `static/js/assistant.js` (`asst`) - The built-in assistant
- `static/js/asstprop.js` (`ast`) - Texts worded by a connected agent, on request
- `static/js/attachments.js` (`md`) - Attachments and the share target
- `static/js/backclose.js` (`f8d`) - On a touch device the Back key / swipe closes the topmost dialog, sheet, menu or the search palette instead of changing the route
- `static/js/backnav.js` (`bn`) - Desktop only - a plain Back arrow at the left of the head bar (#top)
- `static/js/basket.js` (`kb`) - #1185: the sidebar - one button folds / unfolds every group and folder at once (stored like a single fold)
- `static/js/bookmarks.js` (`bm`) - Bookmarks: the view "Bookmarks"
- `static/js/budget.js` (`bg`) - The household budget (module "budget", part of the area Home)
- `static/js/calabs.js` (`abc`) - Public holidays and absences in the calendar (module "calabs", loaded on demand by the "Calendars" window and the event editor)
- `static/js/caldrag.js` (`cg`) - The calendar like macOS Calendar
- `static/js/calendar.js` (`cvx`) - Kanban, the calendar views and external calendar events
- `static/js/calevents.js` (`ev`) - Events (module "events"): own calendars next to the tasks, the event editor and popover, the agenda, creating events in the week grid, calendars (share, import, export)
- `static/js/calgest.js` (`cgs`) - Gestures of the calendar (module "calendar", loaded with calview.js / caldrag.js)
- `static/js/callsheet.js` (`cs`) - The call sheet dialog of a shoot day (module "callsheet", loaded on demand from a booking in the disposition): day details, directions sketch, PDF
- `static/js/calrrule.js` (`crr`) - An own repeat rule for an event ("every 2nd Tuesday", Mon + Wed + Fri)
- `static/js/calview.js` (`cal`) - The calendar views month / week / day and Settings > Integrations > Calendars
- `static/js/calyear.js` (`cyr`) - The calendar's year view: twelve small months, a day with events or tasks tinted in the accent colour (the more, the stronger)
- `static/js/cfkinds.js` (`cfk`) - Editing the custom field types of , loaded on demand (lazyload.js module cfkinds)
- `static/js/cfnew.js` (`cf`) - Scrolled up and something new arrives below
- `static/js/cfstage.js` (`cfst`) - A choice field marked "Ordered (stages)
- `static/js/chat.js` (`tc`) - Team chat and notes of a list / project
- `static/js/chatbase.js` (`rx`) - The parts of the agent chat that code loaded at start uses
- `static/js/chatplus.js` (`csd`) - The conversation and the box empties
- `static/js/chatwin.js` - A chat in its own small browser window
- `static/js/chatwins.js` (`cw`) - Several chats at once in the chat side panel, one above the other
- `static/js/choicecard.js` (`cc`) - (agentchat.js) and in task comments (collab.js)
- `static/js/cleanup.js` (`cln`) - "Tidy up the list"
- `static/js/clienterr.js` (`cer`) - The browser's own errors to the server
- `static/js/clientpage.js` (`ms`) - Office > Clients in the layout of the contacts
- `static/js/clients.js` (`cl`) - Package "Team, family, clients"
- `static/js/codecheck.js` (`ckv`) - Settings > Help > Check code: hashes the cached shell files against the server's web manifest, the line to compare with SHA256SUMS of the GitHub release (code integrity stage 3, loaded on demand)
- `static/js/collab.js` (`news`) - News and comments + activity (module "collab")
- `static/js/contacts.js` (`ct`) - Contacts (module "contacts")
- `static/js/contractprop.js` - Contracts in view. An agent that got the event contract_notice proposes ONE sentence about a contract
- `static/js/core.js` (`out`) - Dates, the client state, the API + offline outbox, edit conflicts, routing
- `static/js/countries.js` (`cty`) - Come from the browser in the app
- `static/js/cryptscope.js` - The two lists in the encryption settings: what the server key encrypts and what is stored as it is
- `static/js/ctfold.js` (`ctf`) - The address book in folders
- `static/js/ctlinks.js` (`ct`) - The contacts in the task panel
- `static/js/custview.js` - List dialog > Public link > "
- `static/js/dashboard.js` (`ly`) - News bundled per task, the dashboard and the tasks-by-e-mail settings
- `static/js/davwrite.js` (`dvw`) - Popover and dragging (calendar part A calls dvw_commit)
- `static/js/dayplan.js` (`brief`) - Day planning and the evening review
- `static/js/depchain.js` (`dch`) - Later (list setting "Move dependent tasks along", the whole chain by the same days, see tasks/depchain.py)
- `static/js/detail.js` (`dsw`) - The detail panel of a task
- `static/js/devlink.js` (`dl`) - A private device <-> a piece of office equipment (life/devlink.py)
- `static/js/diagram.js` (`dg`) - Formulas and Mermaid diagrams on knowledge pages
- `static/js/dialogs.js` (`list`) - Modals: the app's own dialogs, the list dialog and the share dialog
- `static/js/discover.js` (`dsc`) - Finding people by e-mail, connection requests
- `static/js/dispo.js` (`dp`) - Resources and disposition -- a tab of the workload view (module "dispo", off by default)
- `static/js/dlgmove.js` (`dw`) - Dialogs can be moved on the desktop
- `static/js/dnd.js` (`td`) - Drag & drop (desktop) and swipe (touch)
- `static/js/docfacets.js` (`dfc`) - The filters of the documents below the file store's tree: groups by sender, type, tags, archive number and custom fields with counts
- `static/js/docfetch.js` (`fx`) - "Receipt fetcher" in Settings > Integrations, below the folder watcher (docscan.js dsc_integrHtml / dsc_integrDraw)
- `static/js/docflows.js` (`dfl`) - Document flows ("Abläufe")
- `static/js/docnotes.js` (`dn`) - Notes on a document
- `static/js/docpages.js` - The page strip of the document view: pages of a PDF deleted or turned, saved as a new version
- `static/js/docpreview.js` (`dpv`) - The Word / Excel preview and "
- `static/js/docs.js` (`dc`) - Documents: the list (cards with a preview)
- `static/js/docscan.js` (`dsc`) - "Scans from your computer"
- `static/js/docsplit.js` (`dsp`) - Documents, . (1) A stack scan split into documents
- `static/js/docview.js` (`dcv`) - The document view. A click on a document
- `static/js/docviews.js` (`dcv`) - Saved views of the documents search
- `static/js/dpmodal.js` - The "Plan my day" / "Fill free time"
- `static/js/drag.js` (`drg`) - The shared core of dragging
- `static/js/dragmulti.js` (`dg`) - Dependencies by dragging and several selected tasks moved at once
- `static/js/dropany.js` (`da`) - Files dragged from the computer onto the window, wherever the view or the open dialog has an upload button
- `static/js/dupprop.js` (`dup`) - Tidy up contacts with an agent
- `static/js/e2e.js` (`e2e`) - "e2e" = end-to-end encryption in the browser: key handling and the encrypt / decrypt helpers the locks build on
- `static/js/envs.js` (`env`) - Environments of a project (Staging, Live, ...)
- `static/js/events.js` (`q`) - Toasts, quick add wiring and the global event handlers
- `static/js/evinvite.js` (`evi`) - Invitations by e-mail to attendees outside Kalmido (the switch in the event editor)
- `static/js/family.js` (`fam`) - The module "Family"
- `static/js/favorites.js` (`fav`) - Favourite lists and projects
- `static/js/favtiles.js` (`fv2`) - Favourites of every kind as a row of symbols in the head bar
- `static/js/feeds.js` (`rss`) - Feeds: the view "Feeds" (follow a feed, OPML import / export, the articles with "Read later")
- `static/js/filereq.js` - File requests. A folder of the file store gets a public link /u/<token>
- `static/js/filetext.js` (`ftxt`) - Search in the file store (names + recognised text, also project files)
- `static/js/flow.js` (`flw`) - The card "Flow" of a project page (block 'flow', projects.js POV_BLOCKS)
- `static/js/fltdlg.js` (`flt`) - The dialog of a saved filter, loaded on demand (lazyload.js module fltdlg; its stand-in filterModal loads it, LD_CALL)
- `static/js/fltkern.js` (`kflt`) - The filter of the shared core at start: kflt_match / kflt_conds / kflt_cond over an area's catalog (2.846.0, #5520; the dialog: fltdlg.js kflt_rows / kflt_dialog)
- `static/js/formguard.js` (`fg`) - Form and its organisation / document, e.g
- `static/js/formq.js` (`fq`) - Questionnaires -- the own questions of a form (team/formq.py)
- `static/js/formula.js` (`fx`) - Calculating with custom fields
- `static/js/fslock.js` (`fsl`) - Locked folders of the file store
- `static/js/fsshare.js` - The ONE Share dialog of folders and files, taken out of the file store (ablage.js ab_share)
- `static/js/ftsearch.js` (`fts`) - The command palette's group "
- `static/js/git.js` (`snip`) - Git integration of project lists
- `static/js/gitrepo.js` - The repository editor of a project list / folder, moved out of git.js and loaded when the list dialog or the folder settings open it
- `static/js/habits.js` (`mx`) - The Eisenhower matrix, habits and the pomodoro timer
- `static/js/helpview.js` (`hv`) - The page "Help": the how-to topics per area, their search, one topic (GET /api/help, helpuser.py; 2.1086.0)
- `static/js/hookin.js` (`whi`) - Inbound webhooks of a list
- `static/js/hubmail.js` (`hbm`) - E-mail as an input of the hub
- `static/js/hubmailbox.js` (`hmb`) - The own mailbox of a workspace and writing from the e-mail filing
- `static/js/icons.js` (`apply`) - Kalmido — self-hosted task manager
- `static/js/importprop.js` (`aim`) - An agent reads old data (today: fixed costs)
- `static/js/integrations.js` (`chn`) - API tokens + scopes, webhooks, public links, calendar apps (CalDAV)
- `static/js/jobchat.js` (`jcd`) - Talking to one job of an agent
- `static/js/keys.js` (`kb`) - ONE registry for keyboard shortcuts instead of a keydown listener per area
- `static/js/lazyload.js` (`ld`) - Modules loaded on demand. Rarely opened areas (the settings dialog, the contacts view, Office & finance)
- `static/js/leave.js` (`lv`) - Working days per person and leave
- `static/js/letteragent.js` (`lta`) - "Let the agent draft an answer"
- `static/js/letterdoc.js` (`ltd`) - At a document of the documents space (docs.js calls ltd_slot)
- `static/js/life.js` (`life`) - Home & life (modules contracts, home, care, health, review, travel, reading)
- `static/js/listadmin.js` (`lm`) - Who archives and deletes a list
- `static/js/listcal.js` - The calendar view of one list, part of the module "
- `static/js/listcolor.js` (`lp`) - List colours: the palette, the accent of an open list, the card edges, folder colours
- `static/js/liste2e.js` (`le2e`) - The lock per list -- data layer
- `static/js/liste2echan.js` (`le2e`) - The list channel of a list with the lock
- `static/js/liste2efile.js` (`le2e`) - Files of lists with the lock, encrypted with the list key
- `static/js/liste2eui.js` (`le2u`) - The lock per list -- dialogs and display
- `static/js/listedit.js` (`inline`) - List editing, keyboard reordering, recent lists
- `static/js/listhead.js` (`o3c`) - Themes, header strips of lists and folders, small moments
- `static/js/listprint.js` (`lex`) - A list / project as CSV and as a printable page
- `static/js/liveparts.js` (`lp`) - Live updates per area: /api/version carries a change counter per area, so a change in comments, chats, news or calendars refreshes only that part of the screen
- `static/js/lyopts.js` (`lyo`) - The settings of a block in a view built from blocks
- `static/js/lyprop.js` (`lyp`) - An agent proposes how a view is arranged, the person decides
- `static/js/lysets.js` (`lyv`) - Saved arrangements of a view and arrangements sent as templates
- `static/js/mailrules.js` (`mbr`) - Documents from the own mailbox
- `static/js/main.js` - Start-up: loading the state, polling, the service worker
- `static/js/mdtitle.js` - Markdown in task titles
- `static/js/meetprop.js` (`mtg`) - A meeting becomes tasks. The chat with an agent that takes proposal requests from me offers "
- `static/js/mindmap.js` (`mm`) - The mind map a view of a list next to List / Kanban / Timeline
- `static/js/mineboard.js` (`mb`) - "My tasks" as a board, module "
- `static/js/mineorder.js` (`mse`) - "My tasks" in the person's own order
- `static/js/minerules.js` (`mr`) - The dialog of the own rules of "My tasks", module "minerules"
- `static/js/minewait.js` (`mw`) - The view "Waiting for me" (#mine_wait)
- `static/js/miniwin.js` (`mw`) - A list in its own small browser window
- `static/js/move.js` (`umz`) - (kalmido/admin/acctexport.py: start, state polled while it runs, download, delete)
- `static/js/msgpop.js` - the pop-up for new chat messages: one card at the top edge, a tap opens the chat (2.1130.0, #6057)
- `static/js/msvview.js` (`msvv`) - Several Kalmido servers in one app, the merged view
- `static/js/multiedit.js` (`me`) - Editing several selected tasks at once in the task panel
- `static/js/multilist.js` (`ml`) - A task in several lists without a copy
- `static/js/multisel.js` (`ms`) - The selection mode of a list of records, shared by the contacts (contacts.js bk_*)
- `static/js/navmenu.js` (`nav`) - The editor of the areas' menus
- `static/js/newsletter.js` (`nwl`) - The contacts, segments and consent and syncs them with a newsletter service (listmonk; Brevo / CleverReach as a preview)
- `static/js/notelock.js` (`ln`) - Lock a task's note with one
- `static/js/notesall.js` (`qn`) - The notes of all lists and projects in one place
- `static/js/notetrash.js` - The notes of a project in the trash
- `static/js/objprop.js` - An agent's change of a core object as a proposal (kind "obj_patch")
- `static/js/objsave.js` (`obj`) - The browser side of the shared core
- `static/js/offcache.js` (`oc`) - The offline start state in IndexedDB, loaded on demand (lazyload.js)
- `static/js/office.js` (`ofc`) - Equipment + sets, text blocks, framework contracts, settings
- `static/js/office_agreements.js` (`agr`) - Business contracts and insurances in the office, grouped by kind, with the contribution per month and the next cancellation date
- `static/js/office_assets.js` (`ast`) - Members never get these fields (the server leaves them out)
- `static/js/office_bank.js` (`bnk`) - (CSV export of the bank with a column mapping like the household budget, CAMT.052 / .053 XML or MT940)
- `static/js/office_bankacc.js` (`bka`) - The bank accounts of the office as master data
- `static/js/office_banknorc.js` (`bnr`) - The bank bookings without a receipt (tab "Bank", view "Without receipt"; admins of the office area only)
- `static/js/office_bankrules.js` (`brl`) - Bank rules -- bookings of a statement marked on their own (private, ignore, no receipt needed)
- `static/js/office_bookarch.js` (`bka`) - Office & finance, the booking archive
- `static/js/office_books.js` (`bk`) - Admins of the office area only (a personal office: its owner)
- `static/js/office_cand.js` - The candidate card: one receipt / invoice that can match a booking, with preview, amount, date and why it fits
- `static/js/office_cards.js` (`cc`) - Credit card statements (Office > Credit cards)
- `static/js/office_cashbook.js` (`cb`) - The cash book in the office (tab "Cash book", menu group Money, admins only)
- `static/js/office_cashflow.js` (`rk`) - In and goes out, actual (paid / past)
- `static/js/office_cfiles.js` (`dma`) - PDF files of a framework contract (the signed contract, addenda)
- `static/js/office_datev.js` (`dv`) - Office & finance, the DATEV booking batch export
- `static/js/office_datevimp.js` (`dimp`) - Office & finance, the DATEV import
- `static/js/office_docproject.js` (`dpj`) - Office & finance: a quotation / invoice / credit note bound to a project
- `static/js/office_docs.js` (`ofd`) - The quotations tab of the Office view: the list and the editor (the server computes the sums in kalmido/office/calc.py)
- `static/js/office_doctpl.js` (`dt`) - Templates with {{variables}} (three samples in German / English to take over)
- `static/js/office_dunning.js` (`dun`) - Payment reminders suggested for overdue invoices + the GiroCode
- `static/js/office_fints.js` - The direct bank fetch over FinTS of a bank account of the office (tab Bank, button "Fetch from bank")
- `static/js/office_import.js` (`oim`) - Archive list in the documents tab
- `static/js/office_kpi.js` (`kp`) - Revenue received this month and this year against the year before (a small bar per month, this year in the accent, the year before faint)
- `static/js/office_leads.js` (`lead`) - Leads before the sales pipeline: the first column of the pipeline board, with source, next step and follow-up day
- `static/js/office_ledger.js` (`ldb`) - Office & finance, the balance sheet with double-entry bookkeeping
- `static/js/office_letterhead.js` (`bp`) - (page 1 = first page, page 2 = following pages)
- `static/js/office_letterlinks.js` (`ltk`) - At a letter: the linked documents (answers / reply)
- `static/js/office_lettermail.js` (`ltm`) - Send a letter by e-mail (PDF attached)
- `static/js/office_letters.js` (`lt`) - Letters in the office (tab "Correspondence", admins of the office area)
- `static/js/office_logbook.js` (`lb`) - (office_travel.js renders lbHtml())
- `static/js/office_meals.js` (`bw`) - Entertainment receipts (Bewirtungsbelege)
- `static/js/office_numranges.js` (`onum`) - Number ranges -- the office admin sets the next running number of every series (quotation, invoice, credit note, reminder, delivery note)
- `static/js/office_packs.js` (`pkc`) - Office & finance > Settings > Packs
- `static/js/office_parts.js` (`tp`) - Title page lists them like services (position kind 'part' with a quantity)
- `static/js/office_payonline.js` (`pol`) - Office & finance, online payment of invoices
- `static/js/office_peppol.js` (`pep`) - Office & finance, e-invoices over the Peppol network
- `static/js/office_periods.js` (`pl`) - Office & finance, locking accounting periods + the export for the tax auditor
- `static/js/office_pipeline.js` (`pp`) - Stages inquiry, quotation sent, order and lost
- `static/js/office_procdoc.js` (`pd`) - The procedure documentation (GoBD)
- `static/js/office_receipts.js` (`rcl`) - The receipts list of the bookkeeping over all months (#office/books/receipts, "All receipts" below "Receipts this month")
- `static/js/office_recurring.js` (`rin`) - From a template invoice. The editor of an invoice offers "
- `static/js/office_reprice.js` (`orp`) - The dialog "Adjust prices…" of a quotation draft (module "reprice")
- `static/js/office_rights.js` (`orr`) - The page "Rights" of the office
- `static/js/office_sheet.js` (`dk`) - The part editor (office_parts.js)
- `static/js/office_subs.js` (`abo`) - Fixed costs marked as a subscription with price, repeat, notice period, users, "
- `static/js/office_taxdates.js` - A load still under way while a change is saved answered with the old state after the
- `static/js/office_terms.js` (`agb`) - The office's terms and conditions (AGB)
- `static/js/office_travel.js` (`rk`) - Their receipts (Kalmido keeps no receipt images: they live in DATEV, only the tick "in DATEV" + an optional DATEV number)
- `static/js/office_tree.js` (`oft`) - The office's document areas as trees in the panel
- `static/js/office_undo.js` (`oun`) - Undo for the editors that save every change at once
- `static/js/office_walk.js` - The walk-through of open credit card positions and bank bookings, one after the other with their candidate cards
- `static/js/officeagents.js` (`oa`) - Agents in the office (Office & finance)
- `static/js/oinvview.js` (`oinv`) - The organisation settings for inviting people by e-mail
- `static/js/oneway.js` (`dv`) - The mark "one-way step" of a task (reason, a person's yes)
- `static/js/orgcrypt.js` (`oc`) - Settings for the server-side encryption of an organisation (state and recovery key); not the browser encryption of e2e.js
- `static/js/orgexport.js` (`ox`) - Encrypted archive in the background (kalmido/admin/orgexport.py)
- `static/js/orgschema.js` - The field schema of an organisation, module "
- `static/js/orgvis.js` (`ov`) - Who sees an organisation list
- `static/js/palette.js` (`tour`) - Keyboard shortcuts, the command palette, the welcome tour
- `static/js/paperless.js` (`pl`) - Paperless-ngx connection in the settings of the documents (self-hosted servers only): preview, mapping and background import
- `static/js/pdfopt.js` (`po`) - "Optimise PDF" in the document view, the selection bar and the documents settings
- `static/js/pdfview.js` (`pv`) - The PDF preview
- `static/js/photometa.js` - Photo metadata on upload. The server removes GPS, camera and capture time from uploaded photos (kalmido/files/photometa.py)
- `static/js/pinboard.js` (`wg`) - A colour per block for everyone in the project (lists.page_style)
- `static/js/playbook.js` (`pb`) - The Playbook of a list or a folder
- `static/js/points.js` (`spt`) - Story points of tasks (tasks.points 1 2 3 5 8 13, shown where the list has them on: lists.points_on)
- `static/js/polls.js` (`tpo`) - Scheduling polls -- several proposed times, people vote through a public link, the winning time becomes an event with one click
- `static/js/popovers.js` (`dp`) - Popovers (date, priority, list, tags, reminders, repeat ...)
- `static/js/portal.js` (`ptl`) - Customer reports in the task panel
- `static/js/projects.js` (`pov`) - Projects: status, progress, overview, dependencies, custom fields
- `static/js/projtime.js` (`tz`) - The tracked time of a project in a window
- `static/js/propkinds2.js` (`pk2`) - Review dialog of the agent proposal kinds "inquiry" (becomes a project with tasks, shoot days and a quotation draft) and "setup"
- `static/js/props.js` (`pz`) - The properties of a project
- `static/js/pubvideo.js` - The customer page of a video sign-off (/s/q/<token>, videos/review.py vdr_sig_html)
- `static/js/purposemods.js` - The switch "Switch on all modules" under "What do you use Kalmido for?" (Settings > Modules and the first-run setup)
- `static/js/quickadd.js` (`ms`) - The quick-add parser (six languages)
- `static/js/quickadd2.js` (`qa2`) - Quick add, second part: @person (assign)
- `static/js/quotes_dada.js` (`qd`) - The Dada quote of the day on the sign-in page and on Today (loaded on demand: lazyload.js LD_MODS quotes; account.js qd_slot draws it)
- `static/js/quotes_dada_es.js` (`qd`) - The Spanish texts of the Dada quote of the day (QD_TR.es; loaded on demand with the quotes for a Spanish interface: lazyload.js LD_MODS quotes_es)
- `static/js/quotes_dada_fr.js` (`qd`) - The French texts of the Dada quote of the day (QD_TR.fr; loaded on demand with the quotes for a French interface: lazyload.js LD_MODS quotes_fr)
- `static/js/quotes_dada_it.js` (`qd`) - The Italian texts of the Dada quote of the day (QD_TR.it; loaded on demand with the quotes for a Italian interface: lazyload.js LD_MODS quotes_it)
- `static/js/quotes_dada_nl.js` (`qd`) - The Dutch texts of the Dada quote of the day (QD_TR.nl; loaded on demand with the quotes for a Dutch interface: lazyload.js LD_MODS quotes_nl)
- `static/js/readlater.js` (`rdl`) - The view "Read later" (area Reading, part of the module "reading", loaded on demand with bookmarks.js: lazyload.js LD_MODS, styles in static/css/bookmarks.css)
- `static/js/receipts.js` (`rc`) - An agent's suggestion waits here with Accept / Reject (one undo step each: reopen)
- `static/js/recent.js` - "Recently edited": the overview "All workspaces" of Knowledge, Files and Reading and the start page block (GET /api/recent)
- `static/js/refs.js` (`rf`) - References between things
- `static/js/related.js` (`rt9`) - Related tasks. A folded "Related tasks"
- `static/js/reloadguard.js` (`rl`) - Rl_waitServer(): the page and the stylesheet answer with 200 (used before the automatic reload of core.js verReload)
- `static/js/render.js` (`cfk`) - Rendering: the shell (sidebar, header, tabs)
- `static/js/review.js` (`rvw`) - The review step of a list
- `static/js/richcopy.js` (`rcp`) - Copying a chat message with its formatting
- `static/js/roadmap.js` (`rm`) - The roadmap
- `static/js/rowswipe.js` (`rsw`) - Swiping a row sideways, one shared helper (shared core) for the task row, the news and the swipe to reply on a message; holds live redraws while a finger is on the row
- `static/js/rowsym.js` (`rsy`) - Task rows: a level (all | key | calm | custom, default key)
- `static/js/rules.js` (`rul`) - Rules of a list ("When ... then ...")
- `static/js/sbnav.js` (`sbp`) - The sidebar's messenger rows
- `static/js/secdrag.js` (`sb`) - Where a dragged section or board column lands (mouse and long press on a phone)
- `static/js/sectpl.js` - Section templates, module "
- `static/js/selfdelete.js` - Settings > Account > Delete account
- `static/js/servers.js` (`msv`) - Kalmido servers (work + home)
- `static/js/sesview.js` - Settings > Account > Active sessions
- `static/js/setcore.js` (`wp`) - The parts of the settings the app needs from the start
- `static/js/setreset.js` (`rs`) - Settings > Account > Reset settings
- `static/js/settings.js` (`set`) - Settings: notifications, Web Push, autosave settings, personal agents, import
- `static/js/sharedlg.js` (`folder`) - Head, People (the owner first, roles, "Add", by e-mail address, what the roles may do)
- `static/js/sharews.js` (`sh`) - ("Belongs to: <organisation> (organisation)" / "Private")
- `static/js/sheetbook.js` (`shb`) - Several sheets in one table, loaded with the tables (lazyload.js)
- `static/js/sheetchart.js` (`shc`) - The simple chart of a table - bars or a line from its columns, plain SVG (no chart library)
- `static/js/sheetdrag.js` (`sd`) - Bottom sheets on phones can be dragged taller / shorter and swiped down to close
- `static/js/sheetfill.js` (`shfl`) - Quick entry in a table, loaded with the tables (lazyload.js)
- `static/js/sheetfmt.js` (`shfm`) - The format of a table's cells and its colour rules, loaded with the tables (lazyload.js)
- `static/js/sheetfold.js` (`shf`) - Tables in folders. The folders of the tables live in the file store below the workspace
- `static/js/sheetgrid.js` (`sg`) - A list like a spreadsheet, desktop with a fine pointer
- `static/js/sheetgroup.js` (`shg`) - Tables, grouping by one column with subtotals
- `static/js/sheetkinds.js` (`shk`) - Tables, more column kinds, rows / columns kept in view, print and the history of the cells
- `static/js/sheetmotion.js` (`an`) - Bottom sheets, dialogs and the dimming layer move in and out on phones
- `static/js/sheetmove.js` (`shmv`) - Move rows and columns of a table, loaded with the tables (lazyload.js)
- `static/js/sheetpivot.js` (`spv`) - The pivot sheet of a table, loaded on demand (lazyload.js, module sheetpivot)
- `static/js/sheetprint.js` (`shp`) - Tables, the print view as a PDF
- `static/js/sheetprop.js` - Table rows as tasks, proposed by an agent
- `static/js/sheets.js` (`shv`) - Tables, "Excel in simple" with Kalmido variables
- `static/js/sheets2.js` (`sh2`) - Tables, step 2 -- carrying data over BY BUTTON, never a silent live link
- `static/js/sheetshare.js` (`shs`) - One table shared with single people or agents (read | write)
- `static/js/sheetsio.js` (`shx`) - Tables to and from files: CSV / Excel import in the tables overview and CSV / .xlsx export in a table's menu
- `static/js/sheetsize.js` (`shz`) - Tables, the frame. On a computer the frame of a table has a grip at its bottom right corner
- `static/js/shoot.js` - The storyboard of a shoot, module "
- `static/js/showme.js` (`shw`) - "Show me": the spotlight of the tour on the places of an agent's message, loaded on demand (2.1086.0)
- `static/js/sidebar.js` (`folder`) - Multi-select bar, filter lists and the list order in the sidebar
- `static/js/sideviews.js` (`sv`) - Saved views of the sidebar, e.g
- `static/js/signoff.js` (`sg`) - Approval links with a simple electronic signature - on a sent quotation (office)
- `static/js/spacemove.js` (`mv`) - Moving data between the private space and an organisation
- `static/js/splitview.js` - The split view on a wide screen, loaded on demand while it is on
- `static/js/sprints.js` (`spr`) - Sprints of a project list
- `static/js/sprints2.js` (`spr`) - Sprints of a project list, the dialogs and the writes
- `static/js/srvagent.js` (`srv`) - The setup of a server agent ("Kalmido AI")
- `static/js/stats.js` (`stl`) - The statistics view
- `static/js/supporter.js` (`sup`) - /api/supporter answers 404
- `static/js/supportview.js` (`sgv`) - Settings > Account > Support access
- `static/js/swimlanes.js` (`swl`) - Kanban swimlanes
- `static/js/swipenav.js` (`swn`) - Leafing with a swipe, one helper for the full screen of a document (pdfview.js)
- `static/js/tablecells.js` (`tc`) - Lists like a table. #1217: move a column by dragging its title (owner / list admins, mouse and pen; phones keep "Shown fields…")
- `static/js/tagsel.js` (`dt`) - Parts the file store (ablage.js)
- `static/js/tagsview.js` - Tags overview
- `static/js/tapdone.js` (`tp`) - "Tap to complete" of a list
- `static/js/taskbell.js` (`tbl`) - The bell of one task -- As the list / Muted / Urgent, per person
- `static/js/templates.js` (`tpl`) - Templates and statistics
- `static/js/tilesize.js` (`ts`) - The size of the cards of the documents and of the file store (ONE part for both: docs.js viewDocs, abdocs.js abd_toolsHtml / abd_card, tagsel.js through abd_cardsHtml2)
- `static/js/time.js` (`tv`) - Time tracking (module "time")
- `static/js/timeline.js` (`tl`) - The timeline (Gantt)
- `static/js/timesheet.js` (`tsl`) - Monthly timesheets on the time page
- `static/js/tourmods.js` - The short introductions of the areas
- `static/js/trashui.js` (`tr`) - The trash dialogs and views of 2.272.0, loaded on demand
- `static/js/ttypes.js` (`tt`) - Own ticket types per workspace (kalmido/tasks/ttypes.py)
- `static/js/undo.js` (`hist`) - Undo / redo history
- `static/js/undolist.js` - The list "Recent steps": undo across devices up to a chosen step (GET /api/undo, undo.js)
- `static/js/upbar.js` (`up`) - Upload progress with Cancel
- `static/js/videorev.js` (`vdr`) - Video sign-offs, module "videos"
- `static/js/viewmem.js` (`vm`) - Every view keeps its place
- `static/js/views.js` (`dsx`) - Which tasks a view shows (smart lists, filters, sorting, grouping)
- `static/js/vlist.js` (`vl`) - Long task lists draw only the rows near the visible part
- `static/js/voice.js` (`tvc`) - Voice messages in the team chat, loaded on demand (lazyload.js module voice)
- `static/js/whatsnew.js` - The dialog "New for you" after an update
- `static/js/widgets.js` (`wg`) - Every block of a view built with LY (dashboard.js)
- `static/js/wiki.js` (`wk`) - Knowledge pages . Route #wiki (the pages of the current space)
- `static/js/wikie2e.js` (`wke`) - The lock per knowledge space (wiki.js)
- `static/js/wikioff.js` (`wkof`) - "Offline available" per knowledge space
- `static/js/wip.js` (`wip`) - WIP limits of kanban columns (sections.wip_limit; null = none)
- `static/js/wkcm.js` (`wkcm`) - The ONE editor of knowledge pages, on CodeMirror 6 (like SilverBullet)
- `static/js/wkembed.js` (`wem`) - Files of the file store, tables and tasks in knowledge pages (wiki.js)
- `static/js/wkhist.js` (`wks`) - The history of a knowledge page and the text search of the page list
- `static/js/wkimport.js` (`wki`) - The ZIP import of knowledge pages for large archives (wiki.js wk_import)
- `static/js/wklive.js` (`wklv`) - Slash commands of the knowledge editor, the task search, reading styles
- `static/js/wkarea.js` (`wkar`) - The whole knowledge area shared with an agent: Share whole knowledge area…, Exclude folders…, the marks (#5823)
- `static/js/wkshare.js` (`wsh`) - Read-only shares of knowledge pages (wiki.js)
- `static/js/wktags.js` (`wkt`) - 2.371 tags of knowledge pages and the `
- `static/js/workspace.js` (`ws`) - Workspaces: "Private" and the organisations a person belongs to, and the sidebar switch that shows one of them or all
- `static/js/wscolor.js` (`wac`) - Workspace colours: Private stays neutral, an organisation has a colour (its admins choose, every member sees the same)
