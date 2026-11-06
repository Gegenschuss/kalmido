# Moving in: import, e-mail and sharing

Moving from other apps, tasks by e-mail and sharing from your phone.

## Moving from other apps

*Settings > Data > Import*: pick the app, choose its export file, and Kalmido shows a **preview** first: how many
tasks go into which project, a few sample rows and everything that cannot be mapped exactly (a date text it did not
understand, a repetition Kalmido cannot do, a reminder without a date, ...). You choose where it goes: new projects (an
own project with the same name is reused) or one existing project you can edit. The import itself runs in one transaction.

- **Again is safe:** every imported task remembers its id in the other app (or, for formats without ids, a key made
  from project, section, parent and title), so importing the same file again only adds what is new.
- **Undo:** the report after an import, and *Recent imports* below it, offer *Undo* for 24 hours (taking over a whole Kalmido
  account: 30 days, see [SELF-HOSTING](SELF-HOSTING.md)): it removes the
  tasks, sections and (empty) projects that import created. Tasks someone added below an imported task stay.
- **Safe with strange files:** at most 20 MB and 20,000 tasks per import (`KALMIDO_IMPORT_MAX_MB`,
  `KALMIDO_IMPORT_MAX_TASKS`), ZIP and JSON bombs are refused, text encodings UTF-8 (with or without BOM), UTF-16 and
  Windows-1252 are recognized, formula cells stay plain text, nothing inside a file is ever fetched from the internet
  (attachments stay links in the notes), and every task is validated like one typed into the app. Each imported task
  gets a history line *imported from ...*; imports do not send one webhook per task.
