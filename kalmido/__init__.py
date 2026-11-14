"""Kalmido server package. app.py is the entry point; docs/ARCHITECTURE.md explains the layout.

The modules are loaded in the fixed ORDER below (it is the order the code had in the former single app.py): routes, request
hooks and error handlers register in that order, and each module may use names of EARLIER modules at import time
(`from ..core.db import connect` at the top). A name of a LATER module is imported inside the function that needs it
(at call time, when every module is loaded) -- that keeps the import graph free of cycles.
"""
import importlib

# 2.102.0 E (#1999): every package belongs to one of five layers, lowest first. A module imports at module level only from
# its own or a lower layer; a higher layer only inside a function. tools/check_layers.py checks it (the import graph of
# 2.96 still has upward imports -- they stand there as known exceptions). A single module may sit in another layer than
# its package (LAYER_OF). The layers do not change ORDER.
LAYERS = (
    ("core", ("core",)),
    ("accounts", ("accounts",)),
    ("domain", ("tasks", "lists", "calendars", "events", "collab", "contacts", "files", "docs", "sheets", "office", "personal",
                "life", "family", "wiki", "hub", "notify", "videos", "receipts", "team")),
    ("integrations", ("integrations", "api", "admin", "paperless", "newsletter")),
    ("agents", ("agents", "assistant", "startup")),
)
LAYER_OF = {"api.common": "core", "accounts.orgback": "domain",
            "core.objects": "domain", "core.writes": "domain", "core.objlight": "domain", "core.objnotify": "domain", "core.objcomments": "domain", "core.objsearch": "domain", "core.objwords": "domain", "core.objweb": "integrations", "core.objcmtweb": "integrations", "core.objlinks": "domain", "core.objlinkweb": "integrations",
            "core.undoweb": "domain",  # 2.747.0 (#5249): the step groups' routes stand on the write path
            "core.undoareas": "domain",  # 2.777.0 (#5254): the areas' undo steps stand on the write path
            "core.addrshare": "domain",  # 2.1071.0 (#5658): the open shares by address replay the areas' share routes
            "docs.mailnamed": "integrations", "agents.apvdiff": "domain"}  # 2.1034.0 (#5304): admin.migrate (the move from SQLite) is gone; 2.149.0 G (#2517): the v1 helpers are infrastructure; 2.365.1 (#3395): orgback calls every area; 2.558.0 (#4709): the shared core stands on the file store and accounts, its routes on the API

