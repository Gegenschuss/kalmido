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
LAYER_OF = {"admin.migrate": "core", "api.common": "core"}  # the move from SQLite runs inside init_db; 2.149.0 G (#2517): the v1 helpers are infrastructure

ORDER = (
    "core.env",  # 2.149.0 D (#2511): the registry of the environment variables (no imports from the app)
    "core.config",
    "core.schema",
    "core.i18n",
    "core.pg",  # 2.37.0 (#1150): the Postgres layer (core.db re-exports it)
    "core.reqtime",  # 2.149.0 B (#2504): request timing (Server-Timing, slow log); first hooks = whole request measured
    "core.db",
    "core.errors",  # 2.149.0 G (#2517): BadInput, Denied, UnknownFields (re-exported at the old places)
    "core.ctx",  # 2.149.0 G (#2517): me()
    "api.common",  # 2.149.0 G (#2517): the /api/v1 route helpers (core layer, see LAYER_OF)
    "core.tokenhash",  # 2.138.0 C (#1907): upload / calendar tokens as hashes
    "core.rls",  # 2.37.0 (#1150): row-level security, applied by init_db
    "core.retention",  # 2.152.0 (#2165): deletion periods + the switch of the retention runs
    "core.fkeys",  # 2.152.0 C (#2174): foreign keys of references that had none (orphans cleaned first)
    "core.orgcrypt",  # 2.42.0 (#828): keys per organisation, encryption at rest
    "admin.migrate",  # 2.37.0 (#1150): the move from SQLite (migrate-sqlite), used by init_db
    "accounts.session",
    "accounts.setupcode",  # 2.45.0 (#1515): one-time code for the first setup
    "accounts.pictures",
    "accounts.colors",  # 2.47.1 (#1721)
    "accounts.login",
    "accounts.oidc",
    "core.access",
    "core.serializers",
    "core.compress",  # 2.65.0 (#1505): gzip for JSON answers; before core.pages = its after_request hook runs last
    "core.pages",
    "core.instance",
    "core.state",
    "core.csvimport",  # 2.140.0 B (#2134): the statement reader of budget and bank reconciliation
    "core.zipread",  # 2.146.0 (#2453 #2455 #2457): the in-memory ZIP reader of the importers
    "core.merges",  # 2.66.0 (#1835): merging contacts / clients (reversible)
    "core.stmtfiles",  # 2.146.0 C (#2455): the uploaded statements of the bank imports (office + budget)
    "lists.lists",
    "lists.groups",
    "lists.grouppics",  # 2.46.0 (#1605)
    "lists.ownership",
    "lists.sections",
    "lists.sectpl",  # 2.156.0 C (#2073)
    "lists.folders",
    "lists.foldershare",  # 2.41.0 (#1420)
    "lists.listhead",  # 2.83.0 C (#1427)
    "lists.listtrash",  # 2.102.0 A (#1988)
    "tasks.validation",
    "tasks.tasks",
    "tasks.roadmap",
    "tasks.lifecycle",
    "tasks.tasktrash",  # 2.116.0 A (#2063): the trash period of tasks
    "tasks.attachments",
    "tasks.batch",
    "tasks.mineorder",  # 2.40.0 (#1344)
    "tasks.delta",  # 2.42.0 (#1376): GET /api/state/delta
    "collab.replies",  # 2.33.0 (#1076): before comments / teamchat / agents.chat (they import it)
    "collab.comments",
    "collab.news",
    "personal.habits",
    "personal.timetrack",
    "personal.timewipe",  # 2.43.0 (#1434)
    "accounts.settings",
    "lists.favorites",  # 2.40.0 (#1361)
    "lists.listexport",  # 2.116.0 C (#2064)
    "accounts.layouts",  # 2.32.0 (#1063, #983)
    "accounts.layoutsets",  # 2.55.0 (#1069, #1068, #1066)
    "accounts.sideviews",  # 2.156.0 D (#2186): the sidebar's saved views (no routes: user settings side_views / side_view)
    "accounts.onboarding",
    "accounts.users",
    "accounts.orgs",
    "accounts.orgroles",  # 2.143.0 A (#2151): organisation roles guest / read-only / accounting
    "accounts.spacemove",  # 2.96.0 (#1941): the shared rules of moving data between the private space and an organisation (no routes)
    "accounts.orgout",  # 2.148.1 B (#2483): data leaves an organisation only through its admin (no routes)
    "accounts.tenancy",
    "accounts.orglists",  # 2.35.0 (#1101)
    "accounts.useradmin",  # 2.88.0 (#1980)
    "accounts.orgretain",  # 2.152.0 A (#2164 #2167)
    "lists.templates",
    "tasks.dependencies",
    "tasks.depchain",  # 2.67.0 B (#1865)
    "lists.projects",
    "lists.envs",  # 2.60.0 D (#1514)
    "lists.formula",  # 2.43.0 (#1328): the formula parser (no routes; used by lists.fields)
    "lists.fields",
    "personal.stats",
    "calendars.icalfeed",
    "calendars.caldav",
    "integrations.importers",
    "notify.push",
    "tasks.remindat",  # 2.111.0 C (#2057)
    "notify.alerts",
    "notify.sev",  # 2.36.2 (#1133)
    "calendars.subscriptions",
    "calendars.davwrite",  # 2.52.0 B (#1128): writing into CalDAV subscriptions
    "calendars.apptbook",  # 2.94.0 B (#1929): appointment booking by customers (public page, no login)
    "calendars.polls",  # 2.98.0 A (#1953): scheduling polls (vote through a link, the winning time becomes an event)
    "admin.backup",
    "admin.offsite",  # 2.143.0 B (#2152): the off-site target of the backups (S3, WebDAV, SFTP)
    "api.v1",
    "notify.caps",  # 2.33.0 (#927)
    "notify.taskbell",  # 2.53.0 C (#1424): the bell of one task per person
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
    "agents.steps",  # 2.32.0 (#1081 / #1079)
    "agents.quota",  # 2.33.0 (#1045)
    "agents.schedules",  # 2.34.0 (#272)
    "agents.admin",
    "agents.api",
    "agents.proposals",
    "agents.cleanup",  # 2.39.0 (#1151)
    "agents.propkinds2",  # 2.51.0 B (#1351 #1358)
    "agents.setup",  # 2.44.0 (#1517)
    "lists.playbook",  # 2.39.0 (#1168)
    "tasks.attachtext",  # 2.34.0 (#368)
    "tasks.snippets",  # 2.35.0 (#1095)
    "tasks.multilist",  # 2.71.0 B (#1459): a task in several lists without a copy (after api.v1)
    "agents.gates",  # 2.26.0 (#949)
    "agents.safety",  # 2.30.0 (#919)
    "agents.usage",
    "lists.custview",  # 2.50.0 C (#329): customer view of public links (no routes; used by lists.public)
    "lists.public",
    "integrations.git",
    "integrations.gitfolder",  # 2.33.0 (#934)
    "integrations.gitbuild",  # 2.151.0 A (#2558)
    "integrations.errorreports",
    "api.projects",
    "lists.sprints",  # 2.60.0 (#343): sprints of project lists (after api.v1: it has token routes)
    "lists.kpis",  # 2.43.0 (#1328): sum row + key figures (web + token API)
    "lists.orgvis",  # 2.46.0 (#1603): organisation lists visible to the whole organisation
    "api.scopes",
    "collab.notes",
    "wiki.pages",  # 2.49.0 C (#1199): knowledge pages
    "wiki.outline",  # 2.49.0 C (#1201): outline import of the mind map (no storage)
    "sheets.formula",  # 2.89.0 (#1916): tables -- the formula engine (no routes)
    "sheets.shfuncs",  # 2.124.0 A (#2109): SUMMEWENN, SVERWEIS, text and date functions of formulas (no routes)
    "sheets.vars",  # 2.89.0 (#1916): Kalmido variables of formulas, evaluated per viewer (no routes)
    "sheets.shkinds",  # 2.124.0 B (#2110, #2111): column kinds checkbox / person / link / file, rows / columns kept in view
    "sheets.shhist",  # 2.124.0 B (#2112): the change history of the cells (people and agents)
    "sheets.core",  # 2.89.0 (#1916): sheets, columns, rows, cells, agent batches (no routes; used by sheets.web and part C/D)
    "sheets.web",  # 2.89.0 (#1916): the routes of the tables area (/api/sheets)
    "sheets.step2",  # 2.89.0 (#1916, D): step 2 -- rows to tasks / quotation, a list as rows (by button)
    "sheets.shmove",  # 2.96.0 B (#1941): a table to the other workspace (private <-> organisation)
    "sheets.shshare",  # 2.124.0 C (#2113): one table shared with single people / agents (sheet_shares)
    "sheets.shchart",  # 2.124.0 A (#2115): the simple chart of a table (its setting; drawn by static/js/sheetchart.js)
    "sheets.shbook",  # 2.124.0 E (#2116): several sheets in one table (the sheet bar's routes; rights / formulas hang in core)
    "collab.teamchat",
    "collab.teamchan",  # 2.113.1 B (#2059): channels, groups, files of the team chat (after teamchat)
    "collab.msgsearch",  # 2.33.0 (#1080)
    "tasks.ftsearch",  # 2.116.0 B (#2065): full-text search of tasks + comments (/api/search)
    "collab.chatsave",  # 2.37.0 (#1159)
    "collab.chatpins",  # 2.62.0 (#1848): pinned chat messages (after teamchat / agents.chat)
    "collab.cchoice",  # 2.41.0 (#1383): answer buttons / approval cards in comments
    "collab.e2e",  # 2.42.0 (#828, #909): end-to-end encryption (keys, encrypted notes / files / DMs)
    "integrations.mailtrim",  # 2.49.0 (#971)
    "collab.notelock",  # 2.48.0 (#1642): a task's note locked with one's own password (needs collab.e2e)
    "collab.liste2e",  # 2.64.1 (#1817): the lock per list (texts encrypted in the browser; needs collab.e2e)
    "collab.liste2eguard",  # 2.64.1 B (#1817): the lock per list on the other ways (API, agents, CalDAV, mail, push, copies)
    "collab.liste2efile",  # 2.64.2 B (#1817): files of lists with the lock, encrypted with the list key
    "collab.liste2echan",  # 2.64.2 C (#1817): the list channel (team chat of a list) with the lock
    "wiki.wikie2e",  # 2.64.3 (#1817): the lock per knowledge space (path + text encrypted in the browser)
    "wiki.wkmove",  # 2.96.0 B (#1941): wiki pages and folders to the other workspace (private <-> organisation)
    "wiki.wkembed",  # 2.123.0 C (#2103, #2107): files of the file store and tables in knowledge pages (by reference)
    "wiki.wikiatt",  # 2.99.0 A (#2182): files of knowledge pages (upload, ZIP import / export)
    "wiki.wkshare",  # 2.123.0 B (#2104): read-only shares of pages / folders (people, public link)
    "wiki.wkhist", "wiki.wksearch",  # 2.123.0 A (#2105, #2102, #2106): texts sealed at rest, page history, word index
    "files.store",  # 2.48.0 (#1207): the file store (Ablage): tree, roles, versions (no routes; the interface of docs / import)
    "files.scan",  # 2.61.0 (#1818): virus scan of uploads (clamd), the later scan, the admin's scanner state
    "files.web",  # 2.48.0 (#1207): the file store's routes for the web app
    "files.fsmove",  # 2.96.0 A (#1941): files, folders and documents to the other workspace (private <-> organisation)
    "files.fstags",  # 2.122.0 B (#2099): tags of files and folders (the documents' tag set of the workspace)
    "files.bulk",  # 2.112.1 A (#2058): several nodes into the trash / back, the ZIP download, the phone scan -> one PDF
    "files.v1",  # 2.48.0 (#1207): the file store in the REST API (files:read / files:write)
    "files.extlinks",  # 2.112.1 B (#2058): external share links of files / folders (/s/f/<token>, no login)
    "files.trashpurge",  # 2.152.0 B (#2165): trash periods of files, wiki, hub mails, tables, pipeline, series, chat (no routes)
    "files.photometa",  # 2.61.0 B (#1819): photo metadata (GPS, camera) removed on upload (no routes; files/upsafe.py)
    "files.upsafe",  # 2.61.0 (#1818 #1819 #1820): the shared upload path - scan, metadata, text recognition (no routes)
    "files.filereq",  # 2.122.0 A (#2097): file requests - a public link /u/<token> through which a client uploads files
    "integrations.mail",
    "integrations.ntfyin",  # 2.142.0 C (#2150)
    "integrations.exporters",  # 2.142.0 C (#2148)
    "accounts.invite",
    "accounts.sessions",  # 2.115.0 B (#2062): active sessions
    "accounts.orginvite",  # 2.115.0 B (#2062): organisation admins invite accounts by e-mail
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
    "hub.absence",  # 2.50.0 A (#1195): absences + German public holidays
    "hub.leave",  # 2.125.0 A (#2118, #2117): working days per person, vacation account + requests
    "hub.abscal",  # 2.155.0 B (#2076): holidays + absences in the calendar views, their subscription link
    "hub.dispo",  # 2.50.0 A (#1194): resources and disposition (bookings of crew and equipment)
    "hub.agentdispo",  # 2.51.0 C (#1355): shoot planning by agents (event drafts, options), the disposition in the REST API
    "hub.hubmail",  # 2.84.0 A (#1198): e-mail as an input of the hub (mails filed with clients / projects)
    "hub.mailview",  # 2.141.0 B (#2140, #2139): the HTML view of a filed mail, a task / an event made from it
    "hub.mailbox",  # 2.141.0 A (#2141, #2138): the own mailbox of a workspace, sending from the e-mail filing
    "office.packs",  # 2.36.1 (#1021): country packs (data), used by office.model
    "office.model",  # 2.36.1 (#1021): office & finance (B); C/D append office.calc, office.docs, office.pdf
    "office.web",
    "office.calc",  # 2.36.1 (#1021): the quotation calculator (C, no imports)
    "office.sheet",  # 2.47.0 (#1216): the shoot calculation sheet + industry packs (C, imports office.calc)
    "office.catalog",  # 2.76.0 A (#1023): the pack catalogue, installed packs per office area (imports office.sheet)
    "office.costs",  # 2.47.0 (#1645, #1649): producing per document, purchases of accepted quotations (part D, no routes)
    "office.docs",  # 2.36.1 (#1021): quotations (C)
    "office.pdf",  # 2.36.1 (#1021): the PDF writer (D, no kalmido imports)
    "office.einvoice",  # 2.38.0 (#1021 P5, F2): e-invoice XML (CII EN 16931 / XRechnung) from the snapshot, used by office.pdfweb
    "office.einvoice_in",  # 2.146.0 A (#2451): incoming e-invoices (UBL / CII, embedded in ZUGFeRD PDFs; no routes, used by docs.store)
    "office.pdfweb",  # 2.36.1 (#1021): quotation PDF + company logo routes (D; the writer office.pdf has no routes)
    "office.signoff",  # 2.50.0 C (#1200): approval links with a simple electronic signature (quotations, list acceptance)
    "office.ledger",  # 2.36.2 (#1021, #1142, E): finalising, structured company data, office log
    "office.olock",  # 2.152.0 C (#2168 #2169): legal retention locks (booked receipts, logbook)
    "office.invoices",  # 2.38.0 (#1021, F1): invoices, credit notes, reminders, payments, sending, DATEV inbox
    "office.peppol",  # 2.154.0 B (#1960): e-invoices over Peppol (own provider account): ids, connection, UBL, send + status
    "office.delivery",  # 2.120.0 D (#2089): delivery notes / proofs of service, the timesheet of an invoice
    "office.abschlag",  # 2.120.0 A (#2087): progress / final invoices, cash discount (Skonto)
    "office.doclang",  # 2.40.0 (#1381): language switch of drafts swaps the standard texts (no routes; used by office.docs)
    "office.countries",  # 2.40.0 (#1372): the ISO 3166-1 alpha-2 list (no routes)
    "office.contacts_cl",  # 2.40.0 (#1380): contact persons of a client (no routes; used by team.clients, office.docs, legacyimport)
    "office.legacyimport",  # 2.39.1 (#1182): legacy import (clients / services / equipment from .xlsx, archive of old PDFs)
    "office.archiveedit",  # 2.81.0 B (#1834): correct an archived document afterwards (client, tax lines, paid) + its history
    "office.parts",  # 2.47.0 (#1215): parts of a quotation (Teilangebote): routes, title page calculation, invoice modes
    "office.travel",  # 2.47.3 (#1022, part B): travel expenses (trips, receipts, evaluation, billing on)
    "office.outlays",  # 2.121.0 C (#2094): bill receipts of the bookkeeping on to a client (outlays)
    "office.vma",  # 2.95.0 (#1932): the per diem rates (BMF tables per year) and its calculation (pure functions)
    "office.vmareport",  # 2.95.0 A (#1932): the per diem report per person and year (JSON, PDF, Excel, CSV), the rates
    "office.vmaimport",  # 2.95.0 B (#1932): the import of a per diem spreadsheet (preview, import, undo)
    "office.mealpdf",  # 2.119.0 A (#2288): the PDFs of the entertainment receipts (no routes)
    "office.meals",  # 2.119.0 A (#2288): entertainment receipts (Bewirtungsbelege): meals, approval + log, choices, evaluation
    "office.cashflow",  # 2.47.3 (#1652, part B): cash flow per month + fixed costs
    "office.cfstart",  # 2.123.0 D (#2341): start balance, corrections by hand and real balances of the cash flow
    "office.cfbank",  # 2.124.0 D (#2342): the balances of the bank statements in the cash flow (no routes)
    "office.pipeline",  # 2.50.0 B (#1196): the sales pipeline
    "office.leads",  # 2.94.0 A (#1930): leads before the pipeline (stage lead): convert, CSV import, agents
    "office.kpi",  # 2.50.0 B (#1197): the business figures
    "office.datev",  # 2.47.3 (#1460): DATEV booking batch (EXTF) of invoices, credit notes and payments
    "office.periodlock",  # 2.148.0 A (#2471): locked accounting periods (GoBD)
    "office.gobdexport",  # 2.148.0 A (#2471): the export for the tax auditor (GDPdU index.xml + CSV)
    "office.datevzip",  # 2.148.0 B (#2470): DATEV batch + receipt images (document.xml) as one ZIP
    "office.datevin",  # 2.120.0 C (#2090): DATEV batch input side (receipts, travel expenses) + its accounts route
    "office.datevimp",  # 2.148.0 D (#2458): DATEV import (debtors / creditors, opening balances of a booking batch)
    "office.books",  # 2.90.0 A (#1921): bookkeeping light: income/expense statement (EUeR), VAT return figures, tax reserve, receipt photo
    "office.bkexport",  # 2.147.0 (#2461): the neutral bookkeeping export (booking list CSV + documents / receipts ZIP)
    "office.catacct",  # 2.121.0 (#2093): receipt categories with an SKR03 / SKR04 account (no routes; shown by office.books)
    "office.receiptlist",  # 2.153.0 (#2055): receipts list over all months with filters + its CSV / ZIP for the tax adviser
    "office.bank",  # 2.90.0 B (#1921): bank reconciliation: CSV / CAMT import, matching bookings to invoices and receipts
    "office.doctpl_samples",  # 2.117.0 B (#2283): the letter samples of the document templates (data, no routes)
    "office.doctpl",  # 2.93.0 A (#1927): document templates with variables, documents as PDF, signature by customer link
    "office.privacy",  # 2.154.0 C (#2192): data protection sheets of a client (DPA, information, consent): mail, ways back, status
    "office.terms",  # 2.113.2 (#2253): terms and conditions (AGB) as PDF per language, sent with quotations
    "office.letters",  # 2.153.0 (#2028): letters (correspondence): recipient, text, signature, DIN 5008 PDF, status, filing
    "office.letterlinks",  # 2.153.0 (#2028): letter <-> document links, history, deadline -> task, follow-up, reference line
    "office.lettermail",  # 2.153.0 (#2029, #2030): letters by e-mail with the answer linked, text blocks
    "office.letteragent",  # 2.153.0 (#2031): agents draft letters (API v1, MCP, event at a document)
    "videos.review",  # 2.99.1 A (#1959): video sign-off with comments at a timecode (links only), customer link = signoff kind video
    "office.logbook",  # 2.93.0 B (#1928): the logbook (vehicles, drives, change log, year report, mileage allowance)
    "office.cashbook",  # 2.121.0 B (#2095): the cash book (cash boxes, entries, cancellations, day closings, CSV / PDF)
    "office.procdoc",  # 2.148.0 C (#2472): the procedure documentation (GoBD), prefilled, versions, Markdown / PDF
    "office.taxdates",  # 2.90.0 C (#1922): tax dates as recurring tasks (VAT return, income tax prepayments, trade tax)
    "office.agentdocs",  # 2.51.0 A (#1348, #1350): agents in the office: drafts, payment suggestions, the switches (API v1 + routes)
    "office.agreements",  # 2.92.0 A (#1925): business contracts and insurances (term, notice, contribution, cash flow, deadline task)
    "office.contractfiles",  # 2.117.0 B (#2285): PDF files of a framework contract (upload, view, replace, trash)
    "office.assets",  # 2.92.0 B (#1931): equipment value: purchase, depreciation, current value, insurance list
    "office.bpread",  # 2.120.0 E (#2091): the PDF reader of the own letterhead (no routes, no kalmido imports)
    "office.letterhead",  # 2.120.0 E (#2091): the own letterhead behind the office documents (upload, margins, preview)
    "files.officeprev",  # 2.92.0 C (#1926): preview + text of .docx / .xlsx (limited worker), who can summarise a file
    "team.approvals",
    "tasks.review",  # 2.60.0 C (#1512): review step (reviewer, gate, list setting, API v1)
    "team.forms",
    "team.formq",  # 2.98.0 B (#1954): questionnaires (own questions in forms, answers become a task at the customer)
    "team.portal",  # 2.63.0 (#1513): customer reports (status link) and the customer portal
    "office.portaldocs",  # 2.120.0 B (#2088): the customer's documents in the customer portal
    "team.v1",
    "accounts.signup",
    "accounts.pwreset",  # 2.49.0 (#1531): "Forgot your password?"
    "accounts.discover",  # 2.49.0 (#1106): finding people by e-mail, connection requests
    "admin.hosting",
    "admin.clientip",  # 2.33.0 (#834)
    "tasks.stale",  # 2.34.0 (#266)
    "personal.timegaps",  # 2.34.0 (#269)
    "personal.timexlsx",  # 2.125.0 C (#2122): Excel export of times + workload
    "personal.timesheet",  # 2.125.0 B (#2119, #2120): monthly timesheets + the person's time zone of time tracking
    "agents.agentpin",  # 2.51.0 C (#1352): agents on the pin board + the weekly status of a project
    "agents.agenttime",  # 2.51.0 C (#1353): agents check time tracking + propose entries from events
    "agents.lyprop",  # 2.55.0 B (#1066): agents propose arrangements of views (the person accepts)
    "admin.orgexport",  # 2.42.0 (#833): organisation export (encrypted archive)
    "admin.retexport",  # 2.146.0 D (#2468): the retention export before deleting an account / organisation
    "admin.acctexport",  # 2.73.0 B (#1473): account export (moving between servers, GDPR copy)
    "admin.acctimport",  # 2.73.0 B (#1473): account import with the mapping of people
    "admin.wkimport",  # 2.177.0 (#2685): large ZIP imports of knowledge pages in pieces, unpacked in the background with progress
    "admin.orgimport",  # 2.137.0 (#2344): organisation import of the remaining areas (no routes)
    "admin.oi_office",  # 2.137.0 (#2344): its office tables (no routes)
    "admin.oi_store",  # 2.137.0 (#2344): its file store, documents, knowledge pages, tables (no routes)
    "admin.oi_team",  # 2.137.0 (#2344): its chat, absences, forms and the rest (no routes)
    "admin.dataretention",  # 2.152.0 D (#2171 #2173): old logs, expired credentials, orphan files (no routes)
    "admin.orgcrypt_cli",  # 2.42.0 (#828): the organisation keys' start-up pass + command line (no routes)
    "docs.extract",  # 2.48.0 (#1111): date / due date / amount from a text (no routes, standard library only)
    "docs.rules",  # 2.48.0 (#1111): sorting rules (no routes)
    "docs.classify",  # 2.48.0 (#1111): the locally learning classifier (no routes)
    "docs.ocr",  # 2.48.0 (#1111): text recognition + preview images (no routes)
    "docs.store",  # 2.48.0 (#1111): documents: tables, sealing, word index, recognition run (no routes)
    "docs.ingest",  # 2.48.0 (#1111): docs_ingest + the background queue, mail / inbox folder
    "docs.thumbfill",  # 2.66.1 (#1944): one-time catch-up of the previews of imported documents (no routes)
    "docs.unpack",  # 2.146.0 B (#2453): ZIP / winmail.dat of an upload or a mail -> its files (no routes)
    "docs.dups",  # 2.146.0 B (#2452): the same file / the same invoice twice (no routes; hooks into the recognition)
    "files.textscan",  # 2.61.0 C (#1820): text recognition of normal stored files (queue, search, Ablage search route)
    "docs.web",  # 2.48.0 (#1111): the routes of the documents area
    "docs.dsearch",  # 2.122.0 B (#2294): filters + search syntax of the documents list (no routes)
    "docs.batch",  # 2.122.0 B (#2294): the chosen documents at once (tags / type / sender) and as one ZIP
    "docs.fields",  # 2.153.0 (#2179): custom fields of documents (definitions + routes; values via docs.web)
    "docs.split",  # 2.154.0 A (#1111): a stack scan split into documents by its archive number codes / separator sheets
    "docs.tasklink",  # 2.154.0 A (#1111): a document linked with an existing task, the documents of a task
    "docs.v1",  # 2.48.0 (#1111): documents for agents (API v1 + OpenAPI)
    "docs.csvx",  # 2.122.0 (#2100): the documents list as CSV
    "sheets.io",  # 2.89.0 C (#1916): tables to / from CSV and .xlsx (export, import as a new sheet)
    "sheets.v1",  # 2.89.0 C (#1916): tables for agents (API v1 + OpenAPI)
    "personal.v1focus",  # 2.116.0 D (#2067): focus sessions + habit statistics for API v1
    "videos.v1",  # 2.99.1 C (#1959): video sign-offs for agents (API v1 + OpenAPI)
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
    "accounts.layouts_more",  # 2.55.0 (#1067): the new views' blocks for the agents' proposals (after agents.lyprop)
    "tasks.related",  # 2.59.0 B (#1375): related tasks (text vectors from the optional embedding service, API v1, agent events)
    "lists.points",  # 2.60.0 B (#1511): story points velocity (after api.v1)
    "office.fixedimport",  # 2.67.0 A (#1838): fixed costs from a spreadsheet + the monthly check task of the cash flow
    "office.recurring",  # 2.91.0 A (#1923): invoice series (a template invoice every month / quarter / year, drafts or sent)
    "office.subs",  # 2.91.0 B (#1924): subscriptions and tools (fixed costs with notice period, users, renewal reminder)
    "office.girocode", "office.dunning",  # 2.147.1 B (#2054): the GiroCode (EPC QR), payment reminders suggested for overdue invoices
    "office.officemove",  # 2.97.0 C (#2049): office data between the personal office and an organisation's office
    "office.pbtransfer",  # 2.137.0 D (#1981): the personal office into an existing organisation (after office.officemove)
    "office.undo",  # 2.111.0 A (#2233): undo of the office editors (copies before each own change, restore with conflict check)
    "office.numranges",  # 2.138.0 D (#2256): the next running number of every number series (office admin)
    "office.timebill",  # 2.144.6 A (#2053): time entries billable / billed by an invoice, never twice
    "office.invdelete",  # 2.162.0 A (#2603): test phase - deleting a finalised / sent invoice (no routes of its own)
    "agents.importprop",  # 2.68.0 A (#1839): agents propose old data for the office (fixed costs), the person takes it over
    "agents.sheetprop",  # 2.126.1 B (#2125): table rows -> tasks as an agent's proposal (after api.v1, sheets.step2)
    "agents.meetprop",  # 2.70.0 A (#1354): a meeting becomes tasks (extract with photos, the chat's cards)
    "agents.dupprop",  # 2.70.0 B (#1357): duplicate contacts as a proposal (no routes)
    "agents.contractprop",  # 2.70.0 C (#1359): contract_notice + the proposal kind notice (no routes of its own)
    "agents.asstprop",  # 2.126.1 A (#2123 #2124): office texts, document summaries, client reports by an agent (no routes of its own)
    "agents.ideaprop",  # 2.156.0 A (#1201): "Add ideas" in the mind map -- an agent proposes sub-branches
    "lists.rules",  # 2.71.0 A (#1457): rules of a list (When ... then ...), after api.v1
    "admin.supporter",  # 2.74.0 (#338): the supporter licence (self-hosted only, a badge, unlocks nothing)
    "admin.operator",  # 2.144.0 D (#797): the hosting operator's interface (off unless a token file is configured)
    "assistant.core",  # 2.75.0 (#1411): the built-in assistant -- configuration, model call, prompts (off unless configured)
    "assistant.web",  # 2.75.0 (#1411): the routes of the built-in assistant
    "admin.worker",  # 2.102.0 D (#1994 / #1997): health numbers, the process role, one runner per background loop
    "startup",
)
MODULES = [importlib.import_module(f"{__name__}.{m}") for m in ORDER]