- The same import is available to scripts: `POST /api/v1/import/{source}` ([docs/API.md](API.md#import)).
- People named in a file (assignees) are assigned only when the e-mail, user name or display name matches exactly one person who can see the target project (its owner or a member); otherwise the name goes into the notes as text.
- **Leaving again** (2.142.0): *Settings > Data* also exports your projects as **Todoist CSV** (a ZIP with one file per project in Todoist's import format) or as **Markdown** checklists (one `.md` per project); projects with a lock are left out (the server cannot read them).

| From | Export there | What comes along |
|---|---|---|
| **Todoist** | Project > … > *Export as a CSV file* (one file per project), or *Settings > Backups* (a ZIP with every project). A JSON from the Sync API works too. | Sections, subtasks (indent, at most 5 levels), `@labels` as tags, priorities (the CSV scale is detected, or choose it), dates including English and German date texts (*every monday at 9am*, *jeden Montag*, *15. Okt*, *morgen um 10 Uhr*) and recurring dates, durations, deadlines, comments and attachment links (into the notes). Texts it cannot read (other languages, *every 3rd friday*) stay in the notes. |
| **Trello** | Board > Menu > *Print, export and share* > *Export as JSON* | Lists as sections of one project, or one project each in a folder named after the board; cards with description, due date and time, start, reminder, *complete*; labels as tags; checklists as subtasks (several checklists: one subtask each); members assigned when they can see the project, otherwise named in the notes; comments and attachment links in the notes. Archived cards and lists are skipped, or imported as completed. Custom fields are not imported. |
| **Asana** | Project > arrow next to the name > *Export / Print* > *CSV* | Sections, subtasks (*Parent task*), tags, start and due dates, completion, priority; other columns (custom fields, dependencies) in the notes. An assignee is assigned when the e-mail or name matches someone who can see the target project, otherwise the name goes into the notes. |
| **Microsoft To Do** | No export of its own. Classic Outlook for Windows: *File > Open & Export > Import/Export > Export to a file > Comma Separated Values > Tasks* (Outlook for Mac: *File > Export > Tasks*). CSV files of export tools and ICS files work too. | Title, project, due and start date, status, importance / priority, categories as tags, notes, reminders, steps (when the export has them). English and German Outlook columns, also in Windows-1252. |
| **ICS / VTODO** | Nextcloud Tasks (calendar > … > *Export*), Thunderbird (right-click the calendar > *Export*), Apple Reminders via an export app or a CalDAV server, Tasks.org via its CalDAV account | One project per calendar; subtasks (`RELATED-TO`), due and start with time zones, repetitions (daily, weekly, monthly, yearly), reminders (`VALARM`), categories as tags, priorities, completed and cancelled tasks. Events are skipped. |
| **TickTick** | *Settings > Account > Generate backup* | Same way as the others (preview, undo, limits): folders, projects, sections, subtasks, dates, reminders, repetitions, tags. |
| **Notion** (2.142.0) | *Settings > Export > Markdown & CSV* (a ZIP, ZIPs inside it are read too) | Every database CSV becomes a project (name, status, date or date range, tags, priority; other columns in the notes, the text of a row's own page as well, its checkboxes as subtasks); other pages with `- [ ]` checkboxes become projects. The ID suffixes Notion adds to names are removed. |
| **Google Tasks** (2.142.0) | [Google Takeout](https://takeout.google.com) > *Tasks* (the ZIP or the `Tasks.json` in it) | Lists become projects; subtasks, due day, notes, completion; deleted tasks are left out. |
| **ClickUp** (2.142.0) | List or view > … > *Export* > *CSV* | Lists become projects in folders (the space when the folder is hidden), status, start and due dates, priority, tags, checklists as subtasks, estimate as duration; comments, attachments and other columns as text in the notes. |
| **Jira** (2.142.0) | Issue search > *Export* > *CSV (all fields)* | One project per Jira project, subtasks via *Parent*, status (*Won't Do* = cancelled), priority, due date, labels; issue key, type, sprint, reporter and components in the notes. |
| **Any CSV** (2.142.0) | Any spreadsheet saved as CSV | Columns are matched by their English or German header (title, due, notes, project (or list), priority, tags, done ...); the preview shows which column went where, unknown columns go into the notes. |
| **Markdown** (2.142.0) | A `.md` file (Obsidian, Logseq, a README) | Top headings become projects, deeper ones sections; `- [ ]` / `- [x]` tasks, indentation = subtask, text below a task = its note; unambiguous dates (`2025-01-15`, `15.01.2025`, `due:`), `#tags`. |

## Tasks by e-mail

With one mailbox set up (`KALMIDO_MAIL_ADDRESS` + `KALMIDO_IMAP_*`, see *Configuration*), everyone gets a **secret
address** for new tasks: Settings > Integrations > *Tasks by e-mail* (`tasks+<token>@example.com` lands in your basket,
an address per project lands in that project while you may change it). The subject becomes the title, the text the
description, attachments become files, "Fwd:" / "WG:" are dropped, the same message never twice. *New address* makes the
old one stop working. Optionally, mails from your own address (an admin stores it under Settings > Organisation > People) to the plain address go to your basket
too (off by default: sender addresses can be forged). The mailbox must deliver plus addresses (`+…`) to it, which most
providers do. With `KALMIDO_SMTP_*` the **daily summary** (Settings > Notifications, *Daily digest at*) also comes by
e-mail: overdue, today, tomorrow, what waits for you and what is unread; *Send now* tries it.

**A mailbox per workspace (2.141):** in the e-mail filing (*Office > Clients > E-mails*) the section *Mailbox* lets the
admins of an organisation - or a person for their private space - enter an own IMAP mailbox and SMTP access. Its mails
are fetched every `KALMIDO_IMAP_INTERVAL` seconds and filed in that workspace only (by sender, plus address or as a reply
to a filed mail; otherwise *Not assigned*). Passwords are stored encrypted and never shown again; the servers are reached
only with a valid certificate, and hosts in the local network only when listed under *allowed internal hosts*
(`KALMIDO_CALENDAR_ALLOW_HOSTS`). With SMTP set up, *Reply* and *New e-mail* send plain-text mails that are filed as
*Sent*. HTML mails are shown cleaned in a sandboxed frame; external images load only on request.

## Share from your phone

*Settings > Integrations > Share from your phone*. Every share becomes a task in *your* inbox, files attached; it goes
to `POST /drop` with your personal upload token (with a login proxy, let `/drop` pass, see above). Chrome passes no
files to installed web apps via the share sheet (links and text work with *Share > Kalmido*), hence these helpers:

**Android: HTTP Shortcuts** (several files per share)
1. *Download HTTP Shortcuts import*: a ZIP made for you (the server address + `/drop`, your token, the Kalmido icon).
2. Install [HTTP Shortcuts](https://http-shortcuts.rmy.ch), then *menu > Import / Export > Import from file* and pick the ZIP.
3. Share from any app to HTTP Shortcuts > *Kalmido* (photos and files, also several) or *Kalmido text* (links and text;
   the first line becomes the title, a link the task's link).

The ZIP contains your token: keep it like a password (*New token* next to the token, or *Settings > Account > Advanced >
Upload token > New token*, invalidates it; then download the ZIP again and update the iPhone shortcut).

**iPhone / iPad: Shortcuts app.** Copy the server address (without `/drop`) and the token with the buttons in the
same place and follow the guide there (*Get Contents of URL* to the address + `/drop`, method `POST`, header
`Authorization: Bearer <token>`, form field `file` or `text`, *Show in Share Sheet*). If your server has a signed
generic shortcut (`KALMIDO_IOS_SHORTCUT_URL`), an *Add the Kalmido shortcut* button appears; it asks for the server
address (without `/drop`, it adds that itself) and the token on import.

(2.574.0: the share inbox through the ntfy app is gone; use HTTP Shortcuts / the Shortcuts app above, the share menu or
the mail inbox. `NTFY_INBOX_*` variables are ignored.)
