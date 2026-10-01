# Changelog

All notable changes to Kalmido are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Kalmido uses
[semantic versioning](https://semver.org/): every published change gets at least a new patch version, new features a
minor one, anything that needs action on your side a major one.

## [Unreleased]

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

[Unreleased]: https://github.com/Gegenschuss/kalmido/compare/v2.5.2...HEAD
[2.5.2]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.5.2
[2.5.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.5.1
[2.5.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.5.0
