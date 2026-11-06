# Privacy statement for a Kalmido server (template)

**Template – the operator fills it in.** Not legal advice. If you run Kalmido for other people (a team, a club, customers),
you are the controller of their data and need a privacy statement for the app (Art. 13 GDPR). This page lists what a
Kalmido server stores, how long, and which outside services it can talk to, so you can write that statement. Keep only
the parts that apply to your server, replace every `<…>`, and check it against your contracts.

Link the finished statement in the app: set `KALMIDO_PRIVACY_URL` / `KALMIDO_IMPRINT_URL` (see [ENV.md](ENV.md)) or the
two fields under Settings > Server > Server > Privacy and imprint. The links then show on the login page (also
before anyone signs in) and under Settings > Help. Empty = no link. For the optional built-in assistant there is a
separate block: [PRIVACY-ASSISTANT-TEMPLATE.md](PRIVACY-ASSISTANT-TEMPLATE.md).

## 1. Controller and hosting

> **Controller:** `<name of the person or organisation>`, `<address>`, `<e-mail>`.
> **Data protection officer** (if you have one): `<name, e-mail>`.
> **Hosting:** the server runs at `<hosting provider>` in `<country>` under a data processing agreement (Art. 28 GDPR).
> **E-mail delivery:** `<SMTP provider>` (only if you use one; see section 4).

## 2. What the app stores and why

| Data | Purpose | Legal basis (typical) |
|------|---------|-----------------------|
| Account: user name, display name, e-mail, password hash, picture, language, settings | sign-in and use of the app | Art. 6 (1) b GDPR |
| Content: tasks, projects, comments, chats, notes, files, calendars, contacts and whatever the modules switched on hold | the app's function | Art. 6 (1) b GDPR |
| Sign-in data: sessions (device, browser, time), passkeys / two-factor settings, the address of failed sign-ins | security of the accounts | Art. 6 (1) f GDPR |
| Activity history of projects, files and tables (who changed what) | traceability for the members of a project | Art. 6 (1) b / f GDPR |
| Office data (invoices, receipts, books, if the office module is used) | bookkeeping | Art. 6 (1) c GDPR (legal retention) |
| Customer reports and questionnaires through a form or the support portal: name, e-mail, the report or the answers, the reporter's comments, the status link | answering the report | Art. 6 (1) b / f GDPR |
| Approvals through a customer link (quotations, acceptances, video sign-offs): name, e-mail (optional), reason, time, address and browser of the signer, a fingerprint of what was shown | proof of the decision | Art. 6 (1) b / c GDPR |
| Bookings through a booking page: name, e-mail, phone and message as typed, the time; the address of the device only until the booking is confirmed. A confirmed booking also makes an event, with the module Contacts a contact, with an office area chosen a lead | arranging the appointment | Art. 6 (1) b GDPR |
| Scheduling polls through a link: name, e-mail (optional), the answers, a keyed hash of the address (it cannot be turned back into the address) | finding a date | Art. 6 (1) b / f GDPR |
| Online payment of invoices through a pay link: invoice, amount, currency, state and the provider's references. Card and account details go to the provider only | taking the payment | Art. 6 (1) b GDPR |

**Special categories.** The modules Health and Review & journal (journal, mood) can hold health data (Art. 9 GDPR). They
are off until a person switches them on, are shown only to that person (health lists only to the people they are shared
with) and are never given to agents. Name in your statement on which basis you process them (usually the explicit
consent of the person who switches the module on, Art. 9 (2) a GDPR).

**Children.** Child accounts are created by an admin or a parent. For a child under 16, the consent of a parent or
guardian is needed (Art. 8 GDPR); say in your statement who gives it and how.

## 3. How long data is kept

Kalmido's defaults (the operator can change them with the variables named; see [ENV.md](ENV.md)):

