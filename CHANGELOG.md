# Changelog

All notable changes to Kalmido are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Kalmido uses
[semantic versioning](https://semver.org/): every published change gets at least a new patch version, new features a
minor one. Releases in which operators have to do something carry a fixed section "Action needed"; the update notice
in Settings > Help shows that section of the target version.

## Older versions

- [2.600-2.699](docs/changelog/2.600-2.699.md)
- [2.500-2.599](docs/changelog/2.500-2.599.md)
- [2.400-2.499](docs/changelog/2.400-2.499.md)
- [2.300-2.399](docs/changelog/2.300-2.399.md)
- [2.200-2.299](docs/changelog/2.200-2.299.md)
- [2.100-2.199](docs/changelog/2.100-2.199.md)
- [2.0-2.99](docs/changelog/2.0-2.99.md)
- [1.x](docs/changelog/1.x.md)

## [2.761.0] - 2026-11-09

Package 2.742 (Bündel: Bündel: Teil 1/6: Sammelpaket: Aufgaben ohne Paket (Dispatcher), CI-only rot: p2191_c_perf, CI-only rot: p2290_c_fold_ui u. 1 weiter).

### Added
- Wide screens: Settings > Appearance > "Split view" (desktop with a mouse, from about 160 rem window width) shows a second copy of the app on the right; a grip in between moves to the neighbours' minimum width, "Open on the right" in the menus of a project, a task (More...), a document card, a knowledge page and the calendar; on / width / right page are remembered per person; off loads nothing (#4858).
- Documents, file store and bulk edit: tags are a pill field with its own suggestion list from the first letter (start matches first, match in bold, "New: ..." last), arrows + Enter / Tab take a suggestion, comma or Enter adds a new tag, Backspace in the empty field removes the last pill (#4862).
- Document preview: text of a PDF can be marked with the mouse and copied (a text layer over every drawn page, follows zoom); Cmd / Ctrl+A in the preview marks all pages; images and scanned PDFs show "Copy text" with the recognised text (#4861).
- Code integrity, step 1: every weekly release carries web-manifest-X.Y.Z.json with the full SHA-256 of every file the browser gets (as served, comments stripped), built twice in the CI and compared; a server shows the same values at GET /api/code-manifest without signing in (#5217).

### Changed
- Lists: dragged column widths are remembered per person on every device (not only in this browser) and have no upper limit any more, only the title keeps its minimum; "Reset settings" covers them (#4857).

### Fixed
- CI: the SQL check pg_prepare no longer takes translated texts or str.replace() pieces for statements and knows two stand-in exceptions (#4949).

Package 2.755 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Lint vor der CI: FK-Kommentar-Regel und nosham-Prü, Python-Linter Ruff als CI-Gate fü).
### Added
- Lint: tools/check_fk_comment.py (#2174 FK rule) and tools/check_nosham.py (checks that cannot fail) run in seconds without a database; the suites p2103_c_api and p2501_a_nosham call the same logic, so both stop turning red only in the full CI (#5261)
- Lint: tools/check_core_crosscut.py keeps links, tags, comments, read marks, versions and following in the shared core - a new per-area table of that kind is red; today's tables stand in tools/core_crosscut_allow.json with a reason; docs/dev/kern.md section "Cross-cutting parts" (#5267)
- Lint: tools/check_coltypes.py - new columns take TIMESTAMPTZ, BOOLEAN and JSONB instead of TEXT times, 0/1 numbers or JSON text; today's columns stand in tools/coltypes_baseline.txt, which only shrinks (#5305)
- Lint: ruff (E, F, BLE; ruff.toml) as a CI gate for new code only, findings of the existing code in tools/ruff_baseline.json (file, rule, hash of the line); the line length is a guide, not part of the gate; every silent `except Exception: pass` names its reason (#5294)
- SQL table and column names only through qi() with an allowlist (kalmido/core/pg.py); a semgrep rule (.semgrep/sql_ident.yml) flags new f-string SQL with FROM / JOIN / INTO / UPDATE / SET / TABLE / TRUNCATE / INDEX ON without qi(); existing places in the baseline (#5296)
- Indexes lists(deleted_at), fs_nodes(parent_id, deleted_at), list_activity(list_id, created_at) (#5299)
### Changed
- Office money: the plain money columns of document positions (net, tax), cash book and ledger entries become NUMERIC(14,2) at start when every value fits exactly; answers, exports and the hash chain keep the same two-place text; money convention in docs/dev/geld.md (#5293)
- Documents: the neighbour drawn ahead now has its receipt, letter and flow rows filled; the file store's full screen prepares its neighbours too - swiping shows the next document whole, without a placeholder (#5236)
### Fixed
- Tax return (UStVA): when the income statement basis changes between receipts and bank/cash at a year boundary, a receipt's input tax counts in exactly one year - the payment line's day decides at the edge; pure receipt years keep the receipt date (#5241)
- Deleted video and image review comments: a one-off clean-up removes those deleted before 08.11.2026 with their text and guest names; the trash purge and the org export already handled later ones and are now covered by tests (#5263)
- The dead table paperless_links is dropped (#5265)
- Orphaned agent owners repaired on old databases: the agent's private polls go into the trash, their links answer 404 (#4978)
- Document preview keeps its scrollbar's room, so the fit no longer changes after the pages arrive (CI red p2736_b_docswipe_seamless_ui at 460 px) (#5312)

Package 2.739 (Bündel: Job-Ansicht: Auftrag des Jobs als erste, eingeklap).

### Added
- Agent chat: the brief of a job. An agent can post the exact wording it gave a job (`POST /api/v1/agent/chats/{id}` with `kind: "brief"` and `job_id`, MCP `send_chat`, up to 60000 characters). It shows only in the job's own chat, as its first row and folded ("Job brief" / "Show the brief", Markdown); never in the whole chat or the message search, no push, never unread, cannot be pinned, does not end open answer buttons; a newer brief of the job replaces the older one. `GET /api/agents/{id}/chat?job=` carries it as `brief`. Older servers answer 400 (#5216)

Package 2.761 (Bündel: Teil 1/6: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Agenten-Seite: Job-K).

### Changed
- Documents: sender and document type use the same suggestion field as the tags (#4868) - from the first letter an own list
  of the known senders / types (the start first, then within), Enter, Tab or a tap takes one and saves; a new name still
  makes a new sender / type, a comma is part of a name, one value (no pills). The same field in the flows: "then sender",
  "then document type", "Sender is", "Document type is". Find it: open a document, type two letters into Sender.

### Added
- Code integrity stage 1b (#5218): every image and the `web-manifest-X.Y.Z.json` of a weekly release get a GitHub build
  attestation (Sigstore, keyless, public transparency log); check with `gh attestation verify` (docs/SELF-HOSTING.md,
  *Production updates*). The signing job of the weekly release has the OIDC token but no checkout and no shell.

## [2.759.0] - 2026-11-09

Package 2.386 (DATEV-Stapel: Bewirtungsbelege buchen).

### Added
- Office > Books > DATEV booking batch: approved entertainment receipts are booked (Belegfeld 1 "M<id>"): per VAT rate 70 % of the gross amount on "Entertainment (70 % deductible)" (SKR03 4650 / SKR04 6640) and 30 % on "not deductible" (4654 / 6644), both with the input tax key of the rate so the input tax counts in full; the tip without a key; a small business without any key. In a year on the basis "bank and cash" a meal is booked through its bank / cash / card line and that line's receipt stays out (#2328).
- DATEV settings, section "Receipts and travel expenses": the two accounts of the entertainment receipts can be changed (#2328).
- The check before the download names receipts of the category entertainment in the same period as "maybe booked twice"; they stay in the batch (#2328).

Package 2.695 (Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Teil 1/6: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: CI-only rot:).

### Changed
- Search: the task search and the comment search take the visible projects first (index on the project) instead of reading every task of the instance; under the row-level security of tasks and comments no text index can help (#4960).
- Long press: every row with a "…" button opens the same menu on a long press (phone) or a right click (computer), now also bookmarks, read later, table cards, own sections in "My tasks", the rows of the dialogs "Calendars" and "Address books" and the error reports of repositories; a coverage test makes a new "…" without it fail (#4619).

### Fixed
- Travel expenses from the trip planning: when somebody else already entered the travel expenses of a shared trip, the button now says so and points to entering your own in the office, instead of a bare refusal (#4958).
- Quotations: counting the tasks made from a quotation no longer notes a project access in the agents' access log (#4958).

Package 2.728 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Fixed
- Self-hosting, first start: the health check of the `db` service in docker-compose.yml checks the database over TCP (`pg_isready -h 127.0.0.1`). At its very first start the postgres:17 image runs a setup server on the socket only and then restarts it; the socket check reported that server as healthy, so Kalmido could start into the restart. The test start script (tests/start.sh) waits the same way instead of a fixed one-second pause and stops with the container log when the database never gets ready; tests/p2728_db_ready_tcp_test.py plays the setup server and its restart (#5188).

Package 2.735 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Fixed
- Office > Receipts, filters on phones (#5208): the segment buttons (Checked / Not checked, Paid / Not paid, Receipt date / Payment date) are no longer narrower than their label on touch screens of 320-460 px ("Ungeprüft" was 7 px wider than its button); each button now takes at least its label's width and the rest is shared.

## [2.756.0] - 2026-11-09

Package 2.625 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Changed
- Settings > Integrations: every integration is a folded row with icon, name and state (connected / not connected); opening it shows the form. The cards at the top, the search and other jumps open the matching row (#4489)
- Newsletter > New segment: groups, companies and address books are picked as condition rows (What / is or is not / value with a search) instead of one button per entry; "is not" excludes contacts; old segments stay unchanged (#4486)
- Tests: every suite writes a JUnit report (tests/.junit/<suite>.xml, a case per check), the CI uploads it per shard; the train's flaky detection reads it (#4005)
### Security
- Agent runner: permission answers travel over a local connection between runner and hook (Unix socket / named pipe, peer process check, key per run, one-time nonce per question); no answer file an agent could write any more. AGENT-SECURITY.md describes a separate OS user for the agent's tools (#3661)
- Scheduling polls: when a personal agent changes owner, its private polls move into the former owner's trash (read-only, links closed); the new owner only sees what the agent creates afterwards (#3961)

Package 2.637 (Bündel: Teil 1/6: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- #4745 Knowledge: "Offline available" per space in the space menu keeps all files of the space on the device (IndexedDB of this sign-in, never the service worker cache): size and free space are shown before switching on (too little space = a note, nothing loads), persistent storage is requested, loading runs in the background with progress (x of y files, MB), can be paused and resumes after a reload or a lost connection. The next online moment syncs new / changed files and removes deleted, trashed or no longer permitted ones; signing out or switching account removes the copy; switching off frees the space; a copy the browser cleared is marked honestly. Offline, file links and images open from the copy. New route GET /api/wiki/space-files (files of a space with size and checksum, rights as file access, no trash). Encrypted spaces take no files, so the switch is not offered there.
- #4768 Project rules: the due trigger takes a distance ("X days before the due date", 1-30, or "overdue for X days", 0-30), runs once per task and due day and again when the date moves; a rule runs up to 5 actions one after the other (all or nothing; a missing right pauses the whole rule as before; a move into another project only as the last action); optional conditions "Only if" (priority, assignee, project tag, section; all must hold). Existing rules run unchanged. Agent API, OpenAPI and MCP propose_rule take `actions` and `conditions`; account and organisation import / export map the ids inside the chain and the conditions.

Package 2.736 (Bündel: Dokumente: Wischen nahtlos - Nachbar-Dokument fert, Einstellungen: Android-Zurück geht zum vorigen Ber).
### Changed
- Documents: swiping to the next or previous document is seamless on touch screens - both direct neighbours are fetched and drawn ahead with all their fields and the preview in full size; after the snap the drawn view is simply swapped in: no request, no jumping picture, no text that appears later. Leafing on stops what is no direct neighbour any more; swiping back reuses the view just left. The PDF full view and the image viewer leaf the same way (#5212)
### Fixed
- Settings: the Back key (Android) and the arrow in the header go back to the area shown before (on a phone the overview, if you came from there), also after a search hit or a jump to another area; only the last Back closes the settings. Opening and closing a part inside an area is no step (#5214)
- Tests: the field trash column field_id carries its 'no FK' marker and the agent delete check in the field trash suite expects one status (403) - both guard suites were red on main (#4528)

Package 2.642 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- #4772 Client link of a video sign-off for clients without an account: several links per sign-off at once (at most 10), each with an optional expiry and its own switch-off (decided links too); the tick "The client may also see the older versions" makes older versions readable at `?v=<n>`; a new version keeps the link working and shows the client the new version while the earlier decision stays in the history (undoing the version gives it back); the client's name is entered once (cookie on the link's path); client comments show as "Name (Guest)" in the app. Images and PDFs on the client page follow in #5040.
- #4975 `KALMIDO_WEB_PROCS` (default 1): several web processes on one port (SO_REUSEPORT, Linux; otherwise one with a log line), threads and database pool shared out instead of multiplied, background work only in the first process, an ended process is started again (growing wait when it dies at once); restore and the connection check count the processes like `KALMIDO_REPLICAS`; `/api/admin/health` shows the answering process.
### Changed
- #4975 Calendar, contacts, newsletter and PDF text syncs take an advisory lock, so two processes or replicas never run the same sync twice; the hourly limits of uploads, form bytes and error reports are counted in the database for all processes (the first upload of an hour larger than `KALMIDO_UPLOAD_HOURLY_MB` is now refused as well); the printed first-start setup code is accepted by every web process of the container, an operator's code stays the only one.

## [2.749.0] - 2026-11-08

Package 2.583 (Bündel: Teil 1/6: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Teil 1/6: Sa).

### Added
- Documents: a document opens as its own view with its own address (#docs/<id>): head with back (Esc returns to the same place in the list), "3 of 128", arrows and the arrow keys through the current list, download / actions / delete; a foldable strip of neighbouring documents on the left; the fields in tabs (Details, Content, History, Shares) with rarer ones under "More fields", every change saved at once with undo; on the right every PDF page below each other, drawn sharp when scrolled to, zoom, width, whole page, full screen. Grips between the columns move to the edge. Phone: one column, preview on top, swipe as before. Replaces the pane, the phone sheet and the reading view (#4835, #4829).
- File store: one card and one sheet for files and documents - a file opens the same document view, a folder with recognition always shows document cards without a switch (#4832).
- Documents and file store cards: card size slider (7-28 rem) in the bar, Ctrl/Cmd + wheel, Ctrl + plus/minus and two fingers on the card area, remembered per person for computer and phone; small cards show only the picture, bigger ones load a sharper 800 px preview (new column doc_meta.thumb_l, filled for older documents in idle time) (#4812).
- Settings: each tab shows the often used settings first, the rest under "Further options" (open/closed remembered per person on all devices, the search opens it and highlights the field, "2 changed" when something under it differs from the start value); new route GET /api/settings/defaults (#4833).

### Changed
- Large screens: lists and overviews in every area (task lists, projects, start, office, contacts, statistics, time, agents, file store / documents, budget, bookmarks, tags, archive, waiting) use the full width of the content area; reading text and forms keep their widths (#4840).
- Task list rows behave like a table on wide lists: the title gets about 40 rem at most, text columns share the rest and grow instead of being cut, more columns stay in the first line, numbers align right; wider time / progress / created columns in the project list (#4840).
- Settings show one column of form width again on wide monitors; the wider dialog and the invoice editor side by side stay (#4833).

### Fixed
- A document card always shows its title in bold, the sender on its own line below (#4870).
- Documents show every date with its year (06.11.2026), no Today / weekday (#4877).
- Review: a locked or encrypted file reached by its address keeps its own way; the page count of a drawn PDF is capped; the 800 px preview has a file size cap (#4835, #4812).

Package 2.610 (Bündel: Releases für Selbst-Hoster: Tag-Version braucht ei, Sammelpaket: Aufgaben ohne Paket (Dispatcher), Teil 1/6: Sammelpaket: Aufgaben o).

### Added
- Agent API: agents restore task attachments and project files from the trash - `POST /api/v1/attachments/<id>/restore` and `POST /api/v1/list-files/<id>/restore` with the same rights as deleting (scope `attachments:write`, only what is shared with the agent); MCP tools `restore_attachment` and `restore_project_file` (#4010).
- Release workflow: `release.yml` can also be started by hand on an existing tag (Actions > Release > Run workflow, input `tag`), with the same gate - a green full CI run on the tag's commit; the image comes from the tag, the GitHub release stays with the weekly release (#4926).

### Changed
- Office > Bookkeeping: in a year with the basis "Bank and cash (strict)" the neutral export counts like the income statement - receipts through their bank, cash or card line with its day and amount, entertainment receipts through their line, bank and cash lines without a receipt as rows of type "Booking"; what does not count is listed in `missing.txt` of the archive. The DATEV export names receipts without a payment line and invoice payments without a bank booking as hints instead of leaving them out silently (#4932).
- Internal: templates, comments, waiting on, the people of a task, field options and the trash of sections / planned sprints write through the shared core's layer for side objects (`kalmido/core/objparts.py`); answers and rights stay the same (#4762).

## [2.740.0] - 2026-11-08

Package 2.725 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Changed
- Phone: the bar above notes and knowledge pages always wraps; the search gets its own line on narrow and touch screens, the buttons below keep their full size (nothing cut off or overlapping, e.g. on a folded phone). The head's chips (workspace, agents, status, timer) share one height and a round shape (#5163).
- Section heads on touch screens: holding still opens one menu; dragging starts only from the hold of the drag, the row menu's own long press no longer fires as well (#5177).
- Tests: UI suites start Firefox as a mouse unless they ask for touch (#5169).

### Fixed
- Dialogs: the footer sits where it sat before 2.331 again (short dialogs were 20 px taller because of the resize grip); while scrolling, the band above the buttons is a shadow (#5158).
- MCP: the tool log_decision needs the agent scope like its route POST /agent/decisions (#5157).
- CI red suites p2150_api, p2150_ui, p2360_0_c_agents_api, p2260_api (agent PATCH of a list sends the version it read, required since #5052), p2417_a_ui (the click after a drag is sent like a browser does), p2633_b_safearea_ui (waits for the stripes' transitions under reduced motion) (#5173, #5172, #5174, #5171, #5175, #5159).

Package 2.733.0 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Fixed
- Statistics: the travel expenses made from a trip count again under Travel (the office check returns the area and the "own" level since #4642; a member on "own" sees only the trips they entered) (#5204)

Package 2.636 (Bündel: Teil 1/6: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- #4565 Project type "Shoot" (only with the industry Film & Video): every card is a shot with the fields scene, shot size, lens and location, the columns are shooting days, the board shows a picture tile per card (first image attachment) as the storyboard, and "Shot list (PDF)" in the board exports one table per shooting day (`GET /api/lists/<id>/shotlist.pdf`).
- #4952 Second industry pack "Agency & services" (code `agency`): its own day calculation blocks and suggested services, and the archive import file name template date_number_client as its default (`legacy_fn_template` in a pack); Film & Video is unchanged.
### Fixed
- #4853 Mailbox rules: a mail that produced no document is no longer remembered for good - the claim is released so the next run tries again, and the rule shows why (no right on the target folder, or every document refused); a mail whose files are refused for what they are (type, content) stays remembered and is not fetched again; saving a rule with a new target folder checks the mailbox holder's right on it.
- #4854 Organisation import: the history of moved items no longer carries IDs of the source server (move points to the folder in the target or stays empty, moved_space is cleared).

Package 2.550 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- Deleting a custom field puts it into a field trash with all its values (also of tasks in the trash): the confirmation says so, a toast offers Undo, and Project settings > Deleted fields lists it with Restore (owner and project admins, within the trash period; the trash run deletes it for good afterwards) (#4528)
- Removing a member or leaving a project keeps a note of their assignments, person field values, delegations and watches; adding the same person again within the trash period asks "Restore what X had?" (also a button in the member row of the share dialog). Nothing that was set meanwhile is overwritten (#4528)
- Off-site SFTP target: optional field "Expected fingerprint" (the line of `ssh-keygen -lf` or `SHA256:…`); a different host key stops the backup (#4517)
### Changed
- The removal question for a member now also counts delegations and watches and names the way back (#4528)
- Backup names and the manifest carry the instance id of the server (`kalmido-backup-<date>-<time>-<id>-<kind>.zip[.enc]`); older names stay listed and restorable (#4517)
### Security
- Off-site clean-up deletes only this server's own backups and shared files, never those of another server in the same folder; while an old backup name of unknown origin lies there, no shared file is deleted (#4517)
- Off-site S3 endpoints must use https (http only to this machine), like WebDAV; a stored http endpoint is refused with a clear message (#4517)
- Off-site SFTP stores the host key only after a successful sign-in (#4517)

## [2.734.0] - 2026-11-08

Package 2.727 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Changed
- Tables: the sheet bar under the grid is always there, also with one sheet - its tab ("Sheet 1" for a new table) and the "+" beside it, like a spreadsheet; a tap on the open tab gives its menu (rename, duplicate, pivot; the first sheet keeps no delete). Who may only read sees the tab without "+" and menu (#5203).
- Documents and file store: a swipe leafs like turning a page - the previous / next document lies beside the open one as a placeholder (title, type, date, its preview fetched ahead, else an empty page) and glides along with the finger over the whole width; let go and it snaps in, then its content loads. The end of the list still springs back; the full view (PDF) and the picture viewer do the same; reduced motion changes at once (#5202).
- German wording: "Freigabe" means approval only; sharing says "Teilen" / "Zugriff" (e.g. "Links und Zugriffe"), a lone bank "Konto" is "Bankkonto", agent bundles are "Teil {0} von {1}"; English "activity" for the history of one thing is "history". TRANSLATING.md has the glossary lines and tools/i18n_check.py reports "Freigabe" in a sharing text (#5197).

## [2.731.0] - 2026-11-08

Package 2.707 (Bündel: CI: ZAP-Schritt 'Start PostgreSQL' scheitert geleg).

### Fixed
- CI: the OWASP ZAP job pulls the PostgreSQL image with up to 3 tries and a growing pause before starting it, and prints the container log when the database does not start; a short registry hang no longer fails the step and holds the release. The ZAP finding itself stays a hard check. Suite p2707_zap_db_start runs the step with a stand-in docker (#5185).

Package 2.715 (Bündel: CI: ZAP-Datenbank wird zu früh als bereit gemeldet).

### Fixed
- CI, job "OWASP ZAP baseline": the step "Start PostgreSQL" checks the database over TCP (pg_isready -h 127.0.0.1) instead of the socket. The postgres:17 image first runs a setup server on the socket only and restarts it; the socket check took that server as ready and the one final check then met the restart ("rejecting connections") and failed the job. The wait loop (90 s) is now the final check itself; tests/p2707_zap_db_start_test.py plays the setup server and its restart (#5187).

Package 2.724 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Fixed
- #5184: the start state no longer sends the internal organisation column of every task (row-level security of #4602); a big organisation account's start set is back under its 2 MB budget (2.02 -> 1.96 MB in p3136_state_size), the suite now prints the start set's bytes per task key.
- #5186: test p151_ui waits until the timer ran a full second before Stop - a shorter entry is discarded as a misclick, so on a fast runner the hint of the task just tracked was missing.

Package 2.730 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Fixed
- #5195: test p2139_b_api gives its agent the scope attachments:read - a team chat file download needs it since #4382 (finding 8), the test was not pulled along; it now also checks that a token without it gets 403.
- #5196: test p21481_d_api stubs the bookmark sync's allow list with an empty set like the real one - the http check of #4382 (finding 6) looks into it and crashed on None.

## [2.719.0] - 2026-11-08

Package 2.702 (Bündel: Bilanz: Auszahlungen der Online-Zahlungen und CSV-).

### Changed
- Bank reconciliation: importing a CSV statement now asks which bank account it belongs to when the office has two or more bank accounts (Office > Bank > Import, step "columns"). Without a choice the import is refused instead of putting the lines silently on the default account; the balance sheet books the lines on the chosen account (#5183).

### Fixed
- Balance sheet: the collective payout of the online payment provider now lands on the bank account whose statement carries it; before, it stayed on the default account when it arrived on a second account (#5183).
- Balance sheet: a restaurant bill that is both an approved entertainment receipt and a receipt on the same bank, cash or card booking now counts once (the entertainment receipt wins, as the strict income statement does); before, the expense and the input tax were booked twice (#5183).

Package 2.689 (Bündel: Bündel: Bündel: Teil 1/6: Sammelpaket: Aufgaben ohne Paket (Dispatcher), CI-only rot: p2191_c_perf, CI-only rot: p2290_c_fold_ui u. ).

### Changed
- Task search: the server tests the search word only on the tasks of the projects you can see. Since tasks stand under row-level security (2.662), the database could no longer use its text indexes for the search and read every task of the instance once per field; with 32,000 tasks a search took 29 ms in the database, now 2.5 ms, and it no longer grows with other workspaces' tasks. Same results as before (#5116).

### Security
- Names, titles and other typed values that a translated sentence puts into the page (for example "SSO: {0}", "row {0}", "Access data set (…{0})") are now always escaped: 88 places moved from tr() / trn() to trh() / trnh(). A new lint step (tools/check_trh.py, in the CI) reports any new tr() with an unescaped value inside an HTML template; values that are HTML on purpose stand in tools/trh_ok.txt (#5125).

Package 2.705 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Security
- #5151: Receipt fetcher keys (kbh_...) get an optional address rule like API tokens and scan inbox keys: Settings > Integrations > Receipt fetcher, lock button "Only from" (IPs / networks); from any other address the key answers 403 (PATCH /api/docs/fetchers/{id} {allowed_ips}).
- #5151: The plus address tokens of an older version (mail_tokens, hub_tokens, doc_mail still in plain text) are sealed with the server key and hashed by the daily watchdog run, 14 days after the first start of this version (one-way: a version before 2.674 no longer finds those old addresses after that; 2.674 and later still do). The address rule helpers moved to core/ipallow.py (api/scopes.py re-exports them).

## [2.710.0] - 2026-11-08

Package 2.674 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Security
- #4028 Hosted MCP: a body without Content-Length is read in pieces up to the limit; issuer and accepted Origin come from PUBLIC_URL only when it is set (Settings > Organisation > Agents warns when it is missing); an access ends 90 days after it was made; the consent page writes the agent's log; ended or revoked accesses are cleaned up after 30 days, a restored backup still cannot revive them; wiki files through API v1 send an SVG as a download and note no download for HEAD or 404; after an OIDC sign-in the consent page opens again (only that path of this server).
- #4382 Hardening from audit #2483 (14 low findings): letter PDFs only the filed version with a sandbox CSP; shared wiki images raster only with magic bytes; renewing or deleting a client mail address needs write access; webhook and channel tests answer blocked hosts uniformly; new mail plus tokens are stored sealed and matched by hash; Paperless, newsletter and Karakeep refuse plain http to public hosts; messages to a running job need agent use; scopes attachments:read, account and calendar (day plan without calendar shows "Busy"); office agent list limits apply to linked documents; read-only agents cannot post playbook proposals; admin agent audit API filtered like the web route; document fetcher keys expire after 365 days; sheet proposals only to people who may use the agent; hint on the EXIF switch.
### Changed
- #4190 DATEV, GoBD and knowledge exports are written to temporary files and share two export places (busy = 429 with a message); JSON request bodies are limited to 10 MB (routes with larger bodies keep their own limit); the ZIP plan stops at the first file too many; the account export reads its tables in pages.
- #4194 Agent list, job list and news check in batches; the job list no longer carries each job's log (the log loads when a job is opened) and older own jobs no longer go missing behind many newer ones.
### Added
- #4028 Settings > Organisation > Agents lists the connected apps of team agents (who, when, last use, end) and can revoke them.

Package 2.683 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Fixed
- Documents on the phone: a document opened from a card of a file store folder now shows "3 of 48", the arrow buttons and the sideways swipe through the folder's documents in the order shown (before: no leafing at all, the sheet only knew the documents' own list); "Open as document" in the folder's list view leafs the same way; a document opened by its address (link, reload, search hit) that stands further down than the loaded page loads the next pages until it is found (#5150).
- Locked folders: a picture opens with all pictures of the folder (arrows, swipe), a PDF leafs through the folder's PDFs and pictures like an open folder; each file is decrypted in the browser only when it is turned to, never all of them in advance (#5150).

Package 2.671 (Bündel: Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), CI-only rot: p2551_c_favout_ui, Teil 1/6: Sammelpaket: Aufgaben ohne ).
### Added
- Tables: group the rows by one column (dates by day, month or year) with collapsible groups and a subtotal row per group - sum, count or average per number column. A view only, like the filter: nothing is saved, the subtotals take no part in formulas, copying or the export; moving rows is held while grouped (#3463).
- Tables: pivot sheet - a sheet of a workbook computed from another sheet of the same workbook on every read (rows, an optional column field, up to six values as sum / count / average, filters), read-only with totals, always current; its setting is saved with a version (409 on a stale one); the xlsx / CSV export writes its values. Agents see `kind` of every tab and the pivot result when reading a sheet (#3463).
### Fixed
- Organisation import: disposition bookings made from a quotation keep their link to the imported quotation and part (offer_root / offer_doc / offer_pos on the new ids, emptied when nothing of the import fits), and open places of a crew function come along - the disposition on the target no longer books the shoot days twice (#5097).

Package 2.620 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Releases für Selbst-Hoster: Tag-Version braucht ei, Sammelpaket: Aufgaben ohn).
### Changed
- A long press (phone) or right click (computer) opens the row's "…" menu also for mailbox addresses, repositories, webhooks, file requests, table folder cards and file cards (#4616).
- Members without office groups (level "own" for travel) can take their own trip from the trip planning into the office's travel expenses; approval and DATEV stay with the admin (#4642).
### Fixed
- Tasks from a quotation that were moved into another project no longer count for the old project, the next version of the quotation shows them as "moved to another project" and never writes into them; the quotation's task count needs sight of the project, the project's budget sums all quotation chains of the project; the link follows the moved task, so deleting the old project keeps it (#4586).

Package 2.693 (Bündel: Bündel: Kommentare: Schalter 'Mit Aktivität' auch in nicht, Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Fixed
- Tables: printing a pivot sheet no longer gives an empty page or "Nothing to print". The pivot sheet's menu (the three dots) now offers "Print / PDF…"; the PDF holds the computed table as the view shows it, with the header and the bold total row (#5148).

Package 2.685 (Bündel: Kommentare: Aktivität in drei Stufen (nur Kommenta, Bündel: Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), CI-only r).
### Added
- Balance sheet: the journal now also books the approved entertainment receipts (70 % deductible with the full input tax, the 30 % on an account of their own), the mileage allowance of the logbook (31 December) and paid reminder fees (other income, no VAT) - the same figures as the income statement (#5128).
- Balance sheet: every bank account of the office is a ledger account of its own (its DATEV account, else the next free one after the default, SKR03 1200ff / SKR04 1800ff); a bank line belongs to the account whose IBAN its statement carries, invoice payments and card totals follow their bank line (#5128).
- Balance sheet and profit and loss account as PDF next to the CSV (`GET /api/office/books/ledger/<bs|pl>.pdf?year=`, office admin, logged as an export); entries made by hand can be edited in a dialog (409 when someone changed them meanwhile); a difference on the opening balance account 9000 shows before the year-end closing (#5128).
### Changed
- Comments: the history between the comments has three levels in the "…" menu, in shared and private lists alike: comments only, changes of others, all changes incl. my own. Default per device: shared list = all changes, private list = changes of others; the old on/off setting carries over. The head says "Comments only" or (shared list) "Only changes of others" (#5162).
### Fixed
- Office: switching "Office & finance" on no longer leaves the office saying it is switched off when it loaded before the switch was saved (#5176).
- Balance sheet: a receipt booked against the bank (counter account "bank") and paid from the cash box is now booked bank to cash instead of being left out (#5128).

[Unreleased]: https://github.com/Gegenschuss/kalmido/compare/v2.761.0...HEAD
[2.761.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.761.0
[2.759.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.759.0
[2.756.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.756.0
[2.749.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.749.0
[2.740.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.740.0
[2.734.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.734.0
[2.731.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.731.0
[2.719.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.719.0
[2.710.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.710.0
