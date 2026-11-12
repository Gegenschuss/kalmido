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

## [2.1024.0] - 2026-11-12

Package 2.1011 (Bündel: CI-Nachtjob install-upgrade rot seit 07.11. (pgdat, Test-Auswahl: Schema-Änderungen nehmen rls_direct , Aufräum-Ereignis (tidy) komm).
### Added
- The document view's "Actions" menu offers "New task", "Link with a task…" / "Open task" and "Add to / Remove from favourites" (#5688).
### Changed
- The document view's "Actions" menu is now the shared app menu: a sheet with title and close button on phones, arrow keys and Escape work (#5688).
- The plus button in the chat input (phone, narrow chat window) opens the shared menu "More" with the chat tools; after a tool the cursor returns to the message box (#5689).
- The time tracking Export menu and the "running" indicator use the shared menu, the running time shown in each group's heading (#5691).
- The nightly install-and-update check starts from the version that runs live (newest latest-ok tag) instead of the last GitHub release (#5713).
- Test selection runs rls_direct whenever the schema or a migration changes (#5674).
### Fixed
- Updating a self-hosted installation no longer fails building the image with "pgdata: permission denied"; the database, data, server key and .env stay out of the image build (.dockerignore) (#5713).
- An agent no longer gets the same tidy event again and again after its own changes; only a person's change (also via a public link) sends it again, naming that person (#5685).

Package 2.1015 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Fixed
- #5777: the upgrade test's filler row takes the first allowed value of a column with a CHECK listing its values (obj_follow.mode, obj_notif_cap.kind, obj_tags.scope_kind) in every table; the upgrade probe from live 2.996.0 failed on the filler, not on a migration.
- #5675: undoing a big import (master data, DATEV suppliers, an agent's fixed costs) and a moving personal office's letter links delete many rows with a few locks (`okern.ofk_purge_many`: one advisory lock per kind, the rows' own row locks in id order) instead of one advisory lock per row - thousands of rows could break the undo with "out of shared memory".

Package 2.1019 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Fixed
- #5633: applying, undoing and redoing an agent's triage / day plan proposal and a list rule whose chain moves a task now lock the moved tasks with all their subtasks (and the other tasks they write) in id order before the first write, like the batch move of tasks. A rare deadlock (error 500, no wrong data) against the restore of "Delete all times" is gone.

Package 2.1002 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Projekt-Sperre: gelöschte Textfelder bleiben mit K, Sammelpaket: Aufgaben ohn).
### Added
- Deleting or restoring an approval (video, image, PDF, audio) is now a step in "Recent steps" and can be undone or redone on every device; undo checks the rights of now, redo stops an open customer link again (#5490).
- The knowledge search also finds pages by their text that were shared with you through a folder or page share (#5279).
### Changed
- Search in documents, recognised file texts, knowledge pages and filed mails uses one shared keyed word index (obj_search_words, core/objwords.py); umlauts match either way ("Mueller" finds "Müller") and every word matches at its start, also with 2-3 characters. The old indexes doc_words, file_words, wiki_words and hub_words are moved into it and dropped; a background catch-up indexes older objects by the new rules (#5279).
- Restoring a project and deleting it for good from the projects' trash, and restoring a task, go through the shared core (one trash rule for projects in the core, a restore line in the project's history); routes and answers stay the same. Migration 5491_a only adds columns (lists.rev / updated_by, tasks.rev / updated_by / deleted_by) (#5491).
- Organisation bookmarks, feeds and approvals are covered by the shared trash's retention tests; unused trash-period constants of the old bookmark and feed runs removed (#5490).
### Fixed
- Deleting an entertainment receipt, fixed cost or other office entry for good now also removes its edit history and undo steps (#5695).
- Coverage guards (freelancer_coverage, tenant_coverage) no longer fail when a listed old route is tested now; they print a "can go" hint and stay red only for new untested routes or stale entries (#5696).
- A search no longer creates an organisation's key as a side effect (#5279).

Package 2.1024 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- Lint `tools/check_menu_own.py` (runs inside `check_layout.py`, so in the CI lint and the Mac lint): a menu built by hand outside `static/js/popovers.js` is red - `role="menu"` markup, a `<details>` fold-out at a dots button, an `aria-expanded` toggle with `aria-haspopup` or at a dots / plus icon button, `openPop` with a `menu-list` of its own. Every menu goes through the shared `menu()`; a real exception carries `menu-ok: <reason>` on the line. Choosers (listbox, check boxes, folds) stay untouched (#5693).

### Fixed
- main: CI red of 2.1020.0 in p21004_a_office_nav_mobile - the phone test taps the office tabs with a quick finger down / up; its 240 ms press grew past the long-tap time on the slow CI Firefox, which then sent no click.

Package 2.1017 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Changed
- Quote of the day (sign-in page and Today): shown once, in the interface language - German text for German, the French original or English for French, English for every other language; below it only the author. Sound poems stay in their original. No quote ends on a comma any more (#5784).
### Fixed
- Moving a calendar into the trash (or restoring it) while one of its events is saved no longer risks a deadlock: the core's trash locks the children first, in the order of an event's save (#5630).
- Two people / devices sharing the same item with the same person at once no longer leave two share rows: every writer of shares takes the same lock, several in a fixed order; account hand-ons write the object before its shares (#5645).
### Security
- Sharing a list or list folder by e-mail address no longer tells whether the address has a confirmed account: every refusal on that path gives the answer of an unknown address and writes nothing (#5774).

Package 2.1021 (Bündel: Merge Queue: eigene schlanke Prüfung für Queue-Ein, Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Changed
- An organisation admin who adds or invites a person by e-mail address reaches only an account that proved the address (a mailed link, a verified OIDC claim, a confirmed sign-up), like shares of tables, wiki and lists; an address nobody proved is answered like an unknown one (the invitation stays silent). The server's admin keeps adding by address. (#5775)
- Incoming mail: "mails from my own address" and replies by mail to a task count the sender's account only when its address is proved; otherwise the mail is handled like one from an unknown sender. (#5775)
- CI: a merge queue entry runs its own lean check - Lint, PR lint, semgrep, the e-invoice validators, ZAP, the hard suites and the suites it touches (stage "queue"); the new required check "Merge queue gate" is green when no hard suite or hard job is red (judged by suite, soft red suites hold nothing). A pull request runs only Lint and PR lint. (#5787)

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

## [2.1020.0] - 2026-11-12

Not released (the CI of this version was red); its changes are listed under 2.1024.0.

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

[Unreleased]: https://github.com/Kalmido/kalmido/compare/v2.1024.0...HEAD
[2.1024.0]: https://github.com/Kalmido/kalmido/releases/tag/v2.1024.0
[2.1020.0]: https://github.com/Kalmido/kalmido/releases/tag/v2.1020.0
[2.1016.0]: https://github.com/Kalmido/kalmido/releases/tag/v2.1016.0
[2.1014.0]: https://github.com/Kalmido/kalmido/releases/tag/v2.1014.0
[2.1009.0]: https://github.com/Kalmido/kalmido/releases/tag/v2.1009.0
[2.1007.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.1007.0
[2.1001.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.1001.0
