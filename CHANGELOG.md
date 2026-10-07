# Changelog

All notable changes to Kalmido are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Kalmido uses
[semantic versioning](https://semver.org/): every published change gets at least a new patch version, new features a
minor one, anything that needs action on your side a major one.

## [Unreleased]

## [2.26.1] - 2026-10-07

**In short:** The iPhone keyboard no longer covers the quick add sheet (#952), Back on tablets closes only the open
task (#953), plus a sort by creator, a "Created by" line in the task panel and smaller layout fixes.

### Fixed
- **iPhone keyboard over the quick add sheet** (#952): iOS reports the keyboard with a single visual viewport resize
  while the page is still scrolled up, then scrolls back without another event, so the sheet was placed for the wrong
  scroll position and sat under the keyboard. The keyboard position is now measured again on every page scroll and
  shortly after a resize. The + button also focuses the field within the same tap, so the keyboard opens at once and
  the sheet sits right above it.
- **Back on tablets and the unfolded Fold** (#953): with a task open, Back (the Android key or gesture) closes only the
  task and keeps the view and the sidebar; the next Back goes to the previous view. Closing the task with its own
  button removes that step again. Upright, where the sidebar is a drawer, Back to a view that was left from the open
  drawer shows the drawer open again, and it stays open.
- No contact autofill offer from iOS on the quick add sheet, the comment box and the team chat input.
- At 1280 px with a wide sidebar and the task panel open, the title is shortened further before the view switch moves
  into "…".
- Settings tabs on phones: "More ›" sits on a solid background and no longer overlaps a tab.
- Long list names in the agents' list table wrap to two lines instead of being cut (full name as a tooltip).

### Changed
- **Sort by "Creator"**: by the creator's display name, then the manual order. It only changes what you see; the
  manual order is kept, and dragging behaves as with the other non-manual sorts.
- The task panel shows a fixed line "Created by <name> on <date>" at the bottom (agents by their name; without a known
  creator the date only; completed tasks add the completion date).
- Settings > Agents on phones and touch screens: the two stop buttons carry labels, "Pause with a reason" (hourglass)
  and "Emergency stop" (stop icon: token and webhook stop at once).
- A hidden, read-only viewport diagnostics box for keyboard problems on phones: open it with `#vvdebug` in the address
  or five taps on the version number (Settings > Help). It shows only screen and keyboard measurements.

## [2.26.0] - 2026-10-06

**In short:** Agents in a team, safely (#928 #949) and easier handling (#932 #936 #937). The owner of a list decides who
may address its agent, agents no longer instruct each other, and a list holds one agent; coding agents ask for approval
to integrate and to deploy without a pull request, pause with a reason and propose changes to other topics. Several
tasks are edited at once in the task panel, the sidebar can be dragged wider, and the iOS keyboard no longer covers
the input fields.

### Added
- **Edit several tasks at once** (#936): Shift-click selects a range, Ctrl/Cmd-click adds or removes single tasks. From
  two selected tasks the task panel shows "N tasks" with the fields they share (date, deadline, priority, assignee,
  list, section, milestone, repeat, reminder, waiting on, pinned, custom fields, tags): equal values as usual, different
  ones grey as *Mixed*; a change applies to all at once, the field is marked as changed, one undo step takes it back.
  Tags are added or removed (a tag only some have is half filled); dates move by −1 day / +1 day / +1 week, each task
  from its own date. Below, the selected titles (open one alone, take one out). Fields you may not change for some of
  the tasks are locked with a hint. On phones *Edit* opens the panel as a sheet.
- **Resizable sidebar** (#932): drag its right edge (or use the arrow keys on the grip, double-click = default width),
  stored per device like the task panel and the chat. Phones and the collapsed sidebar are unchanged.
- **Who may address a list's agent** (#928): per list, the owner (or a list admin) switches on *Members may see and use
  the agent*. Off (the default, also for existing lists): only the owner, list admins and instance admins can chat with
  the list's agent, @mention it, assign it tasks, ask it for proposals or nudge it there; mentions and comments of other
  members send it no event, assigning it is refused. Members still see what the agent does. The chat and the
  @mention / assignee pickers offer an agent only where it is open to you. API: `agent_members` on lists.
- **Agents do not instruct each other** (#928): an agent's mention, comment or assignment reaches another agent only in
  lists with *Agents may address each other* on (default off). Every agent event and webhook names `actor.kind`
  (`person` / `agent`). The behaviour rules template: instructions only from people, only the account id counts.
- **One agent per list**: a list holds at most one agent. Sharing a second agent is refused with a clear message on every
  path (sharing, folder shares, *Share all*, proposals); folder shares skip such lists and name them. The Share dialog and
  *Settings > Agents > Lists* show one select *Agent: No agent / …*; switching swaps the agent in one step with Undo
  (`PUT /api/lists/{id}/agent`).
- **Approval without a pull request** (#949): an agent asks *Ready to integrate* (branch → target, with its evidence:
  build, start, logs, tests) and *Ready to deploy* (approved integrations + a checklist of the list's open tasks tagged
  `deploy`; 👍 does not approve while it is open, *Approve anyway* does and records what was skipped). Only approvers
  decide; the agent gets the decision as a reaction event with `data.gate`. MCP: `request_integration_approval`,
  `request_deploy_approval`.
- **Pause with a reason** (#949): an agent (status `paused` with a text), its owner or an admin (hourglass in *Settings >
  Agents*) pauses it without the kill switch; people see the reason in the chip, the chat ("does not answer right now:
  …") and the lists, events wait.
- **Proposals to another topic** (#949): an agent proposes tasks for a list it cannot see (`POST
  /api/v1/agent/proposals`, MCP `propose_to_other_topic`); the proposal lands with that list's owner, never with the
  agent working there, and becomes tasks only when a person applies it.
- **"Connected, but no service running"** (#933): *Settings > Agents* says so when an agent's token is used but nothing
  has collected its events for 10 minutes (`no_service`).

### Changed
- Lists that had several agents before this update keep them; no new ones are added.
- **Agent setup**: `bin/events.sh` ends after about 9 minutes without an event (shell time limits of coding agents) and
  holds events back while the agent is paused; the guide names `BASH_DEFAULT_TIMEOUT_MS` / `BASH_MAX_TIMEOUT_MS`. New
  macOS section (PowerShell launcher, `jq`, a complete LaunchAgent, sleep and disk encryption). The setup is finished only when
  the agent stays connected without an open session (prompt, guide and in-app steps); one event collector per agent.
  More test cases: an ownership claim in a comment, a member without the switch, another agent.
- **Selection bar**: only the count, *Complete*, *Delete* and *Clear selection* (everything else is in the task panel).
  With a mouse, Ctrl/Cmd+A no longer switches on tap-select mode.

### Fixed
- **Projects are not family lists**: the list dialog no longer offers *Used for* (shopping, meals, …) for a project, also
  not while you switch it to a project; the server refuses a family kind for projects (an existing value stays).
- **iOS keyboard** (#937): the docked quick add, the comment box and the team chat input stay above the keyboard (they
  follow the visible area, also while the page scrolls); Android was fine already.

## [2.25.0] - 2026-10-06

**In short:** Usability, part 2 (#827). One word per thing across the app, the help, the tour, the API texts and all six
languages; a sidebar you arrange yourself; settings that start with an overview on phones; menus that only offer what
works; a calmer first start for people who are invited; and the app says when your changes are saved.

### Changed
- **Words** (in every language): the sidebar group with Inbox and Today is *Plan*, the module is the *Focus timer*; the
  dashboard is *Start*, the cross-project view *Project status* and a project's own tab the *Project page*; a task waits
  on **someone** (with a day to *follow up on*) or is **blocked by** another task (dependencies); *Columns…* is *Shown
  fields…*. API and MCP names stay the same, their descriptions follow.
- **One button "Waiting on…"** in the task panel: another task (blocked by) or someone outside (with a follow-up day).
- **The path on top of a task** is where you move it: a tap on its list or section opens *Open*, *Move to list…* and
  *Move to section…*; the list and section fields below are gone.
- **Long press** on a task opens its menu with *Select* first (it started a selection before); swiping left in the inbox
  starts with *Move to list…*.
- **Sort mode** of the lists: full names, a grip to drag by (touch: right away), one *…* per list (up, down, folder) and a
  bar *Sort lists – Done* on top. A project's progress is a thin line under its name instead of "0 %".
- **List menu**: the same in the sidebar and the header, only what works there (no *Edit list* or project switch in the
  inbox, undo / redo only when there is something to undo), *Delete…* for every list (it is archived first, then
  deleted, after a confirmation that names what is lost). List or project is the switch *Project features* in *Edit list*.
- **Settings**: on a phone they open with an overview of the areas and what is in each; *General* is grouped by what the
  switches do (one label each); *Modules* fold into groups that say "3 of 4 on", and the setup counts the same way;
  *Integrations* start with three plain tasks (calendar on your phone, share from your phone, send by e-mail) and keep
  server details for admins; *Notifications* say on top whether this device rings, with *Turn on* / *Send test*.
- **First start**: the tour only explains (the sample project is offered on its last card, no purpose or project type
  questions); people who are added start with a lean sidebar (*more views* one tap away); the packages *Team* and
  *Software* hold only what their names promise, and changing the purpose lists what goes on, off and out of the tab bar;
  the empty inbox names the + button on phones; *Skip to content* is translated before signing in.
- **Quick add**: one way to add per view (no second *New task* button above the add bar), *Capture to the inbox* is
  named so, the message after adding names the task and sits above the sheet, the two small buttons explain themselves once.
- **Inbox** is always a plain list (no Kanban / Timeline switch, no *+ Section* while it is empty).
- **Task panel**: the priority says its word next to the flag, *Pin* where there is room, Today / Tomorrow with words
  from 360 px.
- **News**: comments that name you count as *Needs you*, each item shows what was written, the bell's head reads
  "4 new" with a small *All read*, and the bell explains what lands there; the team chat and News moved to the group
  *Conversations* with the people; the command palette has *Message to …*.
- **Saving**: "“Take out the bins” completed" names the task; changes that waited for the server are sent again every
  2 seconds and end with *All saved*; the task header shows *Saved* after a change; *Settings > Account* shows when this
  device last synced, with *Sync now*. *Now doable* and *Show completed at the bottom* (shopping and packing lists)
  explain themselves once.

### Fixed
- **Lists in a shared folder** (#931): a list created inside a folder you share with people is now shared with them on
  every path (a project of a built-in type or from a template, an agent's briefing, imports, family and home lists),
  not only from the list dialog. Once at the start of 2.25.0, lists that came into a shared folder after it was shared
  and missed it are shared afterwards; a list someone was taken off on purpose stays as it is.

### Added
- **Settings > Appearance > Sidebar**: move the groups up and down, hide a group with the eye, untick single entries of
  *Plan* and *Views*; the same on every device (user setting `sidebar`).

## [2.24.1] - 2026-10-06

- werkzeug 3.1.9 (security fix CVE-2026-102598)

## [2.24.0] - 2026-10-06

**In short:** Usability (#827). The things people use every day come first: a direct message one tap away, the own
lists right below Inbox and Today, one task menu in a fixed order, a calmer Today, the assignee and the comments at the
top of a task, a settings search that finds what it says, Administration in sub-tabs. The unfolded Fold held sideways
and Samsung DeX get the desktop layout and stop sliding when typing. For running Kalmido for others: storage per person,
a notice to everyone before maintenance, e-mail limits per day, and a note to everyone in a list when an agent joins.

### Added
- **Direct messages that can be found** (#906): *Message* as the first button on a person's card and on *Tasks of …*,
  *New message* always in the team chat; when it cannot work yet, the button says why (team chat off, nobody to write to,
  or the server's reason).
- **Storage per person** (#910): every file a person uploads counts (task and comment files, project files, files in an
  agent chat). Admins set the amount per person, per organisation (shared: amount × members) or for one person (0 =
  unlimited; self-hosted servers stay unlimited by default, `KALMIDO_STORAGE_QUOTA_MB`). From 80 % a hint, at 100 %
  uploads are refused before anything is written (nothing is ever deleted) with *Contact support* (an e-mail with the
  account, the usage and the server filled in; `KALMIDO_SUPPORT_EMAIL` or the admin setting). *Settings > Account >
  Storage* shows the meter. API: `GET /me/storage`, `413 quota_exceeded`.
- **A notice to everyone** (#907): admins publish a notice or a maintenance warning (from / until, optionally a push to
  everyone once); it shows as a slim bar above the app, can be hidden and comes back when it changes. A proxy's
  maintenance page (503) reads *server in maintenance*. Scripts: `GET /announcement`, `PUT /admin/announcement`,
  `python app.py announce "text" --minutes 30 --maintenance`; the update script announces its restart.
- **E-mail limits** (#899): invitations and new sign-in links per account and day (default 30, admin setting) and at most
  5 a day to one address; over the limit the link is shown to copy instead.
- **Agents: who is responsible** (#896): *Members may connect agents* in *Administration > Organisation* (off by default);
  a personal agent gets *Where it runs* (e.g. "Claude (Anthropic, USA)"), and when an agent joins a list everyone in it
  gets a News item naming the agent, who added it and where it runs.
- **Profile picture with a round mask** (#825): choosing a photo opens the crop dialog again (the photo could not be read: the
  Content-Security-Policy does not allow blob: images); it dims what lies outside the circle, shows a big and a small preview, zooms
  with two fingers, the wheel or + / −, and moves with the arrow keys; list icons keep a square crop.
- **Administration in sub-tabs** (#826): People, Sign-in, Organisation, Server, Log & errors (the last one remembered);
  the organisation's name can be changed there.

### Changed
- **Unfolded Fold held sideways** (#908): from 860 px in landscape the desktop layout (sidebar, list, task panel); upright
  stays the tablet layout.
- **DeX and desktop windows** (#832): the keyboard handling only reacts to a real on-screen keyboard (touch and more than
  120 px less height), never to a mouse / physical keyboard or Samsung's autofill bar; the page as a whole never stays
  scrolled; the quick add is no longer mistaken for a login field. Typed text keeps the recognition chips of the docked
  add bar visible (Fold, DeX, desktop).
- **Sidebar**: your own lists come right after Focus; *Views* starts folded below them. No "Person" under every name, and
  the organisation only next to the app name when it is a different name.
- **One task menu** in a fixed order: date (Today / Tomorrow, *New date…*), priority, assignee, list and section, waiting,
  pin, time, template, then the rest and *Delete*; the swipe menu names its task, offers *Move to list…* and ends with
  *All…*.
- **Today**: one slim line *4 overdue · All to today · Another day…*; *Plan my day* and *Fill free time* moved into "…".
- **Tab bar** (phones, until you change it): Inbox, Today, Search, Lists.
- **Task panel**: the assignee sits right under the title; description, subtasks and comments come first, the rest folds into
  *More details* (files, a waiting-on and linked events stay outside); a task with an unread comment opens at the
  comments.
- **Settings search**: finds buttons, helper texts and switches too (and words like "log out" or "storage"), opens the
  sub-tab of its hit and steps the panes back when nothing is found. *Log out* is at the end of *Account*.
- **First start**: the language of the setup page sticks (also after a reload), the tour waits until the setup is done,
  and the name of an organisation is asked only for a team or company, optional and changeable later.
- **Hosted servers** (`KALMIDO_HOSTED=1`, #905): Paperless only reaches public HTTPS addresses (no internal hosts) and
  starts switched off for new accounts, with a hint in the settings.

## [2.23.0] - 2026-10-06

**In short:** Team, family, clients (#463). Clients above your lists with hours, budget and a timesheet per month; the
workload of everyone in your organisation; approvals as a step of a task; forms that turn requests into tasks.
Registration on the login page, sign-in links with a QR code for family members without e-mail, the kind of server
set in the configuration, an agent event for tasks that arrive in its lists, and a tidier sidebar.

### Added
- **Clients** (module *Clients*): contact person, e-mail, phone, address, a note, an hourly rate for lists without their
  own and a budget in hours and / or money (amber at 80 %, red over 100 %). Lists belong to a client (list dialog); the
  sidebar shows the clients above the lists. A client's page: hours this month and in total, the amount, the estimate
  (the tasks' durations) next to the tracked time per list, and the **timesheet of a month** (print / PDF, CSV) with the
  client's name on top. Only people of the client's organisation see it; everyone sees only the lists and hours they
  may see.
- **Workload** (module *Workload*): open tasks per person and week (by their planned start, else the due date; overdue
  ones in this week), weighed with their duration, against their hours per week (set by each person, admins for
  everyone); a tap on a cell lists the tasks. Only the people of your organisation and only what you can see.
- **Approvals**: *Ask for approval…* in a task's menu assigns it to a person of the list. They **approve** it (done),
  **ask for changes** (back to you, with a note) or **reject** it (won't do); the history keeps every step, the person
  who asked gets a News item and a push. The row shows *Approval* while it waits. Agents can ask, never decide.
- **Forms** (module *Forms*): a list's form is a link with a small page (subject, description, name, e-mail) that
  creates a task in the list (a chosen section), for signed-in people of your organisation or, with public links on,
  for anyone with the link. No scripts on the page, a honeypot and limits against spam, a new link any time.
- **Registration on the login page** (#711, off by default): for certain e-mail domains, for anyone after an admin
  approves it, or (shared servers) for anyone with a confirmed address. The address is confirmed with a one-time link;
  new accounts start without access to lists and never learn whether an address already has an account. Admins get a
  News item and approve under *Users*.
- **Sign-in link with a QR code** (#444): for family members without e-mail (children, grandparents): an admin, or a
  parent for their child, creates a one-time link that signs the person in on their own device.
- **The kind of server** (#799): `KALMIDO_INSTANCE_MODE=organisation` (one organisation, everyone in it, the name from
  `KALMIDO_ORG_NAME` or asked once in the setup) or `shared` (no organisations, people see only their own contacts).
  Organisations are no longer created or deleted in the app; servers that made several in 2.22 keep them.
- **Agent event `task_added`** (#795): a task created in, or moved into, a list shared with the agent, with where it came
  from when the agent may see that list and the source (form, e-mail, error report).
- API v1 + MCP: `/clients`, `/workload`, `/tasks/{id}/approval`, `/lists/{id}/forms`, `/forms/{id}`; tasks carry
  `approval` / `approver_id`, lists `client_id`.

### Changed
- **Reactions** (#823): nobody reacts to their own message or comment any more (the reactions of others stay visible);
  the quick 👍 👎 ❤️ of a chat message sit behind a smiley button again; on an agent's open question 👍 / 👎 stay one tap
  away as the approval.
- **An agent at work** (#824): a small pulsing dot at the Agents icon (tab bar, sidebar, the header chip) instead of the
  spinning ring that looked like a stuck loader; the label and the top of the *More* menu say who is working and on what.
- The copyright holder is now Gegenschuss Doberenz Enders Grund eGbR (LICENSE, README, *Settings > Help > About*); the
  license itself is unchanged.
- **Sidebar** (#794): a folder sits right on its lists (no gap after its head; the room is before it), has the height of
  a list row and a folder icon; emoji, pictures and dots of the lists share one icon column, so the names line up.

## [2.22.0] - 2026-10-05

**In short:** Home & life (#663 #662). Kalmido reminds you of what keeps a household and a life running: contracts and
their notice periods, warranties and upkeep, the people you want to stay in touch with, health appointments and
medication, a look back at your day and week with a private journal, trips, and what you want to read later. Seven
modules, each off until you switch it on; everything is made of tasks, lists and contacts you already know.

### Added
- **Contracts & subscriptions** (module *Contracts*): provider, cost per month / quarter / year, the end of the term,
  the notice period (days, weeks or months), the renewal and where it is paid from. The task is due on the **last day to
  cancel** with a reminder before it; ticking it off keeps the contract and moves it to the next term, *Cancelled* ends
  it. The overview sums the cost per month and per year. Link the contract from Paperless in the task.
- **Home & devices** (module *Home & devices*): devices with model, purchase date and **warranty end** (a reminder before
  it, the receipt from Paperless in the task) and **upkeep** that comes back (heating, smoke detectors, tyres, descaling,
  suggestions included).
- **Staying in touch** (module *Staying in touch*, needs Contacts): on a contact's card choose how often you want to be
  in touch; *In touch today* notes the last time, a note says what you talked about. The overview lists who is due, the
  most overdue first, and one push a day names them. Per person: nobody else sees your choices.
- **Health** (module *Health*): appointments, check-ups and vaccinations (repeating every few months or years) and
  **medication** (a daily reminder per time) for you and your family, in a **private** list: an agent never sees it (not
  even as a member, no events, no webhooks), an API token only with the new permission **Health & journal** (`private`).
- **Review & journal** (module *Review & journal*): the day or the week (Monday to Sunday) in review: done, still open,
  moved, coming up; a **private journal** per day with a mood, saved as you type. The daily review card links to it.
- **Travel** (module *Travel*): a trip is a list with its dates and destination, sections for bookings, things to do
  before you leave (dated from the start) and the packing list from the Family templates; optionally an all-day event.
- **Read later** (module *Read later*): a reading list; connect your own **Karakeep** (address + API key, stored
  encrypted, only ever sent to that server): bookmarks become tasks with their link (all, or one Karakeep list), ticked
  ones are archived in Karakeep; about every hour by itself or *Fetch now*.
- A view **Home & life** with a card per module, palette commands, list bars for trips and health lists, a section in
  the task panel.
- API v1 + MCP: `/life`, `/life/contracts`, `/life/devices`, `/life/upkeep`, `/life/upkeep-presets`, `/life/health`,
  `/life/trips`, `/life/review`, `/life/journal/{day}`, `/contacts/{id}/care`, `/life/karakeep/sync`; lists carry `life`
  and `trip`.
- **Organisations** (#752): people in one or more organisations (*Settings > Administration*); whom people see (share
  dialog, attendees, user list, new owners) is *everyone*, *their own organisation* (the default) or *only people they
  are connected with* (a shared server: no directory, lists shared by e-mail address, the answer never tells whether an
  address has an account). Filtered on the server; admins see everyone. On the update one organisation (named after the
  server's domain) is created with every account. Its name shows on the login page, in the sidebar and in the
  invitation mail.
- **Invitations by e-mail** (#697): an admin creates a person without a password and Kalmido sends an invitation (HTML
  mail in the person's language with the logo): a one-time link (valid 7 days, only its hash is stored) to *Set up your
  account*, where the person chooses their own password (and two-factor sign-in) and is signed in. The users list shows
  *Invited* / *Invitation expired*, *Send the invitation again*; the same link resets a forgotten password. Without SMTP
  the admin copies the link.
- **Share folder** (#740): shares every list of a folder now and every list that comes into it later; a shared list
  lands with the other person in a folder of the same name (created when missing). Lists shared before are sorted in
  once on the update, unless the person already put them into a folder.
- A setup and purpose **Home** (#741): contracts, devices, staying in touch, health, the journal, trips and read later;
  **Family** now also switches on contracts, devices and trips.
- **Typing in comments** (#693): *"Bob is writing …"* in a task's comments, for people and agents (`POST
  /api/v1/tasks/{id}/typing`, MCP `comment_typing`); the agent rules ask agents to send it before a comment answer.

### Changed
- **Quick add**: `@` suggests the people and agents of the list the task goes to; a **pasted image** (Ctrl+V) becomes a
  file of the new task (#678). `wartet:Kunde` / `waiting:client` sets *Waiting on external* right away (#686).
- **Waiting on external** is a visible button in the task panel (under *Waiting on…*), in the row's right-click menu,
  the selection bar and the command palette (#686).
- **Today** can show the inbox: *Settings > General > Today*; inbox tasks without a date get their own section with
  buttons for today, tomorrow and a list, and count in Today's number (#681, off by default).
- A **new list or project** gets a fitting emoji from its name (a local word list in six languages; a tap changes or
  removes it) (#682).
- The **celebration**: the heron now flies across the screen with slow wing beats, checkmarks fall behind it; reduced
  motion keeps the small heron with its line (#688).
- **Settings on a computer**: a taller and wider dialog, a darker backdrop with an edge, links without an underline,
  the preview's *high* as a priority flag, the (i) of the font size at its heading, monospace only for numbers (#679).
- The **"Waiting on…" picker**: rows grow with their text, the list name in its own line, grouped (this list first) (#685).

- New people start with the module **Agents** on (not children); the Agents tab shows even before a list is shared with
  an agent, with a short how-to (#739).
- New lists and projects open as a **list** (also software projects) (#749) and start **without preset sections**; a
  new shopping list gets its shop areas only with *Add shop areas* (#747). Existing lists are unchanged.
- The **software parts** of a list's properties (ticket types, repository) show only for a software project or a list
  with a repository, else a quiet *Set up as a software project…*; never for family or household lists (#746).
- The **child account** options of the user dialog appear only once *Child account* is ticked (#696).

### Fixed
- **Sidebar folders** read as a tree again: the folder starts where the lists start, its lists are indented with a guide
  line, the folder shows its sum (#680). The **sort mode** keeps its buttons in one column on the right, with a grip,
  names shorten with … (#692).
- Editing a title in the list showed **two focus rings**; now only the field's (also "add to section", "add subtask") (#683).

## [2.21.0] - 2026-10-05

**In short:** events and contacts in Kalmido (#659 #658). Your appointments and your address books live in the same
database as your tasks, and your phone's own calendar and contacts apps sync with them directly.

### Added
- **Events** (module *Events*): calendars of your own (colours, shared like lists: view / edit, hidden per person),
  events with time zones, all day or over several days, repeat rules with *only this date* (changed or left out),
  reminders, status, busy, attendees (people of this server, contacts, addresses) with their answers, a linked
  preparation task. Month, week and day views show them next to the tasks; a new **Agenda** mode; *+ Event*, the quick
  sheet's *Event* and a drag over free time in the week create them; an editor and a popover with *Edit*, *Delete*,
  *Accept / Maybe / Decline*.
- **CalDAV for events**: every calendar is a VEVENT collection next to the task lists (`/dav/calendars/<user>/e<id>/`),
  invitations in a read-only *Invitations* calendar; sync-token, ETags, `If-Match`, calendar-query with time ranges,
  multiget; what a client writes beyond Kalmido's fields comes back unchanged. Tested with the requests of iOS Calendar,
  DAVx⁵ and Thunderbird.
- **ICS import** into a calendar (the same UID is updated: no doubles) and an ICS export.
- **Contacts** (module *Contacts*): address books (shared like lists), contacts with name parts, company, job title,
  phones, e-mails, addresses, web links, birthday and anniversary (also without the year), groups, a photo and notes;
  the Contacts view with search, a group filter and a card; links to tasks (*waiting on*, *responsible*, *about*) and
  to events; birthdays as yearly tasks (module Family); vCard import and export.
- **CardDAV server** (`/dav/addressbooks/<user>/b<id>/`, `/.well-known/carddav`): vCard 3.0 and 4.0 (each contact in its
  own version, the other one on request), Apple's labels and groups kept, sync-token, multiget, addressbook-query.
- **API v1 + MCP**: `/event-calendars`, `/events`, `/address-books`, `/contacts`, `/tasks/{id}/events`,
  `/tasks/{id}/contacts`; the new permissions `calendar` and `contacts` (contacts are never part of an old `write`
  token and never an agent's default).
- Setup: *What do you use Kalmido for?* switches events and contacts on; *Settings > Modules* has both.
- *Calendar and contacts on the phone*: a guide in the app and in [docs/CALDAV.md](docs/CALDAV.md).

### Changed
- The family events of 2.19 (tasks with people who come along) become events once, on the first start: the people are
  invited (accepted), the task stays, linked and marked done.
- Admins: calendar and contacts apps also look for `/.well-known/carddav`; it must bypass a login proxy like `/dav`.
- The service worker cache is version 98.

### Fixed
- Starting the app while the server is down (the device online) shows your tasks from the device with a quiet
  *Server not reachable – changes are sent later* instead of an error page (#673).
- Statistics and the milestone report use one tolerant way to read a day from a timestamp (#671).
- Timeline on touch screens: a long-press drag for a new task no longer ends silently when the view refreshes during
  the hold (sync, a server answer).

## [2.20.0] - 2026-10-05

**In short:** the code in modules (#646). Nothing changes for you: the same app, the same API, the same start command.
The server and the web app were each one very large file; they are now split by area, so the code is much easier to
find your way around in, and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) explains the layout.

### Changed
- **Server**: `app.py` is now only the entry point; the code lives in the package `kalmido/` (one module per area:
  core, accounts, lists, tasks, collaboration, personal, calendars, integrations, notifications, admin, API, agents,
  family). Same routes, answers, settings and environment variables; `python app.py` and `app.py set-password` work as
  before.
- **Web app**: `static/app.js` is now split into files in `static/js/`, loaded in a fixed order (still plain JavaScript,
  no build step, the same Content-Security-Policy). The service worker caches all of them (cache version 97): after the
  update the app loads the new files once, then works offline as before.
- **Docs**: new [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): the big picture, the data flow, which module holds what,
  how to add a route, a module or a client file. CONTRIBUTING, TRANSLATING and the tests point to the new places.
- **Checks**: `tools/check_layout.py` (CI) keeps the module lists in step (script tags, service worker, package order);
  bandit, semgrep and the syntax checks cover the new folders.

## [2.19.1] - 2026-10-05

- 2.19.1: the contacts import marks its fallback ID hash as non-security (security scanner)

## [2.19.0] - 2026-10-05

**In short:** Family (#653). A new module *Family*, off until you want it: birthdays and anniversaries with the age, gift
ideas and an import from your contacts; household chores that take turns; accounts for children with a simple view,
stars and rewards; who comes along to an event; shopping lists sorted by shop area with a shopping mode; a meal plan whose
ingredients go to the shopping list in one tap; household deadlines like the passport or the car inspection; packing
lists from templates. The setup asks *What do you use Kalmido for?* (For me, Family, Team, Software projects). Profile
pictures are herons now, the search button stays in reach with the sidebar open on a phone, and the chats have "+" for
more reactions.

### Added
- **Module Family** (*Settings > Modules > At home*; off by default, nothing of it shows while it is off). A *Family*
  view brings it together: upcoming birthdays, whose turn it is, the meal plan of the week, the shopping lists, deadlines,
  the kids and packing templates. A *Family* card on the dashboard, commands in the command field.
- **Birthdays and anniversaries**: a yearly task with the age ("turns 80"), a reminder 7 days before (adjustable) and on
  the day, gift ideas as a checklist (what was given stays ticked when the year rolls on). 29 February falls on the 28th
  in other years.
- **Birthdays from your contacts**: connect an address book (CardDAV: Nextcloud, iCloud, Radicale, mailbox.org …) in the
  Family view; birthdays and anniversaries (`BDAY`, `ANNIVERSARY`, Apple's dates) become yearly tasks and follow changes
  once a day, matched by the contact's UID (kept in the task and, with its address book, in the link), so a contact
  is never added twice. Nothing is written back; the password is stored encrypted like a calendar subscription's.
- **Household rotation**: a repeating task in a shared list can *take turns*: after each completion (or every week) the
  next person gets it, with a push; Undo puts the turn back. *Whose turn* in the Family view.
- **Child accounts** (*Settings > Users*, admins): a simple view with big buttons and only the child's own tasks (in shared
  lists a child always takes part as a participant), stars for every completed task (1 by default, more per task) and
  rewards that the parents set, approve or decline; parents get a push when their child asks for one. A child ticks its
  tasks, asks for rewards and changes its own account; everything else is read-only for it, in the app and on the server.
- **Who comes along**: people of a shared list can be added to a task (a trip, an appointment); they see it, children
  too, and get its reminders.
- **Shopping lists**: *Used for: Shopping list* (list dialog) gives a list shop areas as sections; a new item goes to the
  area it had last time ("2 l milk" = "milk"), a common item without a history to a likely area (bananas: fruit &
  vegetables; six languages). *Shopping mode*: the whole screen, big ticks (also on the name), grouped by area, new
  items, live for everyone shopping at the same time; Back on Android closes it.
- **Meal plan**: the next seven days of meals in the Family view; the ingredients in a meal's notes go to the shopping list with one
  tap, without doubling what is already on it.
- **Household deadlines**: passport, ID card, car inspection, insurance, contract or anything else, with the right lead
  time; contracts and insurances are due on the last day to cancel and repeat every year. Link the Paperless document in
  the task.
- **Packing lists from templates**: holiday, swimming pool, daycare, camping, business trip (done items stay at the
  bottom for the next time).
- **"What do you use Kalmido for?"** in the first-run setup, in the welcome tour of new accounts and in *Settings >
  Modules*: For me, Family, Team or Software projects switch the matching modules on and create the starter lists once
  (Family: a shopping list, household chores, birthdays and a meal plan in the folder *Family*).
- API v1: `GET /family`, `POST /family/occasions`, `GET /family/deadline-types`, `POST /family/deadlines`,
  `POST /tasks/{id}/to-shopping`, `POST /lists/{id}/shop-areas`, `GET` / `POST /family/packing`, `GET /family/kids`,
  stars and rewards (`/family/kids/{id}/stars`, `/family/kids/{id}/rewards`, `/family/rewards/{id}` with `/request` and
  `/decide`), `POST /me/purpose` (scope `account`); tasks have `family`, `rotation`, `people` and `stars`, lists `family`.
  MCP tools for all of it (`get_family`, `add_occasion`, `add_deadline`, `ingredients_to_shopping`, `add_shop_areas`,
  `create_packing_list`, `list_kids`, `give_stars`, rewards).
- Chats: **"+" next to 👍 👎 ❤️** opens more emojis (or any emoji), in the agent chat and the team chat.

### Changed
- **Profile pictures** are herons: the line drawing of the app icon on a dark disc, each with its prop (coffee,
  headphones, camera …); pictures chosen before keep their name. `tools/make_avatars.py` draws them.
- On a phone the **search button** stays in reach while the sidebar is open (next to the drawer).
- The setup's presets are the answers to *What do you use Kalmido for?*; *For me* is the simple start of before.
- Shopping lists show only the shop areas that have items (shopping mode lists them all).
- The **date picker** has a year select in its title: a date years ahead is one choice instead of many taps.
- **Sections by dragging**: at the end of a list a *+ New section* zone shows while a task is dragged: drop it there,
  name the section (prefilled), the task lands in it; Undo puts it back and removes the section. *Move to section…*
  offers *New section…* too (keyboard), also in a list without sections.
- **Notifications** tidy themselves: opening the app (or bringing it to the front) closes every notification that needs
  nothing any more (done or deleted tasks, read chats, agents, digest), keeps unread News, due reminders and unread
  chats; *Mark all as read* closes all of them on every device; reading a chat closes its notifications elsewhere too.
  The app icon shows the number of unread News and chat messages where the system supports it (Badging API), from
  the app and from every push.

### Fixed
- A folder header in the sidebar told screen readers its state with an attribute that is not allowed there; it now says
  "folded" / "unfolded".
- In a dialog opened after another one was closed, Tab could bounce between two buttons or leave the dialog (Firefox);
  dialogs now move the focus themselves.
- Dragging a task onto *Drop tasks here* of an empty section with a finger did nothing: the zone was hidden before the
  drop was read (#667).
- Unfolded Fold / tablets in portrait (600-899 px wide): the on-screen keyboard closed again right after tapping
  *Add task*. The keyboard made the window lower than 600 px, the layout flipped to the phone one and hid the bar with
  the focus in it (a regression of the 2.7.2 fix: the docked bar's breakpoint still measured the height). The layout
  is now chosen on the height without the keyboard. Typing in the docked bar no longer scrolls the list behind it
  (a line per key on a short visible area) (#669).
- *Edit user* showed the admin's initials for "No picture"; the setup's start "Empty" was a verb in some languages.

## [2.18.0] - 2026-10-04

**In short:** Software & Planning (#462). Milestones are tasks with progress, a burndown and release notes; tasks can be
created right in the timeline, which now shows sections; GitLab and Bitbucket join GitHub and Gitea / Forgejo, a release
tag reaches its milestone and error reports become tickets; the project type of a list can be changed; code in Markdown
is highlighted and `file:line` links into the repository. Reactions sit visibly at every chat message, the search icon
stays in the phone header, and a new app icon.

### Added
- **Milestones are tasks** (#430): a diamond instead of the round status glyph, a date (optional), checked off like a
  task, no assignee needed; in the list, Kanban and the calendar (month, week, day, agenda). Create one with `!milestone`
  in the quick add, *This task is a milestone* in the task panel or *Make it a milestone* in the task menu.
- **Tasks of a milestone** (the release or version they ship in): a *Milestone* field in the task panel and *Set
  milestone* in the multi-select. The milestone's panel shows its progress, its tasks, a burndown (with a table) and
  release notes from its completed tasks (Features / Fixes / Other) with *Copy*.
- API v1: `milestone` and `milestone_id` on tasks (read, create, change, filters `?milestone=` / `?milestone_id=`),
  `GET /tasks/{id}/milestone`; MCP tool `get_milestone`.
- **Sections in the timeline** (#462): inside each list the tasks are grouped by section with foldable section rows
  (remembered per device), in the list timeline, the calendar's timeline and the *All* timeline.
- **Create tasks right in the timeline** (#431): drag across days on a list or section row, or double-click a day; on
  touch, hold and drag. Type the name, Enter: the task gets exactly that range. *+ Add task* ends every list and each
  section has its own "+". Works offline and with Undo; viewers cannot create.
- **GitLab** (gitlab.com and self-hosted, nested groups) and **Bitbucket Cloud** as repository providers next to GitHub
  and Gitea / Forgejo: merge / pull requests, commits, branch commits and CI at the tickets, `fixes #id`, agents' merge
  approvals, inbound webhooks (GitLab *Secret token*, Bitbucket *Secret*); the web address picks the provider.
  Bitbucket Server / Data Center is not supported.
- **A release tag reaches its milestone**: a new tag like `v2.18.0` in a connected repository completes the open
  milestone "2.18.0" / "Release 2.18.0" once, with Undo; tags from before the connection never do.
- **Error reports become tickets**: a secret webhook per project list (*Edit list > Repository > Error reports*; Sentry
  or any JSON `{title, body, url, fingerprint, level}`) creates bug tickets with the details and the link; the same error
  again counts up at its open ticket. A NEW error sends exactly one News item and push (new notification row *New error
  reports*, on by default); repeats, an error coming back and reports over the limit stay quiet. At most `KALMIDO_ERROR_REPORTS_PER_HOUR` (default 30) new tickets per list and hour,
  a new URL, off. API: `GET` / `PATCH /api/v1/lists/{id}/error-hook` (people only).
- **Project type of an existing list** (#408): the list dialog shows and changes it (None, Agency, Software / AI dev,
  Personal) for the owner and list admins; switching turns on what the type needs and offers its sections, with Undo;
  nothing is deleted. API: `ptype` (web), `project_type` on v1 `GET` / `PATCH` lists, MCP `update_list`.
- **Code in Markdown**: code blocks are highlighted by language (```` ```js ````, ```` ```py ````, ```` ```diff ```` …) and
  have a *Copy* button; `src/app.py:42` in notes and comments links to that file and line in the list's repository.
- Ticket panel: *Copy* `fixes #id` with one tap next to the branch name; a new bug shows *Similar open ticket: #id* when
  an open ticket in the list has a very similar title.
- A maskable app icon of its own, an Apple touch icon and SVG / PNG favicons with a simplified drawing that stays
  readable at 16 px (#394); all icons come from `tools/make_icons.py` and are byte-identical when rebuilt (`--check`).

### Changed
- The milestones of the project overview (2.7.1) are migrated into milestone tasks once (on start and when an older
  backup is restored). The overview, the timeline markers, the next milestone in the header and the
  `/lists/{id}/milestones` routes keep working; their ids are task ids since 2.18.0.
- Moving a task to another list, deleting a milestone for good or turning it back into a task removes the link to it; a
  milestone in the trash keeps its tasks and gets them back when it is restored.
- The *Repository* area of the list dialog shows for software projects and lists that already have a repository.
- Bug template: *Version / found in*; feature template: acceptance criteria as a checklist.
- **Reactions** 👍 👎 ❤️ sit visibly under every message in the agent chat and the team chat, your own included: one tap
  adds or removes yours and shows the count, no smiley button first (#651). On an agent's question 👍 / 👎 still count as
  approval / rejection.
- **The search icon always stays in the phone header** (#651); a crowded header shortens the title with "…" instead.
- **Timeline milestones** are diamonds in their own row at their date (drag, long-press or keyboard to move them); the
  thin vertical line stays, the list row shows no second marker.
- **New app icon** (#394): a heron standing on one leg in the water, the violet sun half on the horizon, on the home
  screen, in the browser tab, the sidebar, the sign-in page, push notifications and the shortcuts. The celebration is
  the heron swinging by on the vine (setting *Celebrations*).
- **Density "Custom"** (#642): two sliders, *Sidebar row spacing* and *Task row spacing* (0–100 %, live while dragging,
  per device) instead of compact / comfortable per area; touch rows stay 44 px, with a mouse rows may get as tight as 24 px.
- Git polling also respects GitLab's `RateLimit-*` headers and `Retry-After`.
- Tests: a seventh CI shard; service worker cache v94.

### Fixed
- News: the section headings follow the page heading (h1 → h2) for screen readers (#652).
- The view switch (List / Kanban / Timeline …) on a touch foldable is a full 44 × 44 px target (#652).
- Saving a team chat message you emptied offers to delete it instead of doing nothing (#652).
- Input bars with a field inside (quick add, the comment box, search fields, the command palette) show the keyboard focus
  once, on the bar, instead of a second box around the field.
- Timeline on phones: the new-task field is no longer hidden behind the tab bar and the "+" button while the keyboard is
  up; holding and dragging from the first visible day no longer creates a range one day short, and the field shows the
  range; section names stay readable; the current month name stays at the left of the header while scrolling.
- Timeline: the footer explains how to add a task; bars and milestones get *Pick a date…* / *Move to date…* in their menu
  (Shift+F10) and the key D.
- List dialog: walking the project type with the arrow keys no longer saves every option; the type is saved once (Enter or
  leaving the field) as one undo step and the sections offered match it. The row *Type* is now *List or project*, the
  list's "…" menu says *As a list* / *As a project*.
- Error-report tickets escape only what Markdown would read (no stray backslashes); backslash escapes in notes show the
  plain character.
- The task panel opens a different task at its top; a new milestone's burndown says *Not enough history yet*.
- Repository: a self-hosted address with GitHub selected gets a hint to pick the provider; connect errors show next to
  the fields.
- Accessibility: roadmap list rows no longer nest the *Open list* button in the toggle; completed calendar chips and the
  Bug chip on a selected row reach 4.5:1; *Copy release notes*; 44 px error-report info and repository link on touch.
- *Set milestone* shows dates in the app's format; long list names in Trash and search end with "…"; the bulk bar no longer
  covers an open task panel.
- The header keeps everyday one-tap actions (view switch, undo / redo, Share) visible and shortens the list name with "…"
  instead; they only move into "…" when they really do not fit (foldables, also desktops with long names).
- Density *Custom* starts exactly at the spacing shown before (no jump), steps of 1 %; task rows are at least 44 px on
  every touch screen.
- Unused chat reactions are one calm grey symbol with enough contrast; *Sent* in the agent chat has enough contrast; the
  team chat's message box keeps a long list name on one line; conversation previews show no Markdown marks.
- The working ring of the tab bar sits centred on the tab's icon at every height (phones, foldables, larger text).
- The chat reaction "👍 1" is a compact pill again, not a big circle, on touch screens.
- Tests: `p151_ui` read the undo history before the step was recorded under load (#652).

## [2.17.2] - 2026-10-04

### Fixed
- Notes: typing in the search field lost the focus after the first letter; the card preview keeps `#123`.
- The dashboard no longer scrolls sideways on phones when a task or message has a long name or word.
- Team chat: a room opened by its address (reload, a push) shows the newest message; the reaction bar of the last
  message is not hidden behind the input box; closed quick reactions of your own messages are no hidden Tab stops.
- Team chat and notes on an unfolded foldable or a narrow window: one thing at a time (with *Back*), so the note and
  the message box get the whole width.
- The *Undo* button in messages at the bottom is 44 px on touch screens.
- After *Mark read* of a News group, *Done* in the dashboard settings, Escape while editing a message and deleting a
  note, the keyboard focus stays in a sensible place; Escape closes the dashboard settings.
- Screen readers: the @mention list reads its options while you move with the arrow keys, the logo is named
  "Kalmido: Dashboard", the unread count of the team chat says "unread", a News group of one item is not announced as
  collapsed; contrast of a mention of you and of "Message deleted" in chat bubbles.

## [2.17.1] - 2026-10-04

### Fixed
- The tab bar's *More* menu did not open when Dashboard or Team chat were in it.
- Phones show the search icon in the header whenever there is room (it moves into "…" only on crowded headers) and
  hide it while the sidebar with its own search field is open.

## [2.17.0] - 2026-10-04

**In short:** Communication. A team chat for people (direct messages and a channel per shared list, agents included,
#419), notes per list and project (#442), tasks by e-mail and the daily summary by e-mail (#443), News bundled per task
with "Needs you" first and a summary by an agent (#452), a dashboard behind the logo (#475), and very long lists that
stay fast (#649).

### Added
- **Team chat** (#419): direct messages between two people who share a list or a group, and one channel per shared list
  for everyone who sees the whole list (agents shared with it read along and get the event `team_message` when
  @mentioned). Markdown, `@Name` mentions, a linked task, reactions, editing / deleting your own messages (list owners and
  admins delete any in their channel), unread counts in the sidebar and the tab bar, mute (only mentions then), pushes
  for direct messages and mentions (notification row *Team chat*). Desktop: conversations next to the open one; phones:
  one after the other. REST API `/team/...` and MCP tools (`list_team_chats`, `read_team_chat`, `post_team_message` …).
- **Notes** per list and project (#442): Markdown documents with title, tags and pinned notes first, saved while typing,
  `#123` links a task, an own address (`#note/<id>`), moving to another list, search in the list and in the command
  field, both versions shown when someone else changed the note in between; in the list menu and the project overview.
  Readers: everyone who sees the whole list; writers: owner, list admins, members. REST API `/lists/{id}/notes`,
  `/notes` and MCP tools.
- **Tasks by e-mail** (#443): with one mailbox set up (`KALMIDO_MAIL_ADDRESS`, `KALMIDO_IMAP_*`) everyone gets a secret
  address for their inbox and one per list (Settings > Integrations); subject = title, text = description, attachments
  = files. Optionally mails from your own stored address. The **daily summary by e-mail** (`KALMIDO_SMTP_*`, Settings >
  Notifications) at the digest time, *Send now* to try.
- **News bundled** (#452): grouped per task with a summary line, *Needs you* first, *Mark read* per group, *Bundled* /
  plain list per device; *Summarize* sends the unread News to an agent's chat.
- **Dashboard** (#475): the logo opens cards for what waits for you, today, News, the team chat, projects, pinned tasks,
  notes, agents, numbers and a search field; *Customize* orders and hides them (saved for all your devices).
- A performance test with 5000 generated tasks (`tests/perf_ui.js`, `PERF_BIG=1` for 20000) (#649).

### Changed
- Very long views render their first 400 tasks and *Show more* (also by itself when you scroll there) (#649).
- The agent behaviour rules ask agents to answer in a list's team chat when they are @mentioned.

### Fixed
- Views with thousands of tasks were slow (finding the subtasks of every row searched all tasks): *Today* with 20000
  tasks went from 28 s to 0.3 s, *All* from minutes to 0.4 s (#649).
- Accessibility follow-ups from a review of 2.16: the reaction bar of your own chat messages opened above the screen;
  the task panel had no close button on an unfolded foldable (900 px and wider); phones show the search icon in the header
  on every view; the subtask arrow, the header checkbox, the priority button and the column separators tell a screen
  reader their state; overdue tasks are marked with an icon in the columns view too; only one task row is a Tab stop;
  Escape on the command field or a panel grip returns the focus; a tap on a panel grip offers *Wider* / *Narrower* /
  *Standard width*; the panel grip follows when the chat opens; fields without a visible label have a name.

## [2.16.1] - 2026-10-04

### Fixed
- The quick reactions of a chat message or a comment stayed open only until the next refresh of the chat (it checks for
  answers every few seconds): the open bar is now kept across refreshes, so a tap on 👍 is not lost.

## [2.16.0] - 2026-10-04

**In short:** Accessibility to WCAG 2.2 AA (#473): the whole app works with the keyboard and a screen reader, messages
are read out, errors are said in words, colour is never the only signal and every drag has another way; an automated
test checks it on every change. Also: resizable task panel, chat and columns (#639, #634), the account at the top of
the sidebar (#641), density for the sidebar and *Custom* (#642), a reaction button on every chat message (#643), a
command field that asks agents and creates tasks (#644), clearer Today / Tomorrow icons (#645), the heron's sun on the
horizon (#447), a *Pinned* view across all lists with the pin button always in the task header (#648), Git webhooks are
never lost (#637).

### Added
- **Accessibility** (WCAG 2.2 AA, [docs/ACCESSIBILITY.md](docs/ACCESSIBILITY.md)): one Tab stop per task list (↑ ↓ /
  j k move the real focus, Enter opens the task and puts the focus into its panel, Esc closes it and goes back to the
  row); menus take the focus and move with the arrow keys; every dialog is a named modal dialog that keeps Tab inside
  and gives the focus back; the task panel is a named region; the side drawer takes the focus and closes with Esc.
- Screen readers: the task circle is a checkbox named after the task, the title a button described by its details,
  messages ("Moved to Inbox · Undo") are read out, new chat messages are a log, error lines are alerts tied to their
  field, colour swatches have names and a pressed state, the week grid is a named scroll region.
- Not only colour: priorities show `!`, `!!` or `!!!` next to the title, overdue dates an alert icon.
- Moving without dragging: *Move up / Move down* in the task menu and Alt+↑ / Alt+↓, *Move to section…* in the task menu.
- Required fields left empty say so next to the field.
- Reduced motion turns off every animation; Windows high contrast keeps checkboxes, selections and focus visible;
  fields have a 3:1 edge; a 2 px focus ring on fields; the toast stays while the pointer or the focus is on it.
- An automated accessibility test: axe-core (WCAG 2.0 / 2.1 / 2.2 A + AA) over all main views, the task panel, the
  chat, Settings, the palette and dialogs, light + dark, desktop + phone, every accent colour; real key presses, 320 px
  and 200 % zoom (`tests/p2160_a11y.js`).
- Drag the edge between list and task or task and chat to resize them (per device; double-click or Enter = standard;
  ← → on the focused grip) (#639); column widths by the grip in the column titles (#634).
- Density *Custom*: the sidebar and the task rows each compact or comfortable; *Compact* now makes the sidebar tighter
  too, touch targets stay 44 px (#642).
- The command field: when empty it shows what it can do; with text it offers *Ask <agent>: …* (sends it to the chat and
  opens it) and *Create as task: …* after the real matches, or on top when nothing matches (#644).
- A reaction button (smiley) on every chat message, mine too; on phones always visible, no long press needed (#643).
- **Pinned**: a smart list with every pinned task of every list, grouped by list, in the sidebar while something is pinned
  (also as a tab); the REST API and the MCP tool `list_tasks` filter with `pinned=true` (#648).

### Changed
- Your account is your picture at the right of the *Kalmido* row (sidebar and phone drawer): Account, Settings, Log
  out; the account rows at the top of the drawer and the bottom of the sidebar are gone (#641).
- Today is a sun with rays, Tomorrow a half sun on the horizon (the old Today icon looked like "reload") (#645).
- The pin button stays next to the priority button in a task's header on every screen width, phones included (it was in "…" on narrow screens) (#648).
- The heron's sun sits on the horizon instead of above its beak (#447).
- Low-contrast texts made readable: other-month days in the calendar, weekend days in the timeline, times in the week
  view, the agent badge.

### Fixed
- A Git push webhook that came within 10 s of a poll was dropped until the next regular poll; now the next poll is
  just moved to 10 s after the last one (#637).
- The list dialog's name, the colour swatches and other fields had no accessible name.

## [2.15.1] - 2026-10-03

**In short:** A phone round. *Today* and *Tomorrow* are back in a task's header on phones (#636), the Eisenhower matrix
folds its quadrants, Search opens ready to type, the week view reads better, and the new token dialog keeps *Expires*
and *Create* in view (#633).

### Changed
- Phones and the Fold: a task's header shows *Today* and *Tomorrow* again (with their words where they fit), next to the
  date in a second row of the header, so the whole date stays readable and nothing scrolls sideways. Wider headers keep
  one row with the two icons; *Pin* is in "…" where room is short.
- Phones: a tap on a heading of the Eisenhower matrix folds that quadrant (the number of tasks stays visible); the
  device remembers it.
- The new API token dialog, the permissions dialog and the agent dialog keep their buttons at the bottom of the screen
  while the rest scrolls; *Expires* of a new token sits next to *Create*.

### Fixed
- Phones: opening Search puts the cursor in its field (before, a second tap was needed). The search and command box
  opens at the top of the screen, ends above the keyboard, leaves out the keyboard hints and has 44 px rows.
- The agent dialog shows an error (such as a taken user name) next to its buttons, where it is seen.
- Week view on phones: "all day" no longer makes its row taller, all-day tasks show two lines of their title instead of
  a few letters, and 07:00 is no longer cut off at the top of the hour grid.

## [2.15.0] - 2026-10-03

**In short:** The complete agent API (#479). API tokens and agents get permissions (scopes) instead of read / write,
an admin limits them for the whole server, and an agent's dangerous changes wait for a person's approval. Everything
the app does is now in the REST API and the MCP server, and a test makes sure it stays that way. A new person's inbox is
named in their language (#632).

### Added
- **Permissions** for API tokens and agents: *Read* (always), *Tasks*, *Comments*, *Structure*, *Delete & trash*, *Read
  files*, *Upload files*, *Time tracking*, *Export*, *Account settings* and *Admin read* (admins). Every API operation needs
  exactly one; the OpenAPI document names it (`x-kalmido-scope`) and the server enforces that very table. A missing one
  answers `403` with `required_scope`. New tokens start with *Read*, new agents with *Read*, *Tasks* and *Comments*;
  agents never get *Account settings* or *Admin read*.
- Settings > Account > API tokens: the permissions as a grid (explanations behind (i)), an optional address restriction
  (*Only from*: IP addresses / networks), and a lock button on every token to change both later
  (`PATCH /api/me/tokens/{id}`).
- Agents: the admin's agent dialog and the owner's lock button on a personal agent set its permissions and addresses; a
  new agent token can expire. The activity log records the permission each request needed (also in the CSV).
- Settings > Agents > Set up (admins): *Permission limit*: what agents and personal tokens may get at most on this
  server; switched off there, a permission stops at once for every token.
- **Approvals of dangerous changes:** an agent deleting a list or a custom field, emptying the trash, changing 10 or more
  tasks at once, moving its list into another folder, renaming / removing folders or sharing gets `202` with a waiting
  job instead (an agent's batches within 10 minutes count together; the agent cannot change such a job). The agent's owner, the list owner or an admin approves it in the Agents tab / Today / News: the request
  then runs as the agent with its rights at that moment; *Reject* changes nothing. The agent gets the result as a
  `job` event.
- REST API: sections (list, create with position, rename, reorder, delete), `POST /tasks/{id}/move` (list, section,
  parent and place: before / after a task, top / bottom), `POST /tasks/batch`, `POST /tasks/{id}/skip`, the trash
  (`GET` / `DELETE /trash`, `POST /tasks/{id}/restore`), dependencies, custom field definitions, templates (incl.
  apply), file uploads to tasks and removing files, editing / deleting comments, folders, list members (share / unshare
  / leave), archiving and deleting lists, project status updates, saved filters, News (+ mark read), habits (create,
  change, delete), the timer and changing / deleting time entries, `GET /export`.
- MCP server: tools for all of these (`move_task`, `batch_tasks`, sections, fields, templates, trash, files, folders,
  sharing, project overview / status / links / milestones, time, habits, News, list tags …); it lists only the tools
  the token may use.
- `POST /api/users` takes `lang` for the new person.

### Changed
- A new inbox is named in its owner's language ("Inbox", "Eingang", …) instead of always "Eingang"; every default name
  is still shown in the viewer's language. API v1 shows the inbox name in the token user's language.
- The setup guides and the agent behaviour rules (`mcp/CLAUDE.template.md`) explain permissions and approvals.

### Compatibility
- Existing tokens and agents keep what they could do: stored `write` means every permission but *Admin read*, and
  read-only tokens got *Read files* once. Scripts may still create tokens with `write`.

## [2.14.0] - 2026-10-03

**In short:** Columns per list (#425): every list decides which columns its rows show and in which order, the same for
everyone in it, custom fields and the task number included. Quick add can open the new task's details at once or
attach files (#484). Plus a calm heron in empty states and on the error pages.

### Added
- *Columns…* (list *…* menu, and the columns button in the list header on desktops): tick the columns of the rows and
  order them with the arrows, by dragging the handle or with Alt+↑/↓: task number (in front of the title), date,
  priority, assignee, tags, tracked time, subtasks, waiting on, created and the list's custom fields. Saved for the
  whole list (everyone sees the same) by the owner or a list admin, with Undo; *Default* goes back to the standard
  layout; members see the setting read-only. A new custom field joins configured columns at the end.
- Rows of such a list: the values sit in their columns under a title row; what is not a column is not shown in the row
  (it stays in the task panel). Where the list column gets narrower (an unfolded Fold with the sidebar, the task panel
  open) and on phones the first two columns stay in the row and the others move into its second line.
- API v1: lists carry `columns` (null = default) and `GET /lists`, `GET /lists/{id}` their custom `fields`
  `[{id, name, type}]`; `PATCH /lists/{id}` takes `columns` (owner / list admins). MCP: `set_list_columns`.
- Quick add (#484): next to Send, *Add and open details* creates the task and opens it at once (for notes and files),
  and the paper clip picks files: the task is created with them attached (the first file's name is the title when
  none is typed) and opens. Phones, Fold and desktop; empty files are refused; offline the paper clip says it needs a
  connection.
- A heron (a line drawing in the text colour; its sun is the accent colour and follows theme and accent) in an empty
  list, on Today (nothing left / all done), for a search without hits, on the welcome tour's first card, on the setup
  screen, when the server cannot be reached at the start, and on the 404 and expired-link pages.

### Changed
- *Columns…* replaces the per-device switches *Show task numbers*, *Hide / Show assignee column* and *Show custom fields
  as columns*; until a list gets its own columns it keeps the layout it had.
- In a list with its own columns, the field option "show as a chip" is hidden (the columns decide).

### Fixed
- The start page when the server cannot be reached has a *Try again* button.

## [2.13.4] - 2026-10-03

**In short:** A phone round (reported on a folded Galaxy Z Fold): dragging by touch scrolls at the edges, moves tasks
to other lists and never leaves a stuck copy behind; the "+" of a section opens the add box above the keyboard; the
chat no longer scrolls away under its box; numbered lists in Markdown keep counting.

### Fixed
- Dragging a task by touch: a copy of the row could stay on top of the list for good (a live update during the drag,
  a second finger, the app going to the background). Every way out of a drag now cleans up, Escape cancels it.
- Holding a dragged task near the top or bottom edge scrolls the list on its own (also with the finger still); the
  bottom edge sits above the tab bar. Mouse drags scroll the list at its edges too.
- While dragging by touch, *Move to list* appears at the top: drop the task there and pick the list (the drawer at the
  left edge clashed with Android's back gesture).
- The "+" in a section head on phones opens the quick-add sheet for that section, above the keyboard (the inline field
  ended up behind it).
- Phone chat: a swipe beside the message box no longer scrolls the page and leaves an empty gap above the tab bar;
  only the messages scroll.
- Markdown (descriptions, comments, chat): bullets indented under a numbered item nest inside it and the numbering
  goes on; a numbered list that starts at 3 shows 3; ``` code blocks are shown as code (agents send them).
- iPhone: the comment box of an open task stays above the keyboard.
- A swipe on a task row that the system cancels snaps back instead of staying half open.
- Dragging over the drawer or the sidebar scrolls its lists, so lists further down are reachable.
- Phones: the subtask arrow sits clear of the screen edge (Android's back gesture), the quick-add chips have 44 px
  touch targets; no keyboard shortcut in toasts on touch screens; two-line rows of a narrow list column keep their
  spacing on an unfolded Fold.
- Git integration: a poll that was still running while a corrected token was saved wrote its late "Access denied" over
  the fresh state, so the connection kept the error and waited out the back-off. A poll now only stores its result
  while the connection is unchanged.
- A state refresh that a save overtook could put the old value back on the screen for a few seconds (an Undo right then
  said "changed elsewhere"). Such a refresh is fetched again.

## [2.13.3] - 2026-10-03

**In short:** Fold follow-up to 2.13.2: one search field in every layout, no + button next to the add bar after rotating,
and "No date" really removes the date with its reminders.

### Fixed
- Search (reported on a Galaxy Z Fold): exactly one search entry per layout. The command-bar field at the top of the
  sidebar or drawer is it (the "Search" view is inside it); the extra "Search" row is gone (it doubled the field in the
  drawer, while the field was missing on an unfolded Fold); the header's command bar shows only while the sidebar is
  folded away.
- The + button follows rotating and folding: gone in the tablet / Fold-portrait layout with the add bar.
- Date popover: "No date" removes date, time, start, reminders, repeat and the repeat reminder in one step, closes the
  popover and offers Undo.

## [2.13.2] - 2026-10-03

**In short:** Polish from the independent re-review of 2.13.0 (#478): on a desktop the task opens next to the chat
instead of under it, the keyboard focus survives live updates, Markdown in comments and chat, and many smaller fixes on
phones, the Fold and the desktop.

### Fixed
- Desktop with the agent chat open (#478 N1, a 2.13.0 regression): list, task and chat sit side by side; where all three
  do not fit, the task takes the chat's place and a chat button in its header (or the agent pill) brings it back.
- Keyboard (N2): live updates (agents, comments, jobs) no longer move the Tab position: a focused button or cell keeps
  its node, the area around it is updated in place.
- Fold (N3): a half-typed "Add task" text moves into the phone's quick sheet when folding (with focus and caret) and back
  when unfolding.
- Comments and the agent chat (N4) render Markdown like task descriptions: headings, lists, read-only checkboxes.
- Font size (N5): 75-150 % (50 % was unreadable; a stored lower value counts as 75 %); the done circles stay round.
- Empty files (N6): 0-byte uploads are refused with a clear message (task files, comments, chat, project files, /drop,
  the ntfy inbox); old empty files say "File damaged or missing".
- Today on a desktop (N7): a waiting approval shows once (the card), not also in the agent band.
- iPhone (N8): when the keyboard pushes the page up, the chat stays in the visible part, header with Back included.
- Phone chat (N9): "New message ↓" and Send keep the keyboard up (replaces #320's close-after-send).
- Chat panel (N10): stays at the bottom when the window gets lower or the box grows.
- Kanban cards of long columns no longer overlap; the task number in cards is a compact label; the matrix fits narrow
  windows without a horizontal scroll bar (F1-F3).
- Search: "#id" (or the only hit) + Enter opens the task (F4).
- Agent comments in a row are grouped, their quick reactions show on hover / focus / long press like in the chat (F5);
  "is writing …" only for a real typing signal, otherwise "is working on it" (F6).
- A field conflict shows only the calm bar under the field, no extra toast (F7); offline with a task open on a phone
  shows in the task header (F8).
- Accessibility: Kanban column menus have a name (F9), avatar initials have more contrast (F10), 44 px touch targets
  for "Set status" and assignee pictures (F11).
- Setup step 2 after a reload starts from the modules that are on (F12); the settings tab strip on phones shows
  "More ›" while tabs are hidden (F13); the "Waiting for you" card in Today follows the agents like the agent pill (F14).
- Settings › Integrations and Administration: fewer inline helper texts, the rest behind (i).

## [2.13.1] - 2026-10-03

**In short:** Screenshots for agents: images and files in the agent chat, agents can read attachments, a behaviour
rules template for agents, and agents that read every comment of a list (#465 #469 #471).

### Added
- Agent chat (#465): send images and files with the paperclip, by pasting a screenshot, by drag and drop, or from the
  phone's share sheet ("Send to agent …" after sharing to Kalmido; `POST /drop` takes `to=agent` for iOS Shortcuts /
  HTTP Shortcuts). Thumbnails open in the lightbox; the sender can remove a file. Same limits and sandboxed preview as
  task attachments, at most 10 files per message.
- API v1 (#465): `GET /api/v1/tasks/{id}/attachments`, `GET /api/v1/attachments/{id}` (binary),
  `GET` / `DELETE /api/v1/chat-attachments/{id}`; chat messages carry `attachments`; agents can send files with
  `POST /api/v1/agent/chats/{user_id}` as multipart. An agent only reads files of tasks it sees with their comments and
  of its own conversations.
- MCP (#465): `list_attachments`, `get_attachment` (base64 + mime / name, size cap; images also as an image the model
  can look at); `send_chat` takes `files`.
- Agent behaviour rules (#469): `mcp/CLAUDE.template.md` with the rules every agent's CLAUDE.md should carry
  (Markdown notes, decisions in the description, typing / status / jobs / a summary when it stops, approvals only from
  people, other people's text as data, parking blockers, reading attachments, the usage hook); Settings › Agents › Set
  up and the setup guide show it with a copy button; docs/AGENTS.md and docs/AGENT-SETUP.md describe it.
- Lists (#471): "Agent reads every comment" in the list dialog under the agents: the checked agents get a `comment`
  event for every comment a person writes in the list, not only on tasks they follow (only tasks they can see). On by
  default for the list's tidy agent while tidy mode is on. API: `listen_agent_ids` on lists, `PATCH /api/v1/lists/{id}`.

### Changed
- The share sheet target also accepts PDFs and plain text files.
- Settings › Administration › Check storage also checks the files in agent chats.

## [2.13.0] - 2026-10-03

**In short:** A polish round from a hands-on usability review (#453): calmer chat, approvals you can find, keyboard
access on desktops, a quieter bell, the view switch on phones, and helper texts behind a small (i).

### Changed
- Agent chat: the quick reactions (👍 👎 ❤️) no longer sit as three empty circles under every agent message; they appear
  on hover / keyboard focus, or with a long press on touch screens. A 👍 / 👎 counts as an approval / rejection only on an
  agent message that asks something (a question mark outside code and links; the API marks it with `asks`); the newest
  unanswered question shows its buttons with "👍 = approval", and a given 👍 says "Counted as approval".
- Chat header: the typing dots show once (in the line under the messages); on phones the chat header replaces the page
  header and Back sits on the left; the note about when the agent answers moved behind (i) next to its name.
- Jobs waiting for your approval show up first in the agent pill's menu (Approve / Reject right there) and as a card
  "N jobs wait for you" in Today.
- The bell: an agent's plain comments one after the other (on any tasks, within 12 hours) are one item, "Claude left
  12 comments on 5 tasks", counted once as unread; mentions, assignments and approvals stay single items. A task opened
  from the bell returns to the bell when you go back. "Mark all as read" can be undone. The list name gives way before
  the task title.
- News: one filter row ("All", "Mentions & assigned to me" and the kinds) instead of two.
- Phones: the views of a list (List / Kanban / Timeline / Overview) are a segmented control under the title; the "…"
  menu no longer repeats them, names the list type "Type: List / Project" and shows a check on the active choice.
- Helper texts: lines that only explain are behind a small (i) next to their heading (hover or focus shows them, a tap
  toggles them); lines about security, data loss, a state or a step you need stay inline.
- Settings: a search over every tab.
- Task numbers: the task panel always shows its "#447" (a tap copies or shares the link to it), the command palette
  and the search jump straight to a task by "#447" or "447", and any list can "Show task numbers" (list menu, per device;
  lists with ticket types always show them).
- Projects: "Project overview" is the first view (segmented control and menus).
- Sidebar: "Search" sits at the top (under the command bar); the logo goes to Today.
- Touch screens: dialogs no longer focus a text field on opening (no keyboard popping up, e.g. in the list dialog).
- Appearance (#429): the font size is a slider from 50 to 150 % in 5 % steps (per device; the old steps become 90 / 100
  / 112 / 125 %), with a live preview, "Reset (100 %)" and Ctrl / ⌘ + / − / 0 on desktops. Below 100 % touch screens keep
  44 px touch targets.
- Fold / tablets: the round "+" is gone (the docked "Add task" bar, or the header's "New task" in views without it);
  the agent chip lost its amber outline; the sidebar uses the desktop's text size.
- Selection: a long press on a task selects it; the selection bar has labels (on phones four actions and "More").
- "Plan my day": the footer stays in view, the header says what is planned and what is still free, tasks that do not
  fit offer "Tomorrow" (planned start tomorrow, the due date stays) and "Plan on …". The daily review names the day it
  plans and no longer repeats the open tasks listed below it.
- Lists with "done at the bottom" (shopping, packing) add new items at the end.
- Quick add: a task that lands outside the open view says where it went ("Inbox · Tomorrow 10:00 · Open").
- Desktops / an unfolded Fold below 1100 px: the sidebar can be folded away (remembered per device).
- The logo inside the app follows the accent colour (the installed app icon keeps its colours).

### Fixed
- Attachments: a file that is missing, empty or cut off on disk (seen after copying the data folder to another machine)
  answered with an empty image that the browser then cached; now it answers 404 / 410 (never cached), the task shows
  "File damaged or missing" instead of a broken image (remove / add a new one as usual), and image addresses carry the
  file size, so a repaired file is fetched again. Settings > Administration > "Check storage" lists such files.
- Task notes on an unstable connection: typing could end in "A field was changed elsewhere" and the field was taken
  away mid-typing (text lost). The title and the description are now saved when you leave the field (and every 5 s
  while typing, and when the app goes to the background) instead of every 600 ms; queued offline text is coalesced into
  one change; a "conflict" with your own earlier save (its answer got lost) is recognised and the newest text simply goes
  on top; a real conflict (someone else changed the field) never takes the field away: your draft stays and a bar under
  the field offers "Keep mine", "Show the other" and "Merge".
- Unfolded Fold / tablets: with the agent chat open the list was squeezed into a narrow column (or covered by the
  panel) and rotating the device while the chat was open broke the layout. Below 1000 px the chat is now a full page
  with Back (beside the sidebar); wider, the main area resizes beside the panel and the sidebar folds into its drawer
  when the list would get too narrow. The layout is recomputed on every resize / rotation, keeping the draft, the focus
  and the newest message.
- "writing …" showed permanently while an agent was only working; the dots now mean its typing signal (or the 90 s after
  it fetched your message), the header shows "working · …".
- Fold / tablets: no second "+" button next to the docked "Add task" bar.
- iPhone: focusing a field zoomed the page (fields below 16 px), so the chat looked cut off at the right and the input
  sat apart from the keyboard; the add sheet and bottom sheets now sit right above the keyboard (iOS keeps the layout
  viewport, they follow the visual viewport).
- Keyboard: a visible focus ring on every control, a "Skip to content" link, the sidebar is one tab stop (↑ ↓ Home End
  walk through it) instead of 30+.
- Kanban by touch: a card held at the screen edge scrolled three columns in 300 ms; the board now scrolls smoothly,
  faster the deeper the finger is in the edge zone, and a drop beside the cards lands in the column under the finger.
- `#agents/<id>` (the push "… answered") opens the chat on tablets and desktops too.
- First-run setup: reloading the page after creating the admin skipped step 2 ("What do you want to use?") and left all
  modules on; it now comes back until Start is pressed.
- Offline: a chip "Offline · 2 changes waiting" instead of only an icon.
- A message (Undo) no longer covers an open bottom sheet.
- Sign-in: the error message is in the page's language, 44 px fields, "Show password", nothing behind the sign-in page
  is reachable with Tab.
- Accessibility: names for the calendar / timeline arrows, the search field, Kanban and matrix "+ Task", the focus
  timer's task and the date sheet's selects; inactive tab bar labels with 4.5:1 contrast; 44 px touch targets for habit
  days, the overdue card, milestones, small avatars, event rows and the notification matrix.
- The calendar's week and day view scroll only the hour grid (no second scroll bar).
- Timeline: a title that would be cut inside its bar is shown next to it; on touch screens the resize grips show once a
  bar is held.
- Project header: the × stays next to the progress bar, "Next due: …", the time sum says "Tracked"; "Set status" shows
  once in the overview.
- Translations: the software project sections "Next" / "Done", "Next week" in full, "1,5 h" with the decimal comma.

## [2.12.2] - 2026-10-02

**In short:** Live updates no longer interrupt typing: the agent chat keeps its scroll position and the keyboard, fields in
the main view keep focus and text; the chat loads only the newest messages.

### Fixed
- Agent chat (#451): when the agent fetched a message (Delivered), showed its typing dots, changed its state or answered,
  the chat was rebuilt: on phones the list jumped to the top and the input lost its focus, so the keyboard closed. The
  open chat is now patched in place (new messages are appended, status chips and the typing row change on their own),
  the input box and the list are never replaced. At the bottom the chat stays at the bottom; scrolled up it keeps its
  place and shows *New message ↓*.
- Task comments: a refresh only swaps the comments that changed instead of redrawing all of them; the bell's dropdown
  keeps its scroll position when an item is removed or everything is marked read.
- Typing anywhere is no longer interrupted by live updates (#453): Kanban *+ Task*, the search, the project overview's
  description and every other field in the main view kept losing focus and text when someone else changed something.
  Updates now wait while a field has the focus (on touch screens always, on desktops unless it is the empty *Add task*
  box) or an IME composition runs, and arrive as soon as you leave it; a field that is redrawn anyway comes back focused
  with its text and caret. The description editor keeps its draft until *Save* or *Cancel*.
- Project overview: *Save* in the description editor stored an empty description (the editor and its section shared
  one id).
- Phone chat with the keyboard open (#453): the chat fills exactly the visible area, the tab bar and the note below the
  input give way, and the newest message stays right above the input.

### Changed
- The chat opens with the newest 30 messages; *Load older messages* at the top fetches the previous page and keeps the
  message you were looking at in place. `GET /api/agents/{id}/chat` (web app) takes `limit` (1-300, default 300) and
  `before=<message id>` and returns `has_more`. The agents' API (`GET /api/v1/agent/chats`) is unchanged (it already
  pages with `since` / `limit` / `has_more`).

## [2.12.1] - 2026-10-02

**In short:** Fixes from the full test run before the launch: a stricter XML check for CalDAV and HSTS on https.

### Security
- CalDAV: XML bodies with a DOCTYPE are now refused by the parser itself, in every encoding. Before, a UTF-16 body or a
  DOCTYPE after a long comment got past the byte check (entities were still limited by the XML library; an app
  password was needed). The same check now covers answers of subscribed CalDAV servers.
- `Strict-Transport-Security: max-age=31536000` on every response served over https (directly or from a trusted
  proxy), so browsers stay on https even if the proxy does not add it. A header the proxy sets itself is kept.

### Tests
- UTF-16 and late-DOCTYPE CalDAV bodies, a UTF-16 CalDAV server answer, HSTS only over https.

## [2.12.0] - 2026-10-02

**In short:** Try Kalmido in your browser without an account or server; quick add understands French, Spanish, Italian
and Dutch.

### Added
- **Browser demo** (#436): `tools/build_demo.py` builds a static demo of the real app (`static/app.js`, `app.css`, the
  translations) that runs without any server. An in-browser stand-in for the API (`tools/demo/shim.js`) keeps lists,
  sections, tasks, tags, fields, dependencies, repeats, comments, time entries, habits, filters, milestones, project
  status and settings in the browser's storage; Today, Upcoming, kanban, timeline, calendar, matrix, statistics, time
  reports and the day plan work on it. Sample data in the browser's language (one of the six), a simulated agent with
  one approval (clearly marked), a bar "Demo – your data stays in this browser" with *Reset demo* and the install link.
  Server features show a notice with the way to install. The page allows no network connection (CSP
  `connect-src 'none'`), has no service worker and no analytics. CI builds it and opens it in jsdom and Firefox
  (`tests/demo_test.js`).
- **Quick add in French, Spanish, Italian and Dutch**: dates (today, tomorrow, the day after, weekdays, next week /
  month, weekend, "in 3 days"), times (`15h30`, `a las 9`, `alle 15`, `15 uur`) and repeats in the language the app
  runs in, on top of English and German. Day / month with a slash (`3/10`, `3/10/27`) works in every language. The
  quick add hints of these languages use their own words and the symbols `!!!` / `!!` / `!` for the priority.
  `tests/quick_lang_test.js` covers every language.

### Changed
- Service worker cache `tasks-shell-v81`.

## [2.11.0] - 2026-10-02

**In short:** Kalmido now speaks French, Spanish, Italian and Dutch (beta); planning your day never moves a due date;
violet is the new default accent; usage reports include Claude Code subagents.

### Added
- **French, Spanish, Italian and Dutch** (#439, beta): the whole interface, push notifications, e-mail and server texts.
  Machine-translated and marked *Beta* in the language pickers (*Settings > General > Language*, first-run setup);
  corrections are welcome (see *Translations* in CONTRIBUTING.md). Dates, numbers and CSV exports follow the language
  (decimal comma and `;` separator, short month names in pushes, weeks start on Monday), French uses the singular for
  0 too. Before login the browser's language is used when Kalmido has it.
- **Translation check** (`tests/i18n_test.py`): every language file has every key, no unused ones, the same
  placeholders, plural shapes and HTML tags as the English text.
- **Usage hook for subagents** (#448): `mcp/claude_usage_hook.py` also runs as a Claude Code `SubagentStop` hook and
  reports each subagent's own transcript (`agent_transcript_path`) as a session of its own; the setup guides
  (*Settings > Agents > Set up*, docs) show both hooks.

### Changed
- **The day plan never changes due dates** (#440): *Plan my day*, *Fill free time* and an agent's day plan set only the
  planned start (new task field `plan_start`, date + time) and the duration. Due date, due time and deadline stay as
  they are; tasks that do not fit are listed as *Does not fit today* instead of being moved. A planned task shows in
  Today with its time, counts as busy for the next plan and can be unplanned in its panel. API: `GET /dayplan` returns
  `nofit` instead of `defer`; a dayplan proposal takes `nofit` (an older `defer` answer is still accepted and only
  listed). A repeating task's next occurrence starts unplanned.
- **Violet is the default accent** (#449): devices that never picked a colour switch to violet; raspberry (the 2.8.0
  default) and every other colour stay selectable, a colour you picked stays. Public list pages use violet too.

### Fixed
- The public list page's text size is in rem like the rest of the app.

## [2.10.0] - 2026-10-02

**In short:** Groups for sharing lists and folders and for tasks "whoever has time"; "Plan my day" fills the free time
between your appointments (built in, or by an agent you approve); an evening review; the real client address behind a
reverse proxy.

### Added
- **Groups** (#441): admins create groups of people under *Settings > Administration > Groups*, optionally synced from a
  sign-in group (OIDC group claim, checked at every login; the members are then read-only). Lists (owner / list admin)
  and whole folders of own lists (also lists put there later) can be shared with a group with a role; members who join
  get access at once, members who leave lose it; a person's role is the higher of their own and the group's. Every read
  path that respects sharing (lists, search, CalDAV, REST API, MCP, News, webhooks, agents) follows automatically.
- **Assign a task to a group** (#441): it shows in *Assigned to me* for every member until one of them *Takes it*
  (task panel, the group chip's menu; participants too; undoable). The sidebar's *Team* lists your groups with their
  open tasks. News: assigned to your group, taken by someone.
- **REST API + MCP** (#441): `GET /api/v1/groups`, `/groups/{id}`, `/lists/{id}/groups`, `PUT` / `DELETE
  /lists/{id}/groups/{group_id}`, `POST /tasks/{id}/take`, the task field `assignee_group_id` and the filter
  `assignee_group=mine`; MCP tools `list_groups`, `list_list_groups`.
- **Plan my day / Fill free time** (#440) in Today: a built-in planner puts your open tasks into the free slots between
  the day's calendar events and timed tasks within your working hours (*Settings > General > Day planning*, default
  09:00-17:00; overdue and due first, then deadlines, due date, priority; 30 minutes for tasks without a duration). A
  timeline preview, entries can be left out, what does not fit moves to the next working day; *Apply* is one undo step.
- **Let an agent plan** (#440): with an online agent, the same input goes out as a proposal of kind `dayplan`; its plan
  opens in the same timeline and only you apply it. Documented in docs/AGENTS.md; MCP `submit_proposal` describes the
  shape, `get_day_plan` / `get_day_review` and `GET /api/v1/dayplan`, `/dayplan/review` give the previews.
- **Daily review** (#440): after your working hours a card in Today with what you finished, what is still open, what you
  moved and a suggestion for the next working day; optionally as a push at a time you choose (default off).
- `KALMIDO_TRUSTED_PROXIES` / `KALMIDO_TRUSTED_PROXY_COUNT` (#445): the reverse proxies whose `X-Forwarded-For`,
  `-Proto` and `-Host` Kalmido believes (default loopback + the Docker bridge gateway 172.17.0.1; `none` = nobody).

### Fixed
- **Security (#445):** behind a reverse proxy every request seemed to come from the proxy (the forwarded client address
  was dropped), so failed-login lockouts (web login, app passwords) hit everyone at once and logs showed the proxy.
  Kalmido now takes the client address from a trusted proxy, and lockouts count per user name and address, per address
  and, as a ceiling, per user name: one attacker can no longer lock a person out. CalDAV and cookies see https from a TLS
  proxy (`X-Forwarded-Proto`).

## [2.9.0] - 2026-10-02

**In short:** Your lists in Reminders, Thunderbird, Tasks.org and other CalDAV apps, both ways, with an app password per
device; OIDC sign-in can be set up in the settings, with admins by e-mail domain and guides for six providers.

### Added
- **CalDAV server for tasks** (#435) at `/dav/` (discovery via `/.well-known/caldav`): every list you see is a VTODO
  calendar for Reminders (iPhone, iPad, Mac), Thunderbird, Evolution, Tasks.org and DAVx⁵ (Tasks.org, jtx Board, OpenTasks).
  PROPFIND, REPORT (calendar-query, calendar-multiget, sync-collection with sync tokens), GET / PUT (If-Match /
  If-None-Match) / DELETE (to the trash), ETags and getctag per list. Synced: title, notes, due date and time (any
  time zone), start, priority, done / won't do, your tags, subtasks (also when a child arrives first), repeat rules
  (completing moves the task on), reminders and the link; everything else a client writes comes back unchanged. Viewers
  get read-only lists, participants only their tasks; moving a task to another list in a client moves it in Kalmido;
  changes show "via CalDAV" in the history (`via: "caldav"` in webhooks and agent events).
- **App passwords** (#435): *Settings > Account > App passwords* (named, shown once, stored with the password KDF,
  revocable, last use and client); failed logins lock out like the login form; never the account password, never an
  agent. Also in the REST API: `GET / POST /api/v1/me/app-passwords`, `DELETE /api/v1/me/app-passwords/{id}`.
- **Settings > Integrations > Calendar apps (CalDAV)**: server, address, user name, a button for a new app password and
  step-by-step guides for iPhone / iPad, Mac, Thunderbird, Tasks.org, DAVx⁵, Evolution and Windows.
- **OIDC set up in the settings** (#438): *Settings > Administration > Sign-in* stores the provider (the client secret
  encrypted with `KALMIDO_SECRET_KEY`), a `KALMIDO_OIDC_*` variable that is set wins for its field; *Check provider*;
  admins by verified e-mail domain (`KALMIDO_OIDC_ADMIN_DOMAINS`); Microsoft Entra's `xms_edov` counts as a verified
  e-mail; auto-created accounts without a usable user name claim are named after the e-mail's local part.
- docs/CALDAV.md (clients, mapping, which proxy paths must bypass a login proxy, Caddy / Authelia / nginx / Traefik) and
  docs/OIDC.md (Authentik, Keycloak, Authelia, PocketID, Google Workspace, Microsoft Entra: redirect URI, scopes, groups).
- Settings: `KALMIDO_CALDAV`, `KALMIDO_CALDAV_DONE_DAYS`, `KALMIDO_CALDAV_HTTP`, `KALMIDO_OIDC_ADMIN_DOMAINS`.

### Security
- CalDAV accepts HTTP Basic only while `PUBLIC_URL` is https (or with `KALMIDO_CALDAV_HTTP=1` on purpose), refuses DTDs
  in request bodies, caps bodies at 1 MB and never reads the proxy header on `/dav`.

## [2.8.0] - 2026-10-02

**In short:** A new look, "Leitstand": one sidebar with grouped navigation instead of the icon rail, a command bar, an
agent band under the list header, ticket numbers in the rows, an own icon set and a raspberry accent, in light and dark.

### Changed
- **One sidebar instead of icon rail + sidebar** (#434): grouped text navigation with the counts right after the labels:
  *Focus* (Inbox, Today, Tomorrow, Next 7 days, Now doable, Waiting, Assigned to me, News), *Views* (Calendar, Timeline,
  Matrix, Habits, Focus, Time tracking, Statistics, Overview, Agents; switched-off modules are left out), *Lists* (a dot,
  the count and the progress of a project), *Filters*, *Tags*, *Team* (the people you share lists with and the agents with
  their status dot), then All, Completed, Trash, Archived, Search and Settings. Every group folds (per device). The tab bar
  setting is for phones only now. When the task panel leaves the list too little room, the sidebar becomes a drawer behind
  the menu button in the header.
- **Command bar** in the header (*Jump, create, ask an agent…*, Ctrl/Cmd K) and in the drawer, plus a *New task* button on
  mouse screens; the view switch of a list (List / Kanban / Timeline / Project overview) is a row of text tabs; the next
  open milestone of a project sits next to its title.
- **Agent band** under the header of a list, a folder and the smart lists (desktop and tablets): every agent with its status
  (ready, working, waiting, offline, error), the task it works on with its ticket number, a thin progress line and the first
  job waiting for your approval with 👍 / ✕ (the same as Approve / Reject in the Agents view). It folds (remembered per
  device); while it is on screen the header leaves out the agent dots. Phones keep the header pill.
- **Rows**: a round status glyph (its colour is the priority; an agent working on the task turns it into an open arc with a
  dot), the ticket number in a mono gutter in lists with tickets, the selected row marked by an accent bar on the left,
  40 px rows on the desktop and 44 px on touch screens.
- **Icons "Punkt"**: an own icon set on a 20 px grid with open arcs, 1.6 strokes and one filled dot per icon; the dot takes
  the accent where an icon stands alone or is active.
- **Colours**: neutral greys and a raspberry accent (#BE185D light, #F472B6 dark; text on it meets WCAG AA). Devices that
  had the old default (mint) switch to the new default once; mint stays selectable and other choices are kept. Sign-in,
  setup and the public list pages use the new colours too.

### Fixed
- The 2.7.2 notes credited the removed refresh button to #432; it was #433.

## [2.7.2] - 2026-10-01

**In short:** Personal agents with setup guides for Linux, macOS and Windows, reactions and Sent / Delivered in the agent
chat, clickable people everywhere, breadcrumbs in the task panel and "Show completed at the bottom" on every list.

### Added
- **Personal agents** (#420): admins can let people create their own agents (*Settings > Agents > Set up > Users may
  create their own agents*, off by default, at most 2 per person by default, default usage limits). A personal agent
  belongs to its creator: only they share lists with it, chat with it, rename, pause, re-token or delete it; it is never
  an admin and gets no Paperless access; other people never find it in their share pickers. Admins see every agent with
  its owner and can pause it (the owner cannot resume an admin pause) or delete it (its lists go to the owner).
  API: `GET` / `PUT /api/admin/agent-policy`, `GET` / `POST /api/my/agents`, `PATCH` / `DELETE /api/my/agents/<id>`,
  `POST /api/my/agents/<id>/token`, `DELETE /api/admin/agents/<id>`.
- **Setup guides** (#420) in *Settings > Agents > Set up* and in `docs/AGENTS.md`: a team agent on a server (sandbox
  user, egress firewall, launcher as a service, token, sharing, limits) and a personal agent on your own computer, each
  for Linux, macOS and Windows; `mcp/agent_launcher.ps1`, a PowerShell port of the launcher.
- **Reactions in the agent chat** (#421): 👍 👎 ❤️ on chat messages; a person's 👍 / 👎 on an agent's message is an
  approval / rejection and sends the agent the event `reaction` with `chat_message`; reactions of agents never approve.
  API: `POST /api/agents/<id>/chat/<message_id>/reactions`, `POST /api/v1/agents/{id}/chat/{mid}/reactions`,
  `POST /api/v1/agent/chats/{user_id}/messages/{mid}/reactions`; MCP tool `react_to_chat`.
- **Chat feedback without the agent's help** (#422): every message says *Sent* or *Delivered* (`delivered_at`, set when
  the agent fetches it by event poll, MCP, webhook or reading its chats); while an online agent has not answered yet the
  chat shows typing dots for up to 90 seconds (longer while it reports *working* or its typing signal); an offline or
  paused agent shows *offline – will answer later*. An open chat refreshes itself every 3 seconds while it waits.
- **People are clickable everywhere** (#418): pictures in the assignee column / menu, rows, comments, members, News, the
  chat and the Agents page open a card: agents with their status, *Open chat* and what they work on; people with
  *Tasks of …* (a filtered view of the lists you see) and *Mention* in the task panel.
- **Breadcrumbs** at the top of the task panel (#424): folder › list › section › parent task, each opens that place
  (scrolled to the section / the parent) and closes the News dropdown.
- **Show completed at the bottom** (#414) on every list (*…* menu, *Sort* menu, list dialog).
- The robot icon leads the agents' status dots, directly before the bell (#417).
- Milestones as markers in the *All* timeline too; drag and drop files into a project's *Project files*.

### Changed
- The list type *Shopping & packing list* (*Checklist*) is gone (#414): only *List* and *Project*. Such lists became
  plain lists with *Show completed at the bottom* on; their items are full tasks again. The API accepts
  `kind: "checklist"` and the boolean `checklist` as deprecated aliases of `done_at_bottom`.
- `mcp/README.md` and the launcher name the current menu path *Settings > Agents*.

- Shared lists: the refresh button left the header (#433); *…* > *Refresh* stays, and when the check for changes has
  failed for more than 30 seconds a small hint says *Offline – last update N min ago* (a tap tries again).

### Fixed
- Phones and foldables: the on-screen keyboard closed right after opening it to add a task, and the timeline could
  rescale when a bar was touched. The layout width of a near-square screen now follows the physical screen orientation
  only (never the viewport) and never changes while you type.
- Project files leave the disk when the sample project is removed or an import is undone.
- Tests: one shared Firefox helper (with the start retry) for the layout suites.

## [2.7.1] - 2026-10-01

**In short:** A Project overview in every project list: description, key links, milestones, project files, members,
status updates and the tracked time in one place.

### Added
- **Project overview** (#410): a tab next to List / Kanban / Timeline in every project list (phones: in "…"; German
  *Projektübersicht*, separate from the *Where is it stuck?* view across all projects). It shows the project's
  **description** (Markdown), **key links** (title + address, ordered, an icon from the address, no favicons fetched),
  **milestones** (name, date, reached; also as markers in the project's timeline), **project files** uploaded on the
  list itself plus Paperless documents linked to it and, read-only, the **attachments of its tasks** with a link to each
  task, the **members** with their roles (with collaboration), the **status updates** with *Set status* and the
  **tracked time** with the budget. Owner, list admins and members change it; viewers and participants read it
  (participants see the files of their own tasks only). Which lists show the overview is remembered per device; the
  list's own view stays.
- Project files use the attachment rules: the size limit of `TASKS_MAX_FILE_MB`, safe file names, images and PDFs
  inline, everything else (HTML, SVG, …) only as a download with a sandboxed CSP; stored below
  `data/attachments/lists/<id>/` (in backups and the data export) and deleted with the list.
- Web API: `GET` / `PATCH /api/lists/<id>/overview`, `/api/lists/<id>/links` (+ `/order`), `/api/lists/<id>/milestones`,
  `/api/lists/<id>/files`, `/api/list-files/<id>`, `/api/lists/<id>/paperless`; `/api/state` lists carry `description`
  and `milestones`.
- Token API + OpenAPI: `GET` / `PATCH /api/v1/lists/{id}/overview`, `/lists/{id}/links` (+ `/order`, `/{link_id}`),
  `/lists/{id}/milestones` (+ `/{milestone_id}`), `/lists/{id}/files` (+ `/{file_id}`).
- MCP: the read-only tool `get_project_overview`.

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

<!-- Versions 1.0.0–2.4.2: released before this repository started (history only; no tags here). -->

## [2.4.2] - 2026-09-30

**In short:** Comments can be read newest first, the *Code* section appears only where it helps, @mentions open a small card
about the person or agent, a folder switches between its list and one Eisenhower matrix of all its lists, each agent can
get all your lists (or every new one) in one step after a clear warning, and a setup guide walks you through running an
AI colleague safely, done by Claude Code or by hand.

### Added
- **Comment order** (#386): *Oldest first / Newest first* next to *With activity* in the task panel, saved per person on
  all devices (user setting `comment_order`: `old` | `new`). Newest first reverses the comments and puts the comment box
  right above the newest one instead of the sticky bottom edge, so answering needs no scrolling.
- **Clickable @mentions** (#389): a mention in a comment, and `@Name` or `@username` of a list member in a description, is
  a button (never inside code or links; names nobody has stay plain text). It opens a card with the avatar, the name, the
  role in the list and the person's other open tasks there, plus *Assign this task* and *Mention*; for an agent its live
  state, *Open chat* and *Jobs*. List members in the web state carry `username`.
- **Folder matrix** (#390): a folder view has *List | Matrix* in the header (on a phone *Show as matrix* in "…"); the
  matrix shows the tasks of all lists of the folder, subfolders included, each with its list chip, and *Show as list* /
  the switch lead back.
- **Share with an agent in bulk** (#391): per agent in *Settings > AI colleague*, *Share all existing lists* (every list
  you own with role *Member*; never the inbox or archived lists; lists you stopped sharing with that agent in the table
  stay out until you share them there again) and the switch *Share new lists automatically* (off by default; new lists,
  project types, templates and projects from an agent proposal). Both ask first and say that the agent then sees private
  lists too. API: `GET /api/agents/{id}/share`, `POST /api/agents/{id}/share-all`, `PUT /api/agents/{id}/autoshare {on}`;
  stored per person in the server-only user setting `agent_share`.
- **Setup guide** (#392): *Settings > AI colleague > Setup guide* with two ways: *Let Claude Code set it up* (a prompt
  filled in with this server, you as the only person who instructs the agent, and an editable token file and Linux user;
  one click copies it) and *Do it yourself* (the steps with the key commands). The full guide is the new
  [docs/AGENT-SETUP.md](docs/AGENT-SETUP.md): the agent account and token, a Linux user without sudo, an nftables egress
  firewall, Claude Code, the MCP server behind a wrapper that reads a 0600 env file, a CLAUDE.md template, a
  `.claude/settings.json` allowlist, an event monitor with back-off, autostart with a systemd user unit and
  `mcp/agent_launcher.sh`, the usage hook and a test checklist (mention, chat, kill switch, 7 prompt-injection cases).
  Linked from the README, docs/AGENTS.md and docs/AGENT-SECURITY.md.

### Changed
- **Code section only where it helps** (#387): in lists with a connected repository it shows when the task has linked
  pull requests or commits, is a bug or a feature, or is assigned to an agent; otherwise the task's "…" menu offers
  *Link code…* (copies the branch name). Lists without a repository never show it. Agent events and the API still
  carry `repo` as before.

### Removed
- The *Share a list with an agent…* button in *Settings > AI colleague* (#391): the list table below does the same.

## [2.4.1] - 2026-09-30

**In short:** Admins set how each AI colleague runs (model, auto-compact, a nightly fresh restart, *Reset now*) and
Kalmido hands it to the agent's host; exactly one agent tidies up a list; the chat shows whether the agent is typing,
working on a task, waiting for you or offline; the *Wake* buttons are gone and nothing destructive sits next to *Send*.

### Added
- **Agent runtime settings** (#377): *Settings > AI colleague > (agent) > Runtime*: model (free text with the suggestions
  opus / sonnet / haiku or a full model id, empty = the agent's default), auto-compact on / off with a threshold
  (10-100 %), a nightly fresh restart (HH:MM, server time zone) and *Reset now*. Kalmido only stores them:
  `GET /api/v1/agent` returns `runtime {model, autocompact, autocompact_pct, nightly_reset, reset_seq, timezone}`, a
  change sends the event `runtime_changed`, *Reset now* raises `reset_seq` and sends `reset`
  (`POST /api/admin/agents/{id}/reset`, `PATCH /api/admin/agents/{id} {runtime}`); MCP `get_agent` includes it. The
  host contract is in docs/AGENTS.md (*Runtime settings*), with a reference launcher for Claude Code,
  `mcp/agent_launcher.sh` (`--model`, `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` / `DISABLE_AUTO_COMPACT`, always a fresh
  session, restarts on a change, on *Reset now* and nightly; a systemd unit recipe).
- **Agent status in the chat** (#375): the chat header shows typing dots while the agent writes to you and its state in
  words: *working on #51* (a link to the task), *working*, *waiting for you*, *ready*, *paused*, *limit reached*,
  *offline* (no event poll for 5 minutes; stored at most every 30 seconds). New `POST /api/v1/agent/typing
  {chat_user_id}` (10 seconds, the answer ends it; MCP `chat_typing`); the agent objects carry `online`,
  `last_poll_at`, `poll_age`, `typing` and `my_job`.

### Changed
- **One tidy agent per list** (#379): *Tidy up by* in the list dialog and in the *AI colleague* list table picks the
  one agent (with edit rights) that tidies up a list; only it gets `tidy` events, another agent's suggestion or
  `POST /api/v1/tasks/{id}/tidy` is refused (`403`). Default: the first agent with edit rights; lists that had tidy on
  keep the agent that got their events first (one-time migration). API / MCP / events: `tidy_agent_id`
  (`PATCH /api/lists/{id} {tidy_agent_id}`).
- **Task panel footer** (#385): *Delete* and *Track time* moved from the footer (on a phone *Delete* sat right below the
  comment box's *Send*) into the task's *…* menu (*Delete* with undo); a running timer still shows there as its pill.
- Neutral wording (#384): code comments, the README and the changelog describe what Kalmido does without naming other
  apps (the importers keep their names).

### Removed
- **Wake agent** buttons (#376) in the task panel, the Agents view and the chat. `POST /api/tasks/{id}/wake` and
  `POST /api/agents/{id}/wake` stay, documented for agents without an event loop.

## [2.4.0] - 2026-09-30

**In short:** Folders get subfolders, new projects start from a type (Agency, Software / AI dev, Personal) or from your
own project template with dates counted from the project start, software projects get bug / feature / task tickets,
and anything can be captured into the inbox from anywhere: `q`, Ctrl+Space, the app icon menu or a bookmarklet.

### Added
- **Subfolders** (#361): a folder path of at most two levels (`Clients/Company X`), per person as before (owner row,
  member row, the order in the setting `folders`). Sidebar tree (a folder's lists, then its subfolders), folded folders
  in the new user setting `folders_closed` (all devices), drag and drop of lists into subfolders and of subfolders into
  other folders or to the top level, folder menu *New subfolder…* / *Move into a folder…* / *Move to the top level*;
  deleting a folder moves its lists and subfolders up one level. The folder view shows the lists of the subfolders too,
  with a header per subfolder; the command palette lists folders; the list dialog takes `Folder / Subfolder`. API v1:
  `folder` is the path; deeper paths are refused (`400`).
- **Project types** (#243): *Agency* (sections Request / Concept / Production / Approval / Billing, fields Client and
  Budget h, time tracking), *Software / AI dev* (Backlog / Next / In progress / Review / Done, Kanban, ticket types,
  dependencies, a next-steps dialog for the repository and a coding agent), *Personal* (Ideas / Planning / To do). Names
  in the person's language; the modules a type needs are switched on (`modules_on`). In the new list dialog, the command
  palette (*New project…*), the setup (*Start with a project*) and the first welcome card. `POST /api/lists {ptype}`,
  `POST /api/v1/lists {project_type}`.
- **Project templates with relative dates** (#328): saving a project list keeps its dates as days after the project
  start, its dependencies (node keys), ticket types and *Move dependent tasks along*; using it asks for the start and
  an optional end (`POST /api/templates/{id}/apply {start, end}`: the dates are stretched or squeezed to fit).
- **Ticket types** (#340): per list (`tickets`, owner), a task `ttype` / API `type` bug | feature | task with an icon
  chip, a select in the task panel, quick add `!bug` / `!feature` / `!task` (`!fehler` / `!funktion` / `!aufgabe`), a
  filter, `GET /api/v1/tasks?type=`, MCP `type`, `type` in agent events and webhooks. New bugs / features with empty
  notes get the list's template (`ticket_tpl`, editable) or the built-in one in the person's language.
- **Quick capture** (#187): `q` / Ctrl+Space open a capture box anywhere (inbox unless a list is named), the app shortcut
  *Quick add* (`/?action=capture`), and `/capture`: a bookmarklet popup that saves the page title and address into the
  inbox with the normal session (the page stays through a sign-in), plus how to bind a system-wide key.

### Changed
- A `/` in an existing folder name now means a subfolder: existing names with a slash are kept as they were (the slash
  becomes the look-alike `∕`, once, for every person's folders); imported folder names likewise.
- List templates keep the dependencies between their tasks (also the ones without relative dates).

## [2.3.0] - 2026-09-30

**In short:** Ask an AI colleague for a proposal instead of letting it create things on its own: a whole project from a
briefing, subtasks for a big task, a sorted inbox, or tasks (with assignees) from meeting notes. The agent gets exactly
what you send, answers with one structured proposal, and you tick, edit and apply it: everything belongs to you and one
undo takes it back.

### Added
- **Agent proposals** (shared by #260-#263): a person asks an agent from the app; Kalmido creates a job (kind `project`,
  `subtasks`, `triage` or `extract`, shown in the Agents view) and sends the event `job_request` with exactly the input of
  the request dialog. The agent answers with `POST /api/v1/agent/jobs/{id}/proposal` (MCP `submit_proposal`, new
  `get_job`): validated per kind (at most 200 entries, 256 KB, text lengths, ids only from the input, no dependency
  cycles; `400` with the reason, `unknown_field`, `413`). The person gets a News item and a push *Proposal ready* (new
  notification row, on by default) and reviews it in a dialog (from the push, the News item or the job): a checkbox per
  entry (a task's subtasks follow it), inline title / date / section / assignee / list, *Apply n entries* or *Discard*.
  Applying creates / changes everything as the person (owner, creator, history *created the task from a proposal by
  <agent>*), one undo / redo step (`POST /api/proposals/{id}/undo` / `redo`: a new project list nobody touched is
  removed, changed entries stay and are named). The agent gets a `job` event (`approve` with the counts, or `reject`).
- **Who may ask which agent**: per agent *Proposals for* (Settings > AI colleague): people who share a list with it
  (default; instance admins count as sharing), everyone, or nobody. At most 10 open requests per person.
- **#260 Project from a briefing**: *New project from briefing…* (Lists > +, command palette): pasted text or a .txt /
  .md file (PDF: not yet), optional folder; the proposal brings sections, tasks with dates, priorities, subtasks and
  dependencies; applied as a new project list owned by the person, optionally shared with the agent.
- **#261 Break down a task**: *Break down with <agent>…* in the task menu and the palette, with an optional hint; the
  agent sees the task's title, notes and subtask titles; subtasks with dates, estimates (duration) and dependencies.
- **#262 Sort the inbox**: select inbox items (bot button in the selection bar) or *Sort the inbox with <agent>…* (all
  open inbox items, at most 100); the person ticks which of their lists the agent may suggest (default all). Per item:
  list, section, tags, priority, date, a better title.
- **#263 Tasks from notes**: *Tasks from notes…* in a list's menu and the palette; the agent gets the notes and the
  names of the list's people and proposes tasks with assignees, dates and sections (a new section is created on apply).
- `GET /api/v1/agent/jobs/{id}`; jobs carry `kind` and `proposal_state`.

### Privacy
- An agent never gets access to the inbox or unshared lists through a proposal: the input is exactly what the person
  sent, stored with the job and removed with it after 30 days (also when the person is deleted). Only the person who
  asked sees the proposal.

### Changed
- Service worker cache v65.

## [2.2.1] - 2026-09-30

**In short:** Admins see every API call an AI colleague makes in an activity log (route, status, duration; never
content), with filters, denied calls marked and a CSV export. The REST API now names unknown JSON fields instead of
ignoring them, and a new guide, docs/AGENT-SECURITY.md, explains how to run an agent safely: threat model, host sandbox
recipe and the prompt-injection checklist we tested with.

### Added
- **Agent audit log** (#358): every request made with an agent's token (REST API, agent endpoints, MCP calls) is one row
  in the new table `agent_audit`: time, agent, method, route template (`/api/v1/tasks/{tid}`), status, task / list id
  from the path or the body, duration. Never bodies or query values. Denied calls (401 / 403 / 429: paused agent, scope,
  rate or usage limit) are logged and marked. Requests only queue the row in memory, a writer thread stores batches every
  2 s (cheap on a Pi). Retention `KALMIDO_AUDIT_DAYS` (default 90, `0` = off), removed hourly.
- **Settings > AI colleague > Activity log** (admins): newest first, filter by agent, status class (2xx / 4xx / 5xx /
  *Denied*) and day (the app's date picker), *Load more*, CSV export of everything that matches; phone layout with the
  route on its own line. Non-admins see nothing of it.
- **API**: `GET /api/admin/agents/audit` (all agents) and `GET /api/admin/agents/{id}/audit` (admin session; `status`,
  `day`, `before`, `limit`, `format=csv`), `GET /api/v1/admin/agents/{id}/audit` (scope *admin-read*, cursor pages; in
  the OpenAPI spec as `AuditPage`).
- **docs/AGENT-SECURITY.md** (#357): threat model, what Kalmido enforces, a host sandbox recipe for Claude Code (own
  user, nftables egress rule by user id, token in a 0600 env file behind a wrapper, `dontAsk` permissions, CLAUDE.md rules
  template, back-off in the event loop), the 7-case prompt-injection checklist with OS and kill-switch checks, and our
  results. Linked from SECURITY.md, docs/AGENTS.md and the README.

### Changed
- **Unknown fields** (#359): the REST API answers unknown JSON fields with `400` and
  `{"error": {"code": "unknown_field", "message", "fields": [...]}}` everywhere it refused them before with a plain
  `invalid`; comments with extra fields now get `unknown_field` too (before: *Expected {"body": "..."}*). `content` is
  accepted as an alias of `notes` on task create / update (both with different values: 400). The web API (`/api`, the
  app's own) stays lenient but names ignored fields in the response header `X-Kalmido-Unknown-Fields` and logs one
  warning per endpoint and set of names per hour (never values); it accepts `notes` as an alias of `content`.
  **Compatibility:** a v1 client that sent junk fields to an endpoint that refused them already gets the same 400 with a
  new `code`; clients that check `code == "invalid"` for these cases should also accept `unknown_field`.
- `POST /api/lists` takes `dep_shift` (*Move dependent tasks along*) at creation (before, only `PATCH` set it).
- CI: the test suites run in 3 parallel shards (`tests/run_all.sh --shard N/3`), each well under 25 minutes; the
  overall result still needs all of them.
- Service worker cache v64.

## [2.2.0] - 2026-09-30

**In short:** Project lists meet GitHub and Gitea / Forgejo: connect a repository and the pull requests (with CI),
commits and branches show up at their tasks, `fixes #123` in a merged pull request completes the task. It works by
polling, so a server behind a VPN or in the office LAN needs no public address. And tickets can go to a coding agent: it
gets the repository and a branch name with the assignment and merges only after a person's 👍 on its *Ready to merge*.

### Added
- **Git integration** (#271, *Edit list > Repository*, project lists): the list owner and list admins connect up to five
  repositories: GitHub (github.com or GitHub Enterprise) and Gitea / Forgejo, as `owner/name` or the repository's
  address; the repository is read at once, so a wrong name or token shows in the dialog. The access token (read-only is
  enough, optional for public repositories) is write-only and encrypted with `KALMIDO_SECRET_KEY` like the Paperless
  tokens of 2.1.0; without the key only tokenless repositories can be connected. Agents cannot connect repositories or
  see tokens. Everyone in the list sees the results; *Check now* for everyone, token / webhook / remove for owner and
  admins.
- **Polling** in a background thread (every 180 s per repository, `KALMIDO_GIT_POLL`; a few repositories per tick):
  the newest 30 pull requests, the newest 30 commits of the default branch, the own commits of up to 3 branches of open
  pull requests (compare with the default branch) and the CI of up to 5 open pull request heads (combined status +
  GitHub check runs). ETag / `If-None-Match` (a `304` costs GitHub no rate limit), a pause until the reset when fewer
  than 25 requests are left or on `403` / `429` rate limits, back-off on errors (interval × 2^failures, at most an
  hour), no redirects, the SSRF guard of calendar subscriptions (internal servers only on the admin allow-list).
- **Matching** (tasks of the connected list only): `#<id>` in a commit message, pull request title or description;
  branches `kalmido-<id>…`, `task-<id>…`, `<id>-slug` (the last path segment). Only linked pull requests / commits are
  stored (new tables `git_conns`, `git_prs`, `git_commits`, `git_links`, `git_closes`).
- **Task panel > Code** (after the fields, before the comments): linked pull requests (state, title, author, CI icon,
  link) and the latest commits (short sha, message), a button that copies the branch name `kalmido-<id>-<slug>`, *<agent>
  is working on it* while an assigned agent works on the task. **Row chip** with the pull request and its CI. History
  lines when a linked pull request is opened, merged or closed (not for what already existed at the first check).
- **Keywords:** `fixes` / `closes` / `resolves #<id>` (also fix, fixed, close, closed, resolve, resolved and German
  `erledigt`) in a merged pull request or a default-branch commit complete the task, once per task, only for changes
  after the connection; the history names the pull request / commit and offers *Undo* (`POST /api/tasks/{id}/git-undo`).
- **Optional inbound webhook** per repository (off by default): `POST /api/hooks/git/<id>`, signed with a per-repository
  secret (shown once, sealed) as `X-Hub-Signature-256` (GitHub) or `X-Gitea-Signature` / `X-Forgejo-Signature`; it
  only triggers the next check at once, its body is not used.
- **Hand a ticket to a coding agent** (#339): task events and `get_task` in a connected list carry `repo` (provider,
  web / API address, owner / name, default branch, a suggested branch, the linked pull requests with CI and commits).
  An agent's comment with `suggestion: {kind: "merge_request", pr_url, summary}` (only agents, only pull requests of a
  connected repository; the pull request is linked at once) shows as *Ready to merge* with the pull request, CI and
  *Approve* / *Reject* for approvers (list owner, list admins, the assignee, admins). 👍 / 👎 by an approver sets it
  approved / rejected once and sends the agent the `reaction` event with `approval` and `merge_request`; *Apply* is
  refused. Kalmido never merges: the agent does, with its own credentials.
- **API:** `GET /api/v1/lists/{id}/repos`, lists carry `repos`, `GET /api/v1/tasks/{id}` carries `code` and `repo`, tasks
  carry `code`; OpenAPI (`Repo`, `Code`, `MergeRequestInput`). Web app: `GET` / `POST /api/lists/{id}/repos`,
  `PATCH` / `DELETE /api/repos/{id}`, `POST /api/repos/{id}/refresh`; the timeline carries `approver`.
- **MCP** 2.2.0: `list_repos`, `request_merge_approval`; `get_task` documents `code` / `repo`.
- **Docs:** README *Git integration*, docs/AGENTS.md *Coding agent workflow* with a sample `CLAUDE.md` for a project
  agent, docs/API.md, mcp/README.md.
- **Tests:** `p220_api_test.py`, `p220_ui.js` against a fake GitHub + Gitea inside the test container (`fake_git.py`).

### Changed
- Service worker cache v63.

## [2.1.2] - 2026-09-30

**In short:** Lists can change hands: the owner transfers a list to another person and stays in it as a list admin, and
admins take over lists whose owner is an agent or a disabled user, which nobody could manage before. Agents get an
editable username and profile picture and appear in the user list.

### Added
- **Transfer ownership** (#349, *Edit list > Sharing > Transfer ownership…*, with a confirmation): the owner hands the
  list to another active person, a member or anyone they could share with. The old owner becomes a member with the role
  *Admin* (an agent: *Member*, agents are never list admins) and keeps the list where it was in their sidebar; the new
  owner's member row goes, they keep its folder, place and view (not a member before: the end of their sidebar, top
  level) and get a News item (*… made you the owner of the list …*, event *Lists shared with me*). Agents never become
  owners and never transfer; inboxes are never transferred (409).
- **Admin takeover** (#349): instance admins take over a list whose owner is an agent or a disabled user, for
  themselves or another person: *Settings > Administration > Lists owned by agents or disabled users > Take over*, and
  *Take over…* in the list dialog. A non-admin cannot; an admin cannot take a list of an active person.
- **History** of a list's ownership (new table `list_activity`), shown under *Sharing*: *Ownership transferred from X to Y*.
- **API:** `GET /api/lists/{id}/owner` (owner, whether you may transfer / take over, the candidates, the history),
  `POST /api/lists/{id}/owner` and `POST /api/v1/lists/{id}/owner` with `{user_id}` (scope write; agent tokens always
  403), `GET /api/admin/lists/orphaned` (admins).
- **Agents** (#346): admins change an agent's username (checked, unique; its tokens keep working) and profile picture
  (presets, an own photo, `POST /api/admin/agents/{id}/avatar`, or none) in its dialog (*Settings > AI colleague*);
  `PATCH /api/admin/agents/{id}` takes `username` and `avatar_preset`.

### Changed
- *Settings > Administration > Users* lists agents too, with the *Agent* badge and *Managed under AI colleague*, which
  opens the agent dialog instead of the user dialog.
- Service worker cache v62.

## [2.1.1] - 2026-09-30

**In short:** Agents report their model usage (tokens, optionally the cost) and you see it per agent, day, task, list
and model in *Settings > AI colleague > Usage*, as a card in the Agents view and on the task. Admins can give each agent a
soft limit (News + push at 80 % and 100 %) and a hard limit that pauses its API calls until the next day or month. A
Claude Code hook reports a session's usage by itself.

### Added
- **Usage reports** (#326): `POST /api/v1/agent/usage` (agent tokens only) with model, input / output / cache tokens,
  optional cost in USD, the task / list / job it was for and a short note (at most 200 characters). Only numbers and ids
  are stored, never prompt content. `GET /api/v1/agent/usage?from=&to=&group=day|task|list|model` for the agent itself.
  MCP tools `report_usage` and `get_usage`. "Tokens" = input + output + cache writes; cache reads are listed apart.
- **Usage dashboard** (#326, *Settings > AI colleague > Usage*): today / 7 days / 30 days per agent, the last 30 days as
  a chart, top tasks (click opens the task), per list and per model, in tokens or cost (when reported), for all agents or
  one. Admins see every agent; everyone else sees the agents they share a list with, counted only in the lists they see
  (participants: their tasks); what the viewer cannot see is counted without a name. A compact card in the **Agents**
  view, and an *AI usage* line in the task panel on tasks with reports.
- **Usage limits per agent** (#326, admins, agent dialog; default none): per day or month, in tokens or USD. The soft
  limit sends the admins a News item and a push at 80 % and 100 % (once per period; new notification event *An agent
  reached a usage limit*, admins only). The hard limit tells them too and then answers every API call of the agent with
  `429`, a clear message and `Retry-After`, except reporting usage, the status and `GET /agent`, until the period rolls
  over or an admin raises it; the agent shows *limit reached*. `GET /api/v1/agent` has `usage_limit`.
- **Claude Code usage hook** (`mcp/claude_usage_hook.py`): a Stop hook that sums the usage of a session's new assistant
  messages from its transcript (state per session, one report per model, optional cost from a price table, the task of
  the agent's status) and reports it; it never blocks the session. Setup in docs/AGENTS.md.

### Changed
- The MCP server reports version 2.1.1 and accepts numbers (not only integers) for number arguments.
- CI also runs the usage hook test in the quick checks job; service worker cache v61.

## [2.1.0] - 2026-09-30

**In short:** One table decides what notifies you (every event as News, as a push, both or neither), and every list
gets its own bell (*All activity*, *Default*, *Mute*). Paperless can have several connections: server ones where each
person enters their own token, and private ones only their owner sees, with tokens that are write-only and encrypted.
Tasks can wait on someone outside with a follow-up day that reminds you, and tells your AI colleague.

### Added
- **Notification settings** (#317, *Settings > Notifications > What notifies you*): a matrix of events x *News* /
  *Push*. Events: comments on my tasks (created or assigned), **replies to my comment** (the comment right before is
  mine, new), comments on tasks I follow (I commented on them), mentions, assignments, **new tasks in shared lists**
  (created by someone else, new), completions by others, project status, shared lists, unblocked tasks, **an agent
  waiting for my approval** (News new), the **follow-up day** (below) and reminders (push only). A comment counts once,
  as the first of mention, my task, reply, follow. The defaults keep the behaviour of 2.0.8 exactly (existing News
  choices included); of the new ones only replies and follow-ups are on. Pushes for project status and shared lists
  are new (off by default). News and pushes are filtered in one place on the server. The old setting `news_kinds`
  stays the News column of the events it knew; the rest is the setting `notify`.
- **A bell per list** (#317, list menu > *Notifications*, list dialog), only for me: *All activity* (every comment, new
  task and change of that list as News and push), *Default* (the matrix) or *Mute* (only mentions of me and tasks
  assigned to me come through, following the matrix). Reminders and follow-ups are never muted. A muted list shows a
  crossed-out bell in the sidebar. `PUT /api/lists/{id}/bell`; lists carry `bell`.
- **API:** `GET /api/v1/me` has `notifications` (`events`, `lists`); `PATCH /api/v1/me/notifications` changes them.
- **Several Paperless connections** (#180). The connection from the environment keeps working unchanged (legacy,
  *Paperless access*). New:
  - *Server connections* (admins, *Settings > Users > Paperless connections*): name + address, **no shared token**,
    and who may use it; every such user enters their own API token (*Settings > Integrations*), so Paperless'
    permissions apply per person. A new address deletes the stored tokens, taking someone off deletes theirs.
  - *Personal connections* (*Settings > Integrations > Add my own connection*): name, address, token; only the owner
    sees and uses them. Admins can neither see nor grant them; no API answer shows them to anyone else.
  - Tokens are **write-only** (only "•••• set" is ever shown) and **encrypted at rest** (AES-GCM) with the new
    environment variable `KALMIDO_SECRET_KEY` (32 random bytes, base64), which never goes into the database or a
    backup. Without it no token can be stored (409 with a hint; the admin settings say so). **Losing the key means
    everyone enters their tokens again.**
  - Personal connections go through the SSRF guard of the calendar subscriptions (public addresses, internal hosts only
    on the admin's allow-list); no Paperless request follows a redirect, so a token only reaches its own address.
  - Linking and *Send to Paperless* ask for the connection when there is more than one. Links remember it (links from
    before 2.1.0 belong to the environment connection); people who cannot use it see "Paperless document" only, in the
    task, its history and the JSON export. The export lists my own connections without tokens.
- **Waiting on external** (#335, German *Warten auf Extern*): task menu > *Waiting on external…* with a note (who /
  what) and a follow-up day. An hourglass chip on the row, a bar in the task panel (one click ends it, with undo), the
  smart view *Waiting on external* in the sidebar while there are such tasks. On the follow-up day (at the all-day
  reminder time) the person it is for gets a push *Follow up* and a News item, and every agent that follows the task
  the new event **`followup_due`**. API: `PUT` / `DELETE /api/v1/tasks/{id}/waiting`, `GET /api/v1/tasks?waiting=true`,
  `waiting` on every task; MCP `set_waiting`, `clear_waiting`, `list_waiting` (and `list_tasks` `waiting`).

### Changed
- *Settings > Notifications > News* (the checkboxes of 1.9.0) became the News column of the matrix.
- Service worker cache v60.

### Upgrading
- Nothing is required. To use server or personal Paperless connections, set `KALMIDO_SECRET_KEY` (see `.env.example`)
  and keep a copy of it somewhere safe.

## [2.0.8] - 2026-09-30

**In short:** Sort any view by *Created*, answer a comment straight from its notification, see and change which agent
sees which of your lists (and its tidy mode) in one table, pick values on a phone from app-style sheets instead of the
system dropdowns, a sloth in the Android notification badge, and agents that need fewer API calls.

### Added
- **Sort: Created** (#319, German *Erstellt*) in the sort menu of every view, *All* included: newest first; picked
  again while it is on, oldest first (the item says which). While it is on, the rows show the day each task was created.
  Stored per view like the other sort modes; a manual drag switches back to *Priority, then manual*.
- **Reply on comment pushes** (#331, German *Antworten*): a comment or mention notification carries *Reply* (opens the
  task with the comment box focused; on a phone with the Details / Comments tabs, the Comments tab) and *Done*
  (completes it in the background, like the reminder's button); a completed task gets *Reply* alone, the summary of a
  burst of comments gets both. Reminders keep *Done* + *Snooze*; at most two buttons, since some platforms show no more.
  The link `#reply/<id>` works on its own too.
- **Settings > AI colleague: your lists at a glance** (#321): every list you manage in one table. *Agent sees it*: one
  chip per agent, a click shares the list with it (role Member) or, after a confirm, ends the sharing. *Tidy up*: off,
  suggest or automatic, the same setting as in the list dialog, where an agent is in the list.
- **Agent API** (#333, asked for by an agent): task events (`mention`, `comment`, `assigned`, `tidy`, `reaction`, `wake`
  with a task) carry the task's newest 20 comments (`task.comments`, oldest first, texts over 2,000 characters cut,
  `task.comments_total`) and the list's sections and `agent_tidy` (`list.sections`, `list.agent_tidy`), so an agent
  needs no `get_task` / `list_lists` round trip. `GET /api/v1/lists` (and MCP `list_lists`) include every list's
  sections `[{id, name}]`. `GET /api/v1/tasks?fields=compact` returns only id, title, list, section, parent, status,
  due, priority, tags, list tags and assignee; MCP `list_tasks` has `compact` (not given: pages of more than 25 tasks
  come back compact). Everything is additive; old clients keep working.

### Changed
- **Pickers on phones** (#323): a `<select>` opens an app-style bottom sheet like the app's menus: the field's name on
  top, the options with their emoji, icon or avatar, a check on the current value, a search field above 10 options,
  arrow keys / Home / End / Enter / Esc. One enhancer covers the task panel (list, section, assignee), the dialogs and
  the settings. It stays the native select on the desktop, for `multiple` / sized / disabled selects and those with
  fewer than two options, inside a popover or sheet itself (e.g. the date picker's repeat and duration) and wherever
  `data-native` is set.
- **Agent chat on a phone** (#320): sending a message closes the keyboard, so the answer gets the screen; the desktop
  keeps the focus in the box, and a message that could not be sent keeps it everywhere.
- **Notification badge** (#325, `static/badge-96.png`, Android's small status-bar icon): the check with the hanging
  sloth of the app icon as a white silhouette, simplified to read at 24 dp.
- Service worker cache v59.

### Fixed
- `mcp/README.md` still sent admins to *Settings > Administration > Agents*; agents live in *Settings > AI colleague*
  since 2.0.5. `list_lists` promised sections that `GET /api/v1/lists` did not return until now.

## [2.0.7] - 2026-09-29

### Fixed

- Private lists (with collaboration on) show the folded **History** of a task again, as up to 2.0.5: every change,
  your own included, for example "imported the task from Todoist". It stays separate from the comments, so personal
  notes still have no activity lines between them.
- Tests: the new users' `features_rev` is 9 since 2.0.6 (the *Comments* module), and the migration test checks that a
  user already on revision 9 who switched comments off keeps them off.

## [2.0.6] - 2026-09-29

**In short:** Comments are for everyone now, as personal notes in private lists too, with their own *Comments*
module; they sit at the end of the task panel with the comment box always at the bottom edge. The desktop rail shows
exactly your tab bar, *No date* reaches the roadmap and the calendar timeline, focus sessions and the stopwatch get a
card, and the calendar and multi-select have keyboard shortcuts.

### Added
- **Comments as personal notes** (#315): comments no longer need collaboration or a shared list. In private lists and
  with collaboration off they are timestamped notes: no @mentions, no News, no pushes, no history of your own changes
  (changes others made, e.g. through the API or a public link, still show). Old comments of lists that are no longer
  shared are normal and editable again. Checklists have no comments.
- **Module *Comments*** (German *Kommentare*) in *Settings > Modules* and in the setup, on by default (also for
  existing accounts). Off: no comment UI anywhere (the comments stay stored), new comments are refused (409, also
  `POST /api/v1/tasks/{id}/comments`), no comment News or pushes for you. With collaboration on and comments off,
  sharing, assigning, the history and the other News keep working. `GET /api/v1/me` reports `features.comments`.
- **"No date" in the roadmap and the calendar timeline** (#189): in an open list of the roadmap a folding group
  *No date* with one row per undated task; click a day to give it a due date, drag for a range (touch: tap, hold and
  drag). A *No date* chip switches it (on by default, stored with the roadmap settings). The calendar's timeline gets
  the *No date* switch with the count in its bar.
- **Focus session and stopwatch as a card** (#190) on the time page, like the time-tracking timer: live time, task,
  list, start, planned minutes, Pause / Resume, Stop and a link to *Focus*; both cards when a timer runs too.
- **Keyboard shortcuts** (#191): calendar `1` month, `2` week, `3` day, `4` timeline, `←` / `→` previous / next,
  `.` today; multi-select Ctrl/Cmd+A selects every task of the view, Shift+↓ / Shift+↑ (or Shift+J / K) extend the
  selection, Shift+X toggles the focused task, then Space / X completes, M moves, D changes the date of the selection,
  Esc clears it. All in the `?` overview.

### Changed
- **Task panel reordered** (#316, #322): description, subtasks, dependencies, tags, attachments, Paperless, the
  fields (list, section, link, assignee, agent), custom fields, time, and the comments with the history at the end. The
  comment box sits at the bottom edge of the panel (desktop and phone) and stays visible while you scroll; one line
  until you use it. Comments are no longer folded to the newest one (2.0.2 / 2.0.3): all show, oldest first; opened
  from a comment (News, a push), the panel scrolls to the newest.
- **The desktop rail follows the tab bar setting** (#314): exactly its items in their order, then every switched-on
  module that is not in it; search and settings at the bottom unless you placed them. Statistics, time tracking,
  overview, agents, search and settings are no longer hidden in the rail and no longer repeated in the desktop
  sidebar, which keeps lists, folders, filters, tags and All / Completed / Trash. The phone drawer and tab bar are
  unchanged. *Agents* can be added to the tab bar.
- **Tablets in portrait** (#188, under 900 px wide but at least 600 × 600): the composer at the bottom of the list,
  right above the tab bar, instead of the "+" button; "N" focuses it. Phones keep the "+".

### Fixed
- **"Share a list with an agent…"** (#318) in *Settings > AI colleague* did nothing: the list menu opened behind the
  settings dialog. Menus opened inside a dialog now show above it (phone and desktop).
- Tests: the harness ignores a late rejection after a window was closed only when it is exactly that (a TypeError from
  the closed window's own scripts), no longer every app error (CI showed `loadJobs()` → `renderView()` in p200_ui).

## [2.0.5] - 2026-09-29

**In short:** Admins can empty the trash of shared lists they work in, notifications handled on one device disappear
from the others, and the AI colleague (agents) gets its own settings tab.

### Added
- **Settings > AI colleague** (German *KI-Kollege*). Everything about agents in one tab: what an agent is and how to
  connect one, the *Agents* module switch (the same switch as in *Modules*, both stay in step), which lists an agent
  sees (exactly the lists shared with it) with a *Share a list with an agent…* button that opens the list dialog at
  *Sharing*, and the agents themselves. Admins add, edit, test and pause agents here (moved from *Administration*);
  everyone else sees the status of the agents that work in their lists. Also in the command palette.
- **Notifications close on your other devices.** When you complete a task, open it or read its News item on one
  device, its notification disappears from your other phones and computers. Android and desktop browsers get a short,
  rate-limited "close" push (only for notifications that were really sent there); on iPhone and iPad (Apple does not
  allow such silent pushes) the handled notifications are closed with the next notification that arrives.

### Changed
- **Emptying the trash as an admin.** Instance admins now also delete for good what is in the trash of shared lists
  of other owners where they may edit (for example lists of an agent). For everyone else the owner rule stays: those
  items remain in the trash, the trash marks them (*stays*) and says how many stay; after *Empty* a message tells how
  many items were left and why. `DELETE /api/trash` answers `{deleted, kept}`.

## [2.0.4] - 2026-09-29

**In short:** The Flow marker "Next" becomes *Ready to start*, appears only where tasks actually wait on each other
and explains itself on a tap; the project status picker shows every status in its colour.

### Changed
- **Flow: *Ready to start* instead of *Next*** (German *Startklar*). The marker on the first task of a section that
  waits on nothing now shows only when at least one open task in the view has a dependency (*Waiting on*, inside or
  outside the view); in lists without dependencies the Flow order stays the same, just without a marker. Tap or click
  the marker (also on phones, also with the keyboard) for a short explanation: it waits on nothing open and is the
  first task in the flow order (dependencies, then date, then priority). The tap does not open or tick the task.

### Fixed
- **Project status picker: status colours.** The options in the *Project status* dialog showed grey dots; each one
  now has the colour of its status pill (light and dark theme).

## [2.0.3] - 2026-09-29

**In short:** The iPhone home-screen app no longer leaves an empty band under the tab bar, the comment box stays
visible when the comments are folded, and News can show only the unread items.

### Added
- **News: *Unread only*** next to *All | Mentions & assigned to me*: hides the items you have already read (one you
  just opened stays until the next reload); remembered per device, combines with the filter.

### Changed
- **Folded comments keep the comment box**: folding hides only the older comments; the newest one and the box right
  below it stay visible, so you can answer without unfolding. A draft no longer unfolds the list.

### Fixed
- **iPhone home-screen app: empty band under the tab bar** (a gap the height of the status bar). The status bar is now
  plain black (`apple-mobile-web-app-status-bar-style` `black` instead of `black-translucent`), so iOS gives the page
  the full height below it. The 2.0.2 workaround that moved the tab bar down is gone (it pushed the bar partly out of
  the screen). On phones, the area outside the page has the tab bar colour; `theme-color` and the manifest colours
  match the tab bar. **Already installed on the home screen?** Reload the app; if the band stays, remove the icon and
  add it again from Safari.

## [2.0.2] - 2026-09-29

**In short:** Comments move right below the description, titles are edited in the list, lists get their own
pictures, sections a "+", and you see when an agent is writing. Plus fixes for the iPhone home-screen app, dragging in
long lists and the phone share setup.

### Added
- **Comments right below the description**, folded to the newest one: the bar *Comments (n)* shows all of them with
  one click (newest at the bottom, the box below); the choice is remembered per device. Long descriptions fold after
  about eight lines (*Show more*). Phones get *Details | Comments* at the top of the task panel.
- **Edit a title right in the list**: double-click it (computer) or press **E** on the focused row; Enter saves (one
  undo step), Esc cancels.
- **Keyboard**: arrow keys move through the list (J / K as before), **Space** completes, **Enter** opens, a clearer
  focus ring; the shortcut help (?) shows the new keys.
- **Recently viewed**: the last five tasks and lists you opened are at the top of the command palette (Ctrl/Cmd+K).
- **Own list icons**: a picture instead of the emoji, from presets (the Kalmido icon, the sloths) or uploaded
  (cropped square, re-encoded without metadata, like the profile pictures). Shown in the sidebar, the header, the tab
  bar, the palette and list groups. Emojis still work; picking one replaces the picture and the other way round.
  API: `PUT / POST / DELETE /api/lists/{id}/icon`, `icon` in the list (also in `/api/v1`).
- **"+" on every section header** (computer: on hover, touch: always): an input right in the section, Enter adds the
  task there (quick-add syntax works) and stays open for the next one.
- **Collapse all / Expand all** (sections and subtasks) in the list's *…* menu and with **Shift+C**, remembered per
  device.
- **"Claude is writing …"**: while an agent reports *working*, a typing indicator with its status text shows under
  the last chat message and in the comment area of the task it works on. Everywhere, the agent chip in the top bar
  and the Agents button (rail, tab bar) get a spinning ring; while an agent waits for you, an accent dot. The chip's
  tooltip / menu names the agent and what it does. Agents can name the task: `PUT /api/v1/agent/status
  {"status": "working", "task_id": 51}` (MCP `set_status` too); `GET /api/v1/agent` and `/api/agents` report
  `status_task` and `job_tasks`.
- *Share from your phone*: **New token** right there, with a note on what to update afterwards (iPhone shortcut,
  HTTP Shortcuts import).

### Changed
- *Share from your phone* offers the **server address without `/drop`** for the iPhone shortcut (it adds `/drop`
  itself); the guide says so.

### Fixed
- iPhone / iPad home-screen app: a large empty band below the tab bar on some devices (the layout ended above the
  screen edge by the height of the status bar). Kalmido now measures the gap and moves the tab bar and the other
  bottom elements down.
- Dragging sections (and tasks, and lists in the sidebar) in long lists on a computer: the list now scrolls when you
  come near its top or bottom edge, faster the closer you get.
- The iPhone shortcut sent to `/drop/drop` when the address already ended in `/drop`: `POST /drop/drop` is now
  accepted as well.
- After *New token* under *Account*, *Share from your phone* in the same open dialog still showed the old token.

## [2.0.1] - 2026-09-29

### Fixed
- The start guard of 2.0.0 (#279) also refused databases whose only finding in `PRAGMA quick_check` is a NOT NULL /
  CHECK constraint violation. Such a database is readable: Kalmido starts again and the admin alert reports it, as
  before. Damaged pages, broken indexes or an unreadable file still stop the start.

## [2.0.0] - 2026-09-29

**In short:** AI agents join the team: agent users that get events by signed webhook or long-polling, report status
and jobs, chat and wait for your 👍. Reactions on comments, shared list tags, an MCP server, and a new license (AGPL-3.0).

### Added
- **Agent users** (*Settings > Administration > Agents*, admins): a user type *Agent* for external AI agents and automations
  (Claude Code, Codex, n8n, a local model, a script). An agent is never an admin, has no Paperless access, cannot log in
  to the web app and sees only the lists shared with it (roles member, participant or viewer; the 1.10 roles apply).
  Per agent: API token (shown once), optional webhook URL with its own signing secret, a usage note and an
  **on / off switch** (kill switch: its token and its events stop at once). An existing user can be turned into an
  agent and back; its lists, shares and tokens stay.
- **Agent events**: mention (in a comment, a task title or notes), comment on a task the agent follows, assignment /
  unassignment, chat message, reaction on the agent's comment, job action, tidy request, **wake** and ping. Delivered
  as signed webhooks (same signature, retries and delivery log as the user webhooks) and kept for polling:
  `GET /api/v1/agent/events?since=<cursor>` with **long-polling** (`&wait=<seconds, max 60>`: the request answers as
  soon as an event arrives).
- **Wake agent** button in the task panel and in the Agents tab / chat: sends an immediate `wake` event.
- **Reactions** 👍 👎 ❤️ or any single emoji (+) on comments for everyone who can see the task, with the names on hover / tap. 👍 / 👎 on an
  agent's comment by the list owner, a list admin, the task's assignee or a server admin counts as **approval /
  rejection** (sent to the agent, shown in the history).
- **Agent status** (idle, working, waiting for approval, error, a short text, job counts) reported via the API: a dot on
  the agent's avatar and a chip in the top bar like the timer (*Claude · 2 running · 1 waiting*) that opens the jobs.
- **Agents** module / tab (opt-in under *Settings > Modules*): jobs reported by agents (running, waiting, done,
  failed, stopped) with the linked task and a short log; *Approve*, *Reject* and *Stop* send an event to the agent and
  show up in the task's history.
- **Chat with an agent**: a side panel on the desktop, a tab on the phone; one conversation per person and agent,
  stored on the server, delivered as an event and readable via the API; the agent answers via the API.
- **Tidy up** per list (*Agent may tidy up entries*: off, suggest, automatic; only for lists shared with an agent): the
  agent turns long, quickly typed entries into a short title, section, tags and priority. The original text is kept
  word for word at the top of the notes (**Original (Name):** …). *Suggest* posts a suggestion comment that 👍 (or
  *Apply*) applies; *automatic* applies it right away via `POST /api/v1/tasks/{id}/tidy`.
- **Shared list tags**: tags that belong to a list, with a colour per list, visible to all its members, next to the
  personal tags. In shared lists the tag input suggests list tags first; personal tags show a small person icon; a
  personal tag can be promoted to a list tag. Filters, the sidebar, the REST API (`list_tags`, `/api/v1/lists/{id}/tags`)
  and the MCP server handle both; agents may set list tags. Existing tags stay personal.
- **MCP server** for Kalmido in `mcp/` (stdio and HTTP): list / search tasks, read a task with its comments, create,
  change and complete tasks, comment, react, report the agent status, read and wait for events.
- **Quick add understands the list in plain words**: `in list Work` / `in Liste Arbeit` / `to list …` anywhere, and
  `… in Work` / `… auf Einkauf` / `… into Home Office` at the end when it is exactly the name of a list (otherwise the
  words stay in the title: "Letter to grandma in Berlin" stays text unless a list is called "Berlin"). The chip shows the
  list; clicking it keeps the words in the title. `~list` works as before.
- **docs/AGENTS.md**: the agent protocol (events, payloads, signatures, polling and long-polling, approvals, status,
  jobs, chat, tidy) with an example for a Claude Code session that works through the API.

### Fixed
- **Never an empty database on top of existing data** (#279): when `tasks.db` was missing, empty, unreadable or
  damaged (e.g. I/O errors of a failing disk), Kalmido created a new, empty database on start, and the first visitor would
  have become the admin. Now the data dir gets a marker (`.kalmido-initialized`, also written on the first start of 2.0 of
  an existing install); with the marker, attachments or backups present, a broken database makes Kalmido refuse to start
  (clear log line, exit code 3) until the database is repaired or restored. Only an empty data dir starts fresh.

### Changed
- **License: GNU AGPL-3.0.** Contributions need a DCO sign-off (see CONTRIBUTING.md).
- The public git history was squashed into one commit "Kalmido 2.0.0"; the old tags and GitHub releases v1.x were
  removed (the container images 1.x stay on ghcr.io, pinned tags keep working).
- `GET /api/v1/tags` lists personal and list tags (`kind`: `personal` / `list`); `?tag=` on `GET /api/v1/tasks`
  matches both.

## [1.10.0] - 2026-09-29

**In short:** Roles per shared list: admins see and manage everything, participants see only the tasks assigned to them; an assignee column with pictures and one-click assigning, also for subtasks.

### Added
- **List roles** (*Edit list > Sharing*, a picker with a one-line explanation per role):
  - **Admin**: sees and changes the whole list and manages the members and their roles (never the owner's).
  - **Member** (before: *Can edit*): sees and changes every task.
  - **Participant** (new): sees **only the tasks assigned to them**, with all their subtasks, comments, files and time.
    When only a subtask is theirs, its main task shows above it as read-only **context** (title, dates, status; no
    notes, link, files, fields or comments). Sections appear only when they hold one of their tasks. A participant may
    add tasks to the list (they are always assigned to themselves) and subtasks under their tasks, edit, complete and
    comment on them; they cannot delete tasks, move them to another list, hand them to someone else, or change
    sections, the list, its members or the project status.
  - **Viewer** (before: *View only*): sees everything, changes nothing (may comment).
  - The owner keeps everything only the owner could do: rename, type, archive, delete, public link, custom fields.
- The participant rule is enforced on the server for **every** way to read data: the app state and sync, single tasks,
  subtasks, search, completed and trash, filters and smart lists (built from that state), tags, calendar repeats and
  the ICS feed, the roadmap, project progress, the overview, time entries / report / CSV, templates, the export,
  comments and files, dependencies, News, pushes, reminders and the daily digest, the REST API (all endpoints, also
  paging), webhooks (a participant's webhook fires only for their own tasks) and the undo history (checked per task).
- **Assignee column** in list, section, folder, filter and search views: the assignee's picture (or a dashed circle for
  nobody) on every task of a shared list; a click opens the assign menu (owner, admins and members). On phones a compact
  cell at the end of the row. Hide it per list: list *…* > *Hide assignee column*.
- **Subtasks can be assigned on their own** (from the subtask rows in the task panel or its own panel), independent of
  the main task; a participant assigned only to a subtask sees it with its main task as context.
- API: `role` may be `admin` and `participant` too (`PUT /api/lists/{id}/members`); tasks carry `context: true` for a
  participant's read-only main task.

### Changed
- The roles *Can edit* and *View only* are now called **Member** and **Viewer**; the stored values `edit` / `view` and
  what everybody sees stay exactly the same (nothing to migrate). List admins can moderate comments like the owner.

## [1.9.0] - 2026-09-29

**In short:** Share photos, files and links from your phone in two taps, profile pictures (sloths or your own photo), a News inbox that works like mail, deleting a tag everywhere, a refresh button for shared lists, and dialogs that stay put on the Galaxy Fold.

### Added
- **Share from your phone** (*Settings > Integrations > Share from your phone*). Android: *Download HTTP Shortcuts
  import* gives a ZIP made for you (address + `/drop`, your upload token, the Kalmido icon) with two shortcuts, *Kalmido*
  for photos and files (several at once) and *Kalmido text* for links and text; import it in the HTTP Shortcuts app and
  share. iPhone / iPad: copy buttons for the address and the token and a step-by-step guide for the Shortcuts app; a
  signed generic shortcut can be linked with `KALMIDO_IOS_SHORTCUT_URL` (the button is hidden while it is empty).
- **Profile pictures** (*Settings > Account*): ten sloth presets (coffee, headphones, camera, sleepy, laptop, plant,
  robot, sunglasses, party, reading) or your own photo, cropped square in the browser; the server resizes it to 256 px,
  turns it upright and stores a fresh JPEG without EXIF / GPS data (below the attachments, so backups include it).
  Shown wherever the initials were: sidebar, assignee chips, comments, mentions, News, members, time entries and the
  user list. Only you, admins and people sharing a list with you can load your photo. Admins can set a preset for
  another user (e.g. an API bot user).
- **Delete a tag completely:** right-click or long-press a tag in the sidebar (or "…" in the tag view) > *Delete tag…*;
  the dialog says on how many tasks it is, removes only your tag (tasks stay, other people's tags too), one undo step.
- **Refresh for shared lists:** a button in the header on desktop, *…* > *Refresh* and pull-to-refresh on touch. (The
  app keeps polling for changes every 4 seconds while it is visible.)
- **News like a mail inbox:** unread items bold, *×* (desktop) or a swipe (touch) removes one item, the filter *All |
  Mentions & assigned to me*, and *Settings > Notifications > News* chooses which events create News (mentions,
  assignments, comments on my tasks, unblocked, sharing, project status, completions by others). Completions by others
  are off by default now.
- API: `GET /api/v1/admin/status` also returns `update_checked_at` and `update_error`.

### Changed
- *Settings > Administration* starts with the users (and *New user*).
- The open task shows new comments while you are typing in it (the rest of the page still waits until you are done).

### Fixed
- **Update check reported an old release** (e.g. `latest_version` 1.2.0 while 1.8 ran): the result was cached for a
  day and survived updates, so a check made before the update was still shown, and after a failed request (GitHub's
  rate limit for anonymous requests) the old value stayed. Now a cached release older than the running version is never
  reported, the check runs again right after an update, every 6 hours, and an hour after a failure.
- **News showed "Loading…" forever when there was nothing** (or with collaboration off): an empty feed now says
  *No news*, and *Loading…* only shows while a request runs.
- **Dialogs slid down on the Galaxy Fold** after the on-screen keyboard closed (e.g. *Create API token*): dialogs now
  follow the visual viewport and centre again when the keyboard opens or closes.

## [1.8.1] - 2026-09-28

**In short:** The Inbox comes first and is where the app opens, completed tasks are shown everywhere unless you hide them per view, and the sign-in and setup screens are centered on tablets.

### Changed
- **Inbox first.** The Inbox is the first smart list in the sidebar and the phone drawer (before Today, Tomorrow,
  Next 7 days and Now doable), in the tab choices (*Settings > Appearance*) and in the command palette, and it is the
  start view: the app opens on the Inbox until you open another task view (after that it reopens on the last one, as
  before). When the open list goes away (archived, deleted, left), the app goes to the Inbox instead of Today. The
  welcome tour says so.
- **"Show completed" is per view only.** The global switch in *Settings > General* is gone: completed tasks are shown in
  every list, filter and smart list, and you hide them where you do not want them (*Hide completed* in the view's "…"
  menu, the sort menu or the command palette). Choices you made per view stay. The stored global value is removed on
  the first start.
- **Calendar: its own "Completed" toggle** in the bar of the month, week and day view (also in the command palette),
  shown by default, per user and synced like the other views (entry `cal` in the setting `show_done_views`), undoable.

### Fixed
- **Sign-in and first-run setup centered on tablets in portrait** (for example a Galaxy Fold unfolded): below 900 px
  width these screens were a bottom sheet with the empty space above; they are now centered at every size, rounded on
  all corners and opaque in the light theme too (the app behind showed through).
- A welcome tour card without a target is centered on the screen instead of sitting at 30 % from the top.

## [1.8.0] - 2026-09-28

**In short:** New accounts can start with a realistic sample project that shows the project features, and remove it again in one click.

### Added
- **Sample project.** *Example: Image film for client Muster*: a project list with the sections Concept,
  Pre-production, Shoot, Edit and Approval, 15 tasks and 3 subtasks with dates relative to today (overdue, today, next
  week, undated), start dates and durations for the timeline, four dependencies (so *Flow*, *Now doable* and the
  timeline arrows have something to show), priorities in all four matrix quadrants, a Markdown description with a
  checklist, tags, a weekly status call, a comment, two pinned custom fields (budget, effort), a 1.5 h time entry and
  the project status *On track*; plus the checklist *Example: Shoot day packing list*. In the user's language (English,
  German), and only with the modules that are on: without the project modules it is a plain list without
  dependencies, fields, time or status.
- **Where it is offered:** setup step 2 has *Create a sample project* (ticked for *Projects & team*, unticked for
  *Simple list* and *Just me*, a manual choice wins); the first card of the welcome tour of every new account offers
  it too (ticked when dependencies, custom fields or time tracking are on; asked once, not again after the setup
  decided it); *Settings > Data > Sample project* and the command palette create or remove it at any time.
- **Removing** asks with the app's own dialog, naming the lists and the number of sample tasks, and removes exactly
  what the sample created (recorded on the server): sample tasks also when you edited them, including the done copies
  of the repeating task, its sections, fields and time entry. Tasks you added stay (also subtasks below a sample task,
  which become main tasks), and with them their list, section and custom field.
- **Quiet and private:** the sample belongs to the user alone, sets no reminders, creates no activity, News, pushes or
  webhook events, and its tasks are left out of the daily digest. Creating it twice does not duplicate it.
- API (app): `POST /api/sample` (idempotent: `{created: false, exists: true}` while one exists), `DELETE /api/sample`,
  `sample` in `GET /api/state`, `sample: true` in `POST /api/admin/setup`.

## [1.7.1] - 2026-09-28

**In short:** Lists scroll to the end again on phones, and the Markdown syntax moved from the description box into Help.

### Fixed
- **Phones: the last rows of a list sat under the tab bar** and a list only a little longer than the screen (for
  example *Tomorrow* with a few tasks and subtasks) could not be scrolled at all. Since 1.5.3 the docked composer set
  the list column's bottom padding to 0, also on phones, where the composer is hidden (the + button is used there).
  That padding now only goes away on wider screens with the docked composer. New suite `tests/scroll_ui.js` (Firefox
  headless, skipped without Firefox) checks every view at 360 × 780 and 390 × 844 with touch: the last line clears the
  tab bar and the + button, the scroll box can scroll and no touch handler cancels a vertical drag.

### Changed
- The task description box just says **Description** (German *Beschreibung*) instead of listing Markdown syntax.
- **Settings > Help > Formatting (Markdown)** lists what descriptions understand: bold, italic, strikethrough, code,
  links (`[text](https://…)` or a plain address), headings `#` to `###`, bullet and numbered lists and checklists
  `- [ ]` / `- [x]` (tick them in the formatted text), plus the button that turns open checklist items into subtasks.
  With collaboration on it adds that comments understand bold, italic, strikethrough, code and links, line breaks and
  @mentions, but no headings, lists or checklists.

## [1.7.0] - 2026-09-28

**In short:** A "Flow" sort that follows the dependencies, all overdue tasks moved in one click, and the smart list "Now doable".

### Added
- **Sort mode "Flow"** (sort menu; German *Ablauf*; only with the dependencies module): a topological order by
  *Waiting on*, so a task always comes after the open tasks it waits on inside the view; ties by start date (a task
  without one starts on its due date), due date and time, priority, then manual order. The first task of each group
  that waits on nothing gets a subtle *Next* marker; waiting tasks keep the lock and "Waiting on …". Lists order
  within each section, filters and Today / Next 7 days show one sequence instead of date groups. Dependencies on
  tasks outside the view are ignored for the order. A circle of dependencies (only possible in old or imported data)
  falls back to date order with one hint. Project lists use Flow by default while you have not picked a sort (list
  view; kanban and timeline keep theirs); with the module off the option is hidden and the old default applies. A
  manual drag switches the view to *Priority, then manual*, like Date and Title do.
- **Overdue in one click** on Today: when overdue tasks are shown, a compact banner *n overdue → Today / Tomorrow /
  Next week (Mon) / Pick a date…* moves all of them at once. Only the day changes (time, reminders and repeat stay,
  like the date popover), tasks in lists you may only view are skipped and counted in the toast, and the whole move is
  one undo step (one batch request). The × hides the banner until tomorrow on that device. Only on Today.
- **Smart list "Now doable"** (German *Jetzt machbar*, `#doable`, `g d`): open tasks that wait on nothing, are due
  today, overdue or undated (an undated subtask follows its parent), do not start later, are not in an archived list, and are yours: assigned to you, or
  unassigned in a list you own (with collaboration off: every task). Sorted by Flow (by date without the dependencies
  module). In the sidebar after *Next 7 days* with its count, in the command palette, the shortcuts overlay and the
  pinnable tabs.

## [1.6.1] - 2026-09-28

**In short:** "Archived" is now a plain sidebar row like Trash that opens a view of all archived lists.

### Changed
- **Archived lists get their own view.** The folded *Archived (n)* row with its chevron is gone: *Archived* is a
  plain row in the sidebar footer like *Trash* (icon, name, count; only when there is an archived list, phone drawer
  too) and opens *Archived* (`#archived`). It lists every archived list with its colour or emoji, name, folder, open
  and completed tasks, the day it was archived and, for a shared list, its owner. Per list: *Open*, *Restore*
  (undoable) and *Delete permanently…* (owners, with the dialog that names what is lost). Archived lists no longer
  show up one by one in the sidebar; while one is open, the *Archived* row is highlighted. The fold state kept on
  the device is dropped.
- Lists remember when they were archived (`archived_at`, set on archive, cleared on restore; lists archived before
  1.6.1 show no date).

## [1.6.0] - 2026-09-28

**In short:** Docked quick add, undated tasks in the timeline, bigger timeline bars, a filterable matrix, tooltips instead of helper lines.

### Added
- **Quick add docked at the bottom** of the list column (desktop and tablet; phones keep the + button): a card with
  an accent "+", *Add task…*, the `N` key badge and the template button. Focused, it shows chips for date, list and
  priority (from what you type and the view; a click changes them and wins over the text) and the recognised tokens.
  Enter adds and keeps the focus, Esc leaves. Lists, folders, filters, Today and Next 7 days; not kanban, matrix or
  calendar. The old input on top is gone.
- **Undated tasks in the timeline.** Per list a folding *No date (n)* group with one row per task (subtasks under
  their parent) and an empty dashed track: click a day = due that day, drag across days = start and due (touch: hold,
  then drag). *Remove date* in the bar menu, or drop a bar on *No date*. Every change is one undo step. Header switch
  *No date* per device, on by default in project lists. Waiting tasks show *waits for …*; auto-shift ignores them.
- **Matrix scope.** *All lists ▾* picks a list, a folder or a saved filter (same filter engine); chips *Only mine*
  (with collaboration) and *Due by* (overdue and today, 7 or 30 days); remembered per device, shown in the title with
  an × to reset. *Show as matrix* in the "…" menu of lists, folders and filters; quick add in a scoped matrix goes
  into that list (or the folder's first list).
- *Settings > Appearance > Show tips again* brings back the one-time hints on this device.

### Changed
- **Timeline and roadmap bars are taller** (34 px, 44 px on touch), the resize handles reach past the bar ends, a
  1-day bar keeps a minimum width, the dependency dot is bigger and sits outside the bar end.
- **Tooltips instead of helper lines:** the empty checklist *Done* hint, the attachment drop hint, the timeline's
  date-range hint, the custom-fields hint and the Filters placeholder became tooltips (touch screens show them once,
  with ×); the habit day hint disappears after the first tapped day; the owner note of a shared list is a lock icon.
  Tooltips name the keyboard shortcut (`G T`, `D`, `X`, `T`, `Shift+T`, `N`, …).

### Fixed
- CI of 1.5.2: a list colour in a group header now goes through `cssColor`, the stylesheet uses rem only.

## [1.5.2] - 2026-09-28

**In short:** Folder view, "Delete completed…", running timer card on the time page, archived lists folded in the sidebar.

### Added
- **Folder view.** Click a folder's name in the sidebar to see the open tasks of all its lists in one view, grouped
  by list (with the list colour); the chevron still folds the folder. Own address (`#folder/<name>`), can be pinned
  as a tab, has its own *Show completed*, sorting and selection; quick add goes into the folder's first list.
- **"Delete completed…"** on the *Completed* view: all, or those completed more than 30 / 90 days ago, go to the
  trash (restorable, one undo step). Only what you may change; items of checklists stay; the dialog says what stays.
- **Running timer on the time page.** While a timer runs, *Time tracking* opens with a large card: the live time,
  the task (a click opens it), its list or project with colour, the start time and the note, *Stop timer* and *Open
  task*. Nothing running: a short *No timer running* with the tasks you tracked most, one tap starts the timer again.
  Stacks on phones.

### Changed
- The search button in the icon rail (shown while the sidebar is folded) sits at the bottom, right above Settings.
- **Archived lists fold into one row** *Archived (n)* in the sidebar footer (phone drawer too); a click unfolds it,
  remembered per device. An archived list you have open stays visible.

### Fixed
- `tests/checklist_ui.js` still clicked the list dialog's old *Save* button (CI of 1.5.1).

## [1.5.1] - 2026-09-28

**In short:** One-tap Today / Tomorrow, "Show completed" per list, archived lists stay out of the way, no duplicate navigation.

### Added
- **One tap "Today" / "Tomorrow".** Two buttons on top of the task menu (long-press, right-click, the row's "…"), next
  to the date in the task panel and in the selection bar; on the keyboard `t` / `Shift+T` for the focused, open or
  selected tasks (listed in the shortcut help). Only the day changes: time, reminders and repeat stay (a recurring
  task just moves, like in the date dialog). One step in the undo history.

### Changed
- **"Show completed" per view.** Every list, filter and smart list (Today, Tomorrow, Next 7 days, Inbox, All,
  Assigned to me, tags) has its own *Show completed / Hide completed* in its "…" menu (also in *Sort…* and the command
  palette), stored per user on the server (it follows you to every device, the other members of a shared list keep
  their own) and undoable. A view without its own choice follows the old setting (*Settings > General*), which the
  calendar keeps using. Tomorrow, Next 7 days, All, Assigned to me and filters now have a *Completed* group too.
  New user setting `show_done_views` (json map view -> 0 / 1).
- **Archived lists stay out of the way.** Their tasks no longer show up in Today, Tomorrow, Next 7 days, Assigned to
  me, filters, tags, the calendar (incl. repeats), the matrix, the overview, counts and the command palette; they get
  no reminders, are left out of the daily digest, the calendar subscription (ICS) and the overdue trend of the
  statistics. Opening the archived list still shows them; restoring it brings everything back.
- **The list dialog saves itself** like the settings: every change applies at once, *Saved · Undo* in the header, one
  history step each; no *Save* / *Cancel* any more (a new list keeps *Create*).
- **The first weekday of your region** (Monday in Germany, Sunday in the US) now also applies to the timeline, the
  roadmap, the statistics (weekly bars and heatmap; `GET /api/stats?ws=0..6`) and the time reports (*This week*).
- **No duplicate navigation on desktop.** Statistics, time tracking, overview, search and settings appear once: in
  the sidebar footer while the sidebar is visible, in the icon rail only while the sidebar is folded into it.

### Fixed
- The calendar did not show the repeats of a task that just got (or changed) its repeat, was completed or was
  changed on another device until the visible range changed; the repeats now refetch with every such change and
  the old ones stay visible while loading.

## [1.5.0] - 2026-09-28

**In short:** Usability: settings save themselves, own date picker, archive lists, slimmer checklists, tablet layout.

### Changed
- **Settings save themselves.** Every switch, choice and field applies at once (text and numbers when you leave the
  field, press Enter or pause typing; closing the dialog saves what is still pending) and shows *Saved · Undo* in the
  dialog header. Each change is a step in the undo history (*Changed setting: …*), including appearance, the tab bar,
  the display name, the language, admin switches, admin alerts and backups. No *Save* buttons any more.
- **One Modules page.** *Settings > Modules* lists every module with one sentence, grouped (views, for you, projects
  and team, connections); focus and time-tracking options fold out under their module, and admins get the *for
  everyone* switch next to collaboration and time tracking. *Layout*, *Collaboration*, *Focus* and *Time tracking*
  are gone as tabs (9 sections instead of 12; the tab bar moved to *Appearance*, *Users* is now *Administration*).
- Developer things (upload token, API tokens, webhooks, `/drop`, allowed internal hosts, rule texts) sit under a
  folded *Advanced · for developers*; the ntfy details show only when ntfy is a channel; push priority in words
  (*Normal*, *Loud*, *Urgent*).
- **Archive instead of delete.** *Delete* in list menus and the list dialog is now *Archive* (undoable). Deleting for
  good is only possible for archived lists, with a dialog that names what is lost; the server refuses `DELETE
  /api/lists/{id}` for a list that is not archived (409).
- **The app's own dialogs** replace every browser `confirm()` / `prompt()`: title, what happens, a red action for
  destructive ones, Esc = no. What can be undone (deleting selected tasks, removing a link, clearing done checklist
  items) no longer asks and offers *Undo* instead.
- **Own date and time pickers** everywhere (task dates, start, repeat end, time entries, reports, custom date fields,
  templates, habits, public links, settings): in the app language, the week starting on your locale's first day,
  12 or 24 hours as your locale has it, typing a time (`930`, `9:30 pm`, `21 Uhr`), full keyboard and touch support.
  Month calendar and week view start on the same day. Stored formats are unchanged.
- **Custom repeat** is a small form (every n days / weeks / months / years, weekdays); the RRULE text is an expert
  field under *Advanced*.
- **Checklist items** get a slim panel: title, note and (shared, with collaboration) the assignee. Nothing else is
  shown; the data stays.
- **Comments only in shared lists.** In a private list the comment box is gone; comments from when the list was shared
  stay readable, folded and read-only. The activity switch says what it shows (*With activity* / *Comments only*).
- Task panel footer: no focus button (start focus from the task menu or the Focus page); *Track time* and *Delete*
  carry text; a running timer shows its time on the stop button.
- **Header:** the list title keeps its room, the running indicator shrinks to icon and time, *Select* and *Sort* moved
  into the header's “…” menu together with the list menu. Phones and touch tablets: *Undo: …* / *Redo: …* at the top
  of that menu instead of the ← → buttons (desktop keeps them). The running indicator is neutral with a pulsing accent
  dot (red stays for “overdue”) and no longer repeats in the settings header. Offline / sync is translated, an icon
  with a count on phones.
- **Fold and tablets:** while a task panel is open and the list would get narrower than about 420 px, the sidebar folds
  into the icon rail; its new *Lists and filters* button opens it as an overlay. Touch tablets use the compact view
  switch and hide the keyboard search button.
- Desktop sidebar: no second copy of what the rail has (statistics, time, overview, search, settings); tags fold.
  Phone drawer: account and a settings gear at the top.
- Habits: the grid shows the last 7 days up to today; on phones the name sits above its days. *New habit* is a
  labelled button below the list.
- Setup: the single modules are under *Customize…*, *Skip* is gone, *Start* stays in view, sign-in fields have labels.
- Welcome tour: the keyboard step only with a mouse, the project hint only for admins and teams, no line break inside
  `!high`.
- Time report: one tile with time and decimal hours, *today* only when the range is longer than today.
- Command palette: no “action” word on every row.

### Added
- Quick add says when a date and the repeat do not match (*first on Tue, then every Monday*).
- *Turn the open checklist items into subtasks* for “- [ ]” lines in a description (one undo step); those checkboxes
  now look like the app's own.

### Fixed
- Touch targets are at least 44 × 44 px on touch screens (header icons, checkboxes, habit cells, sidebar buttons,
  calendar days, switches, menus).
- Light theme: the red of overdue counts and danger actions is one step darker (AA on the highlighted row, was 4.43:1).
- Settings tabs on phones: the current tab is never cut off at the edge.

## [1.4.0] - 2026-09-28

**In short:** Undo history: step back and forward through every change, by keyboard or menu.

### Added
- **Undo and redo history** per device: ← / → in the top bar (on a phone in the header) step back and forward
  through the last 30 changes, kept until the page is reloaded. The tooltip names the step (*Undo: Completed “Pay
  invoice”*); a right-click or long-press on ← (or →) lists the last ten steps, and picking one undoes everything up
  to it in order. Keys: Ctrl/Cmd+Z, Ctrl/Cmd+Shift+Z and Ctrl+Y, at any time, but never inside text fields (the
  browser's own text undo keeps working there). A new change clears the steps forward; the six-second *Undo* toast
  stays as a shortcut to the newest step.
- Now undoable (and redoable) as well: title, description, tags, priority, assignee, link and custom field values
  (typing is one step per field until you leave it), creating a task (undo moves it to the trash) and subtasks, *Skip
  this occurrence*, sections (add, rename, delete with their tasks at their old place, reorder), lists (type, name,
  colour, view, *Move dependent tasks along*, hourly rate, archive, folder, order), next to everything that already had
  an undo (completing, deleting, moves, dates, batch actions, moving a project, dependent tasks, time entries).
- Conflict safety both ways: a field changed in the meantime, on another device or by another member, is left alone
  and reported (*Changed elsewhere, not undone: …*); a task someone else changed after it came back from the trash is
  not deleted again; a section is only removed while it is still empty and unchanged. Steps with several tasks are one
  transaction. Offline, a step that has not been sent is taken out of the queue; otherwise undo and redo are queued
  (a dot on the button while they wait). Steps in lists that became view-only are refused.

### Changed
- On phones the list's view switch shows only the current view; a tap on it offers the others (room for ← / →).
- Web app API: `POST /api/tasks/batch` reports `conflicts` (per task and field, custom fields as `field:<id>`) and
  the server time; `complete` takes `expect` (the date it should still have), `reopen` returns undo payloads, `delete`
  takes a `guard` (not if someone else changed the task after that time). Sections: `POST` takes `sort` and `tasks`,
  `PATCH` and `DELETE` and the order endpoint take the expected state as `_prev`, `DELETE` returns the section and its
  tasks. `PATCH /api/lists/{id}` and `POST /api/lists/reorder` take `_prev` too. A `_prev` for custom field values is
  checked per field.

### Fixed
- *Events today* (calendar subscriptions) no longer shows on Today while the Calendar module is off, and its setting
  is hidden then too.
- The roadmap label reads *29%* without the wide gap in the monospaced font.
- Tests: `time_api_test.py` fails with a non-zero exit code, and its statistics check no longer breaks on the Monday
  after the seeded week.

## [1.3.0] - 2026-09-28

**In short:** Roadmap of all projects, moving whole projects, section and sidebar drag and drop on touch.

### Added
- **Roadmap**: *All* has a view switch *List | Timeline* (with the timeline module). The timeline shows every list
  on one chart for rough project planning: lists grouped by folder, one row per list with a **summary bar** from the
  earliest start (or due date) to the latest due date of its open tasks, drawn as a bracket in the list's colour and
  filled by the project progress (with the progress module). Click a name to collapse a list to that one row; *Collapse
  all* / *Expand all*; with five or more projects they start collapsed. Filters: *Projects only* (on as soon as one list
  is a project), *Hide done*, an assignee (with collaboration) and a list / folder picker. Zoom *Week*, *Month* or
  *Quarter* (week columns, month labels) with *Today* and back / forward. View, zoom, filters and what is collapsed
  are saved per user, so they follow you to every device.
- **Move a whole project**: drag its summary bar, or long-press it on a phone (*Move project by…* in days or weeks,
  also in the bar's menu and with **M** on a focused bar). Every open task with a date in that list, subtasks too,
  moves by the same number of days and keeps its length; tasks without a date stay. Tasks in other lists that wait on
  it follow when their list has *Move dependent tasks along* on. One toast (*12 tasks moved*), one *Undo* for all of
  it. Needs edit rights on the list; at most 500 dated tasks at once.
- Dependency arrows across lists in the roadmap; into a collapsed list they attach to its summary bar, several
  merged into one arrow with a count.
- API: `GET /api/v1/roadmap` (groups with summary spans, progress and dated tasks; `from`, `to`, `projects_only`,
  `include_done`) and `POST /api/v1/lists/{id}/shift` with `{days}` (write scope, one transaction).
- **Sections by drag and drop:** drop a task on a section header (it goes to the top of that section; a subtask
  becomes a standalone task there), empty sections show *Drop tasks here* while you drag, and sections are reordered
  by the handle on their header, in the list view and on kanban columns (one request, one *Undo*; *Move up / down*
  in the section menu uses the same). On a phone: long-press a task for *Move to section…*, a section header for
  *Move section up / down*.
- **Sidebar drag and drop on touch:** long-press a list and drag it to reorder, onto a folder to move it in, onto
  *Lists* to take it out (with *Undo*); long-press a folder to reorder folders. A closed folder opens while you hover
  over it, the drawer scrolls at its edges, a tap still opens the list, and a hold without moving opens the list's
  menu, which now has *Move to folder…*.

### Changed
- The roadmap draws only the rows in view, so 50 projects with 1000 tasks scroll smoothly.
- A switched-off module is gone everywhere: no *Start focus session* button in the task panel with *Focus* off (and
  no focus entry in the running indicator, the settings, the shortcuts overlay), no *Timeline* shortcuts without the
  timeline, no *Projects* help without the project modules. Starting a focus session, creating or checking in a
  habit, and starting a timer or adding time with the module off are refused by the server (409, with the reason);
  the data stays.

### Fixed
- The task panel showed *Start focus session* with the *Focus* module off.
- Touch tablets (a foldable unfolded, an iPad) at 900 px and wider had no "+" button: it now shows bottom right on
  touch screens without a mouse (left of an open task panel) and opens the quick-add sheet, centred at the bottom.

## [1.2.0] - 2026-09-27

**In short:** Gantt arrows with drag-to-link, list types (list / checklist / project), running-timer indicator.

### Added
- **Gantt timeline** (list view *Timeline* and *Calendar > Timeline*): dependency arrows finish → start between the
  bars (orthogonal, rounded, with arrowheads), a red arrow and bar edge when a task starts before a task it waits on is
  due (*Starts before "X" is due*), hatched waiting bars with a lock, dashed arrows from completed blockers, short stubs
  with a tooltip for tasks outside the visible range or in other lists. The arrows follow a bar while it is dragged
  and are redrawn on resize and font size changes.
- **Link in the timeline:** drag the dot at the end of a bar onto another bar (that task then waits on it), with a
  rubber band, highlighted valid targets and the server's reason for refused ones (a loop, a task you may only view,
  itself); a click on the dot, a long-press on a phone (*Connect to…*), the keyboard (**C** on a focused bar, then
  Enter on the target, Escape to cancel, arrow keys between bars, Shift+F10 / right-click for the bar menu) or
  *Pick from a list…* do the same. Click an arrow to remove the dependency or open either task.
- **Move dependent tasks along** (list dialog, owner, off by default): when a task is postponed, the open tasks of
  that list waiting on it that would now start too early move by the same number of days, keeping their length, down
  the chain (at most 10 levels and 50 tasks, only tasks you may change; also from the date dialog, dragging onto a day
  and the API). The toast says *3 dependent tasks moved*; one *Undo* takes the whole chain back. Timeline drags can be
  undone now too.
- **Three setup presets** in the first-run setup: *Simple list* (lists, subtasks, reminders, calendar), *Just me*
  (preselected: all views for one person) and *Projects & team* (everything, for teams up to about ten people), with
  the single modules below; the welcome tour and the *Getting started* list only mention modules that are on
  (*Getting started* gets a *Plan a project in the timeline* item when timeline and dependencies are on).
- `GET /api/deps` (the app's timeline: every dependency between tasks you can see); `/api/v1/me` reports the modules
  `dependencies` and `custom_fields`.

- **List type** selector (list dialog, new-list dialog, the list's … menu and right-click in the sidebar): *List*
  (default), *Checklist* (the former checklist switch) or *Project*. Only project lists get time tracking,
  dependencies, custom fields and progress / status (while their modules are on); plain lists and checklists hide
  them completely (rows, task details, menus), nothing is deleted. A *Project* badge next to the list title. The server
  refuses timers, time entries, dependencies (both lists must be projects), field values and a status elsewhere with a
  clear 409; reports, the timesheet, statistics and *Where is it stuck?* only count project lists. The update makes
  lists with dependencies, custom fields, a status or at least 5 minutes of tracked time projects and checklists checklists. API: `kind` on
  lists, the `checklist` flag keeps working. With *Projects & team* the *Getting started* list is a project.
- **Hide the progress bar** of a project with the small × next to it, per person and list (synced across devices);
  *Show progress* in the list's … menu or the list dialog brings it back.
- **Running indicator** in the top bar (and the Settings header) for everything that runs: time tracking, a focus
  session or break, the stopwatch, each with its own icon, the time and the task, or *2 running*; a click opens the
  task with Pause / Stop. The task details show what runs on that task; the start buttons say what they start
  (*Start time tracking*, *Start focus session*, *Start stopwatch*).

### Changed
- **Dependencies** and **Custom fields** are modules of their own (*Settings > Layout > Views and features*, per
  person). Off = hidden in the app (details, rows, overview, list dialog, filters, timeline), no *Unblocked* News or
  push; nothing is deleted and the API keeps working. Existing accounts keep them if they already have dependencies
  or custom fields in their lists or use the timeline or project progress; everyone else follows the server's default
  from the setup. A setup default from before 1.2 that includes the timeline or project progress gets both too.

### Fixed
- The task names on the left of the timeline stay in place while the chart scrolls sideways.
- A focus session or break whose tab was closed is finished by the server at its planned end (with its time entry, as
  set under *Finished focus sessions count as time*), and a late *finish* no longer counts the hours in between as
  focus time. A forgotten stopwatch stops after the same hours as a forgotten timer.

## [1.1.10] - 2026-09-27

**In short:** Importers for Todoist, Trello, Asana, Microsoft To Do and ICS, with preview and undo.

### Added
- **Importers** (*Settings > Data > Import*): Todoist (CSV per project, the backup ZIP, Sync API JSON; English and
  German date texts incl. recurring ones, sections, subtasks, @labels, priorities, durations, deadlines, comments),
  Trello (board JSON: lists as sections or as lists in a folder, checklists as subtasks, labels, members, archived
  cards skipped or completed, comments and attachment links in the notes), Asana (CSV: sections, parent tasks, tags,
  dates, completion, assignees when they can see the list), Microsoft To Do (Outlook tasks CSV in English or German,
  also Windows-1252, CSVs of export tools, ICS) and ICS / VTODO (Apple Reminders exports, Nextcloud Tasks,
  Thunderbird: time zones, RELATED-TO, RRULE, VALARM, completed / cancelled). One picker with export instructions per
  app, a **preview** (dry run in the same transaction: counts per list, sample rows, what cannot be mapped), target =
  new lists or an existing one, idempotent re-import (external id per source), an import report and **Undo** for 24
  hours (*Recent imports*), history line *imported from ...*.
- Import safety: 20 MB / 20,000 tasks per import (`KALMIDO_IMPORT_MAX_MB`, `KALMIDO_IMPORT_MAX_TASKS`), 30 imports per
  user within 10 minutes (`KALMIDO_IMPORT_RATE`), ZIP bomb and nesting limits, encoding detection (UTF-8 / BOM,
  UTF-16, Windows-1252), control and bidi characters removed, formula cells kept as text, nothing inside a file is
  fetched, every value validated like the app's own input.
- API: `POST /api/v1/import/{source}` (multipart, scope write, `dry_run`) and `POST /api/v1/imports/{id}/undo`.

## [1.1.9] - 2026-09-27

**In short:** REST API with tokens, webhooks, public read-only list links, checklist mode.

### Added
- **REST API** under `/api/v1` with **personal access tokens** (*Settings > Account > API tokens*): name, access
  (read / write / admin read for admins), optional expiry; shown once (`abk_` + 256 random bits), stored as SHA-256,
  revocable, last use shown. A token acts as its user and never has more rights (same list roles, module switches;
  admin rights re-checked on every request; disabled / deleted users' tokens stop at once). Bearer token only (no
  cookie, no proxy header, so no CSRF header needed). Lists, tasks (filters: list, status, due range, tag, assignee,
  updated since, parent; create / change / complete / reopen / delete to the trash), subtasks, tags, comments, time
  entries, habit check-ins, search, admin users and status. JSON, ISO dates, cursor pages, one error format, unknown
  fields refused. The API uses the app's own endpoints internally: history lines *via API*, notifications and webhooks
  as in the app. 120 requests per token and minute (`KALMIDO_API_RATE`), invalid tokens limited per address and
  reported to the admins. OpenAPI 3.1 at `/api/v1/openapi.json`; [docs/API.md](docs/API.md) with curl, Home Assistant,
  n8n and shell examples. `KALMIDO_API=0`.
- **Webhooks** (*Settings > Integrations > Webhooks*): up to 10 per user for `task.created`, `task.updated`,
  `task.completed`, `task.reopened`, `task.deleted`, `comment.created`, `list.shared`, only for lists the user can see.
  Signed with HMAC-SHA256 (`X-Kalmido-Signature: t=...,v1=...`, secret shown once and stored encrypted), delivered from
  a queue (10 s timeout, response ignored, no redirects), retried after 1 min, 5 min, 30 min and 2 h, then turned off
  with an admin alert. *Send test*, delivery log (last 50, no bodies), new secret. SSRF guard like calendar
  subscriptions: only public https addresses unless an admin allows the host (*Allowed internal hosts*, now shared by
  calendars and webhooks, or `KALMIDO_WEBHOOK_ALLOW_HOSTS`). `KALMIDO_WEBHOOKS=0`.
- **Public links** for a list (*Edit list > Public link*, owner only): view only or view and tick off, optional
  password (hashed, per-link unlock cookie) and expiry, new link / turn off. A script-free page with only that list
  (sections, open tasks, subtasks, recently completed; notes only when switched on), `noindex`, `no-store`, strict CSP.
  Ticking off goes through the normal completion (history and News *via the public link*). Rate limits per address, an
  admin alert when one link is opened unusually often. Admin switch under *Whole server*, `KALMIDO_PUBLIC_LINKS=0`.
- **Checklist mode** for a list (*Edit list*): done items stay in a *Done* section at the bottom, back on the list with
  one tap, *Uncheck all*, *Clear done*, compact rows without dates or priorities. Works with sharing and public links.

### Changed
- *Allowed internal calendar hosts* is now *Allowed internal hosts* and applies to calendar subscriptions and webhooks.
- The service worker never caches public link pages.
- API with tokens and webhooks, public list links, checklist mode

## [1.1.8] - 2026-09-27

### Added
- **Automatic backups + restore** (*Settings > Users > Whole server > Backups*, admins): a daily archive (zip) of the
  database (SQLite online backup API) and all attachments with a manifest of SHA-256 checksums, at a set time (default
  03:30), retention (everything of the last 24 hours, 14 daily, 8 weekly, 3 safety backups; adjustable), *Back up
  now*, download, check, delete. Optional encryption with a passphrase (scrypt + AES-256-GCM in authenticated chunks;
  without the passphrase an encrypted backup cannot be restored). Restore from a listed backup or an uploaded file
  after typing `RESTORE`: the archive is fully checked (expected members only, no traversal / links, size, member and
  ratio limits against zip bombs, checksums, `integrity_check`, no foreign triggers / views, schema version), then
  maintenance mode, a safety backup of the current state, attachments + database swapped (rollback on failure),
  migrations, every other session ended. Admin alerts for a failed backup and for no backup in 2 days.
  `KALMIDO_BACKUPS=0`, `KALMIDO_BACKUP_DIR`, `KALMIDO_BACKUP_PASSPHRASE`, `KALMIDO_BACKUP_MAX_MB`.
- **Two-factor authentication** for the built-in login (*Settings > Account*): authenticator app (TOTP, QR code made on
  the server, encrypted secret, no code accepted twice), 10 one-time recovery codes (hashed), **passkeys** (WebAuthn)
  as second factor and for passwordless login (admin switch), rename / remove, admin reset. Admin policy *Require
  two-factor authentication for built-in logins*: users set it up at their next login. Proxy-header SSO and OIDC
  logins are unaffected. `KALMIDO_WEBAUTHN_RP_ID`, `KALMIDO_WEBAUTHN_ORIGINS`.
- **OpenID Connect login** ("Log in with ..."): Authorization Code + PKCE, discovery, ID token verified against the
  JWKS (iss, aud, azp, exp, nonce), userinfo, only admin-created users by default (linked by user name or verified
  e-mail, then by subject), optional auto-create, required group and admin group, requests through the SSRF guard
  (`KALMIDO_OIDC_ALLOW_HOSTS` for a provider in your network). `KALMIDO_OIDC_*` variables, shown read-only to admins.
- Users have an optional e-mail (for OIDC linking). Sessions remember how they logged in; a login never keeps a
  session token the browser brought along.

### Security
- New dependencies, pinned: `webauthn` 3.0.1 (+ `cbor2`, `pyOpenSSL`, `pyasn1`, `pyasn1-modules`,
  `typing-extensions`) and `segno` 1.6.6.
- Backups with restore, two-factor (TOTP, passkeys) and OIDC login

## [1.1.7] - 2026-09-27

### Fixed
- CI: the control-character filter of calendar texts uses escapes instead of literal bidi characters (bandit B613).
- Calendar text filter: escaped bidi ranges (bandit B613)

## [1.1.6] - 2026-09-27

### Added
- Calendar subscriptions (*Settings > Integrations > Calendars*): events from Google Calendar (secret iCal address),
  iCloud, Outlook or any ICS link (`webcal://` too), or from CalDAV accounts (calendars discovered via
  `current-user-principal` / `calendar-home-set` / `.well-known/caldav`, pick which to show), read-only next to the
  tasks in month / week / day view and the calendar timeline, plus an optional *Events today* block on *Today*
  (per user, on by default). Events are tinted and outlined in the calendar's colour, all-day ones in the all-day row;
  a click shows a popover (time, place, description as escaped plain text with http / https links, calendar) with
  *Create task from event*. Per calendar: name, colour, show / hide, refresh every 15 or 60 minutes, last sync and
  error, *Refresh now*, edit, remove. Private per user, cached for offline use.
- Server-side sync every 15 / 60 minutes (window: 60 days back, 365 ahead): RRULE / RDATE / EXDATE / RECURRENCE-ID,
  time zones, floating times, cancelled events; ETag / If-Modified-Since for ICS, getctag / sync-token for CalDAV; at
  most 10 MB per download and 5,000 occurrences per calendar; sub-daily and never-matching rules are not expanded.
- SSRF guard for these fetches: private, loopback, link-local, CGNAT, multicast and reserved addresses (IPv4 / IPv6,
  mapped forms) are refused at connect time and the checked address is the one connected to (no DNS rebinding);
  admins can allow internal hosts (*Settings > Users > Whole server > Allowed internal calendar hosts*,
  `KALMIDO_CALENDAR_ALLOW_HOSTS`); changes to that list raise a security alert.
- Links and CalDAV passwords are stored encrypted (AES-GCM) and never returned to the browser; five failed syncs in a
  row raise an *Integration problems* admin alert (id, user, error class only).
- `KALMIDO_CALENDARS=0` turns the feature off; `KALMIDO_CALENDAR_MAX_MB`, `KALMIDO_CALENDAR_MAX_EVENTS`,
  `KALMIDO_CALENDAR_RATE` tune the limits.
- Tests: `calendars_test.py` and `calendars_ui.js` with a fake ICS / CalDAV server (`stub_calendar.py`).

### Changed
- The image installs `icalendar`, `recurring-ical-events` (+ `x-wr-timezone`, `click`), all pinned.
- Calendar subscriptions: show ICS/CalDAV events next to tasks

## [1.1.5] - 2026-09-27

### Added
- *Settings > Help* links to the website (kalmido.com), the source code on GitHub and *Report a problem* (GitHub
  issues), each in a new tab without opener or referrer; the command palette has *Open website* and *Report a problem*.
- CI: a failing test suite also shows as an annotation on the run page.
- Help: links to the website, GitHub and issue tracker

## [1.1.4] - 2026-09-27

### Added
- Admin alerts via ntfy (*Settings > Users > Whole server > Admin alerts*, admins only): operational warnings go to
  the admins, independent of their own notification channel: update available (once per version), Web Push delivery
  problems (device removed after 404 / 410 or repeated 4xx, pushes falling back to ntfy), watchdog errors (skipped
  rows per hour with their ids), integration problems (ntfy share inbox refused / unreachable, Paperless failing for
  N minutes, ntfy or Web Push failing five times in a row), security events (failed-login bursts and rate-limit trips
  per user / IP, invalid `/drop` or calendar feed token bursts, a new admin, changed server switches) and storage /
  health (low disk space, daily `PRAGMA quick_check`, attachment folder errors). Each kind can be switched off; each
  admin's own topic or one shared admin topic; priority; *Send test alert*; cooldown per identical alert (6 h), at
  most N per hour (10), or one daily summary; the last 50 alerts are listed with their delivery state. Alerts never
  carry task titles, comments or other content. `KALMIDO_ADMIN_ALERTS=0` turns them off, `KALMIDO_ADMIN_TOPIC` fixes
  the topic, `KALMIDO_ADMIN_ALERT_WINDOW` sets the aggregation window.
- Tests: `admin_alerts_test.py` and `admin_alerts_ui.js`; the other suites run with `KALMIDO_ADMIN_ALERTS=0`.
- `tools/i18n_check.py` knows `Nn_("one", "other")` (plural texts translated later with `trn`).
- Admin alerts via ntfy

## [1.1.3] - 2026-09-27

### Added
- Web Push notifications, no extra app needed: *Settings > Notifications > Notify on this device* (per device, the
  browser asks for permission once), a list of your devices with remove, *Send test to this device*. Works in Chrome,
  Edge, Samsung Internet, Opera, Firefox and Safari; on iPhone / iPad in the app added to the Home Screen (iOS 16.4+,
  the settings show a hint otherwise). Every push kind uses it: reminders (with *Done* and *Snooze* buttons; *Done*
  completes the task in the background), digest, focus / break end, habits, time tracking, comments, mentions,
  assignments, completions, unblocked tasks, test. Payloads are end-to-end encrypted (RFC 8291) and signed with the
  server's own VAPID key (RFC 8292, created on the first start); the server only sends to an allow-list of known push
  services (`KALMIDO_WEBPUSH_HOSTS` adds more, `KALMIDO_WEBPUSH=0` turns Web Push off, `KALMIDO_VAPID_SUBJECT` sets the
  contact).
- Channel per account: Web Push (default), ntfy or both. While no device is subscribed, or none accepts a push, it
  goes to the ntfy topic instead ("No device subscribed yet — using ntfy for now"), so nothing is lost when switching.

### Changed
- Existing accounts move to the Web Push channel too; they keep getting ntfy until their first device is subscribed.
- The accent color Amber is now Orange (dark `#fb923c`, light `#ad4c07`, WCAG AA in both themes, clearly apart from
  the red of high priority). A stored Amber choice becomes Orange automatically.
- The image needs `cryptography` (pinned) for the Web Push encryption.
- Reverse proxy: `/static/badge-96.png` (the notification badge) belongs to the paths fetched without login.
- Web Push notifications (no extra app needed), alongside ntfy

## [1.1.2] - 2026-09-27

### Added
- Settings > Appearance collects every visual setting of the device, applied instantly: color scheme, density
  (both moved here from General), font size (small, normal, large, extra large = 90 / 100 / 112 / 125 %; the whole
  interface scales: text, rows, icons, spacing, dialogs, calendar grid and charts), font (Geist, the system font or
  Atkinson Hyperlegible, bundled) and accent color (mint, sky, violet, rose, amber, lime; each tuned for the dark
  and the light theme, WCAG AA). Live preview and "Reset to defaults". The dates, times, counters and tags stay in
  Geist Mono; the app icon stays mint.
- Command palette: color scheme, font size (larger / smaller / a size), font, accent color and "Reset appearance".

### Changed
- All sizes in the stylesheet are now rem based (1rem = 16px x font size setting).
- Appearance tab: font size, font (Geist, system, Atkinson Hyperlegible), accent colours, theme and density

## [1.1.1] - 2026-09-27

- Docs: screenshots in the new look

## [1.1.0] - 2026-09-27

### Changed
- New look, same layout: Geist and Geist Mono (bundled, no external requests), denser rows with a priority bar
  on the left edge, square checkboxes, hairline separators, date / list / assignee / time as right-aligned
  columns on desktop, cooler greys, tuned dark and light themes (WCAG AA).
- Density per device: compact (desktop default) or comfortable (phone default), Settings > General.

### Added
- Command palette (Ctrl/Cmd+K): fuzzy search over tasks, lists, filters, tags, views, settings and actions,
  actions on the selected task (complete, snooze, date, move, priority, focus, timer), recent items; text
  without a match becomes a new task.
- Keyboard shortcuts overlay (`?`), list navigation (`j` / `k`, Enter, `x`, `s`, `d`, `m`), `g` go-to keys.
- New accounts get a "Getting started" list (in their language, for their device and modules) and a short
  welcome tour, restartable under Settings > Help. Existing accounts are unchanged. `KALMIDO_ONBOARDING=0`
  turns both off.
- The sloth celebrates an emptied Today and completed lists or projects (swing, checkmark confetti, a dry
  one-liner in English or German). Settings > General > "Celebrate completions"; reduced motion shows a
  calm version.
- v1.1.0: new look (Geist, compact), command palette and shortcuts, onboarding list and welcome tour, sloth celebration

## [1.0.0] - 2026-09-27

The first versioned release. Everything below was built before 1.0.0 and is included.

### Tasks and views
- Lists with emoji and colour, folders, sections (Kanban columns), archive; subtasks up to three levels with
  drag and drop between lists and levels.
- Priorities, tags, pins, Markdown notes, attachments, a website link per task.
- Natural-language quick add in English and German (`Dentist tomorrow 3pm !high #private ~Work`).
- Recurring tasks (daily to yearly, any RRULE) with end date, count and skip.
- Smart lists, combinable filters, multi-select with batch actions, snooze, trash, search.
- Undo for completing, reopening, deleting, moving, snoozing and batch actions (also offline).
- Templates for tasks (with subtasks) and whole lists, dates relative to the day of use.
- Calendar (month, week, day), timeline, Eisenhower matrix, Kanban, statistics for the last 12 weeks.

### Habits, focus and time
- Habits per day or n times per week, counters, notes, streaks.
- Pomodoro timer and stopwatch, focus minutes per task.
- Time tracking: timers that follow you across devices, manual entries, reports per list / task / day /
  person, rounding, hourly rates, CSV export, printable timesheet, reminders for forgotten timers.

### Together
- Several users with their own inbox, habits, filters, tags, settings and notifications; built-in login or
  single sign-on through a trusted reverse proxy header.
- Shared lists (edit or view only), assignment, comments with @mentions and files, activity history,
  unread markers, a News inbox, bundled push notifications.
- Projects: dependencies ("waiting on"), progress and status per list, the *Where is it stuck?* overview,
  custom fields (text, number, selection, date, checkbox, person, link).

### Everywhere
- Installable web app (PWA) that works offline: changes queue up and sync later, with conflict detection.
- Push notifications via ntfy, calendar subscription (ICS feed), sharing from Android, app shortcuts.
- Optional Paperless-ngx integration, TickTick CSV import, JSON export.
- English and German interface; translations are plain JSON files with a checker.

### New in 1.0.0
- **Version and update check:** *Settings > Help* shows the version. Admins get a daily, server-side check
  against the latest GitHub release (a dot on the settings gear and the update commands when a new version
  is out). Nothing is installed automatically and the browser never contacts GitHub. Off with
  `KALMIDO_UPDATE_CHECK=0` or in *Settings > Users > Whole server*.
- **Instance switches** for admins (*Settings > Users > Whole server*): *Collaboration for everyone* and
  *Time tracking for everyone*. Off means nobody gets that feature and its API endpoints refuse; running
  timers are stopped at that moment; nothing is deleted and everything comes back when switched on.
- **Settings > Collaboration:** the personal collaboration switch moved out of *Layout* into its own tab.
- **First-run setup, step 2 "What do you want to use?":** presets *Just me* (no collaboration, no time
  tracking) and *Everything*, then fine-tuning per module and the language. The choices set the instance
  switches and the modules of new users. When an admin later creates the second user while collaboration is
  off, Kalmido offers to turn it on.
- Prebuilt multi-arch images (amd64, arm64) on `ghcr.io/gegenschuss/kalmido`, released automatically from
  version tags; the installer uses them and falls back to building locally.
- Tests and CI in the repository: API, UI (jsdom) and security regression suites, `bandit`, `pip-audit`,
  `semgrep`, OWASP ZAP baseline. `SECURITY.md`, `CONTRIBUTING.md`, issue and pull request templates.

### Security
Before 1.0.0 an independent AI security review (separate agent, black-box testing plus code review) was run.
All findings were fixed, re-verified and are covered by `tests/security_test.py`:
- **High:** the ntfy share inbox could be abused for SSRF / local file reads and could leak its token:
  attachments are now only fetched from the configured ntfy server (allow-list), through a request wrapper
  that allows http/https only and same-host redirects; the inbox refuses a guessable topic on the public
  ntfy.sh.
- **High:** Paperless-ngx was reachable for every user: access is now granted per user by an admin (admins by
  default); users without access see neither titles nor document ids of linked documents.
- **Medium:** strict server-side validation of dates, times, durations, reminders, colours, views and folder
  names (malformed values could break the reminder watchdog or inject HTML); recurrence rules are limited
  (no sub-daily rules, rules that never match are refused); parent cycles are impossible.
- **Medium:** the Markdown renderer no longer allows attribute breakouts in links.
- **Low:** dependency updates (Flask, Werkzeug, Waitress pinned to fixed versions), constant-time login for
  unknown users, additional security headers (CSP `frame-ancestors`, `base-uri`, `form-action`, `object-src`,
  `X-Frame-Options`, `Permissions-Policy`).
- Design fixes: members of a shared list can no longer move shared tasks out of reach of the owner or delete
  them permanently; renaming a task no longer updates the title snapshot in time entries of people who lost
  access.

[Unreleased]: https://github.com/Gegenschuss/kalmido/compare/v2.26.1...HEAD
[2.26.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.26.1
[2.26.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.26.0
[2.25.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.25.0
[2.24.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.24.1
[2.24.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.24.0
[2.23.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.23.0
[2.22.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.22.0
[2.21.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.21.0
[2.20.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.20.0
[2.19.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.19.1
[2.19.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.19.0
[2.18.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.18.0
[2.17.2]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.17.2
[2.17.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.17.1
[2.17.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.17.0
[2.16.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.16.1
[2.16.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.16.0
[2.15.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.15.1
[2.15.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.15.0
[2.14.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.14.0
[2.13.4]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.13.4
[2.13.3]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.13.3
[2.13.2]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.13.2
[2.13.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.13.1
[2.13.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.13.0
[2.12.2]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.12.2
[2.12.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.12.1
[2.12.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.12.0
[2.11.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.11.0
[2.10.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.10.0
[2.9.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.9.0
[2.8.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.8.0
[2.7.2]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.7.2
[2.7.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.7.1
[2.7.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.7.0
[2.6.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.6.1
[2.6.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.6.0
[2.5.2]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.5.2
[2.5.1]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.5.1
[2.5.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.5.0