| What | Default | Variable / setting |
|------|---------|--------------------|
| Trash (tasks, projects, files, pages, mails, events, bookmarks, …) | 30 days, then deleted for good | `KALMIDO_TRASH_DAYS` |
| Activity / project / file / table change log | 400 days | `KALMIDO_LOG_DAYS` |
| Cell history of tables | the newest 200 entries of a table within 90 days | – |
| Office log | changes stay for good (bookkeeping); reads (open, preview, PDF, XML) 90 days | – |
| Bookings of a booking page | never confirmed: 7 days after they expired; cancelled and never confirmed: 30 days. Confirmed ones (also when cancelled later) have no period: the owner of the page deletes them in the app (search by name or e-mail over all bookings), otherwise they stay until the owner's account is deleted | – |
| E-mails deleted in a workspace mailbox | the mail leaves the list, but its `.eml` and attachments stay readable in the file store for those who could read it. Only the trash run, when switched on, removes the mail and moves its folder to the file store's trash; without that switch they stay. To remove the content at once, delete the folder *E-Mails / ...* too | `KALMIDO_TRASH_DAYS`, `KALMIDO_PURGE_TRASH` |
| Admin alerts, sign-in addresses seen by admins | 365 days | – |
| News feed entries | 90 days | `TASKS_NEWS_DAYS` |
| Finished agent jobs | 180 days | – |
| Agent usage records / agent audit log | 400 / 90 days | `KALMIDO_USAGE_DAYS` / `KALMIDO_AUDIT_DAYS` |
| Sessions | 1 day, or 30 days with "Stay logged in"; then a new sign-in | `AUTH_SESSION_DAYS` |
| Account export / import archives | 24 hours | – |
| Backups | every backup of the last 24 hours, one a day for 14 days, one a week for 8 weeks (at most 104 weeks, whatever is set; 52 with the retention switch) | Settings > Organisation > Data > Backups |
| Safety backups (made before updates and restores) | 30 days | `KALMIDO_SAFETY_BACKUP_DAYS` |
| Database copies made by `update.sh` / `update.ps1` (installer only; `data/backups/kalmido-*.dump`, **not encrypted**) | the last 10, however old they are | delete them by hand |
| Journal of deleted accounts (salted hashes of user name and e-mail, no plain text) | until no backup can hold the account any more: older than 104 weeks and older than every backup on the server | `KALMIDO_PURGE_LOGS` |
| Receipts, books, logbook, sent business letters (office) | kept 8 / 10 / 8 / 6 years by law, locked, not deleted | – |
| Server log (stdout of the container) | as long as your log rotation keeps it | your Docker / log setup |

**Important:** deleting for good after these periods runs only when `KALMIDO_RETENTION_PURGE=1` is set (or
`KALMIDO_PURGE_<KIND>=1` for one kind). Without it Kalmido only counts what it would delete (the admin reads the counts at
`GET /api/admin/retention`), so an update never deletes anything by surprise. Switch it on before you promise the periods above.

Deleted accounts: an admin deletes an account with its sessions, devices, tokens, keys, private content and files.
Comments and messages the person wrote in shared projects and chats stay with their text, without the name. Say this
in your statement.

A person can also delete their own account (Settings > Account > Delete account, GDPR Art. 17): confirmed with the
password (and the app code when one is set), the account is locked at once and deleted for good after 7 days. Meanwhile
projects they share stay usable for the others; for each own project they chose before whether it goes to a member or is
deleted along. A mail with a cancel link goes out at once and a reminder one day before; signing in with the password
also offers only "Cancel the deletion". The last admin of an organisation and the only server admin cannot delete
themselves until somebody else holds the role.

So that a restored backup does not bring a deleted account back, Kalmido notes each deleted account as salted hashes
(no readable name or address) and deletes it again after a restore. The note goes with the log clean-up once no backup
on the server can still hold the account. A copy kept outside the server (a downloaded backup, an off-site target that
keeps many backups) is not seen: if you restore such an older copy, check the accounts it brings back.

The server log shortens every address by default (IPv4 to /24, IPv6 to /48). `KALMIDO_LOG_FULL_IP=1` keeps them in full, for
example for fail2ban; if you set it, say so here.

## 4. Recipients and outside connections

The browser loads nothing from other servers: fonts, icons and the PDF viewer come from your server, there is no CDN,
no analytics and no telemetry. Exceptions in the browser: a video review that embeds a video from another site (e.g.
YouTube, Vimeo) loads it from there when opened; map and documentation links open only on a click; images in e-mails
load only on a click.

The **server** connects to other services only for what follows. Keep the rows you use.

