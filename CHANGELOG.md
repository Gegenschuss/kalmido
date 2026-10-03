# Changelog

All notable changes to Kalmido are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Kalmido uses
[semantic versioning](https://semver.org/): every published change gets at least a new patch version, new features a
minor one, anything that needs action on your side a major one.

## [Unreleased]

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

[Unreleased]: https://github.com/Gegenschuss/kalmido/compare/v2.13.2...HEAD
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
