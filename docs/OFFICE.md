# Office & finance

The module **Office & finance** (`office`) turns an organisation's Kalmido into a small back office: master data
(services, equipment, text blocks, framework contracts), quotations with a calculator that follows the usual rules of a
media production (producing days, raw data, discount, transfer of rights) and a PDF of every document. Invoices,
e-invoices and bookkeeping exports are planned for later stages.

A person needs the module switched on (Settings > Modules > Office & finance, or the setup purpose "Office & finance").
Since 2.47.3 no organisation is needed: everybody also has a **personal office** of their own (see below). Everything the
module stores belongs to one office area - an organisation's office or one person's personal office; people of another
organisation, and everybody else in the case of a personal office, never see it. Child accounts have no access. Agents (AI
assistants with a token) reach the module only through `/api/v1/office` and only for drafts (2.51.0, see "Agents" below).

## Roles

| Who | May |
|---|---|
| Organisation admin | module settings, master data, framework contracts, logo, import, delete documents |
| Organisation member | read master data and settings, export the master data file, create / edit quotations, PDF |
| Owner of a personal office | everything an organisation admin may, in the own personal office |
| Agents | with three switches on: read master data and documents, drafts of quotations / invoices / reminders, payment suggestions (2.51.0) |
| Children | nothing (403) |

Which office you work in follows the workspace switch at the top of the sidebar: an organisation's workspace (`org:<id>`)
shows its office, **Private** shows your personal office. Without any organisation (a freelancer, or a server in the
mode `shared`) there is no switch: the office is simply your personal one. With the switch on "All workspaces", a person
in exactly one organisation works in that organisation's office (as before 2.47.3); with several organisations the
office asks to choose one.

## Personal office (2.47.3)

Every person has a personal office: own master data (services, equipment, text blocks, framework contracts, freelancer
roles, crew), own number series, settings, company fields, logo, quotations, invoices, payments and archive. The person
is its admin (module settings, logo, import, delete, purchase prices and surplus). Its clients are the person's private
clients (the clients without an organisation, which the workspace "Private" shows). The access log, e-invoices, the
DATEV document inbox and sending by mail work as in an organisation's office.

It is created on the first visit, invisible to everybody else - also to the server's admins: it never appears as an
organisation (lists of organisations, workspaces, sharing, agents, organisation export). Technically it is a hidden row
of the organisation table (`orgs.personal_of` = its owner) without members; row-level security lets only its owner reach
its rows, and it has its own encryption key like an organisation.
Going back to a version before 2.47.3 keeps working, but such a version does not know these rows and lists them as
organisations named `private-<id>` without members (admin dialog). Leave them alone there: do not add members, rename or
delete them - members added there would reach the personal office.

A person in an organisation who opens "Private" for the first time finds an empty personal office with a hint and a
button to the organisation's office.

**Moving into an organisation** (Settings tab, "Move into an organisation"; one way, after a confirmation): the personal
office becomes a new organisation with its owner as admin - documents, numbers (no duplicates: it is the same area),
settings, master data, files and the private clients go with it; "Private" is a new, empty personal office afterwards.
Only where organisations can be created (an instance admin, not in the mode `shared`). Moving into an existing
organisation is not offered yet. `POST /api/office/move` `{name, confirm: true}` -> `{org_id, name, clients}`.

**Moving office data into another workspace** (2.97.0, both ways between the personal office and an organisation's office,
or between two organisations): **Move to another workspace…** in a client's menu (Office > Clients, also for several
selected clients), in the menu of a draft quotation / invoice, in the dialog of a trip and of a document template. The
dialog names what moves and what stays before anything changes:
- a client takes its contact persons and its drafts along (their links to the address book end; the address books stay);
- drafts lose their number - the target numbers them in its own range when they are issued; links into the old office end
  (framework contract, project, catalogue service of a position); a draft moved alone keeps the address but not the client;
- trips move with their receipts as long as none is ticked "in DATEV" or billed; templates move, documents made from them
  stay with their text;
- **issued documents never move** (retention): invoices, credit notes, reminders, sent quotations, number ranges and the
  archive stay where they were issued. A client that issued documents (or projects, trips, deals) still point to stays
  archived in the old office and is created anew in the target. The tick box *Take issued documents along as a read-only
  copy* files a copy of each of them into the target's archive: view and PDF only, no number of its own, never edited,
  and not part of the target's bookkeeping, EÜR, VAT, DATEV export or archive sums (marked "Read-only copy from …").
Rights: the right to work in both offices (travel expenses and templates: the admin of both); out of an organisation only
its office admin or who created the client / draft - a plain member takes only own drafts along and no copies. Agents
never move office data. Undo takes the whole move back in one step (copies and a newly created client go again, unless the
target has used that client since). `POST /api/office/move-space` `{what: clients|drafts|travel|templates, ids, to:
"private"|"org:<id>", dry, copy_issued}` -> `{notes, block, count, move_id}`; `{undo: move_id}` takes it back.

**Small business (section 19 UStG)**: the setting `small_business` (Settings tab, "Invoices"; a setting of every office
area, also of an organisation): new quotations and invoices are made without VAT and with the note "Gemäß § 19 UStG
wird keine Umsatzsteuer berechnet." (`vat_mode` `novat`, `vat_note` `small`); the e-invoice gets the tax category `E`
with this exemption reason.

## The office menu (2.87.9, a rail on the left since 2.98.0)

The area Office (office, clients, contacts) has one menu with three groups instead of tab rows:

- **Sell** - Pipeline, Quotes & invoices, Clients, Contacts, Documents, Framework contracts
- **Money** - Cash flow, Figures, Bank, Bookkeeping, Subscriptions & tools, Travel expenses
- **Administration** - Equipment, Contracts & insurance, Settings

Services and text blocks are no menu points any more: they are the tab **Templates** under **Settings** (Settings has the
tabs *General* and *Templates*; Templates switches between *Services* and *Text blocks*, the one used last opens).

On a computer the menu is a narrow column left of the page (15 rem, 12 rem below 1100 px): the groups as small capitals,
their points below each other, the point shown in the accent colour (`aria-current="page"`); it stays while scrolling.
The page starts with its own heading (the name of the point), a detail page with its grey path ("Clients › Example Ltd",
text only) instead. Arrow up / down, Home and End move inside the column. On a phone `#office` (or `#office/start`) opens
a start page with, for admins of the office, the key figures and then one list per group in a single column; every other
page shows "‹ Office · group" (back to the start page) and the points of its group as one row of tabs that scrolls
sideways and never wraps (arrow left / right inside it). Points for admins only (pipeline, cash flow, figures, travel
expenses, ...) and groups without a point are hidden; a person without an organisation is the admin of the personal
office and sees all of them. Every old address keeps working (`#office/offers`, `#office/services` and `#office/texts`
open the tab Templates, `#office/import` sits under Settings, `#clients`, `#client/<id>`, `#contacts` ...). A new part of
the office joins a group with an entry in `OFM_ITEMS` (`static/js/areas.js`, field `group`, its place in `OFR_ORDER`); an
office tab without one appears at the end of its group (`OFC_TABS` field 5, else Administration).

## Tabs

