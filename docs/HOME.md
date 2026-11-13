# Home, family and reading

Family, home & life, and reading (read later, feeds, bookmarks).

## Family

*Settings > Modules > At home > Family* (or *What do you use Kalmido for? > Family* in the setup, the welcome tour or
*Settings > Modules*) switches on everything for a household; while it is off, none of it shows. The **Family** view
(sidebar, tab bar, command field) brings it together.

- **Birthdays and anniversaries**: *Birthday* in the Family view (or a *Birthdays* project): a yearly task with the age
  ("turns 80"), reminded 7 days before (or 1, 3, 14, 30, on the day only) and on the day; gift ideas are its checklist
  and what was given stays ticked when the year rolls on. *From contacts…* reads an **address book** (CardDAV:
  Nextcloud, iCloud, Radicale, mailbox.org …) once a day: `BDAY`, `ANNIVERSARY` and Apple's anniversary dates become
  yearly tasks and follow changes; nothing is written back, the address and the password are stored encrypted (like a
  calendar subscription's), each date keeps the contact's UID so a change updates it instead of adding a second one, and
  a birthday you deleted is not created again. Internal servers need the admin's allow-list (*Settings > Server > Server > Advanced*).
- **Household chores that take turns**: in a repeating task of a shared project, *Take turns* in the task panel: pick who
  (people of the project, children too) and whether the next person comes after each completion or every week. The next
  person gets a push; Undo puts the turn back; *Whose turn* in the Family view.
- **Children**: an admin makes an account a **child account** (*Settings > Organisation > People*) and picks its parents. A child
  sees a simple view with big buttons: its own tasks only (in shared projects a child always takes part as a participant:
  only what is assigned to it, or where it comes along), its stars and the rewards. Each task it completes gives 1 star
  (or what the task says under *Stars for a child*); parents give stars by hand, set rewards (once or again and again),
  get a push when the child asks for one and approve or decline it in the Family view. A child account can tick its
  tasks, ask for rewards and change its own account; everything else stays read-only for it.
- **Who comes along**: *Who comes along* in the task panel of a shared project's task: those people see the task (children
  too) and get its reminders.
- **Shopping lists**: *Used for: Shopping list* in the project dialog (or *Add shop areas* on a project): the sections become
  shop areas (fruit & vegetables, bakery, dairy …, rename or add your own); move an item to its area once and the next
  one goes there by itself ("2 l milk" and "milk" are the same item); common items (bananas, bread, milk …) find a
  likely area the first time. *Shopping mode*: the whole screen, big ticks,
  grouped by area, add items, live for everyone shopping at the same time; ticked items wait at the bottom for next time.
- **Meal plan**: the next seven days of meals in the Family view (*+* per day); write the ingredients as a list in a meal's notes and
  the cart button puts them on the shopping list, without doubling what is already on it.
- **Household deadlines**: *Household deadline* in the Family view: passport, ID card, car inspection (every two years), insurance
  and contracts (due on the last day to cancel, every year) or anything else, with a lead time that fits.
- **Packing lists** from templates: holiday, swimming pool, daycare, camping, business trip.
- API v1 and MCP: `/family`, `/family/occasions`, `/family/deadlines`, `/tasks/{id}/to-shopping`, `/lists/{id}/shop-areas`,
  `/family/packing`, `/family/kids`, rewards; tasks carry `family`, `rotation`, `people` and `stars` (docs/API.md).

## Home & life

Six modules under *Settings > Modules > At home*, each off until you switch it on; the view **Home & life** shows a
card per module (sidebar, command field). They are made of ordinary tasks, projects and contacts, so reminders, the
calendar, CalDAV, sharing and the API work as everywhere.

- **Contracts & subscriptions**: provider, cost (per month, quarter or year), the end of the current term, the notice
  period and the renewal. The task is due on the **last day to cancel** and reminds you before it; ticking it off means
  you keep it (it moves on to the next term), *Cancelled* in the task panel ends it. The card sums the cost per month and
  per year.
- **Home & devices**: devices with their warranty end (a reminder before it; attach the receipt) and **upkeep** that comes
  back every few months, with suggestions (heating, smoke detectors, tyres, descaling …).
