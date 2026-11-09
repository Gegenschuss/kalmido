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

## [2.787.0] - 2026-11-10

Package 2.764 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Added
- Approvals: the client link without an account works for image and PDF approvals too (#5040) - the client sees the file,
  sets a point (image) or a page and a point (PDF) with the same numbers as in the app, comments and approves; the link hands
  out only the files of the versions it shows, sandboxed. Find it: an image approval > Client link > open the link on the phone,
  tap the image.

### Fixed
- Income statement / VAT return: entertainment receipts at the edge between a "receipts" year and a "bank and cash" year count
  exactly once (the day of their bank line decides, as for receipts since #5241); a travel receipt dated in the year before
  its trip counts in its own year (was in none) - also in the exports and DATEV (#5313).
- Office: a receipts year reads the bank / card / cash lines of the near years only instead of every year (#5314).
- Client link: the guest page played the newest audio file for an older audio version (#5040).

Package 2.777 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Teil 1/6: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Neuer Server-Agent: Startpak).

### Added
- Document view: delete and turn pages of a PDF, saved as a new version of the same document (#4874). The button
  "Pages" in the preview bar opens a strip of all pages; mark pages (Ctrl/Shift for several), Del removes, turn left /
  right, "Delete blank pages" (blank pages are only suggested, never removed by themselves). "Save as new version" keeps
  the original as the older version in the tab History; id, archive number, sender, tags and links stay. Undo is one
  step. Only people with write access; office receipts show that the original stays as a version. Find it: open a
  PDF document, Pages, mark page 2, Del, Save - the view shows one page less, History lists both versions.
- Undo across devices, stage 6 (#5254): calendar events (edit, move to another calendar, trash, restore), contacts
  (edit, move to another address book, trash, restore), files (rename, move, trash, restore, new version, restore a
  version) and habits write their steps on the server, so the list of recent steps can take them back from another
  device. A file's step points at its version, the content is never copied. Taking back checks today's rights.
- New server agent: the create dialog has "Projects for the agent" (several; one's own projects, for a team agent
  those of the organisation); the chosen projects are shared before the starter pack (#5378).

### Changed
- New server agent without a shared project: the starter pack creates its routines paused and waiting instead of
  showing three red errors; they start by themselves once the person shares a project with the agent. The agent
  window lists all starter pack items with their state, adds a missing one at any time and shows a calm hint with
  "Share project" (#5378).
- A team agent is listed in the tab Agents for every member and admin of its organisation, also without a shared
  project, with "No project shared" or "N projects"; a member without a shared project can write to it and gets a
  fixed answer from Kalmido on how to share a project - the agent itself gets nothing from that person (#5378).
  Find it: as a member of an organisation, open Agents - the team agent is there with "No project shared".

### Fixed
- Restoring an older version of a document recognises it again at once (page count and text no longer stale for a
  minute) (#4874).

Package 2.780 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), CI-only rot: p271_ui, Teil 1/6).

### Fixed
- Tags and chips readable again: text on the pale accent ground uses the normal text colour (tag pills in the tag field, filter chips, the selected list row, duplicate and step badges); a lint rule in tools/check_appcss.py refuses --accent-ink on --accent-soft (#5388).
- Document view: the leaf arrows with "n of m" stay in the middle of the head, whatever the length of the file name; long names are cut with an ellipsis (full name in the tooltip), the counter has a fixed width; phone layout unchanged (#5389).
- Opening a document directly by its address (reload, link, favourite) no longer flashes a red "Not a folder" message (#5391).
- Master data PATCH ticked the office area twice (p2566_b_bump, #5384).
- Test fixes for suites red in CI: p2623_b_unshare_cards follows the #5246 decision (#5385), rls_direct fills typed time columns properly (#5386), p249_b_api no longer trips over the PIN's digits inside a random salt (#5374), p2624_b_order puts its probe modules at their sorted place (#5403), p2742_c_tagpills_ui accepts the #ablage address of the document view.

Package 2.778 (Bündel: Bündel: Gemeinsamer Kern Stufe 7e: Büro und Ablage - Direk, Rückgängig über alle Geräte, Stufe 4: Büro: Gruppe, Rückgängig über alle).
### Added
- Office: a walk-through for open credit card positions and open bank bookings - one booking after the other with progress "n of m", the candidates as cards with a preview of the receipt / invoice, take over, search another, upload, no receipt needed, private (bank also ignore, cash, split), skip, undo of the last step; keys 1-3 / Enter / arrows with a mouse, one card per screen and swipe on a phone (#5383)
- Office: the same candidate card (preview, amount, date, reason) replaces the text suggestion and the text match list in the credit card and bank lists (#5383)
- Undo across devices, stage 5: a person's table cell writes and added rows / columns, and a knowledge page's saves, are steps of "Recent steps" pointing to the table's batch / the page's versions; a cell or page changed since by someone else stays and is named, the rest goes back (#5253)
### Fixed
- Office settings, terms and conditions (PDF): the language and the file name no longer run together; every office list shows the name on top and the detail line below (#5382)
- Trash core: a writer who put an object into the trash (trash_role edit) can take that own step back from "Recent steps"; the plain restore from the trash stays with manage (#5371)

Package 2.787 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Security
- Locked (end-to-end encrypted) lists: moving a task from an open list into a locked list records no server undo step for
  that task, so its former plain texts no longer stay in the undo history after the move (#5417); while a list is locking
  itself, an undo step names "Task" instead of the plain title.

### Fixed
- A task opened by its address (link, notification, reload, bookmark) shows its own project behind it with the task's row
  marked, no longer the empty Inbox; Back leads into that project (#5438). Find it: open a task link from another app or
  reload the page while a task is open - the project list stands behind it.

### Fixed
- main: CI red of 2.782.0 - the default columns of lists and collected views (Today, My tasks, ...) follow the row's symbol level again (Calm / Important), task numbers show in collected views again, the subtask cell tells screen readers what it counts, column titles stay at the top while the rows scroll, editing a title in a row with columns keeps the row's height (#4502); in the agent chat header on phones the picture's and the back arrow's touch areas no longer overlap (#5243); a long document title on a phone no longer pushes the actions into a second line, the preview no longer jumps when leafing (#4876); old suites follow "Recent steps", the full-width pages and the document title field (#5250, #4840, #4876); two suites wait for the settled state instead of a fixed time (#3506); CI red of 2.786.0 - after splitting a stack its Undo stays on screen (no "Not found" for the gone document) (#4887), suites follow the start card "Recently edited" (#5352) and a team chat redraw (#3506).

## [2.786.0] - 2026-11-09

Package 2.769 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Added
- Workspaces overview: under "All workspaces" Knowledge, Files and Read later no longer repeat the sidebar's workspace list; they show "Recently edited" across all workspaces (pages, files, read-later entries; the 20 newest, workspace chip, who, when; a tap opens it), "Pinned" above when there are favourites, full width. The workspaces stay as compact chips only where no sidebar shows them (phone, collapsed sidebar, Read later). One read-only endpoint `GET /api/recent` with the areas' own visibility checks, for people only (#5352).
- Start: new block "Recently edited", on by default, can be hidden via "+ Block"; 8 entries, "More" leads to the overview; inside one workspace only its items (#5352).
- Tables: number, currency and percent columns get "Decimal places" (Automatic, 0-4) in the column menu, currency columns also their own currency (default: the table's). Stored values and formulas keep the full value; display, group sums, pivot, print, CSV and .xlsx export follow the column, an .xlsx import reads them back. API v1 / MCP `sheet_create` and `sheet_add_column` take `dec` / `cur` (#5351).
- Files: a folder with recognition (e.g. Documents) has the list / cards switch again (cards stay the default, the choice is kept per folder); the list shows Name, Type, Sender, Date, Amount and To review, sortable; on narrow screens the fields form a second line under the name. Documents can also be sorted by type and by "To review" (#5340).

### Fixed
- Files path line: "All workspaces /" sits on the same line, height and gap as the other path parts (it was a link, now a button like them) (#5339).
- Toast on iPhone: a tap on "Close" could reach the row below (e.g. complete a task) when the toast went away during the tap; a finger on the toast now keeps it, and its old place swallows a click for a moment after it hid. A mouse still on the toast keeps it after a click (#5350).
- Table import: an .xlsx with a very long number format no longer stalls the import (#5351).

### Fixed
- main: CI red of 2.774.0 - switching on a project's encryption now also removes the plain-text undo steps of its tasks and sections (#5408); the deploy webhook's auto close no longer fails with a server error (#5406); a change on one device no longer makes the person's other devices reload everything (#5407); tests p2370_m_api and p2369_4_api follow the reaction tables' move and the own undo counter (#5404, #5405).

Package 2.754 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Agenten-Seite: Job-Karte bekommt 'Chat öffnen' - J, Bündel: Sammelpaket: Aufgaben ohn).
### Added
- Job cards on the agents page get "Open chat" (running and ended jobs); a tap on the job title opens the job's chat too, and Back leads to the agents page again. An ended job's chat keeps its input: a message wakes the job up (#5222).
- Shared core: tasks, events, filed mails and clients are light kinds of the object core (role, title, link), with exactly the role of their area's own checks (#5268).
- CI: CodeQL (Python, JavaScript) and a Trivy scan of the app image, reporting only - high / critical findings in the job summary (#5300).
- CI: the nightly full run measures the server's test coverage; figure and modules without any coverage in the job summary, no gate (#5298).
- Lint: every `${}` in an HTML template runs through esc() / tr() / a safe helper or is marked `html-ok`; the old findings are a shrinking baseline (#5297).
### Changed
- Tasks on phones leaf like turning a page: the previous and next task lie drawn beside the open one with their comments fetched ahead, follow the finger and snap in - nothing slides in afterwards (#5213).
- CSS: one phone width (599px) and one tablet width (767px) for all media queries; a warning check lists unused classes and odd widths (#4511).
### Fixed
- A job chat opened on a phone from another page loaded no messages (#5222).

## [2.782.0] - 2026-11-09

Package 2.772 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Added
- Files: below the folder tree, after "All documents" / "To review", foldable filter groups over all documents of the workspace: Sender, Document type, Tags, Archive number and every custom field of type selection or checkbox, each value with its number of documents; a click shows All documents with only that filter (the row is marked), a second click removes it; over 15 values the most used 15 and "Show all"; each group remembers open / closed, the head has a button to manage it (#4890)
- Archive number as a filter: one number or a range ("143", "140-150"), with / without archive number; also in the filter sheet of the documents list on phones, together with the custom fields (#4890)
- API: GET /api/docs/facets (filters with numbers, same rights as the list); /api/docs takes asn=, has_asn=1, no_asn=1, cf=<field ids>:<value>; facets carry count, asn and fields; saved views keep the new filters (#4890)

### Changed
- The filter pills of the documents list show the number of documents per sender, type and tag (#4890)

Package 2.750 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- Documents have their own title, separate from the file name: the title (without ".pdf") is shown and edited in the document view, cards, list and the documents search and sort; the file name is changed apart under "More fields", with a button "File name from title" that keeps the ending. Titles may repeat; file names stay unique per folder. Download, ZIP and sharing use the file name and add a missing ending from the file type. API v1 `title` writes the title (#4876).
- Column titles with click sorting and the column menu also in My tasks, Today, the collected views and in lists without own columns; a new column Project (on in collected views) (#4502).
### Changed
- The home-screen web app's status bar is plain black again (no more black strip below the tab bar or header under the clock); the slimmer tab bar stays (#5240).
- Wiki: attaching, dropping and deleting a page's files only while the page is being edited; reading keeps Open and Copy link (#5229).
- Prune keeps the checked version of a week only for the last 4 weeks; older GitHub release objects and images go, git tags always stay (#5247).
### Fixed
- Dragging a file or card inside Kalmido onto a folder moves it and never uploads it as a new version (#4879).
- A recognised document opens the same document view from the file store's list as from the cards (#5228).
- Agent and job chat header on phones: tight, even spacing and the same height in every state (#5243).
- Wiki backlinks of a task, file or table list only pages the viewer may read by the page's own role (#5264).
- An expired operator setup code is deleted, the start code comes back and the try counts as a failure (#4518).
- A module loaded during the page start could run before the keyboard registry ("kb_on is not defined") and stayed broken until a reload (#5307).

Package 2.773 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Sammelpaket: Aufgaben ).

### Added
- Undo across devices, stage 2: the list "Recent steps". Right-click or long-press the undo arrow, or open "Recent steps" in the account menu (own page, Android back closes it). It shows your own steps of the last 30 days from all devices with time, area and device, up to 100; "Back up to here" undoes everything above the chosen line, a step that cannot be undone (finalised invoice, sent document, very large change) is greyed out together with everything older; steps of areas still kept in this browser carry "only this device", unsent changes stand on top; on a conflict the rest of the group is undone and the list names what stayed. The redo menu shows area and time; the browser keeps 100 steps instead of 30 (#5250, #5242).
- One trash in the core: `obj_trash` / `obj_restore` / `obj_purge` take an object's registered children along, purging goes one way, the core retention run (`obj_trash_prune`, hourly in the watchdog) deletes for kinds that opted in, and trashing / restoring is a step in "Recent steps". New helpers `live_sql()` / `trash_sql()` and the lint `tools/check_live_filter.py`: a new handwritten `deleted_at IS NULL` is red, the existing places stand in a baseline that only shrinks (#5292).

### Changed
- Customer link: a guest's fetch of a file is noted in the file's history ("opened through the link"); sealed files above 50 MB (`KALMIDO_REVIEW_LINK_SEALED_MAX_MB`) are not handed out without signing in, the link answers 413 with a short note (#5330).

## [2.774.0] - 2026-11-09

Package 2.763 (Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Changed
- Reactions are part of the shared core (#5269, stage Q1): one table `obj_reactions` holds the reactions of task comments,
  team chat messages and the chat with an agent; `comment_reactions`, `tchat_rx` and `chat_reactions` are gone (their rows
  move at the first start, one-way). One rule for all three: not on one's own message, not for guests / read-only people.
  A deleted team chat message keeps its reactions in the trash: "Undo" / restore brings them back (before they were lost).
  Team chat reactions also carry `count` now, like the other two. Find it: react to a team chat message, delete the
  message, undo - the reaction is back.

### Fixed
- Phone scan: a page over 40 million pixels is refused from its header before it is decoded (#4527) - a fixed limit of the
  scan instead of Pillow's process-wide one, which depended on which module set it last.

### Fixed
- main: p2351_a_officetree_ui names on a red phone drawer what the page showed (drawer open, clicks, tree nodes, route, dialogs, page errors), so the next CI red of 2.771.0 can be traced (#3398)

Package 2.774 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Added
- Undo across devices, stage 3: every change of a person to a task records its step on the server, in the step group of the request, whatever way it came (editing, multi-select, dragging, dependent dates, the offline queue, a proposal applied): only the changed fields before / after, plus completing (also a recurring task), reopening, the trash, restoring and creating; sections (name, limits, meaning) and their order too. `POST /api/undo/to/<id>` takes them back through the tasks' own write path - a field changed elsewhere since stays and is named, the other fields go back - and `POST /api/undo/<id>/redo` brings them forward; a task a batch left as it was records nothing, the undo itself records no new step, the parts of a task deleted for good go with the watchdog (#5251).

Package 2.767 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Changed
- Release images: the image `:X.Y.Z` of a version is now built when its full CI is green OR red only in suites outside the hard areas (invoices / office, backup / restore, sign-in and tokens, security scanners - `tests/hard_suites.txt`, the same list the live update uses). All hard shards must be green, every red suite must be named and soft, a security scanner that failed or did not run, a skipped hard job, a missing shard, a cancelled run or only the push stage still keep the image back (`tools/ci_gate.py`). Before, not one of the last 100 full runs was fully green and `latest` stayed on 2.502.0 (#5324).
- Weekly release: the notes name the suites that were red outside the hard areas in the full CI of the released version ("Known test failures in X.Y.Z"), or say that the list could not be read (#5324).

Package 2.743 (Bündel: Bündel: CI-only rot: p2466_c_ui + p2306_f_doc_anchors (Nac, CI-only rot: p2299_e_agentread_ui (TypeError readi, Büro: direkter Banka).

### Changed
- Back arrow: the visible ‹ on contacts, clients, letters, office documents, created documents, notes, team rooms, wiki pages and the agent chat goes back in the history when the previous view is the list it leads to, otherwise it replaces the current entry - Android Back no longer opens what was just closed; the "one level up" links in office and tables do the same (#5235).
- List beside detail: contacts, clients, invoices and receipts share one layout block (`.lsd2`) - narrow list (15rem) next to the detail, about 40 / 60 from 100rem on, one column on phones; the receipt dialog docks over the right column instead of indenting the page (#4930).
- CI: GitHub Actions on their current major versions (checkout 7, setup-python 7, setup-node 7, cache 6, upload-artifact 7, download-artifact 8, setup-java 6, docker actions 4 / 7), still pinned by commit hash; Dependabot also refreshes the base images of `Dockerfile` and `embed/Dockerfile` (#3794).

### Fixed
- Office > Bookkeeping: when the EUeR basis changes between two years ("Receipts" one year, "Bank and cash (strict)" the other), every receipt counts exactly once - in the income statement, the neutral export and the DATEV export, also with cash / card lines; a receipt of late December paid in January is no longer listed as open in the old year (#4937).
- Sign-out without network: the session on the server is ended on the next load of the app, so a shared device does not open the account again once it is online; tests for the user boundary of the offline queue (other account, order, temporary ids, idempotency key) and for sign-out (cache emptied, question about unsynced changes, also offline) (#4284).

Package 2.747 (Bündel: Gemeinsamer Kern Stufe 7e: Büro und Ablage - Direk, Rückgängig über alle Geräte, Stufe 4: Büro: Gruppe, Rückgängig über alle Geräte,).
### Added
- #5249 Undo across devices, stage 1 (core): every write of a person records its undo step on the server as a part of a step group per account (time, area, device, label, state, bytes); `GET /api/undo` lists the own groups, `POST /api/undo/to/<id>` takes them back newest first (a part changed by someone else stays and is named, the rest goes back), `POST /api/undo/<id>/redo`. Caps: 300 groups per person, 30 days, 256 KB per part, 2 MB or 1000 parts per group (bigger steps are listed, not undoable). The watchdog prunes, the retention page counts them. Agents record no steps and get 403. A step older than a key rotation of its organisation is refused instead of writing an unreadable copy back. No visible change yet (the list "Letzte Schritte" comes with #5250).
- #5252 Undo across devices, stage 4 (office): office steps carry a label (document kind and number, client or master data name; letters only their number), and finalising, sending, payments, DATEV exports and period locks write a barrier: undo stops there instead of silently ending the editor session. Undo and finalising a document now take the same lock.
- #5246 The last hard deletes of the office go into the office trash and can be restored: a quotation part with its positions, a rights group (without its members), an orphaned video sign-off.
### Changed
- #5246 Shares of the file store (share dialog, moving, splitting a stack) run through the core (`obj_node_share` / `obj_node_unshare`); a removed share lands in the core's revoked list. Leaving an organisation no longer deletes the same rows twice.
- #5246 Saving office master data runs on the core write layer (lock, version, undo step, history); a conflict answers the current state under `current` (was `row`). The "saved · Undo" of master data and client dialogs goes through the core's undo.
### Removed
- #5246 The table `office_undo` (unused since 2.567) is dropped (one-way: its at most one day old copies, read by nothing since 2.567, are gone; an older version only logs a watchdog error).
### Fixed
- #5249 `field_trash.field_id` carries the "no FK" marker (the schema rule of p2103_c_api was red).

Package 2.771 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Fixed
- Tests: p2742_c_textlayer_ui measures "Shift+arrow does not leaf" against the address before the key (a document link opens under the files area since #4887) and measures the text layer once a redraw has put it back (#5338).
- Tests: p2370_m_api expects the SQLite move report without the table paperless_links, which 2.755 dropped (#5265), and checks that its notes name it (#5342).
- Tests: p2391_t_ui waits for the options of a choice menu instead of a fixed 300 ms (#5343).
- Tests: p2283_ui waits until closing the quick add sheet has taken its history entry back before it opens the next view; a navigation that landed before that Back was taken back to the inbox (#5341).

### Changed
- Lint: `tools/check_migrations.py` reports a column DEFAULT in a migration fragment that calls a function the backup restore refuses (the list `_CALL_HEADS` of `kalmido/admin/backup.py`, read from there), e.g. `now()` - use `CURRENT_TIMESTAMP` (#5333).

Package 2.768 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Changed
- Files: ONE selection for rows and every card - documents, plain files and folders - in a folder's list, its cards, a folder with recognition, All documents and To review (#4888). One bar: All, Move (into a folder of the area, one undo), Download (one file or a ZIP), Edit (tags, type, sender - only with documents chosen), Move to the trash (red, asks with the number, one undo), More (CSV, another workspace). What you may not change is left out and counted ("2 skipped").
- Files: a right click or a long press on a row OR a card opens the same menu with "Select" on top: Open, Download, Share, Rename, Tags, Move to, a new version, Recognition, Move to the trash (#4888). With several ticked, the menu of a ticked one shows the bar's actions. Deleting from the menu, the bar or the document view is one way with one undo.
- Files: the document view is the details sheet of every file (#4888): its tab History lists the versions (view, download, restore, upload a new one - one undo step each), the history and "Mentioned in"; readers see the versions without the writing buttons. Its Actions have "Upload a new version…", "Move to…" and "Rename…". "Details and history" of a file opens this tab; folders keep the dialog.
### Added
- Files: a "+" at the head of the folder tree in the sidebar makes a new folder (#4888).
- Files: document, file and folder cards can be dragged onto a folder (sidebar tree, path, list, folder cards; on a phone hold, then drag); a ticked card drags the whole choice, one undo (#4888). A drag that begins in Kalmido never uploads (#4879).

## [2.771.0] - 2026-11-09

Not released (the CI of this version was red); its changes are listed under 2.774.0.

## [2.766.0] - 2026-11-09

Package 2.765 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Teil 1/6: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Sammelpaket: Aufgabe).

### Added
- Account import: absences (into the personal office, sealed; a waiting request arrives as an entered absence), timesheets (a month already here keeps its own, the preview and the result name it), the household budget (categories with limits, recurring items and entries onto the budget list that comes along; receipt files are not in the export and are named as staying behind) and the playbooks of folders with their versions now move along; the undo takes them away again, a budget list changed since stays whole (#3965).
- Tests: one touch suite for the phone's main views at 375, 460 and 840 px and the iPhone Duo closed (382 x 580) - Today, a project with a task and comments, the file store with an open document, knowledge pages, calendar, contacts, Office > Invoices, the agent chat and the settings: no sideways overflow, no button narrower than its content, no overlapping buttons, the "…" menu and its arrows, sheets close, long press, leafing, a tap in a scrolled dialog (#5170).

### Fixed
- Account and organisation import: an amount with a third decimal place (1234.567) or one that is no plain number is no longer rounded or turned into 0 silently in the money columns - the row stays out and the import's report names the value, as the start's migration does (#5315).
- Document view: a narrow view (the Fold open at 840 px beside the side bar and the file tree) is one column like on a phone - the preview on top, the fields below, swiping leafs; before, the preview was 16 px wide (#5331).

Package 2.758 (Bündel: Agenten-Seite springt beim Aufklappen von Verlauf/).
### Fixed
- Agents page no longer jumps while jobs work (#5223): an open History keeps its lines until the new ones are loaded and only the inside of its box is exchanged (the box keeps its scroll, the bottom stays the bottom); "Loading…" only on the first opening, with a fixed least height; a tap on History opens just that box instead of redrawing the page.
- The Conversation section of a job card is no longer replaced on every reload (#5223): only its messages are exchanged, the opened section under the finger stays.
- Open jobs keep their places (#5223): ordered by start (newest on top) instead of their last change, so a working job no longer climbs over the others on every step.
- The agents page keeps what you look at (#5223): a redraw or a box filled later holds the tapped row (or the first card in sight) at its screen position; a new job appears on top only when the page is scrolled to the very top. The agent cards sorted by "Need" are sorted when the page is entered, not on every live update.

Package 2.766 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), CI-only rot: p2173_a_travel_care_scope, Bündel: Sammelpaket: Aufgaben ohne Paket (Dis).

### Added
- Settings > Help > Check code: shows the version and the SHA-256 of the code this browser really holds (its own hash of every file in the service worker's cache, one recipe with the release's `web-manifest-X.Y.Z.json`), a "Copy hash" button, the files that differ by name, a link to the GitHub release of the version and a guide; it says honestly that it catches mistakes and slips, not an operator who means to deceive. New `docs/CODE-VERIFY.md` with the manual way (#5220).
- Service worker: when the code's hashes change while the version stays the same, a bar says "The app's code changed without a new version" with a button to the check; `/sw-manifest.json` names the version (#5220).

### Fixed
- Settings on a phone: opened straight into an area (e.g. from the office's old settings address) and then leaving by a link or a new address, the settings closed only back to their overview and stayed open over the new page since #5214; a new address closes them whole again, Back still steps through the areas (#5322).
- Video review, client link: "Valid until (optional)" uses the app's own date picker like every other date field instead of the browser's native one (#5321).
- Tests: the member's answer for somebody else's travel expenses of a shared trip is the 409 with the way to the own ones in the office (since #4958), checked without trip id or amounts (#5329); the two-process long-poll measures its wake from the other process' event, not from the slow process start of the CI runner (#5323).

## [2.762.0] - 2026-11-09

Package 2.726 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Fixed
- Menus: every entry that opens a further menu, choice sheet or picker now shows the arrow on the right like a second level (e.g. "Permissions: …" in the agent chat's ⋯ menu, "Workspace…", "Section menu…", "Move to folder…", "Sort…", "Notifications: …"); the lint check `tools/check_menu_next.py` (inside `check_layout.py`) keeps new entries from forgetting it. The info lines of the agent chat menu (kind of agent, usage) all look the same now, the kind line was greyer than the rest (#5164).
- Tests: the suites with their own Firefox start (p230, p240, p241, p242, p251, p252) start as a mouse too, like `tests/ff.js` since #5169 (`MOUSE_PREFS`) (#5160).
- Welcome tour on a computer with a mouse: the last card "Settings and modules" was cut off (9 steps with the keyboard step, the tour shows 8); now the keyboard step gives way and Settings stays the last card (#5160).

Package 2.762 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Fixed
- Weekly release: the prune plan no longer fails silently - the plan step always prints the script's output; a refusal (no latest-ok tag or no latest release) ends as a warning with an empty plan, nothing is deleted; any other error stays red with its message (#5320)

Package 2.760.0 (Dragging between the halves of the split view, real time types in the core, server key loss in the docs).
### Added
- #4859: Drag between the two halves of the split view (and between windows of the app): a document onto a task = linked, a task or file into a knowledge page = a reference, a task onto a project in the sidebar or a list row / column = moved, a task onto a calendar day = its date, a file or document onto a day = an all-day appointment with a reference, a document into the office = moved to the office, a file onto a folder of the file store = moved. The drag carries only kind and id; the receiving half calls the normal routes (rights checked by the server) and each drop has its undo.
### Changed
- #5311: The core template (docs/dev/kern.md) creates created_at / updated_at / deleted_at as TIMESTAMPTZ. TIMESTAMPTZ columns read as one canonical ISO text (UTC, +00:00), and the version check (expect_updated_at) compares both sides canonically, so it works alike for TEXT and TIMESTAMPTZ tables; restoring from the trash, the agents' proposal "stale" flag and the account import handle TIMESTAMPTZ columns too.
### Fixed
- #4859: Split view: "Open on the right" while the right half is still starting no longer leaves it empty.
- #4523: docs/SELF-HOSTING.md names everything lost with the server key because it hangs on the account keys (private files, journal, privately filed mails, household budget, private knowledge pages, values of a person's own documents) and that organisations and private offices come back with their recovery key; the overview table is "the main parts".

Package 2.752 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Changed
- Files: files and documents are one area "Files" with one folder tree in the sidebar - the second tree under "Documents" (the same folders again) is gone. Below the tree: "All documents", "To review" (with its counter) and the saved views, then "Shared with me" and the trash. A folder with recognition shows the documents' view: their bar (search, filter, sort, card size, Add documents and Scan into this folder), its subfolders as cards first, then its own documents and its other files; a search or a filter there takes the subfolders along. Every other folder keeps its list. On phones the bar on top has the spaces plus "All documents" / "To review"; the switch Files | Documents is gone (#4887)
- Files: one address for everything: #ablage/docs, #ablage/review, #ablage/v/<id> and #ablage/<id> (a folder, or a file in the document view). The old links #docs, #docs/review, #docs/v/<id> and #docs/<id> lead there for good; reload and the browser's Back keep working. A document opened by a link closes into the list it leafs through, a plain file into its folder. /api/v1/docs and /api/docs are unchanged, so are the rights (a reader sees no writing buttons) (#4887)

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

[Unreleased]: https://github.com/Gegenschuss/kalmido/compare/v2.787.0...HEAD
[2.787.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.787.0
[2.786.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.786.0
[2.782.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.782.0
[2.774.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.774.0
[2.771.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.771.0
[2.766.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.766.0
[2.762.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.762.0
[2.761.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.761.0
[2.759.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.759.0
[2.756.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.756.0
[2.749.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.749.0
[2.740.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.740.0
[2.734.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.734.0
[2.731.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.731.0
[2.719.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.719.0
[2.710.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.710.0
