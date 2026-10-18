"""Kalmido server package. app.py is the entry point; docs/ARCHITECTURE.md explains the layout.

The modules are loaded in the fixed ORDER below (it is the order the code had in the former single app.py): routes, request
hooks and error handlers register in that order, and each module may use names of EARLIER modules at import time
(`from ..core.db import connect` at the top). A name of a LATER module is imported inside the function that needs it
(at call time, when every module is loaded) -- that keeps the import graph free of cycles.
"""
import importlib

ORDER = (
    "core.config",
    "core.schema",
    "core.i18n",
    "core.pg",  # 2.37.0 (#1150): the Postgres layer (core.db re-exports it)
    "core.db",
    "core.rls",  # 2.37.0 (#1150): row-level security, applied by init_db
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
    "core.merges",  # 2.66.0 (#1835): merging contacts / clients (reversible)
    "lists.lists",
    "lists.groups",
    "lists.grouppics",  # 2.46.0 (#1605)
    "lists.ownership",
    "lists.sections",
    "lists.folders",
    "lists.foldershare",  # 2.41.0 (#1420)
    "lists.listhead",  # 2.83.0 C (#1427)
    "tasks.validation",
    "tasks.tasks",
    "tasks.roadmap",
    "tasks.lifecycle",
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
    "accounts.layouts",  # 2.32.0 (#1063, #983)
    "accounts.layoutsets",  # 2.55.0 (#1069, #1068, #1066)
    "accounts.onboarding",
    "accounts.users",
    "accounts.orgs",
    "accounts.tenancy",
    "accounts.orglists",  # 2.35.0 (#1101)
    "accounts.useradmin",  # 2.88.0 (#1980)
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
    "notify.alerts",
    "notify.sev",  # 2.36.2 (#1133)
    "calendars.subscriptions",
    "calendars.davwrite",  # 2.52.0 B (#1128): writing into CalDAV subscriptions
    "admin.backup",
    "api.v1",
    "notify.caps",  # 2.33.0 (#927)
    "notify.taskbell",  # 2.53.0 C (#1424): the bell of one task per person
    "tasks.dayplan",
    "tasks.briefing",  # 2.34.0 (#264)
    "lists.report",  # 2.34.0 (#265)
    "api.openapi",
    "integrations.webhooks",
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
    "sheets.vars",  # 2.89.0 (#1916): Kalmido variables of formulas, evaluated per viewer (no routes)
    "sheets.core",  # 2.89.0 (#1916): sheets, columns, rows, cells, agent batches (no routes; used by sheets.web and part C/D)
    "sheets.web",  # 2.89.0 (#1916): the routes of the tables area (/api/sheets)
    "sheets.step2",  # 2.89.0 (#1916, D): step 2 -- rows to tasks / quotation, a list as rows (by button)
    "collab.teamchat",
    "collab.msgsearch",  # 2.33.0 (#1080)
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
    "files.store",  # 2.48.0 (#1207): the file store (Ablage): tree, roles, versions (no routes; the interface of docs / import)
    "files.scan",  # 2.61.0 (#1818): virus scan of uploads (clamd), the later scan, the admin's scanner state
    "files.web",  # 2.48.0 (#1207): the file store's routes for the web app
    "files.v1",  # 2.48.0 (#1207): the file store in the REST API (files:read / files:write)
    "files.photometa",  # 2.61.0 B (#1819): photo metadata (GPS, camera) removed on upload (no routes; files/upsafe.py)
    "files.upsafe",  # 2.61.0 (#1818 #1819 #1820): the shared upload path - scan, metadata, text recognition (no routes)
    "integrations.mail",
    "accounts.invite",
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
    "contacts.model",
    "contacts.carddav",
    "contacts.web",
    "contacts.v1",
    "contacts.bulk",  # 2.46.1 (#1554): delete / move several contacts at once
    "contacts.merge",  # 2.66.0 A (#1835): merging duplicate contacts (reversible)
    "contacts.orgbooks",  # 2.52.0 C (#1438): address books an organisation owns
    "life.model",
    "life.karakeep",
    "life.web",
    "life.v1",
    "life.budget",  # 2.72.0 (#1333): the household budget
    "life.budget_web",
    "life.rss",  # 2.85.0 B (#1162): feeds
    "life.rss_web",
    "team.clients",
    "team.clients_bulk",  # 2.47.3 (#1733): several clients at once
    "team.clientmerge",  # 2.66.0 B (#1835): merging duplicate clients (reversible)
    "office.clientlink",  # 2.59.0 A (#1735): the address book search of the client dialog
    "team.workload",
    "hub.absence",  # 2.50.0 A (#1195): absences + German public holidays
    "hub.dispo",  # 2.50.0 A (#1194): resources and disposition (bookings of crew and equipment)
    "hub.agentdispo",  # 2.51.0 C (#1355): shoot planning by agents (event drafts, options), the disposition in the REST API
    "hub.hubmail",  # 2.84.0 A (#1198): e-mail as an input of the hub (mails filed with clients / projects)
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
    "office.pdfweb",  # 2.36.1 (#1021): quotation PDF + company logo routes (D; the writer office.pdf has no routes)
    "office.signoff",  # 2.50.0 C (#1200): approval links with a simple electronic signature (quotations, list acceptance)
    "office.ledger",  # 2.36.2 (#1021, #1142, E): finalising, structured company data, office log
    "office.invoices",  # 2.38.0 (#1021, F1): invoices, credit notes, reminders, payments, sending, DATEV inbox
    "office.doclang",  # 2.40.0 (#1381): language switch of drafts swaps the standard texts (no routes; used by office.docs)
    "office.countries",  # 2.40.0 (#1372): the ISO 3166-1 alpha-2 list (no routes)
    "office.contacts_cl",  # 2.40.0 (#1380): contact persons of a client (no routes; used by team.clients, office.docs, legacyimport)
    "office.legacyimport",  # 2.39.1 (#1182): legacy import (clients / services / equipment from .xlsx, archive of old PDFs)
    "office.archiveedit",  # 2.81.0 B (#1834): correct an archived document afterwards (client, tax lines, paid) + its history
    "office.parts",  # 2.47.0 (#1215): parts of a quotation (Teilangebote): routes, title page calculation, invoice modes
    "office.travel",  # 2.47.3 (#1022, part B): travel expenses (trips, receipts, evaluation, billing on)
    "office.cashflow",  # 2.47.3 (#1652, part B): cash flow per month + fixed costs
    "office.pipeline",  # 2.50.0 B (#1196): the sales pipeline
    "office.kpi",  # 2.50.0 B (#1197): the business figures
    "office.datev",  # 2.47.3 (#1460): DATEV booking batch (EXTF) of invoices, credit notes and payments
    "office.books",  # 2.90.0 A (#1921): bookkeeping light: income/expense statement (EUeR), VAT return figures, tax reserve, receipt photo
    "office.bank",  # 2.90.0 B (#1921): bank reconciliation: CSV / CAMT import, matching bookings to invoices and receipts
    "office.taxdates",  # 2.90.0 C (#1922): tax dates as recurring tasks (VAT return, income tax prepayments, trade tax)
    "office.agentdocs",  # 2.51.0 A (#1348, #1350): agents in the office: drafts, payment suggestions, the switches (API v1 + routes)
    "team.approvals",
    "tasks.review",  # 2.60.0 C (#1512): review step (reviewer, gate, list setting, API v1)
    "team.forms",
    "team.portal",  # 2.63.0 (#1513): customer reports (status link) and the customer portal
    "team.v1",
    "accounts.signup",
    "accounts.pwreset",  # 2.49.0 (#1531): "Forgot your password?"
    "accounts.discover",  # 2.49.0 (#1106): finding people by e-mail, connection requests
    "admin.hosting",
    "admin.clientip",  # 2.33.0 (#834)
    "tasks.stale",  # 2.34.0 (#266)
    "personal.timegaps",  # 2.34.0 (#269)
    "agents.agentpin",  # 2.51.0 C (#1352): agents on the pin board + the weekly status of a project
    "agents.agenttime",  # 2.51.0 C (#1353): agents check time tracking + propose entries from events
    "agents.lyprop",  # 2.55.0 B (#1066): agents propose arrangements of views (the person accepts)
    "admin.orgexport",  # 2.42.0 (#833): organisation export (encrypted archive)
    "admin.acctexport",  # 2.73.0 B (#1473): account export (moving between servers, GDPR copy)
    "admin.acctimport",  # 2.73.0 B (#1473): account import with the mapping of people
    "admin.orgcrypt_cli",  # 2.42.0 (#828): the organisation keys' start-up pass + command line (no routes)
    "docs.extract",  # 2.48.0 (#1111): date / due date / amount from a text (no routes, standard library only)
    "docs.rules",  # 2.48.0 (#1111): sorting rules (no routes)
    "docs.classify",  # 2.48.0 (#1111): the locally learning classifier (no routes)
    "docs.ocr",  # 2.48.0 (#1111): text recognition + preview images (no routes)
    "docs.store",  # 2.48.0 (#1111): documents: tables, sealing, word index, recognition run (no routes)
    "docs.ingest",  # 2.48.0 (#1111): docs_ingest + the background queue, mail / inbox folder
    "docs.thumbfill",  # 2.66.1 (#1944): one-time catch-up of the previews of imported documents (no routes)
    "files.textscan",  # 2.61.0 C (#1820): text recognition of normal stored files (queue, search, Ablage search route)
    "docs.web",  # 2.48.0 (#1111): the routes of the documents area
    "docs.v1",  # 2.48.0 (#1111): documents for agents (API v1 + OpenAPI)
    "sheets.io",  # 2.89.0 C (#1916): tables to / from CSV and .xlsx (export, import as a new sheet)
    "sheets.v1",  # 2.89.0 C (#1916): tables for agents (API v1 + OpenAPI)
    "paperless.ngx",  # 2.48.0 (#1152): Paperless-ngx connection + import into the documents (self-hosted only)
    "paperless.web",  # 2.48.0 (#1152): the routes of the Paperless-ngx connection (self-hosted only)
    "paperless.learn",  # 2.69.0 B (#1847): rules + learning from an import (URL and ZIP)
    "paperless.zipimp",  # 2.69.0 A (#1846): the import of an uploaded Paperless-ngx export (ZIP)
    "accounts.servers",  # 2.73.0 A (#661): several Kalmido servers in one app (server accounts, the other servers' /api/v1)
    "newsletter.adapters",  # 2.55.0 (#1455): listmonk / Brevo / CleverReach (no routes)
    "newsletter.sync",  # 2.55.0 (#1455): connection, segments, consent, the sync runs (no routes)
    "newsletter.web",  # 2.55.0 (#1455): the routes of the newsletter connection
    "receipts.suggest",  # 2.48.0 (#1356): receipts: project / category, agents suggest, people confirm
    "accounts.layouts_more",  # 2.55.0 (#1067): the new views' blocks for the agents' proposals (after agents.lyprop)
    "tasks.related",  # 2.59.0 B (#1375): related tasks (text vectors from the optional embedding service, API v1, agent events)
    "lists.points",  # 2.60.0 B (#1511): story points velocity (after api.v1)
    "office.fixedimport",  # 2.67.0 A (#1838): fixed costs from a spreadsheet + the monthly check task of the cash flow
    "agents.importprop",  # 2.68.0 A (#1839): agents propose old data for the office (fixed costs), the person takes it over
    "agents.meetprop",  # 2.70.0 A (#1354): a meeting becomes tasks (extract with photos, the chat's cards)
    "agents.dupprop",  # 2.70.0 B (#1357): duplicate contacts as a proposal (no routes)
    "agents.contractprop",  # 2.70.0 C (#1359): contract_notice + the proposal kind notice (no routes of its own)
    "lists.rules",  # 2.71.0 A (#1457): rules of a list (When ... then ...), after api.v1
    "admin.supporter",  # 2.74.0 (#338): the supporter licence (self-hosted only, a badge, unlocks nothing)
    "assistant.core",  # 2.75.0 (#1411): the built-in assistant -- configuration, model call, prompts (off unless configured)
    "assistant.web",  # 2.75.0 (#1411): the routes of the built-in assistant
    "startup",
)
MODULES = [importlib.import_module(f"{__name__}.{m}") for m in ORDER]