- **Staying in touch** (needs Contacts): on a contact's card choose *every 2 weeks … every year*; *In touch today* notes
  it. The card lists who is due, a push once a day names them. Your choices are yours only.
- **Health**: appointments, check-ups and vaccinations (repeating) and medication (a daily reminder per time), in a
  **private** project: agents never see it, API tokens only with the permission *Health & journal*, no webhooks.
- **Review & journal**: your day or week (done, still open, moved, coming up) and a private journal with a mood.
- **Travel**: *Trip* creates a project with the dates, sections for bookings and things to do before you leave, a packing
  project from a template and, with Events on, an all-day event.
  Travel and staying in touch also exist per organisation (area *Travel & contacts*, only these two parts; contracts,
  devices, health, budget and family stay private); the button *Travel expenses* on a trip creates the prefilled travel
  expense trip in the office (office admins only).
- Read later, Feeds and Bookmarks moved into their own area *Reading* (see below).
- API v1 and MCP: `/life`, `/life/contracts`, `/life/devices`, `/life/upkeep`, `/life/health` (permission `private`),
  `/life/trips`, `/life/review`, `/life/journal/{day}` (`private`), `/contacts/{id}/care`, `/life/karakeep/sync`.
- **Budget** (2.72.0; its own part of *At home*): a budget is a list of its own that opens the budget view. Entries
  (income or expense, amount, day, title, category, counterpart, note, receipts), categories with a monthly limit, a
  month view with planned / spent / left and the last six months as bars. **Recurring entries** (monthly, quarterly,
  yearly) are templates: *Open this month* books them with one tap; *Add from contracts* turns your contracts into
  recurring entries. **CSV import**: the file you download from your bank (no bank access), columns mapped once and
  remembered, duplicates and errors left out, categories suggested from earlier entries. Share it with your family like
  any project (read-only or writing); agents never see it, there is no API v1 / MCP for it. Amounts, texts and receipts are
  encrypted at rest with the key of the project's space (needs `KALMIDO_SECRET_KEY`).

## Reading

*Reading* is an area of its own (sidebar, tab bar, *Settings > Modules*), in Private and in every organisation apart; each
view shows only the entries of the workspace you are in. Without an organisation everything works privately.

- **Read later**: own view with saved links (site, date, excerpt); tick them off when read, *Read* shows the ticked ones.
  Technically a project per workspace (an organisation's is made on first use and open to its members), so the share
  target, Karakeep and the API keep working.
- **Feeds** (2.85.0): follow RSS / Atom feeds (up to 100, fetched hourly by the server, articles kept 30 days), unread
  first, *Read later* turns an article into a reading-list entry; OPML import and export. An organisation's feeds are read
  by all its members with their own read marks, only its admins add or remove sources; existing feeds stay private. A site
  that refuses servers (403) is named so. Agents and API tokens do not see feeds or read later. "Read later" projects are never visible to agents, API tokens or webhooks (like health lists).
- **Bookmarks** (2.97.0): links with a preview, tags, a note and search, saved from the share target, by pasting or with a
  browser button ([docs/BOOKMARKS.md](BOOKMARKS.md)); *Connect Karakeep…* with your own address and API key (stored
  encrypted) brings Karakeep's links in as bookmarks (notes stay tasks) and archives the archived ones in Karakeep.

## How to: Make a shopping list
<!-- user-help: lists -->

1. Open **Home & life**; with no list yet it offers **Shopping list**. Select it.
2. Add items the way you type a task; "2 l milk" and "milk" count as the same item.

What happens then: the items are sorted into shop areas (move an item once and the next one goes there by itself), and
everyone you share the list with ticks things off live while shopping.

## How to: Sort projects into folders
<!-- user-help: lists -->

1. In the sidebar open the menu (⋯) of a project and select **Move to folder…**.
2. Pick a folder or select **New folder…** and give it a name.

What happens then: the project sits in that folder in the sidebar. You can drag projects between folders as well, and
you can share a whole folder at once (see "Share a folder with people").
