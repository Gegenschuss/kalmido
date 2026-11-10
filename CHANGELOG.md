# Changelog

All notable changes to Kalmido are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Kalmido uses
[semantic versioning](https://semver.org/): every published change gets at least a new patch version, new features a
minor one. Releases in which operators have to do something carry a fixed section "Action needed"; the update notice
in Settings > Help shows that section of the target version.

## Older versions

- [2.700-2.799](docs/changelog/2.700-2.799.md)
- [2.600-2.699](docs/changelog/2.600-2.699.md)
- [2.500-2.599](docs/changelog/2.500-2.599.md)
- [2.400-2.499](docs/changelog/2.400-2.499.md)
- [2.300-2.399](docs/changelog/2.300-2.399.md)
- [2.200-2.299](docs/changelog/2.200-2.299.md)
- [2.100-2.199](docs/changelog/2.100-2.199.md)
- [2.0-2.99](docs/changelog/2.0-2.99.md)
- [1.x](docs/changelog/1.x.md)

## [2.870.0] - 2026-11-10

Package 2.805 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Changed
- Settings: on a computer the dialog opens again at the width its content needs (the tabs and one form column, about 57.5rem), also on wide monitors - the 96rem of #4554 are gone; the content goes along with any width (#5357)

### Added
- Dialogs: a size grip on the right edge and in the bottom right corner of Settings, Edit contact, a mail of the hub, Video review and Set up an agent - drag it to make the dialog wider (the corner also taller), the content goes along; each dialog keeps its size per device, double click (or Enter on the grip) brings back the default size, arrow keys resize, never smaller than the default and at most the window minus 4rem; mouse only, phones and touch keep the sheet without a grip (#5357)

Package 2.836 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Changed
- Documents: the archive number field and "Next free number" show only for a document that already has a number or is a scan (came through a scan inbox, a picture, or a PDF whose pages are page-filling pictures with at most an invisible OCR layer). Digital PDFs and e-invoices no longer show the field; "Assign archive number" is in every document's Actions menu. Documents from before get the scan mark from the background catch-up (#5390).

Package 2.854 (Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Spaltenbreite ziehen in großen Listen ruckelt noch, Sammelpaket: Aufgaben ohn).

### Changed
- Agent chat on a phone: the live interim status under "… is writing" wraps to up to 3 lines instead of being cut to one line; a tap on a cut status shows the whole text, a second tap closes it again. The block keeps its height while the agent works, so the messages above do not jump with every new status; wide screens stay as before (#5508).
- Tools: the lint step `tools/check_lazy_calls.py` scans identifiers instead of one huge alternation and checks a local shadowing once per file and name - same output, about 3.5 s instead of 90-230 s (#5492).

### Fixed
- Bank bookings: a long press (phone) or right click (computer) on an open booking opens its "More" menu, like the other rows with "…"; the suite p2695_a_rowmenu_coverage is green again (#5354).

### Fixed
- main: splitting a stack in the document view keeps its "Split into N documents" message with Undo - a list of flow runs asked just before the split no longer answers afterwards with a "Not found" message in its place (#4887, CI red of 2.833.0, p2154_a_ui); the "Suggest title" button is no "automatic" mark for p2555_a_formnarrow_ui (#4882); the subscribed-calendar mark uses the icon size token (#5468, p2419_scale); every test selection of a changed stylesheet now takes the scale guard p2419_scale along, so a size off the scale is caught before the CI (#5530).
- main: the list "Recent steps" shows a task change of this browser once - its copy on the server no longer stands beside it, so "Back up to here" takes every change back exactly once (#5251, CI red of 2.848.0, undo_ui).

## [2.858.0] - 2026-11-10

Package 2.826 (Bündel: Agent-Status: „nicht verbunden“ nur bei echter Stö, Agent-Chat: Pläne (Morgen-Briefing usw.) im ⋯-Menü, Sammelpaket: Aufgaben ohne P).

### Added
- Agent chat: the "…" menu of the chat header has "Plans" (the same dialog as the card's "Plans" button). The Plans dialog has "Pause all" / "Resume all" on top: all of your own plans with this agent in one step, with undo; other people's plans stay as they are, plans waiting for a project of your own keep waiting, missed runs are not made up. New route `PATCH /api/agents/<id>/schedules` `{enabled, ids?}` (#5510).
- Private AI on the Kalmido server: each starter routine with its own plan (briefing, tidy up the inbox, follow-ups, billing) has an On / Paused switch instead of the plain "On" text; a paused plan stays and can be switched on again. `GET /api/agents/<id>/server/starter` carries the plan ids (#5510).

### Changed
- Agent status: "not connected" only for a real problem - the agent never got in touch, or a chat message to it has waited more than 5 minutes without being fetched or answered. An agent that starts on demand (cloud or server agent) and answered its last message shows "ready" with a calm ring and the hint "starts with the next message" (chat header, agent list, sidebar dots); "connected, but no service running" only while a message waits. The agent payload carries `pending_age` (#5509).

### Fixed
- Tests: p263_c_api keeps its time entries on one day around midnight UTC, p2120_a_ui leaves the app before the second sign-in; both run again in CI (#5507, #5505). setup_ui waits for the login form instead of a fixed 1.5 s and, like p2467_c_ui, logs the screen when it fails (#5504, #5506; both stay skipped until the cause is proven).

Package 2.809 (Neubau von 2.790: iPhone-Tableiste, Papierkorb Stufe 3).
### Added
- Recent steps across devices for more areas: custom fields, sections, sprints, project settings, templates, rules, time entries, budget entries, sidebar folders, bookmarks, followed feeds, scheduling polls, appointment types, team absences, dispatch bookings, a project's environments and the pin board's notepads are steps of the person's undo list on the server - taken back from any device (#5476)
### Changed
- iPhone home-screen app: the empty strip below the tab bar labels is about halved (one value, --tabs-pb, 11 instead of 22 px on a 34 px home indicator area); everything above the bar moves along. Desktop and Android unchanged (#5437)
- Files, knowledge pages (with their files) and tables use the one trash of the shared core: delete, restore, delete for good and the hourly retention run go through it; their own purge runs are gone. Receipts kept by law stay locked in the trash (#5365)
- Bank list in the office: a calmer row - the suggestion, one "Other receipt/invoice" button and a More menu with explained marks; the missing-receipt hint once above the list (#5452)
- Office kinds on the core check that the office is on and allowed (also in a support session); undoing a DATEV import puts its suppliers away the core's way (#5418)
### Fixed
- iPhone home-screen app: headers (lists, agent chat, team chat rooms) looked blurred and dimmed under the clock - iOS blurs the top edge unless the header is a full-width sticky box; on phones they are now sticky at the top (#5437)

Package 2.849.0 (Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Fixed
- Documents: right after "Split" a late step of the browser history could land on the split stack's address again; the app fetched the gone stack and its "Not found" message took the place of the split's message with Undo. A document split in this window now leaves its address quietly, the Undo stays (CI red p2154_a_ui in 2.786.0 and 2.833.0; regression step in the suite) (#5478).

Package 2.846 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- Shared core: one filter building block (#5520) - `static/js/fltkern.js` (matching), `static/js/fltdlg.js` (`kflt_rows` condition rows, `kflt_dialog` saved-filter dialog) and `kalmido/core/filters.py` (`kflt_where` / `kflt_match`) with a field catalog per area; task lists and newsletter segments now use only it, behaviour and stored data unchanged. `docs/dev/kern.md` has a new section "Filter".
- Core guard (#5522): `tools/check_core_crosscut.py` turns red on new share tables (name ending in `_shares`, or a user/org/group/agent column plus a role/perm column) and on new rights checks (`def need_*`, `*_role`, `*_can`) outside `kalmido/core/`; existing ones are listed with a reason in `tools/core_crosscut_allow.json`.
### Changed
- Calendar event editor (#5465): Esc, X, Cancel or a click next to the dialog ask before typed input is lost; the all-day switch keeps your own reminders; "More options" is a visible fold with a city search for the time zone; "Only you so far" is the placeholder of the people field; the hint for guests outside Kalmido is in everyday words; a new event without other people shows no availability bar; the repeat end is labelled "Repeat ends"; existing events focus the title only with a mouse.

## [2.848.0] - 2026-11-10

Package 2.823 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Added
- My tasks > "…" > Rules…: every person sets up to 20 own rules for their own view of My tasks. A rule only moves a task into one of the person's own sections, at the top or the end - the task, its project and the project's order never change. Triggers: some days before the due date, due today, due today or overdue, overdue, newly assigned to me, the priority becomes high, from a project, gets a project tag; optional "Only if" (priority, project, project tag). Each rule moves a task once per occasion (a due day, the priority becoming high, ...): what the person moves by hand afterwards stays where it was put. The topmost rule that applies wins (arrow up in the list). Switch, edit, delete with Undo; agents neither read nor propose these rules (#4773).

### Changed
- My tasks: "due today or overdue -> Now" is no longer fixed in the app but the person's first own rule (switch it off or delete it in Rules…; a deleted one does not come back). Tasks put into a section by hand before stay there (#4773).
- The Undo of a deleted own section points the rules of that section at it again (#4773).

Package 2.832.0 (Bündel: CI-only rot: p2599_b_kopf_ui (Wiederholung: Fix #5, CI-only rot: p2462_c_ui (Wiederholung: Fix #5301 h, CI-only rot: p2586_a_dragper).
### Fixed
- Calendar: Enter in the question for a repeating event no longer picks "Only this date"; the inserted button is a plain button with its own submit, the highlighted "All dates" stays the form's default (#5480)
- CI red p2599_b_kopf_ui: the suite follows #5309 again - start and list report the page width "seite" (#top on the content's edges), Wide of a note is 96rem; a later test fix had expected the state without #5309 (#5514)
- CI red p2462_c_ui: the test scrolls up with the wheel like a person, which ends the 2 s "stay at the newest message" phase of a room just opened; on the slower CI runner that phase put the box back to the end (#5515)
- CI red p2586_a_dragperf_ui: the bar watchers are checked one by one (fewer runs than steps, at most every 200 ms) instead of their sum against the steps (#5516)

## [2.833.0] - 2026-11-10

Package 2.783 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Spaltenbreite ziehen in großen).

### Added
- Documents: a title pattern per workspace in Settings > Documents (default "{Sender} {Type} {Date}", date as DD.MM.YYYY, empty parts drop out with their separator) and a switch "Title automatically" (on by default). Recognition, rules, "Apply learned" and "Recognise again" set the title from it as long as nobody set it by hand; a title set by hand (person or agent) is never replaced, existing documents are not rewritten. The document sheet has "Suggest title" next to the title (with undo), the selection bar "Set title from pattern" under "Edit". New read endpoint `GET /api/docs/<id>/title-suggest`; `doc_json` carries `title_manual` (#4882).

### Changed
- Trash core stage 6: incoming webhooks, deleted team chat messages, member memos, deleted list fields, "Delete all times" copies and section / sprint copies are cleaned up by the core's one trash run after their retention period; the areas' own clean-up paths are gone. Deleted fields and time copies now live as copies in the core's side-object trash (old rows move over at start); restoring a field also brings back "required" and its organisation field (#5368).

### Fixed
- Knowledge on a computer: folder, workspace start, tag, search hits and "All workspaces" use the full width under the toolbar instead of a narrow column in the middle (#5375).
- Knowledge page on a computer: header, search and bar stay where the list has them (no jump when a page opens), the editor card uses the full width and ends at the window edge - the text scrolls inside, "Attach files" and the footer stay visible; only the text column follows the width switch (#5376).
- Files: in folders with recognition the toolbar stays on one line at 320 px - "New folder" and "Share" show only their icon on narrow screens (#5356).

Package 2.794 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Added
- Settings > Modules > Office & finance (parts of the area Office): a switch "Also private" for people in an organisation. Off, the workspace Private shows no office (no entry in the sidebar, no page, not under "All workspaces"), contacts and clients stay; the offices of the organisations stay as they are. The server answers requests to the private office with a clear hint where to switch it on, and the bell items of the private office (payments, overdue invoices) are hidden meanwhile. Nothing is deleted: switched on again, the private office is there with the same data. Stored like a private module card (ws_mods_off), the default stays on (#5392).

Package 2.800 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Sammelpaket: Aufgaben ).

### Added
- Undo across devices, stage 5 rest (#5409): deleting rows and columns, column settings, moving and sorting, the chart, colour rules, cell names, frozen values, rows kept in view and the sheets of the bar are steps of Recent steps; a change someone else made since stays and is named, the rest goes back. Taking a table's project back needs the same rights as changing it.
- Removing a calendar subscription can be undone from its toast for 15 minutes (#5466).

### Changed
- Calendar (#5466): the "only this / all events" question is a normal dialog, "All events" in warning colour when deleting; a single event or one date of a series is deleted without asking and the toast offers Undo; deleting a calendar shows Undo; the custom repeat says "Apply"; the share dialog has the close button.
- Calendar (#5468): dated tasks follow the chosen workspace like the events; events of subscribed calendars carry a subscription mark.
- Calendar wording (#5467): "Termin" throughout, "Abonnierte Kalender" and "Kalender-Link", roles "kann ansehen" / "kann bearbeiten", "belegt", no ICS / iCal in everyday texts.
- Lists wording (#5441): the sidebar group says "Projekte", the section-less group "Ohne Abschnitt", the board's lanes "Gruppieren nach", taking a task "Selbst übernehmen"; a board card reads "seit 2 Std."; one tone for empty hints; shared word list docs/dev/glossar.md.
- Tables (#5283, stage Q7c): the cell history follows the logs' retention switch (daily clean-up, index); sheet_changes stays (agents' trail and target of the people's table steps), reason in docs/dev/kern.md.

### Fixed
- The event window no longer reaches below the window's edge: it is placed again once its details are loaded, scrolls itself when needed and keeps Edit / Accept / Decline in sight; Delete comes last; "Hide on Today" moved to the calendars window (#5460).
- Undoing a move out of a locked list no longer fails for tasks with subtasks, comments or text fields: that part is kept and named, the other fields go back (#5447).

Package 2.821 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Fixed
- #5501: CI red p2466_b_api - the suite follows the decided change of #5378 (a team agent is listed for every member of its organisation, reached only through a project opened to her).

## [2.819.0] - 2026-11-10

Package 2.784 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Added
- Office: a complete business year 2025 of a fictitious "Muster GmbH" (SKR03, accrual accounting) as a hard check suite: the journal, account balances, P&L, balance sheet and the quarterly VAT returns are compared to the cent with expected values computed by hand, with the gaps Kalmido does not cover named explicitly; a demo loader plays the same data into a test instance and refuses live addresses (#5387)
- Office: a guard suite for the office head at 320/460/840 px - the sub area bar and buttons like Apply never overlap (#5402)

### Changed
- Office: suppliers go into the core's one trash - deleting and restoring them is a step of Recent steps, the core's retention run clears them after the trash period (#5366, first kind of the office)

### Fixed
- Office: a reminder fee marked as paid takes the day the money came (optional day) instead of always today, so a fee paid in December counts in December; a paid day in a locked month can no longer be moved or opened again (#5387)
- Trash: the retention run checks a row again under its lock, so a restore in the same moment is never lost (#5366)

Package 2.757 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Added
- Folders now also hand their default view, columns, custom fields and project tags to the projects inside them; repeat reminder, hours per day, hourly rate and the progress bar can be set once per folder (folder settings). A project that differs from its folder shows it and goes back with "Back to the folder" (#4501).
- docs/GLOSSAR.md explains every Python module, every script under static/js and the common function prefixes; linked from CONTRIBUTING.md, a lint guard (tools/check_glossar.py) asks for a line for every new module (#5295).

### Fixed
- Lists and the start page report their width to the header again: the top bar lines up with the content instead of standing 4 px beside it, and the width "Wide" of a note / knowledge page keeps its list + note layout (CI red p2599_b_kopf_ui, #5309).
- p151_ui says why the hint of the task just tracked is missing (toast, totals on the page and on the server); the Mac red was the sub-second discard fixed in #5186 (#5211).

[Unreleased]: https://github.com/Gegenschuss/kalmido/compare/v2.870.0...HEAD
[2.870.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.870.0
[2.858.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.858.0
[2.848.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.848.0
[2.833.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.833.0
[2.819.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.819.0
