<p align="center"><img src="static/icon.svg" width="112" alt="Kalmido logo: a friendly bot with two eyes and an antenna on a petrol tile"></p>

<h1 align="center">Kalmido</h1>

<p align="center"><b>You plan. Kalmido pitches in.</b><br>Tasks, team and office in one app for freelancers and teams: lists, calendar, projects, time tracking, quotes and e-invoices, receipts and bank, docs and wiki, plus AI agents that only act with your approval. Self-hosted with Docker, free for any number of people. AGPL-3.0.</p>

<p align="center"><a href="https://kalmido.com"><b>kalmido.com</b></a> · <a href="#quick-start">Quick start</a> · <a href="#updating">Updating</a> · <a href="TRANSLATING.md">Translate</a> · <a href="CHANGELOG.md">Changelog</a></p>

<p align="center"><a href="https://github.com/Gegenschuss/kalmido/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/Gegenschuss/kalmido?label=version"></a> <a href="https://github.com/Gegenschuss/kalmido/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/Gegenschuss/kalmido/actions/workflows/ci.yml/badge.svg"></a> <a href="LICENSE"><img alt="License: AGPL-3.0" src="https://img.shields.io/badge/license-AGPL--3.0-blue"></a></p>

<p align="center"><img src="docs/today.png" alt="Today view with the morning briefing, today's event, overdue tasks with their assignees and the project sidebar"></p>

<p align="center"><b><a href="https://kalmido.com/demo/">Try it in your browser</a></b>: no account, no server, your data stays in your browser.</p>

<p align="center"><b>Coming soon: Kalmido hosted.</b> No server of your own, we run it for you, on servers in Germany and GDPR-compliant. Self-hosting stays free.</p>

