# Team: workload, absences, disposition

Kalmido's team views live in **Workload** (sidebar, module "Workload"). Since 2.50.0 the view has three tabs:
**Workload**, **Absences** and - with the module "Disposition" switched on - **Disposition**.

## Absences (2.50.0)

- Everybody enters their own absences: **Absences > Enter an absence** - vacation, sick leave, day off or other,
  one day or a period, optionally half a day (morning / afternoon) and a note. There is no approval: entering is enough
  (unless the organisation's admins switch on vacation requests, see below).
- The admins of an organisation can also enter absences for its members.
- **Which area:** the workspace switch decides (2.96): on an organisation its absences, on **Private** your own
  personal area (also as a member of organisations), on **All** the first organisation. The picker at the top switches
  between them.
- **Who sees what:** the team sees *that* somebody is away and when. The kind (above all sick leave) and the note
  only the person and the organisation's admins see. Kind and note are stored encrypted when the server's
  encryption at rest is on.
- **Public holidays:** an organisation's admins pick a German state at the bottom of the tab; Kalmido computes the
  statutory holidays itself (no external service). People without an organisation set their own.
- **Effect:** in the workload a week's capacity shrinks by the absent workdays and holidays (a week away = no
  capacity). *Plan my day* shows a hint instead of a proposal on a day away. Assigning a task to somebody who is
  away on its day shows a warning - the assignment still happens.
- Deleting an absence can be undone.
- Agents read only "away" and the period of their own organisation (`GET /api/v1/absences`, MCP `get_absences`),
  never the kind.

## Working days and weekly hours (2.125.0)

