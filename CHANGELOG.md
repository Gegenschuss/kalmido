# Changelog

All notable changes to Kalmido are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Kalmido uses
[semantic versioning](https://semver.org/): every published change gets at least a new patch version, new features a
minor one, anything that needs action on your side a major one.

## [Unreleased]

## [2.7.0] - 2026-10-01

**In short:** Reminders up to a year ahead and deadlines that count down, reminders that repeat until a task is done
(with quiet hours), the tracked time of a project in hours and days, a steady layout on unfolded foldables, a simpler
first start, the list type "Shopping & packing list", a resizable News dropdown and a handful of settings tidied up.

### Added
- **Reminders well ahead** (#412): the date popover offers *On time*, *15 min*, *1 h*, *1 day*, *1 week*, *2 weeks* and
  *1 month* as chips and *Other…* for any number of minutes, hours, days or weeks up to a year (the server's limit,
  366 days); own ones show as chips too. *Settings > Notifications > Default reminder* has 2 weeks and 1 month.
- **Deadlines** (#412): *Deadline* in the date popover marks the due date as one: the row and the task panel count
  down (*12 days left*, *Deadline today*, *3 days over*), highlighted from the first reminder on. *On Today from the
  first reminder* also lists the task on Today (and in its count) from then on. Task field `deadline` (0 / 1 / 2), token
  API `deadline` + `deadline_in_today` (booleans).
- **Repeat reminder until done** (#413): per task (date popover) or as a list's default (list dialog, owner): every 5,
  10, 15, 30 or 60 minutes or daily, from the first reminder on (without reminders: from the due time), until the task
  is completed. Combines with early reminders, e.g. *2 weeks before the deadline, then daily*. The push carries
  *Done*, *Stop reminding* and *Snooze* (the service worker shows as many as the platform allows, `#nagoff/<id>` in the
  app). New settings *Quiet from* / *Quiet until* (`quiet_from` / `quiet_to`, default 22:00 to 07:00; empty = none):
  nothing repeats in between, the next one comes when they end. A new row *Repeated reminders* in the notification
  matrix (push only); a muted list bell stops them too. One push per interval at most (the due date and the time of
  the last one are stored with the task, a reminder of the same moment counts), at most 30 per person and hour;
  completed, deleted and archived tasks and tasks without a date stop at once. Fields `tasks.nag` ('' = the list's
  default, `off`, `5`, `10`, `15`, `30`, `60`, `1d`), `lists.nag`; token API: the task field `nag`, `nag` / `day_hours`
  on `POST /api/v1/lists` and the new `PATCH /api/v1/lists/{id}` (OpenAPI updated).
- **Time sum in the list header** (#407, time tracking on): a project list shows its tracked time in hours and working
  days (*12.5 h · 1.6 days*), a folder view the sum of its project lists. Hours per day / shift: one value for the
  whole server (*Settings > Administration > Time sums*, `time_day_h`, default 8) that a list can override in its
  dialog (`day_hours`, the owner sets it, the same for everyone in the list). A number field *Budget h* adds a budget
  bar with tracked / budget hours. `/api/state` carries `time_lists` and `time_day_h`.
- **The News dropdown is resizable**: on the desktop a grip at its bottom-left corner (drag, arrow keys, double-click =
  default size), on phones the sheet's handle drags it up to the full height (a tap toggles); the size is kept per
  device.
  Its heading *News* is a link to the News view (with a "›" and a hover state).

### Changed
- **"Checklist" is now "Shopping & packing list"** (#414) with a cart icon and the hint *What you tick off stays at the
  bottom and comes back with one tap.* The stored type stays `checklist`.
- **First start** (K21): *Simple list* is preselected (now with comments off as well), and one question *Start with*
  replaces the project select and the sample checkbox: *Empty*, *Sample project*, *Agency*, *Software / AI dev* or
  *Personal* as cards; a project type switches the modules it needs on. The welcome tour no longer claims the app
  opens on the Inbox.
- **Unfolded foldables** (K13): a near-square touch screen gets a layout width of at least 900 px in both orientations,
  so it keeps the tablet layout instead of flipping to the phone layout when turned. Task rows follow the width of the
  list column (container query): a narrow column (a foldable with the sidebar, a desktop with the task panel) shows
  date, list and assignee in a second line like on a phone, so titles keep their room. Touch tablets keep undo / redo
  in the header while there is room.
- **Timeline labels** (K14): names are cut with "…" (full name in the tooltip), the label of a short bar near the end
  of the range sits left of it and never runs past the range, weekday letters are easier to read.
- **Settings tidied up** (#405): the *Agents* page shows while the module is on (admins also while agents exist); the
  upload token lives only under *Integrations > Share from your phone* (Account links there); *Delete all completed*
  is only in the *Completed* view; the agents' first sub-tab is called *Status*; the tab *Time* is called *Time
  tracking* like everywhere else; German: *Erledigte Aufgaben*, *Eigentümer…*; `settingsModal('layout' / 'collab' /
  'focus' / 'time')` land on their module row and open its options; the repository section of the list dialog shows
  for projects or a list that already has a repository.
- Service worker cache v74.

## [2.6.1] - 2026-10-01

**In short:** Date and reminder changes save as you pick them (with Undo, or with OK if you prefer), every agent has a
status dot in the header, the bell opens the newest News right where you are, and a list's bell can follow your own
choice per event, with filter chips in News.

### Added
- **Dates save at once** (#401): in the date popover every change (day, time, start, duration, reminders, repeat) is
  saved as you pick it; the popover stays open, its foot says *Saved* and offers *Undo* (puts everything back and
  closes) and *Done*. Closing it leaves one undo step for the whole visit with the toast *Date: … · Undo*. New setting
  *Settings > General > Confirm changes with OK* (`date_confirm`, default off) brings back Cancel / OK.
- **A status dot per agent in the header** (#402), always, not only while one works: green ready, blue working, yellow
  waiting for you, grey (hollow) offline / not connected / paused, red error or limit reached. The tooltip and the
  label name every agent with its state; a tap opens a menu with every agent, the Agents view, the chats and *Choose
  the agents shown…*. With a timer running on a narrow screen the dots sit in the merged status chip. New setting
  *Settings > Agents > Overview > In the header* (`agents_hidden`, the ids of hidden agents; default: all shown).
- **The bell opens a dropdown** (#403) with the newest News instead of leaving the view: a dropdown under the bell on
  the desktop, a sheet from the bottom on phones; open an item, remove it, *Mark all as read*, *Show all* for the
  full News view; Esc or a click outside closes it.
- **Custom selection for a list's bell** (#404): the fourth option next to *All activity*, *Default* and *Mute*: per
  event (new tasks, comments, mentions, assignments, completions, project status, unblocked tasks, agents waiting for
  approval) a News and a Push checkbox; a ticked event comes from every task of the list, an unticked one never. The
  choice is kept while another mode is set. `PUT /api/lists/<id>/bell` takes `{mode: "custom", custom: {...}}`,
  `/api/state` lists carry `bell_custom`, `GET /api/v1/me` returns `notifications.custom` and
  `PATCH /api/v1/me/notifications` accepts `{mode: "custom", events: {...}}` per list.
- **Filter chips in News** (#404): *Mentions*, *Comments*, *Assignments*, *New tasks*, *Completed*, *Status*,
  *Agents*, *Sharing*, *Follow-ups* (only the kinds that are there) in the News view and in the bell's dropdown; view
  only, remembered per device.

### Fixed
- The list "+" menu showed *New folder* twice.
- The offline notes ("Changes are sent as soon as the server is reachable") name no host any more.
- The header counts a pill whose own content is cut (the timer's time, the agents' dots) as not fitting and folds one
  level further instead.

## [2.6.0] - 2026-10-01

**In short:** The second usability package: the header always keeps the list title readable plus "…" and the bell, the
agent and timer pills shrink into one status chip when space is short, sharing has its own *Share* dialog, agents that
are not connected say so, "Agents" is the one name for them everywhere, and touch targets, contrast, dates, toasts and a
few texts are tidied up.

### Changed
- **Header with a fixed priority** (K01, K02): on every width the title comes first: it is never cut below its first
  ~12 characters and is shown in full whenever anything else can make room (on a desktop at 1280 and 1920 px also with
  the task panel open). "…" and the bell are always on screen. When space gets short, step by step: the agent pill becomes
  the bot + a number and the timer pill drops the task name; then both merge into one status chip (bot + number, dot +
  time; a tap opens the timer or the agents); then the view switch, field columns, refresh, *Share* and undo / redo move
  into "…"; last, search moves into "…" too. "…" is there on every view (search and the shortcuts where a view has
  nothing of its own). Measured after every render, on resize and once the fonts are loaded.
- **Sharing in its own dialog** (K12): *Share…* in a list's "…" menu, a *Share* button next to the list title (desktop)
  and *Sharing > Share…* in the list dialog open the Share dialog: **People** (roles, *Share with …* + role to invite,
  remove; *What the roles may do* folded), **Agents** (the list's agents with their role, *Share with an agent …*,
  *Stop sharing*, the tidy-up setting), **Public link** (owner) and **Owner** (*Transfer ownership…* / *Take over…*,
  history). The list dialog keeps the list's own settings and shows a one-line summary ("Shared with 2 people · 1 agent").
  Admins without collaboration find *Ownership…* there instead.
- **One term: Agents** (K09): the Settings tab *AI colleague* is now *Agents* (German *Agenten*), its first sub-tab
  *Overview*; "AI usage" is "Agent usage"; texts, the setup guide and the docs follow. The module switch lives only under
  *Settings > Modules*; while the module is off, the Agents tab shows a short hint with *Open Modules*.
- **Agent status** (K08): an agent that never got in touch (no event poll, no API call) or has not for 5 minutes shows
  *not connected* (grey) instead of a green *ready*; its running jobs and its last reported state no longer keep the
  header pill busy (only approvals and unread chat messages do). Webhook agents are unchanged. People's agent lists
  (`/api/state`, `GET /api/agents`, `GET /api/v1/agents`, `GET /api/admin/agents`) carry `webhook` (bool) and
  `contact_age` (seconds since the last poll or API call, `null` = never).
- **Assignee circle only where it means something** (K11): an unassigned task shows the dashed circle only on hover or
  keyboard focus (desktop) and not at all on touch screens; checklists and unassigned subtasks have none. Assigned tasks
  keep their avatar; assigning works as before (click the circle, the task menu, the panel).
- **One date format** (K07): rows, the date column and the task panel all write dates like "Mon, Oct 5" / "Mo, 5. Okt"
  (no more numeric "Mi, 07.10." for the next days), a time after a comma ("Today, 17:30"). The desktop date column
  is wider, cut on the right only, in the normal font, and shows a range as a small range icon with the full range in
  the tooltip.
- **Week view title** (K25): the week's own dates, short enough for one line on a phone: "Sep 28 – Oct 4 · Week 40"
  (the year where it is not this one).
- **Usage card** (K24): the card in the Agents view is a small table with the columns *Today*, *7 days*, *30 days*;
  token counts use one short form in every language ("59.1k" / "59,1 Tsd.", "1.3M" / "1,3 Mio.").
- **Plain words** (K23): settings switched off by the server configuration say "Switched off by the server operator"
  (the variable is in the tooltip) instead of `KALMIDO_UPDATE_CHECK=0` and the like, also for public links, admin
  alerts, the admin topic, the backup passphrase and the agents' log; the refused test alert says the same.

### Fixed
- **Touch targets** (K10): on touch screens the 2.x building blocks reach 44 x 44 px: segment buttons, small buttons,
  icon buttons, the calendar and timeline navigation, the proposal checkboxes and date buttons, the notification matrix
  and settings checkboxes, the agent buttons, the chat; small controls inside rows (assignee, subtask caret, status pill,
  linked tasks) get an invisible 44 px hit area. A new test scans the main views at 390 px and fails on anything smaller
  that is not on its short list of justified exceptions.
- **Contrast** (K17): small texts that used the faint colour (roadmap dates and counts, the palette's type column, chat
  times, group labels in menus and sheets) use the muted colour and meet WCAG AA (4.5:1) in both themes; plain links in
  dialogs use the accent (the dark theme showed the browser's blue at 1.9:1).
- **Toast position** (K18): "Done · Undo" and other toasts sit above the composer, the tab bar and the + button instead
  of on top of them.

Decisions: the Share dialog (K12) came forward from 2.7.0; the agent status counts any API call as contact, not only an
event poll, so an agent that works through tools only is not shown as "not connected" while it is busy.

## [2.5.2] - 2026-10-01

**In short:** A hotfix from the second usability review: on phones the header always keeps "…" and the bell, the
review dialog of a proposal is compact and without stray commas, the first-run tour fits on a laptop screen, and admin
alerts no longer go to the public ntfy.sh unless someone chose it.

### Fixed
- **Header on phones** (K01, minimal form; the full header rework follows in 2.6.0): while an agent is working or a timer
  runs, the agent pill shrinks to the bot with a number and the timer pill to a dot with the time (phones, the Fold cover
  screen and any narrow header, e.g. the Fold inside), so "…" (list menu, view, undo) and the bell always stay on screen.
- **Proposal review** (K03): no more commas between the entries of a "Break down" or "Tasks from notes" proposal; each
  entry is one compact line (checkbox, title, date on the right) with its other fields below, and the footer with the
  count and *Apply* stays visible.
- **First-run tour** (K05): the card is placed with its real height and kept inside the window, so step 5 (*Settings and
  modules*) shows *Back* / *Next* at 1280 x 800 and on every other size.
- **Task panel header** (K06): on phones the checkbox no longer sits on top of the date chip; a long date is shortened
  with "…" (the full date is in the tooltip). On touch screens *Pin* and *Today* / *Tomorrow* are in the task's "…" menu
  and the date picker.
- **Task panel** (K22): no horizontal scroll bar any more (desktop and phone).
- **File picker** (K15): *Data > Import* and *Backups > Restore from a file* use a button in the app's language with the
  chosen file name instead of the browser's "Browse… No file selected.".
- **Plurals and charts** (K16): German "1 Tag" / "1 Woche" (was "1 Tage") and a few more singular forms; the date labels
  of the statistics and usage charts are thinned out so they never overlap.
- **Error text** (K19): opening someone else's proposal (e.g. via its link) explains why instead of showing "unknown".
- **"Ready to start"** (K20) stays on one line in list rows.

### Changed
- **Admin alerts** (K04): they follow each admin's own notification channel. With the public `ntfy.sh` (the default
  `NTFY_URL`) an admin on *Web Push* (the default) gets them on their subscribed devices and none until a device is
  subscribed (they are then only listed in the settings, with a neutral hint and *Subscribe this device*); ntfy only
  for the channels *ntfy* / *Both* or a shared admin topic. With your own ntfy server nothing changes. If you relied on
  admin alerts reaching an ntfy.sh topic while using Web Push: set your channel to *Both* or set an admin topic.
  `GET /api/admin/alerts` lists `topic` (only where it really goes), `devices` and `me` per admin and `ntfy_public`;
  an alert without any destination has the state `listed`. The switch is now called *Admin alerts*.
- **Notification hint** (K04): "No device subscribed for push yet" is a neutral hint instead of a red warning.

Decisions for this release (open questions of the review): on phones the agent pill is an icon with a number; admin
alerts are on by default but only via Web Push to an admin's subscribed device (otherwise nowhere until enabled); the
separate *Share* dialog (K12) moves to 2.6.0.

## [2.5.1] - 2026-10-01

**In short:** Settings > *AI colleague* is tidied up into four sub-tabs instead of one very long page, comment avatars
open the person's card, and suggested branch names are just `kalmido-<id>`.

### Changed
- **AI colleague settings in sub-tabs** (#393): *Agents*, *Lists*, *Usage* and *Log* (admins). Each sub-tab loads only
  when you open it, and the last one is remembered on the device. The default tab is about 200 px high on a desktop
  instead of about 5,900 px for the old single page.
  - *Agents*: one compact card per agent (state and number of lists, today's and this week's usage, a red line only
    for a reached limit or a failing webhook; more details in the tooltip). *Add agent* and *Setup guide* sit side by
    side. The explanation is folded away once an agent exists, and the module switch only shows while the module is
    off (it is always in Settings > Modules).
  - *Lists*: one hint instead of two, one line per agent ("sees 9 of your 25 lists", *Share all*, *New lists
    automatically*). The table first shows only the lists an agent sees, with *Show all (n)*, a search above 10 lists
    and shared lists first. The tidy-up select has short labels, and the tidy agent appears next to it only when tidying
    is on and more than one agent could do it. The heading reads "Which lists they see" when there are several agents.
  - *Usage*: one summary card per agent (today, 7 days, 30 days, and the limit as a bar for admins). The chart, the top 5
    tasks and the per-list and per-model bars are behind *Details*. The chart's date labels no longer overlap.
  - *Log*: 20 requests first, *Load more* adds 50. Event polling (`GET /api/v1/agent/events`, usually most of the
    log) is hidden by default with a switch, a summary line shows today's requests and denied calls (click to filter),
    and task and list names appear where you can see them. On phones the filters sit behind a *Filter* button.
- **Branch suggestion** (#396): the suggested branch name is `kalmido-<id>` without the title part, in the task's
  *Code* section, *Link code…*, the agent events (`repo.branch`), `get_task` and the docs. Branches named
  `kalmido-<id>-…`, `task-<id>-…` and `<id>-…` still link to their task.

### Added
- **Clickable avatars in comments** (#395): a comment author's avatar opens the same card as an @mention (role, open
  tasks, *Assign this task*, *Mention*, an agent's state and chat).
- `GET /api/admin/agents/audit`: `hide_poll=1` leaves out event polling; JSON rows carry `task_title` / `list_name`
  where the admin can see that task or list, and the first page has `today` {`requests`, `denied`, `polls`}. The v1
  audit route is unchanged.

## [2.5.0] - 2026-10-01

**In short:** The first public release of Kalmido, a self-hosted task app for households and small teams: personal
planning, shared projects, time tracking and AI colleagues in one small web app you run yourself, free for any number
of people.

### Added
- **Tasks and lists:** lists with emoji, picture or colour, folders with subfolders, sections as Kanban columns,
  subtasks up to three levels, repeating tasks, reminders, priorities, tags (personal and per list), attachments,
  checklists for shopping and packing, templates, archive instead of delete, undo / redo of the last 30 changes and
  quick capture from anywhere (`q`, Ctrl+Space, a bookmarklet).
- **Views:** Today, *Now doable*, list and Kanban, an Eisenhower matrix (also per folder), a month / week /
  day calendar, a Gantt timeline with dependencies, a roadmap of all projects and statistics.
- **Habits, focus and time:** habits with streaks, a focus timer and stopwatch, time tracking per task with manual
  entries, rates and timesheets (CSV).
- **Together:** unlimited users, shared lists with roles, assignment, comments with @mentions and reactions, an
  activity log, a News inbox, dependencies, project status and progress, custom fields and public read-only or
  tick-off links.
- **Calendars:** subscriptions to Google, iCloud, Outlook or any CalDAV / ICS calendar, and an ICS feed of your tasks.
- **Notifications:** Web Push (also on iOS as an installed app) or ntfy, admin alerts.
- **Sign-in:** built-in login with two-factor authentication (TOTP, recovery codes, passkeys), OpenID Connect, or the
  login of a reverse proxy.
- **Integrations:** a REST API with personal access tokens (`/api/v1`, OpenAPI 3.1), signed webhooks, Paperless-ngx,
  Git hosting (GitHub, Gitea / Forgejo: pull requests, commits, branches per task), import from common task apps and
  ICS / VTODO files, sharing from the phone.
- **AI colleagues:** agents as list members with their own rights, an MCP server ([mcp/](mcp/)), chat, jobs,
  approvals, proposals you review before they apply, tidy-up per list, runtime settings, usage limits, an activity
  log and a setup guide ([docs/AGENT-SETUP.md](docs/AGENT-SETUP.md)).
- **Operations:** automatic, optionally encrypted backups with restore, an update check (GitHub releases), a prebuilt
  multi-arch image (`ghcr.io/gegenschuss/kalmido`, linux/amd64 and linux/arm64), an installable web app that works
  offline, English and German.

[Unreleased]: https://github.com/Gegenschuss/kalmido/compare/v2.7.0...HEAD
[2.7.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.7.0
[2.6.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.6.1
[2.6.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.6.0
[2.5.2]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.5.2
[2.5.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.5.1
[2.5.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.5.0