> **Language:** the interface is **English** by default, with **German** included and **French, Spanish, Italian and Dutch** in beta (machine-translated, corrections welcome); switch under *Settings > General > Language*. More languages are welcome, see [CONTRIBUTING.md](CONTRIBUTING.md#translations) and [TRANSLATING.md](TRANSLATING.md). Kalmido = calm + the Japanese -do (道, “the way”, as in aikido or judo): the calm way of getting things done.
> Kalmido is an independent project and not affiliated with or endorsed by any of the products or companies named here; their names are trademarks of their respective owners and are used only to describe compatibility (import, calendar, export, agents).

## What's new

**2.457.0** (2026-10-31):
- **Workspaces**: each workspace remembers its own view (page, open task, scroll position, sidebar) on every device.
- **Fields and board**: choice fields as a stage bar ("Ordered (stages)") and the board's time per card with yellow / red limits per column.
- **Moving**: the account export now includes project notes and encrypted task notes; the organisation export includes the team chat channels with their files.
- **Self-hosting**: on Windows `update.ps1` also makes a `pg_dump` into `data/backups/` before the update.

**2.436.0** (2026-10-31):
- **Office**: receipts by e-mail - forward invoice mails to your office address, Kalmido fetches linked invoice PDFs by itself; the client card's blocks fold and can be switched off per office.
- **Documents**: the list can be sorted (date, arrival, sender, amount, due date, title).
- **Settings**: "View as member" (Settings > Account) shows Kalmido as a member of your organisation sees it; the rights stay, the way back is in the account menu.
- **Projects**: properties per project type (software, agency, personal), switchable in the project options under Properties.
- **Agents**: git author for AI commits is a setting (agent settings, per project overridable).
- **Backups and restore**: larger files are kept once in `data/backups/.store` for all backups (2.432); copy the backup folder WITH `.store`; *Download* always gives one complete file; a copy elsewhere is made complete with `python3 -I kalmido/admin/bkstore.py assemble` (see SELF-HOSTING.md).

**2.430.0** (2026-10-30):
- **Projects**: ticket keys APP-123 (project dialog), linked from commits, branches and pull requests; saved filters by assignee, column, sprint, milestone and text; the agent API filters and sorts tasks by every field; "Project type" in folder settings.
- **Agents**: a live "working on it" mark on tasks (dot, name, time, last line) through the API / MCP.
- **Knowledge**: tags (#word) with a list in the panel, live query blocks, `![[Page]]` embeds, daily notes and template placeholders.
- **Office**: missing invoices of recurring providers with a link to their portal, a receipt fetcher for portal invoices, a booking archive for past DATEV years, final invoices after the BMF letter of 15.10.2026.
- **Documents**: the open document stands in a pane beside the list, arrow keys go through the list.
- **Moving**: office data moves between workspaces now also with deals, letter drafts and equipment sets.

**2.409.0** (2026-10-30):
- **Projects**: one kind of project; project folders live in the file store tree with shares that apply at runtime.
- **File store**: one area for files and documents (list or cards per folder, recognition per folder), locked end-to-end encrypted folders.
- **First start**: a short "What do you use Kalmido for?" for added accounts, Start as home page, tablets with the computer navigation, one Organisation area for people, agents and data.
- **Workspaces**: areas can be switched on and off per workspace (Private by each person, an organisation by its admins).
- **Knowledge**: reading styles, a "/" task picker, formulas (LaTeX) and Mermaid diagrams.
- **Office**: Quotations and Invoices as two areas, with a paid filter in the invoice archive.
- **Office PDFs**: quotation PDF with a compact closing and the totals at the bottom; logo size and side selectable in the office settings.
- **Entertainment receipts**: optional signature picture on the approval line, drawn in the app.
- **Software projects**: ticket keys like APP-123, linked from commits, branches and pull requests; saved filters by assignee, column, sprint, milestone and text.
- **Office**: receipts by e-mail, a booking archive for past DATEV years, final invoices after the BMF letter of 15.10.2026, quotation PDF with a compact closing.
- **Settings**: areas per workspace and "View as member" (Settings > Account).

**2.412.0** (2026-10-28):
- **Entertainment receipts**: optional signature picture on the approval line, drawn in the app.

**2.401.0** (2026-10-28):
- **Office**: Quotations and Invoices as two areas (Invoices with credit notes, reminders, delivery notes and a paid filter in the archive).
- **Agents**: personal agents are allowed per workspace (private area: the person; organisation: its admins; server switch: everyone).
- **Moving**: the account export now includes project notes and encrypted task notes; the organisation export includes the team chat channels with their files.

**2.376** (2026-10-28, seven packages in one train):
- **Office**: hand in receipts to the bookkeeping, GoBD export, take your part of an organisation's office into your personal one; refunds on credit notes, reverse charge hints, progress and final invoices.
- **Projects**: show a task in several projects (field "Projects" in the task panel, Alt-drag onto a project).
- **Knowledge**: live preview editor with "/" commands and tickable checkboxes; search hits show a text snippet.
- **Agent chat**: a calm one-row header, everything else in the "…" menu.
- **Offline**: typed text survives a closed tab, an expired session or a failed save; it is sent later, never twice.
- **Security**: downloads of backups and exports, restores and public links ask for your password first.

**2.361** (2026-10-27, fixes up to 2.361.3): split bank bookings across invoices, default interest and the 40 EUR flat fee on reminders, paper size A4 or US Letter, your own signature in office PDFs; members ask an admin to give back what they brought in.

Full history: [CHANGELOG.md](CHANGELOG.md).

## Why Kalmido

- **Free for everyone in the house or team.** No per-seat subscription, unlimited users, projects and tasks, and everyone you share a project with works in it for free.
- **One app instead of three.** Tasks, habits, focus timer and real time tracking with rates and timesheets, plus the team essentials: sharing, assignment, comments, activity, a News inbox, dependencies, project status and custom fields.
- **Simple when you want it.** Switch *Collaboration* off and it is a quiet personal project again.
- **Yours.** Runs on your own server, no vendor account, no telemetry (the update check asks GitHub for the latest version every 6 hours and can be switched off; everything else that leaves your server is listed in docs/SELF-HOSTING.md, Outgoing connections), open source under the AGPL-3.0. Fits a self-hosted setup: single sign-on through your proxy, Web Push or ntfy notifications, a calendar feed.
- **Honest trade-offs.** No native apps or widgets (it is an installable web app), no location-based reminders, and no support desk yet.

## Try it without installing

[kalmido.com/demo](https://kalmido.com/demo/) runs the real app in your browser with sample data in your language (a
client website project with sections, tickets, milestones, time entries and dependencies, a personal project, and a
simulated agent that waits for your approval). There is no server behind it: an in-browser stand-in for the API keeps
everything in your browser's storage, the page's Content-Security-Policy forbids every network connection
(`connect-src 'none'`), and there is no analytics. *Reset demo* brings the sample back. Features that need a server
(push notifications, CalDAV, calendar subscriptions, real agents, Git, webhooks, OIDC, more users) show a
short notice with the way to install.

The demo is built from the current sources by `python3 tools/build_demo.py [out_dir]` (static files only; serve the
folder with any web server, e.g. `python3 -m http.server` in it). CI builds it and opens it in jsdom
(`tests/demo_test.js`) so it cannot drift from the app.

## Quick start

Requirements: Docker with Compose on a 64-bit system (linux/amd64 or linux/arm64, also macOS and Windows with Docker
Desktop). Without the virus scanner **1 GB RAM** (about 250 MB idle); with it (the default of the installer and of
`.env.example`, `COMPOSE_PROFILES=localdb,clamav`) about **2.5 GB**, and the first start can take up to 5 minutes. On a
small server remove `clamav` from `COMPOSE_PROFILES` and set `KALMIDO_CLAMD=` empty. Details and disk, CPU and Raspberry
Pi advice: [docs/SELF-HOSTING.md](docs/SELF-HOSTING.md#requirements).

**Installer** (macOS, Linux; Windows: `irm https://kalmido.com/install.ps1 | iex`): downloads the latest release,
uses the prebuilt image (or builds it locally if that is not possible) and starts it on `http://localhost:3040`.
kalmido.com/install.sh (and `.ps1`) forwards to the installer of the latest GitHub release; it checks the download
against the release's `SHA256SUMS` and uses the image digest of the release.
It never uses sudo, writes an `update.sh` into the install folder (`~/kalmido`) and shows the one-time **setup
code** for the first account at the end. The scripts are in this repository: [install.sh](install.sh),
[install.ps1](install.ps1).

```sh
curl -fsSL https://kalmido.com/install.sh | sh
```

The same without the website:

```sh
curl -fsSL https://github.com/Gegenschuss/kalmido/releases/latest/download/install.sh | sh
```

<details>
<summary><b>Install by hand (git clone, or the prebuilt image)</b></summary>

**By hand:**

```sh
git clone https://github.com/Gegenschuss/kalmido.git
cd kalmido
git checkout "$(git tag --sort=-v:refname | head -n 1)"   # the latest release
cp .env.example .env        # set TZ, PUBLIC_URL and POSTGRES_PASSWORD at least
mkdir -p data secret        # create them yourself, so the container (user 1000) may write them
docker compose up -d --build
docker compose logs kalmido | grep "Setup code"
```

Instead of building, you can use the prebuilt image (linux/amd64 and linux/arm64): put
`KALMIDO_IMAGE=ghcr.io/gegenschuss/kalmido:X.Y.Z` into `.env` (X.Y.Z = the release you checked out, `git describe
--tags` without the `v`), then `docker compose pull && docker compose up -d`. On Linux with a user other than 1000,
give the folders to the container's user (`sudo chown 1000:1000 data secret`). The image runs as uid 1000 and read-only:
[docs/SELF-HOSTING.md](docs/SELF-HOSTING.md) *User and read-only image*.

</details>

Kalmido now listens on `http://127.0.0.1:3040`. The database runs in the `db` service (PostgreSQL 17, files in
`./pgdata`), attachments and backups live in `./data`, the server key in `./secret` (see below).
`docker compose ps` shows the service as *healthy* once it answers (`/api/health`).

<details>
<summary><b>First start: setup code, presets, sample project</b></summary>

Open it: the first start shows a **setup page** that creates the first account (the admin). It asks for the
**one-time setup code** that only the server's log shows (`docker compose logs kalmido`, a framed block *Kalmido first
setup*), so nobody else who reaches a fresh server first can make themselves its admin. The code works once; a
restart prints a new one; wrong codes are rate limited like logins. For tests and automation only:
`KALMIDO_SETUP_CODE=<fixed code>` or `KALMIDO_SETUP_CODE=off` in `.env`. A second step asks **what you want to use**, with three
starting points:

| Preset | For | On |
|---|---|---|
| **Simple list** (preselected) | a plain to-do list, a household | projects, subtasks, reminders, the calendar |
| **Just me** | one person who likes views | also timeline, kanban, matrix, habits, focus, statistics, project progress, comments |
| **Projects & team** | small teams up to about ten people, e.g. an agency | everything: sharing, assigning, comments, time tracking, the Gantt timeline with dependencies, custom fields |

Under *Customize…* below the cards you can switch single modules on or off (the matching card stays highlighted),
and pick the language; *Start* stays in view. The modules become the default for new users; collaboration and time tracking are switches for the whole
server. The welcome tour and the *Getting started* project only mention modules that are on. All of it can be changed
later in *Settings*.

Below that, one question: **Start with**: *Empty*, the *Sample project*, or a project of the type *Agency*,
*Software / AI dev* or *Personal* (sections, fields and settings for that kind of work; picking one switches the
modules it needs on). More projects any time: *Projects > + > New project*.

**Sample project.** *Sample project* under *Start with* and on the first card of every new account's welcome tour
(ticked when the project modules are on) adds a realistic example in the user's
language: *Example: Image film for client Muster* with the phases Concept, Pre-production, Shoot, Edit and Approval,
about fifteen tasks around today (overdue, today, next week, undated) with start dates for the timeline, dependencies
for *Flow* and *Now doable*, all four matrix quadrants, subtasks, a Markdown checklist, tags, a weekly status call, a
comment, custom fields, a time entry and a project status, plus the project *Example: Shoot day packing list* (completed
items at the bottom). It only
uses the modules that are on, stays private and quiet (no reminders, pushes, News or webhooks, not in the daily
digest). *Settings > Data > Sample project* creates it again or removes exactly what it created: sample tasks go even
if you edited them, tasks you added yourself stay, and so does their project.

<p align="center"><img src="docs/setup.png" width="560" alt="First-run setup: language, then what Kalmido is for (For me, Home, Family, Team, Software projects, Office &amp; finance) and a switch for all modules"></p>

</details>

> [!IMPORTANT]
> Use HTTPS (a reverse proxy) for anything beyond your own machine: the login sends your password and
> the session cookie is only marked `Secure` behind HTTPS.

**Server key and backups (2.45.0).** Without `KALMIDO_SECRET_KEY` in `.env` the server creates its key on the first
start in `./secret/kalmido.key` (mode 0600) and keeps using it; a key in `.env` always wins. It encrypts stored tokens
and the organisation data, and it is deliberately **not** in `./data`, so a backup never carries the key next to the
data it protects: keep a copy of the file somewhere safe (a password manager). Without any key, *Administration >
Server* shows a warning. A new server makes an **automatic backup every day** (03:30, 14 daily and 8 weekly kept, in
`./data/backups`; *Settings > Users > Whole server > Backups*); copy that folder to another disk too. The backup page warns when the
disk has room for fewer than three more archives; set a passphrase (see `docs/SELF-HOSTING.md`, "Disk space and passphrase").

The server remembers the fingerprint of its key: a different key than before does not start (`KALMIDO_SECRET_KEY_CHANGED=1` for a wanted change, then rewrap; see docs/SELF-HOSTING.md).

## Features

Kalmido is built from modules: switch on what you need under *Settings > Modules*, the rest stays out of sight. One line
per area here; the details are under [Documentation](#documentation), every single feature in the
[full feature list](#full-feature-list).

**Your own work**
- **Tasks and projects**: projects with folders, sections and Kanban columns, subtasks up to five levels, priorities, tags, pinned tasks, Markdown notes, attachments, drag and drop everywhere (also on touch)
- **Quick add** in plain language (`Dentist tomorrow 3pm !high #private ~Work`) and quick capture from anywhere (`q`, a bookmarklet, [sharing from your phone](#share-from-your-phone))
- **Dates and reminders**: recurring tasks (also any RRULE), reminders up to a year ahead, deadlines with a countdown, reminders that repeat until done
- **Today and planning**: smart lists (basket, today, next 7 days, *Now doable*), *Plan my day* between your appointments, a daily review, all overdue tasks moved in one click
- **Views**: calendar and timeline, a Gantt timeline with dependencies, a roadmap of all projects, the Eisenhower matrix, Kanban with WIP limits, sprints and burndown
- **Habits, focus and time**: habits with streaks, a Pomodoro timer and stopwatch, [time tracking](#time-tracking) with rates, rounding, CSV export and a printable timesheet
- **Templates, undo, statistics**: templates for tasks and projects, undo and redo of your last 30 changes, a trash with restore ([details](#templates-undo-statistics)); [notes](#notes) per project

**Together**
- **Sharing**: projects and folders shared with people or groups as admin, member, participant or viewer, tasks assigned (also to a group, "whoever has time"), public links ([Users and sharing](#users-and-sharing))
- **Comments and News**: comments with @mentions and files, reactions, an activity history, a News inbox and bundled push notifications
- **Project tools**: project types, dependencies, project status and progress, a project page, custom fields with formulas ([details](#projects-dependencies-status-custom-fields))
- **Workspaces and organisations**: a private space for everybody plus organisations with invitations, apart or together in one view ([Workspaces](#workspaces-work-and-private-apart), [Organisations](#organisations-and-invitations))
- **Clients, workload, approvals, forms** for small teams ([details](#clients-workload-approvals-forms), [docs/TEAM.md](docs/TEAM.md))
- **Team chat**: direct messages and a channel per shared project, agents included ([Team chat](#team-chat))
- **Start page**: what waits for you, today's tasks, News, the team chat and your projects on one page ([Start page](#start-page))

**Home and family**
- **Family**: birthdays, chores that take turns, children, shopping lists, a meal plan, household deadlines and packing lists ([Family](#family))
- **Home & life**: contracts & subscriptions, home & devices, staying in touch, health, review & journal, travel and budget ([Home & life](#home--life))
- **Reading**: read later, feeds and bookmarks per workspace ([Reading](#reading))

**Office, files and knowledge**
- **Office & finance**: quotes and invoices with PDFs, e-invoices, receipts, letters on your own letterhead, bank import and DATEV export ([docs/OFFICE.md](docs/OFFICE.md))
- **Files and documents**: folders and files for you and each organisation, with versions, a trash and sharing ([Files and documents](#files-and-documents))
- **Knowledge pages and tables**: knowledge spaces with a mind map, also offline, reading styles (Book, Compact, Notepad), formulas, Mermaid diagrams, a "/" task picker, and tables ([docs/WIKI.md](docs/WIKI.md), [docs/SHEETS.md](docs/SHEETS.md))
- **Events and contacts**: your own calendars and address books in Kalmido, synced with the phone's apps ([Events](#events), [Contacts](#contacts))

**AI agents**
- **Agents as team members**: Claude Code, Codex, n8n, a local model or your own script as a user of type *Agent*: sees only the projects shared with it, has its own token and an on/off switch
- **You stay in control**: control levels, approval cards for one-way steps, permissions per agent and token, data the agent never sees, usage limits and an activity log ([AI agents](#ai-agents), [docs/AGENT-SECURITY.md](docs/AGENT-SECURITY.md))
- **Events, chat and MCP**: signed webhooks or long-polling, a chat panel per agent, an MCP server and a setup guide ([docs/AGENTS.md](docs/AGENTS.md), [docs/AGENT-SETUP.md](docs/AGENT-SETUP.md))
- **Built-in assistant**: one language model of the operator's choice for small everyday helps ([docs/ASSISTANT.md](docs/ASSISTANT.md))
- **Git integration**: GitHub, GitLab, Gitea / Forgejo or Bitbucket Cloud at the tasks; hand a ticket to a coding agent ([Git integration](#git-integration))

**Connect and run**
- **Everywhere**: an installable web app (PWA) for phone and desktop that works offline and syncs later
- **Notifications**: Web Push or ntfy, plus Slack, Matrix, Telegram or Signal ([Notifications](#notifications))
- **Calendars**: [other calendars in Kalmido](#calendar-subscriptions-other-calendars-in-kalmido), [your tasks as a feed](#calendar-subscription-your-tasks-in-other-calendars) and [CalDAV both ways](#calendar-apps-caldav)
- **Tasks by e-mail**: a secret address for new tasks ([Tasks by e-mail](#tasks-by-e-mail))
- **Import and export**: Todoist, Trello, Asana, Microsoft To Do, TickTick, Notion, Google Tasks, ClickUp, Jira, CSV, Markdown and ICS, with a preview and undo; out again as Todoist CSV or Markdown ([Moving from other apps](#moving-from-other-apps))
- **REST API and webhooks** (OpenAPI 3.1) for Home Assistant, n8n or your own scripts ([docs/API.md](docs/API.md))
- **Login and security**: built-in login with two-factor and passkeys, single sign-on through your proxy or OpenID Connect, end-to-end encrypted notes and a lock per project, encryption at rest ([Login](#login))
- **Backups**: automatic daily backups, optionally encrypted, an off-site target, restore in the app ([Backups and restore](#backups-and-restore))
- **Languages, look and accessibility**: English and German, French, Spanish, Italian and Dutch in beta; dark or light, font size from 75 to 150 %; aims at WCAG 2.2 AA ([Language](#language), [Accessibility](#accessibility))

| | | |
|---|---|---|
| <img src="docs/calendar.png" alt="Month calendar"> | <img src="docs/matrix.png" alt="Eisenhower matrix"> | <img src="docs/habits.png" alt="Habits: the last seven days and streaks"> |
| Calendar | Eisenhower matrix | Habits |

### Dark mode

Every view also comes in a dark design: *Settings > Appearance > Color scheme* (Automatic follows your system).
The pictures on this page show the light design; here are a few views in dark.

| | | |
|---|---|---|
| <img src="docs/dark-today.png" alt="Today in the dark design: briefing, today's event and overdue tasks"> | <img src="docs/dark-calendar.png" alt="Calendar week in the dark design with all-day tasks and appointments"> | <img src="docs/dark-roadmap.png" alt="Roadmap of all projects in the dark design with progress bars and milestones"> |
| Today | Calendar | Roadmap |

<p align="center"><img src="docs/dark-office.png" width="560" alt="Office pipeline in the dark design: open value, expected income per month and the deals by stage"> <img src="docs/dark-mobile.png" width="170" alt="Today on the phone in the dark design"></p>

## Updating

Kalmido follows [semantic versioning](https://semver.org/); every release is listed in [CHANGELOG.md](CHANGELOG.md)
and on the [releases page](https://github.com/Gegenschuss/kalmido/releases). *Settings > Help* shows the running version
and, since 2.27.0, the version of the app in that window. A window that was open across an update shows *New version
available – Reload* and reloads by itself once nothing is being typed.

How to update depends on how you installed:

| Installed with | Update |
|---|---|
| the installer | `~/kalmido/update.sh` (Windows: `update.ps1`): backs up the database to `data/backups/` (from 2.37 a `pg_dump`; Windows: `update.ps1` also makes a `pg_dump` into `data/backups/`), adds a database password to `.env` if missing, then fetches the latest release and restarts |
| prebuilt image (`KALMIDO_IMAGE`) | set the new version in `KALMIDO_IMAGE` (or use `:latest`), then `docker compose pull && docker compose up -d` (2.149: `.env` needs a `COMPOSE_PROFILES` line, e.g. `COMPOSE_PROFILES=localdb,clamav`) |
| git + local build | `git fetch --tags && git checkout "$(git tag --sort=-v:refname \| head -n 1)" && docker compose up -d --build` (2.149: `.env` needs a `COMPOSE_PROFILES` line, e.g. `COMPOSE_PROFILES=localdb,clamav`, and Docker Compose 2.20+; the installer adds it) |

Back up first (*Back up now*, see *Backups and restore*). The database migrates itself on start; migrations only add, so the data of
an older version stays readable.

**Installing a specific version** (vX.Y.Z = a tag from the releases page): with the installer
`curl -fsSL https://kalmido.com/install.sh | KALMIDO_VERSION=vX.Y.Z sh` (the same variable pins updates:
`KALMIDO_VERSION=vX.Y.Z ~/kalmido/update.sh`); by hand `git checkout vX.Y.Z` or
`KALMIDO_IMAGE=ghcr.io/gegenschuss/kalmido:X.Y.Z`.

<details>
<summary><b>Updating from a version before 2.45, and the update check</b></summary>

**Updating to 2.45 or later from an older version:** the new `docker-compose.yml` keeps the server key in its own folder
`./secret` next to `./data`. Create it before the first start so the container (user 1000) can write the key file:
`mkdir secret && sudo chown 1000 secret`. If `KALMIDO_SECRET_KEY` is already set in `.env`, it stays in charge and the folder
stays empty. Otherwise the server creates a key once and from then on encrypts organisation data with it: keep a copy of
`secret/kalmido.key` apart from the backups of `./data` - a backup without its key cannot be read
(*Administration > Whole server* reminds you).

**Update check:** every 6 hours the server asks the GitHub API for the latest release and compares it with its own
version (after a failed check, e.g. GitHub's rate limit, again after an hour; right after an update at once). Admins then see a dot on the settings gear and, under *Settings > Administration > Server* (since 2.46.6; before *Settings > Help*), "vX.Y.Z installed — vX.Y.Z+1
available" with a link to the release notes. Nothing is downloaded or installed automatically, the container gets
no Docker access, and the browser never contacts GitHub. Switch it off under *Settings > Administration > Whole server* or
for good with `KALMIDO_UPDATE_CHECK=0` in `.env`. The update check uses api.github.com every 6 hours; an update pulls the image from ghcr.io, and update.sh downloads the installer of the latest release. The image `:latest` and the GitHub release appear only after the CI of that version is green (a few minutes after the tag).

</details>

## Backups and restore

*Settings > Administration > Whole server > Backups* (admins):

- **Automatic backups:** once a day at a set time (default 03:30) Kalmido writes one archive into `data/backups/`
  (`KALMIDO_BACKUP_DIR`): `kalmido-backup-<date>-<time>-auto.zip` with `kalmido.dump` (a consistent `pg_dump` made while Kalmido
  keeps running), `attachments/` (2.46.0: with the profile pictures, project icons and group pictures) and `manifest.json` (app and schema version, counts,
  size + SHA-256 of every file). 2.45.0: on by default for a new server (the first automatic one the day after the
setup); an existing server keeps its setting. *Back up now* makes one at any time.
- **Retention:** everything from the last 24 hours, then the newest backup of each of the last 14 days that have one
  and the newest of each of the last 8 weeks (both adjustable); the last 3 safety backups. Other files in the folder
  (e.g. the database copies of the installer's `update.sh`) are never touched.
- **Encryption (optional, off by default):** AES-256-GCM with a key derived from a passphrase (scrypt), in 1 MiB
  chunks whose order and end are authenticated (`.zip.enc`). The passphrase is set in the app (stored encrypted on
  the server, never shown again) or with `KALMIDO_BACKUP_PASSPHRASE`. **Without the passphrase an encrypted backup
  cannot be restored, by anyone.** Keep it in your password manager. Only the date, versions and counts are readable
  without it. Useful when the backups are copied to a place you trust less than the server.
- **Download** (admins only, streamed) and **Check** (decrypts, verifies every checksum and the database integrity
  without changing anything). Copy the folder somewhere else too: a backup on the same disk does not survive the disk.
- **Admin alerts** (*Storage and health*): a failed backup, no successful backup for 2 days, low disk space.

<details>
<summary><b>Restore: what Kalmido checks and does</b></summary>

**Restore** a listed backup or an uploaded file (larger files: copy them into the backup folder, they show up in the
project). You type `RESTORE` to confirm. Kalmido then:

1. checks the archive completely: only the expected members (`manifest.json`, `kalmido.dump`, `attachments/<task>/<file>`, 2.46.0: `attachments/avatars|listicons/<file>` - a 2.45 server refuses such an archive; 2.79.0: `attachments/chat|budget|docthumbs/...` - a 2.78 server refuses such an archive;
   no paths outside, no links, no folders), size and member limits (`KALMIDO_BACKUP_MAX_MB`), compression ratio (zip
   bombs), free disk space, every SHA-256 while extracting, the dump's table of contents and statements (only tables,
   data, sequences, indexes, constraints and plain defaults are taken; functions, triggers and access rules are always
   rebuilt by Kalmido), a schema version this Kalmido can migrate (a backup from a newer version is refused);
2. switches to maintenance (other requests get "please try again in a minute", background jobs pause) and waits
   until nothing else runs;
3. makes a **safety backup** of the current state (listed as "before a restore");
4. swaps the attachments folder and replaces the database with `pg_restore` (one transaction), runs the migrations;
   if anything fails, the previous database and attachments are put back. Backups from before 2.37 (`tasks.db`) are
   moved over into PostgreSQL the same way as on the first start of 2.37;
5. ends every session except yours (you get a fresh one; with single sign-on nothing changes). The backup settings
   themselves stay as they are.

Restoring the safety backup undoes a restore. Without the app: see *Backup* in [docs/SELF-HOSTING.md](docs/SELF-HOSTING.md)
(`pg_restore` of `kalmido.dump`, attachments unzipped into `./data`).

</details>

*Settings > Data > Export* gives every user a JSON dump of their own data.

## Documentation

Everything in detail, folded: click a title to open it. More in [docs/](docs/): [self-hosting](docs/SELF-HOSTING.md), [all settings](docs/ENV.md), [API](docs/API.md), [agents](docs/AGENTS.md), [office](docs/OFFICE.md), [architecture](docs/ARCHITECTURE.md).

[Try it locally](#try-it-locally) · [Accessibility](#accessibility) · [Full feature list](#full-feature-list) · [Moving from other apps](#moving-from-other-apps) · [Users and sharing](#users-and-sharing) · [Start page](#start-page) · [Family](#family) · [Workspaces: work and private apart](#workspaces-work-and-private-apart) · [Organisations and invitations](#organisations-and-invitations) · [Clients, workload, approvals, forms](#clients-workload-approvals-forms) · [Home & life](#home--life) · [Reading](#reading) · [Events](#events) · [Contacts](#contacts) · [Team chat](#team-chat) · [Files and documents](#files-and-documents) · [Offline knowledge, office projects, pictures](#offline-knowledge-office-projects-pictures) · [Notes](#notes) · [Tasks by e-mail](#tasks-by-e-mail) · [Calendar subscriptions (other calendars in Kalmido)](#calendar-subscriptions-other-calendars-in-kalmido) · [Calendar subscription (your tasks in other calendars)](#calendar-subscription-your-tasks-in-other-calendars) · [Calendar apps (CalDAV)](#calendar-apps-caldav) · [REST API and webhooks](#rest-api-and-webhooks) · [AI agents](#ai-agents) · [Git integration](#git-integration) · [Templates, undo, statistics](#templates-undo-statistics) · [Time tracking](#time-tracking) · [Projects: dependencies, status, custom fields](#projects-dependencies-status-custom-fields) · [Login](#login) · [Reverse proxy](#reverse-proxy) · [Configuration](#configuration) · [Language](#language) · [Notifications](#notifications) · [Share from your phone](#share-from-your-phone) · [Tech](#tech) · [Limits](#limits) · [How this was built](#how-this-was-built) · [Contributing and contact](#contributing-and-contact) · [Supporter licence](#supporter-licence)

<details>
<summary><a id="try-it-locally"></a><b>Try it locally</b></summary>

No proxy needed for a quick look. After the quick start above, open **http://localhost:3040** on the same machine.
Everything works there, including installing it as an app and offline mode (browsers treat `localhost` as secure).
Push notifications and `/drop` stay off until you configure them.

To try it from your phone or another device on your network, change the port line in `docker-compose.yml` to
`"3040:3040"`, run `docker compose up -d` again and open `http://<your-computer's-ip>:3040`. Over plain HTTP the
app works, but it cannot be installed and has no offline mode.

> [!WARNING]
> Over plain HTTP your password travels unencrypted through your network. Fine for a test at home; for daily
> use put it behind a reverse proxy with HTTPS (next section) and switch the port back.

To remove the test again: `docker compose down` and delete the folder (your test data is in `./data`).

</details>
<details>
<summary><a id="accessibility"></a><b>Accessibility</b></summary>

Kalmido aims at **WCAG 2.2 level AA**: everything works with the keyboard (one Tab stop per project, ↑ ↓ to move, Enter to
open, Esc to go back, `?` for all keys), the focus is always visible and never hidden, screen readers get names, roles,
states and announcements, errors are said in words, colour is never the only signal, every drag has another way
(menu items, Alt+↑ / Alt+↓, keys on the grips), touch targets are 44 px, *reduce motion* and Windows high contrast are
respected, and the app reflows at 320 px and 200 % zoom. An automated test with axe-core checks the main views in light
and dark and with every accent colour on every change. Details and known limits: [docs/ACCESSIBILITY.md](docs/ACCESSIBILITY.md).

</details>
<details>
<summary><a id="full-feature-list"></a><b>Full feature list</b></summary>

**Projects**
- Projects with emoji, own picture or colour, project folders with one level of subfolders, sections (Kanban columns) with a "+" each, collapse / expand all, archive
- **Folders and subfolders**: *Clients › Company X*. The sidebar is a tree (a folder's projects, then its subfolders),
  folded folders stay folded on all your devices. Drag projects into a subfolder, a subfolder into another folder or onto
  *Projects* (top level); the folder menu (…) has *New subfolder…*, *Rename*, *Move into a folder…* / *Move to the top
  level* and *Dissolve* (projects and subfolders move up one level). Opening a folder shows the tasks of all its projects,
  subfolders included, with a small header per subfolder. In the project dialog type `Clients / Company X`. A project in
  its owner's folder sits for everyone in that folder and place, and the owner's folders keep their order among each
  other in every member's sidebar (2.27.0); a shared project without a folder can be filed where each member likes. The
  sort of a shared project is set by its owner or a project admin for everyone; a member may sort it otherwise on one device
  and the project says so. The API takes and returns the path (`"folder": "Clients/Company X"`, at most two levels)
- **Quick capture** from anywhere: `q` (or Ctrl+Space, also while typing somewhere else) opens a small box, the quick
  add syntax works and it lands in the basket whatever view is open (unless you name a project). The installed app's icon
  menu has *Quick add*. The page `/capture` holds a **bookmarklet**: drag it to the bookmarks bar, click it on any
  page and a small window opens with the page's title and address, Enter saves it to your basket (your normal
  sign-in, no code of Kalmido runs on that page). A system-wide key for it: Windows: Start menu > right-click Kalmido >
  More > Open file location > Properties > *Shortcut key*; macOS: Shortcuts app > *Open URL* `https://your-host/capture` >
  *Add keyboard shortcut*; GNOME / KDE: a custom shortcut that opens that address
- Drag and drop everywhere, also on touch: tasks onto a section header or into an empty section, sections by their
  handle (list and kanban), projects and folders in the sidebar (long-press on a phone); on a phone a long press
  selects a task (a bar with *Move*, *Date*, *Complete*, *More*; tap more tasks to add them, drag by the grip), and in
  the open task a swipe left or right goes to the next or previous task
- Drop files from the desktop on a project: one new task per file, with the file attached
- Subtasks up to five levels, drag and drop between projects and levels
- Priorities, tags, pinned tasks (the smart list *Pinned* collects them from every project, 2.16), Markdown notes, attachments (images, PDFs, documents)
- Long descriptions fold to a few lines; *Show more* keeps the following tasks unfolded too until *Show less* (per device, 2.101).
- A website link per task, shown as a small domain chip (paste a URL in quick add or share a page from Android)
- Quick add with two extra buttons (2.14): *Add and open details* creates the task and opens it at once, the paper clip creates it with files attached (the file name is the title when none is typed)
- Natural-language quick add in English and German, whatever the interface language, plus French, Spanish, Italian or Dutch when the app runs in that language: `Dentist tomorrow 3pm !high #private ~Work`, `Zahnarzt morgen 15 Uhr !hoch #privat ~Arbeit`, `Dentiste demain 15h !!! #privé`
- Recurring tasks (daily, weekdays, weekly, monthly, yearly, every n days / weeks / months with weekdays, or any RRULE for experts) with end date, count and skip
- **Dates save as you pick them** (2.6.1): in the date popover every tap (day, time, start, duration, reminders,
  repeat) is saved at once and the popover stays open for more; *Done* (or a click outside, Esc) closes it and leaves
  one undo step with *Date: … · Undo*, *Undo* in its foot puts everything back. *Settings > General > Confirm changes
  with OK* brings back Cancel / OK
- **Reminders well ahead and deadlines** (2.7.0): reminders from *On time* to *1 month* before as chips, or any number
  of minutes, hours, days or weeks up to a year with *Other…* (also as the default reminder). Tick *Deadline* and the
  task counts down on its row and in the task panel (*12 days left*), highlighted from its first reminder on;
  *On Today from the first reminder* also puts it on Today from then on
- **Repeat reminder until done** (2.7.0): a task's reminder can repeat every 5, 10, 15, 30 or 60 minutes or daily
  until it is completed, starting with its first reminder (e.g. *2 weeks before the deadline, then daily*). Set it per
  task in the date popover, or as the default of a project (project dialog). The push offers *Done*, *Stop reminding* and
  *Snooze*. Nothing repeats during your quiet hours (*Settings > Notifications*, 22:00 to 07:00 by default), for a
  project whose bell is muted, or with *Repeated reminders* switched off in the notification matrix; completed, deleted
  and archived tasks stop at once, and every interval sends one push at most
- Smart lists (basket, the start view; today, tomorrow, next 7 days, now doable, all), combinable filters (project, date, priority, tag)
- **Plan my day** (2.10.0): in Today, *Plan my day* puts your open tasks into the free time between the day's calendar
  events and timed tasks within your working hours (*Settings > General > Day planning*): overdue and due first, then
  deadlines and priority, 30 minutes for a task without a duration; what does not fit is listed as *does not fit
  today*. *Fill free time* only fills the gaps with tasks not planned yet. A timeline preview, leave out what you like,
  one undo step. Planning sets only a task's planned start and duration (2.11.0): **due dates, times and deadlines never
  change**; planned tasks show in Today with their time and can be unplanned in the task panel. With an agent online, *Let an agent plan* asks it for the same plan as a proposal that you approve
- **Daily review** (2.10.0): after your working hours Today shows what you finished, what is still open and what you
  moved, with a suggestion for the next working day; optionally as a push at a time you choose
- **Now doable** (`g d`): what you can start right now: open, not waiting on another task, due today, overdue or
  undated, and yours (assigned to you, or unassigned in your own projects; everything with collaboration off). In the
  order the dependencies allow, with a count in the sidebar; pin it as a tab like the other smart lists
- **Overdue in one click**: on top of Today, *3 overdue → Today / Tomorrow / Next week (Mon) / Pick a date…* moves
  every overdue task you may change at once (time and repeat stay, view-only ones are skipped and counted), one undo
  step; the × hides it until tomorrow on that device
- Multi-select (Shift-click a range, Ctrl/Cmd-click single tasks) and multi-edit in the task panel (2.26.0: the shared fields of all selected tasks, *Mixed* where they differ, one undo step), snooze, trash with restore, search in titles, notes and links
- **Undo and redo history**: ← / → in the top bar step back and forward through your last 30 changes (edits,
  completing, deleting, moves, sections, project settings, batch actions, moving projects); right-click or long-press ←
  to jump back several steps. Ctrl/Cmd+Z, Ctrl/Cmd+Shift+Z, Ctrl+Y; on phones *Undo* / *Redo* sit at the top of the header's “…” menu (touch tablets and an unfolded foldable keep the arrows in the header while there is room).
  Settings changes are steps too. Never overwrites what others changed meanwhile, works offline
- **Settings save themselves**: every switch, field and choice applies at once with a small *Saved · Undo*; one
  *Modules* page with a sentence per module; developer things (API tokens, webhooks, rule texts) folded under
  *Advanced*; the upload token for sharing from a phone lives in one place, *Integrations > Share from your phone*
- **Archive instead of delete** for projects (undoable); deleting for good only from the archive, with a dialog that names
  what is lost. All questions use the app's own dialog, and whatever can be undone asks nothing. Tasks of an archived
  project stay out of Today, filters, the calendar, reminders and the digest until you restore it. *Archived* in the
  sidebar opens all archived projects (tasks, folder, archived date, owner) with Open, Restore and Delete permanently
- **Folder view**: click a folder name in the sidebar for all its projects' tasks in one view, grouped by project
- **One tap "Today" / "Tomorrow"** in the task menu, the task panel and the selection bar (keys `t` / `Shift+T`);
  time, reminders and repeat stay. **Completed tasks are shown** everywhere; hide them per project, filter and smart list
  (its “…” menu) or in the calendar (its bar)
- **Own date and time pickers** in the app language: a small month grid (the week starts on your locale's first day)
  and hours / minutes you can also type (`930`, `9:30 pm`, `21 Uhr`); keyboard and touch friendly
- **Templates**: save a task with its subtasks, or a whole project with sections, and reuse it with dates relative to today;
  **Duplicate project…** (2.78.0) copies a project at once with its dates as they are (completed tasks optional, no members)
- **Every list is a project** (2.152.2): the switch *Progress and status* in the project dialog turns on the progress ring,
  the status, the project page and the row in *All projects* (dependencies with the Gantt timeline and custom fields have
  their own switches). Every project can **show completed at the bottom** (what you tick off stays there and comes
  back with one tap: shopping and packing lists). Set it in the project dialog or the project's menu; with the switch off
  a project stays free of project controls (the repository section shows only with the switch on or for a project that already has one)
- **Running indicator** in the top bar: time tracking, a focus session or the stopwatch, each with its own icon, the
  time and the task; a click shows the task with Pause / Stop. The *Time tracking* page shows a running timer as a
  large card (live time, task, project, start, Stop)

**Views**
- Calendar (month, week, day) and a timeline, drag tasks onto days; swipe to turn the page, pinch to zoom the hours (2.164.0)
- **Gantt timeline**: dependency arrows between the bars, a red mark when a task starts before the one it waits on is
  due, link two tasks by dragging from one bar onto another (long-press on a phone, keyboard too), and optionally
  *Move dependent tasks along* when a date slips, with one undo for the whole chain
- **Roadmap**: *All* as a timeline: every project on one chart, grouped by folder, collapsible to one summary bar per
  project with its progress; drag a summary bar (or long-press it on a phone) to move the whole project, one undo
- **Calendar subscriptions**: events from Google Calendar, iCloud, Outlook or any CalDAV server (Nextcloud, Radicale,
  Fastmail, ...) right next to your tasks, read-only, with "Create task from event"
- Eisenhower matrix (priority x due date)
- Kanban per project, with WIP limits per column, story points and sprints with burndown and velocity (2.60.0)
- Review step per project: reviewer, done only after approval; environments (Staging, Live) per project (2.60.0)
- **Statistics**: completions per week / day and per project, on-time rate, overdue trend, focus time, habit streaks

**Habits, focus and time**
- Habits per day or *n* times per week, counters (e.g. 8 glasses of water), notes per day, streaks
- Pomodoro timer and stopwatch, focus minutes per task
- **Time tracking** (2.41.0: its own switch per project, any project type): a timer on any task that follows you across devices, manual entries, hours per project and task
  for any period, rounding, hourly rates, CSV export and a printable timesheet
- **Time sum in the project header** (2.7.0): a project with time tracking (and a folder of them) shows its tracked time in hours and in
  working days, e.g. *12.5 h · 1.6 days*. The length of a day / shift is one value for the whole server
  (*Settings > Administration*, 8 h by default) that a project can override in its dialog, the same for everyone in it. A
  number field *Budget h* (the agency project type has one) adds a budget bar: tracked against the sum of the budgets

**Together**
- Several users, each with their own basket, habits, filters, tags, settings and notifications
- **Groups** (2.10.0): an admin creates groups (*Office*, *Field team*; optionally synced from a sign-in group of the
  OIDC provider). Share a project or a whole folder with a group and a role: whoever joins gets access, whoever leaves loses
  it, and a person's role is the higher of their own and the group's. Assign a task to a group, "whoever has time": it is
  in *Assigned to me* for every member until one of them takes it. Groups appear under *Team* in the sidebar
- **Shared project tags** besides your personal tags: tags that belong to a project, with a colour per project, visible to
  everyone in it (`1.9.0`, `bug`, `Client X`). In shared projects the tag input suggests project tags first; your personal
  tags keep a small person icon, and one click turns a personal tag into a project tag. Filters, the sidebar and the API
  know both
- **Reactions** 👍 👎 ❤️ or any emoji (+) on comments, with the names on hover or tap
- Share a project with others as admin, member, participant (sees only the tasks assigned to them) or viewer; shared projects show up in their smart lists, calendar and search
- Assign tasks and subtasks in shared projects, with an assignee column (pictures, one click to assign): reminders go to the assignee, plus an *Assigned to me* list
- Comments on every task with @mentions and files, at the end of the task panel with the comment box always at the bottom edge (2.0.6: also as personal notes in private projects, own *Comments* module), an activity history (who changed what, when) and unread markers
- A *News* inbox (bell icon with an unread badge): mentions, comments on your tasks, assignments, completions, unblocked tasks, status updates and projects shared with you, newest first; filter *Mentions & assigned to me* and *Unread only*
- **Dependencies:** a task can be *blocked by* other tasks (also in other projects); it shows *blocked* until they are done, and its assignee gets a message when the last one is finished
- **Waiting on someone** (2.1.0): mark a task as waiting for someone outside (a client, an office, a delivery) with a note and a follow-up day (task menu > *Waiting on someone…*, or *Waiting on…* in the task panel, which also offers *Another task*). It shows an hourglass chip, sits in the smart view *Waiting on someone*, and on the follow-up day you get a reminder and a News item, while agents that follow the task get the event `followup_due`. One click (the × on the bar in the task panel) ends it. API: `PUT` / `DELETE /api/v1/tasks/{id}/waiting`, `GET /api/v1/tasks?waiting=true`; MCP `set_waiting`, `clear_waiting`, `list_waiting`
- **Project status and progress:** a progress bar per project, a status (*On track*, *At risk*, *Off track*, *On hold*, *Complete*) with a short note, and the **project status** (*Where is it stuck?*) with the overdue, blocked and unassigned tasks across all projects
- **Project page:** every project has a tab next to List / Kanban / Timeline with its description (Markdown), key links, milestones (also in the timeline), project files plus the files of its tasks, members, status updates and the tracked time
- **Custom fields** per project: text, number (with unit), currency, selection with colours, multiple choice, rating, date, checkbox, person, link or a link to another task; formulas with IF, SUM, ROUND, MIN, MAX; shown as chips or columns, usable in filters, sorting and search
- **Shown fields per project** (2.14): project *…* > *Shown fields…* (or the button in the project header) picks which columns the
  rows show and in which order: task number, date, priority, assignee, tags, tracked time, subtasks, dependencies,
  created and the project's custom fields. The setting belongs to the project, so every member sees the same; the owner and
  project admins change it, *Default* goes back to the standard layout. Desktops show a title row above the columns; where
  the list column gets narrower (a Fold, the task panel open) and on phones the first two columns stay in the row and the
  rest moves into its second line. API v1 (`columns` on projects) and the MCP tool `set_list_columns` read and set it
- Push notifications for new comments, mentions, assignments and completions, bundled so a busy task does not spam you
- **Public links**: share one project with people who have no account through a secret link, view only or *view and tick off*, with an optional password and expiry
- One switch (*Collaboration*) turns all of this off for a simple personal task list, per person or (admins) for the whole server;
  *Dependencies* and *Custom fields* are modules of their own, so a household project stays simple while a small team
  (an agency, a club) gets the project tools
- Built-in login or single sign-on through your reverse proxy (Authelia, Authentik, oauth2-proxy)
- **Two-factor authentication** for the built-in login: authenticator app (TOTP) with recovery codes, or **passkeys**
  (also for logging in without a password); admins can require it for everyone
- **Log in with an OpenID Connect provider** (Authentik, Keycloak, Authelia, Google, ...): code flow with PKCE, only
  accounts an admin created (or automatic accounts, if you want), optional group check and admin group
- **Encryption** (2.42.0): an end-to-end encrypted note and files per task and encrypted direct messages (WebCrypto in
  the browser, the server only stores ciphertext), plus encryption at rest with a key per organisation for bank and tax
  data, purchase and contract rates and stored files (needs `KALMIDO_SECRET_KEY`; see SELF-HOSTING.md)
- **Lock per project** (2.64.1): a project can be *encrypted in the browser* (project dialog): titles, descriptions, subtasks,
  comments, project notes, section names, text fields, links and code snippets are encrypted with a key per project that each
  member gets wrapped with their own key; dates, status, assignees and the project name stay readable. Members without a key
  wait until the owner releases it; agents, the mail address, public links and templates are not available there.
  Since 2.64.2 attachments and the project's team chat are encrypted too, and the key changes when a member leaves;
  since 2.64.3 a whole knowledge space can be encrypted the same way (see docs/ARCHITECTURE.md, *Lock per list*, and
  docs/SELF-HOSTING.md, *Exporting encrypted content*)
  data, purchase and contract rates and stored files (needs `KALMIDO_SECRET_KEY`; see SELF-HOSTING.md). 2.64.0: the files
  of the private space are stored encrypted on the server as well, with a key per person (server-side, not end-to-end)
- **Automatic backups** of the database and all attachments, daily with retention, optionally encrypted, downloadable,
  and a **restore** right in the app (checked, with a safety backup of the current state first); encrypted backups can also go to an
  **off-site target** (S3-compatible, WebDAV over https or SFTP) after each run (2.143.0)
- **Admin alerts** over each admin's own channel (Web Push or ntfy): a new version, devices that stopped taking pushes, watchdog errors, failing integrations, repeated failed logins, low disk space or a failed database check reach the admins, never with task contents

**AI agents**
- **Agents as team members**: an admin adds an agent (Claude Code, Codex, n8n, a local model, your own script) as a
  user of type *Agent*: never an admin, sees only the projects shared with it, with its own API token, an
  optional webhook and an on/off switch that stops everything at once
- **Settings > Agents** (called *AI colleague* before 2.6.0; 2.7.0: shown while the *Agents* module is on, and to
  admins while agents exist): one tab in four sub-tabs (2.5.1). *Status* (2.7.0, was *Overview*): a card per agent with its state, projects and
  usage; admins add, edit, test and pause them there (username, display name and profile picture: a preset, an own
  photo or the initials). *Projects*: which projects each agent sees, *Share all* / *New projects automatically*, and a table
  of the projects you manage (shared ones first, *Show all*, search): which agent sees it (one click shares or unshares),
  its tidy mode and which agent tidies it up. *Usage* and *Log* (admins) below
- Agents get **events** as signed webhooks or by **long-polling** (no public endpoint needed): @mentions, assignments,
  comments on their tasks, chat messages and reactions. A task event
  brings the task's newest comments and the project's sections along, so the agent can act at once; project pages can be
  fetched compact
- **Approvals**: 👍 / 👎 on an agent's comment from the project owner, a project admin or the assignee counts as approval or
  rejection; nothing needs to happen without it. 2.15.0: deleting projects or fields, emptying the trash, changing 10+
  tasks at once, moving projects and sharing by an agent always wait for *Approve* (then run as the agent) or *Reject*
- **Permissions** (2.15.0): each agent and each API token gets only what it needs: *Read*, *Tasks*, *Comments*,
  *Structure*, *Delete & trash*, *Read / Upload files*, *Time tracking*, *Export* (new agents: read, tasks, comments).
  Admins set them for team agents, owners for their personal agents (lock button); a server-wide limit and an optional
  address restriction per token; the MCP server shows only the allowed tools
- **Status and jobs**: a dot on the agent's avatar (idle, working, waiting for you, error), a chip in the top bar
  (*Claude · 2 running · 1 waiting*) and an *Agents* tab with its jobs, a short log and *Approve* / *Reject* / *Stop*
- **Chat** with an agent in a side panel (a tab on the phone); the agent can create tasks and comments within its rights.
  The header shows typing dots while it writes to you and what it is doing: *working on #51*, *waiting for you*,
  *ready*, *paused*, *limit reached* or *offline* (2.4.1). 2.13.1: send screenshots and files in the chat (paperclip,
  paste, drag and drop, or *Send to agent* from the phone's share sheet); thumbnails open in a lightbox, the sender can
  remove a file, and agents can read chat, task and comment files through the API / MCP (`get_attachment`)
- **Agent reads every comment** (2.13.1): per project, the checked agents hear about every comment people write there, not
  only on tasks they follow (on by default for the project's tidy agent)
- **Tidy up** per project (off, suggest, automatic) by exactly one agent of the project (*Tidy up by*, 2.4.1): it turns
  quickly typed entries into a short title, section and tags; the original text stays at the top of the notes, a
  suggestion is applied with 👍
- **Runtime settings** per agent (2.4.1): model, auto-compact threshold, a nightly fresh restart and *Reset now*.
  Kalmido only stores them; the agent's host applies them ([mcp/agent_launcher.sh](mcp/agent_launcher.sh) for Claude Code)
- **MCP server** ([mcp/](mcp/)) so agents can use Kalmido as a tool, and a protocol description in
  [docs/AGENTS.md](docs/AGENTS.md). 2.15.0: everything the app does is in the API and the MCP server (a test checks it)
- **Setup guide** ([docs/AGENT-SETUP.md](docs/AGENT-SETUP.md), in the app under *Settings > Agents > Set up*): an agent step by step, either by pasting one prompt into Claude Code or by hand (sandbox user,
  firewall, MCP wrapper, rules, event loop, autostart, test checklist)
- **Usage and limits** (2.1.1): agents report their model usage (tokens, optionally the cost; numbers only, never
  prompts); *Settings > Agents > Usage* shows today / 7 / 30 days per agent, behind *Details* a chart per day, top tasks, projects and
  models (admins: every agent; others: the agents and projects they share), the Agents view a compact card, the task panel
  *AI usage*. Per agent a soft limit (News + push to the admins at 80 % / 100 %) and a hard limit (its API calls get
  `429` until the next day / month or a higher limit). A Claude Code Stop hook ([mcp/claude_usage_hook.py](mcp/claude_usage_hook.py))
  reports a session's usage by itself, and as SubagentStop hook (2.11.0) the usage of its subagents too
- **Activity log** (2.2.1): every API request an agent makes (route, status, task / project, duration; never content) in
  *Settings > Administration > Agents* for admins (2.46.6; before *Settings > Agents > Log*), filtered by agent, status and day, event polling hidden by default, denied calls marked, CSV export;
  kept `KALMIDO_AUDIT_DAYS` days (default 90)
- **Git integration** (2.2.0, 2.18.0): connect a project to GitHub, GitLab, Gitea / Forgejo or Bitbucket Cloud; pull requests (state, CI), commits
  and branches show up at their tasks (`#123`, `kalmido-123`), `fixes #123` in a merged pull request completes the
  task. Works by polling, so the server needs no public address. **Hand a ticket to a coding agent**: it gets the
  repository and a branch name with the assignment and merges only after your 👍 on its *Ready to merge* comment
  ([Git integration](#git-integration))

**Fast and friendly**
- **Resize the panels** (2.16; the sidebar too since 2.26.0): drag the edge between the list and the task, or between the task and the chat, to
  make them wider or narrower (desktops, an unfolded Fold; each device remembers it, a double-click goes back to the
  standard width; with the keyboard: focus the grip, ← →, Enter). **Column widths** work the same way: the grip at the
  right of a column title (per device and project)
- Command palette (Ctrl/Cmd+K, the field at the top of the sidebar) for tasks, projects, views and actions, the recently
  viewed ones on top; type text and pick *Ask <agent>: …* (sends it to the agent's chat) or *Create as task: …* (quick
  add syntax; Enter when nothing else matches); `#123` jumps to task 123; keyboard shortcuts (`?` shows them all: arrows, Space to complete, E to rename in the project; calendar 1-4 / ← → / `.`; multi-select Ctrl/Cmd+A, Shift+↓ ↑, Shift+X, then Space, M or D for the selection; D / M open the date / project field of the multi-edit panel), compact, comfortable or custom density (the sidebar and the task rows each on their own); your account sits as your picture at the right of the *Kalmido* row (Account, Settings, Log out)
- New accounts start with a "Getting started" project and a short welcome tour
- A **sample project** to try things out: an image film for a client with phases, dates, dependencies, custom fields and a packing checklist, offered in the setup and the tour, removed again in one click (Settings > Data)
- When Today is clear or a project is done, the Kalmido bot celebrates (with one of 50 dry one-liners). Can be switched off.

**Everywhere**
- Installable web app (PWA) for phone and desktop, works offline: changes queue up and sync later, with conflict detection
- Sorting per view: priority, manual, date, title, *Created* (newest or oldest first, with the creation day on the rows), Flow and custom fields
- On phones every choice list (project, section, assignee, settings) opens as a bottom sheet like the app's menus: icons, a check on the current value, a search field for long lists
- Mobile layout with swipe gestures, long-press drag, configurable tab bar per device (on the desktop one sidebar with grouped navigation: Focus, Views, Projects, Filters, Tags and Team); tablets in portrait keep the composer at the bottom
- Push notifications without an extra app (Web Push: Chrome, Edge, Firefox, Safari, iPhone and iPad from the Home Screen) or via [ntfy](https://ntfy.sh): reminders with *Done* / *Snooze*, focus end, habit reminders, daily digest, comments and assignments; a notification you handled on one device (task completed or opened, News read) closes on your other devices
- **Slack, Matrix, Telegram or Signal** as extra channels (2.142.0): each person picks which kinds go there (reminders, assignments, mentions, digest, changes in own projects), organisation admins add a team channel for projects everyone in the organisation sees; the address stays encrypted on the server. People without a push device get assignments and mentions by **e-mail**, collected into at most one mail every 10 minutes (off / only without push / always, *Settings > Notifications*)
- Share from your phone into the basket: a ready-made import for the Android app HTTP Shortcuts, a guide for the iPhone Shortcuts app (see below); app shortcuts (long-press the icon: new task, today, news, search)
- Profile pictures: ten heron presets (2.19.0) or your own photo (cropped square, resized, metadata removed), shown wherever the initials were
- **Events and contacts** (2.21.0): your own calendars and address books in Kalmido, synced with the phone's calendar and contacts apps ([Events](#events), [Contacts](#contacts))
- **Calendar apps (CalDAV), both ways**: every project as a task list in Reminders (iPhone, iPad, Mac), Thunderbird, Evolution, Tasks.org or DAVx⁵ on Android, with an app password per device ([Calendar apps](#calendar-apps-caldav))
- **Calendar subscription**: your open tasks with a date as an ICS feed for Google Calendar, Apple Calendar, Outlook or Thunderbird
- **Import from Todoist, Trello, Asana, Microsoft To Do, TickTick, Notion, Google Tasks, ClickUp, Jira, any CSV, Markdown checklists and any ICS / VTODO file** (Apple Reminders exports, Nextcloud Tasks, Thunderbird) with a preview, re-import without duplicates and undo ([Moving from other apps](#moving-from-other-apps)); export everything as JSON (incl. your time entries), or your projects as Todoist CSV files or Markdown checklists (2.142.0) - no lock-in
- **REST API** with personal access tokens (`/api/v1`, OpenAPI 3.1) and signed **webhooks** for Home Assistant, n8n or your own scripts ([docs/API.md](docs/API.md))
- **Appearance per device**: dark or light theme, compact or comfortable rows, font size from 75 to 150 % in 5 % steps, also with Ctrl + / − / 0 (the whole interface scales, not just the text), Geist, your system font or the low-vision friendly [Atkinson Hyperlegible](https://www.brailleinstitute.org/freefont/), and seven accent colors (petrol by default) that all meet WCAG AA in both themes; the switch **View on this device** (Automatic / Phone / Computer) is kept per device, and an unfolded foldable or small tablet in landscape gets the narrow desktop view
- English and German interface, French, Spanish, Italian and Dutch in beta (translations are plain JSON files, [fix or add yours](CONTRIBUTING.md#translations))

| | | |
|---|---|---|
| <img src="docs/calendar.png" alt="Month calendar"> | <img src="docs/matrix.png" alt="Eisenhower matrix"> | <img src="docs/habits.png" alt="Habits: the last seven days and streaks"> |
| Calendar | Eisenhower matrix | Habits |

| | |
|---|---|
| <img src="docs/palette.png" alt="Command palette with actions for the selected task"> | <img src="docs/celebration.png" alt="The Kalmido figure with a checkmark and confetti after Today was cleared"> |
| Command palette | The heron celebrates |

<p align="center"><img src="docs/appearance.png" width="760" alt="Settings, Appearance tab with a live preview, theme, color scheme, density and font size"></p>

<p align="center"><img src="docs/mobile.png" width="300" alt="Phone layout with tab bar"></p>

</details>
<details>
<summary><a id="moving-from-other-apps"></a><b>Moving from other apps</b></summary>

*Settings > Data > Import*: pick the app, choose its export file, and Kalmido shows a **preview** first: how many
tasks go into which project, a few sample rows and everything that cannot be mapped exactly (a date text it did not
understand, a repetition Kalmido cannot do, a reminder without a date, ...). You choose where it goes: new projects (an
own project with the same name is reused) or one existing project you can edit. The import itself runs in one transaction.

- **Again is safe:** every imported task remembers its id in the other app (or, for formats without ids, a key made
  from project, section, parent and title), so importing the same file again only adds what is new.
- **Undo:** the report after an import, and *Recent imports* below it, offer *Undo* for 24 hours: it removes the
  tasks, sections and (empty) projects that import created. Tasks someone added below an imported task stay.
- **Safe with strange files:** at most 20 MB and 20,000 tasks per import (`KALMIDO_IMPORT_MAX_MB`,
  `KALMIDO_IMPORT_MAX_TASKS`), ZIP and JSON bombs are refused, text encodings UTF-8 (with or without BOM), UTF-16 and
  Windows-1252 are recognized, formula cells stay plain text, nothing inside a file is ever fetched from the internet
  (attachments stay links in the notes), and every task is validated like one typed into the app. Each imported task
  gets a history line *imported from ...*; imports do not send one webhook per task.
- The same import is available to scripts: `POST /api/v1/import/{source}` ([docs/API.md](docs/API.md#import)).
- People named in a file (assignees) are never matched to accounts; their names go into the notes as text.
- **Leaving again** (2.142.0): *Settings > Data* also exports your projects as **Todoist CSV** (a ZIP with one file per project in Todoist's import format) or as **Markdown** checklists (one `.md` per project); projects with a lock are left out (the server cannot read them).

| From | Export there | What comes along |
|---|---|---|
| **Todoist** | Project > … > *Export as a CSV file* (one file per project), or *Settings > Backups* (a ZIP with every project). A JSON from the Sync API works too. | Sections, subtasks (indent, at most 5 levels), `@labels` as tags, priorities (the CSV scale is detected, or choose it), dates including English and German date texts (*every monday at 9am*, *jeden Montag*, *15. Okt*, *morgen um 10 Uhr*) and recurring dates, durations, deadlines, comments and attachment links (into the notes). Texts it cannot read (other languages, *every 3rd friday*) stay in the notes. |
| **Trello** | Board > Menu > *Print, export and share* > *Export as JSON* | Lists as sections of one project, or one project each in a folder named after the board; cards with description, due date and time, start, reminder, *complete*; labels as tags; checklists as subtasks (several checklists: one subtask each); members assigned when they can see the project, otherwise named in the notes; comments and attachment links in the notes. Archived cards and lists are skipped, or imported as completed. Custom fields are not imported. |
| **Asana** | Project > arrow next to the name > *Export / Print* > *CSV* | Sections, subtasks (*Parent task*), tags, start and due dates, completion, priority; other columns (custom fields, dependencies) in the notes. An assignee is assigned when the e-mail or name matches someone who can see the target project, otherwise the name goes into the notes. |
| **Microsoft To Do** | No export of its own. Classic Outlook for Windows: *File > Open & Export > Import/Export > Export to a file > Comma Separated Values > Tasks* (Outlook for Mac: *File > Export > Tasks*). CSV files of export tools and ICS files work too. | Title, project, due and start date, status, importance / priority, categories as tags, notes, reminders, steps (when the export has them). English and German Outlook columns, also in Windows-1252. |
| **ICS / VTODO** | Nextcloud Tasks (calendar > … > *Export*), Thunderbird (right-click the calendar > *Export*), Apple Reminders via an export app or a CalDAV server, Tasks.org via its CalDAV account | One project per calendar; subtasks (`RELATED-TO`), due and start with time zones, repetitions (daily, weekly, monthly, yearly), reminders (`VALARM`), categories as tags, priorities, completed and cancelled tasks. Events are skipped. |
| **TickTick** | *Settings > Account > Generate backup* | Imported directly (no preview): folders, projects, sections, subtasks, dates, reminders, repetitions, tags. |
| **Notion** (2.142.0) | *Settings > Export > Markdown & CSV* (a ZIP, ZIPs inside it are read too) | Every database CSV becomes a project (name, status, date or date range, tags, priority; other columns in the notes, the text of a row's own page as well, its checkboxes as subtasks); other pages with `- [ ]` checkboxes become projects. The ID suffixes Notion adds to names are removed. |
| **Google Tasks** (2.142.0) | [Google Takeout](https://takeout.google.com) > *Tasks* (the ZIP or the `Tasks.json` in it) | Lists become projects; subtasks, due day, notes, completion; deleted tasks are left out. |
| **ClickUp** (2.142.0) | List or view > … > *Export* > *CSV* | Lists become projects in folders (the space when the folder is hidden), status, start and due dates, priority, tags, checklists as subtasks, estimate as duration; comments, attachments and other columns as text in the notes. |
| **Jira** (2.142.0) | Issue search > *Export* > *CSV (all fields)* | One project per Jira project, subtasks via *Parent*, status (*Won't Do* = cancelled), priority, due date, labels; issue key, type, sprint, reporter and components in the notes. |
| **Any CSV** (2.142.0) | Any spreadsheet saved as CSV | Columns are matched by their English or German header (title, due, notes, project (or list), priority, tags, done ...); the preview shows which column went where, unknown columns go into the notes. |
| **Markdown** (2.142.0) | A `.md` file (Obsidian, Logseq, a README) | Top headings become projects, deeper ones sections; `- [ ]` / `- [x]` tasks, indentation = subtask, text below a task = its note; unambiguous dates (`2025-01-15`, `15.01.2025`, `due:`), `#tags`. |

</details>
<details>
<summary><a id="users-and-sharing"></a><b>Users and sharing</b></summary>

<p align="center"><img src="docs/share.png" width="760" alt="The Share dialog of a project: people with their roles open, groups, agents, the public link and the owner folded with their state"></p>

- **Accounts:** admins manage users under *Settings > Administration* (username, display name, optional password,
  optional SSO login, admin flag, ntfy topic, disable / delete). Everyone can change their own display name and
  password under *Settings > Account*, and a profile picture there (a heron preset, an own photo or just the initials;
  admins can set a preset for someone else, e.g. the bot user of an API integration). The *Users* block comes first
  under *Settings > Administration*; agents are listed there too (with the *Agent* badge) and open their own dialog
  (*Managed under Agents*). A user who still owns projects cannot be deleted (delete the projects or
  disable the user instead); deleting removes their inbox, habits, filters and focus history.
- **Private per user:** inbox, habits, focus sessions, filters, folders and sidebar order, tags (two people can tag
  the same shared task differently; right-click or long-press a tag in the sidebar, or "…" in the tag view, >
  *Delete tag…* removes it from all your tasks after showing how many, the tasks stay, undo brings it back), settings (language, notifications, digest, ...), ntfy topic, upload token.
- **The Share dialog** (2.6.0): *Share…* in a project's "…" menu, the *Share* button next to the project title (desktop), or
  *Sharing > Share…* in the project dialog. One place for everything about who sees a project: **People** (members with their
  role, *Share with …* + role + *Add* to invite, remove), **Agents** (the project's agent: one select *Agent: No agent / …*
  -- **one agent per project** (2.26.0), switching swaps it in one step with Undo; *Members may see and use the agent*
  (default off: only the owner and project admins can chat with it, @mention it or assign it tasks here), *Agents may
  address each other* (default off), which agent may tidy up entries), the **Public link** (owner) and the **Owner** (*Transfer
  ownership…* / *Take over…* with the history). Members see who is in the project, read-only. The project dialog keeps the
  project's own settings and shows a one-line summary ("Shared with 2 people · 1 agent").
- **Sharing and roles:** in the Share dialog add people with a role (*What the roles may do* explains each one):

  | Role | Sees | Changes |
  |---|---|---|
  | **Owner** | everything | everything; the only one who renames, changes the type, archives, deletes, creates a public link or custom fields |
  | **Admin** | everything | every task, sections, project status; adds and removes members and sets their roles (never the owner's); moderates comments |
  | **Member** | everything | every task, sections, project status |
  | **Participant** | only the tasks assigned to them, with their subtasks, comments, files and time; the main task of an assigned subtask as read-only context (title, dates, status) | their own tasks; may add tasks (always assigned to themselves) and subtasks; never deletes, moves out or reassigns |
  | **Viewer** | everything | nothing (may comment) |

  A participant's view is filtered on the server everywhere (search, calendar feed, statistics, time reports, News,
  pushes, reminders, the REST API, webhooks), not only hidden in the app; sections show only when they hold one of
  their tasks. Changing a role takes effect at once. Projects shared before 1.10.0 keep their meaning: *Can edit* is now
  *Member*, *View only* is *Viewer*. Members can leave a project; the basket cannot be shared.
- **Transfer ownership:** the owner hands a project to another person in the Share dialog (*Owner > Transfer ownership…*)
  (a member or anyone they could share with; confirmed twice). The new owner gets it in the same folder and place
  where they had it as a member (otherwise at the end of their sidebar) and a News item; the old owner stays in the
  project as a **project admin**, where it was in their sidebar. Every transfer is noted under *Owner* in the Share dialog ("Ownership
  transferred from X to Y"). Agents never become owners and never transfer; baskets cannot be transferred.
  **Admins take over** projects whose owner is an agent or a disabled user, which nobody could manage otherwise (agents
  cannot share, disabled users cannot log in): *Settings > Administration > Projects owned by agents or disabled users >
  Take over* (for themselves or another person), or *Take over…* in the Share dialog when they are in the project. An
  agent that owned the project stays in it as a *Member* (agents are never project admins). API:
  `POST /api/v1/lists/{id}/owner` with `{"user_id": …}` (scope structure; agent tokens get 403).
  Moving a task into a project needs edit rights there, moving it out needs edit rights on its current project. Members
  with edit rights can only move a task out of a shared project into a project that all its current people can see (e.g. between
  two projects shared with the same people); moving it anywhere else is up to the project owner, so a member can never take a
  shared task (with its subtasks and comments) away from the owner. Subtasks follow their parent; a subtask that lives
  in someone else's project stays there (at the top level) when a member moves the parent elsewhere.
- **Trash:** deletion after the trash period needs `KALMIDO_RETENTION_PURGE=1` (new installations get it from the installer). Everyone with edit rights can move tasks to the trash and restore them. Only the project owner deletes
  tasks of a shared project permanently (*Empty trash* of a member leaves shared projects of other owners alone, marks those
  items *stays* and says how many stayed). Instance admins also empty the trash of shared projects where they may edit.
- **Assignment:** in shared projects a task or subtask can be assigned to the owner or any member (task panel >
  *Assignee*, or the **assignee column**: every row of a shared project shows the assignee's picture or a dashed circle
  for nobody; a click opens the assign menu; on phones a small cell at the end of the row; 2.14: project *…* > *Columns…*
  shows or hides it, and orders it among the other columns, for everyone in the project). A subtask's assignee is independent of its main task.
  Reminders go to the assignee, otherwise to whoever created the task (if they still see it, else to the project owner). The daily digest contains your own
  projects' tasks plus everything assigned to you.
- **Export** (*Settings > Data > Export*) contains your data and the projects you own (tasks with links, comments and history) and your templates.
  Note: the export of a project owner includes the comments that other members wrote in the owner's shared projects.

### Public links

A project owner can share one project with people who have **no account**: *Share… > Public link > Create public link* (the Share dialog, 2.6.0).
The link (`/s/<token>`, 192 random bits) opens a plain page with only that project: its sections, open tasks with their
subtasks and due dates, and the tasks completed in the last 7 days (in a checklist: all done items). Never comments,
assignees, tags, files, custom fields or anything from other projects; task notes only if you tick *Show task notes*
(then as plain text).

- **Access:** *View only* or *View and tick off*. Ticking goes through the normal completion: the history says
  *Someone via the public link*, and the task's creator gets a News item and a push like after any completion in a
  shared project (if collaboration is on). Put back on the project works too; nothing else can be changed.
- **Password** (optional, stored hashed): visitors enter it once per browser (a cookie for that link only). Changing
  or removing the password, *New link* and *Turn off* take effect at once.
- **Expiry** (optional): the link works through the end of that day.
- Only the owner creates and manages the link; the basket cannot be shared. The page loads no scripts and nothing
  external, is marked `noindex`, is never cached, and has a strict Content-Security-Policy. Views, ticks, unknown links
  and wrong passwords are rate-limited per address; an unusual number of views of one link sends the admins an alert.
- Admins can turn public links off for everyone (*Settings > Administration > Whole server*; existing links then stop working
  but are kept); `KALMIDO_PUBLIC_LINKS=0` turns them off for good.

### Show completed at the bottom

For projects you work through again and again (groceries, packing, a cleaning routine): *Show completed at the bottom* in
the project's *…* menu, its *Sort* menu or the project dialog (2.7.2; before, this was the project type *Shopping & packing list*
/ *Checklist*: such projects became plain projects with the option on, nothing changed for their items).
Ticked-off items move to a **Done** section at the bottom (open, collapsible) instead of disappearing, sorted by name,
and go back on the project with one tap (↺). *Uncheck all* puts everything back, *Clear done* moves the done items to the
trash. Quick add works as usual, and it works with sharing and public links (*View and tick off* makes a shared shopping
project for the whole household, no accounts needed). API: the project field `done_at_bottom`; `kind: "checklist"` and the
boolean `checklist` are still accepted as deprecated aliases.

### Comments and activity

<p align="center"><img src="docs/comments.png" alt="Task panel with comments of the team, reactions and activity lines"></p>

- **Comments** (module *Comments*, on by default): everyone who can see a task can comment on it, including *View only*
  members (they still cannot change the task). In private projects and without collaboration, comments are personal
  notes with a timestamp: no @mentions, no News, no pushes, no history of your own changes. Checklists have none.
  On a desktop (2.31.0, #344) the comments and the history have their own area below the properties: drag the line
  between them (or use the arrow keys) to resize it, fold it with a double-click or the arrow in its head; position and
  fold are saved per user. On phones and tablets the comments and the history sit at the end of the task panel (a small
  *To the comments* link jumps there; order and history are in the "…" of the comment head). The comment box stays at
  the bottom edge of the panel while you scroll, a single line until you use it. Opened from a comment (News, a
  push), the panel shows the newest one. Comments support a little Markdown,
  links, files (images show as thumbnails inside the comment, not in the task's attachment list) and
  **@mentions**: type `@` for a list of the people who can see the task. Mentions are stored by user, so a
  renamed user stays linked. *Ctrl+Enter* sends.
- **Edit and delete:** you can edit and delete your own comments (edited ones show *edited*, deleted ones and
  their files disappear). The owner and the admins of a project may delete any comment in it (moderation); server
  admins have no extra rights on other people's comments. Participants comment on their own tasks only.
- **Activity:** the task panel shows the history between the comments: created, renamed, dates, priority,
  assignment, moves, completion, repetition, links, attachments, subtasks, trash. Sort order, pins, reminders
  and your private tags are not logged. *Show activity* hides it (remembered per device).
- **Unread:** tasks with comments show a count; a dot marks comments by others you have not seen yet. Opening the
  task marks them as read.
- **Notifications** (over each person's own channel, Web Push and / or ntfy, in their language; tapping opens the task; never for your
  own actions and only to people who can still see the task):
  - new comment: to the assignee, the creator and everyone who commented before; *@mentioned* people always,
    with "mentioned you"
  - *Sam assigned you: task* to the new assignee (with project and due date), *Sam unassigned you from: task*
    to the previous one
  - *Robin completed: task* to the creator and whoever assigned it, for tasks in shared projects
  - bundling: after a push about a task, anything else on that task within a minute is collected into one
    summary push ("2 more comments · 1 more change").
- **Offline:** comments need a connection. Offline, the text stays in the box with a notice (task edits still
  queue up and sync later as before).
- **Comments off:** *Settings > Modules > Comments* hides every comment (they stay stored), the API refuses new ones
  (409) and you get no comment News or pushes. Collaboration keeps working without them (sharing, assigning, history,
  News about assignments and status).
- **Simple mode:** *Settings > Modules > Collaboration* (per user) hides activity, mentions, assignee chips, the sharing section, the assignee field, *Assigned to me* and the News inbox, and stops these
  notifications and News entries. Shared projects you are in stay visible as normal projects, nothing is deleted.
  The website link field is always available.
- **For the whole server:** admins can switch collaboration off for everyone (*Settings > Modules*, the
  *for everyone* switch next to *Collaboration*). Then nobody can share, assign, mention or get News and collaboration pushes
  (comments stay as personal notes), the related API endpoints answer 403, and shared projects are only visible to their owner. Personal switches are shown
  disabled. Nothing is deleted: switched back on, memberships, comments, assignments and status history are all
  there again. When an admin creates the second user while it is off, Kalmido offers to turn it on.

### News and notifications

2.28.0 (#987): News come in two parts. **For you** holds what *people* send you -- @mentions, assignments, replies to
your comments, approval decisions -- and the unread direct messages of the team chat; **Activity** holds every change
and everything agents do. The bell counts only *For you*, its dropdown shows *For you* first, the News view has the
tabs *For you | Activity | All*, and the start page shows *N messages for you* while something is unread. Pushes for
what agents do (their comments, completions, new tasks, status) are off by default (*Settings > Notifications > Pushes
for what agents do*); an agent's @mention of you and its approval requests push as before.

**Notification templates** (2.33.0, #927): the owner of a shared project or folder chooses in the share dialog how much
the other people are notified at most -- *Read only* (mentions, assignments, direct replies), *Collaborate* (+ comments
on their tasks and due reminders), *Everything* or *Custom*, also per person. Members can set themselves quieter, never
louder, and see who limited the project; the News list stays complete, only pushes are held back. New shares start with
*Read only*; projects and folders shared before 2.33.0 keep *Everything* until the owner chooses (asked once).

<p align="center"><img src="docs/news.png" alt="News inbox with mentions, grouped comments, an assignment, a completion and a shared project"></p>

**Bundled (2.17.0):** News are grouped per task (or project) with one line of what happened ("2 comments · completed"),
three sections (2.138.2): *For you* (unread approvals, proposals, mentions, assignments, follow-ups; the number is the
bell's), *Also new* (other unread activity) and *Read* (muted, below), *Mark read* per group;
*Bundled* in the bar switches to the plain list (per device). *Summarize* sends your unread News to an agent's chat,
which answers with a short summary.

- **News** (bell icon in the top bar, also as a sidebar entry and a pinnable tab) lists what concerns you,
  newest first: *@mentions*, new comments on tasks you take part in (creator, assignee, earlier commenter),
  *assigned you* / *unassigned you*, completions by others (same rule as the push; off by default, see below), and projects someone shared
  with you, your role changes and *removed you from a project*. Never your own actions.
- Same recipients as the push notifications, but nothing is bundled: every event is kept (people without an
  ntfy topic get them too). Consecutive comments on the same task are shown as one row with a count.
- Only items you may still see: if you lose access to a project or a task goes to the trash, its items disappear;
  deleted comments disappear as well. Comment items show a short excerpt with mentions highlighted.
- Works like a mail inbox: unread items are bold, tapping one opens the task and marks it read (opening a task any
  other way also marks its items read), *×* (desktop) or a swipe sideways (touch) removes a single item, *Mark all as
  read* and the filter *All | Mentions & assigned to me* are at the top. The unread badge updates with the normal sync.
- **What notifies you** (2.1.0) is one table under *Settings > Notifications* (or the gear next to the filter): every
  event with a *News* and a *Push* checkbox. Events: comments on your tasks (created by you or assigned to you),
  replies to your comment (the comment right before is yours), comments on tasks you follow (you commented on them),
  mentions, assignments, new tasks in shared projects (someone else created them), completions by others, project status,
  projects shared with you, unblocked tasks, an agent waiting for your approval, the follow-up day of a task *waiting on
  external*, reminders (push only), repeated reminders (2.7.0, push only; a muted project bell stops them) and, for admins, an agent reaching a usage limit (2.1.1). A comment counts once, as the first of: mention, your task, reply, follow.
  Defaults = the behaviour before 2.1.0 (completions only as a push; status and sharing only in News); new tasks in
  shared projects are off, replies and follow-ups on. `GET /api/v1/me` shows the settings, `PATCH /api/v1/me/notifications`
  changes them.
- **The bell of a project** (project menu > *Notifications*, or the project dialog), for you only: *All activity* = every
  comment, new task and change in that project as News and push; *Default* = the table above; *Mute* = nothing from that
  project except mentions of you and tasks assigned to you (those follow the table); *Custom selection…* (2.6.1) = your
  own choice per event for this project, News and Push each: new tasks, comments, mentions, assignments, completions,
  project status, unblocked tasks, agents waiting for approval. A ticked event reaches you from every task of the
  project, an unticked one never; the choice is kept when you switch to another mode and back. Reminders and follow-ups
  are your own and are never muted. A muted project shows a crossed-out bell in the sidebar.
- **The bell in the top bar** (2.6.1) opens the newest News right where you are (a dropdown on the desktop, a sheet
  from the bottom on a phone): open an item, remove it, *Mark all as read*, *Show all* for the full view; a click
  outside or Esc closes it and you stay in your project. **Filter chips** (*Mentions*, *Comments*, *Assignments*, *New
  tasks*, *Completed*, *Status*, *Agents*, …, only the kinds that are there) narrow the dropdown and the News view;
  they only change what you see, per device.
- Items are kept for 90 days, at most 500 per person (`TASKS_NEWS_DAYS`, `TASKS_NEWS_MAX`).

</details>
<details>
<summary><a id="start-page"></a><b>Start page</b></summary>

A tap on the logo (*Kalmido* at the top of the sidebar) opens the **start page** (the dashboard): what waits for you (approvals,
mentions, assignments), today's tasks (complete them right there), News bundled, the team chat, your projects with
their progress, pinned tasks, recent notes, the agents, a few numbers and a search field. *Customize* orders the cards
(↑ ↓, also with the keyboard) and hides the ones you do not need; the choice follows you to every device. The same
*Customize* (2.32) arranges Today, Time tracking, the agents and projects overviews and the project page: show, hide,
reorder, half or full width, optionally different on the phone; on the project page the owner sets the standard for
everyone and each person may override it. The start page can also be a tab (Settings > Appearance > Tab bar).

<p align="center"><img src="docs/project-page.png" width="760" alt="A project page built from blocks: status line, description, status updates, milestones, key links, members, notes and team chat"></p>

</details>
<details>
<summary><a id="family"></a><b>Family</b></summary>

*Settings > Modules > At home > Family* (or *What do you use Kalmido for? > Family* in the setup, the welcome tour or
*Settings > Modules*) switches on everything for a household; while it is off, none of it shows. The **Family** view
(sidebar, tab bar, command field) brings it together.

- **Birthdays and anniversaries**: *Birthday* in the Family view (or a *Birthdays* project): a yearly task with the age
  ("turns 80"), reminded 7 days before (or 1, 3, 14, 30, on the day only) and on the day; gift ideas are its checklist
  and what was given stays ticked when the year rolls on. *From contacts…* reads an **address book** (CardDAV:
  Nextcloud, iCloud, Radicale, mailbox.org …) once a day: `BDAY`, `ANNIVERSARY` and Apple's anniversary dates become
  yearly tasks and follow changes; nothing is written back, the address and the password are stored encrypted (like a
  calendar subscription's), each date keeps the contact's UID so a change updates it instead of adding a second one, and
  a birthday you deleted is not created again. Internal servers need the admin's allow-list (*Settings > Administration > Advanced*).
- **Household chores that take turns**: in a repeating task of a shared project, *Take turns* in the task panel: pick who
  (people of the project, children too) and whether the next person comes after each completion or every week. The next
  person gets a push; Undo puts the turn back; *Whose turn* in the Family view.
- **Children**: an admin makes an account a **child account** (*Settings > Users > Edit*) and picks its parents. A child
  sees a simple view with big buttons: its own tasks only (in shared projects a child always takes part as a participant:
  only what is assigned to it, or where it comes along), its stars and the rewards. Each task it completes gives 1 star
  (or what the task says under *Stars for a child*); parents give stars by hand, set rewards (once or again and again),
  get a push when the child asks for one and approve or decline it in the Family view. A child account can tick its
  tasks, ask for rewards and change its own account; everything else stays read-only for it.
- **Who comes along**: *Who comes along* in the task panel of a shared project's task: those people see the task (children
  too) and get its reminders.
- **Shopping lists**: *Used for: Shopping list* in the project dialog (or *Add shop areas* on a project): the sections become
  shop areas (fruit & vegetables, bakery, dairy …, rename or add your own); move an item to its area once and the next
  one goes there by itself ("2 l milk" and "milk" are the same item); common items (bananas, bread, milk …) find a
  likely area the first time. *Shopping mode*: the whole screen, big ticks,
  grouped by area, add items, live for everyone shopping at the same time; ticked items wait at the bottom for next time.
- **Meal plan**: the next seven days of meals in the Family view (*+* per day); write the ingredients as a list in a meal's notes and
  the cart button puts them on the shopping list, without doubling what is already on it.
- **Household deadlines**: *Household deadline* in the Family view: passport, ID card, car inspection (every two years), insurance
  and contracts (due on the last day to cancel, every year) or anything else, with a lead time that fits.
- **Packing lists** from templates: holiday, swimming pool, daycare, camping, business trip.
- API v1 and MCP: `/family`, `/family/occasions`, `/family/deadlines`, `/tasks/{id}/to-shopping`, `/lists/{id}/shop-areas`,
  `/family/packing`, `/family/kids`, rewards; tasks carry `family`, `rotation`, `people` and `stars` (docs/API.md).

</details>
<details>
<summary><a id="workspaces-work-and-private-apart"></a><b>Workspaces: work and private apart</b></summary>

Since 2.28.0.

Every project belongs to a **workspace**: your private space or one of your organisations (the project dialog, *Workspace*).
The switch at the top of the sidebar (*Private | <organisation> | All*) shows the projects, tasks, News, agents and team
chats of one workspace at a time (the basket is always there); a chip in the header says which one you look at, and the
choice follows you to every device. A new project starts in the shown workspace.

What the server keeps apart:

- An **organisation's project** is shared only with the organisation's members (a share with somebody else is refused with
  a clear message, a share by e-mail address into it does nothing and reveals nothing); its groups must consist of
  members and its ownership stays inside the organisation.
- **Private projects** are shared with anyone you may see (also colleagues) and stay invisible to the organisation.
- **Agents work in one workspace** and join only its projects: an organisation's agent never sees a private project, a private
  agent never an organisation's project. "Used for" (family / household) and Home & life projects are private only.
- Changing a project's workspace is the owner's call and refused while people or agents in it do not fit the new one.
- *Settings > Account > Workspaces* lists your organisations with their members; an organisation's admins manage them
  there (see below).

**Leaving an organisation** (removed by an admin, or on your own): your projects of that workspace stay with the
organisation (they go to the admin who removes you, or to the next admin), you leave every list of the organisation;
your private projects go with you. When the only admin leaves, the operator (an instance admin) takes the organisation over.

**On the update** to 2.28.0 every list of a server with an organisation stays in the organisation (a server from before
was one company), except family / household and Home & life projects, projects in a top folder named like *Private* /
*Family* / *Home* and every basket: those become private. Team agents work in the organisation, a personal agent in the
workspace most of its projects are in; an agent that already sits in a list of another workspace is kept and pointed out --
the owner decides.

**Calendars and address books** (2.30.0, #1036) belong to a workspace too, with the same rules: an organisation's
calendar or address book is shared only with its members and agents, a private one never with an organisation's agent,
and a share always needs a person you may see. *New calendar…* / *New address book…* ask for the workspace, *Workspace…*
in their menu moves one (the owner; refused while a member does not fit). The sidebar switch filters events, calendars,
contacts and address books as well. Groups of another organisation stay unknown. On the update every calendar and
address book of a server with an organisation goes into its owner's organisation, except the ones named like *Private* /
*Family* / *Home*, address books mirrored from an outside account and those with a member who does not fit (they stay
private; nobody loses access). A **nightly boundary check** counts every membership across the workspace boundary
(projects, calendars, address books, groups, agents), raises an admin alert when the count changes and shows it under
*Administration > Organisations*.

</details>
<details>
<summary><a id="organisations-and-invitations"></a><b>Organisations and invitations</b></summary>

2.46.0: **one kind of server** - organisations plus a private space for everybody. People see the members of their
organisations and the people they are connected with (a project or group in common, their kids, their agents); on a server
without any organisation everyone sees everyone (a household). People outside your organisations are reached by sharing
a private project by e-mail address (the answer never says whether the address has an account).

- The **instance admin** (the operator) creates organisations with a first admin and deletes empty ones; *Users* lists
  every account. When adding a person the admin picks the organisation (none, or one of them) and the role (member /
  admin); with exactly one organisation it is preselected.
- 2.143.0: besides member and admin an organisation knows **read-only** (sees what members see, changes nothing; team
  chat stays open), **guest** (sees only what is shared with them personally) and **accounting** (reads and exports the
  office, uploads receipts). The server checks the role everywhere (see docs/TEAM.md). Going back to an older version
  treats these roles as "member" - set them back to member first.
- **Organisation admins** manage their members (add by e-mail address, roles, removal - the removed person's projects of the
  organisation go to the admin), name and e-mail domains under *Settings > Account > Workspaces*, without being admins of
  the server.
- New accounts join no organisation by themselves: registrations join the organisation of their e-mail domain, or one
  that invited them. The login page names no organisation.
- The first-run setup asks for an optional organisation name (or takes `KALMIDO_ORG_NAME`): with a name the server starts
  with that organisation and you as its admin, without one only with private spaces.
- **Organisation projects** are shared with invited people only, or (2.46.0) with *everyone in the organisation*: members see
  them read-only until they join (or may edit, when the project allows it); agents only when invited.
- Upgrading from 2.45 or older: memberships, roles and projects stay as they are; nobody is added to an organisation at a
  start any more. `KALMIDO_INSTANCE_MODE=organisation` is ignored (a log line says so); `shared` (no organisations, people
  see only their own contacts) still works when set explicitly.

**Registration** (*Settings > Administration > Sign-in*, off by default): *Create account* on the login page for addresses
of certain e-mail domains, for anyone after an admin approves it, or (shared servers) for anyone with a confirmed
address. With e-mail (SMTP) people confirm their address with a link and choose their password; without it only
"after an admin approves" works. New accounts start without access to projects, never as admins or child accounts; the
answer never says whether an address already has an account. Admins approve waiting accounts under *Users*.

**Sign-in link / QR code** (user dialog; parents for their children in the family): for family members without an
e-mail address. Opened on their device it signs them in there, once, within 7 days.

**Invitations**: create a person without a password and Kalmido e-mails them a link (valid 7 days, once) to *Set up
your account*: they choose their own password and are signed in. *Send the invitation again* / *Send a link to set a
new password* in the user dialog; without SMTP you copy the link.

</details>
<details>
<summary><a id="clients-workload-approvals-forms"></a><b>Clients, workload, approvals, forms</b></summary>

Three modules under *Settings > Modules > Projects and team*, each off until you switch it on, all within your
organisation:

- **Clients**: name, contact, address, an hourly rate for projects without their own, a budget in hours and / or money
  (the bar turns amber at 80 %, red over 100 %). A project belongs to a client (project dialog). The client's page shows the
  hours of the month and in total, the amount, the estimate (the tasks' durations) next to the tracked time per project,
  and the **timesheet** of a month (printable / PDF, CSV). The sidebar lists the clients above the projects.
- **Workload**: open tasks assigned to each person, week by week (by their planned start, else the due date; overdue
  ones count this week), weighed with their duration, against their hours per week (each person sets their own; admins
  for everyone). Only what you can see is counted.
- **Forms**: a project's form is a link with a small page (subject, description, name, e-mail). What someone sends becomes
  a task in the project, the project's agents get it to sort in. For signed-in people of your organisation or, with public
  links on, for anyone with the link (a honeypot and limits against spam).

**Approvals** (with collaboration): *Ask for approval…* in a task's menu assigns it to a person of the project; they
**approve** it (done), **ask for changes** (back to you, with a note) or **reject** it (won't do). Agents can ask, never
decide.

</details>
<details>
<summary><a id="home--life"></a><b>Home & life</b></summary>

Six modules under *Settings > Modules > At home*, each off until you switch it on; the view **Home & life** shows a
card per module (sidebar, command field). They are made of ordinary tasks, projects and contacts, so reminders, the
calendar, CalDAV, sharing and the API work as everywhere.

- **Contracts & subscriptions**: provider, cost (per month, quarter or year), the end of the current term, the notice
  period and the renewal. The task is due on the **last day to cancel** and reminds you before it; ticking it off means
  you keep it (it moves on to the next term), *Cancelled* in the task panel ends it. The card sums the cost per month and
  per year.
- **Home & devices**: devices with their warranty end (a reminder before it; attach the receipt) and **upkeep** that comes
  back every few months, with suggestions (heating, smoke detectors, tyres, descaling …).
- **Staying in touch** (needs Contacts): on a contact's card choose *every 2 weeks … every year*; *In touch today* notes
  it. The card lists who is due, a push once a day names them. Your choices are yours only.
- **Health**: appointments, check-ups and vaccinations (repeating) and medication (a daily reminder per time), in a
  **private** project: agents never see it, API tokens only with the permission *Health & journal*, no webhooks.
- **Review & journal**: your day or week (done, still open, moved, coming up) and a private journal with a mood.
- **Travel**: *Trip* creates a project with the dates, sections for bookings and things to do before you leave, a packing
  project from a template and, with Events on, an all-day event.
  Travel and staying in touch also exist per organisation (area *Travel & contacts*, only these two parts; contracts,
  devices, health, budget and family stay private); the button *Travel expenses* on a trip creates the prefilled travel
  expense trip in the office (office admins only).
- Read later, Feeds and Bookmarks moved into their own area *Reading* (see below).
- API v1 and MCP: `/life`, `/life/contracts`, `/life/devices`, `/life/upkeep`, `/life/health` (permission `private`),
  `/life/trips`, `/life/review`, `/life/journal/{day}` (`private`), `/contacts/{id}/care`, `/life/karakeep/sync`.
- **Budget** (2.72.0; its own part of *At home*): a budget is a list of its own that opens the budget view. Entries
  (income or expense, amount, day, title, category, counterpart, note, receipts), categories with a monthly limit, a
  month view with planned / spent / left and the last six months as bars. **Recurring entries** (monthly, quarterly,
  yearly) are templates: *Open this month* books them with one tap; *Take over from contracts* turns your contracts into
  recurring entries. **CSV import**: the file you download from your bank (no bank access), columns mapped once and
  remembered, duplicates and errors left out, categories suggested from earlier entries. Share it with your family like
  any project (read-only or writing); agents never see it, there is no API v1 / MCP for it. Amounts, texts and receipts are
  encrypted at rest with the key of the project's space (needs `KALMIDO_SECRET_KEY`).

</details>
<details>
<summary><a id="reading"></a><b>Reading</b></summary>

*Reading* is an area of its own (sidebar, tab bar, *Settings > Modules*), in Private and in every organisation apart; each
view shows only the entries of the workspace you are in. Without an organisation everything works privately.

- **Read later**: own view with saved links (site, date, excerpt); tick them off when read, *Read* shows the ticked ones.
  Technically a project per workspace (an organisation's is made on first use and open to its members), so the share
  target, Karakeep and the API keep working.
- **Feeds** (2.85.0): follow RSS / Atom feeds (up to 100, fetched hourly by the server, articles kept 30 days), unread
  first, *Read later* turns an article into a reading-list entry; OPML import and export. An organisation's feeds are read
  by all its members with their own read marks, only its admins add or remove sources; existing feeds stay private. A site
  that refuses servers (403) is named so. Agents and API tokens do not see feeds or read later. "Read later" projects are never visible to agents, API tokens or webhooks (like health lists).
- **Bookmarks** (2.97.0): links with a preview, tags, a note and search, saved from the share target, by pasting or with a
  browser button ([docs/BOOKMARKS.md](docs/BOOKMARKS.md)); *Connect Karakeep…* with your own address and API key (stored
  encrypted) brings Karakeep's links in as bookmarks (notes stay tasks) and archives the archived ones in Karakeep.

</details>
<details>
<summary><a id="events"></a><b>Events</b></summary>

Kalmido keeps your appointments itself (module *Events*, on by default; *Settings > Modules*). They show next to your
tasks in the **year**, month, week and day view, in the **agenda** (the coming two weeks, events and tasks by day) and in *Events
today*. **+ Event** in the calendar bar, the quick sheet of a free slot (*Event*) or a **drag over free time** in the
week create one; a click opens it (details, your answer, *Edit*, *Delete*, *Preparation task*).

- An event: title, from – to (all day or with times, over several days, in any **time zone**), place, notes, a link,
  **repeat** (daily, weekdays, weekly, every two weeks, monthly, yearly, or an own rule such as *every 2nd Tuesday* or
  *Mon, Wed and Fri*; until a date or a number of times),
  **reminders** (a push before the start), status and *busy*. A repeating event changes as a whole or **only this
  date**; a single date can be left out.
- **Calendars**: as many as you like, each with a colour; *Calendars* in the calendar bar shows, hides, renames,
  shares (*can view* / *can edit*, like projects), imports an **ICS file** (an export of Google Calendar or any other app;
  importing it again changes the events instead of doubling them) and exports one.
- **People**: invite people of this server (they see this one event, not your calendar, get News and a push and
  answer *Accept* / *Maybe* / *Decline*), your contacts or any e-mail address.
- **Preparation**: a task linked to the event, due before it (*Preparation task*), or the other way round *Schedule as
  an event* in a task's panel.
- **People's availability** (2.155): while you invite, a free / busy bar shows you and every invited person of your
  organisation for the day - only busy and away times, never titles or places.
- **Holidays and absences** (2.155): the public holidays of your state (Germany by state, Austria) and your absences show
  in the calendar, your team's on request as "away" only; the state can be set per person, also without an
  organisation. Your absences and holidays are also a subscription link for the phone's calendar app.
- **On the phone**: each calendar is a calendar in the phone's own app (CalDAV), changes go both ways; invitations come
  in a calendar *Invitations* and are answered there (*Accept* / *Maybe* / *Decline*) or in the app; a calendar created on
  the phone becomes a Kalmido calendar. See [Calendar and contacts on the phone](docs/CALDAV.md#calendar-and-contacts-on-the-phone).
- The family events of 2.19 (tasks with people who come along) became events once, with those people invited; the
  task stays, marked done and linked to its event.

</details>
<details>
<summary><a id="contacts"></a><b>Contacts</b></summary>

Your address books live in Kalmido too (module *Contacts*, on by default): **Contacts** in the sidebar lists them with
a search (name, company, e-mail, phone, address, group), a group filter and a card per person (phones and e-mails as
links, addresses, birthday, notes, linked tasks and events). *New contact* / *Edit*: name, company, job title, phones,
e-mails, addresses, web links, birthday and anniversary (also without the year), groups, a photo, notes.

- **Address books**: as many as you like, shared like projects (*can view* / *can edit*); contacts are personal data, so
  they only show to people who see their address book, also in a task.
- **Tasks**: *People and dates* in a task's panel links a contact (*Waiting on*, *Responsible*, *About*).
- **Birthdays** (module Family): an address book's birthdays and anniversaries become yearly tasks of a project you pick.
  An address book connected under *Family > From contacts…* is also copied into an address book of its own.
- **Import / export**: vCard files (3.0 and 4.0); **on the phone** each address book is an address book in the phone's
  contacts app (CardDAV), both ways.

</details>
<details>
<summary><a id="team-chat"></a><b>Team chat</b></summary>

People talk to each other in Kalmido: **direct messages** between two people who work together (they share a project or a
group) and **one channel per shared project** for everyone who sees the whole project. Agents shared with the project are in its
channel: they read along and answer when you @mention them. Messages are Markdown, `@Name` mentions a member, a message
can link a task, shows 👍 👎 ❤️ under every message (one tap adds or removes yours, 2.18.0; "+" for any other emoji,
2.19.0), and you edit or delete your own (project owners and admins delete
any in their channel). *Team chat* in the sidebar shows the unread count; a direct message and a mention push to your
devices (notification row *Team chat*; muting a conversation leaves only mentions). Find it in the sidebar, the tab bar,
the project menu (*Team chat*) and a project's overview. The REST API and the MCP server have it too (`/team/...`, see
docs/API.md); agents cannot open direct messages.

**Reply to one message** (2.33.0, #1076): swipe a message to the right on a phone (or *Reply* on hover / in its menu
on a computer); the answer shows a small quote that jumps to the original, and its author is notified. The same works
in comments and the agent chat. **Search** (#1080): the magnifier in a chat's header searches that conversation; the
search page and the command field find messages and comments everywhere you may read them.

**Several chats at once** (#1720): Ctrl/Cmd+click a chat (or *Open in split window* in its right-click menu or the person
card) opens it below the chat that is open; agent chats, channels and direct messages share the panel, each window keeps
its draft and unread dot, a header folds, moves or closes it, the divider between two windows moves (double-click: equal
heights). On phones a row of the open chats at the top switches between them. Every agent and person has a **fixed
colour** (#1721) in avatars everywhere; change yours under *Settings > Account*, an agent's in its settings, and switch
people's colours off under *Settings > Appearance*.

</details>
<details>
<summary><a id="files-and-documents"></a><b>Files and documents</b></summary>

Since 2.48.0.

**Files** (#1207) keeps folders and files for you and for each organisation, with versions (upload the same name again),
a trash with undo and links to task and project files that keep the original's rights. Share a folder or file with
people, groups or agents to view or edit, optionally until a date; shares are inherited by everything below and never
leave the workspace. Agents see only what is shared with them, write their results into their own folder, and every
agent access shows up in the file's history.

**Documents** (#1111) is the place for letters, invoices and contracts: drop PDFs, scans or photos, share them from the
phone, forward them by mail or put them into *Documents/Inbox*. A **folder watcher** (Mac, Windows, Linux; upload-only key) scans from a desktop folder straight into Kalmido. Kalmido reads scans locally (German and English),
finds date, due date and amount, and sorts in sender, type, tags and folder by your rules or by learning from your
corrections; what it is unsure about waits in *To review*. Search finds words from the content. Text and amounts are
stored encrypted. Self-hosters can import an existing Paperless-ngx instance (#1152).

**PDF preview** (#1367): PDFs open inside Kalmido (pages, zoom, swipe), also in the Android app. **Lock a note**
(#1642): the lock in a task's note encrypts it with your own password in your own, unshared projects; without the
password and the recovery code it cannot be recovered, not even by the operator.

**Word and Excel preview** (2.92.0, #1926): a .docx or .xlsx file at a task, a comment, in the project files or the file
store opens like a PDF - Word with headings, bold / italic, lists and tables, Excel one tab per sheet with column letters and
row numbers (at most 5 sheets x 500 rows x 50 columns). The server reads the file in a sandboxed process; no macros run,
formulas show their stored result; old .doc / .xls and password-protected files: download only. Their text is searchable
and readable for agents. **Summarize**: in the preview of a task's file, when a connected agent may see the task, the button
(with a confirmation naming the agent) posts a comment in your name that mentions the agent; the agent reads the file and
answers with the summary. Kalmido calls no language model itself; undo removes the comment.

**Knowledge folders** (2.200.0, #2747): knowledge pages live in the same folder tree as the file store (empty folders, drag to move or sort, a "…" menu). Share a folder or a page with people, groups or agents (read / edit, inherited). Agents reach pages through API v1 / MCP (`wiki_list`, `wiki_read`, `wiki_write`, `wiki_create`, scopes `wiki:read` / `wiki:write`), only those shared with them.

</details>
<details>
<summary><a id="offline-knowledge-office-projects-pictures"></a><b>Offline knowledge, office projects, pictures</b></summary>

- **Knowledge pages offline**: every space you can read is kept on the device, opens and can be searched without a
  connection; pages edited offline are sent once you are online again (a change made elsewhere meanwhile waits at the
  page: keep yours or take theirs). Encrypted spaces stay encrypted on the device, logging out deletes the copy (#2671).
- **Knowledge in folders**: pages and folders live in a shared folder tree like the file store (drag, sort, empty folders); share a folder or a page with people, groups and agents, read or edit, inherited by subfolders.
- **Agents and knowledge**: pages through API v1 / MCP (`wiki_list`, `wiki_read`, `wiki_write`, `wiki_create`) with the scopes `wiki:read` / `wiki:write`, only pages shared with that agent.
- **Office documents belong to a project**: quotations, invoices and credit notes can be bound to a project (the client's
  projects on top, or *Create new project*), also later on finalised or sent documents; the project page lists
  *Quotations & invoices* for people with office rights only (#2665).
- **Office rights**: a client's invoicing fields belong to *Quotes & invoices*, sets / roles / crew to *Equipment*; "own entries only" covers times to bill and own reports; agents need the area *Receipts* for an organisation's receipts (#2735).
- **Pictures**: the bot figure's antenna sways gently at rest; profile pictures come as ten people for users and ten bots
  for agents (#2673 #2674 #2675).

</details>
<details>
<summary><a id="notes"></a><b>Notes</b></summary>

Every project has **notes**: Markdown documents next to the tasks for meeting notes, briefings and decisions
(project menu > *Notes*, the project page). Title, tags, pinned notes first, a search field; typing saves by itself,
*Read* shows the rendered text where `#123` links that task. Each note has its own address (`#note/<id>`, *Copy link*),
moves to another project, and is found by the command field. Everyone who sees the whole project reads its notes (participants
do not), owner, project admins and members write them; when someone else changed a note while you were typing, Kalmido shows
both versions. API: `/lists/{id}/notes`, `/notes` (docs/API.md), MCP tools `list_notes`, `search_notes`, `create_note` ….

</details>
<details>
<summary><a id="tasks-by-e-mail"></a><b>Tasks by e-mail</b></summary>

With one mailbox set up (`KALMIDO_MAIL_ADDRESS` + `KALMIDO_IMAP_*`, see *Configuration*), everyone gets a **secret
address** for new tasks: Settings > Integrations > *Tasks by e-mail* (`tasks+<token>@example.com` lands in your basket,
an address per project lands in that project while you may change it). The subject becomes the title, the text the
description, attachments become files, "Fwd:" / "WG:" are dropped, the same message never twice. *New address* makes the
old one stop working. Optionally, mails from your own address (an admin stores it under Settings > Users) to the plain address go to your basket
too (off by default: sender addresses can be forged). The mailbox must deliver plus addresses (`+…`) to it, which most
providers do. With `KALMIDO_SMTP_*` the **daily summary** (Settings > Notifications, *Daily digest at*) also comes by
e-mail: overdue, today, tomorrow, what waits for you and what is unread; *Send now* tries it.

**A mailbox per workspace (2.141):** in the e-mail filing (*Office > Clients > E-mails*) the section *Mailbox* lets the
admins of an organisation - or a person for their private space - enter an own IMAP mailbox and SMTP access. Its mails
are fetched every `KALMIDO_IMAP_INTERVAL` seconds and filed in that workspace only (by sender, plus address or as a reply
to a filed mail; otherwise *Not assigned*). Passwords are stored encrypted and never shown again; the servers are reached
only with a valid certificate, and hosts in the local network only when listed under *allowed internal hosts*
(`KALMIDO_CALENDAR_ALLOW_HOSTS`). With SMTP set up, *Reply* and *New e-mail* send plain-text mails that are filed as
*Sent*. HTML mails are shown cleaned in a sandboxed frame; external images load only on request.

</details>
<details>
<summary><a id="calendar-subscriptions-other-calendars-in-kalmido"></a><b>Calendar subscriptions (other calendars in Kalmido)</b></summary>

![Calendar week with tasks and calendar events](docs/calendar-events.png)

*Settings > Integrations > Calendars > Add calendar* shows events from your other calendars in Kalmido's month, week
and day view, in the calendar's timeline and, optionally, as *Events today* at the top of *Today*. Events are
read-only and look different from tasks (tinted and outlined in the calendar's colour; all-day events in the all-day
row). A click shows title, time, place, description (plain text, only http / https links are clickable) and the
calendar, plus **Create task from event** (a task in the basket with the event's title, date, time and duration,
opened for editing). Subscriptions are private: project members never see them. Two ways to add one:

- **Link (ICS / iCal)**, `https://` or `webcal://`:
  **Google Calendar:** on a computer, calendar.google.com > *Settings* > your calendar > *Integrate calendar* >
  *Secret address in iCal format*. **iCloud:** share the calendar as a *Public Calendar* in the Calendar app and copy
  the link. **Outlook / Microsoft 365:** *Settings > Calendar > Shared calendars > Publish a calendar* > ICS link.
  Any other `.ics` URL works too.
- **CalDAV account:** server address, username and password (use an app password where the service offers one:
  iCloud `caldav.icloud.com` with an app-specific password, Nextcloud, Radicale, Baïkal, Fastmail, mailbox.org ...).
  Kalmido finds your calendars (`current-user-principal` > `calendar-home-set`, also via `/.well-known/caldav`) and you
  pick which ones to show.

**What is fetched:** the server fetches every subscription every 15 minutes or every hour (per calendar), and
*Refresh now* on demand (rate-limited). It keeps the events from 60 days back to 365 days ahead and expands
recurring events (RRULE, RDATE, EXDATE, moved or cancelled occurrences, time zones, floating times in the server's
`TZ`). ICS links are fetched with `If-None-Match` / `If-Modified-Since`, CalDAV calendars only when their `getctag` /
`sync-token` changed (plus once a day, as the window moves). A download may be at most 10 MB, a calendar keeps at most
5,000 occurrences (the ones closest to today), rules below daily (hourly, every minute) are not expanded, and nothing
is ever written back to a calendar. Each calendar shows its last sync and error; after five failed syncs in a row the
admins get an *Integration problems* alert (subscription id, user and error class only).

**Security:** the link (for Google a secret address) and the CalDAV password are stored encrypted (AES-GCM with a
key derived from a random server secret in the database) and are never sent back to the browser, nor logged; a
backup of the database contains both, so keep it as private as the data itself. Credentials only go to the host they
were entered for (and, over https, to the same parent domain when a CalDAV server points there, as iCloud does).
Every fetch is protected against server-side request forgery: before connecting, the server resolves the host name
and refuses private, loopback, link-local, CGNAT (100.64.0.0/10), multicast and reserved addresses (IPv4 and IPv6,
including IPv4-mapped and NAT64 / 6to4 forms), then connects to exactly the address it checked (no second DNS
lookup, so DNS rebinding does not help; TLS still verifies the host name). Redirects are followed by hand, at most
five, never from https to http, to another host only for links without a password and only over https, and every hop
runs through the same check. XML from CalDAV servers with a DTD or entities is refused.

**Your own server at home:** a Radicale, Nextcloud or other calendar server in your own network (a LAN or VPN
address) is blocked by that guard until an admin allows its host: *Settings > Administration > Advanced > Allowed
internal hosts* (`host` or `host:port`, comma-separated), or `KALMIDO_CALENDAR_ALLOW_HOSTS` in the environment. Only
list servers you trust: every user can then subscribe to calendars on them. `KALMIDO_CALENDARS=0` turns the whole
feature off.

</details>
<details>
<summary><a id="calendar-subscription-your-tasks-in-other-calendars"></a><b>Calendar subscription (your tasks in other calendars)</b></summary>

*Settings > Integrations > Calendar subscription > Create subscription link* gives you a private URL
(`https://tasks.example.com/ical/<id>.<secret>.ics`) that any calendar app can subscribe to (read-only):

- **Google Calendar / Android:** calendar.google.com > *Other calendars* > *+* > *From URL*. It then syncs to the phone.
- **iPhone / iPad:** *Settings > Apps > Calendar > Calendar Accounts > Add Account > Other > Add Subscribed Calendar*;
  **Mac:** *Calendar > File > New Calendar Subscription*. **Thunderbird:** *New Calendar > On the Network*. **Outlook:** *Add calendar > Subscribe from web*.

What is in it: open tasks with a due date from all projects you can see (or, per setting, only your own and those
assigned to you). Timed tasks are events with their duration (30 minutes if none is set), all-day tasks are all-day
events (a start date makes it a range), recurring tasks carry their RRULE so every future date shows up (tasks that
repeat from the completion date only show their next date), reminders become alarms (can be switched off), and the
description holds the notes, the project and a link back to the task. Completed tasks disappear on the next refresh;
how often that happens is up to the calendar app (Google: every few hours).

> [!NOTE]
> Google Calendar, iCloud and Outlook.com fetch subscriptions from their own servers, so your Kalmido must be
> reachable from the internet at that address. If it only runs at home or behind a VPN, use a client that fetches
> on the device: [ICSx⁵](https://icsx5.bitfire.at) on Android (the calendar then appears in every calendar app),
> the location *On My Mac* instead of iCloud on a Mac, or Thunderbird.

The secret in the URL is the only credential: anyone with the link can read these tasks. *New link* replaces it
(the old URL stops working at once), *Turn off* removes it. Wrong tokens answer 404 and are rate-limited per
address. With a login proxy, let `/ical/*` bypass it (see *Reverse proxy*); Kalmido never reads the proxy header there.

</details>
<details>
<summary><a id="calendar-apps-caldav"></a><b>Calendar apps (CalDAV)</b></summary>

Kalmido is a CalDAV server for tasks: every project you see (not archived) shows up as a task list in Reminders on iPhone,
iPad and Mac, Thunderbird, Evolution, Tasks.org or DAVx⁵ (with Tasks.org, jtx Board or OpenTasks) on Android, and changes
go both ways. *Settings > Account > App passwords* creates a password per device (shown once, stored as a hash,
revocable, with its last use); *Settings > Integrations > Calendar apps (CalDAV)* shows the server, the address
`https://<host>/dav/`, your user name and step-by-step guides for each app. iPhone and Mac only need the host name
(discovery via `/.well-known/caldav`).

What syncs: title, notes, due date (all-day or with a time, any time zone is converted to the server's), start,
priority, done / won't do, your tags (`CATEGORIES`), subtasks (`RELATED-TO`), repeat rules (daily to yearly; completing
moves the task on as in the app), reminders (`VALARM`) and the link. Everything else a client writes comes back to it
unchanged. Viewers get read-only projects, participants only their tasks; deleting moves to the trash; changes show "via
CalDAV" in the history. Behind a login proxy, `/dav` and `/.well-known/caldav` must bypass the login (see *Reverse
proxy*). Details, the mapping table and proxy examples (Caddy, Authelia, nginx, Traefik): [docs/CALDAV.md](docs/CALDAV.md).

</details>
<details>
<summary><a id="rest-api-and-webhooks"></a><b>REST API and webhooks</b></summary>

Kalmido has a small REST API (`/api/v1`) for scripts and integrations, and outgoing webhooks. Full reference with
examples for curl, Home Assistant, n8n and a shell script: **[docs/API.md](docs/API.md)**; the OpenAPI 3.1 description
is served at `/api/v1/openapi.json`.

- **Personal access tokens** (*Settings > Access*, was *Account > Advanced > API tokens*): name, permissions (2.15.0: *Read* always,
  *Tasks*, *Comments*, *Structure*, *Delete & trash*, *Read files*, *Upload files*, *Time tracking*, *Export*, *Account
  settings*, and *Admin read* for admins; changeable later with the lock button), optional address restriction and
  expiry. Older tokens with *write* keep everything. Shown once (`abk_...`), stored only as a SHA-256 hash, revocable. A token acts as its user
  and never has more rights: the same project roles and switches as in the app apply to every request, and a disabled
  user's tokens stop working. Send it as `Authorization: Bearer abk_...`; the API accepts nothing else (no cookie, no
  proxy header), so it needs no CSRF header. 120 requests per token and minute (`KALMIDO_API_RATE`).
- **Endpoints:** projects (also archive, delete, members, folders), sections, tasks (filter by project, due range, status,
  tag, assignee, updated since; create, change, complete, reopen, move with position, batch, skip, trash and restore),
  subtasks, dependencies, custom fields, templates, files, tags, comments, saved filters, News, time entries and the
  timer, habits, search, export, and for admins users and server status. JSON, ISO dates, cursor pages, one error format. Changes show up in the task history
  *via API* and notify people like changes in the app.
- **Webhooks** (*Settings > Integrations > Advanced > Webhooks*): up to 10 URLs per user for `task.created`, `task.updated`,
  `task.completed`, `task.reopened`, `task.deleted`, `comment.created` and `list.shared`, only for projects that user can
  see. Every delivery is signed (`X-Kalmido-Signature: t=...,v1=<HMAC-SHA256>`, check it and reject anything older than
  5 minutes), retried after 1 min, 5 min, 30 min and 2 h, then the webhook is turned off and the admins are alerted.
  A delivery log (last 50 attempts, no bodies) and *Send test* help setting it up. Only public https addresses, like
  calendar subscriptions; internal hosts need the admin allow-list (then http:// works too).
- **Strict input** (2.2.1): an unknown JSON field is refused with `400` and `{"error": {"code": "unknown_field",
  "fields": [...]}}`, so a misspelt field never gets lost silently (`content` is accepted as an alias of `notes`).
- `KALMIDO_API=0` / `KALMIDO_WEBHOOKS=0` turn them off.

</details>
<details>
<summary><a id="ai-agents"></a><b>AI agents</b></summary>

Agents are external programs (Claude Code, Codex, n8n, a local model, a script) that work in Kalmido like a team
member: an admin creates them under *Settings > Agents* (or turns an existing user into an agent), shares projects
with them and gives them a token. When an admin allows it (*Settings > Administration > Agents > Users may create their own
agents*, off by default, a limit per person), everyone can create **personal agents** (2.7.2): owned by their creator,
seeing only the projects the creator shares with them, chatting only with the creator, never admins. Since 2.28.0 (#965)
**admins reach agents like everyone** -- only through projects they are in (as the owner / a project admin, or where *Members
may see and use the agent* is on); somebody else's personal agent is listed in the administration by name and owner with
the kill switch only. *Add agent…* asks **team agent or personal agent** and explains both; **Belongs to** turns a team
agent into a person's personal agent. Every agent works in **one workspace** (private or an organisation, see
*Workspaces*) and joins only its projects. A small **robot badge** marks agents wherever people appear (#985). Kalmido
itself never starts an agent or any other process; the agent runs wherever you like and talks to Kalmido through the REST
API, webhooks or the MCP server. The one exception is the optional **built-in assistant** (2.75.0, #1411, off by default):
the operator points Kalmido at a single OpenAI-compatible chat model (a provider in the EU, or Ollama on the same
server); every person switches it on for themselves and ticks the projects it may read, and gets summaries, extracted
tasks, basket sorting, tag / due-date suggestions, short drafts and day plans as proposal cards with yes / no - never a
direct change, every call in a log without texts. See [docs/ASSISTANT.md](docs/ASSISTANT.md). The optional similarity service (`KALMIDO_EMBED_URL`) likewise sends task titles and descriptions to the service the admin enters (on another host only with `KALMIDO_EMBED_EXTERNAL=1`).

**Which agent?** A personal agent runs on your computer with your Claude access and only you give it orders; a team
agent runs on a shared, always-on computer and colleagues give it orders. See [Which agent when?](docs/AGENTS.md#which-agent-when-2466).

**Everyday helpers** (2.34.0): Kalmido collects the data, the agent writes. The **morning briefing** (#264, top of
*Today*, optional push at a time you choose) and the **project status report** (#265, *Status report* on the project
page) are plain data views; agents read them with `read_briefing` / `read_project_status`. The **Lying idle** view
(#266) lists tasks nobody touched for a while; with *Agent follows up* on a project (off by default) its agent gets them
once a day (`stale_tasks`) and asks or drafts a reminder in a comment. **Planned jobs** (#272, *Plans* on an agent's
card) send an agent a recurring order ("every Monday at 9: the week plan"; `scheduled_job`), the answer arrives in your
chat. Agents read the **text of PDF attachments** (#368, `read_attachment`; no OCR for scans).

**Plan usage ring** (2.33.0, #1045): an agent can report how much of its plan it has used (`PUT /api/v1/agent/quota`,
MCP `report_plan_usage`, Claude Code's status line `rate_limits` as it is); a ring next to its name in the chat header
fills up, turns yellow from 75 % and red with "paused until …" at the agent's own limit, and greys out when the report
is older than 24 hours. Agents also receive the message a reply refers to and can search the chats they are in
(`search_messages`).

- **No silent overwriting**: edits from several devices, people and agents never overwrite each other unnoticed (conflict hints, history of task descriptions, a recurring task advances once per check-off).
- **Safe by default** (2.30.0, #919 / #920): an agent never connects two projects with **different people** unasked --
  sharing such a project with it (or adding a person to a project with an agent) asks the owner first (*Connect anyway*), and
  existing bridges are flagged in the agent's settings; an agent that moves a task into a project more people see waits for
  approval. Agents and API tokens can be **limited to chosen projects**; *Agent access* in a project's menu shows which agents
  read or changed it in the last 30 days. *Settings > Agents > Use safely* has ten rules (one agent per context, minimal
  rights, ...); more in [docs/AGENT-SECURITY.md](docs/AGENT-SECURITY.md#use-agents-safely).
- **Listening in by project type** (2.30.0, #1034): in a *Software / AI development* list the agent gets every new or
  moved task and every comment without an @mention; elsewhere only @mentions, assignments and wakes. *Agent listens in*
  is a switch in every project and folder; tidying up is a separate switch.
- Events (mention, assignment, comment, chat, reaction, job action, tidy request, wake (API), runtime change / reset
  (2.4.1), and from 2.1.0
  `followup_due`: the follow-up day of a task *waiting on external* the agent follows) arrive as signed
  webhooks and are also kept for polling: `GET /api/v1/agent/events?since=<cursor>&wait=60` answers as soon as
  something happens (long-polling), so an agent without a public address reacts within seconds.
- Approval semantics, status reporting, jobs, chat, the *tidy up* setting, payloads and an example session:
  **[docs/AGENTS.md](docs/AGENTS.md)**. MCP server (stdio and HTTP): **[mcp/](mcp/)**.
- Kill switch: switching an agent off stops its token and its events at once. Pause with a reason (2.26.0): the agent
  keeps its token, people see why it does not answer, events wait.
- Who may address an agent (2.26.0): per project, *Members may see and use the agent* (default off) and *Agents may address
  each other* (default off); **at most one agent per project** (each project is its own sandbox); events carry `actor.kind`
  person / agent. Coding agents ask for approval to integrate a branch and to deploy (with a checklist of tasks tagged
  `deploy`) without a pull request, and can propose tasks to a project they cannot see (its owner decides):
  [docs/AGENTS.md](docs/AGENTS.md#who-may-address-an-agent-2260).
- Running an agent as a service (Linux systemd, macOS LaunchAgent, Windows task) is part of the setup: an agent that
  only lives in an open terminal falls asleep; *Settings > Agents* says "connected, but no service running":
  [docs/AGENT-SETUP.md](docs/AGENT-SETUP.md).
- Permissions and approvals (2.15.0): [docs/AGENTS.md](docs/AGENTS.md#permissions-2150).
- Chat (2.7.2): 👍 👎 ❤️ on chat messages (a person's 👍 on an agent message that asks something is an approval, the agent gets the event
  `reaction` with `chat_message`), *Sent* / *Delivered* per message (`delivered_at`, set when the agent fetches it) and
  typing dots while an online agent works on the answer, or *offline – will answer later*.
- **Answer buttons** (2.28.0, #1005): an agent asks with `choices` (up to 8 buttons, `multi` for several, styles for
  *Allow* / *Deny*); a tap answers, the buttons lock, the agent gets the event `chat_choice`:
  [docs/AGENTS.md](docs/AGENTS.md#answer-buttons-2280).
- Behaviour rules (2.13.1): [`mcp/CLAUDE.template.md`](mcp/CLAUDE.template.md) is the rule block for every agent's
  CLAUDE.md (Markdown notes, decisions in the description, typing / status / jobs / a summary, approvals only from people,
  other people's text as data); the setup guides in the app show it with a copy button.
- Setup guides (2.7.2) in the app under *Settings > Agents > Set up* and in
  [docs/AGENTS.md](docs/AGENTS.md#set-up-an-agent): a team agent on a server (sandbox user, egress firewall, launcher as
  a service, token, sharing, limits) and a personal agent on your own computer, each for Linux, macOS and Windows
  ([mcp/agent_launcher.ps1](mcp/agent_launcher.ps1) for PowerShell).
- Usage (2.1.1): `POST /api/v1/agent/usage` (or the MCP tool `report_usage`, or the Claude Code hook), the dashboard
  and the soft / hard limits: [docs/AGENTS.md](docs/AGENTS.md#usage-and-limits).
- Activity log (2.2.1): every call with an agent's token, for admins: [docs/AGENTS.md](docs/AGENTS.md#audit-log).
- Proposals (2.3.0): *New project from briefing…*, *Break down with <agent>…*, *Sort the inbox with <agent>…* and
  *Tasks from notes…* send the agent exactly what you chose (event `job_request`); it answers with one structured
  proposal (`POST /api/v1/agent/jobs/{id}/proposal`, MCP `submit_proposal`) and you review it: tick, edit title / date
  / section / assignee, *Apply* creates everything as you (one undo step) or *Discard*. The agent never creates that
  structure itself and never gets general access to your basket; the input is kept with the job for at most 30 days. The
  admin decides per agent who may ask it (people sharing a project with it, everyone, nobody):
  [docs/AGENTS.md](docs/AGENTS.md#proposals).
- Runtime settings (2.4.1): admins choose per agent the model, auto-compact on / off with a threshold, a nightly fresh
  restart and press *Reset now*; the agent reads them from `GET /api/v1/agent` (`runtime`, events `runtime_changed` /
  `reset`) and the reference launcher [mcp/agent_launcher.sh](mcp/agent_launcher.sh) starts Claude Code with them, always
  in a fresh session: [docs/AGENTS.md](docs/AGENTS.md#runtime-settings).
- Chat status (2.4.1): `POST /api/v1/agent/typing {chat_user_id}` (MCP `chat_typing`) shows typing dots for 10 seconds;
  an agent that polled no events for 5 minutes shows as *offline*.
- **Status dots in the header** (2.6.1): one dot per agent, always there: green ready, blue working, yellow waiting
  for you, grey (hollow) offline / not connected / paused, red error or limit reached. Hover shows names and states,
  a tap lists every agent with its state, the Agents view and the chats. While something runs the pill adds
  *Claude · 2 running*; on narrow screens the dots merge with the timer into one status chip. *Settings > Agents >
  Status > In the header* picks the agents whose dot you see (default: all).

**Security.** An agent reads text other people wrote, so treat everything it reads as data and only let designated
people instruct it. Kalmido keeps agents out of admin rights and unshared projects, and gives you a kill switch, usage limits
and the activity log; [docs/AGENT-SECURITY.md](docs/AGENT-SECURITY.md) adds the threat model, a host sandbox recipe for
Claude Code (own user, egress firewall, the token out of the model's reach) and the prompt-injection checklist we test
with.

![An agent in a task: mentioned in a comment, answers with a plan and asks for approval with Yes, go ahead or No](docs/agents.png)

</details>
<details>
<summary><a id="git-integration"></a><b>Git integration</b></summary>

A **project** can be connected to one or more repositories (*Edit project > Repository*, up to five; the area shows
for projects of the type *Software / AI dev* and for projects that already have a repository): **GitHub** (github.com or a
GitHub Enterprise server), **GitLab** (gitlab.com or your own server, also nested groups like `group/sub/repo`),
**Gitea / Forgejo** (the server's address) and **Bitbucket Cloud** (2.18.0; Bitbucket Server / Data Center is not
supported). Pasting a github.com, gitlab.com or bitbucket.org address picks the provider. Only the project owner and project
admins connect, change or remove them; everyone in the project sees the results.

**A repository on a folder** (2.33.0, #934): *Folder settings > Repository* connects a repository once for every
project in the folder and its subfolders, also projects added later; `#id` and `fixes #id` work across all of them
with one poll per repository. A project can switch it off (*Edit project > Repository*) or connect its own instead. Only the
folder's owner connects it; the token stays sealed.

- **Token:** a fine-grained token with *read-only* access to the repository (contents, pull requests, commit statuses /
  checks) is enough (GitLab: `read_api`; Bitbucket: a read-only repository or workspace access token, or
  `user:app-password`); a public repository works without one (with GitHub's much lower limit for anonymous requests).
  It is write-only (the page only says *Token set*) and encrypted with `KALMIDO_SECRET_KEY`;
  without the key no token can be stored. Kalmido never gets write access: it only reads.
- **Polling, not webhooks:** the server asks the Git server itself, every 3 minutes per repository
  (`KALMIDO_GIT_POLL`), with ETags (unchanged answers cost GitHub no rate limit), pauses when the rate limit runs low
  and backs off while a repository fails (up to an hour). So it works on a server that GitHub cannot reach (behind a
  VPN, in the office LAN). A background thread does it, a few repositories at a time: requests never wait on it.
  Internal Git servers need the host on the admin allow-list (*Settings > Administration > Advanced*, or
  `KALMIDO_CALENDAR_ALLOW_HOSTS`), the same SSRF guard as calendar subscriptions.
- **Matching** (tasks of the connected project only): `#123` (the task number, in the address `#t/123`) in a commit
  message, a pull request title or description, or a branch named `kalmido-123` (also `kalmido-123-…`), `task-123-…` or `123-…`.
- **Task panel > Code** (after the fields, before the comments): the linked pull requests (open / merged / closed,
  author, CI ✓ ✗ ⏲ from the combined status and the check runs) and the latest commits, a button that copies a branch
  name for the task, and *… is working on it* while an assigned agent works on it. Rows show a chip with the pull request
  and its CI. The history notes when a linked pull request is opened, merged or closed.
- **Keywords:** `fixes #123`, `closes #123`, `resolves #123` (also fix / fixed, close / closed, resolve / resolved, and
  German `erledigt #123`) in a **merged** pull request or a commit on the default branch complete the task, once, and
  only for changes after the repository was connected. The history names the pull request or commit and has *Undo*.
- **Optional webhook** (off by default, for a Gitea / Forgejo next door or a public server): *Turn the webhook on* shows
  the payload URL `/api/hooks/git/<id>` and a secret once; a push, pull request or status event with a valid signature
  (`X-Hub-Signature-256`, `X-Gitea-Signature`, `X-Forgejo-Signature`, GitLab's *Secret token* `X-Gitlab-Token`,
  Bitbucket's *Secret* `X-Hub-Signature`) triggers the next check at once. The body is
  never trusted, polling stays the source of truth.
- **Build state** (2.151.0): every linked commit and merged pull request knows the **first version tag** that holds it
  (a new tag is compared once with the version before it; tags are versions like `v2.151.0`, sorted by number), and
  branches named after a task are compared with the default branch. *Code* starts with one line: *In version 2.151.0*,
  *In main, not released yet* or *Built, not in main yet* with the branch and how many commits it is ahead. The project's
  **version field** (a text field named *Package*, *Version*, *Release* or *Target version*, or the one picked in the
  repository dialog; *Off* turns it off) is checked against the tags: a task that is still open although a tag with
  exactly its version exists gets a hint at the task and a small mark in its row. Values like `2.46c` are not checked.
  Agents read it as `build` (`get_task`, `GET /api/v1/tasks/{id}`) and per project with `list_build_status`
  (`GET /api/v1/lists/{id}/build-status`).
- **Releases** (2.18.0): a new tag like `v2.18.0` completes the open milestone "2.18.0" or "Release 2.18.0" of the project
  once, with *Undo*; tags that existed before the connection never do.
- **Error reports** (2.18.0): *Error reports > Turn on* gives the project a secret URL (shown once; *New URL*, *Turn off*).
  Point a Sentry webhook (an internal integration with issue / alert webhooks) or any service that sends JSON
  `{title, body, url, fingerprint, level}` at it: a new error becomes a bug ticket with the details and the link, the same
  error again only counts up at its open ticket. A new error sends one News item and push (*Settings > Notifications >
  New error reports*); repeats stay quiet. At most `KALMIDO_ERROR_REPORTS_PER_HOUR` (default 30) new tickets per
  project and hour. Tasks by e-mail (see [Tasks by e-mail](#tasks-by-e-mail)) are another way in.
- **Code in Markdown** (2.18.0): code blocks are highlighted by language and have *Copy*; `src/app.py:42` (or
  `app.js:10-20`) in notes and comments links to that file and line at the default branch.
- **API / MCP:** `GET /api/v1/lists/{id}/repos` (never a token), `get_task` includes `code` and `repo`;
  `GET` / `PATCH /api/v1/lists/{id}/error-hook` for people.

### Hand a ticket to a coding agent

Assign a task in a connected project to an agent (for example Claude Code with the MCP server on a dev machine). Its
`assigned` event and `get_task` carry `repo`: provider, web address, owner / name, default branch, a suggested branch
`kalmido-<id>` and the linked pull requests with CI. The agent works in its own checkout, pushes the branch with its
own credentials, opens a pull request and asks for approval (`request_merge_approval`): a *Ready to merge* comment with
the pull request, its CI and *Approve* / *Reject* for the project owner, project admins, the assignee and admins. 👍 / 👎 sends
the agent a `reaction` event with `approval` and `merge_request`; only then does it merge. A sample `CLAUDE.md` for such
a project agent: [docs/AGENTS.md](docs/AGENTS.md#coding-agent-workflow).

</details>
<details>
<summary><a id="templates-undo-statistics"></a><b>Templates, undo, statistics</b></summary>

- **Templates:** *Save as template* in a task's menu (the task with its subtasks, priority, tags, notes, repeat and
  dates as "days after use") or in the project dialog (sections and open tasks). The template button in the add bar
  creates the task in the current project, *Projects > + > New project from template* a new project. Templates are private and
  can be renamed, edited as a plain outline (one task per line, two spaces per level, `# Name` = section) or deleted
  under *Settings > Data*.
- **Project templates with relative dates:** saving a project keeps every date as *Start + n days*, counted
  from the project's earliest start or due date, together with sections, custom fields, dependencies, ticket types
  and *Move dependent tasks along*. Using it asks for the project start and, optionally, an end date: the dates are
  then stretched or squeezed so the last one falls on the end. Your templates also show up as cards next to the
  project types (Agency, Software / AI dev, Personal) in *New project*.
- **Undo and redo:** the ← / → buttons in the top bar (on phones and touch tablets: *Undo: …* / *Redo: …* at the top of the header's “…” menu) step back and forward through the
  history of this device: up to 30 steps, kept until you reload the page. Their tooltip names the step (*Undo:
  Completed “Pay invoice”*, *Redo: Moved 3 tasks to Work*); right-click or long-press ← (or →) lists the last ten
  steps, and picking one undoes everything up to it, one step after the other. Covered: completing, reopening and
  *Won't do*, creating and deleting tasks (undo moves a new task to the trash, a deleted one comes back), title,
  description, tags, priority, date, repeat, reminder, assignee, link and custom field values, moves between projects,
  sections and levels, subtasks, *Skip this occurrence*, sections (add, rename, delete with their tasks, reorder),
  projects (type, name, colour, view, *Move dependent tasks along*, hourly rate, archive, folder, order), batch actions,
  moving a whole project in the roadmap, dependent tasks moved along, deleted time entries. Typing counts as one step
  per field until you leave it. A new change clears the steps forward. The toast after an action still offers *Undo*
  for six seconds.
  Undo and redo never overwrite a change made in the meantime, by you on another device or by someone else: such a
  field stays as it is and a notice lists it (*Changed elsewhere, not undone: “Invoice”: Priority*). Steps with
  several tasks go to the server in one request (all or nothing per task). A task that someone else changed after it
  came back from the trash is not deleted again. Steps in a project that became view-only for you are refused. Offline,
  a change that has not been sent yet is simply taken out of the queue; otherwise undo and redo are queued like any
  change (a dot on the button shows it is waiting). Sections and project settings need a connection.
  Since 2.270.0 edits from several devices, people and agents never silently overwrite each other: conflict hints, a history of
  descriptions, `Idempotency-Key` on writes, and recurring tasks advance once per check-off.

  | Keys | |
  |---|---|
  | Ctrl+Z / Cmd+Z | Undo (outside text fields; while typing, the browser's own text undo applies) |
  | Ctrl+Shift+Z / Cmd+Shift+Z, Ctrl+Y | Redo |
  | Right-click or long-press on ← / → | The last ten steps, jump to one |

<p align="center"><img src="docs/undo.png" alt="Top bar with the undo and redo arrows and the history menu: task moved, date changed"></p>

- **Settings save themselves:** every switch, choice and field in *Settings* applies at once and shows *Saved · Undo*;
  each change is a step in the history above, so a wrong click is one *Undo* away. *Settings > Modules* lists every
  module with one sentence; switched off, a module disappears from the menus and nothing is deleted.
- **Date and time pickers** follow the app language, not the browser: the week starts on your locale's first day,
  times show 12 or 24 hours as your locale does, and you can type a time (`930`, `9:30 pm`, `21 Uhr`). Arrow keys,
  PageUp / PageDown and Enter work in the month grid; on a phone it opens as a sheet.

| Settings > Modules | Date picker |
|---|---|
| <img src="docs/settings-modules.png" alt="Settings, Modules tab: what Kalmido is for, the switch for all modules, then the modules grouped into views, calendar and people, for you"> | <img src="docs/datepicker.png" alt="Task date dialog with the own month grid and a second picker for the start date"> |
- **Statistics** (module, on by default; sidebar, command bar or a pinned tab) for the last 12 weeks: completed tasks per
  week or per day and per project, on-time rate (completed on or before the due day), the overdue trend (your open
  tasks past their due date at the end of each week), focus minutes per week and per project, habit rates and streaks.
  A completion counts for the person who ticked the task off, also in shared projects.

<p align="center"><img src="docs/stats.png" alt="Statistics view with completed tasks per week, by project, overdue trend, focus time, tracked time and habits"></p>

</details>
<details>
<summary><a id="time-tracking"></a><b>Time tracking</b></summary>

A module (on by default, *Settings > Modules*) for tracking the time you spend on tasks, for yourself or to bill a client.
Since 2.41.0 each project switches it on in its settings (*Track time in this project*, off by default, any project type).
Admins can turn it off for everyone (*Settings > Modules*, *for everyone* next to *Time tracking*): the module
disappears for all users, the time endpoints answer 403, timers running at that moment are stopped (the entries
are kept), focus sessions no longer become time entries and no timer reminders go out. Switched back on, all
entries are there again.

- **Maybe forgotten** (2.34.0, #269): working days of the last two weeks with work on tasks but no tracked time;
  *Copy as text* on the timesheet gives date, task, duration and note with totals for an invoice.
- **Timer:** *Start timer* in a task's detail panel or menu. The running timer shows in the top bar (with the task
  and the elapsed time) on every device you are logged in on; click it to stop, open the task or change the start
  time. One timer per person: starting another one stops the first. Start and stop also work offline: they carry
  the device's time and are sent later with the right times.
- **Manual entries:** *Add time* with a date and a from-to time (an end before the start means the next day) or
  just a duration (`1:30`, `45m`, `1.5`). The *Time* section of a task lists its entries with totals; your own
  entries can be edited, continued (a new timer with the same note) or deleted (with undo). A task row shows a small
  total-time chip.
- **Focus sessions** (Pomodoro or stopwatch) on a task count as time entries when they end, unless a timer ran at
  the same time: the timer wins, nothing is counted twice. Can be turned off in *Settings > Modules > Time tracking settings*.
- **Reports** (sidebar *Time tracking*, the command bar or a pinned tab): this week, last week, this month, last month or a
  custom range; totals per project and task, per day and per person, filtered by projects and, with shared projects, *only
  mine* or *all members*. **CSV export** (one row per entry: project, task, user, start, end, duration in hours and
  h:mm, rounded hours, amount, note; UTF-8 with BOM, in German with `;` and decimal commas for Excel) and a
  printable **timesheet** (summary per project and task, hours per day, individual entries; *Print / save as PDF*).
- **Rounding and rates:** every entry can be rounded up to 5, 6, 10, 15 or 30 minutes in reports, CSV and the
  timesheet; the tracked times stay exact. The project owner can set an hourly rate in the project dialog, the report
  then shows amounts. A daily target shows today's progress.
- **Forgotten timers:** a push notification after a few hours (default 4) and an automatic stop after 12 hours
  (end = start + 12 h), both adjustable per user.
- **Rules:** an entry counts on the local day it starts (entries across midnight are not split); durations are
  real elapsed time, so daylight-saving changes are exact; weeks start on Monday. In a shared project every member
  sees everyone's time on its tasks, but only the person who tracked an entry can change it; time on private
  tasks stays private. View-only members can track their own time.

<p align="center"><img src="docs/time.png" alt="Time tracking report with hours per day and per project and task"></p>

</details>
<details>
<summary><a id="projects-dependencies-status-custom-fields"></a><b>Projects: dependencies, status, custom fields</b></summary>

**Project types.** *Projects > + > New project…* (also from the command palette, the setup and the first welcome card)
can start from a type:

| Type | Standard sections (2.27.0: only when ticked) | Also |
|---|---|---|
| Agency | Request · Concept · Production · Approval · Billing | fields *Client* (text) and *Budget h* (number), time tracking |
| Software / AI dev | Backlog · Next · In progress · Review · Done | Kanban view, ticket types, dependencies, *Move dependent tasks along*; a next-steps dialog to connect a repository and, optionally, share the project with a coding agent |
| Personal | Ideas · Planning · To do | no fields |

A new project starts without sections; tick *With the standard sections* to get the type's (2.27.0). The names come
in your language (German: Anfrage / Konzept / Umsetzung …). A type switches the modules it needs on for you and says
so. Types are templates: change anything afterwards. API: `POST /api/v1/lists {"project_type": "agency" | "software" |
"private", "sections": true}`.

**Ticket types.** A project setting (*Ticket types*, in the project dialog of a project; on for Software / AI dev): tasks
get a type, *Bug*, *Feature* or *Task*, shown as a small chip with an icon, set in the task panel or in quick add
with `!bug`, `!feature`, `!task` (German `!fehler`, `!funktion`, `!aufgabe`), and filterable in saved filters. A new
bug starts with the notes *Steps to reproduce / Expected / Actual / Environment*, a feature with *Goal / Acceptance
criteria* (in your language; *Templates…* next to the switch sets the project's own). In the API, MCP and agent events
the task has `"type": "bug" | "feature" | "task" | null`; `GET /api/v1/tasks?type=bug` filters.

Every list is a project. For projects that need more than a to-do pile, switch on *Progress and status* (project dialog, the project's
… menu or right-click in the sidebar): the progress ring, the status, the project page and the row in *All projects* appear.
Dependencies (and the Gantt arrows; 2.41.0: time tracking is a switch of its own per project, `time_tracking`, off by default)
and custom fields follow the modules below, so a shopping list or a household project never shows fields unless you want them. The
modules below stay the outer switch: a feature shows when its module is on **and** the project has the matching switch. Switching
*Progress and status* off again only hides these things (nothing is deleted). The server refuses a custom field value
or a status on a project without the switch with a clear message. Time tracking (2.41.0) has its own switch in the project settings
(*Track time in this project*, off by default; projects with time entries got it on with the update):
without it the server refuses a timer or a new time entry, tracked time stays in the review and reports. Projects that already had dependencies, custom fields, a status or at least five
minutes of tracked time got *Progress and status* on with the update; checklists stayed checklists. Each person can hide a project's progress bar with the
small **×** next to it (*Show progress* in the project's … menu or the project dialog brings it back).

![Gantt timeline of a website relaunch: milestones, bars from start to due and arrows from each task to the tasks waiting on it](docs/gantt.png)

- **Gantt timeline** (list view *Timeline*, or *Calendar > Timeline* for all projects): every open task with a date is a
  bar from its start to its due date, and each dependency is an arrow from the end of a task to the start of the
  task waiting on it. A task that starts before a task it waits on is due gets a red arrow and a red edge (*Starts
  before "Design" is due*); waiting tasks are hatched with a lock; arrows from completed tasks are dashed; a task
  outside the visible range or in another project gets a short arrow stub with a tooltip.
  - **Link:** drag the dot at the end of a bar onto another bar: the second task then waits on the first (valid
    targets light up, a loop or a task you may only view is refused). A click on the dot, a long-press on a phone
    (*Connect to…*), or the keyboard (focus a bar with Tab, press **C**, then Enter on the target) do the same;
    *Pick from a project…* opens the searchable picker. Shift+F10 or right-click opens a bar's menu.
  - **Remove:** click an arrow for *Remove dependency* and links to both tasks, or use the bar's menu.
  - **Move dependent tasks along** (project dialog, owner, off by default): when a task is postponed, the tasks of that
    project that wait on it and would now start too early move by the same number of days, keeping their length, and
    so on down the chain (at most ten levels and 50 tasks, only tasks you may change). The toast says *3 dependent
    tasks moved*, and one *Undo* takes the whole chain back.
- **Sort: Flow** (sort menu, only with the dependencies module; the default of projects): tasks in the order
  the dependencies allow, so a task always comes after the ones it waits on; ties by start date, due date and time,
  priority and manual order. When a task in the view waits on something, the first task of each section that waits
  on nothing is marked *Ready to start* (tap it for a short explanation); without dependencies there is no marker.
  Waiting tasks keep their lock. Works in projects (per section), folders, filters and smart lists; dependencies on tasks outside the
  view only keep the lock. Tasks that wait on each other in a circle (old or imported data) fall back to date order
  with a short hint. A manual drag switches the view back to *Priority, then manual*.

### Roadmap: all projects on one timeline

![Roadmap of a small agency: the projects in two folders, each with a summary bar filled by its progress and its milestones](docs/roadmap.png)

- **Where:** *All* > the *Timeline* button next to the title (needs the *Timeline* module; nothing else). Your choice,
  the zoom, the filters and which projects are collapsed are saved for you on the server.
- **Groups:** projects without a folder first, then folder by folder in your sidebar order. Each project has a header row
  with a **summary bar** from the earliest start (or due date) to the latest due date of its open tasks, in the project's
  colour with its emoji, filled by the project progress when the *Project progress* module is on. Click a name (or
  Enter on it) to collapse the project to that one row; *Collapse all* / *Expand all* sit next to the filters. With
  fewer than five projects they start expanded, otherwise collapsed.
- **Filters:** *Projects only* (on by default as soon as one project is a project; otherwise the chart shows every project
  with dates and a hint *Make a project a project to plan it here*), *Hide done*, an assignee (with collaboration) and a
  project / folder picker.
- **Zoom:** *Week* (day columns), *Month* (week columns with the Monday's date) and *Quarter* (week columns, month and
  quarter labels), plus *Today* and back / forward.
- **Move a whole project:** drag its summary bar (the task bars move along while you drag), or long-press it on a
  phone and pick *Move project by…* in days or weeks (also in the bar's menu, or **M** on a focused bar). Every open
  task with a date in that project, subtasks included, moves by the same number of days in one step on the server and
  keeps its length; tasks without a date stay. Tasks in other projects waiting on it follow when their project has *Move
  dependent tasks along* on. The toast says *12 tasks moved*, one *Undo* takes all of it back. You need edit rights
  on the project (view-only members get a notice), and a project with more than 500 dated tasks is refused.
- **Arrows** work across projects as in the Gantt timeline. When a project is collapsed, its arrows start or end at its
  summary bar, several between the same two rows merged into one with a count; click it to see and open them.
- **Phone:** the project names stay put while you scroll sideways, rows are taller, the filters scroll in one line.
- Only the rows in view are drawn, so 50 projects with 1000 tasks stay smooth.

- **Dependencies ("blocked by"):** in a task's panel, *Waiting on…* > *Another task* picks the tasks that have to be done
  first (search over all your open tasks, also in other projects and shared projects), *Blocking…* the other way round.
  Cycles and self-dependencies are refused. The task row shows *blocked* with the names of the open blockers;
  completing a blocked task asks first. When the last blocker is done (or marked *won't do*), the waiting task
  gets an activity line and its assignee (or creator) a News item and a push: *Unblocked: Send invoice*. A blocker
  in the trash is ignored until it is restored; a recurring blocker stays open until its repetition ends.
  *Settings > General > Today* can hide blocked tasks. If you lose access to a blocker, you see
  *a task you cannot see* (never its title) and can remove it.
- **Progress:** the project header shows done vs. all main tasks (optionally subtasks too), overdue tasks and the next
  due date. It counts all time, leaves out *won't do* and the trash, and counts a recurring task once.
- **Status** (with *Collaboration* on): the owner and editors set *On track*, *At risk*, *Off track*, *On hold* or
  *Complete* with a short note. It shows as a coloured pill in the project header, a dot in the sidebar and in the
  overview; everyone else in the project gets it in their News. Each project keeps a status history.
- **Project status** (*Where is it stuck?*; sidebar, command bar or a pinned tab; shown once you have two projects or a shared
  one): per list the status, the progress, overdue tasks grouped by assignee, blocked tasks and, in shared projects, tasks without an
  assignee, with *Needs attention* to hide the calm ones. Everything is clickable.
- **Project page** (2.7.1, projects only; a tab next to List / Kanban / Timeline, on phones in "…"): the place
  for what belongs to the project as a whole. *Description* in Markdown; *Key links* (title + address, in your order,
  an icon from the address such as a repository or a design file, nothing is fetched from the linked site);
  *Milestones* (milestone tasks of the project, see below); *Project files* uploaded on the
  project itself (same size limit and download rules as task files: images and PDFs open, everything else downloads)
  and, read-only, *Attachments from tasks* with
  a link to each task; *Members* with their roles (with collaboration); *Status updates* with *Set status*; the
  tracked time with the budget. Owner, project admins and members change it, viewers and participants read it
  (participants only see the files of their own tasks). The choice of the tab is remembered per device; the project's own
  view stays. Token API: `/api/v1/lists/{id}/overview`, `/links`, `/milestones`, `/files`; MCP tool
  `get_project_overview`.
- **Milestones** (2.18.0): a task can be a milestone (quick add `!milestone`, *This task is a milestone* in the task
  panel, or the task menu): a diamond instead of the round glyph, a date, checked off like a task, no assignee needed;
  in the list, Kanban, calendar and timeline. Tasks belong to a milestone (the release or version they ship in) via
  the *Milestone* field or *Set milestone* in the multi-select; the milestone's panel shows the progress, its tasks, a
  burndown (also as a table) and **release notes** from its completed tasks (Features / Fixes / Other) to copy.
  Token API: `milestone`, `milestone_id` on tasks, `GET /api/v1/tasks/{id}/milestone`; MCP `get_milestone`. The
  older overview milestones were migrated into milestone tasks; `/lists/{id}/milestones` stays as a compatibility
  route (ids are task ids).
- **Project type of an existing project** (2.18.0): *Edit project > Project type* (None, Agency, Software / AI dev,
  Personal), for the owner and project admins. Switching turns on what the type needs (Software: ticket types and the
  *Repository* area) and offers the type's missing sections, with Undo; nothing is deleted.
- **Custom fields:** the project owner adds fields in the project dialog: text, number (optional unit such as € or h),
  selection (options with colours), date, checkbox, person (owner or member of the project) or link. Values are the
  same for everyone in the project; view-only members see them but cannot change them. Up to two fields show as chips
  on the task rows; on a computer the columns button shows up to six fields as a table. Filters (selection,
  checkbox, date, number greater / less / equal / empty) and sorting work on fields, search finds text and option
  names. A task moved to another project keeps its values, hidden until it comes back. Deleting a field deletes its
  values. Project templates keep the fields and their values; the JSON export includes fields, values, dependencies
  and status updates.
- Modules (*Settings > Modules*, per person): *Project progress* (progress, status, the
  overview), *Dependencies* (waiting on, the arrows and linking in the timeline, the waiting part of the overview,
  *Unblocked* notices) and *Custom fields*. Switched off, they are only hidden: nothing is deleted, the API keeps
  working, and switching back on shows everything again. Existing accounts keep both after the update if they
  already use dependencies or custom fields, or the timeline or project progress.

| | |
|---|---|
| <img src="docs/fields.png" alt="Project timeline with blocked tasks; task panel with custom fields (phase, budget, effort, preview link) and tracked time"> | <img src="docs/overview.png" alt="Where is it stuck overview: overdue by assignee, waiting and unassigned tasks per project"> |
| Custom fields, dependencies, progress and status | *Where is it stuck?* |

</details>
<details>
<summary><a id="login"></a><b>Login</b></summary>

**Built-in (default):** username and password (hashed with scrypt), an HttpOnly `SameSite=Lax` session cookie
("stay logged in" = 30 days), failed logins are rate-limited per user name and address (5), per address (20, which slows sign-ins down instead of refusing them; names known at that address for 30 days are not slowed down) and per user
name from all addresses (100, against slow distributed guessing) within 15 minutes, so one attacker cannot lock a person out.
*Administration > Server* shows **your IP** as the server sees it (2.33.0): if it shows a Docker gateway such as
`172.18.0.1` instead of your public address, the proxy hides the clients (see docs/SELF-HOSTING.md).
Behind a reverse proxy Kalmido takes the client address from `X-Forwarded-For` of a trusted proxy (`KALMIDO_TRUSTED_PROXIES`,
default loopback + the Docker bridge gateway). Upgrading from the single-user
version: your data is moved to the user `admin` (or `AUTH_BOOTSTRAP_USER`); give it a password once with
`docker exec -it kalmido python app.py set-password admin`.

**Single sign-on via your reverse proxy:** set `AUTH_PROXY_HEADER` (e.g. `Remote-User`) and
`AUTH_TRUSTED_PROXIES`, then enter each person's proxy user name as *SSO login* in *Settings > Administration*. A logged-in
proxy user without an Kalmido account sees a "no account, ask the admin" page. Without the header (or from an
untrusted address) Kalmido falls back to its own login page.

**Two-factor, passkeys, OpenID Connect:** the built-in login can ask for a second factor (authenticator app,
passkey, recovery code) and passkeys can log in without a password; Kalmido can also log you in through an OpenID
Connect provider. See the two sections below.

> [!CAUTION]
> The header is a password: whoever can send it to Kalmido is that user. Kalmido only trusts it from
> `AUTH_TRUSTED_PROXIES` (the **direct** peer address), never on `/drop`, `/ical/`, `/s/`, `/api/v1/`, `/manifest.json` and static files, and
> your proxy **must remove client-supplied copies** before its auth step, especially on paths that bypass the login.
> With Docker port publishing every connection (your proxy, other containers, monitoring) usually arrives from the
> Docker bridge gateway address; then also set `AUTH_PROXY_PORT=3045` and publish that container port only
> on the address your proxy uses (`127.0.0.1:3040:3045`), so nothing else can reach the port that trusts the header.

**CSRF:** every state-changing API request must carry `X-Requested-With: kalmido` (the app always sends it; other
sites cannot without a CORS preflight, which Kalmido never allows). The REST API under `/api/v1` only accepts personal
access tokens (never the session cookie or the proxy header), so it needs no such header.

**Headers:** every page and API response carries a strict Content-Security-Policy (no inline scripts,
`frame-ancestors 'none'`), `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`
and a restrictive `Permissions-Policy`. Attachments are served with a sandbox CSP; only images
and PDFs are shown inline, everything else is a download. Your proxy does not need to add anything.

**Server-side requests:** the server only contacts services you or your admin configure or use (full list: [docs/SELF-HOSTING.md](docs/SELF-HOSTING.md#outgoing-connections)); the browser loads no CDN, fonts or scripts from outside (exception: the video review shows YouTube / Vimeo players and video files from other https hosts once such a review is opened). The services are
(ntfy, Git hosts), the push services of the browsers that subscribed to Web Push (see *Notifications*), the calendar
links and CalDAV servers your users subscribe to (with an SSRF guard that refuses internal addresses unless an admin
allows the host, see *Calendar subscriptions*), the OpenID Connect provider if you configure one (same guard), your users' webhook URLs (same guard, no redirects, see [docs/API.md](docs/API.md#webhooks)), plus an optional update check against GitHub (`api.github.com`,
see *Updating*), all http/https only with redirects only within the same host (calendar links: see there). Web Push only goes to https endpoints of an allow-list of known push services, so a crafted
subscription cannot make the server call anything else. Links in tasks or shared text are not fetched, with these exceptions: the preview of a saved bookmark (module on), contact photos at a Google import, feeds and calendar subscriptions you add.

### Two-factor authentication and passkeys

For accounts with a password (the built-in login). *Settings > Account > Two-factor authentication*:

- **Authenticator app (TOTP, RFC 6238):** scan the QR code (made on the server, no external service) or type the key
  into Aegis, 2FAS, Google Authenticator, 1Password, Bitwarden, ... and confirm with a first code. After the password
  the login asks for the 6-digit code. A code is accepted once (a used time step is never accepted again), ±30 s of
  clock drift are fine. The secret is stored encrypted with a key derived from a random server secret.
- **Passkeys (WebAuthn):** fingerprint, face, device PIN or a security key. Work as the second factor and, unless an
  admin turns it off, for **logging in without a password** ("Log in with a passkey"; the device must verify the user).
  Add, rename and remove them in the same place; several per account. Passkeys need HTTPS (or `localhost`) and a host
  name, not an IP address. The RP ID is the host the page is opened on (`PUBLIC_URL`, plus the origins in
  `KALMIDO_WEBAUTHN_ORIGINS`), or `KALMIDO_WEBAUTHN_RP_ID` for several hosts under one domain; a passkey only ever works on
  the address it was created on. Registrations use attestation "none"; a sign counter that goes backwards (a cloned
  authenticator) is refused.
- **Recovery codes:** 10 one-time codes, shown once when the first method is set up (copy / download). Only their
  SHA-256 is stored. *New codes* replaces them. Logging in with one tells the admins (admin alert).
- Setting up a method needs the current password; turning the app off needs the password and a code; the first
  method ends your other sessions. Lost phone and codes: an admin can *reset* two-factor in *Settings > Administration* (the
  user's sessions end).

**Admin policy:** *Settings > Administration > Whole server > Require two-factor authentication for built-in logins*. Users
without a second factor must set one up at their next login (before they get a session); the last method cannot be
removed while the policy is on. Logins through the proxy header or OIDC are not affected: two-factor is the job of
your login proxy / identity provider there, and the account page says so. Wrong codes count against the same limits as
wrong passwords (5 per user name / 20 per IP in 15 minutes), a login ticket dies after 5 wrong codes, and the answers
never reveal whether an account exists or has two-factor on.

### OpenID Connect (Authentik, Keycloak, Authelia, PocketID, Google, Microsoft Entra, ...)

A *Log in with ...* button on the login page. Set it up in *Settings > Administration > Sign-in* (2.9.0: the client
secret is stored encrypted with `KALMIDO_SECRET_KEY`, *Check connection* tests the discovery; the sign-in is a draft until the check passed and it is switched on) or with environment
variables; a variable that is set always wins for its field (the settings show it locked). Step-by-step guides per
provider (redirect URI, scopes, group claims): [docs/OIDC.md](docs/OIDC.md).

```ini
KALMIDO_OIDC_ISSUER=https://auth.example.com          # discovery: <issuer>/.well-known/openid-configuration
KALMIDO_OIDC_CLIENT_ID=kalmido
KALMIDO_OIDC_CLIENT_SECRET=...                        # empty = public client (PKCE only)
KALMIDO_OIDC_BUTTON_LABEL=Authentik
#KALMIDO_OIDC_SCOPES=openid profile email             # add "groups" if your provider needs it for the groups claim
#KALMIDO_OIDC_USERNAME_CLAIM=preferred_username
#KALMIDO_OIDC_GROUPS_CLAIM=groups
#KALMIDO_OIDC_REQUIRED_GROUP=kalmido                   # only members may log in
#KALMIDO_OIDC_ADMIN_GROUP=kalmido-admins               # admin flag follows this group (the last admin is never demoted)
#KALMIDO_OIDC_ADMIN_DOMAINS=example.com               # 2.9.0: a verified e-mail of these domains = admin too
```

Register Kalmido at the provider as a confidential client with the redirect URI **`<PUBLIC_URL>/api/auth/oidc/callback`**
(exactly; the admin page shows it with a copy button), grant type *authorization code*, PKCE S256, token endpoint auth
`client_secret_basic` (or `client_secret_post`). Example for Authelia (`identity_providers.oidc.clients`):

```yaml
- client_id: kalmido
  client_name: Kalmido
  client_secret: '$pbkdf2-sha512$...'   # authelia crypto hash generate pbkdf2 --random
  public: false
  authorization_policy: two_factor
  redirect_uris: ['https://tasks.example.com/api/auth/oidc/callback']
  scopes: ['openid', 'profile', 'email', 'groups']
  grant_types: ['authorization_code']
  response_types: ['code']
  require_pkce: true
  pkce_challenge_method: S256
  token_endpoint_auth_method: client_secret_basic
```

**Accounts:** by default only users an admin created can log in. The first OIDC login links a user whose user name
equals the username claim, or whose e-mail (optional field in *Settings > Administration*) equals the provider's **verified**
e-mail; from then on the provider's subject (issuer + `sub`) decides, even if the name changes. 2.79.0: a user name match
needs the same verified e-mail as well (accounts made for SSO, without password and e-mail, link as before), and admins, accounts with a second factor and child accounts are linked only from
their own open session (log in with the password, then use the provider's button once in the same browser). Without a match the
login page says "no account, ask the admin". *Create accounts on the first OIDC login* (admin switch) creates them
instead (no admin rights unless the admin group says so, no password). An admin can unlink a user again.

**Security:** Authorization Code flow with PKCE (S256), `state` (one-time, 10 minutes, bound to the browser by an
HttpOnly cookie, so nobody can log you into their account) and `nonce`. The ID token is verified by Kalmido itself:
signature against the provider's JWKS (RSA, RSA-PSS, ECDSA, Ed25519; never `none` or HMAC; keys cached for an hour and
fetched again for an unknown key id), `iss`, `aud`, `azp`, `exp`, `iat`, `nbf`, `nonce`. Extra claims come from the
userinfo endpoint (only with the same `sub`). Every request to the provider goes through the same SSRF guard as the
calendar subscriptions: public addresses and https only, unless the host is allowed (`KALMIDO_OIDC_ALLOW_HOSTS` or the
internal hosts list under *Settings > Administration > Advanced*), which you need for a provider in your own network. The
client secret, codes and tokens are never logged or shown. Two-factor for OIDC logins is the provider's job.

</details>
<details>
<summary><a id="reverse-proxy"></a><b>Reverse proxy</b></summary>

More from running Kalmido (proxy pitfalls, VPN-only setups, PWA and push, backups and encryption at rest, server
hardening, mail, moving to a new server, production updates): [docs/SELF-HOSTING.md](docs/SELF-HOSTING.md).

Terminate HTTPS in your proxy. If the proxy has its own login (single sign-on), put it in front of everything
except these paths:

| Path | Why it must bypass the login |
|---|---|
| `/manifest.json`, `/static/icon-192.png`, `/static/icon-512.png`, `/static/badge-96.png` | Browsers fetch these without cookies when installing the PWA or showing a notification. They contain no data. |
| `/static/shortcuts/*` | Icons of the app shortcuts in the manifest, also fetched without cookies. |
| `/drop` (and `/drop/drop`) | Upload endpoint for share apps. Protected by each user's own bearer token. `/drop/drop` is an alias for shortcuts that append `/drop` to an address that already ends in it. |
| `/ical/*` | Calendar subscription. Calendar apps cannot log in; the secret token in the URL protects it. |
| `/dav`, `/dav/*`, `/.well-known/caldav` | CalDAV (2.9.0). Calendar apps cannot log in at a portal; Kalmido checks the user name + app password itself and never reads the proxy header there ([docs/CALDAV.md](docs/CALDAV.md#reverse-proxy-let-dav-past-the-login-proxy)). |
| `/s/*`, `/static/public.css`, `/static/fonts/*`, `/static/icon.svg` | Public project links and the stylesheet, fonts and icon of their page. Visitors have no account; the secret token in the URL (and an optional password) protects the links; the static files contain no data. |
| `/api/v1/*` **with** `Authorization: Bearer abk_...` | REST API. Scripts have a token, not a login cookie. Only let requests with an Kalmido token past the login, and send them to the app port where the proxy header is not trusted (see [docs/API.md](docs/API.md#behind-a-reverse-proxy) for nginx and Traefik). |

Example for Caddy with Authelia (single sign-on). The `route` keeps the order: first strip any client-sent
`Remote-*` headers, then let `forward_auth` set the real ones:

```caddyfile
tasks.example.com {
	route {
		request_header -Remote-User
		request_header -Remote-Groups
		request_header -Remote-Email
		request_header -Remote-Name
		# REST API with a personal access token: no login, and to port 3040 where the Remote-User header is never trusted
		@kalmido_api {
			path /api/v1/*
			header_regexp Authorization ^Bearer\s+abk_[A-Za-z0-9_-]{20,}$
		}
		reverse_proxy @kalmido_api 127.0.0.1:3040
		# calendar apps (CalDAV): user name + app password, checked by Kalmido
		@kalmido_dav path /dav /dav/* /.well-known/caldav /.well-known/caldav/*
		reverse_proxy @kalmido_dav 127.0.0.1:3040
		@gated not path /manifest.json /static/icon-192.png /static/icon-512.png /static/badge-96.png /static/shortcuts/* /drop /drop/drop /ical/* /s/* /static/public.css /static/fonts/* /static/icon.svg
		forward_auth @gated authelia:9091 {
			uri /api/authz/forward-auth
			copy_headers Remote-User Remote-Groups Remote-Email Remote-Name
		}
		reverse_proxy 127.0.0.1:3040
	}
}
```

With `AUTH_PROXY_PORT` (see *Login*) the last line points at the proxy port instead (`127.0.0.1:3045` or wherever you
published it), while the API line keeps using the app port. With the built-in login a plain
`reverse_proxy 127.0.0.1:3040` is enough.

</details>
<details>
<summary><a id="configuration"></a><b>Configuration</b></summary>

All settings are environment variables in `.env` (see [.env.example](.env.example)); [docs/ENV.md](docs/ENV.md) lists every variable the server reads with its default (2.149, generated from the code). Switches accept `1`/`true`/`yes`/`on` and `0`/`false`/`no`/`off`.

| Variable | Default | Purpose |
|---|---|---|
| `TZ` | `Europe/Berlin` | Time zone for due dates and reminders |
| `PUBLIC_URL` | `http://localhost:3040` | Your address, used in notification links |
| `NTFY_URL` | `https://ntfy.sh` | ntfy server for push notifications (see *Notifications*) |
| `NTFY_TOPIC` | random | Topic of the first admin; every other user gets a random one (editable by admins) |
| `NTFY_TOKEN` | | Access token for a protected ntfy server |
| `AUTH_PROXY_HEADER` | | Header with the user name from an authenticating proxy (e.g. `Remote-User`); empty = built-in login only |
| `AUTH_TRUSTED_PROXIES` | | Comma list of IPs / CIDRs whose header is trusted (direct peer) |
| `AUTH_PROXY_PORT` | | Extra container port; if set, the header is only trusted on it (see *Login*) |
| `KALMIDO_TRUSTED_PROXIES` | `127.0.0.1,::1` | Reverse proxies (IPs / CIDRs of the direct peer) whose `X-Forwarded-For` / `-Proto` / `-Host` are believed: the real client address for login lockouts, logs and alerts, https for cookies and CalDAV. The `AUTH_TRUSTED_PROXIES` peers count too; `none` = trust nobody. A proxy in another container on its own Docker network arrives from that network's gateway (e.g. `172.18.0.1`): add it. 2.79.0: the docker bridge gateway `172.17.0.1` is no longer in the default; a proxy on the host in front of a port published on Docker's default bridge needs `127.0.0.1,::1,172.17.0.1` |
| `KALMIDO_IP_WARN_ACCOUNTS` | `3` | 2.33.0 (#834): warn in the log and under *Administration > Server* when at least this many accounts sign in from one private address within 7 days (the client addresses do not arrive: check the reverse proxy, see docs/SELF-HOSTING.md); only private addresses are kept, 14 days |
| `KALMIDO_NOTIF_TEMPLATE` | `read` | 2.33.0 (#927): the notification template a newly shared project or folder starts with: `read` (mentions, assignments, direct replies), `work`, `all` |
| `KALMIDO_TRUSTED_PROXY_COUNT` | `1` | Proxies in a row in front of Kalmido; the client is the entry that many places from the right in `X-Forwarded-For` |
| `AUTH_BOOTSTRAP_USER`, `AUTH_BOOTSTRAP_NAME`, `AUTH_BOOTSTRAP_PROXY_LOGIN` | `admin` | Account that receives the data when upgrading from the single-user version |
| `AUTH_SESSION_DAYS` | `30` | Lifetime of a "stay logged in" session |
| `TASKS_DROP_TOKEN` | | Becomes the first admin's `/drop` token (every user has an own one, see *Share from your phone*) |
| `NTFY_INBOX_URL`, `NTFY_INBOX_TOKEN`, `NTFY_INBOX_TOPIC` | | Optional share inbox: each message on this ntfy topic becomes an inbox task. The topic must be access-controlled (see *Share from your phone*) |
| `NTFY_INBOX_USER` | first admin | Username whose inbox receives the share inbox (2.142.0: everyone can also set an own share inbox under *Settings > Notifications*; this variable stays the fallback) |
| `NTFY_INBOX_PUBLIC` | | Public ntfy URL, if attachment links use a different address than `NTFY_INBOX_URL` |
| `KALMIDO_SECRET_KEY` | | 2.1.0: 32 random bytes, base64 (`openssl rand -base64 32`). Encrypts (2.2.0) repository tokens and webhook secrets; without it none can be stored. Keep a copy outside the server: losing it means everyone enters their tokens again. Never in the database or backups. 2.42.0: also wraps the per-organisation keys (encryption at rest); without it or an organisation's recovery key, encrypted office data and files are lost. 2.64.0: also the account keys of the private files (no recovery key: keep it safe; `orgcrypt_cli rewrap-accounts` after a planned change) |
| `KALMIDO_SECRET_FILE` | `/secret/kalmido.key` (docker-compose.yml) | 2.45.0: without `KALMIDO_SECRET_KEY` the key is read from this file; a missing file is created once (32 random bytes, base64, mode 0600). Must not lie inside the data or backup folder (refused: a backup would carry the key). Keep a copy |
| `KALMIDO_SETUP_CODE` | | 2.45.0: empty = while no account exists the server prints a one-time setup code into its log and the setup page asks for it. **Only for tests and automation:** a fixed code, or `off` (no code: whoever opens the page first becomes the admin) |
| `TASKS_MAX_FILE_MB` | `50` | Maximum size per attachment (task and comment files) |
| `KALMIDO_IMPORT_MAX_MB`, `KALMIDO_IMPORT_MAX_TASKS` | `20`, `20000` | Limits of one import (*Moving from other apps*) |
| `KALMIDO_IMPORT_RATE` | `30` | Imports and previews per user within 10 minutes |
| `KALMIDO_PDF_MEM_MB`, `KALMIDO_PDF_PARALLEL`, `KALMIDO_PDF_TIMEOUT_S` | `512`, `2`, `20` | 2.34.0: reading the text of a PDF (agents' *read attachment*, the briefing field) runs in its own process: its memory limit in MB, how many PDFs are read at the same time (small servers: `1`) and the seconds one PDF may take |
| `TASKS_PUSH_GAP` | `60` | Seconds in which further comments / changes on a task are bundled into one summary push |
| `TASKS_NEWS_DAYS` | `90` | Days a News item is kept |
| `TASKS_NEWS_MAX` | `500` | News items kept per user (newest) |
| `KALMIDO_UPDATE_CHECK` | `1` | `0` turns the update check off completely (see *Updating*) |
| `KALMIDO_MAIL_ADDRESS` | | 2.17.0: the address new tasks are sent to (plus addresses `local+token@domain` are the personal / project addresses) |
| `KALMIDO_IMAP_HOST`, `KALMIDO_IMAP_PORT`, `KALMIDO_IMAP_SSL`, `KALMIDO_IMAP_USER`, `KALMIDO_IMAP_PASSWORD`, `KALMIDO_IMAP_FOLDER`, `KALMIDO_IMAP_INTERVAL` | `993`, `1`, `INBOX`, `60` | The mailbox Kalmido polls for new tasks (unread mails; deleted after a complete import, `KALMIDO_IMAP_KEEP=1` only marks them read) |
| `KALMIDO_MAIL_AUTHSERV_ID` | *(empty)* | 2.86: the hub takes a mail from a person's own address as forwarded (the original sender picks the client) only when the receiving mail server confirmed that domain (DKIM / DMARC / SPF pass in its `Authentication-Results`); set its authserv-id (the first word of that header, e.g. `mx.example.com`) to read only its header, empty = the topmost one. Without the proof the mail stays *Not assigned* |
| `KALMIDO_SMTP_HOST`, `KALMIDO_SMTP_PORT`, `KALMIDO_SMTP_TLS`, `KALMIDO_SMTP_INSECURE`, `KALMIDO_SMTP_USER`, `KALMIDO_SMTP_PASSWORD`, `KALMIDO_MAIL_FROM` | `587`, `starttls` | Sending the daily summary by e-mail (`TLS`: `starttls`, `ssl` or `none`) |
| `KALMIDO_IOS_SHORTCUT_URL` | empty | Link to a signed generic iOS shortcut for *Share from your phone* (asks for address and token on import); empty = the button is hidden |
| `KALMIDO_INSTANCE_MODE` | *(empty)* | 2.46.0: only `shared` (no organisations, people see only their own contacts) is still read; everything else, `organisation` included, means organisations + private spaces (2.23.0-2.45: `organisation` / `workspaces`) |
| `KALMIDO_ORG_NAME` | *(empty)* | the name of the organisation the first-run setup creates (else asked once in the setup); 2.46.0: never renames an existing one |
| `KALMIDO_STORAGE_QUOTA_MB` | `0` | 2.24.0: storage per person in MB (0 = unlimited); admins can change it in *Administration > Server* |
| `KALMIDO_UPLOAD_HOURLY_MB` | `1024` | Uploads per person and hour in MB (0 = off); above it a clear 429 message |
| `KALMIDO_SUPPORT_EMAIL` | *(empty)* | 2.24.0: where *Contact support* writes to when storage is full (else the admin setting, else the first admin's address) |
| `KALMIDO_HOSTED` | `0` | 2.24.0: `1` = a server run as a service for others: integrations only reach public HTTPS addresses |
| `KALMIDO_AI_BASE_URL` | *(empty)* | 2.75.0: base URL of an OpenAI-compatible chat API (`…/v1`) for the built-in assistant; empty = no assistant (no menu entry, routes 404) |
| `KALMIDO_AI_MODEL` | *(empty)* | 2.75.0: model name sent to that API (required together with the URL) |
| `KALMIDO_AI_KEY_FILE` | *(empty)* | 2.75.0: file with the API key (one line); `KALMIDO_AI_KEY` sets it directly; Ollama needs none. Never logged or shown |
| `KALMIDO_AI_NAME` | *(host of the URL)* | 2.75.0: provider name people see when they share projects with the assistant |
| `KALMIDO_AI_TIMEOUT_S` | `60` | 2.75.0: time limit of one model call; `KALMIDO_AI_MAX_CHARS` (`24000`) caps the input, `KALMIDO_AI_MAX_TOKENS` (`1500`) the answer |
| `KALMIDO_ONBOARDING` | `1` | `0`: new accounts start empty (no "Getting started" project, no welcome tour) |
| `KALMIDO_SEARCH_INDEX` | `0` | 2.29.0: search engines stay out by default (`X-Robots-Tag: noindex, nofollow` on every answer, `/robots.txt` with `Disallow: /`); `1` lets them index the sign-in page. Public project links, forms, feeds and the API stay noindex either way |
| `KALMIDO_AGENT_EVENTS_STALE_H` | `48` | 2.29.0: agent events older than this many hours reach a poller as one `missed` summary instead of one by one (`0` = off; see docs/AGENTS.md) |
| `KALMIDO_CHANNELS` | `1` | 2.142.0 (#2145): `0` turns the Slack / Matrix / Telegram / Signal channels off |
| `KALMIDO_CHANNEL_FAILS` | `5` | Failed sends in a row after which a channel switches itself off |
| `KALMIDO_TELEGRAM_API` | `https://api.telegram.org` | Base address for Telegram channels (a local Bot API server) |
| `KALMIDO_EVENT_MAIL_DELAY`, `KALMIDO_EVENT_MAIL_GAP` | `600`, `600` | 2.142.0 (#2146): seconds an assignment / mention mail waits to collect more, and the least time between two such mails to one person |
| `KALMIDO_WEBPUSH` | `1` | `0` turns Web Push off (no key handed out, no new devices, everything goes to ntfy) |
| `KALMIDO_VAPID_SUBJECT` | `PUBLIC_URL` | Contact the push services see in the VAPID signature: `mailto:you@example.com` or an https URL (Apple needs one of the two; without an https `PUBLIC_URL` the default is `mailto:admin@example.com`) |
| `KALMIDO_WEBPUSH_HOSTS` | | Extra push services, comma list: `host`, `*.domain` or an exact origin `https://host:port` (only this form allows plain `http://`, e.g. for tests) |
| `KALMIDO_ADMIN_ALERTS` | `1` | `0` turns the admin alerts off completely (see *Notifications > Admin alerts*) |
| `KALMIDO_ADMIN_TOPIC` | | One fixed ntfy topic for all admin alerts (instead of each admin's own topic; the setting in the app is then read-only) |
| `KALMIDO_ADMIN_ALERT_WINDOW` | `3600` | Seconds over which counted events (failed logins, skipped watchdog rows, removed devices) are summed up into one alert |
| `KALMIDO_CALENDARS` | `1` | `0` turns calendar subscriptions off (no fetching, no events, the settings say so) |
| `KALMIDO_GIT_POLL` | `180` | 2.2.0: seconds between two checks of a connected repository (see *Git integration*) |
| `KALMIDO_TENANT_CHECK_HOUR` | `3` | 2.30.0 (#1036): hour of the nightly workspace boundary check (memberships across organisations / private; admin alert when the count changes) |
| `KALMIDO_TIDY_QUIET_S` | `120` | 2.27.0: seconds a new task must be left alone before its agent gets the `tidy` event (and nobody may have it open in a field); `0` = at once |
| `KALMIDO_AUDIT_DAYS` | `90` | 2.2.1: days the agents' activity log is kept (see *AI agents*); `0` = no log |
| `KALMIDO_CALENDAR_ALLOW_HOSTS` | | Internal hosts calendar subscriptions may reach, comma list of `host` or `host:port` (in addition to the project under *Settings > Administration > Advanced*) |
| `KALMIDO_CALENDAR_MAX_MB` | `10` | Largest calendar download (ICS file or CalDAV answer) in MB |
| `KALMIDO_CALENDAR_MAX_EVENTS` | `5000` | Occurrences kept per calendar (the ones closest to today) |
| `KALMIDO_CALENDAR_RATE` | `30` | Calendar adds, discoveries and manual refreshes per user within 15 minutes |
| `KALMIDO_BACKUPS` | `1` | `0` turns automatic backups and restore off completely (see *Backups and restore*) |
| `KALMIDO_BACKUP_DIR` | `backups/` next to the database | Folder for the backup archives |
| `KALMIDO_BACKUP_PASSPHRASE` | | Passphrase for encrypted backups (instead of setting it in the app; the app then shows it as set) |
| `KALMIDO_BACKUP_MAX_MB` | `4096` | Largest backup a restore accepts (upload size and unpacked total) |
| `KALMIDO_WEBAUTHN_RP_ID` | host of the page | Passkeys: relying party ID, e.g. `example.com` to use passkeys on several subdomains |
| `KALMIDO_WEBAUTHN_ORIGINS` | | Passkeys: extra origins (comma list, e.g. `https://tasks.example.net`) besides `PUBLIC_URL` |
| `KALMIDO_OIDC_ISSUER`, `KALMIDO_OIDC_CLIENT_ID`, `KALMIDO_OIDC_CLIENT_SECRET` | | OpenID Connect login (see *Login > OpenID Connect*); issuer + client id turn it on. 2.9.0: also settable in *Settings > Administration > Sign-in*; a set variable wins per field |
| `KALMIDO_OIDC_ADMIN_DOMAINS` | | Comma list of e-mail domains: a verified e-mail of one of them makes the person an admin (like `KALMIDO_OIDC_ADMIN_GROUP`) |
| `KALMIDO_OIDC_SCOPES` | `openid profile email` | Scopes requested from the provider |
| `KALMIDO_OIDC_USERNAME_CLAIM`, `KALMIDO_OIDC_GROUPS_CLAIM` | `preferred_username`, `groups` | Claims for the user name and the groups |
| `KALMIDO_OIDC_REQUIRED_GROUP`, `KALMIDO_OIDC_ADMIN_GROUP` | | Only members of this group may log in; members of this one are admins |
| `KALMIDO_OIDC_BUTTON_LABEL` | `OpenID Connect` | Text on the login button ("Log in with ...") |
| `KALMIDO_OIDC_ALLOW_HOSTS` | | Internal hosts the OIDC requests may reach (`host` or `host:port`), e.g. a provider in your LAN |
| `KALMIDO_CALDAV` | `1` | `0` turns CalDAV off (`/dav` and `/.well-known/caldav` answer 404, no new app passwords) |
| `KALMIDO_CALDAV_DONE_DAYS` | `90` | Days completed tasks stay in the calendar apps |
| `KALMIDO_CALDAV_HTTP` | `0` | `1` allows CalDAV logins while `PUBLIC_URL` is plain `http://` (only inside a trusted network: the app password is sent with every request) |
| `KALMIDO_API` | `1` | `0` turns the REST API off (every `/api/v1` request answers 404, no new tokens) |
| `KALMIDO_API_RATE` | `120` | API requests per token and minute |
| `KALMIDO_WEBHOOKS` | `1` | `0` turns webhooks off (nothing is queued or sent) |
| `KALMIDO_WEBHOOK_ALLOW_HOSTS` | | Internal hosts webhooks may reach (`host` or `host:port`, comma list), in addition to *Allowed internal hosts* in the app; only these may use `http://` |
| `KALMIDO_PUBLIC_LINKS` | `1` | `0` turns public project links off for good (the admin switch in the app is then off and locked) |
| `KALMIDO_PUBLIC_RATE` | `60` | Public link page views per client address and minute |
| `KALMIDO_PUBLIC_BURST` | `300` | Views of one public link within 10 minutes that trigger an admin alert |
| `KALMIDO_IMAGE` | `kalmido:local` | Image for `docker compose`; set `ghcr.io/gegenschuss/kalmido:<version>` to use the prebuilt one |

Everything else (language, reminder defaults, digest time, pomodoro lengths, which modules are shown) is set per user in the app under *Settings*; the switches for the whole server (collaboration, time tracking, public links, update check, sign-in policy, OIDC, backups, admin alerts, allowed internal hosts) are under *Settings > Administration > Whole server*.

</details>
<details>
<summary><a id="language"></a><b>Language</b></summary>

Kalmido starts in **English**. Open *Settings > General > Language* (in German: *Einstellungen > Allgemein > Sprache*) to switch; **Deutsch**
is included. The choice is stored per user on the server, so it applies to all your devices and also to your push
notifications (reminders, focus end, habit reminders, daily digest) and server messages.

Each language other than English is one JSON file in [`static/i18n/`](static/i18n/) that is picked up
automatically. Want Kalmido in your language? [TRANSLATING.md](TRANSLATING.md) explains how to add one in a few
steps (copy `de.json`, translate, run `python3 tools/i18n_check.py`, open a pull request).

Quick add always understands English and German; with French, Spanish, Italian or Dutch chosen here it also understands
that language (2.12.0). Priority, tags and the project are symbols in every language (`!!!` / `!!` / `!`, `#tag`, `~list`):

| | English | German |
|---|---|---|
| Dates | `today`, `tomorrow`, `day after tomorrow`, `friday`, `next monday`, `in 3 days`, `in 2 weeks`, `next week`, `weekend`, `12.10.` | `heute`, `morgen`, `übermorgen`, `freitag`, `nächsten montag`, `in 3 tagen`, `nächste woche`, `wochenende` |
| Times | `3pm`, `at 9:30am`, `15:00`, `at 15:00` | `15 uhr`, `um 9:30` |
| Repeat | `daily`, `every day`, `weekdays`, `weekly`, `every monday`, `every 2 weeks`, `monthly`, `yearly` | `täglich`, `werktags`, `wöchentlich`, `jeden montag`, `alle 2 wochen`, `monatlich`, `jährlich` |
| Priority | `!high`, `!medium`, `!low` (or `!!!`, `!!`, `!`) | `!hoch`, `!mittel`, `!niedrig` |
| Tag, project | `#tag`, `~list`, `in list Work`, `… in Work` at the end (only an exact project name) | `#tag`, `~liste`, `in Liste Arbeit`, `… in Arbeit` am Ende (nur ein genauer Listenname) |

| | French | Spanish | Italian | Dutch |
|---|---|---|---|---|
| Dates | `aujourd'hui`, `demain`, `après-demain`, `vendredi`, `lundi prochain`, `dans 3 jours`, `la semaine prochaine`, `3/10` | `hoy`, `mañana`, `pasado mañana`, `viernes`, `el próximo lunes`, `en 3 días`, `la próxima semana`, `3/10` | `oggi`, `domani`, `dopodomani`, `venerdì`, `lunedì prossimo`, `tra 3 giorni`, `la settimana prossima`, `3/10` | `vandaag`, `morgen`, `overmorgen`, `vrijdag`, `volgende maandag`, `over 3 dagen`, `volgende week`, `3/10` |
| Times | `15h`, `à 9h30` | `a las 15`, `a las 9:30` | `alle 15`, `alle 9:30` | `15 uur`, `om 9:30` |
| Repeat | `tous les jours`, `en semaine`, `chaque semaine`, `chaque lundi`, `toutes les 2 semaines`, `chaque mois`, `chaque année` | `todos los días`, `entre semana`, `cada semana`, `cada lunes`, `cada 2 semanas`, `cada mes`, `cada año` | `ogni giorno`, `nei giorni feriali`, `ogni settimana`, `ogni lunedì`, `ogni 2 settimane`, `ogni mese`, `ogni anno` | `dagelijks`, `elke werkdag`, `wekelijks`, `elke maandag`, `elke 2 weken`, `maandelijks`, `jaarlijks` |

Dates with a slash (`3/10`, `3/10/27`) are day / month in every language, like the dotted `3.10.`.

Task titles, project names, tags and notes are never translated.

</details>
<details>
<summary><a id="notifications"></a><b>Notifications</b></summary>

Kalmido has two ways to reach you. Pick one per account under *Settings > Notifications > Channel*:

| Channel | What it needs | |
|---|---|---|
| **Web Push** (default) | nothing extra: the browser or the installed app shows the notifications | turn it on per device |
| **ntfy** | the [ntfy](https://ntfy.sh) app and a topic | one topic for all your devices |
| **Both** | both of the above | every push twice |

**Web Push**, on every device that should ring:

1. Open Kalmido (on a phone: installed to the home screen is best), *Settings > Notifications*.
2. Tick *Notify on this device* and allow notifications when the browser asks.
3. Press *Send test to this device*.

Works in Chrome, Edge, Samsung Internet, Opera and Firefox on Android and the desktop, and in Safari on macOS 13+.
**iPhone and iPad:** only in the app added to the Home Screen (iOS / iPadOS 16.4 or newer): in Safari *Share > Add to
Home Screen*, open Kalmido from there, then turn it on as above. The settings show a hint when this is missing.
The project below the switch shows all your devices; remove one there (logging out removes the current device too).

As long as none of your devices is subscribed (or none of them accepts a push, e.g. after a browser reset), the pushes
go to your ntfy topic instead, so switching from ntfy loses nothing: *Settings > Notifications* says "No device
subscribed yet — using ntfy for now" until the first device is on.

Reminders carry two buttons: *Done* completes the task right from the notification (with your login session; if it
expired, the app opens and completes it), *Snooze* opens the snooze options. Comment and mention pushes carry *Reply*
(opens the task with the comment box ready) and *Done*. Tapping a notification opens the task,
project or view it is about. Several pushes about the same task replace each other instead of piling up.

**ntfy:**

1. Install the ntfy app ([Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy), [iOS](https://apps.apple.com/app/ntfy/id1625396347)).
2. Open Kalmido > *Settings > Notifications*: your topic is shown there (every user has an own one). Subscribe to it in the ntfy app.
3. Press *Send test* next to the topic.

On ntfy.sh anyone who knows the topic name can read it, so keep it random or run your own ntfy server with a token.

Besides reminders, focus end, habit reminders and the daily digest, Kalmido pushes new comments, @mentions,
assignments and completions in shared projects (see *Comments and activity*; off with the *Collaboration* module), and
the time tracking reminders (timer still running, stopped automatically). Every kind goes over your channel.

**How urgent** (*Settings > Notifications*): *Normal* (ntfy 3), *Loud* (ntfy 4, the default) or *Urgent* (ntfy 5), used by both
channels (ntfy priority; Web Push: *High* and *Urgent* are sent with `Urgency: high`, *Urgent* notifications also stay
on screen until you dismiss them). Two kinds never go out below *High*, even when you choose *Normal*: reminders of
tasks with priority *high*, and the notice that a forgotten timer was stopped automatically.

**Privacy of Web Push:** the notification text is end-to-end encrypted on your server (RFC 8291) with the keys of
your browser; the push service in between (Google FCM for Chrome / Edge on Android and most Chromium browsers,
Mozilla for Firefox, Apple for Safari and iOS, Microsoft WNS for Edge on Windows) only sees that a message of a
certain size goes to a certain device at a certain time, never its content. The payload holds only what the
notification shows (title, text, the in-app link, the buttons). Your server signs each push with its own VAPID key,
created on the first start and stored in the database; the private half never leaves the server. The server only
sends to https endpoints of those services (`fcm.googleapis.com`, `*.push.services.mozilla.com`,
`web.push.apple.com` / `*.push.apple.com`, `*.notify.windows.com`); add others with `KALMIDO_WEBPUSH_HOSTS`.
Delivery goes through the push service, so it also reaches a phone that cannot reach your server at that moment
(a server only reachable at home or over a VPN); only opening the task needs the server.

### Admin alerts

Things that need an admin's eye go to the admins over their own notification channel (2.5.2). With the public
`ntfy.sh` (the default `NTFY_URL`) nothing goes there unless someone chose it: an admin on *Web Push* (the default) gets
the alerts on their subscribed devices, and none at all until they subscribe a device under *Settings > Notifications*
(the alerts are then only listed in the settings); the channels *ntfy* / *Both* send them to the admin's own topic. With
your own ntfy server (`NTFY_URL` elsewhere) each admin's own topic gets them whatever channel they use, as before.
*Settings > Administration > Whole server > Admin alerts* shows where they go per admin and can set one shared admin
topic instead (or `KALMIDO_ADMIN_TOPIC` fixes it), the priority (default *High*, 4) and *Send test alert* (labelled
"Kalmido test alert").
Regular users never get them. Each alert comes in the admin's language.

| Kind (each can be switched off) | When |
|---|---|
| Update available | the update check found a new release (once per version) |
| Web Push delivery | a device was removed because its push service refused it (404 / 410, or 4xx five times in a row), or pushes fell back to ntfy although the user has devices |
| Watchdog errors | rows the background job had to skip (e.g. a reminder with a broken value), summed up per hour with their ids |
| Integration problems | the ntfy share inbox was refused (guessable topic) or cannot reach its server for more than 15 minutes, five ntfy or Web Push deliveries in a row failed |
| Security events | five or more failed logins within an hour and every login rate-limit trip (per user / IP), bursts of invalid `/drop` or calendar feed tokens, a new admin, a changed server switch (collaboration, time tracking, update check, admin alerts, admin topic) |
| Storage and health | less than 5 % or 1 GB free on the data volume, data page checksum failures reported by PostgreSQL (daily check), the attachment folder not writable |

Alerts only carry counts, ids, usernames, device labels, IP addresses and error classes, never task titles,
comments, project names or file names; login names that do not exist are shown as `?` (it could be a password typed
into the wrong field). Against floods: an identical alert (same kind and subject) goes out at most once per 6 hours
(the project counts the repeats), at most 10 alerts per hour (the rest is only listed), or everything in one *daily
summary* at a time you choose. All limits and thresholds are under *Limits and thresholds*. The last 50 alerts are
listed below the settings with their state (delivered, not delivered, waiting for the summary, hourly limit
reached) and can be cleared. The background job (watchdog) sends them, so they need `TASKS_WATCHDOG` on (default).

</details>
<details>
<summary><a id="share-from-your-phone"></a><b>Share from your phone</b></summary>

*Settings > Integrations > Share from your phone*. Every share becomes a task in *your* inbox, files attached; it goes
to `POST /drop` with your personal upload token (with a login proxy, let `/drop` pass, see above). Chrome passes no
files to installed web apps via the share sheet (links and text work with *Share > Kalmido*), hence these helpers:

**Android: HTTP Shortcuts** (several files per share)
1. *Download HTTP Shortcuts import*: a ZIP made for you (the server address + `/drop`, your token, the Kalmido icon).
2. Install [HTTP Shortcuts](https://http-shortcuts.rmy.ch), then *menu > Import / Export > Import from file* and pick the ZIP.
3. Share from any app to HTTP Shortcuts > *Kalmido* (photos and files, also several) or *Kalmido text* (links and text;
   the first line becomes the title, a link the task's link).

The ZIP contains your token: keep it like a password (*New token* next to the token, or *Settings > Account > Advanced >
Upload token > New token*, invalidates it; then download the ZIP again and update the iPhone shortcut).

**iPhone / iPad: Shortcuts app.** Copy the server address (without `/drop`) and the token with the buttons in the
same place and follow the guide there (*Get Contents of URL* to the address + `/drop`, method `POST`, header
`Authorization: Bearer <token>`, form field `file` or `text`, *Show in Share Sheet*). If your server has a signed
generic shortcut (`KALMIDO_IOS_SHORTCUT_URL`), an *Add the Kalmido shortcut* button appears; it asks for the server
address (without `/drop`, it adds that itself) and the token on import.

**ntfy** (one file per share): set the `NTFY_INBOX_*` variables, then share to the ntfy app on that topic.

> [!IMPORTANT]
> Everything published to the inbox topic becomes a task in that user's inbox, so the topic must be
> access-controlled: use your own ntfy server with access control (a read token for Kalmido, write access only for
> you), or at least an unguessable topic name. Kalmido refuses to start the inbox on the public `ntfy.sh` with a short
> or the default topic name (`inbox`). Attachments are only downloaded when their URL points to your ntfy server
> (`NTFY_INBOX_URL` or `NTFY_INBOX_PUBLIC`); the inbox token is never sent anywhere else.

</details>
<details>
<summary><a id="tech"></a><b>Tech</b></summary>

Python (Flask, waitress, python-dateutil, cryptography for Web Push, the stored secrets, backup encryption and the OIDC token checks, icalendar and recurring-ical-events for calendar subscriptions, py_webauthn for passkeys, segno for the QR code of the authenticator app, Pillow for profile photos) and PostgreSQL 17 (psycopg) on the server, plain JavaScript in the browser (`static/js/`, translation helpers in `i18n.js`, translations in `static/i18n/*.json`): no build step, no framework. How the code is organised: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). The browser makes no external requests (website links are never fetched, no favicons, no CDN); the server only contacts services you configure, plus the optional update check against GitHub. Icons from [Lucide](https://lucide.dev).

### Logo variants

| File | Use |
|---|---|
| `static/icon.svg` | The app icon: the Kalmido bot (two eyes, an antenna) on the petrol tile |
| `static/logo-white.svg` | The white bot, transparent, for dark backgrounds |
| `static/icon-light.svg` | White tile, dark bot |
| `static/favicon.svg` | Favicon without a tile: the bot is dark in a light browser and white in a dark one |

</details>
<details>
<summary><a id="limits"></a><b>Limits</b></summary>

One Kalmido instance is built for one person, a household or a small team. Many separate groups run best as one instance each, not as thousands of accounts on a single instance.

- **Tasks:** every device loads all open tasks plus the last 14 days of completed ones (and a year of habit
  history) in one request and re-renders from it. A few thousand open tasks per user feel instant; around
  10,000 open tasks the payload reaches several megabytes and rendering slows down, especially on phones.
  Completed tasks older than 14 days are not loaded, so a long history costs nothing.
- **Users:** devices poll for changes every few seconds, and any change makes every active device reload its
  state. That is fine for a handful of people; with more than roughly 20 to 30 users active at the same time
  it becomes wasteful.
- **Database:** PostgreSQL handles hundreds of thousands of tasks without trouble, with a connection pool (up to 56
  connections, `KALMIDO_DB_POOL_MAX`). Attachments are stored as files, not in the database.

If you run into these limits, the next steps would be per-user change tracking, sending only changes
instead of the full state, and rendering long lists incrementally. Issues and pull requests are welcome.

</details>
<details>
<summary><a id="how-this-was-built"></a><b>How this was built</b></summary>

Kalmido is built with AI assistance (Claude Code). The owner decides what it does, uses it every day, and every
change runs the automated test suite (API, UI, security regression tests) in CI. Before 1.0.0 an independent AI
security review (separate agent, black-box + code review) was run and all findings were fixed and re-verified;
automated scanners (bandit, pip-audit, semgrep, OWASP ZAP baseline) run too. There has been no independent human
security audit yet — reviews and reports are welcome ([SECURITY.md](SECURITY.md)).

</details>
<details>
<summary><a id="contributing-and-contact"></a><b>Contributing and contact</b></summary>

Issues, translations and pull requests are welcome, see [CONTRIBUTING.md](CONTRIBUTING.md) and
[tests/README.md](tests/README.md). Pull requests need a one-time agreement to the [CLA](CLA.md) (you keep your copyright; the
project stays AGPL-3.0). A red test suite stops a release; a suite proven flaky is skipped for at most 14 days while its fix is open (`tests/skip.txt`). Security problems: please report them privately, see [SECURITY.md](SECURITY.md).
Contact: hello@kalmido.com.

</details>
<details>
<summary><a id="supporter-licence"></a><b>Supporter licence</b></summary>

Kalmido is free and stays free. If you want to support it, there is a voluntary one-time supporter licence: 25 EUR per
person or 100 EUR per server, VAT included, no subscription. It unlocks nothing - every feature is in the free app - and
shows a small badge under *Settings > Help > About*, where you also enter the key. The key is checked offline on your
server. Purchases will run through a merchant of record with its buyer terms (refund within 14 days); until the shop is
open the dialog shows only the prices. Hosted servers do not show the licence at all.

</details>

## License

[GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0); the copyright notice is in [NOTICE](NOTICE), the licence text in [LICENSE](LICENSE). You may use, change and host Kalmido freely, also for
your company or clients. If you offer a modified version to others over a network, you must make the source code of
your changes available to those users under the same license.
Third-party notices: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

© 2026 Gegenschuss Doberenz Enders Grund eGbR · Product owner: Moritz Grund
