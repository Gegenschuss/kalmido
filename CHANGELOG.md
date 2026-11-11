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

## [2.974.0] - 2026-11-11

Package 2.963 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Changed
- Back on a phone goes one view back inside a page that has no address of its own: team chat thread -> room, contacts trash -> contacts, office card statement -> card -> card list, a trip -> trip list, notes trash -> notes; the visible ‹ takes the same way (#5233)
- A subtask opened from a task's panel: Back and the panel's ‹ open the task above it again instead of closing the panel (no dead Back left behind); the X still closes the whole panel (#5233)
- Back on a phone ends a selection mode first and stays on the page (task list, contacts, clients, documents, file store, knowledge, trip receipts); ending the selection another way takes its Back step away again (#5234)
- Search > "Move to another project": Back returns to the normal search like Esc, the next Back closes it (#5234)

### Fixed
- The task panel no longer opens again when it was closed in the same frame it opened in (the ‹ right after Back) (#5233)
- The notes card's markdown strip writes the backtick as \x60, so the innerHTML lint reads chat.js correctly again (#5233)

Fix auf main: harte Suite p287b_a_freelancer_api (#5666).

### Fixed
- Tests: the freelancer API sweep knows an own folder for the new move check of locked folders (`GET /api/files/lock/movecheck/<id>`, #3348), so it stays at most 80 routes without a known id; the threshold is unchanged (#5666)

Package 2.959 (Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), CI-only rot: p2579_c_ui, CI-only rot: p2430_c_ui u. 1 weitere, Sammelpaket: A).

### Added
- Documents: in the document view's page strip, pages of a PDF can be reordered - drag with the mouse, hold and drag on the phone, or Move left / Move right (Ctrl+Shift+arrow); saving makes a new version, Undo brings the old order back (#4805)
- Documents: select several PDF documents, then More > Merge PDFs: a dialog sets the order, the first document gets a new version with all pages, the others go into the trash; one Undo step brings everything back. Not for locked receipts or folders, at most 50 documents / 1000 pages / 100 MB (#4805)
- Agents: new event `task_changed` with `diff` `{field: {old, new}}` (like the webhook `task.updated`) for tasks assigned or delegated to the agent or watched by it, changed by someone else; at most 50 per agent and request; switch `task_changed` in the agent's work style (on by default) (#4030)
- Organisation export / import: the organisation's own ticket types and its field schema (`lists/org_fields.json`) travel along; imported project fields are linked to the target's schema field (same key and type), into the private space both become the importing person's own (#4031)

### Fixed
- Documents: dragging in the page strip on a phone no longer swipes to the next document; a document brought back by Undo shows in the list at once (#4805)

Package 2.958 (Bündel: Gemeinsamer Kern Stufe 7d: Listen - folder_people , Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), USt-Jahreserkläru).
### Changed
- #5245 Shared core stage 7d: who sees a folder now comes only from the shares on its folder nodes (fs_shares); a group share of a project is a core row on the project node (fs_shares.group_id), a group share of a folder gives a folder role like a person's folder share. folder_people and group_shares are dropped at start after a forward copy and a start check (one-way: older versions no longer start on that database). The org export carries the projects' group shares as group ids in store/shares.json. A folder node created later in the same path takes over the folder's group shares, and group / folder shares now reach other open devices at once.
- #5281 Shared core Q7a: obj_versions is the core's second table next to obj_history; knowledge page versions move there at start (sealed texts resealed, ids kept for undo), a hold becomes held_at, and wiki_versions is dropped once empty (one-way). The version list and a single version also return their number `no`.
### Fixed
- #3911 Moving a task that is already done into the done column (or a rejected task into the rejected column) no longer offers Undo - the move changed nothing, and Undo would have reopened the task. The toast "Moved to section …" stays.

Package 2.974 (Bündel: Agenten-Einstellungen: Modellwahl je Lauf (großes ).

### Added
- Agent settings: "Select the model per run" below *Model* in the admin's *Runtime* section, and a section *Model* (field + switch, saved at once) in the permissions dialog of an own personal agent: one model for the person's own messages and decisions, one for routine; off by default = one model as before (runtime `model_split`, `model_decide`, `model_routine`) (#5668)
- Reference starter (`mcp/agent_run.py`, both launchers, capability `model_per_run`): with the switch on every Claude Code run gets `--model` of its kind - chat messages, buttons, reactions, comments, unknown events and job wakes with a hard sign (not done, late messages, result not in the chat, a question or approval card, an open decision, a hard red that is not a story, soft or negated) on the first model; quiet job wakes, new tasks, tidy, follow-ups and planned jobs without a sign word on the second; one conversation per chat, a switch that fails early stays on the previous model for an hour; the log names model and reason per run (#5668)

### Changed
- The agent chat header shows only the model of the last run while the model per run is on (no "set: … · runs: …" mismatch) (#5668)

Package 2.972 (Bündel: Kern-Querschnitt Q4a: Kommentar-Kern obj_comments , Kern-Querschnitt Q9a: Folgen obj_follow: Aufgaben-).
### Changed
- Comments are part of the shared core: task comments live in obj_comments (kind task) with their trash text in obj_comment_trash; one mention parser, one "who may say something" rule, delete by the author or whoever manages the task, pushes through obj_notify (only readers), the agent event once (core/objcomments.py). Routes, API v1, MCP and the export formats are unchanged. At the first start the rows move over with their ids; the tables comments and comment_trash_text are dropped - one-way: the start raises the database's back limit to this release's minor, back only through a backup (#5272)
- Following is part of the shared core: task watchers and the task bell live in obj_follow (core/objfollow.py); obj_notify's follow step reads it; leaving a project or an organisation or deleting the account removes the person's rows. The tables task_watchers and task_bell are moved over and dropped at the first start - one-way, same back limit (#5285)
- Rebuilt from package 2.903 (job/3948) on today's main; the back limit is no longer a fixed line in BACK_LIMITS but the minor of the image that moves (core/kernretire.py kern_retire_floor, Fable review of the rebuild) (#5272 #5285)

Package 2.951 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Fixed
- Redo of a change the undo took out of the outbox before it was sent says "Redone: …" while the device is online; the hint "sent as soon as you are online" only appears offline (#5638).

Package 2.947 (Bündel: Kern-Querschnitt Q5a: Tags-Kern obj_tags: Projekt-, Papierkorb-Kern Stufe 5: Kalender, Kontakte, Leben, Polish Büro: Wortwahl verein).

### Changed
- Tags run on the shared core: project tags and organisation labels are rows of one tag table (`obj_tags`, scope list / org, ready for personal and workspace tags) with one link table (`obj_tag_links`). An organisation label now sits on the task itself - no copy per project any more; a project that leaves its organisation (or whose organisation is deleted) keeps the labels of its tasks as project tags, and a project that joins one hands its same-named project tags to the labels. Members with a restricted role (guest, accounting) only see labels a task of their project carries. Organisation labels are part of the organisation export; the git issue sync finds a label of the project's organisation by name. Tags on end-to-end encrypted tasks stay plain text (as before, now fixed in the core). The old tables `list_tags`, `task_list_tags` and `org_tags` move over at start and are dropped (#5275; one-way: migration fragment `5275_a`, the way back is the backup).
- Calendars, address books, bookmarks, feeds and video sign-offs use the core's one trash: a deleted calendar takes its events along and can be taken back from Recent steps; bookmarks and feeds keep their own undo step; the hourly trash run of the core deletes all five after the trash period (an address book with its contacts, a bookmark with its picture); the own restore and purge ways of these areas are gone (#5367)
- Office wording: one thing, one word - Briefpapier, Dokumentnummer for own documents, Textbaustein, Geräte, Erstattung for card refunds, "Im Gespräch" as the pipeline stage after a lead, distinct names for the three contract menu points, settings always "Einstellungen > Firma & Büro"; a draft without number names its kind in the document lists; deleting into the office trash says "Moved to the trash" (#5454)
- Data retention: the activity clean-up reads the portal history rows to spare once per run instead of grouping them again in every batch of 5,000 (#5055)

### Fixed
- Events: the trash's retention run deletes in one statement, so a calendar restored at the same moment keeps its events (#5367)

Package 2.937 (Bündel: Gemeinsamer Kern Stufe 7c: Wiki und Tabellen nur n, Büro: übrige Löschrouten auf doppeltes Hochzählen ).

### Changed
- Shared core stage 7c: tables and knowledge pages / folders decide who may see them only through the shares on their node in the shared core. The Share dialog of a table and of a knowledge page lists, adds, changes and ends those node shares directly (the file store's dialog shows the same rows); a group shared on a table's node counts too (#5244)
- Tables: an address typed into the Share dialog stays its own row until the person signs in; then it becomes that account's core share. Moving a table and undoing the move gives the shares back through the core (#5244)
- Knowledge: a person share's card data (the switch "show pictures", the News entry) lives in the new table `wiki_share_cards` next to the core share; the dialog's id of a person share is `p<share id>`, public links keep their numbers. Ending a share and Undo keep the same id (#5244)
- Office: every delete / restore route counts the office area once per request, also when one request deletes many rows (fixed costs, letter links); other devices reload the office view once instead of several times (#5632)

### Added
- `kalmido/core/kernretire.py kern_retire_rows`: the stage-7 clean-up for an old table that stays - start check, delete old rows, drop columns, retype, raise the back limit (#5244)

### Fixed
- Sharing a file store node with the same person twice at the same moment no longer makes two share rows (a lock per node and person in `obj_node_share`) (#5244)

### Migration (one way)
- At the first start with this version the old person rows of `sheet_shares` and `wiki_shares` are copied forward a last time, then checked; with nothing left over they are deleted, `sheet_shares.core_id` and `wiki_shares.core_id` / `core_id2` are dropped, their times become TIMESTAMPTZ (`is_folder` BOOLEAN) and the database's back limit rises: a version before 2.937 does not start on it. A database from before 2.565 (no `core_id` yet) runs the same steps. While a row is left that the core does not hold, nothing is deleted and admins see an alert (#5244)

Package 2.956 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), USt-Jahreserklärung 20).

### Added
- Board: a column with the meaning "done" or "rejected" shows the tasks completed or marked "won't do" in it (newest first, five and the rest behind "Show N more tasks"), crossed out, also in the board with lanes; the count in the column head and the WIP limit still count open tasks only, a board with only completed cards no longer says "No tasks." (#3912)

### Changed
- Back on phones and tablets (Android Back, swipe) is exactly one visible step for every layer: one shared mechanism in backclose.js where every layer (dialog, menu, lightbox, search, sheets, tour, date picker, the sidebar drawer and the page itself) can carry views of its own; Back takes the top view away and only the last Back closes the layer. New: Back closes the open sidebar drawer instead of leaving the page, closes the date picker only (the dialog below stays), and steps back through the tour's cards (the last Back ends it); the search counted twice and left a stray history entry; a drawer reopened by Back no longer makes the following Back a dead one (#5230)

Package 2.957 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Added
- Office > Credit cards and Bank: receipts file themselves into month folders (#4910). A statement's PDF and every receipt matched with one of its positions (upload at the position or a later match) go to Documents / Receipts / Credit card / <card with holder> / <year> / <YYYY-MM month> (the statement's month); a receipt matched with a bank booking (by hand or a provider's invoice matched by itself) goes to Documents / Receipts / Bank / <account> / <year> / <YYYY-MM month> (the booking's day). The receipt gets the tag "Credit card" / "Bank". Only documents still in the inbox move; documents filed by hand stay; taking the match back moves nothing back; a folder of the path opened wider than the documents folder (organisation access, a share, a public link) takes no receipt. One shared part for both ways (office/rcfolder.py).

Package 2.953 (Bündel: Gesperrte Ordner: Rest (Schlüsselwechsel, Unterordner-Suche, Review-Funde)).

### Added
- Locked folders: when someone loses access (a share taken back, leaving the organisation or a group, a deleted account), the folder gets a new key: the browser of its owner (or an organisation admin) changes it on opening the folder and encrypts the files again with it; a key seen for the first time on that device waits for the button "Change the key now" in the folder's bar. Earlier versions of a file stay readable for the people keeping the folder; who lost access gets nothing added afterwards (#3348)
- Locked folders: the name search in the bar finds files and folders in the subfolders too (in the browser, over the decrypted names); a hit below shows the folder it lies in (#3348)
- Locked folders: a folder with its content moves into or out of a locked folder (one question, every file re-encrypted in the browser, files and folders keep their ids, shares and links); before the first step the server says what would block it (#3348)

### Changed
- Locking a folder removes the tags of the files and folders in it (the server could read them); the lock dialog says how many first. Moving a file into a locked folder removes its tags too (#3348)
- Locked folders: several items chosen at once move across the border after one question, encrypted files are downloaded decrypted one by one (no ZIP of ciphertexts), "Move to another workspace" leaves locked items out, and the targets of "Move to…" show the decrypted names of folders in a locked folder (#3348)
- Agents: a folder that holds a locked folder somewhere below it can no longer be shared with an agent (409 `fs_locked_agent`, as locking refuses a folder below an agent's share) (#3348)

### Fixed
- Locked folders, review findings of 2.353: who reaches only a part of a locked folder learns nothing about the rest (progress, who switched it, when); a deleted file request does not come back into a folder locked since; no version restore while a folder is being locked or unlocked (never an octet-stream version of a decrypted file); locking waits for a plain upload below the folder that runs at the same moment, and a write into a locked folder finishes before its switch ends; undoing a move to another workspace never puts a plain item below a folder locked since; a move into a locked folder that is refused at the end leaves no stored file behind (#3348)

Package 2.962 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Changed
- Back in menus goes one step back (#5231): a second level ("More…", "Change position…", the chat menu's "Usage", "Page width…") and a follow menu (an entry that opens another menu or picker in the same place, e.g. task "…" > "New date…") are steps of Back - the Android Back key and the menu's "Back" row show the menu before instead of closing everything; closing the menu (X, tap outside) takes all its steps along.
- Back in windows with a second view goes one view back (#5232): the CSV / bank imports (start > columns > preview), the merge dialog, playbook versions and regular checks, the agent's plan form, the wiki history and a shared wiki page (linked page, editor), the folder pickers (wiki "From the file store", new approval) and the sub-tabs of Settings > Agents / Organisation / Server; the window closes only with the last Back.

### Fixed
- The bank fetch (FinTS) shows its Back button in the TAN / approval / preview steps (it was never shown) (#5232).
- The office's bank import has a way back from the column view (and the CAMT preview) to the start step (#5232).

Package 2.955 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Added
- Sign-in page and Today: a Dada quote of the day (78 public-domain quotes with verified sources, Ball, Schwitters, Picabia, Satie and others). The sign-in page shows the quote alone above the form instead of the old greeting; Today shows it below "Good evening, {name}": the original in italics, below it small the translation in the interface language and the author (work and year as a tooltip; sound poems never translated). One quote per day, the same on both pages, no jump on a redraw; the file loads on demand (#5239)

### Changed
- Client timesheet of an invoice: non-billable time entries are left out by default; a switch "Show non-billable entries" in the send dialog and in the new timesheet PDF dialog brings them back, marked "not billable", with the billable hours apart in the total. Entries billed on another invoice of the same office carry "billed with <number>" (only when the sender may see it, otherwise "already billed") (#5648)
- Personal tags run on the shared core: they are rows of `obj_tags` (scope user, an agent's own tags in its own scope) with `obj_tag_links`; one name per person regardless of case (Kunde / kunde are merged), CalDAV categories, filters, the data lock, API v1, the account export and import read the core; promoting a tag moves its links. The old table `task_tags` moves over at start and is dropped (#5276; one-way: migration fragment `5276_a`, the way back is the backup)

### Fixed
- Retention export: a check that the sign-off CSV carries no token columns (#3811)

## [2.962.0] - 2026-11-11

Not released (the CI of this version was red); its changes are listed under 2.974.0.

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

[Unreleased]: https://github.com/Gegenschuss/kalmido/compare/v2.974.0...HEAD
[2.974.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.974.0
[2.962.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.962.0
[2.941.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.941.0
[2.929.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.929.0
[2.910.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.910.0
[2.902.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.902.0
[2.900.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.900.0
