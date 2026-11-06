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

[Unreleased]: https://github.com/Gegenschuss/kalmido/compare/v2.605.0...HEAD
[2.605.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.605.0
[2.601.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.601.0
