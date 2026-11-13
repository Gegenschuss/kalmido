# Changelog

All notable changes to Kalmido are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Kalmido uses
[semantic versioning](https://semver.org/): every published change gets at least a new patch version, new features a
minor one. Releases in which operators have to do something carry a fixed section "Action needed"; the update notice
in Settings > Help shows that section of the target version.

## Older versions

- [2.1000-2.1099](docs/changelog/2.1000-2.1099.md)
- [2.900-2.999](docs/changelog/2.900-2.999.md)
- [2.800-2.899](docs/changelog/2.800-2.899.md)
- [2.700-2.799](docs/changelog/2.700-2.799.md)
- [2.600-2.699](docs/changelog/2.600-2.699.md)
- [2.500-2.599](docs/changelog/2.500-2.599.md)
- [2.400-2.499](docs/changelog/2.400-2.499.md)
- [2.300-2.399](docs/changelog/2.300-2.399.md)
- [2.200-2.299](docs/changelog/2.200-2.299.md)
- [2.100-2.199](docs/changelog/2.100-2.199.md)
- [2.0-2.99](docs/changelog/2.0-2.99.md)
- [1.x](docs/changelog/1.x.md)

## [2.1104.0] - 2026-11-13

Package 2.1101 (Bündel: Altspalten obj_history / obj_undo / obj_revoked au).
### Changed
- The shared core's own tables take real column types: `obj_history.created_at` / `updated_at`, `obj_undo.created_at` and `obj_revoked.created_at` are `TIMESTAMPTZ`, `vals_before` / `vals_after` / `snap` / `row_json` are `JSONB`. A new database makes them so at once; `kalmido/core/objretype.py` moves an older database at its next start (a readable time / JSON is kept, an unreadable time becomes the start's time, a broken JSON `{}`), each column in its own step, and raises the database's back limit. The history merge of a folder rename (`obj_history_add_many`) and the list lock's search in undo copies work on the new types; the merge window is compared as a point in time. Lines taken out of `tools/coltypes_baseline.txt` (#5954).
- One way: after the first start of this version an older version refuses to start on the database (back limit); going back needs the backup taken before the update (#5954).

Package 2.1102.0 (Sammel-Fix: red suites of the CI).
### Fixed
- #5957: the chat window keeps your own messages at the right edge again (the reading column of #5903 is not used in the small chat window) - CI red p2365_a_ui
- #5704: dragging an event in the calendar while the events reload no longer loses the drag (end time at the pointer, the next click works); the grid is drawn after the drop - CI red p252_a_ui
- #5955: the command search lists the Inbox as first view again; Help comes after the views - CI red p181_ui
- #5956: the header menu "…" keeps archive and delete last and set apart; "Help for this area" comes before them - CI red p2310_c_ui
- #5137: /api/state no longer reads the signed-in person's own data lock as system on every request (back to at most 4 set_config) - CI red p2369_6_api
- #5908: the News test follows the folded History of #5807/#5808 (owner change as bundle "you own it now") - CI red p212_ui
- #4744: the toast-above-sheet test waits for the frame in which the toast is placed - CI red p2130_ui
- #5516: "bars are fitted after release" is only required when a watcher still waited at release - CI red p2586_a_dragperf_ui
- #5958: the search plan probe recognises the search statement after #5655 added ", id DESC" - CI red p2695_l_search_rls

### Fixed
- main: the backup suite tests the zip bomb check again instead of the size limit - the bomb member comes before the database dump (CI red of 2.1086.0)

Package 2.1088 (Bündel: Seitenleiste Android: letzter Eintrag (Kassenbuch), Sammelpaket: Aufgaben ohne Paket (Dispatcher), Glocke: Bündel einer Agenten-Frag).
### Fixed
- News / bell: an entry that stands alone in its bundle shows its note again, e.g. the note of a project's status change ("Vendor is late"), hidden since the bundled view (#5938).
- News / bell: a bundle of an agent's question says "waits for your answer" under its title instead of only the time (#5873).
### Changed
- Agent approvals: the card of an upload names the files it binds (count and the first three names, "and N more"), visible without unfolding; no hash shown (#5937).
- Tests: a guard test checks that the phone's drawer ends above its foot (Settings + account) at 320, 360 and 460 px; no app change was needed (#5894 checked).

Tool package: a smoother flow - list suites from the code, lint per finding, flaky suites in quarantine (job/4314).
### Changed
- Tests, row-level security: `kalmido/core/rls.py` no longer reads a hand-kept table list - every table with an `org_id` gets its policy from the database itself; `tests/rls_static_test.py` checks that property in the code, `tests/rls_direct_test.py` that every such table of a fresh database has ENABLE + FORCE and its policy.
- Tests, coverage tables (`tenant_coverage`, `freelancer_coverage`): a new route whose neighbour routes all share one matrix kind takes that kind without a table line (and with it the duty of a cross-tenant probe / a freelancer call); a table line of a gone route or an unused kind is a hint.
- Tests, freelancer sweep (`p287b_a_freelancer_api`): a 400 / 404 on a route without an own object in its address passes when an organisation's admin gets the same answer (status and body) - no `QUERY` / `EXPECT_4XX` line needed for it; the sweep covers inherited routes too.
- Tests: the OpenAPI comparison of `api_v1` ignores placeholder names; `p211_ui` checks the notification rows as a property instead of a fixed number.
- `tools/check_glossar.py --fix` writes missing lines of `docs/GLOSSAR.md` from each file's header comment.
- Lint: `tools/check_layers.py` keeps its function-local imports per finding in `tools/layers_baseline.json` (replaces the totals of `tools/layers_budget.json`): only a new finding is red, a fixed one is a note. Stale baseline lines of `check_coltypes`, `check_trh` and `check_core_crosscut` are notes (red with `--strict`).
- Tests: `tests/skip.txt` is the quarantine of proven flaky suites - `tests/run_all.sh` runs them, their red does not count (reported as "QUARANTINE red" with an annotation), their green is reported; the date of a line no longer ends it. Rights, encryption, login and invoice suites never go quiet (`tests/quarantine_never.txt`).

Package 2.1076 (Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- Shared core for links between items (`obj_links`, core stage Q3): one table, one rights check for both sides (write on the source, read on the target, same workspace), the end-to-end lock and "target deleted" decided once in the core, unlink goes to the trash and onto the personal undo list; general routes `/api/obj/<kind>/<id>/links`, API v1 `/api/v1/agent/objects/<kind>/<id>/links` and the MCP tools `list_links`, `link_objects`, `unlink_objects` (#5271).
### Changed
- Mail links, device links, contact links and letter links now live in the shared link core; the area routes and answers stay the same, exports keep their file names and columns, unlinking a letter link is undone from the undo list instead of the office trash (#5271).
- Office: empty, loading, failed and no-access states come from the same block as the lists - a load error shows the reason and "Try again" instead of looking empty, one wording for "nothing matches", an empty office shows a real empty state on Receipts (no filter block) and on the figures (no empty axis), the start page keeps room for "bookings without a receipt" while loading, Correspondence appears in the menu only for the admin role (#5450).
### Fixed
- Contact merge overview names event attendances again (#5271).
- Links (review of the package): links stay inside one workspace for files, pages and tables too; an agent needs the read scope of the other side (events: `calendar`) to link, list or unlink; a deleted other side shows only "gone" without kind or id; permanently deleting an item removes its links for every kind (#5271).

One-way step: the old tables `hub_mail_links`, `life_device_links`, `contact_tasks` and `office_letter_links` are dropped after their rows are copied into `obj_links`; an older image no longer starts on that database (#5271).

Package 2.1091 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Changed
- Phone sidebar: a light shadow over the foot (Settings + account) shows that more entries follow below; it disappears at the end of the list and is missing when the list fits the screen. Computer sidebar unchanged (#5896).

Package 2.1090 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Hilfe in der App Stufe 2: „So geht's“ für die übri, Hilfe in der App: „Zeig mir“-Knop).
### Added
- Help: a help topic that marks the places of its way shows a "Show me" button under its text - it opens the spotlight of "Show me" step by step (the places' own headings), Close comes back to the topic; a topic marks one place per step (#5899).
### Added
- Help: "How to" topics for six more areas - Knowledge pages, Tables, Team chat, Budget, Lists and Sharing (14 topics in all languages), with "Show me" places for a new page, a new table, a new message and a new budget (#5900).
### Changed
- Help: the topics' named places now point at places the app knows (the scan inbox: settings, Integrations, the scan inbox; a new event, a new quotation, a new invoice, adding a task, adding documents); `tools/check_userhelp.py` reads the keys of `docs/help-targets.json` and turns an unknown place red instead of warning (#5899).
- Tests, row-level security: `tests/rls_static_test.py` keeps the tables whose `org_id` may be NULL as a decision with a reason; a new nullable `org_id` is red until it is listed there (or gets NOT NULL) (#5942).
### Removed
- The dead hand-kept table list `TABLES` (and `DROPPED`) in `kalmido/core/rls.py` and `LEGACY_COUNT` in `tests/tenant_coverage_test.py` (nobody reads them since the policies follow the database) (#5941).
### Fixed
- Tests: `p272_ui` follows the agent card of 2.1044 - on the agents page an admin's agent picture opens the agent's settings; the agent's person card is checked on the picture in the chat header (#5898).

Package 2.1092 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Changed
- Self-hosting, database: the `db` service of docker-compose.yml runs `postgres:17.12` instead of the moving `postgres:17` tag. This line is the one place of Kalmido's PostgreSQL version: the CI, the test start (tests/start.sh), the test helpers and the Mac run read it (tools/pg_image.py), the Dockerfile's `ARG PG_VERSION` and the uninstall text of the installers follow it. A new minor version of PostgreSQL now comes with a Kalmido update (`python3 tools/pg_image.py --set X.Y`), pulling images never moves the database on its own (#5948).
- App image: `pg_dump` / `pg_restore` come from the PostgreSQL project's own packages (PGDG, signing key in tools/pgdg-ACCC4CF8.asc) instead of Debian's, and the build stops when `pg_dump` is older than `PG_VERSION`: the backup tool is never older than the database server. Debian's client was 17.11 while `postgres:17` had moved to 17.12, which turned backups red in the CI only (#5948).

### Fixed
- CI lint: a new step `tools/pg_image.py --check` fails on any bare `postgres:<major>` tag and on any other version than docker-compose.yml (changelogs excepted); tests/p5948_pg_image_test.py (#5948).

Package 2.1094 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Fixed
- Office: the side paths say a failed load with the reason and "Try again" instead of quietly showing nothing or an empty list: suggested payments of agents, the import page (runs, counter, file name templates, clients), the own travel purposes and the entertainment places / people in the settings, "Paid with" of an entertainment receipt, the receipt search of the walk-through, the signature links of a document, the receipts handed in by members, the references, document search and history of a letter (#5902).
- Office: the terms and conditions (AGB) and the country choice of a new office no longer stay on "Loading…" or say "No terms and conditions yet" when loading failed; their loading text is the one loading block (#5902).
- Office menu: the role Bookkeeping without an office group (previous access) sees the areas it may read again - Bookkeeping, Bank, Receipts and the other money areas were missing; Correspondence stays for admins (#5902).

Package 2.1093 (Bündel: Bündel: CI-only rot: p21382_b_ui, CI-only rot: p2742_c_tagpills_ui, Geteilte Ansicht reparieren: rechts die volle App  u. 2 weitere,).
### Changed
- Trash core, rest of stage 3: a folder taken into the file store's trash now takes its knowledge pages (with their files) and tables into the shared trash with who deleted it and a history entry, and brings them back on restore; undoing a new table, splitting a document stack, deleting a hub mail's folder, the file store's own undo, the sheet steps "add/delete sheet" and the undo of an account move all go through the shared trash instead of setting the deleted mark themselves (#5472).
- Retention: deleted page attachments and table files are now removed by the shared trash run (part kinds `wiki_file`, `sheet_file`); the separate runs of the pages' and tables' files are gone (#5472).
- Export register of the core (stage Q11): the shared core tables (`obj_*`) declare in one place where their rows go in the organisation, account and retention export and what the account import reads (`kalmido/core/objexport.py`, `obj_register(export=)`); their hand entries left the export lists, file names, columns and filters stay the same; `tools/check_export_tables.py` reports a core table without an entry, an entry twice or an entry also listed by hand (#5289).

Package 2.1097 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Changed
- Export register of the core, rest of stage Q11: the account export's queries of the shared core tables (comments, tags, follows, notification settings, reactions), the notes of single documents in a personal office's export and the import's list of what stays behind now come from the register (`kalmido/core/objexport.py` keywords `acct`, `acct_more`, `nodes`); files, columns and filters stay the same; `tools/check_export_tables.py` reports a part or name given both in the register and by hand (#5949).

Package 2.1100 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Fixed
- Wiki: files held when a space's lock was switched on are no longer deleted by the trash run once the space is open again; they stay for the people of the space at that time, like the held page versions (#5950).

Package 2.1078 (Bündel: Bündel: PDF-Vorschau: Grund und Leiste an die Design-Farbe, Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Fixed
- Agent approvals, hosted MCP: a refused step (`step_ref`) and the approved card of `use_approval` now belong to the access of the connection, not to one access token or one `/mcp` request: they survive a token refresh and the next request, and end with the access; a step whose body is longer than a card binds (32,000 characters) gets no `step_ref` and says so (#5866).
- Agent approvals: the refusal of an upload (multipart with files) sends the agent the header way (`X-Kalmido-Approval`, MCP `use_approval`) with `error.run: "header"` instead of the card run, which cannot send files (#5866).
- Agent approvals: a card step path that still holds a `%` after decoding is refused with 400 (the run decoded it a second time) (#5866).
- Agent data lock: read as system, so a request outside the agent's organisation gets the agent's real lock instead of the open defaults (#5866).

Package 2.1084 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Fixed
- Upgrade test (p2192_c_upgrade): the "migrations ran" check no longer demands a log line when the jump brings only new tables; it now matches the logged step count to the MIGRATIONS steps recorded at this start (the upgrade probe from live v2.1067.0 was a false alarm) (#5916)

Package 2.1081 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Changed
- Agent chat and team chat use the full width from 768 px (open Fold, tablet, computer): header, switch row and composer reach both edges of the view next to the lists, the messages stay in a reading column in the middle; the team chat without conversations no longer shrinks to its content (#5903).
- Menus glide: on a computer a menu unfolds under its button (a little from above with fading in, 0.15 s) and goes back the same way, on a phone the menu sheet slides up from the bottom in 0.2 s and down again; with "reduce motion" a menu only fades in. Only the menu moves (#5901).
- Knowledge: a folder that has a page of the same name (page "A" with subpages "A/…", e.g. from a SilverBullet import) shows once in the folder list and in the panel, as the folder row with a small page mark; opening it shows the page's text on top ("Edit" opens the page) and the subfolders and subpages below. The narrow view's tree, search and [[A]] links still open the page (#5907).

Package 2.1085 (Bündel: Agenten-Freigaben: Upload-Karte bindet auch den Da).
### Security
- Agent approvals: an approval card for an upload now binds the files too - `approval.body._files` lists form field, name and SHA-256 of each file (a form field named `_files` is refused); after the Yes only exactly these files go through with `X-Kalmido-Approval` (other content: `409 approval_invalid`, reason `body`, field `_files`), and a run from the card answers reason `upload` (#5936).

Package 2.1079 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Sammelpaket: Aufgaben ).

### Fixed
- Search: hits changed in the same second keep one fixed order (newest first) on every answer, so the results no longer reshuffle under the reader when a hit is edited (#5655).
- Start-up: applying the row-level security policies next to a running server locks all tables in one step and gives way instead of dying in a deadlock (#5654).
- MCP: `wiki_append` belongs to the toolset `wiki`; with `--toolsets` / `KALMIDO_TOOLSETS` it no longer leaked into every other toolset (#5095).
- Row-level security list: the dropped office trash table is marked as dropped at start-up; two system contexts carry their reason (#5683).
- Tests follow the bell of #5806 (a person's comment on my own task waits for me): p262_b_api, p21037_b_bell_ui, p21052_news_one_ui, p2170_ui, p2102_b_ui and the other News suites (#5912 #5905 #5906 #5477 #5904 #5911 #4737).
- Test stability: p2220_b_focus_ui, p2115_b_api, p2905_b_docview, p2924_c_ruhe_ui, p265_b_ui, p2353_e_setsearch_guard (#5423 #5640 #5642 #5655 #5913 #5910).

### Fixed
- main: backups made against PostgreSQL 17.12 or newer with an older `pg_dump` were refused at check and restore as "unexpected objects" - the column version key `pg_attver` of PostgreSQL 17.12, written out by an older `pg_dump`, is now accepted in exactly that form (the server drops it); every other column option stays refused (CI red of 2.1077.0, #3506).

Package 2.1086 (Bündel: Agenten: „Zeig mir“ - der Agent öffnet die passend, Hilfe in der App: je Bereich „So geht's“ auf Deuts).
### Added
- #5820 Help in the app, stage 1: "How to" sections in plain words for files / documents (incl. setting up a scan inbox), agents, office (quotations, invoices), tasks and calendar - the same text agents read through `search_help` / `read_help` (they now get the user's sections first, with the translation). The English text lives in the docs (`<!-- user-help: area -->`), translations in `docs/help/<lang>.md` with a fingerprint of the English text. The app shows them under "Help": the command search (entry "Help" plus one entry per topic, e.g. "Scan" finds "Set up a scan inbox"), "Help for this area" in the "…" menu, "How to" links in the empty states of projects, the filing and the documents, and Settings > Help. New session routes `GET /api/help` and `GET /api/help/section`; the app's search kind `help`. New lint `tools/check_userhelp.py` (CI): a bold menu item that is no longer a text of the interface, a missing or outdated translation or an unknown "Show me" place is red.
- #5860 Agents: "Show me" - an agent's chat message can carry `show: [{target, text}]` (API v1 chat, MCP `send_chat`); the app shows a "Show me" button that opens the view and highlights the control the person presses next with the tour's spotlight and the agent's line, step by step (Next / Back / Done / Close, Escape, the phone's back button). It never clicks, switches or saves anything. Places come only from the fixed list `docs/help-targets.json` (unknown key = 400); `help_overview` lists them (`show_targets`), `read_help` names a section's places (`show`). A missing control (phone, no right, area off) says so in one line. New column `agent_chat.show_steps` (JSONB). The tour and "Show me" share one spotlight.
### Fixed
- #5861 follow-up: `wiki_append` belongs to the MCP toolset "wiki" (p2391_b_toolsets was red on main).

Package 2.1077 (Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Sammelpaket: A).
### Added
- Lint `tools/check_notify_calls.py`: a new direct call of `notif_ok(` or `news_put(` outside `core/objnotify.py` and `collab/news.py` is red (send through `obj_notify`, rights first); the existing ones stand per file in `tools/notify_calls_baseline.json`, which only shrinks; CI step and suite `p21077_a_notifylint` (#5459).
### Changed
- Calendar: loading, empty and error states come from the shared block. While the shown range loads, a quiet "Loading…" floats over the grid; a failed load says "Events could not be loaded" with "Try again" instead of looking like an empty month (and is not fetched again on every drawing); offline with a saved copy the view says it shows the saved copy. An empty week, day or year says "Nothing planned …"; the agenda's "nothing" is the shared block (#5461).
- Calendar month: the day list under the month no longer says "No tasks on this day" next to that day's events ("Nothing planned on this day." only when the day is empty), and turning the month moves it along (the 1st of the month, today in the current month) instead of showing "Today" under another month (#5461).
### Fixed
- Event editor: a refused save opens the editor again with what was typed and now says "Not saved: …" with the reason above its buttons (#5461).
- Calendars window: opens at once instead of waiting silently for the people list (only "Share…" waits for it); a calendar trash that failed to load says so with "Try again" instead of "The trash is empty"; Settings > Calendars and the absences subscription link say a failed load with "Try again" instead of always "Only available online." (#5461).

Package 2.1073 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Changed
- #5570: "Optimise PDF" goes page by page: each page (its measure, then the page with its text layer) is one step of its queue thread (#5412), the run's folder keeps the pages made so far between the steps. A restore no longer waits for the end of a long run, a restart between two pages no longer starts a run over, and a file put into the trash mid-run cleans up at once. The run's time limit counts over all its steps; GET `/api/docs/<id>/pdfopt` names how far a run got (`step: [done, all]`).
- #5865: the old table of office trash copies (`office_trash`) is gone. Every start writes copies of an older database back into the shared trash first, then drops the table; copies that could not come back go with it (the log names their number). The key rotation, encrypt-all / decrypt-all and the terms clean-up no longer walk those copies.

Package 2.1068 (Bündel: Freigabe-Karte eines Agenten zeigt bei Textänderun, Agenten-Werkzeug: Text an eine Wissensseite anhäng).
### Added
- #5831 An agent's approval card that changes a text (knowledge page, task notes, project description, comment) shows the change itself: folded one line in words ("Knowledge page Wiki/2D: 1 line added, nothing removed"), unfolded the removed and added lines with + / − and two lines around each change, "Show everything" for long ones. The server reckons it from the card's bound step against the text now, with the rights of the person who looks (`GET /api/approvals/diff`); a target changed since the card is marked, an unreadable or encrypted one shows no lines, and after the answer the card keeps the change as it was then. The technical "Step: …" line moved into the fold for every card.
- #5829 `wiki_append` / `POST /api/v1/wiki/pages/{id}/append` takes `under` (a heading of the page): the text goes to the end of that section; an unknown heading answers 404 `heading_not_found` with the page's headings and writes nothing. `wiki_write` points to `wiki_append` for additions.
### Changed
- #5829 Appending puts exactly one empty line between the page and the new text (was one line break).

Package 2.1069 (Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Listen-Zustand: Kern-Papierkorb-Schreiber absicher).
### Changed
- #5412: "Optimise PDF" runs in a thread of its own next to the documents queue, so a long run (up to 30 minutes) no longer holds up the text recognition of newly uploaded documents (a new run starts once no document waits for its recognition); the queue serves the workspaces in turn, and besides the limit per person at most 200 runs wait per workspace (the automatic runs of new scans count only against the person) (then "Too many documents wait for optimising"), a selection skips the documents of a full workspace.
- #5416: the core's trash is guarded for every kind with the generic routes or the retention run (`obj_trash_cols_missing()`: a kind whose table lacks deleted_at / deleted_by is named by its suite); the lint `tools/check_list_state.py` also counts a handwritten compare on a project's state marker `lists.state` (only `core/access.py` writes it).

Package 2.1060 (Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Weich rot: p2100_ui, Weich rot: p2106_b_ui u. 18 weitere, Bündel: Bündel: Sam).
### Fixed
- Search in bookmarks, tasks, contacts, notes, events, letters and messages: words typed without a space between them (`page.html`, `anna@firma.de`, `Kick-off`) must stand next to each other again, as before the shared search index; with a space each word may stand anywhere (#5878).
- Quotations: a draft moved into the trash takes its open approval links with it, so a restored draft never brings back an old link; signing waits for the quotation's lock (the trash's order), a link decided meanwhile keeps the quotation out of the trash, a link gone with the draft redirects instead of an error (#5869).
- Agent approvals without a task: one News entry in the bell instead of two (#5870).
- Start state: the lean tasks filled back on the device carry exactly the fields of the whole state again (`rev`, `updated_by`, `deleted_by` no longer added) (#5875, #5184).
- Organisation invitations: the clean-up of expired invitations is one plain statement the schema check covers in full (#4949).
- Office and split view: the last pixel sizes in the style sheets are rem (#5676).
- Test suites follow the intended behaviour since earlier packages: the toast's Undo takes back exactly its own step (roadmap_ui #5625, p1_ui #5868), a deleted reminder draft lies in the trash (#5871), a guest's search finds the pages of the folder shared with them and never others (#5833), the install script's backup block (#5874), the service worker's language parts (#5877), the drag receivers of the favourites row and the split view (#5876), a docstring the rowid guard read as SQL (#5682).

Package 2.1075 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Fixed
- #5496: the retention report of the core's trash run (Settings > Data retention, run "obj_trash") counts what it really deleted: side objects (inbound webhooks, team chat tombstones, member memos, the copies of fields / sections / "Delete all times") are read again under a row lock before they go, so one restored between reading and deleting stays (it was deleted before) and is not counted; the attachments of deleted tasks are named again (`task_attachments`, with the switch off the ones that would go).

Package 2.1071 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- #5658 Sharing by e-mail address: a project, a folder of projects or a knowledge page shared with an address that has no account with a confirmed address yet is kept as an open invitation (the shared core's `obj_addr_shares`, `kalmido/core/addrshare.py`). It becomes the share as soon as the account of that address signs in with the address confirmed (or confirms it while signed in), made as the person who typed it in would make it then (their rights and the project's / folder's rules at that moment). The Share dialogs of a project and a folder list such invitations under the address field ("Invited: gets access once the address is confirmed") with a button to remove them (`GET /api/addr-shares`, `DELETE /api/addr-shares/{id}`); the knowledge page dialog lists them as a card with the address, like a share by address that found its account. The answer of the share stays the same for every address, also when a confirmed account does not fit (yet), e.g. outside the project's organisation: then the invitation waits the same way. Invitations nobody redeems go after 180 days; at most 50 per address.
### Security
- #5658 (Fable review 2.965 F2): the Share dialog of a knowledge page no longer shows a card only when the address belongs to a confirmed account (that told whether the address has an account): every address typed in shows its card.
- #5658 (Fable review 2.983 N2): changing the role of a table's share by address no longer lifts the role of an account the row was bound to before the address had to be confirmed: the row opens again and is redeemed at the next sign-in with the address confirmed.
- #5658: a table shared by address is redeemed right after the address is confirmed by its mailed link too, not only at the next sign-in.

Package 2.1074 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Changed
- #5493: undo across devices, stage 3c - a project's settings with side effects are server steps too (kind `listside`, `kalmido/lists/lpside.py`): folder (with the folder's adopted defaults), workspace, project type, agents (listening, tidying up, members' access, follow-up), client, Home & life (and a trip's dates), time tracking, ticket key and visibility in the organisation; ticket templates / types and properties saved together with them go back too. The step keeps the values before / after (also the ones the save changed as a side effect) and goes back through the project's own write path (`list_apply`, was the route body of `PATCH /api/lists/<id>`), so a workspace change brings back what it ended (client, links); a value changed elsewhere since stays and is named. "Recent steps" lists them on every device; the project dialog's Undo, Ctrl+Z and the workspace toast take back that server step (no second browser entry any more).
- #5493: a device's own undo / redo of a step without a server group sends `X-Kalmido-Undo-Own: 1` and records no new server step, so the way forward (redo) of the person's undone steps stays.
- #5493: the server labels a task's step as the app's history does ("Priority of “Jump”: High", "Renamed …", "Date of …: 4 Mar", "Moved …", the title in quotes; was "Edited Jump"); no project, section or field name goes into a label (a project locked later would keep it there).

## [2.1103.0] - 2026-11-13

Not released (the CI of this version was red); its changes are listed under 2.1104.0.

## [2.1100.0] - 2026-11-13

Not released (the CI of this version was red); its changes are listed under 2.1103.0.

[Unreleased]: https://github.com/Kalmido/kalmido/compare/v2.1104.0...HEAD
[2.1104.0]: https://github.com/Kalmido/kalmido/releases/tag/v2.1104.0
[2.1103.0]: https://github.com/Kalmido/kalmido/releases/tag/v2.1103.0
[2.1100.0]: https://github.com/Kalmido/kalmido/releases/tag/v2.1100.0