- **Quotations** - the documents (number, recipient, project, date, net total, status) and the editor.
- **Services** - what you sell: name in German and English, category (free text such as Video, Audio, Office), unit
  (day, hour, piece, minute, flat), daily and hourly rate, tax class (standard, reduced, exempt), the flags "raw data fee"
  (the position counts towards the raw data amount) and "producing" (the position's quantity counts towards the
  producing days), internal / external, role. Search box, archive. 2.47.0: the unit "percent" (a rate on the external
  fees, e.g. the Künstlersozialkasse), the kind "shoot" (only in the shoot calculation, never in the position picker)
  and the freelancer role the service points to (`role_id`). Below the services two masters: **Freelancer roles**
  (name DE / EN, purchase price per day and per hour; the role's price is the default purchase price of a new position)
  and **Crew** (Drehpersonal of the shoot calculation: name DE / EN, daily rate = the client's price, internal /
  external, an optional markup in percent). Purchase prices and markups reach only the organisation's admins: members
  get the rows without them (also in the export), never in a PDF.
- **Equipment** - devices with a daily rate, and **sets** (a bundle of devices with a discount in percent). 2.92.0: admins also
  record purchase, depreciation and insurance values (see [Equipment value](#equipment-value-depreciation-and-insurance-list-2920)).
- **Contracts & insurance** (2.92.0, admins) - business contracts and insurances with notice deadlines, see
  [Contracts and insurance](#contracts-and-insurance-2920).
- **Text blocks** - reusable texts in German and English, grouped by kind: the rights catalogue (`rights_time`,
  `rights_territory`, `rights_media`), introduction, closing, note, free block between positions, raw data note.
  The first call of the module copies the country pack's catalogue into the organisation's text blocks.
- **Framework contracts** - one per agency or client: date, raw data included, default rights (three catalogue entries),
  rights note, closing text, special rates per service. A document can pick a contract and deviate from it.
  The signed contract and its addenda can be attached as PDF files in the contract's dialog ("Contract (PDF)": upload,
  open, replace, remove, a date per file; the list shows a paper clip). Only PDFs, the usual upload size limit; stored
  encrypted with the office area's key like the stored quotation PDFs. Members of the office open them, admins change
  them. Deleting the contract moves its files into the trash; after 30 days they are deleted for good, file included.
  API: `GET|POST /api/office/contracts/<id>/files` (multipart `file`, `date?`, `replace?`),
  `GET|PATCH|DELETE /api/office/contracts/<id>/files/<file id>`, `POST .../<file id>/restore`.
- **Bookkeeping** (admins, 2.90) - income/expense statement, VAT return figures, tax reserve, receipt photo and tax
  dates, see below.
- **Bank** (admins, 2.90) - bank reconciliation, see below.
- **Settings** - company name and address lines, contact / register / bank lines (printed in the footer), logo, own letterhead PDF (2.120, see "Own letterhead"),
  brand colour (accent in the print only), document language (de / en), currency (EUR / USD + rate), number scheme with
  a live preview, producing quotient and rate, raw data factor, days a quotation stays valid, default text blocks,
  default rights, country pack with its tax rates, and the import / export of the master data.
  Since 2.40 producing (a markup by production days) and the raw data surcharge are switches per organisation
  (`producing_on`, `raw_on`): new organisations start without them; at the first start of 2.40 an organisation that uses
  them (services, positions, contracts with raw data included) keeps both on, once, so switching off later stays off.
  Off means: no automatic producing / raw data line in new quotations (raw data "none"), the flags of the catalogue are
  not taken over. Since 2.47 both are only the default of a new quotation: every quotation has its own switches
  (`producing_on` 0/1, raw data via `raw_mode`, "none" = off), always shown; the flags of services and positions are
  always kept, the spreadsheet import always reads those columns, a framework contract always presets raw data;
  existing and finalised documents keep what they hold, documents of 2.46 and older get `producing_on` once at start-up
  (1 when a position counts towards producing, else the default), so their sums stay. The company data choose the word before the
  management's names in the footer (`md_label`: Geschäftsführung, Gesellschafter, Inhaber, Inhaberin, Vorstand, Partner;
  German or English by the document's language). Unsaved input of these pages survives a change of the view and live
  updates until it is saved or discarded.

## Number scheme

Placeholders: `{yyyy}` `{yy}` year, `{seq}` or `{seq:03}` the counter (zero-padded to the given width), `{project}`,
`{client}`, `{date}` (`yyyymmdd`), `{initials}`. Default `KVA-{yyyy}-{seq:03}` -> `KVA-2026-001`. The counter runs per
organisation, document kind and period: with `{yyyy}` / `{yy}` in the scheme it starts again every year, without it
never. A number is reserved once and never reused.

When the number is assigned depends on the document kind: quotations get it when they are created (as before); the
organisation can switch this to "when it is finalised" (settings key `offer_number_at`: `create` | `finalize`). Then a
draft carries no number ("Draft") and the number is assigned in the moment the document is finalised, so deleted
drafts leave no gaps. Later document kinds (invoices) are always numbered when they are finalised. Numbers are unique per
organisation.

## Country packs

Tax rates, number and date formats, the labels of the documents and the default texts are not in the code but in a
**country pack**: one JSON file per country under `kalmido/office/packs/<code>.json` (shipped: `DE`). A pack holds data
only - no code - and is checked by a validator before it is used (`POST /api/office/packs/validate` runs the same check
on a pack you paste, a dry run for community packs; packs from a catalogue: see *Packs* below).

Shape (see `de.json`):

```
{"code": "DE", "name": "Deutschland", "version": 1, "community": false, "currency": "EUR",
 "tax": {"standard": 19, "reduced": 7, "exempt": 0, "labels": {"de": {...}, "en": {...}}, "exempt_note": {"de": "...", "en": "..."}},
 "formats": {"date": "dd.mm.yyyy", "decimal": ",", "thousands": ".", "currency_pos": "after"},
 "required_fields": ["company_name", ...],
 "labels": {"de": {"offer": "Kostenvoranschlag", ..., "units": {"day": "Tage", ...}}, "en": {...}},
 "texts": {"intro": {"de","en"}, "closing": {...}, "vat_note": {...}, "rights_time": [{"key","de","en"}, ...], ...},
 "numbering": {"offer": "KVA-{yyyy}-{seq:03}"},
 "einvoice": {"formats": ["zugferd", "xrechnung"], "status": "planned"},
 "bookkeeping": {"export": "datev", "status": "planned"}}
```

Labels and default texts come from the pack and the **document's** language, not from the app language of the person
who writes the document.

## Shoot calculation and industry packs (2.47)

A quotation part of kind `shoot` is a **shoot calculation sheet** (Drehkalkulation), printed for the client on its own
page. Three layers, no code plugin:

- **Core** (`kalmido/office/sheet.py`): head values and rows with fixed rules. Head: shooting days, travel days (share of
  the day rate), preparation days (share of the day rate), nights x price per night, meal rates (full day / part day),
  Saturdays and Sundays / holidays with a surcharge in percent.
  - crew row: day rate x (shooting days + travel days x share + [with preparation] preparation days x share + Saturdays x
    surcharge + Sundays x surcharge), times the number of people; an optional markup raises the price, not the purchase
  - producing: a share (for example 0.2) of the crew sum, internal
  - car: km x rate x trips; meals: people x (travel days x part-day rate + shooting days x full-day rate, the full-day
    rate only with more than one night); hotel: people x nights x price per night (only with nights); all external
  - equipment set: days (default = the shooting days; another value shows "differs from n shooting days") x the price
    per day (the sum of its devices) x (1 - discount). Picking a set copies its devices and discount into the sheet;
    devices can be added or removed there, the master set stays as it is
  - additional costs: free rows (text, quantity, price, external by default) or a service of the kind `shooting`
    (such services appear only here, never among the positions of a quotation)
  - sum, discount in percent rounded to whole units, net total (the part's net on the title page); third-party costs =
    the purchase of the external rows (internal rows are no cost)
- **Crew master data** (`office_roles` kind `crew`): function DE / EN, day rate (the client's price), internal / external,
  optional markup in percent. A row copies name, rate, internal / external and markup when it is added; changing the
  role later affects new rows only.
- **Industry pack** (`kalmido/office/packs/industry/<code>.json`, `film` = Film & Video): data only, checked like the
  country packs (`dk_pack_validate`) - labels DE / EN, print order of the blocks, defaults (meal rates 28 / 14,
  surcharges 25 / 75 %, producing share 0.2, km rate 0.35), suggested crew functions. Switched on per organisation in
  the office settings (`industry_packs: ["film"]`); without a pack there is no shoot calculation.

Purchase, surplus, markup and internal / external are for the organisation's admins only: members edit the sheet but
get none of these values (the price of a row with a markup is shown including it) and cannot set them; the server keeps
the stored values. The printed page has no internal / external, purchase or markup column.

## Packs (2.76)

Office & finance > Settings > **Packs** lists the country and industry packs this office can use: the ones shipped with
the app (*Built in*), the ones installed here, and the packs of a **catalogue**. The catalogue is an index file the
operator of the server names in `KALMIDO_PACKS_CATALOG`; without it the list shows only the built-in packs and the note
"No catalogue set up". Kalmido fetches nothing from the network unless a catalogue is set up.

- **Search and filter**: the search field filters by code, name, description and author while you type; the buttons
  *All / Countries / Industries* narrow the kind. Admins can fetch the catalogue again with *Refresh* (it is kept for an
  hour otherwise).
- **Badges**: *Verified* = checked by the Kalmido team (built-in packs always are); *Community* = made by someone else
  and not checked. Installing a community pack asks first: check its tax rates and texts before you send documents
  with it.
- **Install, update, uninstall** (office admins; members see the list only): *Install* downloads the pack, checks its
  checksum, size and shape (the same check as the built-in packs, no markup, data only, never program code) and makes
  it available in this office only - a private office or one organisation, never others. An installed country pack
  appears in the *Country pack* choice, an installed industry pack gets its box in the *Calculation rules*. *Update to
  vN available* shows when the catalogue has a newer version, with its notes. A pack with the code of a built-in one
  (for example a newer `DE`) replaces it in this office only; uninstalling it brings the built-in one back.
- **Uninstalling** asks first. It is refused, with the reason, while the pack is still in use: the country pack chosen
  in the settings, an industry pack switched on in the calculation rules, or used by open quotations. Change those
  first.
  Exception: a pack that replaces a built-in one (a newer `DE`) can be uninstalled while chosen - the office goes back
  to the built-in version.
- **Open documents follow the pack in effect**: quotations and invoices that are not finalised yet are calculated with
  the pack the office uses now. Updating or uninstalling that pack therefore changes their rates and texts; the
  confirmation says how many open documents are affected.
- **Undo**: every install, update and uninstall is one step of the undo history (the arrow or Ctrl/Cmd+Z). Undoing an
  update installs the version before again, as long as the catalogue still has it.
- **Finalised documents keep their pack**: a finalised quotation or invoice stores the pack version, its checksum and
  its source, and is always shown with that data - updating or uninstalling a pack never changes it.

## Import and export of master data

Settings > Office & finance > "Export" downloads one JSON file with the settings and all master data (no documents, no
logo file, no client ids). "Import" (organisation admin) reads the same shape back - also a hand-written file, for
example a service catalogue converted from a spreadsheet. The import is additive: rows are matched by name (services:
`name_de`; equipment, sets, contracts: `name`; text blocks: `kind` + `key`) and existing ones are left alone unless
"overwrite existing" is on. Ids inside the file (set items, contract rates, default text ids) are mapped to the new ids.
An id that matches no row of the file is left empty (a set item or contract rate is dropped) and listed in the answer
under `counts.unmapped` (`[{in, name, field, id}]`); it is never taken over as it is.

Minimal file:

```
{"kalmido_office": 1,
 "services": [{"name_de": "Kamera", "name_en": "Camera", "category": "Video", "unit": "day", "daily_rate": 980, "tax": "standard",
               "raw_fee": 1, "producing": 1}],
 "equipment": [{"name": "Kamera-Set A", "name_en": "Camera kit A", "category": "Kamera", "daily_rate": 250}],
 "texts": [{"kind": "rights_time", "key": "unlimited", "text_de": "unbegrenzt", "text_en": "in perpetuity"}]}
```

Tables and keys: `services` (name_de, name_en, category, sort, unit, daily_rate, hourly_rate, raw_fee, producing, intext,
role, role_id, tax, archived), `roles` (2.47.0: name_de, name_en, cost_day, cost_hour, sort, archived), `crew` (2.47.0:
name_de, name_en, rate_day, intext, markup_pct, sort, archived), `equipment` (name, name_en, category, daily_rate, archived), `sets` (name, discount_pct, items
[{equipment_id, qty}], archived), `texts` (kind, key, text_de, text_en, sort, archived), `contracts` (name, date,
raw_included, rights_time_id, rights_territory_id, rights_media_id, rights_note_de, rights_note_en, closing_de,
closing_en, rates {service_id: rate}, note, archived), `settings` (the keys of the settings tab).

## Importing legacy data (2.39.1)

Settings > "Import legacy data" (organisation admins only) takes over what an office kept in a spreadsheet and old PDF
documents. It is a function of the app: the person uploads the files, sees a preview, corrects it and confirms. Nothing
is guessed in the background and no language model is involved.

- **Spreadsheet (.xlsx)**: read with the Python standard library only (no macros, no formulas evaluated, files with XML
  entities refused, at most 10 MB). Sheets or tables (Excel "Format as table") are found by name: `Contacts` (column
  `addresses`, one address text per cell), `Services` (`serviceDE`, `serviceEN`, `dailyrate`, `hourlyrate`, `rawfee`,
  `producingfee`, `order`, `category`, `freelancer`, `intext`), `Equipment` (`device`, `category`, `dailyrate`; since 2.45.1
  also `Device DE` / `Device EN`, `Gerät DE` / `Gerät EN`, `Name EN` - spaces, underscores and case do not matter). A device
  whose German or English name exists already is a duplicate. DE and EN in separate rows become one device only when the
  sheet has an id column (`id`, `nr`, `article no`, `sku`, ...) and a language column (`language` / `sprache`, value `en`);
  otherwise every row stays a device of its own. Separator
  rows like `---- VIDEO ----` are the category of the rows below, not services. 2.47.0: `Freelancer` (`jobtitle`,
  `dailyrate`, `hourlyrate`) becomes the master "Freelancer roles" (purchase price per day / hour) and `Staff` / `Crew`
  (`jobtitleDE`, `jobtitleEN`, `dailyrate`, `intext`) the master "Crew" of the shoot calculation, both through the same
  way; they are imported before the services, so the column `freelancer` of a service points to its role (`role_id`).
  The column `order` is the order of the category (a table `category` / `order` wins); inside a category the rows keep
  the file's order. Excel error values like `#NV` count as empty; `intext` may be `intern`, `extern` or `shooting`; a
  service named "Künstlersozialkasse" becomes a rate in percent (`0.05` -> 5 %). `rawfee` / `producingfee` are always
  read. A table renamed by Excel (`Services_2`) is found too.
- **Fill instead of skip (2.47.0)**: a service, device, role or crew row whose name exists already is proposed as "fill":
  only the EMPTY fields of the existing entry take the file's value (empty = no text / no number; for the flags and the
  order also 0), set values are never overwritten. The preview lists the fields per row (`fill`); with nothing to fill
  the row is skipped. The undo empties the filled fields again while they still hold the imported value.
- **Addresses** are split by rules into company, contact person, street, postcode, city and country: German postcodes
  have 5 digits, Austrian and Swiss 4 (without a country line the split is marked unsure), `D-` / `A-` / `CH-` prefixes and
  a country line set the country, "z. Hd." / "Attn." / "Herr" / "Frau" and `c/o` lines go to the contact, a P.O. box is
  taken as the street (marked). Every unsure split shows its reason; the fields can be edited in the preview, rows can be
  deselected, and the original text is kept in the client's free address field.
- **Duplicates**: the normalised company name (without legal form, accents and punctuation) plus the postcode is compared
  with the organisation's clients and within the file. A duplicate is skipped by default; an existing client can instead
  be merged (only its empty fields are filled) or the row added as a new client. 2.40.0: a duplicate that names another
  contact person is proposed as "Add as contact person to the client" (to the existing client, or to the client of the
  earlier row of the file); the undo removes the added contact persons again.
- **Old invoices and quotations** are uploaded as PDF files (several at once, at most 20 MB each, checked by their first
  bytes). The file name proposes the key data: `<project no>_<client>_<project>__<date>_R.pdf` is an invoice,
  `<project>_<client>_KV<n>_<date>_<initials>.pdf` a quotation; dates as `dd.mm.yy`, `dd.mm.yyyy`, `yyyy-mm-dd` or
  `yyyymmdd`. The client is proposed by name and can be changed; amount and "paid" are entered by hand. The number is the
  file name without `.pdf`. An archived document is read-only: the original PDF is stored unchanged (folder 0700, file
  0600, part of every backup) and is never re-rendered, renumbered, sent or turned into an e-invoice. The Quotes & invoices tab
  lists it under "Archive" with the sum of the archived invoices and of the paid ones; the other lists and the reminders
  do not count it. 2.40.0: Kalmido also reads the recipient's address from the text layer of page 1 (not the own sender
  line; split like a spreadsheet address, unsure splits marked) and proposes, each only with a tick: a new client (no
  client matches), a contact person for a client that has another one, a note when the address differs from the client
  card. A scan without text gets a hint - there is no text recognition. The archive file is written only after the
  database commit.
- **Correcting an archived document (2.81.0)**: the pencil next to an entry of the archive list opens a dialog for
  everybody who reads the organisation's archive (members too, no lock after the first entry): client, amount as net
  plus tax lines (19 %, 7 %, 0 %, reverse charge; "Add tax rate" for mixed invoices; Kalmido adds up tax and gross)
  and "Paid" (invoices only). Number and PDF never change. An entry with only one amount counts as gross with unknown
  tax until it is corrected. Every change is kept in the entry's history (time, person, old and new value), folded in
  the dialog; saving is one undo step. A select above the list filters by client. Amounts are not read from the PDF.
- **Numbers**: an archived number is never given to a new document (the automatic number skips it, a manual one is
  refused). The import page proposes to continue the invoice / quotation counter after the highest archived number (a
  number that follows today's scheme, else the project number of the file name); the person confirms, the counter is
  never lowered.
- **Undo**: every confirmed import is a run (list with date, person, count). Undoing removes what the run added unless
  something builds on it by now - a client with a list, document, framework contract or archived document of another run
  stays, as does a service used in a document or as the producing rate, and equipment in a set; the answer says what
  stayed. Fields a merge filled are emptied again while they still hold the imported value.

Routes (organisation admin; members read the archive and, 2.81.0, correct it): `POST /api/office/legacy/preview` (multipart `file`, stores
nothing), `POST /api/office/legacy/split` `{address}`, `POST /api/office/legacy/import` `{clients, roles, crew, services, equipment}`
(the preview's rows with `action` new / merge / fill / skip and `merge_id`; 2.46.1: `areas` = only these of clients / roles /
crew / services / equipment, the others are neither written nor checked), `GET /api/office/legacy/runs` (2.46.1: a data run lists its
`areas` with `count` and `undone_at`), `POST /api/office/legacy/runs/<id>/undo` (2.46.1: `{kinds: [...]}` undoes only these
areas of a data run, `409` for an area undone already; the whole undo afterwards takes the areas left), `POST /api/office/legacy/archive/parse` `{names}`,
`POST /api/office/legacy/archive/run`, `POST /api/office/legacy/archive` (multipart `file` + `run_id`, `kind`, `number`,
`project_no`, `project`, `client_id`, `client_name`, `date`, `amount`, `paid`; 409 for a used number or the same PDF
twice), `GET /api/office/legacy/archive?kind=&client_id=`, `PATCH /api/office/legacy/archive/<id>` (only `amount`, `paid`,
`client_id`; 2.81.0: members too, `tax_lines` `[{net, tax: 19 | 7 | 0 | rc}]` (1-10 lines) instead of `amount` -> the
gross, `amount` alone = gross with unknown tax (`tax_lines` null), `paid` only for invoices; the answer has `tax_lines`,
`net`, `tax`), `GET /api/office/legacy/archive/<id>` (2.81.0: the entry with `history` [{at, user_name, field: client |
amount | paid, old, new}], newest first), `GET /api/office/legacy/archive/<id>/pdf`, `GET/POST /api/office/legacy/counter` `{kind, last}`.
2.40.0: the import takes `action` `contact` (with `merge_id` = the existing client or `contact_row` = the earlier row);
`POST /api/office/legacy/archive/address` (multipart `file`, `client_id`?) -> `{status: ok | no_text | none | busy | error,
address, unsure, client_id, client_name, new_client, add_contact, address_differs}` (nothing stored); the archive upload
takes the ticked proposals as `new_client` (JSON `{name, contact, street, zip, city, country}`) and `add_contact`.

**Contact persons (2.40.0)**: a client has several contact persons (name, function / department, e-mail, phone), one of
them the default (its name stays the client's field `contact`). Quotations, invoices, credit notes and reminders choose
one (`contact_id`: empty = the default, `0` = none); the attention line of the address follows the choice and the
e-invoice names the buyer's contact (BT-56, with phone / e-mail). A finalised document keeps its snapshot. **Country**:
clients and the company take an ISO 3166-1 alpha-2 code, chosen by name (the browser's names, Germany / Austria /
Switzerland on top, empty = Germany); `UK` becomes `GB`, `EL` `GR`, anything else is refused, and an old unknown value
stops the finalising of an invoice instead of turning silently into `DE`.

**Contact persons from the address book (2.59)**: in the client dialog, "From the address book" next to a contact person
searches the address books the client's organisation owns (a client without an organisation: your own address books;
private books never) and copies name, function, e-mail and phone into the fields; the contact person is then linked
("Linked", "Unlink" drops the link). Saving the client stores the link, Cancel drops it. Later changes of the contact do not
follow: documents keep reading the copy at the contact person. The contact's card shows "Contact person at" with the clients,
only to people who may open those clients. Deleting the contact or its address book only drops the link; a client moved into
another workspace loses its links. The nightly boundary check reports a link to an address book outside the client's
organisation and drops it.

**Merging duplicate clients (2.66)**: tick two or more clients (Office > Clients, selection mode) and choose "Merge". Pick the
client that stays and, where the values differ, which value it keeps; the contact persons are joined (the kept client's
default stays the default). The next step lists what moves: quotations and invoices, framework contracts, archive entries,
projects, contact persons, trips and sales opportunities. A finalised document keeps its printed address, only its client
changes; drafts and open quotations show the kept client's address afterwards. The DATEV export takes the customer number from the client:
issued invoices of a merged client go out under the kept client's number afterwards (the overview says so when the numbers differ).
2.81.0 (#1867): an invoice finalised while its client had a customer number keeps that number in the export; only issued
invoices without one follow the kept client (and only those are counted in the overview). The other clients are gone then; the toast
and the "History" of the kept client offer "Undo" for 30 days (a field or a link changed since stays as it is). Only the
clients of one workspace can be merged, and only by people who may delete the others (their creator or an admin).
`POST /api/clients/merge` `{target, ids, pick: {field: client id}, dry}` (dry: `{lines}` = the overview), then `{run_id,
target}`; `POST /api/clients/merges/{run_id}/undo`; the client's answer carries `merges` (the history). Not in the agent API yet.

## E-mails at clients and projects (2.84)

Mails can be filed with a client or a project: filed, assigned and searchable. Kalmido is no mail client: it never sends or
answers these mails, does not sync a mailbox and shows the text as plain text. It needs the mail input of *Tasks by
e-mail* (the server's mailbox, see SELF-HOSTING.md "Mail"); without it the addresses are not offered.

- **Addresses** (plus addresses of the server's mailbox, made on the first tap of *Copy address*): one per client (everybody
  who sees the client gets the same one), one per project (people who may change the project), and a **filing address** per
  person and workspace (Office > Clients > *E-mail filing*, one for the private space and one per organisation). The menu
  next to an address makes a new one (the old one stops at once) or turns it off.
- **Matching at the filing address**: the sender is compared with the client's e-mail, its contact persons and the address book
  contacts linked to them - only clients of the same workspace that the recipient sees. A mail the person forwards (or
  sends a copy of) counts with the original sender of the forwarding header, else with To / Cc. No match or several
  clients: the mail waits under *Not assigned* (only its recipient sees it) until it is assigned by hand. A client's or
  project's address files without matching; a project's mail names the project's client as well.
- **Where it goes**: the headers and the text are stored with the mail (sealed with the organisation's key when encryption
  is on); the original `.eml` and the attachments go into the file store, folder *E-Mails / client / date subject* of the
  workspace (the virus scan and the storage limit apply; a find leaves the attachment out, a full storage all of them -
  the mail says so). Assigning moves the folder along when the person may change it.
- **Who sees a mail**: a client's mail everybody who sees the client, a project's mail everybody who sees the project, a mail
  that is not assigned only its recipient - never across workspaces. Assigning and deleting need the right to change the
  project / see the client (taking a mail back to *Not assigned*: its recipient). Both are one undo step each; a deleted
  mail can be restored with Undo. The attachments of a mail can be opened by everybody who sees the mail.
- **Search**: subject, sender and text (a hashed word index, no plain index).
- **Agents** have no access to filed mails in 2.84 (no API route, no MCP tool).

## Travel expenses: taking over a per diem spreadsheet (2.95)

Office -> Money -> Travel expenses -> **Take over from Excel** (shown while the trip list is empty and in the
evaluation) reads a per diem spreadsheet you kept so far (.xlsx, up to 2 MB, at most 30 sheets with 500 rows each).
Nothing is stored before you confirm.

- **One sheet = one person.** The name comes from the title above the header ("... Arbeitsliste <name> - <year>") or the
  sheet's name. A person of the office with the same name is taken over as that person, otherwise as a free name; you can
  change it per sheet in the preview.
- **One row = one trip.** Columns (German or English headers): `Vom` / `bis` (Excel dates or DD.MM.YYYY), `Start` /
  `Ende` (times, needed for single days), `Ort` (place; a country in brackets, e.g. "Example town (Netherlands)", sets the
  country), `Anlass` ("Recherche/Akquise", "Akquise" or "Recherche" = acquisition / research, anything else = a job with
  the text as project) and `MVA` (the per diem of the row, only compared). A row "Summe" is the sheet's sum.
- **Cell comments** become the trip's note. A comment with lines like `Czechia: 1 × 21 € + 3 × 32 € = 117 €` (one line
  per country, "Inland" = Germany) sets the country of every day: the partial-day rates on the first and last day, the full
  days of the countries in the order of the lines in between. These lines are not copied into the note.
- **Preview:** every row is recalculated with the BMF rates of its year and compared with the spreadsheet. Status *new*,
  *hint* (the amount differs, start / end time of a single day missing, no rates for that year), *already there* (same
  person, same dates, same place; not ticked) or *error* (date not readable). Each sheet shows its sum from the
  spreadsheet next to the calculated one.
- **Take over N trips** creates the ticked trips in one step; the toast's **Undo** removes them again (trips whose receipts
  were billed on to a client meanwhile stay).
- Hints in comments (e.g. meals paid by the company, an unknown change of country) are never applied automatically: they
  stay in the note, set meals or days per trip yourself.

## Subscriptions and tools (2.91)

The office tab "Subscriptions & tools" (office admins; in a personal office its owner) shows every fixed cost marked as a
subscription: price, repeat, the next renewal, the last day to cancel (notice period in days), who uses it and a "hardly
used" switch. At the top are the sums per month and per year (net or gross; quarterly and yearly amounts spread over the
months, one-off costs not counted) and, when some are marked, what the hardly used ones cost a year. Subscriptions are
ordinary fixed costs: the fixed costs list in the cash flow, the spreadsheet import (optional columns "Abo" and
"Kündigungsfrist" in days) and this view edit the same rows, and the cash flow counts them once. A reminder (days before the
last day to cancel, for an office admin) puts a task "Check subscription: <name>" into that person's inbox, due on the last
day to cancel, with a link to the view and never an amount; it comes once per deadline and stays when the reminder is
switched off. Suggestions list fixed costs that look like software or a small repeating tool; nothing is marked by itself.
The list can be downloaded as CSV.

Routes (office admins): `GET /api/office/subs` {items, totals, candidates, people, remind_people}, `GET
/api/office/subs.csv`; writing goes through the fixed cost routes with the fields `sub`, `notice_days`, `seats` (user ids
of the office area or free names), `low_use`, `remind_days`, `remind_user`, `url` (http / https). Answers of the fixed
costs carry `next_renewal`, `cancel_by`, `per_month` / `per_year` (gross) and `per_month_net` / `per_year_net`.

## Sales pipeline and figures (2.50)

Two tabs for the admins of the office area (a personal office: its owner; members get `403`).

- **Pipeline** - deals from the first inquiry to the order, in four stages: *Inquiry*, *Quotation sent*, *Order*, *Lost*
  (2.94: before them the leads, see below).
  A deal has a name, a client of the area or a free contact name, a net value in the office currency, a probability
  (preset 20 / 50 / 100 / 0 % by stage; a value changed by hand stays when the stage changes, *Order* and *Lost* always
  set 100 / 0), an expected date, a note and a reason when lost. On a computer the stages are columns (drag a card into
  another column); on a phone one stage at a time with a switcher. On top: the open sum (inquiries + quotations), the
  weighted sum (value x probability) and what is expected to come in per month for six months (a past date counts in
  the current month, the next month is marked; deals without a date are shown apart).
  *Create quotation* makes a draft with the office's own quotation code (client and name taken over), binds it to the
  deal and moves an inquiry to *Quotation sent*. When the quotation's status becomes *accepted* - by hand or by the
  client's sign-off - the server moves its deal to *Order* (`pl2_offer_status`). A declined quotation leaves the deal
  where it is: the card is marked and the admin sets *Lost* or makes a new quotation. *Create project* (a won deal)
  makes a project list (type "Agency") named like the deal, in the office's workspace (a personal office: private),
  with the deal's client. Every change is one undo step; a deleted deal can be restored.
- **Figures** - one view the server computes (`GET /api/office/kpi?year=`): revenue = payments received on invoices,
  net share of each payment (refunds on credit notes subtracted), this month and this year so far against the same span
  a year earlier and per month as small bars (this year / the year before); open and overdue invoices (count and open
  gross; a tap opens the invoice list); the pipeline's weighted value; the next three months of the cash flow (the
  numbers of the cash flow tab, not computed again); per client the hours of its projects against `budget_h` /
  `budget_amount`, the net invoiced in the year, the costs in the year (purchases of accepted quotations, travel
  expenses of the client) and the margin = invoiced minus costs; per project the hours against its "Budget h" field.
  The start page has a block *Figures* with the main values for the admins of the office.

Routes: `GET /api/office/deals` (`items`, `summary`, `stages`, `probabilities`, `currency`), `POST /api/office/deals`,
`PATCH /api/office/deals/<id>` (answers `before` = the old values, the undo), `DELETE /api/office/deals/<id>`,
`POST /api/office/deals/<id>/restore`, `POST /api/office/deals/<id>/offer`, `POST /api/office/deals/<id>/project`,
`GET /api/office/deals/summary`, `GET /api/office/kpi`. Clients, lists and quotations of another area are refused.

### Leads (2.94)

Leads are people who might become clients: the first column *Leads* of the pipeline, before *Inquiry* (the same deals,
stage `lead`, preset 10 %). A lead has a source (website, recommendation, event, social media, appointment booking,
import, agent, other), a next step, a follow-up day, the person, company, e-mail and phone. The column is sorted by
follow-up day; a day that has come is marked in the accent colour, the toolbar counts the leads and those to follow up.
Leads never count in the open sum, the weighted sum or the forecast. *Convert into a client* makes a client of the area
from company / person / e-mail / phone (the person as its contact person) - or takes an existing client with the same
e-mail or company name, which is offered - and moves the deal to *Inquiry*; the undo moves it back and removes a client
made by the conversion as long as nothing else uses it. *Import CSV* reads a file with columns such as name, company,
e-mail, phone, source, next step, follow-up, note, value (German, English, Spanish, French, Italian and Dutch headers;
at most 1000 rows): a preview first, then the rows without errors are taken over; e-mails already in the pipeline or
earlier in the file are skipped as duplicates. An import is one undo step (its leads go into the bin). A confirmed
appointment booking adds a lead with the source *appointment booking* when its booking page names an office area.
Agents (scope `office`, the office switches, acting for an admin) list leads, add leads and change the next step,
follow-up day or note - they never convert, delete or set another stage.

Routes: `GET` / `POST /api/office/deals/<id>/convert` (`{client_id?}`; `GET` = fitting existing clients),
`POST /api/office/deals/<id>/unconvert` (`{remove_client?}`), `POST /api/office/leads/import` (`{text, commit?}`),
`POST /api/office/leads/import/undo` (`{ids}`); agents `GET` / `POST /api/v1/office/leads`, `PATCH /api/v1/office/leads/<id>`.

## Cash flow and fixed costs (2.67)

The tab **Cash flow** (admins of the office area only) shows per month what comes in and goes out, actual and planned.
**Fixed costs** (rent, subscriptions, insurances) are entered there: name, amount **net**, a free **category** (the list
groups by it, without one last; the field suggests the categories already used), the **VAT rate** (0, 7 or 19 %), repeat
(once, monthly, quarterly, yearly), first due date and end. Each row shows net and gross. Fixed costs from before 2.67
have 0 % and keep their amounts.

**Net | Gross** above the months switches the sums (gross by default; the choice is kept on the device). Gross adds the
rate to the fixed costs; documents (payments, open invoices, quotations, credit notes) are gross and take their
net share on the net basis; purchases and travel receipts have no rate here and count the same on both. The start page
figures use gross.

**Receipts** (2.114.1): the receipts of the tab Bookkeeping go out on the same day as in the income/expense statement - their
payment day (set by matching them to a bank booking), else their document date. A receipt matched to a booking counts with
the booking's amount; net takes the receipt's VAT rate off. A fixed cost or purchase entered for the same thing as a
receipt counts twice - leave one of them out.

**Quotations in the plan** (2.88): sent and accepted quotations count as planned income on the end of their period of
service (else its start, else their date); a sent one is marked **open quotation** (a dashed entry, the month shows its
share apart). "Duplicate" on a quotation makes the copy its next **version** (`version_of` = the first quotation of the
chain; a copy given to another client is a quotation of its own). Per chain one version counts:

- **Automatic** (default): the newest sent or accepted version; drafts and declined versions never count.
- **Yes**: when a version of the chain says yes, exactly the yes versions count (several are possible).
- **No**: this version never counts.
- Once a finalised invoice exists for any version of the chain, the whole chain is left out (the invoice is in the plan
  itself); a draft invoice does not take it out yet. Before 2.88 only the invoiced part was taken off.

The choice **In the cash flow** sits in the quotation (also when it is sent or finalised: it is planning, not printed and
not part of the approval) with a line which version counts; everyone who may edit the area's quotations may change it, one
undo step takes it back, the office log records it. Freelancers without an organisation have the same in their personal
office.

**Import from Excel**: "Download template" gives an .xlsx with the header row and three example rows. The first sheet is
read below its header row: `Name`, `Betrag (netto)` (also `Betrag`, `netto`, `Amount (net)`), `fällig Monat` (also
`Monat`, `Due month`); optional `Kategorie`, `USt`, `Wiederholung`. A row with a name but no amount is a group row: its
name is the category of the rows below. Month 0 = monthly from 1 January 2026, 1-12 = yearly in that month (on the 1st);
a quarterly cost (the name says "vierteljährlich" / "Quartal", or the column `Wiederholung`) with a month X becomes four
yearly rows (X, X+3, X+6, X+9); with month 0 the month wins (monthly). The VAT rate is 0 % for insurances, levies and
contributions, else 19 %, and can be changed per row in the preview. Amounts like `1.200,50`, `12.500`, `1,200.50` and
`29,90` are read. The preview marks every row new, duplicate (same name, amount and repeat as an existing cost or an
earlier row of the file; not ticked) or error (no name, amount 0 or missing; never taken over). Nothing is stored before
"Take over N rows"; then every row is checked again, all are written in one step (the undo removes them again), at most
500 fixed costs per area. Files up to 2 MB and 500 rows; cells are read as text, formulas are never run.

**Import with your own agent** (2.68): old fixed costs in any other format (an old spreadsheet, a PDF, a list in a mail)
can be read by your own agent, which sends them as an import proposal in a fixed JSON shape (permission *Propose imports*,
off by default; format in [AGENTS.md](AGENTS.md#importing-old-data-into-the-office-2680)). Kalmido does not read the data
itself. The proposal card shows the same preview as the Excel import (new / duplicate unticked / error greyed out with the
reason, VAT per row, net and gross) and the office it goes into; "Take over N rows" writes them as you, one undo step
removes them again. The agent never sees the office; an agent of an organisation imports only into that organisation.
Freelancers without an organisation import into their personal office.

**Monthly check** (optional): a tick creates the task "Cash flow: check the actual state" for one admin of the area, due
on the 1st of every month in that person's basket, with only a link to the cash flow (never an amount). Another person
ends the old task and creates a new one; switching it off ends the task (done, without a next date; not deleted). If the
person later loses access to the cash flow, the tab says so; nobody else is picked automatically.

Routes (office admins, people only; agents get 403): `GET /api/office/cashflow?from=YYYY-MM&months=1..12&basis=gross|net`,
`GET/POST /api/office/fixed-costs`, `PATCH/DELETE /api/office/fixed-costs/<id>` (`category`, `vat_rate` 0/7/19; the answer
adds `gross`), `POST /api/office/fixed-costs/import/preview` (multipart `file`), `POST /api/office/fixed-costs/import`
(`{items: [{label, amount, repeat, start, until?, category?, vat_rate?}]}` -> `{created, ids}`),
`POST /api/office/fixed-costs/delete` (`{ids}`: the undo of an import), `GET /api/office/fixed-costs/import/template`,
`GET/PUT /api/office/cashflow/check` (`{on, user_id}` -> `{on, user_id, task_id, people, lost}`).

## Bookkeeping (2.90)

The tab **Bookkeeping** (admins of the office; without an organisation your personal office) covers the running bookkeeping
of a self-employed person. **Photograph receipt** opens the camera on a phone (the file dialog on a desktop, PDF too): the
receipt goes into your documents, amount and date are recognised in the background, and you add the category and the VAT
rate (19 / 7 / 0 % or unknown). The **income/expense statement** of a year counts payments received on your invoices
(cash principle, split by VAT rate) against your receipts and travel expenses, with export as CSV or PDF. The **VAT return**
section lists the figures (fields 81, 86, 21, 45, 66, 83) for a month or quarter to type into ELSTER, on cash or accrual basis;
small businesses get no return. A **tax reserve** (percentage of the net money received) shows up per month in the cash flow
as "Tax reserve" and "Freely available". No tax advice; figures without guarantee. Kalmido sends nothing to the tax office.

## Bank reconciliation (2.90)

The tab **Bank** (admins of the office area; in a personal office its owner) matches the bookings of your account with
invoices and receipts. Kalmido has no bank access: you import the file you download from your bank yourself.

- **Import bank statement**: a CSV export (German and English formats: `1.234,56` or `1,234.56`, `DD.MM.YYYY`,
  `YYYY-MM-DD` …; account lines above the header are skipped) or a CAMT.052 / CAMT.053 XML file. For a CSV you confirm
  which column holds the date, the amount (one column with a minus for money out, or income and expense apart), the
  purpose and the counterpart; Kalmido guesses them as in the household budget. A CAMT file goes straight to the
  preview (booking day, amount with credit / debit, counterpart and IBAN, purpose, the bank's reference). XML files with
  a DOCTYPE or ENTITY are refused. At most 2 MB and 3000 rows per file.
- **Duplicates**: a booking already imported into this office area (same day, amount, counterpart, purpose, reference)
  is skipped and counted; two equal bookings in one file stay two.
- **Matching**: every open booking shows the best suggestion with its reason. Money in -> open invoices (same amount as
  open, invoice number in the purpose, customer name); money out -> receipts of the office's documents (same amount,
  date within 14 days, name). **Match** records a payment on the invoice (day and amount of the booking, transfer; a
  smaller amount = partly paid) or sets the receipt's payment day (used by the bookkeeping's cash principle). **Other …**
  searches all open invoices / receipts; **Private** and **Ignore** only mark the booking. **Undo match** removes the
  payment again; deleting the payment on the invoice opens the booking too. Every step can be undone.
- **Imports**: the list of imported files; **Take back** removes its bookings (refused while one of them is matched -
  undo those matches first); its undo brings them back.
- Amounts, counterparts, purposes and IBANs are encrypted at rest when the encryption of the organisation is on. The
  DATEV export is unchanged. Agents have no access to the bank reconciliation.

Routes (office admins only; members 403, other areas 404, agents 403): `POST /api/office/bank/import/preview`,
`POST /api/office/bank/import`, `GET /api/office/bank/imports`, `POST /api/office/bank/imports/<id>/undo|restore`,
`GET /api/office/bank/tx?state=open|matched|all&from&to`, `GET /api/office/bank/tx/<id>/candidates?q=`,
`POST /api/office/bank/tx/<id>/match` `{kind: invoice|receipt|private|ignored, id?}`, `POST /api/office/bank/tx/<id>/unmatch`.
Tables `office_bank_imports`, `office_bank_tx` (see Database).

## Tax dates as tasks (2.90)

At the bottom of **Bookkeeping**, **Tax dates** keeps the usual German deadlines in view: the VAT return (none, monthly
or quarterly, optionally with the permanent extension), the income tax prepayments (10 March, June, September, December)
and the trade tax prepayments (15 February, May, August, November). Each kind switched on becomes ONE recurring task in
the basket of the person chosen (an admin of the office; in a personal office its owner), due on the deadline minus the
lead time (default 3 days); the title names the real deadline, the VAT task links to the VAT return figures.
Switching a kind off or changing it ends the old task (done, never deleted) and creates a new one when needed; a task
completed or deleted by hand comes back on the next save. A deadline on a weekend or holiday moves to the next working
day (Kalmido does not shift it). No tax advice; figures without guarantee.

Routes (office admins only): `GET /api/office/tax-dates`, `PUT /api/office/tax-dates`.

## Contracts and insurance (2.92.0)

The tab **Contracts & insurance** (office admins only; in a personal office its person) keeps the business contracts of the
office in one place: insurances, rent, leasing, service providers and others. Per contract: name, provider, policy or
contract number, the contribution per month / quarter / year (net when a VAT rate is set), start, the end of the current
term, the notice period (days, weeks, months), the automatic renewal (or "ends without renewal"), how many days before the
deadline to remind, a note and the contract document. The list is grouped by kind and shows the contribution per month and
the next deadline ("Cancel by 12 Mar 2027 · 41 days left", in red from the reminder lead on).

- **Deadline**: the last day to cancel is the end of the term minus the notice period (the same logic as the household
  contracts in Home & life). When it has passed and the contract renews, the term rolls on to the next one; a contract
  without renewal is simply over.
- **Deadline as a task** (on by default): one task in a list you pick (default: your Basket), due on the last day to cancel,
  with reminders and a repeat that follows the renewal. Changes to the contract update the task; switching it off,
  archiving or deleting the contract ends the task (it is completed, never deleted). Agents that may see that list can remind
  you of the deadline (event `contract_notice`, see AGENTS.md); Kalmido itself never phrases anything.
- **Cash flow**: with "Contribution in the cash flow" (on by default) the contribution is an outflow in the cash flow like a
  fixed cost (kind *Contract or insurance*, net or gross by the VAT rate), from the start (else the start of the current
  term) every period, up to the end of the term when it does not renew. The fixed costs list shows these rows read-only
  under *From contracts* with a link to the contract - they are never copied into the fixed costs.
- **Document**: choose a document of the office's documents space (the organisation's, or your own in a personal office)
  or upload one there; it is stored encrypted like every document.
- Cost, number and note are encrypted at rest. Every change is one undo step; a deleted contract can be restored by the
  undo (it is purged after 30 days).

API (office admins; agents and members 403, another office area 404): `GET /api/office/agreements` (`?archived=1`),
`POST /api/office/agreements`, `GET|PATCH|DELETE /api/office/agreements/<id>`, `POST /api/office/agreements/<id>/restore`.
Fields: `kind` (insurance | rent | leasing | service | other), `name`, `provider`, `number`, `cost`, `per` (month | quarter |
year), `vat_pct` (null | "19" | "7" | "0"), `start`, `ends`, `notice`, `notice_unit` (d | w | m), `renew_months` (0-120, 0 =
ends), `lead_days`, `cashflow` (0|1), `doc_node_id`, `note`, `archived` (0|1, PATCH), `task` (0|1) and `list_id` (the
deadline task). `GET /api/office/fixed-costs` also answers `agreements` (the contributions in the cash flow, read-only).

## Equipment value, depreciation and insurance list (2.92.0)

Admins of an office (and every person in their personal office) can record what a device cost:
purchase date, net purchase price, serial number, vendor and the receipt. Open a device and unfold
**Purchase and value**.

- **Take from receipt** picks a document of the office's document space and proposes date, net price
  and vendor. The net price is only filled in when the receipt states its VAT rate (19 % or 7 %);
  otherwise the gross amount is shown as a hint and you enter the net price yourself.
- **Depreciation**: a useful life is suggested from the category or name (for example computers and
  software 12 months, cameras, lenses, light and sound 84, drones 84, furniture 156, vehicles 72, everything
  else 60) and can be changed per device. Devices up to 800 EUR net are written off in full in the
  purchase year, more expensive ones linearly by the month from the purchase month on. The table in the
  device shows depreciation and book value per year.
- **Insurance values**: the new value defaults to the purchase price, the current value to the book
  value; both can be overwritten. **Insured by** links the device to an insurance contract
  (Contracts & insurance).
- The equipment list shows the sums (new value, current value, depreciation of the year) and exports the
  insurance list as CSV or PDF, optionally filtered by policy.

Members of an organisation see the devices, never their prices or values. All prices, values and
serial numbers are encrypted at rest. No tax advice; figures without guarantee.

API (office admins; members 403, another office area 404): the fields go through `POST|PATCH /api/office/equipment[/<id>]`
(`purchase_date`, `purchase_net`, `new_value`, `current_value`, `serial_no`, `vendor`, `receipt_node_id`, `life_months`,
`agreement_id`); `GET` answers admins also `afa_plan`, `afa_year`, `book_value`, `new_value_eff`, `current_value_eff`,
`life_suggest`, `life_eff`, `agreement_name`. `GET /api/office/equipment/value` (sums and rows), `value.csv`, `value.pdf`
(`?agreement_id=`, 0 = not insured), `GET /api/office/equipment/policies`, `GET /api/office/equipment/receipts[/<id>]`.
## Logbook (2.93)

The tab **Travel expenses** has a third view **Logbook** (admins of the office area; without an organisation your
personal office). First add a **vehicle**: name, plate, kind (**private car used for business** -> mileage allowance, or
**company car** -> its costs come through receipts) and the odometer at the start. Vehicles are archived, never deleted.

- **Drives** of a vehicle and year, newest first (cards on a phone): date, start, destination, purpose, kilometres or
  the odometer at start and end (km is computed; the start is prefilled with the last end of the vehicle), kind
  business / private / home - workplace, client and project (as in the travel expenses), driver (default: you). The end
  below the start is refused; a gap or an overlap to the odometer of the previous drive is shown as a warning and saved.
- **Change log**: every create, change, delete and restore is recorded with the values before, who and when ("History"
  in the drive). Deleting only hides the drive (undo restores it); nothing is deleted for real.
- **Take over into travel expenses** (business drives): creates a trip with day, route, purpose "job", client, project
  and km - without a receipt, so nothing counts twice. Once taken over, the button opens that trip.
- **Year report** per vehicle: km total / business / private / home - workplace, the business share and the **mileage
  allowance** (business km of private cars x the rate per km, default 0.30, changeable in the report). Export as CSV
  (semicolon, decimal comma) or PDF, both with the change log of the year.
- The **rate per business km is kept per year**: changing it for one year never changes the allowance of earlier years.
  Every new or changed vehicle and every rate change is written to the office log and listed in the change log of the
  CSV / PDF of the year. Taking a drive over into the travel expenses is logged too (only the destination goes into the
  trip, start and purpose into its encrypted note); the trip keeps its km when the drive changes later, the drive shows a hint.
- The mileage allowance goes into the **income/expense statement** as its own expense line "Mileage allowance" (no input
  tax); travel receipts of the category car stay as they are. Drives without a vehicle, private drives, drives with a
  company car and deleted drives do not count.
- The tax office only accepts a logbook kept promptly and without gaps; Kalmido logs later changes but does not make a
  logbook "tamper-proof" in the legal sense. No tax advice; figures without guarantee.

Routes (office admins only; members 403, other areas 404, agents 403): `GET|POST /api/office/vehicles`,
`PATCH /api/office/vehicles/<id>` (also `archived`), `GET /api/office/drives?vehicle_id=&year=`, `POST /api/office/drives`,
`PATCH|DELETE /api/office/drives/<id>`, `POST /api/office/drives/<id>/restore`, `GET /api/office/drives/<id>/log`,
`POST /api/office/drives/<id>/trip`, `GET /api/office/logbook/report?year=&vehicle_id=`,
`GET /api/office/logbook.csv|pdf?year=&vehicle_id=`, `PUT /api/office/logbook/settings` `{km_rate, year}`.

## Travel expenses: per diem (2.95)

Every trip computes the German per diem (*Verpflegungsmehraufwand*) per participant with the flat rates of its year:
Germany 28 EUR for a full day and 14 EUR for the day of arrival / departure (or a single day of more than 8 hours), abroad
the rates of the BMF letter of that year (2025: BMF letter of 2 December 2024, 2026: BMF letter of 5 December 2025). A
year without a table gives **no amount but a hint** -- Kalmido never estimates or extends rates.

- **Trip dialog**, section *Per diem*: the country (Germany first, then the countries of the year's table) and, where the
  table names cities (e.g. Athens), the city or *Other places*; start and end time for a single day (and for two days
  without an overnight stay); *No per diem* switches it off for that trip.
- **Trip view**, card *Per diem*: the amount per person x participants, the breakdown like a spreadsheet
  ("Greece: 1 x 24 EUR + 1 x 36 EUR = 60 EUR"), hints (times missing, 8 hours or less, no rates for that year, the rate of
  another country used) and the source. **Edit days**: per day the country (where you are before midnight) and the meals
  provided -- breakfast cuts 20 %, lunch and dinner 40 % each of that day's full rate. Only days that differ are stored;
  every change is one undo step.
- **Trip list**: the per diem of all participants next to the receipts.
- **Evaluation**: *Per diem allowances <year>* (with "All years": the current year) with the sum per person (a trip
  without participants under "No person"), unfolding to the trips and their breakdown; trips without an amount are listed
  but not summed, trips with *No per diem* are left out. A trip over the turn of the year counts its days per year.
  Downloads: **PDF** (a section per person), **Excel** (one sheet per person: From, to, Start, End, Destination,
  Occasion, Per diem, Breakdown, with a total) and **CSV** (semicolon, decimal comma). Each download is written to the
  office log.

Routes (admins of the office area; a person without an organisation in the personal office): `GET
/api/office/trips/vma-rates?year=` (countries, cities and rates of a year), `GET /api/office/trips/vma?year=&person=`
(the report as JSON), `GET /api/office/trips/vma.pdf|vma.xlsx|vma.csv` (same parameters). Agents do not reach travel
expenses. Kalmido does not replace tax advice.

## Travel expenses: purposes, person filter, row menu (2.117)

- **Own purposes**: the choice *Purpose* of a trip ends with *Add another purpose…*; a field opens right below it, Enter
  stores the name as an own purpose of the office area and chooses it. Office -> Settings -> *Travel expenses* lists the
  own purposes: rename in place (saved when you leave the field), remove (one undo step), add more. Trips keep the text
  they have when a purpose is renamed or removed. The evaluation sums *by purpose* too; a spreadsheet import adopts
  purposes it does not know yet, an occasion named like an own purpose becomes that purpose; moving trips into another
  office offers their purposes there as well. A person without an organisation has an own list in the personal office.
- **Person filter**: next to *All* / *Not in DATEV* a choice of the people of the office and the free names of the
  trips (hidden when only one person occurs). It filters the trip list, the evaluation (each receipt with that person's
  equal share of the trip) and the per diem report, and the downloads (CSV, PDF, Excel) take it over. The choice stays
  when you switch views.
- **Row menu**: the arrow at the right of a trip opens a menu: Open, Edit trip, Duplicate (a new trip with the same data,
  without receipts), Move to another workspace, Delete (asks first, one undo step). A tap on the row still opens the trip.
- **Dates**: the picker of *To* opens at the start day when it is empty, days before the start are disabled; a later start
  moves an earlier end along. The other from / to pairs of the office (DATEV export, contracts, cash flow, subscriptions,
  service period, invoice from time entries, recurring invoices) open the same way.

Routes (admins of the office area): `GET /api/office/trips/purposes`, `POST /api/office/trips/purposes` `{name}` (201;
the same name = the one there, a removed one comes back), `PATCH /api/office/trips/purposes/<id>` `{name}`, `DELETE
/api/office/trips/purposes/<id>`; `GET /api/office/trips/report?...&by=purpose&person=u<id>|n:<name>`. Agents do not reach
travel expenses.

## Web API

All routes require a signed-in person with the module on; they work in the office of the shown workspace (`400` with a
hint only for "All workspaces" with several organisations); writes need the area's admin. `GET /api/office/settings`
also returns `personal` (1 = the personal office); a personal office adds `can_move` (1 = `POST /api/office/move` is
allowed) and `org_offices` (`[{id, name}]` while it is empty and the person has organisations: the hint). `GET/PUT /api/office/settings`, `GET /api/office/packs`, `GET /api/office/packs/<code>`,
`POST /api/office/packs/validate`, `GET /api/office/number-preview?scheme=&kind=offer|invoice|credit|reminder` (the next number, `yearly` = the counter restarts every year, or a plain-language `error`), and for each of `services`, `equipment`,
`sets`, `texts`, `contracts`, `roles`, `crew` (2.47.0): `GET /api/office/<kind>?q=&archived=1`, `POST /api/office/<kind>`,
`GET/PATCH/DELETE /api/office/<kind>/<id>` (delete archives a row that documents, contracts or sets still use).
`GET /api/office/export`, `POST /api/office/import?overwrite=1` (JSON body or multipart `file`). Documents: see
`/api/office/docs` below. 2.38.0 adds `POST /api/office/docs/<id>/invoice`, `POST /api/office/docs/<id>/credit`,
`POST /api/office/docs/from-time`, `POST /api/office/docs/reminder`, `GET/POST /api/office/docs/<id>/payments`,
`DELETE /api/office/docs/<id>/payments/<pid>`, `POST /api/office/docs/<id>/send`, `POST /api/office/docs/<id>/datev` and
`GET /api/office/mail-status` (see "Invoices and credit notes" below); 2.40.0 adds `POST /api/office/docs/<id>/fee`
(see "Payments and reminders"). Agents never reach `/api/office/*` (their routes are `/api/v1/office`, see "Agents").

## Quotations and the calculator

(Stage 1: quotations. See the editor's tab "Quotations".) The calculator is a pure function over the document, its
positions and the country pack: position total = quantity x rate; producing days = sum of the "producing" quantities
divided by the producing quotient, rounded to half days; raw data amount = sum of the "raw fee" positions x raw data
factor (optional, included via a framework contract, or none); discount in percent on the discountable positions; tax
per position from the pack. Transfer of rights is printed as its own section (duration, territory, media) in the
document's language.

Routes (members of the organisation; deleting needs its admin; costs and surplus only for the admin):
`GET /api/office/docs?kind=offer&status=&q=`, `POST /api/office/docs` (a new draft from the settings; the number of the
scheme is reserved at once), `GET/PATCH/DELETE /api/office/docs/<id>` (PATCH changes the head and returns the totals;
choosing a framework contract presets raw data, rights and closing unless `apply_contract: false`),
`PUT /api/office/docs/<id>/items` (the whole list of positions; a `service_id` fills title, rate, tax and flags),
`POST /api/office/docs/<id>/number` (`{number}` by hand, unique per organisation, or the next one of the scheme),
`POST /api/office/docs/<id>/status`, `POST /api/office/docs/<id>/duplicate`, `GET /api/office/docs/<id>/render` (the
print model as JSON: all texts, labels and amounts already in the document's language and format),
`POST /api/office/docs/<id>/finalize`, `GET /api/office/docs/<id>/log` and `GET /api/office/log?limit=` (organisation
admins). The head also carries the period of service (`service_from`, `service_to`, dates; printed as one line).

Purchase and surplus (2.47): a new position of a service takes the purchase (`cost`) of the service's freelancer role
for its unit (day / hour); a later change of the role's price reaches only new positions; the admin can change it per
position. Admins get the surplus of every position (`items[].margin` = total minus purchase x quantity) and their sum
(`items_margin`); members get neither `cost` nor `margin` (the fields are absent), and neither appears in the print model
or the PDF. A position of unit `percent` (e.g. the artists' social insurance) is its rate in percent of the positions
marked `extern` on the same sheet; its quantity does not count; an invoice made from the quotation turns it into a plain
amount. When a quotation becomes "accepted" its purchase is stored for the cash flow (`office_purchases`: one row per
position with a purchase and per part, amount encrypted at rest, dated at the start of the period of service, else the
day of acceptance), stored anew when the accepted quotation changes and removed when it leaves that status.

## Recipient and client names (2.97.0)

- A client has its name (printed on quotations, invoices, the e-invoice) and an optional **display name** for the pickers
  and lists ("Foo Switzerland" / "Foo Germany"). Without one, two clients of one workspace with the same name show the
  city in brackets, the country when the city is the same too. The client search finds both names.
- The address is kept in fixed fields only: street, address extra (c/o, building), postcode, city, country. The old free
  "Address" text left the form; where it was the only address, street / postcode / city were filled from it once (the
  text stays in the database, nothing is overwritten).
- A quotation or invoice with a client shows the recipient read-only next to the client (name, attn., street, extra line,
  postcode city, the country when it is foreign) with "Edit client"; a missing street / postcode / city shows "Address
  missing - add it at the client". A document without a client offers "Add client" (name + address), which then becomes
  its client. Drafts always read the client's current address; finalising (or sending) freezes it, later changes at the
  client leave issued documents alone. Old documents with free address lines keep them. With the clients module off the
  free recipient fields stay.
- 2.99.0: a client may have a **name addition** (field under the name, e.g. "Berg, Tal & Partner GbR" under
  "NORDLICHT"). Quotations and invoices print it as its own line under the name, the e-invoice joins it to the buyer
  name with " - ", lists and the search show "name - addition" on one line. The buyer e-mail of the e-invoice is the
  client's invoice e-mail, else its e-mail; VAT ID and buyer reference (Leitweg-ID) come from the client's billing fields.
- 2.99.0: the own **company name** in the office settings may have up to three lines; the letterhead and the footer print
  them one under the other, the small sender line above the address, mails and the e-invoice (seller name) on one line.
  The company address has the same fixed fields as a client (street, address extra, postcode, city, country). While
  they are empty, a plain address in the old free "Address lines" (street, postcode + city, maybe a country) is shown in
  the fields; saving the settings keeps it there, the free lines stay as they were.

## Finalising

A document can be finalised (button "Finalise" in the editor, after a confirmation; any member of the organisation).
Finalising freezes it:

- the number is assigned if it has none yet;
- the totals are stored and never recomputed; every position keeps its tax rate, net amount and tax amount as decimal
  text (`tax_pct`, `net`, `tax_amount`);
- the sender (company lines and fields, colour, the logo by its SHA-256 - the file is kept as `logo-<hash>.png`), the
  recipient (with the client's billing fields) and the country pack's rates, formats and print words (`pack_version`)
  are stored in the document.

The print model and the PDF of a finalised document are built from this snapshot only: later changes of the company,
the logo, the services, the client or the country pack do not change it. Changing the head, the positions or the number
and deleting answer `409` with a reason; the status of a quotation can still change. "Duplicate" makes a new open draft
(a new version) without the snapshot. Quotations do not have to be finalised; it is an optional step for them. Since
2.38.0 a quotation with status "sent" is locked the same way (a business letter is kept as sent; a new version = duplicate).

Since 2.114.2 a finalised **quotation that never left the house** can be taken back by the organisation's admin (a
person without an organisation in the personal office, too; members get `403`): it is still in status "draft", was never
sent (no `sent_at`, no logged e-mail), the customer did not decide on an approval link, and no invoice or order
confirmation was made from it. Then the "More" menu offers:

- **Undo finalising** (`POST /api/office/docs/<id>/unlock`): back to an open draft; the number stays and is kept when it
  is finalised again; the snapshot is made anew then. The history shows "finalising undone" with the number.
- **Delete**: the number stays used and the office log keeps the delete entry with the number (`locked: true`), so the
  gap stays traceable. Open approval links go with it, a sales opportunity loses its link to the quotation, the later
  versions of a deleted first quotation stay in their chain.

Everything else answers `409` with the reason (sent, accepted, declined, signed, invoiced); invoices, credit notes and
reminders stay strictly locked. The list rows carry `can_delete` / `can_unlock` for the admin.

## Parts of a quotation

(2.47.0.) A quotation may have **parts**: own pages behind the title page, each with its own positions and calculation
(producing, raw data, sum net / incl. raw data), e.g. one page per module or per shooting day. The title page lists a part
like a service: a position of kind `part` with a quantity ("Interactive module x 5"); the title page can also have direct
positions. A part may stand on the title page several times or not at all (then it counts nothing and is not printed; the
editor marks it).

- **Calculation**: a part line = the part's net x quantity; its tax bases per rate x quantity (a part with 7 % and 19 %
  positions stays exact), its raw data x quantity (optional stays optional, included stays included) and its external
  costs x quantity flow into the title page. Producing on the title page counts its direct positions only; the title
  page's discount applies to part lines marked discountable. A part takes the quotation's calculation values unless its
  `settings` set their own (`raw_mode`, `raw_factor`, `prod_quotient`, `producing_rate`, `producing_on`, `discount_pct`;
  the quotation's discount is not applied inside a part). The stored rate of a title page part line is the part's net.
- **Printing**: the title page as before (part lines with title x quantity and amount), then every part with "Print in the
  PDF" on its own page (part title, quotation number, its positions and sums). A part with printing off still counts.
  External costs and surplus never appear in the PDF.
- **Invoice**: "Create invoice" on a quotation with parts asks for the form - `full` (like the quotation: the title
  page's direct positions, then per printed part a heading and its positions with quantity x part quantity, its producing /
  raw data / discount as positions; a part not printed stays one line), `title` (the title page; a part becomes a
  position with its amount, one per tax rate) or `summary` (one position per tax rate with a title, default
  "Filmherstellung" / "Film production"). Net and gross equal the quotation's in every form, to the cent: with a
  fractional part quantity (1.5 shooting days) and mixed tax rates the part line is exactly rate x quantity, and the
  rest cent of the rounded positions goes on the last position of that rate, which then shows as one amount with its
  quantity x rate in the description (2.58.0). The preset is an office
  setting (`parts_invoice_mode`: `full` default, `title`, `summary`; `parts_summary_title_de`, `parts_summary_title_en`).
- A quotation without parts computes, looks and prints exactly as before.

Routes (members of the organisation like the positions; external costs only for its admin; a finalised or sent quotation
answers `409`): `POST /api/office/docs/<id>/parts` (`{kind: items|shoot, title, print, add_to_title}`; the new part is put
on the title page once unless `add_to_title: false`), `PATCH /api/office/docs/<id>/parts/<pid>` (`{title, print, sort,
settings, sheet}`), `DELETE /api/office/docs/<id>/parts/<pid>` (with its positions and its title page lines),
`PUT /api/office/docs/<id>/parts/<pid>/items` (the whole list of the part's positions, like `PUT .../items`).
`GET /api/office/docs/<id>` carries `parts: [{id, kind, title, print, sort, settings, items, totals, used}]`;
`POST /api/office/docs/<id>/invoice` takes `{parts_mode, parts_title}`. Duplicating copies the parts.

## Invoices and credit notes

(2.38.0, stage 2.) The Quotes & invoices tab lists quotations, invoices, credit notes and reminders (`kind` = `offer`, `invoice`,
`credit`, `reminder`). An invoice starts in one of three ways:

- **from a quotation** ("Create invoice" on the quotation, `POST /api/office/docs/<id>/invoice`): every line of the
  quotation becomes a plain position - the producing, raw data and discount lines the calculator made are condensed
  into positions with their amount, an uncounted raw data option is left out; rights, framework contract text,
  recipient, project title, language, currency and rate, period of service and the PO number are taken over
  (`source_doc_id` points back);
- **from time entries** (`POST /api/office/docs/from-time` with `{client_id, from, to, project_id?}`): the finished time
  entries of the client's lists in the period, one position per list with the hours; the rate is the client's hourly
  rate when set, else 0 to fill in;
- **empty** (`POST /api/office/docs` with `{"kind": "invoice"}`).

Invoices have no producing / raw data / discount automation: a document is exactly its positions. A discount is a
position of kind `discount` (its amount is taken off, same tax class). The invoice calculator is Decimal throughout:
every position is quantity x rate rounded half up to 2 places (the rate converted into USD first, like quotations), the
net is the sum of the positions, the tax per rate is computed on the rounded sum of that rate (EN 16931), and all
amounts of `totals` are decimal strings with 2 places (`"net": "34422.90"`, `tax_lines: [{pct, base, amount}]`, `tax`,
`gross`). A USD invoice also carries `tax_eur` and `gross_eur` by the document's rate (printed as a note). Quotations
keep their numeric totals.

Head fields of an invoice: `order_ref` (the client's PO number), `payment_days` and `due_date` (the due date is set from
the payment days when it is empty: the client's payment terms, else the organisation's default), `vat_note` for
documents without VAT (`reverse`, `abroad` or `small`; the text comes from the country pack and is required before
finalising), `einvoice_format` (`zugferd` by default, `xrechnung` proposed for clients with a buyer reference).

States: `draft -> issued -> sent -> paid`. `issued` comes with finalising only; `sent` with sending (or by hand);
`paid` through payments (or by hand; setting or leaving `paid` by hand: the organisation's admins only, members 403). The answers also carry a derived `state` (never stored): `partial` when part of
the gross is paid, `overdue` when the due date passed and the invoice is still open. `cancelled` is set only by a credit
note over the full amount, never by editing; there is no way back to `draft`. A status change the model does not allow
answers `409`.

Finalising an invoice checks the required fields first and answers `400` with the list of what is missing: recipient
name and address (street, postcode and city from the client, or at least two address lines), date, period of service,
at least one position, the company's name, address, tax number or VAT ID and IBAN (settings > company fields), a due
date or payment days, and the VAT note for documents without VAT. Then the number is assigned (see below), the status
becomes `issued`, the snapshot is stored like for quotations and the PDF/A-3 + e-invoice XML are written (see
"E-invoices").

Numbers: one series per organisation and kind - settings `invoice_scheme` (`RE-{yyyy}-{seq:03}`), `credit_scheme`
(`GS-{yyyy}-{seq:03}`), `reminder_scheme` (`MA-{yyyy}-{seq:03}`); a draft has no number, the number comes with finalising
(no gaps through deleted drafts). A number by hand (`POST /api/office/docs/<id>/number`) is accepted in the draft only
when it follows the scheme and lies above the series' last value; the counter then continues from it. A number more than
one above the counter leaves a gap and needs `{number, reason}` (at least 5 characters; kept in the office log). Checking
and writing a number run under one lock per organisation. Numbers are unique per organisation.

A **credit note** (`POST /api/office/docs/<id>/credit` on a finalised invoice; button "Credit note / cancel") is a draft
with the invoice's positions and `cancels_id`; shorten it for a partial credit. When the credit note is finalised it
lowers the invoice's open amount; over the full gross it sets the invoice to `cancelled`. Credit notes have their own
number series and print "Credit note for invoice no. ...". Since 2.40.0 a credit note keeps the e-invoice format of its
invoice (XRechnung for a client with a buyer reference), has its own closing (pack text `credit_closing`) and its XML
carries no "payable on receipt" terms.

**Changing the language of a draft** (2.40.0): `PATCH /api/office/docs/<id> {lang}` sets intro, closing (settings, pack or
framework contract), the rights texts, the rights note and the titles of catalogue positions anew in the new language,
but only where the field still holds the standard text of the old language; for reminders a new `reminder_level` swaps
the level's texts the same way. Texts changed by hand stay. The answer then carries `lang_notes` (list of plain
sentences: "Introduction changed by hand, not translated", "Media: no English text stored", ...), which the editor shows
in a note box. A text block without an English text keeps its German text and is named there. Finalised documents are
never changed (409).

## Payments and reminders

Payments (`office_payments`): `GET /api/office/docs/<id>/payments`, `POST ... {date, amount, method: transfer|cash|card|
other, note}` by the organisation's admins (members 403, since 2.39.1) on a finalised, open invoice, `DELETE /api/office/docs/<id>/payments/<pid>` by the
organisation's admin. The sum of the payments plus the finalised credit notes against the invoice's gross gives
`paid`, `credits` and `open` in the answers; covered in full the invoice becomes `paid` with `paid_at`, a removed payment
reverts that. The print model of an invoice with payments shows "already paid" and "amount outstanding".

Reminders (`kind` = `reminder`, "Create reminder" in the invoice list): `POST /api/office/docs/reminder` with
`{doc_ids: [...], level: 1|2|3, fee?, deadline_days?}` makes a draft over open, finalised invoices (one client); the
recipient comes from the first invoice. Level 1 prints "Payment reminder", 2 "Reminder", 3 "Final reminder" (country
pack labels `reminder_1..3`), with a table of the invoices (number, date, due date, amount outstanding), the fee and the
deadline; totals = the open amounts plus the fee. Reminders are finalised and sent like other documents (`draft ->
issued -> sent`) and keep the amounts of their day. Defaults: settings `reminder_fee` and `reminder_deadline_days`.
Since 2.40.0 each level has its own intro and closing (pack texts `reminder_intro_2/3`, `reminder_closing_2/3`; level 3
in a clear tone); the last sum row is "Gesamtbetrag" / "Total amount due". The reminder dialog only hints (no block)
when the fee is above 5 (private clients: only the actual costs) or a chosen invoice is not yet due.

Reminder fee as an open item (2.40.0, decision 2026-10-13: no fees for now; if one is charged, it must not vanish): the
fee of a finalised reminder stays open after its invoices are paid. Reminder answers carry `fee`, `fee_state` (`""` open,
`waived`, `paid`) and `fee_open`; invoice answers carry `fee_open` / `fee_reminders` from the reminders that name them
(invoice and reminder lists show "reminder fee open"). The organisation's admin sets `POST /api/office/docs/<id>/fee
{state: "waived" | "paid" | ""}` (members 403, drafts 409; office log `reminder_fee`). The reminder document itself and
the invoice stay unchanged; the fee does not keep an invoice from being `paid`. A finalised reminder whose invoices are
all paid or cancelled has the derived state `done` ("Settled", `settled: true`, never stored); the list shows settled
reminders below the open ones.

## Progress and final invoices, cash discount (2.120)

**Create invoice** on a quotation asks for the type: full invoice (as before), **progress invoice** or **final invoice**.
Both are ordinary invoices of the invoice number series (`inv_type` `progress` / `final`, no own series); the list and the
document head show the type, the PDF prints "Abschlagsrechnung" / "Schlussrechnung".

- **Progress invoice:** a net amount or a percentage of the quotation's net. The amount is split onto the quotation's VAT
  rates in proportion (one position per rate, "Progress payment no. n on quotation X"). All progress invoices of a
  quotation (drafts included) never exceed its net. E-invoice type code 326 (partial invoice).
- **Final invoice:** all positions of the quotation, then, under a heading, one negative position per finalised, not
  cancelled progress invoice and VAT rate (its net, VAT, gross and whether it is paid in the description). The VAT is
  therefore computed on the remaining amount per rate, which keeps the e-invoice valid (a prepaid amount, BT-113, would
  take off gross without the VAT). The last total row reads "Amount remaining". E-invoice type code 380. Finalising checks
  that the progress invoices are still the ones deducted; a progress invoice cancelled or finalised in the meantime asks
  for the final invoice to be created anew.
- **Cash discount (Skonto):** percent and days per invoice (default in the office settings, empty = none). The PDF adds
  "When paid by <date> <pct> % cash discount (= amount), payable <amount>" under the payment terms; the e-invoice carries
  the XRechnung line `#SKONTO#TAGE=14#PROZENT=2.00#` in the payment terms (BT-20). Payments dated within the period that
  reach the gross less the discount (credit notes count) mark the invoice paid; otherwise the difference stays open.

API: `POST /api/office/docs/<offer id>/invoice` takes `{inv_type: "progress", amount | pct}` or `{inv_type: "final"}`;
`GET /api/office/docs/<offer id>/progress` lists the progress invoices with the quotation's net and what is left to bill;
`PATCH /api/office/docs/<id>` takes `skonto_pct`, `skonto_days`, `inv_type` on invoice drafts; the office settings
`skonto_pct` / `skonto_days`. Agents: `draft_invoice_from_offer` with `inv_type`, `amount`, `pct`.

## Invoice series (2.91)

An invoice can be repeated as a series: in the editor of an invoice choose "Repeat as series", pick the interval (monthly,
quarterly, yearly), the start of the first period of service and an optional start of the last period. On the day of every
period Kalmido makes a new invoice from the template: a normal invoice with the date of that day, the period of service of
the period (`service_from` / `service_to`), the next number when it is finalised and the e-invoice (ZUGFeRD / XRechnung)
like any other invoice. By default it is a draft that waits for you (a task in your inbox links to it, never an amount);
with "Send automatically" it is finalised and mailed to the client's invoice address at once - if a check fails (missing
fields, no address, mail not set up, the send budget) it stays a draft without a number and the task names the reason.
Placeholders in the project title, introduction, closing and positions are filled per period: `{period}`
(01.10.2026 - 31.10.2026), `{month}` (October 2026), `{quarter}` (Q4 2026), `{year}`; unknown braces stay, the template
keeps them. A period starting on the 31st falls on the last day of shorter months. The series are listed above the
invoices ("Invoice series": pause, make now, edit, delete with undo, restore from the deleted ones); an invoice made by a
series shows "From series ..., period ..." and carries `series_id` / `series_period` (one invoice per series and period).
The cash flow shows the expected income of the coming periods as "Invoice series" (kind `series`, planned, due on the
period start plus the template's payment term) until the invoice exists; a draft of the series counts once. A missed
period is made later, of more than three missed periods only the newest. Only admins of the office area (and a person in
their personal office) manage series.

Routes (office admins): `GET /api/office/series` (`?bin=1` the deleted ones), `POST /api/office/series` {template_id, every
monthly | quarterly | yearly, start, until?, auto_send?, title?}, `PATCH /api/office/series/<id>`, `DELETE
/api/office/series/<id>` (into the bin), `POST /api/office/series/<id>/restore`, `POST /api/office/series/<id>/run` (make the
next period now). Table `office_inv_series`.

## Sending and DATEV

`POST /api/office/docs/<id>/send` with `{to, cc?, subject?, text?, datev?}` mails a finalised document with its files
(PDF/A-3, and for invoices and credit notes the e-invoice XML) through the server's SMTP settings (`KALMIDO_SMTP_*`);
the status becomes `sent` and `sent_at` is set. Without SMTP the route answers `409` with a readable reason (the send
dialog says so and offers the PDF download instead). Mails with an own `text` (not the standard text) are limited to 50
per organisation and day (UTC): admins' mails count, admins are not limited; a member past the limit gets `429` and can
still send with the standard text (the daily count reads the index `office_doc_log_action` since 2.40.0).
`GET /api/office/mail-status` tells the client whether mail is set up and which DATEV address is configured; without
mail the send dialog's button downloads the PDF (2.40.0).

PDF in the browser (2.40.0): the editor's PDF button opens `GET /api/office/docs/<id>/pdf?inline=1` in a new tab, the
"Download" button next to it the attachment (`/pdf` without `inline`); "Preview (PDF)" in the menu opens the same inline
PDF (the JSON print model stays at `/render` for the API). In the Android app's WebView, which shows no PDF itself,
the PDF button downloads as before. Archive PDFs of the legacy import open inline, `?download=1` downloads them.

DATEV: the settings hold one e-mail address of the DATEV document inbox (`datev_email`); `datev: true` in the send
body, the setting `datev_auto` or `POST /api/office/docs/<id>/datev` mail the PDF + XML of an invoice or credit note
there (`datev_sent_at`). No credentials; the booking batch export follows below. Every send is
in the office log (`send`, `datev`), payments as `payment` / `payment_delete`.

DATEV booking batch (2.47.3, #1460): `GET /api/office/datev/extf?from=YYYY-MM-DD&to=YYYY-MM-DD` (admin; default the
previous month; `check=1` answers `{count, from, to, file}` only) downloads the finalised invoices, credit notes and the
payments of the period as a DATEV EXTF file (format 700, category 21 "Buchungsstapel", format version 13): header line
with 31 fields, 125 column names, one booking line per tax rate of a document (gross, debtor against the revenue account
of that rate; credit notes H) and per payment (bank or cash account against the debtor, S). Windows-1252, semicolons,
decimal comma, document date DDMM, CRLF; the period must lie within one fiscal year. Settings `datev_extf`:
`advisor_no` (4-7 digits), `client_no` (1-5 digits, both required for the export), `fy_start` (month), `acct_len`
(4-8), `chart` (`SKR03` / `SKR04`, default accounts per case: 8400 / 8300 / 8100 / 8337 / 8338 / 8195 resp. 4400 /
4300 / 4100 / 4337 / 4338 / 4185, collective debtor 10000, bank 1200 / 1800, cash 1000 / 1600, stretched to the ledger
length), `accounts` / `bu` (own account / tax key per case `standard`, `reduced`, `exempt`, `reverse`, `abroad`,
`small`), `debtor`, `bank`, `cash`. A client's customer number is its debtor when it is a debtor number (digits, ledger
length + 1, first digit 1-6); 2.81.0 (#1867): a finalised document uses the customer number of its snapshot (the client
at finalising), the live client only when the snapshot has none. Documents without VAT go by their VAT note (reverse charge, abroad, small business; small
business never with a tax key). Foreign currency documents are booked in EUR by the document's rate. The export is in
the office log (`export`, target `datev`).

Receipts and travel expenses in the batch (2.120.0, #2090): with `in_on` (default on; the download dialog can leave it
out, `?in=0`) the same batch also books the input side, Belegfeld 1 stays unique (`B<receipt>`, `R<trip>-<receipt>`,
`V<trip>`). Every receipt of the office's documents with an amount (by its document date) is one line: expense account
of its category (own assignment `cat_accounts` {category: account}, else a default per chart found by words in the
category, e.g. software 4964 / 6837, office supplies 4930 / 6815, phone 4920 / 6805, else other expenses 4900 / 6300 or
`in_other`) against the collective creditor (`creditor`, default 70000) or, with `in_counter: "bank"`, the bank account;
input tax key 9 for 19 % and 8 for 7 % (`bu_in`), none for 0 %, an unknown rate or a small business. Every travel
receipt is one line on the travel account of its category and the per diem of a trip one line on its last day, both
without input tax (`travel` {fares, hotel, vma, other}; defaults for an organisation 4663 / 4666 / 4664 / 4660 resp.
6663 / 6660 / 6664 / 6650, for a personal office the owner's accounts 4673 / 4676 / 4674 / 4676 resp. 6673 / 6680 /
6674 / 6680). `check=1` also answers `hints`: receipts without an amount (not exported), without a category (booked on
the other expenses account), without a VAT rate (booked without input tax). `GET /api/office/datev/accounts` (admin)
lists the receipt categories with their default and own account and the travel accounts for the settings page.

Settings for all of this (`PUT /api/office/settings`): `invoice_scheme`, `credit_scheme`, `reminder_scheme`,
`payment_days` (14), `reminder_fee` (0), `reminder_deadline_days` (10), `einvoice_format`, `datev_email`, `datev_auto`,
`invoice_closing_de/en`, `reminder_text_de/en` (empty = the country pack's texts).

### Rules the server enforces (2.38.0)

- Finalising an invoice or credit note: the date must not lie in the future and not before the last finalised document of
  the same series (organisation, kind, counter year); `due_date` must not lie before `date` (400 with the reason).
- A duplicate of a credit note or reminder is a fresh document: `cancels_id`, `ref_doc_ids` and `source_doc_id` are not
  copied. The finalised credit notes against one invoice may not exceed its gross (409).
- Payments: only on finalised, open invoices (409 on paid or cancelled), never above the open amount (409), never dated in
  the future (400); checked and booked under a lock per invoice. An invoice with booked payments cannot be set back from
  `paid` by hand (409).
- Reminders: all invoices of one client in one currency, finalised or sent, with an open amount (400 otherwise).
- Sending: the DATEV address and the mail server are checked before the mail to the recipient goes out; the recipient's
  mail is booked first, the DATEV copy afterwards, and a failing DATEV copy answers 409 without undoing the first (repeat
  it with `POST .../datev`). Line breaks in the subject become spaces (subject 200 characters, text 5000); a refusing
  mail server answers 409 with a generic reason, details stay in the server log.
- A finalised document whose stored PDF or XML is missing answers 409 (logged as `store_missing`) instead of being
  rendered again from the snapshot; drafts are always rendered.

## Company fields

Settings > Company holds the company as single fields: name, street, postcode, city, country (ISO code), e-mail, phone,
tax number, VAT ID, bank, IBAN (check digits are verified), BIC, register court, register number, managing directors
(table `office_company`, key `company_fields` of `GET/PUT /api/office/settings`). The printed lines are made from them
group by group (address, contact, register, bank and tax); the free lines of the settings stay as the fallback for a group
whose fields are empty, so existing setups print as before. Clients (module "Clients") have folded "Billing details":
street, postcode, city, country, VAT ID, customer number, buyer reference (for example a routing ID), e-mail for
invoices and payment terms in days; the free address stays. These fields are for people only and are not part of agent
answers.

## Approval by the customer (2.50.0)

A sent quotation gets an **approval link** (block *Approval by the customer* in the editor, members of the organisation):
`POST /api/office/docs/<id>/signoff` `{expires?: YYYY-MM-DD}` (`409` unless the quotation is sent; a new link stops the
older one), `GET /api/office/docs/<id>/signoffs` (newest first, with the protocol), `POST /api/office/signoffs/<sid>/revoke`.
The customer opens `/s/q/<token>` without an account: the quotation as a summary (positions, totals) and as PDF, types a
name (e-mail optional), ticks *I accept the quotation* and presses *Accept bindingly*, or declines with an optional
reason. Stored in `office_signoffs` and in the office log (`signoff_accepted` / `signoff_declined` with the detail): name,
e-mail, time (UTC), client address, user agent and the SHA-256 of the quotation's printed content when the link was
made (`doc_hash`). The quotation is set to accepted / declined through the same code as the status change in the app
(`odoc_set_status`: purchase, sales pipeline). Afterwards the link shows only the confirmation; a second decision is
impossible. A quotation that changes after the link was made voids the link. The person who made the link gets a push
(notification switch *Approval requests*). Token: 256 bits, looked up by its SHA-256 (a sealed copy lets the creator copy
it again); unknown, expired, stopped and voided links get the same `404`; decisions are limited per client address and
per link; the form carries a check value bound to the link. Name, e-mail, reason, address and user agent are encrypted at
rest in organisations with encryption.

**The accepted PDF** (2.99.0): once the customer accepts, the quotation's PDF shows a box *Accepted online by <name>*, the
time (UTC) and the SHA-256 of the accepted content (`doc_hash`) instead of the empty *Order confirmation* lines. The
accepted version is written right after the acceptance as its own file next to the original
(`doc<id>-<number>.accepted-<signoff id>.pdf` below the organisation's office folder, sealed like the original); the stored
original of a finalised quotation is never changed. The customer's download `/s/q/<token>/pdf` and the app's
`GET /api/office/docs/<id>/pdf` serve the accepted version while the quotation's content is still the accepted one;
`?original=1` returns the original as sent. Open and declined quotations keep the original.

This is a **simple electronic signature**: usually enough to accept a quotation or confirm an acceptance; not for contracts
that the law requires in written form (they need a qualified signature). Kalmido gives no legal advice and builds no
advanced or qualified signature. The same flow confirms the **acceptance** of a project, a section or a milestone from the
list's Share dialog > Public link (*Request acceptance*); the customer's list page shows the open request.
2.99.1: a **video sign-off** (kind `video`, see [TEAM.md](TEAM.md) *Video sign-off*) uses the same link: the page shows the
newest version's player and the customer's comments at a timecode (`POST /s/q/<token>/comments`, limited per client address
and per link, a form check value of its own) and *Approve* / *Request changes*; the decision names the version shown.

## Documents in the customer portal (2.120.0)

*Settings > Invoices > Show documents in the customer portal* (off by default) lets clients see their sent quotations,
invoices with the payment state and credit notes in the customer portal; *Send portal link* in the client's menu mails them
the sign-in link. Details: [TEAM.md](TEAM.md) *The customer portal*.

## Documents from templates (2.93.0)

Tab *Documents* (admins of the office area; members `403`, agents `403`, another area `404`; a person without an
organisation uses it in the personal office). Two parts: **templates** and the **documents** made from them. The task
templates of the lists are something else and stay as they are.

**Templates** (`office_doc_templates`): kind (contract, order confirmation, non-disclosure agreement, other), name,
language (de / en), text and *Documents from it can be signed by the customer*. The text is plain: a line starting with
`#` is a heading (`##` a smaller one), `-` a list item, an empty line starts a new paragraph. Variables are written as
`{{name}}` and inserted with the button bar: `{{client.name}}`, `{{client.address}}`, `{{client.contact}}`,
`{{project.title}}`, `{{offer.number}}`, `{{offer.date}}`, `{{offer.total}}`, `{{company.name}}`, `{{company.address}}`,
`{{today}}`. They are replaced by a plain text search, never evaluated; an unknown name stays as it is in the preview
(marked) and is left empty in the PDF. *Use sample* (also *Start from a sample* in the new template dialog) takes over
one of ten short samples in the office's document language (or the other one) as an own, freely editable template of
the current area (organisation or private): service agreement, order confirmation, non-disclosure agreement, cover
letter, payment reminder, dunning letter, notice of termination, power of attorney, handover record and credit note
cover letter. What no variable knows (an invoice number, a deadline) stays as `[placeholder]` in square brackets.
Samples are sample text, no legal advice; the picker marks the legal ones (contracts, dunning, termination, power of
attorney) to be checked before use. The samples live in the code (`kalmido/office/doctpl_samples.py`), never in the
database.

**Documents** (`office_gen_docs`): made from a template for a client (required), optionally a project list (one the
admin sees, of the same office area) and a quotation of the same client. A draft keeps the text with its variables; the
preview fills them from the current client (name, address from the billing fields, default contact person), project,
quotation (number, date, total incl. VAT) and company. *Finish* fills the variables for good, freezes the text
(`body_hash` = SHA-256 of it) and files the PDF (letterhead and logo like a quotation) into the office documents space,
in a folder named after the client. A finished document never changes: *Edit a copy* starts a new draft with its text.
Archive instead of delete (undo restores). The client page lists the client's documents; the documents list filters by
client, project and status. In a quotation's menu, *Create order confirmation* opens the dialog with client and quotation
set.

**Signature by the customer**: a finished document that may be signed gets a link (`office_signoffs`, kind `document`,
the same rules as the approval of a quotation: 256-bit token, one live link per document, optional expiry, rate limits,
form check value, the same `404` for unknown, expired, stopped and voided links). The customer page `/s/q/<token>` shows
the text (escaped, no scripts), its SHA-256 and the PDF; the customer types a name, ticks *I sign this document* and signs
or declines with an optional reason. Afterwards the document is *Signed* / *Declined*, the person who made the link gets
a push (*Approval requests*), the office log has the decision, and the signed PDF (the original plus a block with name,
time in UTC, the SHA-256 of the text and *Simple electronic signature*) is filed next to the original when an admin opens
the documents next. Archiving a document or changing its text stops its link. This is a simple electronic signature:
not for contracts that the law requires in written form.

Routes (office admins only): `GET/POST /api/office/doc-templates` (`{starter: contract|confirmation|nda|letter|reminder|dunning|termination|authority|handover|credit, lang?}` takes over
a sample), `GET /api/office/doc-templates/starters?lang=`, `PATCH/DELETE /api/office/doc-templates/<id>`,
`POST /api/office/doc-templates/<id>/restore`, `GET/POST /api/office/gen-docs` (`?client_id=&list_id=&status=&archived=1`;
`{copy_of: id}` = edit a copy), `GET/PATCH/DELETE /api/office/gen-docs/<id>` (`PATCH` of a finished document `409`),
`POST /api/office/gen-docs/<id>/restore`, `POST /api/office/gen-docs/preview`, `POST /api/office/gen-docs/<id>/final`,
`GET /api/office/gen-docs/<id>/pdf` (`?signed=1`), `POST /api/office/gen-docs/<id>/signoff`,
`GET /api/office/gen-docs/<id>/signoffs`; a link is stopped with `POST /api/office/signoffs/<sid>/revoke`. Template and
document texts are encrypted at rest in organisations with encryption.

## Delivery notes and the timesheet (2.120.0)

- **Delivery note / proof of service** (document kind `delivery`, tab "Delivery notes"): made from a quotation or an invoice
  (`POST /api/office/docs/<id>/delivery`, positions without prices, discounts left out) or empty. Own number series
  (`delivery_scheme`, default `LS-{yyyy}-{seq:03}`, set at finalising). `delivery_title` picks the title: "" = Lieferschein,
  `service` = Leistungsnachweis. The PDF shows no prices, sums, tax or payment details and ends with the box "received /
  accepted" (place, date, signature). It has no e-invoice, no payment state and is not counted in revenue, cash flow, DATEV or
  reminders. Finalising needs a recipient (with address) and one position; sending works like other documents.
- **Timesheet of an invoice** (`GET /api/office/docs/<id>/timesheet.pdf`, `?inline=1`): for an invoice with a client and a
  period of service, the time entries of the client's lists in that period (date, person, activity, hours per list, total),
  rounded like the time report. Only entries the signed-in person may see in the time report; made on demand, never stored.
  `POST .../send` takes `timesheet: true` to attach it as a second file (the invoice's own PDF / ZUGFeRD file is unchanged;
  the DATEV copy never gets it). The document answer has `timesheet_ok`.

## Access log

Every change and every read of documents and master data is written to the office log (`office_doc_log`): who, when,
what (create, change with the values before and after, positions, number, status, finalise, duplicate, delete, open,
PDF, preview, export, import, logo) and on which document or master data. Repeated reads of the same person within ten
minutes are written once. Organisation admins see the history of a document in its editor ("History") and the latest
entries under Settings > Access log. The log is never part of alerts. An agent token on `/api/office/*` gets `403` without
content; every request of an agent on `/api/v1/office` is one line in the log (2.51.0).

## Agents (2.51.0)

An agent prepares, a person decides. Three things must be on (all off by default): the token's scope `office`, the
agent's switch **May draft office documents** (its settings dialog; an admin of its office area sets it, in a personal
office the person) and the area's privacy switch **Agents may read office data** (Settings > Agents, admins; the hint
says that client and price data go to the agent's AI model). Then the agent may read services (never purchase prices),
text blocks, framework contracts, clients and the area's documents, and create:

- **quotation drafts** (no number; positions from the services, free positions, other prices and discounts are marked in
  the accent colour with a text until a person changes the position or presses *Confirm*; *Drafted by the agent ...*);
- **invoice drafts** from accepted quotations (the same as *Create invoice*), **reminder drafts** over open invoices;
- **payment suggestions** for open invoices (Kalmido has no bank access; the agent reads them from what a person gave
  it): *Suggested payments* above the invoice list, an admin books or rejects each one.

It never reserves a number, finalises, sends, changes a status, deletes or books. Its area is its workspace's office (a
personal agent without a workspace: its owner's personal office), it acts for one person of that office (`requested_by`)
and never sees another area. Each request is one line in the access log (filter *Agents*). Details: docs/AGENTS.md.
People's routes: `GET/PATCH /api/office/agents/<id>` (the switch), `GET /api/office/pay-props`, `POST /api/office/pay-props/<id>`
`{action: accept|reject}` (admins). The event `offer_accepted` tells the area's office agents about an accepted quotation.

## PDF layout

`GET /api/office/docs/<id>/pdf` returns the quotation as a PDF file (`?inline=1` opens it in the browser instead of
downloading; the file name is the document number). The PDF is written by `kalmido/office/pdf.py` without any PDF
library: PDF 1.4, real A4 pages, the base-14 fonts Helvetica / Helvetica-Bold (WinAnsi encoding, so umlauts, the sharp
s and the euro sign print), text wrapped with the fonts' width tables, the logo embedded as an RGB image. Input is the
print model of `GET /api/office/docs/<id>/render`, so the PDF and the preview show the same texts and figures in the
document's language (labels from the country pack, not from the signed-in person's app language).

Layout (DIN 5008 form B, the usual German business letter):

- Letterhead: the logo top right (or the company name when there is none), fold and punch marks at the left edge.
- Address field in the window area of a DL envelope with the sender line above it; the key data on the right (number,
  date, client, reference, valid until, custom fields of the document).
- Title, project title, intro text; the table of positions (No., service, quantity with unit, unit price, VAT rate,
  total) with category headings and free text blocks between positions; producing and discount lines like positions.
- Totals block: net total, "including raw data" (raw data optional) or "excluding raw data" (raw data included via a
  framework contract), the VAT note of the pack (quotations show the note, not the tax lines), the exchange rate note
  for USD, the validity note.
- The raw data option as three rows of the totals (since 2.114.5: net total, "+ Optional: <name>", net total with the
  option), the transfer of rights as its own section (duration,
  territory, media, exceptions, exclusivity, note), closing text, greeting with the signer's name, an order confirmation
  area (place / date, signature) and a footer in up to four columns (company, contact, registration, bank; empty
  columns are left out; since 2.114.5 at most three lines each: the address on one line, the two shortest lines of a
  column joined with " · ", the font shrinks a little before a line breaks). Since 2.114.5 page 1 is tighter: one VAT
  rate in all positions -> no VAT column (the note names that rate), no validity sentence below the table (the head has
  "Valid until"), a smaller logo, a closer greeting; with a rights appendix or printed parts the order confirmation
  area stands at the very end (behind the appendix) and page 1 says "Order confirmation by signature on page n". Since 2.114.4 the order confirmation area can be switched off: the office setting `accept_on`
  (default on) and per quotation `accept_on` (empty = like the setting, 1 = on, 0 = off, "Order confirmation with
  signature line" in the texts section of the editor); a finalised quotation keeps the value it was finalised with. The company colour is the only accent (rules, title underline, category headings).
- Page breaks: following pages carry a small head (logo, title, number, recipient) and repeat the table head; from
  two pages on the footer says "Page x of y" (a one-page PDF has no page line); a category heading never stays alone at the end of a page, text blocks and the rights block
  are not torn, and the totals never stand alone on a page (the last position comes along). No carry-over lines.

Logo: `POST /api/office/logo` (organisation admin, multipart `file`) accepts PNG, JPEG or WebP up to 4 MB, scales it to
at most 1600 px width and stores it as PNG below `<data>/office/<org_id>/logo.png`; `GET /api/office/logo` serves it,
`DELETE /api/office/logo` removes it. For a sharp print upload a PNG at least 600 px wide; SVG is not accepted (the PDF
writer has no SVG renderer). The folder is part of the backups and restores like the attachments. Internal figures
(costs, margin) are never printed.

### Own letterhead (2.120)

Settings -> Letterhead takes a PDF that goes behind every quotation, invoice, credit note, reminder and every later
document kind: its page 1 behind the first page, its page 2 behind the following pages (a one-page PDF goes behind all
of them). A4 portrait, up to 10 MB. The pages are copied into the document as they are (vector graphics, pictures and
the letterhead's own fonts), so the print stays sharp. A PDF that cannot be read safely (password protected, an unknown
compression, rotated or landscape pages) is refused at the upload with a short message; a document is never printed
from a half read letterhead.

- Margins in mm for page 1 and for the following pages (top, right, bottom, left). On page 1 "top" is where the address
  field begins (DIN 5008: 45 mm). The defaults are the normal layout. The text column takes the narrower of the two pages.
- "Leave out our own head" drops the logo / company name and the fold marks; "Leave out our own footer" drops the footer
  columns (number and page stay, below the text). Both are on after an upload, because a letterhead usually has them.
- "Preview" shows a two-page sample invoice with the letterhead. Every change is saved at once and can be undone in the
  message that follows; removing the letterhead can be undone the same way (the previous file is kept for that one step,
  older ones are deleted).
- Finalising freezes the letterhead with the sender (a copy `lhs-<hash>.pdf`), so a finalised document looks the same
  later; documents finalised before stay as they were. The e-invoice XML inside a ZUGFeRD PDF and the PDF/A metadata
  stay as they are. Without a letterhead the PDF is exactly the one of before.
- Organisation admins (and a person without organisation in the personal office) upload and change it; members see the
  state and the preview. The file is stored sealed like the documents below `<data>/office/<org_id>/`.

Routes: `GET / POST / PUT / DELETE /api/office/letterhead` (state, multipart `file`, `{m1, m2, hide_head, hide_footer}`
with `m1` / `m2` = `[top, right, bottom, left]` in mm, removal), `POST /api/office/letterhead/restore` (`{file}`: the
previous file again, the undo) and `GET /api/office/letterhead/preview` (the sample as PDF).

## Database

New tables, all additive and keyed by `org_id` with `ON DELETE CASCADE`: `office_settings`, `office_services`,
`office_equipment`, `office_sets`, `office_texts`, `office_contracts`, `office_numbers`, `office_docs`,
`office_doc_items`. A backup (Settings > Administration > Backup) contains them; an older release runs on with them.
Since 2.36.2 also `office_company` and `office_doc_log`, the columns `locked_at`, `locked_by`, `sender`,
`recipient_snapshot`, `tax_snapshot`, `pack_version`, `service_from`, `service_to` of `office_docs`, `org_id`,
`tax_pct`, `net`, `tax_amount` of `office_doc_items` (positions written without `org_id` get it at the next start) and
the billing columns of `clients` - all nullable or with a default, so the previous release runs on with them.
Unfinished logo uploads (`*.tmp`) are not part of backups.
Since 2.37.0 (PostgreSQL) amounts, rates and quantities are `NUMERIC(14,4)` (exact decimals; read back as numbers as
before), and every `office_*` table is under row-level security by `org_id`: a request only ever gets rows of its own
organisations, even if a route forgot a check.
Since 2.38.0 also `office_payments` (`org_id`, `doc_id`, `date`, `amount NUMERIC`, `method`, `note`, `created_by`,
`created_at`; under row-level security as well) and the nullable columns `order_ref`, `due_date`, `payment_days`,
`cancels_id`, `ref_doc_ids`, `reminder_level`, `reminder_fee`, `reminder_deadline_days`, `paid_at`, `source_doc_id`,
`einvoice_format`, `pdf_sha256`, `xml_sha256`, `datev_sent_at`, `vat_note` of `office_docs`; 2.37.1 runs on with them.
Since 2.39.1 also `office_import_runs` and `office_archive` (both under row-level security) and the nullable column
`import_run_id` of `clients`, `office_services` and `office_equipment`; 2.39.0 runs on with them.
Since 2.42.0 the sensitive values are encrypted at rest with a key per organisation when the server has
`KALMIDO_SECRET_KEY` (see SELF-HOSTING.md, *Encryption of organisation data*): in `office_company` the tax number, VAT ID,
IBAN, BIC and bank; the key `company` of `office_settings.data`; `office_contracts.rates`; `office_docs.sender` and the
keys `costs` / `margin` of `office_docs.totals`; office log entries with such values; purchase prices move from
`office_doc_items.cost` (then 0) to the new nullable column `cost_enc`. Stored invoice PDFs / XML and archived PDFs are
sealed on disk and served as the originals (same SHA-256 as recorded). The API answers in plain as before. Before going
back to an older release run `python -m kalmido.admin.orgcrypt_cli decrypt-all`.
Since 2.45.1 also the column `name_en` of `office_equipment` (text, default empty); 2.45.0 runs on with it.
Since 2.50.0 also `office_deals` (the sales pipeline; under row-level security, `value`, `contact`, `note` and
`lost_reason` encrypted at rest, `deleted_at` = deleted and restorable); 2.49.0 runs on with it.
Since 2.90.0 also `office_bank_imports` and `office_bank_tx` (the bank reconciliation; under row-level security,
`amount`, `counterpart`, `purpose` and `iban` encrypted at rest, `deleted_at` = taken back and restorable) and the nullable
columns `vat_pct` and `paid_at` of `rc_receipts` (VAT rate and payment day of a receipt); 2.87.0 runs on with them.
Since 2.93.0 also `office_doc_templates` and `office_gen_docs` (document templates and the documents made from them; the
texts encrypted at rest, archived = removed and restorable), the column `gen_doc_id` of `office_signoffs` (a signature
link of such a document), and `office_vehicles`, `office_drives` and `office_drive_log` (the logbook; under row-level security, the
plate, start / destination / purpose and the logged values encrypted at rest, `deleted_at` = deleted and restorable) and
the settings keys `km_rate` / `km_rates` (rate per year); 2.92 runs on with them.
Since 2.120.0 also the columns `inv_type` (text, default empty), `abs_refs` (text, default `[]`), `skonto_pct` and
`skonto_days` (nullable) of `office_docs` and the settings keys `skonto_pct` / `skonto_days`; 2.117 runs on with them.

## E-invoices (ZUGFeRD / XRechnung) and PDF/A-3

Since 2.38.0 every document PDF is a PDF/A-3b file (PDF 1.7): the fonts Liberation Sans Regular / Bold are embedded
(`kalmido/office/fonts/`, SIL OFL), the file carries XMP metadata (`pdfaid` part 3 / conformance B, title, author, dates
consistent with the Info dictionary), an sRGB output intent with the embedded ICC profile (`sRGB2014.icc`), a file
identifier and no encryption or scripts. The writer is still `kalmido/office/pdf.py` without any PDF library.

A finalised invoice or credit note also gets its e-invoice XML (`kalmido/office/einvoice.py`): UN/CEFACT Cross Industry
Invoice (CII D16B) in the EN 16931 profile, built from the document's snapshot only (sender fields, recipient billing
fields, positions with their rates, the frozen totals as decimal strings, period of service, due date, order reference,
IBAN / BIC, the VAT note). Two formats, chosen per document (`einvoice_format`) with the organisation's setting as the
default:

- `zugferd` (default): ZUGFeRD 2.x / Factur-X profile EN 16931 -- the XML is embedded in the PDF as `factur-x.xml`
  (associated file, relationship Alternative, the `fx:` XMP schema with its extension description), so the PDF alone is
  the e-invoice. The XML is stored and downloadable as well.
- `xrechnung`: XRechnung 3.0 (the German public sector CIUS) -- the XML is the e-invoice, the PDF stays a plain PDF/A-3
  without an embedded file. XRechnung needs the client's buyer reference (routing id, billing details of the client);
  without it, finalising answers `400` with the reason. The seller contact (phone and e-mail of the company) and the
  electronic addresses (seller e-mail, the client's invoice e-mail) are part of it.

Buyer address without client data (only free address lines, 2.40.0): the last line with a postcode ("12345 Town",
"1010 Wien", "CH-8000 Zürich") gives postcode and city, the line before it the street (LineOne), the lines before that
LineTwo / LineThree (attention, department). Without a postcode line (e.g. UK) the last line is the city.

Tax categories follow the document: `S` for taxed documents (one breakdown per rate, the tax of a rate computed from the
rounded base), `AE` (reverse charge), `G` (export) or `E` (exempt / small business) by the VAT note of a document without
VAT, with the exemption reason text. A foreign currency gives the invoice currency (BT-5), the tax currency EUR (BT-6)
and the tax in EUR (BT-111) from the document's exchange rate. A credit note is type 381 with positive amounts and the
cancelled invoice in BT-25. A discount line is written as a positive price with a negative quantity (the net price is
never negative). The amounts are decimal strings throughout; `ein_check()` (the module's own plausibility check: mandatory
terms, the sum rules BR-CO-10/13/14/15/16/17) is used by the tests without a validator.

Finalising an invoice, credit note or reminder stores the files: `<data>/office/<org_id>/doc<id>-<kind>-<number>.pdf` and `.xml` (flat below the
organisation's office folder, so they are part of the backups and come back with a restore like the logo), with both
SHA-256 in the document (`pdf_sha256`, `xml_sha256`, also in the API) and an access-log entry `store`. From then on
`GET /api/office/docs/<id>/pdf` serves the stored file (bytes identical for ever, whatever changes later), and
`GET /api/office/docs/<id>/xml` the stored XML (file name `<kind>-<number>.xml`; `409` for drafts and for quotations /
reminders). A draft invoice, credit note or reminder is rendered on request with a light "Draft" mark. The mail dispatch
attaches the stored files (PDF, and the XML for invoices / credit notes). A finalised quotation is not stored; its PDF is
rendered from the snapshot on every request.

## Validators

Two real validators run in CI (job "E-invoice validators", blocking) on the files `tests/office_einvoice_test.py` writes
to `tests/.data/einvoice/`: veraPDF (PDF/A-3b, Docker image `ghcr.io/verapdf/cli`) for the PDFs and the KoSIT validator
(Java 17, the release jar plus the XRechnung scenario configuration, both downloaded once with their SHA-256 checked and
cached) for the XML -- the configuration validates XRechnung files against the XRechnung rules and plain EN 16931 files
against the EN 16931 Schematron. Locally:

```
python3 tests/office_einvoice_test.py
tools/einvoice_validate.sh tests/.data/einvoice/*.pdf tests/.data/einvoice/*.xml
```

The script needs Docker (veraPDF) and Java 17 or newer (KoSIT); it keeps the downloads in `~/.cache/kalmido-validators`
(`KALMIDO_VALIDATOR_CACHE`) and writes the KoSIT reports to `reports/` there. Any file of your own installation can be
checked the same way (download the PDF / XML of a finalised invoice and pass it to the script).

More national e-invoice formats are welcome as pull requests with an official validator run in CI; see
[CONTRIBUTING.md](../CONTRIBUTING.md), *Contributing national e-invoice formats*.