| Service | When | What is sent | Default |
|---------|------|--------------|---------|
| Push services of the browsers (Google `fcm.googleapis.com`, Mozilla `push.services.mozilla.com`, Apple `push.apple.com`, Microsoft `notify.windows.com`) | a person allows notifications on a device | the notification, encrypted end to end (RFC 8291); the service sees only that a message goes to a device | on (`KALMIDO_WEBPUSH`) |
| ntfy (`NTFY_URL`, default `https://ntfy.sh`) | a person chooses ntfy for notifications (an own ntfy server also gets a message no device took on Web Push; the public ntfy.sh only with ntfy chosen) | title and text of the notification, **not encrypted** | off per person |
| E-mail (`KALMIDO_SMTP_*`) | invitations, password links, reminders and notifications by e-mail | address, name, task or project titles in the text | only when configured |
| GitHub (`api.github.com`) | update check for admins, a few times a day | the installed version and the server's address | on (`KALMIDO_UPDATE_CHECK`, switch in Settings > Server > Server) |
| Calendar subscriptions (ICS / CalDAV) and address books (CardDAV) | a person adds one | sign-in to that server, appointments / contacts to sync | per subscription |
| Contact import (Google contacts) | a person imports contacts with photos | the photo addresses are fetched from Google's image server | per import |
| Bookmarks, feeds, read later (Karakeep) | the module is on and a person saves a link / feed | the link is fetched for a preview / the articles | module off |
| Webhooks, chat channels (Slack, Matrix, Telegram, Signal) | a person or admin sets one up | task data, names, a short comment excerpt | per webhook / channel |
| Git hosting (GitHub, GitLab, Bitbucket, own) | a project is connected to a repository | repository requests with the token given | per connection |
| E-invoicing (Peppol access point) | an invoice is sent over Peppol | the invoice with the customer's data | office, per action |
| Online payment (Stripe) | an office connected its Stripe account and a customer presses *Pay* on a pay link | amount, currency, the invoice number as title and the return address. The customer then enters the payment details at Stripe, in the customer's browser. Stripe reports payment, refund and dispute to `/api/hooks/pay/...`; for a payout the server fetches its fees | off until an office sets it up |
| Invoice links in mails | a mail to a person's document address has no file, only a download link to an invoice | the server fetches that link once (https, public addresses only, no sign-in, no cookies); the other side sees the server's address and the link | only with a document address |
| Newsletter services (listmonk, Brevo, CleverReach) | a newsletter list is connected | e-mail and name of the subscribers | per connection |
| Mailbox of a workspace (IMAP / SMTP) | a workspace connects its mailbox | the mails of that mailbox | per mailbox |
| Sign-in provider (OIDC) | single sign-on is configured | the sign-in request | only when configured |
| Other Kalmido servers (server link) | an admin links two servers | what is shared over the link | off |
| Off-site backup (S3, WebDAV, SFTP) | configured by the admin | backups, always encrypted | off |
| Virus scanner (ClamAV) | configured by the admin | uploaded files (on your own network) | off |
| Assistant (`KALMIDO_AI_BASE_URL`) | configured by the admin, switched on by a person, on that person's request | see [PRIVACY-ASSISTANT-TEMPLATE.md](PRIVACY-ASSISTANT-TEMPLATE.md) | off |
| Similarity service (`KALMIDO_EMBED_URL`) | configured by the admin; in the background, no person starts it | titles and descriptions of tasks. If the service is not your own, name it and its contract here | off |

