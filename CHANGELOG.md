# Changelog

All notable changes to Kalmido are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Kalmido uses
[semantic versioning](https://semver.org/): every published change gets at least a new patch version, new features a
minor one, anything that needs action on your side a major one.

## Older versions

- [2.400-2.499](docs/changelog/2.400-2.499.md)
- [2.300-2.399](docs/changelog/2.300-2.399.md)
- [2.200-2.299](docs/changelog/2.200-2.299.md)
- [2.100-2.199](docs/changelog/2.100-2.199.md)
- [2.0-2.99](docs/changelog/2.0-2.99.md)
- [1.x](docs/changelog/1.x.md)

## [2.549.0] - 2026-11-05

Package 2.531 (Bündel: Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Rot auf main a).
### Added
- Office > Log: new button "Check: chain intact". Every finalised invoice, credit note and dunning letter now carries a hash chained to the previous document of the same office and number range; the check recomputes the whole chain and names the first document that differs (e.g. after a change directly in the database). Quotes and test documents stay outside the chain. Existing finalised documents are chained once at the first start (#4497)
- Office: tax rates of a country pack can carry a validity date; drafts use the rate valid on the day of service (service end, else the invoice date). The German pack knows the 2020 cut (16 % / 5 % from 01.07. to 31.12.2020). Finalised documents keep their rates (#4498)
- Settings > Account > Move account: the export page lists what is not in the file (open: "What is not in the file (n)"), including the trash of files, knowledge pages, sheets and address books (#4317)
- Account export: family links and connections are part of the file; the import never creates a family link (it names them in a warning) and asks for each connection again as an open request (#4317)
### Fixed
- Account import: the notes "these areas stay on the old server" and on locked folders always come first and no longer drop out after 50 warnings (#4317)
- Account import: parts of the file the import never reads (activity, notifications, sessions ...) no longer count against the size limits, so the export of a long used account can be imported (#4317)
- Account import: approver, reviewer, "waiting for" and the delegated agent of a task are mapped like the assignee; what cannot be mapped is named in a warning instead of vanishing (#4317)
- Account import: a journal day that already has an entry gets the file's entry below it (with a divider and the source date) instead of losing it; undo removes it again (#4317)
- Account import: rows the server refuses are counted per area in the warnings; importing the same file again no longer adds child rows (tags, dependencies, habit logs ...) twice (#4317)
- Account import: the preview counts comments and files of tasks in the trash among what stays behind (#4317)

Package 2.549 (Bündel: CI rot in 2.544.0: p2190_a_sessions erwartet noch,, Bündel: Einreihen-Prüfung: Warten auf den einen Lint-Platz, Sammelpaket: Aufgabe).

### Added
- Trash view: a new section "Video sign-offs" lists video reviews in their trash (own and the organisation's ones you may see) with the days left; "Restore" brings them back, a review without a place asks for a project of its workspace (`GET /api/videos/trash`, `POST /api/videos/ID/restore` takes an optional `list_id`) (#4536).

### Changed
- ntfy share inbox: the inbox topic may not be a push topic or another person's inbox topic, the minimum length applies on the default server too, and a push topic that is already an inbox topic is refused; the message does not tell who uses it (#4515).
- i18n merge driver: a new or renamed key from theirs lands behind its predecessor instead of at the end, so split commits give the same order (#4564).

### Fixed
- ntfy share inbox: the duplicate check counts only the recipient's own tasks, a message to two people reaches both (#4515).
- Off-site upload holds the backup store's readers' lock while it reads store files, a cleanup in between no longer breaks the upload (#4529).
- PDF preview: when the pdf.js worker hangs or fails, the preview ends after 15 s in the message with a Download button instead of "Loading…" for ever (#4578).
- Tests: the own password change ends app passwords by default (#4639); the mail folder test stamps hub_mail_id (#4637); the shared page test checks exact paths of the hidden text file (#4636).

Package 2.537 (Bündel: Neuer Tab / eigenes Fenster nur mit Maus, Bilder i, Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Added
- Office: a quotation gets the button "Create tasks" next to its project. A preview with a tick per line turns each service line into a task in the project (a sub-quotation becomes a section, a shoot part one task per crew role) with its time in the "Budget h" field: hours = quantity, days = quantity x the project's day hours; flat rates and pieces get no budget unless you type one in. Without a project at the quotation it is created in the same step. Tasks never carry prices. For a new version the button reads "Update budget from quotation": new lines become tasks, changed lines get the new budget unless it was changed by hand, dropped lines are only marked, nothing is deleted. The project page shows the quotation's total budget in hours and net amount to people with office rights (#3433).
- Task detail: the time block shows "Tracked X of Y h" against the task's budget (task and subtasks), yellow from 80 %, red above 100 %; members without admin rights see only their own time (#3433).

### Changed
- Phone and tablet: buttons that open a new tab or an own window (PDF preview "Open in new tab", the window button of tables) only appear on devices with a mouse; pictures open in the app's preview everywhere (file store, file search, documents) instead of a new tab (#4574).
- Editing a task (title, description, date, tags, fields, priority, assignees) is shown and saved at once, online too: the change goes through the outbox and the server's answer (e.g. dependent tasks moved along) follows; a conflict opens the conflict dialog. Locked lists, moving to another list and deleting work as before (#4568).
- A comment without files stands in the timeline at once as "Sending…", the box empties and the button stays free; if sending fails it stays with "Send again" and "Discard", without a duplicate on the second try. Comments with files, to the customer or by e-mail work as before (#4569).
- Deleting an account: shared folders and files of the private file store go to the person with the longest-standing edit right on them, resealed for their account, contributions of others and recognised documents included; group shares stay group shares, public links and file requests of others on that branch end. Without such a person the branch goes with the account and the dialog says so (#4347).

### Fixed
- "Use mine" in the conflict dialog sends the shown other version as its base, so the same conflict no longer comes back at once (#4568).

Package 2.546 (Bündel: Einreihen-Prüfung: Warten auf den einen Lint-Platz, Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Added
- Tests: a finalised invoice stays unchanged on every write route under /api/office/docs/<id>, through undo and through the agent API (header, items and stored PDF compared; allowed routes listed with their reason); also for a person without an organisation (#4287)
- Tests: the e-invoice CI job also validates files from the real finalising (ZUGFeRD and XRechnung: 19 / 7 %, discount, reverse charge, credit note) with veraPDF and KoSIT, with a minimum number of files; p2424_c joined the list (#4289)
- Tests, rights guards: every non-GET operation with scope read is on a fixed list with its reason; the tenant coverage now requires the route path in the named suite, the old routes without one are on a list that may only shrink; foreign probe for the recovery passkey route (#4291)

### Changed
- Office: the books, the receipt list and the bank list are much faster with many receipts - visibility and trash are checked for the whole list at once (books: 12 queries per receipt before, now a fixed number), the books route computes the month from the year instead of twice, and bank suggestions only compare an entry with invoices / receipts that can match (same suggestions, same order) (#4186)

### Fixed
- Phone (320 px): Settings > Agents > Set up - the three fields for a new personal agent (display name, username, where it runs) stand one below the other at full width, the "Create agent" button under them; before they were squeezed to a letter each (#4491)

Package 2.519 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Rot auf main allein: p2356_b_import_target, Tabellen: Agenten-Rückgängig lässt die Da).
### Fixed
- Documents (computer): the open document's side pane stays below the page head while the list is scrolled, also when the list is short or scrolled to its end; its title and the close button stay visible and clickable, and the pane no longer reaches past the bottom of the window (#4467).
- Sheets: undoing an agent's change of a file cell brings the cell's former file back out of the trash, so the trash run no longer deletes the file the cell shows again (#4386).
- Mail in: an incoming HTML mail is turned into text in one linear pass (the HTML part cut to 2 MB first); a malformed mail with many unclosed script or style tags could stall every mail inbox of the instance and the background work. A mail is marked seen before its import, so one that is cut off does not come back every round (#4378).
- Wiki: a folder or page made while the tree was loading no longer stays hidden because an older answer counted as the newest (#3715).
- Tests: six flaky UI and API suites wait for a real state and run again (out of tests/skip.txt): p2425_c_ui (#4042), p21383_b_ui (#4045), p2190_family_ui (#4049), p23672_notify (#4050), p21445_b_api (#4053), p2451_a_office_rows_ui (#4054); p2200_a_wiki_tree_ui (#3715) too.

Package 2.498 (Bündel: Handy 320 px: Kopfzeile verliert Titel und Glocke,, Sprache: letzte feste Texte im Wiki-Import und bei, Handy: Wechsel nach Privat v).
### Changed
- List icons and list header pictures count as used storage (Settings, Storage) and a full storage refuses them; older pictures are measured in the background. A header switched off counts no more, its file stays for undo (#3884).
### Fixed
- Phone, narrow screen (320 px): page title and bell stay visible in the header. On Projects "New project" becomes a plus sign; workspace and agents signs move into the "…" menu when space is short; in the sidebar the share signs and the progress ring give way, not the name; the chosen view tab shows its whole name or only its sign (#3854).
- Phone: switching to another workspace from the menu on a project page stays in the new workspace (on Projects when the project is not there), instead of jumping back (#3863).
- Wiki import: the reasons for skipped files follow the language of the person reading the report; the "function not switched on" check of the office keeps its text for later readers, e.g. a recurring invoice's error (#3858).

Package 2.528 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- Tables: a trash view - "More > Trash" in the tables overview (per workspace, with the days left, restore, delete for good) and "Deleted rows and columns" in a table's menu (#4306).
### Changed
- Switching on encryption for knowledge asks first and names how many versions and trashed files there are; they are no longer deleted at once but kept until the trash period ends (only for people who could read the space before) (#4306).
- An agent's Undo in a table keeps rows, columns and a table a person has typed values into since; the toast says what stayed. The v1 answer carries `kept` (#4306).
- Online changes of tasks (single and multi-edit), time entries and project properties carry the previous values like the offline queue: a change made on another device in between shows the conflict dialog instead of being overwritten silently (#4305).
- Office settings save only the changed fields and say so when another person changed the settings in between; the inputs stay in the form (#4305).
- Accepting an agent's sort or day-plan proposal refuses tasks the person changed since the proposal (409 naming them) (#4305).
### Fixed
- "Skip this occurrence" pressed twice (two devices, offline queue) skipped two dates; it now skips one. v1 `POST /tasks/{id}/skip` takes `expect_due` (#4305).
- Table rows, row order and columns are saved under the table's lock; a row order sorted elsewhere in between is reported instead of lost (#4305).
- Moving a table or a knowledge page to another workspace stops as a whole when a file cannot be copied, instead of leaving a file with the old key (#4306).
- Restoring a folder from the file store's trash brings its knowledge pages back too (#4306).
- Favourites, the custom-fields module switch and the first-run setup no longer overwrite each other's user settings (#4305).

### Fixed
- main: CI red of 2.541.0 - pg_prepare: the subtask depth limit of the trash cascade count is a bound parameter (no number inside the SQL text); p242_ui: the agent setup guide test counts the 12th step "Control level" (#4179).

Package 2.534 (Bündel: CI: harte Suiten (Büro, Rechnung, Sicherung, Login, Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- CI: the suites of the hard areas (office, invoices, backup, login, security scanners; list in tests/hard_suites.txt) run on their own test shards that start first ("Test suites N/M ... hart"), the other shards follow; tools/shards.py --hard-target-min (#4557).
- Office, EÜR and VAT figures: approved entertainment receipts count - their own EÜR line "Entertainment (70 % deductible)", the input tax in full in field 66, small businesses 70 % of the gross without input tax; the statement names the non-deductible 30 % and warns when the same bill is also under Receipts; the neutral export has two rows per receipt (#4333).
### Changed
- Wide screens: one width system - reading text and chat 46rem, forms 40rem, lists, office and start pages at most 96rem (1536 px) and centred, board, calendar, timeline, matrix, table and mind map use the full width; task lists no longer stretch over the whole monitor. Phones and 1440 px stay as before (#4551).
### Fixed
- Sending a quotation or invoice by mail: when the terms could not be joined to the PDF or their file is missing, the mail no longer goes out silently without them - the send dialog says why and offers "send as separate file" / "send without terms" or cancel (#4339).
- Phone: the sidebar no longer opens on its own when the current page is drawn again after it was closed; only going back still reopens it (#4344).

Package 2.540 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Lesen unter „Alle Arbeitsbereiche“: Übersicht je B).
### Added
- Booking pages: the owner can delete confirmed and cancelled bookings (trash icon in the booking list, with a question first; the event, contact and lead stay, the booked person gets no mail) and search all bookings of the page by name or e-mail, also those older than 30 days (#4349).
### Changed
- File store under "All workspaces": the top level lists every space (Private, each organisation, Shared with me, Trash) instead of silently showing the last remembered one; a tap opens `#ablage/s/<space>`, the path "All workspaces / <space>" leads back. With one workspace chosen nothing changes (#4575).
- Reading under "All workspaces" (Read later, Bookmarks, Feeds, Home & life): the same overview of the spaces instead of the space picker; the address carries the open space (#4588).
- Receipt (document details): the project is chosen with the picker of quotations and invoices - app icons, folders, search from 10 entries, a sheet on a phone, the last chosen projects on top; only the projects of the receipt's area, privately only your own lists, no inbox, archive, health or budget lists (#4471).
- Toolbars of Documents and the office lists: search, switch, filter, sort and buttons share one height (40 px with a mouse, 44 px on touch); on a phone the documents bar shows symbols only and "To review" only once, office list filters stand in two equal columns, the invoice / quotation sub tabs scroll sideways; receipt filters: ticks on one line, "Day" is now "Date by" (#4472).
### Fixed
- Documents: the chosen part of the "All / To review" switch is marked again (#4472).
- News: the rule hiding another organisation's items compares the organisation number where the item has it, the name only for old items; a retired organisation's name is free again for a new organisation and for moving a personal office (#4383).

Package 2.523 (Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Rot auf main allein: p).
### Changed
- Office > invoices: a payment date typed before the invoice date is refused with a clear message (also for agent payment suggestions); bank reconciliation, cash book and online payments keep their real booking day, so prepayments still work (#4082)
- Office > final invoice in a foreign currency: the progress invoices are deducted with the net they really billed in their own currency; changing the rate of the draft recomputes the deductions (#4082)
- Booking archive import: all files of one upload share 200 MB (checked before reading), its undo works for 24 hours like the other imports (#4073)
- File previews: at most 60 per person and minute and one at a time with text recognition; beyond that the card shows the file symbol (#4073)
- User docs: corrections where the docs said something the app does not do (import, knowledge pages and agents, project roles, time tracking, dependencies, quiet hours, retention, polls, limits) and short sections for quick notes, delegating and watching, the Chat area, leafing through documents, favourites and saved views, moving a task to another workspace, the software bug inbox, newsletter, receipt fetcher and the practice project (#4176, #4177)
### Fixed
- Settings > Company & office > Functions: one press on a switch (e.g. DATEV) is one undo step again and no longer rewrites your personal modules (#4343, #4039)
- A link into another workspace brings that workspace's own sidebar state (open groups, folders) back; the page stays the link's target (#4189)
- E-invoice (UBL/Peppol): prices below a cent in a foreign currency keep their quantity (1,000 minutes instead of 1), with a rounding line where needed (#4082)
- Cash discount: a payment reversed later (reversal dated today after a DATEV export) no longer keeps the invoice "paid" (#4082)
- Credit card statements and MT940 bank statements: very long lines or files are read in bounded time (#4073)

Package 2.536 (Bündel: Notizen speichern sofort über die Warteschlange (a, Bündel: Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: S).
### Added
- Office > Equipment: the depreciation choice is always visible and has a third value "none (no expense)" - a price kept only for the insurance list no longer becomes an expense; the field "new value" says it is no expense (#4335).
- Equipment dialog and income statement (EÜR) warn when a device is depreciated without a linked receipt, with a link to the equipment (#4335).
### Changed
- Notes save at once, online too: every change (text, title, tags, pin, a new note, a quick note) goes into the outbox and shows "Saved" immediately, the server gets it in the background; typing no longer waits for the server on a slow connection. A conflict (409) from the outbox opens the note's own conflict dialog with both versions. Notes in locked (encrypted) lists go to the server directly as before and never wait in plain text (#4567).
- Deleting a mail in the project mail takes its .eml and attachments into the file trash with it; Undo brings back only what went with the mail, files deleted by hand before stay in the trash; the files of a deleted mail can no longer be opened or restored on their own; a day folder shared with another mail stays, and a mail whose file is a receipt of a locked month cannot be deleted (#4338).
- Self-hosting docs: the AI examples (Ollama, EU provider) belong in docker-compose.override.yml; the Ollama example names its top-level volume, the EU example no longer mounts /secret a second time read-only (#4345).
### Fixed
- Income statement (EÜR) and cash flow count card fees and interest without a receipt ("no receipt needed" on a confirmed card statement) as the DATEV export does: their own EÜR line "Card fees without receipt", a cash flow entry of the kind card; matched positions still count once through their receipt, the bank booking of the statement total is no expense (#4334).
### Security
- A support session counts as no session at the OIDC sign-in: /api/auth/oidc/start is refused in a support session and the callback with a support cookie is refused, so a support session can neither link an identity to the customer's account nor swap itself for a session without the support mark; the HTTP Shortcuts download (a new upload token) is refused in a support session, too (#4363).

Package 2.509.0 (Waiting for me opens completed tasks, Office menu without the signature editor, additive migrations checked).
### Fixed
- Waiting for me (#4324): a tap on a row whose task was completed long ago opened an empty panel with no way out. Any link to a task that is not in the app's memory now loads and opens it and it stays open through the next reload; a task that does not exist or a device that is offline gets a hint and no panel. A short "Loading…" with Back and Close shows meanwhile. Check on a phone: Waiting for me, a row of an old completed task.
- Office menu (#4342): every tap on a row of the Office menu also opened the e-mail signature editor. Only Edit in a send dialog opens it now. Check: Office, tap several areas in the menu.
- Invoices (#4331): a PDF rebuilt for an older finalised invoice without a stored file showed "Already paid / Amount outstanding" of today while its embedded XML has the full amount. The rows are left out of that PDF; the preview on screen keeps them, the stored PDF and the XML do not change.
### Changed
- Migrations (#4285): `tools/check_migrations.py` also reads the statements of the fragments: a step adds exactly its own column, nullable or with a DEFAULT; AFTER creates indexes only; SCHEMA only creates; a UNIQUE index on an existing table needs a stated reason. The upgrade test starts on the old database with a row in every table and also compares defaults and constraints; new tests for a step failing in the middle of a start and for two starts at once.

Package 2.538 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Security
- A support session books nothing in the office and changes no account structure: finalising, unlocking, cancelling by credit note, payments (also the status "paid"), cash book, bank, DATEV, periods, legacy import, master data import, reminder fees, `office/move`, deleting for good (office trash, finished tasks, all times of a project, fixed costs and trips undo, a whole project) and the HTTP Shortcuts download with its upload token answer "Not possible in a support session". Single trips and fixed costs cannot be deleted and number ranges cannot be changed either. Reading stays, editing contents stays (#4365).
- A support session puts no contents into an organisation that has not opened its own support access: new projects, calendars, address books and clients land privately, an explicit `org_id` / `list_id`, a calendar, address book or project of such an organisation and any write into its office are refused. The HTTP Shortcuts download is hidden in a support session (#4365).
- Every way a project changes hands (organisation projects list, shared folder, removing a person with `?to=`, leaving) only hands it to a member or admin of the organisation; a guest or read-only member answers 409. When nobody is left, the projects go to an admin, not to a guest (#4371).
- Locked (end-to-end encrypted) projects keep no time note, status note or description in plain text: the server refuses them, switching the lock on empties existing ones (and the status history and earlier descriptions), the app hides the fields and the notice before switching on names them. Projects locked before this version lose these texts once at the next start (one way). An agent's time proposal brings no note into a locked project, and the lock state never comes from an import file (#4372).

### Changed
- Public release notes on GitHub show three to five highlights on top, leave out bundle titles and main / CI lines and stay below a fixed length; the rest is a link to the CHANGELOG (#4360).
- Installer: a busy port prints a command you can run with another port and `PUBLIC_URL` follows the new port while it is still `http://localhost:<port>`; the uninstall text is complete (`down -v`, the images, `sudo rm -rf` of the folder, keep backups and the key first); wording fixed (#4361).
- New setup card "Import from another app": starts empty and opens Settings > Data after the reload (#4361).
- Monaco counts as France for VAT (EU, and Monaco - France is domestic). Areas without an own country code (Canary Islands, Ceuta, Melilla, Mount Athos, Heligoland, Büsingen, Livigno, Campione) are not recognised; for clients there pick "not taxable in Germany" by hand (#4368).
- VAT return and DATEV export work out the reverse charge case from the client's country each time, so older documents move too: since 2.502 a reverse charge invoice to a client outside the EU counts in field 45 / account 8338 instead of 21 / 8336, and since 2.538 one to a client in Monaco counts in field 21 / 8336 instead of 45 / 8338 - a period already filed can show figures that differ from what was filed then (#4368, see docs/OFFICE.md).

### Fixed
- Finalising a reverse charge invoice without the client's country is refused with a clear message (it counted as domestic §13b before) (#4368).
- Cash book: without the right to book payments, an entry with an invoice is refused before anything is written with a message that says what to do, and the invoice choice is hidden (#4368).
- Off-site backup: removing or changing the target keeps its backups as "formerly off-site", so the deletion journal is not cut too early; off-site on without a successful upload shows a hint on the backup page; the note after a restore says "accounts excepted"; if the list of formerly off-site backups cannot be read, removing a target that still holds backups is refused instead of losing their names (#4367).
- Leaving an organisation clears its unsent changes from the device's offline queue; the leave dialog says how many would be lost (#4369).

Package 2.539 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Security
- Organisations: when an admin who saw the organisation's recovery key is removed, demoted, leaves, is locked or deleted, the remaining admins get a News item "Renew the recovery key" (nothing is rotated by itself); the export dialog names the risk of an old key (#4373).
- Hosted instances: the operator's user list shows a client's account reduced (user name, lock, storage, number of organisations; no e-mail, name, 2FA, sign-in methods, organisation ids or photo), the search no longer matches a client's e-mail or name, and a client's photo answers 404. Self-hosted instances are unchanged (#4374).
- Sign-in (#4375): Settings > Account > Password has a ticked box "End all app passwords and API tokens" (untick to keep them; apps for calendar / contacts and scripts must reconnect otherwise; agent tokens stay; a reset by an admin or by link always ends them). App passwords can only be created from the web session, no longer with an API token. An OIDC account is linked by user name alone only with auto-create on, otherwise via the confirmed e-mail. The new-device mail takes the network into account. An address counts as proved only when the link was sent by mail to that address.
- Browser encryption (#4376): files of encrypted lists are bound to their task (older files stay readable); the passphrase gets a strength check; "Remember on this device" is bound to the current key generation and dropped on a key reset; before a key is handed to a member for the first time, a short confirmation shows the safety number. A key change (by hand or after removing a member) hands the new key only to confirmed members; the others wait in the list until the owner confirms their safety number once (keys seen before this version count as unconfirmed).
- Incoming mail (#4381): without `KALMIDO_MAIL_AUTHSERV_ID` no sender counts as confirmed; a reply through a person's signed reply address is stored in their name only with that confirmation, otherwise as "By e-mail from <address>".
### Fixed
- Webhooks, notification channels, git and newsletter calls end after 15 s in total; a target that answers drop by drop no longer holds the delivery queue, and a target that timed out is tried once per round (#4379).
- Tests: p264a_d_ui waits for the drawn "Understood" button before clicking (#4394).

## [2.546.0] - 2026-11-05

Not released (the CI of this version was red); its changes are listed under 2.549.0.

## [2.544.0] - 2026-11-05

Not released (the CI of this version was red); its changes are listed under 2.546.0.

## [2.541.0] - 2026-11-05

Package 2.530 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- Comments and team chat messages go into the trash with their files: Undo right after deleting, restore until the trash period ends, the trash run removes them for good; also when a list owner deletes someone else's comment and when an agent's comment is undone (#4315).
- Habits go into the trash with their history: Undo toast and a trash section under the habit list (#4315).
- "Delete all times": the deleted entries stay on the server; the delete dialog shows the last deletion with a Restore button, also after closing the tab (#4315).
- Before deleting for good (empty trash, task, project) the dialog names what goes along: customer reports, form entries, video reviews (these now go into the video trash instead of being lost), projects kept by law (#4316).
### Changed
- Empty trash as an instance admin empties only the own trash; other owners' trashes only after a second question with the number (#4316).
- Agents delete comments and habits only after a person's approval (#4315).
- Undo of a booking archive import works within 24 hours; the files stay until the trash run (#4315).
- Moving a task keeps watchers and the delegated agent for the way back; the hint names them (#4316).
### Fixed
- Removing the sample project, deleting a finalised but never sent quotation and deleting a trip (or a trip receipt line) now go through the trash instead of deleting at once (#4315).
- "No receipt" keeps the lock from arrival, so the document is not purged before the legal period; received business letters are locked like receipts; kept projects are respected by every delete way, also for attachments (#4316).
- Undo of a completed recurring task no longer overwrites later changes to the series; the table view asks the server for the number of values before deleting a field (#4316).

### Fixed
- main: CI red of 2.532.0 - setup_ui registers its own windows for the late-error check of closed windows (a poll answered after the window closed broke the run), p2393_2_b_ui counts only the mails to the reporter (the security mail of the new Firefox sign-in arrived in the same window on the slow runner).

Package 2.512.0 (Audit fixes: names across organisations, menu paths, operations docs).

### Security
- The leave preview of an organisation no longer names any account of the server: `?to=` is checked like the removal itself, anything but an active person of the organisation answers 400 (#4076).
- Creating a company of one's own, or moving a personal office into one, no longer tells whether another customer's company has that name: only your own companies count, so the same name can now exist twice. The server admin's route stays server-wide (#4077).

### Changed
- Hints in the app name today's settings: "Settings > Organisation > People" instead of Workspaces, "Settings > Agents > Assistant", "Settings > Company & office > Data > Import legacy data"; French hints say Paramètres like the menu (#4175).
- A new CI check compares every "Settings > ..." path in the docs, the app and the translations with the real menu (#4175).

### Fixed
- Docs: about 100 menu paths follow today's settings (#4175).
- Operations docs: imported mails are deleted from the mailbox, every deletion period needs `KALMIDO_RETENTION_PURGE=1` (now also in `.env.example`), paths past a login proxy (forms, file requests, portal, MCP, webhooks, CardDAV), default of `KALMIDO_TRUSTED_PROXIES`, pinning the image with the installer, CalDAV methods; `docs/UPGRADING.md` gains 2.79, 2.182, 2.239 and 2.240 (#4174).
- `update.sh` and `update.ps1`: without a running database service they say that no copy was made and wait 15 seconds so you can stop; the installers' link to the reverse proxy guide works again (#4174).

Package 2.533 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Fixed
- Office > Cash book: choosing an invoice while editing an entry (or switching it from out to in) now books the invoice as paid, like a new entry and with the same rights; the "Saved" toast offers no undo once the payment is booked (#4337).
- Office > Cash flow: a progress invoice on an older version of a quotation is now deducted from the version that counts in the plan (the newest, or once with several "yes" versions); the plan was too high (#4525).
- Office > Import > Archive: an invoice file name with one underscore before the date and `_R` (e.g. `657_Client_2026-03-11_R.pdf`) is a recognised invoice; when only the first field of a quotation's file name names the company read from the PDF, client and project are swapped and a hint says so (#4499).
- Meal receipts: when someone other than the host confirms a receipt, the PDF says who confirmed it and leaves the host's signature line empty (was: the confirming admin appeared as the host) (#4336).
- Admin > Alerts and push: a ntfy.sh server with a token is judged the same way in both places (#4321).
- Data safety (#4318): list CSV imports name rows without a title, cells beyond the header, cut texts and a non-UTF-8 file with their row numbers; bank CSV / MT940 imports name skipped rows with number and reason; a vCard without REV no longer overwrites a contact changed here (the names are listed); the account export reads rows and files from one snapshot and counts virus-locked files on the moving page; the undo of an account import counts a mailbox set up since; the delete dialogs say that the account's chat files go for good, that lists deleted along take other members' tasks without trash, and name more organisation areas.
- Data safety (#4318): the offline queue keeps an entry without a user instead of deleting it (never sent) and shows a hint; a repeated app request after a commit never applies its change twice; renaming a knowledge page relinks the linking pages under their save lock (a save in between is kept); "Delete all completed" writes a history line per task; drafts removed by a table or proposal undo go into the office trash; the old letterhead file is removed only after saving; the terms clean-up keeps files of drafts in the office trash; received e-invoices keep all their file versions.
### Changed
- Tests: `tests/stages.py --touched` maps a too-broad file to at most 10 suites with the rarest hits on its routes and names instead of leaving it unmapped (76 recent commits: 24 -> 11 with unmapped files) (#4332).

Package 2.525 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Fixed
- Sign-in lock: the sign-in gate now counts the failed sign-ins of every server process and keeps them across a restart, and a name ceiling check of a known address could hang a server thread (#4292).
- Clicks of one area no longer trigger another area's action with the same data attribute: the reaction picker and the retention export box sent a request for a receipt "NaN", a choice card's answer reached the credit card sheet, and the X of the address books dialog opened the cash book's "Close day" (#4281).
- Backups: the last three "Back up now" copies stay through the rotation; checking or restoring a backup made with an earlier passphrase says so (as the download does); a download of a backup with shared files no longer breaks off while the daily clean-up runs - the clean-up waits for the next run, a download during a clean-up says "busy" (#4303).
### Changed
- Office figures, cash flow, income statement and the client page read only the documents and columns they need; the Figures tile answers from a short cache that any change invalidates; the client page needs one time report instead of two (#4187).
- The documents list works out what you may see once per request and loads tags and shares for all rows at once; the mail lists of the hub no longer load the mail texts (#4195).
- Agent docs: the security page and the setup guides match what the server enforces - a step to choose the control level before the first test, the "one agent per project" exception for folder shares, control level and data lock under "What Kalmido enforces", and many smaller corrections (#4179).
### Added
- Lint `tools/check_dataattr.py` in CI: a document-level click listener whose data attribute another file emits must be listed as shared or check its value / area (#4281).

### Fixed
- main: UI test p2121_c_ui uploads the document for the agent suggestion as an office upload (area=office) since #4433 keeps private documents without a receipt row free of receipt cards.

## [2.535.0] - 2026-11-04

Package 2.517 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Fixed
- Project page, project files: the search text and its filter stay when the page redraws (a live update showed all files again while the field still held the text) (#3586).
- Tables with several sheets: Undo right after "+" while the new sheet is still loading goes back to the previous sheet with the bar of two sheets; a late load no longer replaces the open sheet (#3714).
- Tests: p2331_a_ui waits for the new page after a reload (the cause of its flake), p2124_e_ui waits for the Undo step instead of a fixed pause; p2331_a_ui, p2124_e_ui and p1_ui leave tests/skip.txt (#3586, #3714, #4012).

Package 2.522 (Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), CI-Plan: Zeiten abgebrochener Shards nicht einplan, CI-only rot: p2151_ui, Sa).
### Added
- Documents: for a person with an office, the general input (upload without a target, the share menu, a mail to the own document address) sorts after recognition: a recognised invoice (e-invoice, invoice number, net amount or VAT rate) goes into the office, everything else and every doubt stays private; nothing becomes a receipt by itself. An organisation's office receives automatically only from its admins (members could not take a file out again), members get "Move to office". Bound inputs (scan inbox, receipt fetcher, an organisation's address, uploads into a chosen workspace, office uploads) are never re-sorted (#4433).
- Documents: the private file store offers "Move to office" instead of "Record as receipt"; a sorted document has "Wrong area" (one click, undo); the file store list shows no receipts and office documents; Office > Receipts has a block "New in the office" (#4433).
### Fixed
- Knowledge pages: a diagram's own `%%{init}%%` can no longer switch HTML labels back on or bring its own CSS, font or sanitizer settings; Mermaid locks these keys too (#4170).
- Documents: a scan that waits to be split into letters (a stack) no longer offers a "Recognised" suggestion, an invoice number, receipt hints or a duplicate warning mixed from several letters; one line says the values are recognised per letter after splitting. Taking values over, "Record as receipt" and reading with an agent are off for such a stack; "No stack" brings everything back (#4468).
- Tests: p271_ui checks the project status that #3379 keeps on purpose and runs in the CI again (#4326).

### Changed
- Public repository tidied: no internal tool names in comments, a stray backup file removed (`*~` is ignored now), docs/ENV.md lists every variable the server reads (retention periods and switches, `KALMIDO_SPLIT_PAGES`; `tools/env_check.py` also sees helpers called through a module), current numbers in CONTRIBUTING, ARCHITECTURE, the MCP README and the third-party notices (#4180).

Package 2.527 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Fixed
- Offline conflicts from moving or editing several tasks at once now name the right task, and "Use mine" saves it to that task instead of failing (#4304).
- Knowledge pages: text typed just before the tab is closed or reloaded is no longer lost; in an encrypted space only the encrypted text is kept and sent. A text the server refuses (no right, too large) stays at the page as a draft with "Compare" (#4304).
- Ended session: input in the client dialog, comment drafts, the project dialog and the settings is kept and comes back after signing in again (#4304).
- Signing in with another account on the same device first downloads the previous account's unsynced changes and conflict copies as a text file (#4304).
- Installer: a failed download of a release's checksum list stops the installer instead of continuing unchecked (only releases before 2.277, which have no list, go on with a note); the Windows installer checks for Compose 2.20 and accepts a relative or ~ install folder (#4312).
- main red: p2391_b_toolsets was already fixed on main, suite checked green again (#4493).
### Changed
- The installers say exactly what they check: the prebuilt image is pinned to the release digest; the source is compared with SHA256SUMS on the tarball/zip way, not when it comes via git (#4312).
- API: the token dialog's help, the OpenAPI description and docs/API.md say everything the scope "read" opens (team chat with direct messages, clients with amounts, absences, family, home & life, video sign-offs and more); corrected defaults and answers (time_tracking, DELETE /lists, from-events, archived, address book trash); the outdated closing section is gone; the link check reports a code block left open (#4313).

## [2.532.0] - 2026-11-04

Package 2.521 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- Documents: a "Read" view with a large preview, a narrow list and paging in the full-screen view (#4476, #4399): on a computer the button "Read" next to Filter / Sort turns the list into a narrow column and the preview fills the height (all pages, zoom with + / - or Ctrl + wheel), the properties beside or below and foldable; arrow up / down page through the documents, also in "To review"; in the full-screen "Show" the arrows left / right and the buttons go to the previous / next document without closing; view and widths are kept per device. The width of the documents' side pane can be dragged (double click = default). Phones and narrow windows stay as before.
- Filter dialog as condition rows: "+ Condition", then What / Comparison / Value per row, one AND / OR for all, a live count "N tasks match"; folders include their subfolders, "is none of" always applies on top (also with OR); saved filters are converted and match the same tasks (#4479, #4478).
- `docker-compose.yml`: the database's memory settings as variables `KALMIDO_PG_MAX_CONNECTIONS`, `KALMIDO_PG_SHARED_BUFFERS`, `KALMIDO_PG_WORK_MEM`, `KALMIDO_PG_MAINTENANCE_WORK_MEM` (defaults fit a 1 GB limit), table for 512 MB / 1 GB / 2 GB in docs/SELF-HOSTING.md (#4475).
### Changed
- The database pool defaults to threads + 16 connections (was threads x 3 + 8) and closes idle connections after 30 s; the compose default `max_connections` is 60. Set `KALMIDO_DB_POOL_MAX` if you raised the threads a lot (#4475).
- Start budget: the CI is red only over a ceiling (`decke_*` in tools/perf_budget.json: start JS, CSS and language core gzip, start scripts); the per-package limits and the `--ratchet` are gone (#4391).
- Sidebar: with the favourites in the head bar there is no "Favourites" section in the sidebar any more; "Only favourites" is in the head bar's favourites menu (#4396).
### Fixed
- Chat: replying to an older message while scrolled up keeps the view where it is ("Sent" and the "New message" pill; tap jumps to the end); an agent's answer does not pull you down while you read further up. Agent chat, team rooms and threads (#4393).
- Sidebar: a folder's "…" appears left of the fold arrow on hover, the arrow stays visible and clickable (#4397).
- File store: a tag filter keeps the cards view instead of switching to the list (#4398).
- File store and knowledge rows: on hover the select box replaces the symbol in the same place, the name does not move (#4400).
- Documents: a recognition cut off by a database restart is taken up again within seconds instead of after 30 minutes (#4475).
- Test p2350_c_pins_race_ui counts only the fetches of the tested load() (#4087).

### Fixed
- main: CI red of 2.529.0 - four tests followed the app: the import undo test ages its address book too (#4366), the pins race test waits for the queue's own reload, the signature test scrolls to the drawing field on a phone, the invoice series test waits for the loaded series before "Make now".

Package 2.503 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Changed
- Support access (hosted servers): Settings > Account > Support access now says exactly what is recorded (time, method, route and status, never contents) and its limits: the same reading or refused request within 10 minutes counts once, at most 300 entries, the latest 20 shown (#4307).
- Documentation: docs/OFFICE.md and docs/PACKS.md match the code again for final invoices, travel allowances, the GoBD export, tax categories, depreciation, entertainment receipts, card fees and timesheets; new section "Office rights". Behaviour unchanged (#4178).
### Fixed
- Support access: what the operator does in a session started with a sign-in link is now on the customer's log, the sign-in included; before only the making of the link was. A path without a route no longer appears in the log (#4307).
- Agents: "Pause with a reason" now also holds the reference starter: no run starts, events stay in its queue and run after Resume, the reason is no longer overwritten by "working" or "idle" (#4309).
- Clients: an organisation admin who may delete a client can now merge it too and undo the merge; the error text promised this already (#4322).

Package 2.507 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Fixed
- Moving an account or an organisation no longer silently loses locked folders of the file store (#4300): the export carries the lock and the exporting person's own folder key, the import restores the lock, and names and files still open with the passphrase from before. If the key does not fit the keys on the target, the import preview (Settings > Account > Import) and its result name the folder and its encrypted content stays out, instead of files that could never be read.

## [2.529.0] - 2026-11-04

Package 2.499 (Bündel: Sicherheit: mitgelieferte HEIC-Bibliotheken in pi-, Doku Sicherung: Format 3 (2.432) überall nachziehe, Push: Rückfall von Web Push ).

### Security
- HEIC / HEIF photos are no longer decoded: `pi-heif` left the image. It is discontinued and its last release bundles libheif 1.23.0 and libde265 1.1.0 with known memory-corruption holes, reachable by uploaded files. iPhone photos are still stored and can be downloaded; they get no preview and no text recognition, and a receipt shows "This server cannot read HEIC photos at the moment" (#4168).
- On the channel Web Push nothing goes to the public ntfy.sh any more when no device takes a push (before: a neutral message). What writes a News entry has it there; a reminder shows only on its task. An own ntfy server and the channels ntfy and Both are unchanged; see docs/UPGRADING.md. Admin alert and the hints in Settings > Notifications say so (#4215).

### Fixed
- Phone: the buttons of the selection bar stay at least 44 px wide on the narrowest screens (#3899).
- Phone: in the side menu area names are never cut with "…": they take the lines they need; when a word does not fit, columns with short names give room, and only if that is not enough the row scrolls sideways (#4047).
- Backup docs describe format 3 only: an archive alone is not complete, every way by hand and from an off-site target needs the Download or `bkstore.py assemble`; the wrong line about the server key is corrected (#4172).

Package 2.513.0 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Changed
- Releases are published in two steps (#4354): a version tag builds the image `:X.Y.Z` and the GitHub release without "latest"; the image `:latest` and the latest release, which the installers, `update.sh` and the update check read, move only after that version passed its device test (workflow `promote.yml`, tag `latest-ok/X.Y.Z`). A blocker or a test that could not run leaves them where they were.
- The installers read the latest version from the forward of `github.com/.../releases/latest` instead of the API, which allows 60 requests an hour per address (#4355).
### Added
- Installer: over SSH it prints the ready `ssh -L` command instead of "Open it now"; `KALMIDO_URL=https://...` sets `PUBLIC_URL` in a new or an existing `.env`; at the end it says which address the links use (#4356).
- Administration > Server: a hint when the page is open on another address than `PUBLIC_URL`, the links in e-mails, push messages and password resets lead there (#4356).
- docs/SELF-HOSTING.md: section "From localhost to your own address"; "Try it locally" no longer advises a change in `docker-compose.yml`, which the next update overwrites (#4356).
### Fixed
- Installer: when GitHub does not answer it stops with a clear message instead of silently installing the unreleased branch `main`; `KALMIDO_VERSION=main` still works when named (#4355).
- Installer: the fallback `network_mode: bridge` is gone, Compose refused it beside the networks of `docker-compose.yml` and the file blocked every further try. Without a free address range it now names `docker network prune` and `default-address-pools`; the old line leaves the override on the next run (#4358).

Package 2.516 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Fixed
- Undoing an import no longer deletes the stored PDF and XML of a finalised invoice that stays (for example because a payment was booked since): the import notes which document each office file belongs to, older imports are judged by the document number in the file name, and the logo and letterhead copies stay while any remaining document names them (#4364).
- Undoing an account import keeps an imported calendar or address book that was changed since (for example renamed), no longer keeps every habit with a reminder time by mistake, and leaves sprints, rules and customer tickets alone in a list the person can no longer edit (#4366).
- Two flaky test suites are stable again and run in CI (#3716, #3717).

Package 2.491 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- Agent chat > gear: "Wishes for the replies" - a short text per agent (e.g. "Short answers, no tables"), with quick buttons for short answers, no tables and your language; saved on the server for you and this agent, on every device. Kalmido does not use it itself: it hands the text to the agent as `reply_style` with each of your chat messages, answer buttons and edits, and agents can read it through the agent API (`GET /api/v1/agent/chats/{uid}/reply-style`) and the MCP tool `get_reply_style`; an agent only sees the wishes of people it shares a chat with. The reference agent puts them into its prompt (#2849)
### Changed
- Office > client card: the block of documents made from templates is called "Letters & contracts" like its office page, with "No letters or contracts yet." and "New letter or contract"; the block name in the view builder and the area entry follow (#4020)
- Changelog: closed hundred series of versions move unchanged to docs/changelog/ (links under "Older versions" at the top); the "What's new" section of the README shows only the newest release (#2960)

### Fixed
- main: the Calendars dialog takes a click on its buttons at once instead of only after the calendars loaded; two test fixes (retention stub, a real login check after the upgrade).
- main: the MCP tool get_reply_style is in the chat toolset (an agent with --toolsets sees it).

Package 2.508 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Fixed
- Deleting an account (#4301): what it shares privately no longer goes with it. Private calendars, address books, tables with their files and the knowledge pages somebody else may write pass to the person who has had the right to write them longest, with everything the others entered; a share of a folder they lie in counts. Never to an agent, a child account or a disabled account, and never into a knowledge space with the lock. The delete dialog (Settings > People > Delete) now says what is handed on and to whom, and warns in a line of its own about what goes because nobody else may take it over (an organisation's admin sees numbers only). Shared folders and files of the file store still go with the account and are named there (#4347).

Package 2.501 (Bündel: Stille Grünmeldungen abstellen (übersprungene Suit, Sammelpaket: Aufgaben ohne Paket (Dispatcher), Test: jeder Büro-Menüpunkt öffnet).
### Changed
- The start of the app is smaller: the wiki encryption (loaded first with the wiki), the file store and the family module load on demand, and texts only the server names left the language core; about 54 KB less script and 125 KB less text, packed (#4198).
- The start budget only rises when the same change lowers another limit by as much; CI and the live train check it (`tools/perf_budget.py --ratchet`), and the limits were lowered to the measured values plus about 0.5 percent (#4198).
- `tests/stages.py --touched` gives core files, start files, translations and server files without a route a small fixed set of suites, translations also the suites naming the changed text; the push stage and the CI keep the full run (#4016).
### Fixed
- A test run that skipped something no longer says only ALL SUITES PASSED: it names skipped and partly skipped suites. No Firefox and a failed load of the on-demand modules now fail a suite; checks that could not fail became real checks (#4296).
- New suite: every office menu point opens its page by a real mouse click at computer and phone width, with no foreign dialog and no message; `tests/ff.js` has `realClick` for other suites (#4282).

Package 2.511 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Security
- A reply by In-Reply-To alone becomes a comment only when a token in the address names an account that sees the task. A forged sender address of a person with *mails from me* on no longer comments on the task; the mail becomes a new task in that person's inbox with the note "Reply to #N, sender not allowed" (#4071).

### Changed
- Docs: the privacy template and the list of outgoing connections now name Stripe online payment, invoice links in mails and the similarity service, and cover people without an account (bookings, polls, questionnaires, payment) (#4173).
- Docs: corrected short log addresses by default, unencrypted update dumps, office log reads (90 days), deleted mails and video sign-off records that stay, and what the assistant sends (#4173).
- Proxy templates: Caddy, nginx and Traefik name the right address for `KALMIDO_TRUSTED_PROXIES` per setup, with a command and what *Your IP* must show (#4311).

### Fixed
- Proxy templates: restoring a backup from a file works behind Caddy and nginx (4096 MB on `/api/admin/backups/upload`, one hour on the backup paths). Also the Traefik read timeout and installer file, the nginx `http2` line and certbot order, `/.well-known/carddav` and a dead link in the installers (#4311).
- Tests: `p2146_d_api` prints the server log at its first failure. Its one-time 500 on deleting an account after the export came from the deadlock fixed in #3090 (#4086).

Package 2.510.0 (Backup emergency path: tested and repaired, CI plan without cut-off shard times, robust Firefox start in the tests).
### Fixed
- #4286: a backup of an older version can be restored again: foreign keys added since the backup stopped `pg_restore --clean` ("cannot drop constraint users_pkey"). The keys taken away come back after the restore or, after a hard stop, at the next start.
- #4286: a restore whose way back failed no longer looks healthy: the server stays closed, `/api/health` answers 503, every request says an administrator has to restart it; the restart completes the database.
- #4286: the server start removes the work folder a hard stop of a restore or check left in the backup folder (a plain dump of the database). Helpers such as `app.py set-password` never touch it.
- #4327: the CI plan no longer takes suite times from shards cancelled at their time limit; a full run with such a shard does not end the way back to older times.
- #4346 #4348: tests/ff.js: a retry after a hanging Firefox could not work (same profile, lock still held). Every start has its own profile, a Firefox has really ended before the next start and before its folder goes, three tries, a Firefox that died costs no wait. p2151_ui is back in the CI.
### Changed
- #4286: new suite p4286_restore: four round trips with a content check (encrypted format 3 with a joined file, a backup of 2.101, a backup of another instance with sealed files, init_db failing after pg_restore). tests/fake_offsite.py behaves like the real stores (S3 pages, WebDAV PUT creates no folder). Tests for the folder list of a backup, for secret-like columns of the organisation export (lint) and for rows of others in it.

### Fixed
- main: a restore of a backup no longer hangs in maintenance (503) when the git loop meets it: the loop's reads are gated and committed before it waits (signin_ui, CI red of 2.506.0; the same in the calendar, address book and ntfy inbox loops).
- main: the tax dates keep a saved change when a load begun before the save answers after it (p290_c_ui, CI red of 2.506.0).
- main: the one-time issue import of a repository asks where the issues go before it writes (p2356_b_import_target, CI red of 2.506.0).

Package 2.506 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Fixed
- Undo of an account or organisation import no longer removes work done since the import (#4299): every table is now treated like the tasks. Habits (with days logged since), filters, templates, time entries, journal days, bookmarks, files, knowledge pages, tables, mails, video sign-offs and office rows stay when they changed since the import or got something new below them, also a file laid or moved into an imported folder. The result message counts them ("N entries changed since the import stay").
- Files, knowledge pages and tables of an undone import go into their trash instead of being deleted, with their stored files, and can be restored from there; the message names how many. Their labels and custom fields wait for them; the top folder of an area stays, empty. The other unchanged rows are deleted as before. The 24 hour limit of the undo is unchanged.
- An import that only invited people now has its record, so its undo can withdraw them, and the sharing step no longer loses the file's source keys, so the next import of the same file does not take everything over a second time (#4299).

Package 2.500 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Security
- Support access (hosted): a support session now reads and edits contents only. A positive list of write ways replaces the old list of blocked ones: app connections (OAuth consent, page and form), new agents, public links, shares, members, invitations, webhooks, keys, feeds, office settings, sending and deleting for good answer 403 (#4070).
- Support access: the writes of a support session stand on the grant's log, refused ones included, so the customer sees them under Settings > Account > Support access (#4070).
- Office rights: a cash book entry on an invoice books (and its cancellation takes back) a payment only with quotes edit and the special "pay"; cash without an invoice stays free (#4072).
- Office rights: bank matching of kind card needs credit cards edit, kind payout needs receipts edit (#4072).
- Office rights: the tax forms as CSV / PDF and the original files of the booking archive need the special "export"; their buttons are hidden without it (#4072).

### Fixed
- Office: a click in the office's navigation (sidebar, start list, tabs, tree) no longer opens the e-mail signature editor; it opens only with "Edit" in a send dialog (#4058).

### Changed
- Tests: suites whose flakiness task is closed and that stayed green on repeated runs are back in the run; tests/skip.txt loses their lines (#4083).

Package 2.505 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Fixed
- Offline changes: being removed from an organisation no longer empties the offline queue without a word. Private tasks, notes and knowledge texts go out as usual; a change the server refuses waits in the conflicts dialog with its text (#4298).
- Agents: opening *Projects* on an agent card makes only that card longer. The card next to it keeps its size and layout (#4325).
- Restore: deleted entries an older off-site backup still holds can no longer come back for good. The list of what was deleted for good now also waits for the backups kept on the off-site target (#4302).

### Changed
- Settings > Users > Whole server > Backups, restore dialog: it now shows what was deleted for good since this backup and would be deleted again (number per kind, time span). You choose between *Delete them again* (default) and *Keep everything in the backup*. The choice is in the admin alert and the log (`keep_purged` on `POST /api/admin/backups/restore`, `GET /api/admin/backups/purged-preview`) (#4302).
- Self-hosting and OIDC docs follow the code: what stays readable with browser encryption, that the trash is not in the organisation export, what stays behind in a move (the household budget), the key change, and smaller corrections (#4314).

Package 2.504 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Changed
- "All workspaces" has no colour of its own and no grey any more (#4222): tasks and lists wear the colour of their workspace, everything else Kalmido's accent. On a phone: in All workspaces the stripe and dot are the accent colour; progress and selection of a row in Today, Inbox or Kanban, and the buttons and ticks of an open task or list, show the workspace's colour, while the navigation, plus button and search stay in the accent colour. An open list's own colour still wins there, a workspace with "No colour" uses the accent, and with "Interface in the colour of the workspace" off nothing changes.

### Fixed
- Tests: every jsdom window has `CSS.escape` and `CSS.supports` from `tests/boot.js`, the hand-made shims are gone; p2440_a_ui and p2435_a_ui run again (#4084).
- Tests: the undo suites wait for the recorded history step and the undone state instead of a fixed pause; p284_a_ui, p297_c_ui, p271_a_ui, p2365_2_b_ui, p2115_a_ui and p21121_b_ui run again (#4085). p2147_a_ui stays skipped: one switch makes two undo steps (#4343).
- Tests: p2130_ui checks that sending with real taps opens no menu (#4230, a regression test only; the reported menu is not reproduced yet).

Package 2.394 (Zwei-Wege-Abgleich GitHub/GitLab, Import aus Linear und GitHub).
### Added
- Import from Linear: Settings > Data > Import > "Linear" takes a personal Linear API key (used for this one run, never stored) or Linear's CSV export; teams become projects with status, priority, estimate (story points), labels, type, cycle (sprint), due date, parent issues, assignee and comments; preview and 24 h undo as for the other imports (#3377).
- GitHub / GitLab issues can be taken over once: Project settings > Repository > "..." > "Import issues", with a preview (count, already imported, first titles), the option to skip closed issues and undo. Text, labels (as project tags), open / closed, assignee (matching project member), comments with author and date and the link back are kept; pull requests are skipped, nothing is written to the repository (#3377).
- Two-way sync of issues per repository (GitHub and GitLab): Project settings > Repository > "Sync issues both ways" (off by default, project admins only). Title, text, open / closed, labels and comments follow each other; new issues land as tasks in the Backlog section; "Create new tasks as issues" (off by default) sends new tasks to the repository. When both sides changed the same field, the newer change wins and the other version stays in the task's history - nothing is overwritten silently. Locked notes, attachments, custom fields, personal tags and encrypted projects never leave Kalmido; a token without write access keeps the sync read-only and the settings say so (#3377).
### Changed
- Jira CSV import takes over the issue type (Bug / Story / Task), story points and the sprint of open issues instead of writing them into the notes; imported projects switch on story points, ticket types and sprints when the data has them, and the undo removes the sprints an import created (#3377).

Package 2.502 (Bündel: Büro: Peppol-UBL und XML-Neuaufbau nehmen den Zahl, Büro: Gemeinsamer Zähler (#3597) - Datums-Chronolo, Büro: Reverse Charge bei Kun).

### Fixed
- Read-only role: the disposition now keeps the promise of the role. People with it see the week and "Who is free", but the *Book* button is gone, a booking opens for reading only, and the server refuses creating, changing, deleting and restoring bookings (403), also for an agent's shoot proposal they apply (#4308).
- Office, e-invoice: the Peppol document and an XML rebuilt for an older invoice no longer take today's payments: paid and payable amount (BT-113 / BT-115) stay as in the stored PDF, only progress invoices count as prepaid (#4079).
- Office, shared counter of invoices and corrections: the date check treats both as one series; a correction or an invoice dated before the last finalised document of the other kind is refused (#4080).
- Office, reverse charge: refused before finalising for a client outside the EU and outside your own country (choose *Not taxable domestically*). An older document of that kind counts in UStVA field 45 instead of 21 and on the not-taxable DATEV account (8338 / 4338) and can still be corrected (#4081).

Package 2.497.0 (Document view in one grid, list titles edited in place, workspace switch stays in the area).
### Changed
- Documents (#4046): every field of a document (receipt, correspondence, document) stands in one grid of label and field; on a phone (320 px) the label sits above its field. The receipt fields appear only at a receipt (a recorded receipt, an open suggestion, an e-invoice to take over, a recognised net amount, VAT rate or invoice number); any other document gets the button "Record as receipt". The actions are ordered: Show, Readable view, Download in front, rarer ones under "More…", Delete set apart at the end. "Due" and "Amount" are chips, "Recognised text" a section with a heading.
- List (#4056): double-click, E or F2 edits a title where and as it stands: same font, wrapping over several lines, the field grows with the text, the caret at the double-click, Enter saves (no line break, pasted breaks become spaces), Esc cancels, a click beside saves. A one-line title with an ellipsis in a row with columns opens to the whole title while editing. No frame over the text, a soft tint instead.
- Workspaces (#4048, replaces the page kept per workspace of #3404): a switch stays in the area shown. An open project that is not in the target goes to Projects, a list to the Basket, another single object to the overview of its area, an area missing or switched off there to Start. An open task stays when the target shows it, else it closes; the switch reopens no task remembered for the view. The scroll position, open groups and folders stay per workspace.
### Fixed
- Shopping mode on a touch device (#4040): it had two history entries, closing it left one behind and the next Back did nothing. The test p2190_family_ui passed by luck in the moment between the two; it now waits for each state and also covers Back.

### Fixed
- main: two UI tests no longer overtake the page on a slow CI runner (tax dates, signature picture of entertainment receipts); the Firefox helper of the tests now says why a browser gave no connection (#3506)

Main red after CI 2.496.0 (#3506).
### Fixed
- main: account import, knowledge import, account export and organisation export no longer report "interrupted" when the run ends in the moment the status is read (#3506).
- main: tests p2363_3_c_ui and p2350_c_wkimport_status_ui no longer depend on the timing of a state load or of the import poll (#3506).
- main: test p271_ui expects the project status without collaboration (decision of #3379) and runs again, its line in tests/skip.txt is gone (#3745, #3506).

### Fixed
- Agent chat: after turning a tablet or unfolding a phone while typing, the message box keeps its focus. It used to lose it on a slow device because the new layout came later than the single retry (#3506)
- Background jobs: a push or mail queued right after the worker had checked its queue no longer waits up to three seconds (#3506)
### Changed
- CI: the full test run takes as many shards as 30 minutes each need (at most 28). Two of 20 shards ran into the 50-minute limit with every suite green (#3506)

Package 2.448 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Tests auf main rot: p2186_c_retention und p2361_d_, Sammelpaket: Aufgaben ohn).

### Changed
- The app code carries no private texts any more; the default of PUBLIC_URL is the local address, set it in the environment (#3633).

### Fixed
- Office menu: the group Money shows Figures, Cash flow, Travel, Entertainment and Subscriptions at once, also before their first use (#3784).
- Language: a text for another person follows that person's language: the poll mail (the language used when voting), reasons of invoice series, the status of background imports, proposal titles, the name of encrypted files in the history (#3765).

### Fixed
- main: the open area in the phone drawer keeps its contrast again (#3739); the agent setup test follows the revoked "Create agent" token (#1762).

Package 2.450 (Bündel: Handy-Leiste: Bereiche zuerst, Heute und Eingang n, Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Changed
- Phone sidebar: from the top search, the row of the areas, then the content of the chosen area. Today and Inbox belong to the Plan group again and show only in the area Projects, with the same order and hide rules as on a computer; they are gone from other areas such as Office (#3817).
- The agent starter speaks the agent's language in chat in de, en, fr, es, it and nl: permission questions, failed runs, reminders, yes/no buttons. Status texts also go to the app as keys (`text_key`, `text_at`, additive and optional) and are translated there; old starters and servers keep working (#3769).
- Sizes and numbers follow the app language everywhere; French shows o, Ko, Mo, Go. Backup and storage sizes now count in 1024 like every other size (#3770).
- Names, tags and titles sort by the app language, Spanish ñ comes after n (#3770).
### Fixed
- Amounts of 1000 and more with separators (1.234,56 or 1,234.56) work in family money fields and on documents; a wrong order is refused, never read as another value. A German quantity of 1.500 no longer turns into 1.5, nor an English agent budget of 1,500 (#3770).
- Sheets read dd-mm-yyyy dates; dates of an en-US browser no longer mix orders (#3770).
- Yes and no typed in fr, es, it and nl count as an answer to a starter question, and the check for questions without a card knows these languages (#3769).

Package 2.449 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Added
- Office: all 17 document, letter and legal samples and the film pack in French, Spanish, Italian and Dutch; the legal samples (confidentiality, data processing agreement, privacy notice, consent) carry the note "machine translated, check before use" there (#3768).

### Changed
- Office: the default title of a summary position is empty and neutral ("Services"), the old film title stays only with the film pack on de / en; a new office without a country pack takes the user's language for its documents (#3766).
- Office: the procedure documentation stays German / English and is offered with the German pack only; whoever has saved versions keeps them (#3768).
- Office: the fixed costs template and the export manifest speak the user's language (#3768).

### Fixed
- Office: privacy sheets in fr / es / it / nl send their mail in that language, a sheet from a sample no longer fails; PDF reports use the document language for amounts, dates and file names (#3766).

### Security
- pyasn1 0.6.5 and pypdf 6.21.4: fix the denial-of-service advisories of 30.10.2026 (#3807).

### Tests
- The start clock logs on stderr; p2470_a_roles_ui waits for the role row (#3807). The freelancer guard counts a method on the line above only for an open multi-line call, four write routes got real calls (#3800).

Package 2.362.3 (Teil 3/4: Bündel Export 1: Konto-/Org-Export vollständig (2.279 + Export-Funde)).
### Changed
- Account export: when an export carries projects of an organisation, its other admins get one News with the number of projects, at most once a day per project; the projects stay in the file and the list history names them (#3101).
- Account import in Settings > Data: a file imported before is named in the preview (when, which import, undo until when) and needs the tick "Import again". This also holds for a newer export of the same account (#3098).
### Fixed
- Importing an export twice no longer doubles projects, contacts, events, habits or time entries: what is already in the chosen place is skipped row by row, a newer export adds only what is new, another workspace still gets its own copy (#3098).

Package 2.363 (Teil 1/4: Bündel Import und Verschieben: Reste Audit L/R (2.286 + 2.288 + Export-Funde)).

### Added
- Org import: the projects ticked for an invited person are noted on the invitation and shared when the person accepts; declining, withdrawing or undoing drops the note; tasks keep their creator and assignee (#3132).
- Legacy import: e-mail, phone, customer number and VAT ID of clients come from their columns, also beside a one-cell address, and can be chosen in the column choice; the preview names the columns nothing takes over and says when a file holds more rows than are read (#3103).

### Changed
- Move guide: complete checklist of paths, settings and outside services, what a backup archive holds (kept to the code by a test), the organisation import described as it is today (#3102).

### Fixed
- Knowledge ZIP import: the next step right after a run waits for it to end instead of reporting that an import is running (#3280).
- Legacy import: UTF-16 CSV files are read, a postcode or number with the format 00000 keeps its leading zeros, row numbers count title rows, six digits in a file name read as DDMMYY first and are marked unsure when both readings fit (#3103).
- Trip import: Mac Excel files with the 1904 date system give the right days; per diems and lead values read "1.500" as 1500 (#3103).

Package 2.451 (Bündel: Handy: Büro-Listen ohne Symbole in der Zeile, lang, Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Handy-Leiste: Bereiche zu).
### Added
- Office lists: a sort choice of date, client, amount and name on quotations, invoices, credit notes, reminders, delivery notes, the archive and the pipeline, on computer and phone alike, remembered per list (#3834).
### Changed
- Office lists on a phone: quotations, invoices, the archive, trips and entertainment receipts show no symbols in the row, the row uses the full width; a long press opens the row menu. In the archive the row menu is new (also right click on a computer), and the PDF view on a phone has Correct (#3834).
### Fixed
- Counts read in the singular for one thing in all languages, at about 30 places in lists, wiki, documents, sheets and bookkeeping; the push hint in the settings is one sentence (#3771).
- Office: the service dialog waits for the freelancer roles, and saving no longer clears the role when they could not be read (#3809).

Package 2.452.0 (Office lists on phones, quick add languages, import memory).

### Changed
- Office on phones (#3836): Contracts & insurance, invoice series, bank rules, contract PDFs, DATEV suppliers, travel purposes, entertainment places and people and the data protection sheets of a client show no symbols in the row. Tap opens, hold opens a menu with everything the row had. A hint explains it once. The computer stays as it is.

### Fixed
- Quick add understands month names, day and year in every app language ("5. Oktober", "5 octobre", "5 de octubre", "5 ottobre", "5 oktober") and list words ("dans la liste X", "en la lista X", "nella lista X", "in de lijst X"); time entry reads Dutch "21 uur" (#3772).
- Account import: the record of what came from a source no longer drops out after 20 other imports, so the same file cannot create everything twice (#3810).
- Test p252_a_ui no longer drags at the edge of the 15 minute snap (#3822).

Package 2.453 (Bündel: Handy: Meldung bricht mitten im Wort um (Gespeiche, Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Changed
- Inviting a new address into an organisation now works like inviting an existing account: the person joins by accepting the invitation in the News, after setting a password; the link lasts 14 days instead of 7. On a hosted instance an instance admin also invites a new address instead of adding it directly (#3780).
- Settings > Notifications: a new row for mail limit notes (customer portal, booking page). News only, on by default (#3781).
- The Karakeep fetch button runs in the background and shows no count; a wrong key appears in the Karakeep settings (#3781).
### Fixed
- Phones: the message at the bottom is as wide as its text up to the screen edge, "Saved" no longer breaks inside the word next to Undo and Close (#3840).
- Office: a finalised quotation keeps the heading it was finalised with when an industry pack is switched on or off later; older finalised quotations show the country pack's word (#3816).
### Security
- The member list, the list of open invitations, and the answer to Resend no longer tell whether an address already has an account (#3780).
- Deleting an account leaves a table share by address open instead of removing the row, which told that the address had an account (#3781).
- Letterheads and terms too large for the virus scanner carry the "unchecked" mark; a frozen letterhead from an import is copied only under the name of its content and with the strict scan (#3781).

Package 2.362.2 (Teil 2/4: Bündel Export 1: Konto-/Org-Export vollständig (2.279 + Export-Funde)).
### Added
- Settings > Data > "Move and export everything": the file now holds a readable copy of your own office (invoices, receipts, cash book) under personal-office/, and the files of your knowledge pages and tables (#3099).
- Office settings > "Export the office": the archive now carries the receipts and filed documents of the office (cash book pictures, filed letters, contract and equipment documents); the import points the office at them again (#3099).
- Retention export: procedure documentation, number ranges, opening balances, locked periods, equipment, reminders, purchases, suppliers, Peppol sends, sign-offs (without the network address), contracts and agreements, bank balances, rights log; the index names the new folders books/ and contracts/ (#3105).
### Changed
- Without a server key (KALMIDO_SECRET_KEY) the organisation and the office export are a plain ZIP with a warning instead of being refused (#3099).
- The account export no longer points a person without an organisation at an organisation export; the import preview says the office stays behind and how to take it along (#3099).
### Fixed
- A static guard names every office table that stays out of the retention export with its reason (#3105).

Package 2.360.3 (Teil 3/5: Bündel Sicherheits- und Datenschutz-Reste, Abhängigkeiten (2.197 + 2.223.9 + 2.239.1 + 2.313)).
### Changed
- Moving a large folder to another workspace is quicker: the retention check looks only at files that can be locked at all (#2733).
- The image is reproducible: every Python package, also indirect ones, comes from a lock file with hashes, base images are fixed by digest, CI tools carry versions; the audits now also cover the embedding service, the test tools and the bundled pdf.js (#2915).
- CI and tests run on Node 24 (#2916).
### Fixed
- A receipt taken off a cash book entry keeps its retention lock (#2733).

Package 2.454 (Bündel: Handy: Suche endet nach dem Ausblenden der Tastatu, Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Fixed
- On a phone the search now uses the whole visible height: above the keyboard while it is open, down to the bottom of the screen without it; few hits keep it small (#3842).
- Texts kept for later follow whoever reads them: invoice series reasons from finalising and sending, the areas an account import leaves behind (preview, warning, report), checks of the background wiki import, proposal titles in the task history (#3808).
- Accessibility test p2160_a11y and the other theme / accent tests really run dark and in each accent: the device keeps its own look, the account's look no longer overrides it (#3824).

Package 2.363.2 (Teil 2/4: Bündel Import und Verschieben: Reste Audit L/R (2.286 + 2.288 + Export-Funde)).
### Added
- Office > Settings > Import: imports of fixed costs, trips and leads now appear under Import runs and can be undone there for 24 hours; entries changed since stay, leads go to the trash (#3104).
- TickTick import: a preview first, then the import, with "Undo this import" and the same limits as every other source; also available as source `ticktick` in the API (#3104).
- Newsletter consent import: can be undone from the message after the import and under Settings > Data; contacts go back to their earlier status unless their consent changed since (#3104).
- Account and organisation export: files that could not be read are listed as `missing` in the manifest instead of failing the whole export; list icons, header images and the organisation icon are in the archive under `files/pictures/` (#3106).
### Changed
- Fixed costs import: finds the first sheet with a header row and also reads CSV and .xls (#3106).
- The import page now says what is true about undoing instead of promising every import can be undone (#3104).
- Up to 20 imports are kept per person, plus all that can still be undone (#3106).
### Fixed
- Leads without an e-mail are recognised as duplicates, also inside one file (#3104).
- TickTick: broken dates and numbers or Windows-1252 files no longer show raw errors; a deleted or archived list of the same name is not filled (#3104).
- Task CSV understands priorities as numbers; import errors name the column instead of technical fields and count the rows of the spreadsheet (#3106).
- Contacts import names the cards it could not read, the address book limit says the number, vCards fall back to Windows-1252 (#3106).
- Calendar import says why a file could not be read; bank import says when the file field is missing (#3106).
- Organisation import keeps the link of a filed mail to its file, so the mail's visibility rule still applies (#3106).

Package 2.455.0 (Bündel: Handy: Arbeitsbereich wechseln schließt die Seiten, Verschieben: nur Projekte des eigenen Arbeitsberei, Handy 320 px: Namen in Zeile).
### Added
- Task menu, batch bar and the project picker: "Move to another workspace…" chooses the workspace first, then the project there; it asks before moving and names the task (or the number of tasks), the workspace and the project. Undo stays. Shown only with a second workspace (#3848).
- Moving to another organisation: the feeds and the read-later project of an organisation come along. Moving your account: sprints, further project placements of tasks, rules and customer reports of your own lists come along (#3469).
### Changed
- "Move to project" lists only the projects of the task's own workspace. A task in the inbox uses the workspace on screen; under "All workspaces" it lists all projects under clear workspace headings (#3848).
- Dropping a task on a project of another workspace asks first as well (#3848).
- The import report names rules that were paused or left out and feeds without their address; "not included" names agents and feed addresses that carry an access key (#3469).
### Fixed
- Phone: switching the workspace in the open sidebar keeps it open and shows the new workspace; it closes on a tap on an entry or beside it (#3847).
- Phone at 320 px: in Settings > Organisation names get their own first line with the role selection below; in Office > Receipts the file name gets the first line and the labels the second (#3852).
- Organisation import: rule triggers and actions and sprint close-outs no longer keep ids of the old server (#3469).

Package 2.456 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Changed
- Changing an order now works the same everywhere: hold the grip, then drag. Office positions (also inside an open part), parts, form questions, budget categories, the phone list of dashboard blocks, layouts, side views, project links and scan pages. On a computer the arrows stay for the keyboard; on a phone they are gone (#3837).
- Money fields of documents read an amount like the document's amount, by language: "1,500" is 1500 in English and 1.50 in German; "1,234" in German is refused as too many decimals instead of being read as 1234 (#3819).

### Fixed
- Organisation import: the former owner of a project gets it shared like its members, also through the note on the invitation; the importing admin stays the owner (#3821).
- Locked folders: unlocking no longer fails with "No encryption change is running" when a second run finished the switch first (#3851).
- Test suite p21522_c_ui waits for the value on the server; p21522_c_ui and p2353_a_lockfolder_ui are off the skip list (#3850, #3851).

Package 2.363.3 (Teil 3/4: Bündel Import und Verschieben: Reste Audit L/R (2.286 + 2.288 + Export-Funde)).

### Added
- Uploads from 1 MB show a progress bar with Cancel at the bottom of the screen, in every dialog (#3134).
- Duplicating a list or task and list templates take everything except comments and times: assignees, attachments as copies, other people's tags, person and task fields, sprints, WIP limits, links; people stay only where they may be assigned (#3134).
- `POST /api/tasks/<id>/duplicate`; `POST /lists/{id}/duplicate` answers `skipped_files` as well (#3134).
- List CSV: columns for repeat, reminders, dependencies and the number of comments and attachments (#3134).
- Documents: "Recognise again" can be taken back for 24 hours (#3134).
- Joining an organisation again within 24 hours restores assignments and coming along where the task can still be seen, in lists open to the organisation (#3133).

### Changed
- Template updates are partial, per node (#3134).
- All file dialogs use the server's limit instead of a fixed 50 MB (#3134).
- Moving a folder with several lists keeps a memo per list; moving it back within 24 hours restores it (#3133).
- Knowledge pages in the trash move along with their folder (#3133).
- Tables and knowledge files of a move are sealed into a new stored file and swapped after the commit (#3133).

### Fixed
- Household budget import says when a purpose is cut to 200 characters (#3134).
- An "also in" request waiting offline during a move is kept for the way back (#3133).
- An own order of My tasks that waited offline no longer overwrites a newer one; places of completed tasks stay (#3133).
- ICS import weighs a changed occurrence by its own LAST-MODIFIED (#3133).
- The way back of a files move restores the project of a receipt suggestion (#3133).
- Archive numbers written from a code take the number lock: preview catch-up, split, unsplit, files move (#3133).

### Fixed
- main: the start order of the scripts is back (upload bar after the on-demand loader), and the account export now also carries the file copies of your templates (the import names them as staying behind).

Package 2.367.2 (Teil 2/5: Bündel Benachrichtigungen (2.267 + 2.268)).
### Added
- News, push and bundled mail "Approval needed: <task> (from <person>)" when someone asks you for an approval; before it only said you were assigned, and nothing at all when you already had the task (#2968).
- Reviews: when a review is approved (by a person or a merged pull request) the person assigned, otherwise the creator, gets a News item and a push (#2968).
- Calendar: when an event you are invited to moves, gets another place, is cancelled or deleted, loses one date, or you are taken off the guest list, you get a News item and a push; switch: "Assignments" in the notification settings, as for invitations (#2969).
- Booking page: new bookings and cancellations by the customer now also appear in the News and in the bundled mail, not only as a push (#2969).
- A calendar subscription that failed three times in a row tells its person once in the News (own row "Calendar subscriptions" in the notification settings, News only); the message goes away once it works again (#2969).
### Changed
- Agents: a question with answer buttons or an approval card on a task pushes even with "Pushes for what agents do" off and with the work style "only at limits", and it never ends up in a "1 more comment" summary (#2968).
- Assigning a task to a group now sends push and mail to its members like a personal assignment (#2968).
- News "An agent waits for my approval" is on by default, and list-wide approval requests stay in the News (#2968).
### Fixed
- An approval decision no longer disappears in a "1 more change" summary and arrives as one event: no extra "completed" or "assigned" besides it (#2968).
- A plain agent comment with agent pushes off no longer leaves a later "1 more comment" push (#2968).

Package 2.359.3 (Teil 3/4: Bündel Datenverlust beim Tippen/Offline + Sicherung (2.271 + 2.223.4)).

### Added
- `docs/UPGRADING.md`: every version that needs a step from you, how big jumps work, and the format limits for going back; *Back to the previous version* in SELF-HOSTING.md (#2896).
- A database keeps its format limit (`back_floor` in `kalmido_meta`, currently 2.149): an image below it refuses to start and names the step to run, also as the one step back; `KALMIDO_ALLOW_DOWNGRADE=1` is the emergency way (#2896).

### Changed
- Restore: a backup whose organisation or account keys do not open with this server's key is refused before anything changes, and verifying it warns; with `KALMIDO_SECRET_KEY_CHANGED=1` it restores with a red warning. A backup without such keys but from another key restores with a warning about stored tokens (#2893).
- An existing server without a server key keeps starting and now alerts the admins at every start, next to the warning in the settings (none with `KALMIDO_NO_SECRET_KEY=1`) (#2510).

### Fixed
- Backups: before each backup the major versions of `pg_dump` and the server are compared; an older `pg_dump` stops with a clear message, Settings > Administration names it and the admins get an alert, instead of backups failing without a word (#2945).
- SELF-HOSTING no longer promises an automatic rollback no tool performs (#2896).

Package 2.367.4 (Teil 4/5: Bündel Benachrichtigungen (2.267 + 2.268)).

### Added
- Office: a payment booked on an invoice tells the office's other admins (bell + push, number and client, never an amount); an overdue invoice rings the bell once, also without payment reminder suggestions (switch "Tell me when an invoice is overdue" in the office settings, row "Payments and overdue invoices" in Settings > Notifications) (#2972)
- An existing account invited to an organisation also gets a push and a mail; whoever invited hears the answer; a changed role in an organisation is a News item (#2974)
- Settings > Notifications: row "Notices from the server" switches the maintenance push off (#2974)

### Changed
- Invoice series: everything that needs a person on one day is one task per person ("3 invoice series need you") (#2972)
- The portal sign-in link goes out in the language of the client's newest document (#2972)
- An organisation's events stay with it: an agent's usage limit goes to the organisation's admins and the owner, an organisation admin's sign-in from a new address to the organisation; the instance admins get a number. A registration by domain tells the organisation's admins too, the instance admin still approves (#2974)
- Admin alerts: two-factor sign-in turned on is summed up per window and not sent to the person alone; repeated resets wait out the cooldown (#2974)

### Fixed
- A maintenance notice with a push failed with an error (#2974)
- The registration push follows the notification setting (#2974)

Package 2.362.4 (Teil 4/4: Bündel Export 1: Konto-/Org-Export vollständig (2.279 + Export-Funde)).

### Fixed
- Account import (#3100): no id of the old server stays behind: mentions in comments and team chat point at the new account or become plain `@name`, saved filters carry the new project, section, field and person ids (a filter on something that did not come along is left out and named instead of showing everything), templates are stored as a new template is, person and task field values and formulas are rewritten.
- Account and organisation import (#3100): a full storage now leaves out only the files: time entries, habits, contacts, calendars, journal and settings still come, the sharing still runs, the result names what is missing.
- Account import (#3100): a file that turns out damaged during the run leaves no written files behind.
- Imports (#3100): a run of imports no longer removes the record of an import that can still be undone; Settings > Data lists all of them.

### Added
- Tests/CI (#3107): `tools/check_export_tables.py` in the lint step: every table with people's data is in the account export or named with a reason (`kalmido/admin/exportleft.py`), the same for the organisation and the retention export, and the imports read or name every part. `not_included` of the manifests comes from these lists.

Package 2.368.2 (Teil 2/5: Bündel Englisch und Formate (2.264 + 2.265)).
### Changed
- Office CSV exports follow your language: income statement, cash book, logbook, equipment value, meals, travel and per diem use "," and the decimal point in English, ";" and the decimal comma in German, French, Spanish, Italian and Dutch, so Excel reads the amounts as numbers (#2984). Contact, video comment and journal exports use the same separator.
- Logged times in the cash book, logbook and meals CSV are shown in your time zone from Settings > General > Region and formats instead of raw UTC; the cash book and logbook PDFs show local time too (#2984).
- Documents write the date of their language, the country pack is only the fallback: invoice period placeholders, delivery notes, letters, template documents, terms ("as of 9 October 2026") and travel or outlay lines on an invoice no longer show a German or ISO date in an English document (#2986).
### Fixed
- Tasks and messages of recurring invoices, subscription reminders and the DATEV fiscal year error show dates in the reader's language (#2986).

Package 2.368.3 (Teil 3/5: Bündel Englisch und Formate (2.264 + 2.265)).

### Added
- Tables: English formula names are equal to the German ones: `SUM`, `IF`, `TRUE`, `project.`, `list.`, `client.`, `task.`, `here.` with `total_time`, `tasks`, `open`, `done`, `rate`, `budget_amount`, `title`, `due`, `time`, `assignee` (#2988).
- Settings > General > Region and formats: the time zone now lives here for everybody, shows when this device is elsewhere, and is taken from the browser at the very first login (#2985).

### Changed
- Tables: a formula reads in the person's language (German in German, English in all others), the suggestions after "=" and the hints too; both languages are always understood and found, formulas are stored in one neutral form, older cells keep working (#2988).
- Formula fields: the help names the functions in the person's language; the examples of Spanish, French, Italian and Dutch used names the server does not know (#2988).
- Reminders, fixed-time reminders, nags, event reminders, follow-ups, habits, the daily summary, the briefing, the review and "staying in touch" come at the person's own hours; quiet hours and "today" in those texts follow their time zone; agents' time checks use it too (#2985).
- Pushes show times in the chosen time format (12 / 24 hours), Automatic stays 24 hours there (#2985).

Package 2.458.0 (Bundle: names in the area bar, repeat texts, office lists over 500 documents, organisation invitations, 320 px details).

### Fixed
- Phone drawer and computer bar: the names of the areas no longer break inside a word (Rückblick, Gewohnheiten); a word too wide takes a smaller type or ends in "…" with the whole name as tooltip (#3880).
- Repeat text of a task: monthly rules are one whole text per language instead of pieces put together (#3838).
- Office lists over 500 documents: the sort choice (date, client, amount, name) now covers all documents of the list, not just the newest 500; rows without a value stay last (#3839).
- Organisation invitation: withdrawing it no longer deletes a never used account that another organisation has an open invitation for; only the own invitation ends (#3843).
- Phone at 320 px: Read later and Bookmarks list have their buttons below the title; meals in the meal plan break between words, the day stands above them; amounts keep number and currency sign on one line; Events today on the Today page has one "…" button (the calendars are in its menu); long hints in narrow fields end in "…"; all-day entries in the week view are cut to one line (#3855).

Package 2.367.3 (Teil 3/5: Bündel Benachrichtigungen (2.267 + 2.268)).
### Changed
- A person's forwarding with "Changes in my own projects" no longer reports what they did themselves; the new choice "Including my own changes" brings it back. An inbound webhook and a rule count as news. Organisation forwardings stay a team feed (#2973).
- A failed forwarding message gets one more try after a minute before it is dropped (`KALMIDO_CHANNEL_RETRY`) (#2971).
### Added
- Notifications > "Integrations" (News and push, on by default): a forwarding or webhook that turned itself off, a paused inbound webhook, and a mailbox, git connection or ntfy inbox after 5 failed fetches in a row (`KALMIDO_INTEG_FAILS`) tell who can repair them, once per outage; organisation forwardings and webhooks tell the organisation's admins (#2971).
- A failed backup reaches every instance admin as News, push and e-mail, whatever the admin alerts are set to, once a day per error (#2971).
### Fixed
- Completing a repeating task reaches the forwardings; rule runs "due date reached" do too (#2973).

Package 2.370 (Teil 1/4: Bündel Konfliktschutz- und Wiederherstellungs-Reste (2.269.1 + 2.270.1 + 2.272.1 + 2.205 + 2.210 + 2.287)).

### Added
- Peppol view: **Mark as not delivered** for a send to Storecove that waits for a confirmation (this provider reports no rejections); afterwards **Send again** is free, the office log has it (#2778).
- API v1 `POST /tasks/batch` and MCP `batch_tasks`: `_prev` (update) and `expect` (complete, wont_do); a task changed since is skipped and listed in `conflicts`. Without them nothing changes for older agents (#3126).

### Changed
- Assigning a sprint, the sum row, key figures and the list's sort keep a value someone else set in the meantime and say so; redo of a task due several times a day also compares the time (#3126).

### Fixed
- Retention export: files locked by the virus scanner stay out and are listed under `locked_files` in the manifest and in the index; project receipts were not checked before (#2781).

### Fixed

- main: receipts CSV and ZIP export answer again (500 for areas with a decimal comma), test list of old names knows the ntfy inbox notice.

Package 2.370.2 (Teil 2/4: Bündel Konfliktschutz- und Wiederherstellungs-Reste (2.269.1 + 2.270.1 + 2.272.1 + 2.205 + 2.210 + 2.287)).

### Added
- Comments and an agent's payment suggestions take a `client_ref`: sent again after a lost answer = the first one, also in the app and over MCP (#3088).
- Budget categories carry a version: saved elsewhere meanwhile, the app says so instead of overwriting (#3088).
- Saving positions without `expect_updated_at` names the ones that stayed in `kept_ids` (#3088).
- Settings > Backups and an admin alert at the start name folders a restore left next to the data folder (#2779).

### Changed
- While a restore runs, the background queue and the pushes after a request wait; a restore waits for them. The deadlock retry stays as a safeguard (#2779).
- A document's sending is marked before the mail goes out: what can fail in marking fails while nothing has left (#3088).
- A successful restore also removes older leftovers, unless they hold files the archive does not bring (#2779).

### Fixed
- A restore with the attachments or office folder as a mount of its own is refused at once with a clear message (#2779).
- A failed restore brings the attachments folder back, also when the new one never came in and on a fresh instance (#2779).
- A customer mail the server refused no longer uses up the address's daily share (#3088).
- Time entries are open again when their invoice position is removed from the draft (#3088).
- A deleted draft comes back from the office trash even if the same request made a new one meanwhile (#3088).

Package 2.367.5 (Teil 5/5: Bündel Benachrichtigungen (2.267 + 2.268)).
### Added
- Notification mails can be turned off with one click: event mails, the daily summary and answers on a customer report carry the List-Unsubscribe headers (RFC 8058). The link opens a page with one button; security mails and invoices have none (#2975)
- Settings > Notifications: "Only the title in the push" keeps comment and message text off the lock screen; notification channels keep their text (#2980)
### Changed
- "Completed by others" now also reaches the bell by default, like its push; settings stored before stay (#2980)
- The number on the app icon in a push is now the app's own number: items for you plus direct messages (#2980)
- Test pushes have a limit and a translated title (#2980)
- News about an organisation, one of its lists or a connection leave the feed once you are no longer in it; a notice that you were removed stays (#2980)
### Fixed
- Event mails and the daily summary show the sender's name; the daily summary has a settings footer, counts in the day's mail limit and is tried again up to 3 times after a mail server error (#2975)
- Mentions in a rule's fixed comment and mentions added to an edited chat message now reach the person (#2980)
- An organisation admin handing on a project tells the old owner; a task freed from its blocker tells a group's people, for an agent's task its creator (#2980)
- Pushes carry the person's language, a push refused as too large is sent again in short, refused dismiss pushes count towards removing a device, the hourly limit of repeated reminders survives a restart, a full event mail queue is reported to the admin (#2980)
- Invitation and reset mails to a person in several organisations only name the one shared with the sender (#2980)

Package 2.369 (Teil 1/6: Bündel Leistung: Startansicht, Web-Prozesse, Poll, Watchdog, Schichten (2.289 + 2.193)).

### Changed
- Office document lists load 100 rows at a time, with a "Load more" button at the end of the list instead of stopping silently at 500; search also finds documents that are not loaded yet (#3200).
- Client pages and the reminder dialog show every open invoice, also old ones behind 500 newer documents; quotation and reminder lists open faster with many rows (#3200).
- Restarts and live updates no longer lock tables that hold tasks and comments: database triggers and indexes are only rebuilt when they are missing or have changed. A trigger that was removed, altered or switched off is repaired at the next start (#2731).

### Fixed
- Organisation import of document fields: undo takes back the selection options it added, one summed warning for field values not taken over, the mark "automatic" stays on the value (#2734).

Package 2.368.4 (Teil 4/5: Bündel Englisch und Formate (2.264 + 2.265)).

### Changed
- One English word for one thing, in en-GB (#2990): client, workspace, sign in / sign out, payment reminder, quotation, assignee, people, holiday, enquiry, e-mail, colour, default, and -ise spellings. The other languages keep their wording. The glossary is in TRANSLATING.md and `tools/i18n_check.py` reports the variants as errors.

### Fixed
- The absences calendar link follows the language of its owner, whoever fetches it; public holidays and German states have names in every language, in Settings, Absences and the calendar (#2989).
- The block pages of polls, forms and file requests and the /drop refusal follow the visitor's language; the daily summary names the basket in the reader's language (#2989).

Package 2.413 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Teil 1/6: Sammelpaket Büro, Einsatzplan, Listen und Kleinkram).
### Changed
- Every view keeps its place: switching between Office, Projects, a list, the calendar, documents or the chat overview and back shows the same rows as before, also after a reload (stored in this browser only). An open office document (quotation, invoice, letter) stays open at the same spot, the left sidebar keeps its own scroll position per area, and the task open in the panel opens again with its view (not when it was completed or deleted meanwhile); same on the phone (#3439).
- Task comments: while an agent writes or works in a task's comments, the line above the comment box shows the same small bot figure as the agent chat instead of the dots (people keep the dots) (#3554).
- Lists, menus and settings rows share one row height with task rows (Files, Contacts, Settings, menus, search results); taller on touch screens and following the Compact / Comfortable setting (#3496).
- Search fields of Files, Contacts and Knowledge look the same: icon on the left, same height (#3496).
- Knowledge and Office: "New page", "New folder", "New quotation", "New invoice" and the other main buttons of a page's tool bar are full-height buttons like in Files and Contacts (#3496).
- Office PDFs (quotation, invoice, reminder, delivery note) print from one font size scale (7 / 8 / 9.6 / 10.4 / 14 / 15 pt) instead of 17 sizes between 6.8 and 16 pt: quantities and amounts in the table now match the description, small print is one size, the document title is 14 pt (#3500).

Package 2.367 (Teil 1/5: Bündel Benachrichtigungen (2.267 + 2.268)).

### Changed
- Quiet hours now hold every push, not only repeated reminders and notification channels: comments, assignments, chat, invitations and reminders stay silent, the bell keeps its entries and one summary arrives when the quiet hours end. Priority 5 (a task's "Urgent"), the push test, focus timers and the times you set yourself (digest, briefing, daily review) still come (#2966).
- Settings > Notifications: quiet hours have their own section "Quiet hours (all pushes)" instead of sitting under "Repeated reminders" (#2966).
- Quiet hours, digest, briefing, daily review, the all-day reminder time and "staying in touch" follow the person's time zone (the setting of time tracking); a task's time of day stays as it is (#2966).
- Pushes are bundled per person: from the third push of one actor within a minute one summary ("Anna assigned you 10 tasks", opens the list); @mentions always come. Chat: one push per room and minute, then "3 new messages", none when they were read. All-day reminders of the same moment are one message "3 tasks today"; a reminder with a time of day stays its own push (#2967).
- New switches `KALMIDO_QUIET_PUSH` and `KALMIDO_PUSH_BUNDLE` (docs/ENV.md).

Package 2.439.0 (E-mail signature per person for office mails).
### Added
- Office: every person has their own e-mail signature for quotations, invoices, credit notes, reminders and letters by e-mail: Settings > Company & office > Documents & numbers > E-mail signature, Settings > Account, or Edit in a send dialog. It is prefilled from the name and company data, goes under the text behind "-- " and the mail goes out as text + HTML with the company logo embedded (switch "Show logo", preview in the editor) (#3617).
- Send dialogs: the signature is shown with the tick "Attach signature" (off = for this one mail), the field "Answers to" changes the Reply-To of this mail, one sentence says which address the mail leaves from (#3617).
- Office mails: own sender name and answer address per person. With a mailbox with SMTP (E-mail filing) the mail leaves through it with its address; in an organisation a person can choose their own private mailbox ("Send through"). Through the server the sender address stays the server's. A letter's own reply address stays first (#3617).

Package 2.459.0 (Phone: knowledge page stays put while saving, 320 px layouts, organisation import brings the pictures back).
### Added
- Organisation import: the organisation symbol, list icons and list header pictures from files/pictures are set again; they are checked and re-encoded like an upload, an existing symbol stays, and undo takes them back. Lists in the private space get their pictures too (#3849).
### Fixed
- Knowledge page on a phone: saving or typing no longer moves the view; position, cursor and keyboard stay, in the text editor and the live preview. The text editor field no longer grows or shrinks with scrolling (#3883).
- Phone at 320 px: bars and buttons in Time, Calendar, Knowledge, Notes, project overview, Receipts, Pipeline, the entertainment receipt dialog, the selection bar and Account fit the screen; long buttons take the whole row, tabs scroll inside their bar and a long document title ends in dots (#3853).
- Import: a header picture name from an archive without the picture no longer leaves a dead reference on the list (#3849).
- Tests: the chat at 740x360 is checked with the device look; the gap reported there was a passing moment, not a lasting one (#3857).

Package 2.368.5 (Teil 5/5: Bündel Englisch und Formate (2.264 + 2.265)).

### Changed
- The examples of the number schemes are translated, English shows a promo film and Example Ltd (#2991). The installed app's description matches the server's.

### Fixed
- A shopping amount sent as text, "1,000" in English, is a thousand on the server too, it was 1 (#2991).
- The search filter of the documents shows the quotation marks of the language (#2991).
- The app bar at 1280 px: "Knowledge" stays one word in English (#2991).

### Fixed
- main: on a phone the Completed button of the calendar bar is 44 px wide again (p260_ui, narrowed by the 320 px rules of #3853).

Package 2.378 (household bank import: duplicates of a fixed EndToEndId).

### Fixed

- Household budget, bank import: a fixed EndToEndId (such as a contract number) with the same amount no longer drops next month's payment as a duplicate; the booking day is now part of the key, like in the office's bank import. Keys stored earlier count only for a booking of their own day (#3347).

Package 2.465.0 (Agent events for tables, contact import over the API, held task bursts survive split processes).

### Added
- Agents hear `sheet_shared` when a table is shared with them and `sheet_unshared` when that share ends (#2361).
- API v1 and the MCP tool `import_vcards` take several vCard files or a ZIP of them, like the app (#2477).

### Fixed
- With web and worker in separate processes, the one `tasks_added` summary of many new tasks was never sent: held tasks now wait in the database (#3892).

Package 2.366 (Teil 1/2: Bündel Agenten: Anlegen, Zugänge, Starter-Parität (2.251 + 2.228)).
### Added
- Agents area: "Add agent…" in the header and in the empty state, with the three steps (create, share a project, set it up on your computer); it opens the chooser team / personal directly (admins) or Settings > Agents > Set up (#2998)
- Settings > Access lists the team agents for admins too, with "New API token" and "Set up on a computer" (#2999)
### Changed
- The header's "…" only shows where a page has its own actions; pages like Calendar, Office, Agents no longer show a "…" holding just "Search and commands" (#3002)
- An agent that never connected no longer takes a row over the tasks in the Inbox and in projects (its grey dot in the header stays until it asks something); the start page says "Agents: 2 not connected" instead of "all quiet" (#3000)
- Set up on a computer: the example folder stands under the field instead of a placeholder that looked like a value; a computer without a name is called after its system and day ("macOS · 27 Oct", "Set up by hand") instead of "API token" (#3001, #2999)
- Settings > Agents > Set up: the one-command way comes first, the steps by hand are folded under "For advanced users" (#3001)
- The username hint ("for the login and @mentions") stands under the field in the agent and the person dialogs, so the field keeps its width on phones (#3001)
- Agents page: the blocks' "…" no longer cover "Open | All" and the one-line hint has none (#3001)
### Fixed
- The dialog "New team agent" preselected "Personal agent of <me>"; it now starts on "Team agent" (#2997)

Package 2.445.0 (Tidier task and project menus, tablet layout, agent_run.log on Windows).

### Changed
- #3008 The task "…" menu shows the everyday entries first (date, priority, assignee, time, move, waiting, pin); everything rarer sits under "More…", and nothing repeats what the task panel's header already shows. "Indent" no longer quotes the task above.
- #3008 The project "…" and Sort menus have one switch for completed tasks (Hide / Show / Bottom) instead of three entries; a choice equal to the default follows the default again. Share and Shown fields appear only once.
- #3011 From 600 px Kanban columns are 18 rem wide, the first column is always "Tasks"; the matrix is 2x2 from 700 px and its page title is "Matrix"; the timeline is titled "Timeline" and says how many dated tasks "Projects only" hides.

### Fixed
- #3748 Agent starter on Windows: agent_run.py keeps its own agent_run.log next to the script (appended, rotated at 1 MiB, KALMIDO_RUN_LOG sets the path, 0 turns it off); a command that cannot be found is logged as not started on Linux too.

Package 2.460 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- Office: services, equipment, roles, text blocks, framework contracts and the closing texts in the office settings have language tabs in their form: German, English, Dutch, French, Spanish, Italian (#3767).
- Client form, Billing details: "Document language". New documents of the client use it, choosing the client on a draft switches the language and its standard texts, portal sign-in mails and event invitations to the client's address follow it (#3767).
- Office settings: terms and conditions (PDF) can be uploaded for every document language (#3767).
### Changed
- A document in a language an own text lacks prints the English text (without one the German text) and shows a note above the document which texts are missing (#3767).

Package 2.403 (Prüftor: Dateien ohne Suite melden).
### Changed
- Tests: `tests/stages.py --touched` names every changed file it cannot map to a suite as an `UNMAPPED: FILE (reason)` line and, with `--unmapped-out FILE`, in a file; the release check counts such a package as not checked instead of green (#3505).

Package 2.464 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Handy: Seiten-Schiene ).

### Added
- Settings > Organisation > People: an organisation's admin sees who registered with the organisation's address and waits, with *Approve* in the person's row; the delete button of the row declines. The News item and the push lead there (#3882).
- The account import brings back the files of templates: sealed for your account, counted against your storage, once per export, and an undo takes them away again (#3865).

### Changed
- Export manifests: the reasons why tables stay out of the export are in the language of the person who runs it; the table names stay technical (#3841).

Package 2.392 (Teil 1/3: Lieferkette: Abhaken, Lieferzustand, Jobs, Bremse, Export, Tagesbericht, Einbahn).
### Added
- New view "Waiting for me": jobs, approvals, merge and deploy requests, reviews, blocked tasks and one-way steps without a yes in one place, across all workspaces. It appears in the sidebar under Plan while something waits; the card in Today links to it (#3369).
- Delivery report of a project (API and MCP): released, in main, in progress, stuck and completed for a day or since a moment, as data and Markdown (#3369).
- Repository dialog: "Complete tasks when their package or code is released", off by default; each task once per version, with Undo in its history (#3364).
- Partly done work: task menu "Partly, rest in ...", or a comment starting with "partly: rest in 2.5", keeps the task open until that version and creates a "Rest:" task (#3364).
- Tasks can be marked as a one-way step with a reason (task menu "..."); with "need a yes" on in the project dialog, integrate and deploy requests wait for an approver's yes per task, and "Approve anyway" does not pass it (#3370).
- New section "Decisions" at the top of the task panel: who decided what and when; a new entry can replace an old one, which stays readable, crossed out (#3370).
- Environments can create an acceptance task per new version, assigned to the project owner, with the closed tasks as subtasks (#3370).
- API and MCP: `get_waiting`, `get_delivery_report`, `partial_task`, `add_decision`, `update_task.irreversible`; events `decision_added` and `task.completed` with via "release" (#3364, #3369, #3370).
### Changed
- Agents: a work style limit "at most N tasks at once" is now enforced: a further running job is refused (409 `slots_full`) (#3367).
- Kanban column limits have a switch "No new jobs while over the limit"; while a column is over it, agents cannot start jobs on its tasks (409 `wip_full`) (#3367).

Package 2.463.0 (Rejoining an organisation, template data in the account export, agent office list).
### Added
- Account export and import: templates keep what they hold on the server, sprints, key links, project tags and your own assignments. Other people, and lists and tasks of the old server, stay behind (#3860).
- API v1 and MCP `list_office_documents`: `before`, `limit` and `next_cursor` page through all documents (#3889).
### Changed
- Leaving an organisation and joining again within 24 hours brings back your membership in closed projects with your role, so your assignments there return too. A project with the lock asks for its key as usual (#3859).
### Fixed
- API v1 `office/docs` with `open=1` found no old open invoice behind the 500 newest documents; an agent limited to some projects missed documents the same way (#3889).
- The account import no longer takes a template's server-side part from the file as it stands (#3860).

Package 2.469 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Teil 1/3: Software-Tickets: Kennungen, Status-Spalten, Filter, Ansichten, Delegation;).
### Added
- Online payment of invoices (#3459): customers pay by link in the invoice mail, in the PDF (link and QR code next to the GiroCode) and in the customer portal ("Pay now"). Provider-neutral, Stripe Checkout first; the money goes straight to the office's own account, Kalmido never takes money or a fee. Off until set up in Office > Settings ("Online payment of invoices"), with a switch per invoice. The webhook books the payment the same way as a manual one, including partial payments and refunds; the provider's payout is recognised as a collective payout in the bank match and not counted twice, its fees become an expense. Kalmido's finalised PDF and e-invoice stay unchanged.
- Credit cards (#3749): when a statement cannot be read, "Read with agent" lets a connected agent propose the positions (`card_statement_read`); nothing counts until a person takes them over and confirms.
### Changed
- Knowledge (#3546): the tag list of a space is kept in the process's memory until the space, its keys or the reader's visibility change, instead of opening every tagged page on each call; readers of a share no longer start an index job.
### Fixed
- Office settings (#3352): a hint under the paper size and in the letterhead section when the letterhead's page format does not match the chosen paper size, at once when the field changes; nothing is blocked or converted.

### Fixed
- main: packages 2.392, 2.458 and 2.469 left suites red: the demo answers the new inbox call, the open-gates query uses ILIKE, the two new agent routes have their control class, the coverage and parity lists know the new routes, the demo test reads the protected space in amounts.

### Fixed
- main: after a job or proposal is settled, the Today card and "Waiting for me" update at once instead of within the minute.
- main: font sizes in the change log and e-mail signature follow the type scale; suites follow packed static files, lock files, CSV by language and the number preview.

### Fixed
- main: in the sidebar sort mode the "…" of a list opens up / down / folder again; the sort button of the office lists had taken the same marker and answered in its place.

Package 2.466 (Bündel: Bündel Erststart, Ersteinführung, Entscheidungen UX-Audit (2.254 + 2.274 + 2.275 + 2.334)).
### Added
- Short introductions per area: the first time you open Calendar, Office, Time, Review, Home, Reading, File store, Knowledge, Tables, Habits or Agents, 2-3 cards explain it, once per account (#3314).
- The last card of every tour has the tick "Show more introductions" (on by default); Settings > Help has the same switch and restarts each area's introduction (#3314).
### Changed
- The welcome tour shows today's interface: the bar with the areas on a computer, News from all workspaces, and your agents when you have any (#3314).
- Existing accounts see an area's introduction only for areas they have no content in yet (#3314).

Package 2.365.1 (Leaving an organisation returns what you brought in).
### Changed
- #3395: Leaving an organisation, or being removed from it, now takes back everything the person brought in from their private workspace, not only projects: tables, files and folders, knowledge pages, video sign-offs, polls and bookmarks. Things made in the organisation, things in the trash and office clients and drafts stay. Shares of what goes back end, a name already taken gets " (2)". Items in a workspace or folder with a lock, receipts in the books and a link already saved privately stay; the leave dialog (Settings, Workspaces, Leave) lists what goes back and what stays and points to the request to an admin.

Package 2.474.0 (one list's writes in order, tests wait for state).
### Fixed
- Two quick changes of one project's settings could overtake each other on a slow connection: the screen showed the newer choice while the older one stayed stored. The writes of one project now go out one after the other (#3917).
### Changed
- Tests: the suites p2100_ui and p1_ui wait for a state instead of a fixed time (#3477, the rest in #3927).

Package 2.461 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Added
- Public holidays for Switzerland, France, Spain, Italy and the Netherlands (nationwide). Each country is one data file under `kalmido/office/packs/holidays/`, all names translated (#3773).

### Changed
- Settings > General > Working week and Settings > Organisation: public holidays are chosen by country first, then by region where the country has any. Germany can also use only the nationwide holidays. Other languages no longer see just a list of German states (#3773).

Package 2.467 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- Office > Bookkeeping > "Tax forms": the Anlage EÜR (2025, 2026) and the annual VAT return USt 2 A (2026) line by line with the official line and field numbers, as a page, CSV and PDF, to type into ELSTER. Two fields per year take the VAT paid to and refunded by the tax office. A year without an official form shows a note instead of lines, small businesses get no VAT lines. Nothing is sent to ELSTER, no tax advice. The yearly VAT task links the page (#3456).
- Agents with the calendar permission read free / busy of people shared with them: GET /api/v1/events/freebusy and the MCP tool freebusy, never titles; the person's setting for busy times applies (#2586).
### Changed
- Only an admin of the server sets the e-mail domains of an organisation; an organisation admin sees the field read-only, existing domains stay (#3898).

Package 2.478 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Changed
- Tests: 19 flaky suites (the most frequent ones in recent red CI runs and in tests/skip.txt) wait for a real state (element, toast text, server state, requests settled) instead of fixed sleeps; about 290 fixed waits removed, the few that stay are marked as wanted (time must pass so something does not happen, or a timer is measured) (#3927, #3585).
- Tests: 12 suites run again in the full run (off tests/skip.txt after three green Mac runs on the same code): sections_dnd_ui, p210_ui, p2141_a_ui, p2400_d_ui, p299_e_ui, p21445_c_ui, p2412_ui, time_ui, p180_ui, p2280_ui, p2190_fixes_ui, p220_ui (#3927).

Package 2.388 (Chat: Filter für Dispatcher-Meldungen).
### Added
- Agent chat: the ⋯ menu's filter gets the switch "Show dispatcher messages" (default on, kept per device) wherever such lines exist; off hides the dispatcher's lines (a job's messages and messages with buttons stay), the ⋯ button names it, a search hit or quote on a hidden line shows the lines again (#3341).
- Agent API and MCP `send_chat`: optional field `source` on a chat message (a short lower-case name, e.g. `dispatcher`), delivered back as `source`; older lines that start with "Dispatcher" count for the filter (#3341).

Package 2.399 (Hosting: Betreiber getrennt von Kunden-Organisationen).
### Security
- Hosted instances (`KALMIDO_HOSTED=1`): the instance admin no longer reaches into organisations it does not administer itself - no name, domains, members or roles of a customer's organisation, no new organisation with somebody else as its admin; Administration > Organisations shows such an organisation with its number of people only and without the edit button (#2687)
- Hosted: a customer's account (a member of a foreign organisation or a person without one) can only be locked, unlocked, given a storage quota or deleted by the instance admin; password, sign-in link, password link, e-mail address, organisations, SSO sign-in, ntfy topic, 2FA reset and agent conversion answer 403, and deleting it never hands its projects to somebody; the person dialog shows these fields locked with a note (#2687)
- Hosted: a customer's agents can only be paused by the instance admin (no token, setup code, move, deletion or activity log); new agents of the admin never land in a customer's organisation (#2687)
- Hosted: a single sign-on links an existing account for the first time only from that account's own session (the operator sets the provider); a team agent's workspace "auto" never resolves to a customer's organisation; locked former admins keep a retired customer organisation's retention export (#2687)
- Hosted: no backup download in the app, the storage check without titles and file names, no takeover of a disabled customer's projects (#2687)
### Changed
- Self-hosted servers keep the in-app server admin unchanged; the customers' own admins invite and set roles as before (#2687)

Package 2.473.0 (Bundle: delegation and watchers, Software project type with bug inbox, project-limited tokens).
### Added
- Task details: below the assignee a task can be delegated to an agent while the person stays responsible; the agent gets the task in its work queue (#3357)
- Task details: "Watch" with a visible list of watchers; watchers get comments and done / reopened notifications through the existing, switchable notification settings. API v1, MCP and webhooks carry `delegate_agent_id` and `watchers` (#3357)
- New project, type Software: fields Size (S/M/L, pinned) and Release; the option "With a bug inbox" also creates the list "<Name> – Bugs", and a task moves to the backlog of the build list as soon as Release is filled, with its value (#3378)
- Rules: the trigger for a field can be "Filled", it fires when a value is set, not when it is cleared (#3378)
### Changed
- A task moved by a rule keeps its values in fields of the same name and type in the target list; select fields stay out (#3378)
### Fixed
- `GET /api/v1/absences`: a token limited to some projects sees only the people of those projects, a person's token as well as an agent's (#3907)
- Allowed internal hosts: if the old shared list was changed after a fallback to an older version, the next start copies it into every purpose again (#3569)

Package 2.477 (Bündel: Ablage: Wechsel Liste/Karten ist nicht sofort (läd, Untere Leiste: auf Tablets mehr Punkte statt fest , Sammelpaket: Aufgaben ohne P).
### Added
- Quick note like a notes app (#3881): hold the Plus button on a phone, press `m` on a computer or pick "New note" in the command search (Ctrl/Cmd+K) - an empty note opens with the cursor in the text, no list to choose, no title field. The first line becomes the title, it saves by itself, and a note left empty disappears without a trace (never in the trash).
- The private list "Notes" (#3881): made on the first quick note, a flat list with the newest first and a fixed entry in the sidebar under the inbox; back from a note lands there. It can never be shared - no members, groups, agents, public link, folder or workspace (the server refuses it). Moving a single note into a list other people see first asks, in bold, who will see it.
### Changed
- "New note" in the notes overview no longer asks for a list (#3881): with a list filtered the note goes there, otherwise into "Notes".
- The bottom bar shows more points on wider screens (#3938): 5 on phones, 7 from 600 px (tablet upright), 9 from 900 px (tablet across), the last one "More"; turning the device redraws it, and the hint in Settings names the number for this device.
### Fixed
- File store: switching a folder between list and cards is immediate (#3936) - the loaded entries are drawn again instead of fetching the folder, and picture cards load a small preview instead of the original file.

### Fixed
- main: p2391_k_ui no longer counts the bug inbox of a Software project ("With a bug inbox", 2.473.0) as an old name of the basket (#3378)
- main: p2310_b_ui counts the assignee once without the "Delegate" chip of 2.473.0, which shares its look (#3357)

Package 2.476 (Bündel: Dokumente: am Handy links/rechts wischen zum nächs, Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- Documents: leaf through the open document - on a phone (whole page) and in the side view next to the list (tablet, touch screen) a swipe left / right on the preview opens the next / previous document of the list as it is filtered and sorted; "3 of 48" with two arrow buttons above the preview, the next document glides in, at the real end the page springs back (#3935).
- Documents: a preview enlarged with two fingers moves with one finger instead of turning the page; at normal size the swipe turns again (#3935).
### Changed
- Documents: the list loads the next 200 documents when you scroll to its end (button "Load more (x of N)" as a fallback) instead of "200 of N shown, narrow the search"; swiping past the last loaded document uses the same loading (#3935).
- Documents: in "To review", Checked opens the next document at once (#3935).
- Fewer merge conflicts between parallel packages: app.css no longer grows - styles needed at start go into static/css/start-<topic>.css, which the server sends behind app.css under the same address; new start scripts go into a sorted block at the end of index.html; tools/check_appcss.py and tools/check_layout.py enforce both (#3487).

Package 2.482 (Bündel: Angebot: geschlossener Sprach-Hinweis geht durch e, Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- Phone, Projects page: "Sort projects" in the head of the Projects group and in a project's menu opens the sidebar's sort mode right on the page: a grip on every row drags at once (also into a folder), "…" moves up / down / to a folder, the bar on top ends it with "Done". One order for page and sidebar (#3951)
- EU AI Act Art. 50: agents show as "AI agent" everywhere people read them (chat, comments, members, shares); their answers in the customer portal and in the portal's e-mails carry the mark "AI agent". A bot without AI can be switched to plain "Agent" in its settings (agent field `ai`) (#3530)
- Before a text an agent wrote goes out - an agent's letter draft, a public link to a wiki page an agent created or changed last - a quiet note says so once per document, with "Insert label" (adds "Created with AI support"); nothing is blocked (#3530)
- Privacy template: a paragraph "AI functions" (Kalmido's operator as deployer of third-party AI, agents labelled, responsibility for published texts), also for the operator's terms (#3530)
### Fixed
- Quotation / invoice: a closed note "Language changed …" no longer opens again when a late save answer arrives; only a new language switch shows it (#3940)

Package 2.481 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- Agents: *Work the list off* in the agent's runtime settings (*Off* / *Dry run* / *Active*, runtime `dispatch`) switches on the reference starter's mechanical dispatcher (`mcp/agent_dispatch.py`). It works the lists named in the project's `KALMIDO-DISPATCH.json` off without a model deciding: one state per task, built tasks (a commit with `#ID` in `close_ref`) are closed with a comment naming the commit, a free place starts ONE job for the next bundle (priority order, sizes S / M / L as points), silent jobs and stuck or one-way tasks are told once in the chat, one day report. Brakes: stop file, usage limit, work window. A dry run changes nothing and only reports. Starter capability `dispatcher`, both launchers (#3662, #3320)

Package 2.480 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), USt-Jahreserklärung 20).
### Added
- Fixed assets: declining depreciation (up to 30 % a year, three times linear) as a choice per device for purchases from 01.07.2025 to 31.12.2027; the plan switches to linear once that is higher, the EÜR depreciation line takes it. Shown in the device dialog only for a purchase in that window above the GWG limit; no tax advice (#3528).
- Account export / import: the file contents of the private area travel along - every version of the private files, the files of knowledge pages and of tables; the import restores them into the private area, and a space check before the run refuses with a clear message when quota or disk would not suffice (#3470).
### Security
- Hosted operation only (self-hosting unchanged): the delete info of a client's account shows the operator numbers only, no candidates or member names; the boundary repair cleans up the operator's own organisations and only counts findings in client organisations; uploading a backup archive and restoring from an uploaded archive are refused (server-side backups still restore); accounts the operator made and that never signed in stay the operator's, so invitation and sign-in links work until the first sign-in (#3944).

Package 2.479 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Changed
- Team chat is now an area of its own, "Chat", with an icon in the app bar (with the unread count), next to Agents; it no longer sits inside Projects. Its channels, groups and direct messages are the area's left panel, with "+" (New message) in the panel's head (#2814)
- On a computer an open conversation takes the whole page: the second column "Conversations" beside it is gone. With no conversation open the page is the full list with the last messages ("All conversations" in the panel) (#2814)
- The Projects panel and the phone's drawer no longer list the last conversations on top of "Conversations"; a pinned person with a direct message shows there as the person again. The phone's drawer shows the area Chat like the computer (#2814)

Package 2.475.0 (migrations as fragments).
### Changed
- Developers: new tables, columns and indexes go into one file per task under kalmido/core/migrations.d instead of the end of schema.py; tools/check_migrations.py enforces it in CI, and the row-level security, export and foreign key checks read the fragments too. Nothing changes in an existing database (#3478).

### Fixed
- main: the server starts again - an import moved to module level in the backup code closed a loop between the API modules (#3944, #3506)

Package 2.485.0 (Hosting: support access with the customer's consent, operator console).
### Added
- Settings > Account > Support access (hosted servers only): a person opens the own account, an organisation admin the organisation, for 1 hour, 1 day, 3 days or 7 days. While it is open, the operator's admin ways into exactly that account / organisation work again; the customer sees until when, ends it at any time and sees every access (time, who, kind of request - never contents). The operator's account list shows the end time (#3939).
- Operator console (token interface): find an account by e-mail, its numbers (no names or contents), lock / unlock, storage quota, delete (refused while it owns projects, records must be kept or it is an admin), the default quota (#3939).
### Security
- Support access hands out no sign-in data and adds nobody: no e-mail / password / two-factor changes, password links only by mail to the customer, no agent tokens or setup codes, no new members, accounts or agents. A support sign-in link starts a marked session that ends with the access, creates no tokens, app passwords, passkeys or webhooks and never passes two-factor sign-in; ending the access early ends it (#3939).
### Fixed
- check_layout treats the migration fragments in core/migrations.d as data, not as modules (#3939).

### Fixed
- main: a warning of an account or organisation import names the area in the language of who reads it (it was kept in the language of who imported); the tests of the travel, meal and EUeR CSV follow the language rule of #2984, the freelancer sweep knows the picture preview of #3936, the language test of the import uses an area that still stays behind since #3470.
- main: a background refresh while a timeline bar or new-task ghost is held no longer clears the mark that the view must be redrawn after letting go.

Package 2.360.5 (Teil 5/5: Bündel Sicherheits- und Datenschutz-Reste, Abhängigkeiten (2.197 + 2.223.9 + 2.239.1 + 2.313)).

### Changed
- Free / busy in the event editor: a colleague's bar in the organisation view no longer shows public holidays (they told the person's state) and no longer counts a team calendar that is only shared with them - only the organisation calendars they own, their accepted invitations and absences; your own bar and "all my calendars" stay as before (#3245)
- Office rights: a person in an office group without "Quotations & invoices" can now undo and redo their own change of a client, with the same rights as the change itself (#2753)

### Fixed
- Folder listings check the receipts lock in one query instead of one per file; the "own" lists of entertainment receipts and travel expenses decrypt only the host / travellers instead of every column of every row (#2753)
- Channel and event mail error lines in the server log carry the error class only, never the error text (#3245)

Package 2.369.3 (Teil 3/6: Bündel Leistung: Startansicht, Web-Prozesse, Poll, Watchdog, Schichten (2.289 + 2.193)).
### Changed
- Team chat: a new message checks the push settings of everyone in the room with a fixed number of database queries (account, settings, read mark and mute, list bell, devices and channels read once for all instead of per person; 8 people: 16 instead of 83 queries); who gets a push stays exactly the same (#3199)
- Team chat: the channel list and the room list read a person's organisations once instead of once per open channel (#3199)
- Knowledge: moving or renaming a folder with 10,000 pages was measured at about 2.5 s (2,000 pages: 0.3 s), under the 5 s limit, so the move stays a direct step without a background job; the measurement runs as its own test suite (#3138)

Package 2.484 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- Scheduling polls for agents: REST v1 `GET /api/v1/polls`, `GET /api/v1/polls/{id}`, `POST /api/v1/polls` (scope `calendar`) and the MCP tools `list_polls`, `get_poll`, `create_poll`; an agent sees its own polls and the ones on a task, project or client it may see, never votes, never sees voters' addresses; a team agent creates them in its workspace (#2200)
- Projects page: a long press (phone) or a right click (computer) on a project opens the same menu as in the sidebar, on a folder the folder menu (#3949)
- When Kalmido switches the workspace by itself (a link to a private module, a list of another workspace) a short note "Switched to …" with "Back" appears (#3950)
### Changed
- Calendar: a date of a repeating event that was changed on its own behaves like a single event - dragging, resizing, editing and deleting it no longer ask "Only this date / All dates", the editor shows no repeat; changes to the series leave it as it is (#3945)
- Phone: a tap on a tab of the bottom bar opens its page at the top; Back still returns to the place you left (#3949)
### Fixed
- Switching from Habits (or another private-only page) into an organisation stayed quietly in Private; it now opens the organisation's start page (#3950)
- Calendar: moving a single changed date again no longer shifts the whole series by its offset (#3945)
- Browser demo: the pomodoro statistics threw an error on the second opening (#3942)
- PDF overview: a part row higher than a page now carries its "PAGE n" hint too (#3738)
- The public link of a poll created by an agent opens for people again; it closes when the agent or its owner is switched off (#2200)

Package 2.369.4 (Teil 4/6: Bündel Leistung: Startansicht, Web-Prozesse, Poll, Watchdog, Schichten (2.289 + 2.193)).
### Changed
- Live updates: a change in another organisation, in a project you do not see or in someone else's own settings no longer makes your open app ask the server for changes; changes in your own projects, projects shared with you and your organisation still arrive within seconds as before (#2507)
- The background watchdog runs its clean-up work (trashes, old logs, exports, file clean-ups) at most every 10 minutes instead of every 30 seconds (`KALMIDO_WD_SLOW_S`); reminders, nags, event reminders and pushes keep their 30 seconds. A wave of due reminders reads the recipients' access once per project instead of once per reminder (#2516)

### Fixed
- main: the agent control guard test knows the new write route POST /api/v1/polls (#2200) as class "change"

Package 2.369.2 (Teil 2/6: Bündel Leistung: Startansicht, Web-Prozesse, Poll, Watchdog, Schichten (2.289 + 2.193)).
### Changed
- Big accounts start faster (#3136): when a person sees more than 3,000 tasks (server setting `KALMIDO_STATE_LAZY_MIN`), the app loads only what Today, Tomorrow, Next 7 days, Pinned, Waiting and My tasks show, plus the basket and the lists opened last on this device. A project's tasks load when it is opened; the calendar, filters, tags and the other views over all projects load the rest first. The sidebar keeps showing the number of open tasks of every project (counted by the server). Measured with 200 projects and 20,600 tasks: the start answer goes from 18.2 MB to 5.5 MB (a person without an organisation with 10,000 tasks: 8.7 MB to 3.7 MB), the server's time for it halves. Smaller accounts and older apps get the whole state as before.
- New route `GET /api/state/lists?ids=` (web app only) and the parameters `lz` / `lzl` of `GET /api/state` (#3136), see docs/API.md.

Package 2.483 (Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), USt-Jahreserkl).
### Added
- Lists with ticket types: a default type for new tasks (list settings, "Templates…" -> "Type of new tasks"); a task created without a type gets it. The bug list of a new software project starts with "Bug" (#3916)
- Agent API: agents read filed e-mails of a client or project that is shared with them - `GET /api/v1/mails`, `GET /api/v1/mails/{id}`, MCP tools `list_filed_mails` / `get_filed_mail`; "Unassigned" mails and mails of other organisations stay hidden (#1902)
- Agent API: agents with the scope office read invoice series and the subscriptions & tools overview - `GET /api/v1/office/series`, `GET /api/v1/office/subs`, MCP tools `list_invoice_series` / `get_office_subscriptions`; invoices made by a series carry `series_id` and `series_period` in `GET /api/v1/office/docs` (#2007)

Package 2.372 (Bewirtungsbelege: eigenes Unterschriftsbild ohne Briefe-Recht, Momentaufnahme beim Freigeben).

### Added
- Entertainment receipts: whoever may approve receipts can keep their own signature picture without the right to the correspondence - the approve dialog shows "Add signature picture" when there is none yet (draw or upload, only the picture; afterwards "With my signature" appears); Settings > Account > "Edit signature…" opens the same for them. Never somebody else's picture (#3316)

### Changed
- Entertainment receipts: the signature picture is frozen at approving (an encrypted copy on the receipt); replacing or removing the picture later no longer changes approved receipts, undoing the approval drops the copy. Receipts approved before keep showing the current picture (#3316)

Package 2.391 (Teil 1/2: Agenten-Anbindung: MCP-Pakete, Codex/Cursor, Long-Poll, Ratenlimit, Einrichtung per API, OAuth).
### Added
- MCP server: tool packages with `--toolsets tickets,code,chat,office,calendar,wiki,life` or `KALMIDO_TOOLSETS` in the env file; `chat` is always on, `all` is the default, `integrations` only when named. A tool outside the active packages gets a clear error. The launchers pass the variable through, the setup scripts and the in-app guide show it as a commented line (#3358).
- Agent runner profiles: `KALMIDO_AGENT_PROFILE` / `KALMIDO_AGENT_CMD` (claude, codex, generic). Codex CLI runs as `codex exec --json` with steps, model and resumed conversations; generic commands answer on stdout. The setup scripts ask for the tool (`--tool claude|codex`, default Claude Code). Settings > Agents > connect your own agent: the guide has a tool picker (Claude Code / Codex CLI / other MCP clients) with the lines for Cursor, Windsurf and Gemini CLI (#3359).
- API: every token response carries `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset` (and `X-RateLimit-*`), also on 429; a 429 names the real wait in `Retry-After`. Deprecated fields answer with a `Deprecation` header; API.md has the rule for changing the API (v1 stays, a sunset at least 90 days after the notice) (#3361).
- API: webhooks (own and organisation), API tokens and repository connections can be set up through `/api/v1` with the new scope `integrations` (never for agents, never a default; tokens also need `account`). A new token never gets more than the token that creates it (scopes, networks, projects, lifetime); secrets show once. Matching MCP tools in the package `integrations`. Settings > API tokens shows the new scope in the rights grid (#3362).
### Changed
- Agents waiting for events: the places follow the web threads (threads minus 8, at least 6, `KALMIDO_AGENT_WAITERS` still overrides); the default web threads are 24 (was 16), the database pool 80 (was 56). A busy answer asks to come back after 3-8 s with some spread (#3360).
- MCP client: 429 and 503 are tried again after `Retry-After` (at most 3 tries, 60 s together, never for the event wait), a used-up rate limit waits for its reset, and every writing call carries an `Idempotency-Key` that stays the same on a retry (#3360).

Package 2.363.4 (Teil 4/4: Bündel Import und Verschieben: Reste Audit L/R (2.286 + 2.288 + Export-Funde)).
### Added
- Moving between servers: the account import now also takes over your filed e-mails (with their .eml and attachments, sealed like a mail filed by hand), video sign-offs with their versions and your comments, the notepads and playbooks of your projects, bookmarks (the same link already saved is not doubled, the preview is fetched again), finished focus sessions, whom you stay in touch with, saved arrangements of views and project pages, and your bells and follows on the tasks that came along. Everything goes into your private space and goes away again with the undo of the import (#3127).
- The account import takes over more of your settings from an allow list (task panel, sidebar, start page, calendar views, focus timer, week start / time / date format, modules and folder colours), each checked like a value set by hand; nothing about sign-in, security, push or connections moves (#3127).
### Changed
- The import preview names what still stays on the old server more precisely: a notepad on somebody else's project and a folder's playbook are counted; bookmarks, e-mails, video sign-offs, focus sessions, staying in touch, saved arrangements and task bells are no longer listed as staying behind (#3127).

Package 2.470 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- Bank accounts as master data (#3596): Settings > Company & office > Bank & taxes holds several accounts with IBAN, BIC, bank and an optional DATEV account, one of them the default. Print lines, payment details, e-invoice, GiroCode and the DATEV booking export read the default account; finalised documents stay as they are. The first look creates the account from the existing company fields, the free bank lines stay readable as a fallback.
- Sharing defaults per workspace, private included (#3596): Settings > Data > Sharing defaults sets the validity of external links and the days, size, number and kinds of file requests. The server limits still apply; the dialogs start with these values.
- Texts & templates in Settings > Company & office (#3596): services, text blocks and document templates with a way to each catalogue. Equipment, framework contracts and vehicles stay in the office.
### Changed
- Letter text blocks and the office texts are one list (#3596): letter blocks are the new kind Letters in office texts, still encrypted, and still need the right Correspondence. The letter dialog shows the same rows.
- The page office/settings is gone (#3596): old links and bookmarks open Settings > Company & office; a person without the settings right lands on My rights. The tab rows General | Templates are gone, services, texts and rights have a back button to Settings. Import and rights stay pages of their own.
### Fixed
- An import into an office with its own company now says that the archive's bank accounts were left out (#3596).
- Typing in Settings > Company & office no longer loses the value or the focus when data arrives in the background (#3596).
- The country choice no longer shows twice above the office settings (#3596).
Letter blocks move once per office at the first look; blocks changed afterwards exist only in the new place, so going back to an older version shows the blocks as they were at the move, and that version lists the moved rows empty under Text blocks.

Package 2.369.5 (Teil 5/6: Bündel Leistung: Startansicht, Web-Prozesse, Poll, Watchdog, Schichten (2.289 + 2.193)).
### Changed
- Server code clean-up, nothing changes for users: one helper `need_person()` for the 46 "people only" gates (same answers), one `joined_lists_sql()` for the 12 hand-written "lists an account owns or is a member of" queries, and 1,769 imports inside functions moved to the top of their modules; the layer check's budget of such imports drops from 2,022 to 250 (#2517)

### Fixed
- main: the demo answers the holiday setting with its country list again, the settings view no longer throws (#3596, #3773)
- main: suite p21191_a_api expects the separator of its language in the contacts CSV export (English: comma, since #2984) (#2984)
- main: the agents' permission grid no longer offers "Set up integrations", which agents can never get (#3362)
- main: the settings search finds the online payment of invoices block (#3459)
- main: remembered views work without CSS.escape and stop after the window closed (#3439)
- main: 30 test suites follow deliberate changes of 31.10.-02.11. (CSV separator per language, document languages, PDF font scale, integrations permission, tour, pool size, settings as a jump) (#3506)

Package 2.392.2 (Teil 2/3: Lieferkette: Abhaken, Lieferzustand, Jobs, Bremse, Export, Tagesbericht, Einbahn).
### Added
- Delivery state of a task, next to the build state of its code: in progress (a job works on it), parked with a reason, or waiting for another task or a note. Task menu "Park with a reason", "Waiting for ..." and "Clear the delivery state"; a bar at the top of the task panel; parked and waiting tasks get a small chip in the list (#3365).
- Lists: column "Delivery state" (Columns ...), grouping "Delivery state" (sort menu, Group by) and a filter "Delivery state" in saved filters (#3365).
- "Waiting for me" lists your own parked tasks and, new, stalled jobs and stranded branches of your agents (#3365, #3366).
- An agent's running job marks its tasks "in progress" by itself; ending the job clears the mark. A release never completes a parked task (#3365).
- Agent jobs can belong to several tasks, name their leading job and the job they continue; the job card shows the chain ("Continues Job 82", "Part jobs: ...") and the other tasks (#3366).
- Watchdog: a running agent job without progress for 60 minutes (Settings > Agents > How it works, "No progress for", 0 = never) or a task's branch left without a merge for 3 days is reported once to the agent and to its owner (News, push only where "An agent waits for me" pushes are on) (#3366).
- API and MCP: field `delivery` of a task (PATCH, filter `delivery=`), `set_delivery`; jobs with `task_ids`, `parent_id`, `continue_of`; events `job_stalled` and `branch_stranded`; reference starter: `agent_job.py start --task` several times, `--continue-of` (#3365, #3366).

Package 2.369.6 (Teil 6/6: Bündel Leistung: Startansicht, Web-Prozesse, Poll, Watchdog, Schichten (2.289 + 2.193)).
### Changed
- Faster start view: a request no longer switches its database context back and forth for every helper. Leaving a "system" block is lazy (the person's context is set again right before the next statement that needs it, never later), the membership structure GET /api/state needs (roles, visible people, organisation names) is read once per request in the same step as the sign-in lookup, and the session cookie check runs in that step too. The second /api/state of an organisation member went from 24 to at most 4 context switches, a person without an organisation from 14 to 2 (#3139)
### Fixed
- Tests: the connection pool check follows the default size of 2.391 (threads x 3 + 8) instead of the old fixed 56 (#3139)
- Tests: rls_direct puts back the made-up upload_scan rows the watchdog's file clean-up removes after 10 minutes, so the write checks no longer fail on a busy runner (#3139)

Package 2.370.4 (Teil 4/4: Bündel Konfliktschutz- und Wiederherstellungs-Reste (2.269.1 + 2.270.1 + 2.272.1 + 2.205 + 2.210 + 2.287)).
### Changed
- Undoing an account import now puts its clients (with their contact persons) into the client trash and its address books into the address book trash instead of deleting them; the confirmation text says what still goes for good (#3089).
- Address books in the trash no longer count against the address book limit; restoring a contact counts against the contacts per book (#3089).
- Restoring a contact or address book brings back its old birthday task instead of creating a second one (#3089).
- Moving a project's tasks into the inbox when the project is deleted merges select options into an inbox field of the same name; person values of other members are not carried into the private inbox (#3089).
- Agent docs: clients are managed by people only; an agent account gets 403 on client changes (#3089).
### Fixed
- Office write paths (invoices, deals, letters, trips, drives, documents, data protection sheets, framework contracts) refuse a client in the trash with "The client is in the trash" (#3089).
- The signature link of a document of a client in the trash no longer works (back after a restore) (#3089).
- A contact in the trash is no longer a letter recipient and no longer blocks moving or a CardDAV UID change; a CardDAV restore links the client contact person again (#3089).
- Undoing a contact merge whose target or address book is in the trash answers with what to do first (#3089).
- The data export leaves out address books in the trash (#3089).
- Undoing an import twice at the same time runs once; the quick undo of trips / fixed costs imports only takes rows of the last 24 hours (#3089).
- Client usage counts and the organisation delete dialog count in one query instead of one per client and table; the entertainment receipts dry run no longer counts bills kept by law (#3089).
- Version names of files count versions in the trash; a comment without text whose files are all in the trash is hidden; removing a member counts the assignments in the trash too (#3089).

### Fixed
- main: the layer lint is green again - the module-level imports and own undo-window constants of #3089 (app commit 1b1d2b597) were committed in the app but never exported (#3506)

Package 2.489 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- Time: when no timer runs, the time page shows "Start time tracking" with a search of your open tasks; a task of a project without time tracking asks "Turn time tracking on for this project?" first (#2798)
- Settings > Administration > Whole server: "Allow public links" can be switched off per kind (projects and folders, files, upload links, booking pages and polls, sign-off and signature, wiki pages, forms, client portal, online payment), checked by the server on making and opening a link; the main switch still turns all of them off (#2664, #2656)
- Office > Travel expenses and Logbook: the project field offers the real projects you can see in the office's workspace, free text stays possible (#2664, #2652)
### Changed
- Phone (no head bar): the favourites no longer form a row of tiles at the top, they are entries (icon, name, unread count) under "Favourites" in the sidebar; with a head bar (computer, tablet landscape) the tiles stay at the top (#4014)
- Time: new lists track time by default when the module Time is on (existing lists unchanged); CSV, Excel and timesheet are in one "Export" menu; stopping under a minute says "under 1 minute"; on a computer the task detail shows "Time" outside "More details" in projects with time tracking (#2798)
- Office menu: one point "Contracts & subscriptions" with a filter All / Contracts / Insurances / Subscriptions instead of the separate "Subscriptions & tools"; the address book is an entry of its own, no longer under Sell; the point "Documents" is called "Letters & contracts" (#2664)
- Sidebar: the group "Conversations" is called "People", the More menu has no "Conversations" heading (#2664)
- Settings > Agents: the built-in assistant is a tab there, no section of its own (#2664)
### Fixed
- An Undo pressed while an earlier undo step was still finishing was dropped silently (the deleted task stayed deleted); it now waits and runs, and a late "Undone" message no longer replaces a newer undo notice (#4013)

### Fixed
- main: das Einlesen von E-Rechnungen (office/einvoice_in.py) lässt sich wieder als einzelne Datei laden; die hochgezogenen Paket-Importe aus #2517 sind abgesichert (Suite p2146_a_api war rot, #3506).
- main: der Umzug einer alten SQLite-Datei nach Postgres scheitert nicht mehr an einem Tabellen-Kreis agent_jobs/tasks (#3365); agent_job_tasks steht nicht mehr fälschlich in der Liste der Export-Ausnahmen (#4037).
- main: Test p2210_ui scrollt „Personen und Termine“ vor der Barrierefreiheits-Prüfung in die Mitte, die feste Fußleiste des Aufgabenfensters verdeckte sonst je nach Scrollstand den Knopf „Kontakt verknüpfen“ (#4038).

Package 2.490 (Bündel: Oberfläche in der Farbe des Arbeitsbereichs (Akzen, Kommentar-Kopf: Datum bricht in schmaler Spalte Wo, Heute: vergangene Termine un).
### Added
- The interface takes the colour of the shown workspace: main buttons (+), active navigation, ticks, progress and focus follow the organisation's colour (or your own choice); Private keeps the Kalmido accent, "All workspaces" a neutral grey; the colour stripe on top is wider. Text on buttons keeps at least 4.5:1 in light and dark. Switch in Settings -> Appearance "Interface in the colour of the workspace" (on by default) (#4026)
- Share a link: choose where "Read later" and "Bookmark" go - "Private" (preselected) or each organisation as "(Team)"; from three organisations a "… in team" picker; the browser button's confirm window has the same choice (#4025)
- Tablet / phone: swipe the open sidebar to the left to close it (it follows the finger, closes after a third of its width); the fold button at the top of the rail stays in view while the rail scrolls (#4032)
### Changed
- Today, "Events today": events that are over fold into a quiet "N past" line (tap to show them), a running event is marked "now", the count shows only coming and running events; updates every minute (#4021)
- Comment head: the time stays on one short line ("26.10. 15:21", today only the time); in narrow columns the action icons show on hover or tap (#4018)
### Fixed
- Equipment list: deleting an item or swapping its receipt no longer lifts the retention lock of the old receipt (#3796)

Package 2.393.2 (Teil 2/2: Ticket-Modell: Beziehungen, Typen, Feldschema, Kennzahlen, Mail-Eingang).
### Added
- Project pages have a new "Flow" card at the bottom: lead time (median and 85 %) and cycle time from the task history, a cumulative flow chart per column and day, and the bug trend per week (created vs. done, ticket type bug), each also as a table; switch between 30 and 90 days. Cycle time starts when a task first enters a column named "In Arbeit", "In progress", "Doing" or "WIP" (#3374)
- Agents and the API read the same figures: `GET /api/v1/lists/{id}/flow?days=30|90`, MCP tool `list_flow` (#3374)
- Replies by e-mail land on the task: answering the mail that created a task, an assignment / mention mail about one task, or a reply sent from Kalmido adds a comment to that task ("By e-mail from …", quotes and signatures cut off, attachments kept) instead of creating a new task (#3375)
- Only the original sender or people who can see the task comment by e-mail; other replies still arrive as a new task marked "Reply to #N, sender not allowed" (#3375)
- New switch in the comment field of tasks that came in by e-mail: "Also by e-mail to the reporter" sends the comment back as a reply mail (off by default, at most 30 mails per person and hour, not in end-to-end encrypted projects); API field `mail_reporter`, MCP `add_comment` (#3375)
### Fixed
- Test suite p2146_a loads the e-invoice reader again after the module-level imports of 2.369.5 (#4027)

Package 2.392.3 (Teil 3/3: Lieferkette: Abhaken, Lieferzustand, Jobs, Bremse, Export, Tagesbericht, Einbahn).
### Added
- Work package export: select two or more tasks, then "Copy as brief" (copy icon at the top of the selection panel; on a phone under More) copies one Markdown document with, per task, the status line, the decisions first, the description, subtasks, dependencies, repository hints (suggested branch, build state) and the comments without deleted ones. Without clipboard access it is saved as a .md file. Agents and tools get the same through `POST /api/v1/tasks/brief` (at most 50 tasks, scope read) and the MCP tool `export_brief`; only what the caller sees, tasks of encrypted projects are left out, foreign text is quoted and marked as data (#3368)

### Fixed
- main: the task header keeps the whole date in a narrow panel now that new lists track time (a sixth step sets the icons closer, the header refits when its date chip shrinks); the OCR language choice loads again as a single file; three office menu tests follow "Contracts & subscriptions" as one point (#3506, #2798, #2517, #2648)

### Fixed
- main: p2130_ui and p2320_a_ui expect the new "Copy as brief" in the selection menu (#3368) and the new project block "Flow" (#3374) (#3506)

Package 2.493 (Bündel: Einzeln geladene Module: Prüfung, dass hochgezogen, Beleg endgültig löschen: Serverfehler 500 nach Tau, Sammelpaket: Aufgaben ohne P).
### Changed
- Documentation: the detail sections of the README (login, calendars, agents, team, office projects, notifications, import and more) now live in pages under docs/ (new: FEATURES, TASKS, TEAM additions, HOME, FILES, CALENDAR, IMPORT, NOTIFICATIONS, GIT, ABOUT); the text is unchanged, docs/README.md lists every page (#2961)
- CI: a new lint step `tools/check_singlefile.py` loads every module that a test loads as a single file the same way and finds imports from the own package outside a guard, so such a break shows before it reaches main (#4041)
### Fixed
- Files: deleting a document for good while its text recognition was still running could end in "Server error" (the two waited for each other in the database); the deletion now waits for the recognition, e.g. a former receipt of an equipment item whose retention period is over is deleted with OK (#4034)

Package 2.398 (Notizen, Rückblick und Statistik im Firmen-Bereich).
### Added
- Notes have their own icon in the main bar (computer bar, phone drawer and tab bar), in every workspace; they left Projects > Views. The address #notes stays (#3405).
- Notes in an organisation's view: the notes of that organisation's projects plus your private list Notes; a line says new notes stay private and that you share one by moving it into a project (#3405).
- Review and statistics in an organisation's view: they show only that workspace's projects (done, open, moved, coming up; completed, focus and tracked time) and only your own numbers (#3406).
### Changed
- Private shows only the notes, review and statistics of the private projects; All workspaces shows everything as before (#3405, #3406).
- The journal stays private: it is not part of an organisation's review (no History there), and habits stay out of an organisation's statistics (#3406).
- Review can now be switched off per organisation by its admins (Settings > Workspaces) and per person per workspace (#3406).
- `GET /api/life/review` and `GET /api/stats` take `?space=private|org:<id>` (#3406).

### Fixed
- main: the sidebar head sits on the middle of the page header again under the wider 6 px workspace stripe (#4026); the test of the multi-select menu knows "Copy as brief" (#3368)

Package 2.488 (Bündel: Wanduhr-Warnung im Schichten-Prüfer: 4 Aufrufe ohn, Teil 1/2: Agenten-Anbindung: MCP-Pakete, Codex/Cursor, Long-Poll, Ratenlimit, Ei).
### Added
- Hosted MCP access (#3363): an MCP endpoint `/mcp` on the server (Streamable HTTP, POST + JSON) with an OAuth 2.1 authorization server (metadata, dynamic client registration, authorization code with PKCE S256, refresh token rotation, revoke). The consent page picks one of your agents or creates a new one; the connector gets a short-lived token with exactly that agent's rights. Settings > Agents > Connected apps shows the connector address and every granted access with "Disconnect". Off by default: Administration > Agents > "Hosted MCP access" (switching on asks for the password). The local `kalmido_mcp.py` with a fixed token stays as it is.
- Knowledge page files for agents (#2209): API v1 lists the files of a shared knowledge page and returns their content or text layer (scope `wiki:read`, the page's own visibility check; encrypted spaces stay locked, files blocked by the virus scan are refused); MCP tools `wiki_files` and `wiki_read_file`.
- Desktop Back arrow (#3988): a Back arrow at the left of the head bar on the desktop (not on the phone), active only when there is an earlier view inside Kalmido, greyed out otherwise; Alt+Left, Cmd+[ and the mouse Back button go back too (in the browser and the desktop app, not while typing in a field).
### Changed
- The layer check counts wall-clock calls outside core/db.py as an error now (budget 0); the last four (retention of organisations, DATEV import) use the test clock (#4004).

Package 2.370.3 (Teil 3/4: Bündel Konfliktschutz- und Wiederherstellungs-Reste (2.269.1 + 2.270.1 + 2.272.1 + 2.205 + 2.210 + 2.287)).
### Changed
- Exports and imports run through the background queue instead of a thread of the web process (#2760): the account export, the organisation export, the account import (check, recovery key step, import), the knowledge ZIP import and the large contacts import are queue jobs with slots of their own (`KALMIDO_BG_LONG_SLOTS`, default 4), so a long import never holds back mails or pushes. Whether one runs, and the contacts import's progress, is read from the queue (any process): with a separate worker (`KALMIDO_ROLE=web` + `worker`) the browser shows "running" while the job waits for the worker instead of "interrupted", and "one at a time" / "at most n imports on the server" (`KALMIDO_ACCOUNT_IMPORT_PARALLEL`, knowledge imports count too) hold across every process.
- The pushes after a comment, a task change, a client's approval or a client's video comment, "check for updates now" and the bookmark previews of a web process are queue jobs too (#2760); a push is never sent twice after an interrupted run.
- On a stop (SIGTERM) the server puts its running queue jobs back at once and ends (#2760): an export started again by the next start right away; an import (it writes, so it never runs twice) shows "interrupted" immediately instead of after 2.5 minutes.

### Fixed
- main: the area names in the phone drawer fit again at 320 px with Notes as an own area - the shrinking measures again after each step; tests p2409_b_ui and p2442_c_ui follow review in every workspace (#3406) (#3506).

Package 2.395 (Projekt-Status ohne Team, Projekt-Mails für Mitglieder und Gäste).
### Changed
- Project status works for every project, also when collaboration is switched off (one person, freelancer): "Set status" in the project's menu, the status pill, the status history and the start page's "at risk" count no longer depend on collaboration; only the News and push to other members still need it (#3379)
- Project e-mails: members who may edit the project read its filed e-mails; guests (role view / participant) only when the owner or a project admin switches on "Guests can read e-mails" in the project's E-mails section (default off). Agents and API tokens follow the role of their account; the API shows the switch as `mail_guests` of the project (read only) (#3380). Note: an app older than this release lets every role read project e-mails again

Package 2.383 (Kalender-Reste: Schweiz-Feiertage, CalDAV free-busy, Antworten je Serientermin).
### Added
- CalDAV `free-busy-query` (RFC 4791): a calendar app asking for the busy times of one of your calendars gets a VFREEBUSY with the busy times of the range (busy, timed, not cancelled; in Invitations only accepted dates), never a title (#2587)
- Answers to a single date of a series from a calendar app (RECURRENCE-ID): declining or accepting one date counts for that date only - the calendar view, the free / busy bar and the booking page follow it, the series keeps its answer; the API shows such answers as `occ_partstat` (#2587)
### Fixed
- Saving an event you are invited to in a calendar you may edit from a calendar app took you off the event; now your own answer from the app is taken (#2587)
- Changing the time or title of an invitation in a calendar app is still ignored, but the event now gets a new ETag, so the phone shows Kalmido's version again instead of its own copy (#2587)
- Italian repeat rules: ordinal and article agree with domenica ("la prima domenica", "l'ultima domenica"), the custom repeat dialog reads "ogni prima domenica" (#2587)
- Swiss public holidays were already added in 2.461 (#3773); nothing more in this package (#2587)

## [2.520.0] - 2026-11-04

Not released (the CI of this version was red); its changes are listed under 2.529.0.

## [2.518.0] - 2026-11-04

Not released (the CI of this version was red); its changes are listed under 2.520.0.

## [2.511.0] - 2026-11-04

Not released (the CI of this version was red); its changes are listed under 2.518.0.

## [2.506.0] - 2026-11-04

Not released (the CI of this version was red); its changes are listed under 2.511.0.

## [2.502.0] - 2026-11-04

Not released (the CI of this version was red); its changes are listed under 2.506.0.

[Unreleased]: https://github.com/Gegenschuss/kalmido/compare/v2.549.0...HEAD
[2.549.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.549.0
[2.546.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.546.0
[2.544.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.544.0
[2.541.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.541.0
[2.535.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.535.0
[2.532.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.532.0
[2.529.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.529.0
[2.520.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.520.0
[2.518.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.518.0
[2.511.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.511.0
[2.506.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.506.0
[2.502.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.502.0