- **Settings > General > Working week**: the days you work (Monday to Friday by default) and your hours per week
  (empty = 5 x the server's hours per day).
- The workload spreads the hours per week over your working days: an absence or a public holiday on a working day lowers
  the week by that day's share, a day off on a day you do not work costs nothing. The hint *Maybe forgotten* in the time
  view and the vacation account count only working days.
- An organisation's admins set the working days and hours of their members in **Absences > Vacation accounts**
  (they are the person's own settings, so they apply in every organisation of that person).
- Without a setting everything stays as before (Monday to Friday).

## Vacation account and vacation requests (2.125.0)

- **Vacation account:** per person and year an entitlement in days (half days allowed) and an optional carry-over from
  the year before. The admins of an organisation set it for its members in **Absences > Vacation accounts**; people
  without an organisation set their own there. The tab shows *entitlement*, *taken* (approved vacation working days of
  the year; half days count 0.5, public holidays of the state and days you do not work do not count), *requested* (open
  requests) and *left*. No entitlement = no account, nothing changes.
- **Vacation requests:** off by default. An organisation's admins switch on **Vacation of members needs an approval** in
  **Absences > Vacation accounts**. Then vacation a member enters for themselves is a request: the person and the admins
  see it marked *requested* (striped in the grid); the team, the workload, *Plan my day*, the booking page and agents
  treat the person as present until it is approved. Sick leave, days off and other absences never need an approval;
  vacation an admin enters (for themselves or a member) is approved at once. People without an organisation never ask.
- **Deciding:** the admins see **Open vacation requests** with *Approve* and *Reject* (an optional note for the person).
  Undo opens the request again. A member who changes the period of a request or an approved vacation, or changes a
  rejected request, asks again.
- **Notifications:** the admins get a News item and a push about a new request, the person about the decision; the row
  *Vacation requests* of the notification settings switches both off. The notes stay in the app.

## Disposition (2.50.0)

Book crew and equipment for shoot days and see who and what is free.

- Switch it on in **Settings > Modules > Disposition** (off by default; for organisations and for freelancers in their
  own area).
- **Book:** a title, the day(s), optional times, *Option* (pencilled in) or *Firm*, optionally a project list, and the
  resources: members of the organisation, contacts from the organisation's address books (crew without an account),
  devices and device sets from *Office & finance* (a set books its devices along).
- **Warnings, never blocks:** a person or device booked twice at the same time, or a person who is away
  (vacation, sick leave, day off), is marked; the booking stays.
- **Week grid** with one row per resource (phones: a list per day), **Who is free on ...?** for a single day.
- **My bookings** lists your own bookings; a firm booking also shows up in your News (event "assigned to me", with
  its usual switch in the notification settings).
- Changing or deleting a booking applies to the whole job (one shoot day); deleting can be undone.
- **Export (2.141.0):** the buttons *CSV* and *ICS* next to *Book* download the bookings the view shows (same period, filter and
  organisation). CSV: resource, kind, booking, project, status, start, end, hours (timed bookings only), note. ICS: one event per
  booking, whole days as all-day events, an option as tentative. Your own bookings also appear in your calendar.

## Agents plan with you (2.51.0)

- **Weekly status on the project page**: plan a job for an agent with the template *Status on the pin board*. The agent writes
  one block "Status" on the project page (done, stuck, overdue, who waits on whom) and overwrites only that block each week. It
  is marked "From <agent>, updated ..."; you can edit or delete it as usual. The agent needs the permission *Pin board*.
- **Time tracking**: with the template *Check time tracking and propose entries* the agent points out implausible entries and
  sends one proposal with entries for past events without time. You change times and note and apply it (one undo step). Share
  your calendar with the agent so that it sees your events.
- **Shoot planning**: an agent proposes shoot days and crew / equipment for a project. Warnings show double bookings, absences
  and other projects that day. Applying creates per day a task in the project with a draft in your calendar and pencils in
  crew and equipment as options, never firm.
- **Drafts in the calendar** (tentative events) look pale and dashed and say *Draft*. Tap one: *Confirm* makes it a normal
  event, *Discard* deletes it (undo brings it back).


## References in comments and descriptions (2.53.0)

- **Drag to reference:** drag a list or folder from the sidebar, a task from a list or the calendar, a file from the
  Ablage, a contact or a calendar entry onto the comment field or the description. Kalmido puts a reference in at the
  drop point: a task as `#123`, everything else as a Markdown link to this instance (`[Name](https://…/#l/80)`). Other
  drops (moving tasks, attaching files) work as before; only the text fields take references.
- **Phone / tablet:** the link button next to the comment box (and *Insert reference* under the description) opens the
  search; the pick goes in at the cursor. It finds lists, folders, open tasks, contacts, appointments of the coming
  months and the files of the Ablage folder that is open.
- **Cards:** a link to this instance shows as a small card with an icon (list, folder, task, contact, appointment,
  document) and the name *the reader* sees now - never the label the author typed. A target the reader cannot see (or one
  that was deleted) is a grey *No access* card without a name and without a link.
- **Preview:** with a mouse, resting 0.4 s on a task number or a card shows a preview next to the pointer - for a task its
  status, list, priority, due date, assignee, tags, subtask progress, the start of the description and the number of
  comments and attachments; for a contact company and phone, for an appointment time and place, for a list its open
  tasks, for a document size and date. Clicking opens the target as before. On touch screens a tap opens it directly.
- Names and previews come from what is already loaded or from the normal read routes, which check access; agents see
  references in comments as plain Markdown text.

## Urgent tasks (2.53.0)

The bell in the header of a task decides how that one task notifies you: **As the list** (default), **Muted** (no pushes
for it, News stay) or **Urgent** - until it is completed or until a date. Urgent sends every change and every comment of the
task as a push at the highest priority, even if the list is quiet.

- **For others**: the owner and the admins of a list can mark a task urgent for some or all people of the list (*Urgent for
  others…* in the bell's menu). The people get a News item and see "Urgent, set by ..." on the task. Everyone can switch it
  off for themselves; the task history notes it.
- **Refuse it**: *Settings > Notifications > Accept urgent markings from others* off - such a marking then counts as
  "As the list" for you.
- **Honest limit**: on Android (ntfy) an urgent push comes through. On an iPhone the web app cannot break through Focus or
  silent mode; there it is a prominent push, not an alarm.
## Comments by agents: only replies to me (2.62.0)

*Settings > Notifications > Comments by agents* decides which comments of connected agents reach you (News and push):
**All** (default, as before) or **Only replies to me**. With "only replies" an agent's comment reaches you only when it
answers one of your comments (reply), comes right after your comment on that task, or @mentions you.

- A task marked **Urgent** for you still brings every comment of that task; a list bell **All** does not override "only replies" for agents.
- Approval cards, questions with buttons and suggestions of an agent always arrive: they wait for your answer.
- A list bell **All** and a task marked **Urgent** for you still bring every comment of that list / task.
- Pushes about other things agents do (new tasks, completions) keep their own switch.
- **The bell (2.66.1)**: the agent comments that reach you count in the bell's number and under *For you* - with "only
  replies" its replies and mentions plus what reaches you anyway (approval cards and questions waiting for you, comments on
  a task marked **Urgent** for you), with **All** every agent comment. Other things agents do (completions, status,
  new tasks, assignments) stay under *Activity* without a number.

## Address books of the organisation (2.52.0)

- An address book in an organisation's workspace can belong to the organisation instead of a person: **Contacts > Address
  books > More > Hand over to the organisation…** (the owner, if they are an admin of that organisation). Nothing is handed
  over automatically.
- Admins of the organisation manage it (rename, colour, shares, birthdays, delete). **Members of the organisation** sets what
  the other members may: *They can view* (the default), *They can edit*, or *Only admins and people it is shared with*.
  Sharing it with single people of the organisation keeps working; kid accounts and agents get it only through a share.
- It stays when people leave: if the person who handed it over (or the admin who chose its birthday list) leaves the
  organisation or their account is deleted, another admin (else another member) takes over. Its contacts, its birthday list
  and the links to tasks stay. Only when nobody else is left in the organisation does it go with that person as before.
- It always stays in its organisation's workspace and is seen only by its members. Phones get it over CardDAV like any other
  address book (read-only when members may only view).
- **Make personal again…** only undoes one's own hand-over (2.148.1): the admin who handed it over gets it back as their
  own; other admins keep it with the organisation and can export or copy the contacts.

## Report forms (2.63.0)

A list's form (list menu, Forms) can work as a report form for customers: **Type of report** gives every sent task a
type (bug, feature, task), **Allow one file** adds a file field (at most 10 MB, stored like other attachments and counted
against the list owner's storage; an executable ending gets `.txt`), and **The sender gets a link to the status** asks for
the e-mail address (required then). After sending, a person without an account sees a status link on the thank-you page
and gets it once by mail; the link shows only that report (see the customer portal). People of the organisation who
send a form signed in get no status link: they see the task in the app.

Against spam, without any outside service: the hidden honeypot field, limits per address and per form, a signed time
stamp in the page (sent sooner than 3 seconds after loading or more than 24 hours later = "please send it once more"),
at most 5 reports per e-mail address, form and hour, at most 3 confirmation mails per address and hour (plus the server's
mails per address and day) and at most 5 links in the text.

## Questionnaires: own questions in forms (2.98.0)

A form can ask its own questions instead of subject and description (form dialog, **Questions**): short text, long
text, a choice (one or several options), date, number, a file upload and yes / no; each with a help text and the switch
**Required**. Drag a question by its grip to reorder it (touch too), or use the up / down buttons. A form without own
questions stays the classic form.

- **One question per step**: the page shows one question at a time with Back / Next and the progress; else all questions
  on one page. Both work without scripts. Required answers, numbers, dates and choices are checked on the server; a send
  with a problem shows the page again with the typed answers and opens the step of the first problem (files have to be
  chosen again).
- **Files**: at most three file questions per form, one file each, at most 10 MB; pictures, PDF, office formats and text
  only. They become attachments of the new task (sealed, scanned and counted like every attachment).
- **The task**: in the form's list (and section) as before, titled with the form and the sender; the answers stand in
  its description as Markdown, a heading per question.
- **Client**: with **Match the e-mail to a client** the sender's address is looked up among the clients of the list's
  space only (the list's own client first, else the one client of the list's organisation, or of the owner's private
  space, with that address or a contact person with it). Found: the task names the client; unknown: the task says
  "Client unknown". **Unknown address: create a new client** (off by default) creates one there instead (at most 20 per
  form and day).
- **Submissions**: the form dialog lists the tasks the form made with their answers (only those still in its list and
  not deleted) and downloads them as CSV, a column per question. Only the people who manage the form see them.
- Moving the list into the other workspace takes its forms and their questions along; a client of the old workspace is
  then no longer named in the submissions.

## Tracked time of a project and templates (2.63.0)

- **Who sees whose time.** In the window "Tracked time" of a project, the time reports and the CSV, the owner of the list,
  its admins and the admins of its organisation see everyone's entries. Everyone else sees their own there, and the window
  says "Your time only". The time list in a task's detail still shows everyone's entries of that task.
- **Excel export (2.125.0).** Next to *CSV* the time view and the client page have *Excel (XLSX)*: the same filters,
  columns, rounding and visibility as the CSV, but hours and amounts as numbers, start and end as date-time cells and a
  sum row at the end. The workload view has the same button: people x weeks with the planned and the capacity hours per
  week (only the people and tasks you may see). Without an organisation it works the same on your own data.
- **Timer shortcut (2.125.0).** The installed app (Android, desktop) offers *Start / stop timer* in its long-press menu
  when the module "Time tracking" is on: it opens the time view and starts a timer on the basket, or stops the running one.
- **Templates keep the project page.** "Save as template" on a project also saves its notepads, the standard arrangement of
  the project page and the block colours. A project made from the template gets its own copies of the notepads, placed and
  coloured as in the original. Notepads written by agents stay with their project.
- **Undo after "Delete all times of this project"** brings the entries back exactly as they were, including the link to a
  timer started on a phone, so a stop that arrives later from that phone still finds its entry.

## Monthly timesheets: close, approve, send back (2.125.0)

- **Close a month.** On the time page choose *This month* or *Last month*: a card shows the month's timesheet. *Close month*
  locks your entries that start in that month: no new entry, no change, no delete, no timer start or stop into it, focus
  sessions and agents' proposals no longer add time there, and *Delete all times of this project* leaves them. The entries
  show a lock instead of the edit buttons. An entry from the 31st 23:00 to the 1st 01:00 belongs to the month it starts in.
  A running timer of that month has to be stopped first. *Reopen* unlocks it again as long as nobody approved it.
- **Approval in an organisation.** The admins of your organisation get a News item (and a push) and see your closed month
  under *Timesheets of your team*, with the hours on the organisation's lists (never your private time). They *Approve* it
  or *Send back* with a note: then the month is open again and you get the note. An approved month only an admin reopens.
  Members cannot decide, admins of another organisation never see it. Every step is one Undo step.
- **Without an organisation** you are your own admin: closing locks the month, there is no approval step, you reopen it
  yourself.
- **Notifications:** the event *Timesheets* in Settings > Notifications (News and push, both can be switched off).
- **Agents and the API** get `409` with the error code `month_closed` when they write into a closed month.

## Time zone and entries over midnight (2.125.0)

- **Your own time zone** (Settings > Modules > Time tracking > *Time zone*; empty = the server's, the device's zone is offered
  as a suggestion) decides on which day an entry counts, the periods of the report, the CSV and the timesheet, "today" and
  the month of the lock above. The calendar, reminders, workload and absences keep the server's time zone. With *All members*
  the report uses your time zone for everyone's entries.
- **Entries over midnight** (on by default): an entry from 23:30 to 00:30 counts with 30 minutes on each day in the days of
  the report and the timesheet, and the CSV has one row per day. The entry itself stays one entry, the totals stay the same.
  Rounding stays per entry: the rounded time is split by the share of each day, never rounded twice. Switched off, an entry
  counts on the day it starts, as before.

## Saved arrangements and templates (2.55.0)

- **Several arrangements per view.** The start page, Today, Time tracking, the overviews, the review and every project page
  can keep named arrangements of their blocks, e.g. "Focus" and "Overview". *Save as arrangement…* sits in a block's "…"
  menu and in *Customize*; once a view has one, its header shows a switch (Today: in the view's "…" menu) with *Standard*,
  the saved ones and *Manage arrangements…* (rename, order, delete). They are the same on every device.
- **Switching** shows the saved arrangement as your own arrangement of the view; changes you make while one is active go
  into it. *Reset to the standard* or choosing *Standard* ends that, the saved one stays. Saving, renaming, deleting and
  switching are each one undo step. At most 12 per view.
- **Send as template…** sends the current arrangement to people you see (your organisations and connections; never to
  agents, at most 20 at once; a project page only to people with access to it). Only the arrangement travels (blocks,
  order, widths, heights, a block's switches), never content: a block the recipient cannot see simply stays empty. They get a
  News item ("For you", switched off together with the sharing News) with a preview and *Take over* / *Decline*; taken over,
  it is their own saved arrangement, named after the sender, with no link back.
- Agents cannot use any of this (403); they propose arrangements their own way (2.55.0, #1066).

## Sprints (2.60.0)

For teams that work through a shared backlog (software, agencies): a project list can plan in **sprints**, time boxes of one
or two weeks with a goal. Off by default; switch it on in the list dialog (*Sprints > Plan in sprints*, people who may edit
the list). *Settings…* sets the length (1 week, 2 weeks or free), the start weekday and whether open tasks move to the next
sprint automatically.

- **The sprint header** above the list and the Kanban: name, dates, goal, progress (tasks, or story points when the list
  uses them) and a small burndown with an ideal line. On the phone it folds away with a tap on the name.
- **Filter**: *All*, *Current sprint* or *Backlog* (tasks without a sprint), right in the header.
- **Plan**: *Sprint…* in a task's menu, the *Sprint* field of the multi-selection, or drag tasks onto the sprint header. Each
  step can be undone. *Sprint options > Show the sprint in the task row* shows the sprint in each task row.
- **Close**: *Close sprint* shows the review (done, still open, added after the start) and asks where open tasks go: into the
  next sprint or back to the backlog. The next sprint starts right away; a sprint whose last day is over closes by itself.
  *Sprint options > All sprints* lists every sprint with its review; there you can also plan the next ones.
- Agents of the list read sprints, put tasks into them and hear when a sprint starts or closes (see [AGENTS.md](AGENTS.md#sprints-2600)).

## Review step (2.60.0)

For software teams and anything that needs a second look. Off until a list switches it on: list settings > *Review
step*, with an optional default reviewer, the review section (default: the section named *Review*) and *Done only after
approval*.

- A task shows its reviewer and the review state in the task panel (*Choose reviewer*, *Send for review*). The reviewer
  is a person or an agent of the list.
- Moving a task into the review section (dragging on the board or changing the section) asks its reviewer; they get a
  News item and a push (Settings > Notifications, row *Reviews*).
- The reviewer (or an owner / admin of the list) presses 👍 *Approve* or 👎 *Back* (with an optional note). *Back*
  returns the task to the section it came from and tells the assignee. Nobody approves their own task unless they are a
  list admin.
- With *Done only after approval*, ticking off waits for the approval: the tick explains it and offers *Send for
  review*. Without a reviewer ticking off stays free.
- A linked pull request that is merged, or approved with 👍 in Kalmido, counts as the approval.
- Every step can be undone.

## Video sign-off with comments at a timecode (2.99.1)

For film and video work: the customer or a colleague watches a cut and comments at the second it is about. **Kalmido
stores no videos**: a video sign-off holds **links only** -- Vimeo (also unlisted with its hash), YouTube (also unlisted,
youtu.be, Shorts) or a direct video file over https (MP4, WebM, MOV, e.g. a file link from Nextcloud, a NAS or Dropbox; the
link has to end with the file name). Any other link (a Google Drive page, a Nextcloud share page) is a *link without time
control*: it opens in a new tab and its comments carry no timecode.

- Where: a task's panel (*More details* > *Video sign-off*), a project's overview and a client's card: *Add video link*.
- Comments: typing pauses the player and keeps its time (*at 01:23*; a tap on it comments without a time). A tap on a
  timecode or on a mark of the time line under the player jumps there. Answers (one level), *done* and back, delete.
- Versions: *New version…* in the menu adds the next cut (v1, v2 …); the version switch shows the older ones with their
  comments.
- Export: *Copy comments as text* (timecode, name, text, done -- for the edit) and *Download comments (CSV)*.
- Customer link: *Create customer link* gives a page without an account (the approval link of the office, see
  [OFFICE.md](OFFICE.md) *Approval by the customer*): the newest version, the customer's comments with a timecode (name
  needed) and *Approve* / *Request changes* (with a reason). The decision sets the state of the sign-off and stands in its
  comments; the creator of the link gets a push (notification switch *Approval requests*, also for the customer's first
  comment within ten minutes). Comments of the team stay internal; only answers to the customer's comments are shown to
  them. A new link stops the older one; deleting the sign-off stops it at once.
- Rights: who sees the task / project / client sees the sign-off and may comment (like task comments); changing it, new
  versions, the customer link, moving and deleting need the right to edit there. A locked list (end-to-end) has none.
  At a client (2.122.4) that is an office role in the client's organisation (or, for a private client, its creator).
- *Move to another workspace…* takes it with its versions and comments into a project of the private space or an
  organisation (its creator or an admin of the organisation); the customer links and their record stay in the old
  workspace. Undo brings it back to its old place. Since 2.122.4 the records stay bound to the sign-off and show again
  when it comes back; in the new workspace they never show.
- Deleting for good: a sign-off in the trash is deleted for good after 30 days with its versions, comments and customer
  records. A task, project or client that is deleted for good takes its video sign-offs with it, including the customer's
  recorded decision (like the approval records of documents).
- Every step can be undone. The players are embedded without loading any script of Vimeo or YouTube (YouTube through
  youtube-nocookie.com); only the two player addresses may be framed (Content-Security-Policy).

## Story points, WIP limits and velocity (2.60.0)

For software teams working on a board. Everything is off until you switch it on.

- **WIP limit per column**: in a kanban column's menu choose *WIP limit…* and enter how many open tasks the column should
  hold (empty = no limit). The column head then shows "2/3"; above the limit the number and the head are marked in the
  warning colour and a move into the column says so. Moving stays allowed. New projects of the type *Software / AI dev*
  with the standard sections start with a limit of 3 for *In progress* and *Review* (change or remove it any time).
- **Story points**: in the list dialog (lists with ticket types or sprints) turn on *Story points*. A task then gets the
  field *Story points* (1, 2, 3, 5, 8, 13) in its panel; the number shows in the task row and on the card, the kanban
  column heads add up their points, and the multi panel sets them for many tasks at once. Each change is one undo step.
- **Velocity**: with sprints and story points on, the project page offers the block *Velocity*: the completed points of
  the last (up to six) closed sprints as bars and their average as a planning aid for the next sprint.
- Agents read and set the same through the API and MCP (`points`, `set_wip_limit`, `get_velocity`, see AGENTS.md).

## Swimlanes on the board (2.138.0)

The button *Swimlanes* above a kanban board groups the cards into horizontal lanes: by **person** (the people with tasks
on the board, then *Nobody assigned*), by **priority** (High, Medium, Low, No priority) or by a **custom field** of the
list (a select field: its options, then *No value*; a checkbox: yes / no). *None* shows the board as before.

- The column heads (count, WIP limit, points, the column menu, dragging a column) stay in one row on top; each lane has
  its own head with name and count and folds with a tap (it stays folded).
- Dragging a card into another lane sets that lane's value (priority, field or person; a person replaces the previous
  one); a move into another column at the same time is one undo step. Only people who may edit the list can drag.
- *+ Task* in a lane creates the task with the lane's value.
- On a phone the lanes stand below each other and the board swipes sideways as a whole; a long press drags a card into
  another lane.
- The choice is remembered per list on your account in this browser; other members choose their own.
## Photo metadata on upload (2.61.0)

Photos keep a lot about where and how they were taken: the place (GPS), the camera and its serial number, the capture
time. Uploaded photos lose these metadata before they are stored, on every way in (file store, task and comment files,
project files, chat, documents, mail and sharing into Kalmido); profile pictures and list icons were already stored without them.

- JPEG, PNG, WebP and HEIC / HEIF, recognised from the content, not the file name. The picture itself stays as it was:
  only the metadata blocks are cut out (JPEG keeps its colour profile; HEIC keeps its structure, its metadata blocks are
  emptied). A photo stored turned (the camera's orientation mark) is turned upright first and saved again, so it shows the
  right way round without the mark. Anything Kalmido cannot read is stored unchanged; the upload never fails because of it.
- The switch *Remove location data from photos* (on by default) also removes camera details and capture time. For your
  private files it sits in *Settings > Data > Photos*; files of an organisation follow the organisation's switch in
  *Settings > Workspaces*, which only its admins change. Off: photos are stored exactly as uploaded.
- Documents: the capture date is read before the metadata go (also with the switch off) and shown in the document's
  detail (*Taken on …*). When the recognised text has no date, the document gets the day the photo was taken, marked
  *automatic* like other recognised values. The place is never stored.
- Browser-encrypted files (end-to-end) are not touched: the server cannot read them.
- Agents cannot change either switch.
## Files and documents into the other workspace (2.96.0)

Files, folders (with everything in them) and documents move between the private space and an organisation, both ways:
**Move to another workspace…** in a row's menu of the file store, or **Select** (check boxes, also on the phone) and the bar
*n selected · Move to… · Move to another workspace…*. In *Documents*, **Select** chooses cards (or *Select all* of what the
search and the filters find) and moves them into the documents folder of the other workspace; a single document has the
button in its sheet. The dialog names source and target and says beforehand what happens: how many files, duplicates
already there, shares and openings to the whole organisation that end, what stays (links to task files, agent folders,
the trash). Sender, type, tags, the archive number (when it is free there), the recognised text and a Paperless origin go
along; the files are sealed again with the target's key. One undo step moves everything back.

Out of an organisation only an organisation admin moves something (2.148.1; before, the owner or who uploaded it could);
a person without an organisation has no other workspace and does not see the action. Agents never move data between
workspaces. Receipts the cash book or the equipment list points to stay in their workspace.

**Leaving an organisation is the admins' call (2.148.1).** Lists (also through a folder's workspace), copies of a list,
files and folders, tables, contacts (single or several at once) and *Save as task* from a channel of the organisation
leave it -- into the private space or another organisation -- only through an admin of that organisation; everybody else
gets "Only organisation admins can move data out of the organisation." Each such move is written to the organisation's
list history (*Settings > Workspaces > Lists*) and the other admins find it in their News. Moving something from the
private space into an organisation and moving inside one organisation work as before; a person without an organisation
moves freely in the own private space.

## File requests: clients upload into a folder (2.122.0)

A client sends logos, contracts or receipts without an account: **Request files…** in the menu of a folder of the file
store (everyone who may add files there) opens the folder's requests and **New file request**. A request has a title
and a note for the client, an end date (required, suggested in 14 days, at most 90), the size per file, how many files
in all and the allowed kinds (documents and pictures ticked; design files, archives, audio and video on request).
Programs, web pages and SVG files are never accepted, also not under another ending: the content must fit the name.
Optionally every request gets its own subfolder. **Create link** copies the link; the row also has a QR code.

The page of the link (`/u/<token>`) shows only the title, the note and a file field (drag and drop, a progress bar per
file; without JavaScript the plain form works). It never shows the folder, its files or other uploads. The files land in
the folder as files of whoever asked (counted on their storage, scanned and sealed like every upload, a free name instead
of overwriting); the history of each file says *received through a file request*. A request in the documents inbox
folder is recognised like any other document there.

The folder's list shows each request as open, expired, stopped or not working, with the number of files that arrived.
In its menu: **Extend by 14 days**, **Stop the link** (it stops at once; *Open again* brings it back) and **Remove**;
each is one undo step. A link also stops when its folder goes into the trash or into another workspace, or when whoever
asked can no longer add files there. Unknown, expired and stopped links get the same answer. Limits per address and
link (sends per minute and hour, a daily volume per link: `KALMIDO_FILE_REQUEST_MB_DAY`, default 1000 MB) keep a
link in the open from filling the disk. Public links have to be on (Settings > Administration); a person without an
organisation uses requests in the own folders the same way.

Whoever asked gets one News item (and a push) per request when files arrive; more files within ten minutes raise its
count instead of sending again. *Files from file requests* in the notification settings switches News and push off.

## Several files at once, ZIP download, scanning with the phone (2.138.1)

In the file store, **Select** (check boxes, also on the phone) and the bar now also offer **Download** and **Move to the
trash**. Download of one file gives the file itself; several items or a folder become one ZIP that keeps the folder
structure (a doubled name gets " (2)"). A folder's menu (its row or the open folder's "…") has **Download as ZIP**. The ZIP
holds only what you may see: nothing from the trash, no links to task or project files, no file the virus scanner locked
or has not checked yet. Moving several items into the trash is one undo step that brings all of them back. On a phone the
moves of the bar sit in its "…" menu.

**Scan** next to *Upload* (and in *Documents*) opens the scan dialog: take a photo per page with the camera (on a computer:
choose pictures), turn a page by 90 degrees, change the order, remove a page, then **Save as PDF**. *Black and white
(document)* (on by default) gives a clean grey page. Kalmido builds one PDF on your own server -- at most 30 pages, every page
scaled to about 2000 pixels, without the photo's metadata or location -- and stores it like an upload: the storage limit,
the virus scan and the text recognition apply. From *Documents* the PDF becomes a document of the workspace there.

## Links for external people (2.138.1)

A file or a folder of the file store can go to people without an account through a secret link: **Link for external
people…** in a row's menu, or **Create link** in its details. Choose how long it is valid (1 day, 7 days, 30 days, until a
date, no end), optionally a password and a label only the owners see (one link per customer, for example). The page shows
a file with its size and a download button (pictures with a preview), a folder with its folders and files, each to
download, and the whole folder as a ZIP. Nothing else: no upload, no versions, no comments, no names of people. A row with
a live link carries a link badge; the details list every link with views and the last time it was opened, **Copy**,
**New link** (the old address stops at once) and **Revoke** (one undo step brings the same address back).

Only who may share the item (its owner, an organisation's admins) makes a link; agents never do, and folders of agents,
linked task files and items in the trash cannot be shared outside. A link stops working at once when it expires, is
revoked, the item or a folder above it goes into the trash or into another workspace, the person who made it can no
longer share it (left the organisation, no longer admin), the organisation's admin turns off **Allow external share
links** (Settings > Workspaces; nothing is deleted, turning it on brings the links back) or the server's admin turns off
public links. Every view and download through a link shows up in the item's history, without the visitor's address;
the page is never indexed or cached, and guessing addresses or passwords is limited per address. A person without an
organisation shares from the private space the same way (only the server's switch applies).

## Pinned chat messages (2.62.0)

Important messages stay in view: in the team chat and in the chat with an agent, *Pin* in the menu of a message (on a
phone: press and hold the message) puts it into a bar at the top of the conversation. With several pins the bar shows
the newest; a tap on the arrow goes through the others, a tap on the text jumps to the message, also when it is further
up than the loaded part. *Unpin* in the same menu (or the x in the bar) takes it out again; Undo brings it back. At most
five messages per conversation are pinned; a deleted message leaves the bar. Everyone in a team chat conversation can
pin, in an agent chat the person and the agent. Others see the change right away.

A message is sent once: it shows at once as *Sending…*, and Send / Enter wait until the server took it, so pressing
Enter again (for example right after waking the laptop) does not send it twice.
## Channels, groups and files in the team chat (2.138.1)

Besides the chat of every shared list there are **channels** anyone opens: *Team chat > New message > New channel*. A
channel of an organisation is either *open to the whole organisation* (everyone in it finds it under *Browse channels*
and joins; writing in it joins too) or for invited people only. Without an organisation (your own space) a channel is
always for invited people, chosen from the people you work with. Its creator and the admins of the organisation rename
it, open or close it, add and remove members and archive it (the gear in the head of the channel); an archived channel
stays readable for its members and comes back with *Restore*. Each change is one step of *Undo*. Since 2.148.1 only the
channel's members (and its creator) open a closed channel or add an agent to it; an admin who is not a member can still
archive it.

**Groups** are conversations of three or more people (*New group*): everyone in a group must work with everyone else
(the same people you could write a direct message to). The name is optional; without one the group is named after its
members. Every member adds people and leaves; nobody removes someone else. A group notifies like a direct message.

**Files**: the paperclip next to the message box, pasting an image or dropping files on the conversation adds up to ten
files to a message (50 MB each). Images show as thumbnails (a tap opens them large), other files as tiles. Everyone in
the conversation opens them; deleting the message deletes its files for good. End-to-end encrypted conversations
(encrypted direct messages, the chat of a list with the lock) take no files.

Agents take part in a channel only when a person adds them: your own agents, and as an admin of the organisation its
shared agents. They never join groups.

## Threads and "Read by" in the team chat (2.139.0)

**Threads** keep a side topic out of the main conversation: *Reply in thread* in the menu of a message (the three dots)
opens the thread next to the conversation (on a phone full screen, *Back* returns). Answers there stay out of the main
conversation; under the first message a slim line shows how many answers there are, when the last came and who wrote
them, with a dot while some are unread. Editing, deleting, reactions, pinning, quoting a message and *Save as task* work in
a thread as everywhere; a search hit or a pin of a thread answer opens its thread. A deleted first message keeps its
thread ("Message deleted" stays above the line).

The unread count of a conversation counts the main conversation and the threads you take part in: you wrote the first
message, answered or were @mentioned. Only those people are notified of a new answer (the conversation's *Mute* and the
notification settings still apply); everyone else sees the thread line without a push.

**Read by**: under your own latest message that someone has read a small grey line says *Read* (a direct message) or
*Read by 3* with small pictures (groups, channels, the chat of a list); a tap lists who read it and who did not yet. There
are no ticks at every message. *Settings > Chat > Send read receipts* switches it off: then nobody sees when you read,
and you see nobody's read state either.

## The customer portal (2.63.0)

A form with **status link** turns every report sent without an account into a customer report: the reporter gets a link to
its status page (on the thank-you page and by mail). There they see the title, the state (received, in progress, done), the
text they sent, the team's public answers and their own comments, and they can answer. **All my reports** sends a sign-in
link (valid 30 minutes, once) to their address; it opens a page with all their reports in the same organisation (or the same
private list owner) - never reports of another organisation, even with the same address. Nobody needs an account.

- **Internal stays internal.** In the task panel, a customer report shows the box *Customer report* (who sent it; the
  address, *Copy the status link* and *Mails to the customer* only for people who may change the task). The comment box
  gets a switch *Internal* / *To the customer*: it starts on *Internal* every time. Only comments sent with *To the
  customer* reach the customer; they are marked "to the customer", the customer's own ones "Customer". A public answer
  cannot be made internal later (the customer may have it by mail already); delete it if needed.
- **Mails.** The customer gets a mail for a public answer and when the report is done - at most one mail per report every
  10 minutes, every mail with a link that turns them off. *Mails to the customer* in the box does the same for the team.
- **Clients.** A report belongs to the list's client, else to the client of the organisation whose e-mail (or a contact
  person's) is the reporter's address. The client's card lists its reports (block *Customer reports*).
- **What the customer never sees:** internal comments, the notes once the team changed them, assignees, files, other tasks,
  names of team members other than the name of an answer's author.
- Agents answer customers the same way (`add_comment` with `portal: true`, see AGENTS.md).

### Quotations and invoices in the portal (2.120.0)

With *Office > Settings > Invoices > Show documents in the customer portal* (off by default; the office's admin, or the
person in their own personal office) the portal also lists the client's **documents**: sent quotations (with the button
*Review and approve* while an approval link is open), invoices with their payment state (open, partly paid with the open
amount, overdue, paid; the due date) and credit notes. Each opens as the PDF that was sent. The customer is every client
of the same organisation (or the same personal office) whose e-mail or e-mail for invoices is the signed-in address.

- **Getting in.** In the client's menu (*More*) **Send portal link** mails the client the same one-time sign-in link
  (30 minutes, once; then signed in for 7 days) to the e-mail for invoices, else the e-mail. No account, no password;
  at most three links per address and hour.
- **What the customer never sees:** drafts, invoices that were finalised but not sent yet, reminders, internal notes,
  purchase prices, documents of other clients - and nothing of another organisation, even with the same address.
- Switched off (or public links off on the server), the portal is exactly as before.

## A task in several lists (2.71.0)

- **Show also in list…** in a task's menu (and in the task panel's list path) puts the task into a further list of the same
  workspace without copying it: it is one task, every change shows everywhere. *Remove from <list>* takes it out of that
  list again; the task stays. Both are one undo step, and the task's history notes them.
- In the further list the row says **From <its list>**, in its own list **Also in <list>**. The further list has its own
  place and column for it: dragging it there (also on the board) moves only that place, never the task into another list.
- **Who sees it** is decided by the task's own list only. Someone who sees only the further list does not see the task
  there (nor in search, the calendar feed, a public link or an export). Lists of another organisation, private lists of
  an organisation's task (and the other way round), health lists and locked lists cannot be used.
- It counts once: in statistics, Today, the calendar, search and exports. The sidebar counts it in each list it is in.

## Rules in lists (2.71.0)

In the list settings the owner and the list admins find *Rules*: "When a task comes into the column Review, assign it to
the reviewer" in one sentence per rule, a switch, edit and delete (undo brings it back). *Add rule* asks for a name, *When* (a
task comes into a column, is completed, is opened again, gets a list tag, its due date is reached) and *Then* (assign to
a person of the list, set or remove the due date, write a comment, move to a column or another list of the same
workspace).

- A rule runs with the rights of the person who set it up. Loses that person the access or the admin role, or the target
  list becomes unreachable, the rule pauses and the settings say why; switching it on again makes the person who does it
  its owner.
- A change made by a rule never starts another rule, so two rules cannot play ping-pong.
- The history of the task and the comment show "Rule <name>".
- Health lists, the basket and locked lists have no rules. Copying a list or making a template does not copy its rules.
- Agents read rules and can only propose one; the owner or an admin accepts it with 👍.

2.138.0 adds three triggers and three actions:

- *A task is created* (also by an agent, the API or an import step), *A task is assigned* (to a chosen person or to anyone;
  only when the person is new on the task) and *A custom field changes* (any change, or for selection and checkbox fields
  only a chosen value: an option, checked, unchecked). Formula fields are calculated and never start a rule.
- *Set the priority* (none, low, medium, high), *Add a list tag* (only tags of this list: the rule belongs to everyone in
  the list, personal tags stay personal) and *Set a custom field* (a fixed value, checked like a value you type; empty
  clears the field).
- A deleted custom field or list tag pauses the rules that use it. A value set by a rule never starts a "field changes"
  rule (the same loop protection as above).

## An own picture as the organisation's symbol (2.87.9)

An organisation's symbol was an emoji only. Its admins can now use an own picture instead, like a profile picture:
*Settings > Workspaces*, the organisation, *Symbol > Upload a picture…*; the picture is cropped square in the app and
stored re-encoded without metadata. It shows wherever the emoji showed (the workspace switch, *Settings > Workspaces*,
the server's organisation list for its members).

- Only admins of the organisation set or remove it (*Remove the picture*); setting an emoji later replaces the picture.
- Only members of the organisation get the picture; with organisation encryption it is stored sealed with the
  organisation's key, and it is part of backups like the list icons.
- People without an organisation have nothing to set here: their private space shows its own symbol.

## Managing many accounts (2.88.0)

*Settings > Administration > Users* is built for hundreds of accounts:

- **Search and filter:** the field above the list finds people by name, user name or e-mail address; the filter next to
  it shows *People*, *Active*, *Disabled*, *Admins*, *Invited*, *Waiting for approval* or *Agents*. The list shows 50
  accounts at a time with *Previous page* / *Next page*.
- **Several at once:** tick the boxes in front of the people and use the bar that appears: *Disable*, *Enable* (one undo
  step brings them back) or *Add to an organisation*. Every account is checked on its own; the ones that cannot be
  changed (your own account, a person of an organisation you do not belong to) are named.
- **Deleting someone who still owns lists:** the delete dialog lists them (the names of lists you may see, with whom
  they are shared, the lock) and asks what happens to them: **hand them over** to one person (the default; only people
  every one of the lists may go to are offered, an organisation's list stays in its organisation) or **delete them
  along** (type the user name to confirm; lists shared with others are pointed out). Either way it happens completely or
  not at all. Invoices and filed documents do not hang on lists and stay; a list with receipts in its budget can only be
  handed over, never deleted along (receipts are kept). A list with the lock whose key nobody else holds is pointed out:
  after a handover its content can no longer be read. Lists of an organisation you do not belong to show neither their
  name nor the organisation's and can only be handed over. The security log notes the deletion.
- **Organisation admins** (*Settings > Workspaces*) can delete the account of a member who belongs to their organisation
  alone, is no server admin and whose private space is empty (no private lists, nothing in the basket, no private
  calendars, address books, files, pages, mails, habits or time entries, and since 2.148.1 no personal office, private
  clients, bookmarks, news feeds, journal, booking page, polls, videos, agent chats or direct messages -- deleting the
  account would delete them too; the answer names these areas, never their content), handing the lists over the same
  way. For anyone else they remove the person from the organisation and choose which member gets the person's lists of
  the organisation.
- **Retention (2.148.1):** no account is deleted while its personal office holds finalised documents or cash book entries,
  also not by a server admin. Export the office first and disable the account instead.

API for scripts of the web app (session, not the REST API): `GET /api/users?all=1&limit=50&offset=0&q=&filter=people`
answers `{users, total, offset, limit, agents}` (without `limit` the whole list as before), `GET /api/users/{id}/delete-info`,
`DELETE /api/users/{id}?lists=transfer&to={id}` or `?lists=delete&confirm={user name}` (without `lists` an account that
owns lists still gets 409), `POST /api/users/bulk {ids, action: disable | enable | org_add, org_id}` and
`DELETE /api/orgs/{org}/members/{id}?to={id}`. Agents do not manage accounts: no REST API or MCP change.

## Members of an organisation as a list (2.138.3)

*Settings > Administration > Organisation*, the pencil of an organisation: its members are a list like *Settings > Administration > Users*, with a
search (name, user name, e-mail), the filter *Members* / *All* and a counter. Each person has a *Member* and an *Admin*
box; *Admin* only works for members, and taking someone out of the organisation also ends their admin role. The list
scrolls inside the dialog, *Save* stays in view. The symbol field shows the organisation's picture or an app icon.

## Roles in an organisation: guest, read-only, accounting (2.143)

Besides *Member* and *Admin* an organisation admin can give a person one of three limited roles (*Settings > Workspaces*,
the role next to each member, and in *Invite by e-mail*; *What the roles mean* explains them in the app):

- **Read-only**: sees everything a member sees and changes nothing in the organisation: lists and tasks (also lists shared
  with them as *Member*), the office, pages, tables, address books, calendars, files. The team chat stays open (reading and
  writing). The office shows its data without the buttons to add or delete.
- **Guest**: sees in the organisation only what is shared with them personally (a list, a calendar, an address book, a
  table, a file); there it works with the role of that share. No organisation-wide lists, no office, no pages, no open
  channels, no agents of the organisation, no invitations. In the member list a guest only sees the admins and the people
  they share something with.
- **Accounting**: like a guest, plus the office of the organisation to read and export (also the bookkeeping, the income
  statement and the DATEV export) and receipts to upload into the organisation's documents (a wrongly uploaded receipt
  of their own they can rename or remove again). Nothing else is sent, deleted or changed, no master data or settings.
  The typical case: the tax advisor.

The three limited roles add nothing at the top level of the organisation's files, own no list of the organisation (a list
handed over goes only to a member or admin), copy no list into the organisation, use no internal form of the organisation
and move nothing out of its office. Their closed months of working time stay their own (no approval by the organisation).

The person's private space stays as it is (there they are their own admin); a person without any organisation notices no
change. Every check sits on the server: the app, the REST API, MCP and CalDAV / CardDAV answer 403 (read-only) or 404 (guest,
accounting: as if the content did not exist). The last admin of an organisation cannot step down. The instance admin's
organisation dialog only switches *Admin* on and off; the limited roles stay as they are there.

API for scripts of the web app: `PUT /api/orgs/{org}/members {user_id | email, role}`, `POST /api/orgs/{org}/invites
{email, role}` and `POST /api/users {orgs: [{id, role}]}` take `member`, `admin`, `guest`, `readonly` or `accounting`;
`GET /api/orgs` carries each member's role, `roles` (the roles with their explanation) and `limited` (my own role is one of
the three). Before version 2.143 a server read an unknown role as *Member*: going back to an older version is only safe
while nobody holds one of the new roles. From 2.143 on a stored role the server does not know reads as *Guest* (and is
noted in the server log).

## The group "Conversations" in the sidebar (2.99.0)

The group no longer grows with every person you share a list with:

- **Messages** and at most five last conversations stay, unread ones first.
- People only show while you **pin** them (at most five): right-click a person or a direct conversation in the sidebar and
  choose "Pin to the sidebar" / "Unpin from the sidebar", or use the pin in **All people …**. A person who already stands
  there as a conversation is not shown a second time. Pin and unpin are one undo step each.
- **All people …** at the end of the group lists everyone you share a list with: a name opens their tasks, the bubble writes
  them a message, the pin puts them into the sidebar. Without an organisation it works the same way.
- Groups: only the ones you are a member of.
- Agents: only pinned ones and those with something unread, waiting or running; all others are under **Agents**.
- The pins are personal settings (`side_people`, `side_agents`) and hold on every device. A pinned person you no longer
  share a list with drops out quietly.

## Deleted lists in the trash (2.102.0)

Deleting an archived list no longer scatters it: the list goes into the trash with everything in it (tasks, custom fields
and their values, sections, tags, the list's chat) and nothing moves anywhere else.

- **Where it goes:** a private list into the trash of its owner, a list of an organisation into the organisation's trash.
  Its tasks never land in someone's private basket, and a single task comes back only together with its list.
- **Who sees it:** for a private list its owner and its list admins; for an organisation's list the organisation's admins,
  its owner and its list admins, as long as they belong to the organisation. Agents never.
- **Trash > Deleted lists:** name, who deleted it and when, the number of tasks; *Restore* brings the list back into its
  archive in the same place (the same organisation or the private space), *Delete permanently…* removes it for good.
  Right after deleting, *Undo* in the notice does the same as *Restore*.
- **After 30 days** the list is deleted for good with its tasks, comments, attachments (also the files on disk), fields and
  chat. Tracked time stays (without the list) for the bookkeeping.
- Lists with end-to-end encryption are still deleted for good at once (nobody could read them in the trash).


## Voice messages in the team chat (2.139.0)

When the text box of a team chat conversation is empty, a **microphone** sits next to the paper clip. Tap it and the
recording starts at once (the browser asks for the microphone the first time): a bar shows the running time, the
**bin** discards the recording, **Send** sends it, and the **stop** button ends the recording so you can listen first.
A recording stops by itself after 5 minutes and waits for Send or the bin; Escape discards it.

- Voice messages are files of the message: the same storage quota, virus check and encryption at rest as other files.
  They are not possible in end-to-end encrypted or archived conversations (no microphone there).
- The player in the message: play / pause, the bar to jump, the remaining time, the speed (1×, 1.5×, 2×) and a download
  button. Only one message plays at a time. Other audio files you attach stay a normal file (download).
- The recording format is the one the device records: phones and Safari record MP4 (AAC), which plays everywhere; some
  desktop browsers record WebM (Opus). A device that cannot play a recording shows a note and offers the download.
- The microphone blocked? Allow it in the browser's site settings (or in the phone's settings for the app) and try again.
- Kalmido never transcribes voice messages and sends them to no service. Agents in a channel see them as audio files
  (`voice: true`) and can download them like any other file.

## Notification channels: Slack, Matrix, Telegram, Signal (2.142.0)

Notifications can also go to a chat service, as a short text with the link to the task.

- **Your own channels:** *Settings > Notifications > Channels > Add channel*. Choose the service and paste what it needs:
  Slack an *Incoming Webhook* URL, Matrix the URL of a webhook bridge of your Matrix server (for example hookshot's generic
  webhooks, Kalmido posts `{"text": …}`), Telegram a bot token from @BotFather and the chat ID, Signal the address of your own
  signal-cli-rest-api server with the registered sender number and the recipient (a number or `group.…`). Then pick what goes
  there: reminders, assignments, mentions and comments, the daily digest and briefing, other notifications, and *changes in my
  own lists* (new, completed, assigned, commented in your private lists - the channel of your private area, also without an
  organisation). *Send test* posts a test message at once.
- **The organisation's channels:** *Settings > Workspaces > the organisation > Channels* (its admins). They get what happens in
  the organisation's lists that **every member sees** (*Everyone in the organisation*): new task, completed, assigned, comment.
  Never a list shared only with some people, never a private area, never another organisation; a list with end-to-end
  encryption shows only the neutral word. When the admin who set a channel up is no admin any more, it turns itself off; an
  admin who switches it on again owns it.
- **The address is a secret:** stored encrypted, never shown again (only the service, the name and the last characters).
  Editing leaves it unchanged unless you type a new one.
- **Delivery:** in the background, one try per message with a short time limit. After 5 failed sends in a row the channel
  turns itself off and the settings say why; switching it on again starts the count anew. Quiet hours hold back your own
  channel messages (urgent ones excepted).
- **Addresses:** `https://` only. Addresses in your own network and plain `http://` only for hosts an admin allowed
  (*Settings > Administration > Advanced* or `KALMIDO_WEBHOOK_ALLOW_HOSTS`), the same guard as for webhooks.
- Server settings: `KALMIDO_CHANNELS=0` turns channels off; `KALMIDO_CHANNEL_FAILS` (default 5) failures in a row before a
  channel turns off; `KALMIDO_TELEGRAM_API` another Telegram Bot API server (default `https://api.telegram.org`).

## E-mail for assignments and mentions (2.142.0)

Someone who gets no pushes still learns when a task is assigned to them or they are mentioned in a comment.

- *Settings > Notifications > E-mail for single events*, per kind (*Assigned to me*, *Mentioned*): **Only without a push
  device** (the default), **Always** or **Off**. "Push device" means a device with Web Push, or ntfy when it is your channel
  (*Delivery > Channel* ntfy or both); the chat channels above do not count.
- Needs e-mail sending on the server (`KALMIDO_SMTP_*`) and an e-mail address of the account.
- **Bundled:** the first event waits 10 minutes for more, then one e-mail lists them all with links; at most one e-mail every
  10 minutes and 20 a day per person. The text names who did what and the list - never the words of the comment; a task you
  no longer see by then is left out, a list with end-to-end encryption shows only the neutral word.
- Agents never get these e-mails (they have their events). Server settings: `KALMIDO_EVENT_MAIL_DELAY` and
  `KALMIDO_EVENT_MAIL_GAP` (seconds, default 600 each).