Every account gets a random ntfy topic when it is created; nothing goes to it until the person chooses ntfy. The full list of
what the server contacts, with the switch for each, is in [SELF-HOSTING.md](SELF-HOSTING.md#outgoing-connections).

Agents (AI agents people connect themselves) run on the computer and with the provider of the person who connects
them; they see only the projects shared with them. Say in your statement that the person who connects an agent is
responsible for what that provider receives.

### AI functions (EU AI Act)

Template paragraph, adapt it (EU AI Act Art. 50; the operator of the server is the *deployer*, not the provider of the AI
models):

> **AI functions.** `<name of the operator>` uses AI models of third parties as a deployer: agents that people connect to
> their projects, and the optional assistant if it is switched on. Kalmido itself does not run an AI model. Texts and
> answers written by an agent are marked "AI agent" in the app and in the customer portal (also in its e-mails). Before a
> text written by an agent goes out (a letter, a public link to a wiki page), the app offers to add the line "Created with
> AI support". Whoever publishes or sends such a text is responsible for its content and for labelling it, unless a person
> has checked it and takes editorial responsibility for it.

Use the same paragraph, as a section "AI functions", in your terms of use or service terms for the people and customers
of your server. An agent that is a bot without AI can be marked as such in its settings (it then shows as "Agent").

## 5. Cookies and storage in the browser

The app sets only cookies it needs to work (no consent banner needed for them, § 25 (2) TDDDG):

| Cookie | Purpose | Lifetime |
|--------|---------|----------|
| `kalmido_session` | keeps you signed in | 1 day, or 30 days with "Stay logged in" |
| `kalmido_2fa` | the step between password and second factor | 5 minutes |
| `kalmido_oidc` | the sign-in with single sign-on | for the sign-in |
| `kalmido_pub<number>`, `kalmido_fsxl<number>` | opens a password-protected public project / file link once the password was entered | 30 days |
| `kalmido_portal` | a customer signed in to the support portal by e-mail link | 7 days |
| `kv<number>` | lets a guest change their own vote in a scheduling poll | 180 days |

The app also keeps a copy of your data in the browser (local storage, IndexedDB, the service worker's cache), so it
starts fast and works offline. Logging out, or a session that ended, removes it; if changes are still waiting to be sent, the stored data stays
until they are sent after the next sign-in. Display preferences of the device (theme, text size) stay.

## 6. Your rights

> You have the right to access (Art. 15), rectification (Art. 16), erasure (Art. 17), restriction (Art. 18), data
> portability (Art. 20) and objection (Art. 21), and to lodge a complaint with a supervisory authority
> (`<authority>`). You can download your data yourself (Settings > Data, "Export everything"). To delete your account, write to
> `<e-mail>`.

### People without an account

Customers who send a report or answer a questionnaire, people who sign an approval link, book an appointment, answer a poll
or pay an invoice through a link have no account. The controller for their data is whoever the report, approval, booking,
poll or invoice belongs to: the organisation (or, for a project without organisation, the person who owns it). Requests
for access or erasure go to that controller:

- **Reports:** the reporter sees every own report of the same space by signing in to the portal with the e-mail link,
  and can turn the mails off on the status page. In the app, people who may change the task see the name, the e-mail and
  the status link in the task; the organisation's export (Settings > Organisation > Data > Export the organisation) holds all
  reports of the organisation. To erase a report, delete the task: the reporter's data goes with it when the trash is
  emptied (see section 3).
- **Approvals:** the admins of the office (for an acceptance: the owner of the project) see the full record in the
  quotation's approvals or under the project's public link; the export of the organisation or of the private office
  holds all of them. An open link can be revoked at once. A decided approval is kept as the proof of the decision (a
  signed quotation cannot be deleted); it goes with the project, or with the organisation after its legal retention
  period. **Video sign-offs are different:** when the video, its task or its project is deleted, the record stays with name,
  e-mail, reason, address, browser and decision. The admins of the organisation and the creator see and delete it, a decided
  record of an organisation or private office only after its legal period (6 years, to the end of the year). Say in your
  statement how long you keep it and on which basis.
- **Questionnaires:** the answers and the sender's address stand in the task the form makes, so everyone who sees that task
  reads them and the project's agents get it. They go with the task, or with the form.
- **Bookings:** the person gets a link to cancel by e-mail. The owner of the booking page sees the bookings, and they are in that
  person's export. To answer an erasure request, the owner finds the booking by name or e-mail and deletes a confirmed or
  cancelled booking in the app (no e-mail goes out, the cancel link stops working). Its event, contact and lead are separate
  entries and stay; they are deleted on their own where needed.
- **Polls:** a person changes their own vote in the same browser (cookie, see section 5). The poll's owner sees
  names, e-mails and answers; they go with the poll.
- **Online payment:** the payment stays with the invoice for the legal period (section 3). For what Stripe keeps, name Stripe
  as a separate recipient and link its privacy policy.

---

*Check this template again after updates that add integrations: the CHANGELOG and the
[list of outgoing connections](SELF-HOSTING.md#outgoing-connections) name them.*
