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

## [2.1086.0] - 2026-11-13

Package 2.1078 (Bündel: Bündel: PDF-Vorschau: Grund und Leiste an die Design-Farbe, Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Fixed
- Agent approvals, hosted MCP: a refused step (`step_ref`) and the approved card of `use_approval` now belong to the access of the connection, not to one access token or one `/mcp` request: they survive a token refresh and the next request, and end with the access; a step whose body is longer than a card binds (32,000 characters) gets no `step_ref` and says so (#5866).
- Agent approvals: the refusal of an upload (multipart with files) sends the agent the header way (`X-Kalmido-Approval`, MCP `use_approval`) with `error.run: "header"` instead of the card run, which cannot send files (#5866).
- Agent approvals: a card step path that still holds a `%` after decoding is refused with 400 (the run decoded it a second time) (#5866).
- Agent data lock: read as system, so a request outside the agent's organisation gets the agent's real lock instead of the open defaults (#5866).

Package 2.1084 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Fixed
- Upgrade test (p2192_c_upgrade): the "migrations ran" check no longer demands a log line when the jump brings only new tables; it now matches the logged step count to the MIGRATIONS steps recorded at this start (the upgrade probe from live v2.1067.0 was a false alarm) (#5916)

Package 2.1081 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Changed
- Agent chat and team chat use the full width from 768 px (open Fold, tablet, computer): header, switch row and composer reach both edges of the view next to the lists, the messages stay in a reading column in the middle; the team chat without conversations no longer shrinks to its content (#5903).
- Menus glide: on a computer a menu unfolds under its button (a little from above with fading in, 0.15 s) and goes back the same way, on a phone the menu sheet slides up from the bottom in 0.2 s and down again; with "reduce motion" a menu only fades in. Only the menu moves (#5901).
- Knowledge: a folder that has a page of the same name (page "A" with subpages "A/…", e.g. from a SilverBullet import) shows once in the folder list and in the panel, as the folder row with a small page mark; opening it shows the page's text on top ("Edit" opens the page) and the subfolders and subpages below. The narrow view's tree, search and [[A]] links still open the page (#5907).

Package 2.1085 (Bündel: Agenten-Freigaben: Upload-Karte bindet auch den Da).
### Security
- Agent approvals: an approval card for an upload now binds the files too - `approval.body._files` lists form field, name and SHA-256 of each file (a form field named `_files` is refused); after the Yes only exactly these files go through with `X-Kalmido-Approval` (other content: `409 approval_invalid`, reason `body`, field `_files`), and a run from the card answers reason `upload` (#5936).

Package 2.1079 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Sammelpaket: Aufgaben ).

### Fixed
- Search: hits changed in the same second keep one fixed order (newest first) on every answer, so the results no longer reshuffle under the reader when a hit is edited (#5655).
- Start-up: applying the row-level security policies next to a running server locks all tables in one step and gives way instead of dying in a deadlock (#5654).
- MCP: `wiki_append` belongs to the toolset `wiki`; with `--toolsets` / `KALMIDO_TOOLSETS` it no longer leaked into every other toolset (#5095).
- Row-level security list: the dropped office trash table is marked as dropped at start-up; two system contexts carry their reason (#5683).
- Tests follow the bell of #5806 (a person's comment on my own task waits for me): p262_b_api, p21037_b_bell_ui, p21052_news_one_ui, p2170_ui, p2102_b_ui and the other News suites (#5912 #5905 #5906 #5477 #5904 #5911 #4737).
- Test stability: p2220_b_focus_ui, p2115_b_api, p2905_b_docview, p2924_c_ruhe_ui, p265_b_ui, p2353_e_setsearch_guard (#5423 #5640 #5642 #5655 #5913 #5910).

### Fixed
- main: backups made against PostgreSQL 17.12 or newer with an older `pg_dump` were refused at check and restore as "unexpected objects" - the column version key `pg_attver` of PostgreSQL 17.12, written out by an older `pg_dump`, is now accepted in exactly that form (the server drops it); every other column option stays refused (CI red of 2.1077.0, #3506).

Package 2.1086 (Bündel: Agenten: „Zeig mir“ - der Agent öffnet die passend, Hilfe in der App: je Bereich „So geht's“ auf Deuts).
### Added
- #5820 Help in the app, stage 1: "How to" sections in plain words for files / documents (incl. setting up a scan inbox), agents, office (quotations, invoices), tasks and calendar - the same text agents read through `search_help` / `read_help` (they now get the user's sections first, with the translation). The English text lives in the docs (`<!-- user-help: area -->`), translations in `docs/help/<lang>.md` with a fingerprint of the English text. The app shows them under "Help": the command search (entry "Help" plus one entry per topic, e.g. "Scan" finds "Set up a scan inbox"), "Help for this area" in the "…" menu, "How to" links in the empty states of projects, the filing and the documents, and Settings > Help. New session routes `GET /api/help` and `GET /api/help/section`; the app's search kind `help`. New lint `tools/check_userhelp.py` (CI): a bold menu item that is no longer a text of the interface, a missing or outdated translation or an unknown "Show me" place is red.
- #5860 Agents: "Show me" - an agent's chat message can carry `show: [{target, text}]` (API v1 chat, MCP `send_chat`); the app shows a "Show me" button that opens the view and highlights the control the person presses next with the tour's spotlight and the agent's line, step by step (Next / Back / Done / Close, Escape, the phone's back button). It never clicks, switches or saves anything. Places come only from the fixed list `docs/help-targets.json` (unknown key = 400); `help_overview` lists them (`show_targets`), `read_help` names a section's places (`show`). A missing control (phone, no right, area off) says so in one line. New column `agent_chat.show_steps` (JSONB). The tour and "Show me" share one spotlight.
### Fixed
- #5861 follow-up: `wiki_append` belongs to the MCP toolset "wiki" (p2391_b_toolsets was red on main).

Package 2.1077 (Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Sammelpaket: A).
### Added
- Lint `tools/check_notify_calls.py`: a new direct call of `notif_ok(` or `news_put(` outside `core/objnotify.py` and `collab/news.py` is red (send through `obj_notify`, rights first); the existing ones stand per file in `tools/notify_calls_baseline.json`, which only shrinks; CI step and suite `p21077_a_notifylint` (#5459).
### Changed
- Calendar: loading, empty and error states come from the shared block. While the shown range loads, a quiet "Loading…" floats over the grid; a failed load says "Events could not be loaded" with "Try again" instead of looking like an empty month (and is not fetched again on every drawing); offline with a saved copy the view says it shows the saved copy. An empty week, day or year says "Nothing planned …"; the agenda's "nothing" is the shared block (#5461).
- Calendar month: the day list under the month no longer says "No tasks on this day" next to that day's events ("Nothing planned on this day." only when the day is empty), and turning the month moves it along (the 1st of the month, today in the current month) instead of showing "Today" under another month (#5461).
### Fixed
- Event editor: a refused save opens the editor again with what was typed and now says "Not saved: …" with the reason above its buttons (#5461).
- Calendars window: opens at once instead of waiting silently for the people list (only "Share…" waits for it); a calendar trash that failed to load says so with "Try again" instead of "The trash is empty"; Settings > Calendars and the absences subscription link say a failed load with "Try again" instead of always "Only available online." (#5461).

Package 2.1073 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Changed
- #5570: "Optimise PDF" goes page by page: each page (its measure, then the page with its text layer) is one step of its queue thread (#5412), the run's folder keeps the pages made so far between the steps. A restore no longer waits for the end of a long run, a restart between two pages no longer starts a run over, and a file put into the trash mid-run cleans up at once. The run's time limit counts over all its steps; GET `/api/docs/<id>/pdfopt` names how far a run got (`step: [done, all]`).
- #5865: the old table of office trash copies (`office_trash`) is gone. Every start writes copies of an older database back into the shared trash first, then drops the table; copies that could not come back go with it (the log names their number). The key rotation, encrypt-all / decrypt-all and the terms clean-up no longer walk those copies.

Package 2.1068 (Bündel: Freigabe-Karte eines Agenten zeigt bei Textänderun, Agenten-Werkzeug: Text an eine Wissensseite anhäng).
### Added
- #5831 An agent's approval card that changes a text (knowledge page, task notes, project description, comment) shows the change itself: folded one line in words ("Knowledge page Wiki/2D: 1 line added, nothing removed"), unfolded the removed and added lines with + / − and two lines around each change, "Show everything" for long ones. The server reckons it from the card's bound step against the text now, with the rights of the person who looks (`GET /api/approvals/diff`); a target changed since the card is marked, an unreadable or encrypted one shows no lines, and after the answer the card keeps the change as it was then. The technical "Step: …" line moved into the fold for every card.
- #5829 `wiki_append` / `POST /api/v1/wiki/pages/{id}/append` takes `under` (a heading of the page): the text goes to the end of that section; an unknown heading answers 404 `heading_not_found` with the page's headings and writes nothing. `wiki_write` points to `wiki_append` for additions.
### Changed
- #5829 Appending puts exactly one empty line between the page and the new text (was one line break).

Package 2.1069 (Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Listen-Zustand: Kern-Papierkorb-Schreiber absicher).
### Changed
- #5412: "Optimise PDF" runs in a thread of its own next to the documents queue, so a long run (up to 30 minutes) no longer holds up the text recognition of newly uploaded documents (a new run starts once no document waits for its recognition); the queue serves the workspaces in turn, and besides the limit per person at most 200 runs wait per workspace (the automatic runs of new scans count only against the person) (then "Too many documents wait for optimising"), a selection skips the documents of a full workspace.
- #5416: the core's trash is guarded for every kind with the generic routes or the retention run (`obj_trash_cols_missing()`: a kind whose table lacks deleted_at / deleted_by is named by its suite); the lint `tools/check_list_state.py` also counts a handwritten compare on a project's state marker `lists.state` (only `core/access.py` writes it).

Package 2.1060 (Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Weich rot: p2100_ui, Weich rot: p2106_b_ui u. 18 weitere, Bündel: Bündel: Sam).
### Fixed
- Search in bookmarks, tasks, contacts, notes, events, letters and messages: words typed without a space between them (`page.html`, `anna@firma.de`, `Kick-off`) must stand next to each other again, as before the shared search index; with a space each word may stand anywhere (#5878).
- Quotations: a draft moved into the trash takes its open approval links with it, so a restored draft never brings back an old link; signing waits for the quotation's lock (the trash's order), a link decided meanwhile keeps the quotation out of the trash, a link gone with the draft redirects instead of an error (#5869).
- Agent approvals without a task: one News entry in the bell instead of two (#5870).
- Start state: the lean tasks filled back on the device carry exactly the fields of the whole state again (`rev`, `updated_by`, `deleted_by` no longer added) (#5875, #5184).
- Organisation invitations: the clean-up of expired invitations is one plain statement the schema check covers in full (#4949).
- Office and split view: the last pixel sizes in the style sheets are rem (#5676).
- Test suites follow the intended behaviour since earlier packages: the toast's Undo takes back exactly its own step (roadmap_ui #5625, p1_ui #5868), a deleted reminder draft lies in the trash (#5871), a guest's search finds the pages of the folder shared with them and never others (#5833), the install script's backup block (#5874), the service worker's language parts (#5877), the drag receivers of the favourites row and the split view (#5876), a docstring the rowid guard read as SQL (#5682).

Package 2.1075 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Fixed
- #5496: the retention report of the core's trash run (Settings > Data retention, run "obj_trash") counts what it really deleted: side objects (inbound webhooks, team chat tombstones, member memos, the copies of fields / sections / "Delete all times") are read again under a row lock before they go, so one restored between reading and deleting stays (it was deleted before) and is not counted; the attachments of deleted tasks are named again (`task_attachments`, with the switch off the ones that would go).

Package 2.1071 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- #5658 Sharing by e-mail address: a project, a folder of projects or a knowledge page shared with an address that has no account with a confirmed address yet is kept as an open invitation (the shared core's `obj_addr_shares`, `kalmido/core/addrshare.py`). It becomes the share as soon as the account of that address signs in with the address confirmed (or confirms it while signed in), made as the person who typed it in would make it then (their rights and the project's / folder's rules at that moment). The Share dialogs of a project and a folder list such invitations under the address field ("Invited: gets access once the address is confirmed") with a button to remove them (`GET /api/addr-shares`, `DELETE /api/addr-shares/{id}`); the knowledge page dialog lists them as a card with the address, like a share by address that found its account. The answer of the share stays the same for every address, also when a confirmed account does not fit (yet), e.g. outside the project's organisation: then the invitation waits the same way. Invitations nobody redeems go after 180 days; at most 50 per address.
### Security
- #5658 (Fable review 2.965 F2): the Share dialog of a knowledge page no longer shows a card only when the address belongs to a confirmed account (that told whether the address has an account): every address typed in shows its card.
- #5658 (Fable review 2.983 N2): changing the role of a table's share by address no longer lifts the role of an account the row was bound to before the address had to be confirmed: the row opens again and is redeemed at the next sign-in with the address confirmed.
- #5658: a table shared by address is redeemed right after the address is confirmed by its mailed link too, not only at the next sign-in.

Package 2.1074 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Changed
- #5493: undo across devices, stage 3c - a project's settings with side effects are server steps too (kind `listside`, `kalmido/lists/lpside.py`): folder (with the folder's adopted defaults), workspace, project type, agents (listening, tidying up, members' access, follow-up), client, Home & life (and a trip's dates), time tracking, ticket key and visibility in the organisation; ticket templates / types and properties saved together with them go back too. The step keeps the values before / after (also the ones the save changed as a side effect) and goes back through the project's own write path (`list_apply`, was the route body of `PATCH /api/lists/<id>`), so a workspace change brings back what it ended (client, links); a value changed elsewhere since stays and is named. "Recent steps" lists them on every device; the project dialog's Undo, Ctrl+Z and the workspace toast take back that server step (no second browser entry any more).
- #5493: a device's own undo / redo of a step without a server group sends `X-Kalmido-Undo-Own: 1` and records no new server step, so the way forward (redo) of the person's undone steps stays.
- #5493: the server labels a task's step as the app's history does ("Priority of “Jump”: High", "Renamed …", "Date of …: 4 Mar", "Moved …", the title in quotes; was "Edited Jump"); no project, section or field name goes into a label (a project locked later would keep it there).

## [2.1077.0] - 2026-11-12

Not released (the CI of this version was red); its changes are listed under 2.1086.0.

## [2.1075.0] - 2026-11-12

Not released (the CI of this version was red); its changes are listed under 2.1077.0.

## [2.1067.0] - 2026-11-12

Package 2.1029 (Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Changed
- #5537: projects carry one state marker `lists.state` (`live` / `archived` / `trash`), stage 1: an additive column the database keeps equal to `archived` / `deleted_at` (trigger `kalmido_list_state`, reconciled at every start); every filter on a project's state reads it through `list_state_sql()` / `otr_live()` of `core/access.py`, and the lint `tools/check_list_state.py` (baseline only shrinks) keeps new handwritten ones out. The API v1 and MCP answers are unchanged.
### Fixed
- #5537: a project in the trash that was not archived no longer shows up where only archived projects were left out (folder shares, sprints, the briefing, reminders and pickers of projects).

Package 2.1043 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Changed
- The bell: with Settings > Notifications > "From agents: Only what needs me" (was "Comments by agents: Only replies to me", setting `agent_comments` = `replies`) an agent's new tasks, completions (also closing / reopening) and project status changes no longer write a News entry or send a push, also not through a project bell "All" / "Custom". Still arriving: questions with buttons, approval cards, proposals, mentions, replies to your comment, assignments to you, and completions of a task assigned to you or marked "Urgent" by you. The default "All" is unchanged. (#5792)

Package 2.1042 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- Quotations: the discount of the whole quotation as a fixed net amount instead of a percent (switch % / € next to the discount field in the calculation), spread over the VAT rates of the discountable positions by their share, the rest cent on the largest; never more than the discountable positions (#5815)
- Quotations and invoices: a discount in percent per position ("Discount %" in the row), taken off before the quotation's discount; the row shows "2,000.00 less 10 % discount", the PDF prints it under the unit price, the approval page next to the quantity (#5815)
### Changed
- An invoice or credit note made from such a quotation keeps each position's discount; the e-invoice (ZUGFeRD / XRechnung CII and UBL) carries it as a line allowance with percent and basis (#5815)

Package 2.1044 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- #5824 Agent chat, "…" menu > "Model" for an agent on the Kalmido server: the provider's models by name (current one chosen, the server default marked), saved at once and used from the next message; a link to the model per routine; without an API key a sentence with "Add an API key". Owner of a personal agent and admins of a team agent choose, everyone else sees the model.
- #5825 Page "Agents": every card gets its settings - a gear next to "Chat" and "Plans", a tap on picture or name opens the same, a right click / long press opens the card's menu (Settings, Chat, Plans, Log and usage limit, Pause / Resume); only for who may change the agent (others keep the person card on the picture). The agent objects carry `server` (runs on the Kalmido server).
### Fixed
- #5826 Agent chat, "…" menu > "Permissions": the menu says what is in effect - head "Questions on actions", a line "In effect now: Auto" from the last run, "Host default: Auto" instead of the bare "Host default", "Host default: unknown" (the agent reports it with its next run) when the host never reported it; an agent on the Kalmido server (no host, the switch would do nothing) shows a fixed line "By its permissions in Kalmido".

Package 2.1046 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Fixed
- Knowledge editor: a code block (``` fences or indented) is drawn as one block with a background, a thin line and round corners in the light and the dark design (its lines had the sheet's own colour, so the block did not show); the fence lines like ```sh hide while the cursor is outside the block and show muted inside it (#5828).
- Knowledge editor bar: "More information" stands on one line with the other buttons, the height and type of a small button; on a narrow screen only its symbol (#5828).
### Added
- Knowledge editor: every code block has the "Copy code" button of the read view at its top right (always on a phone, with the mouse while over the block or on keyboard focus); it copies only the block's content, without the fence lines, and leaves the cursor where it is (#5828).

Package 2.997.2 (Teil 2/2: Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Sammelpaket: Aufgaben ohne Paket (Dispatcher), Teil 1/6: Sammelpake).

### Fixed
- Undo of "Delete project" works again: one undo brings a deleted active project back active (an archived one back into the archive), on every device. The undo step from #5609 / #5709 still called the project restore the old way after #5491 had moved it onto the shared core, and every undo of a delete failed with a server error (#5609, #5709).
- A server start no longer replaces the four delete triggers of the shared search word index (#5279) under a table lock every time: the trigger comparison now takes a quoted plain table name as the bare name Postgres prints (#4841).

Package 2.1037 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Glocke: „Außerdem neu“ wird ein ruhiger, eingeklap).
### Added
- Split view: a button next to the bell switches it on and off with one click (pressed = on, only where the split view is offered, i.e. a wide screen with a mouse); Shift+V does the same, also with the focus in the right half; the command search has "Split view on / off"; "Open on the right" now always shows in the menu on a wide screen and switches the view on. The switch in Settings > Appearance shows the same state. (#5803)
- Bell: an @mention in a team chat channel, group or project conversation is an entry under "For you" and counts at the bell and on the app icon (kind `chatmention`; several mentions in one room = one line with their number; read in the chat = read; encrypted messages without text; a muted room counts only the mention). Group conversations get their own line under "For you" like direct messages. (#5800)
- Bell: "N tasks due today" and "N tasks overdue" as two computed lines at the top of "For you" (my open tasks: assigned to me or nobody's in my own list, on my clock); each line counts 1 at the bell and on the app icon, can be marked seen for today (comes back the next day or when more tasks fall due). New route `POST /api/news/due-seen`. Follow-up days and agents' proposals now count under "For you" too. (#5801)
### Changed
- Bell window, phone sheet, News view and start page card: "For you" always stands on top ("Nothing waits for you" when empty); "Also new" and "Read" are one folded "History" without the unread look (no blue ground, no tick, no number; open / closed is kept per device); no number at "Show all"; every filter chip shows its own waiting entries, the bell never follows a filter; the bell's label reads "Waiting for you: N". (#5807)
### Fixed
- The bell's window showed the number of unread direct messages and groups without their lines at the first open (the rooms arrived later); it draws again once they are there. (#5800)

Package 2.1048 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- #5821 Files / Documents: the menu of a folder of the documents ("…", right click, long press on the phone) has "Scan inbox for this folder…": it opens Settings > Integrations > Documents: inboxes with "New scan inbox" open, the folder chosen and its name as the inbox's name; "Create inbox" shows the setup code as before. A folder with a scan inbox shows a small scanner mark and its menu says "Show scan inbox" (jumps to the inbox's row, extend / revoke there). Not offered for plain folders outside the documents, agent folders, locked folders, the trash, or when the server's API is off.
- #5861 Agents: `POST /api/v1/wiki/pages/{id}/append` `{text, expect_updated_at?}` and the MCP tool `wiki_append` add text at the end of a knowledge page without sending the whole page (a line break first when the page does not end with one, at most 20,000 characters; same save, history and rights as `PATCH`; an approval card binds only the added text).
### Fixed
- #5637 follow-up: the single step group's undo route (`POST /api/undo/{id}/undo`) is listed in the parity and tenant coverage tests (both were red on main).

Package 2.1049 (Bündel: Glocke: Termin-Einladung, „Laut für mich“, Komment).

### Changed
- #5806 The bell's "For you" (and its number) now also counts an invitation to an event, a task a colleague marked Urgent for you, a person's comment on a task you created or that is assigned to you (no reply or mention needed), a ready proposal you asked an agent for (and an agent's Playbook proposal) and a stalled job of your agent. Comments on tasks you only follow stay Activity; agents' comments keep following "Comments from agents".

Package 2.1047 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Weich rot: p23602_d_api, Weich rot: p2273_b_move_ui u. 11 weitere).

### Fixed
- An organisation's invitation by e-mail address reaches an account that another organisation's invitation set up and that never signed in again as an ordinary invitation; the check could not see the other organisation's invitation and made it silent (#5837).
- Deleting a file for good while its text recognition was still running could end in a server error (lock order of the core's purge and the file store's documents, #5835).
- Deleting an orphaned video sign-off record from the settings works again without the office switched on (#5793).
- Test suites brought up to date with the proved e-mail address rule and the time export menu (#5004, #5007, #5836, #5838, #5840, #5798, #5796, #5834), the merge queue gate test in a shallow clone (#5841), more diagnosis in p248_b_api (#5839).

Package 2.1051.0 (Bündel: Angebote: gesamte Kalkulation um x % nachkalkulier, Angebote: optionale Positionen und Alternativen (m, Angebote: Zwischensumme je A).
### Added
- #5812 Quotations: "Adjust prices…" in the quotation's menu recalculates the draft's unit prices by x %, to a target total (net or gross) or to a target surplus (admins); rounding to cents, whole euros or 5 euros, the rest on one position (the largest after its own discount), a live preview, one undo step and a history entry; no discount line appears.
- #5814 Quotations: a position can be optional or an alternative ("Kind of position" per row). It is printed with its amount in brackets and "Optional:" / "Alternative:" before the title, but counts in no sum (its own position discount is shown); a note below the totals says so. Invoices and delivery notes made from the quotation leave such positions out.
- #5816 Quotations and invoices: "Subtotal under every section" shows the net of each section (heading to heading) in the editor, the PDF and on the approval page; display only, the totals and the e-invoice stay as they are. New office setting for the default.
- #5817 Quotations: "Print as a flat price" leaves quantities, unit prices, a position's own discount and line amounts out of the PDF, the preview and the approval page (removed on the server, not hidden); net, tax and gross stay. An invoice made from it takes one position per tax rate.
### Fixed
- #5858 Tests: the undo suite calls POST /api/undo/<id>/undo for another person's group, so tenant_coverage is green again.

Package 2.1054 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Changed
- Projects: archiving and restoring a project is written on its state marker `lists.state` at every write path (the project's settings, a project admin, the organisation admin's overview, the quick-notes project, the account clean-up after the sample data, the import undo, a project kept by law) through one helper `list_set_archived()`; the database trigger `kalmido_list_state` now works both ways and keeps the old column `archived` written from the marker, so a version before can still run on the database. The trash stays on the core's `deleted_at` (the trash of every kind). API v1, MCP and exports keep `archived` / `archived_at` / `deleted_at` unchanged. The lint `tools/check_list_state.py` also counts a handwritten write of `lists.archived` (#5794).

Package 2.1056 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Added
- New lint step `tools/check_call_arity.py` in the CI job Lint (and so in the Mac lint and the einreihen check): every call of a module-level function of `kalmido/` and `app.py` gets all its required and keyword-only parameters, no extra positional argument and no unknown keyword; it follows `from ... import`, module aliases and re-exports and respects shadowing per function. A signature change merged next to a new caller (otr_back without uid, 2.1024) is now red in seconds; exceptions only with `# arity-ok: <reason>` on the call. Test `tests/check_call_arity_test.py`, CONTRIBUTING.md (#5863).

Package 2.1055 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Fixed
- #5791: An invoice draft restored from the trash never bills a receipt or time twice: positions whose travel receipt, outlay or time entry was billed on another live document meanwhile are taken out of the draft (the restore says how many), the other sources of such a position are open again, and sources still open are bound to the draft again. Drafts that went into the trash before this version come back as before.
- #5791: The start-up step that writes old office trash copies back reads only the ids of the copies first and loads each copy on its own (never the start balance's copies kept there); a table's columns are asked once per run.

Package 2.1052 (Bündel: Glocke: „Für dich“ hat eine einzige Definition vom).
### Changed
- #5808: News show one way - bundled per task - in the bell's window, the phone sheet and the News view. What stands under "For you" is decided by the server alone (`to_me`, the same entries the bell counts): a bundle stands there when at least one unread entry in it is for you; everything else is the folded history. The plain list, the browser's own list of kinds (`NEWS_NEEDS`) and the toggle "Bundled" are gone; the kept device setting `newsBundle` is no longer read.
- #5808: a team chat mention's bundle shows the words of the message (the plain list did).

Package 2.1045 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- #5827 An approved agent step runs from its card: `POST /api/v1/agent/approvals/{id}/run` and the MCP tool `run_approved_step` send exactly the method, path and body of the card (once, same binding as before); a refused write remembers its step as `step_ref`, `request_chat_approval step_ref=N` turns it into the card, so the agent never retypes a step. Follow-up for appending text to a page: #5861.
- #5822 Agents > Edit agent (and Settings > Agents for a personal agent): section "Sees now" lists what is shared with exactly this agent (projects, knowledge folders / pages, the whole knowledge area, file folders, with role and folders excluded), "Share..." adds a share through the existing ways, a row's remove ends it; permissions that do nothing without a share show "Nothing shared yet" (`GET /api/agents/{id}/sees`; others' private shares only as "+ n more").
- #5823 Knowledge: "Share entire knowledge area..." (menu "..." of the area, right click on "Knowledge" in the sidebar) shares the whole area with the own personal agent or an agent of the organisation, including everything added later; single folders can be excluded per agent ("Exclude folder...", folder menu "Exclude from the shared knowledge area", tag "not for <agent>"; data lock key `wiki_folders`), an own share inside an excluded folder still wins; encrypted areas never. `GET /api/wiki/area-share`. Persons as recipients: #5862.
### Fixed
- #5827 A card whose method and path match no route (e.g. PUT on a knowledge page, the route is PATCH) is refused when it is created (400 naming the allowed methods) instead of being stored as a one-way step that could never run; 409 approval_invalid names its reason (`error.reason`: method, path, body with the differing field names, stale, used with the time it ran, unanswered, rejected, approver rights ...), never contents.

Package 2.1061 (Bündel: Bündel: Projekte (lists): Zustandsmarker Stufe 3 - Wertles).
### Changed
- Projects read their archive state from the state marker `lists.state` everywhere: `core/access.py` `list_archived_sql()` (SQL), `list_archived()` / `list_out()` (rows); 36 reads of the old column `lists.archived` in 24 files moved, `/api/state`, API v1, the organisation admin's project list and the 409 `current` keep the key `archived` (no change of shape). `tools/check_list_state.py` now also counts a read of the old column (#5867, stage 3a; dropping the column follows as its own one-way step).

Package 2.1063 (Bündel: PDF-Vorschau: Grund und Leiste an die Design-Farbe, Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Changed
- #5879: the document view's PDF preview follows the theme instead of fixed greys: its ground is a step darker than the card in the dark theme and a light grey in the light one, the white page stands out by a thin rim and its shadow; the preview bar and the page strip (Pages) look like the other toolbars (the card's surface, muted buttons, the pressed one like a chosen segment). On a phone the bar stays in one row: the page count may shorten, the percentage is narrow, Pages and Full screen sit in the row instead of under it.

Package 2.1062 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Changed
- #5786: a never used account that an organisation's invitation by e-mail created is withdrawn by the daily clean-up (like *Withdraw*: deleted, only while it never signed in, belongs to no other organisation and owns no project) 44 days after its newest invitation (never sooner than 30 days). A week before, a warning mail goes to its address with the date and a link to set the account up; setting it up keeps it, and without a delivered warning nothing is withdrawn. On the same day every expired invitation row of the list goes alike - ordinary, silent, neutral and new-account rows - so the list tells nothing about whether a typed address has an account. New columns `users.oinv_warned_at`, `users.oinv_used` (signed in once).
### Fixed
- #5864: withdrawing an organisation's invitation of a never used new account no longer makes every later invitation of that account silent (the undo, another organisation's): the mark "made by an organisation invitation" (`users.oinv_made_at`) outlives the withdrawal, *Resend* knows the same exception, and the account's link stays while another organisation's invitation is still open.

Package 2.1067 (Bündel: Agenten: Werkzeug „Hilfe durchsuchen“ - die Doku d, Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- #5819 Agents can look up the help of the running version: `GET /api/v1/help` (overview: feature areas and the sections of each help file), `GET /api/v1/search?kind=help` (word search over headings and text, a kind of the search registry) and `GET /api/v1/help/section?key=` (one section by its index key, capped, with the interface words in the person's language). MCP tools `help_overview`, `search_help`, `read_help`; `kalmido_cli.py docs`. The image ships `docs/*.md` (not `docs/dev/`); operator files only for an instance admin's token with admin-read. Agent rules: a question about using Kalmido is looked up first, answered with the click path in the interface's words and its source, never guessed.
- #5819 Help texts for recurring tasks (TASKS.md) and for tasks with a time budget from a quotation (OFFICE.md).
### Changed
- #5789 The start balance of the cash flow goes into the one trash of the core (office trash, recent steps, undo) instead of a copy; the office trash's copy routes are gone, old copies come back as rows of the trash at the start. The table office_trash goes in a later version (#5865).
### Fixed
- #5819 API.md: the path to a scan inbox for a folder (Settings > Integrations > Documents: inboxes > Folder watcher).
- #5822 The agent dialog's Share... project list asks the project's state marker instead of the old archived column (lint red on main after #5867).
- #5801 Tests: the tenant coverage lists `POST /api/news/due-seen` (a mark of the person's own; red on main since 2.1037).

Package 2.1064 (Bündel: Angebote: Hinweis in „wartet auf dich“, wenn ein g).

### Added
- #5818: a sent quotation without an answer now rings the bell under "For you": once a few days before its "Valid until" ("Quotation AN-…, client expires in 3 days") and once the day after ("… has expired without an answer"). It goes to the person who sent it (else the office admins, a private office: its owner), News only, no push, one entry per quotation that counts 1 in the bell; it leaves the bell when the quotation is accepted, rejected, superseded or extended. Nothing changes by itself: the status stays "sent". Quotations without "Valid until" and trial documents never ring.
- #5818: the quotation shows a note above the editor while it waits ("Valid until … - expires in N days" / "- expired without an answer") with **Extend validity** (a new date without a new version; the PDF shows the new date; an open approval link has to be created again), **Follow up** (the send dialog with a follow-up subject and text, finalised quotations) and **Mark as rejected**. The quotation list marks sent quotations past their date "expired". New route `POST /api/office/docs/<id>/valid-until` (sent quotations only, logged in the office log).
- #5818: office settings > Documents: "Tell me when a sent quotation runs out without an answer" (default on) and "Notice before it runs out" (1-30 days, default 3); settings keys `offer_exp_notice`, `offer_exp_days`.

## [2.1040.0] - 2026-11-12

Package 2.1026 (Bündel: Kern-Querschnitt Q6c: Suche im Browser und für Agenten).

### Added
- The command palette's "Everywhere" finds what every area's search finds, from one request: knowledge pages by their text, files and documents, contacts, events, notes, bookmarks, messages, comments and the office; each hit opens its target (#5280).
- Calendar events are searchable for the first time: a word start of the title, place or description (umlauts either way), in the palette, for the API (`GET /api/v1/search?kind=events`, scope calendar) and for agents (#5280).
- MCP: one tool `search` (q, kind all|tasks|messages|contacts|notes|files|wiki|events) replaces `search_tasks`, `search_messages`, `search_contacts`, `search_files` and `search_notes`; kind all gives a short overview of every kind the token may read, never office documents (#5280).

### Changed
- One search registry (core/srchreg.py) and one route per side: `GET /api/search?kind=` and `GET /api/v1/search?kind=`; the routes `/api/search/messages`, `/api/files/search`, `/api/wiki/search` and `/api/v1/files/search` are gone, `scope=messages` stays the older name of `kind=messages` (#5280).
- One browser search registry `SEARCH_SOURCES`: locked lists and knowledge spaces add their hits in the browser; the chat search, the search page and the palette use it (#5280).
- The last ILIKE searches use the shared index: bookmarks, the reading list, the organisation's task overview (a word start, umlauts either way) and file names (a part of the name, umlauts either way) (#5280).

Package 2.1030 (Bündel: Zitat des Tages: Übersetzungen für Spanisch, Itali).

### Added
- Dada quote of the day in Spanish, Italian, Dutch and French: every quote that is no sound poem has its own translation (French for the German and English originals); each language is a file of its own loaded on demand only for that interface language (quotes_dada_es/fr/it/nl.js), English stays the fallback while it is missing (#5785)

Package 2.1028 (Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Changed
- Tasks are deleted for good through the shared core's trash (stage 2c): "Empty trash", its background run and deleting a single task for good (`DELETE /api/tasks/<id>?hard=1`) now run `obj_purge` per task, so the core's history / undo rows of the task go with it. A project kept by law still keeps its tasks (409 with its date); subtasks in lists the person may not empty stay there, detached (#5536).
- Shared word index of sealed texts: the background catch-up works on a time budget per tick (about 2 s over all kinds, in turn) instead of 100 objects per kind, and takes each object under the lock of its source row, so it never overwrites a fresher save; the file-text search of tasks narrows by the index's hashes in SQL before matching (#5783).
### Fixed
- Search in documents, recognised file texts and filed mails: until an object is indexed again by the new rules, a search word of 2-3 characters also finds it by its old whole-word entry (#5783).

Package 2.1031 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Fixed
- #5538: core trash, small findings of the review of 2.851: the projects' trash rule judges the person it is asked for (also outside a request; agents never); deleting for good checks the legal retention under its lock (409, the custodian's early delete stays); the retention run with deleting switched off counts every due item, and full batches rotate so items that stay locked never hold back the rest; a restored task keeps its time format; the task data no longer carries the server's rev / updated_by / deleted_by; the files trash shows the trash period with its floor of one day.

Package 2.1005 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), CI-only rot: p).
### Changed
- Deleted quotation and invoice drafts now go into the shared trash. They stay restorable from the office trash with their number (while still free), client links and billed time, and every list, export, search, the tax report and the agent API leaves them out. (#5415)
- A part removed from a quotation goes into the trash with its positions and comes back with them. (#5415)
- Deleted trips, travel receipts and credit card positions go to the shared trash; undo and the office trash restore them with the same checks as before (open months, a live trip, a draft statement). Taking back a per diem import puts each trip into the trash on its own. (#5415)
- Deleting a finalised quotation that was never sent puts it into the trash as a draft; it comes back as a draft. (#5415)
- Old office trash entries from earlier versions are moved into the shared trash on start and restore through it; old copies of video sign-off records come back the same way; only the opening balance of the cash flow keeps the old copies for now (#5789). (#5415)
### Fixed
- The toast's "Undo" ("Saved - Undo", "Marked read - Undo" ...) takes back exactly its own step again: a newer change of the same person (another device, another item) stays. A part changed since is named; a newer finalisation in the same workspace holds it. The arrow, Ctrl/Cmd+Z and "Back up to here" still go back to the newest step. New route `POST /api/undo/<id>/undo`. (#5637)
- Expired ordinary organisation invitations are deleted by the daily clean-up 30 days after they expire. Silent and neutral entries stay for now, so a vanishing entry never reveals whether an address has an account (#5786). (#5118)
- Travel billing no longer offers or bills onto a draft in the trash. (#5415)

Package 2.1038 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Added
- Favourites: the menu of a folder tile (right click, long press on a phone; head bar and the sidebar's favourites) shows the folder's content on top - a project folder its projects in the sidebar's order (no archived ones) and its subfolders, a folder of the file store its subfolders and files (loaded when the menu opens); a click opens the entry, more than ten end with "Show all", an empty folder says "Empty" (#5811)

### Fixed
- Favourites: folders can be dragged into the favourites row again - a project folder of the sidebar (its tree swallowed the drag) and a folder of the file store (from the sidebar's tree or as a row / card of the open folder) (#5809)

Package 2.1033 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Added
- Settings > Account shows the own e-mail address and whether it is confirmed; "Confirm address" sends a mail with a one-time link (2 days). Opened while signed in as that account (also after signing in first) the app asks once, naming the address, and confirms it. Only a confirmed address counts for organisation invitations by address, "E-mails from my own address" and replies by mail (since #5775); an account an admin typed in now has its own way to confirm it (#5790).
- Confirming wakes the silent organisation invitations of exactly that address: the person hears of them (News, mail, push) in the inviting admin's name, the row keeps its date; a company of its own whose admin may not see the person keeps its row silent (#3570) (#5790).
- Settings > Integrations > Tasks by e-mail: "E-mails from my own address" shows a hint with "Confirm address" while the address is not confirmed (#5790).
- Routes `GET /api/me/email`, `POST /api/me/email/proof`, `POST /api/me/email/proof/confirm` (the web app only: a session or the sign-in proxy, never an agent or an API token) (#5790).

### Fixed
- Settings > Integrations > Tasks by e-mail named no own address ("none set") and the summary by mail had no "Send now": the address had been swallowed by a code comment since 2.49.0 (#5790).

Package 2.1035 (Bündel: Geteilte Ansicht: von links in die rechte Hälfte z).

### Added
- #5802 Split view: drag a project from the sidebar, a task, a document card or a knowledge page from the left half onto the new "Open here" field over the top of the right half to open it there - the same as "Open on the right" in its menu. The field shows only while such a drag runs and only with the split view on; dropped anywhere else the drag does what it did before (sorting the sidebar, moving a task, the drops into the other half). By keyboard the menu entry stays the way.

Package 2.1032 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Fixed
- Sharing a projects folder by e-mail address no longer stores a share for an account outside the organisation of a project in that folder (archived ones too) or of the folder itself: such an address gets the same neutral answer as an unknown one and the folder's people list no longer shows that account's name (#5788).
- The last rare deadlock windows from the review of 2.1017 are closed (one of two requests at the same moment could get an error, no wrong data): handing on a deleted person's address books writes every book first and then the shares, the project members dialog and every other writer of a project member row take the share's lock before the member row (the order of a folder share), and retiring an organisation, moving a calendar into another workspace and moving knowledge pages into a private space lock the events, contacts and page files before the calendar, book or page itself (#5788).

Package 2.1039 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Added
- Bell: every open approval card and permission question of an agent's chat stands under "For you" and counts in the bell's number and on the app icon until it is decided, withdrawn or expired; a waiting job and its card count once, and a waiting job without a task now gets its entry too (before: only the push) (#5804)
- Bell: a question an agent asks in its chat (a job message of kind question, or a message with answer buttons; never judged by its text) stands under "For you" as one row per agent ("Helper has 2 questions for you"), each question counted, until the chat is opened or the question answered; results, status lines and plain messages do not count (#5805)

Package 2.1040 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Changed
- Split view: the line between the two halves is always visible now (4 px in a clear grey, the accent colour on hover, drag and keyboard focus); the grip stays wider than the line and neither half changes its width. (#5813)
### Added
- Settings > Appearance > Split view: "Split from window width" in pixels (default 1440 px, empty = default). The lower bound is the room both halves need (66 rem, about 1056 px at the standard font size); a smaller value is raised to it with a hint. The line below shows the current window width, a "Default" button resets it. The threshold is the person's on every device and also decides when "Open on the right" is offered. The section shows from that lower bound on, so a narrower window can lower the threshold. (#5813)

Package 2.1034 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Changed
- The move from SQLite (Kalmido up to 2.36) to PostgreSQL is gone: `python app.py migrate-sqlite`, `kalmido/admin/migrate.py`, the load hook of the start, the look for an old `tasks.db` at start and `KALMIDO_MIGRATE_CLI`. An install still on SQLite updates to 2.37.0 first (docs/UPGRADING.md); the old command now ends with that note instead of starting a server (#5304).
- Backups from before 2.37 (a `tasks.db` in the zip) are still listed and checked, but their restore is refused; restore them with 2.36 and update through 2.37 (#5304).
- The installers no longer copy a SQLite `tasks.db` before an update, only the PostgreSQL dump (#5304).

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

[Unreleased]: https://github.com/Kalmido/kalmido/compare/v2.1086.0...HEAD
[2.1086.0]: https://github.com/Kalmido/kalmido/releases/tag/v2.1086.0
[2.1077.0]: https://github.com/Kalmido/kalmido/releases/tag/v2.1077.0
[2.1075.0]: https://github.com/Kalmido/kalmido/releases/tag/v2.1075.0
[2.1067.0]: https://github.com/Kalmido/kalmido/releases/tag/v2.1067.0
[2.1040.0]: https://github.com/Kalmido/kalmido/releases/tag/v2.1040.0
[2.1024.0]: https://github.com/Kalmido/kalmido/releases/tag/v2.1024.0
[2.1020.0]: https://github.com/Kalmido/kalmido/releases/tag/v2.1020.0
[2.1016.0]: https://github.com/Kalmido/kalmido/releases/tag/v2.1016.0
[2.1014.0]: https://github.com/Kalmido/kalmido/releases/tag/v2.1014.0
[2.1009.0]: https://github.com/Kalmido/kalmido/releases/tag/v2.1009.0
[2.1007.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.1007.0
[2.1001.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.1001.0
