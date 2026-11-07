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

[Unreleased]: https://github.com/Gegenschuss/kalmido/compare/v2.618.0...HEAD
[2.618.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.618.0
[2.614.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.614.0
[2.605.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.605.0
[2.601.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.601.0
