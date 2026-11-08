# Changelog

All notable changes to Kalmido are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Kalmido uses
[semantic versioning](https://semver.org/): every published change gets at least a new patch version, new features a
minor one. Releases in which operators have to do something carry a fixed section "Action needed"; the update notice
in Settings > Help shows that section of the target version.

## Older versions

- [2.500-2.599](docs/changelog/2.500-2.599.md)
- [2.400-2.499](docs/changelog/2.400-2.499.md)
- [2.300-2.399](docs/changelog/2.300-2.399.md)
- [2.200-2.299](docs/changelog/2.200-2.299.md)
- [2.100-2.199](docs/changelog/2.100-2.199.md)
- [2.0-2.99](docs/changelog/2.0-2.99.md)
- [1.x](docs/changelog/1.x.md)

## [2.693.0] - 2026-11-08

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

## [2.682.0] - 2026-11-08

Package 2.670 Part A (rescue): test diagnostics for two CI-only red suites.
### Changed
- Tests p2589_c_ui and p2239_b_logs: a failure now names the state of the page / the log lines involved, to find the cause of their CI-only red runs (#5009, #4897)

Package 2.677 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Changed
- The single "reduce motion" exception for the phone drawer's area names (start-sbfit-5103.css) is gone; since #5115 the general rule no longer animates sizes, so the drawer fit stays calm without it (#5126).

Package 2.662 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Security
- Tasks, comments, events and contacts carry the organisation of their list / task / calendar / address book (org_id, filled and carried along by database triggers, also for writes of the previous version); row-level security now guards these four tables as a second floor under the app's own visibility check (#4602).

### Changed
- Approval: an image or PDF uploaded through the approval follows the approval's rights (task / project / client), so project colleagues and agents of the shared project see it and its bytes; the file itself stays private in the file store, and a file chosen from the file store still needs the file right (#5041).
- Backups: the names of backups on a former off-site target expire after the longest set retention plus 30 days, so they no longer hold back the deletion journal forever; the backup page says how many former backups still hold the journal and until when (#4587).

### Fixed
- Encryption in the background: the way back (decrypt-all / decrypt-private) counts budget rows and knowledge-base texts it could not write as failed instead of leaving them sealed silently; opening private document previews runs in portions with the file check; new private previews stay plain while private encryption is off (#4939).

Package 2.682 (Bündel: Kommentare: Schalter 'Mit Aktivität' auch in nicht, Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Changed
- Comments of a task in a list that is not shared: as soon as changes of others show between the comments (agents, automations, changes via API / CalDAV / webhook), the "…" menu of the comments has "With activity" too; off shows only the comments and the head says "Comments only". The same per-device setting as in shared lists (#5155).

Package 2.666 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Added
- Bookkeeping: double-entry bookkeeping for companies that must draw up a balance sheet (GmbH, UG). Settings > Bank & tax: choose "income statement (EÜR)" (default, unchanged) or "balance sheet" (suggested for GmbH/UG/HRB), size small or micro. The journal is worked out from the existing documents (invoices, receipts, bank, cash book, depreciation) in SKR03 or SKR04 from the DATEV settings; trial balance, profit and loss account and balance sheet (HGB small / micro) with CSV export; entries by hand (adjustments, opening balances) and the year-end closing, which writes the opening entries of the next year and locks the year. Bookkeeping > Balance sheet (#3461).
- Contacts: the contact card is built from blocks like the client card - each person can show / hide, fold and order the blocks ("Customise the contact card"), kept per person and the same for all contacts (#3624).

### Security
- Approvals: the customer link of a disabled account answers like an unknown link (page, comments, decision) (#5112).
- Hardening from the security audit (#4074): unlocking a locked folder runs the plain files through the upload checks (virus scan, type sniff, photo data); IMAP without UIDPLUS no longer expunges other mails marked deleted; the organisation import's undo keeps time entries billed on a remaining invoice; without PUBLIC_URL the receipt fetcher's and scan inbox's setup codes and the hosted MCP metadata answer 503 instead of using the request's Host header; signature links work at most 90 days after they were made; ending the own session and a 401 for an ended session clear the browser's HTTP cache (Clear-Site-Data); trh()/trnh() escape inserted values; a revoked file or folder share drops the knowledge offline copy at the next sync; the card statement PDF is served sandboxed; foreign ICC colour profiles reach littlecms only when they are well-formed and at most 1 MB; the Peppol status fetch and lookup need the release right; office routes check rights before answering 404 for a switched-off function; a receipt-mail body that is no object is 400.

Package 2.680 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Fixed
- Tables: a chart saved while the table was still loading no longer jumps back to the older chart; a load answer older than the table on screen is dropped (#5138).
- Tests: knowledge pages and list channel messages in the end-to-end encryption suites are created as version 2, as the server demands since #5044; each suite checks that a new version 1 item is refused (#5145, #5146, #5147).
- Tests: headless Firefox reports no hover and no pointer, so the app ran in finger mode there since #5082/#5085; six UI suites start Firefox as a mouse, new suite p2680_c_pointer_ui checks the pointer setting (#5139, #5140, #5141, #5142, #5143, #5144).

## [2.681.0] - 2026-11-08

Package 2.657 (Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), CI-only rot: p2551_c_favout_ui, Teil 1/6: Sammelpaket: Aufgaben ohne Paket (D).

### Changed
- Agents must send the version (`expect_updated_at` or `If-Match`) when they change the settings of a calendar, an address book or a project (name, colour, columns, KPIs, workspace); without it the answer is 400 `version_required`, with an old one 409 with the current state. The MCP tools `update_event_calendar`, `update_address_book`, `update_list` and `set_list_columns` carry the field; agents read the version with the object first (#5052).
- Calendar: renaming, recolouring or moving a calendar sends its version; a change someone else made meanwhile shows the conflict message instead of being overwritten (#5052).
- Projects: the project settings get a version (new column `lists.updated_at`); a person who sends an old version gets the conflict message, people without a version keep working as before (#5052).
- Documents > move receipts into the office: the preview reads the reasons a document stays (locked month, taken over by the accountant, cash book, equipment, booked, recognition running) for the whole list at once; the full move check runs only when moving (#4644).
- Saved document views are always created private; sharing them with an organisation goes through Share (#4828).

### Fixed
- Organisation import: values of "Link to documents" fields point to the imported documents instead of being skipped; links to Paperless or to documents that did not come along drop out and are counted in the import report (#5018).
- Calendar: deleting an event, the booking page's cancel, reopening a poll, undoing agent proposals and the hub dispo now run under the event's lock, so two changes at the same moment cannot overwrite each other (#5052).
- Taking a shared object back from an organisation checks its shares before leaving the organisation and records the person who did it (#4828).

Package 2.660 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Changed
- Modules and style sheets loaded on demand ask with their content hash instead of the app version, so a new version only reloads what really changed (the service worker keeps unchanged ones); the idle chain no longer preloads Settings with its dependencies, and in data saver / 2G it preloads nothing; every language part has a version of its own, a new text reloads only its part, and the language core is no longer rewritten to local storage on every start (#4197).
- Test tooling: jsdom 30 on Node 24 (#3799).

### Fixed
- Phone drawer at 320 px with "reduce motion": area names no longer swing between two sizes and wrap ("Rückblick"); the fit no longer measures during a size transition, and a column that needs more room grows only by its text, so 11 areas fit in two rows at 320 px without scrolling (#5103).
- Renaming a wiki folder with many pages takes all page locks in one database statement again instead of one per page (#5104).
- Chat: arrow keys in a closed reaction row skip the hidden reactions instead of getting stuck (#3799).
- Phone opened directly on an agent chat: the row of open chats from last time is kept instead of being overwritten at start (#3799).
- Deleting an open table: Undo restores it instead of saying "Changed elsewhere, not undone" (#3799).

Package 2.673 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Changed
- Calendar sync (CalDAV): a calendar query with a time range renders only the events in that range when the calendar is not cached yet, instead of every event of the calendar (#5124).
- Contact sync (CardDAV): a contact photo above about 70 KB goes into the vCard at most 512 px on its longest edge as JPEG; the smaller copy is kept in memory. A card a phone writes back with that copy keeps the stored full picture; file exports still carry the full photo. All synced address books and calendars load once again after the update (#5124).

### Fixed
- Document notes: an index on the author column, so removing a person no longer scans all document notes (#5130).
- Tests: the pin board notepad test waits until the new notepad's field has focus before it types and leaves (red only on slow CI runners) (#5129).

Package 2.670 (Bündel: Bündel: Teil 1/6: Sammelpaket: Aufgaben ohne Paket (Dispatcher), CI-only rot: p2191_c_perf, CI-only rot: p2290_c_fold_ui u. 1 weiter).
### Added
- Every area's short introduction now has 5-8 steps that point at the real controls (create, views and filters, folders and sharing, search, links to projects and tasks, the phone gesture, where the settings are), with own targets on the phone; Notes and Chat get an introduction of their own (#4576)
### Changed
- A new agent setup code, and redeeming one, answers 503 with a clear text when PUBLIC_URL is not set on the server, instead of putting http://localhost into the agent's settings (#5127)
### Fixed
- First-run setup: the project type Social media plan no longer shows up as a sixth "Start with" card (#5120)
- Chat: opening the reply bar keeps a chat that was at its end at its end, so the reply scrolls into view instead of showing the "new messages" pill (#4898)
- Lint check_dataattr: an attribute selector is no longer counted as a second meaning of the attribute (#4576)

## [2.675.0] - 2026-11-08

Package 2.665 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Changed
- Calendar and contact sync (CalDAV / CardDAV): the change state of a list, calendar or address book (getctag, sync-token) comes from one database query over its own rows instead of rendering every object; the rendered collections are kept per person and collection instead of being dropped by any change anywhere in the instance. A change in one list no longer re-renders all others (#4196).
- Background work: notification channels are served in turns, and after a failed send the rest of that channel waits for the next run, so one dead channel no longer holds up the others; the issue sync sends to GitHub / GitLab with no open database transaction, keeps errors as the link's state, and a comment whose answer was not stored is looked up instead of posted twice (#5113).

### Fixed
- Reduce motion: with the system setting "reduce motion" only visual properties (opacity, transform, colours) keep their very short transition; sizes and positions change at once, so headings and area names that fit their text measure the new size and no longer flicker or loop (#5115).
- Tests: CI-only failures of p2390_b_api (new section field), p2425_b_ui (date-dependent hint text) and p4434_a_umzug (race with the background cleanup) (#5109, #5110, #5111).

Package 2.663 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Changed
- Large stored files (from 4 MiB) are sealed in 1 MiB chunks (format KENC2, a key per file derived from the space key, chunk index and end mark bound in each chunk): downloads stream, and a range request (videos, large PDFs) decrypts only the chunks it needs instead of the whole file. Files in the older format stay as they are and keep opening; `KALMIDO_SEAL_CHUNKS=0` and `orgcrypt_cli files-to-v1` are the way back before a downgrade (docs/SELF-HOSTING.md) (#4191)
- Sealed files in the older format from 10 MB on count against a RAM budget per process (`KALMIDO_SEAL_RAM_MB`, default 256; `KALMIDO_SEAL_RAM_WAIT`): a signed-in person waits briefly for room, a public link and a third waiting request get 503 with Retry-After at once (#4191)
- The offline start state lives in IndexedDB and is written when the browser is idle (no longer a large JSON in localStorage on the main thread); the old copy is taken over once, a refused write falls back to localStorage and is reported (#4200)
- An open table asks with its etag first and loads and redraws the sheet only when it changed (#4200)
### Fixed
- Tests: 40 status checks that accepted success and refusal alike now expect the one right answer; the eleven remaining importers are checked by behaviour for the target workspace question (#4341)

Package 2.653 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Added
- Agents: `POST /api/v1/agent/decisions {title, ref?}` and the MCP tool `log_decision` write a line "Decided: <title>" into the agent's own history for decisions outside the Kalmido API (a job card answered itself, a tool change on its server, something deliberately not started); no undo, 30 per minute (#5079).
- Agents: Settings > Agents > Work style > History shows the newest five lines and "Show whole history" with paging (`GET /api/agents/<id>/control/history`); the history keeps 500 lines per agent (#5079).
- Developers: the finger switch `isTouchUi()` (coarse pointer or no hover) for operation, `isMobile()` only for layout by width; the lint rule `tools/check_touch_switch.py` (run by check_layout) is red on new width checks next to focus, drag, gestures or shortcut hints (#5087).
- Settings > Help > About shows one line about this device: window size, pixel ratio, pointer, hover, phone layout and finger operation (#5087).

### Changed
- Agent history lines read in plain words with the task title and the changed fields ("Priority changed: <title>") instead of method and path; similar steps of an agent within five minutes in one project form one expandable line ("12 tasks changed in Releases"), each step keeps its own undo (#5079).

## [2.668.0] - 2026-11-08

Package 2.655 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), CI-only rot: p2551_c_favout_ui).

### Changed
- Tablets with touch (over 767 px): swiping sideways in a task's details (and in a news task) goes to the next / previous task, like on a phone (#5080).
- Tablets with touch: a wiki page opens for reading with the pen to switch to writing, like on a phone; a page just created still opens for writing (#5082).
- Tablets with touch: "Edit menu" shows the hide buttons, the column arrow in a list header is always visible, and sidebar menu points have "Hide from menu / Customise" on a long press (#5083).
- Touch screens without a mouse no longer show keyboard hints (the "Keyboard shortcuts" button and text in Settings > Help, shortcut chips in menus, "(Alt+←)" on Back); gesture hints in the timeline and the start page editor say "hold, then drag" on touch. The shortcuts keep working with a keyboard (#5084).
- Touch screens: date picker, "Waiting on", milestone and other dialogs no longer focus a text field on opening (no screen keyboard covering the calendar or buttons); the date field uses the number pad on every touch screen; Search does not take the focus back after every update; "+" on a section opens the quick sheet (#5081).
- Touch screens: rows, calendar events and favourite tiles are no longer browser-draggable (a long press in Chrome no longer cancels the app's hold, selection or finger drag); the edge drawer while dragging a task and the swipe-to-complete animation work on tablets too (#5085).
- Keyboard: the remaining global Escape listeners (tooltip, drags, timeline connect mode, link preview, document preview, favourites bar, chat) and the letter keys n / q / m / a / / run through the shared key registry; the shortcut help reads the letters from there. n and / no longer act behind an open dialog (#4998).

### Fixed
- A server answer that arrives after the app's window was closed no longer draws into a page without a document (late test errors in p2170_ui); test runs print 8 stack lines for such late errors and count them (#5045).

Package 2.652 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Dokumente Handy/Tablet: Wischen auf der Vorschau i).

### Changed
- Documents and images: a swipe sideways leafs to the next / previous document in the full screen of a document and to the next / previous picture in the image viewer, on phones and touch tablets alike (shared helper `static/js/swipenav.js`, loaded on demand); a PDF opened from a file store folder leafs through the folder's PDFs and pictures (#5071, #5073)
- Sheets (dialogs, menus, date picker, quick add) are dragged, resized and swiped away only at their grip / head; a swipe in the content always scrolls (#5078)
- Touch screens wider than a phone get the finger sizes, visible row actions and the long-press guard of the phone (touch rules follow the pointer, not only the width) (#5086)
- New knowledge pages and new list channel messages in an end-to-end locked space are taken as v2 ciphers only (v1 is refused with 400); editing, re-encryption and reading still take v1 (#5044)

### Fixed
- Android / Chrome: Back closes one level at a time (full view -> document -> list) instead of leaving the app on the second Back; closing a document with its arrow leaves no dead Back behind (#5070)
- Documents on phones and touch tablets: the open document covers the whole screen; pulling down or scrolling on the preview no longer shrinks it to half a window with the list showing below; the preview no longer jumps when the sharp page replaces the small picture (#5072)
- Sheets: a dialog scrolled down no longer jumps back to the top when the finger lifts (#5078)
- Calendar / address book: sharing again with someone whose share had run out lets them in again; a still valid end date stays; the organisation boundary check counts a private address book's contact person only while its share is live (#5089)

Package 2.387 (Social-Media-Planer (ohne Veröffentlichen)).
### Added
- Project type "Social media plan" in New project (card with the megaphone icon): opens in the calendar view, field Channel (several values: Instagram, LinkedIn, Facebook, TikTok, YouTube, Newsletter, Other), with the standard sections Idea, Draft, For approval, Approved, Scheduled, Published; with them the review step is on for "For approval" and a post is completed only after the approval (the client as reviewer, e.g. with the role View). A post = a task: text = description, picture = attachment, publishing day = due date. Kalmido publishes nothing itself (#1957)
- API v1 / MCP: `project_type: social` (#1957)

Package 2.658 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: CI-only rot: p2399_hosting_apart, CI-only rot: p2441_favs_ui, CI-only rot: p2).

### Added
- Approvals: an audio file from the file store can be a version of an approval and plays like an audio link (built-in player, comments at a second, versions, customer link); the file's own access applies, the customer link plays it only while the link is open (#5015).

### Changed
- Sheets: sorting rows or columns keeps formula ranges on their positions (=SUM(A1:A3) stays A1:A3); single references still follow their cell, dragging rows keeps its own rule (#5000).
- Approval files (images, PDF, audio) are typed from their first bytes and streamed with range requests instead of being read whole into memory (#5043).
- Background work: reminder and nag runs read only the columns and due days they need; a webhook that fails waits for the next run with the rest of its deliveries, and deliveries are taken in turns over all webhooks; the git poll holds no database transaction while the provider answers; an agent event wakes only that agent's waiting long-polls (#4193).
- Release cleanup (prune-releases): the untagged platform images of a removed release go with it, unless a kept release still names them; dry run stays the default (#5042).

### Fixed
- Undo: a finished write on bookmarks, read later, pipeline, travel, logbook, books and receipts no longer comes back with an older app state after an undo (#5092).
- Document flows: "X days after it came in" also picks up documents added between midnight and 1 am local time (#5099).
- MCP: list_views, create_view, set_section_kind and set_task_state are in the tickets toolset (#5095).
- Tests: CI-only failures of p2554_c_wikicm_ui, p2633_d_audiorev_ui and p220_api (waiting on a real state) and a migration lint note (#5091, #5102, #5101).

### Security
- The approval customer page's audio route: limited per address and per link, a sealed file is decrypted once per request, files of a disabled account's link are not served, a UTF-16 text is not taken for MP3 (#5015).

Package 2.654 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Teil 1/6: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Bündel: Samm).

### Fixed
- Receipts sorted into documents under "All workspaces" land in the office area that is open (header X-Kalmido-Office-Space now also on /api/docs); without an open area, and in the background queue, the setting decides as before (#4823).
- Project core share rows mirror list_members on every way (organisation join, owner transfer, agent share proposals, making an agent, child participant); restoring a share from the file store or a group grants the role at once; an own share that ran out ends at once instead of after the next watchdog tick (#5050).
- Organisation export and import keep the links between tasks and quotation positions (task_offer_links, origin_id on the new ids): after a move the positions are no longer offered as new and one click no longer doubles the tasks (#4585).

### Security
- An API token limited to certain projects no longer finds channel or group messages in the message search, and sees no knowledge pages (wiki pages belong to no project); session logins and unlimited tokens are unchanged (#5053).

## [2.659.0] - 2026-11-08

Package 2.635 (Bündel: CI-only rot: p2399_hosting_apart, CI-only rot: p2441_favs_ui, CI-only rot: p2476_b_appcss u. 6 weitere).

### Added
- Documents: Word and Excel files (.docx, .xlsx) and OpenDocument text / spreadsheets (.odt, .ods) get their text recognised (searchable, date / amount, rules and sorter apply) and a preview image; older formats (.doc, .xls, .ppt, .pptx, .rtf) stay files without text, with a hint in the document view. Existing ones follow with "Recognise again" (#4807).
- Documents: notes on a document - several notes with author and time, visible to everyone who sees the document, written with edit rights, sealed with the workspace key and searchable; the Paperless import brings notes as notes; agents read them with the document (#4807).
- Settings > Documents: the text recognition languages of the workspace can be chosen from the installed ones (default German + English, at most 4, KALMIDO_OCR_LANGS stays the upper limit) (#4807).
- Documents: custom field types "Long text" and "Link to documents" (only documents of the same workspace the person sees; a click opens it); the Paperless import maps both (#4807).
- Settings > Documents: every document flow has an edit button that opens the same form filled in; saving checks the version (conflict message when someone else changed it meanwhile), the on/off switch too (#4856).
- Document flows: new action "Share" - shares the document with people or groups through the shared approvals core, only with targets the person who set it up may share with (checked again on every run); undo takes these shares back. The Paperless import maps owner / permissions of its workflows onto it (#4856).

### Fixed
- Phone scan: pages are opened only as JPEG, PNG, WEBP or HEIF; other image formats (e.g. EPS, TIFF) get "not a picture" (#4645).
- CI: p2399_hosting_apart, p2485_a_support, p2538_a_support followed the e-mail invitation rule of #3570 (people get connected first); p2476_b_appcss places its probe scripts around dropany.js; p2441_favs_ui waits until the favourites row stopped sliding in (#5004, #5005, #5006, #5007, #5008).

Package 2.651 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), CI-only rot: p2559_d_budget_ui, CI-only rot: p2107_ui u. 7 weitere).

### Fixed
- Mailbox: IMAP folder names with umlauts (e.g. "Entwürfe") are sent in modified UTF-7 (RFC 3501), so rules and fetching work on such folders (#5033)
- Undo: an older app state no longer brings back a finished step on feeds, meals and budget data ("Mark all read" undo, a duplicated meal's provisional row); a budget reload keeps the own amount still being saved (#5064, #5076, #5025)
- Drawer: an area name that grows after the fonts load is fitted again, no word split at 320 px (#5063)
- Windows starter: pausing an agent ends its process tree on Windows PowerShell 5.1 too (#5038)
- Browser demo: Settings > Ticket types and Office > Receipts answer in the demo (#5037)
- CSS: the 767px breakpoint of the phone chat moved out of the rem-checked agentchat.css blocks; .amv-row on the 1 px grid (#5026, #5031)
- CI: stable tests for the long-poll wake-up of a second process, the demo print view, the Windows launcher stub, the drawer search and the phone chat composer (#5077, #5036, #5032, #5027, #5075)

Package 2.641 (Bündel: CI-only rot: p23674_a_office, Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- #4769: Approvals take images (JPG, PNG, WebP) and PDFs from the file store or as an upload, next to video links. Comments sit at a numbered point in the image or on a PDF page; tapping a comment's number jumps to its point. A new file is a new version, older versions keep their comments; states as for videos. Who may not see the file does not see the approval. The agent API shows kind, position and point number and reads the file at /api/v1/videos/{id}/versions/{v}/file.
### Changed
- #5011: GitHub release pages come once per ISO week (Sunday, weekly-release.yml): the newest checked version of the week, on its vX.Y.Z tag, with the notes and "Action needed" of every version of that week; the image :latest moves with it. Every version still gets its image :X.Y.Z. prune-releases.yml (dry run by default) thins out old release pages and image versions - the newest of each week, the last 14 days and the current latest stay; git tags are never touched.
### Fixed
- #5012: Overdue invoices and the "invoice series need you" task are told once when two runs meet (test p23674_a_office, red only in the CI).
- #4974: Agent change proposals: a user_id of a person the agent does not see answers like a proposal without user_id (card to the owner), so it no longer tells who has write access; at most 20 proposals per day for one person.
- #4979: Tests ux1_ui, p2170_ui and p270_ui wait for the page's state instead of fixed pauses; the eight suites changed in 2.624 are proven green on the test runner.

## [2.656.0] - 2026-11-08

Package 2.647 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Fixed
- Calendars and address books: a share taken back in the file store's share dialog (or one that expired) now really ends the person's access everywhere - reminders, the heir on account deletion, news, the agent workspace check, client contact links and the organisation export / import no longer read the old member row (#5046)
- Tables and knowledge pages: an organisation import binds every share card to its core share, so ending a share in the table's dialog or in the file store's dialog ends it in both; undoing a table's move between workspaces gives the people back their access; a share card without a core share no longer grants access (#5047)
### Security
- Share revocation: no second, unconnected right on calendars, address books, tables and knowledge pages after a revocation, an expiry or an organisation import (#5046, #5047)

Package 2.577 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Added
- Software tickets: a column can carry a status meaning (open, in progress, review, done, rejected); dragging a task into "done" completes it, into "rejected" marks it won't do, out of them reopens it; the meaning is in API, MCP, filters and the new webhook task.status_changed; review takes the column with the meaning review first (#3354).
- Software tickets: shared views per project - a saved filter can be hung on a project and shared; everyone who reads the project sees it, editors change it; GET /api/v1/tasks?filter_id=, /api/v1/lists/{id}/views, MCP list_views / create_view (#3356).
- Documents: several named mail addresses per area (personal files, an organisation's office) in Settings > Integrations > Documents: inboxes > By e-mail, each with a name, a fixed target folder and fixed tags, switchable on/off, renewable (the old address stops working) and deletable; the existing address stays as "General" (#4466).
- Office under "All workspaces": tapping an area in the overview opens it at its own address (#office/s/<area>) instead of switching the workspace; Back returns to the overview (#4638).

### Changed
- Event calendar links are stored only as a hash and shown once, like task feeds; existing plain links are hashed at start and keep working (#4708).
- Dialogs keep their input over a reload, an ended session or a closed tab (#4708).
- File versions: the app's version routes accept expect_version and answer 409 with the current file when someone else saved a newer version; agents must send it (#4708).
- The wiki history marks versions written by agents; a letter's change goes into the office log with its diff (#4708).
- The token / agent dialog says that a project limit (list_ids) covers projects and their tasks only (#4708).

### Fixed
- Contacts are deleted for good only by the address book's owner (#4708).
- Wiki folder move / rename, contact group changes, online payment / Peppol setup and new list fields lock before they read, so parallel changes are not lost (#4708).
- A waiting wiki text of a locked space is sealed again with the current key generation before it is sent (#4708).
- "Stop reminding" from a push sends the previous state, a conflict opens the app (#4708).
- Office undo/redo of a client leaves the invoicing fields as they are when the person may not change them any more (#3964).

Package 2.649 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), CI-only rot: p274_b_demo, CI-only rot: p287b_a_freelancer_api u. 1 weitere).
### Changed
- Leaving an organisation, a demotion that takes the right away, and retiring now revoke the person's public file links and file requests (restorable like shares, listed in the revocation register); coming back no longer reopens them by itself. Restoring needs the creator to still share or write in the folder, else 409 (#5051)
- An agent that moves to another workspace loses its shares in the old organisation through the revocation register; moving back opens nothing; withdrawing an invitation and the nightly boundary repair go through the register too (rows restorable, card and legacy rows cleaned on both sides) (#5051)
- Docs: docs/dev/kern.md states how a folder share and the office groups work together (decision #2742) (#5048)
### Fixed
- Public file links no longer show, download, preview or zip receipts their creator may not see in the app (#5049)
- Phone: tapping in a scrolled bottom sheet no longer jumps it to the top and hits another row (CI red p2150_ui, #5062)
- Browser demo: answers the ticket-types request at start (CI red p274_b_demo, #5039)
- Tests: p287b_a_freelancer_api expects 404 for mailbox rules without an own mailbox (CI red, #5061)
- semgrep check: an exception entry whose code line still stands is no longer reported as "without a finding" in the partial run (#5056)

## [2.650.0] - 2026-11-07

Package 2.547 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- Office > Receipts: a one-time hint "N receipts are still in your documents" opens a preview of the old receipts of the personal documents (move / stays per row; tag Tax and uncertain ones preset to stays). Only the click moves them, in groups; one undo for the whole move for 30 days (folders, names, ended shares come back). No automatic move at the update (#4434)
### Changed
- Save as view: the section Projects lists only the folders (folded, one tick per folder, half-set when mixed), single projects after unfolding, a search field above the list; every group except Plan starts folded (#4484)
- Team chat: live updates (new message, reaction, edit) change only the changed messages instead of rebuilding the list - no flashing, avatars stay (#4500)
### Fixed
- Notification channels: the hint shows only the host or the Telegram chat ID, no longer the last four characters of the webhook URL, bot token or number; existing hints are rewritten at start (#4516)
- Documents reading view: pulling the grip back right after dragging it fully to the right no longer lands on a width in between (#4492)
- Imports: a failing database look at the import queue counts as busy instead of ended, so a running import is never offered a second start or a clean-up (#4295); new tests for the import edges (undo in a locked month, numbering after import, foreign ids in a forged organisation archive, a cancelled import leaves nothing)

Package 2.640 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Security
- End-to-end encryption: locked knowledge pages and list channel messages are bound to their record (AAD v2 with the page id and path/body field, or room, generation, sender and message id); a server can no longer pass one page's or message's ciphertext off as another's. The browser reserves the id first (signed, short-lived reservation: `POST /api/wiki/e2e/newid`, `POST /api/team/rooms/<rid>/msgid`), writes only v2 (new, edit, switching the lock on, re-encryption after a key change, moving between spaces) and reads v1 only when the ciphertext itself says v1, so there is no downgrade; old v1 records stay readable (#3388).
### Changed
- Performance: the team chat marker of the 4-second poll comes from counters per room kept by a database trigger instead of counting all messages; deleting and restoring a message now moves it too (#4183).
- Performance: the start state reads budgets, clients and formula field names in set queries, checks recurring copies only for done tasks, sums the storage in one statement with indexes on the uploader and computes the storage badge at most once a minute per person (own uploads and deletions show at once) (#4185).
### Fixed
- Tests: p265_b_ui waits for every module it checks (#5065); p2623_d_abnahme expects the renamed refusal "Approvals are switched off" (#5016); p2574_b_wkcm_ui no longer races CodeMirror's own late scroll and waits for the drawn screen instead of a fixed 10 s, a red check prints where screen and decorations stood (#5019).

## [2.648.0] - 2026-11-07

Package 2.644 (Bündel: CI-only rot: p2137_c_api, CI-only rot: p23674_b_org, CI-only rot: p2538_c_buero u. 3 weitere).
### Added
- Agents read the sales pipeline, add inquiries and deals and set a deal's stage: API v1 `GET/POST /office/deals`, `PATCH /office/deals/{id}` (stage only, needs `expect_updated_at`, 409 on a newer version; leads stay with people), MCP `list_office_deals`, `create_office_deal`, `set_office_deal_stage`; scope `office` and the same switches as leads, only for office admins, every call in the office log (#3663)
- Log clean-up: time indexes on list_activity, fs_log, org_list_log and sheet_changes (#4192)
### Changed
- Log clean-up deletes in committed batches of 5,000 rows instead of one statement under the 30 s limit; a table that fails sends an admin alert (kind storage) instead of only a log line (#4192)
- Backups: a store clean-up now answers with its own code `store_busy` and its own text instead of "Another backup or restore is running"; verifying takes the read lock only for own format-3 backups (#4530)
### Fixed
- Backups: downloading a format-3 backup takes the read lock before the one-time confirmation is used, so a clean-up starting in between no longer eats the confirmation; verifying with a typed passphrase counts failed attempts like restoring (#4530)
- Deleting an account: agent shares on folders handed on to the heir end unless the agent belongs to the heir's space, like on a move; the delete dialog counts them as ending (#4999)
- Account import: the importer locks the imported projects until it commits, so the share watchdog no longer removes a project's own member share in between (CI red p2137_c_api, #5024)
- Tests: p2579_d_revoke counts a share the watchdog already ended as ended (CI red p2579_d_revoke, #5030); p23674_b_org and p2538_c_buero check the current wording after #3894 (CI red, #5028, #5029)

## [2.646.0] - 2026-11-07

Package 2.599 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), CI-only rot: p271_ui, Teil 1/6: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Added
- Knowledge pages and notes: a page width switch in the page menu (… > Page width): Read (default), Wide or Full, for this page (kept on the device) or as the default for knowledge pages / notes (kept with the account's appearance); in Read, code blocks and tables may reach the edge of the sheet and scroll sideways instead of being cut (#4808).
- Frontend: one delay helper `debounce(fn, ms)` with `flush()`, `cancel()` and `pending()` in core.js; `tools/perf_budget.py` counts hand-made `clearTimeout(` delays in static/js and that count may only go down (#4506).

### Changed
- Wide screens (from 1700 px): the top bar (page title, search, buttons) stands in the same middle and width as the page below it; the agenda bar, the team chat room head and the bars above a letter and the rights page share the edges of their content. Full-width pages, 1440 x 900, tablets and phones stay as they were (#4814).
- Wide screens (from 1700 px): a knowledge page or a note lies as a sheet (own surface, fine border, rounded corners) with its header, path and toolbar flush with the reading column; the knowledge bar (search, new page, today, new folder) and the notes list with the note form one centred block. The Notepad reading style keeps its own frame (#4808).

### Fixed
- Settings no longer break with "xl_stdHtml before initialization" when the file store module failed to run while loading: a module file that throws while it runs now fails its module (and asks for a reload) instead of counting as loaded, and the sharing defaults are drawn only once their module has loaded (#4907).

## [2.645.0] - 2026-11-07

Package 2.638 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), CI-only rot: p2551_c_favout_ui, Teil 1/6: Sammelpaket: Aufgaben ohne Paket (Dispatche).
### Added
- Server agents: when the first key is stored for an agent without a limit, the dialog proposes a daily limit of 2 million tokens (visible, editable, empty = no limit) and stores it with the key; an agent with a key but no limit shows a hint (#4714)
- Tests: a table test of the public-link switch for every kind (link opens, kind off = old link closed and no new one, kind on = open again) and a lint that every public_links_on() names a known kind (#4294)
### Changed
- API v1 `PATCH /comments/{id}` and `/team/messages/{id}` take `expect_updated_at` (or If-Match) and answer 409 on a newer version; agents must send it (400 `version_required`), MCP `update_comment` / `edit_team_message` pass it on; the template dialog sends the version it opened and reloads on 409 (#4775)
- Tests: the tenant guard counts a route as proven only with the same method on the test line and a 403/404 check within three lines (or a `# tenant: METHOD /path` marker), no more proof from comment blocks; the legacy list grows once from 882 to 1429 and must not grow again (#4641)
- Base image digests and lock files refreshed (#5010)
### Fixed
- Undo after dragging a favourite list out on a touch screen works again: the tap on Undo was swallowed by the drag guard, and star requests now run one after another (CI red p2551_c_favout_ui, #5013)
- Answering a calendar invitation (app, API, CalDAV) takes the event's lock, so a parallel edit of the attendees no longer overwrites the answer (#4780)
- Mailbox: IMAP folder names always go out quoted, so names like `{5}` or with `%` / `*` no longer break the own mailbox connection (#4852)
- A portal form while public links of the kind portal are off makes a plain report without a status link that would not open (#4294)
- p2619_b_starter checks the rules block for the current wording **read-only** (#5014)

Package 2.633 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Angebots-Pipeline: Karte mit dem Finger in eine an, Bündel: Releases für Selbst-Hoste).

### Added
- #4777: video sign-off takes audio too: a direct https link to MP3, M4A/AAC, WAV, OGG/Opus or FLAC plays in the browser's own player; comments sit at a timecode as with video (tap pauses and takes the time, tap the time to jump), a simple timeline with marks, versions and the customer link as with video. Nothing is downloaded or stored by Kalmido.
- #4781: list rules have two new actions, "Mark it as done" and "Open it again"; done goes the way of the tick (next repetition, dependants freed, notifications, history names the rule), a task done by a rule triggers no further rule. Agent API / MCP rule schema list both.
- #4963 #4964 #4965: with the finger (hold, drag, let go): a receipt onto a booking in Bank > Without receipt, an office document onto a folder of the side panel, a quotation pipeline card into another column - the same action as the mouse's drop.

### Changed
- #4920: buttons that opened a file picker made on the click (bank import, meals, travel import, agreements, contacts import, profile / agent picture, project and organisation icon, file store "New version", wiki attachments and import, mindmap / sheet import, …) now have a fixed hidden file field, so a file dropped onto the window lands there too.

### Fixed
- #4994: iPhone home-screen app: the tab bar keeps only part of the home indicator room (no wide empty band below the labels), the list ends right above the "+" button, the office import foot no longer adds the bottom room twice; the status bar is translucent and nothing glows behind the clock (the workspace stripe of the header and of the drawer and the loading bar sit below it; black behind the white clock in light designs); the area below the bar has the bar's colour.
- #4964: holding a document row with the finger no longer opens its menu while the drag starts; let go without moving opens the menu once.
- #4779: a token limited to lists no longer sees team channels (names, member ids) in the channel list (app and API v1) and cannot rename, archive or change members of a channel by its id.

Package 2.624 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Added
- Calendar > Tasks > "Per project": lists grouped by folder like the sidebar, one switch per folder (hides all lists in it and its subfolders, also later ones; their own switches show "hidden by folder"), a search field from 8 lists on; new user setting `cal_folders_hidden` (#3946)
- Agent API: every item of `GET /api/v1/agent/queue` carries `size` and `points` (S=1, M=2, L=3, none = 2); `?points=N` marks the next bundle (`bundle: true` + `bundle {points, sum, count}`); MCP `get_queue` takes `points` (#4521)

### Changed
- `kalmido/__init__.py` ORDER has a sorted block at its end for modules without an order need, checked by `tools/check_layout.py` (fewer merge conflicts) (#3941)
- More UI suites wait for a real state instead of fixed sleeps (#3943)

### Fixed
- TRANSLATING.md: the first day of the week follows the locale or the setting, not always Monday (#4522)

## [2.643.0] - 2026-11-07

Package 2.631 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- Tables: rows and columns move by dragging their head (row number, column letter) - with the mouse at once, with a finger after a long press on the head (the row / column follows the finger, the table scrolls at the edge); the head menu also has "Move up / down / left / right"; several marked rows or columns move together, every move is one Undo step, other editors see the new order live, readers cannot move, a filtered view says to reset the filters instead. Formula ranges keep their rows and columns when one of them is moved; new route `POST /api/sheets/<id>/columns/order` next to `rows/order` (#4620).
- Delete account: the dialog names for every folder handed on to an heir what stays behind and goes with the account (locked folders, shortcuts, agent folders, trash, mail copies), how many public links and file requests end, and how many agents of other people keep their share in it (#4584).
### Fixed
- Phone: a sheet dragged up at its grip grows at most to the height of its content (at most 94 % of the screen) instead of leaving an empty area below it; snapping to "full" uses the same height, the bell's own grip and a stored bell height follow the same rule (#4993).
- Delete account: mail copies that go with the account are no longer sealed again for the heir only to be deleted right after (#4584).

Package 2.595 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Teil 1/6: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Changed
- #4905: The release gate also accepts a green full CI run of a commit with the same files (same git tree, push / schedule / dispatch runs of the own repository only); release.yml can be started again by hand on a release tag.
### Fixed
- #4881: "Move to ..." no longer lists folders that are in the trash, or below a folder in the trash; the server refuses a move into such a folder.
- #4906: Letters: "Send by e-mail" right after typing the e-mail address saves the letter first, the recipient is filled in.
- #4903: Credit card import: the conversion fee line ("2,5% für Währungsumrechnung" and its other names) is its own fee position, so the sum fits the statement; an unknown line with an amount of its own under a position is kept instead of dropped (footer lines stay out); the rate after the foreign amount is no longer part of the merchant name.
- #4896: Command palette (Mod+K): parts that arrive after opening (shared tables, document facets, folders) are found when typing.
- #4900 #4902 #4911: tests p2579_c_ui, p287b_b_ui and p287b_a_freelancer_api follow the app again (wait for the applied view, palette set reset, own objects for new GET routes).

Package 2.630 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- Statistics: three new blocks Contracts (running contracts, cost per month / year, notice periods in the next 90 days, per provider), Health (per person: appointments, check-ups and vaccinations of the last 12 weeks, next due, overdue; medication intakes counted apart) and Travel (trips and travel days in the last 12 months and this year, travel costs, next trip), each only with its module on; `GET /api/v1/stats` and the MCP tool `get_stats` give agents the same numbers, health only with the scope private (#4617).
- Command line `mcp/kalmido_cli.py` for scripts: `list`, `show`, `add`, `comment`, `done` over the REST API with `KALMIDO_URL` / `KALMIDO_TOKEN`, `--json` on every command, part of the starter files (#4520).
- Image build: `tools/pins.py --wheels` checks the libraries inside the Pillow wheel (libjpeg-turbo, zlib-ng, libtiff, libwebp, freetype, openjpeg, lcms2) against minimum versions and stops the build when one is older (#4671).
### Changed
- Keyboard: one key registry (`static/js/keys.js`) with a stack of open things; Escape closes only the innermost open dialog, menu or sheet, the most recently opened first; the shortcut help also lists the keys registered there (#4510).
- Hints that name a settings path, e.g. "(Settings > Modules)", are now a link that opens the settings at that section (#4519).
- Contacts: the contact form shows names and phone / e-mail / addresses side by side on wide monitors (#4695).
- vCard import takes files up to 50 MB (was 20 MB) (#4593).
### Fixed
- CI red p2391_k_ui: the text key "Scan inbox" is the scan inbox, not an old name of the basket (#4992).

## [2.639.0] - 2026-11-07

Package 2.385 (Film: document samples).
### Added
- #2293 Document templates: three film samples for the industry Film & Video - filming permission, location agreement and model release (German and English, signable, marked as legal texts to check before use). Find them in the office document templates under "Use sample"; only listed while the industry Film & Video is on.

Package 2.609 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Teil 1/6: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- Own ticket types per organisation (private: per person): Settings > Data > Ticket types - name, symbol, colour, a note template; Bug / Feature / Task stay the fixed base types, Epic and Story come along (an epic shows the progress of its subtasks); a project chooses which types it offers in "Types and templates…"; quick add `!epic` / `!<own type>`, type filter and chip; API v1 `/ticket-types`, `/lists/{id}/ticket-types`, MCP `list_ticket_types` (read only) (#3372)
- The organisation's field schema, required fields, labels and templates: projects take over fields of the organisation's schema (linked, changed together), a field can be required per ticket type (checked on create in the app, API v1 and MCP), organisation labels for organisation projects (personal tags stay private), organisation templates with trash; v1 filter `fkey_<key>` across projects (#3373)
- CI: the Windows launcher (mcp/agent_launcher.ps1) runs for real on windows-latest when something under mcp/ changed (also nightly / by hand) against a stub server with a stand-in for claude - event, answer, run time limit, pause, runner lock, hard stop; the event runner ends on Windows too when its launcher was killed hard (launcher_gone) (#3660)
### Changed
- The lists an area keeps its entries in (Read later, contracts, home & devices, health, household budget, trips) are no projects any more: not in the sidebar, the archived view, "Move to project", list pickers, quick add, the palette, filters and project overviews; #l/<id> of such a list opens its area (a trip stays its trip view); the buttons "Show as project" and "Reading list" are gone (#4613)
- Read later no longer counts in the statistics (done per day / week, on time, by project, streaks), the day / week review and the start page's done tiles; the other areas still count (#4613)
- The sidebar is drawn anew only when what it shows changed: scroll position, focus and hover stay, a changed open view only moves the marks (#4509)
- Tests: the suites' state files (ids.json, cal_ids.json, news_ids.json) live in the test data folder, the own user id is looked up instead of /api/users/1 (#4512)
### Fixed
- Renaming a big knowledge folder writes its pages' renames into the history in a few statements instead of three to four per page (CI red p2280_c_api, #4928)
- p248_d_ui: a regression test for the document sheet opened while receipts.js still loads (the cause was fixed on main in #4912), failed phone checks print the page's history, dialogs and failed requests; the sync chip no longer touches a closed window (CI red p248_d_ui, #4929)

## [2.634.0] - 2026-11-07

Package 2.622 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Added
- #4514: the update hint for admins (admin settings, Server > Updates) shows the "Action needed" section of the target release as plain text ("To do before the update"), so manual steps for operators are visible before updating.

### Changed
- #3891: short-lived state that broke with several web processes now lives in the database (table eph_state: sign-in steps for 2FA, passkeys and TOTP setup, OIDC states, ZIP download tickets, calendar undo; keys only as HMAC, content sealed, taken once) or goes over pg_notify (agents' long-polls, instance switches, typing / presence / editing markers, queue wake-ups). Without KALMIDO_REPLICAS > 1, KALMIDO_PGBUS=1 or a web/worker role nothing changes; KALMIDO_WEB_PROCS itself follows later.
- #3894: English wording, the rest of #2991 (637 texts): "take over" by meaning (Apply / Import / Add / Use; taking over a project stays), "take back" -> Undo, "for good" -> permanently, "Switch on/off", "Read-only", "Select", "Reject", "Go to sign-in", "Other people" and the examples unified; where two old keys meet, the existing translation is kept; glossary in TRANSLATING.md and tools/i18n_check.py.

### Fixed
- #4946: phone: the header and the input line of the agent / job chat now reach the screen edges; the messages keep their padding, the desktop is unchanged.
- #4948: phone: after opening a task from "Waiting for me" (and writing a comment), one system Back closes the task at the same list position, the next Back goes to the view before.

### Fixed
- main: CI red of 2.632.0 - p23674_a_office: the overdue run of the test sets the due dates of its invoices in one step, so the server's own watchdog tick in between no longer splits them into two items (#2972).

Package 2.634 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), CI-only rot: p2579_c_ui, CI-only rot: p2430_c_ui u. 1 weitere).

### Added
- #4774: rules: the dialog for a new rule shows "Templates" on top - one click fills in when / then (done -> column Done, reopened -> In progress, new -> assign to me, enters Review -> assign a person, due today -> priority high, gets tag Urgent -> priority high; "enters Done -> mark as done" as soon as that action exists). Columns and tags are proposed by name; a missing one stays "Select ..." and must be chosen before saving. Sorted by project type (software, agency). Saving creates a normal rule.

### Changed
- #4797: project board (mouse, desktop / tablet): while dragging a card, a dashed placeholder shows where it will land and the neighbouring cards slide aside smoothly (off with reduced motion). Dropping into the free part of a column with cards puts the card at the end of that column.

### Fixed
- #4997: browser demo: "all modules" in the intro also switches on Approval (videos) - the demo takes its module lists from the server (CI red p2125_d_demo).
- #4996: test p2430_c_ui reports the notepad's state when a save is missing (diagnostics for a rare CI red; no app change).

Package 2.628 (Bündel: CI-only rot: p2350_a_api, CI-only rot: p2521_e_dbmem, CI-only rot: p253_a_ui u. 3 weitere).
### Changed
- Test selection: a test file can say `stages-covers: PATH` (globs allowed) for a client file no suite names; `tests/stages.py --touched` then takes that suite on top of the fixed set, first user the calendar UI suite for the recurrence helper (#4580).
### Fixed
- Bank fetch over FinTS: the period From / To uses the app's own date fields instead of the browser's native date inputs (#4986).
- CI red suites since 2.621: the reply test expects the full fenced quote the agent runner loads since #3757 (#4982); the split load test starts its stack with a cover page so the docs queue does not split the clear stack itself first (#4983); the office cold start test checks the files of the module office, the FinTS dialog is its own on-demand module (#4984); the push tag test row is sent now instead of 1970, the dismiss sweep no longer removes it (#4985).

Package 2.627 (Bündel: Rot auf main allein: p2361_a_texts, Rot auf main allein: p2554_a_docside_ui, Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- Views: organisation admins save the standard arrangement of Start, Today, Time tracking, Overviews and Review for their organisation ("Use as standard for <organisation>" in the organisation's workspace); order: own arrangement > organisation standard > instance standard, "Reset to standard" goes to the organisation's; `PUT /api/layouts/std/<key>` takes an optional `org_id` (members 403, other organisations 404), agents read the same order (#4504)
- Time tracking: the tracked time stands next to the task's duration (the estimate), e.g. "1:30 h / 2:00 h", in the time chip of the row, the column "Tracked time" and the task panel; the window "Tracked time" warns from 80 % of the budget like the head bar (#4503)
- Touch: a file row of the file storage can be held and dragged onto a folder or the path with a finger (#4961); the icons of the area rail can be sorted with a finger (#4962)
### Changed
- The finger drags of the sidebar's list rows, the areas' tree and the favourite tiles run on the shared drag code (edge scroll, Esc, a second finger cancels); the tree now scrolls at the edge while dragging (#4966)
### Fixed
- People list: a member sees per person only the organisations they share with them, no longer the ids of all organisations of that person (#4526)
- Tests: p2361_a_texts follows the removed clients text (#4980), p2554_a_docside_ui builds a stack that waits for a person since the auto split (#4981), p2579_c_ui and p2574_b_wkcm_ui wait for the end state instead of in-between states and are out of the skip list (#4976, #4977)

## [2.632.0] - 2026-11-07

Not released (the CI of this version was red); its changes are listed under 2.634.0.

## [2.629.0] - 2026-11-07

Package 2.591 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Teil 1/6: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Rot auf main allein: p2450_x).
### Added
- Files can be dragged onto the window wherever a view or an open dialog has an upload button (receipts, credit card statements, letterhead, imports ...): one button makes the whole window a drop area, several buttons make each row one; type and count rules of the button apply, areas with their own drop keep it, touch devices are unchanged (#4894).
- A scan inbox (Settings > Integrations) can be edited afterwards with the pencil next to the trash: name, target folder and "extend by one year"; the key and the folder watcher stay the same, the area (private / organisation) does not change (route `PATCH /api/docs/scan-keys/<id>`) (#4886).
- Credit cards: Visa and American Express as providers (same line reader, an agent or entering by hand as before when nothing is read) (#4909); a hint at the statement upload and in the card dialog says which statements are read (providers and size limit from the server) (#4904).
### Changed
- Accounting and receipts: "Take photo of receipt" only on touch devices; on a desktop "Upload files" is the main button (#4892).
- Office lists: rows that open a view or a form end in the arrow to the right, only rows that unfold in place keep the arrow down (#4908).
- Cash flow: when a month has a bank balance, the by-hand real balance is folded behind "Enter the balance by hand"; a value set by hand keeps it open; "Use as real balance" only for a balance of the month's last day (#4889).
### Fixed
- Archive numbers: codes are read on every page (up to the OCR page limit, a finer second try when none is found), a QR code of digits only ("00143") counts, and a number already taken shows a hint with the document that holds it instead of being skipped silently (#4863).
- The fill handle of tables keeps the decimal sign of the source cell instead of a fixed comma (#4871).

Package 2.623 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Teil 1/6: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- Agents can propose a change to a shared core object instead of writing it: a proposal of kind obj_patch shows the old and new values on a card; a person with write access accepts it (written with the agent's version, 409 when someone changed it meanwhile) or rejects it; MCP tool propose_object_change (#4718)
- Settings > Modules: new module "Approval" (the former video sign-off); off = no new approvals in tasks, project overview, client card and API (409), existing ones stay readable and restorable from the trash (#4765)
- Touch: a sheet tab and a group header in My tasks (by project) can be held and dragged with a finger; a coverage test makes every mouse drag place in static/js need a finger way through drag.js or a listed reason (#4621)
### Changed
- The video sign-off is called "Approval" (de "Abnahme") and shows in agency projects and projects without a type, not in software or private projects - also in the project overview; data and API stay videos (#4765)
### Fixed
- Taking a share back in the file store's dialog on a table or knowledge page now ends its share card (revoked_at) and keeps the row in obj_revoked, so an older version cannot reopen it (#4778)
- Tests: seven test files ended with a bare done() and never turned red; run_all.sh counts an "N failed" summary as red and a lint rejects a bare done() (#4950)

Package 2.593.0 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), GitHub-Umbau Schritt 3: CI für die Merge-Queue vor).

### Added
- Settings > Account: "Reset settings…" shows a preview of the look and comfort settings that differ from the default (look, density, sidebar, start view, view options, notifications, modules, saved filters, workspace colours), resets them on the server and on this device, and offers one undo; account, sign-in, language and organisation / office settings stay; push channel and "title only" stay; agents and API tokens cannot call it (#4590)
- Travel expenses: the per diem rates abroad of 2023 and 2024 (BMF letters of 23.11.2022 and 21.11.2023), so trips of these years are calculated; 2022 and earlier still show the note (#4893)
- CI: the merge_group trigger (merge queue entries run the push stage against the queue's base, the release commit the full run) and the job "Pull request lint" (tools/pr_lint.py: task number in every commit subject, changelog part of an app change, privacy guard with the patterns from the repository secrets, one-way steps as warnings; the script runs from the base commit) (#4006)

### Changed
- Office year pickers (travel expenses, entertainment receipts, logbook, cash book, bookkeeping, VAT return, tax forms) list the years with data: from the oldest year up to this year without gaps, later years only with data in them; without data only this year (bookkeeping: also last year); the mileage allowance keeps next year for a rate in advance (#4891)

### Fixed
- Undoing an account import keeps documents that were imported as finalised, with their client, positions, payments, log, PDF / XML and the office's number counters; the undo preview names them under "stays" (#4864)

### Security
- Invitations no longer tell whether an address has an account: in a company someone created themselves, an account the inviting admin may not see gets a silent invitation (same answer and list row, no message, cannot be accepted); locked accounts and agents likewise; the daily invitation limit counts before the address lookup; the list shows every address in small letters with a reference of one length, an organisation admin's invitation mail goes through the background queue; a resend turns a silent invitation into an ordinary one once the admin may see the person; back to an older version: delete the silent invitations first (kalmido/core/migrations.d/3570_a.py) (#3570)

## [2.626.0] - 2026-11-07

### Fixed - main: pg_prepare knows that the second preview column of the documents comes with a later version (CI red of 2.614.0)
### Fixed - My tasks: a section opened again no longer folds back when another section is deleted at the same moment (CI red of 2.614.0, p2569_a_mine_sections_ui)
### Fixed - main: p290_a_ui and p2555_b_bizsettings_ui follow the year comparison (#4921) and the income statement's basis (#4927), scroll_ui runs at a fixed test time (midnight edge) (CI red of 2.614.0)
### Fixed - Notes: the search field in the panel keeps the focus when the page is drawn again while typing; p2350_c_pins_race_ui follows the own changes kept since 2.607.0 (CI red of 2.618.0)

Package 2.581 (Bündel: Teil 1/6: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- Documents: the document rules become flows - trigger "received" (as before), "changed" (tags / type / sender / a field set) or scheduled (X days after the document date, due date or arrival, once per document and day); filters by source (upload, mail, mailbox, scan, fetcher, import), file name, content (any / all / exact / regex / fuzzy), tags, type, sender; actions set / remove tags, type, sender, folder, a custom field, create a task, notify people (News, own switch), webhook (only allowed targets like the other webhooks, signed with an own secret shown once). Every run is in the document's history with undo; a flow never triggers another one. Existing rules keep working as "received" flows. Paperless-ngx workflows (API and export ZIP) become flows where the fields match, the rest is listed with the reason (#4803).
- Documents from the own mailbox of a workspace: mail rules per mailbox (IMAP folder, sender, subject, has attachment, age) take attachments and / or the mail itself (.eml) as documents into a folder with tags and the mail's sender; afterwards mark read, flag or move the mail (delete only with its own switch, off by default). Runs with the mailbox poll every 10 minutes and with "Fetch documents now"; every mail only once (Message-ID). Same intake as the document address (duplicates, ZIP / winmail, invoice links) (#4804).
- Backups: "Check passphrase" next to the passphrase field - an admin types a passphrase and only learns whether it matches the stored one (or KALMIDO_BACKUP_PASSPHRASE); step-up, 5 tries per 15 minutes, constant-time compare, admin log entry without the value (#4826).
- Cash flow > fixed costs: a pencil on every category heading renames the category for all its fixed costs in one step; an existing name merges both (asked first); one undo for the whole step (#4820).
### Fixed
- Fixed cost import: a colon (and spaces) at the end of a category or group line is dropped, "Digital Abos:" becomes "Digital Abos"; the same for categories typed by hand (#4820).
- Organisation export / import keeps the core's nodes of calendars, address books, projects and team chat channels with their shares and history (#4811).

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

[Unreleased]: https://github.com/Gegenschuss/kalmido/compare/v2.693.0...HEAD
[2.693.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.693.0
[2.682.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.682.0
[2.681.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.681.0
[2.675.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.675.0
[2.668.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.668.0
[2.659.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.659.0
[2.656.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.656.0
[2.650.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.650.0
[2.648.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.648.0
[2.646.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.646.0
[2.645.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.645.0
[2.643.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.643.0
[2.639.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.639.0
[2.634.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.634.0
[2.632.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.632.0
[2.629.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.629.0
[2.626.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.626.0
[2.621.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.621.0
[2.618.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.618.0
[2.614.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.614.0
[2.605.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.605.0
[2.601.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.601.0
