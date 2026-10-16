# Team: workload, absences, disposition

Kalmido's team views live in **Workload** (sidebar, module "Workload"). Since 2.50.0 the view has three tabs:
**Workload**, **Absences** and - with the module "Disposition" switched on - **Disposition**.

## Absences (2.50.0)

- Everybody enters their own absences: **Absences > Enter an absence** - vacation, sick leave, day off or other,
  one day or a period, optionally half a day (morning / afternoon) and a note. There is no approval: entering is enough.
- The admins of an organisation can also enter absences for its members.
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

- Comments by people are not affected; they follow the notification table as before.
- A list bell **All** and a task marked **Urgent** for you still bring every comment of that list / task.
- Pushes about other things agents do (new tasks, completions) keep their own switch.

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
- **Make personal again…** (an admin) turns it back into that admin's own address book; one undo step, like the hand-over.

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
