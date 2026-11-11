# Changelog

All notable changes to Kalmido are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Kalmido uses
[semantic versioning](https://semver.org/): every published change gets at least a new patch version, new features a
minor one. Releases in which operators have to do something carry a fixed section "Action needed"; the update notice
in Settings > Help shows that section of the target version.

## Older versions

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

## [2.900.0] - 2026-11-11

Package 2.898 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Security
- A task moved into a project encrypted in the browser no longer leaves its title, note or field values in the trash copies of other projects ("Delete all times" undo copy, deleted custom fields); a one-time pass cleans projects locked before (#5562).
- Switching the encryption off or finishing a key change removes the trash copies that hold ciphertexts (deleted sections, deleted text fields), so a later restore cannot bring back unreadable text (#5563).

Package 2.892 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- Documents: "Optimise PDF" in the document view's Actions and in the selection bar's More - a scanned PDF becomes a new version in black and white, greyscale or colour per page (Automatic, Black and white, Greyscale) with a searchable text layer; the size before and after is shown ("2.4 MB -> 160 KB"), a result that is not smaller keeps the file unchanged, the original stays as the older version and is never pruned; "Remove blank pages" lists the pages that go before anything happens (#4873)
- Documents: the setting "Optimise new scans automatically" (off by default) - never for office receipts, where only the button with a note that the original stays is offered (#4873)
- Documents: after an optimisation, Actions offers "Download searchable PDF" and "Download original" (#4873, #4806)
- Optimise PDF runs Poppler and Tesseract per page in their own process with memory, CPU, file size and time limits, at most 60 pages / 100 MB per run (KALMIDO_PDFOPT_*), at most 200 waiting runs per person; agents get 403 (#4873)
### Changed
- Office > Receipts: the list comes first - one tool row (Upload, Select, receipt types, CSV / ZIP); on a phone only "Upload receipt" and "More" stay visible, the rest is in the More menu, the first receipt shows at 360 px without scrolling; touch devices get ONE upload button with a sheet (Photo / Files), the bookkeeping page too; the receipt sheet shows "EUR" beside the amount and its foot (More, Cancel, Save) fits one line on a phone (#5453)
- Receipt checks: "... not found" hints are soft - listed last and not counted, so a complete receipt carries no hint label; a text without amount, rate and date counts as unreadable; the check version rises to 2 (all receipts are checked again, 200 per list call); the agents' check items carry `soft` (#5453)
- Office on a phone: the big country card "Where is your office?" of a new office stands only on the office start page; every other page shows the slim line with "Select country" leading there; the second choice is labelled "Basis of the income statement" (#5449)
- Office dialogs like the rest of the app (#5455): Cancel left of the main button, "Close" is no main button, deleting and other final confirmations (journal entry, closing a cash day, cash book storno, a bank rule's marks) are red, delete buttons are solid red, the PDF question of a draft is the app's usual question dialog, the rights group picker is the app's menu (phone sheet, Escape)

### Fixed
- main: the documents' filter dialog uses the app's own date picker instead of a native date field (CI red of 2.883.0, ux1_ui); the p2826_b_api test no longer races the watchdog that wakes a waiting starter plan.

Package 2.891 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), CI-only rot: p21382_b_ui).
### Changed
- Split view: the right half is now the normal app with its sidebar, tab bar and menus and the full data (address /?split=1); it keeps only the guard against writing UI state or settings; offered from 90 rem (about 1440 px) window width; a narrow document view keeps room for its title (#5358)
- Notifications: one send decision obj_notify in the core - every recipient of a News entry, reminder, watcher note, team chat push, event reminder, review / approval / urgent bell push is cut with the core read right (obj_role >= view) before anything is sent; the per-area recipient checks are gone (#5270)
- Task panel calmer: the newest comment is in sight on opening, the phone's bottom bar fits one row without the project, the Projects field only for tasks in more than one project, Watch and the watcher count as one element, no empty Attachments heading for readers, no gap under Watch, comments' Loading keeps its height (#5439)
- Lists: empty, loading, error and no-access states from one block (emptyState / loadingHtml / errorState with Try again / noAccessState); a filter without hits says so and offers Change filter; an empty board shows an empty state; + Section sits under the empty text; Completed / Trash show a load error instead of "empty" (#5440)
### Fixed
- Dragging a column width in a large list no longer turns the drawing of off-screen rows off and on (Firefox 300 rows: release to done 69 -> 44 ms, 60 frames per second); the width sheet is not rewritten when unchanged (#5360)
- CI red p21382_b_ui: the organisation dialog's size grip after the foot let the card overflow 1.25rem; the grip nets zero there (#5353)

Package 2.900 (Bündel: Projekt-Sperre: Rückgängig-Kopien von Zeiteinträge, Projekt-Sperre: Rückgängig-Kopien von Projekt-Eins).

### Security
- Project lock: switching the end-to-end lock on now also drops the undo steps whose copy keeps a time entry's note or task title in plain text - of entries deleted since, of entries of tasks moved into a locked project and of entries moved elsewhere - and the history rows an earlier undo wrote with those texts; undo never writes a note back into a locked project (a deleted entry comes back without its note, a note change is refused and stays) (#5550)
- Project lock: the undo steps and history rows of the project's settings (description, status note) and of its notepads (title and text before they were emptied for the lock) go at the lock too (#5551)
- A one-time run at start applies both to projects locked before; the whole step group goes, so a few harmless undo steps of locked projects disappear once (#5550, #5551)

[Unreleased]: https://github.com/Gegenschuss/kalmido/compare/v2.900.0...HEAD
[2.900.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.900.0
