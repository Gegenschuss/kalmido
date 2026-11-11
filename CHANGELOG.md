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

## [2.941.0] - 2026-11-11

Package 2.928 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Changed
- Development: fewer merge conflicts between packages built side by side. New git merge drivers (registered by `tools/git_setup.sh`): the lint baselines `tools/*_baseline.json` merge by JSON value (a count both sides lowered keeps the lower one, `total` is recomputed, the file keeps its tool's layout), and `docs/dev/kern.md`, `docs/API.md`, `docs/OFFICE.md` keep both paragraphs when two packages add text at the same place; a line rewritten differently on both sides stays a conflict (#5597)

Package 2.924 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Changed
- Calm view: when the screen redraws (a live change, new search results, a new comment in the detail panel, a chat window update), the item you are reading stays where it was on the screen instead of jumping by the height of what appeared above it; at the very top the view stays at the top, at the end of a conversation it stays at the end (#5224)
- Shared core stage 7a + 7b: team chat rooms, calendars and address books decide who may see them only through the shares on their node in the shared core; the old member tables `tchat_members`, `ev_cal_members`, `book_members` and their mirror triggers are gone (#5069)
- A share of a calendar or address book that was taken back can be restored through the shared share list (`/api/obj/<kind>/<id>/shares`), with the same notice and refresh as sharing it in the dialog (#5069)
- Organisation export: rooms, calendars and address books carry their members as shares on the node; older archives with `members.json` still import, their members become shares (#5069)

### Added
- `tools/check_scrolljump.py` (CI lint): a new scrollIntoView / scrollTo / scrollTop assignment / focus() without preventScroll outside dialogs needs a `// sprung-ok: <reason>` comment; the existing places stand in `tools/scrolljump_baseline.json`, which may only shrink (#5224)
- `kalmido/core/kernretire.py`: the one start-time clean-up of every stage-7 area - counts the old rows left without a share, keeps the tables with a log line and an admin alert while any are left, else drops them (#5069)

### Migration (one way)
- At the first start with this version the old rows are copied forward once (every room / calendar / address book gets its node and every member its share; calendar / address book rows whose node already says no are dropped), then `tchat_members`, `ev_cal_members`, `book_members`, the triggers and functions of migrations 4712 / 5046 / 5089 and their `obj_revoked` rows are deleted for good. While a row is left that could not be given a node, nothing is deleted and admins see an alert. After the deletion the database refuses every older version (its back limit becomes the version that deleted the tables; see docs/UPGRADING.md) - an older version would rebuild the tables empty and take every member's access; the way back is a backup from before the update (#5069)

Package 2.932 (Bündel: Dateien-Leiste auf das Zeilenraster von Projekte b).

### Changed
- Files' panel uses the row grid of Projects (#5603): the filter groups Sender, Document type, Tags, Archive number and custom fields now sit like the groups of Projects (same head, same gap above each group in every density and on phones); "Shared with me" and the trash stand on the left edge of Files / All documents, set off from the filter groups by a group's gap instead of being stepped in like a sub folder.

Package 2.934 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Sammelpaket: Aufgaben ).

### Fixed
- Undo after applying an agent's proposal takes the whole proposal back again: since the undo across devices (2.905) the apply also recorded a step of the few writes the core tracks (for a contract reminder only the reminder, not the note), and Undo took back only that. Applying a proposal, its undo and its redo now record no step group beside the proposal's own step (#5596)

Package 2.933.0 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Sammelpaket: Aufgaben ).

### Fixed
- Moving an old SQLite database into Postgres works again: templates.user_id of the old file is read as owner_id (renamed in 2.905, #5288) and its times are taken over as TIMESTAMPTZ (#5404, CI red p2370_m_api).
- Deleting an office master data row moves the "office" change counter once again, not twice (the core's trash already ticks it since 2.905) (#5384, CI red p2566_b_bump).

Package 2.941 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Fixed
- Knowledge pages: a picture no longer pushes the text when it loads while you scroll. A picture attached to the page keeps its exact size from the start (the server notes width and height on upload); a picture from the file store, or one uploaded before this version, sits in a calm 4:3 box; a file-store picture that is still loading already holds that box. The same on shared and public knowledge pages (#5227)
- Bookmarks: the picture in the bookmark details sits in a fixed box, the dialog no longer grows when it arrives (#5227)

### Added
- `wiki_files.img_w` / `img_h` (migration fragment 5227_a, nullable): the size of a page's picture, read from its header on upload (PNG / JPEG / GIF / WebP; SVG from width / height or viewBox); the page's file list hands it out as `w` / `h` (#5227)
- `tools/check_scrolljump.py` also reports a new `<img>` in the web client without width / height that is not marked as sitting in a fixed CSS box (`// sprung-ok: <reason>`); the existing places stand in the baseline (#5227)

Package 2.940 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), GitHub-Release-Text: keine deutschen Paket-Titel m).

### Fixed
- The view no longer jumps on its own after a redraw: focus that comes back after a redraw never scrolls, the search field gets the caret only when Search is opened (also on the desktop), and chat windows keep their place when the window bar is rebuilt - a window read further up stays there, one at the end stays at the end (#5225)
- A bar that appears above the view on its own (notice / maintenance, supporter hint, notifications question, encrypted list) no longer pushes down what you are reading; the view is evened out by the bar's height, on the phone too (#5226)
- Document full view: a click on a small picture in the left strip moves only the mark, the strip stays where it is; it scrolls only when the open document would be out of sight (arrows, keys, swipe), and only as far as needed (#5601)
- Address books and calendars in the trash or of a disabled account no longer hold back the removal of the old member tables at start: a calendar in the trash gets its new file-store node in the trash with it, and a calendar in the trash or of a disabled owner opens nothing in the file store; restored or enabled again, its members have it at once (#5605)
- Release workflow: a version whose full CI was cancelled by the next push gets its image when every hard shard and hard job was green and only soft shards were cut (v2.883, v2.897, v2.902 had none); a cut hard part, a job without a result or a Lint whose scanners did not all run green still means no image (#5600)
- GitHub release text: no internal package titles any more - the summary line built from them is gone, all entries are merged under Added / Changed / Fixed and the highlights on top (#5636)

## [2.929.0] - 2026-11-11

Package 2.914 (Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Security
- Locking a project: the change history of its deleted time entries and notepads (the note / text before and after an undo) no longer keeps the text; it goes at the lock, and once at start for every project, as nothing can bring such an entry back. The lock also removes the history and undo copies of the project's settings across organisations (#5564)

Package 2.929 (Bündel: Aufräumung der GitHub-Versionen: Frist 14 -> 3 Tag).
### Changed
- The prune of old GitHub release objects and image versions keeps everything younger than 3 days instead of 14; the workflow "Prune releases" has a new input `days` to run it by hand with another window. Still kept: one checked version per week for 4 weeks, the current latest release, the newest checked version and all above it, `:latest`; git tags are never deleted (#5598).

## [2.910.0] - 2026-11-11

Package 2.905 (Bündel: Rückgängig über alle Geräte, Stufe 7: Browser-Verl, Dokument-Ansicht: Vorschaubild springt beim Wechse, Kern-Querschnitt Q8a: Gelese).

### Changed
- Undo across devices, stage 7: the browser keeps no copies of what it changed any more; Undo, Ctrl+Z and the "Recent steps" list go back through the server's undo steps only, Ctrl+Z takes back the person's newest step also from another device, a "Saved · Undo" button takes back exactly its own step; the date popover's Undo takes back the visit's server steps instead of writing a new change; areas without a server step keep "only this device" (#5255)
- Task read marks live in the shared core table obj_seen; the old table task_seen is moved over at start and dropped (#5284)
- Task, project and section templates are one kind of the shared core: an organisation's templates are changed only by its admins, deleting a section template puts it into the templates' trash, organisation templates come along in the organisation export, a key limited to projects sees and makes no templates; section_templates is moved into templates at start and dropped (#5288)
- Office trash: services, equipment, sets, texts, framework contracts, roles, crew, rights groups, fixed costs (also a fixed cost import taken back), cash flow corrections and a letter's links go into the shared core's trash instead of a copy; the office trash shows them and restores them (#5414)

### Fixed
- Document view: the preview picture takes the first page's size and place at once (zoom, fit, position, shadow); loading the full document only swaps the content, nothing jumps, also when paging to the next document (#5393)

Package 2.910 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Changed
- Lists, dialogs alike (#5442): dialogs that save by themselves close with "Done" (also when opened from another dialog, no "Back" any more: project, folder and repository settings, the project's Share dialog), the "Blocked by…" choice closes with "Close", the project status dialog has "Cancel" + "Save" with the main button at the right edge (was "Close" + "Update status"). The date picker closes with Escape alone (the dialog below stays open, the focus goes back to the date field). The project's Share dialog is built from one shared frame and no longer grows in steps while it loads. The folder's Share dialog, its role question and the several-tasks choice follow in #5587.
- Lists, quick add (#5445): each recognised part shows once - date, project and priority only as the composer's chips (a small x next to them = "don't recognise"), the syntax help disappears once something is recognised; on the phone the recognised title stays in sight in front of the chips.
### Fixed
- Lists, error messages (#5444): a refused tick says "Done could not be saved" (the server's text in brackets) and the circle is empty again; a refused move says the task is back in its place; reopening likewise; comments, history, dependencies and the project overview name what could not be loaded; offline there is one sentence ("Only available online.").

Package 2.909 (Bündel: Projekt-Sperre: gelöschte Textfelder bleiben mit K, Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Security
- Project lock: deleted text fields leave the field trash when the lock is switched on and when a key change is done; a field restored from the trash (also by Undo) takes back only values that fit the project's lock now (no plain text into a locked project, no ciphertext into an open one, during a key change only the new key's values; while the lock switches the restore answers "try again" and the field stays in the trash). Tasks in the trash of projects switched before forget a section name of the other state once at the start; the one-off clean-up of plain section names in locked projects (#5552) now reaches up to the day it went live (#5565)
- Restoring "Delete all times" and restoring a deleted field wait for a task that is being moved into a locked project at the same moment, so no plain title, note or field value lands next to it (#5583, #5565)

## [2.902.0] - 2026-11-11

Package 2.902 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Fixed
- Encryption: undoing "Delete all times" from an older window no longer brings back the title and note of a task that has since moved into an encrypted project; the server's undo copy is used up by person and time (not by its seal), so a second undo no longer doubles entries; the cleanup of trash copies takes the copy's lock (#5574).

### Fixed
- main: CI red of 2.900.0 in p2892_b_receipts_ui - the browser test helper waits after every jump to the blank page until it is really shown, so a late page load can no longer swallow the next sign-in (#3506).

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

## [2.900.0] - 2026-11-11

Not released (the CI of this version was red); its changes are listed under 2.902.0.

[Unreleased]: https://github.com/Gegenschuss/kalmido/compare/v2.941.0...HEAD
[2.941.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.941.0
[2.929.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.929.0
[2.910.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.910.0
[2.902.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.902.0
[2.900.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.900.0
