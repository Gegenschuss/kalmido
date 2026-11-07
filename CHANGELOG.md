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

[Unreleased]: https://github.com/Gegenschuss/kalmido/compare/v2.645.0...HEAD
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
