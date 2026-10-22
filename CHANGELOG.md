# Changelog

All notable changes to Kalmido are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Kalmido uses
[semantic versioning](https://semver.org/): every published change gets at least a new patch version, new features a
minor one, anything that needs action on your side a major one.

## [2.165.10] - 2026-10-22

### Fixed
- Agent chat on phones: the header shows the workspace name too (shortened if needed), not only the colour dot (#2681).

## [2.165.9] - 2026-10-22

Package 2.174.0 (agent chat: bubbles in the agent's colour).

### Changed
- Agent chat: the agent's messages are tinted in its own colour (lighter in the light theme, stronger in the dark one);
  job messages take the job's colour, part jobs a lighter tone; the stripe on the left of job messages is gone, the
  label "Job #N" stays. Your own messages, comments and notifications stay as they were (#2681).
- The colour bar on top of the agent chat is gone; the header shows the agent's workspace by name with a small colour
  dot instead (only with organisations; on a narrow phone only the dot) - in the chat window and the full view (#2681).

## [2.165.8] - 2026-10-22

### Fixed
- CI of 2.165.6: an unused variable in the knowledge desk view and the head bar motion rules written so the reduced-motion check finds them; folded with a task open below 1140 px the menu button is back to open the sidebar; the workspace switch shows its keyboard focus ring (#2619, #2620).

## [2.165.7] - 2026-10-22

Package 2.171.0 (module counts with the parts of the areas).

### Fixed
- Settings > Modules: the counts ("x of y modules on", per group) go by the single modules, an area by its parts (Home:
  home & life, family, budget, feeds ...), so switching off Feeds and Budget no longer shows "22 of 22"; *Switch on all
  modules* is on only while every module really is on, switching it on turns on every part too; an area's switch shows
  *partly on* (half) while only some of its parts are on (#2676).

## [2.165.6] - 2026-10-22

Package 2.152.3 (desktop navigation: one head bar over everything, folders and tables in the panel, app icon).

### Changed
- Computer: one low head bar over the area bar, the panel and the page with the brand, the workspace switcher, the
  search ("Search, create, ask …"), the bell and the account. The workspace menu lists Private and every company with
  its own sign, a tick on the current one, *Add a company* and *Company settings*. The brand left the panel; the page
  head keeps only the page's title and buttons. The phone stays as it was (#2619).
- Panel head: the area's name with *Fold all* / *Unfold all* (panels with groups) and *Hide the panel*; a hidden panel
  leaves only the area bar, the choice is kept on this device (#2619).
- Tables: the panel lists the tables of the current workspace (grouped by project, shared with me), a click opens the
  table directly; *All tables* and *New table* on top. The cell details on the right stay (#2619).
- Knowledge: the folders sit in the panel (subfolders load when opened), a folder opens as a page list with its path on
  top; the tree column is gone on a computer, search, *New page* and the area menu moved into the page head (#2620).
- File store: the folders sit in the panel under *Files* (subfolders load when opened), dropping files on a folder in
  the panel moves or uploads them; the tree column is gone on a computer (#2621).

### Fixed
- App icon: the antenna is white, so the icon stays recognisable on the dark tile of macOS 26's dark icon style
  (re-add the web app to see the new icon) (#2667).

## [2.165.5] - 2026-10-22

### Fixed
- CI fix of 2.165.4: the backup test tries the statement check again after a Postgres deadlock with the starting server, and the v1 … p290 suites run in the short last CI shard (shard 1 ran into its 45 min limit) (#2622).

## [2.165.4] - 2026-10-22

### Fixed
- CI fix of 2.165.3: below 1140 px with the sidebar folded and a task open the bar of the areas steps aside, so the task panel keeps its width and the page title stays readable (#2622); three timing-sensitive tests wait for slow runners.

## [2.165.3] - 2026-10-22

### Fixed
- CI fix of 2.165.1 / 2.165.2: the time export as Excel names the column Project like the CSV, the report status page and its mails address customers formally in German (#2650), a folded sidebar with the task panel open keeps the page title readable around 900-1100 px (#2622), tests follow the new wording (#2624 #2629 #2630 #2631 #2647 #2651 #2655 #2656 #2657).

## [2.165.2] - 2026-10-22

Package 2.152.4 (wording run: one word per thing in the German interface).

### Changed
- German interface: the terms decided on 2026-10-21 are used everywhere: *Eingang* for the inbox (#2634), *Mir zugewiesen*
  (#2635), *Modul*, *Bereich*, *Gruppe* and *Arbeitsbereich* each for one thing and *Zuhause* for the home area (#2636,
  #2637), *das Tag* (#2638), ticket words only in software projects and the type *Wunsch* (#2639), *Tagesüberblick* and
  *Journal* (#2640), the bell level *Laut* and *Erinnerung wiederholen* (#2641), *teilen* for sharing, *Freigabe* only for
  approvals, *Abnahme* for customers (#2642), *verschlüsselt* (#2643), *Zeit messen* and *Fokus-Runden* (#2644).
- Office (German): *Anfragen*, *Liquidität*, *Kennzahlen*, *Abos & Software*, *Geräte* (#2645), *Schreiben & Verträge*,
  *Belege & Nummern*, *Angebote und Rechnungen* (#2646), *Adressbuch* and a new customer text (#2647), *Kundenverträge*
  (#2648), *Beispieldatei*, *Vorlage* only for letter and document templates (#2649); everything customers and people
  without an account see uses the formal *Sie* (#2650); a quotation is printed as *Angebot*, *Kostenvoranschlag* only with
  the film industry pack (new documents; existing numbers stay) (#2651); the document field is *Betreff* (#2652);
  *Einkauf* and *Marge*, *USt* in the app, *MwSt.* on print (#2653).
- Agents, accounts and links (German): *Eingebauter Assistent* and *Auftrag* for an agent's work (#2654), *Person*,
  *Konto* and *Mitglied* each for one thing, spelled-out admin roles and the settings section *Verwaltung* (#2655),
  *Öffentlicher Link* and *Ausschalten* (#2656), notification channels are *Weiterleitungen* (#2657),
  *Nachrichtenquellen*, *Arbeitsanleitung*, *Unterstützer-Lizenz*, *Sicherung* (#2658).
- Wording fixes from the UI review in tasks, calendar and sidebar (#2629), office, time and tables (#2630), knowledge,
  files, agents, settings and sign-in (#2631): no English leftovers or technical names, *Min.* / *Std.*, *Zeitstrahl*,
  *Prüfung*, *Frist*, *Besitzer*, *Nur lesen*; English source texts use typographic apostrophes.
- Agent chat: only a job's long messages fold (*Show less*); your own and the main agent's long messages always stay
  whole (#2659).

Stored values, API and MCP field names are unchanged.

## [2.165.1] - 2026-10-22

Package 2.152.2 (sidebar B, project instead of list, chat header).

### Changed
- Sidebar on a computer: a narrow bar with the areas (Tasks, Calendar, Office, Time, Review, Home, File store, …) and
  next to it one panel with the content of the chosen area. A click on an icon switches panel and page together; every
  area reopens the page used last on this device. Settings and the account sit at the bottom of the bar. The phone
  stays as it was (#2622).
- Tasks panel: search and Plan (Inbox, Today …) stay on top, *Views* (timeline, matrix, *All projects*) sit between
  Plan and the projects; the calendar is an icon of its own (#2622).
- Office on a computer: no second column any more; the panel shows *Sell*, *Money* and *Administration*, each group
  folds on its own and is remembered per device (#2617). Time, Review, Home and File store show their parts in the
  panel instead of tabs on top (#2618).
- Every list is now called a **project** (in all languages, help texts and the agent descriptions; the API keeps
  `list`). The type "project" became the switch *Progress and status* in the project dialog (ring, status, project
  page, *All projects*); existing projects keep it on. The inbox stays the inbox (#2624).
- Chat header: only search and the menu stay visible; filter, *Fold long messages* and *Always show steps* are entries
  of the menu, a dot on the menu shows an active filter (#2627).

### Fixed
- The office menu shows the same points on every page (it showed 10 or 17 depending on what was loaded) (#2632).
- The line under the brand ("All workspaces") is no longer cut in the phone drawer (#2660).

## [2.165.0] - 2026-10-22

Package 2.165 (bot figure: greeting, errors / offline, pull to refresh).

### Added
- The very first start greets once: on the first card of the welcome tour the bot pops up, waves and says hello by first
  name; a restarted tour shows the calm figure (#2612).
- An error answer or the loss of the connection startles the bot figures on screen for a moment (an empty view, the
  brand's bot in the sidebar, the start error page), at most every five seconds (#2613).
- Phones: pull to refresh shows the bot instead of the turning arrow; it looks up once pulled far enough and hops while
  the refresh runs (#2614).
- With the system setting *reduce motion* nothing of this moves; the greeting stays as text (#2612 #2613 #2614).

## [2.161.3] - 2026-10-22

Follow-ups to 2.153.0 (correspondence, receipt list) and the organisation import.

### Fixed
- Organisation import: the ids inside the task and list history are mapped to the new ones (unknown ones dropped), undoing an import also removes the document settings it created, and a failed import into the private space removes the personal office it made while that stayed empty (#2399).
- Correspondence: the signature picture goes through the virus scan like every upload; the letter PDF date uses the server clock consistently (#2028).
- An incoming e-invoice dated in a locked month stays an ordinary document instead of becoming a receipt; the check also works in the document worker (#2055).

## [2.161.2] - 2026-10-21

Package 2.152.1 (small fixes: navigation, News number).

### Changed
- Sidebar: the Kalmido brand (bot icon + word mark) is back on top and is the workspace switch; the shown workspace stands
  under it (dot + name). Its menu also offers *Start* and *Hide the sidebar*; the small mark at the bottom is gone (#2607).
- The bot figure stays alive: empty views keep a calm loop (a blink, a glance), the brand's bot blinks now and then;
  nothing moves with the system setting *reduce motion* (#2608).
- The bot nods once when the last open task of Today or of a list is ticked off (#2609), works in the agent chat instead
  of the typing dots (#2610) and next to the progress of long jobs (ZIP / contacts import, bank statement, organisation
  export, task import) (#2611).
- Office: *Documents* follows *Quotes & invoices* in the menu; on a computer the office opens on the point used last on
  this device, else the pipeline (admins) or quotes & invoices (#2616).

### Fixed
- The News number in the menu, the sidebar, the tab bar and the app badge is the same as the bell's ("For you" + direct
  messages); activity only counts at its tab in the News view (#2626).
- Dialogs: the resize grip only shows where the content can grow (text field, editor, list, preview), not on short
  confirmations (#2615).

### Security
- pypdf 6.21.2 (was 6.20.1): fixes CVE-2026-113786 (unchecked JPEG image data in PDF files).

## [2.161.0] - 2026-10-21

Bundle of the packages 2.152.0 (deletion rules and legal retention), 2.153.0 (correspondence, job chat, document fields, receipt list), 2.154.0 (documents: stack scans, task links, Peppol, privacy sheets), 2.155.0 (calendar: answers, rules, absences, availability, year), 2.156.0 (lists and views), 2.157.0 (project agents, job chat) and 2.161.0 (small interface fixes).

### Added
- Office: new area *Correspondence* - letters to authorities, insurers and others after DIN 5008 with letterhead, signature (optional signature picture), channel, status and tracking number; recipients from clients or the address book; the PDF is filed with the client. Letters and filed documents link both ways (*Answer to*, *Write answer*), the thread per contact and topic shows the history, a deadline in an incoming letter becomes a task, a follow-up date creates a task when no answer comes (#2028).
- Correspondence: send a letter by e-mail with its PDF; the answer arrives through the documents address and is linked to the letter automatically (#2029). Text blocks per office (also without an organisation) are inserted at the cursor (#2030).
- Agents: *Let an agent draft the answer* at a document (only agents the document is shared with); event `letter_draft_requested`, API v1 and MCP `create_letter_draft` create drafts only - a person checks, signs and sends (#2031).
- *Write answer* also takes the address from an address-book contact when the sender is no client; a company card wins over single persons of the company (#2229).
- Documents: custom fields per workspace (text, number, amount, date, checkbox, choice, link), nothing preset; organisation admins define them, in the private space the person; values are encrypted like the text, searchable, move along between workspaces; the Paperless import takes custom fields as real fields; agents read and fill existing fields (#2179).
- Agents: every job has its own chat - start line, progress lines and messages of the job; *Open job chat* under each job card; questions show under the card; messages typed there carry the job (#1962).
- Bookkeeping: *All receipts* across all months with filters (period, paid / open, receipt or payment date, category, supplier, project, without VAT rate, search) and totals; export exactly the filtered receipts as CSV or as ZIP with the original files for the tax advisor, behind the country pack switch of the export (#2055).
- Incoming e-invoices in an office's documents become a receipt on the first read (own invoices not, credit notes negative) (#2055).
- Documents: a stack scan with several archive numbers (or separator sheets) is marked *Stack - split?* and splits into single documents after a preview with movable cuts; blank back pages can be left out; one undo step brings the stack back. A separator sheet to print is in the documents' settings (#1111).
- Documents: a document can be linked with an existing task (and unlinked); the task shows *Document: <name>* to everyone who may see the document (#1111).
- Office: the receipt sheet shows the open suggestions of agents (accept / reject, with undo) and "Suggested by …, confirmed by …" (#1356).
- Office: e-invoices over the Peppol network through your own Peppol access point provider account (set up in the office settings, off by default): Peppol ID for the office and clients with format and check digit test and a suggestion from the VAT ID, receiver check, status sent / delivered / rejected, protection against double sending; UBL download (Peppol BIS Billing 3.0, XRechnung UBL), checked in CI with KoSIT and the OpenPeppol rules (#1960).
- Office: data protection sheets for a client - data processing agreement, privacy information and consent as samples (sample text, no legal advice); a PDF in the client's folder, sent by mail with a link to sign, signed back by the link, by upload or by a reply mail with a tag in the subject (a person confirms); status per sheet and a data protection filter in the client list (#2192).
- Office: when a calculation part is added, the industry pack can be chosen (only switched-on packs; with one pack nothing changes); existing parts keep theirs (#1876).
- Calendar on the phone: invitations in the calendar *Invitations* can be accepted, answered with *Maybe* or declined in the phone's calendar app (CalDAV); only your own answer is taken, deleting an invitation there declines it (#2074).
- Calendar on the phone: a calendar created in the phone's calendar app becomes a Kalmido calendar with its name and colour (MKCALENDAR) (#2079).
- Events: *Own …* in *Repeat* opens a small rule dialog - every N days / weeks / months / years, weekdays to tap, *on the 15th* or *on the 2nd Tuesday* / *the last Friday* (#2075).
- Calendar: a year view with twelve small months; days with events or due tasks are tinted, a tap opens the day, a month name the month (#2078).
- Calendar: public holidays (German state or Austria, chosen per person or by the organisation) and your absences show in all views; the team's absences on request, as "away" only; switches in *Calendars*. Absences and holidays as a subscription link for the phone (#2076).
- Events: while inviting, a free / busy bar for you and every invited person of your organisation - busy and away times only, never titles (#2077).
- Mind map: *Add ideas…* (key `I`) asks an agent the list is shared with for sub-branches; they appear as faint branches you take over one by one or all at once, or drop. The agent only gets the list name and the branch path; Kalmido itself calls no language model (#1201).
- Mind map: *Show properties* (key `E`) puts priority, due date, person, repeat, subtask progress, tags and list fields under each branch - the same choice as the task row; off, the selected branch still shows them; the export takes the current state along (#1948).
- List fields: new kinds multiple choice, currency, rating (stars) and a link to another task; only people who may see the linked task see its title (#2069).
- Formula fields use the functions of the sheets: `IF`/`WENN`, `SUM`/`SUMME`, `ROUND`/`RUNDEN`, `MIN`, `MAX`, `AVERAGE`, `COUNT` and comparisons; a failed calculation (division by 0) shows a short text in the field (#2070).
- Lists have a calendar view: month, week, day and agenda with only the list's tasks; dragging onto a day sets the date, a new entry on a day lands in the list (#2071).
- *My tasks* as a board: columns by due date, priority or list; dragging changes exactly that; the choice is the same on every device (#2072).
- Section templates: save the sections of a list (private or for the organisation) and add the missing ones to another list; nothing is deleted (#2073).
- Sidebar views: a view remembers which groups are open and which entries are visible, optionally a start page; each view is a tile above the favourites, hidden entries wait under *Others (N)*, a second tap on the active tile goes back to *Everything*; views and the active view are per person and the same on every device (#2186).
- Trash periods for the file store, hub mails, tables, pipeline deals, invoice series, chat and comments (`KALMIDO_TRASH_DAYS`, 30 days); every run only counts until the retention switch is on; *Admin > Retention* shows the numbers (#2165).
- Logbook: months close after 7 days or by hand; a closed drive is corrected with a reason, the change log is visible in the dialog and the exports (#2169).
- Newsletter: unsubscriptions and bounces survive deleting or merging a contact (suppression list as a hash), with a consent log (#2170).
- Agent chat: delete one of your messages or the whole history with an agent for good (#2175).

### Changed
- Correspondence is for office admins (and the person in the private office); the accounting role does not see letters.
- Moving a private office into an organisation keeps an existing letter signature there and unlinks letters from private documents (named in the preview).
- Writing into a job's chat needs the right to stop that job, like the job's message button.
- Office: duplicating an invoice made from times asks first and the copy says "Copy of …: the hours of that invoice are already billed" while it is a draft (#2567).
- Tasks and the mind map have up to five levels instead of three; on phones each level indents less; imports flatten anything deeper into level five (#1949).
- Folded sections stay folded on all your devices (#2073).
- Admin > Organisation > *Edit organisation*: an admin of the organisation uploads or removes the organisation's own picture right next to the symbol (as in Settings > Workspaces); the emoji stays the fallback without a picture. Server admins who do not administer the organisation see a hint instead (#2594).
- Deleting an organisation shows what goes with it. Self-hosting: an organisation or personal office with records the law keeps is retired (read only, export by the instance admins, deleted after the period). Hosted instance: nothing is kept for others - retention export or waiver, then it is deleted (#2167, #2164).
- Office: booked receipts, DATEV / billed travel receipts and edited archive imports cannot be deleted; payments of finalised invoices are reversed instead of deleted; a client in use is archived (#2168).
- Clean-up of old logs, sessions, expired tokens, invitations and setup codes (`KALMIDO_LOG_DAYS`) (#2171).
- Backups: safety backups have an age limit, weekly backups at most 52, daily rotation, a journal of deleted accounts that a restore applies again; list headers, table files, team chat files and bookmark pictures are in the backup (#2172).
- Files: failed deletions are retried, an orphan sweep, at most 20 file versions, import undo removes its files (#2173).
- Foreign keys for task, list and person references; orphans are cleaned at the start (#2174).

### Fixed
- Agent setup on a Mac over SSH (nobody logged in at the screen): the agent now starts in the background right away and at the next screen login, instead of the setup stopping with "launchctl could not load" (#1517).
- Agent setup: when a setup stops half-way, the autostart file it wrote is removed too, so launchd / systemd no longer try to start a deleted folder (#1517).
- Agent starter: when the launcher is killed hard, its event runner ends as well, so the restarted launcher takes over and an uninstall leaves nothing running (#1517).
- Agent starter: after *Remove computer* (or deleting the agent) the launcher stops the agent with one log line and waits quietly, instead of logging "Kalmido not reachable" every minute and restarting again and again; Mac/Linux and Windows (#1517).

### Security
- Security fix: deletion of accounts and organisations (personal office, files, agents, direct messages) (#2164, #2167).

### Note
- A rollback to 2.147.1 is not recommended: it knows neither logbook corrections nor payment reversals (corrected drives would count twice, the original of a reversed payment could be deleted again).

## [2.151.1] - 2026-10-21

### Security
- pypdf 6.20.1 (was 6.19.0): fixes CVE-2026-113792, CVE-2026-113793, CVE-2026-113794 and CVE-2026-113795 in reading PDF files
  (attachments, receipts, incoming e-invoices).

## [2.151.0] - 2026-10-21

Bundle of the packages 2.148.0 (DATEV Unternehmen online replaced: locked periods, receipt images with the DATEV batch, export for the tax auditor, procedure documentation, DATEV import), 2.148.1 (security release: findings of the follow-up audit), 2.149.0 (clean-up: architecture and maintainability) and 2.151.0 (a task knows its build state).

### Action needed (self-hosting)
- `docker-compose.yml` now starts the optional services through `COMPOSE_PROFILES` in `.env` (`localdb` = the PostgreSQL container, `clamav` = virus scan) instead of "delete the block". The installer / `update.sh` adds the line once; if you update by hand (git or prebuilt image), add `COMPOSE_PROFILES=localdb,clamav` (or only what you use) to `.env`. Needs Docker Compose 2.20 or newer (#2510).
- A new installation no longer starts without a server key (`KALMIDO_SECRET_KEY` or a key file on its own volume, the image uses `/secret/kalmido.key` when `/secret` is mounted); existing installations keep the warning. Tests and demos: `KALMIDO_NO_SECRET_KEY=1` (#2510).

### Added
- Git integration: a task in a list with a repository shows its build state at the top of *Code* - *In version …* (the first version tag that holds its commits or merged pull request), *In main, not released yet* or *Built, not in main yet* with the branch and how far it is ahead; commit rows show their version or branch (#2558).
- Git integration: the list's version field (*Package*, *Version*, *Release*, *Target version*, or picked in the repository dialog) is checked against the tags; an open task whose version is already released gets a hint at the task and a mark in its row (#2558).
- Agents: `build` at every task of a list with a repository and the MCP tool `list_build_status` (`GET /api/v1/lists/{id}/build-status`) (#2558).
- Agent rules: the task list is the truth for tickets and releases - done only when the code is in main and released, the rest gets a new version, no work ends on an unmerged branch, `list_build_status` before every "done" report; in the rules, the template, the in-app rules and the setup guide (#2560).
- Every signed-in answer carries a `Server-Timing` header (app time, database time, statement count); requests slower than `KALMIDO_SLOW_REQUEST_MS` (default 500) leave a log line without user data; *Admin > Server* health shows p50 / p95 / max of the last 1000 requests (#2504).
- Downgrade guard: the database remembers the newest Kalmido version that ran on it. An older minor version refuses to start (one step back, e.g. the automatic rollback after a failed update, still works); restoring a backup made by a newer minor version is refused. Emergency switch `KALMIDO_ALLOW_DOWNGRADE=1` (#2509).
- `docs/ENV.md` lists every environment variable the server reads, generated from one register (`kalmido/core/env.py`); the CI checks that nothing undocumented is read. Switches understand `1/true/yes/on` and `0/false/no/off` everywhere, also `TASKS_WATCHDOG` (#2511).
- Clear start errors when `/data` is not writable; the installer waits patiently for long first migrations (#2510).
- Office: **lock periods (GoBD)** per month in the bookkeeping, in order and for good (the dialog asks to type the month). In a locked month the server refuses every change of booking data dated there - invoices, payments, bank matches, receipts, cash entries, trips, imports and agents' payment suggestions; corrections go into an open month. Each lock is in the office log (#2471).
- Office: **export for the tax auditor** - one ZIP with bookings, invoices, positions, payments, receipts, cash book, clients, opening balances and the office log as CSV, described in index.xml (GDPdU description standard) (#2471).
- Office: the **DATEV export with receipt images** - the booking batch plus a receipt archive in the format of the DATEV XML interface (document.xml): invoice PDFs and receipt files, every booking line linked by its Beleglink; a check lists receipts without a booking and bookings without a receipt; "only locked months" marks the batch as fixed (#2470).
- Office: a prefilled **procedure documentation** (Verfahrensdokumentation) in the GoBD outline from the office settings; gaps are marked, every save is a version, export as Markdown or PDF (#2472).
- Office: **DATEV import** of the tax advisor's files - debtors become clients (only empty fields of existing ones are filled), creditors become suppliers whose creditor account the DATEV batch then uses, opening balances from a booking batch; preview first, undo per run (#2458).

### Changed
- Faster start: scripts and styles carry a content hash and stay in the browser cache; static files are served without a session lookup; twelve start files of modules (time sheets, team tabs, sprints, mail filing, other servers, household budget, list print, event invitations, project time, environments, day plan, repository editor) load when first used (#2505, #2518).
- Updates only fetch the changed files into the offline store instead of the whole app (#2506).
- The 4-second sync check needs one database query instead of about ten; team chat counters are read in bulk; access rights are cached briefly per process and every membership change still takes effect at once; deltas for list participants (#2507, #2508).
- New indexes for the done list, due dates, the calendar range and the search (same hits as before); the background watchdog reads all settings in one query and writes nothing while idle (#2515, #2516).
- Office: agent drafts (offer, change, invoice, reminder) appear in the office log like a person's; header and item changes no longer run in parallel with finalising or sending; undoing a project proposal deletes the offer only for admins and only if nothing was made from it; recurring invoices send the `invoice.created` webhook. Invoice from an offer stays possible from any status on the web (#2235); agents still need an accepted offer (#2521).
- Office: a payment proposal by an agent above the open amount is refused (409) instead of being flagged (#2521).
- Office: document words come from the language files instead of inline texts; German and English documents read exactly as before (#2520).
- New lists without a chosen workspace go to your only organisation, with several organisations to the private space instead of the first one.
- `GET /api/v1/export` with a personal token needs the scope `account`.

### Fixed
- Start files no longer call functions of modules that are not loaded yet without a guard (a fresh device could hit a script error, e.g. the design command in the command bar); five CSS variables that were used but never defined (#2519).

### Security
- Security fix: office writes (lock checks on every path, shared period lock).
- Security fix: exports (formula guard in CSV cells, file names in archives).
- Security fix: organisation membership - an existing account joins an organisation only after accepting the invitation (news with Join / Later / Decline); invitation answers no longer differ by account, organisation admins never get an invitation link (#2480 #2486).
- Security fix: organisation boundary - data leaves an organisation (lists, files, sheets, contacts, saved chat messages) only through an organisation admin, logged and announced to the other admins; organisation admins act on shared lists only; closed channels are opened only by their members (#2483 #2491 #2480).
- Security fix: public links and deploy webhooks of a list are reset when its owner changes (#2478).
- Security fix: account deletion - accounts with finalised invoices or a cash book in the personal office are kept (retention), clients with finalised documents stay (#2479 #2484).
- Security fix: encryption tooling covers all protected tables; deleting an organisation never writes its files in clear (#2481 #2487).
- Security fix: backups include team chat, sheet, list header and bookmark files; a restore removes nothing it does not know (#2482).
- Security fix: retention and privacy - client approvals stay when a video review is deleted, approval logs without contact data, push fallback over the public ntfy server only with a neutral text, failed sign-ins without the typed name, a fuller account export (#2493 #2494).
- Security fix: account import scans every file and imports other people's comments by name only (#2492).
- Security fix: resource limits for imports, sheets, mail fetch, booking page, Karakeep and PDF reading (#2485).
- Security fix: filed e-mails in the file store follow the mail's visibility, also through shared file links (#2488).
- Security fix: the assistant takes only your own lists; the embedding service needs https or an internal address (#2489).
- Security fix: agent actions on events, public forms, address books and deploy approvals wait for a person (#2495).
- Security fix: mentions and error messages name no accounts you cannot see (#2490); hardening across office uploads, numbering, webhooks, imports and time sheets (#2496).

### Maintenance
- The server knows the test clock (`KALMIDO_TEST_NOW`, only in test containers with `KALMIDO_TEST=1`); suites with night / Sunday failures run at a fixed time of day (#2512).
- `tests/kt.py` (check, sess, until, fresh); shorter rate-limit and burst windows in tests instead of waiting a minute (about 10 min less per CI run) (#2513).
- `run_all.sh` writes `timings.csv` (CI artefact), `tools/shards.py` shows a measured shard split, a CI rerun repeats only the failed groups (#2514).
- Layers: basic types in `core/errors.py` / `core/ctx.py` / `api/common.py` (old imports keep working), `tools/check_layers.py` counts function-local imports against `tools/layers_budget.json` (may only go down), 514 needless local imports pulled up, shared office / time / ICS helpers (#2517).

## [2.147.2] - 2026-10-21

Bundle of the packages 2.144.5 to 2.144.11, 2.147.2 and #2603 (leftovers, office fixes: time to the invoice, invoice from a quotation, test-phase deletion, office PDF numbers, trial documents, cash book; phone-test fixes of 2.143). The version number is set when it is pushed.

### Added
- Time entries are billable or not (default billable). "Invoice from time" takes only open billable hours and binds them to the draft as billed; the same hours never land on two invoices, billed entries are locked (only the note stays editable). Deleting the draft frees them again; on a cancelled invoice the office admin frees them with "Release the time again". Works the same in a personal office without an organisation (#2053).
- Office: trial documents. Creating a quotation or an invoice offers *Just to try*: such a document gets its own number series (TEST-001, ...), a large SAMPLE watermark (MUSTER in German) on every page and never an e-invoice; real number series stay gapless. Invoices, credit notes, reminders, delivery notes and documents made from a trial document are trial documents too. They never go into bookkeeping, VAT returns, DATEV and accounting exports, cash flow, reports, dunning, bank matching, the cash book, recurring invoices, the client portal or webhooks. An admin (a person without an organisation in their private space) deletes them at any time - one by one or all at once - and billed receipts and trip items become free again. The list marks them *Trial* and filters by them; the first quotation and the first invoice of an office area point to the trial mode once (#2576).
- Office (test phase): an admin can delete a finalised or sent invoice after typing its number; credit notes and reminders of it, payments and bank matches go with it, billed time is free again, cash book entries only on request; the number stays a gap in the office log (#2603).

### Changed
- Approval cards in comments are decided only by the list's managers, the assignee or an admin; others see who decides (#2001).
- Import target: with the sidebar on "All", imported tasks go to Private, with "Rather into <organisation>" as the other choice; the calendar import offers "Rather into Private" also without a private calendar and creates one when needed (#2002).
- Time: the sum in the list header shows members only their own hours, as the time window does; owners and admins see everyone's (#1523).
- Subscriptions & tools: a missed notice period shows the next chance, sorts by it and reminds of it; invoice series without an own name are named without placeholders like {month} (#2021).
- Phone: the full-screen search closes with a soft animation (#1560).
- Office, cash book: the change log keeps its lines even if an entry were ever removed by a maintenance tool (GoBD); lists and checks decrypt only the entries they show, so large cash books stay fast (#2354).
- Office, test phase: an admin can delete a quotation also after it was sent, answered or signed by the client (the confirmation says so); only one an invoice or a document was made from stays, and "Undo finalising" keeps the old rule. This is taken back before the launch (#2573, #2574).

### Fixed
- Sheets on the phone: the suggestions after "=" stay above the keyboard and never cover the field, the cell editor stays inside the screen, the side panel shows the right button right after "Freeze value" / "Live again" (#2011).
- CalDAV: a calendar app that never sends attendees no longer removes the attendees and their answers when it saves an event; capabilities are learned only after the version check (#2379).
- The workspace mailbox moves along with the organisation export / move and the account export (server, user, sender; passwords never) and stays switched off until the passwords are entered again; the tenancy check knows it (#2410).
- "Delete all times" recognises billed entries by the invoice position's list, also after a rename and in the personal office; list formulas have a fixed depth limit (#1523).
- Test p2400_e_ui waits for all saved settings (#2026).
- Legacy import: raising the invoice counter asks for a reason like the number ranges (GoBD); the reason is in the office log (#2400).
- Legacy import: undo puts the order of the services back (#2400).
- List rules: asking for an approval (or for changes) no longer counts as "assigned", the task stays with the approver (#2400).
- Legacy import: archiving the rest of an undone import leaves entries you restored by hand alone (#2400).
- Office settings > Data: one section "Transfer into an organisation" with both ways (a new organisation or an existing one) instead of two wordings (#2436).
- Office, cash book: after a failed load the tab offers *Try again* instead of keeping the error until the page is reloaded; the receipt hint "in the cash book" follows the office switch like every cash book view (#2354).
- Read-only role: the office opens straight away again (it stayed on *Loading…* when opened directly or after a reload) (#2500).
- Read-only role: an organisation-wide list no longer offers *Join* (it would bring no writing) but says the role is read-only; a list you may only read has no + button, and a typed task says you can only read it instead of silently doing nothing (#2500).
- Organisation settings on phones: the role picker is 44 px high and shows *Read-only* in full; *What the roles mean* shows the list when opened (#2501).
- Off-site backup on Android: a tapped field scrolls above the keyboard; the S3 field *Region* has its own label (was "Bundesland / Region" in German) (#2501).
- Pages trash: long page names wrap instead of being cut (#2501).
- Office: *Create invoice* is a visible button on every quotation (the main button once accepted, before that it asks once) and is in the row menu of the quotation list; it left the editor's "…" menu (#2572).
- Office PDF: an empty block of the number scheme (no project, client or initials) takes its separator along - `KV02-M` instead of `-KV02-M`, no double hyphens; numbers given before stay as they are; the rights page and the part pages of an invoice say "Rechnung Nr." instead of "Angebot Nr."; an invoice made from a quotation names it in its head ("zu Angebot Nr. …" with its date); part pages show the row "+ Optional …" before the total with the option; the part's name is one source - renaming it in *Parts* or on the title page changes both, printed as typed (#2575).

### Security
- Recovery key of accounts without a password (single sign-on): showing or renewing it needs a real new sign-in at the provider (prompt=login, max_age=0, a fresh auth_time from the ID token), bound to the organisation and the purpose; a link alone triggers nothing. The key-rotation test switch only works in test mode, a refused shortcut download says why, the settings hint at the incomplete search during a key rotation (#2387).

## [2.147.1] - 2026-10-21

Drag tasks into the chats as references; overdue invoices suggest a payment reminder and carry a GiroCode; moving many documents shows progress; agents show their workspace; small bell fixes.

### Added
- Chats: tasks, lists, contacts and events can be dragged into the team chat, a thread or an agent chat; they go in as a reference (`#123` or a link card) at the cursor. Several selected tasks at once give one reference each; phones and tablets get *Insert reference* in the chat input row (#2523).
- Office: an invoice overdue for more than the grace days (default 7) gets a suggested payment reminder as a draft per client - nothing is sent, a task and a hint in the list point to it; switchable in the office settings (#2054).
- Office: invoices and reminders in EUR carry a GiroCode (EPC QR code) next to the bank details, so banking apps fill in the transfer; switchable, documents finalised earlier stay as they were (#2054).

### Changed
- Moving many documents to another workspace goes in batches with a progress bar "x of n moved"; smaller moves show *Moving…* on the button; undo still takes back everything at once (#2230).
- Agents carry the colour of their workspace as a thin stripe in the sidebar, the window bar and the Agents view; chat header and input keep the agent's own colour (#2231).
- Bell: unread approvals an agent waits for count in the bell and in *For you* (#2405).

### Fixed
- Bell: the section of read news is called "Gelesen" in German (was "Lesen") (#2405, #2420).
- Organisation card: the member count leaves agent accounts out, like the members dialog (#2420).
- Agent chat on Android: the coloured line on top of the input shows again (#2411, #2502).

## [2.147.0] - 2026-10-21

The country pack decides which office functions exist, single ones can be switched off, and an international base pack
lets offices outside Germany work without German assumptions.

### Added
- The country pack lists the office functions it offers (DATEV, e-invoices, VAT return figures, tax dates, export for the tax advisor, finalising rules); menus, settings, buttons and the server follow it. Offices from before stay as they were: Germany, everything on (#2459).
- *Office > Settings > Functions*: one switch per function. Off only hides - nothing is deleted, the DATEV address and settings stay, switching on brings everything back; finalised documents and retention periods stay in force. Admins only, in a personal office its owner (#2460).
- International base pack: own VAT rates, EN 16931 e-invoices (ZUGFeRD / Factur-X), retention set by the office, texts without country assumptions; the export for any tax advisor (booking list as CSV, with invoices and receipts as ZIP) in every pack. docs/PACKS.md: how the community builds a country pack (#2461).
- A new office asks for its country once (suggestion from the company country or the language); changing it later says first what is hidden and that finalised invoices keep their state (#2462).
- Agents: `get_office` names the country pack and the functions as switched on.

## [2.146.0] - 2026-10-21

Imports from everyday life: e-invoices are received and read, duplicates are found, several files and ZIPs go in at once, and a retention export comes before deleting an account or organisation.

### Added
- E-invoices received: XRechnung (UBL / CII) as .xml in the mail inbox, the document upload and the receipt button; the XML inside ZUGFeRD / Factur-X PDFs is read too. Supplier, number, dates, net / VAT per rate, gross, currency and IBAN come from the XML instead of text recognition; a readable view prints or saves the invoice as PDF (#2451).
- Receipts: the same file is not stored twice ("This file exists already" with a link); the same invoice (supplier + number, or supplier + amount + date) is marked "Possibly a duplicate" and left out of the DATEV export unless chosen (#2452).
- Receipts: several files at once, ZIP files and winmail.dat are unpacked (also in the mail inbox), several photos can be joined into one receipt (#2453).
- Household import: a debit/credit column (S/H, Soll/Haben, D/C, -/+) with a Volksbank / Raiffeisenbank preset, several files or a ZIP, a whole import can be taken back, duplicates without the title (day + amount + counterpart IBAN), the date formats DD-MM-YYYY and YYYYMMDD, more than 3000 rows (#2455).
- Legacy import: client addresses from separate columns (company, street, postcode, town, country), found by the header or chosen by hand; CSV files are read, old .xls files get a clear hint (#2456).
- Contacts: several vCard files at once or one ZIP (e.g. Google Takeout), duplicates and limits as in the single import (#2457).
- Retention export before deleting an account or an organisation: a readable ZIP with invoices (incl. e-invoices), receipts with their files, cash books, bank statements and the office log, with a table of contents and checksums. Deleting needs a finished export or an explicit waiver, both logged; the hint says: invoices and receipts 8 years, books 10 years (#2468).

### Fixed
- Bank import (office and household): CAMT.052 pending entries (status PDNG) are shown apart and never imported; the same booking in several reports is found by its reference (AcctSvcrRef / EndToEndId), also when it came first as pending; the dialog recommends CAMT.053 (#2469).
- iPhone photos in HEIC format are read (text recognition, preview) (#2454).

### Security
- Security fix: file uploads, ZIP and XML reading, retention export.

## [2.145.0] - 2026-10-21

Own windows open faster, the list CSV has more columns, the printable project starts with a project head, the sidebar shows the Kalmido mark.

### Added
- List CSV export: new columns at the end - start date, deadline, duration, tracked time (hours with the decimal comma of the language), created by, completed by, milestone, sprint and the checklist (checkbox lines of the notes and the subtasks) in one cell; comments and attachments stay out (#2431).
- Printable list / PDF of a project begins with a compact project head: description, status with its note, time span and progress, members with role, milestones with date and state; empty parts are left out, plain lists show only their name (#2432).
- Sidebar: a small Kalmido logo with the word mark at the bottom under *Settings*, a tap opens Start (#2437).
- News: when unread items for you lie in another workspace, the view says how many and where, with *Switch* (the bell keeps counting all workspaces) (#2444).

### Changed
- Own windows (list, task, chat) take the state of the open main window and catch up in the background: usable in about 0.5 s instead of 0.8 s on the test machine, more over slow connections (#2424).
- The logo has the fixed brand colours of the app icon (lilac plate) everywhere, independent of the accent colour (#2433).

### Fixed
- Sidebar: the workspace head sits on the line of the page title (phone with notch, desktop), the colour stripe stays flush (#2438).
- Team chat: a message that arrived in the first seconds after opening a conversation shows at once instead of with the next change.
- List CSV: open tasks are called "Offen" in German again (was "Öffnen").

## [2.144.2] - 2026-10-21

Small fixes and UI polish: subtasks appear at once, touch targets of at least 44 px in office and settings dialogs, Android print view and office search focus.

### Fixed
- Subtasks typed quickly one after another appear at once and in order, without a reload per entry (#2467); the office search (services, equipment, text blocks, contracts) keeps the focus on Android (#1644).
- Sheets: print / PDF on Android shows the print view instead of the app (#2370); cash flow: "Take over as actual" sits in its own bar under the table, reachable above the phone tab bar (#2372).
- Calendar: a confirmed draft no longer shows Draft + Confirm in its popup (#1811); vacation approved / rejected comes with Undo, the vacation accounts stay open after a save, "Use this device" shows right after a time zone change (#2375).
- Touch targets of at least 44 px in the channel dialog, the receipt sheet, the cash book, the bill-on dialog and the work week (#2447 #2352 #2375); the channel kind is labelled "Type" (#2448); the receipt sheet keeps its account line after Undo (#2352).
- Reply to a stored mail: the cursor starts above the quote (#2441); the setup dialog starts without an error when the modules fit no purpose (#2369); the folder share icon on the phone stays in the lists' column (#1730); the read-receipt label is tied to its box (#2435).

## [2.144.1] - 2026-10-21

Office fixes: the office side bar stays put on touch tablets, the bank import says which file to take and reads several statements or a ZIP at once.

### Added
- Bank reconciliation: several statements or one ZIP file (CAMT XML / CSV inside) in one import - one shared preview sorted by date, the same booking in a daily and a monthly statement counts once, the balances of every statement are kept (the newest is the current one), one undo step for all (#2450).
- The import window explains which file to export from online banking: CAMT.053 (XML) with booked transactions recommended, CSV possible, not pending transactions / CAMT.052 or MT940/MT942 (an MT940 file gets a clear message); files can also be dropped into the window. The cash flow opens the same import next to the bank balance (#2446).

### Fixed
- Touch tablets: the office side bar is a real column, only the page next to it scrolls; the scroll position stays when the page redraws (#2445).

### Security
- Security fix: bank statement upload.

## [2.144.0] - 2026-10-20

Agent chat with a stop button, agent colours and a quieter filter; the home block Today shows today's events; lists grouped by a custom field; groundwork for hosting (operator interface) and supporter licence prices.

### Added
- Agent chat: stop a running answer - a stop button next to Send while the agent works for you; Esc stops always, Ctrl+C stops when no text is selected (on a Mac always, plus Cmd+.). New agent event `abort` (`POST /api/agents/{id}/abort`), the agent confirms with `POST /api/v1/agent/aborted` or the MCP tool `confirm_abort`; the reference launcher ends the running command (#2412).
- Agent chat: one icon in the header folds long messages for all at once (remembered per device); a message you unfold stays open, search and reply quotes unfold their target (#2417).
- Agent chat: the header and the composer carry the agent's colour, so two agent chats are easy to tell apart (#2411).
- Home: the block Today lists today's events above the tasks (switch "Show events" in the block settings); the header counts running jobs ("1 agent working (10 jobs)") and names overdue tasks of another workspace (#2418).
- Lists: group a list by a custom text or choice field, one collapsible group per value, for all members; sections stay as they are. `PATCH /api/v1/lists/{id}` and the MCP tool `update_list` set `sort_mode` and `group_field` (#2414).
- Hosting: optional operator interface for a hoster's console (`KALMIDO_OPERATOR_TOKEN_FILE`, off by default) - numbers only (version, health, people, organisations, storage, backup), a one-time setup code for the first admin (valid 24 h) and the maintenance notice, never any content (#797).
- Supporter licence: the dialog shows the prices (person 25 EUR, server 100 EUR, once, VAT included); a purchase link only when switched on (#2158).

### Fixed
- Agent chat: the filter "Only me and ..." no longer shows job results with buttons; open approvals waiting for you stay visible; "Jobs" shows only job cards and their messages (#2416).
- Agent chat: the filter is the icon in the chat header on every width, the filter row above the messages is gone (#2419).
- Agent chat: a job card whose only message is the final result shows it below the card, its unfolding is remembered (#2365).

## [2.143.0] - 2026-10-20

Organisation roles, off-site backups, a stronger offline app, sharing any file to Kalmido, the pages trash emptied for good.

### Added
- Organisations: three more roles besides member and admin - **read-only** (sees what members see, changes nothing; team chat stays open), **guest** (sees only what is shared with them personally) and **accounting** (reads and exports the office, uploads receipts). Admins pick the role in the member list and in invitations, with a short explanation; the server checks it on every route, including REST API, CalDAV/CardDAV and files (#2151).
- Backups: an off-site target per server - S3-compatible storage, WebDAV (https) or SFTP (key pair made by Kalmido, host key pinned after the first test). Only encrypted backups leave the server; upload after each backup with retries, the newest N are kept on the target; "Test connection", "Upload now", "Remove target" (#2152).
- Offline: the outbox lives in IndexedDB and is sent by background sync, also with the app closed; notes and time entries can be written offline and never arrive twice; a quiet install hint (browser prompt, steps on iPhone), with "not now" and "never" (#2153).
- Share to Kalmido takes every file type (office files, ZIP, audio, video ...); shared contact cards and calendar files can go straight into contacts or a calendar; files over the upload limit are named instead of failing later (#2154).
- Appearance follows your account across devices; "Only on this device" keeps a device's own look (#2155).
- Administration: activity per organisation - members, last sign-in date, storage, lists and tasks; numbers only (#2156).

### Changed
- Pages: the trash has its own dialog (restore, delete for good, empty); pages in the trash are deleted for good with their files after the trash period (#2211).
- Office: replaced terms PDFs that no document names any more are removed 30 days after they stopped being current (#2259).

### Security
- Security fix: organisation boundary (roles are enforced server-side in every area).
- Security fix: backup credentials are sealed and never sent back to the browser; the service worker replays only the app's own write requests.

## [2.142.3] - 2026-10-20

### Security
- Pillow 13.0.0: fixes nine image-library advisories published on 20.10.2026 (one critical heap overflow when reading JPEG files); the test suites switch off the quiet hours where they wait for channel messages and are spread more evenly over the CI shards (#2145).

## [2.142.2] - 2026-10-20

- Meal plan: on a narrow phone the week switcher moves under the title, the next-week arrow stays on screen (#2132); the restore check of the sign-in suite waits for the restore instead of a fixed pause.

## [2.142.1] - 2026-10-20

- Fixes from CI of 2.142.0: the ntfy share inbox texts call the basket by its name in every language (#2150), the notification channel lookup and a schema comment follow the Postgres rules (#2145).

## [2.142.0] - 2026-10-20

Notifications to Slack, Matrix, Telegram and Signal, e-mail on assignments and mentions, importers for Notion, Google Tasks, ClickUp, Jira, CSV and Markdown, export as Todoist CSV or Markdown.

### Added
- Notification channels Slack, Matrix (webhook bridge), Telegram and Signal (signal-cli REST): own channels per person under *Settings > Notifications* with the kinds that go there and *Send test*; organisation admins add channels for new, completed, assigned and commented tasks of lists everyone in the organisation sees (never private or locked contents). Addresses are stored encrypted and never shown again; a channel switches itself off after 5 failures in a row; quiet hours apply (#2145).
- E-mail on assignment and mention for people without a push device, collected into at most one mail every 10 minutes (20 a day), per kind off / only without push / always; default: only without push (#2146).
- Import from Notion (Markdown & CSV export, nested ZIPs), Google Tasks (Takeout), ClickUp and Jira (CSV), any CSV (columns matched by header, the preview shows which column went where) and Markdown checklists; people in the files are never matched to accounts (#2147).
- Export of your lists as Todoist CSV (a ZIP, one file per list, Todoist's import format) or Markdown checklists under *Settings > Data* (#2148).
- Administration: *Fetch mails now* next to the mail-to-task settings (#2149).
- Own share inbox over ntfy per person under *Settings > Notifications* (topic, optionally own server and read token); the `NTFY_INBOX_*` variables stay the fallback (#2150).

### Security
- Exported CSV cells cannot start a spreadsheet formula; per-person ntfy servers get a time budget per round; a deeply nested ClickUp checklist cell is refused cleanly (review of 2.142.0).

## [2.141.0] - 2026-10-20

The e-mail filing becomes a small mail desk: each workspace its own mailbox, replies and new mails from the filing, HTML
mails shown safely, tasks and events from a mail; plus a disposition export and a consent import for newsletters.

### Added
- E-mail filing: every workspace (an organisation or the private space) can set up its own IMAP mailbox and SMTP access;
  its mails are filed in that workspace only, replies to filed mails go to the same client or project. The server
  mailbox (`KALMIDO_IMAP_*` / `KALMIDO_SMTP_*`) keeps working as before (#2141).
- E-mail filing: reply to a filed mail and write new mails to a client or project (plain text); the sent mail is filed
  automatically, a failed one stays visible as "Not sent" (#2138).
- E-mail filing: HTML mails are shown cleaned in a sandboxed frame, external images only after "Load images"; a switch
  between text and HTML (#2140).
- E-mail filing: make a task or an event from a mail; the task / event shows the mail and the mail shows what was made
  from it (#2139).
- Disposition: download the bookings shown as CSV or ICS (#2142).
- Newsletter: import consents from a CSV (e-mail, date, source) with a preview of all rows and their problems (#2143).

### Security
- Security fix (e-mail filing): mailbox passwords are stored encrypted, never sent back, bound to their server, and a
  workspace's own mail servers are only reached with a checked certificate and through the internal-host guard (#2141).
- Security fix (e-mail filing): HTML content is cleaned on the server and isolated in the browser (#2140).

## [2.140.0] - 2026-10-20

Private space: shopping, recipes, journal, budget, habits, devices and birthdays.

### Added
- Shopping lists: quantity, unit and price per item (shown in the task row and large in the shopping mode, with the
  sums "still to buy" and "in the cart"); a clear leading quantity like "500 g flour" moves into the quantity field; the
  shopping mode works offline - ticks and new items wait in the outbox and go out when the connection is back (#2131).
- Recipes as their own list kind: servings, ingredients with a selection and scaling onto a shopping list (the same
  open item gets the quantity added instead of a duplicate), a recipe on any day of the meal plan; the meal plan pages
  through any week and date; API `GET /api/family?days=` up to 62 days, `to-shopping` with `servings` / `preview` (#2132).
- Journal: a history tab with search, mood filter, Markdown / CSV export and mood statistics over 30 / 90 / 365 days;
  older days can be edited (#2133).
- Budget: month comparison per category over 3, 6 or 12 months (actual, plan, difference to the previous month and the
  average); budget and office bank import read statements with one shared module - CAMT now also in the budget, common
  bank formats are recognised (#2134).
- Habits: up to six reminder times per habit (the old single time stays the first) and a clear "3 of 5 this week"
  progress bar on the phone; API v1 habits carry `remind_times` (#2135).
- A private device can be taken into the office equipment and back, linked on both sides (jump, update fields,
  unlink); a link to an office you can no longer reach shows a note instead of an error (#2136).
- Birthdays from address books: per address book you can switch on that a date or year changed in Kalmido is written
  back to the contact (CardDAV, If-Match); only that date changes, the rest of the vCard stays byte for byte; changes in
  the address book meanwhile are never overwritten; read-only books and mirrors show a note instead of the switch (#2137).

### Changed
- Database: new columns `habits.remind_times`, `habits.reminded_hm`, `contact_srcs.writeback` / `wb_ro` / `wb_books` /
  `wb_err`, `contact_links.want` and the table `life_device_links` (all additive, 2.139 runs on with them).

## [2.139.1] - 2026-10-20

Package 2.137: moving a whole organisation between servers; the personal office into an organisation.

### Added
- Organisation move: the import of an organisation export takes over every area, not only lists, tasks, calendars and
  address books - office (master data, quotations and invoices with their items, payments, series, cash book, trips,
  meals, contracts, archive, bank data, logbook, the stored PDFs; finalised invoices stay finalised with their numbers),
  clients, file store with all versions, documents, knowledge pages with pictures and history, tables with formulas and
  file cells, video sign-offs, team chat, absences and vacation accounts, bookings, filed e-mails, newsletter, customer
  reports, forms with their answers, playbooks, project notes, notepads, rules, sprints, time entries and timesheets.
  References between the areas point at the new entries; fields and files are sealed again with the target's key; the
  preview lists what is taken over; one undo removes it all (#2344).
- The organisation export also contains the office tables that were missing (bank statements, document templates,
  vehicles and logbook), the page history of knowledge pages and the projects / categories of receipts (#2344).
- Freelancers: the owner of a personal office exports it (Office > Settings), and the import of such a file goes into
  the personal office (#2344).
- Office: the personal office moves into an existing organisation the person administers, with a preview of what goes
  along, what stays (company and bank data, number ranges, absences) and who sees it afterwards; finalised invoices keep
  their numbers and stay locked, a number the organisation already uses stops the move (#1981).

### Security
- Security fix: organisation import (links of video sign-offs, number ranges, logo copies).
- Security fix: feeds (database connection) (#2408).

### Fixed
- Server log: every line is written once again (since 2.138.4 each line showed twice) (#2381).
- API: removing a member from a team chat room through v1 matches its documented path (#2059).
- Tests: six suites follow the changes of 2.138.1-2.139.0 (news sections, error report header, draft watermark,
  contact move copies, media queries, full-text placeholders) (#2405 #2381 #2393 #2378 #2372 #2065).

## [2.139.0] - 2026-10-20

Team chat: threads, voice messages, "Read by"; comments become tasks.

### Added
- Team chat threads: "Reply in thread" in a message's menu; the main conversation shows a line with the number of
  answers, who answered and a dot for unread ones; the thread opens beside the chat (on phones as its own view).
  Unread counts and notifications cover only threads you take part in (you wrote, answered or were mentioned);
  agents read and answer with `thread` / `thread_of` (#2127).
- "Read by" under your last message that was read (in direct chats "Read"), tap for the list of who read it and who
  not yet; switch it off under Settings > Notifications > Send read receipts - then nobody sees yours and you see
  nobody's (#2129).
- Voice messages: the microphone next to the paper clip records up to 5 minutes, you can listen before sending; stored
  like other chat files (quota, virus scan, encryption at rest), with its own player (seek, remaining time, 1x / 1.5x /
  2x). Kalmido does not transcribe them; agents see them as audio attachments with `voice` and `duration_ms` (#2128).
- Every comment of a task can be saved as a task (own, other people's and agents' comments), with a back link, its
  files and a "Saved" mark (#2130).

### Fixed
- Pages: a page whose key was missing is found by its text again once the key is restored; its message says how to
  open it again or that it can only be deleted; an import or the browser lock skips such a page and names it instead of
  stopping (#2386).
- Proposal cards: the app thumb instead of an emoji on accept / reject, larger check boxes and the whole row as the
  target; the "Your wish" field of the agent text dialog uses the full width (#2401).

## [2.138.5] - 2026-10-20

### Fixed
- Quotation parts: a part with its own producing setting "off" shows the switch and "Use the values of the document" again; tests follow the parts that open in place and the film pack defaults (#2266 #2248 #2251 #2252).

## [2.138.4] - 2026-10-20

Phone fixes for office, tables, documents and bookmarks; the agent chat keeps an open edit; hardening leftovers of 2.126.0.

### Fixed
- Office: importing fixed costs on a phone - rows no longer shrink with more than five entries; amount and VAT stay inside their row (#2359).
- Tables: on a phone a tap anywhere in a checkbox cell ticks it, followed by the "Undo" hint; the arrows in link and file cells are 44 px (#2371).
- Tables: SUMIF/COUNTIF with the criterion TRUE/FALSE count the ticks of a checkbox column (#2371).
- Tables: the sheet bar stays above the tab bar on phones; formula suggestions stay above the iOS keyboard (#2372).
- Tables: print / save as PDF on Android shows the print view instead of the app (#2370).
- Documents and office: filter chips, "New tag", the tax date level and the selection bar are touch-sized (44 px); the selection bar sits right above the tab bar; removing the search chip clears the field; the note in "Request files" is full width (#2362).
- Bookmarks: the state selection and the tags are touch-sized (44 px) on phones (#2367).
- Agent chat: editing your own message keeps text and focus while the chat reloads (#2189).

### Security
- Error reports: the webhook also takes its token in a header (`Authorization: Bearer` or `X-Kalmido-Token`) on `POST /api/hooks/issues/<list>`; the old URL keeps working; the app log masks hook tokens in paths (#2381).
- Contacts: a large import takes a database connection per block instead of for the whole run (#2377); moving a contact out of a mirrored address book makes a copy (#2378).
- Customer portal: when a space's sign-in mail budget is used up, its admins (or the owner of a private space) get one notice in the bell; the budget is set with `KALMIDO_PORTAL_LOGIN_SPACE` (#2380).
- Server key change: the status shows unreadable Paperless tokens and the state of the private document index; new admin command `reindex-private` (#2382).

## [2.138.3] - 2026-10-20

Organisation dialog with a searchable member list; decided approvals leave the notifications.

### Changed
- Edit organisation: members as a list like Users, with a search (name, user name, e-mail), a filter "Members / All"
  and a counter; per person a "Member" and an "Admin" box instead of two walls of name buttons. The list scrolls inside
  the dialog, head and buttons stay (also on the phone). The symbol field shows the organisation's picture or an app
  icon instead of an emoji placeholder; the e-mail domain hint sits under its field (#2407).

### Fixed
- Notifications: an approval that was decided (yes, no, stop) no longer stays unread under "For you", for everybody it
  was shown to; older stuck entries clear with the next decision (#2406).

## [2.138.2] - 2026-10-20

Sidebar head and workspace colour, office document PDFs, News sections, Mac dock icon.

### Added
- Office: the PDF button of a draft (quotation, invoice, credit note, ...) asks "Finalise now" / "Show as draft" / Cancel;
  every PDF of a draft carries a bold DRAFT next to the number and a diagonal watermark on every page - preview,
  download, mail attachment and agent API alike. Quotations set to sent / accepted / declined without finalising stay
  unmarked (approval link). E-invoices only for finalised documents (#2393).
- Number scheme: the building block `{isodate}` gives the date with hyphens (2026-04-15) (#2391).
- A 1024 px Apple touch icon for the Mac dock: full-bleed, the figure larger (#2396). Re-add the app to the dock to see it.

### Changed
- Sidebar head: no logo; the first row is the workspace switch (dot, name, arrow). The avatar sits without dots at the
  bottom next to the search, "Start" is in the account menu; "Collapse all" and the collapse button show on hover or
  focus (always on touch screens); the network dot only shows offline or while syncing (#2392).
- Workspace colour: a 4 px stripe across the top of the sidebar (3 px on top of the header when the sidebar is closed)
  replaces the sidebar tint and the stripe in the list header; Private has one too, Kalmido purple by default; the
  setting is called "Workspace colour" and can be chosen without an organisation (#2389).
- News: three sections *For you* (the bell's number), *Also new* and *Read*; unread entries with an accent stripe and
  bold title, read ones muted and below; the head says "N for you" (#2405).
- Quotation rights annex: rows and labels 10 pt, note 8.5 pt, the order confirmation as its own section with more space
  before it; the project line at the top right no larger than the text (#2388).

### Fixed
- PDF footer: every line of a multi-line company name is bold, the address below stays normal (#2397).
- Office settings: the company name field grows with its lines (up to 3) instead of scrolling (#2395).

## [2.138.1] - 2026-10-20

Six releases that were built on 19.10. but never reached main (2.111-2.116 under their old numbers), brought onto
today's code.

### Added
- 2.111 (old): office editors keep an undo per own step and offer "Undo" for 10 s when you leave; invitation mails
  (.ics) to external attendees and a secret subscription link per event calendar; the quick add understands @person,
  a duration and reminders, reminders at a fixed time of day (#2233 #2056 #2057).
- 2.112 (old): file store - select several files to download as a ZIP or move to the trash, a folder as ZIP, scan
  pages with the phone into one PDF, external share links for files and folders (expiry, password, revoke) (#2058).
- 2.113 (old): office settings in five areas that save field by field, industry pack cards with their own switch,
  quotation parts open in place on the title page with a colour each (#2246 #2247 #2248).
- 2.113b (old): team chat with files, free channels per organisation and group conversations; producing by amount,
  handling costs and markup through the film pack, own industry packs from the data folder (#2059 #2251 #2252).
- 2.113c (old): terms and conditions as a PDF per language - with quotations by mail and on the approval link, frozen at
  finalising; finalised quotations can be mailed (#2253).
- 2.115 (old): an inbound webhook per list, webhooks of an organisation with more events; active sessions with sign-out
  everywhere; organisation admins invite new accounts by e-mail (#2061 #2062).
- 2.116 (old): tasks in the trash are deleted for good after the trash period, list CSV export and print view,
  server full-text search of tasks and comments, repeats several times a day, focus sessions and habit stats in API v1
  (#2063 #2064 #2065 #2066 #2067 #2068).

### Fixed
- Brought in with the merge: an organisation invitation always goes by mail (the link never to the admin), the daily
  invitation limit counts before the address lookup (#2062); a restore leaves out the full-text indexes and builds them
  again (#2065); surcharge lines are numbered like producing; the per-field settings save knows the producing-by-amount
  fields (#2247 #2251).

## [2.138.0] - 2026-10-20

Office: start number per number range, quotation bar with the next step, quotation fixes (units, parts, PDF headings);
resizable dialogs; more rule triggers and Kanban swimlanes; sidebar search at the bottom; security fixes.

### Added
- Office: a start number per number range (quotation, invoice, credit note, reminder, delivery note) in the office
  settings; it only goes up, a jump for invoices and credit notes needs a reason (office log); a draft's number can be
  changed in the editor (#2256).
- Rules: new triggers "created", "assigned" and "field changed", new actions "priority", "list tag" and "set field" (#2060).
- Board: swimlanes by person, priority or a custom field; moving a card to another lane takes its value, with one undo
  step (#2060).
- Dialogs on a desktop can be resized at a grip and keep their size per kind (#2234).
- Company data: the form "Partners (GbR)" (#2242).

### Changed
- Quotations: the bar shows the next step (finalise, mark as sent, accepted / declined, create invoice); an invoice before
  the acceptance sits in the "..." menu with one question; the PDF button reads "Preview" (#2235).
- Office import: existing services take the file's order, a "Renumber" button; undoing an import archives entries in use
  (with where they are used and "Restore") and can tidy leftovers (#2237 #2241).
- Sidebar: the search field sits as a fixed bar at the bottom of the sidebar (phone menu and desktop); the head shows logo
  and avatar, below it the workspace button with its name and "Collapse all". Mod+K still opens the search (#2161).
- Quotation items: the unit choice follows the quantity ("5 days", singular only for exactly 1), in all languages (#2249).

### Fixed
- Quotations: a percent item keeps its unit choice, switching back to a unit sets quantity 1 if it was empty (#2236).
- Quotation parts: renaming a part also renames its line on the title page (own texts there stay); saving the title page
  no longer drops the line of a part added meanwhile (#2239).
- Quotation PDF: long part and title headings wrap, the quotation number line sits above the part title (#2240).
- The service worker leaves requests of other origins (e.g. browser extensions) alone (#2257).
- Quotation PDF: the closing (totals, greeting, signature, confirmation) stays on one page, set a little tighter before a
  page break; no heading alone at a page end (#2238).

### Security
- Security fix (upload and calendar subscription tokens): the link is shown once when it is created; existing shortcuts
  and subscriptions keep working (#1907).
- Security fix (organisation recovery key): showing the key asks for password and second factor, the other admins are
  told; server admins can renew an organisation's key with `orgcrypt_cli rotate --org <id>` (#1972).

## [2.126.3] - 2026-10-20

### Fixed
- CI of 2.126.1 / 2.126.2: a client function name no longer trips the icon check, the browser demo answers which agents may draft (#2123 #2124) and the table backlinks (#2357).

## [2.126.2] - 2026-10-20

Pages: suggestions above the phone keyboard, a news entry when someone shares pages with you, "Mentioned in" on tables.

### Added
- Pages: when someone shares a page or folder with you, the news show "X shared the page ... with you"; a tap opens
  "Shared with me". It follows the existing "Sharing" row of the notification settings, no new push or mail (#2355).
- Tables: a "Mentioned in" line lists the pages that link the table with [[tabelle:...]] (#2357).

### Fixed
- Pages on phones: the suggestion list after [[datei: / [[tabelle: stays above the on-screen keyboard; the "+" at
  checkbox lines no longer overlap (hit area grows to the right only); a search hit only in a page name no longer shows
  an empty "Found in the text" section (#2363).
- Pages: a public link of an organisation page whose creator left the organisation is shown as ended and no longer
  counts as an active share. A sealed page text whose key is missing is never shown or saved as text: the page is
  "not readable" (409), search, history and export skip it (#2358).

## [2.126.1] - 2026-10-20

Agents draft for you: office texts, document summaries, the client report, table rows as tasks and a planned morning
sort of the basket. Kalmido calls no language model for this; the connected agent words it and you decide on a card.

### Added
- Office: "Draft text with an agent" for the introduction and closing text of quotation, invoice and reminder drafts.
  The agent gets the document without purchase prices; you edit the text on the proposal card and take it over (one
  undo step); nothing is sent, a finalised or sent document is never changed (#2123).
- Documents: "Summarise with an agent" saves a summary on the document (sealed like the recognised text), shown in the
  document sheet and in the API (#2123).
- Projects: "Word the report with an agent" in the status report - the agent gets the report of the period without
  comments, notes and names; the text you take over replaces the fixed text for copying and sharing (#2124).
- Agents can propose rows of a table shared with them as tasks of a shared list (`POST /api/v1/agent/proposals/sheet-tasks`,
  MCP `propose_sheet_tasks`); you untick rows, edit titles and apply the card as yourself (#2125).
- Planned agent jobs have a kind: "Sort the basket (proposal)" sends your basket to the agent at the planned time
  (suggested: weekdays 7:30) like the button, you find the proposal card in the morning; an empty basket sends nothing (#2126).
- Agent API / MCP: new proposal kinds `office_text`, `doc_summary`, `report`, `sheet_tasks`; `job_request` of a planned sort
  carries `scheduled: true`; `GET /api/v1/agent/schedules` shows the plan's `action`.
## [2.126.0] - 2026-10-20

Security release: fixes from the internal audit (office, documents, agents, sync, offline). Please update.

### Security
- Security fix: invoice numbers of drafts and deleting numbered invoice / credit note drafts (#1966); invoices from times in
  the personal office (#1967); office hardening (#1979).
- Security fix: document data encryption - encrypt-all / decrypt-all / status cover the document tables; private
  documents use the account key (#1970 #1971); documents and receipts hardening (#1979).
- Security fix: approvals of agent requests and approval jobs (#1974 #1975); permission questions of the agent launcher
  (#1973); texts from outside reach agents marked as data (#1978); agent launcher, MCP http mode, git hook (#1979).
- Security fix: rate limits (#1976 #1977), push subscriptions on the device at a change of user (#1991, client part),
  contacts import (#1986), public links and forms (#1979).
- Security fix: tasks and offline queue - recurring completions, repeated creates, several windows (#1987 #1989 #1990);
  tasks in the trash, list copies, moves, batch changes, device data at logout (#1992).

### Fixed
- Calendar: extra dates of repeating events (RDATE) are kept and shown; changed occurrences follow a moved series;
  reminders are not sent twice after an edit; alarms stay with the person who set them (#1985 #1992).
- Offline changes the server refuses keep their text in the conflict dialog (#1992).

### Upgrade notes
- Private document data moves to the account key at the first start. Before a downgrade to 2.125 or older run
  `python -m kalmido.admin.orgcrypt_cli docs-to-server-key` in the container (see docs/SELF-HOSTING.md).
- Team agents: permission questions are answered only by the operator (`KALMIDO_PERM_USER` / `KALMIDO_OWNER_IDS` or the
  agent's owner); the MCP server in `--http` mode needs `MCP_HTTP_TOKEN` (at least 16 characters).
- Numbered invoice and credit note drafts can no longer be deleted (finalise and cancel instead).
- CI checks the web client with ESLint (#1993).
## [2.125.1] - 2026-10-20

### Fixed
- CI of 2.125.0: the vacation client passes the type check, the notification tests count the new rows "Vacation requests" and "Timesheets" (#2117 #2119).
- The client list could fail (error 500) when a time entry was stored without a time zone offset and entries are split at midnight (#2120).

## [2.125.0] - 2026-10-20

Vacation requests and accounts, working days per person, monthly timesheets, time zone per person, timer shortcut,
Excel export; the browser demo starts like a new account and shows every module.

### Added
- Working days and weekly hours per person (Settings > General > Working week; admins of an organisation set them for
  members): workload, "Maybe forgotten" and the vacation account count only the person's working days; without a
  setting Monday to Friday as before (#2118).
- Vacation account per person and year: entitlement, carry-over, taken, requested, rest; half days count 0.5, public
  holidays and days off do not count (#2117).
- Vacation requests: an organisation can switch on "Vacation of members needs an approval" (off by default); admins
  approve or reject with a note (one undo step each), only approved vacation counts as absent - for the team, workload,
  booking pages and agents. Notifications in their own switchable row "Vacation requests" (#2117).
- Time tracking: close a month - its entries are locked (web, API, offline replays, focus sessions, agent proposals);
  admins of the organisation approve it or send it back with a note (stored encrypted, not in push or news). Without an
  organisation closing locks the month on its own. Notifications in their own switchable row "Timesheets"; the API
  answers writes into a closed month with 409 `month_closed` (#2119).
- Time tracking: an own time zone per person (Settings > Modules > Time tracking, "Use this device"); entries over
  midnight count on each day with their share in report, CSV and timesheet (switchable, on by default; totals and
  rounding stay the same) (#2120).
- App shortcut "Start / stop timer" in the long-press menu of the installed app (#2121).
- Excel export (.xlsx) of time entries, client times and the workload view, with the same filters, rows and visibility
  as the CSV (#2122).
- Browser demo: starts like a new account (intro, module choice, tutorial) and runs every module in the browser -
  contacts, home & life, review, budget, bookmarks, workload with absences and dispo, events, knowledge pages, tables
  with formulas, file store, documents and the office pages; what needs a server says so in place, and the build lists
  app calls without a demo stand-in (#1653).

### Changed
- Time reports and the CSV split entries that run over midnight into one row per day (see above; switch off under
  Settings > Modules > Time tracking) (#2120).

## [2.124.2] - 2026-10-20

### Fixed
- CI of 2.122-2.124: new client files are type-checked, file requests import the API helpers inside their routes, the
  start budget is raised on purpose, the lazy lists keep polls / formq last, German cash flow texts no longer use the old
  name of the basket, a sheet tab ignores drops without data (#2341 #2116).

## [2.124.1] - 2026-10-20

### Fixed
- Office: a tap on a view that is still reloading after a save (e.g. "Add receipt", a pipeline card) is no longer lost; it is carried out as soon as the new content is there (#2327).

## [2.124.0] - 2026-10-20

Tables: more functions, new column kinds, rows and columns kept in view, print, history, sharing, charts and several
sheets; cash flow balance from the bank reconciliation.

### Added
- Tables: new functions SUMMEWENN/SUMIF, ZÄHLENWENN/COUNTIF (criteria like `">5"`, `"<>x"`, wildcards `*` `?`),
  SVERWEIS/VLOOKUP, XVERWEIS/XLOOKUP, LINKS/LEFT, RECHTS/RIGHT, TEIL/MID, LÄNGE/LEN, VERKETTEN/CONCAT, GLÄTTEN/TRIM,
  GROSS/UPPER, KLEIN/LOWER, DATUM/DATE, JAHR/YEAR, MONAT/MONTH, TAG/DAY, EDATUM/EDATE; they come in and go out as
  formulas in .xlsx files; a lookup that finds nothing shows "Not found" (#2109).
- Tables: column kinds checkbox (counts as 1 in formulas), person (someone who may see the table), link (http, https,
  mailto) and file (upload into a cell, stored encrypted, trash and Undo like attachments) (#2110).
- Tables: keep the first rows / columns in view while scrolling; "Print / save as PDF" with the header repeated on every
  page (#2111).
- Tables: change history of the cells for people and agents - "History of the cell" and "Recent changes" (newest 200 per
  table within 90 days) (#2112).
- Tables: share a single table with people (read or edit) and with agents of its workspace, revocable at any time; it
  shows under "Shared with me"; deleting, moving and step 2 stay with the table's own people (#2113).
- Tables in the Mod+K search (#2114).
- Tables: a simple bar or line chart from columns, live with the values, saved per table (#2115).
- Tables: several sheets per table - sheet bar under the grid (add, rename, duplicate, move, delete with Undo),
  formulas across sheets (`Sheet2!A1`), .xlsx import / export of all sheets, sheets through the agent API (#2116).
- Cash flow: the balances of imported bank statements (CAMT.052 / .053 balances, an optional balance column for CSV,
  several accounts added up) show as "Account balance according to the bank" with the difference to the computed
  balance and can be taken over as starting balance or real balance; a value by hand always wins (#2342).

## [2.123.0] - 2026-10-20

Knowledge pages: history, pictures from the file store, sharing, full-text search; cash flow with an account balance.

### Added
- Knowledge pages: a history of every page - versions with date and person, a line comparison with the current text and
  "Restore" (one undo step); saves of one person within ten minutes count as one version, at most 100 per page (#2102).
- Knowledge pages: "Insert picture or file" in the editor - upload from the device (also by pasting or dropping into the
  text) or pick a file from the file store; a file from the file store is only referenced, never copied, and shows only
  for people who may open it (#2103).
- Knowledge pages: share a page or a folder read-only - with people who have an account (private space, "Shared with
  me") or by a public link without sign-in, with an optional expiry, revocable at any time; the public page shows only
  the shared pages and their pictures, is not indexed and runs without scripts. Spaces encrypted in the browser cannot
  be shared (#2104).
- Knowledge pages: the texts and their history can be stored encrypted at rest with the key of the space (organisation
  key, account key for private pages). Off after the update; the server admin switches it on with
  `orgcrypt_cli encrypt-wiki`, `decrypt-wiki` is the way back before going to an older version (#2105).
- Knowledge pages: the search uses a word index (keyed hashes, not the text) - hits in the name first, then in the text,
  then the newest, more than 30 hits with "Show more"; in the text whole words and word beginnings count (#2106).
- Knowledge pages: `[[datei:…]]` and `[[tabelle:…]]` link files of the file store and tables, with suggestions while
  typing; the file store shows which pages mention a file (#2107).
- Knowledge pages: open check box lines become tasks with one tap (quick-add syntax for date, tags and priority, list
  of your choice, one undo step); the line then links the task and shows when it is done (#2108).
- Office: cash flow with an account balance - an opening balance with its date in the office settings, the calculated
  balance at the end of every month (also in the preview), corrections by hand per month ("Other income / expense" with
  a note) and the real balance at month end with the difference; values by hand are marked, calculated ones stay as
  they are (#2341).

### Fixed
- Office: the installment list shows the open amount in the number format of the document (#2351).
## [2.122.4] - 2026-10-20

Fixes: quotation PDF, storage quota, CSV exports, phone sizes, boundary check and edit rights of the instance admin, feeds, video sign-off, two clock-dependent tests.

### Fixed
- Quotation PDF lists "Exceptions" and "Exclusive" of the transfer of rights only once (#2261); the storage quota counts entertainment receipts and contract files (#2316); every CSV export guards text cells against formulas, also after a tab or line break (#2317).
- Instance admin: the boundary check names objects and people only inside the own organisations, and a private connection no longer gives the right to edit members of another organisation (#1724); the same feed address is followed only once, also on a double tap or parallel import (#1906).
- Video sign-off: protocols stay after a move between private and organisation and come back on undo, the customer page controls YouTube under any address, writing at an office client needs an office role, the customer's decision shows in the reader's language (#2215 #2217).
- Phones: 44 px selects in office settings on iOS, the contact import notice lies under dialogs, larger touch targets in video sign-off and bookmarks, full-width bookmark fields, "Save" stays reachable above the keyboard (#2326 #2348 #2217 #2223); tests no longer depend on the time of day (#2218 #1910).
## [2.122.3] - 2026-10-20

Office fixes, drag a task under another, chat "Show more".

### Changed
- Office: one-off imports (fixed costs from Excel, leads from CSV) moved from the lists to Settings > Import legacy data, each with its own section; empty lists link there with "Already have a list? Import from Excel", filled ones with a quiet "Import…" at the end (#2335).

### Fixed
- Office: fixed costs and subscriptions without VAT show one amount with "without VAT" instead of the same net and gross amount twice (#2333).
- Tasks: a single task dropped onto the middle of another becomes its subtask, with the mouse and with the finger, one undo step; milestones and its own subtasks are no target (#2334).
- Chat: "Show more" of a shortened message sits right under the cut text, before steps, suggestion and time (#2340).

## [2.122.2] - 2026-10-20

Office: scroll position, fixed cost import, tab picker.

### Fixed
- Office: saving an entry (cash flow, subscriptions, books incl. the year switch, logbook, travel costs, templates, pipeline, contracts) keeps the view and its scroll position; no short "Loading…" page any more (#2327).
- Office: the fixed cost import fits a phone (amount and VAT rate on a second line), suggests 0 % VAT for bank and credit costs, taxes (not the tax adviser), service charge, memberships, KSK, Knappschaft and BG, finds a header row without "Name" in A1 and skips rows with only "0" (#2323).
- Settings > Appearance: "+ Add tab …" opens a sheet with a search, folded sections, lists below their folder and the app's icons instead of one long list (#2329).

## [2.122.0] - 2026-10-20

File store and documents: file request links, tags everywhere, a stronger search; swiping through the news; yearly VAT.

### Added
- File store: "Request files…" on a folder creates a public upload link for clients (no account): with an expiry date
  (at most 90 days), limits for size, number and file types, stop / reopen / extend, a QR code. Uploads land sealed in
  the folder (optionally one subfolder per send), never overwrite and show nothing of the folder; a news item tells the
  creator, switchable in the notification settings (#2097).
- File store: tags on files and folders, the same tags as in Documents, with a tag filter per space (#2099).
- Documents: several tags (every one / one of them / not), several senders, types and folders, document date and date of
  arrival, file type, "without tag / sender"; search syntax `tag:`, `sender:`/`absender:`, `type:`/`typ:`,
  `date:`/`datum:`, `"exact text"`, `-word`; the chosen filters in one line above the list (on phones in a sheet);
  bulk changes of the selection (tags, type, sender, one undo step) and the selection as one ZIP (#2294).
- File store and documents: Shift-click selects a range, Ctrl/Cmd-click toggles one item (#2295).
- Documents: create documents via the API and MCP (`POST /api/v1/documents`, `create_document`); an agent writes only
  into folders shared with it for editing, its sender / type / tags follow the levels like a change (#2098).
- Documents: the selection as a CSV file (metadata, amounts; `;` and decimal comma in German) (#2100).
- Text recognition also reads French, Italian, Spanish and Dutch, following the app language; a missing language pack
  is shown as a note in the documents settings (#2101).
- News on phones: swiping in an opened news item goes to the next / previous unread one (#2314).
- Office: tax dates "Yearly (annual return only)" - one task per year for the annual VAT return (31 July of the
  following year, with a note on the later deadline with a tax adviser); the VAT figures for the whole year, preselected
  for the previous year in this mode (#2315).

### Not yet
- Documents: saved searches and sorting by relevance with highlighted matches follow later (#2294).
## [2.121.0] - 2026-10-20

Receipts: recognition of supplier, VAT and invoice number, accounts per category, billing on to clients, cash book,
agents suggest amount and VAT.

### Added
- Receipts: the recognition now also reads the supplier (with VAT id and tax number), the VAT rate(s), net, VAT and
  gross and the invoice number - locally, without any language model. It is only a suggestion: a line "Recognised: …"
  with "Take over" (sender, VAT rate, amount; one undo step) and "Discard"; the invoice number can be copied. Agents
  read the values as `extracted` of `GET /documents/{id}`, they never take them over (#2092).
- Receipts: a category shows its account of the chart SKR03 or SKR04 - the one the DATEV export books on (default
  by keywords or your own); "Change account" in the receipt sheet sets your own, the EÜR lines show it too (#2093).
- Office: receipts can be billed on to a client as outlays - net when the receipt has a VAT rate, else gross, with an
  optional markup, one position per receipt or one for all; never twice, undo takes it back while the document is a
  draft (#2094).
- Office: a cash book for cash income and expenses - gapless numbers per cash box, balance, quick entry for the phone,
  several cash boxes. No deleting: a correction is a cancellation (counter entry); the day closing is final, the
  balance never goes below zero, every change is logged. Export as CSV and PDF with closings and log. Receipts show
  their cash entry. The cash book does not count into the EÜR (#2095).
- Agents: a receipt suggestion may also carry amount, currency and VAT rate; the person can change all of it when
  accepting, undo brings the old values back. Agent rights stay as they are (#2096).

## [2.120.0] - 2026-10-19

Office: progress and final invoices, cash discount, client portal with documents, delivery notes, DATEV input side, own letterhead.

### Added
- Invoices: progress invoices from a quotation (amount or percentage of its net, split onto its VAT rates, e-invoice type 326) and a final invoice that deducts every finalised, not cancelled progress invoice per VAT rate (type 380); a second final invoice or a progress invoice after the final one is refused; the cash flow plan keeps the rest of the quotation after a progress invoice (#2087).
- Invoices: cash discount (Skonto) per invoice with a default in the office settings - a line under the payment terms in the PDF, the XRechnung discount line in BT-20, a payment of the discounted amount within the period settles the invoice (#2087).
- Client portal: clients see their sent quotations, invoices with payment state and due date and credit notes and download the PDF as it was sent (office setting "Show documents in the client portal", off by default); "Send portal link" in the client menu mails the sign-in link - no account, no password (#2088).
- Delivery notes / proofs of service as a document kind of their own (number series LS-, positions without prices, a receipt box for signature, from a quotation or invoice); a timesheet PDF for invoices with a client and service period, optionally attached when sending (#2089).
- DATEV booking batch: incoming receipts (expense account per category, input tax key, collective creditor or bank) and travel costs incl. per diem; hints before the download for receipts without amount, category or VAT rate; travel receipts already marked "in DATEV" are not exported again; new settings "Receipts and travel costs" that save at once (#2090).
- Own letterhead: upload a PDF (page 1 behind the first page, page 2 behind the following ones), margins per page, switch off the own head and footer, preview, every change undoable; finalised documents keep their letterhead, the ZUGFeRD XML stays embedded, without a letterhead the PDF is unchanged (#2091).

### Changed
- Country pack de: bookkeeping export DATEV is marked ready (#2090).
- Agents: `draft_invoice_from_offer` / POST /api/v1/office/offers/{id}/invoice take `inv_type`, `amount` and `pct` (#2087).

## [2.119.2] - 2026-10-19

Contacts, undo of a list delete, framework contracts between workspaces, a flaky chat test.

### Added
- Contacts: CSV import (Outlook, Google, Excel) with a column mapping step - encoding and separator are detected, the headers of Outlook (English and German) and Google are mapped for you - and a CSV export that Excel opens directly; formula cells are defused, phone numbers stay as they are (#2080).
- Contacts: a hint on possible duplicates when you create a contact (same e-mail, phone or name; "Create anyway" or open the existing one) and after an import, with a way to the merge view; nothing is merged on its own (#2084).
- Contacts: "Manage groups…" with the count per group, rename and delete (only the label) across all writable address books, one undo step; synced devices get the change (#2085).
- Contact card: "Create client" in the card's menu takes over company, e-mail, phone and address and links the contact as the contact person, with undo; a linked contact shows "Open client" (#2082).
- Contact card: a "Contact history" section with filed e-mails, quotations, invoices and appointments, newest first - only what you may see anyway (#2083).
- Office: framework contracts move with their PDF files between the private area and an organisation ("Move to another workspace…" in the contract dialog), one step undo; a contract that issued documents point to stays archived and is created anew in the target (#2298).

### Changed
- Contacts: long address books load further pages while you scroll instead of stopping at 500; "All" in selection mode really takes every match (#2081).
- Addresses on the contact card and the client page open the map app on a tap (Apple Maps on Apple devices, Google Maps elsewhere) (#2086).

### Fixed
- Deleting a list: "Undo" right after it brings an active list back active in its old place, not into the archive; restoring from the trash still goes to the archive (#2304).
- Documents: the selection marks have a real 44 px touch target on phones (#2206).
- Chat side window: unchanged parts (job filter, status, steps) are no longer redrawn on every update, and a team conversation parked right after opening loads its messages instead of staying at "Loading…" (#2310).

## [2.119.1] - 2026-10-19

### Fixed
- Entertainment receipts: the amount lines use the full width on phones, saved people always show among the guests, agents are no host or guest; the keep period counts from the last approval; CI: office menu tests know the new point, start CSS budget (#2288).

## [2.119.0] - 2026-10-19

Entertainment receipts, filled icon buttons, agents in "All people".

### Added
- Office: new module "Entertainment receipts" (under Money, next to travel costs). A form with pick lists for place, host and further guests (new places and people join the lists when a receipt is approved), gross amounts per VAT rate split into food and drinks, the tip as its own field and the restaurant bill as a file (a note from 250 EUR gross: the bill must be made out to the company) (#2288).
- Entertainment receipts: approving locks the receipt and records the host's digital confirmation; unlocking is possible and logged with who, when and why. A clean PDF receipt of your own, a yearly report (input VAT 100 %, 70 % deductible / 30 % not), filters by person, period and occasion like the travel costs, export as CSV and PDF; drafts move between the private office and an organisation, approved receipts are kept 8 years (#2288).
- "All people …" has an "Agents" section with a pin, so agents can be pinned to the sidebar on the iPhone too (#2210).

### Changed
- Icon buttons that are switched on (pin, priority, lock, bells) show a filled shape in the accent or priority colour instead of only a colour change; off stays an outline (#2301).

### Fixed
- Agent chat: the hint "Ctrl+Enter sends" (Mac: "Cmd+Enter sends") shows as a small line under the field, also in the narrow side panel next to a task and in split windows; the same in the team and job chat, not on phones (#2302).

## [2.118.0] - 2026-10-19

Quotation counter per client or project, one progress switch.

### Added
- Office: a new setting "Counter for quotations" - per organisation (as before), per client or per project. Each
  client / project counts on its own, per year when the scheme holds the year, e.g. `KV-{client}-{yyyy}-{seq:02}`
  gives KV-ACME-2026-03. Existing numbers stay as they are; a new counter continues from the highest number the
  client / project already has. In these modes a new quotation gets its number once the client or project is set
  (at the latest when it is finalised). Invoices, credit notes and reminders keep one gapless counter (#2265).
- Office: the building block `{version}` for quotation numbers - the first quotation is 1, each duplicate keeps the
  running number and counts only the version on, e.g. KV-ACME-2026-03-V2 (#2265).

### Fixed
- Sidebar: "Progress in the sidebar" now switches the line and the progress rings together, kept in the account for
  all devices; the separate device switch for the rings is gone, a device that had it off hands that to the account
  once (#2297).

## [2.114.5] - 2026-10-19

Office fixes 5 (page 1 of the quotation PDF tightened).

### Changed
- Quotation PDF, page 1 takes more positions: with a rights appendix or printed parts the order confirmation (when on,
  #2270) moves to the very end behind the appendix and page 1 says "Order confirmation by signature on page n"; switched
  off, neither the block nor the line is printed. One VAT rate in all positions -> no VAT column; no validity sentence
  below the table (the head has the date); the raw data option as three total rows (net, + option, net with option)
  instead of the dashed box; smaller logo, closer greeting; footer columns at most three lines, "E-Mail:" with a colon (#2300).

## [2.117.1] - 2026-10-19

### Fixed
- PDF metadata: the PDF module finds the version also when it is loaded on its own (#2262).

## [2.117.0] - 2026-10-19

Travel costs, document samples, small fixes.

### Added
- Travel costs: filter by person next to "All / Not in DATEV" (members and free names from the trips); it filters the list, the report, the per diem report and the CSV / PDF / Excel export, stays when you switch the view and hides when only one person occurs (#2291).
- Travel costs: own purposes - "Add another purpose…" at the end of the purpose list, rename or remove them under office settings > Travel costs (trips keep their text), report grouped by purpose, the import takes unknown purposes over; per organisation or private space (#2292).
- Documents: seven more samples in German and English (cover letter, payment reminder, dunning letter, termination, power of attorney, handover record, credit note letter), also via "Start from a sample" when you create a template; legal samples carry a note to have them checked (#2283).
- Framework contracts: attach the signed contract and addenda as PDF - open, replace, remove, a date per file; stored encrypted, a paper clip in the list; deleting the contract moves its PDFs to the trash, they go for good after 30 days (#2285).

### Changed
- Travel costs: the arrow of a trip opens a row menu (open, edit, duplicate, move, delete with undo), like the quotations; a tap on the row still opens the trip (#2287).
- PDF metadata: producer and creator of every generated PDF read "Kalmido v<version>" (#2262).
- Agent chat: on phones the filter All / Only me / Jobs is a filter icon in the chat head with a dot while a filter is on, no extra row (#2260).

### Fixed
- Travel costs: the calendar of "To" opens in the month of the start date, days before it are locked, and "To" follows a later "From"; the same for the other from / to pairs in the office (#2290).

## [2.102.1] - 2026-10-19

### Fixed
- After a database restart the first request no longer waits 30 s and fails: a broken pooled connection makes the pool
  test all idle ones at once instead of one by one with a growing pause (2.102.0 #1994 follow-up).

## [2.99.0] - 2026-10-19

Files on knowledge pages and a ZIP import that keeps PDFs and pictures, one "…" menu on knowledge pages, the acceptance note
on accepted quotations, a short sidebar group Exchange, the rest of the fixed recipient fields of office documents and
44 px fields in the document editor.

### Added
- Knowledge pages carry files: PDFs and pictures (PNG, JPEG, GIF, WebP, cleaned SVG) below the text (*Attach files*, up to
  25 MB each), shown in the text as a picture or a link; they have the rights of their page, are encrypted at rest like
  task attachments, go into the backup and the organisation export, and a file deleted on its own is removed for good
  after 30 days; they move along when their pages move between the private space and an organisation (#2182).
- The ZIP import of knowledge pages (SilverBullet export) takes PDFs and pictures along: a file goes to the page that links
  it (`[[file.pdf]]`, `![[_attachments/pic.png]]`, `![](pic.png)`, `[text](file.pdf)`) and the links are rewritten; files
  nobody links land on the page *Imported files* of their folder. The type is checked by the content. Limits: 25 MB per
  file, 500 MB per ZIP. A report lists pages, files and every skipped file with its reason. The export puts the files
  under `_attachments/`, so importing it again gives the same pages and files (#2182).
- A quotation accepted online through the customer link gets the acceptance box instead of the empty signature lines in
  its PDF: "Accepted online by <name>", the time (UTC) and the SHA-256 of the accepted content - in the customer's
  download and in the app (the original stays available) (#2195).

- Clients have a *Name addition*: its own line under the name in the recipient of documents (preview and PDF), joined to
  the buyer name in the e-invoice (BT-44 "Name - addition"), one line in lists and search; agents read and write it
  (`name_extra`) (#2188).
- The own company: the name may have up to three lines (letterhead and footer print them below each other, the sender
  line and the e-invoice BT-27 join them), a new field *Address extra* (BT-36); old free address lines are read into the
  fixed fields when the settings open (nothing is changed until you save) (#2188).

### Changed
- Sidebar group *Exchange*: people show only when you pin them (right click / long press, or the pin in *All people …*;
  at most five, the same on all devices); a person with a chat is not listed twice; *All people …* opens the list of
  everyone you share lists with (tasks, message, pin); groups only where you are a member; agents only when pinned or
  when they have something unread, waiting or running - the others stay under *Agents* (#2187).
- The e-invoice takes the client's normal e-mail as buyer address (BT-49) when no invoice e-mail is set (#2188).
- Knowledge pages: export, import and encryption moved into the "…" menu of the header (section *Space*); the menu above
  the page list is gone, the page's own menu shows on hover of the title row on a desktop and always on a phone (#2183).
- An encrypted (locked) knowledge space takes no files yet: uploads are refused with a clear message, the browser import
  skips files with a reason, and switching the lock on deletes the space's files in the trash for good (#2182).

### Fixed
- Document editor: every field is 44 px high with 16 px text on phones, also the selects on iOS (customer, language,
  currency, status, text blocks, unit, VAT) and the position detail (#2025).
- Chat composer: the paperclip and the meeting (list) icon sit on one line; the width grip's label shows to its left and
  no longer covers the send button (#2185).

## [2.102.0] - 2026-10-19

Architecture audit T3, news, chat and phone fixes; a trash for deleted lists.

### Added
- Deleted lists go to the trash with everything (tasks, fields, tags, chat, sections); a list of an organisation goes
  to the organisation's trash, where its admins can restore it. After 30 days a list is deleted for good, files
  included. The tasks of a deleted organisation list no longer land in the owner's private trash; a list in the trash
  has no public link and is not part of an account export (#1988 #2166).
- Questionnaires: a client link (the form's link signed for one client, from the form dialog or the client's menu)
  assigns a submission to that client before any e-mail matching; only clients of the list's space count (#2201).
- Browser errors can become a bug ticket in a project list chosen by the admin (default off; only the message, the
  place in the code, the version and the open area) (#1999).
- Server: KALMIDO_THREADS, the database pool follows the threads, warnings for an exhausted pool or a too small
  max_connections, GET /api/admin/health (#1994).
- Migrations are recorded in the table kalmido_migrations (stable ids, one-shot flags mirrored) (#1996).
- For developers: type check without a build step (jsconfig.json, `// @ts-check` for new client files) (#1995) and a
  layer linter tools/check_layers.py in CI (#1999).

### Changed
- News: bundles only per task, read and unread apart, unread on top, the number per line counts unread, the tab
  "All" has its own number (#2197).
- Chat: a visible hint "Ctrl/Cmd+Enter sends" next to the send button in team chat, agent / job chat and comments
  (#2204).
- Every background loop runs only once per instance (database lock); web and worker can run apart (KALMIDO_ROLE,
  `python app.py worker`), one container stays the default (#1997).
- One shared drag core (drag.js): sections and bottom sheets drag the same with touch, mouse and pen, scroll at the
  edge, Esc cancels (#1998, first part).
- Start size: scheduling polls and questionnaires load on demand, the start budget is lower again (#2208).

### Fixed
- The calendar shows invitations also without an own calendar (#2006); the change detection counts only valid
  invitations (#2003).
- Files and documents: in selection mode the bar no longer covers the last row; the selection marks in documents have
  a 44 px target (#2206).

## [2.114.4] - 2026-10-19

Office fixes 4 (quotation PDF, documents, travel costs).

### Added
- Quotations: the order confirmation block (place, date, signature of the client) is optional - an office setting
  (default on) and a choice per quotation (like the setting / on / off); a finalised quotation keeps the state it was
  finalised with (#2270).
- Documents: a large "Preview (PDF)" button in the draft opens the pages like in quotations (#2278).

### Changed
- Quotation and invoice PDF: the footer columns follow their content, IBAN, BIC, e-mail and tax number never break;
  phone numbers are printed grouped (+49 221 ...); the page number stands only in the footer and only from two pages
  on, also in documents (#2271 #2272 #2273 #2282).
- Quotation PDF: the VAT note names only the rates that occur; the option sum reads "Net total with option raw data";
  the producing line gets a position number and "1 day", its formula shows only in the app; the "Client" row in the
  head is gone, the name stands in the address (#2274 #2275 #2276 #2277).
- Documents: the footer has the same columns as the quotation (address, contact, register, bank) (#2284).
- Documents: variable buttons insert at the cursor with a space, the client address on lines of its own; finishing
  with empty variables names them and asks first (#2280 #2281).
- Travel costs: without receipts in the year the per diem is the main amount, with receipts there are two columns
  "Per diem" and "Receipts", a missing value shows a dash (#2286).

### Fixed
- Invoice from a quotation with parts: the choice texts stand right next to their radio buttons again (#2269).

## [2.114.3] - 2026-10-19

### Changed
- Quotations: the producing calculation is visible -- a hint at the switch, "like the document" or "own setting" in a part, "incl. producing 1.5 days" on each part line of the title page and a marked producing tick at the positions; the sums do not change (#2266).

## [2.114.2] - 2026-10-19

Office fixes 2.

### Changed
- Quotations: an admin (or a person without an organisation in their own space) can delete a finalised quotation that
  was never sent and has no decision of the client; its number stays as a traceable gap in the office log. Sent,
  accepted, declined or signed quotations and all invoices, credit notes and reminders stay locked (#2263).
- Quotations: "Undo finalising" takes such a quotation back to a draft; it keeps its number and the office log notes
  the step (#2263).

### Fixed
- Office settings: the error of a number scheme shows under the field, which keeps its full width (also on phones); a
  "Reset" button below it brings back the last saved scheme (#2264).

## [2.114.1] - 2026-10-19

Office fixes.

### Changed
- Quotation PDF: the transfer of rights moves to a calm appendix on its own last page, after the part pages; above the
  signature a short line points to it (German and English, quotations and order confirmations) (#2258).
- Cash flow: receipts of the books count as an outgoing payment like in the profit statement, on their payment day, else
  their document date; one matched to a bank booking counts with the booking's amount (#2018).

### Fixed
- Books, cash flow, key figures and the invoice list show the new numbers after a bank booking is matched, unmatched or
  undone, without reloading the page (#2016).
- Bank: the button on a suggestion reads "Assign" (German "Zuordnen"), the secondary buttons are 44 px high on phones (#2017).
- Quotations and parts: adding a heading or a text block no longer shows an error first; it is saved with its first
  text (#2254).
- Calculation values: the "Calculate producing" checkbox has its normal size again (#2255).

## [2.136.0] - 2026-10-19

A new face: the Kalmido bot replaces the heron in the app icon and everywhere in the app.

### Changed
- New app icon, favicons, store and shortcut icons: the Kalmido bot (two eyes, an antenna) on the violet tile; the push
  badge on Android is its white silhouette. iPhone / iPad: remove the web app from the home screen and add it again to
  get the new icon - iOS keeps the old one otherwise (#2193).
- The bot instead of the heron in empty views, search without results, "all done", the celebration (it pops up and hops),
  the welcome screen, the loading screen and the error pages; a running agent job shows the bot at work, a job waiting
  for your approval the bot waiting. Calm and gentle motion, none with "reduce motion" (#2193).
- The sidebar and the sign-in screens show the new word mark, dark on light and light on dark (#2193).

## [2.98.1] - 2026-10-19

### Fixed
- Scheduling polls: the proposed times and the end of voting use the app's own date and time pickers instead of the browser's (2.98.0 CI).

## [2.98.0] - 2026-10-19

Scheduling polls, questionnaires in forms, the office menu as a rail on the left, resizable tables and polish.

### Added
- Scheduling polls: propose 2 to 20 times, send a link, people vote without an account (yes / maybe / no, their own vote
  can be changed later); the best time is highlighted and becomes an event with one click, in a Kalmido calendar or a
  writable CalDAV calendar, an invitation mail only when you tick it. Start from the calendar, a task or a customer. Polls
  live in the private space or an organisation and move between them. The link is unguessable, can be renewed, switched
  off or expire; votes are limited per address and poll, no outside service (#1953).
- Questionnaires: forms get own questions (short and long text, single and multiple choice, date, number, file, yes / no)
  with "required" and a help text, sorted by dragging; on one page or one question per step, without scripts. A submission
  becomes a task with the answers as Markdown and the files as attachments; on request the sender's e-mail is matched to a
  customer of the same workspace. Submissions are listed in the form dialog and download as CSV (#1954).
- Tables: the frame can be resized freely, also when the table is empty (kept per device); empty cells fill it and typing
  into one creates the row or column. "Open in own window" and full screen next to "Dependencies" (#2181).

### Changed
- Office: the menu is a rail on the left with three groups (Sell, Money, Administration); every page has its own heading.
  Services and text blocks are a "Templates" tab under Settings; travel expenses moved to Money, framework contracts to Sell.
  On phones the office start lists the groups one below the other, and a page shows "‹ Office · group" with one swipeable
  tab row (#2180).
- Ticking off and creating a task animate a little longer; a ticked row leaves only after its animation (#2163).
- Documents: amount and due date are only guessed for invoices and receipts with a total line (and for "to pay by" lines of
  tax notices); the Paperless import takes only money fields; empty amount / due fields are hidden in the document view (#2178).

### Fixed
- A table could stay on "Loading…" when it was loaded twice at the same time (#2181).
- Code comments no longer carry the name of another product (#2184).

## [2.101.0] - 2026-10-19

### Changed
- **"Show more" for all tasks** (#2157): pressing *Show more* on a long description keeps the next tasks unfolded too, until *Show less*; a setting per device that stays after logging out.
- **Trademark note** (#1964): Settings > About and the README say that named products are trademarks of their owners and Kalmido is not affiliated with or endorsed by them; names only, no logos.

## [2.97.1] - 2026-10-19

### Fixed
- Quotations and invoices: the sender line above the address field starts with the company name ("Company · Street ·
  Postcode City"); finalised documents keep the line they were printed with (#2224).
- Quotations show the customer number in the key data, like invoices (#2224).

## [2.97.0] - 2026-10-19

Bookmarks, a display name for customers, office data and locked wiki spaces between your private space and an organisation.

### Added
- Bookmarks (Home & life, module "Read later"): save links with a preview (title, description, picture), tags, a note and
  read / archived; cards or a list, search over everything including the page's reading text. Save from the share target,
  by pasting, or with a browser button that asks before saving. Karakeep links arrive as bookmarks. Bookmarks move between
  the private space and an organisation. No screenshots, no whole pages, no automatic tags (#1950).
- Customers: an optional display name for pickers and lists (e.g. "Foo Switzerland" / "Foo Germany"); customers with the
  same name show their city automatically. Invoices and e-invoices keep the legal name. New field "Address line 2" (#1951).
- Office data moves between the personal office and an organisation: customers with their contact persons and drafts,
  travel-expense drafts and document templates. Issued invoices, closed receipts, number ranges and the archive always stay
  where they are; on request a read-only copy goes along ("copy from …", not counted in the target's figures). The target
  numbers drafts in its own range. One step undoes it (#2049).
- Wiki spaces with a lock: pages move between the private space and an organisation; your browser re-encrypts them for the
  target (a warning comes before they go into an open space). One step undoes it (#2050).

### Changed
- Quotations and invoices take the recipient from the customer (name, attn., street, address line 2, postcode, city,
  country): the document head shows it read-only with "Edit customer" and "Address missing"; without a customer you create
  one right there. The address is frozen when a document is finalised; older documents stay as they are. The free-text
  address of a customer is no longer in the form; where the fixed fields were empty it was taken over once (#1951).
- "Moved out of …" under a page or table names a workspace only to its members, others see a neutral word (#2051).

### Fixed
- Files left behind by an interrupted move between workspaces are cleaned up at night (#2051).

### Security
- Security fix: link previews and moves between workspaces (organisation boundary).

## [2.96.3] - 2026-10-19

### Fixed
- Video sign-off (CI 2.96.2): the agents' route for a comment names its second id like the API description, the browser demo
  answers the video list, and the task detail keeps the comment box's focus (push button "Reply") when the section arrives (#1959).

## [2.96.2] - 2026-10-19

Video sign-off with comments at the time code (links only), and an invitation to contribute national e-invoice formats.

### Added
- Video sign-off at tasks, projects and clients: paste a link from Vimeo, YouTube (also unlisted) or a direct video file
  (MP4, WebM, MOV over https, e.g. from your own cloud or NAS). Kalmido stores no videos. Comments sit at the second the
  player paused, show as marks on a time line and jump there with a tap; answers, done, versions v1, v2 ... with the old
  comments kept at their version. Links without time control (e.g. a share page) open in a new tab, comments go without
  a time code (#1959).
- A customer link without an account, on the existing approval flow: the customer types a name, comments at the time code
  and chooses "Approve" or "Request changes"; the decision is a line in the comments, the push follows the "approval"
  switch. Internal team comments stay internal (#1959).
- Comments as CSV or as text for the edit; a video sign-off moves between the private space and an organisation (one
  undo); usable without an organisation in the private space (#1959).
- Agents read the video sign-offs of shared tasks and lists and comment at the time code, answer and tick comments off:
  `GET /api/v1/videos`, `GET /api/v1/videos/{id}`, `POST /api/v1/videos/{id}/comments`,
  `PATCH /api/v1/videos/{id}/comments/{comment_id}`; MCP `list_video_reviews`, `get_video_review`, `add_video_comment`,
  `set_video_comment_done` (scope comments for writing). The customer link never comes through the API (#1959).
- CONTRIBUTING: "Contributing national e-invoice formats" - how `einvoice.py` is laid out, what every format needs
  (invented example invoices, a pinned validator run in CI, the specification source), clearance countries only after an
  issue; a pull request checklist and an issue template "E-invoice format proposal" (#1961).

### Security
- The players are embedded without any script of the provider (YouTube through youtube-nocookie.com, control by
  postMessage with origin checks); the app's CSP allows frames of these two players only and `media-src https:` for
  video files, which load only when played. The customer page has its own CSP; comments over it are rate-limited.
  Sign-offs in the trash are deleted for good after 30 days (#1959).

## [2.96.1] - 2026-10-19

### Fixed
- Moving a table: the scan for formulas that name another workspace runs on Postgres too (CI 2.96.0) (#1941).

## [2.96.0] - 2026-10-18

Moving data between your private space and an organisation, and one card per job in the agent chat.

### Added
- Files, folders with everything in them and documents move between the private space and an organisation, both ways
  ("Move to another workspace…"). Sender, document type, tags, recognised text and the Paperless-ngx origin go along; the
  files are sealed again with the target's key. Shares that do not hold in the target end - the dialog names them, and
  duplicates, first. One step undoes it; a moved document is learned by the target's suggestions at once (#1941).
- The file store and Documents have a multiple selection ("Select"); Documents can select all hits of a search or filter
  (up to 2,000) in one go (#1941).
- Wiki pages and whole folders with their sub-pages move between the private space and an organisation; links between pages
  that move together follow, links into the other workspace are named before. Spaces with a lock cannot move yet (clear
  message) (#1941).
- Tables move between the private space and an organisation; a binding to a list of the old workspace ends and comes back
  with the undo. The last move shows under a page and in a table's side panel (#1941).
- An organisation export can be imported into your own private space: nobody joins an organisation, lists are shared only
  with the people you tick (#1941, #1918).
- Agent chat: every background job shows as one card with name, version, state and its last line; tapping it shows the whole
  history. The final result, errors and approvals stay visible, long results are cut to five lines with "Show more". A
  filter in the chat head: All / Only me and the agent / Jobs (#2015).
- Agent API: optional `job_msg` (say | question | result | error) on job messages; the chat answer carries `jobs` with state
  and version. MCP `send_chat` and the reference starter send it (#2015).

### Changed
- Absences follow the workspace switch "Private": your own area instead of the first organisation (#1941, #1918).
- Agents never move data between workspaces; that stays with people in the app.

## [2.95.0] - 2026-10-18

The per diem of business trips with the German flat rates per year, its report as PDF / Excel / CSV and the import of a
per diem spreadsheet.

### Added
- Travel expenses compute the per diem (*Verpflegungsmehraufwand*) of every trip per participant: Germany 28 / 14 EUR,
  abroad the rates of the BMF letter of the year (2025: 2 December 2024, 2026: 5 December 2025, taken over line by line),
  country and city per day (where you are before midnight), start and end time for single days (more than 8 hours), meals
  provided per day (breakfast 20 %, lunch / dinner 40 % of the full rate). A year without a table shows a hint, never an
  estimate (#1932).
- The evaluation shows *Per diem allowances <year>* per person with the breakdown "country: n x rate", as PDF (a section per
  person), Excel (one sheet per person) and CSV (#1932).
- *Take over from Excel* imports a per diem spreadsheet: one sheet = one person, one row = one trip, cell comments become
  the note and set the countries of the days; a preview compares every row with the spreadsheet before anything is stored,
  undo removes the import again (#1932).

### Fixed
- An unclosed phone block in the office stylesheet (since 2.91) made the later office styles (invoice series, equipment
  value, travel expenses) apply on phones only (#1932).

## [2.94.1] - 2026-10-18

### Fixed
- Booking page settings: the opening hours use the app's own time picker instead of the browser's time field; CI fixes of 2.94.0 (#1929).

## [2.94.0] - 2026-10-18

Appointment booking for customers, leads before the sales pipeline, Enter in the chats makes a new line.

### Added
- Booking page (Calendar > Calendars > Booking page...): customers book a time with you on a public page without an
  account. Appointment types with duration, buffer, notice and days ahead; free times are your opening hours minus busy
  events, accepted invitations, subscriptions, absences and open bookings, customers never see anything of your calendars.
  The customer confirms by mail, then Kalmido makes the event, a contact and (if chosen) a lead in the office; cancel links
  for the customer and a list with *Call off...* for you. Spam protection without outside services: mail confirmation,
  rate limits, a hidden field, at most 3 open bookings per address. Works without an organisation; separate from the
  disposition (#1929).
- Leads before the sales pipeline: a first column *Leads* with source, next step and follow-up day (due ones marked),
  *Convert to client* (a matching client is suggested, undo possible) and a CSV import with preview and duplicate check by
  e-mail. Leads stay out of the sums and the forecast. Agents with the office switch list, add and update leads (next step,
  follow-up, note) through `/api/v1/office/leads` and three MCP tools, never convert or delete (#1930).

### Changed
- Team chat and agent chat (also editing a message): Enter makes a new line, Ctrl+Enter or Cmd+Enter sends, like the
  comments; the phone keyboard shows a return key, the send button names the shortcut (#2024).

## [2.93.1] - 2026-10-18

### Fixed
- Customer signing page: the checksum of the document wraps on phones instead of running out sideways (#1927).

## [2.93.0] - 2026-10-18

Documents from templates with a customer signature, and a logbook in the office.

### Added
- Office > Documents (admins; a person without organisation in the personal office): own templates for contracts, order
  confirmations and NDAs with variables from client, project, quotation and company; three samples in German and English
  to take over (no legal advice). A document for a client (optionally with project and quotation) shows a live preview,
  *Finalise* freezes the text (SHA-256) and files the PDF in the client's folder of the documents; the client page lists
  them, a quotation offers *Create order confirmation* (#1927).
- Signature by customer link for such documents: the same simple electronic signature as the quotation approval (name +
  confirmation, time, checksum); the signed PDF with a signature block is filed next to the original (#1927).
- Travel expenses > Logbook: vehicles (private car with mileage allowance or company car), drives with odometer (km is
  computed, gaps shown as a warning), kind business / private / home - workplace, client and project; every change is
  logged with the values before, deleting can be undone. Business drives go into the travel expenses with one click
  (once, without amounts). Year report per vehicle with business share and mileage allowance (rate per year), CSV / PDF
  with the change log (#1928).
- The mileage allowance of business drives with a private car is its own expense line in the income/expense statement
  (2.90). No tax advice (#1928).

### Fixed
- Office: the styles after the subscriptions block applied on phones only (a bracket missing since 2.91.0).

## [2.92.3] - 2026-10-18

### Fixed
- Opening the equipment page directly no longer stops with an error while the office is still loading (2.92.2).
- The inline title field in a task row keeps its height again; the common field height of 2.92.2 (#1952) is only for forms (#1622).

### Changed
- Start-up budget raised by about one percent for the office menu and the field sizes of 2.92.2 (tools/perf_budget.json).

## [2.92.2] - 2026-10-18

Freelancer parity, an office menu in four groups, import targets you confirm, Paperless-ngx in the settings and a round of polish.

### Added
- Before every import (Paperless-ngx connection and ZIP, tasks from Todoist / Trello / Asana / Microsoft To Do / TickTick / ICS,
  contacts, calendars, budget CSV, office data, wiki pages, account move, feeds) Kalmido says in words where the data goes - an
  organisation (and who sees it) or your private space - and asks first; from an organisation, *Rather to private* imports into
  your own space instead (#1940).
- Organisations can use their own picture as their symbol instead of an emoji: set by their admins, shown to members only,
  sealed with the organisation's key (#1913).
- The office has one menu in four groups - Sell, Money, On the road, Administration - instead of two tab rows; on the phone a
  start page with four tiles and the key figures; the path shows only on detail pages (#1917). Bookkeeping, bank and
  subscriptions & tools sit under Money, contracts & insurance under Administration.
- Search (Mod+K) finds the Paperless-ngx import, the sub-points of every area, the senders, document types and tags of your
  documents and the top folders of your files (#1934).
- Document rows in the office (quotations, invoices, credit notes, reminders) have their own menu: dots button, right click or a
  long press - open, duplicate, preview, e-invoice XML, DATEV, delete (#1920).
- New test guard `freelancer_coverage`: every route is checked for a person without an organisation or carries a reason; the
  live update refuses a release when it is red (#1919). The sweep found no function that needs an organisation (#1918).

### Changed
- Paperless-ngx moved to *Settings > Integrations* (per workspace); the documents' settings keep the progress of a running import
  and a jump there. The progress says it runs in the background - and to keep the window open while a file uploads (#1936, #1935).
- The list column *Date* is called *Due*; an empty cell shows a dash (#1914).
- Pinned chat messages stand one below the other; from three on the area scrolls on its own (#1909).
- Sidebar: search and workspace in one line, the workspace as a round button - also without an organisation (#1933).
- Every dialog with a header can be moved; the background behind a dialog darkens less (#1937).
- One font size and field height in all forms (16 px on touch screens, against the zoom on iOS); dates and numbers in the normal
  font with even digits (#1952).
- Approval cards: the app's own thumbs instead of emoji; while a card is open, the reactions below it show no thumbs, and a
  thumb no longer decides an approval or permission card - only its Yes / No buttons do (#1963).
- Dragging is smooth everywhere: panel and column widths, chat windows and dividers, dialogs, tasks in lists and boards (mouse
  and touch), calendar, mind map, timeline and the smaller drag places update once per frame and store on release (#1965).

### Fixed
- The Paperless-ngx import progress no longer stops when the settings are closed and opened again; it asks again after a lost
  answer and reports when it is done (#1938).

## [2.92.1] - 2026-10-18

CI fixes of 2.92.0 (and 2.91.0).

### Fixed
- Tests: the office view counts every tab of its tab list (bookkeeping, bank, subscriptions, contracts joined); the pdf
  module lists the Word / Excel preview; a task-detail UI test waits until the client state exists (#1925, #1926).
- French, Italian and Dutch name the Basket in the tax dates hint (#1922).

## [2.92.0] - 2026-10-18

Contracts and insurance in the office, equipment value, Word and Excel preview, fixes from the 2.88 device tests.

### Added
- Office > Contracts & insurance (admins; a person without organisation in the personal office): insurances, rent,
  leasing, service providers with term, notice period, contribution and document; the last day to cancel becomes a task
  in a list you pick (agents that see it can remind you, `contract_notice` with `office: true`), contributions flow into
  the cash flow and show read-only under the fixed costs (#1925).
- Equipment: purchase date, net price, serial number, vendor and receipt (taken over from a receipt); depreciation with a
  suggested useful life (GWG up to 800 EUR at once, else linear by the month) and the book value per year; new and current
  value for the insurance, sums, insurance list as CSV / PDF, the policy that covers a device. Prices and values are
  encrypted and reach only admins; the year's depreciation counts in the income/expense statement (2.90), the
  device's receipt there only with its input tax. No tax advice (#1931).
- Word (.docx) and Excel (.xlsx) preview for task files, comments, project files and the file store, read in a sandboxed
  process; their text is searchable and readable for agents. *Summarize* in the preview of a task file asks a connected
  agent that may see the task (a comment that mentions it); Kalmido calls no language model itself (#1926).

### Fixed
- Delete account: the deleting admin is preselected as the new owner of the lists, else nobody (the button waits for a
  choice); invited accounts that never signed in come last (#2008).
- Quotation on the phone: the "Saved / Undo" message no longer covers the "In the cash flow" choice (#2009).
- User list on the phone: the selection bar sits at the bottom, the list no longer jumps on the first tick (#2010).

## [2.91.0] - 2026-10-18

Recurring invoices, an overview of subscriptions and tools.

### Added
- Invoice series: any invoice can be repeated monthly, quarterly or yearly (start, optional last period). Every period
  makes a normal invoice from the template with its period of service; placeholders `{period}`, `{month}`, `{quarter}`,
  `{year}` are filled in the texts. By default a draft waits for you (a task in your inbox links to it); *Send
  automatically* finalises and mails it, with the next number and the e-invoice as always. Series are listed above the
  invoices (pause, make now, edit, delete with undo) (#1923).
- Cash flow: the expected income of invoice series shows as *Invoice series* until the invoice exists (#1923).
- Office tab *Subscriptions & tools*: every fixed cost marked as a subscription with price, next renewal, last day to
  cancel, users and a *hardly used* switch; sums per month and per year and what the hardly used ones cost; suggestions
  for fixed costs that look like a subscription; CSV export. Subscriptions are ordinary fixed costs, the cash flow counts
  them once (#1924).
- A reminder before the last day to cancel a subscription as a task in the chosen admin's inbox (never an amount); the
  fixed costs import reads the optional columns *Abo* and *Kündigungsfrist* (#1924).

### Changed
- Agent API: invoices made by a series carry `series_id` and `series_period` (#1923).

### Notes
- Database: new tables `office_inv_series`, `office_sub_reminders` and new columns on `office_docs` / `office_fixed_costs`,
  all additive. Going back to the previous version works; there, duplicating an invoice made by a series fails until you
  update again.
## [2.90.0] - 2026-10-18

Bookkeeping light and tax dates in *Office & finance* (#1921, #1922): the running bookkeeping of a self-employed person
without a second tool. Works the same in a personal office without an organisation. No tax advice; Kalmido sends nothing
to the tax office (no ELSTER, no payroll).

### Added
- **Bookkeeping** tab: the income/expense statement of a year (payments received by VAT rate against receipts and travel
  expenses, by category) with CSV and PDF export, and the VAT return figures (fields 81, 86, 21, 45, 66, 83) per month or
  quarter to type into ELSTER, on cash or accrual basis.
- **Photograph receipt**: the phone camera puts a receipt straight into the office's documents; amount and date come from
  the existing text recognition, category and VAT rate (new: 19 / 7 / 0 % or unknown, also in the document's receipt slot)
  are added in one sheet.
- **Tax reserve**: a percentage of the net money received, shown per month in the cash flow with "freely available".
- **Bank** tab: import a bank statement (CSV or CAMT.052 / .053), duplicates skipped, every booking with suggestions -
  money in to open invoices (records the payment, partly paid too), money out to receipts; private / ignore, undo,
  take back an import. Amounts and counterparts are encrypted at rest.
- **Tax dates**: VAT return (monthly / quarterly, permanent extension), income tax and trade tax prepayments as one
  recurring task each, with lead time, linked to the VAT return figures.

### Fixed
- Documents: the text recognition no longer overwrites an amount typed in while it was still running.
## [2.89.1] - 2026-10-18

CI fixes of 2.89.0.

### Fixed
- Tests: the workspace guard and the route scan know the tables; a task-detail UI test waits for the loaded state (#1916).

## [2.89.0] - 2026-10-18

Tables: Excel made simple, with Kalmido values in the cells.

### Added
- Tables (module *Tables*, off by default): own area in the sidebar, private or per organisation, optionally attached
  to a project or list (then `hier.zeit_gesamt` and friends know its data). Grid with keyboard like a spreadsheet,
  copy and paste of ranges, sorting and filters, every action one undo step (#1916).
- Formulas: `+ - * /`, `%`, text with `&`, comparisons, SUMME, MITTELWERT, MIN, MAX, ANZAHL, WENN, RUNDEN, HEUTE, TAGE
  (English names work too), date + days, own cell names (`tagessatz` instead of `B4`), column names as ranges and
  completion after `=` (#1916).
- Kalmido variables: `projekt.<name>.zeit_gesamt`, `liste.<name>.offen`, `kunde.<name>.satz`, `aufgabe.<id>.status` …,
  stored by id, so renaming a project, list, client, cell or column updates every formula; a deleted source shows
  *Source deleted* with the last value you saw; every value is computed with the viewer's own rights (#1916).
- Transparency: cells coloured by origin (own number, formula, Kalmido value in the accent colour, frozen grey),
  *Comes from / Goes into* in the side panel, dependency arrows, the sources of a sheet, *Freeze value* per cell (#1916).
- Selection columns with own options and one colour each, for the cell or the whole row; filter and sort by them (#1916).
- Import and export as CSV and Excel (.xlsx with formulas, number formats, drop-down validation and colours) (#1916).
- Team: saving per cell, *X is editing* and automatic refresh every few seconds (#1916).
- Step 2: *Create tasks from rows*, *Turn into a quotation* (draft in Office) and *List as rows* (live task values),
  only by button, with a trace in both directions and undo (#1916).
- Agent API and MCP: list, read, create a whole sheet in one call (columns, selection options with colours, rows,
  formulas), set cells, append rows, add columns, undo a batch; scopes `sheets:read` / `sheets:write`; every agent
  change is marked and can be taken back, a created sheet as a whole (#1916).

### Changed
- The account export carries the person's private tables, the organisation export the organisation's (#1916).

## [2.88.1] - 2026-10-18

### Fixed
- User administration (#1980): the tick boxes of the user list have a 44 px touch target on phones; the delete text uses
  the basket's current name in every language.

## [2.88.0] - 2026-10-18

Quotations in the cash flow plan, user administration for hundreds of accounts.

### Added
- Cash flow: sent quotations now count as *open quotation* (dashed), accepted ones as before; of several versions of a
  quotation only the newest counts (#1915).
- Quotations: *Duplicate* creates a new version of the quotation; the switch *In the cash flow* (Automatic / Yes / No)
  decides which version counts, also on sent or finalised quotations (#1915).
- User administration: search, filters (active, disabled, admins, invited, awaiting approval, agents) and pages of 50 with
  the total; select several accounts to disable, enable or add them to an organisation (#1980).
- Deleting an account that owns lists: hand all lists to one person (default) or delete them along after typing the user
  name; lists with receipts are only handed over, a warning shows when nobody else holds the key of a locked list.
  Organisation admins delete only accounts that belong to their organisation alone and have an empty private space,
  otherwise they remove the person from the organisation and choose who gets its lists (#1980).

### Changed
- Cash flow: once an invoice for any version of a quotation is finalised, the whole quotation leaves the plan (before:
  only the invoiced part was taken off) (#1915).
- Agent API: quotations carry `version_of` and `cashflow`; `cashflow` can be set in the PATCH of an agent's own draft (#1915).

## [2.87.0] - 2026-10-18

Hardening from the security audit, part 3 (two high findings at the organisation boundary) and a calmer agent chat header.

### Security
- Appointments: a person who leaves an organisation or is removed from it (also with their agents) is no longer invited
  to the appointments in its calendars - no view, reply, reminder push or CalDAV entry. Appointments in an organisation
  calendar invite only people of that organisation (in the app with a clear message, over CalDAV and ICS); an
  appointment or a calendar with outside guests moves into an organisation only after they are removed, and old
  invitation notes of former members disappear. Guests from outside are invited from a private calendar as before.
- Lists: a list is handed over only to people you can see (or who are members of it); any other account answers exactly
  like an unknown one. Freelancers without an organisation hand lists to their contacts as before.
- The nightly boundary check finds and removes left-over invitations of former members (and counts those of agents).

### Changed
- Agent chat: the info button next to the agent's name is gone, so it no longer covers the usage ring; the note on when an
  agent answers is now in the agent's settings (own agents: *Permissions*, team agents: *Edit agent*).

## [2.86.0] - 2026-10-17

Hardening from the security audit, part 1 (low findings, #1896). No new features; normal use stays the same.

### Security
- Sign-in: a flood of reset or login attempts from foreign addresses no longer locks the owner out (addresses the
  account signed in from recently and re-authentication in a signed-in session are exempt); sign-in links re-check admin
  status and the two-factor policy when used; an SSO account sets its first local password only right after a fresh sign-in.
- Child accounts: no way past their write limit through *Share* or the drop address; instance admins see and manage only
  the children of their own organisations (a household without organisation as before), and the state lists only children
  the person sees. *Share* refuses foreign sites and logs no form contents.
- Rights: approval decisions need write access (viewers are no approvers); history lines in a blocking task only with write
  access to it; a parent task is checked for access before its rules (no existence hint); list rules over the API only for
  owners and list admins, as in the app; restoring wiped time entries of others only as they were deleted; tasks of
  organisation-wide lists move only into equally open lists.
- Office: clients stay in their workspace; bank lines, bank fields and DATEV export data only for office admins; an invoice
  from time tracking counts only lists the creator sees; a decided quotation PDF only until the link expires (else 30 days);
  DATEV text fields starting with = + - @ are protected; document mails have a day limit (150 per person, 300 per
  organisation, 20 per address).
- Files: uploads stop reading at the size limit and "too large" is a clear message everywhere (it showed as "session
  expired" outside the contact import); inline PDFs open in a sandbox; public forms have an hourly file budget
  (`KALMIDO_FORM_FILES_MB_HOUR`, default 200); final deletion in the file store removes files only after saving; job chat
  name prefixes are escaped in searches.
- Agents: sharing over the API checks visibility before an approval names anyone; the approval card of a batch change names
  fields and lists; a daily push limit per agent and person (`KALMIDO_AGENT_PUSH_DAY`, default 500, the message still
  arrives); events of lists the agent no longer sees are left out; the workload shows an agent only people who share a list
  with it; a token limited to certain lists cannot create lists on import; participants see only the people of the task
  in the mention picker.
- Audit part 2, before the merge of 2.81-2.86: archived documents of the legacy import - members only assign the client,
  amount, tax lines and *Paid* only an office admin, no negative amounts, the history marks a member's change (#1968);
  hub mail - a mail from the person's own address counts as forwarded (the original sender picks the client) only when the
  receiving mail server confirmed that domain (DKIM / DMARC / SPF pass, `KALMIDO_MAIL_AUTHSERV_ID`), else it stays *Not
  assigned*; the API task search finds tasks by the recognised text of their files only with `attachments:read`.

## [2.85.0] - 2026-10-17

Feeds (RSS reader), list lock hint, test clock.

### Added
- *At home*: **Feeds**, an RSS / Atom reader of your own (module, off by default; private to you, agents do not see it).
  Follow up to 100 feeds, the server fetches them hourly and keeps articles for 30 days; filter per feed, unread only,
  mark read (with undo), *Read later* puts one task with the link into your *Read later* list. OPML import and export.
  Fetching only goes to public http / https addresses (also after redirects), with time and size limits; feeds with a
  DTD are refused and article texts are shown as plain text (#1162).

### Fixed
- *Edit list* no longer says the own encryption is not set up right after loading the app, when it is; the lock switch is
  free at once. The same for the wiki area dialog (#1904).
- Tests take "today" in the app's time zone (Europe/Berlin) instead of UTC, so they no longer fail between midnight and
  2 am; a test clock (`KALMIDO_TEST_NOW`) checks that window (#1863).

## [2.84.0] - 2026-10-17

E-mails filed at clients and projects.

### Added
- Clients and projects: file e-mails at them. Every client and project has its own address, every person one filing
  address per workspace (*Office > Clients > E-mail filing*); mails to it are matched by the sender (client e-mail,
  contact persons, linked contacts), forwarded mails by their original sender, anything unclear waits under
  *Not assigned*. Filed mails are searchable on the client card and the project page; the original mail and its
  attachments land in the file store under *E-mails / client / date subject* and go through the usual upload checks.
  No mail client: nothing is sent or answered. Needs the mail import (IMAP) of *Tasks by e-mail* (#1198).
- The account export includes your own private filed e-mails (#1903).

### Fixed
- *Switch all modules on* also switches the household budget on, like every other module (#1808).
- Tests: a tags overview check took the UTC date as today and failed at night (#1868).

## [2.83.0] - 2026-10-17

Organisation view, list themes, team room.

### Added
- Appearance: ready-made themes *Control room* (as before), *Paper* (warm, light), *Night* (deep blue) and *Contrast*,
  per device; accent, density and font stay your own (#1427).
- Lists and folders: a header strip - gradient from the list colour, dots, lines, grid or an own picture (JPEG / PNG /
  WebP up to 2 MB, re-encoded without metadata, stored sealed like attachments; not for locked lists); low on the phone,
  can be switched off per device. Progress rings at the lists in the sidebar, a short tick animation (none with reduced
  motion) and a calm K drawing on empty pages (#1427).
- Organisation admins change an agent's colour right on its person card (#1775).
- Team rooms have a button *Open in split window* in their header, so it works on the iPhone too (#1774).

### Changed
- The organisation view shows only what belongs to the organisation: Home, Habits, Review and Notes are hidden there
  (sidebar, phone tab bar, search); an old link to them switches quietly to the private space (#1845).
- Organisation-wide lists that every member may edit: tasks can be assigned to members who have not joined; those tasks
  show in their Today / All, the calendar link and CalDAV (read only). Other tasks of such lists still only after joining (#1725).

### Fixed
- The hint of the monthly cash flow task says *basket*, not *inbox*, in every language (#1838).

## [2.82.0] - 2026-10-17

Leftover fixes: tasks, agents, chat.

### Security
- Security fix (permission boundaries): folder defaults, birthday tasks of moved contacts, the personal *My tasks*
  order and the related-tasks cache keep to the person's rights and visibility (#1464, #1831, #1832, #1880).
- Security fix (agent permissions): an agent that is a list admin no longer renames, recolours or archives the list (#1467).

### Fixed
- Locked lists: a title or text beginning with `e2e1:` no longer blocks opening the lock; it gets a leading space and a
  short hint (#1878).
- Agents page: *Load more* stops at the scan limit also after a full page (#1465).
- Layout proposals of an agent: the buttons read *Accept* / *Decline* (#1821).
- Pinning: *Undo* closes when you switch to another conversation; the team chat takes live changes while you type; the
  agent API chat feed with `user_id` also returns the conversation's `pins` (#1862).
- Reviews: *Approve* / *Back* are 44 px high on the phone, the history names the reviewer instead of *Deleted user*,
  and the public form page translates *Sent as* (#1880).

## [2.81.0] - 2026-10-17

Remaining fixes: office, import, clients, uploads. Contains security fixes.

### Security
- Security fix (customer portal): signing out ends the portal session on the server too. **Portal users sign in once
  again after the update** (#1866).
- Security fix (forms): a form page can be sent only once; at most 50 confirmation mails per form and day (#1866).
- Security fix (rate limits): reading the address from archive PDFs shares the per-account PDF limit (#1463).
- Security fix (agent data): agents see only name and role of a client's contact persons (#1466).

### Added
- Office archive: client, amount (net per tax rate - 19 %, 7 %, 0 %, reverse charge - Kalmido computes the gross) and
  *Paid* can be corrected after the import by everyone in the office, with a history per entry and undo; the archive
  list shows the client and filters by it. Number and file stay unchanged (#1834).
- Org export: includes customer portal reports (without status links) (#1866).
- Agent API: the search names the attachment whose text matched (`file_hit`) (#1856).
- Self-hosting: `KALMIDO_PHOTO_MAX_PIXELS` limits photo re-encoding on small servers (#1856).

### Fixed
- DATEV export: issued invoices keep the customer number they were locked with, also after the client is changed or
  merged (#1867).
- Paperless ZIP import: the export is checked in the background (*Export is being checked ...*), not in the upload
  request; lower entry limits (#1874). A run that took too long no longer runs twice, and exports of two different
  Paperless servers keep their own rules (#1875).
- Archive import: a failed import leaves no half-written file behind (#1462).
- Client dialog: if the linked contact was deleted meanwhile, the link is removed and the client is saved with a hint (#1852).
- Sharing to Kalmido: a refused file is reported instead of dropped silently (#1856). The nightly boundary check also
  covers recognised file texts; a long text recognition is resumed after 45 instead of 30 minutes (#1856).
- Self-hosting: concurrent first requests print one setup code; the backup warning counts from re-enabling; the install
  scripts point to the newest setup code in the log (#1627).
## [2.80.3] - 2026-10-18

Live fix from the device test of 2.80.2.

### Fixed
- Bell: the panel lists what counts for you under *Needs you*, no longer under *For your information* (#1943).
- Tests: robust after midnight and on Sundays, the test run is split into 11 parts.

## [2.80.2] - 2026-10-18

Live fixes: the bell, document previews of imports, switching the workspace.

### Fixed
- Bell: comments of agents that reach you count at the bell again - with *only replies to me* their replies, mentions and
  approval cards, with *all comments* every agent comment; other agent actions (completing, status, new tasks) stay
  Activity without a number. A bundle of comments counts as soon as one of them is for you (#1943).
- Documents: imports that bring their own text (Paperless, ZIP archive) get a preview image and the QR / archive number check
  again; documents imported earlier get their missing preview once in the background after the update, a few at a time
  (`KALMIDO_DOCS_THUMB_FILL=off` turns it off) (#1944).
- Documents: switching the workspace (organisation <-> private) reloads the list, the *To check* count and the filters at once
  and closes a document of the other workspace; an answer that arrives late for the old workspace is dropped. An open wiki
  page closes on the switch too. A new guard test switches every view tied to a workspace in both directions (#1945).

## [2.80.1] - 2026-10-17

CI fixes for the 2.80 bundle.

- Browser demo: the evening review card in Today no longer stops the demo after the end of the working day (the demo's
  review answer had no *tomorrow* part).
- Office catalog: the control character filter is written with escapes instead of raw bidirectional characters (bandit B613).

## [2.80.0] - 2026-10-17

Small fixes: import, clients, contacts.

### Fixed
- Import (archive documents): amounts with thousands separators are read correctly - `2.436,53` was refused and `1.500`
  was stored as 1.50; `2,436.53`, `€` / `EUR` and spaces work too, also when correcting an archived document (#1837).
- Import: a client created while the app is open shows in the client choice of the import without reloading the page (#1836).
- Quotations / invoices: the client field is always there when clients are on; without clients in the area it shows a
  hint and *Add client* (created in the office's organisation, you stay on the document); new clients show at once, and
  the office follows a workspace switch reliably (#1842).
- Merging contacts: undo also links client contact persons again that lie in another workspace or did not fit the
  address book (#1885).
- Phone: the *Undo* button of a message is at least 44 px high on every touch device, and the contacts' selection bar
  wraps instead of scrolling sideways (#1897).
- Agent chat usage ring: further quota windows are named (week incl. extra usage, Opus, Sonnet), unknown ones read
  *Other quota* instead of the raw English key, and an idle weekly window at 0 % is left out (#1841).
- Bundle G3 + G4 + 2.78-2.80 (live in one step): the list name in the task rows (Today, matrix, folders) was gone after a
  merge and is back; *Switch on all modules* includes the household budget; `DELETE /api/v1/tasks/{id}/links/{list_id}`
  matches its OpenAPI entry; the cash flow's monthly check task text says *Basket* in every language; two case checks in
  queries follow PostgreSQL (`ILIKE`). Tests: the newest suites are spread over five shards (shard 10 ran past the limit).

## [2.79.0] - 2026-10-17

Security release: the fixes of the security audit #476, part 1 (one finding "high", nine "medium"; no critical finding).

### Action needed (self-hosted servers)
- **Reverse proxy on the host in front of a published Docker port:** `KALMIDO_TRUSTED_PROXIES` now defaults to loopback
  only (`127.0.0.1,::1`); the docker bridge gateway 172.17.0.1 is no longer believed by default. If your proxy runs on the
  host and reaches Kalmido through a port published on Docker's default bridge, set
  `KALMIDO_TRUSTED_PROXIES=127.0.0.1,::1,172.17.0.1` in `.env` - otherwise login lockouts count per proxy instead of per
  client and CalDAV may see plain http. Proxies on their own Docker network had to be listed already and are not affected.
  Before, with a port published directly to the internet, every client could send forged `X-Forwarded-For` headers.
- **Virus scanner strict mode:** with a scanner configured (`KALMIDO_CLAMD`), an upload the scanner could not check
  (scanner down, error) is held back (403) until the later scan finds it clean. A file larger than `KALMIDO_CLAMD_MAX_MB`
  is never scanned and stays readable with its *Unchecked* mark - keep the upload limit at or below it.
  `KALMIDO_CLAMD_STRICT=0` keeps the behaviour of 2.61-2.78.

### Security
- Importing an ICS file or saving an event from a calendar app (CalDAV) invited any account of the server named by its
  Kalmido id as an attendee - with a News item and a push, also across organisations. Now only people you may see are
  invited this way; other ids stay a plain address (#1886).
- A personal API token limited to some lists (or without calendar / contacts) could create a CalDAV app password with full
  access. Creating app passwords through the API now needs a token for all lists with `calendar` and `contacts` (#1887).
- An admin token with read-only scopes (`read`, `admin-read`) could write admin routes such as the server announcement.
  Admin routes now need their own scope as well (#1888).
- The first OIDC login could take over an existing local account (also an admin, bypassing its second factor) through a
  matching user name claim alone. A user name match now needs the same verified e-mail (accounts made for SSO without
  password and e-mail link as before); admins, accounts with a second
  factor and child accounts are linked only from their own open session (log in with the password, then use the provider's
  button once in the same browser). Accounts already linked are not affected (#1889).
- About 100 wrong invitation / password / sign-in link tokens from a few addresses locked these links for everybody for 15
  minutes. The limit now counts per address only (#1890).
- Child accounts kept working API tokens and CalDAV app passwords made before; the API and CalDAV now refuse child accounts
  and making an account a child account deletes its tokens and app passwords (#1891).
- A token without the `private` scope saw the titles and notes of health and budget tasks through its own time entries.
  These entries are left out for such tokens and for agents (#1892).
- Uploads the virus scanner could not check were readable at once, also through public links (strict mode above, #1893).

### Fixed
- Backups now contain the files of agent chats, the receipts of the household budget and the document previews; before,
  their database rows were saved but the files were skipped. The manifest counts files outside the known folders
  (`skipped_files`). A server before 2.79 refuses archives with these new members (#1894).

## [2.78.0] - 2026-10-17

### Added
- **Duplicate list** (list menu *Duplicate list…* and the button *Duplicate* in the list dialog, next to *Save as
  template*): a new list of yours named *<list> (copy)* with the sections, the open tasks with their subtasks, tags,
  priorities and dates as they are (an overdue task stays overdue), custom fields and their values, dependencies,
  milestones, ticket types, the Playbook, the notepads, the page arrangement and the block colours - the same parts a list
  template carries since 2.63.0. *Copy completed tasks too* brings the completed and won't-do tasks along with their state.
  Members, shares, assignees and the public link stay with the original; the copy lands in your folder of the list and in
  the original's workspace when you belong to it (a private list stays private). Participants cannot duplicate a list
  (#1881).
- REST API `POST /api/v1/lists/{id}/duplicate` (`structure`; `{name?, done?, folder?}` -> `{list_id}`) and the MCP tool
  `duplicate_list`.

### Security
- A list locked in the browser (end-to-end) cannot be duplicated (`409 list_e2e`, like saving it as a template): the copy
  would have been an unlocked list. Very large lists are refused before the copy is built (audit #476 N35).

## [2.77.0] - 2026-10-17

### Added
- **Pack catalogue** (Office & finance > Settings > Packs): search country and industry packs by name, code or author, see
  version, author, licence and a badge **Verified** / **Community** (community packs ask with a warning first), install,
  update and uninstall them per office (an organisation or a person's own office). Packs are data only (rates, formats,
  labels, texts), never code; every file must match the catalogue's SHA-256, its schema and a size limit (#1023).
- Updates are shown, never installed automatically; a pack still in use (the office's country pack, a switched-on industry
  pack, open quotations) cannot be uninstalled and says why. Install, update and uninstall can be undone.
- Finalised quotations and invoices keep the exact pack they were made with (version, SHA-256, source): updating or removing
  a pack never changes them.
- For operators: `KALMIDO_PACKS_CATALOG` (the catalogue's address; empty = only the built-in packs, no network call),
  `KALMIDO_PACKS_ALLOW_HOSTS`, the tool `tools/packs_catalog.py` and [docs/PACKS.md](docs/PACKS.md) (index format,
  checks, your own catalogue); contributing packs: [CONTRIBUTING.md](CONTRIBUTING.md).

## [2.76.0] - 2026-10-17

### Added
- Built-in assistant (#1411), the one exception to "Kalmido never calls a language model": an operator points Kalmido at a
  single OpenAI-compatible chat model (`KALMIDO_AI_BASE_URL`, `KALMIDO_AI_MODEL`, `KALMIDO_AI_KEY_FILE`; a provider in the
  EU, or Ollama on the same server). Off by default: without the variables there is no menu entry and the routes answer
  404. Every person switches it on for themselves (*Settings > Assistant*) and ticks the lists it may read; basket tasks go
  only when you pick them. It summarises a task with its notes, comments or mail text, drafts a short reply, pulls tasks out
  of a text, suggests tags and a due date, sorts the basket and proposes a day plan - always as a proposal card with
  yes / no, never a direct change. Locked notes, health lists, attachments and office documents never go to the model;
  every call leaves a log line with numbers only, the key appears nowhere. Admins see calls and errors per day. Your own
  agents stay as they are (docs/ASSISTANT.md, docs/PRIVACY-ASSISTANT-DRAFT.md for the operator's privacy texts).
## [2.75.0] - 2026-10-17

### Added
- Supporter licence for self-hosted servers, like Immich: voluntary, paid once, unlocks nothing. Settings > Help >
  "Support Kalmido" takes a server licence (admins) or a personal licence, checked offline (Ed25519, no network), and shows
  a small "Supporter" badge under About and in Account. Admins see a quiet hint at most once a year (switchable off, never
  in the first 30 days). Optional payment link via `KALMIDO_SUPPORT_URL`. Hidden completely on hosted servers
  (`KALMIDO_HOSTED=1`: no section, no hint, no badge, the routes answer 404) (#338).
- Browser demo starts like a new account: inbox, "Getting started" and the welcome tour; the sample project only on request
  and removable again. Old demo data is kept (#1653).
- Office & finance in the browser demo: clients, services, quotations, invoices and payments with the same sums and VAT as
  the server; a print view in the browser instead of the PDF (#1653).

### Changed
- The browser demo is rebuilt from the current sources with every release and still works without any network connection
  (CSP `connect-src 'none'`, now tested) (#1653).

## [2.74.0] - 2026-10-17

### Added
- **Several Kalmido servers in one app** (#661): *Settings > Account > Servers* connects accounts on other Kalmido servers
  (work + home) with a connection code, or an address and an API token. Their lists appear as their own group in the
  sidebar, their tasks in Today, Basket, Search, the calendar and News, each with the server's short name in its colour so
  nothing gets mixed up. Open, edit, complete and delete tasks of the other server without switching; the quick add shows
  where a task goes. "Move to another server…" asks in plain words first (comments and attachments stay in the old
  server's trash). Data stays on its server: your own server talks to the other server's API, the token is sealed and never
  reaches the browser, nothing of the other server is stored, agents see none of it.
- **Moving between app.kalmido.com and your own server** (#1473): *Settings > Data > Export everything* builds one file with
  your lists, tasks, comments, files, calendars, contacts and settings (ZIP with JSON and checksums), also usable as a copy
  of your data under the GDPR. *Take over from a Kalmido export* uploads it on another server (large files in pieces),
  checks it, shows a preview with the people of your lists matched to accounts there (shared only where you tick it,
  missing people can be invited by an admin), imports privately or into an organisation and can be undone.
- Organisation exports (2.42) can be taken over into an organisation on another server with the recovery key (stage 1:
  lists, tasks, comments, files, calendars and address books; members matched by e-mail).

## [2.73.0] - 2026-10-17

### Added
- **Household budget** at home (#1333): module *Budget* (off by default) under *Settings > Modules > At home*. A budget is a
  list of its own: entries (income / expense) with category, counterpart, note and receipts, categories with a monthly
  limit, the month view with planned / spent / left, the last six months as bars and a card in *Home & life*.
- Recurring entries (monthly, quarterly, yearly, from / until a month) are templates: *Open this month* books them with
  one tap (once per month); *Take over from contracts* turns contracts of the same space into recurring entries and
  shows when a contract's cost changed later (*Match*).
- CSV import of a bank statement (no bank access): delimiter, header lines, German and English numbers, signs and separate
  debit / credit columns are recognised, the column mapping is remembered per header, duplicates and broken lines are
  left out, a category is suggested from earlier entries and a line that matches an open recurring entry is booked on it.
- Shared like any list (family, read-only or writing). Agents never see a budget (like Health), API tokens only with the
  scope `private`; no API v1 / MCP routes. Amounts, texts and receipts are encrypted at rest with the key of the list's
  space; the start-up pass and `orgcrypt_cli decrypt-all` / `decrypt-private` cover the new tables.

## [2.72.0] - 2026-10-17

Project automation: lists that do the routine steps themselves, and one task that lives in several lists.

### Added
- **Rules in lists:** in the list settings the owner and the list admins set up rules in one sentence: *When* a task
  comes into a column, is completed, is opened again, gets a list tag or its due date is reached, *then* assign it to a
  person of the list, set or remove the due date, write a comment or move it to a column or another list of the same
  workspace. A rule runs with the rights of the person who set it up and pauses itself (with the reason) when a right is
  missing. A change made by a rule never starts another rule - no chains, no ping-pong. History and comments show
  "Rule <name>". Health lists, the inbox and locked lists have no rules (#1457).
- **A task in several lists:** "Show also in list…" in a task's menu puts it into a further list of the same workspace
  without a copy - one task, every change everywhere, its own column and place in the further list (also on the board).
  The row says "Also in <list>" / "From <list>"; "Remove from <list>" never deletes the task. Who sees it is decided by its
  own list only: someone who sees only the further list does not see the task. Other organisations, health and locked
  lists cannot be used. Statistics, search, calendar and exports count it once (#1459).

### Agents
- Rules: `GET /api/v1/lists/{id}/rules`, MCP `list_rules`; agents only propose a rule (proposal kind `rule`, MCP
  `propose_rule`); the owner or a list admin accepts it and then owns it.
- Tasks carry `also` (only the further lists the caller may see); `POST/DELETE /api/v1/tasks/{id}/links`, MCP
  `link_task_to_list` / `unlink_task_from_list`.

### Database
- New tables only: `list_rules`, `list_rule_runs`, `task_links`; new column `comments.rule_name` (default empty).
  Older versions ignore them.

## [2.71.0] - 2026-10-17

Agent workflows: three everyday jobs an agent prepares and you decide. The agent only proposes; nothing is sent, merged or
cancelled until a person applies it, and it works the same for freelancers without an organisation.

### Added
- **A meeting becomes tasks:** in the chat with an agent, "Turn a meeting into tasks" hands over notes and / or up to four
  photos (whiteboard, handwritten notes; on a phone the camera opens) for a list you choose. The agent proposes tasks with
  assignees and due dates; one card in the chat lists them with a tick each, "Create N tasks" creates the ticked ones in your
  name, one undo step. "Tasks from notes…" in the list menu takes photos too; health lists cannot be chosen (#1354).
- **Tidy up contacts:** "Find duplicates with an agent…" in the contacts. The agent gets only the name, company, e-mail
  addresses and phone numbers of one address book and proposes groups of duplicates. You check each group, pick the contact
  that stays and merge them with the 2.66 merge; undo takes the whole proposal back (#1357).
- **Contracts in view:** shortly before a contract's last day to cancel, an agent the contracts list is shared with sends
  one sentence on what the contract costs. Take it as a note on the contract (optionally with a reminder three days before
  the deadline) or discard it. Nothing is ever cancelled; amounts never appear in push texts (#1359).

### Agents
- `job_request` of kind `extract` may carry `input.images` (photos of the meeting, read with `get_attachment`, source chat).
- New proposal kind `merge` (`input.contacts`, answer `groups: [{target_id, ids, reason}]`).
- New event `contract_notice` and proposal kind `notice` (`POST /agent/proposals`, MCP `propose_contract_notice`).
- Reference launcher: capabilities `meeting_images`, `merge_proposal`, `contract_notice`.

### Security
- Health lists and the journal stay closed to agents; new tests cover events, proposals and the review.

## [2.70.0] - 2026-10-17

### Added
- Paperless-ngx import on hosted servers: only public HTTPS addresses there, the allow-list of internal hosts does not
  apply (#1846).
- Import from a Paperless-ngx export without a connection: upload the ZIP of `document_exporter` in the documents
  settings, with the same preview and mapping as the import over the address (#1846).
- Storage quota in the import: the preview shows what is needed and what is free; at a full storage the import stops
  cleanly ("after X of Y documents") (#1846).
- One import per server at a time; others wait in a queue and show their place (#1846).
- The matching rules of Paperless-ngx tags, correspondents and document types become document rules (any, all, literal,
  regex, fuzzy; case-sensitive kept; "auto" covered by Kalmido's learning), switchable in the preview, never twice (#1847).
- After every import the classifier learns the imported senders, types, tags and folders once, as confirmed examples (#1847).
- Document rules can be case-sensitive.

### Security
- Security fix: Paperless-ngx import (network boundary on hosted servers, upload handling).

## [2.69.0] - 2026-10-17

### Added
- Import old data with your own agent, starting with fixed costs: the agent reads the old data in any format and sends it in
  a fixed JSON format as an "Import" proposal. The card shows the same preview as the spreadsheet import (new / already
  there / error with reason, VAT rate per row, duplicates unticked); nothing is written before you accept it, then with
  your account and one undo step. Freelancers without an organisation import into their personal office (#1839).
- Agents: new permission "import" (off until you turn it on), route `POST /api/v1/agent/proposals/import`, MCP tool
  `propose_import`; the agent never sees the office (#1839).

## [2.68.0] - 2026-10-17

### Added
- Office > Cash flow: import fixed costs from a spreadsheet (.xlsx). A preview shows every row (amount, repeat, due month,
  category, VAT rate); duplicates (same name, amount and repeat) are marked and unticked, rows without a name or amount are
  shown with the reason and skipped; only "Import" writes. A template can be downloaded. Group rows become the category;
  quarterly costs become four yearly rows (#1838).
- Fixed costs have a category and a VAT rate (0 / 7 / 19 %). The list is grouped by category and shows net and gross; the
  cash flow counts gross and its totals switch between net and gross. Existing fixed costs keep 0 %, so their values do not
  change (#1838).
- Optional monthly task "Cash flow: check the actual state" on the 1st for a chosen office admin - with a link, never with
  amounts; switching it off ends the task (#1838).
- Timeline: when a task becomes due later, every task waiting on it moves along by the same number of days, down the whole
  chain, gaps kept - when dragging, in the task detail, through the API and for agents. A preview shows what moves while
  dragging; "N dependent tasks moved along" comes with one undo. Completed tasks, milestones, tasks without a date and tasks
  you cannot edit stay where they are and are named (#1865).
- "Pull the chain in": a task that became earlier does not drag its chain back by itself; a button (bar menu, task detail,
  the message) moves the chain up to right behind it (#1865).
- "Move dependent tasks along" is on from the start in new project lists. API / MCP: field `chain` in the answer,
  `shift_chain: false` turns it off for one change (#1865).

## [2.64.3] - 2026-10-17

### Added
- **Encrypted knowledge space** (lock per list, stage 3): an organisation admin (or the owner of the private space) can
  encrypt a whole knowledge space in the browser (*Knowledge pages > … > Encryption…*). Page names and texts are then
  encrypted with a key per space that every member of the organisation gets wrapped with their own key; the server
  stores only ciphertext and no links. Search, backlinks, "mentioned in", link suggestions, templates, renaming with its
  links and export / import as ZIP run in the browser. New members of the organisation wait until an admin releases the
  key; when a member who held it leaves, the key changes and the pages are encrypted again in the background. Agents
  have no access to an encrypted space; switching back needs the password (#1817).
- Settings > Administration > Encryption lists the encrypted knowledge spaces; a help paragraph in Settings > Account
  and new documentation explain how to export encrypted lists, chats and knowledge spaces and what is lost without the
  keys (docs/SELF-HOSTING.md *Encryption in the browser*, *Exporting encrypted content*; docs/WIKI.md, AGENT-SETUP.md).

### Security
- Security fix (encryption in the browser: knowledge pages and lists).

### Note
- Before going back to an older version, switch the encryption of every knowledge space off again (and open the lock of
  every list, as for 2.64.1 / 2.64.2): older versions show the encrypted names as page titles and do not guard such a
  space, and a backup of 2.64.3 is refused by older versions.

## [2.64.2] - 2026-10-17

### Added
- **Lock per list, stage 2**: when a member who held the key leaves a list with the lock (or the organisation), the
  browser of the next owner or list admin changes the list key automatically and encrypts the older contents again in the
  background (resumable, with progress; a button *Change the key now* for owners and list admins). The honest hint in the
  member dialog stays until that run is done. New members get every key generation and read older contents too (#1817).
- Attachments of tasks and comments in a list with the lock are encrypted in the browser with the list key; every member
  opens them, agents and the API see only "encrypted". Switching the lock on, the key change and the way back convert
  existing attachments in the browser. Project files and the other ways to add files (mail, API, sharing) are not
  available in such a list; a task with encrypted files stays in its list.
- The team chat of a list with the lock is encrypted with the list key; agents and the API read no text and cannot write
  there, search and *Save as task* leave it out, a mention still notifies the person.
- Safety numbers of all members of a list with the lock, reachable from its team chat and its attachments; a changed key
  is shown there too.

### Changed
- Pushes about a list with the lock show the neutral word in the language of the person who gets them, and a comment
  push names the list instead of quoting the comment.

### Note
- Before going back to an older version, open the lock of every list again (as for 2.64.1): older versions do not know
  the lock, and 2.64.1 cannot open the encrypted attachments and team chat messages of 2.64.2.

## [2.64.1] - 2026-10-17

### Added
- **Lock per list** (encrypted in the browser): the owner or a list admin can lock a list in the list dialog. Titles,
  descriptions, subtasks, comments, list notes, section names, text fields, links and code snippets of that list are then
  encrypted in the browser with a key per list that every member gets wrapped with their own key; the server stores only
  ciphertext. Dates, status, priority, assignees and the list name stay readable. Members without a key wait on a list
  until the owner releases it with one click; every member has a safety number, a changed key is shown. Agents, the mail
  address, public links, templates, the participant role and "everyone in the organisation" are not available in such a
  list, and lists of the Family and Household & Life modules cannot be locked (the server writes into them); in a locked
  list CalDAV shows "🔒 Task" with dates, pushes and mails name only the list, search runs in the browser. The offline copy
  in the browser keeps only ciphertext; texts that do not open with your key are reported (compare the safety numbers). The
  way back decrypts everything again (owner, with the password). Not yet:
  attachments, the list channel and a new key when a member leaves (the member dialog says so) (#1817).
- Before going back to an older version, open the lock of every list again: older versions do not know the lock and
  would show and accept texts of such a list unprotected.
- Settings > Administration > Encryption lists a third kind: "Encrypted in the browser (lists with a lock)".

### Fixed
- Encrypted direct messages: the notice for your own switch says "You switched encryption on" (it read "You has ..." in
  German), and the *Attach encrypted* button has an accessible name (#1518).
## [2.66.0] - 2026-10-17

**In short:** duplicate contacts and duplicate clients can be merged by hand - pick the record that stays and, per field,
the value it keeps; everything linked moves along, and the merge can be undone for 30 days.

### Added
- **Merge contacts:** tick two or more contacts, *Merge*: choose the contact that stays and, where the entries differ, which
  value each field keeps; phone numbers, e-mail addresses, addresses, web links and groups are joined. Linked tasks, event
  attendances, client contact persons and "stay in touch" move to the kept contact; the others disappear from the address
  book and, over CardDAV, from your devices (#1835).
- **Merge clients:** the same in the clients list; offers, invoices, contracts, archive entries, projects, trips, deals and
  contact persons move to the kept client. Issued invoices keep the address they were printed with, only the client
  changes (#1835).
- **Undo and history:** an overview of what moves where before the merge, *Undo* right after it and in the history of the
  kept contact / client for 30 days (#1835).

## [2.65.0] - 2026-10-17

**In short:** Kalmido **starts faster** and **long lists stay smooth**: a smaller start, compressed answers, and only the
rows you see are drawn.

### Changed
- Faster start with many tasks: `GET /api/state` with 5,000 tasks takes about 160 ms instead of 333 ms; a single task loads
  only its own rows (#1505).
- JSON answers go out gzip-compressed when the browser accepts it: the start state with 5,000 tasks shrinks from 3.6 MB to
  158 KB (#1505).
- Less at start: agent chat, calendar, statistics, knowledge pages, mind maps, PDF preview, documents, Home & life,
  timeline / roadmap, playbooks, integrations and parts of the settings load when first opened and ahead of time while
  idle (not in data saver mode); still available offline (#1823).
- The styles of these areas live in their own files and arrive with the area, without a flash (#1824).
- Long lists stay smooth: from 300 rows Kalmido draws only the rows around the visible part (lists, Today, All,
  Completed, Trash, contacts); redrawing 5,000 tasks takes 21 ms instead of 331 ms; selection, keyboard, dragging and the
  scroll position work across the whole list (#1825).
- Performance budget in CI: start size and load time are measured, a too large state turns CI red
  (`tools/perf_budget.py`, `tools/perf_budget.json`) (#1822).

## [2.64.0] - 2026-10-17

### Security
- Security fix (files at rest): the files of the private space (attachments of tasks and comments in lists without an
  organisation, their project files, the own file store and documents, files in chats with agents) are now stored
  encrypted on the server with a key per person, wrapped with `KALMIDO_SECRET_KEY` like the organisation keys (#1864).
  Server-side encryption, not end-to-end: everyone who may see a file gets it as before.
- Existing files are encrypted by the start-up pass (in portions); a file that moves into another space (task, list,
  new list owner) is sealed again for it. Deleting an account deletes its key.
- The way back: `python -m kalmido.admin.orgcrypt_cli decrypt-private` (before a downgrade below 2.64; `decrypt-all`
  covers it too), `encrypt-private`, and `rewrap-accounts` after a planned change of the server key. See SELF-HOSTING.md,
  *Encryption of private files*.
- `decrypt-all` now also covers the versions of the file store and the files of agent chats.
## [2.63.0] - 2026-10-17

**In short:** a list's form becomes a **report form for customers** - a type for every report, one file, and a **link to
the status** for the sender - and the **customer portal** behind it: the reporter sees the state and the public answers
and can answer, without an account; comments stay internal unless you send them to the customer. Plus a security fix
(time entries of a project) and smaller follow-ups. This release takes 2.57.1 to 2.62.0 live along.

### Added
- Report forms (#1513): *Type of report* (bug, feature, task), *Allow one file* (up to 10 MB) and *The sender gets a
  link to the status*. The sender sees the link on the thank-you page and gets it once by mail. Spam protection without
  any outside service: a signed time stamp, limits per e-mail address, at most 5 links per report.
- Customer portal (#1513): the status page of a report shows its state, the text sent and the public answers; the
  reporter can answer there. *All my reports* sends a one-time sign-in link and lists the reporter's reports of the same
  space. In the app, a report has a *Customer report* box (copy the status link, mails to the customer on / off) and the
  comment bar a switch *Internal / Send to customer* (internal by default). Mails to the customer: at most one per report
  every 10 minutes, each with a link to stop them. Reports belong to the client of the list (or of the address) and show
  on the client's card. Agents answer customers with `portal: true` (API, MCP, reference starter).
- Job cards (#1482): a collapsible *Conversation* with the job's latest messages and a link into its whole history.

### Changed
- Project templates keep the project page: notepads, the standard arrangement and the block colours (#1523).
- Undo after *Delete all times* restores the entries exactly, including the link to a timer started on a phone (#1523).
- Knowledge pages show their own space list only when the workspace switch is on *All* (#1857).

### Security
- Security fix (time entries of a project): the time window, time reports, the CSV and the REST API show everyone's
  entries only to the list's owner and admins and the organisation's admins (#1523).

## [2.62.0] - 2026-10-17

**In short:** **pin chat messages** in the team and the agent chat, comments by agents **only as replies to you** if you
like, a message is **sent exactly once**, and a tidier list menu.

### Added
- Pin messages in the team chat and the agent chat (at most 5 per conversation): a bar at the top shows them, a tap jumps
  to the message, older ones too (#1848). Agents: event `chat_pinned`, MCP tools `pin_chat_message` / `pin_team_message`,
  fields `pinned_at` / `pinned_by` and the list `pins` (#1848, #1861).
- Settings > Notifications: *Comments by agents: All / Only replies to me*. With *only replies* an agent's comment reaches
  you only when it answers your comment, follows it directly or mentions you; approval cards and questions always arrive.
  Comments by people stay as they are (#1854).

### Changed
- A chat message is sent only once: it shows at once as *Sending...* in the conversation, Send and Enter wait for the
  server, after waking up the chat reloads at once (#1530).
- List and basket menu: the four move entries are under *Change position...* (#1853).
- The head of the list and folder settings stays at the top while scrolling, *Saved - Undo* is always visible (#1485).

### Fixed
- Files > Documents reloads when opened and no longer stays empty (#1844).

## [2.61.0] - 2026-10-17

**In short:** uploads get safe - every file is **checked for malware** (ClamAV) before it is stored, **photos lose their
location and camera data**, and PDFs and pictures in tasks, projects and the file store become **searchable by their text**.

### Added
- **Virus scan of uploads** with ClamAV (task and comment files, file store, documents, mail intake, sharing, project and
  chat files): a find refuses the file with a clear message. While the scanner is unavailable files are taken, marked
  *Unchecked* and checked in the background; a later find locks the file (no download or preview, a note for the
  uploader). New service `clamav` in docker-compose (about 1-1.5 GB RAM; `KALMIDO_CLAMD=` switches it off for small
  servers, then nothing is marked). The scanner's state is shown in the server settings (#1818).
- **Photo metadata removed on upload:** JPEG, PNG, WebP and HEIC lose GPS, camera and other EXIF/XMP/IPTC data on every
  way in, the picture itself stays as it is (turned photos are set upright first). Setting *Remove location data from
  photos* (on by default) per account and per organisation (#1819).
- **Receipt photos keep their capture date:** read before the metadata goes, shown as *Taken on ...* and used as the
  date when the text has none (#1819).
- **Text recognition for normal files:** PDFs and pictures attached to tasks, in projects and in the file store are read
  in the background (same local Tesseract and limits as documents), become searchable and show *Text recognised* /
  *No text found*; existing files follow slowly (#1820).

### Changed
- The file type now comes from the content: a program or HTML page posing as a picture or PDF is only offered as a
  download (#1818).

### Fixed
- A public list link never hands out browser-encrypted files.

## [2.60.0] - 2026-10-17

**In short:** "Software team" - project lists can plan in **sprints** with a burndown and a review, kanban columns get
**WIP limits**, tasks **story points** with a **velocity** chart, a real **review step** (reviewer, done only after
approval) and **environments** (Staging, Live) that show where a milestone runs and since when. Everything is off until a
list switches it on.

### Added
- **Sprints** per project list (list dialog > *Sprints*): one or two weeks or a free length, a start weekday, open tasks
  move on automatically if wanted. A sprint header above the list and the Kanban shows goal, progress and a small burndown
  with an ideal line; filter *Current sprint* / *Backlog*; plan by task menu, multi-selection or dragging onto the header;
  *Close sprint* shows a review (done, moved, added later). API v1 + MCP `list_sprints`, `get_sprint`, `set_task_sprint`,
  events `sprint_started` / `sprint_closed` (#343).
- **WIP limit per kanban column** (column menu): the head shows "2/3" and is marked above the limit; moving stays allowed.
  New *Software / AI dev* projects start with 3 for *In progress* and *Review*. MCP `set_wip_limit` (#1510).
- **Story points** (1, 2, 3, 5, 8, 13) per list switch, in the task panel, rows, cards, column sums and the multi-selection;
  the sprint burndown counts tasks or points; **velocity** of the last six sprints with the average as a planning aid.
  API/MCP field `points`, `get_velocity` (#1511).
- **Review step** per list: a reviewer per task (person or agent of the list), moving into the review section asks the
  reviewer (News + push, row *Reviews* in the notification settings), 👍 *Approve* / 👎 *Back*; with *Done only after
  approval* every way of completing waits for it. A merged or approved linked pull request counts. API v1 + MCP
  `review_task`, `set_list_review`, event `review_requested` (#1512).
- **Environments** per project (Staging, Live, ...): put a milestone there by hand, via API/MCP `set_deployment` or a
  deploy webhook with a secret token; milestone, roadmap and task rows show "Live since 15.10.", optionally the
  milestone's tasks complete on arrival. Event `deployed` (#1514).

### Fixed
- Office: the top tabs wrap instead of disappearing behind an open chat window (#1830).
## [2.59.0] - 2026-10-17

**In short:** **related tasks** - every task can show up to five tasks with a similar meaning and flags probable
duplicates, a quiet hint while adding, "similar meaning" in the search - computed by a small local model in the new
optional `kalmido-embed` service (no language model, nothing leaves the server); a client's **contact persons link to
address book contacts**; agent job messages show the **job's name with a colour of its own**.

### Added
- **Related tasks:** a folded section *Related tasks* in a task lists up to five tasks with a similar meaning (only tasks
  you can see) and marks *probably a duplicate*; tasks mentioned by number (#123) stand apart below. While adding a
  task a quiet hint "Similar: #… title" appears (tap opens it, nothing blocks), the search gets *also similar meaning*.
  Admins switch it on and off under *Administration > Server* and see the state of the service. Agents get `related` in
  task events, `GET /api/v1/tasks/{id}/related`, `search?semantic=1` and the MCP tool `related_tasks` (#1375).
- **Optional embedding service `kalmido-embed`:** `docker compose --profile embed up -d --build` plus
  `KALMIDO_EMBED_URL=http://embed:8090` in `.env`. A small multilingual model (multilingual-e5-small, int8, MIT) turns
  task texts into numbers on your CPU (~0.15 s per task on a small 4-core machine, ~0.6 GB RAM), without network at run
  time and without logging texts. Vectors live in the new table `task_vectors`, protected like tasks (row-level
  security, sealed with the organisation's key in encrypted organisations). Without the service nothing changes (#1375).
- **Clients:** a contact person of a client can be linked to a contact from the organisation's address books (*Pick
  from address book* takes over name, role, e-mail and phone); freelancers without an organisation link their own
  books. The contact card shows "Contact person at <client>" to everybody who may open the client. Deleting a contact
  or a book only drops the link; the nightly boundary check unlinks contacts across organisations (#1735).

### Changed
- **Job messages in the agent chat** carry the job's name in their tag (without a name "Job #N" as before); the colour
  comes from the name, so a follow-up job with the same name keeps it, and part jobs take their leader's tone, a little
  lighter. Messages deliver `job_name`, `job_parent`, `job_parent_name`; jobs `parent_id`; the reference launcher
  `mcp/agent_job.py` names its jobs (`--name`, else from a list) (#1827).

### Fixed
- `POST/PATCH /api/v1/clients` accept `contacts` (with `contact_id`) as documented since 2.40.0 (#1735).

## [2.58.0] - 2026-10-17

**In short:** a collection of fixes - Back on Android closes dialogs, invoices from quotations with parts are exact to the
cent, a share's expiry date is the chosen day, the password reset answers in constant time, organisation list pictures
are sealed in encrypted organisations, agents can give their jobs a name of their own, task rows and the sidebar
show fewer symbols, and the archive import finds the recipient's address again.

### Added
- **Job names for agents:** `POST /api/v1/agent/jobs` takes an optional `name` (MCP `create_job`, `agent_job.py start --name`);
  without it the name still comes from a title like "Clara: ...", but ordinary titles like "Release: 2.56" or "Fix: Login"
  no longer count as a name (#1803).

### Changed
- **Phones:** the Back key / swipe closes the topmost dialog, sheet, menu or the search palette first; the close symbol of
  dialogs is visible again with a full touch target (#1757, #1730).
- **Password reset:** "Forgot password?" always answers after the same time; the "New password" page says that app
  passwords (CalDAV) and API tokens stay valid (#1792).
- **Organisation list pictures** in encrypted organisations are stored sealed like attachments; existing ones are sealed
  on the next start (#1805). A picture and a new name set together give one news item (#1804).
- **Office > Services:** the section is called "Drehpersonal" in German, like its dialog (#1765).
- **Fewer symbols in the task row:** *Settings > Appearance > Task rows > Symbols in the row* with the levels *All*
  (as before), *Important* (due date, reminder, deadline, person, approvals and locks), *Calm* (title, status circle,
  due date) and *Custom* (boxes per group: dates, content, time, status, placement, people). The status circle, overdue
  tasks and an agent waiting for your yes always show; the task itself shows everything. Per person, on every device.
  **Default for every account: Important** (#1799).
- **Sidebar:** task counts, the status dots of lists and the share marks (person / robot) can be switched off (#1799).

### Fixed
- **Invoice from a quotation with parts:** title page, summary and full positions match the quotation to the cent, also
  with fractional part quantities and mixed tax rates (#1759).
- **Subscribed CalDAV calendars:** a server with weak ETags gets a clear message instead of a lasting conflict; PUT and
  DELETE follow no redirects (#1789).
- **File store:** a share's expiry date lasts until the end of the chosen day in your time zone (#1787).
- **Contacts:** a bulk action that stops halfway reports how many contacts are done; no move into imported address books
  (also for agents); deleting a contact over CardDAV handles its birthday task like the app (#1656). Import and folder
  details (#1657).
- **Agents:** the agent card lists only lists within the agent's list limit (#1761); old API tokens show as "API token"
  in the machine list (#1527); "Request becomes project" keeps its undo hint longer, Undo goes back, the quotation is only
  named when there is one (#1810).
- **Chats:** X on the active chat on phones switches to the next chat at once (#1771); small chat window fixes (#1773).
- **Interface:** search fields keep the focus while typing (#1644), the "New message" pill stays (#1756), Esc in a detail
  field restores the saved value (#1758), the bell menu stays inside the window (#1760), colour marks in the assign sheet
  (#1772), a confirmed draft event's popup redraws (#1811), the office privacy switch stands above Save (#1812).
- **Organisations:** "Join" is a full touch target on phones, member counts update at once, a failed group picture upload
  leaves no file; a request to a deactivated account stays in "sent" (#1724, #1792).
- **Archive import:** the recipient's address of a PDF is found on the whole first page, also behind long position
  lists; the organisation's own sender block (a name on two lines, eGbR, the city in English, "/ Germany") no longer
  slips into the address; US ("New York NY 10017") and UK ("EC1A 1BB London") addresses are read; a client in the own
  street of another town and quantities like "10000 pieces" are told apart (#1813).
- **Switch on all modules** switches on every module of *Settings > Modules* (also agents, knowledge pages, file store,
  dispatch and the business modules); switching it off leaves only lists and tasks. Its explanation stands below the
  title (#1808).

## [2.57.1] - 2026-10-17

### Fixed
- The drawer on phones no longer scrolls sideways: the background of the sidebar's fixed head was 4 px wider than the
  sidebar (#1798).

## [2.57.0] - 2026-10-17

**In short:** the sidebar gets a **fixed head** - brand, workspace, search and your **favourites** stay while the rest
scrolls -, **anything in the sidebar can be a favourite** (shown as icon tiles in your own order, the same on all your
devices), and **every workspace can get your own colour**: a light tint of the sidebar and a dot in the workspace switch.

### Added
- **Favourites of every kind:** lists, projects, folders, Plan views like Today, views and areas like the calendar,
  filters, tags, people, groups and agents get a star from the row's menu (right-click or long press). The favourites
  are icon tiles with the name as hint and without counts; arrange them by dragging (long press and drag on a phone) or
  with *Move left / Move right* in a tile's menu. The order is personal and synced to every device; *Only favourites*
  still applies to lists and projects only (#1798).
- **Fixed sidebar head:** brand, workspace switch, search and favourites stay in place while the sidebar scrolls - on the
  desktop, the Fold and in the phone's drawer (#1798).
- **Your colour per workspace:** Settings > Workspaces offers the 12 list tones (or no colour) for Private and every
  organisation; only you see it. The sidebar takes a light tint of the shown workspace and the workspace switch shows a
  dot in front of each workspace. Without a choice an organisation keeps the colour its admins chose (#1807).

## [2.56.4] - 2026-10-17

### Fixed
- Connecting Paperless-ngx 3.x works again: it only speaks API version 9 / 10 and answered Kalmido's version 5 with
  "error (406)". Kalmido now asks for 10, then 9, then 5 (older servers keep working); a server without any of them gets a
  readable reason (#1859).
- Custom fields of newer Paperless-ngx versions come in readable: the label of a select option (instead of its id), amounts
  as "42.00 EUR", yes / no and document links.

## [2.56.3] - 2026-10-16

### Fixed
- In an organisation's office the client field of a quotation or invoice offers the organisation's clients again (it
  stayed empty there, #1842).

## [2.56.1] - 2026-10-16

CI fixes for 2.56.0 (both go live with this version).

### Fixed
- A job's own chat history now also finds messages addressed to it by name or number on Postgres (the match ignored
  upper / lower case only on SQLite).
- The colour swatch in *Lists of the organisation* only takes checked colour values.

## [2.56.0] - 2026-10-16

**In short:** talking to a running background job of an agent gets direct - a **Message** button on the job card, every
job with **its own chat history** (tap its name or tag), running jobs in the agent menu of the header - organisation
admins **rename and restyle** their organisation's lists without access to the contents, and the sidebar's share
symbols stand in fixed columns.

### Added
- **Message to a job:** running and waiting job cards get *Message* next to *Stop* (a sheet on phones, sending stays off
  while empty, up to 4000 characters); the agent gets the `job` event with `action: "message"` and `text`, the job's state
  is not touched. Same rights as *Stop* (#1791).
- **A chat history per job:** the job tag ("Clara · Job #220") and the job's name at the start of its messages open the
  job's own history - its messages, your messages to it and the agent's answers to those; the input writes to the job
  ("Clara: …"), *Back* returns to the whole chat; an ended job shows "Job has ended" and no input. Running jobs for you
  appear with their name in the agent menu of the header. API: jobs carry `name`, `GET /api/agents/<id>/chat?job=<id>` (#1793).
- **Organisation lists:** organisation admins change name, icon (emoji or picture) and colour of their organisation's
  lists under *Settings > Organisation > Lists of the organisation > Edit*, without a role in the list and without access
  to its tasks, sections or members. The change is logged (old -> new) and the owner and members get a News item (#1795).

### Changed
- **Sidebar:** person and agent symbols stand in two fixed columns at the right edge; a missing agent symbol leaves its
  column empty, folders, sublists and lists line up, the dot and counter sit left of the columns (#1797).

### Agents
- `job` event: `action: "message"` with `text`; jobs carry `name`; the reference launcher passes a job message on as a chat
  run with a hint (capability `job_message`).

## [2.55.1] - 2026-10-16

### Fixed
- Start page: with Office & finance on, saving an arrangement or changing the layout no longer fails ("Invalid layout") -
  the figures card is a known start page block on the server, also for agent proposals.

## [2.55.0] - 2026-10-16

**In short:** views you arrange become more personal - **several saved arrangements** per view ("Focus", "Overview")
switched in the header, **settings per block** behind a small gear, an arrangement **sent as a template** to others,
**agents may propose** an arrangement (you accept with a thumbs up), more views on the block builder, and a **newsletter
connection** that hands contacts and segments to listmonk (Brevo and CleverReach as a preview) instead of sending mail itself.

### Added
- **Saved arrangements:** *Save as arrangement…* in the block menu or while customising; with one saved arrangement a
  switcher appears in the view's header (a sheet on phones) with *Standard*, your arrangements and *Manage* (rename,
  reorder, delete with undo). The same on all your devices; changes while one is active go into it (#1069).
- **Send as a template:** send the arrangement you see to people who see you; they get a News item with a preview and
  take it over or decline. Only the arrangement travels, never content; a block they cannot see stays empty (#1068).
- **Settings per block:** a gear on blocks with settings while customising (also *Settings…* in the block menu): e.g.
  time tracking blocks only for one client or project and the day chart as a line, Today on the start page for one list
  or folder, only mine and how many, sorting and filters for the project and agent overviews, which key figures show (#1065).
- **Agents propose arrangements:** with the new agent right *Propose arrangements* (off by default) a connected agent
  reads which blocks a view has (never their content) and proposes an arrangement; a card shows before and after, a thumbs
  up saves it as an arrangement of yours, a thumbs down discards it. Agents never change a view themselves. API
  `GET /api/v1/layouts/<view>`, `GET /api/v1/layouts/blocks`, `POST /api/v1/layouts/proposals`, MCP `get_view_layout`,
  `list_layout_blocks`, `propose_layout`; reference launcher capability `layout_answer` (#1066).
- **More views on the block builder:** statistics, the client card and family can be arranged like the start page
  (show / hide, order, width, a different arrangement on phones, a standard for everyone); without an own arrangement they
  look as before. Roadmap, calendar and habits stay one area each (#1067).
- **Newsletter connection** (Contacts > … > *Newsletter…*): per workspace a connection to listmonk (Brevo and
  CleverReach as a preview, not yet tested against the real services); segments from groups, companies and address books
  become lists at the service; a consent status per contact (with date and source); only consented contacts are sent,
  unsubscribes, bounces and confirmed double opt-ins come back to the contact and unsubscribed addresses are never added
  again. Sync by hand or daily (off by default), a log for admins, access data sealed and never shown again. Kalmido
  itself sends no newsletters (#1455).

## [2.53.1] - 2026-10-16

**In short:** the checks of 2.53.0 green again; 2.53.0 and 2.53.1 go live together.

### Fixed
- The browser demo loads settings, contacts and Office & finance again (the areas that load on demand, #1410).
- The colour of a tag card goes through the colour check like every other colour (#446).

## [2.53.0] - 2026-10-16

**In short:** the interface - **list colours** as the accent of an open list, a fixed palette of 12 tones and coloured
task edges; **organisations get a colour** (private stays neutral); a **bell per task** with *Urgent*; **references by
drag and drop** with cards and a **preview on hover**; agents' comments in their **own tone**; a **tags overview**; and
the web app **loads rarely used areas on demand**.

### Added
- **Bell per task** (task menu > *Notifications for this task*): *As the list*, *Muted* or *Urgent* (until completed or until a
  date). Urgent sends every change and comment as a push at the highest priority. List owners and admins can mark a task
  urgent for members; everyone can switch it off for themselves (noted in the history), and *Settings > Notifications >
  Accept urgent markings from others* turns it off entirely. On iPhone an urgent push is prominent but cannot break
  through Focus (#1424).
- **References by drag and drop:** drag a list, folder, task, Ablage file, contact or event onto a comment or the
  description to insert a reference; on phones *Insert reference* with search. Links to this instance show as small
  cards with the name the reader sees; without access only *No access* (#1449).
- **Preview card:** resting the mouse 0.4 s on a task number or a reference card shows status, list, due date, assignee
  and more (#1440).
- **Organisation colour** (Settings > Workspaces, set by the organisation's admins): a stripe in the list header and the
  sidebar, the workspace badge and switch in that colour, a frame around quick add and the comment box; moving something
  from Private into an organisation shows *Visible to everyone in X* with Undo. Private stays neutral (#1474).
- **Tags overview:** all tags as cards with open/done, next due date, lists and last use (button in the *Tags* header) (#446).

### Changed
- **List colours:** a fixed palette of 12 tones (readable in light and dark); an older free colour stays stored and is shown
  as the nearest tone. An open list uses its colour as the accent; tasks carry their list colour as a thin edge in board,
  calendar and the collection views; folders have a colour that new lists take over; *Appearance > List colours only as a
  dot* for a calmer look (#1426).
- **Agents' comments** have their own soft tone in comments, News and chats, in light and dark (#1451).
- **Faster start:** settings, contacts and Office & finance load when you first open them (about 430 KB less code at start,
  12 % less to download) and stay cached for offline use; if loading fails, *Retry* (#1410).

## [2.52.1] - 2026-10-16

**In short:** the checks of 2.52.0 green again; 2.52.0 and 2.52.1 go live together.

### Fixed
- The new calendar styles (drag preview, new-event block, actions of subscribed calendars) follow the font size.

## [2.52.0] - 2026-10-16

**In short:** the calendar feels like a desktop calendar app - **drag to create** an event right in the grid, **move**
and **resize** events, multi-day events from the all-day row and the month view, also by **long press on phones and
tablets**. Events can now be **written into subscribed CalDAV calendars**, and **address books can belong to an
organisation**.

### Added
- **Calendar like a desktop app:** drag over free time and type the title right in the new block (Enter saves,
  *Details* opens the full editor); drag events to another time or day, drag the bottom edge to change the length; drag
  over several days in the all-day row or the month view for a multi-day event. On touch screens: hold for 0.4 s, then
  drag; a normal swipe still scrolls. Repeating events ask *only this one / all*. Esc cancels, every change can be
  undone (#1016).
- **Write into subscribed CalDAV calendars** (iCloud, Nextcloud, Fastmail, mailbox.org, Radicale ...): a switch
  *Allow writing* per CalDAV subscription, off by default and only possible when the server grants write access. New,
  changed, moved and deleted events go to the other calendar; properties of other apps (guests, alarms) are kept. If the
  event was changed elsewhere, Kalmido overwrites nothing and reloads. Calendar links (ICS, also Google) stay read-only (#1128).
- **Address books of an organisation:** *Transfer to organisation…* (org admins) - members view or edit depending on the
  book's setting, single shares stay possible; when the managing person leaves or deletes the account, the book stays
  with its contacts, birthday list and task links and another admin takes over. *Make personal again…* is the way back;
  nothing is moved automatically (#1438).

## [2.51.1] - 2026-10-16

**In short:** the checks of 2.51.0 green again; 2.51.0 and 2.51.1 go live together.

### Fixed
- Time and shoot proposals of agents pick times with the app's own time picker instead of the browser's field.
- The marks of agent drafts and agent notes on the project page follow the font size.

## [2.51.0] - 2026-10-16

**In short:** connected agents pitch in with business work - **quotation drafts** in the office, the way **from quotation
to invoice** (invoice and reminder drafts, payment suggestions), an **inquiry becomes a project** with one yes, a
**setup assistant**, a **weekly status** on project pages, a **time tracking check** and **shoot planning**. The agent
proposes, a person confirms: agents never send, finalise, book or delete. All new agent rights are off by default.

### Added
- **Agents in the office** (Office & finance): on request a connected agent drafts quotations with services and prices from
  the master data; free positions, changed prices and discounts are marked for review. A card in the chat shows the sum,
  the PDF preview and *Open in the office*. Two switches (per agent and a privacy switch per office), every agent request
  in the access log; freelancers without an organisation get the same in their personal office (#1348).
- **From quotation to invoice:** invoice drafts from accepted quotations, reminder drafts for open invoices, and payment
  suggestions an admin books or rejects (#1350).
- **An inquiry becomes a project:** one proposal with the project list, first tasks, shoot days as draft events and
  (with office rights) a quotation draft; an accepted quotation becomes a project the same way (#1351).
- **Set up with your agent** (Settings > Modules and the tour): the agent suggests modules, lists and a first project (#1358).
- **Weekly status on the pin board:** an agent keeps its own *Status* notepad on a project page (done, overdue, blocked,
  who waits for whom); new permission *Pin board* and a template for scheduled checks (#1352).
- **Time tracking check:** agents find too long days, overlaps and events without time and suggest entries from calendar
  events; you review and take them over (#1353).
- **Shoot planning:** agents propose shoot days as draft events and crew / equipment as options, with warnings for double
  bookings and absences; draft events show dashed in the calendar with *Confirm* / *Discard* (#1355).
- **For agents:** the scopes *Office drafts* and *Pin board*, the event `offer_accepted`, reading the disposition of the own
  organisation, and new MCP tools (office, pin board, time check, shoot planning, `propose_to_person`).

## [2.50.2] - 2026-10-16

**In short:** amounts from 1,000 keep their value when a form is opened and saved again.

### Fixed
- Office forms read the thousands separator of the app language: a pipeline deal of 1,500 no longer becomes 1.50 after
  opening and saving it; the same for rates and cash flow amounts.

## [2.50.1] - 2026-10-16

**In short:** the checks of 2.50.0 green again; 2.50.0 and 2.50.1 go live together.

### Fixed
- On phones some form rows (contact and event notes, agent forms) stayed hidden: the pipeline's columns shared a style
  name with them. The day plan bar keeps its look next to the disposition's booking bars.
- Absences and bookings pick dates and times with the app's own picker instead of the browser's field.
- After saving an absence or a booking its row opens again on a tap without switching tabs.
- German: the cash flow hint without the old word for the basket.

## [2.50.0] - 2026-10-16

**In short:** the second part of the business hub: **absences** with public holidays, a **disposition** for crew and
equipment, a **sales pipeline** and **key figures** in the office, a **customer view** for public links with a choice of
what customers see, and **approvals by customers** (accept a quotation, sign off a project) with a simple electronic signature.

### Added
- **Absences** (Team > Workload > Absences): holiday, sick leave, day off, other; whole or half days. The team only sees
  "away" and the dates, the kind and the note only the person and the admins (encrypted at rest). Public holidays per
  German state. Workload, *Plan my day* and assignments take them into account (a warning, never a block) (#1195).
- **Disposition** (module, off by default): book members, contacts, devices and device kits for shoot days, as an option
  or firm; week grid on large screens, a day list on phones; double bookings and absences are flagged, "Who is free on …?".
  Booked people see *My bookings*, the booking in their calendar and a News item for firm bookings (#1194).
- **Sales pipeline** (Office, admins): inquiry, quotation sent, won, lost; value, probability per stage (editable), weighted
  sum and the expected income per month. A deal turns into a quotation with one tap, a won deal into a project; an accepted
  quotation moves its deal to won (#1196).
- **Key figures** (Office, admins; freelancers for their own office): revenue with last year's comparison, open and
  overdue invoices, pipeline, cash flow of the next months, hours against budget and margin per client, and a home
  screen block (#1197).
- **Customer view** for public links: choose what customers see (progress, sections, due dates, assignees, tags, fields,
  files, logo), optionally only tasks with one tag, and let them leave a comment; team comments are never shown (#329).
- **Customer approvals** with a simple electronic signature: customers accept or decline a sent quotation through a link,
  or sign off a project, section or milestone; the record keeps name, time, address and a checksum. Suitable for accepting
  quotations and sign-offs, not for contracts that need the written form (#1200).
- Agents: `get_absences` / `GET /api/v1/absences` returns only "away" and the dates within the agent's organisation.

## [2.49.1] - 2026-10-16

**In short:** the checks of 2.49.0 green again; 2.49.0 and 2.49.1 go live together.

### Fixed
- On phones the view switch of a list fits again with the new mind map view: the inactive views show only their icon.
- The mind map's second tap on a branch opens its actions on phones.
- Withdrawn connection requests and moving knowledge page folders work the same on PostgreSQL.
- The new views of 2.49 follow the text size setting (rem instead of px); "Check your e-mail" wording on the login page.

## [2.49.0] - 2026-10-16

**In short:** **Forgot your password?** on the login page and a calmer, friendlier login page; **kid accounts** start
without errors, get their own tour and a **parents' PIN**; **knowledge pages** per organisation and a **mind map** view
of every list; **find people by e-mail** like in a messenger (opt-in).

### Added
- **Forgot your password?** on the login page sends a one-time reset link by e-mail (only when the server sends mail).
  The answer is the same for every address, requests are rate limited, and two-factor stays required afterwards (#1531).
- **Find people** (Settings > Account, and the share dialog): enter a full e-mail address, send a connection request; the
  other person accepts or declines. Being findable is off by default and confirmed by a link in a mail. Kalmido never
  reveals whether an address has an account. Optional address book check, withdraw, disconnect, block (#1106).
- **Knowledge pages** (module, off by default): a small wiki per organisation or private, folders from the page name,
  `[[links]]` with suggestions, backlinks, templates, frontmatter fields, "Mentioned in" on tasks, ZIP export / import
  of Markdown files (#1199).
- **Mind map** as a view of every list: branches are tasks, typing like in a mind map tool (Enter, Tab, Shift+Tab, Delete,
  Space), drag to re-hang, pinch to zoom, outline view; export as Markdown, SVG or PNG, import of Markdown, OPML and
  FreeMind outlines; ```mindmap blocks on knowledge pages (#1201).
- **Parents' PIN** per kid: with a PIN the kid needs it for settings, account and logging out; ticking off stays free.
  Five wrong tries pause it for 15 minutes and notify the parents (#1551).
- **Kids' tour**: three big cards in simple words instead of the grown-up tour (#1533).
- **Shorten forwarded mails** (Settings > Integrations > Tasks by mail, off by default): the forward header becomes one
  line, signatures, disclaimers and older quotes go; the original can stay attached as .eml (#971).
- A small **x** closes notices with a button or a longer display time (#1769).
- A fixed **Private / organisation sign** in a list's header, from the list's own workspace (#1770).

### Changed
- The **login page** has a soft purple background, a calm light that follows the pointer (fixed on phones, still with
  reduced motion), a greeting by time of day, and light and dark; invitation, setup and password pages look the same (#1553).
- **Ticking off** first draws a line across the title; with "Hide completed" the row then fades out softly (#1766).
- **New lists hide completed tasks** by default (Settings > Appearance > New lists); new accounts hide them by default
  too. Existing lists and accounts stay as they are (#1535).
- Switching the workspace leaves a list of another workspace for the inbox; opening such a list directly switches the
  filter along (#1770).
- A reset link from an admin now also leads into the two-factor step when the account has two-factor (#1531).

### Fixed
- Kid accounts no longer show "Not possible with a kid account" at the start; buttons and settings a kid cannot use are
  hidden; shared lists appear in "My day" as their own sections (#1537).
## [2.48.1] - 2026-10-16

**In short:** the checks of 2.48.0 green again; 2.48.0 and 2.48.1 go live together.

### Fixed
- Documents and Files use the app's own date picker instead of the browser's date fields.
- The new views of 2.48 follow the text size setting (rem instead of px).
- The folder queries of the file store keep their depth limit as a query parameter.
- Closing a document sheet after its window is gone no longer raises a script error.
- Tests follow the new behaviour of 2.48.0 (modules of new accounts, the areas, the route scan); two UI tests and the
  setup test run more steadily.

## [2.48.0] - 2026-10-16

**In short:** **Files** for you and your organisation with shares to people, groups and agents, **Documents** that read
scans locally and sort themselves in, a **PDF preview** inside Kalmido and **notes locked with your own password**.

### Added
- **Files** (#1207): a new area with folders and files for yourself and per organisation (*My files*, the organisation,
  *Shared with me*, *Trash*). Upload with the button or by dragging; the same name again makes a new version, older
  versions can be restored. Rename, move and delete into the trash, each with undo. Share a folder or file with people,
  groups and agents (view or edit, optional end date, inherited by everything below), only within its workspace; an
  organisation folder can be opened to the whole organisation. *Show in Files* on task and project files adds a link
  that keeps the original's rights. Contents are encrypted at rest like attachments and count towards the storage quota.
- **Documents** (#1111): PDFs, scans and photos in one place with a preview image, date, sender, type and tags, filters
  and full-text search in the content. Scans are read locally in the container (German and English text recognition,
  no external service); date, due date and amount are found without any agent. Sorting in works per feature (sender,
  type, tags, folder) with rules (word, all words, exact phrase, pattern, fuzzy), learning from your own corrections, by
  an agent, or off; sure hits are set and marked *automatic*, unsure ones wait in *To review*, every correction trains
  along. A document never moves to another workspace. In: drag and drop, *Save as document* in the share sheet, a mail
  address for documents (with an IMAP mailbox configured), the folder *Documents/Inbox*. A due date becomes a task with
  one click. Archive serial numbers (ASN) with your own prefix, read from a QR code or the text. Recognised text,
  amounts and senders are stored encrypted; the search uses keyed word hashes instead of a plain-text index.
- **PDF preview** (#1367): attachments, comment and chat files, project files, quotations, invoices, credit notes,
  reminders and archive PDFs open in a preview window: pages, zoom (buttons, Ctrl+wheel, pinch), swipe on phones, page
  numbers, download and *Open in new tab*; Ctrl/Cmd+click still opens a tab. pdf.js is shipped with Kalmido (no CDN,
  scripts in PDFs stay off); offline or damaged files show a clear note.
- **Lock a note** (#1642): the lock in a task's note encrypts the note text in your browser with your own password
  (the end-to-end key with its printable recovery code). The server and the operator see only ciphertext; title, date
  and list stay readable. Only in your own lists that are not shared. Search, agents, exports, mail, calendars and
  webhooks leave a locked note out and mark it as locked. Without the password and the recovery code the note is lost.
- **Paperless-ngx import** (#1152, self-hosted instances only): connect a Paperless-ngx instance per organisation (and
  for your private space) and take over its documents with the original file, text, date, correspondent, document type,
  tags (mapped in a preview first), custom fields and notes; no duplicates on a second run. Optionally new documents
  follow every 15 minutes up to once a day. Kalmido only reads there.
- **Agents** (#1207, #1111, #1356): the scopes `files:read` / `files:write`, the MCP tools `list_files`, `read_file`,
  `write_file`, `create_file_folder`, `list_documents`, `get_document`, `update_document`, `suggest_receipt`,
  `list_receipt_suggestions` and the events `file_shared` and `document_added`. Every agent gets its own result folder;
  every access of an agent is listed in the file's history. For receipts an agent only suggests project and category,
  a person accepts or rejects (with undo).

### Fixed
- The backup now contains project files again (missing since 2.7.1) and the new files.

### Notes
- Additive database change (new tables `fs_*`, `doc_*`, `pl_sources`, `pl_imported`, `rc_*`, `task_note_locks`); the
  previous version runs on with it.
- The image is about 125 MB larger (Tesseract with German and English, Poppler, zbar).
- Existing agents do not get `files:read` / `files:write` by themselves: tick them in the agent's settings.

## [2.47.4] - 2026-10-16

**In short:** the checks of 2.47.3 green again; no new functions.

### Fixed
- The DATEV export dialog uses the app's date picker (#1460); the (i) buttons in the quotation editor are big enough to
  tap (#1382); sizes of the new travel and cash flow elements follow the text size (#1022, #1652).
- Tests: the office now has eight tabs, and three date-dependent tests no longer fail shortly after midnight.

## [2.47.3] - 2026-10-16

**In short:** **Office & finance without an organisation** (a personal office for freelancers), **travel expenses**, a
**cash flow** overview, the **DATEV booking batch** export, **several entries at once** for contacts, clients and lists,
and a clients page in the layout of the contacts.

### Added
- **Personal office** (#1360): everybody has an office of their own - master data, number ranges, company details, logo,
  quotations and invoices - and is its admin; no organisation needed (also in the server mode `shared`). The workspace
  switch decides: *Private* = the personal office, an organisation = its office (no silent fallback to the only
  organisation any more). **Small business rule** (section 19 UStG) in the company settings: new documents without VAT,
  with the legal note, e-invoice tax category E. *Office > Settings > Move into an organisation* turns a personal office
  into a new organisation (one way, with confirmation; server admins).
- **Travel expenses** (#1022): trips with period, destination, overnight stay, participants and purpose (job with client /
  project, or acquisition), receipts with fixed categories, currency and rate, the tick *Receipt in DATEV* (no receipt
  images in Kalmido), a filter for missing ticks, evaluations per month, year, person, project, client and category
  (CSV), and billing receipts on to a quotation or invoice draft (never twice). Office admins only.
- **Cash flow** (#1652): per month money in (payments, open invoices by due date, accepted quotations not yet invoiced)
  and out (purchases of accepted quotations, travel receipts, fixed costs with repetition), actual and planned apart,
  3 or 6 months ahead, tap a value for the entries behind it. Office admins only.
- **DATEV booking batch** (#1460): *Office > Invoices > DATEV export* downloads finalised invoices, credit notes and
  payments of a period as EXTF CSV (format 700, category 21); consultant / client number, fiscal year, account length,
  SKR03/SKR04 accounts and tax keys in the settings. Let your tax adviser import a test file once.
- **Contacts: edit several at once** (#1731): groups add / remove, company, department, kind, append a note; undo.
- **Clients: several at once** (#1733): select (Shift/Cmd+click, long press), delete (clients in use are archived),
  archive / restore, set rate, budget, colour, append a note; undo. Also `POST /api/v1/clients/bulk` and the MCP tool
  `bulk_clients`.
- **Several lists at once** (#1727): Shift/Cmd+click lists in the sidebar (phone: list menu > *Select several lists*)
  shows their tasks grouped like a folder; archive them together with one undo.
- **Uninstall command** (#1729): deleting an agent or removing a computer shows the command that removes the agent from
  that computer (macOS/Linux or Windows).
- **Job colours in the chat** (#1764): messages of a job get a coloured stripe and a "Job #N" mark; part jobs take the
  colour of their leading job (optional `job_parent` on agent chat messages).

### Changed
- **Clients page** (#1734): list on the left, the client's card on the right (phone: list, then card) with rate, budget,
  contact persons, billing details and open invoices; a "Client" tag and briefcase vs. "Contact" and person keep the two
  apart. It follows the workspace switch.
- **Office settings** (#1382): (i) explanations for the remaining fields, the quotation / invoice editor and the client card.
- **vCard import** (#1738): photo links of Google contacts are fetched and stored (Google's image server only, size and
  time limits); Google's letter placeholders are skipped; importing the file again adds missing photos.

### Notes
- Additive database changes (`orgs.personal_of`, travel / fixed cost tables, `agent_chat.job_parent`); the previous
  version runs on with them. Going back: personal offices show up there as organisations `private-<id>` without members -
  leave them alone (see docs/OFFICE.md).

## [2.47.2] - 2026-10-15

**In short:** CI fixes for 2.47.0 and 2.47.1; this version brings both packages live together.

### Fixed
- The person card keeps *Message* first and big (#906); *Open in split window* follows it (#1720).
- New sizes of 2.47.0 / 2.47.1 in rem, so they follow the font size (calculation box, colour picker, split windows).
- `p2466_c_ui` waits for both time tracking switches after switching on under Administration.

## [2.47.1] - 2026-10-15

**In short:** **several chats at once** in the chat panel, one above the other, and a **fixed colour for every agent
and colleague**, the same everywhere.

### Added
- **Split chat panel** (#1720): Ctrl/Cmd+click or *Open in split window* (right click, person card) opens another agent
  chat, team channel or direct message below the open one; each window keeps its own messages, draft, scroll position
  and unread dot. Header: fold, menu (move up / down, own browser window), close; drag a header to reorder, drag the
  divider (arrow keys too), double-click it to share the height evenly. At least about 220 px per window, more fold to
  their header. Open windows and heights are kept per device. Phones and tablets do not split: a row of the open chats
  at the top switches between them. A normal click still replaces the active chat.
- **Fixed colour per account** (#1721): every agent and person gets a colour of a 12-colour palette, per organisation
  agents first and as different as possible. Without a photo the initials sit on it, a photo gets a thin ring; agents
  keep the robot badge and "me" its accent mark. Shown in task rows, the *Assigned* column, the sidebar, the agents page,
  job cards, the chat header, the split windows, the assign menu and grouping by assignee. Change your own colour in
  *Settings > Account*; admins (and owners of personal agents) change an agent's colour in its settings
  (`PATCH /api/agents/<id>/color`). *Settings > Appearance > Show colours for people* off = only agents in colour.

### Notes
- Additive database change (`users.color`, default empty); the previous version runs on with it.

## [2.47.0] - 2026-10-15

**In short:** **Office & finance: calculation and master data import**: quotations with sub pages (parts), a shoot
calculation for film and video, purchase prices with the surplus per position (admins only), producing and raw data
switched per quotation, and a legacy Excel import that fills gaps instead of skipping.

### Added
- **Quotation parts** (#1215): a quotation can have any number of parts, each its own page in the usual layout
  (positions, producing, raw data, net total). The title page picks parts like services, with a quantity
  (*Interactive module ×5*); sum, raw data and purchase of a part times its quantity flow into the title page. A part can
  be left out of the PDF and still count. An invoice from a quotation with parts offers three forms: the title page with
  its positions, everything summed up in one position per VAT rate (title editable, default *Film production*), or
  complete like the quotation; the default per organisation is set in the office settings (app default: complete).
- **Shoot calculation** (#1216): a part of the kind *shoot calculation* with the rules of a film shoot sheet: shoot,
  travel and preparation days, overnight stays, meals, Saturday / Sunday surcharges, crew × count with the daily rate
  projected, producing as a share of the crew, car kilometres, an equipment set per shoot day with its discount, extra
  costs. Printed for the client without internal / external or purchase. The industry pack **Film & video** (data only,
  labels in German and English, default rates) is switched on per organisation in the office settings.
- **Crew and freelancer roles** (#1649, #1216): two new master data lists below the services. *Freelancer roles* hold
  the purchase price per day and per hour; a service points to its role, and a new position takes the role's price as
  its purchase. *Crew* holds the daily rate for the client, internal / external and an optional markup for the shoot
  calculation. Purchase prices and markups are encrypted at rest and only admins of the organisation see them.
- **Surplus per position** (#1649): admins see the purchase and the surplus of every position and the sum; never in the
  PDF, the print model or for members. Accepting a quotation stores its purchase with amount and date (for the cash flow
  overview that follows).
- **Percent positions** (#1649): a service with the unit *Percent* (e.g. the artists' social insurance at 5 %) is that
  share of the external positions on the same page.

### Changed
- **Producing and raw data per quotation** (#1645): every quotation has its own switches *Calculate producing* and raw
  data; the office settings only set the default for new quotations. The flags of services and positions are always
  kept and shown, a framework contract always presets raw data. Existing documents keep their sums.
- **Legacy Excel import fills gaps** (#1648, #1649): a service, device or role that exists already gets its empty fields
  filled from the file (*Fill empty fields*, the new default; nothing is overwritten), the preview lists them, and the
  undo (whole run or per area) empties them again. The blocks *Freelancer* and *Crew* of the sheet are imported in one
  way into the new role lists; a service's freelancer column points to its role; the raw data / producing columns are
  always read; the category order of the sheet orders the services.

### Fixed
- **Account picture in the sidebar** (#1654) no longer blinks away while moving through the app.

### Notes
- Database: new tables `office_roles`, `office_doc_parts`, `office_purchases`; new columns `office_services.role_id`,
  `office_doc_items.part_id` / `ref_part_id`, `office_docs.producing_on` (filled once at start-up). 2.46.3 keeps running
  with the new database, but quotations with parts made in 2.47 show their parts flat (and a too high sum) under 2.46: roll
  back only with a database restore, or do not edit such quotations there.

## [2.46.7] - 2026-10-15

**In short:** fixes for 2.46.6 from the device test.

### Fixed
- **Long press on "Yes" or a suggestion button on Android** (#1711): "Yes, but: ..." is inserted once, not twice.
- **Touch targets** (#1708): the agent's "Lists" summary and the workspace button are 44 px high on touch screens.

## [2.46.6] - 2026-10-15

**In short:** **agent launcher and settings**: the reference launcher brings its own safety rules to every run, one
suggestion per answer, a working-routine file and a wake run after jobs; the agent view shows an agent's lists, setup is
offered right after creating an agent and speaks your language; admin settings live together under Administration.

### Added
- **Fixed safety rules in every launcher run** (#1715): `mcp/agent_rules.md` is updated with the launcher and put in
  front of every chat, task, job and wake run (who gives orders and the language come from Kalmido, `GET /api/v1/agent`
  now returns `lang`); the project's CLAUDE.md is never touched and cannot weaken them.
- **WORKFLOW-KALMIDO.md** (#1717): the agent reads it first for every order and writes a routine you explain into it;
  without it, the first chat after setup asks once. Interim notes go to `NOTIZEN.md`. Help: "Teaching the agent".
- **Wake run after a job** (#1445): a finished, failed, stopped or lost job starts one chat run so the chat agent can go
  on; a job lost to a restart is resumed once in the same session.
- **An agent's lists** (#1708): the agent card lists its lists with folder, who can address it there and whether it
  listens; personal agents show their workspace in their row and can change it (with undo).
- **Set up right after creating** (#1709): a new personal agent (and a new team agent) offers *Set up on a computer*;
  the token only on request. The row shows "Set up" until a computer connected.
- **Pen on approval cards** (#1711): writes "Yes, but: <card>" into the message box (chat and comments), nothing is
  sent; Alt+click, right click, long press. Not on permission requests.
- **"Which agent when?"** (#1716): team or personal agent, in the add dialogs and in `docs/AGENTS.md`.

### Changed
- **Exactly one suggestion** (#1714) per launcher answer, at most 80 characters, never one already offered.
- **Suggestion buttons cut at a word** with "…" at 80 characters (#1722), no longer mid-word.
- **Setup command in the account language** (#1713): `--lang de|en` / `-Lang de|en`, all messages of `setup.sh` and
  `setup.ps1` in German or English.
- **Administration gathers the admin parts** (#1710): the agent rules, the API log and the admins' usage alert under
  *Administration > Agents*, the update check result under *Administration > Server*; the German tab is called *Admin*;
  switches that stay next to your own settings (Modules) carry "Admin · applies to everyone" and a link. Old links land
  in the new place.
- **Members switch with a personal agent** (#1680): a hint under the switch says that only its owner can address it.

## [2.46.5] - 2026-10-15

**In short:** the undo message with the keyboard open now sits above the field you type in.

### Fixed
- **Undo message with the keyboard open** (#1755): it sits above the focused field (or the lowest one, e.g. the
  comment field), no longer above the description higher up in the task details.

## [2.46.4] - 2026-10-15

**In short:** **Contacts sync, share labels, shopping lists**: the Mac Contacts app can change and delete contacts over
CardDAV again, contacts of a deleted address book leave the list at once, Share dialogs say which workspace an item
belongs to, a tap in shopping lists ticks off instead of opening the details, and the undo message fits small screens.

### Added
- **"Tap does not open details"** (#1751): a switch in the list settings; on, a tap on a task ticks it off or back on
  (with undo), the details stay one step away (row menu "Open details", long press > More on a phone, Enter). On for new
  shopping and packing lists; existing shopping and packing lists get it on once (switch it off any time).
- **Workspace line in Share dialogs** (#1737): lists, folders, calendars and address books show "Belongs to:
  <organisation> (organisation)" or "Private" with a sentence on what that means and a link to change the workspace;
  people outside the organisation are greyed out with the reason instead of failing after sending.

### Fixed
- **CardDAV writes from macOS Contacts** (#1736): the address book home now reports full rights to its owner, so the
  Mac app sends changes and deletions again (creating address books from a device stays off).
- **Stable contact ETags** (#1736): a card's ETag no longer depends on the app version, so an update no longer makes
  every client reload all contacts or drop a change made before the update. After this update clients reload once.
- **Deleted address book** (#1732): its contacts, an open card, a selection and a filter on it leave the contacts view
  at once (also when another device deletes it), not only after a reload.
- **Undo message on small screens** (#1755): with the keyboard open it sits above the input field or the keyboard,
  it never jumps over the header or into the content, and it stays on one line (the name is shortened, "Undo" stays).

## [2.46.3] - 2026-10-15

**In short:** fixes for 2.46.2 found by the automatic tests and the device check.

### Fixed
- **Redraws** (#1718): a table cell shows its new value after editing (Esc cancels again), the header keeps its buttons
  on a redraw so a closed dialog gives the focus back to where it was opened, no script error in older test browsers.
- **"New message ↓" / "New comment ↓"** (#1660): the team room shows the pill on a live update too, and the comment pill
  sits above the task's foot on phones.
- **Evening review on Home** (#1452): its *Hide for today* x no longer sits under the block's *...* button.
- **Settings** (#1651): the helper user name field for password managers is fully hidden.

## [2.46.2] - 2026-10-15

**In short:** **Fixes and polish**: views no longer flicker on live updates, renames and list settings show at once,
new chat messages and comments fade in, dialogs move on the desktop, a chat opens in its own window, and a round of
smaller fixes (customers, PDF import, import bar, empty sections, encrypted notes, folders, copying comments).

### Added
- **Dialogs move on the desktop** (#1665): drag any dialog (settings, sharing, list and folder settings, questions) by
  its header; it stays inside the window, a double click centres it again, new dialogs open centred. Phones unchanged.
- **A chat in its own window** (#1719): a button in the head of an agent chat, a team room or a direct message (and a
  middle click) opens just that conversation in a small browser window; the same chat comes back to its window.
- **"New message ↓" / "New comment ↓"** (#1660) in the team chat and on tasks when you scrolled up and something new
  arrives; new messages and comments fade in briefly (off with reduced motion).
- **Copy a comment** (#1666): *Copy* and *Copy as Markdown* on every comment, also on others' and in read-only lists.
- **Dismiss the "differs from the standard" note** (#1726) on Home and project pages; it comes back when your layout or
  the standard changes (synced across devices).

### Changed
- **No flicker on live updates** (#1718): a view that is redrawn (live updates, running agent jobs, calendar, timeline,
  roadmap, agents page) keeps the parts that did not change instead of rebuilding the page; pictures do not reload,
  scroll position, focus, open logs and typed text stay; redraws during busy agent jobs are bundled (at most every 0.4 s).
- **Renames and list settings show at once** (#1659): the list name follows each keystroke in the sidebar and header
  (still one undo step), calendars and address books rename at once, a list moves to its folder or the archive at once,
  ticket templates and key figures save without a reload, a deleted list is gone at once; an error puts the old state back.
- **Empty sections** (#1662): the section name is the one drop target; the extra "Drop tasks here" field is gone.
- **Subfolder to top level by drag** (#1664): drop a subfolder on the upper half of a top folder to make it a top-level
  folder right before it; the lower half still moves it inside.
- **Archive import bar** (#1647): the bottom bar spans the width with a clear edge, buttons on the right; *Paid* is a
  normal check box and date / number are no longer cut off on narrow screens.

### Fixed
- **Customers** (#1472): a customer without a linked list showed "Invalid Date" instead of the month.
- **Legacy PDF import** (#1646): bank and contact values of a template (IBAN, BIC, phone, tax numbers, a bank's name)
  no longer end up in the recipient address; a person above the company becomes the contact (marked for checking);
  a company name on two lines stays together.
- **Settings search** (#1651): browsers no longer fill a saved user name into the search field; secret fields are no
  longer read as a login form.
- **Encrypted note** (#1663): while encrypted notes are locked and the task has no note of your own, the field is hidden.
- **"New API token" button** (#1712): readable again (a danger button instead of red on the accent colour).

## [2.46.1] - 2026-10-15

**In short:** **Lists, sidebar, phone animations**: folder rows read like list rows, lists and sections can be dragged to
the very end, several contacts at once, the legacy import per area, a list channel for listening agents, favourites
grow up, and on the phone sheets, rows and views move softly instead of jumping.

### Added
- **Several contacts at once** (#1554): *Select* in the contacts (a long press on the phone), a bar with the count,
  *All* follows search, group and address book; delete (one question with the number, gone from the phones via CardDAV
  too) or move to another address book you may change. One request for up to 5,000 contacts (`POST /contacts/bulk`,
  MCP `bulk_contacts`); every contact is checked first, nothing changes on a foreign or read-only one. Agents: 10 or more
  contacts wait for a person's approval. Birthday tasks follow (deleted contacts: to the trash).
- **Legacy Excel import per area** (#1557): a switch per area (customers, services, equipment) in the preview, the count
  on the button follows; the import history can undo one area (*Only equipment back*), the whole undo still works after it.
- **List channel for listening agents** (#1639): an agent that listens in a list gets every channel message of a person
  as `team_message` (fields `mentioned`, `listening`), not only @mentions; its own messages trigger nothing. Docs, MCP
  template and the reference launcher (`team_listen`) are updated.
- **Favourites, the rest** (#1361): agents see the person's stars (`favorite` in `GET /lists`), Ctrl+K starts with
  favourites, an optional *Quieter pushes from lists without a star* (off by default; @mentions, replies to you,
  assignments, reminders and approvals still come), and a one-time suggestion for a busy list (never set on its own,
  can be switched off).
- **Switch on all modules** (#1591): a switch under *What do you use Kalmido for?* (setup, purpose dialog, Settings >
  Modules); off = only lists and tasks, whatever the purpose. API: `all_modules` in `/me/purpose`.
- **What is encrypted** (#1641): Settings > Administration > Organisation shows two short lists *Encrypted* / *Not
  encrypted* taken from the server's list of encrypted fields; the same table in SELF-HOSTING.md.

### Changed
- **Folder rows** (#1607, #1643): the arrow stands before the folder icon, the number right after the name, the share
  icon in the lists' share column; a folder row is as high as a list row, no extra room between folders.
- **Sample project only on request** (#1602): switching the purpose asks with a switch *Create a sample project* (off
  by default); *Getting started* stays. API: `/me/purpose` creates samples only with `examples: true`.
- **Family setup** (#1615, #1608): a shopping list (with shop areas) and one list *Family* with the sections Household,
  Birthdays, Meal plan, Deadlines; dishes carry a mark and count from every list; birthdays, deadlines, dishes and the
  CardDAV import without a chosen list go there. New family lists get no automatic colour. Existing lists stay as they are.
- **Shopping lists show the cart** (#1636) in the sidebar, the list header and the search, unless they have an own icon.
- **Office tab "Quotes & invoices"** (#1637, was *Documents*); empty states with one big button under the text, calmer
  three-level tabs, search and filter of the same height.
- **Folder default "Hide completed"** (#1422) works like the other folder defaults (*Only new lists*, the number of
  changed lists, *This list differs* / *Back to folder*), for your own lists.
- **Phone animations** (#1558, #1559, #1560): sheets and dialogs fold up from the bottom and away again; rows fade out
  when completed or deleted and slide off on a swipe; opened and new rows, the dimmed background, the + button, the
  selection bar and hint texts fade; views, the calendar (from its side), the tab underline and the search glide in.
  *Reduce motion* turns all of it off; the desktop is unchanged.

### Fixed
- **Subtasks typed fast** (#1634): a second Enter waits its turn and what is typed meanwhile stays in the field.
- **Module counter** (#1601): quick changes of the purpose no longer leave the counter and the switches disagreeing.
- **Drag to the very end** (#1612, #1635): a list dropped below the last list (or on its own folder header) goes to the
  end; sections and Kanban columns can go last too, and on the phone a long press on a section header drags it.
- **Inline title edit** (#1622): the field stays on the line of the circle and ends before the columns.

## [2.46.0] - 2026-10-15

**In short:** **Organisations and rights**: one kind of server for everybody - organisations plus a private space -, an
admin picks the organisation when adding a person, organisation lists can be open to the whole organisation, and folder
sharing asks before it replaces roles set per list.

### Security
- Security fix (organisation boundary, sign-up) (#1562).

### Changed
- **One kind of server** (#1592): organisations and a private space everywhere (formerly the mode *workspaces*); there is
  no automatic single-organisation mode any more and no membership is added at start. Existing memberships, roles and
  lists stay as they are. Organisation admins can remove members (their lists go to the admin). The user management
  still lists every account for instance admins. `KALMIDO_INSTANCE_MODE=organisation` is ignored; `shared` stays.
  People outside your organisations are reached by sharing a private list by e-mail address; a server without any
  organisation lets everyone see everyone. The login page names no organisation; open registration stays off on a server
  with organisations. Clients follow the organisation boundary for instance admins too. Upgrading: one check at the first
  start of 2.46.0 writes once what the old start-up sync wrote every time (everybody in the one organisation), nothing else.
- **Folder sharing asks first** (#1606): changing a person's or group's role in a shared folder asks *Set everywhere* /
  *Only new lists* when some lists have a role of their own.
- **Organisation settings tidied up** (#1563): one heading and one info link for the encryption block; the boundary check
  unfolds to the affected lists, calendars and address books with a *Clean up* button.

### Added
- **Organisation and role when adding a person** (#1561): *Administration > People > Add* offers the organisation (none or
  one of them) and the role (member / admin); the API takes `orgs: [{id, role}]`.
- **Everyone in the organisation** (#1603): an organisation list can be visible to all members of its organisation
  (read-only until they join, or editable for all); agents only when invited; no notifications for readers.
- **Group pictures** (#1605): a preset or an own photo per group, shown in the share dialogs, the group management and on
  tasks assigned to a group; backups now include profile pictures, list icons and group pictures (a 2.45 server cannot
  restore such a backup).

### Fixed
- Back button between the share dialog and the settings of a folder or a list, without stacking dialogs (#1604).

## [2.45.1] - 2026-10-15

**In short:** fixes for contacts and office master data (no new features apart from the English device name).

### Fixed
- **vCard import with ß** (#1555): a file with an ß (or another letter whose capital form is longer) before a card no
  longer cuts every following card in the wrong place; large address book exports now arrive complete.
- **vCard 2.1 in quoted-printable** (#1555): names, organisations and notes in `ENCODING=QUOTED-PRINTABLE` (with
  `CHARSET`, soft line breaks) are decoded instead of arriving as `M=C3=BCller`; an unknown charset no longer stops the import.

### Changed
- **Devices in two languages** (#1556): a device has a *Name (English)* like services; the device list shows it and the
  search finds it. The legacy Excel import reads *Device DE* / *Device EN* (also *Gerät*, *Name EN* …) as both names,
  shows both in the preview and takes them along on import and undo; separate DE and EN rows are joined only when the
  sheet has an id and a language column. Database: one new column (`office_equipment.name_en`), 2.45.0 keeps running.

## [2.45.0] - 2026-10-15

**In short:** **Sidebar, start page, self-hosting**: the lists move right below Plan, the messenger and all notes are one
click away, the start page is calmer and shows the day in one sentence, and a new server is safer out of the box
(one-time setup code, server key file, backups on).

### Added
- **Messenger in the sidebar** (#1509): a fixed row *Messages* with the unread count in *Conversations*, below it the last
  5 conversations (unread first and bold), a bubble at every person opens the direct message (the row still leads to the
  tasks); shortcut `g n`.
- **All notes in one place** (#1516): *Views > Notes* lists the notes of all lists and projects (pinned first, then
  recently changed) with a list filter, search and *New note* with a list choice; rights as before.
- **Setup code for a new server** (#1515): until the first account exists the server writes a one-time code to its log
  (`docker compose logs kalmido`); the setup page asks for it, 10 wrong tries are rate-limited. Existing servers and the
  login are unchanged. `KALMIDO_SETUP_CODE=off` (tests and automation only) switches it off.
- **Server key file** (#1515): without `KALMIDO_SECRET_KEY` the key is created once in `KALMIDO_SECRET_FILE`
  (docker-compose: `./secret/kalmido.key`, mode 0600, never inside the data or backup folder); the variable still wins.
  *Administration > Whole server* warns when there is no key and reminds you to keep a copy of the key file.
- **Self-hosting kit** (#1515): `install.sh` / `install.ps1` in the repository, proxy examples in `examples/` (Caddy, nginx,
  Traefik), a health check in `docker-compose.yml`, requirements (RAM, CPU, disk, amd64/arm64, Raspberry Pi 4/5 with SSD)
  in SELF-HOSTING.md.

### Changed
- **Start page** (#1504): a greeting with one sentence ("4 tasks for today, 1 overdue, 2 agents working"), *Today* with a
  box to add a task for today, *News* compact (at most 5, a bundle is one line), *Active projects* (at most 5, with
  progress), *Agents* with all running jobs, empty cards as a slim line, two columns (one on a phone), search card off by
  default. Own arrangements keep their order.
- **Sidebar order** (#1503): Plan, Lists, Views, Areas, Filters, Tags, Conversations by default; an own order stays.
- **Sidebar group More** (#1502): All, Completed, Trash and Archived form a folding group like the others (folded on a new
  device, follows *Fold all*); *Tags* has the same header as the other groups; a folded group that holds the open view
  says so.
- **No organisation name under the app name** (#1552) in the sidebar; the login page names an organisation only when the
  server is set to `KALMIDO_INSTANCE_MODE=organisation`.
- **Backups on for new servers** (#1515): daily, with the usual retention; existing servers keep their setting.
- The install guide names no fixed version any more (#1515).

### Fixed
- **Blank page after an automatic reload** (#1529): the reload after an update waits until the page and the stylesheet
  are served; a page that loads without styling reloads itself up to 3 times and then offers a *Reload* button; the
  service worker keeps the old cache until the new one is complete and falls back to it while the server restarts.
- **A new folder in a workspace** (#1532) shows up there at once (it belongs to the chosen workspace).
- The self-hosting part of the README no longer mentions the SQLite check `PRAGMA quick_check` (#1515).

## [2.44.0] - 2026-10-15

**In short:** **Agent starter**: set up a project agent on a **Mac, Windows or Linux computer with one command**, the
reference starter runs on macOS **without PowerShell**, and it learns what a hosted agent service does (permission
questions in the chat, approvals decided in words, files at the answer, long work as a job, a conversation that goes on,
bundled task events, robust runs). The sidebar gets four **areas**: Office, Time, Review, Home.

### Added
- **Set up an agent with one command** (#1517): Settings > Agents > *Set up on a computer*: pick Mac, Windows or Linux and
  the project folder, copy ONE command with a one-time code (15 minutes, used once, stored as a hash, rate-limited). The
  setup script checks python3 and the agent command, stores the token readable only for you, fetches the starter of this
  version and sets up autostart (launchd, Task Scheduler without admin rights, systemd --user), one instance per project
  folder; `--uninstall` removes it. The agent shows its computers (green dot, name, last contact); *Remove computer*
  revokes that computer's token.
- **Permission questions in the chat** (#1442): with Claude Code a tool outside the allow list asks the person in the chat
  (*Allow* / *Deny*, a thumb or yes/no while exactly one question is open); no answer in 9 minutes = no.
- **Approvals decided in words** (#1441): open approval cards are listed in the prompt; an ```approval-done block closes
  exactly the named cards (never as a yes). Open approvals survive a restart, get one reminder after 2 hours and expire
  after 7 days (#1444).
- **Files at the answer** (#1443): files the agent puts into `KALMIDO_OUTBOX` and images it looks at come with the chat answer.
- **Long work as a job** (#1445): `mcp/agent_job.py` runs a background job that survives a restart of the runner, reports
  progress to a Kalmido job, waits for a plan limit and goes on.
- **A conversation that goes on** (#1446): a chat continues one session instead of a fresh run per message; a new one
  starts by size, age, day, model change or reset, with a fenced summary of the old one.
- **Bundled task events** (#1447): task events of lists the agent listens in are collected for 2 minutes and handled in one run.
- **Robust runs** (#1448): HTTP 429 retried, a time limit per run that ends everything the command started, two tries with
  a clear message, a queue on disk and a lock against a second runner.

### Changed
- **Areas** (#1187): Office (Office & finances, contacts, clients), Time (time tracking, focus timer), Review (review &
  journal, statistics) and Home (home & life, family) are one sidebar entry each with tabs; the sidebar shows *Views*
  (calendar, timeline, matrix, project status, workload) and *Areas*. One switch per area in Settings > Modules, the
  parts stay switchable one by one; old links open the right tab; nothing is lost.
- **macOS without PowerShell** (#962): `agent_launcher.sh` runs with the stock bash 3.2 and python3 (no GNU date, no
  setsid); the guide recommends it with a LaunchAgent.

## [2.43.1] - 2026-10-15

**In short:** fixes for the checks of 2.43.0 (no new features).

### Fixed
- The custom period of *Tracked time* uses the app's date picker; *Tracked* in a project header is a full-size touch target.
- The … button of a block no longer covers the *Open / All* switch in the agents view.
- New styles of 2.43.0 follow the text size (rem instead of px).

## [2.43.0] - 2026-10-15

**In short:** **Project pro**: lists with columns work like a **spreadsheet**, **formula fields**, a totals row and **key
figures** on the project page, **dependencies and subtasks by dragging** (also several tasks at once), **blocks adjusted in
place** with a project page that works like a **pinboard** (colours, notepads), tracked time of a project in one window,
and a task in its own window.

### Added
- **Lists like a spreadsheet** (#1331): an active cell moved with the arrow keys, Tab and Enter; typing replaces the value,
  Esc cancels. Paste ranges from a spreadsheet with a preview (columns mapped to fields, extra rows become tasks), copy a
  selection as a table, fill down (Ctrl/Cmd+D or the handle), select several cells and change them at once, a filter per
  column, due date and assignee right in the cell, Enter in the last row adds a task. One Undo per action; on the phone a
  tap still edits the cell.
- **Calculating with custom fields** (#1328): a totals row under number columns (sum, average, count, min, max; owners and
  list admins save the choice for everyone), a new field type *Formula* (`+ - * /`, brackets, `round()`, computed on the
  server, read-only; renaming a field keeps the formula) and *key figures* on the project page (sum, count, average or a
  rate under a condition). API: `GET /api/v1/lists/{id}/kpis`, MCP `get_key_figures`;
  writing a formula value answers 400.
- **Dependencies by dragging** (#1330): drag a task with Alt/Option onto another one in the list or on the board = "waits
  on it"; while dragging, the task panel offers *Waits on* / *Blocks* drop fields. Circles are refused with both task names;
  on the phone the task menu has *Waiting on a task…*.
- **Several tasks at once** (#1003): drag a selection onto a task to make them its subtasks, onto a section, column or
  list to take them out of their parent; the selection panel has *Subtasks of…* and *Out of the parent task*. One Undo,
  order, assignees and dates stay.
- **Blocks adjusted in place** (#1452): every block of the start page, Today, time tracking, agents, projects, the project
  page and the review has a … menu (width 1/3 to full, height, move, hide), a resize handle and a move grip on a computer,
  *+ Block* at the end, and *Set as default for everyone* / *Reset to default* once your arrangement differs (project:
  owner and list admins; other views: instance admins).
- **Project page as a pinboard** (#1346): a colour per block for everyone in the project and notepads (Markdown, own title
  and colour, several per project) that members with write access edit right on the page.
- **Tracked time of a project** (#1434): a click on *Tracked* opens the time by person and task with a period, the latest
  entries and CSV; *Delete all times of this project* (owner and list admins all, members their own, typed confirmation,
  billed time stays, Undo).
- **A task in its own window** (#1500): middle click on a task, *Open in its own window* in the task menu or the button in
  the task panel (computer only).

### Fixed
- The agents card of the start page showed one row per agent, so a second running job of the same agent was missing.
- Moving selected subtasks to another list kept them attached to their parent in the old list.

## [2.42.0] - 2026-10-14

**In short:** **End-to-end encryption** in the browser for a private note and files on a task and for direct messages,
**encryption at rest per organisation** for bank and tax data, purchase rates, framework contract rates and stored
files, an encrypted **organisation export**, and live updates that load only the changed tasks.

### Added
- **Encrypted task note and files** (#828): a note per task and person, encrypted in the browser (WebCrypto, AES-GCM;
  key bundle wrapped with your passphrase and a recovery code). Files can be attached encrypted (no preview, no text
  search). Only you read them; others, agents, the API, CalDAV, search and mail see only that a note exists.
  Settings > Account > *End-to-end encryption*: set up, unlock per session (optionally remembered on this device),
  change the passphrase, reset with the recovery code. Losing both means losing the encrypted content.
- **Encrypted direct messages** (#909): *Encrypted conversation* per direct chat once both people set up their keys
  (ECDH P-256 + AES-GCM), a safety number to compare, a warning when the other key changes, push only "New message from".
- **Encryption per organisation** (#828): with `KALMIDO_SECRET_KEY` set, every organisation gets its own key; bank details,
  tax number / VAT ID, purchase rates, framework contract rates and the stored files (attachments of the organisation's
  lists, invoice PDF/XML; the archive original stays PDF/A-3) are encrypted at rest and existing data is encrypted at the
  first start. Organisation admins can show the recovery key; deleting an organisation destroys its key. Way back before
  a downgrade: `python -m kalmido.admin.orgcrypt_cli decrypt-all` (see SELF-HOSTING.md).
- **Organisation export** (#833): Settings > Organisation > *Export*: one encrypted archive of the organisation's lists,
  tasks, comments, files, calendars, books, office documents and member roles (no private lists, no secrets), ready for
  24 hours; open it with `tools/kalmido_export_decrypt.py` and the organisation's recovery key. Import comes later.
- **Save a comment as a task** (#1383): agent comments get *Save as task* (subtask or new task in the same list), like the chat.
- Reference launcher: suggestion / approval blocks in comment replies become buttons and approval cards (`comment_blocks`).

### Changed
- Live updates load only the tasks changed since the last version and redraw only those rows (#1376); list or sharing
  changes still load everything.

## [2.41.2] - 2026-10-14

### Changed
- **The interface answers at once** (#1501): a list's colour, name, view and display options, folders (rename, move),
  sections (add, rename, order, delete), list tags, custom fields (pin, order), shown fields and settings change on
  screen right away; the server is updated behind it instead of reloading the whole state first. An error puts the old
  value back, other devices and windows get the change with the live update, Undo works as before.

## [2.41.1] - 2026-10-14

### Fixed
- The News badge and an open News view update within the poll again when a comment brings news (#1376).
- Withdrawing comment questions answers 404 for an unknown comment before the agent check (#1383); the per-area change
  counters no longer use a case-sensitive LIKE (#1376).
- Tests that track time switch time tracking on in their lists (#1471).

## [2.41.0] - 2026-10-14

**In short:** Folders show and manage **who they are shared with** (people, groups and several agents in one Share
dialog, folder settings like a list's), **My tasks** can leave lists out, **time tracking** is a switch per list,
chat messages **copy with formatting**, agents can ask with **approval cards in comments**, large **vCard imports**
run in the background, and live updates redraw only what changed.

### Added
- **Share a folder like a list** (#1420): one dialog for people, groups and agents (several agents per folder; the lists
  get the first one as their default), owner row with *Transfer ownership of all lists*, public read-only links of all
  lists in the folder at once, *Folder settings…* in the footer. The former folder agent is taken over; the old field stays.
- **Folders show whether they are shared** (#1428): the person / robot symbols of a list on the folder row (weaker when
  only lists inside are shared), also folded, in the folder view and on phones; the *New list* hint names the folder's
  agents; moving a list into a shared folder says *Now shared with …* with Undo.
- **My tasks per list** (#1365): *Show in My tasks* in the list settings (per person, on by default); tasks of hidden lists
  wait in a folded *Hidden (N)* group with *Show the list again*; assigned tasks due today or overdue stay visible in a
  small *From hidden lists* line. The sidebar count leaves hidden tasks out.
- **Time tracking per list** (#1471): its own switch for every list type, off by default; lists that already have time
  entries keep it on. Tracked time stays in the review when it is switched off. API field `time_tracking`, folder default.
- **Waiting on: recent entries** (#1205): up to eight of your own recent entries below the field (filter while typing,
  x removes one from the suggestions), also in the multi-select dialog.
- **Copy with formatting** (#1374): *Copy* in the chat puts the rendered message (HTML) and readable plain text on the
  clipboard; *Copy as Markdown* keeps the raw text. Suggestion / approval blocks are left out.
- **Notices in the agent chat** (#1206): agents can post a small grey line (`kind: notice`, e.g. after a summary or
  compaction) without push or unread count; the reference launcher sends one on compaction.
- **Approval cards, answer buttons and suggestions in comments** (#1383), the same component as in the agent chat
  (open / answered / expired / withdrawn, only the newest question is live); a press sends the agent one `comment`
  event with the answer. REST `POST /api/v1/comments/{id}/choice`, MCP `request_comment_approval`,
  `withdraw_comment_choices`, `add_comment` with `choices`.
- **Contributor License Agreement** (#1204): [CLA.md](CLA.md); CONTRIBUTING.md points to it, the DCO sign-off stays.

### Changed
- **Folder settings work like list settings** (#1423): switches with a third state *Not set*, saved at once with Undo,
  the list's texts and order, *Agent follows up* as a folder default, tidying only with an agent, *Agent listens* per
  agent, groups and e-mail invitations in the Share dialog.
- **Large vCard imports** (#1437) run in batches (each one saved, the instance is no longer blocked for other writes)
  and, above 100 cards, in the background with progress; the result stays until you close it. A too large file says so.
- **Live updates per area** (#1376): `/api/version` also returns change counters per area (`a`, the total `v` stays);
  comments, chats, news and calendar reload only their part, the sidebar no longer flickers, unsaved form input holds
  the redraw back.
- The *Link* row of a task shows only when a link is set (#1475); *Add link* is in the task menu and under *More details*.

### Fixed
- Permission limits and token overview name the calendar, contacts and private scopes instead of showing their keys;
  agents no longer get a *private* box (#1476).
- The hover dot in the round status circle sits in the middle (#1477).
- An opened job log stays open (and scrolled) when progress arrives (#1479).
- The submenu *More list options…* opens at the menu, beside it on computers, instead of the top left corner (#1439).

## [2.40.2] - 2026-10-14

### Fixed
- The pen next to a long (shortened) task description can be clicked again: the shortened text no longer lies over it (#1203).

## [2.40.1] - 2026-10-14

### Fixed
- Task panel on narrow screens: the pen next to the description (#1203) no longer takes a row of its own, so the panel
  header fits on a 360 px phone again.
- Touch tablets and the unfolded Fold: the view switch in a crowded list header stays a 44 x 44 px touch target (#1361).
- Favourites: removing the star of a list you cannot see answers 404 like starring it (#1361); an own star of a list you
  lost access to can still be removed.

## [2.40.0] - 2026-10-14

**In short:** Office & finance gets ready for **everyday invoicing** (several contacts per client, a country picker,
texts that follow the document language, clearer settings, unsaved input is kept), **favourite lists**, your **own
order in My tasks**, Markdown in task titles, faster tables and a row of fixes.

### Added
- **Several contacts per client** (#1380): name, role, mail and phone, one is the default; quotations, invoices, credit
  notes and reminders pick the contact (the *attn.* line and the buyer contact of the e-invoice follow). The old single
  contact becomes the default contact, the API keeps `contact`. The import preview offers *Add as contact to the client*
  for duplicates that only differ in the contact; undoing the import run removes them again.
- **Archive import reads addresses from PDFs** (#1421): page 1 of an old invoice or quotation suggests a new client, a
  new contact or flags a different address (always a suggestion with a checkbox, no OCR for scans).
- **Country as a picker** (#1372) in the client card, company data and import preview (names in your language, search by
  name or code); the server only accepts ISO 3166 codes (UK becomes GB, EL becomes GR), an unknown stored code stops
  finalising instead of silently becoming Germany.
- **Producing and raw-footage surcharge can be switched on and off** (#1379) in the Office settings; off for new
  organisations, organisations that already use them keep them on. Existing and finalised documents stay as they are.
- **Selectable label for the managing people** (#1377): managing directors, partners, owner, board on the document footer.
- **Office settings explained** (#1382): (i) help for the technical terms, number schemes with insertable building blocks,
  a live preview of the next number for all four schemes and plain-language errors.
- **Favourites** (#1361): star lists and projects, only for you; a *Favourites* section at the top of the sidebar,
  *Only favourites* folds the rest under *More lists (N)*, Today, Tomorrow, Next 7 days, Doable now and My tasks can be
  filtered to favourites.
- **Your own order in My tasks** (#1344): drag tasks into your personal order (shared lists stay unchanged for
  others), *List › Section* under each task, new and newly assigned tasks on top; *Grouped by list* stays available
  (dragging into another group moves the task there). My tasks sits right below the Basket and is always shown.
- **Markdown in task titles** (#1409): bold, italic, code and links show in rows, calendar, timeline, roadmap and
  dashboard; push, mail and calendar feed get plain text. *Convert to subtasks* keeps indented lines as the subtask's
  description and the earlier description can be restored from the activity.
- **Priority as background** (#1416): an option under Appearance tints rows and cards by priority (off, subtle, strong).
- **Load more** (#1432): jobs (20, then 50 at a time; running ones always on top), Completed and Trash (100 at a time) and
  News (50 at a time) no longer load everything at once; counters, *Empty trash* and *Mark all as read* still cover all.
- **List admins** may manage custom fields (#1192, deleting asks with the number of affected tasks) and change the name,
  icon and colour of a list (#1431, the owner gets a news item on a rename).
- **Choice fields** (#1193): colour palette, filled coloured chips with readable text, options can be reordered, a
  *Status* template.
- **Reference launcher** (#1347): an answer that asks for a decision or proposes something without an approval block goes
  back to the agent once, then gets a visible note (`KALMIDO_APPROVAL_CHECK=0` turns it off); blocks only count at the
  start of a line, closing blocks in any order, long answers keep code blocks intact when split, suggestions become reply
  buttons. See [docs/AGENT-SETUP.md](docs/AGENT-SETUP.md).

### Changed
- **Document language** (#1381, #1363, #1368): switching the language of a draft also switches intro, closing, rights
  texts and position titles that are still the default; texts you changed stay, with a note. The settings show the
  English texts in the English fields and mark building blocks without English text.
- **Invoices** (#1368): new closing text without a due-date statement, own closing text for credit notes, reminder texts
  per level, a credit note takes the e-invoice format of its invoice, buyer address from free address lines read
  correctly (postcode line), *Total* in reminders and *Qty* in English tables. A reminder fee stays an open item after the
  invoice is paid (waive or mark paid), fully paid reminders show as done, hints for high fees and not yet due invoices;
  the send dialog without mail offers *Download PDF*.
- **PDF buttons** (#1364, #1366): *Preview (PDF)* instead of the raw print model, the PDF opens in the browser with a
  separate *Download* button (also for archived PDFs).
- **Project progress bar off by default** (#1190), switched on per project in the list options; the X on the bar is gone.
- **Columns from 600 px** (#1191): tablets and the unfolded Fold show custom fields as real columns in lists.
- Sidebar header (#1345): the organisation name gets its own line; the agent chat header keeps the name in full.
- *Agents may address each other* is gone (#1373), agents never address each other; the API still accepts `agent_peers`
  and ignores it (deprecated).
- The word *chip* is gone from the texts (#1429).

### Fixed
- Office settings: unsaved input survives switching views and live updates, with *Save / Discard* and a question
  before leaving the page (#1371); logo upload and settings import work again (#1378).
- Phones: a tap that stops scrolling no longer opens the description editor, a pen button edits it (#1203).
- Tables: column guide lines no longer stay behind, live changes are bundled into one redraw (#1430).
- Folders: a new list is no longer marked as different for the same workspace; *Hide completed* now only applies to your
  own lists, as the dialog says (#1422). A new project in a folder with an agent no longer offers to share it again (#1414).
- Archiving by a list admin informs the members (#1337); empty-state buttons no longer stick to the text (#1415).
- Smaller fixes from the 2.39.1 review: size limits for the group order (#1334), the archive PDF is written only after the
  commit (#1335), an index for the reminder mail count (#1336).

## [2.39.1] - 2026-10-12

**In short:** Lists with columns now work **like a spreadsheet**, the inbox becomes the **Basket** with a *Sort* mode,
Office & finance can **import legacy data** from an Excel workbook and keep old invoices as an archive, and a long row of
phone and interface fixes.

### Added
- **Lists like a spreadsheet** (#1217, #1327): fine column lines across all rows, column widths follow the mouse (no
  snapping, the title keeps a minimum width, widths are kept per device and list), **drag a column heading** to reorder
  the columns (undo works). Click a custom-field cell to **edit it in place** (number, text, link, date, choice with its
  colours, person, checkbox; Enter or a click outside saves, Esc cancels, Tab moves on); a small arrow on the column
  heading opens the column menu. *Shown fields* can add, rename and delete custom fields. **Custom fields now work in
  plain lists** too (columns, details, filters); time tracking and dependencies stay with projects. List admins may now
  manage custom fields like the owner.
- **The inbox is now the Basket** (#1219): same place, new name in every language (internal names such as `is_inbox` stay).
  A **Sort** button walks through the basket item by item (to a list, assign to me, today, tomorrow, a date, waiting
  for someone, delete, skip; keys 0-7, Esc ends; large buttons on phones). *My tasks* keeps showing what is assigned to
  you and adds a collapsible group *From your lists, no date* with the open tasks of lists only you use.
- **Group headings show their origin** (#1221): *Folder › List* in My tasks and other cross-list views, every part
  clickable; groups can be reordered (drag the handle, long press on phones), the order is kept per view on every device,
  *Reset order* in the view menu.
- **Sidebar: Views and Areas** (#1185): *Views* (calendar, timeline, matrix, project status, workload) and *Areas*
  (office, time, contacts, habits, focus, review, statistics, home, family, agents); your own arrangement stays. One
  icon in the sidebar header collapses or expands everything.
- **Legacy data import for Office & finance** (#1182): upload an .xlsx workbook, Kalmido splits the one-field addresses
  of the *Contacts* sheet into company, contact, street, postcode, town and country, marks unsure splits, finds
  duplicates and lets you correct everything in a preview before importing; services and equipment come along. Old
  invoices and quotations are uploaded as PDFs into a **read-only archive** (details suggested from the file name),
  new numbers never collide with archived ones, and every import run can be **undone**. Only organisation admins import.
  See [docs/OFFICE.md](docs/OFFICE.md).
- **Settings > Organisation** (#1188): members and roles, *Lists of the organisation* (shared lists in the organisation's
  area, grouped by owner, with their folder path) and the history in one place.
- **Hide completed as a default** (#1214): a personal default in *Settings > Appearance*, a folder setting that applies
  to its lists and subfolders, and every list can still choose for itself (*Completed: as default* resets it).
- **Open a list in its own window** (#1294): double click or middle click a list in the sidebar, or *Open in its own
  window* in the list menu (desktop): a slim window with only that list, live updates included.
- **Use a suggestion as a draft** (#1224): the pencil on a reply suggestion in the agent chat (or right click / long
  press) puts its text into the input field instead of sending it.
- A **loading screen** with the heron and a running bar while the app starts (#1213).

### Changed
- **List admins may delete shared lists** (#1188), still in two steps (archive first); the tasks go to the owner's
  trash and the owner is told. Server admins get no extra right on other people's lists. Moving a list into a folder
  with defaults (area, agent) now asks first.
- Custom fields created or shown as columns through the API **switch the *Custom fields* module on** for the list's
  owner; the answer names it in `modules_on` (#1293).
- List menu texts say what they act on: *Archive list*, *Delete list…*, *Restore list from archive* (#1291).
- The celebration has more punch (#1292): the heron in the middle, a big check mark, colourful confetti, three levels
  (today, list, project), a short vibration on phones, a tap ends it; *Reduce motion* keeps the calm version.
- Office: **only organisation admins record payments** and mark invoices as paid; a manual invoice number that skips
  numbers needs a reason; members may send at most 50 mails with their own text per organisation and day (#1210).

### Fixed
- Phones: bottom sheets can be dragged to a height and swiped down to close (#1181); the whole app no longer slides
  away when you swipe past the end of the sidebar on foldables (#1189); the paper clip in the comment field can be
  tapped without typing first (#1202); statistics charts with round axis steps, no cut-off labels and the explanation
  behind an info icon (#1180).
- The dimmed backdrop of the *Add service* dialog covered only half of the window (#1220).
- Office files restored from a backup are private (0700) and document items always belong to an organisation; larger
  tap targets for *More info* in the Playbook section (#1210).

## [2.39.0] - 2026-10-12

**In short:** Every list and folder can have a **Playbook**: the owner's working rules for the agents of that list, with
versions, agent proposals and optional scheduled checks. The tidy agent of a list can now **tidy up an existing list**
(a proposal first, nothing changes before you confirm, one step to undo), and your own **messages to an agent can be
edited** afterwards.

### Added
- **Playbook per list and folder** (#1168): Markdown rules (up to 8,000 characters, with preview) that every agent event
  of the list carries along; a folder's Playbook applies to all lists inside it and a list adds its own part. Only the
  owner and list admins write it; agents read it (`get_playbook`) and may only **propose** a change, which a person takes
  over, edits or discards. Every save is a **version** (who, when), with a line comparison and *Restore*. A list can be
  **checked on a schedule** by one of its agents (for example every day at 07:00), switchable off at any time; the check
  event carries the Playbook and the open tasks the agent may see. The Playbook travels with templates, the account
  export and backups. See [docs/AGENTS.md](docs/AGENTS.md#playbook-2390).
- **Tidy up a list** (#1151): *Tidy up the list* in the list menu (or for the selected tasks) asks the list's tidy agent
  for one bundled proposal: merge duplicates, rename, move to a section, close as *won't do* with a reason. Nothing
  changes until you confirm in the proposal sheet; the whole run is **undone in one step**. Tasks somebody is editing or
  that changed since the agent looked are skipped and listed, the bulk-change protection stays, open subtasks of a merged
  task move to the kept one, and the list's Playbook goes along with the request. See
  [docs/AGENTS.md](docs/AGENTS.md#tidy-up-a-list-2390).
- **Edit your own messages to an agent** (#1179): *Edit* in the menu of your message in the agent chat, marked *edited*
  with the earlier versions (only for you), the same way comments and team chat messages are edited. A message the
  agent has not fetched yet is simply replaced; once fetched or answered, only that agent gets the new event
  `message_edited` with the old and the new text and keeps its running work. Edited comments and team messages an
  agent already had send the same event. MCP, the agent template and the reference launcher know the event.

### Fixed
- Office & finance hardening after the review of 2.38 (#1209): finalising a document and credit notes are serialised,
  control characters are removed from document and client texts (well-formed e-invoice XML), a sent quotation can no
  longer return to draft, invoice mails carry the company's address as *Reply-To*, client lists respect the organisation
  boundary for every account, and new document folders are private to the app.

## [2.38.0] - 2026-10-12

**In short:** Office & finance can now **issue invoices**: invoices, credit notes and payment reminders with a GoBD-style
number series, exact amounts, **ZUGFeRD / XRechnung e-invoices** inside PDF/A-3 files, payments, sending by e-mail and a
copy to the DATEV document inbox. On phones, a long press on a task title always starts the multi-select, *Move to list*
shows folders like the sidebar, the installed app no longer zooms by accident, and the list colour tints the whole icon.

### Added
- **Invoices, credit notes and reminders** (#1021, stage 2 of Office & finance): a quotation becomes an invoice with one
  click (positions condensed, rights and framework-contract text carried over, PO number and service period), invoices can
  also be built from time entries or from scratch. The **number is assigned when the document is finalised** (drafts have
  none, so deleted drafts leave no gap), one series per kind and organisation, unique, and nothing can be changed after
  finalising or sending; a cancellation is a **credit note** that points at the invoice. Amounts are exact decimals
  throughout; invoices in USD state the tax in EUR with the exchange rate. **Payments** (paid / partly paid / overdue) and
  **payment reminders** (three levels, fee, deadline, the invoices listed) use the same model. Documents are **sent by
  e-mail** from Kalmido (PDF, for invoices also the XML), optionally with a copy to the **DATEV document inbox** (address in
  the module's settings). Not in this release: the DATEV booking batch (CSV), shooting calculation, quotation to project,
  importing old documents, a pack catalogue and a bookkeeping role.
- **E-invoices and PDF/A-3** (#1021): finalised documents are written as PDF/A-3b with the embedded font Liberation Sans
  and an sRGB output intent; invoices and credit notes carry a **ZUGFeRD (EN 16931) XML** inside the PDF or, for public
  buyers with a routing ID, a separate **XRechnung** XML (download in the document). The PDF and XML are stored at
  finalising with their SHA-256 and served unchanged afterwards; drafts print with a "Draft" mark. The build checks run
  veraPDF and the KoSIT validator against generated samples (`tools/einvoice_validate.sh`).

### Changed
- Quotations are locked once they are sent (change them by duplicating), as decided for stage 2 (#1021).
- The list colour tints the **whole list icon** in the sidebar and everywhere a list is shown; emoji and picture icons sit on
  a tinted tile (#1174).
- *Move to list…* (task menu, chat notes, inbox) shows the lists in the **order of the sidebar with their folders**, and menu
  sheets on phones have a head with a close button (#1177).
- The **installed app** (home screen) no longer zooms on pinch or double tap; picture lightbox, file view and timeline keep
  their zoom, and a browser tab can still zoom to 200 % (#1173).
- Multi-edit **skips locked tasks** and changes the rest instead of stopping (#1132).

### Fixed
- A long press on a task title on a phone starts the **multi-select** instead of selecting text (#1178); the sidebar no
  longer selects text on a long press either (#1155).
- iOS: *Save as task* saves on the **first tap** on Save while the keyboard is open (#1170).
- Chat: the part mark of split answers is shown in italics; the command palette folds ae / oe / ue like the message search
  (#1171).
- Message search with only special characters answers an empty list instead of an error (#1169).
- Phone touch targets of 44 px for *Duplicate* and *Finalise* on documents and the calendar row of *Plan my day*; a quick
  add left open no longer leaves its veil over the agent chat (#1155).
- Security fix (admin alerts): addresses in alert texts are masked; the full log stays in the database (#1155).
- An assignment taken away from someone who cannot see the list now tells them with the list name only; read entries of the
  office access log are pruned after 90 days (#1155).

## [2.37.1] - 2026-10-11

**In short:** a maintenance release for 2.37.0 without changes to the app's behaviour: the build checks pass again.

### Fixed
- The module list of the server package names the three new 2.37.0 modules (the Postgres layer, row-level security and
  the move from SQLite), and the layout check lists saved chat messages as a person's own rows (#1150, #1159).
- The test suites run in nine parallel groups instead of eight: the last group had grown past the 30 minute limit.

## [2.37.0] - 2026-10-11

**In short:** Kalmido now runs on **PostgreSQL 17** only, for every installation. **Self-hosters: this update needs
action** - add the database service to your compose file and set a password (see *Upgrading* below); your data moves
over by itself on the first start. The organisation boundary is enforced **in the database** as well (row-level
security), backups use `pg_dump`, any chat message can be **saved as a task** or **copied** as a whole, folder
settings explain themselves, and finished agent jobs leave *Open* without a reload.

### Upgrading (self-hosters, required)
- **PostgreSQL is required** (#1150); SQLite is no longer supported. Take the new `docker-compose.yml` (service `db`
  with `postgres:17`), put `POSTGRES_PASSWORD=<long random letters and digits>` into `.env`, then
  `docker compose pull && docker compose up -d`. Without `DATABASE_URL` Kalmido does not start and prints these steps.
- **Automatic move:** on the first start Kalmido copies `data/tasks.db` into the empty database in one transaction,
  compares row counts and checksums of every table, and only then renames the old file to
  `tasks.db.migrated-<time>` (never deleted). A report lands in `data/backups/migration-report-<time>.json`, a copy
  of the old database in `data/backups/pre-postgres-<time>.db`. If anything does not match, nothing is kept in
  PostgreSQL, `tasks.db` stays untouched and the container stops with the reason in its log.
  Dry run first: `docker compose run --rm kalmido python app.py migrate-sqlite --check`.
- **Way back:** pin the 2.36.2 image, rename `tasks.db.migrated-<time>` back to `tasks.db`, start. Changes made after
  the move are not in that file. Step by step: [docs/SELF-HOSTING.md](docs/SELF-HOSTING.md#upgrade-to-237-postgresql-required).
- **Own or managed PostgreSQL:** use a database owner without superuser/BYPASSRLS, or let Kalmido create its role
  `kalmido_app` (needs CREATEROLE). If row-level security cannot be enforced, Kalmido refuses to start in workspace
  mode and raises a security alert on every start otherwise. New settings `KALMIDO_DB_STATEMENT_TIMEOUT` (seconds,
  default 30) and `KALMIDO_DB_POOL_MAX`.
- The app image is about **80 MB larger** (PostgreSQL client for backups).

### Changed
- **PostgreSQL instead of SQLite** (#1150). Searching messages finds word beginnings and parts of words with and
  without umlauts as before (trigram index).
- **Backups** (Settings > Administration > Backup) contain a `pg_dump` of the database (format 2). A restore takes
  only tables and data from a backup; functions, triggers and access rules are always rebuilt by Kalmido itself.
  **Backups from before 2.37** (with `tasks.db`) can still be restored: they are moved over like the database above.
- **Instance admins see contents of their own organisations only**; admin overviews of other organisations show
  counts. The admin interface is per organisation, a backup still covers the whole instance.
- **Search takes your text literally:** `%`, `_` and `\` in a search are plain characters now.
- **Invalid values** sent to the server are refused with "Invalid data" (400) instead of being stored.
- **API:** `snippets` of a task is `null` when there are none (was an empty string).
- **Private agents in organisation lists:** an agent without a workspace no longer sees lists of an organisation it
  was added to before 2.28; the move report and the organisation boundary check name these cases (assign the agent
  to a workspace).
- **Folder settings** (#1158): *Folder settings…* is always in the folder menu, also for a folder holding only lists
  shared by others (they keep their own settings); *Share folder…* stays visible but greyed with the reason; the check
  before saving reads "Not saved yet" with "Save anyway"; *People and roles…* and *Repository…* open on top with
  *Back*, and closing with unsaved changes asks first.

### Added
- **Save a chat message as a task** (#1159): every message in agent and team chats has *Save as task*: the full text,
  its files and a link back to the message, into a list you can write to (default Inbox), optionally due "to review
  by". A saved message shows *Saved*. Agents can offer the button (`offer_save` with `send_chat`), never save
  themselves.
- **Copy a whole message** (#1165): *Copy* in the same message menu copies the Markdown text; an answer that was split
  into several parts is copied as one.
- `python app.py migrate-sqlite [--check] [--source FILE]` for the move by hand.

### Fixed
- **Agent jobs** (#1161): a finished job no longer stays under *Open* until you reload; the list reloads when the app
  comes back to the foreground and ignores late answers.
- Public forms and links opened by someone signed in to another organisation work like for visitors.

### Security
- **Row-level security per organisation** (stage 1): every table with an organisation and the organisations
  themselves are protected in the database. A database permission error answers 403 and is counted for the admin
  alerts.
- Backups: hardened restore checks.

## [2.36.2] - 2026-10-11

**In short:** Organisations hardened, intrusion alerts, the office foundation and many small things. This release
contains **security fixes** (organisation boundary, office & finance, admin alerts); it was rolled out before it was
published, details stay out of this note (see [SECURITY.md](SECURITY.md)). Lists show their **line icons
everywhere**, the sidebar tells **people from agents** at a glance, projects can keep **completed tasks in their
section**, quick add in *Tasks of <person>* assigns the task, and a new view **Assigned by me**. Office documents can
be **finalised**.

### Security
- **Security fix: organisation boundary and access layer** (#1142). One central access layer with a request context
  (the person and all of their organisations) decides which lists, calendars and address books someone may see; it is
  the base for database row-level security later.
- **Security fix: office & finance** (#1142, #1146), with an access log for organisation admins.
- **Admin alerts for intrusion signs** (#1133): new instance admins, organisation admins, agents and agent tokens and an
  admin sign-in from a new address are reported as *Security events* (switchable like the other alert kinds), plus one
  `kalmido-security:` JSON line per event in the server log for log watchers. See *Intrusion alerts* in
  [docs/SELF-HOSTING.md](docs/SELF-HOSTING.md).
- [SECURITY.md](SECURITY.md) describes the disclosure order: fixes go live first and are published afterwards (#1134).

### Added
- **Office & finance foundation** (#1021): documents can be **finalised**: number, totals, sender, recipient and tax
  rates are frozen and a finalised document can only be duplicated (quotations stay editable as before unless you
  finalise them). Quotations can optionally get their number only when finalised. A **period of service** per document.
  **Structured company data** and **client billing details** (address fields, country, tax and VAT numbers, IBAN,
  buyer reference); printed lines are built from them, the free lines remain as a fallback. An **access log** (document
  history, settings) for organisation admins.
- **Keep completed tasks in their section** (#1136): a list setting (list dialog and list menu), on by default for
  projects and lists with sections, always off for shopping lists and lists that show completed at the bottom; section
  heads show "3/8 done".
- **Assigned by me** (#1138): a new view with the open tasks you created or assigned to someone else, grouped by person.
- **List colour by right-click / long press** in the sidebar (#1135): nine colours plus none.
- **Job links in the agent chat** (#1141): "Job #50" opens the job (new route `#job/<id>`, unfolded with its history)
  instead of task #50; jobs you cannot see stay plain text.

### Changed
- **List icons everywhere** (#1135): with *Line* or *Dot* the list header, task chips, the task path, move menus, quick
  add, search, groups, archive and roadmap show the line icon instead of the name's emoji (the name itself is
  unchanged); *Emoji* keeps the old look.
- **People or agents in the sidebar** (#1139): a person icon, a robot in calm blue, or both, always visible; agents get
  the same robot where they write in chats and comments.
- **Quick add in "Tasks of <person>"** (#1138) assigns the task to that person in a list you both use (shown as a chip,
  changeable) and keeps it in the view; without such a list you get a hint instead of an unassigned task.
- **Chat header** (#1140): the permission badge is small grey text without a frame, with an invisible 44 px touch area.

### Fixed
- Phone: live steps line up with "… is writing …", the permission badge keeps its distance from the name, and the
  sidebar's "N approvals open" updates right after answering in the chat (#1123).
- Phone tap targets of 44 px: icon grid of the list dialog (#1130), calendar switches and "Per list", the calendar lines
  of *Plan the day*; *Office & finance* is in the *More* sheet; the quotation's PDF button has a label (#1146).
- Office: the master-data import leaves unknown references empty and reports them; unfinished logo uploads are left out
  of backups (#1146).

### Agents
- Behaviour rules (template, in-app guide, AGENTS.md, AGENT-SETUP.md): security fixes are rolled out first and
  published after; commit messages and changelogs name only "Security fix" and the area.

## [2.36.1] - 2026-10-10

**In short:** Office & finance, stage 1, plus calendar switches. A new **Office & finance** module for organisations
with master data (services and rates, equipment and sets, text blocks with a rights catalogue, framework contracts, a
German country pack) and **quotations** with a live calculator and a **PDF** on real A4 pages. In the calendar,
**subscribed calendars, own calendars and tasks** can be switched on and off right from the calendar view, per
calendar also for *Today* and for *Plan the day*, and event titles in the phone timeline no longer run over each other.

### Added
- **Office & finance module** (#1021, stage 1): a switchable module in the business area (needs an organisation),
  with a new setup purpose *Office & finance* (Team plus clients, workload, forms and the office module). Tabs:
  quotations, services (DE/EN names, categories, daily/hourly rates, raw data and producing flags, tax rate),
  equipment and sets with a set discount, text blocks (intro, closing, notes, free blocks, rights catalogue for
  duration, territory and media), several framework contracts with special rates, and settings (company lines,
  logo, print colour, document language, currency and USD rate, number scheme with preview, producing quotient and
  rate, raw data factor, validity, country pack). Organisation admins edit master data and settings, members read
  them and write quotations; agents and children have no access in this stage.
- **Country pack DE** as a data file: VAT 19 % / 7 % / 0 %, date and number formats, document labels in German and
  English, default texts and the rights catalogue. Packs are validated on load.
- **Quotations** (#1021): positions picked from your services in the document language, quantities with comma or
  point, headings and text blocks between positions, automatic lines for **producing days** (production days divided
  by the quotient, rounded to half days), **optional or included raw data** and a **discount**, each explained in
  plain words; EUR or USD, with or without VAT; a framework contract presets raw data, rights and closing; a
  **transfer of rights** block (duration, territory, media, exceptions, exclusivity); own fields; status draft / sent /
  accepted / declined; duplicate; numbers from your scheme. Totals are calculated on the server; external costs and
  the surplus are visible to organisation admins only.
- **PDF quotations** (#1021): A4 pages in a DIN 5008 layout (address window, key data on the right, table with
  category headings, raw data option, totals, rights section, order confirmation field, four-column footer), several
  pages with a short header, repeated table head and "Page x of y", German or English labels, EUR or USD. Built
  without any new dependency.
- **Company logo** for documents: organisation admins upload a PNG, JPEG or WebP; it is part of backups.
- **Master data import / export** as one JSON file (admins import, additive or overwriting matches).
- **Calendar switches** (#1127): the *Calendars* window (button in the calendar header, a sheet on phones) lists
  *Tasks with a date* (all, and per list), your own calendars and subscriptions, each with three switches:
  *Calendar*, *Today* and *Plan the day*. Tapping a calendar's name in the timeline hides it (with *Undo*), its menu
  offers *Only this calendar* and *Show all*. Changes apply at once and follow you across devices.
- **Today's events per calendar** (#1127): the *Events today* block on Today has a menu with its own switches,
  independent of the calendar view.
- **Leave calendars out of the day plan** (#956): calendars switched off for *Plan the day* are ignored by the day
  planner and by *Agent plans the day*; the *Plan the day* dialog has a *Calendars* row with the same switches.

### Changed
- **Day planning counts your own events** as busy time too, not only subscriptions (#956); all-day events still do
  not block time.

### Fixed
- **Phone timeline** (#1126): every calendar has its own row, titles stay inside their bar and end with "…" before
  the next event, overlapping events move to their own sub-row, tapping an event shows its full title.

### Upgrade notes
- New tables only: `office_settings`, `office_services`, `office_equipment`, `office_sets`, `office_texts`,
  `office_contracts`, `office_numbers`, `office_docs`, `office_doc_items` (all tied to an organisation and deleted
  with it). Logos are stored under `office/<organisation>/` next to the database and included in backups.
  2.36.0 keeps running on the migrated database.
- New user settings `cal_tasks`, `cal_lists_hidden`, `today_cals_hidden`, `plan_cals_off`; existing accounts keep
  everything visible.
- The office module has no agent API or MCP tools yet; they follow after a security review.

## [2.36.0] - 2026-10-09

**In short:** Sidebar, lock and comments. The sidebar gets calm grey **line icons** instead of emojis, a task can be
**locked** against accidental edits (tasks created by agents start locked), selecting text in a description no longer
opens the editor, code blocks in comments **wrap**, an open task **keeps its scroll position** when something new
arrives, and the **Paperless connection is removed**.

### Added
- **Lock a task** (#1118): the lock button at the top of a task makes title, description, dates, priority, list, tags,
  repeat and assignee read-only until someone who may edit the task unlocks it; comments, checkboxes in the
  description, completing / reopening and subtasks stay free. A small lock shows in the task row; trying to change a
  locked field says so and offers *Unlock*. Dragging, multi-select, shortcuts and *Skip this occurrence* respect the
  lock, undo and the history record it. Read-only members cannot toggle it.
- **Tasks created by agents start locked** (#1118): the agent API and MCP read and write the new task field `locked`
  (`locked: false` on create keeps a task open); the lock only guards the app, agents keep changing tasks through the
  API.
- **Sidebar settings** (#1117): *Settings > Appearance > Sidebar* offers list icons as *Lines* (default), *Emoji* or
  *Dot*, and a switch for the progress bars in the sidebar (on by default). The line icon set grows to 200; lists with
  an emoji in their name get a matching line icon, and new lists get one suggested.

### Changed
- **Calmer sidebar** (#1117): grey line icons with the list colour as the icon's dot (the emoji stays in the name),
  the share icon shows on hover or keyboard focus (always on touch devices), progress bars are 1 px and respect a
  project's own *Hide progress*, folder heads are quieter.
- **Agent chat** (#1110): the suggestion button sits below the time and reactions of the agent's message; permission
  questions and approval cards are unchanged.
- **Agent rules** (template, guides, in-app setup): commands and code for the person always go in their own fenced
  code block with a language, one block per place, one command per line, no prompt sign (#1100); the rules explain
  locked tasks.

### Removed
- **Paperless connection** (#1116): linking documents, sending attachments, personal and server connections, the
  module switch and the *Paperless access* user right are gone. `PAPERLESS_*` variables are ignored; existing link
  data stays in the database untouched.

### Fixed
- Selecting text in a task description (drag, double or triple click, long press) no longer opens the editor; clicks
  in code blocks, tables and links never do (#1118).
- Code blocks in comments and in the description wrap like in the chat instead of scrolling sideways; no scroll bar
  covers the next line, *Copy* still takes the original text. A comment's quick reactions no longer cover its Reply /
  Edit / Delete buttons (#1119).
- An open task keeps its scroll position when a new comment or chat message arrives; reading at the end, you stay at
  the end (#1120).

### Upgrade notes
- New column `tasks.locked` (default 0 = open); existing tasks, including those created by agents before, stay open.
  2.35.0 keeps running on the migrated database. The Paperless tables and `users.paperless_access` are kept.

## [2.35.0] - 2026-10-09

**In short:** Agents, chat and polish. Agents **ask for approval with a card** (Yes / No, pinned until answered,
counted at the agent), tasks in software projects get **code snippets** (plain code with highlighting that agents read
and write), **#123** links the task everywhere, **Customize** arranges blocks right in the view, organisation admins
**manage the lists of their organisation**, links to **files on network drives**, and the reference **agent launcher**
catches up with live steps, model, permission mode, usage ring, reply reference and approvals.

### Added
- **Approval requests in the agent chat** (#1103): an agent marks a message as an approval request (`approval` on
  `POST /api/v1/agent/chats/{id}`, MCP `request_chat_approval`). It shows as an *Approval needed* card with Yes / No,
  pinned at the top of the chat and counted at the agent in the sidebar, on its card and at the chat button until it
  is answered; afterwards the card shows who approved or declined and when. Only the person of the chat answers, never
  an agent; the answer reaches the agent as `chat_choice` with `approval`, silence is never a yes. At most 10 open
  requests per agent and person. Push *Approval needed* uses the existing switch *An agent waits for my approval*
  (at most 5 an hour per agent).
- **Code snippets** (#1095): tasks get a *Code snippets* section (always in software projects, elsewhere from the
  task menu): plain code with syntax highlighting (language picked or recognised), optional file path and line (opens
  the list's repository when one is connected), Copy, a code editor with Tab indentation. Pasting code into the
  description offers to keep it as a snippet. Search finds code; duplicating and templates keep the snippets. Agents
  read and write them (`snippets`, `POST /api/v1/tasks/{id}/snippets`, MCP `add_snippet`); task events carry a
  shortened copy.
- **Task links** (#1096): "#123" links the task in the agent chat, the team chat, comments and the description, with
  the title as tooltip; tasks you cannot see stay plain text. Links to the app itself open in the same window.
- **Arrange blocks in the view** (#1097): *Customize* shows the blocks of a view (start page, Today, project page,
  overviews) in place: drag a block by its handle (phone: hold, then drag; the view scrolls at the edge), hide it or
  switch its width at the block, bring hidden blocks back, undo every change. The list with arrows stays for keyboard
  and screen reader.
- **Lists of the organisation** (#1101): organisation admins see the lists that belong to their organisation (name,
  owner, numbers, never contents) under *Settings > Account > Workspaces*, and can archive, restore, hand over to
  another member or delete them from the archive after typing the list's name (tasks go to the owner's trash). Owner
  and members are told, every action is in the history. Private lists, private sharing and inboxes stay out of reach;
  agents never get this.
- **Links to files** (#186): task links, key links of projects and link fields accept links to files on network
  drives (`smb://`, `afp://`, `nfs://`, `webdav(s)://`, `file://`, `\\server\share`); `file://` and Windows paths
  show as a copy button because browsers do not open them.
- **Agent launcher event mode** (#1098): `agent_launcher.sh|.ps1 --events` (new `mcp/agent_run.py`) starts one fresh
  headless run per event and reports live steps, the real model and permission mode, typing and status, the plan
  usage ring from Claude Code's stream (with its measurement time; stale values count as unknown), the reply
  reference and approval cards; older servers keep working. Plan usage passes through every window Claude Code
  reports.
- **Checks for new agents** (#1098): both launchers must implement every capability in
  `mcp/launcher_capabilities.json` (`tests/launcher_parity_test.py`), and every agent event, agent endpoint and MCP
  tool must be documented in the guides and the agent template (`tests/agent_docs_coverage_test.py`).

### Changed
- Agent rules (template, guides, in-app setup): one short sentence in the person's language before each tool step;
  approvals only as approval requests with buttons, silence is never a yes; the 2.34 tools are described (#1100).
- The agent's step lines line up with "… is writing …", with a thin accent line (#1099).
- The list menu no longer has *Refresh*: the app checks for changes every few seconds, the offline hint still
  refreshes on tap (#1105).

### Fixed
- New texts no longer appear in English after an update while the browser holds an old language file: language
  files load with the app version, a stale copy is replaced in the background without a reload, and the automatic
  reload waits for the second report of the new version (#1094).
- Mac: scrolling to the end of a chat no longer moves the page beside it (agent chat and team chat) (#1102).
- Phones: the tap areas in the agent chat header no longer overlap (the permission badge moves under the agent's
  name); the (i) of the agent switches in the share dialog
  sits at the edge of its row; planned agent jobs show dates in your date format (#1107).

### Upgrade notes
- New table `org_list_log`, new column `tasks.snippets` (default empty); 2.34.0 keeps running on the migrated
  database. Approval requests are stored in the existing chat table.

## [2.34.0] - 2026-10-09

**In short:** Agents in everyday work. **Today starts with a briefing** (due, blocked, new since yesterday, lying
idle), every project has a **status report** to copy or share, a **Lying idle** view finds tasks nobody touched, the
time tracking points out **days without tracked time** and copies the **timesheet as text**, people **plan recurring
jobs for an agent** ("every Monday at 9: the week plan"), and agents can **read the text of a PDF attachment**.
Kalmido itself still calls no AI: it collects the data, the agent writes.

### Added
- **Morning briefing** (#264): Today starts with a compact briefing: due today, overdue, blocked (waiting on someone
  or an open dependency), new since yesterday (other people's comments, assignments, status and date changes on your
  tasks) and tasks lying idle. *Read* folds it to one line for the day on every device. Optional push with just the
  numbers at a time you choose (*Settings > Notifications > Morning briefing at*, off by default). Agents read it with
  `GET /api/v1/briefing?user_id=` / MCP `read_briefing`, only for people who may chat with them and only from lists
  shared with them.
- **Project status report** (#265): *Status report* on the project page: done, in progress, blocked, overdue, next
  dates, milestones and tracked hours for the last 7 / 14 / 30 days or any period, as plain text to copy or share. No
  comments, notes or names; hours only for people (and tokens with the `time` scope) who may see time tracking.
  `GET /api/v1/lists/{id}/status-report`, MCP `read_project_status`.
- **Tasks lying idle** (#266): a new view *Lying idle* lists open tasks without a change, comment or time entry for
  7 days (*Lying idle after* per list: 3 to 30 days or never) and tasks waiting on someone without a follow-up day.
  The list setting *Agent follows up* (off by default) sends the list's agent these tasks once a day (event
  `stale_tasks`); it asks about them or drafts a reminder in a comment and never contacts anyone outside.
  `GET /api/v1/stale`, MCP `list_stale_tasks`.
- **Time tracking helper** (#269): *Maybe forgotten* on the time page shows working days of the last two weeks with
  work on tasks but no tracked time (*Track time* opens an entry on that day); the timesheet has *Copy as text* (date,
  task, duration, note, totals, in your date format). `GET /api/v1/time/gaps`, MCP `get_time_gaps`.
- **Planned agent jobs** (#272): *Plans* on an agent's card: daily, on working days, weekly on chosen days or monthly,
  at a time in your time zone, optionally about a shared list; templates for the morning briefing, the weekly project
  status, idle tasks and time tracking; pause, run now, edit, delete. The agent receives `scheduled_job` once per due
  time (after an outage only one, marked late) and answers in your chat. People plan only for themselves with agents
  they may chat with (at most 20 per agent, at most daily); agents read their plans (`GET /api/v1/agent/schedules`,
  MCP `list_schedules`).
- **Read attachments as text** (#368): `GET /api/v1/attachments/{id}/text`, MCP `read_attachment`: the text layer of
  a PDF (read in a separate process with time, memory and page limits; a scanned PDF reports `no_text_layer`, no
  OCR), text files as text, images as images; only files the agent may see. *New project from a briefing* also loads
  a PDF (#260).

### Fixed
- The member notification template *Custom* had the German label of the date range ("Zeitraum") (#1089); members
  also see the owner's limit in the list settings.
- Agent chat header on narrow phones: the usage ring has a 44 px tap area, the permission badge shows a short label
  with the full text as its label (#1090).
- Android: the tab bar no longer covers the input while the chat search has the focus; swipe to reply works on the
  whole message row, not only on the bubble (#1091).

### Upgrade notes
- New table `agent_schedules`, new columns `lists.stale_days`, `lists.agent_followup`, `agents.stale_sent` and four
  indexes; 2.33.0 keeps running on the migrated database. PDF reading needs the new Python package `pypdf` (in the
  image); limits: `KALMIDO_PDF_MEM_MB`, `KALMIDO_PDF_PARALLEL`, `KALMIDO_PDF_TIMEOUT_S`.

## [2.33.0] - 2026-10-09

**In short:** Agents and notifications. **Reply to one message** (swipe it to the right on a phone, *Reply* on a
computer) in comments, team chat and the agent chat, with a quote that jumps to the original; **search in chats and
comments**; list and folder owners choose **how much the other people are notified** (new shares start with *Read
only*); a **ring shows an agent's plan usage** next to its name; a **repository connected to a folder** serves every
project list in it; *Administration > Server* shows **your IP as the server sees it**. Fixes for the iPhone: the
comment box no longer pushes the task header away, the *Done* bar of *Customize* stays reachable.

### Added
- **Replies to one message** (#1076): swipe a comment or a chat message to the right on a phone (not from the screen
  edge, which stays the system back gesture), or use *Reply* on hover and in the message menu on a computer. A bar
  above the input shows what you answer (× or Escape cancels); the answer carries a small quote that jumps to the
  original and highlights it, loading older messages when needed ("Message deleted" when it is gone). The author of the
  original gets "… replied to your message" like a mention. Agents receive the reference (`reply_to`, `reply` with a
  short quote) in comments, team messages and chat messages and reply the same way (REST, MCP `reply_to`, OpenAPI).
- **Search in chats and comments** (#1080): a magnifier in the header of a team chat or the agent chat searches that
  conversation (hits marked, arrows or Enter / Shift+Enter step through them); the command field and the search page
  add a *Messages* section with sender, chat, date and snippet, filter chips (comments, team chats, agent chats) and a
  sender filter. Case, accents and ä / ae spellings do not matter. `GET /api/v1/search?scope=messages`, MCP
  `search_messages`; only what you may see, agents only their shared lists and their own chats. A full-text index
  (SQLite FTS5) is built once at the first start and kept current.
- **Notification templates for shared lists and folders** (#927): in the share dialog the owner chooses how much the
  other people are notified at most: *Read only* (mentions, assignments, direct replies), *Collaborate* (+ comments
  on their tasks and due reminders), *Everything* or *Custom*, also per person. Members can be quieter, never louder,
  and see who limited a list. Only pushes are limited, the News list stays complete. New shares start with *Read only*
  (`KALMIDO_NOTIF_TEMPLATE`); lists and folders shared before keep *Everything* and their owners are asked once.
  Agents can read the setting (`GET /api/v1/lists/{id}/notify-template`), never change it.
- **Plan usage ring for agents** (#1045): agents report their plan usage (`PUT /api/v1/agent/quota` with windows or
  Claude Code's status line `rate_limits` as it is, an own limit and the time it was measured; MCP
  `report_plan_usage`). A ring next to the agent's name in the chat header fills with the main window: yellow from
  75 %, red from the agent's limit with "paused until …", grey when the report is older than 24 hours; hover or tap
  lists every window with its reset time. docs/AGENTS.md shows a status line script for Claude Code.
- **Repository on a folder** (#934): *Folder settings > Repository* connects one repository for every project list in
  the folder and its subfolders, also lists added later; `#id`, branch names and `fixes #id` work across all of them
  with one poll per repository. A list can switch it off or connect its own; only the folder's owner connects it, the
  token stays sealed.
- **Your IP** (#834): *Administration > Server* shows the client address as the server sees it, and Kalmido warns there
  and in its log when many accounts sign in from one private address (a reverse proxy in Docker that hides the client
  addresses; `KALMIDO_IP_WARN_ACCOUNTS`). docs/SELF-HOSTING.md explains `network_mode: host`, `"userland-proxy": false`
  and `KALMIDO_TRUSTED_PROXIES`.

### Fixed
- **iPhone: the comment box pushed the task header away** (#1087): focusing it moved the page by the keyboard height;
  the task panel now follows the visible area.
- **iPhone: *Done* out of reach in *Customize*** (#1086): the bar with *Done* sticks to the top of every Customize
  editor (Today, start page, projects, time tracking, agents).

### Upgrade notes
- Additive database changes only: columns `reply_to` (comments, team and agent chat messages), `agents.quota`,
  `lists.git_folder_off`; tables `list_notif`, `folder_notif`, `login_ips`, `git_folders`; the full-text index
  `msg_fts` with its triggers. 2.32.0 keeps running on a migrated database.
- Lists and folders that are already shared keep notifying everyone as before (*Everything*); their owners are asked
  once in the app. Set `KALMIDO_NOTIF_TEMPLATE=all` to start new shares with *Everything* as well.

## [2.32.0] - 2026-10-09

**In short:** Shorter ways, part 2 of the usability round, and a more talkative agent chat. **Views you arrange
yourself** (Today, Time tracking, the agents and projects overviews, the start page and the **project page** as blocks:
show, hide, reorder, half or full width, a different arrangement for the phone), **a long press selects** tasks on a
phone with a bar for *Move*, *Date*, *Complete* and *More*, **swipe through tasks** in the open task panel, a **share
dialog in folded parts**, **quick add with chips**, **settings on a phone without a second tab row**. Agents can show
their **steps while they work**, the chat header names the **model and permission mode that really run**, and
approvals use **thumbs up / down**. Fix: typing a comment no longer scrolls the task panel with every letter.

### Added
- **Arrange your views** (#1063): Today (*Customize Today…* in its "…" menu), Time tracking, the Agents overview, the
  projects overview and the start page share one builder: *Customize* shows every block with ↑ ↓ (Alt+arrow keys,
  dragging on a computer, each move announced), a switch to hide it and *Half* / *Full* width (two side by side on a
  computer). *Different on the phone* keeps a second arrangement for small screens, *Reset* returns to the default.
  Stored per person on the server (`view_today`, `view_time`, `view_agents`, `view_projects`, `dashboard`), the same on
  every device; agents cannot change arrangements. Time tracking remembers its period and the open entries.
- **Project page as blocks** (#983 #1061): the owner and list admins set the arrangement for everyone (*Customize* >
  *Standard for all*), each person may override it for themselves (*Only for me*, *Reset to the standard*); a small ×
  hides a block, *+ Block* brings it back. Images in project files and task attachments show as previews and open large.
  Empty blocks take one line (title, hint, button) instead of a whole card. `GET/PUT /api/lists/<id>/layout`.
- **Select by long press on a phone** (#1055): a long press on a task selects it; tapping more tasks adds them. A bar
  offers *Move* (choose a list), *Date* (today, tomorrow, next week, pick a date, none), *Complete* and *More* (*Edit* for
  several tasks, *More actions* for one, *Select all*, *Delete*). While selecting, every row has a grip to drag it at
  once; holding and dragging outside the selection works as before.
- **Swipe through tasks on a phone** (#1071): in the open task panel, swipe the properties left or right for the next or
  previous task of the view you came from (its sort and filter); "3 of 12" shows briefly, the ends spring back, typed
  text is saved first. The comments, fields with focus, selected text, sideways scrolling parts and the screen edges
  (system back) are left alone.
- **Agent steps** (#1081): an agent's short prose between its tool calls (`POST /api/v1/agent/progress` with
  `chat_user_id` or `job_id`, MCP `report_progress`) shows as up to three small grey lines under the typing dots, only
  for the person the agent works for; a tap hides them (*Show steps* brings them back). The switch *Always show steps*
  in the chat header keeps them above every answer. A job result gets a folded *History* grouped by the job's progress
  messages (300 lines, the whole history as a text file). Steps are stored with the answer or job and are never shown
  to other members, admins, other workspaces or agents; recognisable secrets are replaced by "[removed]" before they are
  stored, and agents are told to send prose only, never tool output. Rate limit 60 per minute and agent.
- **Model and permission mode as they run** (#1079): `PUT /api/v1/agent/status` takes `model`, `permission_mode` and
  `host_permission_mode`; the chat header shows "Host default (Auto)" and the running model ("Opus 5.5"), and both
  values when the chosen model or mode differs from what runs ("set: sonnet · running: Opus 5.5").
- **Drop files on a list** (#362): files dragged from the desktop onto an open list or a list in the sidebar become one
  new task each, named after the file, with the file attached (one undo step); dropping on a task, the task panel,
  comments and project files works as before.
- **Suggest icons for new lists** (#1077): a personal switch in Settings > Appearance (on by default, all devices).
- **Logo variants** (#1070): `static/logo-white.svg` (white mark for dark backgrounds) and `static/icon-light.svg`
  (white tile); the favicon follows the browser's light or dark mode. The violet sun stays in every variant; the app
  icons are unchanged.

### Changed
- **Share dialog in parts** (#1058): *People* stays open; groups, agents, the public link and the owner fold, with a
  short state in their line (agent "listens in", link on / off / expired). The agent switches explain themselves
  behind the (i), and *What the roles may do* is a plain fold-out line.
- **Quick add** (#1059): the same placeholder on every device; the syntax help became chips that insert the shortcut
  at the cursor (the keyboard stays open), also in the desktop dock and *Note to inbox*; on a phone *File* and
  *Details* are labelled buttons in their own row.
- **Settings on a phone** (#1060): inside an area the second row of area tabs is gone, the back arrow leads to the list
  of areas and the header names the area; sub-tabs keep their width and scroll sideways; the agent card labels *Send
  test* and *Edit*.
- **Agent chat** (#1062): "working" is stated once, in the header (below the messages only the typing dots); the
  reaction smiley under an agent's message appears on hover, focus or a long press.
- **Calmer fonts and header** (#1062): no monospace outside code and numbers (daily review, task panel footer, quick
  add help); with the task panel open on a computer the view tabs stay in the header as icons, *Share* moves into "…".
- **Approvals with thumbs** (#1082): permission questions, job approvals, merge / integrate / deploy approvals and
  task approvals use 👍 / 👎 with their text (the emoji is hidden from screen readers); the reaction button stays an
  icon.
- **Agent rules** (#1078): the rules template (`mcp/CLAUDE.template.md`) and docs/AGENT-SETUP.md add: read the whole
  task with all comments before answering a task event, answer task events only on the task, hand anything a person
  must apply themselves to them as a high-priority task with a checklist, report model and mode, steps only as prose.

### Fixed
- **Typing a comment scrolled the task panel** (#1074): on Android (Chrome) every letter in the comment box moved the
  panel down by about 50 px; the panel's bottom scroll padding is dropped while the docked comment box has the focus,
  and the growing box keeps the panel's position.

### Upgrade notes
- Additive database changes only: table `agent_steps`, table `list_layouts`, columns `agents.host_info`,
  `agent_chat.job_id` and `lists.page_layout`, new user settings. 2.31.2 keeps running on a migrated database.

## [2.31.2] - 2026-10-09

### Fixed
- **Done circle on a phone** (#1051): 2.31.1 had narrowed its touch area below 44 px; it is 44 px wide again and grows
  to the left instead of over the ticket number, and a subtask arrow next to it stays tappable.
- **Tests**: the check of the folded daily review no longer depends on the time of day.

## [2.31.1] - 2026-10-08

### Fixed
- **Task rows on a phone** (#1051): a tap on the ticket number in the meta line ticked the task off on real phones (the
  done circle's touch area reached over the number); the area now ends before the number and the title, and the number
  opens the task as intended.
- **Today on a phone** (#1052): with the largest font size the overdue actions under the Overdue heading ran past the
  screen edge; they now wrap.
- **"To the comments"** (#1054): the jump no longer hides the comments heading under the panel's header.

## [2.31.0] - 2026-10-08

**In short:** Phone everyday, part 1 of a usability round. **Task rows line up** on a phone (the ticket number moved into
the meta line, no dead zone next to the circle), **Today is calmer** (the daily review folds to one line once read,
the overdue actions sit in the Overdue heading, the agent band only shows when an agent needs you), the **list head is
one slim line**, the **task panel on a phone drops its tabs** and on a desktop shows the **comments in their own
resizable area**, **menus come in groups** with the dangerous entries last, the **Search tab opens the search** at once,
a **column title sorts** the list, and a **dot on your picture** shows your connection. Fixes: file names next to the
"Created by agent" label, Markdown tables on narrow screens, the agent sub-tabs on a phone.

### Added
- **Comments in their own area on a desktop** (#344): the task panel shows the properties above and the comments (with
  the history and its switch) below; drag the line between them or use the arrow keys (Home / End for the limits),
  fold the area with a double-click, Enter or the arrow in its head. Position and fold are saved per user
  (`detail_split` 20-85, `detail_cm_fold`) and apply on every desktop; without comments the area says so. Phones,
  foldables and touch tablets keep comments at the end of the panel.
- **Sort by a column title** (#354): in lists with their own columns (*Shown fields…*) a click on a column title sorts
  by it, a second click reverses, a third returns to the sort from before; arrow and `aria-sort` on the title, Enter /
  Space work, right-click offers both directions, *Hide column* and *Shown fields…*. Saved like the sort menu (list
  owners and admins for everyone, with a one-time note; members on their device). New `sort_mode` values `date_desc`,
  `prio_asc`, `col:who|tags|time|progress|deps[_desc]`, `cf:<id>_desc`.
- **Connection dot on your picture** (#378): green online, grey offline (the tooltip counts the waiting changes),
  yellow while syncing; the state is also given as text, and the account menu starts with it ("Online · All saved",
  or "Offline · 3 changes waiting" with *Try again*). The offline chip in the header stays.

### Changed
- **Task rows on a phone** (#1051): the ticket number moved from its own column into the meta line under the title, so
  titles with and without numbers line up; a tap on the number or a gap in the row opens the task. The pin shows only
  on pinned tasks (on a desktop also on hover, where one click pins). Today no longer repeats a "Today" chip on every
  task, only its time.
- **Today** (#1052): the daily review folds to one line ("1 done · 7 open", *Plan tomorrow*) after the first look of the
  day and unfolds with its arrow (remembered for the day); its numbers use the normal font. *All to today* and
  *Another day…* moved into the Overdue heading. The agent band on Today appears only when an agent needs you (a
  question, an approval, an error or a limit), not for "offline".
- **List head** (#1053): progress, overdue and the next due date share one slim line; *Set status* moved into the list's
  "…" menu and the project page (a set status still shows); the view switch on a phone is lower (36 px).
- **Task panel on a phone** (#1054): the "Details | Comments" tabs are gone, a small "To the comments" link with the
  count jumps down; comment order and history moved into a "…" menu in the comment head; the assignee is chosen in one
  place (the chip under the title: people, agents, groups, *Take over*); the "Created by" footer uses the normal font.
- **Menus in groups** (#1056): the list menu, the task menu, the swipe menu and *More* show small group headings, with
  archive and delete last and set apart; rarely used list options (notifications, progress, agent access, tasks from
  notes) moved into *More list options…* (a second level with *Back*, → and ← on the keyboard); in the task panel the
  menu no longer repeats date and priority.
- **One search on a phone** (#1057): the *Search* tab opens the search with the keyboard; while that tab is pinned, the
  header magnifier and the drawer's search field are gone (nothing behind the open drawer is tappable), and the *Lists*
  tab opens the drawer at the lists.

### Fixed
- **File tiles** (#1050): the name gets its own line, so size and the "Created by agent" label no longer squeeze it to
  two letters.
- **Markdown tables** (#1048): in the file viewer, descriptions, comments and the chat, short cells stay on one line,
  words never break letter by letter, and wide tables scroll sideways in their frame.
- **Settings > Agents on a phone** (#1046): the sub-tabs keep their width and scroll sideways instead of overlapping.

## [2.30.0] - 2026-10-08

**In short:** Clear boundaries, calmer agents. **Calendars and address books belong to a workspace** like lists, and a
**nightly boundary check** counts anything that crosses one; a new guard test fails for every route that is neither in
the cross-tenant matrix nor listed with a reason (#1036). An agent **never bridges lists with different people** unasked,
agents and tokens can be **limited to chosen lists**, and every list shows its **agent access log**; *Settings > Agents >
Use safely* has ten rules (#919, #920). In the agent chat, **permission questions get Allow / Deny buttons**, answer
buttons of older messages **expire**, and "working" shows only where the agent really writes (#1041, #1037, #1039).
Agents **listen in by project type**: in software lists without an @mention, elsewhere only when addressed; tidy-up is a
separate switch (#1034). **Markdown, text and code files open in a viewer**, and agents can write text files onto tasks
(#1035, #380). Plus phone fixes from the device test and many additions to the self-hosting and agent docs (#933).

### Added
- **Workspaces for calendars and address books** (#1036): `ev_cals.org_id` / `books.org_id` (NULL = private) with the
  rules of lists -- an organisation's calendar or address book only for its members and agents, a private one never for
  an organisation's agent, a share only with people you may see (B2). *New calendar…* / *New address book…* ask for the
  workspace, *Workspace…* in their menu moves one (owner only, `409` while a member does not fit), web + API v1
  (`org_id` on create / PATCH) + MCP. The sidebar switch filters events, calendars, contacts and address books. Leaving
  or deleting an organisation takes its calendars and address books along like its lists. One-time migration on start:
  into the owner's organisation unless named like a private one, mirrored from an outside account, or a member does not
  fit (then private; no share is removed).
- **Nightly boundary check** (#1036): once a day (`KALMIDO_TENANT_CHECK_HOUR`, default 3) the watchdog counts memberships
  across the workspace boundary (list members and groups, owners, calendar and address book members, agents); an admin
  alert (ids and counts only) when the result changes, `boundary` in `GET /api/admin/orgs` and a line under
  *Administration > Organisations*.
- **Guards for the boundary** (#1036): `tests/tenant_coverage_test.py` fails for any route of the web app, CalDAV /
  CardDAV or `/api/v1` that is neither covered by the cross-tenant matrix nor listed with the reason the boundary does
  not apply; `tools/check_layout.py` requires `org_id` or `list_id` (or a stated reason) on every table that refers to a
  person. New matrix suite for calendars, events, address books, contacts, groups, templates, DAV, feeds, webhooks,
  export, attachments, chat files, forms, statistics.
- **Agent bridges** (#919): sharing a list with an agent (or adding a person to a list with an agent) that would connect
  two lists with different people (neither the same nor nested) is refused with `409 agent_bridge` and the conflicting
  lists; *Connect anyway* (`bridge_ok: true`, only for someone who manages all lists involved or the owner of the
  personal agent) records it. Automatic ways (share all, new lists automatically, shared folders, folder settings,
  proposals, group sync, sharing by e-mail address) skip such lists without a word; existing bridges stay and are flagged
  (`GET /api/agents/<id>/bridges`). `PUT /api/v1/lists/{id}/members/{user_id}` takes `bridge_ok` for people's tokens.
- **Approval for moves into a wider circle** (#919): an agent moving a task into a list whose people are not a subset of
  the source list's waits for a person (`202`, PATCH `list_id`, `/move`, batch).
- **Only these lists** (#919): agents and API tokens can be limited to chosen lists (`list_ids`; token dialog, agent
  dialog, `PATCH /api/admin/agents/{id}`, `/api/my/agents/{id}`, `/api/me/tokens`); other lists answer 404 and send no
  events, News only from those lists, and the full export is refused. Widening the limit so that it would switch on an
  unapproved bridge asks first. `GET /api/v1/me` shows `token.list_ids`.
- **Agent access log** (#919): *Agent access* in a list's menu shows per agent how often it read or changed the list per
  day, last 30 days, for every member (`GET /api/lists/<id>/agent-access`).
- **Use agents safely** (#920): *Settings > Agents > Use safely* (ten rules + a part for admins), a short step in every
  setup guide, a hint before the first share with an agent.
- **Allow / Deny** (#1041): a permission question in the agent chat (`permission: true`, optional `expires_in`; buttons
  with the ids `allow` / `deny` count as one) shows two buttons, then *Allowed 14:47* / *Denied 14:47* or *Not answered,
  denied* after the time limit. A button sends `chat_choice` (`permission`, `approval`, `via`) and the familiar
  `reaction` event; 👍 / 👎 still answer an open question (a `reaction` on a closed one carries `approval: null` and
  `stale: true`).
- **Withdraw answer buttons** (#1037): `POST /api/v1/agent/chats/{uid}/messages/{mid}/withdraw` (optional `outcome`),
  MCP `withdraw_chat_choices`.
- **Agent listens in** (#1034): a switch per list and per folder (`agent_listen`); default on in *Software / AI
  development* lists, off elsewhere. `listen_default` in state and v1, `project_type` and `listen_agent_ids` in every
  task event.
- **File viewer** (#1035): Markdown files attached to tasks, comments or chat messages open formatted (switch to the
  source), text and code files as highlighted source, with *Copy* and *Download*; full screen on phones, dark mode,
  nothing in a file is ever run (files above 1 MB download). Markdown now also renders tables, quotes, rules and
  headings down to level 6.
- **Text files from agents** (#380): `POST /api/v1/tasks/{id}/attachments/text` (`name`, `content`, max 1 MB, scope
  `attachments:write`), MCP `create_text_file`; the same name creates a new version next to the old one
  (`report (v2).md`). Files an agent stores never keep an executable ending (`deploy.sh` becomes `deploy.sh.txt`, also
  for uploads to tasks, comments, chats and projects) and show *Created by agent*.
- **Docs** (#933): new [docs/SELF-HOSTING.md](docs/SELF-HOSTING.md) (proxy, VPN-only, PWA and push, backups and
  encryption, server hardening, mail, moving, production updates); AGENT-SECURITY.md: server-enforced boundaries, *Use
  agents safely*, egress and redaction steps, new test cases; AGENT-SETUP.md: several specialist agents under one
  Kalmido agent; API.md: bulk changes with pause and `Retry-After`, closing tasks from git, lists, people and agents;
  many new rules in the CLAUDE.md template (binding decisions, privacy, coding agents, jobs, usage limit, denied
  permissions, one suggestion per answer, status only with the task you write in).

### Changed
- **Answer buttons expire** (#1037): only the newest message keeps open buttons; a newer message (from the agent or the
  person) hides older open ones, pressed ones stay as *Answered*; a click on an expired button gets `409` "This
  suggestion is no longer current". Permission questions do not expire by newer messages.
- **"Working" only where the agent writes** (#1039): a status without `task_id` shows only under the last chat message
  and in the header chip, never in tasks; with `task_id` only in that task; the status text never appears in a task.
- **`task_added` / `tasks_added` only for listening agents** (#1034), for created and moved-in tasks; tidy-up no longer
  makes an agent listen and now also covers tasks moved into the list (at most five per bulk). Existing lists keep who
  listened before (one-time migration).
- The "👍 = approval" hint under chat questions is gone (#1041, #1044).
- Groups are only shown to people who may see one of their members across organisations (B1, #1036); a form of an
  organisation's list is only for that organisation's members; people newly invited to an existing event must be
  visible; folder sharing no longer brings someone else's personal agent into a member's list.
- **Sharing with agents may ask first** (#919): scripts that add a person or an agent to a list with
  `PUT /api/lists/<id>/members` now get `409 agent_bridge` when that would connect lists with different people (repeat
  with `bridge_ok: true`); only someone who manages all lists involved, or the owner of a personal agent, may confirm (a
  list admin who is neither gets `403`). Folder sharing and *share all* leave such lists out. Existing bridges stay.
- The test suites run as 8 parallel shards.

### Fixed
- Phones: after a dialog opened from the sidebar drawer (*Folder settings…*, *People and roles…*, *Edit list…*) the
  drawer is dimmed again and a tap next to it closes only the drawer instead of opening the task behind it (#1043).
- Share folder on phones: names and *new lists too* wrap instead of being cut, people who already have the folder are no
  longer offered again (#1044).
- The agent chat keeps its side margin when the iOS keyboard opens; one-time hints no longer have stretched line
  spacing (#1044).
- The copy button of code blocks sits in its own column with a subtle background and never covers the code (#1042).
- The quick-add sheet no longer shows the paper-clip / square explanation under the field (#1033).
- In the workspaces mode instance admins see a profile photo only where everyone would (#1036).

## [2.29.0] - 2026-10-08

**In short:** Folders like lists, calm agents. A folder now carries **settings for every list in it** -- workspace,
agent, *Members may use it*, tidy-up -- for the lists already there and the ones added later; a list changed on its own
keeps its value until *Back to the folder* (#1030, #929). **Sharing a folder works like sharing a list**: every role
(admin too), a changed role reaches the lists, removing can take the person out of them, and a list someone adds to a
folder shared with them is shared with the folder's owner and people at once (#929). On the desktop the **agent chat
opens as a pop-up window** from anywhere (round button bottom right, key `A`, command bar), stays open across views,
can be moved, folded and docked (#363). An agent's **permission mode** (*Auto* / *Ask first*) shows in its chat header
and can be switched there (#1029). Agents get **no backlog flood** any more: a new poller starts from now, old events
come as one summary, bulk changes as one event (#1031). Kalmido is **not indexed by search engines** unless you allow it
(#1026). Settings > Agents has **one clear "Set up"** (for me / for the team) and a separate *Administration* (#1024).

### Added
- **Folder settings** (#1030, #929): *Folder settings…* in a folder's menu sets defaults for every list in the folder and
  its subfolders (a subfolder can override its top folder): the workspace, the agent (or *No agent*), *Members may use
  the agent*, *Agents may address each other* and *Tidy up*. Saving asks whether the existing lists follow or only new
  ones, and first names the lists that cannot follow (a person or agent outside the workspace, a Home & life list that
  stays private) or that were changed on their own; *Also the lists changed on their own* overrides those. A new list
  in the folder and a list moved or dragged into it take the settings. The list dialog says what comes from the folder;
  a list changed on its own (workspace, agent, tidy-up, agent access) is marked and offers **Back to the folder**.
  API: `GET / PUT /api/folders/props` (`props`, `apply: all | new`, `force`, `dry_run`), `POST /api/lists/{id}/folder-reset`,
  the state's `folder_props`; lists carry `folder_own`.
- **Folder sharing like list sharing** (#929): every role when sharing a folder (admin, member, participant, viewer), a
  role switch per person that reaches the folder's lists (`updated` in the answer), and removing a person asks: *Also
  remove from the lists in the folder* (`DELETE /api/folders/people {remove: true}`) or *Only stop sharing new lists*. A
  list someone creates in a folder shared with them stays theirs and is shared with the folder's owner (list admin) and
  its other people (their folder roles); the new-list dialog says so and offers *Create it without a folder instead*
  (state: `folders_shared_in`). Dragging a list into a shared folder in the sidebar now shares it too (before only the
  list dialog did).
- **Agent chat as a pop-up window** (#363, desktop): a round button with the agent's picture bottom right (the agent you
  chatted with last, its unread count), the key `A` and *Chat with … as a window* in the command bar. The window floats
  over the page without taking room, stays open while you switch lists and views, moves by its header (remembered per
  device), folds to the header and docks as the side panel (and back; remembered).
- **Permission mode of an agent** (#1029): runtime setting `permission_mode` (`ask` = every action outside the allow list
  asks the person in the chat, `auto` = the host's safety check decides, empty = the host's default), a badge *Auto* /
  *Ask first* in the chat header; the owner of a personal agent and an admin for a team agent switch it there
  (`PUT /api/agents/{id}/permission-mode`) or in the runtime section; `PATCH /api/my/agents/{id}` takes `runtime`.
  `GET /api/v1/agent` returns it, `runtime_changed` tells the agent.
- **No backlog flood for agents** (#1031): `GET /api/v1/agent/events?since=latest` (also in the MCP tools) starts from now;
  events older than `KALMIDO_AGENT_EVENTS_STALE_H` (default 48 h) come as one event `missed` `{count, events, from, to}`;
  more than five tasks added to one list by one person within a minute come as one event `tasks_added` `{list, task_ids,
  count, how}`; tasks created in bulk through the API get no `tidy` event each. docs/AGENTS.md explains how services should bundle events.
- **Not indexed by search engines** (#1026): `X-Robots-Tag: noindex, nofollow` on every answer and `/robots.txt` with
  `Disallow: /` (it redirected to the sign-in page before); `KALMIDO_SEARCH_INDEX=1` allows indexing the sign-in page,
  public list links, forms, feeds and the API stay noindex.

### Changed
- **Settings > Agents** (#1024): one *Set up* that first asks **For me** or **For the team** (one sentence each, then the
  guide for your system and your personal agents); the server-wide switches (*Personal agents for everyone*, the
  permission limit) moved to a new sub-tab *Administration* (admins). Every agent card says **Personal** (whose) or
  **Team**; *Setup guide* is now *How to set one up*.
- **Settings > Agents > Lists** (#345): lists of others shared with you show up too, read-only with their owner and agent
  (only the owner and list admins change them).

### Fixed
- **Code blocks in chat bubbles** (#1028): a long command wraps inside the bubble instead of scrolling sideways, so no
  scrollbar sits over the line under it (Mac with "always show scrollbars").
- **Empty "Assigned" cell** (#1002): in a list with an assignee column the empty cell is always there (faint) and
  clickable, also where the browser reports no hover (some desktop web apps, touch laptops); it was hidden there.
- Checked again with real clicks in Firefox: the sidebar grip under a right-click menu (#976), "+" in the reactions opens
  the emoji field on top, also over the chat window (#963); typing in the quick add / comments keeps the page still
  (#958, regression test from 2.27).

## [2.28.0] - 2026-10-08

**In short:** Work and private apart, messages. Every list and agent belongs to a **workspace** -- your private space or
one of your organisations; a switch in the sidebar shows one at a time, and the server keeps an organisation's lists and
agents inside it (#935). A new server mode `workspaces` runs several organisations on one shared server, each with its
own admins. **Personal agents are invisible to admins** (#965); *Add agent* asks team or personal (#970); *Users* shows
people only, agents are grouped under *Agents* (#1011); a **robot badge** marks agents wherever people appear (#985).
News split into **For you** (what people send you) and **Activity**; the bell counts only *For you* (#987). Agents can
ask with **answer buttons** in the chat (#1005).

### Added
- **Workspaces** (#935): every list has one (`org_id`, `null` = private); an organisation's list is shared only with the
  organisation's members (a person who is not a member is refused with a clear message; a share by e-mail address into
  it does nothing and reveals nothing), its groups must consist of members, its ownership stays inside. Agents work in
  one workspace (`agents.org_id`) and join only its lists; "Used for" (family / household) and Home & life lists are
  private only, the inbox always is. The owner changes a list's workspace in the list dialog (refused while people or
  agents in it do not fit). The sidebar's switch *Private | <organisation> | All* (setting `workspace`, followed on every
  device) shows the lists, tasks, News, agents and team chats of one workspace; a chip in the header says which. A new
  list starts in the shown workspace (or in the one of its folder's lists). *Settings > Account > Workspaces* lists your
  organisations and their members.
- **Server mode `workspaces`** (`KALMIDO_INSTANCE_MODE=workspaces`): several organisations as workspaces on one shared
  server. People see the members of their organisations and the people they are connected with -- nobody else, instance
  admins included (*Users* shows only them and how many others there are). The instance admin creates organisations
  (`POST /api/admin/orgs`, with a first admin) and deletes empty ones; **organisation admins** (`org_members.role`)
  manage their members (add by e-mail address, roles, removal), name and e-mail domains (`/api/orgs/...`), also without
  being server admins. Registrations join by e-mail domain. The login page names no organisation.
- **Leaving an organisation**: the person's lists of that workspace go to an organisation admin (the one who removes
  them, or the next admin), the person leaves every list of the organisation; private lists go with the person. When the
  only admin leaves, the operator (an instance admin) takes the organisation over and is told (News).
- **Migration**: on the update every list of a server with an organisation stays in the organisation (a server from before
  = one company), except family / household lists, Home & life lists, lists in a top folder named like *Private* /
  *Family* / *Home* (several languages) and every inbox: those are private. Team agents work in the organisation, a
  personal agent in the workspace most of its lists are in. An agent that already sits in a list of another workspace is
  kept and pointed out (list dialog, share dialog, *Settings > Account > Workspaces*); the owner decides.
- **Answer buttons in the chat** (#1005): `POST /api/v1/agent/chats/{user_id}` (and MCP `send_chat`) take `choices`
  `[{id, label, style?: primary | danger}]` (at most 8) and `multi`; the buttons show under the message, a tap answers
  (several with `multi`, then *Send*), the choice is shown and the buttons lock. The person's answer comes as the event
  `chat_choice` (`message_id`, `choice_ids`, `labels`, `user`) and in `GET /agent/chats` as `choice`;
  `POST /api/agents/{id}/chat/{mid}/choice {choice_ids}` (web and `/api/v1`, a person's own token). Only the chat's
  person answers, once; agents never. For permission requests: the command in a code block, buttons *Allow* / *Deny*.
- **"Belongs to"** on an agent (#965 / #970): admins create a **personal agent for a person** (`owner_id` on
  `POST /api/admin/agents`) or turn a team agent into one (`PATCH ... {owner_id}`); *Add agent…* asks *Team agent* or
  *Personal agent* and explains both. An agent's workspace (`org_id`) is set there too (personal agents: by their owner).
- **Robot badge** (#985): a small robot on an agent's picture wherever people appear (members, share dialog, News,
  comments, chat), with a tooltip and a text for screen readers.
- **News "For you" / "Activity"** (#987): items carry `to_me` (an @mention, assignment, reply to your comment or
  approval decision **by a person**; everything agents do and every plain change is activity); `unread_me` in
  `/api/news` and the state. The News view has the tabs *For you | Activity | All*, the bell's dropdown shows *For you*
  first, the bell counts only *For you* plus unread direct messages (`team.dm_unread`), the start page shows a banner
  *N messages for you* while something is unread.

- **Display name first** (#926): the user and agent dialogs ask for the display name first (it may be anything) and show
  the username below it with what it is for (the login, @mentions); the username is suggested from the display name
  ("Team Dev AI" becomes "team-dev-ai") until typed by hand, and a wrong one gets an error that names the
  suggestion. Renaming an agent says that @mentions use the new name.

### Changed
- **Admins reach agents like everyone** (#965): an instance admin sees and uses an agent (chat, @, assigning, sharing,
  `GET /api/agents`, jobs) only through lists it is in -- as the owner / a list admin, or where *Members may see and use
  the agent* is on. Every agent is still listed in the administration; somebody else's **personal agent** comes there as
  name + owner + kill switch only (`restricted`), every other change answers 403.
- **Settings > Users shows people only** (#1011); one row says how many agents there are and leads to *Agents*, where
  the agents are grouped: team agents, my personal agents, personal agents of others.
- **Pushes for what agents do are off by default** (#987): an agent's comments, completions, new tasks and status
  changes push only with the new setting *Pushes for what agents do* (`agent_push`); an agent's @mention of you and its
  approval requests push as before.
- Organisation News: being added to / removed from an organisation is a News item.

### Fixed
- **Width grips over menus** (#976, hardened): the 2.27 rule relied on `:has()`, which browsers from before 2023 ignore.
  The code now also marks the page while a menu, popover or dialog is open (`body.pop-open` / `body.modal-open`), so the
  grips step aside in every browser; a right-click on a list or folder in the sidebar opens its menu (mouse).

## [2.27.0] - 2026-10-08

**In short:** Bugs & polish. A window that still runs old code after an update now says so and reloads (#968);
shared folders and lists look the same for everyone (#988); automatic tidy-up waits until nobody types (#999); new
projects start without sections unless you ask for them (#972); comments are back at the bottom of a task (#957);
plus 20 smaller fixes and changes.

### Fixed
- **Old code after an update** (#968): a window (or installed app) that stayed open across an update kept running the
  code it had loaded, while Help showed the server's new version. The page now names the version of its code, and when
  the server runs another version a bar says **"New version available – Reload"**. With nothing typed, no draft and no
  change waiting it reloads by itself once. Settings > Help shows the version of the app in the window next to the
  server's.
- **Typing moved the list behind** (#958, again after #669): on phones every key could fire a viewport event that
  scrolled the list or the task panel behind the quick add sheet or the comment box. While a field has the focus on a
  touch screen the page is left alone; a field is only scrolled into view when it really is under the keyboard, once per
  focus, never for the boxes that sit above the keyboard anyway.
- **Hidden rows that stayed visible** (#966): the `hidden` attribute now always hides, so "Used for" is gone from
  project dialogs and the chat's width grip no longer stays behind at the task panel's edge (#978).
- **Family fields in work lists** (#975): "Who comes along", "Take turns" and the stars only show in family and
  household lists, never in projects (a task that already uses them keeps showing them).
- **Menus under the width grips and the agent chat** (#976, #963): menus and popovers are above the grips, the chat
  panel and a pinned composer; while a menu or dialog is open the grips step aside. The emoji picker of "+" in the agent
  chat panel opened behind the panel and seemed to do nothing.
- **Order in shared folders** (#988): a list in its owner's folder sits for every member in the owner's folder and
  place; the owner's folders keep their order among each other in every member's sidebar (members' own folders stay
  where they are). Existing arrangements are aligned once on the update. Only the owner moves those lists.
- **The sort of a shared list** (#988): set by the owner or a list admin for everyone (`sort_mode`); a member may look
  at it sorted otherwise on one device and the list says so, with "Back to the shared sort".
- **Automatic tidy-up over your typing** (#999): the tidy event for a new task waits until it was left alone for two
  minutes (`KALMIDO_TIDY_QUIET_S`) and nobody edits it (the task panel tells the server while a field has the focus).
  An agent's tidy is refused (409) while a person edits the task, after people changed it since the event, or when its
  `base_updated_at` is old. The original text always stays.
- **Empty list without "+ Section"** (#990): also in an empty list, and "Add section…" in the list's menu.
- **A list to the very end of a folder** (#991): dropping on the lower half of a list puts it after that list;
  "Move to the top / bottom" in the list's menu in the sidebar and in the sort mode.
- **Agent status** (#1007): the agent band of a list and the header asked for the agents' status only when data
  changed and showed "not connected" while the chat said "ready"; the status is now fetched again once it is older than
  a minute.
- **The assignee cell** (#1002) of lists with their own columns is always visible (faint) so it reads as clickable.
- **Column widths** (#1006): a visible line between the column titles shows where to drag, with a tooltip.

### Changed
- **New projects without sections** (#972): a project of a built-in type starts without the type's sections; the box
  "With the standard sections" (off by default) names them. API: `sections: true` with `ptype` / `project_type`.
- **List type at the top** (#977): "Type: Simple list | Project" replaces the "Project features" checkbox in the list
  dialogs; the project fields show right below it.
- **Comments at the bottom again** (#957): below the folded "More details", whose summary line tells what it holds
  (tags, link, fields, documents).
- **"Agent: <name>…"** (#974) in a list's menus and the command palette opens the share dialog at its agent.
- **Settings > Agents > Lists** (#964): grouped by folder (each group folds), a filter (with / without an agent, by
  agent) and one agent for all lists of a folder at once (one undo). With one agent per list "Agent reads every
  comment" is a switch and "Tidy up by" is gone.
- **List tags in lists that are not shared** (#967), with the hint that everyone sees them once the list is shared.
- **"Views" above the lists** by default again (#984); an own arrangement of the sidebar stays.
- **Team chat** (#986): only conversations with messages, newest first; "New message" also starts the chat of a shared
  list nobody wrote in yet.
- **The Agents tab without an agent** (#955) explains why and offers to connect your own.
- **"My tasks"** (#1001) instead of "Assigned to me"; what lands in your own inbox (mail, the share sheet, the drop
  inbox) and what you create in "My tasks" is assigned to you.
- **Longer descriptions** before "Show more" (#994): about nine lines, only the last one fades.

## [2.26.1] - 2026-10-07

**In short:** The iPhone keyboard no longer covers the quick add sheet (#952), Back on tablets closes only the open
task (#953), plus a sort by creator, a "Created by" line in the task panel and smaller layout fixes.

### Fixed
- **iPhone keyboard over the quick add sheet** (#952): iOS reports the keyboard with a single visual viewport resize
  while the page is still scrolled up, then scrolls back without another event, so the sheet was placed for the wrong
  scroll position and sat under the keyboard. The keyboard position is now measured again on every page scroll and
  shortly after a resize. The + button also focuses the field within the same tap, so the keyboard opens at once and
  the sheet sits right above it.
- **Back on tablets and the unfolded Fold** (#953): with a task open, Back (the Android key or gesture) closes only the
  task and keeps the view and the sidebar; the next Back goes to the previous view. Closing the task with its own
  button removes that step again. Upright, where the sidebar is a drawer, Back to a view that was left from the open
  drawer shows the drawer open again, and it stays open.
- No contact autofill offer from iOS on the quick add sheet, the comment box and the team chat input.
- At 1280 px with a wide sidebar and the task panel open, the title is shortened further before the view switch moves
  into "…".
- Settings tabs on phones: "More ›" sits on a solid background and no longer overlaps a tab.
- Long list names in the agents' list table wrap to two lines instead of being cut (full name as a tooltip).

### Changed
- **Sort by "Creator"**: by the creator's display name, then the manual order. It only changes what you see; the
  manual order is kept, and dragging behaves as with the other non-manual sorts.
- The task panel shows a fixed line "Created by <name> on <date>" at the bottom (agents by their name; without a known
  creator the date only; completed tasks add the completion date).
- Settings > Agents on phones and touch screens: the two stop buttons carry labels, "Pause with a reason" (hourglass)
  and "Emergency stop" (stop icon: token and webhook stop at once).
- A hidden, read-only viewport diagnostics box for keyboard problems on phones: open it with `#vvdebug` in the address
  or five taps on the version number (Settings > Help). It shows only screen and keyboard measurements.

## [2.26.0] - 2026-10-06

**In short:** Agents in a team, safely (#928 #949) and easier handling (#932 #936 #937). The owner of a list decides who
may address its agent, agents no longer instruct each other, and a list holds one agent; coding agents ask for approval
to integrate and to deploy without a pull request, pause with a reason and propose changes to other topics. Several
tasks are edited at once in the task panel, the sidebar can be dragged wider, and the iOS keyboard no longer covers
the input fields.

### Added
- **Edit several tasks at once** (#936): Shift-click selects a range, Ctrl/Cmd-click adds or removes single tasks. From
  two selected tasks the task panel shows "N tasks" with the fields they share (date, deadline, priority, assignee,
  list, section, milestone, repeat, reminder, waiting on, pinned, custom fields, tags): equal values as usual, different
  ones grey as *Mixed*; a change applies to all at once, the field is marked as changed, one undo step takes it back.
  Tags are added or removed (a tag only some have is half filled); dates move by −1 day / +1 day / +1 week, each task
  from its own date. Below, the selected titles (open one alone, take one out). Fields you may not change for some of
  the tasks are locked with a hint. On phones *Edit* opens the panel as a sheet.
- **Resizable sidebar** (#932): drag its right edge (or use the arrow keys on the grip, double-click = default width),
  stored per device like the task panel and the chat. Phones and the collapsed sidebar are unchanged.
- **Who may address a list's agent** (#928): per list, the owner (or a list admin) switches on *Members may see and use
  the agent*. Off (the default, also for existing lists): only the owner, list admins and instance admins can chat with
  the list's agent, @mention it, assign it tasks, ask it for proposals or nudge it there; mentions and comments of other
  members send it no event, assigning it is refused. Members still see what the agent does. The chat and the
  @mention / assignee pickers offer an agent only where it is open to you. API: `agent_members` on lists.
- **Agents do not instruct each other** (#928): an agent's mention, comment or assignment reaches another agent only in
  lists with *Agents may address each other* on (default off). Every agent event and webhook names `actor.kind`
  (`person` / `agent`). The behaviour rules template: instructions only from people, only the account id counts.
- **One agent per list**: a list holds at most one agent. Sharing a second agent is refused with a clear message on every
  path (sharing, folder shares, *Share all*, proposals); folder shares skip such lists and name them. The Share dialog and
  *Settings > Agents > Lists* show one select *Agent: No agent / …*; switching swaps the agent in one step with Undo
  (`PUT /api/lists/{id}/agent`).
- **Approval without a pull request** (#949): an agent asks *Ready to integrate* (branch → target, with its evidence:
  build, start, logs, tests) and *Ready to deploy* (approved integrations + a checklist of the list's open tasks tagged
  `deploy`; 👍 does not approve while it is open, *Approve anyway* does and records what was skipped). Only approvers
  decide; the agent gets the decision as a reaction event with `data.gate`. MCP: `request_integration_approval`,
  `request_deploy_approval`.
- **Pause with a reason** (#949): an agent (status `paused` with a text), its owner or an admin (hourglass in *Settings >
  Agents*) pauses it without the kill switch; people see the reason in the chip, the chat ("does not answer right now:
  …") and the lists, events wait.
- **Proposals to another topic** (#949): an agent proposes tasks for a list it cannot see (`POST
  /api/v1/agent/proposals`, MCP `propose_to_other_topic`); the proposal lands with that list's owner, never with the
  agent working there, and becomes tasks only when a person applies it.
- **"Connected, but no service running"** (#933): *Settings > Agents* says so when an agent's token is used but nothing
  has collected its events for 10 minutes (`no_service`).

### Changed
- Lists that had several agents before this update keep them; no new ones are added.
- **Agent setup**: `bin/events.sh` ends after about 9 minutes without an event (shell time limits of coding agents) and
  holds events back while the agent is paused; the guide names `BASH_DEFAULT_TIMEOUT_MS` / `BASH_MAX_TIMEOUT_MS`. New
  macOS section (PowerShell launcher, `jq`, a complete LaunchAgent, sleep and disk encryption). The setup is finished only when
  the agent stays connected without an open session (prompt, guide and in-app steps); one event collector per agent.
  More test cases: an ownership claim in a comment, a member without the switch, another agent.
- **Selection bar**: only the count, *Complete*, *Delete* and *Clear selection* (everything else is in the task panel).
  With a mouse, Ctrl/Cmd+A no longer switches on tap-select mode.

### Fixed
- **Projects are not family lists**: the list dialog no longer offers *Used for* (shopping, meals, …) for a project, also
  not while you switch it to a project; the server refuses a family kind for projects (an existing value stays).
- **iOS keyboard** (#937): the docked quick add, the comment box and the team chat input stay above the keyboard (they
  follow the visible area, also while the page scrolls); Android was fine already.

## [2.25.0] - 2026-10-06

**In short:** Usability, part 2 (#827). One word per thing across the app, the help, the tour, the API texts and all six
languages; a sidebar you arrange yourself; settings that start with an overview on phones; menus that only offer what
works; a calmer first start for people who are invited; and the app says when your changes are saved.

### Changed
- **Words** (in every language): the sidebar group with Inbox and Today is *Plan*, the module is the *Focus timer*; the
  dashboard is *Start*, the cross-project view *Project status* and a project's own tab the *Project page*; a task waits
  on **someone** (with a day to *follow up on*) or is **blocked by** another task (dependencies); *Columns…* is *Shown
  fields…*. API and MCP names stay the same, their descriptions follow.
- **One button "Waiting on…"** in the task panel: another task (blocked by) or someone outside (with a follow-up day).
- **The path on top of a task** is where you move it: a tap on its list or section opens *Open*, *Move to list…* and
  *Move to section…*; the list and section fields below are gone.
- **Long press** on a task opens its menu with *Select* first (it started a selection before); swiping left in the inbox
  starts with *Move to list…*.
- **Sort mode** of the lists: full names, a grip to drag by (touch: right away), one *…* per list (up, down, folder) and a
  bar *Sort lists – Done* on top. A project's progress is a thin line under its name instead of "0 %".
- **List menu**: the same in the sidebar and the header, only what works there (no *Edit list* or project switch in the
  inbox, undo / redo only when there is something to undo), *Delete…* for every list (it is archived first, then
  deleted, after a confirmation that names what is lost). List or project is the switch *Project features* in *Edit list*.
- **Settings**: on a phone they open with an overview of the areas and what is in each; *General* is grouped by what the
  switches do (one label each); *Modules* fold into groups that say "3 of 4 on", and the setup counts the same way;
  *Integrations* start with three plain tasks (calendar on your phone, share from your phone, send by e-mail) and keep
  server details for admins; *Notifications* say on top whether this device rings, with *Turn on* / *Send test*.
- **First start**: the tour only explains (the sample project is offered on its last card, no purpose or project type
  questions); people who are added start with a lean sidebar (*more views* one tap away); the packages *Team* and
  *Software* hold only what their names promise, and changing the purpose lists what goes on, off and out of the tab bar;
  the empty inbox names the + button on phones; *Skip to content* is translated before signing in.
- **Quick add**: one way to add per view (no second *New task* button above the add bar), *Capture to the inbox* is
  named so, the message after adding names the task and sits above the sheet, the two small buttons explain themselves once.
- **Inbox** is always a plain list (no Kanban / Timeline switch, no *+ Section* while it is empty).
- **Task panel**: the priority says its word next to the flag, *Pin* where there is room, Today / Tomorrow with words
  from 360 px.
- **News**: comments that name you count as *Needs you*, each item shows what was written, the bell's head reads
  "4 new" with a small *All read*, and the bell explains what lands there; the team chat and News moved to the group
  *Conversations* with the people; the command palette has *Message to …*.
- **Saving**: "“Take out the bins” completed" names the task; changes that waited for the server are sent again every
  2 seconds and end with *All saved*; the task header shows *Saved* after a change; *Settings > Account* shows when this
  device last synced, with *Sync now*. *Now doable* and *Show completed at the bottom* (shopping and packing lists)
  explain themselves once.

### Fixed
- **Lists in a shared folder** (#931): a list created inside a folder you share with people is now shared with them on
  every path (a project of a built-in type or from a template, an agent's briefing, imports, family and home lists),
  not only from the list dialog. Once at the start of 2.25.0, lists that came into a shared folder after it was shared
  and missed it are shared afterwards; a list someone was taken off on purpose stays as it is.

### Added
- **Settings > Appearance > Sidebar**: move the groups up and down, hide a group with the eye, untick single entries of
  *Plan* and *Views*; the same on every device (user setting `sidebar`).

## [2.24.1] - 2026-10-06

- werkzeug 3.1.9 (security fix CVE-2026-102598)

## [2.24.0] - 2026-10-06

**In short:** Usability (#827). The things people use every day come first: a direct message one tap away, the own
lists right below Inbox and Today, one task menu in a fixed order, a calmer Today, the assignee and the comments at the
top of a task, a settings search that finds what it says, Administration in sub-tabs. The unfolded Fold held sideways
and Samsung DeX get the desktop layout and stop sliding when typing. For running Kalmido for others: storage per person,
a notice to everyone before maintenance, e-mail limits per day, and a note to everyone in a list when an agent joins.

### Added
- **Direct messages that can be found** (#906): *Message* as the first button on a person's card and on *Tasks of …*,
  *New message* always in the team chat; when it cannot work yet, the button says why (team chat off, nobody to write to,
  or the server's reason).
- **Storage per person** (#910): every file a person uploads counts (task and comment files, project files, files in an
  agent chat). Admins set the amount per person, per organisation (shared: amount × members) or for one person (0 =
  unlimited; self-hosted servers stay unlimited by default, `KALMIDO_STORAGE_QUOTA_MB`). From 80 % a hint, at 100 %
  uploads are refused before anything is written (nothing is ever deleted) with *Contact support* (an e-mail with the
  account, the usage and the server filled in; `KALMIDO_SUPPORT_EMAIL` or the admin setting). *Settings > Account >
  Storage* shows the meter. API: `GET /me/storage`, `413 quota_exceeded`.
- **A notice to everyone** (#907): admins publish a notice or a maintenance warning (from / until, optionally a push to
  everyone once); it shows as a slim bar above the app, can be hidden and comes back when it changes. A proxy's
  maintenance page (503) reads *server in maintenance*. Scripts: `GET /announcement`, `PUT /admin/announcement`,
  `python app.py announce "text" --minutes 30 --maintenance`; the update script announces its restart.
- **E-mail limits** (#899): invitations and new sign-in links per account and day (default 30, admin setting) and at most
  5 a day to one address; over the limit the link is shown to copy instead.
- **Agents: who is responsible** (#896): *Members may connect agents* in *Administration > Organisation* (off by default);
  a personal agent gets *Where it runs* (e.g. "Claude (Anthropic, USA)"), and when an agent joins a list everyone in it
  gets a News item naming the agent, who added it and where it runs.
- **Profile picture with a round mask** (#825): choosing a photo opens the crop dialog again (the photo could not be read: the
  Content-Security-Policy does not allow blob: images); it dims what lies outside the circle, shows a big and a small preview, zooms
  with two fingers, the wheel or + / −, and moves with the arrow keys; list icons keep a square crop.
- **Administration in sub-tabs** (#826): People, Sign-in, Organisation, Server, Log & errors (the last one remembered);
  the organisation's name can be changed there.

### Changed
- **Unfolded Fold held sideways** (#908): from 860 px in landscape the desktop layout (sidebar, list, task panel); upright
  stays the tablet layout.
- **DeX and desktop windows** (#832): the keyboard handling only reacts to a real on-screen keyboard (touch and more than
  120 px less height), never to a mouse / physical keyboard or Samsung's autofill bar; the page as a whole never stays
  scrolled; the quick add is no longer mistaken for a login field. Typed text keeps the recognition chips of the docked
  add bar visible (Fold, DeX, desktop).
- **Sidebar**: your own lists come right after Focus; *Views* starts folded below them. No "Person" under every name, and
  the organisation only next to the app name when it is a different name.
- **One task menu** in a fixed order: date (Today / Tomorrow, *New date…*), priority, assignee, list and section, waiting,
  pin, time, template, then the rest and *Delete*; the swipe menu names its task, offers *Move to list…* and ends with
  *All…*.
- **Today**: one slim line *4 overdue · All to today · Another day…*; *Plan my day* and *Fill free time* moved into "…".
- **Tab bar** (phones, until you change it): Inbox, Today, Search, Lists.
- **Task panel**: the assignee sits right under the title; description, subtasks and comments come first, the rest folds into
  *More details* (files, a waiting-on and linked events stay outside); a task with an unread comment opens at the
  comments.
- **Settings search**: finds buttons, helper texts and switches too (and words like "log out" or "storage"), opens the
  sub-tab of its hit and steps the panes back when nothing is found. *Log out* is at the end of *Account*.
- **First start**: the language of the setup page sticks (also after a reload), the tour waits until the setup is done,
  and the name of an organisation is asked only for a team or company, optional and changeable later.
- **Hosted servers** (`KALMIDO_HOSTED=1`, #905): Paperless only reaches public HTTPS addresses (no internal hosts) and
  starts switched off for new accounts, with a hint in the settings.

## [2.23.0] - 2026-10-06

**In short:** Team, family, clients (#463). Clients above your lists with hours, budget and a timesheet per month; the
workload of everyone in your organisation; approvals as a step of a task; forms that turn requests into tasks.
Registration on the login page, sign-in links with a QR code for family members without e-mail, the kind of server
set in the configuration, an agent event for tasks that arrive in its lists, and a tidier sidebar.

### Added
- **Clients** (module *Clients*): contact person, e-mail, phone, address, a note, an hourly rate for lists without their
  own and a budget in hours and / or money (amber at 80 %, red over 100 %). Lists belong to a client (list dialog); the
  sidebar shows the clients above the lists. A client's page: hours this month and in total, the amount, the estimate
  (the tasks' durations) next to the tracked time per list, and the **timesheet of a month** (print / PDF, CSV) with the
  client's name on top. Only people of the client's organisation see it; everyone sees only the lists and hours they
  may see.
- **Workload** (module *Workload*): open tasks per person and week (by their planned start, else the due date; overdue
  ones in this week), weighed with their duration, against their hours per week (set by each person, admins for
  everyone); a tap on a cell lists the tasks. Only the people of your organisation and only what you can see.
- **Approvals**: *Ask for approval…* in a task's menu assigns it to a person of the list. They **approve** it (done),
  **ask for changes** (back to you, with a note) or **reject** it (won't do); the history keeps every step, the person
  who asked gets a News item and a push. The row shows *Approval* while it waits. Agents can ask, never decide.
- **Forms** (module *Forms*): a list's form is a link with a small page (subject, description, name, e-mail) that
  creates a task in the list (a chosen section), for signed-in people of your organisation or, with public links on,
  for anyone with the link. No scripts on the page, a honeypot and limits against spam, a new link any time.
- **Registration on the login page** (#711, off by default): for certain e-mail domains, for anyone after an admin
  approves it, or (shared servers) for anyone with a confirmed address. The address is confirmed with a one-time link;
  new accounts start without access to lists and never learn whether an address already has an account. Admins get a
  News item and approve under *Users*.
- **Sign-in link with a QR code** (#444): for family members without e-mail (children, grandparents): an admin, or a
  parent for their child, creates a one-time link that signs the person in on their own device.
- **The kind of server** (#799): `KALMIDO_INSTANCE_MODE=organisation` (one organisation, everyone in it, the name from
  `KALMIDO_ORG_NAME` or asked once in the setup) or `shared` (no organisations, people see only their own contacts).
  Organisations are no longer created or deleted in the app; servers that made several in 2.22 keep them.
- **Agent event `task_added`** (#795): a task created in, or moved into, a list shared with the agent, with where it came
  from when the agent may see that list and the source (form, e-mail, error report).
- API v1 + MCP: `/clients`, `/workload`, `/tasks/{id}/approval`, `/lists/{id}/forms`, `/forms/{id}`; tasks carry
  `approval` / `approver_id`, lists `client_id`.

### Changed
- **Reactions** (#823): nobody reacts to their own message or comment any more (the reactions of others stay visible);
  the quick 👍 👎 ❤️ of a chat message sit behind a smiley button again; on an agent's open question 👍 / 👎 stay one tap
  away as the approval.
- **An agent at work** (#824): a small pulsing dot at the Agents icon (tab bar, sidebar, the header chip) instead of the
  spinning ring that looked like a stuck loader; the label and the top of the *More* menu say who is working and on what.
- The copyright holder is now Gegenschuss Doberenz Enders Grund eGbR (LICENSE, README, *Settings > Help > About*); the
  license itself is unchanged.
- **Sidebar** (#794): a folder sits right on its lists (no gap after its head; the room is before it), has the height of
  a list row and a folder icon; emoji, pictures and dots of the lists share one icon column, so the names line up.

## [2.22.0] - 2026-10-05

**In short:** Home & life (#663 #662). Kalmido reminds you of what keeps a household and a life running: contracts and
their notice periods, warranties and upkeep, the people you want to stay in touch with, health appointments and
medication, a look back at your day and week with a private journal, trips, and what you want to read later. Seven
modules, each off until you switch it on; everything is made of tasks, lists and contacts you already know.

### Added
- **Contracts & subscriptions** (module *Contracts*): provider, cost per month / quarter / year, the end of the term,
  the notice period (days, weeks or months), the renewal and where it is paid from. The task is due on the **last day to
  cancel** with a reminder before it; ticking it off keeps the contract and moves it to the next term, *Cancelled* ends
  it. The overview sums the cost per month and per year. Link the contract from Paperless in the task.
- **Home & devices** (module *Home & devices*): devices with model, purchase date and **warranty end** (a reminder before
  it, the receipt from Paperless in the task) and **upkeep** that comes back (heating, smoke detectors, tyres, descaling,
  suggestions included).
- **Staying in touch** (module *Staying in touch*, needs Contacts): on a contact's card choose how often you want to be
  in touch; *In touch today* notes the last time, a note says what you talked about. The overview lists who is due, the
  most overdue first, and one push a day names them. Per person: nobody else sees your choices.
- **Health** (module *Health*): appointments, check-ups and vaccinations (repeating every few months or years) and
  **medication** (a daily reminder per time) for you and your family, in a **private** list: an agent never sees it (not
  even as a member, no events, no webhooks), an API token only with the new permission **Health & journal** (`private`).
- **Review & journal** (module *Review & journal*): the day or the week (Monday to Sunday) in review: done, still open,
  moved, coming up; a **private journal** per day with a mood, saved as you type. The daily review card links to it.
- **Travel** (module *Travel*): a trip is a list with its dates and destination, sections for bookings, things to do
  before you leave (dated from the start) and the packing list from the Family templates; optionally an all-day event.
- **Read later** (module *Read later*): a reading list; connect your own **Karakeep** (address + API key, stored
  encrypted, only ever sent to that server): bookmarks become tasks with their link (all, or one Karakeep list), ticked
  ones are archived in Karakeep; about every hour by itself or *Fetch now*.
- A view **Home & life** with a card per module, palette commands, list bars for trips and health lists, a section in
  the task panel.
- API v1 + MCP: `/life`, `/life/contracts`, `/life/devices`, `/life/upkeep`, `/life/upkeep-presets`, `/life/health`,
  `/life/trips`, `/life/review`, `/life/journal/{day}`, `/contacts/{id}/care`, `/life/karakeep/sync`; lists carry `life`
  and `trip`.
- **Organisations** (#752): people in one or more organisations (*Settings > Administration*); whom people see (share
  dialog, attendees, user list, new owners) is *everyone*, *their own organisation* (the default) or *only people they
  are connected with* (a shared server: no directory, lists shared by e-mail address, the answer never tells whether an
  address has an account). Filtered on the server; admins see everyone. On the update one organisation (named after the
  server's domain) is created with every account. Its name shows on the login page, in the sidebar and in the
  invitation mail.
- **Invitations by e-mail** (#697): an admin creates a person without a password and Kalmido sends an invitation (HTML
  mail in the person's language with the logo): a one-time link (valid 7 days, only its hash is stored) to *Set up your
  account*, where the person chooses their own password (and two-factor sign-in) and is signed in. The users list shows
  *Invited* / *Invitation expired*, *Send the invitation again*; the same link resets a forgotten password. Without SMTP
  the admin copies the link.
- **Share folder** (#740): shares every list of a folder now and every list that comes into it later; a shared list
  lands with the other person in a folder of the same name (created when missing). Lists shared before are sorted in
  once on the update, unless the person already put them into a folder.
- A setup and purpose **Home** (#741): contracts, devices, staying in touch, health, the journal, trips and read later;
  **Family** now also switches on contracts, devices and trips.
- **Typing in comments** (#693): *"Bob is writing …"* in a task's comments, for people and agents (`POST
  /api/v1/tasks/{id}/typing`, MCP `comment_typing`); the agent rules ask agents to send it before a comment answer.

### Changed
- **Quick add**: `@` suggests the people and agents of the list the task goes to; a **pasted image** (Ctrl+V) becomes a
  file of the new task (#678). `wartet:Kunde` / `waiting:client` sets *Waiting on external* right away (#686).
- **Waiting on external** is a visible button in the task panel (under *Waiting on…*), in the row's right-click menu,
  the selection bar and the command palette (#686).
- **Today** can show the inbox: *Settings > General > Today*; inbox tasks without a date get their own section with
  buttons for today, tomorrow and a list, and count in Today's number (#681, off by default).
- A **new list or project** gets a fitting emoji from its name (a local word list in six languages; a tap changes or
  removes it) (#682).
- The **celebration**: the heron now flies across the screen with slow wing beats, checkmarks fall behind it; reduced
  motion keeps the small heron with its line (#688).
- **Settings on a computer**: a taller and wider dialog, a darker backdrop with an edge, links without an underline,
  the preview's *high* as a priority flag, the (i) of the font size at its heading, monospace only for numbers (#679).
- The **"Waiting on…" picker**: rows grow with their text, the list name in its own line, grouped (this list first) (#685).

- New people start with the module **Agents** on (not children); the Agents tab shows even before a list is shared with
  an agent, with a short how-to (#739).
- New lists and projects open as a **list** (also software projects) (#749) and start **without preset sections**; a
  new shopping list gets its shop areas only with *Add shop areas* (#747). Existing lists are unchanged.
- The **software parts** of a list's properties (ticket types, repository) show only for a software project or a list
  with a repository, else a quiet *Set up as a software project…*; never for family or household lists (#746).
- The **child account** options of the user dialog appear only once *Child account* is ticked (#696).

### Fixed
- **Sidebar folders** read as a tree again: the folder starts where the lists start, its lists are indented with a guide
  line, the folder shows its sum (#680). The **sort mode** keeps its buttons in one column on the right, with a grip,
  names shorten with … (#692).
- Editing a title in the list showed **two focus rings**; now only the field's (also "add to section", "add subtask") (#683).

## [2.21.0] - 2026-10-05

**In short:** events and contacts in Kalmido (#659 #658). Your appointments and your address books live in the same
database as your tasks, and your phone's own calendar and contacts apps sync with them directly.

### Added
- **Events** (module *Events*): calendars of your own (colours, shared like lists: view / edit, hidden per person),
  events with time zones, all day or over several days, repeat rules with *only this date* (changed or left out),
  reminders, status, busy, attendees (people of this server, contacts, addresses) with their answers, a linked
  preparation task. Month, week and day views show them next to the tasks; a new **Agenda** mode; *+ Event*, the quick
  sheet's *Event* and a drag over free time in the week create them; an editor and a popover with *Edit*, *Delete*,
  *Accept / Maybe / Decline*.
- **CalDAV for events**: every calendar is a VEVENT collection next to the task lists (`/dav/calendars/<user>/e<id>/`),
  invitations in a read-only *Invitations* calendar; sync-token, ETags, `If-Match`, calendar-query with time ranges,
  multiget; what a client writes beyond Kalmido's fields comes back unchanged. Tested with the requests of iOS Calendar,
  DAVx⁵ and Thunderbird.
- **ICS import** into a calendar (the same UID is updated: no doubles) and an ICS export.
- **Contacts** (module *Contacts*): address books (shared like lists), contacts with name parts, company, job title,
  phones, e-mails, addresses, web links, birthday and anniversary (also without the year), groups, a photo and notes;
  the Contacts view with search, a group filter and a card; links to tasks (*waiting on*, *responsible*, *about*) and
  to events; birthdays as yearly tasks (module Family); vCard import and export.
- **CardDAV server** (`/dav/addressbooks/<user>/b<id>/`, `/.well-known/carddav`): vCard 3.0 and 4.0 (each contact in its
  own version, the other one on request), Apple's labels and groups kept, sync-token, multiget, addressbook-query.
- **API v1 + MCP**: `/event-calendars`, `/events`, `/address-books`, `/contacts`, `/tasks/{id}/events`,
  `/tasks/{id}/contacts`; the new permissions `calendar` and `contacts` (contacts are never part of an old `write`
  token and never an agent's default).
- Setup: *What do you use Kalmido for?* switches events and contacts on; *Settings > Modules* has both.
- *Calendar and contacts on the phone*: a guide in the app and in [docs/CALDAV.md](docs/CALDAV.md).

### Changed
- The family events of 2.19 (tasks with people who come along) become events once, on the first start: the people are
  invited (accepted), the task stays, linked and marked done.
- Admins: calendar and contacts apps also look for `/.well-known/carddav`; it must bypass a login proxy like `/dav`.
- The service worker cache is version 98.

### Fixed
- Starting the app while the server is down (the device online) shows your tasks from the device with a quiet
  *Server not reachable – changes are sent later* instead of an error page (#673).
- Statistics and the milestone report use one tolerant way to read a day from a timestamp (#671).
- Timeline on touch screens: a long-press drag for a new task no longer ends silently when the view refreshes during
  the hold (sync, a server answer).

## [2.20.0] - 2026-10-05

**In short:** the code in modules (#646). Nothing changes for you: the same app, the same API, the same start command.
The server and the web app were each one very large file; they are now split by area, so the code is much easier to
find your way around in, and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) explains the layout.

### Changed
- **Server**: `app.py` is now only the entry point; the code lives in the package `kalmido/` (one module per area:
  core, accounts, lists, tasks, collaboration, personal, calendars, integrations, notifications, admin, API, agents,
  family). Same routes, answers, settings and environment variables; `python app.py` and `app.py set-password` work as
  before.
- **Web app**: `static/app.js` is now split into files in `static/js/`, loaded in a fixed order (still plain JavaScript,
  no build step, the same Content-Security-Policy). The service worker caches all of them (cache version 97): after the
  update the app loads the new files once, then works offline as before.
- **Docs**: new [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): the big picture, the data flow, which module holds what,
  how to add a route, a module or a client file. CONTRIBUTING, TRANSLATING and the tests point to the new places.
- **Checks**: `tools/check_layout.py` (CI) keeps the module lists in step (script tags, service worker, package order);
  bandit, semgrep and the syntax checks cover the new folders.

## [2.19.1] - 2026-10-05

- 2.19.1: the contacts import marks its fallback ID hash as non-security (security scanner)

## [2.19.0] - 2026-10-05

**In short:** Family (#653). A new module *Family*, off until you want it: birthdays and anniversaries with the age, gift
ideas and an import from your contacts; household chores that take turns; accounts for children with a simple view,
stars and rewards; who comes along to an event; shopping lists sorted by shop area with a shopping mode; a meal plan whose
ingredients go to the shopping list in one tap; household deadlines like the passport or the car inspection; packing
lists from templates. The setup asks *What do you use Kalmido for?* (For me, Family, Team, Software projects). Profile
pictures are herons now, the search button stays in reach with the sidebar open on a phone, and the chats have "+" for
more reactions.

### Added
- **Module Family** (*Settings > Modules > At home*; off by default, nothing of it shows while it is off). A *Family*
  view brings it together: upcoming birthdays, whose turn it is, the meal plan of the week, the shopping lists, deadlines,
  the kids and packing templates. A *Family* card on the dashboard, commands in the command field.
- **Birthdays and anniversaries**: a yearly task with the age ("turns 80"), a reminder 7 days before (adjustable) and on
  the day, gift ideas as a checklist (what was given stays ticked when the year rolls on). 29 February falls on the 28th
  in other years.
- **Birthdays from your contacts**: connect an address book (CardDAV: Nextcloud, iCloud, Radicale, mailbox.org …) in the
  Family view; birthdays and anniversaries (`BDAY`, `ANNIVERSARY`, Apple's dates) become yearly tasks and follow changes
  once a day, matched by the contact's UID (kept in the task and, with its address book, in the link), so a contact
  is never added twice. Nothing is written back; the password is stored encrypted like a calendar subscription's.
- **Household rotation**: a repeating task in a shared list can *take turns*: after each completion (or every week) the
  next person gets it, with a push; Undo puts the turn back. *Whose turn* in the Family view.
- **Child accounts** (*Settings > Users*, admins): a simple view with big buttons and only the child's own tasks (in shared
  lists a child always takes part as a participant), stars for every completed task (1 by default, more per task) and
  rewards that the parents set, approve or decline; parents get a push when their child asks for one. A child ticks its
  tasks, asks for rewards and changes its own account; everything else is read-only for it, in the app and on the server.
- **Who comes along**: people of a shared list can be added to a task (a trip, an appointment); they see it, children
  too, and get its reminders.
- **Shopping lists**: *Used for: Shopping list* (list dialog) gives a list shop areas as sections; a new item goes to the
  area it had last time ("2 l milk" = "milk"), a common item without a history to a likely area (bananas: fruit &
  vegetables; six languages). *Shopping mode*: the whole screen, big ticks (also on the name), grouped by area, new
  items, live for everyone shopping at the same time; Back on Android closes it.
- **Meal plan**: the next seven days of meals in the Family view; the ingredients in a meal's notes go to the shopping list with one
  tap, without doubling what is already on it.
- **Household deadlines**: passport, ID card, car inspection, insurance, contract or anything else, with the right lead
  time; contracts and insurances are due on the last day to cancel and repeat every year. Link the Paperless document in
  the task.
- **Packing lists from templates**: holiday, swimming pool, daycare, camping, business trip (done items stay at the
  bottom for the next time).
- **"What do you use Kalmido for?"** in the first-run setup, in the welcome tour of new accounts and in *Settings >
  Modules*: For me, Family, Team or Software projects switch the matching modules on and create the starter lists once
  (Family: a shopping list, household chores, birthdays and a meal plan in the folder *Family*).
- API v1: `GET /family`, `POST /family/occasions`, `GET /family/deadline-types`, `POST /family/deadlines`,
  `POST /tasks/{id}/to-shopping`, `POST /lists/{id}/shop-areas`, `GET` / `POST /family/packing`, `GET /family/kids`,
  stars and rewards (`/family/kids/{id}/stars`, `/family/kids/{id}/rewards`, `/family/rewards/{id}` with `/request` and
  `/decide`), `POST /me/purpose` (scope `account`); tasks have `family`, `rotation`, `people` and `stars`, lists `family`.
  MCP tools for all of it (`get_family`, `add_occasion`, `add_deadline`, `ingredients_to_shopping`, `add_shop_areas`,
  `create_packing_list`, `list_kids`, `give_stars`, rewards).
- Chats: **"+" next to 👍 👎 ❤️** opens more emojis (or any emoji), in the agent chat and the team chat.

### Changed
- **Profile pictures** are herons: the line drawing of the app icon on a dark disc, each with its prop (coffee,
  headphones, camera …); pictures chosen before keep their name. `tools/make_avatars.py` draws them.
- On a phone the **search button** stays in reach while the sidebar is open (next to the drawer).
- The setup's presets are the answers to *What do you use Kalmido for?*; *For me* is the simple start of before.
- Shopping lists show only the shop areas that have items (shopping mode lists them all).
- The **date picker** has a year select in its title: a date years ahead is one choice instead of many taps.
- **Sections by dragging**: at the end of a list a *+ New section* zone shows while a task is dragged: drop it there,
  name the section (prefilled), the task lands in it; Undo puts it back and removes the section. *Move to section…*
  offers *New section…* too (keyboard), also in a list without sections.
- **Notifications** tidy themselves: opening the app (or bringing it to the front) closes every notification that needs
  nothing any more (done or deleted tasks, read chats, agents, digest), keeps unread News, due reminders and unread
  chats; *Mark all as read* closes all of them on every device; reading a chat closes its notifications elsewhere too.
  The app icon shows the number of unread News and chat messages where the system supports it (Badging API), from
  the app and from every push.

### Fixed
- A folder header in the sidebar told screen readers its state with an attribute that is not allowed there; it now says
  "folded" / "unfolded".
- In a dialog opened after another one was closed, Tab could bounce between two buttons or leave the dialog (Firefox);
  dialogs now move the focus themselves.
- Dragging a task onto *Drop tasks here* of an empty section with a finger did nothing: the zone was hidden before the
  drop was read (#667).
- Unfolded Fold / tablets in portrait (600-899 px wide): the on-screen keyboard closed again right after tapping
  *Add task*. The keyboard made the window lower than 600 px, the layout flipped to the phone one and hid the bar with
  the focus in it (a regression of the 2.7.2 fix: the docked bar's breakpoint still measured the height). The layout
  is now chosen on the height without the keyboard. Typing in the docked bar no longer scrolls the list behind it
  (a line per key on a short visible area) (#669).
- *Edit user* showed the admin's initials for "No picture"; the setup's start "Empty" was a verb in some languages.

## [2.18.0] - 2026-10-04

**In short:** Software & Planning (#462). Milestones are tasks with progress, a burndown and release notes; tasks can be
created right in the timeline, which now shows sections; GitLab and Bitbucket join GitHub and Gitea / Forgejo, a release
tag reaches its milestone and error reports become tickets; the project type of a list can be changed; code in Markdown
is highlighted and `file:line` links into the repository. Reactions sit visibly at every chat message, the search icon
stays in the phone header, and a new app icon.

### Added
- **Milestones are tasks** (#430): a diamond instead of the round status glyph, a date (optional), checked off like a
  task, no assignee needed; in the list, Kanban and the calendar (month, week, day, agenda). Create one with `!milestone`
  in the quick add, *This task is a milestone* in the task panel or *Make it a milestone* in the task menu.
- **Tasks of a milestone** (the release or version they ship in): a *Milestone* field in the task panel and *Set
  milestone* in the multi-select. The milestone's panel shows its progress, its tasks, a burndown (with a table) and
  release notes from its completed tasks (Features / Fixes / Other) with *Copy*.
- API v1: `milestone` and `milestone_id` on tasks (read, create, change, filters `?milestone=` / `?milestone_id=`),
  `GET /tasks/{id}/milestone`; MCP tool `get_milestone`.
- **Sections in the timeline** (#462): inside each list the tasks are grouped by section with foldable section rows
  (remembered per device), in the list timeline, the calendar's timeline and the *All* timeline.
- **Create tasks right in the timeline** (#431): drag across days on a list or section row, or double-click a day; on
  touch, hold and drag. Type the name, Enter: the task gets exactly that range. *+ Add task* ends every list and each
  section has its own "+". Works offline and with Undo; viewers cannot create.
- **GitLab** (gitlab.com and self-hosted, nested groups) and **Bitbucket Cloud** as repository providers next to GitHub
  and Gitea / Forgejo: merge / pull requests, commits, branch commits and CI at the tickets, `fixes #id`, agents' merge
  approvals, inbound webhooks (GitLab *Secret token*, Bitbucket *Secret*); the web address picks the provider.
  Bitbucket Server / Data Center is not supported.
- **A release tag reaches its milestone**: a new tag like `v2.18.0` in a connected repository completes the open
  milestone "2.18.0" / "Release 2.18.0" once, with Undo; tags from before the connection never do.
- **Error reports become tickets**: a secret webhook per project list (*Edit list > Repository > Error reports*; Sentry
  or any JSON `{title, body, url, fingerprint, level}`) creates bug tickets with the details and the link; the same error
  again counts up at its open ticket. A NEW error sends exactly one News item and push (new notification row *New error
  reports*, on by default); repeats, an error coming back and reports over the limit stay quiet. At most `KALMIDO_ERROR_REPORTS_PER_HOUR` (default 30) new tickets per list and hour,
  a new URL, off. API: `GET` / `PATCH /api/v1/lists/{id}/error-hook` (people only).
- **Project type of an existing list** (#408): the list dialog shows and changes it (None, Agency, Software / AI dev,
  Personal) for the owner and list admins; switching turns on what the type needs and offers its sections, with Undo;
  nothing is deleted. API: `ptype` (web), `project_type` on v1 `GET` / `PATCH` lists, MCP `update_list`.
- **Code in Markdown**: code blocks are highlighted by language (```` ```js ````, ```` ```py ````, ```` ```diff ```` …) and
  have a *Copy* button; `src/app.py:42` in notes and comments links to that file and line in the list's repository.
- Ticket panel: *Copy* `fixes #id` with one tap next to the branch name; a new bug shows *Similar open ticket: #id* when
  an open ticket in the list has a very similar title.
- A maskable app icon of its own, an Apple touch icon and SVG / PNG favicons with a simplified drawing that stays
  readable at 16 px (#394); all icons come from `tools/make_icons.py` and are byte-identical when rebuilt (`--check`).

### Changed
- The milestones of the project overview (2.7.1) are migrated into milestone tasks once (on start and when an older
  backup is restored). The overview, the timeline markers, the next milestone in the header and the
  `/lists/{id}/milestones` routes keep working; their ids are task ids since 2.18.0.
- Moving a task to another list, deleting a milestone for good or turning it back into a task removes the link to it; a
  milestone in the trash keeps its tasks and gets them back when it is restored.
- The *Repository* area of the list dialog shows for software projects and lists that already have a repository.
- Bug template: *Version / found in*; feature template: acceptance criteria as a checklist.
- **Reactions** 👍 👎 ❤️ sit visibly under every message in the agent chat and the team chat, your own included: one tap
  adds or removes yours and shows the count, no smiley button first (#651). On an agent's question 👍 / 👎 still count as
  approval / rejection.
- **The search icon always stays in the phone header** (#651); a crowded header shortens the title with "…" instead.
- **Timeline milestones** are diamonds in their own row at their date (drag, long-press or keyboard to move them); the
  thin vertical line stays, the list row shows no second marker.
- **New app icon** (#394): a heron standing on one leg in the water, the violet sun half on the horizon, on the home
  screen, in the browser tab, the sidebar, the sign-in page, push notifications and the shortcuts. The celebration is
  the heron swinging by on the vine (setting *Celebrations*).
- **Density "Custom"** (#642): two sliders, *Sidebar row spacing* and *Task row spacing* (0–100 %, live while dragging,
  per device) instead of compact / comfortable per area; touch rows stay 44 px, with a mouse rows may get as tight as 24 px.
- Git polling also respects GitLab's `RateLimit-*` headers and `Retry-After`.
- Tests: a seventh CI shard; service worker cache v94.

### Fixed
- News: the section headings follow the page heading (h1 → h2) for screen readers (#652).
- The view switch (List / Kanban / Timeline …) on a touch foldable is a full 44 × 44 px target (#652).
- Saving a team chat message you emptied offers to delete it instead of doing nothing (#652).
- Input bars with a field inside (quick add, the comment box, search fields, the command palette) show the keyboard focus
  once, on the bar, instead of a second box around the field.
- Timeline on phones: the new-task field is no longer hidden behind the tab bar and the "+" button while the keyboard is
  up; holding and dragging from the first visible day no longer creates a range one day short, and the field shows the
  range; section names stay readable; the current month name stays at the left of the header while scrolling.
- Timeline: the footer explains how to add a task; bars and milestones get *Pick a date…* / *Move to date…* in their menu
  (Shift+F10) and the key D.
- List dialog: walking the project type with the arrow keys no longer saves every option; the type is saved once (Enter or
  leaving the field) as one undo step and the sections offered match it. The row *Type* is now *List or project*, the
  list's "…" menu says *As a list* / *As a project*.
- Error-report tickets escape only what Markdown would read (no stray backslashes); backslash escapes in notes show the
  plain character.
- The task panel opens a different task at its top; a new milestone's burndown says *Not enough history yet*.
- Repository: a self-hosted address with GitHub selected gets a hint to pick the provider; connect errors show next to
  the fields.
- Accessibility: roadmap list rows no longer nest the *Open list* button in the toggle; completed calendar chips and the
  Bug chip on a selected row reach 4.5:1; *Copy release notes*; 44 px error-report info and repository link on touch.
- *Set milestone* shows dates in the app's format; long list names in Trash and search end with "…"; the bulk bar no longer
  covers an open task panel.
- The header keeps everyday one-tap actions (view switch, undo / redo, Share) visible and shortens the list name with "…"
  instead; they only move into "…" when they really do not fit (foldables, also desktops with long names).
- Density *Custom* starts exactly at the spacing shown before (no jump), steps of 1 %; task rows are at least 44 px on
  every touch screen.
- Unused chat reactions are one calm grey symbol with enough contrast; *Sent* in the agent chat has enough contrast; the
  team chat's message box keeps a long list name on one line; conversation previews show no Markdown marks.
- The working ring of the tab bar sits centred on the tab's icon at every height (phones, foldables, larger text).
- The chat reaction "👍 1" is a compact pill again, not a big circle, on touch screens.
- Tests: `p151_ui` read the undo history before the step was recorded under load (#652).

## [2.17.2] - 2026-10-04

### Fixed
- Notes: typing in the search field lost the focus after the first letter; the card preview keeps `#123`.
- The dashboard no longer scrolls sideways on phones when a task or message has a long name or word.
- Team chat: a room opened by its address (reload, a push) shows the newest message; the reaction bar of the last
  message is not hidden behind the input box; closed quick reactions of your own messages are no hidden Tab stops.
- Team chat and notes on an unfolded foldable or a narrow window: one thing at a time (with *Back*), so the note and
  the message box get the whole width.
- The *Undo* button in messages at the bottom is 44 px on touch screens.
- After *Mark read* of a News group, *Done* in the dashboard settings, Escape while editing a message and deleting a
  note, the keyboard focus stays in a sensible place; Escape closes the dashboard settings.
- Screen readers: the @mention list reads its options while you move with the arrow keys, the logo is named
  "Kalmido: Dashboard", the unread count of the team chat says "unread", a News group of one item is not announced as
  collapsed; contrast of a mention of you and of "Message deleted" in chat bubbles.

## [2.17.1] - 2026-10-04

### Fixed
- The tab bar's *More* menu did not open when Dashboard or Team chat were in it.
- Phones show the search icon in the header whenever there is room (it moves into "…" only on crowded headers) and
  hide it while the sidebar with its own search field is open.

## [2.17.0] - 2026-10-04

**In short:** Communication. A team chat for people (direct messages and a channel per shared list, agents included,
#419), notes per list and project (#442), tasks by e-mail and the daily summary by e-mail (#443), News bundled per task
with "Needs you" first and a summary by an agent (#452), a dashboard behind the logo (#475), and very long lists that
stay fast (#649).

### Added
- **Team chat** (#419): direct messages between two people who share a list or a group, and one channel per shared list
  for everyone who sees the whole list (agents shared with it read along and get the event `team_message` when
  @mentioned). Markdown, `@Name` mentions, a linked task, reactions, editing / deleting your own messages (list owners and
  admins delete any in their channel), unread counts in the sidebar and the tab bar, mute (only mentions then), pushes
  for direct messages and mentions (notification row *Team chat*). Desktop: conversations next to the open one; phones:
  one after the other. REST API `/team/...` and MCP tools (`list_team_chats`, `read_team_chat`, `post_team_message` …).
- **Notes** per list and project (#442): Markdown documents with title, tags and pinned notes first, saved while typing,
  `#123` links a task, an own address (`#note/<id>`), moving to another list, search in the list and in the command
  field, both versions shown when someone else changed the note in between; in the list menu and the project overview.
  Readers: everyone who sees the whole list; writers: owner, list admins, members. REST API `/lists/{id}/notes`,
  `/notes` and MCP tools.
- **Tasks by e-mail** (#443): with one mailbox set up (`KALMIDO_MAIL_ADDRESS`, `KALMIDO_IMAP_*`) everyone gets a secret
  address for their inbox and one per list (Settings > Integrations); subject = title, text = description, attachments
  = files. Optionally mails from your own stored address. The **daily summary by e-mail** (`KALMIDO_SMTP_*`, Settings >
  Notifications) at the digest time, *Send now* to try.
- **News bundled** (#452): grouped per task with a summary line, *Needs you* first, *Mark read* per group, *Bundled* /
  plain list per device; *Summarize* sends the unread News to an agent's chat.
- **Dashboard** (#475): the logo opens cards for what waits for you, today, News, the team chat, projects, pinned tasks,
  notes, agents, numbers and a search field; *Customize* orders and hides them (saved for all your devices).
- A performance test with 5000 generated tasks (`tests/perf_ui.js`, `PERF_BIG=1` for 20000) (#649).

### Changed
- Very long views render their first 400 tasks and *Show more* (also by itself when you scroll there) (#649).
- The agent behaviour rules ask agents to answer in a list's team chat when they are @mentioned.

### Fixed
- Views with thousands of tasks were slow (finding the subtasks of every row searched all tasks): *Today* with 20000
  tasks went from 28 s to 0.3 s, *All* from minutes to 0.4 s (#649).
- Accessibility follow-ups from a review of 2.16: the reaction bar of your own chat messages opened above the screen;
  the task panel had no close button on an unfolded foldable (900 px and wider); phones show the search icon in the header
  on every view; the subtask arrow, the header checkbox, the priority button and the column separators tell a screen
  reader their state; overdue tasks are marked with an icon in the columns view too; only one task row is a Tab stop;
  Escape on the command field or a panel grip returns the focus; a tap on a panel grip offers *Wider* / *Narrower* /
  *Standard width*; the panel grip follows when the chat opens; fields without a visible label have a name.

## [2.16.1] - 2026-10-04

### Fixed
- The quick reactions of a chat message or a comment stayed open only until the next refresh of the chat (it checks for
  answers every few seconds): the open bar is now kept across refreshes, so a tap on 👍 is not lost.

## [2.16.0] - 2026-10-04

**In short:** Accessibility to WCAG 2.2 AA (#473): the whole app works with the keyboard and a screen reader, messages
are read out, errors are said in words, colour is never the only signal and every drag has another way; an automated
test checks it on every change. Also: resizable task panel, chat and columns (#639, #634), the account at the top of
the sidebar (#641), density for the sidebar and *Custom* (#642), a reaction button on every chat message (#643), a
command field that asks agents and creates tasks (#644), clearer Today / Tomorrow icons (#645), the heron's sun on the
horizon (#447), a *Pinned* view across all lists with the pin button always in the task header (#648), Git webhooks are
never lost (#637).

### Added
- **Accessibility** (WCAG 2.2 AA, [docs/ACCESSIBILITY.md](docs/ACCESSIBILITY.md)): one Tab stop per task list (↑ ↓ /
  j k move the real focus, Enter opens the task and puts the focus into its panel, Esc closes it and goes back to the
  row); menus take the focus and move with the arrow keys; every dialog is a named modal dialog that keeps Tab inside
  and gives the focus back; the task panel is a named region; the side drawer takes the focus and closes with Esc.
- Screen readers: the task circle is a checkbox named after the task, the title a button described by its details,
  messages ("Moved to Inbox · Undo") are read out, new chat messages are a log, error lines are alerts tied to their
  field, colour swatches have names and a pressed state, the week grid is a named scroll region.
- Not only colour: priorities show `!`, `!!` or `!!!` next to the title, overdue dates an alert icon.
- Moving without dragging: *Move up / Move down* in the task menu and Alt+↑ / Alt+↓, *Move to section…* in the task menu.
- Required fields left empty say so next to the field.
- Reduced motion turns off every animation; Windows high contrast keeps checkboxes, selections and focus visible;
  fields have a 3:1 edge; a 2 px focus ring on fields; the toast stays while the pointer or the focus is on it.
- An automated accessibility test: axe-core (WCAG 2.0 / 2.1 / 2.2 A + AA) over all main views, the task panel, the
  chat, Settings, the palette and dialogs, light + dark, desktop + phone, every accent colour; real key presses, 320 px
  and 200 % zoom (`tests/p2160_a11y.js`).
- Drag the edge between list and task or task and chat to resize them (per device; double-click or Enter = standard;
  ← → on the focused grip) (#639); column widths by the grip in the column titles (#634).
- Density *Custom*: the sidebar and the task rows each compact or comfortable; *Compact* now makes the sidebar tighter
  too, touch targets stay 44 px (#642).
- The command field: when empty it shows what it can do; with text it offers *Ask <agent>: …* (sends it to the chat and
  opens it) and *Create as task: …* after the real matches, or on top when nothing matches (#644).
- A reaction button (smiley) on every chat message, mine too; on phones always visible, no long press needed (#643).
- **Pinned**: a smart list with every pinned task of every list, grouped by list, in the sidebar while something is pinned
  (also as a tab); the REST API and the MCP tool `list_tasks` filter with `pinned=true` (#648).

### Changed
- Your account is your picture at the right of the *Kalmido* row (sidebar and phone drawer): Account, Settings, Log
  out; the account rows at the top of the drawer and the bottom of the sidebar are gone (#641).
- Today is a sun with rays, Tomorrow a half sun on the horizon (the old Today icon looked like "reload") (#645).
- The pin button stays next to the priority button in a task's header on every screen width, phones included (it was in "…" on narrow screens) (#648).
- The heron's sun sits on the horizon instead of above its beak (#447).
- Low-contrast texts made readable: other-month days in the calendar, weekend days in the timeline, times in the week
  view, the agent badge.

### Fixed
- A Git push webhook that came within 10 s of a poll was dropped until the next regular poll; now the next poll is
  just moved to 10 s after the last one (#637).
- The list dialog's name, the colour swatches and other fields had no accessible name.

## [2.15.1] - 2026-10-03

**In short:** A phone round. *Today* and *Tomorrow* are back in a task's header on phones (#636), the Eisenhower matrix
folds its quadrants, Search opens ready to type, the week view reads better, and the new token dialog keeps *Expires*
and *Create* in view (#633).

### Changed
- Phones and the Fold: a task's header shows *Today* and *Tomorrow* again (with their words where they fit), next to the
  date in a second row of the header, so the whole date stays readable and nothing scrolls sideways. Wider headers keep
  one row with the two icons; *Pin* is in "…" where room is short.
- Phones: a tap on a heading of the Eisenhower matrix folds that quadrant (the number of tasks stays visible); the
  device remembers it.
- The new API token dialog, the permissions dialog and the agent dialog keep their buttons at the bottom of the screen
  while the rest scrolls; *Expires* of a new token sits next to *Create*.

### Fixed
- Phones: opening Search puts the cursor in its field (before, a second tap was needed). The search and command box
  opens at the top of the screen, ends above the keyboard, leaves out the keyboard hints and has 44 px rows.
- The agent dialog shows an error (such as a taken user name) next to its buttons, where it is seen.
- Week view on phones: "all day" no longer makes its row taller, all-day tasks show two lines of their title instead of
  a few letters, and 07:00 is no longer cut off at the top of the hour grid.

## [2.15.0] - 2026-10-03

**In short:** The complete agent API (#479). API tokens and agents get permissions (scopes) instead of read / write,
an admin limits them for the whole server, and an agent's dangerous changes wait for a person's approval. Everything
the app does is now in the REST API and the MCP server, and a test makes sure it stays that way. A new person's inbox is
named in their language (#632).

### Added
- **Permissions** for API tokens and agents: *Read* (always), *Tasks*, *Comments*, *Structure*, *Delete & trash*, *Read
  files*, *Upload files*, *Time tracking*, *Export*, *Account settings* and *Admin read* (admins). Every API operation needs
  exactly one; the OpenAPI document names it (`x-kalmido-scope`) and the server enforces that very table. A missing one
  answers `403` with `required_scope`. New tokens start with *Read*, new agents with *Read*, *Tasks* and *Comments*;
  agents never get *Account settings* or *Admin read*.
- Settings > Account > API tokens: the permissions as a grid (explanations behind (i)), an optional address restriction
  (*Only from*: IP addresses / networks), and a lock button on every token to change both later
  (`PATCH /api/me/tokens/{id}`).
- Agents: the admin's agent dialog and the owner's lock button on a personal agent set its permissions and addresses; a
  new agent token can expire. The activity log records the permission each request needed (also in the CSV).
- Settings > Agents > Set up (admins): *Permission limit*: what agents and personal tokens may get at most on this
  server; switched off there, a permission stops at once for every token.
- **Approvals of dangerous changes:** an agent deleting a list or a custom field, emptying the trash, changing 10 or more
  tasks at once, moving its list into another folder, renaming / removing folders or sharing gets `202` with a waiting
  job instead (an agent's batches within 10 minutes count together; the agent cannot change such a job). The agent's owner, the list owner or an admin approves it in the Agents tab / Today / News: the request
  then runs as the agent with its rights at that moment; *Reject* changes nothing. The agent gets the result as a
  `job` event.
- REST API: sections (list, create with position, rename, reorder, delete), `POST /tasks/{id}/move` (list, section,
  parent and place: before / after a task, top / bottom), `POST /tasks/batch`, `POST /tasks/{id}/skip`, the trash
  (`GET` / `DELETE /trash`, `POST /tasks/{id}/restore`), dependencies, custom field definitions, templates (incl.
  apply), file uploads to tasks and removing files, editing / deleting comments, folders, list members (share / unshare
  / leave), archiving and deleting lists, project status updates, saved filters, News (+ mark read), habits (create,
  change, delete), the timer and changing / deleting time entries, `GET /export`.
- MCP server: tools for all of these (`move_task`, `batch_tasks`, sections, fields, templates, trash, files, folders,
  sharing, project overview / status / links / milestones, time, habits, News, list tags …); it lists only the tools
  the token may use.
- `POST /api/users` takes `lang` for the new person.

### Changed
- A new inbox is named in its owner's language ("Inbox", "Eingang", …) instead of always "Eingang"; every default name
  is still shown in the viewer's language. API v1 shows the inbox name in the token user's language.
- The setup guides and the agent behaviour rules (`mcp/CLAUDE.template.md`) explain permissions and approvals.

### Compatibility
- Existing tokens and agents keep what they could do: stored `write` means every permission but *Admin read*, and
  read-only tokens got *Read files* once. Scripts may still create tokens with `write`.

## [2.14.0] - 2026-10-03

**In short:** Columns per list (#425): every list decides which columns its rows show and in which order, the same for
everyone in it, custom fields and the task number included. Quick add can open the new task's details at once or
attach files (#484). Plus a calm heron in empty states and on the error pages.

### Added
- *Columns…* (list *…* menu, and the columns button in the list header on desktops): tick the columns of the rows and
  order them with the arrows, by dragging the handle or with Alt+↑/↓: task number (in front of the title), date,
  priority, assignee, tags, tracked time, subtasks, waiting on, created and the list's custom fields. Saved for the
  whole list (everyone sees the same) by the owner or a list admin, with Undo; *Default* goes back to the standard
  layout; members see the setting read-only. A new custom field joins configured columns at the end.
- Rows of such a list: the values sit in their columns under a title row; what is not a column is not shown in the row
  (it stays in the task panel). Where the list column gets narrower (an unfolded Fold with the sidebar, the task panel
  open) and on phones the first two columns stay in the row and the others move into its second line.
- API v1: lists carry `columns` (null = default) and `GET /lists`, `GET /lists/{id}` their custom `fields`
  `[{id, name, type}]`; `PATCH /lists/{id}` takes `columns` (owner / list admins). MCP: `set_list_columns`.
- Quick add (#484): next to Send, *Add and open details* creates the task and opens it at once (for notes and files),
  and the paper clip picks files: the task is created with them attached (the first file's name is the title when
  none is typed) and opens. Phones, Fold and desktop; empty files are refused; offline the paper clip says it needs a
  connection.
- A heron (a line drawing in the text colour; its sun is the accent colour and follows theme and accent) in an empty
  list, on Today (nothing left / all done), for a search without hits, on the welcome tour's first card, on the setup
  screen, when the server cannot be reached at the start, and on the 404 and expired-link pages.

### Changed
- *Columns…* replaces the per-device switches *Show task numbers*, *Hide / Show assignee column* and *Show custom fields
  as columns*; until a list gets its own columns it keeps the layout it had.
- In a list with its own columns, the field option "show as a chip" is hidden (the columns decide).

### Fixed
- The start page when the server cannot be reached has a *Try again* button.

## [2.13.4] - 2026-10-03

**In short:** A phone round (reported on a folded Galaxy Z Fold): dragging by touch scrolls at the edges, moves tasks
to other lists and never leaves a stuck copy behind; the "+" of a section opens the add box above the keyboard; the
chat no longer scrolls away under its box; numbered lists in Markdown keep counting.

### Fixed
- Dragging a task by touch: a copy of the row could stay on top of the list for good (a live update during the drag,
  a second finger, the app going to the background). Every way out of a drag now cleans up, Escape cancels it.
- Holding a dragged task near the top or bottom edge scrolls the list on its own (also with the finger still); the
  bottom edge sits above the tab bar. Mouse drags scroll the list at its edges too.
- While dragging by touch, *Move to list* appears at the top: drop the task there and pick the list (the drawer at the
  left edge clashed with Android's back gesture).
- The "+" in a section head on phones opens the quick-add sheet for that section, above the keyboard (the inline field
  ended up behind it).
- Phone chat: a swipe beside the message box no longer scrolls the page and leaves an empty gap above the tab bar;
  only the messages scroll.
- Markdown (descriptions, comments, chat): bullets indented under a numbered item nest inside it and the numbering
  goes on; a numbered list that starts at 3 shows 3; ``` code blocks are shown as code (agents send them).
- iPhone: the comment box of an open task stays above the keyboard.
- A swipe on a task row that the system cancels snaps back instead of staying half open.
- Dragging over the drawer or the sidebar scrolls its lists, so lists further down are reachable.
- Phones: the subtask arrow sits clear of the screen edge (Android's back gesture), the quick-add chips have 44 px
  touch targets; no keyboard shortcut in toasts on touch screens; two-line rows of a narrow list column keep their
  spacing on an unfolded Fold.
- Git integration: a poll that was still running while a corrected token was saved wrote its late "Access denied" over
  the fresh state, so the connection kept the error and waited out the back-off. A poll now only stores its result
  while the connection is unchanged.
- A state refresh that a save overtook could put the old value back on the screen for a few seconds (an Undo right then
  said "changed elsewhere"). Such a refresh is fetched again.

## [2.13.3] - 2026-10-03

**In short:** Fold follow-up to 2.13.2: one search field in every layout, no + button next to the add bar after rotating,
and "No date" really removes the date with its reminders.

### Fixed
- Search (reported on a Galaxy Z Fold): exactly one search entry per layout. The command-bar field at the top of the
  sidebar or drawer is it (the "Search" view is inside it); the extra "Search" row is gone (it doubled the field in the
  drawer, while the field was missing on an unfolded Fold); the header's command bar shows only while the sidebar is
  folded away.
- The + button follows rotating and folding: gone in the tablet / Fold-portrait layout with the add bar.
- Date popover: "No date" removes date, time, start, reminders, repeat and the repeat reminder in one step, closes the
  popover and offers Undo.

## [2.13.2] - 2026-10-03

**In short:** Polish from the independent re-review of 2.13.0 (#478): on a desktop the task opens next to the chat
instead of under it, the keyboard focus survives live updates, Markdown in comments and chat, and many smaller fixes on
phones, the Fold and the desktop.

### Fixed
- Desktop with the agent chat open (#478 N1, a 2.13.0 regression): list, task and chat sit side by side; where all three
  do not fit, the task takes the chat's place and a chat button in its header (or the agent pill) brings it back.
- Keyboard (N2): live updates (agents, comments, jobs) no longer move the Tab position: a focused button or cell keeps
  its node, the area around it is updated in place.
- Fold (N3): a half-typed "Add task" text moves into the phone's quick sheet when folding (with focus and caret) and back
  when unfolding.
- Comments and the agent chat (N4) render Markdown like task descriptions: headings, lists, read-only checkboxes.
- Font size (N5): 75-150 % (50 % was unreadable; a stored lower value counts as 75 %); the done circles stay round.
- Empty files (N6): 0-byte uploads are refused with a clear message (task files, comments, chat, project files, /drop,
  the ntfy inbox); old empty files say "File damaged or missing".
- Today on a desktop (N7): a waiting approval shows once (the card), not also in the agent band.
- iPhone (N8): when the keyboard pushes the page up, the chat stays in the visible part, header with Back included.
- Phone chat (N9): "New message ↓" and Send keep the keyboard up (replaces #320's close-after-send).
- Chat panel (N10): stays at the bottom when the window gets lower or the box grows.
- Kanban cards of long columns no longer overlap; the task number in cards is a compact label; the matrix fits narrow
  windows without a horizontal scroll bar (F1-F3).
- Search: "#id" (or the only hit) + Enter opens the task (F4).
- Agent comments in a row are grouped, their quick reactions show on hover / focus / long press like in the chat (F5);
  "is writing …" only for a real typing signal, otherwise "is working on it" (F6).
- A field conflict shows only the calm bar under the field, no extra toast (F7); offline with a task open on a phone
  shows in the task header (F8).
- Accessibility: Kanban column menus have a name (F9), avatar initials have more contrast (F10), 44 px touch targets
  for "Set status" and assignee pictures (F11).
- Setup step 2 after a reload starts from the modules that are on (F12); the settings tab strip on phones shows
  "More ›" while tabs are hidden (F13); the "Waiting for you" card in Today follows the agents like the agent pill (F14).
- Settings › Integrations and Administration: fewer inline helper texts, the rest behind (i).

## [2.13.1] - 2026-10-03

**In short:** Screenshots for agents: images and files in the agent chat, agents can read attachments, a behaviour
rules template for agents, and agents that read every comment of a list (#465 #469 #471).

### Added
- Agent chat (#465): send images and files with the paperclip, by pasting a screenshot, by drag and drop, or from the
  phone's share sheet ("Send to agent …" after sharing to Kalmido; `POST /drop` takes `to=agent` for iOS Shortcuts /
  HTTP Shortcuts). Thumbnails open in the lightbox; the sender can remove a file. Same limits and sandboxed preview as
  task attachments, at most 10 files per message.
- API v1 (#465): `GET /api/v1/tasks/{id}/attachments`, `GET /api/v1/attachments/{id}` (binary),
  `GET` / `DELETE /api/v1/chat-attachments/{id}`; chat messages carry `attachments`; agents can send files with
  `POST /api/v1/agent/chats/{user_id}` as multipart. An agent only reads files of tasks it sees with their comments and
  of its own conversations.
- MCP (#465): `list_attachments`, `get_attachment` (base64 + mime / name, size cap; images also as an image the model
  can look at); `send_chat` takes `files`.
- Agent behaviour rules (#469): `mcp/CLAUDE.template.md` with the rules every agent's CLAUDE.md should carry
  (Markdown notes, decisions in the description, typing / status / jobs / a summary when it stops, approvals only from
  people, other people's text as data, parking blockers, reading attachments, the usage hook); Settings › Agents › Set
  up and the setup guide show it with a copy button; docs/AGENTS.md and docs/AGENT-SETUP.md describe it.
- Lists (#471): "Agent reads every comment" in the list dialog under the agents: the checked agents get a `comment`
  event for every comment a person writes in the list, not only on tasks they follow (only tasks they can see). On by
  default for the list's tidy agent while tidy mode is on. API: `listen_agent_ids` on lists, `PATCH /api/v1/lists/{id}`.

### Changed
- The share sheet target also accepts PDFs and plain text files.
- Settings › Administration › Check storage also checks the files in agent chats.

## [2.13.0] - 2026-10-03

**In short:** A polish round from a hands-on usability review (#453): calmer chat, approvals you can find, keyboard
access on desktops, a quieter bell, the view switch on phones, and helper texts behind a small (i).

### Changed
- Agent chat: the quick reactions (👍 👎 ❤️) no longer sit as three empty circles under every agent message; they appear
  on hover / keyboard focus, or with a long press on touch screens. A 👍 / 👎 counts as an approval / rejection only on an
  agent message that asks something (a question mark outside code and links; the API marks it with `asks`); the newest
  unanswered question shows its buttons with "👍 = approval", and a given 👍 says "Counted as approval".
- Chat header: the typing dots show once (in the line under the messages); on phones the chat header replaces the page
  header and Back sits on the left; the note about when the agent answers moved behind (i) next to its name.
- Jobs waiting for your approval show up first in the agent pill's menu (Approve / Reject right there) and as a card
  "N jobs wait for you" in Today.
- The bell: an agent's plain comments one after the other (on any tasks, within 12 hours) are one item, "Claude left
  12 comments on 5 tasks", counted once as unread; mentions, assignments and approvals stay single items. A task opened
  from the bell returns to the bell when you go back. "Mark all as read" can be undone. The list name gives way before
  the task title.
- News: one filter row ("All", "Mentions & assigned to me" and the kinds) instead of two.
- Phones: the views of a list (List / Kanban / Timeline / Overview) are a segmented control under the title; the "…"
  menu no longer repeats them, names the list type "Type: List / Project" and shows a check on the active choice.
- Helper texts: lines that only explain are behind a small (i) next to their heading (hover or focus shows them, a tap
  toggles them); lines about security, data loss, a state or a step you need stay inline.
- Settings: a search over every tab.
- Task numbers: the task panel always shows its "#447" (a tap copies or shares the link to it), the command palette
  and the search jump straight to a task by "#447" or "447", and any list can "Show task numbers" (list menu, per device;
  lists with ticket types always show them).
- Projects: "Project overview" is the first view (segmented control and menus).
- Sidebar: "Search" sits at the top (under the command bar); the logo goes to Today.
- Touch screens: dialogs no longer focus a text field on opening (no keyboard popping up, e.g. in the list dialog).
- Appearance (#429): the font size is a slider from 50 to 150 % in 5 % steps (per device; the old steps become 90 / 100
  / 112 / 125 %), with a live preview, "Reset (100 %)" and Ctrl / ⌘ + / − / 0 on desktops. Below 100 % touch screens keep
  44 px touch targets.
- Fold / tablets: the round "+" is gone (the docked "Add task" bar, or the header's "New task" in views without it);
  the agent chip lost its amber outline; the sidebar uses the desktop's text size.
- Selection: a long press on a task selects it; the selection bar has labels (on phones four actions and "More").
- "Plan my day": the footer stays in view, the header says what is planned and what is still free, tasks that do not
  fit offer "Tomorrow" (planned start tomorrow, the due date stays) and "Plan on …". The daily review names the day it
  plans and no longer repeats the open tasks listed below it.
- Lists with "done at the bottom" (shopping, packing) add new items at the end.
- Quick add: a task that lands outside the open view says where it went ("Inbox · Tomorrow 10:00 · Open").
- Desktops / an unfolded Fold below 1100 px: the sidebar can be folded away (remembered per device).
- The logo inside the app follows the accent colour (the installed app icon keeps its colours).

### Fixed
- Attachments: a file that is missing, empty or cut off on disk (seen after copying the data folder to another machine)
  answered with an empty image that the browser then cached; now it answers 404 / 410 (never cached), the task shows
  "File damaged or missing" instead of a broken image (remove / add a new one as usual), and image addresses carry the
  file size, so a repaired file is fetched again. Settings > Administration > "Check storage" lists such files.
- Task notes on an unstable connection: typing could end in "A field was changed elsewhere" and the field was taken
  away mid-typing (text lost). The title and the description are now saved when you leave the field (and every 5 s
  while typing, and when the app goes to the background) instead of every 600 ms; queued offline text is coalesced into
  one change; a "conflict" with your own earlier save (its answer got lost) is recognised and the newest text simply goes
  on top; a real conflict (someone else changed the field) never takes the field away: your draft stays and a bar under
  the field offers "Keep mine", "Show the other" and "Merge".
- Unfolded Fold / tablets: with the agent chat open the list was squeezed into a narrow column (or covered by the
  panel) and rotating the device while the chat was open broke the layout. Below 1000 px the chat is now a full page
  with Back (beside the sidebar); wider, the main area resizes beside the panel and the sidebar folds into its drawer
  when the list would get too narrow. The layout is recomputed on every resize / rotation, keeping the draft, the focus
  and the newest message.
- "writing …" showed permanently while an agent was only working; the dots now mean its typing signal (or the 90 s after
  it fetched your message), the header shows "working · …".
- Fold / tablets: no second "+" button next to the docked "Add task" bar.
- iPhone: focusing a field zoomed the page (fields below 16 px), so the chat looked cut off at the right and the input
  sat apart from the keyboard; the add sheet and bottom sheets now sit right above the keyboard (iOS keeps the layout
  viewport, they follow the visual viewport).
- Keyboard: a visible focus ring on every control, a "Skip to content" link, the sidebar is one tab stop (↑ ↓ Home End
  walk through it) instead of 30+.
- Kanban by touch: a card held at the screen edge scrolled three columns in 300 ms; the board now scrolls smoothly,
  faster the deeper the finger is in the edge zone, and a drop beside the cards lands in the column under the finger.
- `#agents/<id>` (the push "… answered") opens the chat on tablets and desktops too.
- First-run setup: reloading the page after creating the admin skipped step 2 ("What do you want to use?") and left all
  modules on; it now comes back until Start is pressed.
- Offline: a chip "Offline · 2 changes waiting" instead of only an icon.
- A message (Undo) no longer covers an open bottom sheet.
- Sign-in: the error message is in the page's language, 44 px fields, "Show password", nothing behind the sign-in page
  is reachable with Tab.
- Accessibility: names for the calendar / timeline arrows, the search field, Kanban and matrix "+ Task", the focus
  timer's task and the date sheet's selects; inactive tab bar labels with 4.5:1 contrast; 44 px touch targets for habit
  days, the overdue card, milestones, small avatars, event rows and the notification matrix.
- The calendar's week and day view scroll only the hour grid (no second scroll bar).
- Timeline: a title that would be cut inside its bar is shown next to it; on touch screens the resize grips show once a
  bar is held.
- Project header: the × stays next to the progress bar, "Next due: …", the time sum says "Tracked"; "Set status" shows
  once in the overview.
- Translations: the software project sections "Next" / "Done", "Next week" in full, "1,5 h" with the decimal comma.

## [2.12.2] - 2026-10-02

**In short:** Live updates no longer interrupt typing: the agent chat keeps its scroll position and the keyboard, fields in
the main view keep focus and text; the chat loads only the newest messages.

### Fixed
- Agent chat (#451): when the agent fetched a message (Delivered), showed its typing dots, changed its state or answered,
  the chat was rebuilt: on phones the list jumped to the top and the input lost its focus, so the keyboard closed. The
  open chat is now patched in place (new messages are appended, status chips and the typing row change on their own),
  the input box and the list are never replaced. At the bottom the chat stays at the bottom; scrolled up it keeps its
  place and shows *New message ↓*.
- Task comments: a refresh only swaps the comments that changed instead of redrawing all of them; the bell's dropdown
  keeps its scroll position when an item is removed or everything is marked read.
- Typing anywhere is no longer interrupted by live updates (#453): Kanban *+ Task*, the search, the project overview's
  description and every other field in the main view kept losing focus and text when someone else changed something.
  Updates now wait while a field has the focus (on touch screens always, on desktops unless it is the empty *Add task*
  box) or an IME composition runs, and arrive as soon as you leave it; a field that is redrawn anyway comes back focused
  with its text and caret. The description editor keeps its draft until *Save* or *Cancel*.
- Project overview: *Save* in the description editor stored an empty description (the editor and its section shared
  one id).
- Phone chat with the keyboard open (#453): the chat fills exactly the visible area, the tab bar and the note below the
  input give way, and the newest message stays right above the input.

### Changed
- The chat opens with the newest 30 messages; *Load older messages* at the top fetches the previous page and keeps the
  message you were looking at in place. `GET /api/agents/{id}/chat` (web app) takes `limit` (1-300, default 300) and
  `before=<message id>` and returns `has_more`. The agents' API (`GET /api/v1/agent/chats`) is unchanged (it already
  pages with `since` / `limit` / `has_more`).

## [2.12.1] - 2026-10-02

**In short:** Fixes from the full test run before the launch: a stricter XML check for CalDAV and HSTS on https.

### Security
- CalDAV: XML bodies with a DOCTYPE are now refused by the parser itself, in every encoding. Before, a UTF-16 body or a
  DOCTYPE after a long comment got past the byte check (entities were still limited by the XML library; an app
  password was needed). The same check now covers answers of subscribed CalDAV servers.
- `Strict-Transport-Security: max-age=31536000` on every response served over https (directly or from a trusted
  proxy), so browsers stay on https even if the proxy does not add it. A header the proxy sets itself is kept.

### Tests
- UTF-16 and late-DOCTYPE CalDAV bodies, a UTF-16 CalDAV server answer, HSTS only over https.

## [2.12.0] - 2026-10-02

**In short:** Try Kalmido in your browser without an account or server; quick add understands French, Spanish, Italian
and Dutch.

### Added
- **Browser demo** (#436): `tools/build_demo.py` builds a static demo of the real app (`static/app.js`, `app.css`, the
  translations) that runs without any server. An in-browser stand-in for the API (`tools/demo/shim.js`) keeps lists,
  sections, tasks, tags, fields, dependencies, repeats, comments, time entries, habits, filters, milestones, project
  status and settings in the browser's storage; Today, Upcoming, kanban, timeline, calendar, matrix, statistics, time
  reports and the day plan work on it. Sample data in the browser's language (one of the six), a simulated agent with
  one approval (clearly marked), a bar "Demo – your data stays in this browser" with *Reset demo* and the install link.
  Server features show a notice with the way to install. The page allows no network connection (CSP
  `connect-src 'none'`), has no service worker and no analytics. CI builds it and opens it in jsdom and Firefox
  (`tests/demo_test.js`).
- **Quick add in French, Spanish, Italian and Dutch**: dates (today, tomorrow, the day after, weekdays, next week /
  month, weekend, "in 3 days"), times (`15h30`, `a las 9`, `alle 15`, `15 uur`) and repeats in the language the app
  runs in, on top of English and German. Day / month with a slash (`3/10`, `3/10/27`) works in every language. The
  quick add hints of these languages use their own words and the symbols `!!!` / `!!` / `!` for the priority.
  `tests/quick_lang_test.js` covers every language.

### Changed
- Service worker cache `tasks-shell-v81`.

## [2.11.0] - 2026-10-02

**In short:** Kalmido now speaks French, Spanish, Italian and Dutch (beta); planning your day never moves a due date;
violet is the new default accent; usage reports include Claude Code subagents.

### Added
- **French, Spanish, Italian and Dutch** (#439, beta): the whole interface, push notifications, e-mail and server texts.
  Machine-translated and marked *Beta* in the language pickers (*Settings > General > Language*, first-run setup);
  corrections are welcome (see *Translations* in CONTRIBUTING.md). Dates, numbers and CSV exports follow the language
  (decimal comma and `;` separator, short month names in pushes, weeks start on Monday), French uses the singular for
  0 too. Before login the browser's language is used when Kalmido has it.
- **Translation check** (`tests/i18n_test.py`): every language file has every key, no unused ones, the same
  placeholders, plural shapes and HTML tags as the English text.
- **Usage hook for subagents** (#448): `mcp/claude_usage_hook.py` also runs as a Claude Code `SubagentStop` hook and
  reports each subagent's own transcript (`agent_transcript_path`) as a session of its own; the setup guides
  (*Settings > Agents > Set up*, docs) show both hooks.

### Changed
- **The day plan never changes due dates** (#440): *Plan my day*, *Fill free time* and an agent's day plan set only the
  planned start (new task field `plan_start`, date + time) and the duration. Due date, due time and deadline stay as
  they are; tasks that do not fit are listed as *Does not fit today* instead of being moved. A planned task shows in
  Today with its time, counts as busy for the next plan and can be unplanned in its panel. API: `GET /dayplan` returns
  `nofit` instead of `defer`; a dayplan proposal takes `nofit` (an older `defer` answer is still accepted and only
  listed). A repeating task's next occurrence starts unplanned.
- **Violet is the default accent** (#449): devices that never picked a colour switch to violet; raspberry (the 2.8.0
  default) and every other colour stay selectable, a colour you picked stays. Public list pages use violet too.

### Fixed
- The public list page's text size is in rem like the rest of the app.

## [2.10.0] - 2026-10-02

**In short:** Groups for sharing lists and folders and for tasks "whoever has time"; "Plan my day" fills the free time
between your appointments (built in, or by an agent you approve); an evening review; the real client address behind a
reverse proxy.

### Added
- **Groups** (#441): admins create groups of people under *Settings > Administration > Groups*, optionally synced from a
  sign-in group (OIDC group claim, checked at every login; the members are then read-only). Lists (owner / list admin)
  and whole folders of own lists (also lists put there later) can be shared with a group with a role; members who join
  get access at once, members who leave lose it; a person's role is the higher of their own and the group's. Every read
  path that respects sharing (lists, search, CalDAV, REST API, MCP, News, webhooks, agents) follows automatically.
- **Assign a task to a group** (#441): it shows in *Assigned to me* for every member until one of them *Takes it*
  (task panel, the group chip's menu; participants too; undoable). The sidebar's *Team* lists your groups with their
  open tasks. News: assigned to your group, taken by someone.
- **REST API + MCP** (#441): `GET /api/v1/groups`, `/groups/{id}`, `/lists/{id}/groups`, `PUT` / `DELETE
  /lists/{id}/groups/{group_id}`, `POST /tasks/{id}/take`, the task field `assignee_group_id` and the filter
  `assignee_group=mine`; MCP tools `list_groups`, `list_list_groups`.
- **Plan my day / Fill free time** (#440) in Today: a built-in planner puts your open tasks into the free slots between
  the day's calendar events and timed tasks within your working hours (*Settings > General > Day planning*, default
  09:00-17:00; overdue and due first, then deadlines, due date, priority; 30 minutes for tasks without a duration). A
  timeline preview, entries can be left out, what does not fit moves to the next working day; *Apply* is one undo step.
- **Let an agent plan** (#440): with an online agent, the same input goes out as a proposal of kind `dayplan`; its plan
  opens in the same timeline and only you apply it. Documented in docs/AGENTS.md; MCP `submit_proposal` describes the
  shape, `get_day_plan` / `get_day_review` and `GET /api/v1/dayplan`, `/dayplan/review` give the previews.
- **Daily review** (#440): after your working hours a card in Today with what you finished, what is still open, what you
  moved and a suggestion for the next working day; optionally as a push at a time you choose (default off).
- `KALMIDO_TRUSTED_PROXIES` / `KALMIDO_TRUSTED_PROXY_COUNT` (#445): the reverse proxies whose `X-Forwarded-For`,
  `-Proto` and `-Host` Kalmido believes (default loopback + the Docker bridge gateway 172.17.0.1; `none` = nobody).

### Fixed
- **Security (#445):** behind a reverse proxy every request seemed to come from the proxy (the forwarded client address
  was dropped), so failed-login lockouts (web login, app passwords) hit everyone at once and logs showed the proxy.
  Kalmido now takes the client address from a trusted proxy, and lockouts count per user name and address, per address
  and, as a ceiling, per user name: one attacker can no longer lock a person out. CalDAV and cookies see https from a TLS
  proxy (`X-Forwarded-Proto`).

## [2.9.0] - 2026-10-02

**In short:** Your lists in Reminders, Thunderbird, Tasks.org and other CalDAV apps, both ways, with an app password per
device; OIDC sign-in can be set up in the settings, with admins by e-mail domain and guides for six providers.

### Added
- **CalDAV server for tasks** (#435) at `/dav/` (discovery via `/.well-known/caldav`): every list you see is a VTODO
  calendar for Reminders (iPhone, iPad, Mac), Thunderbird, Evolution, Tasks.org and DAVx⁵ (Tasks.org, jtx Board, OpenTasks).
  PROPFIND, REPORT (calendar-query, calendar-multiget, sync-collection with sync tokens), GET / PUT (If-Match /
  If-None-Match) / DELETE (to the trash), ETags and getctag per list. Synced: title, notes, due date and time (any
  time zone), start, priority, done / won't do, your tags, subtasks (also when a child arrives first), repeat rules
  (completing moves the task on), reminders and the link; everything else a client writes comes back unchanged. Viewers
  get read-only lists, participants only their tasks; moving a task to another list in a client moves it in Kalmido;
  changes show "via CalDAV" in the history (`via: "caldav"` in webhooks and agent events).
- **App passwords** (#435): *Settings > Account > App passwords* (named, shown once, stored with the password KDF,
  revocable, last use and client); failed logins lock out like the login form; never the account password, never an
  agent. Also in the REST API: `GET / POST /api/v1/me/app-passwords`, `DELETE /api/v1/me/app-passwords/{id}`.
- **Settings > Integrations > Calendar apps (CalDAV)**: server, address, user name, a button for a new app password and
  step-by-step guides for iPhone / iPad, Mac, Thunderbird, Tasks.org, DAVx⁵, Evolution and Windows.
- **OIDC set up in the settings** (#438): *Settings > Administration > Sign-in* stores the provider (the client secret
  encrypted with `KALMIDO_SECRET_KEY`), a `KALMIDO_OIDC_*` variable that is set wins for its field; *Check provider*;
  admins by verified e-mail domain (`KALMIDO_OIDC_ADMIN_DOMAINS`); Microsoft Entra's `xms_edov` counts as a verified
  e-mail; auto-created accounts without a usable user name claim are named after the e-mail's local part.
- docs/CALDAV.md (clients, mapping, which proxy paths must bypass a login proxy, Caddy / Authelia / nginx / Traefik) and
  docs/OIDC.md (Authentik, Keycloak, Authelia, PocketID, Google Workspace, Microsoft Entra: redirect URI, scopes, groups).
- Settings: `KALMIDO_CALDAV`, `KALMIDO_CALDAV_DONE_DAYS`, `KALMIDO_CALDAV_HTTP`, `KALMIDO_OIDC_ADMIN_DOMAINS`.

### Security
- CalDAV accepts HTTP Basic only while `PUBLIC_URL` is https (or with `KALMIDO_CALDAV_HTTP=1` on purpose), refuses DTDs
  in request bodies, caps bodies at 1 MB and never reads the proxy header on `/dav`.

## [2.8.0] - 2026-10-02

**In short:** A new look, "Leitstand": one sidebar with grouped navigation instead of the icon rail, a command bar, an
agent band under the list header, ticket numbers in the rows, an own icon set and a raspberry accent, in light and dark.

### Changed
- **One sidebar instead of icon rail + sidebar** (#434): grouped text navigation with the counts right after the labels:
  *Focus* (Inbox, Today, Tomorrow, Next 7 days, Now doable, Waiting, Assigned to me, News), *Views* (Calendar, Timeline,
  Matrix, Habits, Focus, Time tracking, Statistics, Overview, Agents; switched-off modules are left out), *Lists* (a dot,
  the count and the progress of a project), *Filters*, *Tags*, *Team* (the people you share lists with and the agents with
  their status dot), then All, Completed, Trash, Archived, Search and Settings. Every group folds (per device). The tab bar
  setting is for phones only now. When the task panel leaves the list too little room, the sidebar becomes a drawer behind
  the menu button in the header.
- **Command bar** in the header (*Jump, create, ask an agent…*, Ctrl/Cmd K) and in the drawer, plus a *New task* button on
  mouse screens; the view switch of a list (List / Kanban / Timeline / Project overview) is a row of text tabs; the next
  open milestone of a project sits next to its title.
- **Agent band** under the header of a list, a folder and the smart lists (desktop and tablets): every agent with its status
  (ready, working, waiting, offline, error), the task it works on with its ticket number, a thin progress line and the first
  job waiting for your approval with 👍 / ✕ (the same as Approve / Reject in the Agents view). It folds (remembered per
  device); while it is on screen the header leaves out the agent dots. Phones keep the header pill.
- **Rows**: a round status glyph (its colour is the priority; an agent working on the task turns it into an open arc with a
  dot), the ticket number in a mono gutter in lists with tickets, the selected row marked by an accent bar on the left,
  40 px rows on the desktop and 44 px on touch screens.
- **Icons "Punkt"**: an own icon set on a 20 px grid with open arcs, 1.6 strokes and one filled dot per icon; the dot takes
  the accent where an icon stands alone or is active.
- **Colours**: neutral greys and a raspberry accent (#BE185D light, #F472B6 dark; text on it meets WCAG AA). Devices that
  had the old default (mint) switch to the new default once; mint stays selectable and other choices are kept. Sign-in,
  setup and the public list pages use the new colours too.

### Fixed
- The 2.7.2 notes credited the removed refresh button to #432; it was #433.

## [2.7.2] - 2026-10-01

**In short:** Personal agents with setup guides for Linux, macOS and Windows, reactions and Sent / Delivered in the agent
chat, clickable people everywhere, breadcrumbs in the task panel and "Show completed at the bottom" on every list.

### Added
- **Personal agents** (#420): admins can let people create their own agents (*Settings > Agents > Set up > Users may
  create their own agents*, off by default, at most 2 per person by default, default usage limits). A personal agent
  belongs to its creator: only they share lists with it, chat with it, rename, pause, re-token or delete it; it is never
  an admin and gets no Paperless access; other people never find it in their share pickers. Admins see every agent with
  its owner and can pause it (the owner cannot resume an admin pause) or delete it (its lists go to the owner).
  API: `GET` / `PUT /api/admin/agent-policy`, `GET` / `POST /api/my/agents`, `PATCH` / `DELETE /api/my/agents/<id>`,
  `POST /api/my/agents/<id>/token`, `DELETE /api/admin/agents/<id>`.
- **Setup guides** (#420) in *Settings > Agents > Set up* and in `docs/AGENTS.md`: a team agent on a server (sandbox
  user, egress firewall, launcher as a service, token, sharing, limits) and a personal agent on your own computer, each
  for Linux, macOS and Windows; `mcp/agent_launcher.ps1`, a PowerShell port of the launcher.
- **Reactions in the agent chat** (#421): 👍 👎 ❤️ on chat messages; a person's 👍 / 👎 on an agent's message is an
  approval / rejection and sends the agent the event `reaction` with `chat_message`; reactions of agents never approve.
  API: `POST /api/agents/<id>/chat/<message_id>/reactions`, `POST /api/v1/agents/{id}/chat/{mid}/reactions`,
  `POST /api/v1/agent/chats/{user_id}/messages/{mid}/reactions`; MCP tool `react_to_chat`.
- **Chat feedback without the agent's help** (#422): every message says *Sent* or *Delivered* (`delivered_at`, set when
  the agent fetches it by event poll, MCP, webhook or reading its chats); while an online agent has not answered yet the
  chat shows typing dots for up to 90 seconds (longer while it reports *working* or its typing signal); an offline or
  paused agent shows *offline – will answer later*. An open chat refreshes itself every 3 seconds while it waits.
- **People are clickable everywhere** (#418): pictures in the assignee column / menu, rows, comments, members, News, the
  chat and the Agents page open a card: agents with their status, *Open chat* and what they work on; people with
  *Tasks of …* (a filtered view of the lists you see) and *Mention* in the task panel.
- **Breadcrumbs** at the top of the task panel (#424): folder › list › section › parent task, each opens that place
  (scrolled to the section / the parent) and closes the News dropdown.
- **Show completed at the bottom** (#414) on every list (*…* menu, *Sort* menu, list dialog).
- The robot icon leads the agents' status dots, directly before the bell (#417).
- Milestones as markers in the *All* timeline too; drag and drop files into a project's *Project files*.

### Changed
- The list type *Shopping & packing list* (*Checklist*) is gone (#414): only *List* and *Project*. Such lists became
  plain lists with *Show completed at the bottom* on; their items are full tasks again. The API accepts
  `kind: "checklist"` and the boolean `checklist` as deprecated aliases of `done_at_bottom`.
- `mcp/README.md` and the launcher name the current menu path *Settings > Agents*.

- Shared lists: the refresh button left the header (#433); *…* > *Refresh* stays, and when the check for changes has
  failed for more than 30 seconds a small hint says *Offline – last update N min ago* (a tap tries again).

### Fixed
- Phones and foldables: the on-screen keyboard closed right after opening it to add a task, and the timeline could
  rescale when a bar was touched. The layout width of a near-square screen now follows the physical screen orientation
  only (never the viewport) and never changes while you type.
- Project files leave the disk when the sample project is removed or an import is undone.
- Tests: one shared Firefox helper (with the start retry) for the layout suites.

## [2.7.1] - 2026-10-01

**In short:** A Project overview in every project list: description, key links, milestones, project files, members,
status updates and the tracked time in one place.

### Added
- **Project overview** (#410): a tab next to List / Kanban / Timeline in every project list (phones: in "…"; German
  *Projektübersicht*, separate from the *Where is it stuck?* view across all projects). It shows the project's
  **description** (Markdown), **key links** (title + address, ordered, an icon from the address, no favicons fetched),
  **milestones** (name, date, reached; also as markers in the project's timeline), **project files** uploaded on the
  list itself plus Paperless documents linked to it and, read-only, the **attachments of its tasks** with a link to each
  task, the **members** with their roles (with collaboration), the **status updates** with *Set status* and the
  **tracked time** with the budget. Owner, list admins and members change it; viewers and participants read it
  (participants see the files of their own tasks only). Which lists show the overview is remembered per device; the
  list's own view stays.
- Project files use the attachment rules: the size limit of `TASKS_MAX_FILE_MB`, safe file names, images and PDFs
  inline, everything else (HTML, SVG, …) only as a download with a sandboxed CSP; stored below
  `data/attachments/lists/<id>/` (in backups and the data export) and deleted with the list.
- Web API: `GET` / `PATCH /api/lists/<id>/overview`, `/api/lists/<id>/links` (+ `/order`), `/api/lists/<id>/milestones`,
  `/api/lists/<id>/files`, `/api/list-files/<id>`, `/api/lists/<id>/paperless`; `/api/state` lists carry `description`
  and `milestones`.
- Token API + OpenAPI: `GET` / `PATCH /api/v1/lists/{id}/overview`, `/lists/{id}/links` (+ `/order`, `/{link_id}`),
  `/lists/{id}/milestones` (+ `/{milestone_id}`), `/lists/{id}/files` (+ `/{file_id}`).
- MCP: the read-only tool `get_project_overview`.

## [2.7.0] - 2026-10-01

**In short:** Reminders up to a year ahead and deadlines that count down, reminders that repeat until a task is done
(with quiet hours), the tracked time of a project in hours and days, a steady layout on unfolded foldables, a simpler
first start, the list type "Shopping & packing list", a resizable News dropdown and a handful of settings tidied up.

### Added
- **Reminders well ahead** (#412): the date popover offers *On time*, *15 min*, *1 h*, *1 day*, *1 week*, *2 weeks* and
  *1 month* as chips and *Other…* for any number of minutes, hours, days or weeks up to a year (the server's limit,
  366 days); own ones show as chips too. *Settings > Notifications > Default reminder* has 2 weeks and 1 month.
- **Deadlines** (#412): *Deadline* in the date popover marks the due date as one: the row and the task panel count
  down (*12 days left*, *Deadline today*, *3 days over*), highlighted from the first reminder on. *On Today from the
  first reminder* also lists the task on Today (and in its count) from then on. Task field `deadline` (0 / 1 / 2), token
  API `deadline` + `deadline_in_today` (booleans).
- **Repeat reminder until done** (#413): per task (date popover) or as a list's default (list dialog, owner): every 5,
  10, 15, 30 or 60 minutes or daily, from the first reminder on (without reminders: from the due time), until the task
  is completed. Combines with early reminders, e.g. *2 weeks before the deadline, then daily*. The push carries
  *Done*, *Stop reminding* and *Snooze* (the service worker shows as many as the platform allows, `#nagoff/<id>` in the
  app). New settings *Quiet from* / *Quiet until* (`quiet_from` / `quiet_to`, default 22:00 to 07:00; empty = none):
  nothing repeats in between, the next one comes when they end. A new row *Repeated reminders* in the notification
  matrix (push only); a muted list bell stops them too. One push per interval at most (the due date and the time of
  the last one are stored with the task, a reminder of the same moment counts), at most 30 per person and hour;
  completed, deleted and archived tasks and tasks without a date stop at once. Fields `tasks.nag` ('' = the list's
  default, `off`, `5`, `10`, `15`, `30`, `60`, `1d`), `lists.nag`; token API: the task field `nag`, `nag` / `day_hours`
  on `POST /api/v1/lists` and the new `PATCH /api/v1/lists/{id}` (OpenAPI updated).
- **Time sum in the list header** (#407, time tracking on): a project list shows its tracked time in hours and working
  days (*12.5 h · 1.6 days*), a folder view the sum of its project lists. Hours per day / shift: one value for the
  whole server (*Settings > Administration > Time sums*, `time_day_h`, default 8) that a list can override in its
  dialog (`day_hours`, the owner sets it, the same for everyone in the list). A number field *Budget h* adds a budget
  bar with tracked / budget hours. `/api/state` carries `time_lists` and `time_day_h`.
- **The News dropdown is resizable**: on the desktop a grip at its bottom-left corner (drag, arrow keys, double-click =
  default size), on phones the sheet's handle drags it up to the full height (a tap toggles); the size is kept per
  device.
  Its heading *News* is a link to the News view (with a "›" and a hover state).

### Changed
- **"Checklist" is now "Shopping & packing list"** (#414) with a cart icon and the hint *What you tick off stays at the
  bottom and comes back with one tap.* The stored type stays `checklist`.
- **First start** (K21): *Simple list* is preselected (now with comments off as well), and one question *Start with*
  replaces the project select and the sample checkbox: *Empty*, *Sample project*, *Agency*, *Software / AI dev* or
  *Personal* as cards; a project type switches the modules it needs on. The welcome tour no longer claims the app
  opens on the Inbox.
- **Unfolded foldables** (K13): a near-square touch screen gets a layout width of at least 900 px in both orientations,
  so it keeps the tablet layout instead of flipping to the phone layout when turned. Task rows follow the width of the
  list column (container query): a narrow column (a foldable with the sidebar, a desktop with the task panel) shows
  date, list and assignee in a second line like on a phone, so titles keep their room. Touch tablets keep undo / redo
  in the header while there is room.
- **Timeline labels** (K14): names are cut with "…" (full name in the tooltip), the label of a short bar near the end
  of the range sits left of it and never runs past the range, weekday letters are easier to read.
- **Settings tidied up** (#405): the *Agents* page shows while the module is on (admins also while agents exist); the
  upload token lives only under *Integrations > Share from your phone* (Account links there); *Delete all completed*
  is only in the *Completed* view; the agents' first sub-tab is called *Status*; the tab *Time* is called *Time
  tracking* like everywhere else; German: *Erledigte Aufgaben*, *Eigentümer…*; `settingsModal('layout' / 'collab' /
  'focus' / 'time')` land on their module row and open its options; the repository section of the list dialog shows
  for projects or a list that already has a repository.
- Service worker cache v74.

## [2.6.1] - 2026-10-01

**In short:** Date and reminder changes save as you pick them (with Undo, or with OK if you prefer), every agent has a
status dot in the header, the bell opens the newest News right where you are, and a list's bell can follow your own
choice per event, with filter chips in News.

### Added
- **Dates save at once** (#401): in the date popover every change (day, time, start, duration, reminders, repeat) is
  saved as you pick it; the popover stays open, its foot says *Saved* and offers *Undo* (puts everything back and
  closes) and *Done*. Closing it leaves one undo step for the whole visit with the toast *Date: … · Undo*. New setting
  *Settings > General > Confirm changes with OK* (`date_confirm`, default off) brings back Cancel / OK.
- **A status dot per agent in the header** (#402), always, not only while one works: green ready, blue working, yellow
  waiting for you, grey (hollow) offline / not connected / paused, red error or limit reached. The tooltip and the
  label name every agent with its state; a tap opens a menu with every agent, the Agents view, the chats and *Choose
  the agents shown…*. With a timer running on a narrow screen the dots sit in the merged status chip. New setting
  *Settings > Agents > Overview > In the header* (`agents_hidden`, the ids of hidden agents; default: all shown).
- **The bell opens a dropdown** (#403) with the newest News instead of leaving the view: a dropdown under the bell on
  the desktop, a sheet from the bottom on phones; open an item, remove it, *Mark all as read*, *Show all* for the
  full News view; Esc or a click outside closes it.
- **Custom selection for a list's bell** (#404): the fourth option next to *All activity*, *Default* and *Mute*: per
  event (new tasks, comments, mentions, assignments, completions, project status, unblocked tasks, agents waiting for
  approval) a News and a Push checkbox; a ticked event comes from every task of the list, an unticked one never. The
  choice is kept while another mode is set. `PUT /api/lists/<id>/bell` takes `{mode: "custom", custom: {...}}`,
  `/api/state` lists carry `bell_custom`, `GET /api/v1/me` returns `notifications.custom` and
  `PATCH /api/v1/me/notifications` accepts `{mode: "custom", events: {...}}` per list.
- **Filter chips in News** (#404): *Mentions*, *Comments*, *Assignments*, *New tasks*, *Completed*, *Status*,
  *Agents*, *Sharing*, *Follow-ups* (only the kinds that are there) in the News view and in the bell's dropdown; view
  only, remembered per device.

### Fixed
- The list "+" menu showed *New folder* twice.
- The offline notes ("Changes are sent as soon as the server is reachable") name no host any more.
- The header counts a pill whose own content is cut (the timer's time, the agents' dots) as not fitting and folds one
  level further instead.

## [2.6.0] - 2026-10-01

**In short:** The second usability package: the header always keeps the list title readable plus "…" and the bell, the
agent and timer pills shrink into one status chip when space is short, sharing has its own *Share* dialog, agents that
are not connected say so, "Agents" is the one name for them everywhere, and touch targets, contrast, dates, toasts and a
few texts are tidied up.

### Changed
- **Header with a fixed priority** (K01, K02): on every width the title comes first: it is never cut below its first
  ~12 characters and is shown in full whenever anything else can make room (on a desktop at 1280 and 1920 px also with
  the task panel open). "…" and the bell are always on screen. When space gets short, step by step: the agent pill becomes
  the bot + a number and the timer pill drops the task name; then both merge into one status chip (bot + number, dot +
  time; a tap opens the timer or the agents); then the view switch, field columns, refresh, *Share* and undo / redo move
  into "…"; last, search moves into "…" too. "…" is there on every view (search and the shortcuts where a view has
  nothing of its own). Measured after every render, on resize and once the fonts are loaded.
- **Sharing in its own dialog** (K12): *Share…* in a list's "…" menu, a *Share* button next to the list title (desktop)
  and *Sharing > Share…* in the list dialog open the Share dialog: **People** (roles, *Share with …* + role to invite,
  remove; *What the roles may do* folded), **Agents** (the list's agents with their role, *Share with an agent …*,
  *Stop sharing*, the tidy-up setting), **Public link** (owner) and **Owner** (*Transfer ownership…* / *Take over…*,
  history). The list dialog keeps the list's own settings and shows a one-line summary ("Shared with 2 people · 1 agent").
  Admins without collaboration find *Ownership…* there instead.
- **One term: Agents** (K09): the Settings tab *AI colleague* is now *Agents* (German *Agenten*), its first sub-tab
  *Overview*; "AI usage" is "Agent usage"; texts, the setup guide and the docs follow. The module switch lives only under
  *Settings > Modules*; while the module is off, the Agents tab shows a short hint with *Open Modules*.
- **Agent status** (K08): an agent that never got in touch (no event poll, no API call) or has not for 5 minutes shows
  *not connected* (grey) instead of a green *ready*; its running jobs and its last reported state no longer keep the
  header pill busy (only approvals and unread chat messages do). Webhook agents are unchanged. People's agent lists
  (`/api/state`, `GET /api/agents`, `GET /api/v1/agents`, `GET /api/admin/agents`) carry `webhook` (bool) and
  `contact_age` (seconds since the last poll or API call, `null` = never).
- **Assignee circle only where it means something** (K11): an unassigned task shows the dashed circle only on hover or
  keyboard focus (desktop) and not at all on touch screens; checklists and unassigned subtasks have none. Assigned tasks
  keep their avatar; assigning works as before (click the circle, the task menu, the panel).
- **One date format** (K07): rows, the date column and the task panel all write dates like "Mon, Oct 5" / "Mo, 5. Okt"
  (no more numeric "Mi, 07.10." for the next days), a time after a comma ("Today, 17:30"). The desktop date column
  is wider, cut on the right only, in the normal font, and shows a range as a small range icon with the full range in
  the tooltip.
- **Week view title** (K25): the week's own dates, short enough for one line on a phone: "Sep 28 – Oct 4 · Week 40"
  (the year where it is not this one).
- **Usage card** (K24): the card in the Agents view is a small table with the columns *Today*, *7 days*, *30 days*;
  token counts use one short form in every language ("59.1k" / "59,1 Tsd.", "1.3M" / "1,3 Mio.").
- **Plain words** (K23): settings switched off by the server configuration say "Switched off by the server operator"
  (the variable is in the tooltip) instead of `KALMIDO_UPDATE_CHECK=0` and the like, also for public links, admin
  alerts, the admin topic, the backup passphrase and the agents' log; the refused test alert says the same.

### Fixed
- **Touch targets** (K10): on touch screens the 2.x building blocks reach 44 x 44 px: segment buttons, small buttons,
  icon buttons, the calendar and timeline navigation, the proposal checkboxes and date buttons, the notification matrix
  and settings checkboxes, the agent buttons, the chat; small controls inside rows (assignee, subtask caret, status pill,
  linked tasks) get an invisible 44 px hit area. A new test scans the main views at 390 px and fails on anything smaller
  that is not on its short list of justified exceptions.
- **Contrast** (K17): small texts that used the faint colour (roadmap dates and counts, the palette's type column, chat
  times, group labels in menus and sheets) use the muted colour and meet WCAG AA (4.5:1) in both themes; plain links in
  dialogs use the accent (the dark theme showed the browser's blue at 1.9:1).
- **Toast position** (K18): "Done · Undo" and other toasts sit above the composer, the tab bar and the + button instead
  of on top of them.

Decisions: the Share dialog (K12) came forward from 2.7.0; the agent status counts any API call as contact, not only an
event poll, so an agent that works through tools only is not shown as "not connected" while it is busy.

## [2.5.2] - 2026-10-01

**In short:** A hotfix from the second usability review: on phones the header always keeps "…" and the bell, the
review dialog of a proposal is compact and without stray commas, the first-run tour fits on a laptop screen, and admin
alerts no longer go to the public ntfy.sh unless someone chose it.

### Fixed
- **Header on phones** (K01, minimal form; the full header rework follows in 2.6.0): while an agent is working or a timer
  runs, the agent pill shrinks to the bot with a number and the timer pill to a dot with the time (phones, the Fold cover
  screen and any narrow header, e.g. the Fold inside), so "…" (list menu, view, undo) and the bell always stay on screen.
- **Proposal review** (K03): no more commas between the entries of a "Break down" or "Tasks from notes" proposal; each
  entry is one compact line (checkbox, title, date on the right) with its other fields below, and the footer with the
  count and *Apply* stays visible.
- **First-run tour** (K05): the card is placed with its real height and kept inside the window, so step 5 (*Settings and
  modules*) shows *Back* / *Next* at 1280 x 800 and on every other size.
- **Task panel header** (K06): on phones the checkbox no longer sits on top of the date chip; a long date is shortened
  with "…" (the full date is in the tooltip). On touch screens *Pin* and *Today* / *Tomorrow* are in the task's "…" menu
  and the date picker.
- **Task panel** (K22): no horizontal scroll bar any more (desktop and phone).
- **File picker** (K15): *Data > Import* and *Backups > Restore from a file* use a button in the app's language with the
  chosen file name instead of the browser's "Browse… No file selected.".
- **Plurals and charts** (K16): German "1 Tag" / "1 Woche" (was "1 Tage") and a few more singular forms; the date labels
  of the statistics and usage charts are thinned out so they never overlap.
- **Error text** (K19): opening someone else's proposal (e.g. via its link) explains why instead of showing "unknown".
- **"Ready to start"** (K20) stays on one line in list rows.

### Changed
- **Admin alerts** (K04): they follow each admin's own notification channel. With the public `ntfy.sh` (the default
  `NTFY_URL`) an admin on *Web Push* (the default) gets them on their subscribed devices and none until a device is
  subscribed (they are then only listed in the settings, with a neutral hint and *Subscribe this device*); ntfy only
  for the channels *ntfy* / *Both* or a shared admin topic. With your own ntfy server nothing changes. If you relied on
  admin alerts reaching an ntfy.sh topic while using Web Push: set your channel to *Both* or set an admin topic.
  `GET /api/admin/alerts` lists `topic` (only where it really goes), `devices` and `me` per admin and `ntfy_public`;
  an alert without any destination has the state `listed`. The switch is now called *Admin alerts*.
- **Notification hint** (K04): "No device subscribed for push yet" is a neutral hint instead of a red warning.

Decisions for this release (open questions of the review): on phones the agent pill is an icon with a number; admin
alerts are on by default but only via Web Push to an admin's subscribed device (otherwise nowhere until enabled); the
separate *Share* dialog (K12) moves to 2.6.0.

## [2.5.1] - 2026-10-01

**In short:** Settings > *AI colleague* is tidied up into four sub-tabs instead of one very long page, comment avatars
open the person's card, and suggested branch names are just `kalmido-<id>`.

### Changed
- **AI colleague settings in sub-tabs** (#393): *Agents*, *Lists*, *Usage* and *Log* (admins). Each sub-tab loads only
  when you open it, and the last one is remembered on the device. The default tab is about 200 px high on a desktop
  instead of about 5,900 px for the old single page.
  - *Agents*: one compact card per agent (state and number of lists, today's and this week's usage, a red line only
    for a reached limit or a failing webhook; more details in the tooltip). *Add agent* and *Setup guide* sit side by
    side. The explanation is folded away once an agent exists, and the module switch only shows while the module is
    off (it is always in Settings > Modules).
  - *Lists*: one hint instead of two, one line per agent ("sees 9 of your 25 lists", *Share all*, *New lists
    automatically*). The table first shows only the lists an agent sees, with *Show all (n)*, a search above 10 lists
    and shared lists first. The tidy-up select has short labels, and the tidy agent appears next to it only when tidying
    is on and more than one agent could do it. The heading reads "Which lists they see" when there are several agents.
  - *Usage*: one summary card per agent (today, 7 days, 30 days, and the limit as a bar for admins). The chart, the top 5
    tasks and the per-list and per-model bars are behind *Details*. The chart's date labels no longer overlap.
  - *Log*: 20 requests first, *Load more* adds 50. Event polling (`GET /api/v1/agent/events`, usually most of the
    log) is hidden by default with a switch, a summary line shows today's requests and denied calls (click to filter),
    and task and list names appear where you can see them. On phones the filters sit behind a *Filter* button.
- **Branch suggestion** (#396): the suggested branch name is `kalmido-<id>` without the title part, in the task's
  *Code* section, *Link code…*, the agent events (`repo.branch`), `get_task` and the docs. Branches named
  `kalmido-<id>-…`, `task-<id>-…` and `<id>-…` still link to their task.

### Added
- **Clickable avatars in comments** (#395): a comment author's avatar opens the same card as an @mention (role, open
  tasks, *Assign this task*, *Mention*, an agent's state and chat).
- `GET /api/admin/agents/audit`: `hide_poll=1` leaves out event polling; JSON rows carry `task_title` / `list_name`
  where the admin can see that task or list, and the first page has `today` {`requests`, `denied`, `polls`}. The v1
  audit route is unchanged.

## [2.5.0] - 2026-10-01

**In short:** The first public release of Kalmido, a self-hosted task app for households and small teams: personal
planning, shared projects, time tracking and AI colleagues in one small web app you run yourself, free for any number
of people.

### Added
- **Tasks and lists:** lists with emoji, picture or colour, folders with subfolders, sections as Kanban columns,
  subtasks up to three levels, repeating tasks, reminders, priorities, tags (personal and per list), attachments,
  checklists for shopping and packing, templates, archive instead of delete, undo / redo of the last 30 changes and
  quick capture from anywhere (`q`, Ctrl+Space, a bookmarklet).
- **Views:** Today, *Now doable*, list and Kanban, an Eisenhower matrix (also per folder), a month / week /
  day calendar, a Gantt timeline with dependencies, a roadmap of all projects and statistics.
- **Habits, focus and time:** habits with streaks, a focus timer and stopwatch, time tracking per task with manual
  entries, rates and timesheets (CSV).
- **Together:** unlimited users, shared lists with roles, assignment, comments with @mentions and reactions, an
  activity log, a News inbox, dependencies, project status and progress, custom fields and public read-only or
  tick-off links.
- **Calendars:** subscriptions to Google, iCloud, Outlook or any CalDAV / ICS calendar, and an ICS feed of your tasks.
- **Notifications:** Web Push (also on iOS as an installed app) or ntfy, admin alerts.
- **Sign-in:** built-in login with two-factor authentication (TOTP, recovery codes, passkeys), OpenID Connect, or the
  login of a reverse proxy.
- **Integrations:** a REST API with personal access tokens (`/api/v1`, OpenAPI 3.1), signed webhooks, Paperless-ngx,
  Git hosting (GitHub, Gitea / Forgejo: pull requests, commits, branches per task), import from common task apps and
  ICS / VTODO files, sharing from the phone.
- **AI colleagues:** agents as list members with their own rights, an MCP server ([mcp/](mcp/)), chat, jobs,
  approvals, proposals you review before they apply, tidy-up per list, runtime settings, usage limits, an activity
  log and a setup guide ([docs/AGENT-SETUP.md](docs/AGENT-SETUP.md)).
- **Operations:** automatic, optionally encrypted backups with restore, an update check (GitHub releases), a prebuilt
  multi-arch image (`ghcr.io/gegenschuss/kalmido`, linux/amd64 and linux/arm64), an installable web app that works
  offline, English and German.

<!-- Versions 1.0.0–2.4.2: released before this repository started (history only; no tags here). -->

## [2.4.2] - 2026-09-30

**In short:** Comments can be read newest first, the *Code* section appears only where it helps, @mentions open a small card
about the person or agent, a folder switches between its list and one Eisenhower matrix of all its lists, each agent can
get all your lists (or every new one) in one step after a clear warning, and a setup guide walks you through running an
AI colleague safely, done by Claude Code or by hand.

### Added
- **Comment order** (#386): *Oldest first / Newest first* next to *With activity* in the task panel, saved per person on
  all devices (user setting `comment_order`: `old` | `new`). Newest first reverses the comments and puts the comment box
  right above the newest one instead of the sticky bottom edge, so answering needs no scrolling.
- **Clickable @mentions** (#389): a mention in a comment, and `@Name` or `@username` of a list member in a description, is
  a button (never inside code or links; names nobody has stay plain text). It opens a card with the avatar, the name, the
  role in the list and the person's other open tasks there, plus *Assign this task* and *Mention*; for an agent its live
  state, *Open chat* and *Jobs*. List members in the web state carry `username`.
- **Folder matrix** (#390): a folder view has *List | Matrix* in the header (on a phone *Show as matrix* in "…"); the
  matrix shows the tasks of all lists of the folder, subfolders included, each with its list chip, and *Show as list* /
  the switch lead back.
- **Share with an agent in bulk** (#391): per agent in *Settings > AI colleague*, *Share all existing lists* (every list
  you own with role *Member*; never the inbox or archived lists; lists you stopped sharing with that agent in the table
  stay out until you share them there again) and the switch *Share new lists automatically* (off by default; new lists,
  project types, templates and projects from an agent proposal). Both ask first and say that the agent then sees private
  lists too. API: `GET /api/agents/{id}/share`, `POST /api/agents/{id}/share-all`, `PUT /api/agents/{id}/autoshare {on}`;
  stored per person in the server-only user setting `agent_share`.
- **Setup guide** (#392): *Settings > AI colleague > Setup guide* with two ways: *Let Claude Code set it up* (a prompt
  filled in with this server, you as the only person who instructs the agent, and an editable token file and Linux user;
  one click copies it) and *Do it yourself* (the steps with the key commands). The full guide is the new
  [docs/AGENT-SETUP.md](docs/AGENT-SETUP.md): the agent account and token, a Linux user without sudo, an nftables egress
  firewall, Claude Code, the MCP server behind a wrapper that reads a 0600 env file, a CLAUDE.md template, a
  `.claude/settings.json` allowlist, an event monitor with back-off, autostart with a systemd user unit and
  `mcp/agent_launcher.sh`, the usage hook and a test checklist (mention, chat, kill switch, 7 prompt-injection cases).
  Linked from the README, docs/AGENTS.md and docs/AGENT-SECURITY.md.

### Changed
- **Code section only where it helps** (#387): in lists with a connected repository it shows when the task has linked
  pull requests or commits, is a bug or a feature, or is assigned to an agent; otherwise the task's "…" menu offers
  *Link code…* (copies the branch name). Lists without a repository never show it. Agent events and the API still
  carry `repo` as before.

### Removed
- The *Share a list with an agent…* button in *Settings > AI colleague* (#391): the list table below does the same.

## [2.4.1] - 2026-09-30

**In short:** Admins set how each AI colleague runs (model, auto-compact, a nightly fresh restart, *Reset now*) and
Kalmido hands it to the agent's host; exactly one agent tidies up a list; the chat shows whether the agent is typing,
working on a task, waiting for you or offline; the *Wake* buttons are gone and nothing destructive sits next to *Send*.

### Added
- **Agent runtime settings** (#377): *Settings > AI colleague > (agent) > Runtime*: model (free text with the suggestions
  opus / sonnet / haiku or a full model id, empty = the agent's default), auto-compact on / off with a threshold
  (10-100 %), a nightly fresh restart (HH:MM, server time zone) and *Reset now*. Kalmido only stores them:
  `GET /api/v1/agent` returns `runtime {model, autocompact, autocompact_pct, nightly_reset, reset_seq, timezone}`, a
  change sends the event `runtime_changed`, *Reset now* raises `reset_seq` and sends `reset`
  (`POST /api/admin/agents/{id}/reset`, `PATCH /api/admin/agents/{id} {runtime}`); MCP `get_agent` includes it. The
  host contract is in docs/AGENTS.md (*Runtime settings*), with a reference launcher for Claude Code,
  `mcp/agent_launcher.sh` (`--model`, `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` / `DISABLE_AUTO_COMPACT`, always a fresh
  session, restarts on a change, on *Reset now* and nightly; a systemd unit recipe).
- **Agent status in the chat** (#375): the chat header shows typing dots while the agent writes to you and its state in
  words: *working on #51* (a link to the task), *working*, *waiting for you*, *ready*, *paused*, *limit reached*,
  *offline* (no event poll for 5 minutes; stored at most every 30 seconds). New `POST /api/v1/agent/typing
  {chat_user_id}` (10 seconds, the answer ends it; MCP `chat_typing`); the agent objects carry `online`,
  `last_poll_at`, `poll_age`, `typing` and `my_job`.

### Changed
- **One tidy agent per list** (#379): *Tidy up by* in the list dialog and in the *AI colleague* list table picks the
  one agent (with edit rights) that tidies up a list; only it gets `tidy` events, another agent's suggestion or
  `POST /api/v1/tasks/{id}/tidy` is refused (`403`). Default: the first agent with edit rights; lists that had tidy on
  keep the agent that got their events first (one-time migration). API / MCP / events: `tidy_agent_id`
  (`PATCH /api/lists/{id} {tidy_agent_id}`).
- **Task panel footer** (#385): *Delete* and *Track time* moved from the footer (on a phone *Delete* sat right below the
  comment box's *Send*) into the task's *…* menu (*Delete* with undo); a running timer still shows there as its pill.
- Neutral wording (#384): code comments, the README and the changelog describe what Kalmido does without naming other
  apps (the importers keep their names).

### Removed
- **Wake agent** buttons (#376) in the task panel, the Agents view and the chat. `POST /api/tasks/{id}/wake` and
  `POST /api/agents/{id}/wake` stay, documented for agents without an event loop.

## [2.4.0] - 2026-09-30

**In short:** Folders get subfolders, new projects start from a type (Agency, Software / AI dev, Personal) or from your
own project template with dates counted from the project start, software projects get bug / feature / task tickets,
and anything can be captured into the inbox from anywhere: `q`, Ctrl+Space, the app icon menu or a bookmarklet.

### Added
- **Subfolders** (#361): a folder path of at most two levels (`Clients/Company X`), per person as before (owner row,
  member row, the order in the setting `folders`). Sidebar tree (a folder's lists, then its subfolders), folded folders
  in the new user setting `folders_closed` (all devices), drag and drop of lists into subfolders and of subfolders into
  other folders or to the top level, folder menu *New subfolder…* / *Move into a folder…* / *Move to the top level*;
  deleting a folder moves its lists and subfolders up one level. The folder view shows the lists of the subfolders too,
  with a header per subfolder; the command palette lists folders; the list dialog takes `Folder / Subfolder`. API v1:
  `folder` is the path; deeper paths are refused (`400`).
- **Project types** (#243): *Agency* (sections Request / Concept / Production / Approval / Billing, fields Client and
  Budget h, time tracking), *Software / AI dev* (Backlog / Next / In progress / Review / Done, Kanban, ticket types,
  dependencies, a next-steps dialog for the repository and a coding agent), *Personal* (Ideas / Planning / To do). Names
  in the person's language; the modules a type needs are switched on (`modules_on`). In the new list dialog, the command
  palette (*New project…*), the setup (*Start with a project*) and the first welcome card. `POST /api/lists {ptype}`,
  `POST /api/v1/lists {project_type}`.
- **Project templates with relative dates** (#328): saving a project list keeps its dates as days after the project
  start, its dependencies (node keys), ticket types and *Move dependent tasks along*; using it asks for the start and
  an optional end (`POST /api/templates/{id}/apply {start, end}`: the dates are stretched or squeezed to fit).
- **Ticket types** (#340): per list (`tickets`, owner), a task `ttype` / API `type` bug | feature | task with an icon
  chip, a select in the task panel, quick add `!bug` / `!feature` / `!task` (`!fehler` / `!funktion` / `!aufgabe`), a
  filter, `GET /api/v1/tasks?type=`, MCP `type`, `type` in agent events and webhooks. New bugs / features with empty
  notes get the list's template (`ticket_tpl`, editable) or the built-in one in the person's language.
- **Quick capture** (#187): `q` / Ctrl+Space open a capture box anywhere (inbox unless a list is named), the app shortcut
  *Quick add* (`/?action=capture`), and `/capture`: a bookmarklet popup that saves the page title and address into the
  inbox with the normal session (the page stays through a sign-in), plus how to bind a system-wide key.

### Changed
- A `/` in an existing folder name now means a subfolder: existing names with a slash are kept as they were (the slash
  becomes the look-alike `∕`, once, for every person's folders); imported folder names likewise.
- List templates keep the dependencies between their tasks (also the ones without relative dates).

## [2.3.0] - 2026-09-30

**In short:** Ask an AI colleague for a proposal instead of letting it create things on its own: a whole project from a
briefing, subtasks for a big task, a sorted inbox, or tasks (with assignees) from meeting notes. The agent gets exactly
what you send, answers with one structured proposal, and you tick, edit and apply it: everything belongs to you and one
undo takes it back.

### Added
- **Agent proposals** (shared by #260-#263): a person asks an agent from the app; Kalmido creates a job (kind `project`,
  `subtasks`, `triage` or `extract`, shown in the Agents view) and sends the event `job_request` with exactly the input of
  the request dialog. The agent answers with `POST /api/v1/agent/jobs/{id}/proposal` (MCP `submit_proposal`, new
  `get_job`): validated per kind (at most 200 entries, 256 KB, text lengths, ids only from the input, no dependency
  cycles; `400` with the reason, `unknown_field`, `413`). The person gets a News item and a push *Proposal ready* (new
  notification row, on by default) and reviews it in a dialog (from the push, the News item or the job): a checkbox per
  entry (a task's subtasks follow it), inline title / date / section / assignee / list, *Apply n entries* or *Discard*.
  Applying creates / changes everything as the person (owner, creator, history *created the task from a proposal by
  <agent>*), one undo / redo step (`POST /api/proposals/{id}/undo` / `redo`: a new project list nobody touched is
  removed, changed entries stay and are named). The agent gets a `job` event (`approve` with the counts, or `reject`).
- **Who may ask which agent**: per agent *Proposals for* (Settings > AI colleague): people who share a list with it
  (default; instance admins count as sharing), everyone, or nobody. At most 10 open requests per person.
- **#260 Project from a briefing**: *New project from briefing…* (Lists > +, command palette): pasted text or a .txt /
  .md file (PDF: not yet), optional folder; the proposal brings sections, tasks with dates, priorities, subtasks and
  dependencies; applied as a new project list owned by the person, optionally shared with the agent.
- **#261 Break down a task**: *Break down with <agent>…* in the task menu and the palette, with an optional hint; the
  agent sees the task's title, notes and subtask titles; subtasks with dates, estimates (duration) and dependencies.
- **#262 Sort the inbox**: select inbox items (bot button in the selection bar) or *Sort the inbox with <agent>…* (all
  open inbox items, at most 100); the person ticks which of their lists the agent may suggest (default all). Per item:
  list, section, tags, priority, date, a better title.
- **#263 Tasks from notes**: *Tasks from notes…* in a list's menu and the palette; the agent gets the notes and the
  names of the list's people and proposes tasks with assignees, dates and sections (a new section is created on apply).
- `GET /api/v1/agent/jobs/{id}`; jobs carry `kind` and `proposal_state`.

### Privacy
- An agent never gets access to the inbox or unshared lists through a proposal: the input is exactly what the person
  sent, stored with the job and removed with it after 30 days (also when the person is deleted). Only the person who
  asked sees the proposal.

### Changed
- Service worker cache v65.

## [2.2.1] - 2026-09-30

**In short:** Admins see every API call an AI colleague makes in an activity log (route, status, duration; never
content), with filters, denied calls marked and a CSV export. The REST API now names unknown JSON fields instead of
ignoring them, and a new guide, docs/AGENT-SECURITY.md, explains how to run an agent safely: threat model, host sandbox
recipe and the prompt-injection checklist we tested with.

### Added
- **Agent audit log** (#358): every request made with an agent's token (REST API, agent endpoints, MCP calls) is one row
  in the new table `agent_audit`: time, agent, method, route template (`/api/v1/tasks/{tid}`), status, task / list id
  from the path or the body, duration. Never bodies or query values. Denied calls (401 / 403 / 429: paused agent, scope,
  rate or usage limit) are logged and marked. Requests only queue the row in memory, a writer thread stores batches every
  2 s (cheap on a Pi). Retention `KALMIDO_AUDIT_DAYS` (default 90, `0` = off), removed hourly.
- **Settings > AI colleague > Activity log** (admins): newest first, filter by agent, status class (2xx / 4xx / 5xx /
  *Denied*) and day (the app's date picker), *Load more*, CSV export of everything that matches; phone layout with the
  route on its own line. Non-admins see nothing of it.
- **API**: `GET /api/admin/agents/audit` (all agents) and `GET /api/admin/agents/{id}/audit` (admin session; `status`,
  `day`, `before`, `limit`, `format=csv`), `GET /api/v1/admin/agents/{id}/audit` (scope *admin-read*, cursor pages; in
  the OpenAPI spec as `AuditPage`).
- **docs/AGENT-SECURITY.md** (#357): threat model, what Kalmido enforces, a host sandbox recipe for Claude Code (own
  user, nftables egress rule by user id, token in a 0600 env file behind a wrapper, `dontAsk` permissions, CLAUDE.md rules
  template, back-off in the event loop), the 7-case prompt-injection checklist with OS and kill-switch checks, and our
  results. Linked from SECURITY.md, docs/AGENTS.md and the README.

### Changed
- **Unknown fields** (#359): the REST API answers unknown JSON fields with `400` and
  `{"error": {"code": "unknown_field", "message", "fields": [...]}}` everywhere it refused them before with a plain
  `invalid`; comments with extra fields now get `unknown_field` too (before: *Expected {"body": "..."}*). `content` is
  accepted as an alias of `notes` on task create / update (both with different values: 400). The web API (`/api`, the
  app's own) stays lenient but names ignored fields in the response header `X-Kalmido-Unknown-Fields` and logs one
  warning per endpoint and set of names per hour (never values); it accepts `notes` as an alias of `content`.
  **Compatibility:** a v1 client that sent junk fields to an endpoint that refused them already gets the same 400 with a
  new `code`; clients that check `code == "invalid"` for these cases should also accept `unknown_field`.
- `POST /api/lists` takes `dep_shift` (*Move dependent tasks along*) at creation (before, only `PATCH` set it).
- CI: the test suites run in 3 parallel shards (`tests/run_all.sh --shard N/3`), each well under 25 minutes; the
  overall result still needs all of them.
- Service worker cache v64.

## [2.2.0] - 2026-09-30

**In short:** Project lists meet GitHub and Gitea / Forgejo: connect a repository and the pull requests (with CI),
commits and branches show up at their tasks, `fixes #123` in a merged pull request completes the task. It works by
polling, so a server behind a VPN or in the office LAN needs no public address. And tickets can go to a coding agent: it
gets the repository and a branch name with the assignment and merges only after a person's 👍 on its *Ready to merge*.

### Added
- **Git integration** (#271, *Edit list > Repository*, project lists): the list owner and list admins connect up to five
  repositories: GitHub (github.com or GitHub Enterprise) and Gitea / Forgejo, as `owner/name` or the repository's
  address; the repository is read at once, so a wrong name or token shows in the dialog. The access token (read-only is
  enough, optional for public repositories) is write-only and encrypted with `KALMIDO_SECRET_KEY` like the Paperless
  tokens of 2.1.0; without the key only tokenless repositories can be connected. Agents cannot connect repositories or
  see tokens. Everyone in the list sees the results; *Check now* for everyone, token / webhook / remove for owner and
  admins.
- **Polling** in a background thread (every 180 s per repository, `KALMIDO_GIT_POLL`; a few repositories per tick):
  the newest 30 pull requests, the newest 30 commits of the default branch, the own commits of up to 3 branches of open
  pull requests (compare with the default branch) and the CI of up to 5 open pull request heads (combined status +
  GitHub check runs). ETag / `If-None-Match` (a `304` costs GitHub no rate limit), a pause until the reset when fewer
  than 25 requests are left or on `403` / `429` rate limits, back-off on errors (interval × 2^failures, at most an
  hour), no redirects, the SSRF guard of calendar subscriptions (internal servers only on the admin allow-list).
- **Matching** (tasks of the connected list only): `#<id>` in a commit message, pull request title or description;
  branches `kalmido-<id>…`, `task-<id>…`, `<id>-slug` (the last path segment). Only linked pull requests / commits are
  stored (new tables `git_conns`, `git_prs`, `git_commits`, `git_links`, `git_closes`).
- **Task panel > Code** (after the fields, before the comments): linked pull requests (state, title, author, CI icon,
  link) and the latest commits (short sha, message), a button that copies the branch name `kalmido-<id>-<slug>`, *<agent>
  is working on it* while an assigned agent works on the task. **Row chip** with the pull request and its CI. History
  lines when a linked pull request is opened, merged or closed (not for what already existed at the first check).
- **Keywords:** `fixes` / `closes` / `resolves #<id>` (also fix, fixed, close, closed, resolve, resolved and German
  `erledigt`) in a merged pull request or a default-branch commit complete the task, once per task, only for changes
  after the connection; the history names the pull request / commit and offers *Undo* (`POST /api/tasks/{id}/git-undo`).
- **Optional inbound webhook** per repository (off by default): `POST /api/hooks/git/<id>`, signed with a per-repository
  secret (shown once, sealed) as `X-Hub-Signature-256` (GitHub) or `X-Gitea-Signature` / `X-Forgejo-Signature`; it
  only triggers the next check at once, its body is not used.
- **Hand a ticket to a coding agent** (#339): task events and `get_task` in a connected list carry `repo` (provider,
  web / API address, owner / name, default branch, a suggested branch, the linked pull requests with CI and commits).
  An agent's comment with `suggestion: {kind: "merge_request", pr_url, summary}` (only agents, only pull requests of a
  connected repository; the pull request is linked at once) shows as *Ready to merge* with the pull request, CI and
  *Approve* / *Reject* for approvers (list owner, list admins, the assignee, admins). 👍 / 👎 by an approver sets it
  approved / rejected once and sends the agent the `reaction` event with `approval` and `merge_request`; *Apply* is
  refused. Kalmido never merges: the agent does, with its own credentials.
- **API:** `GET /api/v1/lists/{id}/repos`, lists carry `repos`, `GET /api/v1/tasks/{id}` carries `code` and `repo`, tasks
  carry `code`; OpenAPI (`Repo`, `Code`, `MergeRequestInput`). Web app: `GET` / `POST /api/lists/{id}/repos`,
  `PATCH` / `DELETE /api/repos/{id}`, `POST /api/repos/{id}/refresh`; the timeline carries `approver`.
- **MCP** 2.2.0: `list_repos`, `request_merge_approval`; `get_task` documents `code` / `repo`.
- **Docs:** README *Git integration*, docs/AGENTS.md *Coding agent workflow* with a sample `CLAUDE.md` for a project
  agent, docs/API.md, mcp/README.md.
- **Tests:** `p220_api_test.py`, `p220_ui.js` against a fake GitHub + Gitea inside the test container (`fake_git.py`).

### Changed
- Service worker cache v63.

## [2.1.2] - 2026-09-30

**In short:** Lists can change hands: the owner transfers a list to another person and stays in it as a list admin, and
admins take over lists whose owner is an agent or a disabled user, which nobody could manage before. Agents get an
editable username and profile picture and appear in the user list.

### Added
- **Transfer ownership** (#349, *Edit list > Sharing > Transfer ownership…*, with a confirmation): the owner hands the
  list to another active person, a member or anyone they could share with. The old owner becomes a member with the role
  *Admin* (an agent: *Member*, agents are never list admins) and keeps the list where it was in their sidebar; the new
  owner's member row goes, they keep its folder, place and view (not a member before: the end of their sidebar, top
  level) and get a News item (*… made you the owner of the list …*, event *Lists shared with me*). Agents never become
  owners and never transfer; inboxes are never transferred (409).
- **Admin takeover** (#349): instance admins take over a list whose owner is an agent or a disabled user, for
  themselves or another person: *Settings > Administration > Lists owned by agents or disabled users > Take over*, and
  *Take over…* in the list dialog. A non-admin cannot; an admin cannot take a list of an active person.
- **History** of a list's ownership (new table `list_activity`), shown under *Sharing*: *Ownership transferred from X to Y*.
- **API:** `GET /api/lists/{id}/owner` (owner, whether you may transfer / take over, the candidates, the history),
  `POST /api/lists/{id}/owner` and `POST /api/v1/lists/{id}/owner` with `{user_id}` (scope write; agent tokens always
  403), `GET /api/admin/lists/orphaned` (admins).
- **Agents** (#346): admins change an agent's username (checked, unique; its tokens keep working) and profile picture
  (presets, an own photo, `POST /api/admin/agents/{id}/avatar`, or none) in its dialog (*Settings > AI colleague*);
  `PATCH /api/admin/agents/{id}` takes `username` and `avatar_preset`.

### Changed
- *Settings > Administration > Users* lists agents too, with the *Agent* badge and *Managed under AI colleague*, which
  opens the agent dialog instead of the user dialog.
- Service worker cache v62.

## [2.1.1] - 2026-09-30

**In short:** Agents report their model usage (tokens, optionally the cost) and you see it per agent, day, task, list
and model in *Settings > AI colleague > Usage*, as a card in the Agents view and on the task. Admins can give each agent a
soft limit (News + push at 80 % and 100 %) and a hard limit that pauses its API calls until the next day or month. A
Claude Code hook reports a session's usage by itself.

### Added
- **Usage reports** (#326): `POST /api/v1/agent/usage` (agent tokens only) with model, input / output / cache tokens,
  optional cost in USD, the task / list / job it was for and a short note (at most 200 characters). Only numbers and ids
  are stored, never prompt content. `GET /api/v1/agent/usage?from=&to=&group=day|task|list|model` for the agent itself.
  MCP tools `report_usage` and `get_usage`. "Tokens" = input + output + cache writes; cache reads are listed apart.
- **Usage dashboard** (#326, *Settings > AI colleague > Usage*): today / 7 days / 30 days per agent, the last 30 days as
  a chart, top tasks (click opens the task), per list and per model, in tokens or cost (when reported), for all agents or
  one. Admins see every agent; everyone else sees the agents they share a list with, counted only in the lists they see
  (participants: their tasks); what the viewer cannot see is counted without a name. A compact card in the **Agents**
  view, and an *AI usage* line in the task panel on tasks with reports.
- **Usage limits per agent** (#326, admins, agent dialog; default none): per day or month, in tokens or USD. The soft
  limit sends the admins a News item and a push at 80 % and 100 % (once per period; new notification event *An agent
  reached a usage limit*, admins only). The hard limit tells them too and then answers every API call of the agent with
  `429`, a clear message and `Retry-After`, except reporting usage, the status and `GET /agent`, until the period rolls
  over or an admin raises it; the agent shows *limit reached*. `GET /api/v1/agent` has `usage_limit`.
- **Claude Code usage hook** (`mcp/claude_usage_hook.py`): a Stop hook that sums the usage of a session's new assistant
  messages from its transcript (state per session, one report per model, optional cost from a price table, the task of
  the agent's status) and reports it; it never blocks the session. Setup in docs/AGENTS.md.

### Changed
- The MCP server reports version 2.1.1 and accepts numbers (not only integers) for number arguments.
- CI also runs the usage hook test in the quick checks job; service worker cache v61.

## [2.1.0] - 2026-09-30

**In short:** One table decides what notifies you (every event as News, as a push, both or neither), and every list
gets its own bell (*All activity*, *Default*, *Mute*). Paperless can have several connections: server ones where each
person enters their own token, and private ones only their owner sees, with tokens that are write-only and encrypted.
Tasks can wait on someone outside with a follow-up day that reminds you, and tells your AI colleague.

### Added
- **Notification settings** (#317, *Settings > Notifications > What notifies you*): a matrix of events x *News* /
  *Push*. Events: comments on my tasks (created or assigned), **replies to my comment** (the comment right before is
  mine, new), comments on tasks I follow (I commented on them), mentions, assignments, **new tasks in shared lists**
  (created by someone else, new), completions by others, project status, shared lists, unblocked tasks, **an agent
  waiting for my approval** (News new), the **follow-up day** (below) and reminders (push only). A comment counts once,
  as the first of mention, my task, reply, follow. The defaults keep the behaviour of 2.0.8 exactly (existing News
  choices included); of the new ones only replies and follow-ups are on. Pushes for project status and shared lists
  are new (off by default). News and pushes are filtered in one place on the server. The old setting `news_kinds`
  stays the News column of the events it knew; the rest is the setting `notify`.
- **A bell per list** (#317, list menu > *Notifications*, list dialog), only for me: *All activity* (every comment, new
  task and change of that list as News and push), *Default* (the matrix) or *Mute* (only mentions of me and tasks
  assigned to me come through, following the matrix). Reminders and follow-ups are never muted. A muted list shows a
  crossed-out bell in the sidebar. `PUT /api/lists/{id}/bell`; lists carry `bell`.
- **API:** `GET /api/v1/me` has `notifications` (`events`, `lists`); `PATCH /api/v1/me/notifications` changes them.
- **Several Paperless connections** (#180). The connection from the environment keeps working unchanged (legacy,
  *Paperless access*). New:
  - *Server connections* (admins, *Settings > Users > Paperless connections*): name + address, **no shared token**,
    and who may use it; every such user enters their own API token (*Settings > Integrations*), so Paperless'
    permissions apply per person. A new address deletes the stored tokens, taking someone off deletes theirs.
  - *Personal connections* (*Settings > Integrations > Add my own connection*): name, address, token; only the owner
    sees and uses them. Admins can neither see nor grant them; no API answer shows them to anyone else.
  - Tokens are **write-only** (only "•••• set" is ever shown) and **encrypted at rest** (AES-GCM) with the new
    environment variable `KALMIDO_SECRET_KEY` (32 random bytes, base64), which never goes into the database or a
    backup. Without it no token can be stored (409 with a hint; the admin settings say so). **Losing the key means
    everyone enters their tokens again.**
  - Personal connections go through the SSRF guard of the calendar subscriptions (public addresses, internal hosts only
    on the admin's allow-list); no Paperless request follows a redirect, so a token only reaches its own address.
  - Linking and *Send to Paperless* ask for the connection when there is more than one. Links remember it (links from
    before 2.1.0 belong to the environment connection); people who cannot use it see "Paperless document" only, in the
    task, its history and the JSON export. The export lists my own connections without tokens.
- **Waiting on external** (#335, German *Warten auf Extern*): task menu > *Waiting on external…* with a note (who /
  what) and a follow-up day. An hourglass chip on the row, a bar in the task panel (one click ends it, with undo), the
  smart view *Waiting on external* in the sidebar while there are such tasks. On the follow-up day (at the all-day
  reminder time) the person it is for gets a push *Follow up* and a News item, and every agent that follows the task
  the new event **`followup_due`**. API: `PUT` / `DELETE /api/v1/tasks/{id}/waiting`, `GET /api/v1/tasks?waiting=true`,
  `waiting` on every task; MCP `set_waiting`, `clear_waiting`, `list_waiting` (and `list_tasks` `waiting`).

### Changed
- *Settings > Notifications > News* (the checkboxes of 1.9.0) became the News column of the matrix.
- Service worker cache v60.

### Upgrading
- Nothing is required. To use server or personal Paperless connections, set `KALMIDO_SECRET_KEY` (see `.env.example`)
  and keep a copy of it somewhere safe.

## [2.0.8] - 2026-09-30

**In short:** Sort any view by *Created*, answer a comment straight from its notification, see and change which agent
sees which of your lists (and its tidy mode) in one table, pick values on a phone from app-style sheets instead of the
system dropdowns, a sloth in the Android notification badge, and agents that need fewer API calls.

### Added
- **Sort: Created** (#319, German *Erstellt*) in the sort menu of every view, *All* included: newest first; picked
  again while it is on, oldest first (the item says which). While it is on, the rows show the day each task was created.
  Stored per view like the other sort modes; a manual drag switches back to *Priority, then manual*.
- **Reply on comment pushes** (#331, German *Antworten*): a comment or mention notification carries *Reply* (opens the
  task with the comment box focused; on a phone with the Details / Comments tabs, the Comments tab) and *Done*
  (completes it in the background, like the reminder's button); a completed task gets *Reply* alone, the summary of a
  burst of comments gets both. Reminders keep *Done* + *Snooze*; at most two buttons, since some platforms show no more.
  The link `#reply/<id>` works on its own too.
- **Settings > AI colleague: your lists at a glance** (#321): every list you manage in one table. *Agent sees it*: one
  chip per agent, a click shares the list with it (role Member) or, after a confirm, ends the sharing. *Tidy up*: off,
  suggest or automatic, the same setting as in the list dialog, where an agent is in the list.
- **Agent API** (#333, asked for by an agent): task events (`mention`, `comment`, `assigned`, `tidy`, `reaction`, `wake`
  with a task) carry the task's newest 20 comments (`task.comments`, oldest first, texts over 2,000 characters cut,
  `task.comments_total`) and the list's sections and `agent_tidy` (`list.sections`, `list.agent_tidy`), so an agent
  needs no `get_task` / `list_lists` round trip. `GET /api/v1/lists` (and MCP `list_lists`) include every list's
  sections `[{id, name}]`. `GET /api/v1/tasks?fields=compact` returns only id, title, list, section, parent, status,
  due, priority, tags, list tags and assignee; MCP `list_tasks` has `compact` (not given: pages of more than 25 tasks
  come back compact). Everything is additive; old clients keep working.

### Changed
- **Pickers on phones** (#323): a `<select>` opens an app-style bottom sheet like the app's menus: the field's name on
  top, the options with their emoji, icon or avatar, a check on the current value, a search field above 10 options,
  arrow keys / Home / End / Enter / Esc. One enhancer covers the task panel (list, section, assignee), the dialogs and
  the settings. It stays the native select on the desktop, for `multiple` / sized / disabled selects and those with
  fewer than two options, inside a popover or sheet itself (e.g. the date picker's repeat and duration) and wherever
  `data-native` is set.
- **Agent chat on a phone** (#320): sending a message closes the keyboard, so the answer gets the screen; the desktop
  keeps the focus in the box, and a message that could not be sent keeps it everywhere.
- **Notification badge** (#325, `static/badge-96.png`, Android's small status-bar icon): the check with the hanging
  sloth of the app icon as a white silhouette, simplified to read at 24 dp.
- Service worker cache v59.

### Fixed
- `mcp/README.md` still sent admins to *Settings > Administration > Agents*; agents live in *Settings > AI colleague*
  since 2.0.5. `list_lists` promised sections that `GET /api/v1/lists` did not return until now.

## [2.0.7] - 2026-09-29

### Fixed

- Private lists (with collaboration on) show the folded **History** of a task again, as up to 2.0.5: every change,
  your own included, for example "imported the task from Todoist". It stays separate from the comments, so personal
  notes still have no activity lines between them.
- Tests: the new users' `features_rev` is 9 since 2.0.6 (the *Comments* module), and the migration test checks that a
  user already on revision 9 who switched comments off keeps them off.

## [2.0.6] - 2026-09-29

**In short:** Comments are for everyone now, as personal notes in private lists too, with their own *Comments*
module; they sit at the end of the task panel with the comment box always at the bottom edge. The desktop rail shows
exactly your tab bar, *No date* reaches the roadmap and the calendar timeline, focus sessions and the stopwatch get a
card, and the calendar and multi-select have keyboard shortcuts.

### Added
- **Comments as personal notes** (#315): comments no longer need collaboration or a shared list. In private lists and
  with collaboration off they are timestamped notes: no @mentions, no News, no pushes, no history of your own changes
  (changes others made, e.g. through the API or a public link, still show). Old comments of lists that are no longer
  shared are normal and editable again. Checklists have no comments.
- **Module *Comments*** (German *Kommentare*) in *Settings > Modules* and in the setup, on by default (also for
  existing accounts). Off: no comment UI anywhere (the comments stay stored), new comments are refused (409, also
  `POST /api/v1/tasks/{id}/comments`), no comment News or pushes for you. With collaboration on and comments off,
  sharing, assigning, the history and the other News keep working. `GET /api/v1/me` reports `features.comments`.
- **"No date" in the roadmap and the calendar timeline** (#189): in an open list of the roadmap a folding group
  *No date* with one row per undated task; click a day to give it a due date, drag for a range (touch: tap, hold and
  drag). A *No date* chip switches it (on by default, stored with the roadmap settings). The calendar's timeline gets
  the *No date* switch with the count in its bar.
- **Focus session and stopwatch as a card** (#190) on the time page, like the time-tracking timer: live time, task,
  list, start, planned minutes, Pause / Resume, Stop and a link to *Focus*; both cards when a timer runs too.
- **Keyboard shortcuts** (#191): calendar `1` month, `2` week, `3` day, `4` timeline, `←` / `→` previous / next,
  `.` today; multi-select Ctrl/Cmd+A selects every task of the view, Shift+↓ / Shift+↑ (or Shift+J / K) extend the
  selection, Shift+X toggles the focused task, then Space / X completes, M moves, D changes the date of the selection,
  Esc clears it. All in the `?` overview.

### Changed
- **Task panel reordered** (#316, #322): description, subtasks, dependencies, tags, attachments, Paperless, the
  fields (list, section, link, assignee, agent), custom fields, time, and the comments with the history at the end. The
  comment box sits at the bottom edge of the panel (desktop and phone) and stays visible while you scroll; one line
  until you use it. Comments are no longer folded to the newest one (2.0.2 / 2.0.3): all show, oldest first; opened
  from a comment (News, a push), the panel scrolls to the newest.
- **The desktop rail follows the tab bar setting** (#314): exactly its items in their order, then every switched-on
  module that is not in it; search and settings at the bottom unless you placed them. Statistics, time tracking,
  overview, agents, search and settings are no longer hidden in the rail and no longer repeated in the desktop
  sidebar, which keeps lists, folders, filters, tags and All / Completed / Trash. The phone drawer and tab bar are
  unchanged. *Agents* can be added to the tab bar.
- **Tablets in portrait** (#188, under 900 px wide but at least 600 × 600): the composer at the bottom of the list,
  right above the tab bar, instead of the "+" button; "N" focuses it. Phones keep the "+".

### Fixed
- **"Share a list with an agent…"** (#318) in *Settings > AI colleague* did nothing: the list menu opened behind the
  settings dialog. Menus opened inside a dialog now show above it (phone and desktop).
- Tests: the harness ignores a late rejection after a window was closed only when it is exactly that (a TypeError from
  the closed window's own scripts), no longer every app error (CI showed `loadJobs()` → `renderView()` in p200_ui).

## [2.0.5] - 2026-09-29

**In short:** Admins can empty the trash of shared lists they work in, notifications handled on one device disappear
from the others, and the AI colleague (agents) gets its own settings tab.

### Added
- **Settings > AI colleague** (German *KI-Kollege*). Everything about agents in one tab: what an agent is and how to
  connect one, the *Agents* module switch (the same switch as in *Modules*, both stay in step), which lists an agent
  sees (exactly the lists shared with it) with a *Share a list with an agent…* button that opens the list dialog at
  *Sharing*, and the agents themselves. Admins add, edit, test and pause agents here (moved from *Administration*);
  everyone else sees the status of the agents that work in their lists. Also in the command palette.
- **Notifications close on your other devices.** When you complete a task, open it or read its News item on one
  device, its notification disappears from your other phones and computers. Android and desktop browsers get a short,
  rate-limited "close" push (only for notifications that were really sent there); on iPhone and iPad (Apple does not
  allow such silent pushes) the handled notifications are closed with the next notification that arrives.

### Changed
- **Emptying the trash as an admin.** Instance admins now also delete for good what is in the trash of shared lists
  of other owners where they may edit (for example lists of an agent). For everyone else the owner rule stays: those
  items remain in the trash, the trash marks them (*stays*) and says how many stay; after *Empty* a message tells how
  many items were left and why. `DELETE /api/trash` answers `{deleted, kept}`.

## [2.0.4] - 2026-09-29

**In short:** The Flow marker "Next" becomes *Ready to start*, appears only where tasks actually wait on each other
and explains itself on a tap; the project status picker shows every status in its colour.

### Changed
- **Flow: *Ready to start* instead of *Next*** (German *Startklar*). The marker on the first task of a section that
  waits on nothing now shows only when at least one open task in the view has a dependency (*Waiting on*, inside or
  outside the view); in lists without dependencies the Flow order stays the same, just without a marker. Tap or click
  the marker (also on phones, also with the keyboard) for a short explanation: it waits on nothing open and is the
  first task in the flow order (dependencies, then date, then priority). The tap does not open or tick the task.

### Fixed
- **Project status picker: status colours.** The options in the *Project status* dialog showed grey dots; each one
  now has the colour of its status pill (light and dark theme).

## [2.0.3] - 2026-09-29

**In short:** The iPhone home-screen app no longer leaves an empty band under the tab bar, the comment box stays
visible when the comments are folded, and News can show only the unread items.

### Added
- **News: *Unread only*** next to *All | Mentions & assigned to me*: hides the items you have already read (one you
  just opened stays until the next reload); remembered per device, combines with the filter.

### Changed
- **Folded comments keep the comment box**: folding hides only the older comments; the newest one and the box right
  below it stay visible, so you can answer without unfolding. A draft no longer unfolds the list.

### Fixed
- **iPhone home-screen app: empty band under the tab bar** (a gap the height of the status bar). The status bar is now
  plain black (`apple-mobile-web-app-status-bar-style` `black` instead of `black-translucent`), so iOS gives the page
  the full height below it. The 2.0.2 workaround that moved the tab bar down is gone (it pushed the bar partly out of
  the screen). On phones, the area outside the page has the tab bar colour; `theme-color` and the manifest colours
  match the tab bar. **Already installed on the home screen?** Reload the app; if the band stays, remove the icon and
  add it again from Safari.

## [2.0.2] - 2026-09-29

**In short:** Comments move right below the description, titles are edited in the list, lists get their own
pictures, sections a "+", and you see when an agent is writing. Plus fixes for the iPhone home-screen app, dragging in
long lists and the phone share setup.

### Added
- **Comments right below the description**, folded to the newest one: the bar *Comments (n)* shows all of them with
  one click (newest at the bottom, the box below); the choice is remembered per device. Long descriptions fold after
  about eight lines (*Show more*). Phones get *Details | Comments* at the top of the task panel.
- **Edit a title right in the list**: double-click it (computer) or press **E** on the focused row; Enter saves (one
  undo step), Esc cancels.
- **Keyboard**: arrow keys move through the list (J / K as before), **Space** completes, **Enter** opens, a clearer
  focus ring; the shortcut help (?) shows the new keys.
- **Recently viewed**: the last five tasks and lists you opened are at the top of the command palette (Ctrl/Cmd+K).
- **Own list icons**: a picture instead of the emoji, from presets (the Kalmido icon, the sloths) or uploaded
  (cropped square, re-encoded without metadata, like the profile pictures). Shown in the sidebar, the header, the tab
  bar, the palette and list groups. Emojis still work; picking one replaces the picture and the other way round.
  API: `PUT / POST / DELETE /api/lists/{id}/icon`, `icon` in the list (also in `/api/v1`).
- **"+" on every section header** (computer: on hover, touch: always): an input right in the section, Enter adds the
  task there (quick-add syntax works) and stays open for the next one.
- **Collapse all / Expand all** (sections and subtasks) in the list's *…* menu and with **Shift+C**, remembered per
  device.
- **"Claude is writing …"**: while an agent reports *working*, a typing indicator with its status text shows under
  the last chat message and in the comment area of the task it works on. Everywhere, the agent chip in the top bar
  and the Agents button (rail, tab bar) get a spinning ring; while an agent waits for you, an accent dot. The chip's
  tooltip / menu names the agent and what it does. Agents can name the task: `PUT /api/v1/agent/status
  {"status": "working", "task_id": 51}` (MCP `set_status` too); `GET /api/v1/agent` and `/api/agents` report
  `status_task` and `job_tasks`.
- *Share from your phone*: **New token** right there, with a note on what to update afterwards (iPhone shortcut,
  HTTP Shortcuts import).

### Changed
- *Share from your phone* offers the **server address without `/drop`** for the iPhone shortcut (it adds `/drop`
  itself); the guide says so.

### Fixed
- iPhone / iPad home-screen app: a large empty band below the tab bar on some devices (the layout ended above the
  screen edge by the height of the status bar). Kalmido now measures the gap and moves the tab bar and the other
  bottom elements down.
- Dragging sections (and tasks, and lists in the sidebar) in long lists on a computer: the list now scrolls when you
  come near its top or bottom edge, faster the closer you get.
- The iPhone shortcut sent to `/drop/drop` when the address already ended in `/drop`: `POST /drop/drop` is now
  accepted as well.
- After *New token* under *Account*, *Share from your phone* in the same open dialog still showed the old token.

## [2.0.1] - 2026-09-29

### Fixed
- The start guard of 2.0.0 (#279) also refused databases whose only finding in `PRAGMA quick_check` is a NOT NULL /
  CHECK constraint violation. Such a database is readable: Kalmido starts again and the admin alert reports it, as
  before. Damaged pages, broken indexes or an unreadable file still stop the start.

## [2.0.0] - 2026-09-29

**In short:** AI agents join the team: agent users that get events by signed webhook or long-polling, report status
and jobs, chat and wait for your 👍. Reactions on comments, shared list tags, an MCP server, and a new license (AGPL-3.0).

### Added
- **Agent users** (*Settings > Administration > Agents*, admins): a user type *Agent* for external AI agents and automations
  (Claude Code, Codex, n8n, a local model, a script). An agent is never an admin, has no Paperless access, cannot log in
  to the web app and sees only the lists shared with it (roles member, participant or viewer; the 1.10 roles apply).
  Per agent: API token (shown once), optional webhook URL with its own signing secret, a usage note and an
  **on / off switch** (kill switch: its token and its events stop at once). An existing user can be turned into an
  agent and back; its lists, shares and tokens stay.
- **Agent events**: mention (in a comment, a task title or notes), comment on a task the agent follows, assignment /
  unassignment, chat message, reaction on the agent's comment, job action, tidy request, **wake** and ping. Delivered
  as signed webhooks (same signature, retries and delivery log as the user webhooks) and kept for polling:
  `GET /api/v1/agent/events?since=<cursor>` with **long-polling** (`&wait=<seconds, max 60>`: the request answers as
  soon as an event arrives).
- **Wake agent** button in the task panel and in the Agents tab / chat: sends an immediate `wake` event.
- **Reactions** 👍 👎 ❤️ or any single emoji (+) on comments for everyone who can see the task, with the names on hover / tap. 👍 / 👎 on an
  agent's comment by the list owner, a list admin, the task's assignee or a server admin counts as **approval /
  rejection** (sent to the agent, shown in the history).
- **Agent status** (idle, working, waiting for approval, error, a short text, job counts) reported via the API: a dot on
  the agent's avatar and a chip in the top bar like the timer (*Claude · 2 running · 1 waiting*) that opens the jobs.
- **Agents** module / tab (opt-in under *Settings > Modules*): jobs reported by agents (running, waiting, done,
  failed, stopped) with the linked task and a short log; *Approve*, *Reject* and *Stop* send an event to the agent and
  show up in the task's history.
- **Chat with an agent**: a side panel on the desktop, a tab on the phone; one conversation per person and agent,
  stored on the server, delivered as an event and readable via the API; the agent answers via the API.
- **Tidy up** per list (*Agent may tidy up entries*: off, suggest, automatic; only for lists shared with an agent): the
  agent turns long, quickly typed entries into a short title, section, tags and priority. The original text is kept
  word for word at the top of the notes (**Original (Name):** …). *Suggest* posts a suggestion comment that 👍 (or
  *Apply*) applies; *automatic* applies it right away via `POST /api/v1/tasks/{id}/tidy`.
- **Shared list tags**: tags that belong to a list, with a colour per list, visible to all its members, next to the
  personal tags. In shared lists the tag input suggests list tags first; personal tags show a small person icon; a
  personal tag can be promoted to a list tag. Filters, the sidebar, the REST API (`list_tags`, `/api/v1/lists/{id}/tags`)
  and the MCP server handle both; agents may set list tags. Existing tags stay personal.
- **MCP server** for Kalmido in `mcp/` (stdio and HTTP): list / search tasks, read a task with its comments, create,
  change and complete tasks, comment, react, report the agent status, read and wait for events.
- **Quick add understands the list in plain words**: `in list Work` / `in Liste Arbeit` / `to list …` anywhere, and
  `… in Work` / `… auf Einkauf` / `… into Home Office` at the end when it is exactly the name of a list (otherwise the
  words stay in the title: "Letter to grandma in Berlin" stays text unless a list is called "Berlin"). The chip shows the
  list; clicking it keeps the words in the title. `~list` works as before.
- **docs/AGENTS.md**: the agent protocol (events, payloads, signatures, polling and long-polling, approvals, status,
  jobs, chat, tidy) with an example for a Claude Code session that works through the API.

### Fixed
- **Never an empty database on top of existing data** (#279): when `tasks.db` was missing, empty, unreadable or
  damaged (e.g. I/O errors of a failing disk), Kalmido created a new, empty database on start, and the first visitor would
  have become the admin. Now the data dir gets a marker (`.kalmido-initialized`, also written on the first start of 2.0 of
  an existing install); with the marker, attachments or backups present, a broken database makes Kalmido refuse to start
  (clear log line, exit code 3) until the database is repaired or restored. Only an empty data dir starts fresh.

### Changed
- **License: GNU AGPL-3.0.** Contributions need a DCO sign-off (see CONTRIBUTING.md).
- The public git history was squashed into one commit "Kalmido 2.0.0"; the old tags and GitHub releases v1.x were
  removed (the container images 1.x stay on ghcr.io, pinned tags keep working).
- `GET /api/v1/tags` lists personal and list tags (`kind`: `personal` / `list`); `?tag=` on `GET /api/v1/tasks`
  matches both.

## [1.10.0] - 2026-09-29

**In short:** Roles per shared list: admins see and manage everything, participants see only the tasks assigned to them; an assignee column with pictures and one-click assigning, also for subtasks.

### Added
- **List roles** (*Edit list > Sharing*, a picker with a one-line explanation per role):
  - **Admin**: sees and changes the whole list and manages the members and their roles (never the owner's).
  - **Member** (before: *Can edit*): sees and changes every task.
  - **Participant** (new): sees **only the tasks assigned to them**, with all their subtasks, comments, files and time.
    When only a subtask is theirs, its main task shows above it as read-only **context** (title, dates, status; no
    notes, link, files, fields or comments). Sections appear only when they hold one of their tasks. A participant may
    add tasks to the list (they are always assigned to themselves) and subtasks under their tasks, edit, complete and
    comment on them; they cannot delete tasks, move them to another list, hand them to someone else, or change
    sections, the list, its members or the project status.
  - **Viewer** (before: *View only*): sees everything, changes nothing (may comment).
  - The owner keeps everything only the owner could do: rename, type, archive, delete, public link, custom fields.
- The participant rule is enforced on the server for **every** way to read data: the app state and sync, single tasks,
  subtasks, search, completed and trash, filters and smart lists (built from that state), tags, calendar repeats and
  the ICS feed, the roadmap, project progress, the overview, time entries / report / CSV, templates, the export,
  comments and files, dependencies, News, pushes, reminders and the daily digest, the REST API (all endpoints, also
  paging), webhooks (a participant's webhook fires only for their own tasks) and the undo history (checked per task).
- **Assignee column** in list, section, folder, filter and search views: the assignee's picture (or a dashed circle for
  nobody) on every task of a shared list; a click opens the assign menu (owner, admins and members). On phones a compact
  cell at the end of the row. Hide it per list: list *…* > *Hide assignee column*.
- **Subtasks can be assigned on their own** (from the subtask rows in the task panel or its own panel), independent of
  the main task; a participant assigned only to a subtask sees it with its main task as context.
- API: `role` may be `admin` and `participant` too (`PUT /api/lists/{id}/members`); tasks carry `context: true` for a
  participant's read-only main task.

### Changed
- The roles *Can edit* and *View only* are now called **Member** and **Viewer**; the stored values `edit` / `view` and
  what everybody sees stay exactly the same (nothing to migrate). List admins can moderate comments like the owner.

## [1.9.0] - 2026-09-29

**In short:** Share photos, files and links from your phone in two taps, profile pictures (sloths or your own photo), a News inbox that works like mail, deleting a tag everywhere, a refresh button for shared lists, and dialogs that stay put on the Galaxy Fold.

### Added
- **Share from your phone** (*Settings > Integrations > Share from your phone*). Android: *Download HTTP Shortcuts
  import* gives a ZIP made for you (address + `/drop`, your upload token, the Kalmido icon) with two shortcuts, *Kalmido*
  for photos and files (several at once) and *Kalmido text* for links and text; import it in the HTTP Shortcuts app and
  share. iPhone / iPad: copy buttons for the address and the token and a step-by-step guide for the Shortcuts app; a
  signed generic shortcut can be linked with `KALMIDO_IOS_SHORTCUT_URL` (the button is hidden while it is empty).
- **Profile pictures** (*Settings > Account*): ten sloth presets (coffee, headphones, camera, sleepy, laptop, plant,
  robot, sunglasses, party, reading) or your own photo, cropped square in the browser; the server resizes it to 256 px,
  turns it upright and stores a fresh JPEG without EXIF / GPS data (below the attachments, so backups include it).
  Shown wherever the initials were: sidebar, assignee chips, comments, mentions, News, members, time entries and the
  user list. Only you, admins and people sharing a list with you can load your photo. Admins can set a preset for
  another user (e.g. an API bot user).
- **Delete a tag completely:** right-click or long-press a tag in the sidebar (or "…" in the tag view) > *Delete tag…*;
  the dialog says on how many tasks it is, removes only your tag (tasks stay, other people's tags too), one undo step.
- **Refresh for shared lists:** a button in the header on desktop, *…* > *Refresh* and pull-to-refresh on touch. (The
  app keeps polling for changes every 4 seconds while it is visible.)
- **News like a mail inbox:** unread items bold, *×* (desktop) or a swipe (touch) removes one item, the filter *All |
  Mentions & assigned to me*, and *Settings > Notifications > News* chooses which events create News (mentions,
  assignments, comments on my tasks, unblocked, sharing, project status, completions by others). Completions by others
  are off by default now.
- API: `GET /api/v1/admin/status` also returns `update_checked_at` and `update_error`.

### Changed
- *Settings > Administration* starts with the users (and *New user*).
- The open task shows new comments while you are typing in it (the rest of the page still waits until you are done).

### Fixed
- **Update check reported an old release** (e.g. `latest_version` 1.2.0 while 1.8 ran): the result was cached for a
  day and survived updates, so a check made before the update was still shown, and after a failed request (GitHub's
  rate limit for anonymous requests) the old value stayed. Now a cached release older than the running version is never
  reported, the check runs again right after an update, every 6 hours, and an hour after a failure.
- **News showed "Loading…" forever when there was nothing** (or with collaboration off): an empty feed now says
  *No news*, and *Loading…* only shows while a request runs.
- **Dialogs slid down on the Galaxy Fold** after the on-screen keyboard closed (e.g. *Create API token*): dialogs now
  follow the visual viewport and centre again when the keyboard opens or closes.

## [1.8.1] - 2026-09-28

**In short:** The Inbox comes first and is where the app opens, completed tasks are shown everywhere unless you hide them per view, and the sign-in and setup screens are centered on tablets.

### Changed
- **Inbox first.** The Inbox is the first smart list in the sidebar and the phone drawer (before Today, Tomorrow,
  Next 7 days and Now doable), in the tab choices (*Settings > Appearance*) and in the command palette, and it is the
  start view: the app opens on the Inbox until you open another task view (after that it reopens on the last one, as
  before). When the open list goes away (archived, deleted, left), the app goes to the Inbox instead of Today. The
  welcome tour says so.
- **"Show completed" is per view only.** The global switch in *Settings > General* is gone: completed tasks are shown in
  every list, filter and smart list, and you hide them where you do not want them (*Hide completed* in the view's "…"
  menu, the sort menu or the command palette). Choices you made per view stay. The stored global value is removed on
  the first start.
- **Calendar: its own "Completed" toggle** in the bar of the month, week and day view (also in the command palette),
  shown by default, per user and synced like the other views (entry `cal` in the setting `show_done_views`), undoable.

### Fixed
- **Sign-in and first-run setup centered on tablets in portrait** (for example a Galaxy Fold unfolded): below 900 px
  width these screens were a bottom sheet with the empty space above; they are now centered at every size, rounded on
  all corners and opaque in the light theme too (the app behind showed through).
- A welcome tour card without a target is centered on the screen instead of sitting at 30 % from the top.

## [1.8.0] - 2026-09-28

**In short:** New accounts can start with a realistic sample project that shows the project features, and remove it again in one click.

### Added
- **Sample project.** *Example: Image film for client Muster*: a project list with the sections Concept,
  Pre-production, Shoot, Edit and Approval, 15 tasks and 3 subtasks with dates relative to today (overdue, today, next
  week, undated), start dates and durations for the timeline, four dependencies (so *Flow*, *Now doable* and the
  timeline arrows have something to show), priorities in all four matrix quadrants, a Markdown description with a
  checklist, tags, a weekly status call, a comment, two pinned custom fields (budget, effort), a 1.5 h time entry and
  the project status *On track*; plus the checklist *Example: Shoot day packing list*. In the user's language (English,
  German), and only with the modules that are on: without the project modules it is a plain list without
  dependencies, fields, time or status.
- **Where it is offered:** setup step 2 has *Create a sample project* (ticked for *Projects & team*, unticked for
  *Simple list* and *Just me*, a manual choice wins); the first card of the welcome tour of every new account offers
  it too (ticked when dependencies, custom fields or time tracking are on; asked once, not again after the setup
  decided it); *Settings > Data > Sample project* and the command palette create or remove it at any time.
- **Removing** asks with the app's own dialog, naming the lists and the number of sample tasks, and removes exactly
  what the sample created (recorded on the server): sample tasks also when you edited them, including the done copies
  of the repeating task, its sections, fields and time entry. Tasks you added stay (also subtasks below a sample task,
  which become main tasks), and with them their list, section and custom field.
- **Quiet and private:** the sample belongs to the user alone, sets no reminders, creates no activity, News, pushes or
  webhook events, and its tasks are left out of the daily digest. Creating it twice does not duplicate it.
- API (app): `POST /api/sample` (idempotent: `{created: false, exists: true}` while one exists), `DELETE /api/sample`,
  `sample` in `GET /api/state`, `sample: true` in `POST /api/admin/setup`.

## [1.7.1] - 2026-09-28

**In short:** Lists scroll to the end again on phones, and the Markdown syntax moved from the description box into Help.

### Fixed
- **Phones: the last rows of a list sat under the tab bar** and a list only a little longer than the screen (for
  example *Tomorrow* with a few tasks and subtasks) could not be scrolled at all. Since 1.5.3 the docked composer set
  the list column's bottom padding to 0, also on phones, where the composer is hidden (the + button is used there).
  That padding now only goes away on wider screens with the docked composer. New suite `tests/scroll_ui.js` (Firefox
  headless, skipped without Firefox) checks every view at 360 × 780 and 390 × 844 with touch: the last line clears the
  tab bar and the + button, the scroll box can scroll and no touch handler cancels a vertical drag.

### Changed
- The task description box just says **Description** (German *Beschreibung*) instead of listing Markdown syntax.
- **Settings > Help > Formatting (Markdown)** lists what descriptions understand: bold, italic, strikethrough, code,
  links (`[text](https://…)` or a plain address), headings `#` to `###`, bullet and numbered lists and checklists
  `- [ ]` / `- [x]` (tick them in the formatted text), plus the button that turns open checklist items into subtasks.
  With collaboration on it adds that comments understand bold, italic, strikethrough, code and links, line breaks and
  @mentions, but no headings, lists or checklists.

## [1.7.0] - 2026-09-28

**In short:** A "Flow" sort that follows the dependencies, all overdue tasks moved in one click, and the smart list "Now doable".

### Added
- **Sort mode "Flow"** (sort menu; German *Ablauf*; only with the dependencies module): a topological order by
  *Waiting on*, so a task always comes after the open tasks it waits on inside the view; ties by start date (a task
  without one starts on its due date), due date and time, priority, then manual order. The first task of each group
  that waits on nothing gets a subtle *Next* marker; waiting tasks keep the lock and "Waiting on …". Lists order
  within each section, filters and Today / Next 7 days show one sequence instead of date groups. Dependencies on
  tasks outside the view are ignored for the order. A circle of dependencies (only possible in old or imported data)
  falls back to date order with one hint. Project lists use Flow by default while you have not picked a sort (list
  view; kanban and timeline keep theirs); with the module off the option is hidden and the old default applies. A
  manual drag switches the view to *Priority, then manual*, like Date and Title do.
- **Overdue in one click** on Today: when overdue tasks are shown, a compact banner *n overdue → Today / Tomorrow /
  Next week (Mon) / Pick a date…* moves all of them at once. Only the day changes (time, reminders and repeat stay,
  like the date popover), tasks in lists you may only view are skipped and counted in the toast, and the whole move is
  one undo step (one batch request). The × hides the banner until tomorrow on that device. Only on Today.
- **Smart list "Now doable"** (German *Jetzt machbar*, `#doable`, `g d`): open tasks that wait on nothing, are due
  today, overdue or undated (an undated subtask follows its parent), do not start later, are not in an archived list, and are yours: assigned to you, or
  unassigned in a list you own (with collaboration off: every task). Sorted by Flow (by date without the dependencies
  module). In the sidebar after *Next 7 days* with its count, in the command palette, the shortcuts overlay and the
  pinnable tabs.

## [1.6.1] - 2026-09-28

**In short:** "Archived" is now a plain sidebar row like Trash that opens a view of all archived lists.

### Changed
- **Archived lists get their own view.** The folded *Archived (n)* row with its chevron is gone: *Archived* is a
  plain row in the sidebar footer like *Trash* (icon, name, count; only when there is an archived list, phone drawer
  too) and opens *Archived* (`#archived`). It lists every archived list with its colour or emoji, name, folder, open
  and completed tasks, the day it was archived and, for a shared list, its owner. Per list: *Open*, *Restore*
  (undoable) and *Delete permanently…* (owners, with the dialog that names what is lost). Archived lists no longer
  show up one by one in the sidebar; while one is open, the *Archived* row is highlighted. The fold state kept on
  the device is dropped.
- Lists remember when they were archived (`archived_at`, set on archive, cleared on restore; lists archived before
  1.6.1 show no date).

## [1.6.0] - 2026-09-28

**In short:** Docked quick add, undated tasks in the timeline, bigger timeline bars, a filterable matrix, tooltips instead of helper lines.

### Added
- **Quick add docked at the bottom** of the list column (desktop and tablet; phones keep the + button): a card with
  an accent "+", *Add task…*, the `N` key badge and the template button. Focused, it shows chips for date, list and
  priority (from what you type and the view; a click changes them and wins over the text) and the recognised tokens.
  Enter adds and keeps the focus, Esc leaves. Lists, folders, filters, Today and Next 7 days; not kanban, matrix or
  calendar. The old input on top is gone.
- **Undated tasks in the timeline.** Per list a folding *No date (n)* group with one row per task (subtasks under
  their parent) and an empty dashed track: click a day = due that day, drag across days = start and due (touch: hold,
  then drag). *Remove date* in the bar menu, or drop a bar on *No date*. Every change is one undo step. Header switch
  *No date* per device, on by default in project lists. Waiting tasks show *waits for …*; auto-shift ignores them.
- **Matrix scope.** *All lists ▾* picks a list, a folder or a saved filter (same filter engine); chips *Only mine*
  (with collaboration) and *Due by* (overdue and today, 7 or 30 days); remembered per device, shown in the title with
  an × to reset. *Show as matrix* in the "…" menu of lists, folders and filters; quick add in a scoped matrix goes
  into that list (or the folder's first list).
- *Settings > Appearance > Show tips again* brings back the one-time hints on this device.

### Changed
- **Timeline and roadmap bars are taller** (34 px, 44 px on touch), the resize handles reach past the bar ends, a
  1-day bar keeps a minimum width, the dependency dot is bigger and sits outside the bar end.
- **Tooltips instead of helper lines:** the empty checklist *Done* hint, the attachment drop hint, the timeline's
  date-range hint, the custom-fields hint and the Filters placeholder became tooltips (touch screens show them once,
  with ×); the habit day hint disappears after the first tapped day; the owner note of a shared list is a lock icon.
  Tooltips name the keyboard shortcut (`G T`, `D`, `X`, `T`, `Shift+T`, `N`, …).

### Fixed
- CI of 1.5.2: a list colour in a group header now goes through `cssColor`, the stylesheet uses rem only.

## [1.5.2] - 2026-09-28

**In short:** Folder view, "Delete completed…", running timer card on the time page, archived lists folded in the sidebar.

### Added
- **Folder view.** Click a folder's name in the sidebar to see the open tasks of all its lists in one view, grouped
  by list (with the list colour); the chevron still folds the folder. Own address (`#folder/<name>`), can be pinned
  as a tab, has its own *Show completed*, sorting and selection; quick add goes into the folder's first list.
- **"Delete completed…"** on the *Completed* view: all, or those completed more than 30 / 90 days ago, go to the
  trash (restorable, one undo step). Only what you may change; items of checklists stay; the dialog says what stays.
- **Running timer on the time page.** While a timer runs, *Time tracking* opens with a large card: the live time,
  the task (a click opens it), its list or project with colour, the start time and the note, *Stop timer* and *Open
  task*. Nothing running: a short *No timer running* with the tasks you tracked most, one tap starts the timer again.
  Stacks on phones.

### Changed
- The search button in the icon rail (shown while the sidebar is folded) sits at the bottom, right above Settings.
- **Archived lists fold into one row** *Archived (n)* in the sidebar footer (phone drawer too); a click unfolds it,
  remembered per device. An archived list you have open stays visible.

### Fixed
- `tests/checklist_ui.js` still clicked the list dialog's old *Save* button (CI of 1.5.1).

## [1.5.1] - 2026-09-28

**In short:** One-tap Today / Tomorrow, "Show completed" per list, archived lists stay out of the way, no duplicate navigation.

### Added
- **One tap "Today" / "Tomorrow".** Two buttons on top of the task menu (long-press, right-click, the row's "…"), next
  to the date in the task panel and in the selection bar; on the keyboard `t` / `Shift+T` for the focused, open or
  selected tasks (listed in the shortcut help). Only the day changes: time, reminders and repeat stay (a recurring
  task just moves, like in the date dialog). One step in the undo history.

### Changed
- **"Show completed" per view.** Every list, filter and smart list (Today, Tomorrow, Next 7 days, Inbox, All,
  Assigned to me, tags) has its own *Show completed / Hide completed* in its "…" menu (also in *Sort…* and the command
  palette), stored per user on the server (it follows you to every device, the other members of a shared list keep
  their own) and undoable. A view without its own choice follows the old setting (*Settings > General*), which the
  calendar keeps using. Tomorrow, Next 7 days, All, Assigned to me and filters now have a *Completed* group too.
  New user setting `show_done_views` (json map view -> 0 / 1).
- **Archived lists stay out of the way.** Their tasks no longer show up in Today, Tomorrow, Next 7 days, Assigned to
  me, filters, tags, the calendar (incl. repeats), the matrix, the overview, counts and the command palette; they get
  no reminders, are left out of the daily digest, the calendar subscription (ICS) and the overdue trend of the
  statistics. Opening the archived list still shows them; restoring it brings everything back.
- **The list dialog saves itself** like the settings: every change applies at once, *Saved · Undo* in the header, one
  history step each; no *Save* / *Cancel* any more (a new list keeps *Create*).
- **The first weekday of your region** (Monday in Germany, Sunday in the US) now also applies to the timeline, the
  roadmap, the statistics (weekly bars and heatmap; `GET /api/stats?ws=0..6`) and the time reports (*This week*).
- **No duplicate navigation on desktop.** Statistics, time tracking, overview, search and settings appear once: in
  the sidebar footer while the sidebar is visible, in the icon rail only while the sidebar is folded into it.

### Fixed
- The calendar did not show the repeats of a task that just got (or changed) its repeat, was completed or was
  changed on another device until the visible range changed; the repeats now refetch with every such change and
  the old ones stay visible while loading.

## [1.5.0] - 2026-09-28

**In short:** Usability: settings save themselves, own date picker, archive lists, slimmer checklists, tablet layout.

### Changed
- **Settings save themselves.** Every switch, choice and field applies at once (text and numbers when you leave the
  field, press Enter or pause typing; closing the dialog saves what is still pending) and shows *Saved · Undo* in the
  dialog header. Each change is a step in the undo history (*Changed setting: …*), including appearance, the tab bar,
  the display name, the language, admin switches, admin alerts and backups. No *Save* buttons any more.
- **One Modules page.** *Settings > Modules* lists every module with one sentence, grouped (views, for you, projects
  and team, connections); focus and time-tracking options fold out under their module, and admins get the *for
  everyone* switch next to collaboration and time tracking. *Layout*, *Collaboration*, *Focus* and *Time tracking*
  are gone as tabs (9 sections instead of 12; the tab bar moved to *Appearance*, *Users* is now *Administration*).
- Developer things (upload token, API tokens, webhooks, `/drop`, allowed internal hosts, rule texts) sit under a
  folded *Advanced · for developers*; the ntfy details show only when ntfy is a channel; push priority in words
  (*Normal*, *Loud*, *Urgent*).
- **Archive instead of delete.** *Delete* in list menus and the list dialog is now *Archive* (undoable). Deleting for
  good is only possible for archived lists, with a dialog that names what is lost; the server refuses `DELETE
  /api/lists/{id}` for a list that is not archived (409).
- **The app's own dialogs** replace every browser `confirm()` / `prompt()`: title, what happens, a red action for
  destructive ones, Esc = no. What can be undone (deleting selected tasks, removing a link, clearing done checklist
  items) no longer asks and offers *Undo* instead.
- **Own date and time pickers** everywhere (task dates, start, repeat end, time entries, reports, custom date fields,
  templates, habits, public links, settings): in the app language, the week starting on your locale's first day,
  12 or 24 hours as your locale has it, typing a time (`930`, `9:30 pm`, `21 Uhr`), full keyboard and touch support.
  Month calendar and week view start on the same day. Stored formats are unchanged.
- **Custom repeat** is a small form (every n days / weeks / months / years, weekdays); the RRULE text is an expert
  field under *Advanced*.
- **Checklist items** get a slim panel: title, note and (shared, with collaboration) the assignee. Nothing else is
  shown; the data stays.
- **Comments only in shared lists.** In a private list the comment box is gone; comments from when the list was shared
  stay readable, folded and read-only. The activity switch says what it shows (*With activity* / *Comments only*).
- Task panel footer: no focus button (start focus from the task menu or the Focus page); *Track time* and *Delete*
  carry text; a running timer shows its time on the stop button.
- **Header:** the list title keeps its room, the running indicator shrinks to icon and time, *Select* and *Sort* moved
  into the header's “…” menu together with the list menu. Phones and touch tablets: *Undo: …* / *Redo: …* at the top
  of that menu instead of the ← → buttons (desktop keeps them). The running indicator is neutral with a pulsing accent
  dot (red stays for “overdue”) and no longer repeats in the settings header. Offline / sync is translated, an icon
  with a count on phones.
- **Fold and tablets:** while a task panel is open and the list would get narrower than about 420 px, the sidebar folds
  into the icon rail; its new *Lists and filters* button opens it as an overlay. Touch tablets use the compact view
  switch and hide the keyboard search button.
- Desktop sidebar: no second copy of what the rail has (statistics, time, overview, search, settings); tags fold.
  Phone drawer: account and a settings gear at the top.
- Habits: the grid shows the last 7 days up to today; on phones the name sits above its days. *New habit* is a
  labelled button below the list.
- Setup: the single modules are under *Customize…*, *Skip* is gone, *Start* stays in view, sign-in fields have labels.
- Welcome tour: the keyboard step only with a mouse, the project hint only for admins and teams, no line break inside
  `!high`.
- Time report: one tile with time and decimal hours, *today* only when the range is longer than today.
- Command palette: no “action” word on every row.

### Added
- Quick add says when a date and the repeat do not match (*first on Tue, then every Monday*).
- *Turn the open checklist items into subtasks* for “- [ ]” lines in a description (one undo step); those checkboxes
  now look like the app's own.

### Fixed
- Touch targets are at least 44 × 44 px on touch screens (header icons, checkboxes, habit cells, sidebar buttons,
  calendar days, switches, menus).
- Light theme: the red of overdue counts and danger actions is one step darker (AA on the highlighted row, was 4.43:1).
- Settings tabs on phones: the current tab is never cut off at the edge.

## [1.4.0] - 2026-09-28

**In short:** Undo history: step back and forward through every change, by keyboard or menu.

### Added
- **Undo and redo history** per device: ← / → in the top bar (on a phone in the header) step back and forward
  through the last 30 changes, kept until the page is reloaded. The tooltip names the step (*Undo: Completed “Pay
  invoice”*); a right-click or long-press on ← (or →) lists the last ten steps, and picking one undoes everything up
  to it in order. Keys: Ctrl/Cmd+Z, Ctrl/Cmd+Shift+Z and Ctrl+Y, at any time, but never inside text fields (the
  browser's own text undo keeps working there). A new change clears the steps forward; the six-second *Undo* toast
  stays as a shortcut to the newest step.
- Now undoable (and redoable) as well: title, description, tags, priority, assignee, link and custom field values
  (typing is one step per field until you leave it), creating a task (undo moves it to the trash) and subtasks, *Skip
  this occurrence*, sections (add, rename, delete with their tasks at their old place, reorder), lists (type, name,
  colour, view, *Move dependent tasks along*, hourly rate, archive, folder, order), next to everything that already had
  an undo (completing, deleting, moves, dates, batch actions, moving a project, dependent tasks, time entries).
- Conflict safety both ways: a field changed in the meantime, on another device or by another member, is left alone
  and reported (*Changed elsewhere, not undone: …*); a task someone else changed after it came back from the trash is
  not deleted again; a section is only removed while it is still empty and unchanged. Steps with several tasks are one
  transaction. Offline, a step that has not been sent is taken out of the queue; otherwise undo and redo are queued
  (a dot on the button while they wait). Steps in lists that became view-only are refused.

### Changed
- On phones the list's view switch shows only the current view; a tap on it offers the others (room for ← / →).
- Web app API: `POST /api/tasks/batch` reports `conflicts` (per task and field, custom fields as `field:<id>`) and
  the server time; `complete` takes `expect` (the date it should still have), `reopen` returns undo payloads, `delete`
  takes a `guard` (not if someone else changed the task after that time). Sections: `POST` takes `sort` and `tasks`,
  `PATCH` and `DELETE` and the order endpoint take the expected state as `_prev`, `DELETE` returns the section and its
  tasks. `PATCH /api/lists/{id}` and `POST /api/lists/reorder` take `_prev` too. A `_prev` for custom field values is
  checked per field.

### Fixed
- *Events today* (calendar subscriptions) no longer shows on Today while the Calendar module is off, and its setting
  is hidden then too.
- The roadmap label reads *29%* without the wide gap in the monospaced font.
- Tests: `time_api_test.py` fails with a non-zero exit code, and its statistics check no longer breaks on the Monday
  after the seeded week.

## [1.3.0] - 2026-09-28

**In short:** Roadmap of all projects, moving whole projects, section and sidebar drag and drop on touch.

### Added
- **Roadmap**: *All* has a view switch *List | Timeline* (with the timeline module). The timeline shows every list
  on one chart for rough project planning: lists grouped by folder, one row per list with a **summary bar** from the
  earliest start (or due date) to the latest due date of its open tasks, drawn as a bracket in the list's colour and
  filled by the project progress (with the progress module). Click a name to collapse a list to that one row; *Collapse
  all* / *Expand all*; with five or more projects they start collapsed. Filters: *Projects only* (on as soon as one list
  is a project), *Hide done*, an assignee (with collaboration) and a list / folder picker. Zoom *Week*, *Month* or
  *Quarter* (week columns, month labels) with *Today* and back / forward. View, zoom, filters and what is collapsed
  are saved per user, so they follow you to every device.
- **Move a whole project**: drag its summary bar, or long-press it on a phone (*Move project by…* in days or weeks,
  also in the bar's menu and with **M** on a focused bar). Every open task with a date in that list, subtasks too,
  moves by the same number of days and keeps its length; tasks without a date stay. Tasks in other lists that wait on
  it follow when their list has *Move dependent tasks along* on. One toast (*12 tasks moved*), one *Undo* for all of
  it. Needs edit rights on the list; at most 500 dated tasks at once.
- Dependency arrows across lists in the roadmap; into a collapsed list they attach to its summary bar, several
  merged into one arrow with a count.
- API: `GET /api/v1/roadmap` (groups with summary spans, progress and dated tasks; `from`, `to`, `projects_only`,
  `include_done`) and `POST /api/v1/lists/{id}/shift` with `{days}` (write scope, one transaction).
- **Sections by drag and drop:** drop a task on a section header (it goes to the top of that section; a subtask
  becomes a standalone task there), empty sections show *Drop tasks here* while you drag, and sections are reordered
  by the handle on their header, in the list view and on kanban columns (one request, one *Undo*; *Move up / down*
  in the section menu uses the same). On a phone: long-press a task for *Move to section…*, a section header for
  *Move section up / down*.
- **Sidebar drag and drop on touch:** long-press a list and drag it to reorder, onto a folder to move it in, onto
  *Lists* to take it out (with *Undo*); long-press a folder to reorder folders. A closed folder opens while you hover
  over it, the drawer scrolls at its edges, a tap still opens the list, and a hold without moving opens the list's
  menu, which now has *Move to folder…*.

### Changed
- The roadmap draws only the rows in view, so 50 projects with 1000 tasks scroll smoothly.
- A switched-off module is gone everywhere: no *Start focus session* button in the task panel with *Focus* off (and
  no focus entry in the running indicator, the settings, the shortcuts overlay), no *Timeline* shortcuts without the
  timeline, no *Projects* help without the project modules. Starting a focus session, creating or checking in a
  habit, and starting a timer or adding time with the module off are refused by the server (409, with the reason);
  the data stays.

### Fixed
- The task panel showed *Start focus session* with the *Focus* module off.
- Touch tablets (a foldable unfolded, an iPad) at 900 px and wider had no "+" button: it now shows bottom right on
  touch screens without a mouse (left of an open task panel) and opens the quick-add sheet, centred at the bottom.

## [1.2.0] - 2026-09-27

**In short:** Gantt arrows with drag-to-link, list types (list / checklist / project), running-timer indicator.

### Added
- **Gantt timeline** (list view *Timeline* and *Calendar > Timeline*): dependency arrows finish → start between the
  bars (orthogonal, rounded, with arrowheads), a red arrow and bar edge when a task starts before a task it waits on is
  due (*Starts before "X" is due*), hatched waiting bars with a lock, dashed arrows from completed blockers, short stubs
  with a tooltip for tasks outside the visible range or in other lists. The arrows follow a bar while it is dragged
  and are redrawn on resize and font size changes.
- **Link in the timeline:** drag the dot at the end of a bar onto another bar (that task then waits on it), with a
  rubber band, highlighted valid targets and the server's reason for refused ones (a loop, a task you may only view,
  itself); a click on the dot, a long-press on a phone (*Connect to…*), the keyboard (**C** on a focused bar, then
  Enter on the target, Escape to cancel, arrow keys between bars, Shift+F10 / right-click for the bar menu) or
  *Pick from a list…* do the same. Click an arrow to remove the dependency or open either task.
- **Move dependent tasks along** (list dialog, owner, off by default): when a task is postponed, the open tasks of
  that list waiting on it that would now start too early move by the same number of days, keeping their length, down
  the chain (at most 10 levels and 50 tasks, only tasks you may change; also from the date dialog, dragging onto a day
  and the API). The toast says *3 dependent tasks moved*; one *Undo* takes the whole chain back. Timeline drags can be
  undone now too.
- **Three setup presets** in the first-run setup: *Simple list* (lists, subtasks, reminders, calendar), *Just me*
  (preselected: all views for one person) and *Projects & team* (everything, for teams up to about ten people), with
  the single modules below; the welcome tour and the *Getting started* list only mention modules that are on
  (*Getting started* gets a *Plan a project in the timeline* item when timeline and dependencies are on).
- `GET /api/deps` (the app's timeline: every dependency between tasks you can see); `/api/v1/me` reports the modules
  `dependencies` and `custom_fields`.

- **List type** selector (list dialog, new-list dialog, the list's … menu and right-click in the sidebar): *List*
  (default), *Checklist* (the former checklist switch) or *Project*. Only project lists get time tracking,
  dependencies, custom fields and progress / status (while their modules are on); plain lists and checklists hide
  them completely (rows, task details, menus), nothing is deleted. A *Project* badge next to the list title. The server
  refuses timers, time entries, dependencies (both lists must be projects), field values and a status elsewhere with a
  clear 409; reports, the timesheet, statistics and *Where is it stuck?* only count project lists. The update makes
  lists with dependencies, custom fields, a status or at least 5 minutes of tracked time projects and checklists checklists. API: `kind` on
  lists, the `checklist` flag keeps working. With *Projects & team* the *Getting started* list is a project.
- **Hide the progress bar** of a project with the small × next to it, per person and list (synced across devices);
  *Show progress* in the list's … menu or the list dialog brings it back.
- **Running indicator** in the top bar (and the Settings header) for everything that runs: time tracking, a focus
  session or break, the stopwatch, each with its own icon, the time and the task, or *2 running*; a click opens the
  task with Pause / Stop. The task details show what runs on that task; the start buttons say what they start
  (*Start time tracking*, *Start focus session*, *Start stopwatch*).

### Changed
- **Dependencies** and **Custom fields** are modules of their own (*Settings > Layout > Views and features*, per
  person). Off = hidden in the app (details, rows, overview, list dialog, filters, timeline), no *Unblocked* News or
  push; nothing is deleted and the API keeps working. Existing accounts keep them if they already have dependencies
  or custom fields in their lists or use the timeline or project progress; everyone else follows the server's default
  from the setup. A setup default from before 1.2 that includes the timeline or project progress gets both too.

### Fixed
- The task names on the left of the timeline stay in place while the chart scrolls sideways.
- A focus session or break whose tab was closed is finished by the server at its planned end (with its time entry, as
  set under *Finished focus sessions count as time*), and a late *finish* no longer counts the hours in between as
  focus time. A forgotten stopwatch stops after the same hours as a forgotten timer.

## [1.1.10] - 2026-09-27

**In short:** Importers for Todoist, Trello, Asana, Microsoft To Do and ICS, with preview and undo.

### Added
- **Importers** (*Settings > Data > Import*): Todoist (CSV per project, the backup ZIP, Sync API JSON; English and
  German date texts incl. recurring ones, sections, subtasks, @labels, priorities, durations, deadlines, comments),
  Trello (board JSON: lists as sections or as lists in a folder, checklists as subtasks, labels, members, archived
  cards skipped or completed, comments and attachment links in the notes), Asana (CSV: sections, parent tasks, tags,
  dates, completion, assignees when they can see the list), Microsoft To Do (Outlook tasks CSV in English or German,
  also Windows-1252, CSVs of export tools, ICS) and ICS / VTODO (Apple Reminders exports, Nextcloud Tasks,
  Thunderbird: time zones, RELATED-TO, RRULE, VALARM, completed / cancelled). One picker with export instructions per
  app, a **preview** (dry run in the same transaction: counts per list, sample rows, what cannot be mapped), target =
  new lists or an existing one, idempotent re-import (external id per source), an import report and **Undo** for 24
  hours (*Recent imports*), history line *imported from ...*.
- Import safety: 20 MB / 20,000 tasks per import (`KALMIDO_IMPORT_MAX_MB`, `KALMIDO_IMPORT_MAX_TASKS`), 30 imports per
  user within 10 minutes (`KALMIDO_IMPORT_RATE`), ZIP bomb and nesting limits, encoding detection (UTF-8 / BOM,
  UTF-16, Windows-1252), control and bidi characters removed, formula cells kept as text, nothing inside a file is
  fetched, every value validated like the app's own input.
- API: `POST /api/v1/import/{source}` (multipart, scope write, `dry_run`) and `POST /api/v1/imports/{id}/undo`.

## [1.1.9] - 2026-09-27

**In short:** REST API with tokens, webhooks, public read-only list links, checklist mode.

### Added
- **REST API** under `/api/v1` with **personal access tokens** (*Settings > Account > API tokens*): name, access
  (read / write / admin read for admins), optional expiry; shown once (`abk_` + 256 random bits), stored as SHA-256,
  revocable, last use shown. A token acts as its user and never has more rights (same list roles, module switches;
  admin rights re-checked on every request; disabled / deleted users' tokens stop at once). Bearer token only (no
  cookie, no proxy header, so no CSRF header needed). Lists, tasks (filters: list, status, due range, tag, assignee,
  updated since, parent; create / change / complete / reopen / delete to the trash), subtasks, tags, comments, time
  entries, habit check-ins, search, admin users and status. JSON, ISO dates, cursor pages, one error format, unknown
  fields refused. The API uses the app's own endpoints internally: history lines *via API*, notifications and webhooks
  as in the app. 120 requests per token and minute (`KALMIDO_API_RATE`), invalid tokens limited per address and
  reported to the admins. OpenAPI 3.1 at `/api/v1/openapi.json`; [docs/API.md](docs/API.md) with curl, Home Assistant,
  n8n and shell examples. `KALMIDO_API=0`.
- **Webhooks** (*Settings > Integrations > Webhooks*): up to 10 per user for `task.created`, `task.updated`,
  `task.completed`, `task.reopened`, `task.deleted`, `comment.created`, `list.shared`, only for lists the user can see.
  Signed with HMAC-SHA256 (`X-Kalmido-Signature: t=...,v1=...`, secret shown once and stored encrypted), delivered from
  a queue (10 s timeout, response ignored, no redirects), retried after 1 min, 5 min, 30 min and 2 h, then turned off
  with an admin alert. *Send test*, delivery log (last 50, no bodies), new secret. SSRF guard like calendar
  subscriptions: only public https addresses unless an admin allows the host (*Allowed internal hosts*, now shared by
  calendars and webhooks, or `KALMIDO_WEBHOOK_ALLOW_HOSTS`). `KALMIDO_WEBHOOKS=0`.
- **Public links** for a list (*Edit list > Public link*, owner only): view only or view and tick off, optional
  password (hashed, per-link unlock cookie) and expiry, new link / turn off. A script-free page with only that list
  (sections, open tasks, subtasks, recently completed; notes only when switched on), `noindex`, `no-store`, strict CSP.
  Ticking off goes through the normal completion (history and News *via the public link*). Rate limits per address, an
  admin alert when one link is opened unusually often. Admin switch under *Whole server*, `KALMIDO_PUBLIC_LINKS=0`.
- **Checklist mode** for a list (*Edit list*): done items stay in a *Done* section at the bottom, back on the list with
  one tap, *Uncheck all*, *Clear done*, compact rows without dates or priorities. Works with sharing and public links.

### Changed
- *Allowed internal calendar hosts* is now *Allowed internal hosts* and applies to calendar subscriptions and webhooks.
- The service worker never caches public link pages.
- API with tokens and webhooks, public list links, checklist mode

## [1.1.8] - 2026-09-27

### Added
- **Automatic backups + restore** (*Settings > Users > Whole server > Backups*, admins): a daily archive (zip) of the
  database (SQLite online backup API) and all attachments with a manifest of SHA-256 checksums, at a set time (default
  03:30), retention (everything of the last 24 hours, 14 daily, 8 weekly, 3 safety backups; adjustable), *Back up
  now*, download, check, delete. Optional encryption with a passphrase (scrypt + AES-256-GCM in authenticated chunks;
  without the passphrase an encrypted backup cannot be restored). Restore from a listed backup or an uploaded file
  after typing `RESTORE`: the archive is fully checked (expected members only, no traversal / links, size, member and
  ratio limits against zip bombs, checksums, `integrity_check`, no foreign triggers / views, schema version), then
  maintenance mode, a safety backup of the current state, attachments + database swapped (rollback on failure),
  migrations, every other session ended. Admin alerts for a failed backup and for no backup in 2 days.
  `KALMIDO_BACKUPS=0`, `KALMIDO_BACKUP_DIR`, `KALMIDO_BACKUP_PASSPHRASE`, `KALMIDO_BACKUP_MAX_MB`.
- **Two-factor authentication** for the built-in login (*Settings > Account*): authenticator app (TOTP, QR code made on
  the server, encrypted secret, no code accepted twice), 10 one-time recovery codes (hashed), **passkeys** (WebAuthn)
  as second factor and for passwordless login (admin switch), rename / remove, admin reset. Admin policy *Require
  two-factor authentication for built-in logins*: users set it up at their next login. Proxy-header SSO and OIDC
  logins are unaffected. `KALMIDO_WEBAUTHN_RP_ID`, `KALMIDO_WEBAUTHN_ORIGINS`.
- **OpenID Connect login** ("Log in with ..."): Authorization Code + PKCE, discovery, ID token verified against the
  JWKS (iss, aud, azp, exp, nonce), userinfo, only admin-created users by default (linked by user name or verified
  e-mail, then by subject), optional auto-create, required group and admin group, requests through the SSRF guard
  (`KALMIDO_OIDC_ALLOW_HOSTS` for a provider in your network). `KALMIDO_OIDC_*` variables, shown read-only to admins.
- Users have an optional e-mail (for OIDC linking). Sessions remember how they logged in; a login never keeps a
  session token the browser brought along.

### Security
- New dependencies, pinned: `webauthn` 3.0.1 (+ `cbor2`, `pyOpenSSL`, `pyasn1`, `pyasn1-modules`,
  `typing-extensions`) and `segno` 1.6.6.
- Backups with restore, two-factor (TOTP, passkeys) and OIDC login

## [1.1.7] - 2026-09-27

### Fixed
- CI: the control-character filter of calendar texts uses escapes instead of literal bidi characters (bandit B613).
- Calendar text filter: escaped bidi ranges (bandit B613)

## [1.1.6] - 2026-09-27

### Added
- Calendar subscriptions (*Settings > Integrations > Calendars*): events from Google Calendar (secret iCal address),
  iCloud, Outlook or any ICS link (`webcal://` too), or from CalDAV accounts (calendars discovered via
  `current-user-principal` / `calendar-home-set` / `.well-known/caldav`, pick which to show), read-only next to the
  tasks in month / week / day view and the calendar timeline, plus an optional *Events today* block on *Today*
  (per user, on by default). Events are tinted and outlined in the calendar's colour, all-day ones in the all-day row;
  a click shows a popover (time, place, description as escaped plain text with http / https links, calendar) with
  *Create task from event*. Per calendar: name, colour, show / hide, refresh every 15 or 60 minutes, last sync and
  error, *Refresh now*, edit, remove. Private per user, cached for offline use.
- Server-side sync every 15 / 60 minutes (window: 60 days back, 365 ahead): RRULE / RDATE / EXDATE / RECURRENCE-ID,
  time zones, floating times, cancelled events; ETag / If-Modified-Since for ICS, getctag / sync-token for CalDAV; at
  most 10 MB per download and 5,000 occurrences per calendar; sub-daily and never-matching rules are not expanded.
- SSRF guard for these fetches: private, loopback, link-local, CGNAT, multicast and reserved addresses (IPv4 / IPv6,
  mapped forms) are refused at connect time and the checked address is the one connected to (no DNS rebinding);
  admins can allow internal hosts (*Settings > Users > Whole server > Allowed internal calendar hosts*,
  `KALMIDO_CALENDAR_ALLOW_HOSTS`); changes to that list raise a security alert.
- Links and CalDAV passwords are stored encrypted (AES-GCM) and never returned to the browser; five failed syncs in a
  row raise an *Integration problems* admin alert (id, user, error class only).
- `KALMIDO_CALENDARS=0` turns the feature off; `KALMIDO_CALENDAR_MAX_MB`, `KALMIDO_CALENDAR_MAX_EVENTS`,
  `KALMIDO_CALENDAR_RATE` tune the limits.
- Tests: `calendars_test.py` and `calendars_ui.js` with a fake ICS / CalDAV server (`stub_calendar.py`).

### Changed
- The image installs `icalendar`, `recurring-ical-events` (+ `x-wr-timezone`, `click`), all pinned.
- Calendar subscriptions: show ICS/CalDAV events next to tasks

## [1.1.5] - 2026-09-27

### Added
- *Settings > Help* links to the website (kalmido.com), the source code on GitHub and *Report a problem* (GitHub
  issues), each in a new tab without opener or referrer; the command palette has *Open website* and *Report a problem*.
- CI: a failing test suite also shows as an annotation on the run page.
- Help: links to the website, GitHub and issue tracker

## [1.1.4] - 2026-09-27

### Added
- Admin alerts via ntfy (*Settings > Users > Whole server > Admin alerts*, admins only): operational warnings go to
  the admins, independent of their own notification channel: update available (once per version), Web Push delivery
  problems (device removed after 404 / 410 or repeated 4xx, pushes falling back to ntfy), watchdog errors (skipped
  rows per hour with their ids), integration problems (ntfy share inbox refused / unreachable, Paperless failing for
  N minutes, ntfy or Web Push failing five times in a row), security events (failed-login bursts and rate-limit trips
  per user / IP, invalid `/drop` or calendar feed token bursts, a new admin, changed server switches) and storage /
  health (low disk space, daily `PRAGMA quick_check`, attachment folder errors). Each kind can be switched off; each
  admin's own topic or one shared admin topic; priority; *Send test alert*; cooldown per identical alert (6 h), at
  most N per hour (10), or one daily summary; the last 50 alerts are listed with their delivery state. Alerts never
  carry task titles, comments or other content. `KALMIDO_ADMIN_ALERTS=0` turns them off, `KALMIDO_ADMIN_TOPIC` fixes
  the topic, `KALMIDO_ADMIN_ALERT_WINDOW` sets the aggregation window.
- Tests: `admin_alerts_test.py` and `admin_alerts_ui.js`; the other suites run with `KALMIDO_ADMIN_ALERTS=0`.
- `tools/i18n_check.py` knows `Nn_("one", "other")` (plural texts translated later with `trn`).
- Admin alerts via ntfy

## [1.1.3] - 2026-09-27

### Added
- Web Push notifications, no extra app needed: *Settings > Notifications > Notify on this device* (per device, the
  browser asks for permission once), a list of your devices with remove, *Send test to this device*. Works in Chrome,
  Edge, Samsung Internet, Opera, Firefox and Safari; on iPhone / iPad in the app added to the Home Screen (iOS 16.4+,
  the settings show a hint otherwise). Every push kind uses it: reminders (with *Done* and *Snooze* buttons; *Done*
  completes the task in the background), digest, focus / break end, habits, time tracking, comments, mentions,
  assignments, completions, unblocked tasks, test. Payloads are end-to-end encrypted (RFC 8291) and signed with the
  server's own VAPID key (RFC 8292, created on the first start); the server only sends to an allow-list of known push
  services (`KALMIDO_WEBPUSH_HOSTS` adds more, `KALMIDO_WEBPUSH=0` turns Web Push off, `KALMIDO_VAPID_SUBJECT` sets the
  contact).
- Channel per account: Web Push (default), ntfy or both. While no device is subscribed, or none accepts a push, it
  goes to the ntfy topic instead ("No device subscribed yet — using ntfy for now"), so nothing is lost when switching.

### Changed
- Existing accounts move to the Web Push channel too; they keep getting ntfy until their first device is subscribed.
- The accent color Amber is now Orange (dark `#fb923c`, light `#ad4c07`, WCAG AA in both themes, clearly apart from
  the red of high priority). A stored Amber choice becomes Orange automatically.
- The image needs `cryptography` (pinned) for the Web Push encryption.
- Reverse proxy: `/static/badge-96.png` (the notification badge) belongs to the paths fetched without login.
- Web Push notifications (no extra app needed), alongside ntfy

## [1.1.2] - 2026-09-27

### Added
- Settings > Appearance collects every visual setting of the device, applied instantly: color scheme, density
  (both moved here from General), font size (small, normal, large, extra large = 90 / 100 / 112 / 125 %; the whole
  interface scales: text, rows, icons, spacing, dialogs, calendar grid and charts), font (Geist, the system font or
  Atkinson Hyperlegible, bundled) and accent color (mint, sky, violet, rose, amber, lime; each tuned for the dark
  and the light theme, WCAG AA). Live preview and "Reset to defaults". The dates, times, counters and tags stay in
  Geist Mono; the app icon stays mint.
- Command palette: color scheme, font size (larger / smaller / a size), font, accent color and "Reset appearance".

### Changed
- All sizes in the stylesheet are now rem based (1rem = 16px x font size setting).
- Appearance tab: font size, font (Geist, system, Atkinson Hyperlegible), accent colours, theme and density

## [1.1.1] - 2026-09-27

- Docs: screenshots in the new look

## [1.1.0] - 2026-09-27

### Changed
- New look, same layout: Geist and Geist Mono (bundled, no external requests), denser rows with a priority bar
  on the left edge, square checkboxes, hairline separators, date / list / assignee / time as right-aligned
  columns on desktop, cooler greys, tuned dark and light themes (WCAG AA).
- Density per device: compact (desktop default) or comfortable (phone default), Settings > General.

### Added
- Command palette (Ctrl/Cmd+K): fuzzy search over tasks, lists, filters, tags, views, settings and actions,
  actions on the selected task (complete, snooze, date, move, priority, focus, timer), recent items; text
  without a match becomes a new task.
- Keyboard shortcuts overlay (`?`), list navigation (`j` / `k`, Enter, `x`, `s`, `d`, `m`), `g` go-to keys.
- New accounts get a "Getting started" list (in their language, for their device and modules) and a short
  welcome tour, restartable under Settings > Help. Existing accounts are unchanged. `KALMIDO_ONBOARDING=0`
  turns both off.
- The sloth celebrates an emptied Today and completed lists or projects (swing, checkmark confetti, a dry
  one-liner in English or German). Settings > General > "Celebrate completions"; reduced motion shows a
  calm version.
- v1.1.0: new look (Geist, compact), command palette and shortcuts, onboarding list and welcome tour, sloth celebration

## [1.0.0] - 2026-09-27

The first versioned release. Everything below was built before 1.0.0 and is included.

### Tasks and views
- Lists with emoji and colour, folders, sections (Kanban columns), archive; subtasks up to three levels with
  drag and drop between lists and levels.
- Priorities, tags, pins, Markdown notes, attachments, a website link per task.
- Natural-language quick add in English and German (`Dentist tomorrow 3pm !high #private ~Work`).
- Recurring tasks (daily to yearly, any RRULE) with end date, count and skip.
- Smart lists, combinable filters, multi-select with batch actions, snooze, trash, search.
- Undo for completing, reopening, deleting, moving, snoozing and batch actions (also offline).
- Templates for tasks (with subtasks) and whole lists, dates relative to the day of use.
- Calendar (month, week, day), timeline, Eisenhower matrix, Kanban, statistics for the last 12 weeks.

### Habits, focus and time
- Habits per day or n times per week, counters, notes, streaks.
- Pomodoro timer and stopwatch, focus minutes per task.
- Time tracking: timers that follow you across devices, manual entries, reports per list / task / day /
  person, rounding, hourly rates, CSV export, printable timesheet, reminders for forgotten timers.

### Together
- Several users with their own inbox, habits, filters, tags, settings and notifications; built-in login or
  single sign-on through a trusted reverse proxy header.
- Shared lists (edit or view only), assignment, comments with @mentions and files, activity history,
  unread markers, a News inbox, bundled push notifications.
- Projects: dependencies ("waiting on"), progress and status per list, the *Where is it stuck?* overview,
  custom fields (text, number, selection, date, checkbox, person, link).

### Everywhere
- Installable web app (PWA) that works offline: changes queue up and sync later, with conflict detection.
- Push notifications via ntfy, calendar subscription (ICS feed), sharing from Android, app shortcuts.
- Optional Paperless-ngx integration, TickTick CSV import, JSON export.
- English and German interface; translations are plain JSON files with a checker.

### New in 1.0.0
- **Version and update check:** *Settings > Help* shows the version. Admins get a daily, server-side check
  against the latest GitHub release (a dot on the settings gear and the update commands when a new version
  is out). Nothing is installed automatically and the browser never contacts GitHub. Off with
  `KALMIDO_UPDATE_CHECK=0` or in *Settings > Users > Whole server*.
- **Instance switches** for admins (*Settings > Users > Whole server*): *Collaboration for everyone* and
  *Time tracking for everyone*. Off means nobody gets that feature and its API endpoints refuse; running
  timers are stopped at that moment; nothing is deleted and everything comes back when switched on.
- **Settings > Collaboration:** the personal collaboration switch moved out of *Layout* into its own tab.
- **First-run setup, step 2 "What do you want to use?":** presets *Just me* (no collaboration, no time
  tracking) and *Everything*, then fine-tuning per module and the language. The choices set the instance
  switches and the modules of new users. When an admin later creates the second user while collaboration is
  off, Kalmido offers to turn it on.
- Prebuilt multi-arch images (amd64, arm64) on `ghcr.io/gegenschuss/kalmido`, released automatically from
  version tags; the installer uses them and falls back to building locally.
- Tests and CI in the repository: API, UI (jsdom) and security regression suites, `bandit`, `pip-audit`,
  `semgrep`, OWASP ZAP baseline. `SECURITY.md`, `CONTRIBUTING.md`, issue and pull request templates.

### Security
Before 1.0.0 an independent AI security review (separate agent, black-box testing plus code review) was run.
All findings were fixed, re-verified and are covered by `tests/security_test.py`:
- **High:** the ntfy share inbox could be abused for SSRF / local file reads and could leak its token:
  attachments are now only fetched from the configured ntfy server (allow-list), through a request wrapper
  that allows http/https only and same-host redirects; the inbox refuses a guessable topic on the public
  ntfy.sh.
- **High:** Paperless-ngx was reachable for every user: access is now granted per user by an admin (admins by
  default); users without access see neither titles nor document ids of linked documents.
- **Medium:** strict server-side validation of dates, times, durations, reminders, colours, views and folder
  names (malformed values could break the reminder watchdog or inject HTML); recurrence rules are limited
  (no sub-daily rules, rules that never match are refused); parent cycles are impossible.
- **Medium:** the Markdown renderer no longer allows attribute breakouts in links.
- **Low:** dependency updates (Flask, Werkzeug, Waitress pinned to fixed versions), constant-time login for
  unknown users, additional security headers (CSP `frame-ancestors`, `base-uri`, `form-action`, `object-src`,
  `X-Frame-Options`, `Permissions-Policy`).
- Design fixes: members of a shared list can no longer move shared tasks out of reach of the owner or delete
  them permanently; renaming a task no longer updates the title snapshot in time entries of people who lost
  access.

[Unreleased]: https://github.com/Gegenschuss/kalmido/compare/v2.88.1...HEAD
[2.88.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.88.1
[2.80.3]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.80.3
[2.80.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.80.1
[2.41.2]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.41.2
[2.41.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.41.1
[2.41.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.41.0
[2.40.2]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.40.2
[2.40.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.40.1
[2.39.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.39.0
[2.38.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.38.0
[2.37.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.37.1
[2.37.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.37.0
[2.36.2]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.36.2
[2.36.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.36.1
[2.36.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.36.0
[2.35.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.35.0
[2.34.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.34.0
[2.33.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.33.0
[2.32.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.32.0
[2.31.2]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.31.2
[2.31.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.31.1
[2.31.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.31.0
[2.30.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.30.0
[2.29.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.29.0
[2.28.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.28.0
[2.27.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.27.0
[2.26.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.26.1
[2.26.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.26.0
[2.25.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.25.0
[2.24.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.24.1
[2.24.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.24.0
[2.23.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.23.0
[2.22.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.22.0
[2.21.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.21.0
[2.20.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.20.0
[2.19.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.19.1
[2.19.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.19.0
[2.18.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.18.0
[2.17.2]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.17.2
[2.17.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.17.1
[2.17.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.17.0
[2.16.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.16.1
[2.16.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.16.0
[2.15.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.15.1
[2.15.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.15.0
[2.14.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.14.0
[2.13.4]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.13.4
[2.13.3]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.13.3
[2.13.2]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.13.2
[2.13.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.13.1
[2.13.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.13.0
[2.12.2]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.12.2
[2.12.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.12.1
[2.12.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.12.0
[2.11.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.11.0
[2.10.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.10.0
[2.9.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.9.0
[2.8.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.8.0
[2.7.2]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.7.2
[2.7.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.7.1
[2.7.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.7.0
[2.6.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.6.1
[2.6.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.6.0
[2.5.2]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.5.2
[2.5.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.5.1
[2.5.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.5.0
