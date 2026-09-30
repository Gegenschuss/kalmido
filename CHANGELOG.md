# Changelog

All notable changes to Kalmido are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Kalmido uses
[semantic versioning](https://semver.org/): every published change gets at least a new patch version, new features a
minor one, anything that needs action on your side a major one.

## [Unreleased]

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

[Unreleased]: https://github.com/Gegenschuss/kalmido/compare/v2.5.0...HEAD
[2.5.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.5.0