ORDER = (
    "core.env",  # 2.149.0 D (#2511): the registry of the environment variables (no imports from the app)
    "core.objhooks",  # 2.558.0 (#4709): what accounts needs of the shared core (filled by core.objects, no imports)
    "core.config",
    "core.schema",
    "core.i18n",
    "core.mailframe",  # 2.420.0 B (#3499): the one HTML frame of every mail
    "core.numtext",  # 2.263.0 (#2976): one reader for typed numbers
    "core.pg",  # 2.37.0 (#1150): the Postgres layer (core.db re-exports it)
    "core.reqtime",  # 2.149.0 B (#2504): request timing (Server-Timing, slow log); first hooks = whole request measured
    "core.db",
    "core.usertz",  # 2.368.3 (#2985): the person's clock (time zone, time format)
    "core.errors",  # 2.149.0 G (#2517): BadInput, Denied, UnknownFields (re-exported at the old places)
    "core.jsonlimit",  # 2.674.0 (#4190): JSON bodies at most 10 MB (a few routes larger on purpose); before every hook that reads a body
    "core.ctx",  # 2.149.0 G (#2517): me()
    "core.dlock",  # 2.235.0 B (#2902): THE check of an agent's data lock (core/access.py calls it)
    "core.conflict",  # 2.269.0 C (#3017): expect_updated_at -> 409 with the current state (Conflict, ccf_check)
    "core.mdedit",  # 2.1111.0 (#5830): change a Markdown text in a targeted way (append, replace a section)
    "core.ratedb",  # 2.306.0 D1 (#2875): rate limits counted for every web process
    "core.ephem",  # 2.622.0 (#3891): short-lived state for every web process (sign-in steps, tickets)
    "core.pgbus",  # 2.622.0 (#3891): signals between the processes of an instance (pg_notify)
    "core.kernretire",  # 2.924.0 (#5069): stage 7 of the shared core, the start check and DROP of an old member table
    "api.common",  # 2.149.0 G (#2517): the /api/v1 route helpers (core layer, see LAYER_OF)
    "core.srchreg",  # 2.1026.0 (#5280): the one registry of the searches + the routes /api/search and /api/v1/search
    "core.tokenhash",  # 2.138.0 C (#1907): upload / calendar tokens as hashes
    "core.ipallow",  # 2.705.0 (#5151): the address rule of a key (API tokens, receipt fetcher keys)
    "core.rls",  # 2.37.0 (#1150): row-level security, applied by init_db
    "core.orgrows",  # 2.662.0 (#4602): the organisation of tasks / comments / events / contacts (triggers, set up by init_db)
    "core.retention",  # 2.152.0 (#2165): deletion periods + the switch of the retention runs
    "core.fkeys",  # 2.152.0 C (#2174): foreign keys of references that had none (orphans cleaned first)
    "core.coltime",  # 2.1115.0 (#5951): the other old time columns per area (CT_MORE, no imports)
    "core.colbool",  # 2.1118.0 (#5952): the old yes / no columns as BOOLEAN (cb_migrate in init_db, core/pg.py reads them as 0 / 1)
    "core.coltype",  # 2.1095.0 (#5306): the old created_at / updated_at / deleted_at as TIMESTAMPTZ (ct_migrate in init_db)
    "core.moneycol",  # 2.755.0 (#5293): the plain money columns as NUMERIC(14,2) (mc_migrate in init_db, mc_text for the readers)
    "core.orgcrypt",  # 2.42.0 (#828): keys per organisation, encryption at rest
    "accounts.session",
    "accounts.setupcode",  # 2.45.0 (#1515): one-time code for the first setup
    "accounts.pictures",
    "accounts.colors",  # 2.47.1 (#1721)
    "accounts.mailtok",  # 2.674.0 (#4382 finding 5): the plus address tokens sealed + hashed (no routes; before login: it seals lazily)
    "accounts.login",
    "accounts.bgjobs",  # 2.193.0 D (#2220): the queue of short background work (mails after an action, back up now) in the database
    "accounts.oidc",
    "core.access",
    "core.objexport",  # 2.1093.0 (#5289): the export register of the shared core (no imports from the app)
    "core.objfollow",  # 2.972.0 (#5285): following an object in the shared core (one table obj_follow: watching + the bell)
    "core.objnotifcap",  # 2.981.0 (#5287): the owner's notification ceilings in the shared core (obj_notif_cap)
    "core.objparts",  # 2.610.0 (#4762): the write layer of a project's side objects (stands on core.access / core.conflict)
    "core.objreact",  # 2.763.0 (#5269): the reactions of the shared core (one table obj_reactions, one rule)
    "core.objseen",  # 2.905.0 (#5284): the read marks of the shared core (one table obj_seen, no routes)
    "core.tplmove",  # 2.905.0 (#5288): templates onto the shared core at the start (owner_id, real types, section templates moved in)
    "core.objretype",  # 2.1101.0 (#5954): obj_history / obj_undo / obj_revoked onto TIMESTAMPTZ / JSONB at the start
    "core.objtags",  # 2.947.0 (#5275): the tags of the shared core (obj_tags, obj_tag_links)
    "core.objversions",  # 2.958.0 (#5281): the versions of the shared core (obj_versions: numbered whole states)
    "core.serializers",
    "core.compress",  # 2.65.0 (#1505): gzip for JSON answers; before core.pages = its after_request hook runs last
    "core.strip",  # 2.191.0 B (#1824): JS / CSS go out without comments (core.pages serves them)
    "core.codemanifest",  # 2.742.0 (#5217): the web manifest's recipe (core.pages serves it, tools/web_manifest.py builds it)
    "core.pages",
    "core.i18nkeys",  # 2.191.0 A (#1410 #2518): the translation keys of the code + their split per module
    "core.i18nparts",  # 2.191.0 A (#1410 #2518): /static/i18n/<code>.core.json + .mod-<name>.json
    "core.instance",
    "core.state",
    "core.csvimport",  # 2.140.0 B (#2134): the statement reader of budget and bank reconciliation
    "core.zipread",  # 2.146.0 (#2453 #2455 #2457): the in-memory ZIP reader of the importers
    "core.merges",  # 2.66.0 (#1835): merging contacts / clients (reversible)
    "core.mt940",  # 2.299.0 A (#3190): MT940 / MT942 statements (after csvimport, before stmtfiles)
    "core.stmtfiles",  # 2.146.0 C (#2455): the uploaded statements of the bank imports (office + budget)
    "core.addrshare",  # 2.1071.0 (#5658): open shares by e-mail address (projects, folders, knowledge pages), redeemed at sign-in
    "lists.lists",
    "lists.groups",
    "lists.grouppics",  # 2.46.0 (#1605)
    "lists.ownership",
    "core.filters",  # 2.846.0 (#5520): the shared core's filter (rules -> SQL / match, no routes)
    "lists.filterrules",  # 2.577.0 (#3356): the rules of a saved filter as SQL (no routes)
    "lists.sections", "lists.seckind",
    "lists.sectpl",  # 2.156.0 C (#2073)
    "lists.folderdefs",  # 2.757.0 (#4501)
    "lists.folders",
    "lists.lmove",  # 2.401.0 (#2924): the dry run of a project's workspace change, what goes along
    "lists.foldershare",  # 2.41.0 (#1420)
    "lists.lffolder",  # 2.352.0 A (#2748): the folders of the lists in the file store
    "lists.listhead",  # 2.83.0 C (#1427)
    "lists.listtrash",  # 2.102.0 A (#1988)
    "tasks.validation",
    "tasks.tasks",
    "tasks.oneway",  # 2.392.0 C (#3370): the one-way mark and the decisions of a task
    "tasks.deliver",  # 2.392.2 (#3365): the delivery state of a task (in progress, parked, waiting)
    "tasks.roadmap",
    "tasks.lifecycle",
    "tasks.tasktrash",  # 2.116.0 A (#2063): the trash period of tasks
    "tasks.attachments",
    "tasks.batch",
    "tasks.mineorder",  # 2.40.0 (#1344)
    "tasks.minerules",  # 2.823.0 (#4773): the own rules of My tasks
    "tasks.delta",  # 2.42.0 (#1376): GET /api/state/delta
    "core.objcomments",  # 2.972.0 (#5272): the comments' core (obj_comments; domain layer, LAYER_OF: it asks the core's roles)
    "core.objsearch",  # 2.981.0 (#5278): the shared search index obj_search (domain layer, LAYER_OF: it asks the core's roles)
    "core.objwords",  # 2.1002.0 (#5279): the shared keyed word index obj_search_words of the sealed texts (domain layer, LAYER_OF)
    "collab.replies",  # 2.33.0 (#1076): before comments / teamchat / agents.chat (they import it)
    "collab.cmttrash",  # 2.530.0 A (#4315): the trash of comments and team chat messages (helpers only)
    "collab.comments",
    "collab.news",
    "collab.integfail",  # 2.367.3 (#2971): an integration stopped working: News + push to who can repair it
    "personal.habits",
    "personal.timetrack",
    "personal.timewipe",  # 2.43.0 (#1434)
    "personal.budgetwarn",  # 2.555.0 (#4570): the budget warning at 80 / 100 % (no routes)
    "accounts.settings",
    "accounts.colwidths",  # 2.742.0 (#4857): the column widths of the lists per person (user setting col_widths)
    "accounts.whatsnew",  # 2.556.0 (#4685): "New for you" after an update (user settings whatsnew_seen / whatsnew_on)
    "lists.favorites",  # 2.40.0 (#1361)
    "lists.listexport",  # 2.116.0 C (#2064)
    "accounts.layouts",  # 2.32.0 (#1063, #983)
    "accounts.layoutsets",  # 2.55.0 (#1069, #1068, #1066)
    "accounts.sideviews",  # 2.156.0 D (#2186): the sidebar's saved views (no routes: user settings side_views / side_view)
    "accounts.onboarding",
    "accounts.users",
    "accounts.orgs",
    "accounts.wsareas",  # 2.409.0 (#3490): areas on / off per workspace (a before_request gate)
    "accounts.navmenus",  # 2.418.0 (#3560): the person's menus of the areas (setting nav_menus, orgs.nav_off)
    "accounts.modcards",  # 2.575.0 (#3778): own module cards, the cap of an organisation's cards (a before_request gate)
    "accounts.orgroles",  # 2.143.0 A (#2151): organisation roles guest / read-only / accounting
    "accounts.spacemove",  # 2.96.0 (#1941): the shared rules of moving data between the private space and an organisation (no routes)
    "accounts.orgout",  # 2.148.1 B (#2483): data leaves an organisation only through its admin (no routes)
    "accounts.tenancy",
    "accounts.orglists",  # 2.35.0 (#1101)
    "accounts.orgtasks",  # 2.574.0 (#3376): an organisation admin's read-only view of its tasks
    "accounts.orgoutreq",  # 2.361.2 (#2923): a member asks back what they brought into an organisation
    "accounts.useradmin",  # 2.88.0 (#1980)
    "accounts.orgretain",  # 2.152.0 A (#2164 #2167)
    "lists.tplextra",  # 2.363.3 (#3134)
    "lists.templates",
    "tasks.dependencies",
    "tasks.depchain",  # 2.67.0 B (#1865)
    "tasks.relations",  # 2.576.0 (#3371): saved relations between tasks (relates to, duplicate of)
    "lists.projects",
    "lists.envs",  # 2.60.0 D (#1514)
    "lists.formula",  # 2.43.0 (#1328): the formula parser (no routes; used by lists.fields)
    "lists.fields",
    "lists.orgfields",  # 2.609.0 (#3373): the field schema of an organisation (linked custom fields)
    "lists.orglabels",  # 2.609.0 (#3373): labels of an organisation (linked project tags)
    "personal.stats",
    "personal.statslife",  # 2.630.0 (#4617)
    "calendars.icalfeed",
    "calendars.caldav",
    "integrations.importers",
    "notify.push",
    "tasks.remindat",  # 2.111.0 C (#2057)
    "notify.alerts",
    "notify.sev",  # 2.36.2 (#1133)
    "calendars.subscriptions",
    "integrations.imp_linear",  # 2.394.0 A (#3377): Linear import (API key / CSV), registers into integrations.importers
    "calendars.davwrite",  # 2.52.0 B (#1128): writing into CalDAV subscriptions
    "calendars.apptbook",  # 2.94.0 B (#1929): appointment booking by customers (public page, no login)
    "calendars.polls",  # 2.98.0 A (#1953): scheduling polls (vote through a link, the winning time becomes an event)
    "admin.bkstore",  # 2.432.0 (#3584): the shared store of the backups (standard library only)
    "admin.backup",
    "admin.offsite",  # 2.143.0 B (#2152): the off-site target of the backups (S3, WebDAV, SFTP)
    "api.v1",
    "notify.caps",  # 2.33.0 (#927)
    "notify.taskbell",  # 2.53.0 C (#1424): the bell of one task per person
    "tasks.watchers",  # 2.473.0 (#3357): delegated to an agent, watchers of a task
    "notify.channels",  # 2.142.0 A (#2145, #2146): Slack / Matrix / Telegram / Signal, e-mails for single events
    "tasks.dayplan",
    "tasks.briefing",  # 2.34.0 (#264)
    "lists.report",  # 2.34.0 (#265)
    "api.openapi",
    "integrations.webhooks",
    "integrations.hookin",  # 2.115.0 A (#2061)
    "agents.core",
    "collab.reactions",
    "agents.chat",
    "agents.jobchat",  # 2.56.0 A (#1791 / #1793)
    "agents.chatprefs",  # 2.233.0 A (#2848): chat settings per person and agent, collected suggestions
    "api.showme",  # 2.1086.0 (#5860): "Show me" -- the named places an agent's message may point at
    "agents.chatnews",  # 2.1039.0 (#5804 #5805): approval cards and questions of the agent chat in the bell's "For you"
    "agents.steps",  # 2.32.0 (#1081 / #1079)
    "agents.quota",  # 2.33.0 (#1045)
    "agents.schedules",  # 2.34.0 (#272)
    "agents.workstyle",  # 2.236.0 (#2904-#2911)
    "agents.workqueue",  # 2.236.0 C (#2906 #2907)
    "agents.control",  # 2.235.0 A (#2891 #2900 #2901)
    "agents.datalock",  # 2.235.0 B (#2902)
    "agents.agentrules",  # 2.235.0 C (#2903)
    "agents.admin",
    "agents.agsees",  # 2.1045.0 (#5822): what an agent sees (the dialog "Edit agent")
    "agents.api",
    "agents.proposals",
    "agents.cleanup",  # 2.39.0 (#1151)
    "agents.propkinds2",  # 2.51.0 B (#1351 #1358)
    "agents.setup",  # 2.44.0 (#1517)
    "agents.srvstarter",  # 2.557.0 C (#4670): the setup of a server agent (defaults, starter pack)
    "agents.mcpremote",  # 2.488.0 (#3363): the hosted MCP access (/mcp, OAuth 2.1, after agents.admin)
    "agents.srvweb",  # 2.571.0 D (#4676): read-only web research of the server agent (web tools, VIES, the gate of a web run)
    "agents.srvagent",  # 2.557.0 B (#4670): the server agent (settings, provider, routes; after agents.mcpremote)
    "agents.srvagent_run",  # 2.557.0 B (#4670): its runs (a queue row of the worker)
    "agents.srvteam",  # 2.569.0 B (#4675): the server agent in team projects (routes; after agents.srvagent_run)
    "lists.playbook",  # 2.39.0 (#1168)
    "tasks.attachtext",  # 2.34.0 (#368)
    "tasks.snippets",  # 2.35.0 (#1095)
    "tasks.multilist",  # 2.71.0 B (#1459): a task in several lists without a copy (after api.v1)
    "tasks.movememo",  # 2.273.0 B (#3042): what a task move ends, restored by a move back (no routes)
    "lists.membermemo",  # 2.550.0 (#4528): what removing a member ends, restored on adding them again
    "agents.gates",  # 2.26.0 (#949)
    "agents.watch",  # 2.392.2 (#3366): the watchdog over agent jobs (stalled, stranded branch)
    "agents.taskdec",  # 2.392.0 C (#3370): the yes to a one-way task
    "agents.waiting",  # 2.392.0 D (#3369): what waits for a person
    "integrations.delivery",  # 2.392.0 D (#3369): the delivery report of a list
    "integrations.taskbrief",  # 2.392.3 (#3368): a work package, the brief of a choice of tasks
    "agents.safety",  # 2.30.0 (#919)
    "agents.usage",
    "lists.custview",  # 2.50.0 C (#329): customer view of public links (no routes; used by lists.public)
    "lists.public",
    "integrations.git",
    "integrations.gitfolder",  # 2.33.0 (#934)
    "integrations.gitbuild",  # 2.151.0 A (#2558)
    "integrations.git_issues",  # 2.394.0 B (#3377): issue import of a repository connection
    "integrations.git_sync",  # 2.394.0 C (#3377): two-way issue sync (hooks into git / tasks.validation)
    "integrations.errorreports",
    "api.projects",
    "lists.sprints",  # 2.60.0 (#343): sprints of project lists (after api.v1: it has token routes)
    "lists.parttrash",  # 2.567.0 A (#4707): sections / sprints in the trash, the trash view of the other parts
    "lists.flow",  # 2.393.2 A (#3374): flow figures of a project (imported by lists.kpis)
    "lists.kpis",  # 2.43.0 (#1328): sum row + key figures (web + token API)
    "lists.orgvis",  # 2.46.0 (#1603): organisation lists visible to the whole organisation
    "api.scopes",
    "api.helpdocs",  # 2.1067.0 (#5819): the help (docs/*.md) for agents: search kind help, GET /api/v1/help(/section)
    "api.helpuser",  # 2.1086.0 (#5820): the help for people in the app: GET /api/help(/section), the web side of search kind help
    "api.v1setup",  # 2.391.0 (#3362): webhooks, API tokens, repository connections through /api/v1 (after git, gitbuild, webhooks, api.v1, api.scopes)
    "collab.notes",
    "wiki.pages",  # 2.49.0 C (#1199): knowledge pages
    "wiki.outline",  # 2.49.0 C (#1201): outline import of the mind map (no storage)
    "sheets.formula",  # 2.89.0 (#1916): tables -- the formula engine (no routes)
    "sheets.shfuncs",  # 2.124.0 A (#2109): SUMMEWENN, SVERWEIS, text and date functions of formulas (no routes)
    "sheets.shfuncs2",  # 2.578.0 (#3462): SUMMEWENNS, VERGLEICH, WENNFEHLER, work days, TEXT ... of formulas (no routes)
    "sheets.vars",  # 2.89.0 (#1916): Kalmido variables of formulas, evaluated per viewer (no routes)
    "sheets.shkinds",  # 2.124.0 B (#2110, #2111): column kinds checkbox / person / link / file, rows / columns kept in view
    "sheets.shhist",  # 2.124.0 B (#2112): the change history of the cells (people and agents)
    "sheets.core",  # 2.89.0 (#1916): sheets, columns, rows, cells, agent batches (no routes; used by sheets.web and part C/D)
    "sheets.shorder",  # 2.631.0 (#4620): ranges of formulas keep their rows / columns when those are moved (no routes)
    "sheets.web",  # 2.89.0 (#1916): the routes of the tables area (/api/sheets)
    "sheets.step2",  # 2.89.0 (#1916, D): step 2 -- rows to tasks / quotation, a list as rows (by button)
    "sheets.shmove",  # 2.96.0 B (#1941): a table to the other workspace (private <-> organisation)
    "sheets.shshare",  # 2.124.0 C (#2113): one table shared with single people / agents (sheet_shares)
    "sheets.shchart",  # 2.124.0 A (#2115): the simple chart of a table (its setting; drawn by static/js/sheetchart.js)
    "sheets.shbook",  # 2.124.0 E (#2116): several sheets in one table (the sheet bar's routes; rights / formulas hang in core)
    "sheets.shfmt",  # 2.578.0 (#3462 C): cell format and colour rules of a table (drawn by static/js/sheetfmt.js)
    "sheets.shpivot",  # 2.671.0 (#3463 b): the pivot sheet of a table (setting, result computed on read, export)
    "collab.teamchat",
    "collab.teamchan",  # 2.113.1 B (#2059): channels, groups, files of the team chat (after teamchat)
    "collab.msgsearch",  # 2.33.0 (#1080)
    "tasks.ftsearch",  # 2.116.0 B (#2065): full-text search of tasks + comments (/api/search)
    "collab.chatsave",  # 2.37.0 (#1159)
    "collab.chatpins",  # 2.62.0 (#1848): pinned chat messages (after teamchat / agents.chat)
    "collab.cchoice",  # 2.41.0 (#1383): answer buttons / approval cards in comments
    "collab.e2e",  # 2.42.0 (#828, #909): end-to-end encryption (keys, encrypted notes / files / DMs)
    "integrations.mailtrim",  # 2.49.0 (#971)
    "integrations.mailtrim_html",  # 2.352.0 D (#2754)
    "collab.notelock",  # 2.48.0 (#1642): a task's note locked with one's own password (needs collab.e2e)
    "collab.liste2e",  # 2.64.1 (#1817): the lock per list (texts encrypted in the browser; needs collab.e2e)
    "collab.liste2eguard",  # 2.64.1 B (#1817): the lock per list on the other ways (API, agents, CalDAV, mail, push, copies)
    "agents.msgpop",  # 2.1130.0 (#6057): the in-app pop-up for new chat messages (after collab.liste2eguard)
    "collab.liste2efile",  # 2.64.2 B (#1817): files of lists with the lock, encrypted with the list key
    "collab.e2eresv",  # 2.640.0 (#3388): id reservations of the E2E record binding (AAD v2: wiki pages, list channel)
    "collab.liste2echan",  # 2.64.2 C (#1817): the list channel (team chat of a list) with the lock
    "wiki.wikie2e",  # 2.64.3 (#1817): the lock per knowledge space (path + text encrypted in the browser)
    "wiki.wkmove",  # 2.96.0 B (#1941): wiki pages and folders to the other workspace (private <-> organisation)
    "wiki.wkembed",  # 2.123.0 C (#2103, #2107): files of the file store and tables in knowledge pages (by reference)
    "wiki.wikiatt",  # 2.99.0 A (#2182): files of knowledge pages (upload, ZIP import / export)
    "wiki.wkshare",  # 2.123.0 B (#2104): read-only shares of pages / folders (people, public link)
    "wiki.wkhist", "wiki.wksearch",  # 2.123.0 A (#2105, #2102, #2106): texts sealed at rest, page history, word index
    "wiki.wktags",  # 2.371 (#3150): tags of pages (hashes in the word index) and the ```abfrage block
    "files.store",  # 2.48.0 (#1207): the file store (Ablage): tree, roles, versions (no routes; the interface of docs / import)
    "files.fsref",  # 2.199.0 A (#2742): reference nodes -- office documents / sheets filed in folders (no routes; the register)
    "files.fsroots",  # 2.199.0 C (#2742): an area's root folder in a workspace's tree (fs_area_roots; no routes)
    "sheets.shfolder",  # 2.199.0 C (#2742): tables in folders (the reference kind 'sheet', the panel's folder tree)
    "wiki.wkfolder",  # 2.200.0 A (#2747): knowledge pages in folders of the file store (the reference kind 'wiki', the tree)
    "wiki.wkv1",  # 2.200.0 C (#1781): knowledge pages for agents (API v1 + OpenAPI; only what is shared with them)
    "agents.apvdiff",  # 2.1068.0 (#5831): what an approval card's step changes in a text (domain layer, LAYER_OF: it reads the areas' texts)
    "wiki.wkfshare",  # 2.200.0 B (#2747): pages reached through folder / page shares (Shared with me, new pages in a shared folder)
    "wiki.wkarea",  # 2.1045.0 (#5823): a whole knowledge area shared with an agent (the dialog's facts; the share is the file store's)
    "wiki.wkstyle",  # 2.371.3 (#3152): the reading style of a knowledge space (PUT /api/wiki/style)
    "files.scan",  # 2.61.0 (#1818): virus scan of uploads (clamd), the later scan, the admin's scanner state
    "files.web",  # 2.48.0 (#1207): the file store's routes for the web app
    "files.fsviews",  # 2.429.0 (#3580): the file store shows only its own folders; "From <area>" collections (read-only)
    "files.fsshnames",  # 2.558.0 (#4693): the names of a listing's shares, one bundled read (no routes)
    "files.fslock",  # 2.353.0 A (#2758): locked folders (names and contents encrypted in the browser)
    "files.fsmove",  # 2.96.0 A (#1941): files, folders and documents to the other workspace (private <-> organisation)
    "files.fstags",  # 2.122.0 B (#2099): tags of files and folders (the documents' tag set of the workspace)
    "files.bulk",  # 2.112.1 A (#2058): several nodes into the trash / back, the ZIP download, the phone scan -> one PDF
    "files.v1",  # 2.48.0 (#1207): the file store in the REST API (files:read / files:write)
    "files.extlinks",  # 2.112.1 B (#2058): external share links of files / folders (/s/f/<token>, no login)
    "files.trashpurge",  # 2.152.0 B (#2165): trash periods of files, wiki, hub mails, tables, pipeline, series, chat (no routes)
    "files.photometa",  # 2.61.0 B (#1819): photo metadata (GPS, camera) removed on upload (no routes; files/upsafe.py)
    "files.upsafe",  # 2.61.0 (#1818 #1819 #1820): the shared upload path - scan, metadata, text recognition (no routes)
    "files.filereq",  # 2.122.0 A (#2097): file requests - a public link /u/<token> through which a client uploads files
    "accounts.sharedefs",  # 2.470.0 (#3596): the sharing defaults of a workspace (external links, file requests)
    "integrations.mail",
    "integrations.exporters",  # 2.142.0 C (#2148)
    "integrations.mailproof",  # 2.1033.0 (#5790): a person proves the own e-mail address (a mailed one-time link)
    "accounts.invite",
    "accounts.sessions",  # 2.115.0 B (#2062): active sessions
    "accounts.supportgrant",  # 2.485.0 (#3939): support access the client grants (hosted)
    "accounts.orginvite",  # 2.115.0 B (#2062): organisation admins invite accounts by e-mail
    "accounts.orgleave",  # 2.361.0 (#2920 / #2922): what leaving / deleting an organisation means for its members
    "accounts.orgback",  # 2.365.1 (#3395): what a person brought in goes back with their leaving (no routes)
    "family.family",
    "family.web",
    "family.pin",  # 2.49.0 B (#1551)
    "family.carddav",
    "family.v1",
    "events.model",
    "events.ics",
    "events.web",
    "events.dav",
    "events.v1",
    "calendars.pollsv1",  # 2.484.0 (#2200): scheduling polls over REST v1 / MCP (read, create)
    "events.invite",  # 2.111.0 B (#2056): invitation mails to external attendees (iMIP)
    "events.evfeed",  # 2.111.0 B (#2056): subscription links of event calendars (GET /ical/ev/<token>.ics)
    "events.freebusy",  # 2.155.0 B (#2077): free / busy of invited people (GET /api/events/freebusy)
    "contacts.model",
    "contacts.carddav",
    "contacts.web",
    "contacts.v1",
    "contacts.bulk",  # 2.46.1 (#1554): delete / move several contacts at once
    "contacts.merge",  # 2.66.0 A (#1835): merging duplicate contacts (reversible)
    "contacts.orgbooks",  # 2.52.0 C (#1438): address books an organisation owns
    "contacts.ctxlist",  # 2.119.1 A (#2080 #2084 #2085): CSV import / export, duplicate hint, managing the groups
    "contacts.history",  # 2.119.1 B (#2083): the history on a contact's card
    "contacts.ctfolder",  # 2.351.0 B (#2749): address books and contacts in folders (reference kinds, the folder tree)
    "life.model",
    "life.bookmarks",  # 2.97.0 A (#1950): bookmarks with a preview, tags and search (Karakeep fills the same store)
    "life.karakeep",
    "life.web",
    "life.v1",
    "life.budget",  # 2.72.0 (#1333): the household budget
    "life.devlink",  # 2.140.0 B (#2136): a private device <-> office equipment
    "life.budget_web",
    "life.rss",  # 2.85.0 B (#1162): feeds
    "life.rss_web",
    "life.reading",  # 2.172.0 B (#2679): read later per space
    "life.tripcost",  # 2.173.0 A (#2680): from a trip to its travel expenses in the office
    "team.clients",
    "team.clients_bulk",  # 2.47.3 (#1733): several clients at once
    "team.clientmerge",  # 2.66.0 B (#1835): merging duplicate clients (reversible)
    "office.clientlink",  # 2.59.0 A (#1735): the address book search of the client dialog
    "team.workload",
    "hub.holidays",  # 2.461 (#3773): public holidays per country (data files), used by hub.absence
    "hub.absence",  # 2.50.0 A (#1195): absences + German public holidays
    "hub.leave",  # 2.125.0 A (#2118, #2117): working days per person, vacation account + requests
    "hub.abscal",  # 2.155.0 B (#2076): holidays + absences in the calendar views, their subscription link
    "hub.dispo",  # 2.50.0 A (#1194): resources and disposition (bookings of crew and equipment)
    "hub.agentdispo",  # 2.51.0 C (#1355): shoot planning by agents (event drafts, options), the disposition in the REST API
    "hub.hubmail",  # 2.84.0 A (#1198): e-mail as an input of the hub (mails filed with clients / projects)
    "hub.hmv1",  # 2.483.0 (#1902): the filed mails in the REST API v1 (read only, agents too)
    "hub.mailview",  # 2.141.0 B (#2140, #2139): the HTML view of a filed mail, a task / an event made from it
    "hub.mailbox",  # 2.141.0 A (#2141, #2138): the own mailbox of a workspace, sending from the e-mail filing
    "hub.mailrules",  # 2.581.0 (#4804): documents from the own mailbox (mail rules)
    "office.packs",  # 2.36.1 (#1021): country packs (data), used by office.model
    "office.homecur",  # 2.189.0 (#2475): the office's home currency (no routes; used by office.model and the money modules)
    "office.oubar",  # 2.747.0 (#5252): labels and barriers of the office's undo steps (core imports only; ledger, invoices, letters use it)
    "office.model",  # 2.36.1 (#1021): office & finance (B); C/D append office.calc, office.docs, office.pdf
    "office.web",
    "office.rights",  # 2.187.0 (#2476): office access rights (groups, levels per area; a before_request gate)
    "office.calc",  # 2.36.1 (#1021): the quotation calculator (C, no imports)
    "office.sheet",  # 2.47.0 (#1216): the shoot calculation sheet + industry packs (C, imports office.calc)
    "office.catalog",  # 2.76.0 A (#1023): the pack catalogue, installed packs per office area (imports office.sheet)
    "office.costs",  # 2.47.0 (#1645, #1649): producing per document, purchases of accepted quotations (part D, no routes)
    "office.docs",  # 2.36.1 (#1021): quotations (C)
    "office.pdf",  # 2.36.1 (#1021): the PDF writer (D, no kalmido imports)
    "office.einvoice",  # 2.38.0 (#1021 P5, F2): e-invoice XML (CII EN 16931 / XRechnung) from the snapshot, used by office.pdfweb
    "office.einvoice_in",  # 2.146.0 A (#2451): incoming e-invoices (UBL / CII, embedded in ZUGFeRD PDFs; no routes, used by docs.store)
    "office.pdfweb",  # 2.36.1 (#1021): quotation PDF + company logo routes (D; the writer office.pdf has no routes)
    "lists.shoot",  # 2.636.0 (#4565): the shot list PDF of a shoot (after the PDF writer, office.pdf)
    "hub.callsheet",  # 2.855.0 (#1956): the call sheet of a shoot day (Film & Video), its PDF (after the writer and lists.shoot)
    "office.docref",  # 2.199.0 B (#2742): quotations / invoices filed in folders (reference kind office_doc, the folder routes)
    "office.oftref",  # 2.351.0 A (#2823): generated documents, letters, receipts filed in folders (reference kinds)
    "office.oftree",  # 2.351.0 A (#3312): the office's document areas as trees in the panel (folders + 20 newest)
    "office.signoff",  # 2.50.0 C (#1200): approval links with a simple electronic signature (quotations, list acceptance)
    "office.ledger",  # 2.36.2 (#1021, #1142, E): finalising, structured company data, office log
    "office.chain",  # 2.531.0 (#4497): the hash chain over finalised documents (used by office.ledger)
    "office.olock",  # 2.152.0 C (#2168 #2169): legal retention locks (booked receipts, logbook)
    "office.invoices",  # 2.38.0 (#1021, F1): invoices, credit notes, reminders, payments, sending, DATEV inbox
    "office.peppol",  # 2.154.0 B (#1960): e-invoices over Peppol (own provider account): ids, connection, UBL, send + status
    "office.payonline",  # 2.469.0 (#3459): online payment of invoices (own provider account): connection, pay link, webhook
    "office.delivery",  # 2.120.0 D (#2089): delivery notes / proofs of service, the timesheet of an invoice
    "office.abschlag",  # 2.120.0 A (#2087): progress / final invoices, cash discount (Skonto)
    "office.offerlink",  # 2.356.0 C (#3003): quotation <-> invoices made from it (links, asking before a second invoice)
    "office.doclang",  # 2.40.0 (#1381): language switch of drafts swaps the standard texts (no routes; used by office.docs)
    "office.countries",  # 2.40.0 (#1372): the ISO 3166-1 alpha-2 list (no routes)
    "office.contacts_cl",  # 2.40.0 (#1380): contact persons of a client (no routes; used by team.clients, office.docs, legacyimport)
    "office.legacyimport",  # 2.39.1 (#1182): legacy import (clients / services / equipment from .xlsx, archive of old PDFs)
    "office.archiveedit",  # 2.81.0 B (#1834): correct an archived document afterwards (client, tax lines, paid) + its history
    "office.parts",  # 2.47.0 (#1215): parts of a quotation (Teilangebote): routes, title page calculation, invoice modes
    "office.repcalc",  # 2.1041.0 (#5812): the repricing's calculation (pure, no routes)
    "office.reprice",  # 2.1041.0 (#5812): repricing a quotation (Nachkalkulieren), the calculation in office/repcalc.py
    "office.years",  # 2.593.0 (#4891): the years with data of the office lists (no routes)
    "office.travel",  # 2.47.3 (#1022, part B): travel expenses (trips, receipts, evaluation, billing on)
    "office.outlays",  # 2.121.0 C (#2094): bill receipts of the bookkeeping on to a client (outlays)
    "office.vma",  # 2.95.0 (#1932): the per diem rates (BMF tables per year) and its calculation (pure functions)
    "office.vmareport",  # 2.95.0 A (#1932): the per diem report per person and year (JSON, PDF, Excel, CSV), the rates
    "office.vmaimport",  # 2.95.0 B (#1932): the import of a per diem spreadsheet (preview, import, undo)
    "office.mealpdf",  # 2.119.0 A (#2288): the PDFs of the entertainment receipts (no routes)
    "office.meals",  # 2.119.0 A (#2288): entertainment receipts (Bewirtungsbelege): meals, approval + log, choices, evaluation
    "office.mealpay",  # 2.603.0 (#4927): an entertainment receipt as the proof of its bank / cash / card line
    "office.cashflow",  # 2.47.3 (#1652, part B): cash flow per month + fixed costs
    "office.cfstart",  # 2.123.0 D (#2341): start balance, corrections by hand and real balances of the cash flow
    "office.cfbank",  # 2.124.0 D (#2342): the balances of the bank statements in the cash flow (no routes)
    "office.pipeline",  # 2.50.0 B (#1196): the sales pipeline
    "office.leads",  # 2.94.0 A (#1930): leads before the pipeline (stage lead): convert, CSV import, agents
    "office.agentdeals",  # 2.644.0 (#3663): agents read / add inquiries and deals, set a stage
    "office.kpi",  # 2.50.0 B (#1197): the business figures
    "office.datev",  # 2.47.3 (#1460): DATEV booking batch (EXTF) of invoices, credit notes and payments
    "office.periodlock",  # 2.148.0 A (#2471): locked accounting periods (GoBD)
    "office.gdpdudtd",  # 2.188.0 A (#2498): the official GDPdU DTD (text) for the auditor ZIP
    "office.gobdexport",  # 2.148.0 A (#2471): the export for the tax auditor (GDPdU index.xml + CSV)
    "office.datevzip",  # 2.148.0 B (#2470): DATEV batch + receipt images (document.xml) as one ZIP
    "office.datevin",  # 2.120.0 C (#2090): DATEV batch input side (receipts, travel expenses) + its accounts route
    "office.okern",  # 2.784.0 (#5366): office kinds on the core's trash (before their modules: office.datevimp registers osupplier)
    "office.datevimp",  # 2.148.0 D (#2458): DATEV import (debtors / creditors, opening balances of a booking batch)
    "office.bookarch",  # 2.414.0 (#3502): the booking archive of past DATEV years (read-only)
    "office.taxforms",  # 2.467.0 (#3456): Anlage EUeR and annual VAT return line by line
    "office.taxcheck",  # 2.589.0 (#3458): the tax check before filing (traffic light)
    "office.euerbasis",  # 2.603.0 (#4927): the basis of the EUeR per year (bank and cash, strict | receipts)
    "office.books",  # 2.90.0 A (#1921): bookkeeping light: income/expense statement (EUeR), VAT return figures, tax reserve, receipt photo
    "office.euercmp",  # 2.603.0 (#4921): the EUeR next to the year before (display only; older years from the DATEV archive)
    "office.bkexport",  # 2.147.0 (#2461): the neutral bookkeeping export (booking list CSV + documents / receipts ZIP)
    "office.catacct",  # 2.121.0 (#2093): receipt categories with an SKR03 / SKR04 account (no routes; shown by office.books)
    "office.receiptlist",  # 2.153.0 (#2055): receipts list over all months with filters + its CSV / ZIP for the tax adviser
    "office.rcsubmit",  # 2.356.0 D (#3129): members hand in receipts to the bookkeeping
    "office.rcfolder",  # 2.957.0 (#4910): receipts of the credit cards and the bank file themselves into month folders
    "office.bank",  # 2.90.0 B (#1921): bank reconciliation: CSV / CAMT import, matching bookings to invoices and receipts
    "office.bankrules",  # 2.299.0 B (#3191): bank rules: marking bookings by rule, rules learned from confirmations
    "office.bankacc",  # 2.470.0 (#3596): the bank accounts of an office as master data
    "office.fints",  # 2.616.0 (#2473): the direct bank fetch over FinTS (PIN/TAN), into the file import
    "office.rethold",  # 2.545.0 (#4595): the switch "Extend the lock" (tax audit) of an office
    "office.banknorc",  # 2.299.0 C (#3192): bank bookings without a receipt: the list, the counter, the reminder task
    "office.bankvend",  # 2.425.0 B (#3451): recurring providers of the bank bookings, their missing invoices
    "office.ccread",  # 2.444.0 (#3447): reading a credit card statement (PDF), one reader per provider's layout
    "office.cards",  # 2.444.0 (#3447): credit card statements: cards, PDF positions
    "office.cardlines",  # 2.444.0 (#3447): their positions, the search for the receipts, the match
    "office.candthumb",  # 2.778.0 (#5383): the preview address of a candidate receipt (no route)
    "office.cardnorc",  # 2.444.0 (#3447): the reminder of the positions without a receipt, the rows of the exports
    "office.doctpl_samples_es", "office.doctpl_samples_fr", "office.doctpl_samples_it", "office.doctpl_samples_nl",  # 2.449.0 (#3768): the samples in other languages (data)
    "office.doctpl_samples",  # 2.117.0 B (#2283): the letter samples of the document templates (data, no routes)
    "office.doctpl",  # 2.93.0 A (#1927): document templates with variables, documents as PDF, signature by customer link
    "office.privacy",  # 2.154.0 C (#2192): data protection sheets of a client (DPA, information, consent): mail, ways back, status
    "office.terms",  # 2.113.2 (#2253): terms and conditions (AGB) as PDF per language, sent with quotations
    "office.letters",  # 2.153.0 (#2028): letters (correspondence): recipient, text, signature, DIN 5008 PDF, status, filing
    "office.letterlinks",  # 2.153.0 (#2028): letter <-> document links, history, deadline -> task, follow-up, reference line
    "office.lettermail",  # 2.153.0 (#2029, #2030): letters by e-mail with the answer linked, text blocks
    "office.mailsig",  # 2.439.0 (#3617): the person's signature, sender name, answer address of the office mails
    "office.letteragent",  # 2.153.0 (#2031): agents draft letters (API v1, MCP, event at a document)
    "videos.review",  # 2.99.1 A (#1959): video sign-off with comments at a timecode (links only), customer link = signoff kind video
    "videos.vdrescue",  # 2.530.0 D (#4316): video sign-offs go to their own trash before a hard delete of task / list / client
    "videos.vdmedia",  # 2.641.0 (#4769): the sign-off of images and PDFs of the file store (the bytes of a version)
    "office.logbook",  # 2.93.0 B (#1928): the logbook (vehicles, drives, change log, year report, mileage allowance)
    "office.cashbook",  # 2.121.0 B (#2095): the cash book (cash boxes, entries, cancellations, day closings, CSV / PDF)
    "office.procdoc",  # 2.148.0 C (#2472): the procedure documentation (GoBD), prefilled, versions, Markdown / PDF
    "office.taxdates",  # 2.90.0 C (#1922): tax dates as recurring tasks (VAT return, income tax prepayments, trade tax)
    "office.agentdocs",  # 2.51.0 A (#1348, #1350): agents in the office: drafts, payment suggestions, the switches (API v1 + routes)
    "office.agentinvoice",  # 2.568.0 B (#4673): an agent's invoice draft without a quotation (time of a project / free positions)
    "office.agreements",  # 2.92.0 A (#1925): business contracts and insurances (term, notice, contribution, cash flow, deadline task)
    "office.contractfiles",  # 2.117.0 B (#2285): PDF files of a framework contract (upload, view, replace, trash)
    "office.agrref",  # 2.351.0 B (#2749): framework contract PDFs and contracts & insurance in folders (reference kinds)
    "office.assets",  # 2.92.0 B (#1931): equipment value: purchase, depreciation, current value, insurance list
    "office.ledger_dbl",  # 2.666.0 (#3461): double-entry bookkeeping, trial balance, profit and loss, balance sheet (GmbH / UG)
    "office.eqcare",  # 2.558.0 C (#4591): warranty end and maintenance of equipment as tasks (no routes)
    "office.bpread",  # 2.120.0 E (#2091): the PDF reader of the own letterhead (no routes, no kalmido imports)
    "office.letterhead",  # 2.120.0 E (#2091): the own letterhead behind the office documents (upload, margins, preview)
    "files.officeprev",  # 2.92.0 C (#1926): preview + text of .docx / .xlsx (limited worker), who can summarise a file
    "team.approvals",
    "tasks.review",  # 2.60.0 C (#1512): review step (reviewer, gate, list setting, API v1)
    "tasks.ticketkey",  # 2.390.0 (#3353): ticket keys APP-123 (no routes)
    "tasks.ttypes",  # 2.609.0 (#3372): own ticket types per workspace (epic, story, ...), API v1
    "team.forms",
    "team.formq",  # 2.98.0 B (#1954): questionnaires (own questions in forms, answers become a task at the customer)
    "team.portal",  # 2.63.0 (#1513): customer reports (status link) and the customer portal
    "office.portaldocs",  # 2.120.0 B (#2088): the customer's documents in the customer portal
    "team.v1",
    "accounts.signup",
    "accounts.pwreset",  # 2.49.0 (#1531): "Forgot your password?"
    "accounts.secmail",  # 2.266.0 (#2963): security mails to the person (registers its background mail job)
    "accounts.discover",  # 2.49.0 (#1106): finding people by e-mail, connection requests
    "admin.hosting",
    "integrations.taskmail",  # 2.393.2 B (#3375): replies by e-mail become comments, answers to the reporter
    "integrations.reqmail",  # 2.553.0 B (#3460): requests by e-mail become portal tickets, answers and replies by mail
    "admin.clientip",  # 2.33.0 (#834)
    "tasks.stale",  # 2.34.0 (#266)
    "personal.timegaps",  # 2.34.0 (#269)
    "personal.timexlsx",  # 2.125.0 C (#2122): Excel export of times + workload
    "personal.timesheet",  # 2.125.0 B (#2119, #2120): monthly timesheets + the person's time zone of time tracking
    "agents.agentpin",  # 2.51.0 C (#1352): agents on the pin board + the weekly status of a project
    "agents.agenttime",  # 2.51.0 C (#1353): agents check time tracking + propose entries from events
    "agents.lyprop",  # 2.55.0 B (#1066): agents propose arrangements of views (the person accepts)
    "admin.exportleft", "admin.oilock", "admin.orgexport",  # 2.42.0 (#833): organisation export (encrypted archive); #4300: oilock
    "admin.retexport",  # 2.146.0 D (#2468): the retention export before deleting an account / organisation
    "admin.purgeshare",  # 2.508.0 (#4301): what an account shares privately passes on when it is deleted (no routes)
    "admin.selfdelete",  # 2.553.0 (#1413): a person deletes their own account (7 days locked, then the watchdog deletes it)
    "admin.acctexport",  # 2.73.0 B (#1473): account export (moving between servers, GDPR copy)
    "admin.acctimport",  # 2.73.0 B (#1473): account import with the mapping of people
    "admin.wkimport",  # 2.177.0 (#2685): large ZIP imports of knowledge pages in pieces, unpacked in the background with progress
    "admin.umz_undoplan", "admin.orgimport",  # 2.137.0 (#2344): organisation import of the remaining areas (no routes)
    "admin.oi_office",  # 2.137.0 (#2344): its office tables (no routes)
    "admin.oi_store",  # 2.137.0 (#2344): its file store, documents, knowledge pages, tables (no routes)
    "admin.oi_team",  # 2.137.0 (#2344): its chat, absences, forms and the rest (no routes)
    "admin.umz_more",  # 2.363.4 (#3127): the account import's own rows (bookmarks, focus sessions, arrangements, bells; no routes)
    "admin.dataretention",  # 2.152.0 D (#2171 #2173): old logs, expired credentials, orphan files (no routes)
    "admin.orgcrypt_cli",  # 2.42.0 (#828): the organisation keys' start-up pass + command line (no routes)
    "docs.extract",  # 2.48.0 (#1111): date / due date / amount from a text (no routes, standard library only)
    "docs.rcheck",  # 2.299.0 D (#3193): the fixed check of a receipt (no routes, standard library + docs.extract)
    "docs.rules",  # 2.48.0 (#1111): sorting rules (no routes)
    "docs.classify",  # 2.48.0 (#1111): the locally learning classifier (no routes)
    "docs.ocr",  # 2.48.0 (#1111): text recognition + preview images (no routes)
    "docs.pagesize",  # 2.905.0 (#5393): the first page's size of a document (the view's preview); imported by docs.store / docs.thumbfill (no routes)
    "docs.scanmark",  # 2.836.0 (#5390): is a document a scan (archive number field); imported by docs.store / docs.thumbfill (no routes)
    "docs.store",  # 2.48.0 (#1111): documents: tables, sealing, word index, recognition run (no routes)
    "files.fsreceipts",  # 2.1148.0 (#4895): the point Receipts below the file store tree (references to office / meals / budget)
    "docs.dtags",  # 2.1119.0 (#5277): the file store's tags moved into the core at the start, their ids rewritten (no routes)
    "docs.maillink",  # 2.424.0 B (#3450): invoice download links of a mail to the document address (no routes)
    "docs.mailaddr",  # 2.577.0 C (#4466): named document addresses: target folder, tags, the rights check of a delivery (no routes)
    "docs.ingest",  # 2.48.0 (#1111): docs_ingest + the background queue, mail / inbox folder
    "docs.thumbfill",  # 2.66.1 (#1944): one-time catch-up of the previews of imported documents (no routes)
    "docs.unpack",  # 2.146.0 B (#2453): ZIP / winmail.dat of an upload or a mail -> its files (no routes)
    "docs.dups",  # 2.146.0 B (#2452): the same file / the same invoice twice (no routes; hooks into the recognition)
    "files.textscan",  # 2.61.0 C (#1820): text recognition of normal stored files (queue, search, Ablage search route)
    "docs.notes",  # 2.635.0 (#4807 d): notes on a document (routes; before docs.web, which shows them)
    "docs.web",  # 2.48.0 (#1111): the routes of the documents area
    "docs.recog",  # 2.353.0 D (#2759): recognition per folder / file of the file store (one route; after docs.web)
    "docs.dsearch",  # 2.122.0 B (#2294): filters + search syntax of the documents list (no routes)
    "docs.dfilter",  # 2.857.0 (#5518): the saved views' filter on the shared core's kflt_where (no routes)
    "docs.batch",  # 2.122.0 B (#2294): the chosen documents at once (tags / type / sender) and as one ZIP
    "docs.fields",  # 2.153.0 (#2179): custom fields of documents (definitions + routes; values via docs.web)
    "docs.flows",  # 2.581.0 (#4803): document flows (trigger, filters, actions), their runs and undo (after docs.fields)
    "integrations.docflowhook",  # 2.581.0 (#4803): the flows' scheduled tick and webhook calls (after docs.flows; no routes)
    "docs.split",  # 2.154.0 A (#1111): a stack scan split into documents by its archive number codes / separator sheets
    "docs.pages",  # 2.777.0 B (#4874): pages of a PDF document deleted / turned as a new version (after docs.split)
    "docs.docmerge",  # 2.959.0 (#4805): several PDF documents merged into the first one's new version (after docs.pages)
    "docs.pdfopt",  # 2.892.0 (#4873): "Optimise PDF" -- the tools (no routes): pages measured, black and white / grey, text layer
    "docs.pdfoptq",  # 2.892.0 (#4873, #4806): "Optimise PDF" as a new version -- routes, queue step, the automatic setting
    "docs.area",  # 2.522.0 (#4433): office and private file store apart: the general input sorts, "Move to office", "Wrong area"
    "docs.areamove",  # 2.547.0 (#4434): the old receipts of the private file store into the office once (preview, undo 30 days)
    "docs.tasklink",  # 2.154.0 A (#1111): a document linked with an existing task, the documents of a task
    "docs.v1",  # 2.48.0 (#1111): documents for agents (API v1 + OpenAPI)
    "docs.scankeys",  # 2.207.0 A (#2763): scan inboxes (upload-only keys) + the folder watcher downloads
    "docs.mailnamed",  # 2.577.0 C (#4466): the settings routes of the named document addresses (integrations layer, LAYER_OF)
    "docs.fetcher",  # 2.425.0 C (#3453): receipt fetchers (own key kind: upload receipts + report the portals' state)
    "docs.csvx",  # 2.122.0 (#2100): the documents list as CSV
    "docs.dviews",  # 2.579.0 (#4802): saved views of the documents search (a kind of the shared core + their counts / hits)
    "sheets.io",  # 2.89.0 C (#1916): tables to / from CSV and .xlsx (export, import as a new sheet)
    "sheets.shprint",  # 2.578.0 (#3462): the print view of a table as a PDF (portrait / landscape, fitted, page numbers)
    "sheets.v1",  # 2.89.0 C (#1916): tables for agents (API v1 + OpenAPI)
    "personal.v1focus",  # 2.116.0 D (#2067): focus sessions + habit statistics for API v1
    "videos.v1",  # 2.99.1 C (#1959): video sign-offs for agents (API v1 + OpenAPI)
    "videos.vdlink",  # 2.642.0 (#4772): client links of a sign-off (several, older versions, carried on to a new version)
    "paperless.ngx",  # 2.48.0 (#1152): Paperless-ngx connection + import into the documents (self-hosted only)
    "paperless.web",  # 2.48.0 (#1152): the routes of the Paperless-ngx connection (self-hosted only)
    "paperless.learn",  # 2.69.0 B (#1847): rules + learning from an import (URL and ZIP)
    "paperless.zipimp",  # 2.69.0 A (#1846): the import of an uploaded Paperless-ngx export (ZIP)
    "accounts.servers",  # 2.73.0 A (#661): several Kalmido servers in one app (server accounts, the other servers' /api/v1)
    "newsletter.adapters",  # 2.55.0 (#1455): listmonk / Brevo / CleverReach (no routes)
    "newsletter.sync",  # 2.55.0 (#1455): connection, segments, consent, the sync runs (no routes)
    "newsletter.web",  # 2.55.0 (#1455): the routes of the newsletter connection
    "receipts.suggest",  # 2.48.0 (#1356): receipts: project / category, agents suggest, people confirm
    "receipts.extracted",  # 2.121.0 A (#2092): supplier / VAT / net / gross / invoice number read off a receipt, taken over by a person
    "receipts.rchecks",  # 2.299.0 D (#3193): the fixed check of a receipt (required details, arithmetic), hints only
    "accounts.layouts_more",  # 2.55.0 (#1067): the new views' blocks for the agents' proposals (after agents.lyprop)
    "tasks.related",  # 2.59.0 B (#1375): related tasks (text vectors from the optional embedding service, API v1, agent events)
    "lists.points",  # 2.60.0 B (#1511): story points velocity (after api.v1)
    "office.fixedimport",  # 2.67.0 A (#1838): fixed costs from a spreadsheet + the monthly check task of the cash flow
    "office.recurring",  # 2.91.0 A (#1923): invoice series (a template invoice every month / quarter / year, drafts or sent)
    "office.subs",  # 2.91.0 B (#1924): subscriptions and tools (fixed costs with notice period, users, renewal reminder)
    "office.storefill",  # 2.357.0 (#3221): once: the stored files of finalised documents from before they were stored (no routes)
    "office.girocode", "office.dunning",  # 2.147.1 B (#2054): the GiroCode (EPC QR), payment reminders suggested for overdue invoices
    "office.offerexp",  # 2.1064.0 (#5818): a sent quotation without an answer rings the bell before / after its "valid until"
    "office.officemove",  # 2.97.0 C (#2049): office data between the personal office and an organisation's office
    "office.pbtransfer",  # 2.137.0 D (#1981): the personal office into an existing organisation (after office.officemove)
    "office.owrite",  # 2.567.0 (#4711): the one write call of an office row on the core's write layer (lock, version, history, undo)
    "office.undo",  # 2.111.0 A (#2233): undo of the office editors (copies before each own change, restore with conflict check)
    "office.undogrp",  # 2.747.0 (#5249): who may take an office step back from the core's step groups (after office.undo)
    "office.otrash",  # 2.272.0 E2 (#3038): the office trash's routes (2.1067.0, #5789: the core's rows only, the copies are gone)
    "tasks.atttrash",  # 2.272.0 E2 (#3038): the trash run of task / comment / project files (no routes)
    "office.numranges",  # 2.138.0 D (#2256): the next running number of every number series (office admin)
    "office.timebill",  # 2.144.6 A (#2053): time entries billable / billed by an invoice, never twice
    "office.docproject",  # 2.168.0 A (#2665): quotations / invoices bound to a project, the project's documents
    "office.offerdispo",  # 2.589.0 (#4571): shoot days of a quotation as pencilled-in bookings of the disposition (no routes)
    "office.offertasks",  # 2.537.0 C (#3433): tasks with a time budget from a quotation
    "office.search",  # 2.250.0 A (#2992): office hits of the web search /api/search (no routes; used by tasks.ftsearch)
    "agents.importprop",  # 2.68.0 A (#1839): agents propose old data for the office (fixed costs), the person takes it over
    "agents.sheetprop",  # 2.126.1 B (#2125): table rows -> tasks as an agent's proposal (after api.v1, sheets.step2)
    "agents.meetprop",  # 2.70.0 A (#1354): a meeting becomes tasks (extract with photos, the chat's cards)
    "agents.dupprop",  # 2.70.0 B (#1357): duplicate contacts as a proposal (no routes)
    "agents.contractprop",  # 2.70.0 C (#1359): contract_notice + the proposal kind notice (no routes of its own)
    "agents.ccsread",  # 2.469.0 (#3749): an agent reads a credit card statement (card_statement_read, no routes of its own)
    "agents.rcread",  # 2.299.0 E (#3194): an agent reads a receipt (receipt_read of agents.asstprop, no routes of its own)
    "agents.asstprop",  # 2.126.1 A (#2123 #2124): office texts, document summaries, client reports by an agent (no routes of its own)
    "agents.ideaprop",  # 2.156.0 A (#1201): "Add ideas" in the mind map -- an agent proposes sub-branches
    "lists.rules",  # 2.71.0 A (#1457): rules of a list (When ... then ...), after api.v1
    "core.objects", "core.writes", "core.objweb",  # 2.558.0 (#4709): the shared core (register, roles, write path) and its generic routes
    "core.objcmtweb",  # 2.981.0 (#5273): the generic routes of the comments' core (/api/obj/<kind>/<id>/comments, /api/obj/comments/<cid>)
    "core.objlinks", "core.objlinkweb",  # 2.1076.0 (#5271): the links' core (obj_links) and its routes (/api/obj/<kind>/<id>/links)
    "core.undogroups",  # 2.747.0 (#5249): the step groups per account (storage, limits, prune; no routes)
    "core.undoweb",  # 2.747.0 (#5249): undo across devices -- the own step groups listed and taken back (GET /api/undo)
    "core.undoareas",  # 2.777.0 (#5254): what the areas share to record and take back their steps (no routes)
    "agents.objprop",  # 2.623.0 (#4718): an agent's change of a core object as a proposal a person accepts (after core.objweb)
    "collab.tcxcore",  # 2.565.0 (#4719): the team chat's channels and groups as a kind of the shared core (no routes of its own)
    "lists.tplkind",  # 2.905.0 (#5288): task, project and section templates as a kind of the shared core (after core.writes)
    "lists.lmcore",  # 2.568.0 (#4739): the projects as a kind of the shared core (shares, revocation, settings history)
    "lists.lkretire",  # 2.958.0 (#5245): stage 7d, folder_people and group_shares go at the start (no routes)
    "events.evkern", "contacts.ctkern",  # 2.566.0 (#4712): calendars and address books as kinds of the shared core (stage 3)
    "core.objlight",  # 2.754.0 (#5268): the light kinds task, event, hub_mail, client of the shared core (after their areas)
    "core.objnotify",  # 2.891.0 (#5270): THE send decision (obj_role >= view of every recipient), after the kinds it asks
    "files.fskern", "wiki.wkkern", "sheets.shkern",  # 2.809.0 (#5365): file-store nodes, knowledge pages, tables on the core's trash
    "hub.dspkern",  # 2.872.0 (#5532): the shoot day and its call sheet as kinds of the shared core (after hub.callsheet)
    "events.evundo", "contacts.ctundo", "files.fsundo", "personal.habitundo",  # 2.777.0 (#5254): their steps in the step groups (who may take them back)
    "lists.lpundo",  # 2.809.0 (#5476): a project's settings in the step groups
    "lists.lpside",  # 2.1074.0 (#5493): a project's settings with side effects in the step groups (after lists.lpundo)
    "lists.otrundo",  # 2.997.0 (#5609): a project into the list trash in the step groups
    "lists.secundo",  # 2.809.0 (#5476): creating / deleting / restoring a section in the step groups
    "personal.timeundo",  # 2.809.0 (#5476): changing / deleting a time entry in the step groups
    "lists.fieldundo",  # 2.809.0 (#5476): a project's custom fields in the step groups
    "lists.ruleundo",  # 2.809.0 (#5476): a project's rules in the step groups (after lists.rules)
    "lists.tplundo",  # 2.809.0 (#5476): renaming / trashing a template in the step groups
    "lists.sprundo",  # 2.809.0 (#5476): a project's sprints in the step groups
    "life.budundo",  # 2.809.0 (#5476): the budget's entries in the step groups (2.985.0 #5394: the lock per list space)
    "lists.foldundo",  # 2.809.0 (#5476): renaming / moving a sidebar folder in the step groups
    "admin.supporter",  # 2.74.0 (#338): the supporter licence (self-hosted only, a badge, unlocks nothing)
    "admin.operator",  # 2.144.0 D (#797): the hosting operator's interface (off unless a token file is configured)
    "life.bmundo", "calendars.pollundo", "hub.absundo", "lists.envundo",  # 2.809.0 (#5476, part B): steps in the step groups
    "calendars.apptundo", "hub.dspundo", "lists.padundo", "life.rssundo",  # (core/undoareas.py) of more areas
    "assistant.core",  # 2.75.0 (#1411): the built-in assistant -- configuration, model call, prompts (off unless configured)
    "assistant.web",  # 2.75.0 (#1411): the routes of the built-in assistant
    "admin.worker",  # 2.102.0 D (#1994 / #1997): health numbers, the process role, one runner per background loop
    # -- sorted block (2.624.0, #3941): a new module WITHOUT an order need goes here, one per line, sorted by name (tools/check_layout.py)
    # (it loads after every module above, so it may use their names at import time; one with an order need goes above instead)
    "accounts.setundo",  # 2.985.0 (#5394): the settings' undo steps (one diff part per key, no routes)
    "collab.duebell",  # 2.1037.0 (#5801): the deadline lines of the bell (due today / overdue, seen for today)
    "collab.recent",  # 2.769.0 (#5352): "Recently edited" over Knowledge, Files and Reading (GET /api/recent)
    "core.undodiff",  # 2.774.0 (#5251): the diff parts of the step groups (no routes)
    "life.lfkern",  # 2.947.0 (#5367): bookmarks and feeds on the core's trash (no routes)
    "sheets.shundo",  # 2.778.0 (#5253): a person's table writes as steps on the server (no routes)
    "sheets.shustep",  # 2.800.0 (#5409): a person's structural table changes as steps on the server (no routes)
    "tasks.tundo",  # 2.774.0 (#5251): the tasks' and sections' undo steps on the server (no routes)
    "videos.vdkern",  # 2.947.0 (#5367): video sign-offs on the core's trash (no routes)
    "wiki.wkundo",  # 2.778.0 (#5253): a person's knowledge page saves as steps on the server (no routes)
    # -- end of the sorted block: only core.idem and startup follow, they stay last
    "core.idem",  # 2.270.0 C (#3022): idempotency keys of write requests (after every other before_request hook, its after_request runs first)
    "startup",
)
MODULES = [importlib.import_module(f"{__name__}.{m}") for m in ORDER]
