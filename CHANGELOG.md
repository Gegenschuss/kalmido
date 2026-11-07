# Changelog

All notable changes to Kalmido are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Kalmido uses
[semantic versioning](https://semver.org/): every published change gets at least a new patch version, new features a
minor one, anything that needs action on your side a major one.

## Older versions

- [2.500-2.599](docs/changelog/2.500-2.599.md)
- [2.400-2.499](docs/changelog/2.400-2.499.md)
- [2.300-2.399](docs/changelog/2.300-2.399.md)
- [2.200-2.299](docs/changelog/2.200-2.299.md)
- [2.100-2.199](docs/changelog/2.100-2.199.md)
- [2.0-2.99](docs/changelog/2.0-2.99.md)
- [1.x](docs/changelog/1.x.md)

## [2.621.0] - 2026-11-07

Package 2.615.0 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Fixed
- Phone: the dialog "New for you" is a normal full-width bottom sheet whose height follows its content, with a gap before the hint (#4938).
### Added
- Reference starter: a PreToolUse hook refuses force-push, deleting remote refs or tags, docker / podman prune and reboot / shutdown in every run and job, whatever the allow list says; `KALMIDO_BLOCK_DANGEROUS=0` switches it off; docs/AGENT-SECURITY.md lists what it covers and what not (#3758, #3756).
- Reference starter: approval cards of a job belong to that job (its answer goes to the job), a card wanders to the newest answer that refers to it, an approval only mentioned in passing becomes a card, messages from a job's card reach the running job after its next tool step (only from the job's person or an operator), Stop with a job id ends that one job (#3658, #2347, #2390, #1801, #2422).
- Reference starter: the full replied message in the prompt, typing dots on tasks, no card alarm for advice against something or quoted words, cards with the same title close one by one, a quiet wake after a finished job (#3757, #3751, #3752, #3753, #3754, #3755).
- Tests: CalDAV smoke test with a real client (vdirsyncer): list, task both ways, change, delete, also for a person without an organisation (#4513).

Package 2.619 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Changed
- Wiki pages: a task link is only `[[#123]]` (or `[[#123|label]]`); a bare `#123` stays plain text in the page, the editor, encrypted pages and "Linked from". The "/" task search inserts `[[#123]]`. Chat, comments and task texts keep `#123` (#4947)
- Reload waves: the first poll after start fetches a delta instead of the whole state again (`/api/state` sends the area counters `lva`), at most `KALMIDO_STATE_AUTO_MAX` (default 4) live reloads of the whole state run at once per process, and after a server update open windows reload spread over 0-30 s (#3890)
- Agent starter parity: rules in the template and the in-app rules (never set formula fields, meetings/contacts/contracts flows), weekly limit handled apart from the 5-hour window, image sharing bound to the project folder (`KALMIDO_PROJECT_DIR`), read-only audit jobs (`agent_job.py start --audit`), the usage hook in jobs, the macOS step names the launcher, a task run commits as the project's git author (#3659, #1521, #1870, #2196, #2383, #2792, #3267, #3467)
- Export: one list of left-out tables per export (`exportleft.py`), the duplicate lists in the retention and the account export are gone (#3862)
### Fixed
- Phone: Back closes the quick add sheet also after a menu in it was opened and closed (Android); tapping the entry of the page already open closes the sidebar (iOS) (#4943)

Package 2.580 (Bündel: Teil 1/6: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Sammelpaket: Aufgabe).
### Added
- Documents: a clear stack (every part starts with an archive number code, no page before the first code, no number twice or already taken) is split automatically after recognition, without a confirmation; the parts carry the note "Split automatically from a stack" with Undo. Unclear stacks still ask "Stack - split?" (#4401)
- Mixed views under All workspaces (Today, Upcoming, filters, search, tags) show each task's origin "Workspace · Project" with the workspace's colour dot; phones show the dot and short letters (#4821)
### Changed
- Project limit of API tokens and agents (New API token, token rights, Edit agent, Settings > Agents): a field "Add projects" with a search, folder groups and whole folders, the chosen projects as removable rows; none = all projects as before (#4488)
- Settings > Organisation > Data: the overview "What is encrypted?" stands once, folded, instead of once per organisation (#4485)
- Every page sits on one of the four widths: documents use the page width and fill the row with tiles, office forms, tables overview, Completed/Trash, channel list, news and the calendar agenda follow the common widths; dead width rules removed (#4815)
### Fixed
- What's new dialog: a gap and a thin line between the scrolling list and the hint below, the last entry ends fully readable (#4822)

Package 2.621 (Bündel: CI-only rot: p2273_a_backup, CI-only rot: twofa, Sammelpaket: Aufgaben ohne Paket (Dispatcher) u. 1 weitere).

### Added
- Office > Import > old documents: a choice "File names" under "Choose PDF files" - the standard reading as before, three common patterns (date_number_client, number_client_date, client_number) or an own template from fixed parts and one separator; kept per office area, also without an organisation (#4600).

### Fixed
- Agent on the Kalmido server, starter pack: a second run after switching the language no longer creates a second plan or rule (plans are found by their fixed routine marker); the dialog names the workspace "Sort receipts and documents" applies to (#4715).

Package 2.616 (Bündel: CI-only rot: p2466_c_ui + p2306_f_doc_anchors (Nac, CI-only rot: p2299_e_agentread_ui (TypeError readi, Büro: direkter Bankabruf per).
### Added
- #2473: Office > Bank: "Fetch from the bank" pulls the statement of a bank account directly over FinTS (PIN asked on every fetch and never stored, TAN approval in the banking app or TAN entry in the dialog) into the same preview, duplicate check, bank rules and undo as the file import. Off until the instance sets its own FinTS product ID (`KALMIDO_FINTS_PRODUCT_ID`, registered with the Deutsche Kreditwirtschaft); agents cannot start it. New dependency python-fints 5.0.1 (LGPL-3.0).
### Changed
- #4563: the neutral export writes one 70 % entertainment row per VAT rate with the rate filled (the tip at 0 %).
### Fixed
- #4563: an invoice sent over the API with `terms: true` whose frozen terms file is gone (and no current terms in its language) answers 409 `terms_missing` instead of going out without terms.
- #4933: the menu path check matches a sub-tab as a whole word ("Server > Backups" is reported again); the sub-tab list test knows Server > Backup.

## [2.618.0] - 2026-11-07

Package 2.611 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Security
- #4019: An admin without a password (OIDC or passkey) turns the server-opening switches (public links, registration, 2FA requirement, OIDC settings) only with a fresh sign-in of the last 10 minutes; otherwise Settings offers "Sign in again" (passkey right in the dialog, OIDC via its confirmation step). A sign-in link does not count as fresh.
- #4884: Turning organisation encryption on (or off, or deleting a key) now takes the documents' preview images along; before they stayed readable on disk.
- #4784: Team proposals of a server agent: others with write rights no longer see the free text and images of an extract request, nor the task notes of a subtasks request once the task is out of their sight; "Waiting for me" checks the team rule in one go.
### Fixed
- #4865: Background encryption passes: a list skipped because it was busy is queued again (with a limit), rows are rewritten only when their content is unchanged, a wiki page moved meanwhile gets the key of its new space, a file deleted meanwhile is not written back.
- #4866: The preview of undoing an account import counts exactly like the undo (trash, calendars, focus sessions, arrangements, billed time entries); the undo answer names what went for good (for_good).

Package 2.384 (Besprechungen mit Protokoll).

### Added
- Meeting minutes as a knowledge page: "Minutes" in an event's window (calendar, phone and computer) makes the page "Minutes/YYYY-MM-DD <title>" in the workspace of the event's calendar (the private space without an organisation) and opens it for writing; title, date, time, place, participants and the agenda (the event's notes, one item per line) are filled in, decisions and action items are checkbox lines that "Open items as tasks" turns into tasks. A template "Templates/Besprechung" (or Protokoll / Meeting / Minutes) of the space is used when there is one, with the new placeholders {{termin}}, {{zeit}}, {{ort}}, {{teilnehmer}}, {{tagesordnung}} (English names too). The page keeps the event in its frontmatter, so "Minutes" on the same event opens that page again (#1958).

Package 2.607 (Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), CI-only rot: p271_ui, Teil 1/6: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- Date picker: a text field on top of every date picker and of the task's date dialog - type 6.11. / 06.11.2026 / 61126 / 2026-11-06 / 11/6/2026, today / tomorrow / +3 and press Enter; due dates without a year take the next matching day, min/max apply, invalid input turns red, the calendar follows the typing; on phones a number pad that does not open by itself (#4867)
- Documents: "Apply what was learned" in the selection's Edit menu and as a button above To review - sorts again with the stored text only (no new text recognition, no new archive number, date and amount stay), fills empty sender / type / folder, adds learned tags, keeps hand-set values and tags; message "x documents sorted, y suggestions" with one undo step (#4872)
### Changed
- Files, contacts, knowledge, clients and documents: a long press or right click opens the row's menu with the name on top, then "Select", then the other entries; a long press no longer starts the selection directly (while selecting, it still ticks) (#4612)
- Organisations: guests and read-only people only read in the organisation's objects - no comments, reactions, answers to choice buttons, video review comments or team chat posts (web and API v1 answer 403); the app shows a short lock hint instead of the input. Private lists, direct messages, people without an organisation and accounting are unchanged (#4549)
- Documents: "Recognise again" adds learned tags instead of locking the tags as a whole, and may re-decide values that a rule or the learning set (#4872)
### Fixed
- Lists and other optimistic saves: a state load that was already on its way no longer puts back an own change that was just saved (e.g. a list switched to the timeline jumped back to the list view; CI red p271_ui) (#4901)
- Budget: after "Create budget" the new budget opens at once instead of the empty start text until a reload (#4925)

### Fixed - main: a restore tries again after a deadlock while it takes the foreign keys away (before, work outside the maintenance gate could end it with a database error; suite p2273_a_backup), twofa takes the step of its login code before the login (a 30-second edge made the replay check sign in), the demo test finds the note list in the panel (2.602.0) (CI red of 2.614.0)

### Fixed - main: test p4286_restore runs its hard stops alone on the database (server beside it frozen without an open transaction, like behind the maintenance gate) and names a failed pg_restore of the backup (CI red of 2.601.0)

Package 2.603 (Bündel: Bündel: Teil 1/6: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Teil 1/6: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Sa).

### Added
- Office > Bookkeeping > income statement (EUeR): a section "Comparison with the year before" with this year, the year before, deviation and percent per line, totals, profit and a VAT liability line. Years before Kalmido come from the DATEV booking archive, marked "Source: DATEV archive", display only - never booked or added (#4921).
- Office settings > Company & office > Bank & taxes: new setting "Basis of the income statement" per year - "Receipts" (as before, default) or "Bank and cash (strict)": receipts count only through their bank, cash or card line on its day, bank lines without a receipt count with the warning "Receipt missing", income only through bank/cash, card totals are transfers and the card positions the expenses, cash withdrawals are transfers to the cash book, private lines do not count. Also offered on the country card of a new office; a year with a locked month keeps its basis. EUeR, VAT figures, tax reserve, cash flow and the DATEV export follow it (#4927).
- Entertainment receipt: "Paid with" links it to its bank, cash or card line; with the strict basis it counts through that line with the 70/30 split, never twice (#4927).

### Fixed
- Travel costs: restoring a single deleted receipt from the office trash no longer fails because another receipt of the same trip lies in a locked month (#4555).
- Documents on the phone: the document sheet could open without its receipt hints when the app redrew while the documents module was still loading (#4912).

Package 2.602 (Bündel: Bündel: CI-only rot: p2141_a_api, CI-only rot: p2172_a_edit_ui, CI-only rot: p2273_c_ui u. 7 weitere, Sammelpaket: Aufgaben ohne Pak).

### Changed
- On a computer the note list sits in the shared sidebar like Knowledge: search, bin, "New note" and the cards are in the sidebar, which can be hidden and dragged wider; the page shows the open note. On a phone list and note still come one after the other (#4817).
- Lists that stay inside the page (file store spaces, team chat, contacts / customers, notes without sidebar) share one width token --w-leiste (15rem, at least 14rem) (#4817).
- Cards and surfaces use the radius, border and shadow tokens only: cards var(--r-l) with border var(--line2), hints / fields / chips var(--radius) or var(--r-s); the undefined --r / --r-m / --hover are gone; the month calendar has the same frame as the week (#4816).
- Fewer database queries: the participant lists are worked out once per request, v1 tags of all lists, the approval hint's list names / roles and the tag copy of a repeated task each run as one query (#4507, #4508).

### Fixed
- A cold start on a document address (#docs/<id>) showed the document without the reading view and folded properties; the pane is drawn anew once the reading layout is ready (#4913).
- The sweep of p287b_a_freelancer_api makes its own sprint, field and saved documents view instead of skipping their routes (#4935).
- The second /api/state switched the database context 14 times (10 without an organisation) instead of at most 4: the account kind, the receipts' structure and the own organisation are no longer read in the system context each time (#4729).

Package 2.570 (part B: undo with a version check).

### Fixed
- Undo and redo no longer silently overwrite a change made in another session: a bookmark, a document, an office archive correction and "Make this the default" for the dashboard and project page arrangements now check the version, keep the other change and say "Changed elsewhere, not undone" (#4770).
- A bookmark preview fetch and a document recognition run no longer move the item's version, so undo after them works as before; documents carry their own edited_at, office archive entries an updated_at and the standard arrangements a version (#4770).

## [2.614.0] - 2026-11-06

Not released (the CI of this version was red); its changes are listed under 2.618.0.

## [2.605.0] - 2026-11-06

Package 2.586 (Bündel: Teil 1/6: Sammelpaket: Aufgaben ohne Paket (Dispatcher), CI-only rot: p2191_c_perf, CI-only rot: p2290_c_fold_ui u. 1 weitere).

### Changed
- Pages have one spacing: page shells (time, budget, bookmarks, feeds, agents, start, archive, documents, help hub) no longer add their own padding on top of the page area, and no extra room at the bottom; a title inside the content (start, calendar, shop, office, sheets, waiting cards) is never as big as the page title in the top bar - section titles use one size with weight 600. The time view's bar has its own class and no longer inherits the file view's left line (#4818).

### Fixed
- Dragging a panel grip (task panel, sidebar) is smoother: the content still reflows live, but the bars and modes that fit to a new width (top bar, task header, list/detail pair, agents band, title field) are fitted at most every 200 ms and once on release instead of every frame, the width variable sits on the app grid while dragging, and rows and tiles out of view skip drawing during the drag; measured in Firefox with 300 rows the watchers' script time per drag fell from about 105 ms to 3 ms (#4860).

Package 2.589 (Bündel: Teil 1/6: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Teil 1/6: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Sammelpake).
### Added
- Files: the trash has "Empty trash" (asks first, names the number of files and folders, cannot be undone), "Delete for good" next to "Restore" on every own row, and a selection with "Restore" / "Delete for good"; only what the person owns goes, the message names what stayed because it belongs to others or is kept by law; a document deleted for good frees its archive number (route `POST /api/files/trash/purge` {ids | all}) (#4875).
- Film & Video: taking a quotation into a project books every shoot part as a pencilled-in shoot day in the disposition, linked to the project, with one open place per crew person; the preview asks for a date when the quotation has none, and only offers it with the module Disposition and the industry Film & Video. A new quotation version adjusts pencilled-in days; firm bookings and filled places stay and are only marked. Open places are filled in the booking sheet (route `POST /api/team/dispo/bookings/<id>/fill`) (#4571).
- Office: "Tax check" before filing the Anlage EÜR and the annual VAT return - a traffic light per point (EÜR vs. VAT advance returns and annual return, jumps against the previous year, rough ratios, check fields such as entertainment, gifts, car, home office, low-value assets, reverse charge, receipts and bank, formal details); a click leads to the place, red blocks nothing, nothing goes to ELSTER (route `GET /api/office/books/taxcheck?year=`) (#3458).
- CI: the nightly run installs the previous GitHub release with its own install.sh, fills it with data, updates it with the installer's update.sh to the candidate and checks sign-in, data and tenant borders; it keeps the filled database as artifact `upgrade-fixture` for the quarterly upgrade fixture (#4359).
### Fixed
- Tables: arrow keys no longer land in a hidden cell of a merged block (they go to its anchor cell); empty cells that only carry a format survive the .xlsx import; the PDF print takes bold, italic, alignment and fill (#4825).

Package 2.582 (Bündel: Teil 1/6: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: CI-only rot: p2141_a_api, CI-only rot: p2172_a_edit_ui, CI-only rot).

### Changed
- Settings: backups, off-site backup and the storage check moved from Organisation > Data to Server > Backup (server admins, also without an organisation); the backup error's link and the old jump lead there (#4827).
- Every vertical grip can be dragged up to the neighbours' minimum width: the task panel in lists is no longer capped at 48 rem, the documents' properties grip leaves the preview only 12 rem (#4830).
- Documents: the private space is called "Private" like in the file store, also as scan target and in the API's location text (#4831).
- Edit project: the folded "Project features" section shows the number of custom fields (#4490).

### Security
- Agents need the `time` scope to read time entries and time gaps; others' entries only in projects where both the agent and the person who set it up are admins (also by task); totals on clients, project overview and sheet variables stay empty for agents without `time` (#4380).
- Subtask, day plan and inbox sorting proposals never hand health or budget content to an agent; such appointments count as busy without a title (#4380).

### Fixed
- Favourites bar: the letter badge uses the size token (CI red p2419_scale, #4730).
- Motion observers stop when the page is gone (CI red p230_ui, #4809).
- Event watchdog with nothing due back to at most 4 statements (CI red p2191_c_perf, #4810).

## [2.601.0] - 2026-11-06

Not released (the CI of this version was red); its changes are listed under 2.605.0.

[Unreleased]: https://github.com/Gegenschuss/kalmido/compare/v2.621.0...HEAD
[2.621.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.621.0
[2.618.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.618.0
[2.614.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.614.0
[2.605.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.605.0
[2.601.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.601.0
