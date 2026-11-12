# Changelog

All notable changes to Kalmido are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Kalmido uses
[semantic versioning](https://semver.org/): every published change gets at least a new patch version, new features a
minor one. Releases in which operators have to do something carry a fixed section "Action needed"; the update notice
in Settings > Help shows that section of the target version.

## Older versions

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

## [2.1020.0] - 2026-11-12

Package 2.1012 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Changed
- #5690: the "..." menus at the top of the household budget, the bookmarks and the feeds open the app's shared menu instead of a small drop-down of their own: on a phone a sheet from below with its title and an X, on a computer Escape, Back and the arrow keys work and the first entry has the focus. Feeds: "Import OPML file" and "Export OPML file" are plain menu entries now (no link / file label). A read-only budget without any entry shows no empty "..." menu.

Package 2.1010 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Fixed
- Approvals with "two people": a first approval only counts while its person still may approve; after a role is taken away the request waits for a second approver again (integrate, deploy, merge requests) (#4033).
- "Close as duplicate": the comment names the other task by its ticket key and, where every reader of the task sees the other one, its title (#4033).

### Changed
- Moving a task into a project that does not offer its own ticket type keeps the type and says so in the move message; the API answers `move_ttype` (#4033).

Package 2.1013 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- Undo across devices (#5513): changing, deleting and restoring household budget categories and recurring templates now appear in "Recent steps" and can be undone or redone from any device; the sealed limit / title goes back only under the key that sealed it, a category's order alone is no step.
### Fixed
- Undo (#5773): settings the app saves by itself (a view's block switches such as the period of the time report, a folder added along with a project edit or move, a device's old settings handed to the account) are no undo step any more, so Ctrl+Z or the undo arrow right after an action takes back that action instead of the setting.
- Settings (#5519): the list of known browsers for the "new device" security mail is written by the sign-in only; PATCH /api/settings no longer accepts it.

Package 2.1004 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Changed
- #5572: on a phone, the office list pages (quotations, invoices, reminders and the other office pages) show a single navigation line: the back arrow sits before the tabs, and the document kinds (credit notes, payment reminders, delivery notes, archive) follow their tab in the same row; with a single office the company and role line above the page is gone. The desktop stays as it was.
- #5494: the approval records of deleted video reviews (Settings > Move and export everything) go into the core's trash and show in the office trash (a private one in its creator's personal office); restore and delete for good there. A person without a personal office deletes them for good as before, without leftovers in history or undo.
### Fixed
- #5494: restoring a fixed cost or a cash flow correction from the trash (office trash, the toast's undo, the undo list) no longer passes their maximum (500 fixed costs, 50 corrections per month): 409 instead.
- #5494: undoing an office move deletes the target's copies of master data and sets on the core's way (no history or undo steps left behind); an account's end takes its private sign-off records' core history along.

Package 2.1009 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Fixed
- Task panel on phones: while a comment is being edited, the bottom bar (comment box with Send, date / done) no longer sticks over the edited comment, so "Save" and "Cancel" stay visible and tappable with the keyboard up (iPhone) (#5772).

Package 2.1003 (Bündel: Teil 1/6: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Weich rot: p2106_a_api, Weich rot: p21261_b_ui u. 15 weitere).
### Fixed
- #5716 #5722: Searching letter recipients and a client's address book contacts works again; both read the removed contacts search column and now search through the shared search index.
- #5721: Document notes show their time in seconds again, as before their move into the shared comments core.
- #5733: The shared comment routes are listed in the agent parity (review API or people only); the MCP tool add_comment answers with a clear error without a task id instead of failing.
- #5718 #5724 #5725 #5726 #5727 #5728 #5729 #5730 #5731 #5732: The database's back limit names every step of a release that raised it, not only the first one; the start check of an older version lists all reasons.
- #4839 #5717 #5719 #5723: Tests p230_ui (waits for the undo toast and the server state instead of fixed times), p21261_b_ui (the plan dialog's review kind), p2351_f_review (the core's trash retention) and p265_d_ui (no removed column in its setup, setup errors logged) follow the app.

Package 2.997 (Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Sammelpaket: Aufgaben ohne Paket (Dispatcher), Teil 1/6: Sammelpaket: Aufgabe).

### Fixed
- Undo: a setting the app saves by itself (the device's look on first start, view arrangements) no longer lends its undo group to the next step of another area - Undo took back the setting instead of the action (receipt suggestion, closed month, checked receipts, time entries, deadline task, agent proposal, new event) (#5697 #5699 #5700 #5701 #5703 #5704 #5707 #5710 #5711 #5478 #5607 #5615 #5702).
- Undo: the first upload of an account's look and the roadmap's view state (zoom, folded projects) are no undo steps any more (#5702 #5625).
- Undo: keys with several entries (favourites, workspace colours) are one undo step per change again, not bundled for 10 minutes (#5705 #5706).
- Undo: "Take it" and an idea taken over from a proposal record their server undo step; deleting a project into the list trash is a server undo step, so undo after redo makes it active again (#5606 #5611 #5609 #5709).
- Undo: a task's undo step keeps its code snippets and its lock (#5613 #5614).
- Table shares: an address row (pending invitation) can be removed and its role changed again (#5672).
- /api/state switches into the system context only when there are folder / group shares to read (#5137); a start no longer locks org_joins (#4841).
- The repair of lists in shared folders (#931) reads the folder shares from fs_shares again (#5677); restoring a rights group from the trash writes the rights log again (#5708).
- Tests follow the current behaviour (server undo stage 7, file version undo by pointer, confirmed addresses for shares, model-per-run agent defaults, word search, travel as a back step, CI speed calibration of the column width check) and static checks are clean again (#4949 #5682 #5683 #5671 #5617 #5624 #5354 #5679 #5680 #5678 #5612 #5616 #5618 #5620 #5622 #5698 #5681 #5641 #5720).

Package 2.1001 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Security
- #5669: sharing a list or a list folder by e-mail address binds only an account that proved the address (the core helper used by tables and wiki since #5643); an address nobody proved is answered like an unknown address and reaches nobody. The address path is decided once per request, and its answer carries nothing account-specific.

## [2.1016.0] - 2026-11-12

Not released (the CI of this version was red); its changes are listed under 2.1020.0.

## [2.1014.0] - 2026-11-12

Not released (the CI of this version was red); its changes are listed under 2.1016.0.

## [2.1009.0] - 2026-11-12

Not released (the CI of this version was red); its changes are listed under 2.1014.0.

## [2.1007.0] - 2026-11-12

Not released (the CI of this version was red); its changes are listed under 2.1009.0.

## [2.1001.0] - 2026-11-12

Not released (the CI of this version was red); its changes are listed under 2.1007.0.

[Unreleased]: https://github.com/Kalmido/kalmido/compare/v2.1020.0...HEAD
[2.1020.0]: https://github.com/Kalmido/kalmido/releases/tag/v2.1020.0
[2.1016.0]: https://github.com/Kalmido/kalmido/releases/tag/v2.1016.0
[2.1014.0]: https://github.com/Kalmido/kalmido/releases/tag/v2.1014.0
[2.1009.0]: https://github.com/Kalmido/kalmido/releases/tag/v2.1009.0
[2.1007.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.1007.0
[2.1001.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.1001.0
