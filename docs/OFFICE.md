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

## Personal office

*Since 2.47.3.*

Every person has a personal office: own master data (services, equipment, text blocks, framework contracts, freelancer
roles, crew), own number series, settings, company fields, logo, quotations, invoices, payments and archive. The person
is its admin (module settings, logo, import, delete, purchase prices and surplus). Its clients are the person's private
clients (the clients without an organisation, which the workspace "Private" shows). The access log, e-invoices, the
DATEV document inbox and sending by mail work as in an organisation's office.

It is created on the first visit, invisible to everybody else - also to the server's admins: it never appears as an
organisation (projects of organisations, workspaces, sharing, agents, organisation export). Technically it is a hidden row
of the organisation table (`orgs.personal_of` = its owner) without members; row-level security lets only its owner reach
its rows, and it has its own encryption key like an organisation.
Going back to a version before 2.47.3 keeps working, but such a version does not know these rows and lists them as
organisations named `private-<id>` without members (admin dialog). Leave them alone there: do not add members, rename or
delete them - members added there would reach the personal office.

A person in an organisation who opens "Private" for the first time finds an empty personal office with a hint and a
button to the organisation's office.

**Moving into a new organisation** (Settings > Data, section "Transfer into an organisation", button "Transfer into a new organisation…"; one way, after a confirmation): the personal
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
  stay with their text; entertainment receipts (2.119) move while they are drafts, with their restaurant bill (sealed anew
  for the target) and their approval log; a host or guest who is no person of the target stays as a free name, approved
  receipts stay (retention);
- framework contracts (2.119.1, in the contract's dialog) move with their PDF files, sealed with the target's key; the
  rights text blocks they name are copied into the target, their client stays behind, drafts pointing at them lose the
  link. A contract that issued documents still point to stays archived in the old office and is created anew in the
  target with copies of its files;
- **issued documents never move** (retention): invoices, credit notes, reminders, sent quotations, number ranges and the
  archive stay where they were issued. A client that issued documents (or projects, trips, deals) still point to stays
  archived in the old office and is created anew in the target. The tick box *Take issued documents along as a read-only
  copy* files a copy of each of them into the target's archive: view and PDF only, no number of its own, never edited,
  and not part of the target's bookkeeping, EÜR, VAT, DATEV export or archive sums (marked "Read-only copy from …").
Rights: the right to work in both offices (travel expenses, templates and framework contracts: the admin of both); out of an organisation only
its office admin or who created the client / draft - a plain member takes only own drafts along and no copies. Agents
never move office data. Undo takes the whole move back in one step (copies and a newly created client go again, unless the
target has used that client since). `POST /api/office/move-space` `{what: clients|drafts|travel|templates|meals|contracts, ids, to:
"private"|"org:<id>", dry, copy_issued}` -> `{notes, block, count, move_id}`; `{undo: move_id}` takes it back.

**The whole personal office into an organisation** (2.139.1): Settings of the office, *Transfer into an organisation*, offered
when you are an admin of at least one organisation. The preview names what goes along (documents, payments, clients with
their contact persons, master data, cash book, travel expenses, files ...), what stays in the personal office (its settings,
company and bank data, your number counters, the start and real balances of the cash flow; the organisation keeps its own)
and who sees it afterwards (every member of the organisation with access to the office). Every entry keeps its id;
finalised invoices stay finalised with their numbers, closed cash book days stay closed; the protected fields and the
stored files are sealed anew with the organisation's key. A number the organisation already uses refuses the transfer
(the preview lists them; numbers are never rewritten). One way, no undo. Only the person in the app, never an agent or an
access token. `GET /api/office/move/check?org=<id>` -> `{org, ok, moves, keeps, notes, conflicts, numbers, who}`;
`POST /api/office/move/org` `{org, confirm: true}` -> `{ok, org_id, name, clients, files, rows}` (404 not a member, 403 not
its admin, 409 conflicts / not a personal office / nothing to move).

**Small business (section 19 UStG)**: the setting `small_business` (Settings tab, "Invoices"; a setting of every office
area, also of an organisation): new quotations and invoices are made without VAT and with the note "Gemäß § 19 UStG
wird keine Umsatzsteuer berechnet." (`vat_mode` `novat`, `vat_note` `small`); the e-invoice gets the tax category `E`
with this exemption reason.

## The office menu (a rail on the left since 2.98.0)

*Since 2.87.9.*

The area Office (office, clients, contacts) has one menu with three groups instead of tab rows:

- **Sell** - Pipeline, Quotes & invoices, Clients, Contacts, Documents, Framework contracts
- **Money** - Receipts (2.276), Cash flow, Figures, Bank, Bookkeeping, Cash book (2.121), Subscriptions & tools, Travel expenses, Entertainment receipts
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

*Since 2.276.0 (#3039):* the office is quieter on the first day. Without a point kept on this device it opens on
**Quotes & invoices** for everybody; the Pipeline becomes the start only once the office has an inquiry or a lead. The
group **Money** stays folded until the office holds its first invoice or receipt (a fold or unfold by hand is kept per
device). Cash flow, Figures, Travel expenses, Entertainment receipts and Subscriptions & tools appear once there is
something in them; until then **Show more** at the end of Money lists them (and keeps them shown on this device), a
direct link or a point opened once keeps working. The signal is `used` in `GET /api/office/settings` (existence checks
only: invoice, receipt, inquiry, meal, travel, sub, fixed). The new point **Receipts** (`#office/receipts`, for everybody
with the bookkeeping) holds the upload (*Photograph receipt*, *Upload files*), the receipts list and links to
entertainment receipts and travel expenses; the upload on Bookkeeping stays. The uploaded file is stored in the file
store folder "Documents" of the office and listed under Office > Receipts.

## Settings: areas, every field saves itself

*Since 2.113.*

Office & finance > Settings > General shows its fields in six **areas**, with the same strip of tabs as
Settings > Administration: **Company** (company data, logo, brand colour, master data file), **Documents** (documents,
invoices, invoice from parts, closing texts, calculation rules, default texts), **Packs** (country pack, packs list),
**Functions** (the functions of the country pack, 2.147, see below), **Data** (DATEV inbox and booking export, legacy import, moving a personal office into an organisation) and **Access**
(agents' read access, access log). Only one area is shown; the last one chosen is remembered on the device. On a phone the
strip scrolls sideways.

There is no Save button: each field saves itself when you leave it (a box or a choice at once) and says *Saved* next
to it, with *Undo* (one undo step per field). Only that field goes to the server (`PUT /api/office/settings` with its
key; the company data, the free line groups, one language of the default texts and one part of the default rights each
on their own, the DATEV booking export as one group), so fields of the other areas are never written over. A value the
server refuses stays in the field, marked with the error, until it is corrected; closing the page asks meanwhile.
Members see every field locked.

In the area Packs, every industry pack's card says **Switched on** or **Off** and has its own switch; it changes
`industry_packs` at once, like the box of the same pack in the calculation rules.

<a id="country-pack-functions-and-switches-2147"></a>

## Country pack functions and switches

*Since 2.147.*

The country pack decides which office functions exist at all; the office admin switches single ones off in the area
**Functions** (one switch each, saved at once, one undo step; in a personal office its owner is the admin).

| Function | Key | Germany (`DE`) | Base pack (`XX`) |
|---|---|---|---|
| DATEV: booking batch, document inbox, SKR accounts, travel receipts "in DATEV" | `books.datev` | yes | - |
| E-invoice XML on finalising and mailing (ZUGFeRD / Factur-X, XRechnung) | `docs.einvoice` | yes | ZUGFeRD / Factur-X only |
| VAT return figures (advance return; filing stays with your tax software) | `books.vat_return` | yes | - |
| Tax dates as recurring tasks | `books.tax_dates` | yes | - |
| Export for any tax advisor (booking list CSV, ZIP with invoices and receipts) | `books.export_csv` | yes | yes |
| Finalising rules (locked documents, number gaps with a reason, date order) | `books.gobd` | always on | always on |

- **Off only hides.** Nothing is deleted: the DATEV address and booking settings, tax date settings and stored XML files
  stay; switching on again brings everything back. The server checks too: the routes of a function that is off answer
  `404` ("This function is not switched on in this office"), the automatic DATEV copy is skipped, a newly finalised
  invoice gets no XML (an XML stored before stays reachable).
- **Always in force**, whatever the switches say: finalised documents stay locked with their snapshot, and receipts are
  kept for the retention period of the pack (`DE`: receipts 8 years, books 10 years).
- Settings keys: `features_off` (list of switched off keys; empty = everything the pack offers is on, so offices from
  before 2.147 stay exactly as they were), `GET /api/office/settings` answers `features` (`{key: true|false}`) and
  `pack.offers`, `pack.retention`, `pack.einvoice_formats`. Agents read the same in `GET /api/v1/office` (`country_pack`,
  `features`) and leave out what is off.

**Choosing the country.** A new office area (no saved settings, no documents) shows its admin the question *Where is your
office?* on top of the office, with a suggestion (the company's country when a pack exists for it, otherwise the
international base pack; without a company country the language: German -> `DE`). Offices from before never see it and
stay `DE`. **Changing** the country under Settings > Packs asks first and says what changes (`GET /api/office/pack-switch?code=XX`:
hidden / new functions, open documents recalculated with the new rates and texts, finalised documents that keep their
state). `DE -> XX -> DE` loses nothing.

**International base pack (`XX`).** For countries without an own pack: no country assumptions in the texts, the VAT
rates are set by the office (`tax_rates: {standard, reduced}`, labels like "21 % VAT"; empty = 20 / 10), the retention
is set by the office (`retention_years`, default 10), e-invoices as EN 16931 ZUGFeRD / Factur-X (an XRechnung setting
becomes ZUGFeRD), and the company country is needed before an invoice is finalised. Home currency: chosen by the
office (2.189, see *Home currency*).

**Home currency (2.189).** Every office has one home currency (ISO 4217, `home_currency` in the settings): the currency
of its price list, books, cash flow, key figures, travel expenses, bank reconciliation and exports, and the currency the
tax of a foreign currency document is also shown in. A country pack fixes it (`DE`: always EUR - nothing changes for
German offices); a pack with `"currency_editable": true` (the base pack `XX`) lets the admin choose it from the list in
`pack.currencies` (currencies with two decimal places). The choice is possible only as long as the office has no
bookings - no finalised invoice or credit note, payment, receipt, travel receipt, bank or cash book entry, opening
balance; after that `home_locked` is true and a change (also a pack switch that would change it) answers 400. An office
from before keeps its currency (EUR, or USD in the base pack). `currency` is the currency of new documents (the home
currency or a foreign one); a foreign currency is converted with an exchange rate = units of the foreign currency per one
unit of the home currency: the office rates `fx_rates` (`{"USD": 1.27}`; a EUR office keeps its USD rate in `fx_usd`)
are the default of a new document, each document keeps its own `fx_rate`. Rates are entered by hand - Kalmido asks no
rate service.

**Export for the tax advisor** (Bookkeeping, `GET /api/office/books/export?from=&to=`, admins only): every finalised
invoice and credit note (one row per tax rate), payments received, receipts and travel expenses of the period in one
list, amounts signed in the office currency; `&zip=1` adds the invoice PDFs / XML (`documents/`) and the receipt files
(`receipts/`); `&check=1` only counts. The CSV follows the pack's number format (decimal comma = semicolon separated).
The receipts are the ones the exporting person sees (a hidden folder stays out); a receipt file found infected (strict
mode: not checked yet) keeps its line in the list without the file (2.306.0).

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
  record purchase, depreciation and insurance values (see [Equipment value](#equipment-value-depreciation-and-insurance-list)).
- **Contracts & insurance** (2.92.0, admins) - business contracts and insurances with notice deadlines, see
  [Contracts and insurance](#contracts-and-insurance).
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
  dates, see below. Since 2.146 the receipt buttons take several files at once (at most 50, also a ZIP or a
  `winmail.dat`); several photos can be merged into one receipt (the pages of a long till receipt become one PDF). A file
  that is already there is not stored again (*This file already exists*, Open shows it); a receipt that looks like the
  same invoice as an older one is marked *Possibly a duplicate of ...* with a link and *No duplicate*. The DATEV export
  leaves such receipts out unless *Include possibly duplicate receipts* is ticked.
- **Bank** (admins, 2.90) - bank reconciliation, see below.
- **Settings** - company name and address lines, contact / register / bank lines (printed in the footer), logo, own letterhead PDF (2.120, see "Own letterhead"),
  brand colour (accent in the print only), document language (de / en), home currency (base pack, 2.189), currency of new documents + rate, number scheme with
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
  (1 when a position counts towards producing, else the default), so their sums stay. Since 2.138.1 a new quotation computes producing only
  through an industry pack that offers "share by amount" (see docs/PACKS.md, calculation options); without such a pack
  new quotations start without producing and the switch, the fields and the marks are hidden. Older quotations keep
  their calculation by quantities / quotient (and show their switch to turn it off). The company data choose the word before the
  management's names in the footer (`md_label`: Geschäftsführung, Gesellschafter, Inhaber, Inhaberin, Vorstand, Partner;
  German or English by the document's language). Unsaved input of these pages survives a change of the view and live
  updates until it is saved or discarded.

## Number scheme

Placeholders: `{yyyy}` `{yy}` year, `{seq}` or `{seq:03}` the counter (zero-padded to the given width), `{project}`,
`{client}`, `{date}` (`yyyymmdd`), `{isodate}` (`yyyy-mm-dd`, 2.138.2), `{initials}`, `{version}` (quotations, see below). Default `KVA-{yyyy}-{seq:03}` -> `KVA-2026-001`.
In `{client}`, `{project}` and `{initials}` spaces and other punctuation become hyphens; letters (umlauts too), digits, `_` and `-`
stay, at most 40 characters: `{client}_{project}_KV{seq:02}_{isodate}_{initials}` -> `DAF_Beteiligung_KV04_2026-04-15_MG`. The counter runs per
organisation, document kind and period: with `{yyyy}` / `{yy}` in the scheme it starts again every year, without it
never. A number is reserved once and never reused. An empty `{project}`, `{client}` or `{initials}` is left out together
with one separator next to it (2.144.9): `{project}-KV{seq:02}-{initials}` without a project gives `KV02-MG`, not
`-KV02-MG`; numbers given before stay as they are.

When the number is assigned depends on the document kind: quotations get it when they are created (as before); the
organisation can switch this to "when it is finalised" (settings key `offer_number_at`: `create` | `finalize`). Then a
draft carries no number ("Draft") and the number is assigned in the moment the document is finalised, so deleted
drafts leave no gaps. Later document kinds (invoices) are always numbered when they are finalised. Numbers are unique per
organisation.

**Quotation counter per client or project** (settings key `offer_counter`: `org` (default) | `client` | `project`):
per client each client counts on its own (a quotation without a client by its recipient's name), per project each
project (its list, else its project title); with a year in the scheme each one starts again at 1 every year. A new
client / project counter continues from the highest running number its existing quotations carry under today's scheme;
existing numbers stay as they are. A quotation counted this way gets its number once its client / project is set (at the
latest when it is finalised, then from the organisation's counter). Invoices, credit notes and reminders always keep
one gapless counter per organisation.

**`{version}`** (quotation schemes only; invoice, credit note and reminder schemes refuse it): the first quotation is 1,
each duplicate in its chain of versions the next number. A duplicate keeps the running number of the first quotation
and does not move the counter: `KV-{client}-{yyyy}-{seq:02}-V{version}` gives `KV-ACME-2026-03-V1`, then
`KV-ACME-2026-03-V2`. When the first quotation's number does not follow today's scheme, the duplicate takes the next
number with its version.
### Number ranges: the next running number

*Since 2.138.0.*

Under the number schemes the settings show **Next running number** for every series (quotation, invoice, credit note,
reminder, delivery note), with the finished number as a preview. Only an office admin changes it (members read it, agents never), and
only upwards: never to or below the last number given. With a year in the scheme it applies to the current year ("applies
to 2026"). A jump in the invoice or credit note series needs a reason (GoBD); every change, with its reason, goes into the
office log. Typical use: continue the numbers of a previous program (e.g. start invoices at 1001). Quotations
counted per client or project have no single series and are not listed.

- `GET /api/office/number-ranges` -> `{ranges: [{kind, scheme, period, yearly, last, next, min_next, preview, reason_needed}], admin}`
- `POST /api/office/number-ranges/<kind>` `{next, reason?}` (admin; 400 below `min_next` or without a needed reason)

A draft's number can be changed in the document editor (the pencil next to the number; `POST /api/office/docs/<id>/number`
`{number, reason?}`): unique per office area, never for a sent or finalised document (409). For invoices, credit notes,
reminders and delivery notes the series continues from the new number (a gap needs a reason) and a draft numbered this
way can no longer be deleted (no gaps); a quotation's own number leaves the counter as it is. The document
list shows the new number at once. Both routes are session routes of the office (no API
v1 / MCP tool), the same in the personal office of a person without an organisation.

## Country packs

Tax rates, number and date formats, the labels of the documents and the default texts are not in the code but in a
**country pack**: one JSON file per country under `kalmido/office/packs/<code>.json` (shipped: `DE` and the
international base pack `XX`, 2.147). A pack holds data
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
 "einvoice": {"formats": ["zugferd", "xrechnung"], "status": "ready"},
 "bookkeeping": {"export": "datev", "status": "ready"},
 "features": {"books.datev": {"status": "ready"}, "docs.einvoice": {"status": "ready"}, ...,
              "books.period_lock": {"status": "planned"}},
 "retention": {"receipts": 8, "books": 10, "min_years": 8, "editable": false}}
```

2.147: `features` lists the office functions the pack offers (see *Country pack functions and switches*); a pack without
it (made before 2.147) offers what its `einvoice` / `bookkeeping` blocks say plus the export and the finalising rules.
`retention` gives the years receipts and books are kept (`editable`: the office sets its own value, never below
`min_years`). `tax.editable: true` lets the office set its own rates; labels may then hold `{rate}`. `neutral: true`
marks the base pack. `currency` is the pack's home currency; `currency_editable: true` (2.189) lets the office choose its
own (see *Home currency*).

Labels and default texts come from the pack and the **document's** language, not from the app language of the person
who writes the document.

## Shoot calculation and industry packs

*Since 2.47.*

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

## Packs

*Since 2.76.*

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
  appears in the *Country pack* choice, an installed industry pack gets its box in the *Calculation rules*. Since 2.113
  every industry pack's card (built in or installed) says **Switched on** or **Off** and has its own switch: it
  changes `industry_packs` of the office at once (the same setting as the box in the calculation rules; one undo step). *Update to
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

## Importing legacy data

*Since 2.39.1.*

Settings > "Import legacy data" (organisation admins only) takes over what an office kept in a spreadsheet and old PDF
documents. It is a function of the app: the person uploads the files, sees a preview, corrects it and confirms. Nothing
is guessed in the background and no language model is involved.

Since 2.122.3 the page also holds the one-off imports of fixed costs (spreadsheet) and leads (CSV); each section has its
own address (`#office/import/master`, `fixed`, `leads`, `archive`) that scrolls there and marks it. An empty list of
clients, services, equipment, fixed costs, subscriptions or leads links to its section ("Already have a list? Import
from Excel"), a filled one ends with a quiet "Import…" link. Running exports (DATEV, bookkeeping, bank statements) stay
where they are used.

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
  the file's order. 2.138.0: the import takes this order also for services that existed before (only their order is
  overwritten) and then numbers all services 1, 2, 3 ... without gaps, grouped by category; services that are not in the
  file follow in their category. **Renumber** in the services list does the same for the order shown (one undo step). Excel error values like `#NV` count as empty; `intext` may be `intern`, `extern` or `shooting`; a
  service named "Künstlersozialkasse" becomes a rate in percent (`0.05` -> 5 %). `rawfee` / `producingfee` are always
  read. A table renamed by Excel (`Services_2`) is found too.
- **Client columns and CSV (2.146.0)**: the clients' address may also stand in columns of their own (company, contact,
  street, house number, postcode, city, country; German and English headers like `Firma`, `Straße`, `PLZ`, `Ort`, `Land`,
  `company`, `street`, `zip`, `city`, `country` are found). The preview shows a box "Columns" with a choice per field;
  changing it reads the file again. Without street / postcode / city columns the one-cell address and its splitter stay.
  A country name becomes its code, a 5-digit postcode without a country counts as Germany. Instead of the .xlsx a CSV
  file (UTF-8 or Windows-1252, delimiter found) is read as the sheet `Contacts` (or as `Services` / `Equipment` when the
  file is named so). Old Excel files (.xls, 2.185.0) are read like an .xlsx (every sheet; numbers without ".0", dates as
  their serial number like in the .xlsx); a damaged or password-protected .xls answers with a message that asks to save it
  as .xlsx or CSV; a text file named .xls (some programs export so) is read as CSV.
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
  never lowered. 2.144.6: raising the invoice counter asks for a reason like the number ranges (GoBD); it goes into the
  office log.
- **Undo**: every confirmed import is a run (list with date, person, count). Undoing removes what the run added unless
  something builds on it by now - a client with a list, document, framework contract or archived document of another run
  stays, as does the service the calculation rules name as the producing one; the answer says what stayed. 2.138.0: a
  service used in a document or framework contract and a device in a set are archived instead of staying active
  (documents keep showing them with name and price); the page lists them with the document or set they are in, each with
  **Restore**. A run undone before 2.138 shows **Archive leftover entries** once: it archives what that run left active
  (only its own services and devices, never the producing service, nothing deleted; 2.144.6: an entry restored by hand
  stays active). Fields a merge filled are emptied again while they still hold the imported value. 2.144.6: the undo of
  the services also puts back the order the import renumbered, for every service nobody reordered since.

Routes (organisation admin; members read the archive and, 2.81.0, correct it): `POST /api/office/legacy/preview` (multipart `file`, stores
nothing; 2.146.0: .xlsx or CSV, the optional form field `map` = `{name, contact, address, street, house, zip, city, country: column index}`,
the answer's `columns` = `{head, map, mode: columns | one}`), `POST /api/office/legacy/split` `{address}`, `POST /api/office/legacy/import` `{clients, roles, crew, services, equipment}`
(the preview's rows with `action` new / merge / fill / skip and `merge_id`; 2.46.1: `areas` = only these of clients / roles /
crew / services / equipment, the others are neither written nor checked), `GET /api/office/legacy/runs` (2.46.1: a data run lists its
`areas` with `count` and `undone_at`), `POST /api/office/legacy/runs/<id>/undo` (2.46.1: `{kinds: [...]}` undoes only these
areas of a data run, `409` for an area undone already; the whole undo afterwards takes the areas left; 2.138.0: `archived` =
`[{kind, id, name, used}]`), `POST /api/office/legacy/runs/<id>/tidy` (2.138.0: archives the leftovers of an undone run,
`409` for a run not undone; the runs list `leftover` per data run), `POST /api/office/services/renumber` (2.138.0: 1..n in
the list's order, or `{sorts: {id: sort}}` = exactly these values; answers `changed` and `before`), `POST /api/office/legacy/archive/parse` `{names}`,
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

## E-mails at clients and projects

*Since 2.84.*

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
- **The mail's files in the file store** (2.148.1): the `.eml`, the attachments and the mail's own folder follow the same
  rule as the mail, not the rights of the folder they sit in. Whoever owns the *E-Mails* folder, has it shared or opened
  for the organisation, and organisation admins see a filed mail's files only when they may read the mail itself (a
  client's mail: they see the client; a project's mail: they see the project; a mail not assigned: only its recipient).
  Listing, search, preview and download in the file store all check this.
- **Search**: subject, sender and text (a hashed word index, no plain index).
- **HTML view** (2.141): a mail with an HTML part opens in that view (*Text / HTML* switches). The HTML is cleaned on the
  server (scripts, frames, forms, event attributes and script links removed) and shown in a sandboxed frame without scripts
  under its own strict content security policy. External images stay blocked until *Load images* (for this view only);
  embedded images show at once. Links open in a new tab. A damaged or unreadable original falls back to the text.
- **Task / event from a mail** (2.141): *Task from it* / *Event from it* in the reading view - a project or calendar of the
  mail's workspace where you may write; title = the subject without Re / Fwd, description = the start of the text and the
  sender. The task / event shows *E-mail: subject* (a tap opens the mail) - only to people who may read the mail, everybody
  else sees just *E-mail*. The mail lists the tasks / events made from it. Such tasks are normal tasks for agents too; the
  mail itself stays invisible to them.
- **Agents** have no access to filed mails in 2.84 (no API route, no MCP tool).

### The mailbox of a workspace, replies and new mails

*Since 2.141.*

Since 2.141 a workspace can bring its **own mailbox** and Kalmido can **send** from the filing (plain text, no attachments).

- **Set up**: Office > Clients > *E-mail filing* > *Mailbox* (an organisation: its admins; the private space: the person
  themselves, also a person without any organisation). Receiving = IMAP (server, port, SSL, user, password, folder),
  sending = SMTP (server, port, STARTTLS / SSL / none, user, password, sender address and name); either one alone is fine.
  Each field saves itself when it is left (while the set is incomplete the dialog says what is missing);
  *Check connection* logs in to both (nothing is sent) and says what failed - never with the server's own words. The
  passwords are stored encrypted with the server key and never shown again: an empty field keeps them, another server or
  port needs them again. A server in the local network needs the admin's *Allowed internal hosts* (Settings >
  Administration > Advanced, the same list as calendar subscriptions and webhooks).
- **Receiving**: the mailbox is fetched with the server's mail round (`KALMIDO_IMAP_INTERVAL`, *Fetch now* in the dialog);
  each mail is marked as read and goes to the e-mail filing of **this workspace only**: a client's / project's address of
  the same workspace files there, an answer to a filed mail (In-Reply-To / References) joins that mail's client or project,
  else the sender is matched like at the filing address; the rest waits under *Not assigned* with the person who set the
  mailbox up (an organisation: while they are its admin, else its first admin). A workspace mailbox feeds only the filing
  (no tasks by mail, no documents). The server's own mailbox (`KALMIDO_IMAP_*`) works as before.
- **Reply / New e-mail**: *Reply* in the reading view of a mail (to its sender, "Re: ...", the quote, In-Reply-To /
  References), *New e-mail* in the e-mails of a client or project (the client's and its contact persons' addresses are
  suggested). Who may change the mail / see the client / change the project may write. The mail goes out through the SMTP of
  the workspace; without one through the server's (`KALMIDO_SMTP_*`: the server's sender address, Reply-To = the person's
  own address, the server's daily e-mail limit), without both the dialog says how to set it up. At most 30 mails per person
  and hour, 20 recipients per mail.
- **Filed as sent**: the mail is filed before it goes out (with the same client / project, the `.eml` in the file store) and
  shows "Sent" in the list; when the SMTP fails it stays as "Not sent" with the reason (and the text stays in the dialog).
- **Agents and kid accounts** cannot send (no API route, no MCP tool in 2.141).
- **Exports and moves (2.144.5)**: the organisation export, the account export (the private space's mailbox) and their
  imports carry the mailbox's servers, ports, user names and sender, never the passwords. After an import the mailbox asks
  for them again (*The password is missing*) and is switched off: nothing is fetched and mail goes out through the server
  until the passwords are entered and the mailbox is switched on again in the settings; undoing the import removes it only
  while it is unchanged. A workspace that already has a mailbox keeps
  its own. The nightly boundary check reports a mailbox whose workspace does not match its organisation or owner.

## Travel expenses: taking over a per diem spreadsheet

*Since 2.95.*

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

## Subscriptions and tools

*Since 2.91.*

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
When the last day to cancel before the next renewal has already passed, `cancel_missed` is 1 and `cancel_next` is the last
day for the first later renewal that can still be reached (empty when the cost ends before); the list then shows "Notice
period missed, next chance ...", sorts by that day and the reminder aims at it (`cancel_by` keeps the missed day).

## Sales pipeline and figures

*Since 2.50.*

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
  makes a project (type "Agency") named like the deal, in the office's workspace (a personal office: private),
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

### Leads

*Since 2.94.*

Leads are people who might become clients: the first column *Leads* of the pipeline, before *Inquiry* (the same deals,
stage `lead`, preset 10 %). A lead has a source (website, recommendation, event, social media, appointment booking,
import, agent, other), a next step, a follow-up day, the person, company, e-mail and phone. The column is sorted by
follow-up day; a day that has come is marked in the accent colour, the toolbar counts the leads and those to follow up.
Leads never count in the open sum, the weighted sum or the forecast. *Convert into a client* makes a client of the area
from company / person / e-mail / phone (the person as its contact person) - or takes an existing client with the same
e-mail or company name, which is offered - and moves the deal to *Inquiry*; the undo moves it back and removes a client
made by the conversion as long as nothing else uses it. *Import CSV* (since 2.122.3 under Settings > Import legacy data) reads a file with columns such as name, company,
e-mail, phone, source, next step, follow-up, note, value (German, English, Spanish, French, Italian and Dutch headers;
at most 1000 rows): a preview first, then the rows without errors are taken over; e-mails already in the pipeline or
earlier in the file are skipped as duplicates. An import is one undo step (its leads go into the bin). A confirmed
appointment booking adds a lead with the source *appointment booking* when its booking page names an office area.
Agents (scope `office`, the office switches, acting for an admin) list leads, add leads and change the next step,
follow-up day or note - they never convert, delete or set another stage.

Routes: `GET` / `POST /api/office/deals/<id>/convert` (`{client_id?}`; `GET` = fitting existing clients),
`POST /api/office/deals/<id>/unconvert` (`{remove_client?}`), `POST /api/office/leads/import` (`{text, commit?}`),
`POST /api/office/leads/import/undo` (`{ids}`); agents `GET` / `POST /api/v1/office/leads`, `PATCH /api/v1/office/leads/<id>`.

## Cash flow and fixed costs

*Since 2.67.*

The tab **Cash flow** (admins of the office area only) shows per month what comes in and goes out, actual and planned.
**Fixed costs** (rent, subscriptions, insurances) are entered there: name, amount **net**, a free **category** (the list
groups by it, without one last; the field suggests the categories already used), the **VAT rate** (0, 7 or 19 %), repeat
(once, monthly, quarterly, yearly), first due date and end. Each row shows net and gross (at 0 % VAT one amount and "without VAT", 2.122.3). Fixed costs from before 2.67
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

**Import from Excel** (since 2.122.3 under Settings > Import legacy data, section "Fixed costs from a spreadsheet"): "Download template" gives an .xlsx with the header row and three example rows. The first sheet is
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
off by default; format in [AGENTS.md](AGENTS.md#importing-old-data-into-the-office)). Kalmido does not read the data
itself. The proposal card shows the same preview as the Excel import (new / duplicate unticked / error greyed out with the
reason, VAT per row, net and gross) and the office it goes into; "Take over N rows" writes them as you, one undo step
removes them again. The agent never sees the office; an agent of an organisation imports only into that organisation.
Freelancers without an organisation import into their personal office.

**Monthly check** (optional): a tick creates the task "Cash flow: check the actual state" for one admin of the area, due
on the 1st of every month in that person's basket, with only a link to the cash flow (never an amount). Another person
ends the old task and creates a new one; switching it off ends the task (done, without a next date; not deleted). If the
person later loses access to the cash flow, the tab says so; nobody else is picked automatically.

**Account balance** (2.123): a rough orientation also when not everything is in Kalmido. In the office settings, section
**Cash flow**, the admin enters a **starting balance** (may be negative) and its **reference date** (saved on change, one undo
step; empty = no balance). The cash flow then shows per month the **account balance at the end of the month** (computed):
the starting balance plus all money in minus all money out from the reference date on - actual and planned, so also in
the preview - always gross (the account sees gross amounts), also when the view is set to net. Months before the reference
date have none. **Corrections by hand** ("Other money in" / "Other money out", amount and a short note, per month, marked
"by hand") are for money outside Kalmido: they count only in the account balance, the computed rows (in, out, balance,
tax reserve) stay as they are. Adding, editing and deleting is one undo step each. **Real balance** (optional, by hand):
the balance from the bank statement at the end of a month; the card shows the **difference** to the computed balance
(only shown, nothing is booked). Without a starting balance and without corrections the cash flow looks exactly as before.
Amounts and notes are encrypted at rest; the same for organisations and for freelancers in their personal office.
`GET/PUT/DELETE /api/office/cashflow/start` (`{amount, day}` -> `{start, prev}`), `POST /api/office/cashflow/adjust`
(`{month, dir in|out, amount, note}`), `PATCH/DELETE /api/office/cashflow/adjust/<id>` (delete answers the row for the undo),
`PUT /api/office/cashflow/actual` (`{month, amount}`; null removes it). The cash flow answer adds `start`, `adjust` and per
month `account`, `manual {in, out}`, `real`, `diff` - only when they are set.

**Balance according to the bank** (2.124): the balances of the imported bank statements (tab **Bank**) appear in the cash
flow as "Account balance according to the bank on DD.MM.YYYY", marked "from the bank reconciliation", with the
**difference to the computed balance** (the running balance above at the end of that day; only with a starting balance).
Several accounts are added up (per account its newest closing balance; the date is the oldest of them); each month card
shows the balance of the statements inside it. Without a starting balance **Use as starting balance** takes it over; per
month **Use as real balance** fills the real balance of that month - both go through the routes above and are one undo
step. A starting balance or a real balance entered by hand always wins; the bank only suggests. Without balances the
cash flow looks exactly as before. The cash flow answer adds `bank {day, amount, accounts[], computed?, diff?,
suggest_start}` and per month `bank {day, amount, computed?, diff?}` - only when an active import has balances.

Routes (office admins, people only; agents get 403): `GET /api/office/cashflow?from=YYYY-MM&months=1..12&basis=gross|net`,
`GET/POST /api/office/fixed-costs`, `PATCH/DELETE /api/office/fixed-costs/<id>` (`category`, `vat_rate` 0/7/19; the answer
adds `gross`), `POST /api/office/fixed-costs/import/preview` (multipart `file`), `POST /api/office/fixed-costs/import`
(`{items: [{label, amount, repeat, start, until?, category?, vat_rate?}]}` -> `{created, ids}`),
`POST /api/office/fixed-costs/delete` (`{ids}`: the undo of an import), `GET /api/office/fixed-costs/import/template`,
`GET/PUT /api/office/cashflow/check` (`{on, user_id}` -> `{on, user_id, task_id, people, lost}`).

## Bookkeeping

*Since 2.90.*

The tab **Bookkeeping** (admins of the office; without an organisation your personal office) covers the running bookkeeping
of a self-employed person. **Photograph receipt** opens the camera on a phone (the file dialog on a desktop, PDF too): the
receipt goes into your documents, amount and date are recognised in the background, and you add the category and the VAT
rate (19 / 7 / 0 % or unknown). The **income/expense statement** of a year counts payments received on your invoices
(cash principle, split by VAT rate) against your receipts and travel expenses, with export as CSV or PDF. The **VAT return**
section lists the figures (fields 81, 86, 21, 45, 66, 83) for a month, a quarter or the whole year to type into ELSTER, on cash
or accrual basis; with the yearly tax dates setting the whole previous year is preselected (2.122); small businesses get no return. A **tax reserve** (percentage of the net money received) shows up per month in the cash flow
as "Tax reserve" and "Freely available". No tax advice; figures without guarantee. Kalmido sends nothing to the tax office.

**Billing receipts on to a client (2.121):** under the receipts of the month, **Bill receipts on to a client …** (or **Bill on to a
client …** in a receipt's sheet) puts the ticked receipts as positions "external costs" on a quotation or invoice in draft: the
amount is the purchase price, the markup in % makes the price (one position per receipt or one for all). A receipt with a VAT rate
is billed net (the input tax stays yours), without a rate or in a small business gross. The row then says "billed on …"; a receipt
is never billed twice, and Undo takes the positions back while the document is a draft. Agents may suggest amount, currency and VAT
rate of a receipt as well; you change them in the suggestion card before you accept (Undo brings the old values back).

**Receiving e-invoices (2.146):** XRechnung files (.xml, UBL or CII syntax) and ZUGFeRD / Factur-X PDFs (the XML embedded in
the PDF) are read as e-invoices - uploaded with **Photograph receipt** or **Add documents**, or attached to a mail to your
documents' forwarding address (any other .xml in a mail is left out). Date, due date, gross amount, currency and the seller
(as sender) come from the invoice data instead of the text recognition; invoice number, net, VAT per rate and the VAT rate wait
in the suggestion line of the receipt. The document says "E-invoice" and offers **Readable view**: the invoice as a plain page
(seller, recipient, lines, VAT, totals, IBAN) to read, print or save as PDF with the browser. An XML with a DOCTYPE, a broken one
or one beyond the limits (5 MB, nesting, number of elements) stays an ordinary file.

**Accounts per category (2.121):** with the DATEV export set up, a receipt's sheet shows under the category the account of the
chart SKR03 or SKR04 (Settings → DATEV) it is booked on - the default the export finds for the category (e.g. Software 4964 /
6837), or your own. **Change account** sets your own account for this category (empty = the default again; one undo step); the
DATEV batch and the lines of the income/expense statement use the same account.

### All receipts and the export for the tax adviser

*Since 2.153.*

**All receipts** below "Receipts this month" opens the receipts of every month (`#office/books/receipts`). Filters: the
period (this / last year, quarter, month, or two dates of your own), paid / not paid (paid = a payment day is set, e.g. by
the bank reconciliation), category, supplier (the document's sender), project, only receipts without a VAT rate, and a search
in title, supplier and invoice number. The day of a receipt is its **receipt date** (the tax adviser books by it); switch
to the **payment date** to see what was paid in a period. Below the list: the number of receipts and the sums (net, VAT,
gross). On a phone the filters are folded away. The filters stay while the app is open.

**CSV** and **ZIP for the tax adviser** export exactly the filtered list (shown while the country pack has the export
switched on, like the booking list of the year). The CSV follows the pack's number format (decimal comma: semicolon
separated, dates as DD.MM.YYYY; else comma separated, decimal point, ISO dates) and has one row per receipt: receipt date,
paid on, supplier, VAT ID and invoice number (of an incoming e-invoice only), e-invoice yes/no, title, category, project,
net, VAT rate, VAT, gross, currency, the original amount and currency of a receipt in a foreign currency, the file name in
the ZIP and the Kalmido ID. The ZIP holds this CSV as `belege.csv` and the original files in `belege/` as uploaded (an
e-invoice as its XML or PDF), named `YYYY-MM-DD_supplier_gross_id.ext`; the limits of a ZIP of the file store apply (choose
a shorter period for more). Only receipts you see, nothing from the trash; every export is noted in the office log. The
booking list with invoices, payments and travel expenses stays the export of the year above (2.147). Routes:
`GET /api/office/books/receipts`, `/receipts.csv`, `/receipts.zip` with the same query (`from`, `to`, `by=doc|paid`,
`status=all|paid|open`, `category`, `supplier`, `project`, `novat=1`, `q`; the list also `limit`, `offset`); people only,
agents get 403.

An **incoming e-invoice** (XRechnung / ZUGFeRD) that lands in the documents of an office area becomes a receipt the first
time it is read, with the VAT rate of the invoice; an invoice the office issued itself (same VAT ID, tax number or company
name) does not. The amount of a credit note is negative.
## Bank reconciliation

*Since 2.90.*

The tab **Bank** (admins of the office area; in a personal office its owner) matches the bookings of your account with
invoices and receipts. Kalmido has no bank access: you import the file you download from your bank yourself.

- **Import bank statement**: a CSV export (German and English formats: `1.234,56` or `1,234.56`, `DD.MM.YYYY`,
  `YYYY-MM-DD` …; account lines above the header are skipped) or a CAMT.052 / CAMT.053 XML file. For a CSV you confirm
  which column holds the date, the amount (one column with a minus for money out, or income and expense apart), the
  purpose and the counterpart; Kalmido guesses them as in the household budget. A CAMT file goes straight to the
  preview (booking day, amount with credit / debit, counterpart and IBAN, purpose, the bank's reference). XML files with
  a DOCTYPE or ENTITY are refused. At most 2 MB and 3000 rows per file. 2.140: the household budget reads files with the
  same reader (one module, no data shared); a few bank layouts are recognised by their columns and pre-fill the choice.
- **Duplicates**: a booking already imported into this office area (same day, amount, counterpart, purpose, reference)
  is skipped and counted; two equal bookings in one file stay two.
- **Matching**: every open booking shows the best suggestion with its reason. Money in -> open invoices (same amount as
  open, invoice number in the purpose, customer name); money out -> receipts of the office's documents (same amount,
  date within 14 days, name). **Match** records a payment on the invoice (day and amount of the booking, transfer; a
  smaller amount = partly paid) or sets the receipt's payment day (used by the bookkeeping's cash principle). **Other …**
  searches all open invoices / receipts; **Private** and **Ignore** only mark the booking. **Undo match** takes the
  payment back (2.152: as a reversal line, see "Payments and reminders"); reversing the payment on the invoice opens the
  booking too. Every step can be undone.
- **Imports**: the list of imported files; **Take back** removes its bookings (refused while one of them is matched -
  undo those matches first); its undo brings them back.
- Amounts, counterparts, purposes and IBANs are encrypted at rest when the encryption of the organisation is on. The
  DATEV export is unchanged. Agents have no access to the bank reconciliation.
- **Balances** (2.124): a CAMT file brings the opening balance (OPBD / PRCD) and the closing balance (CLBD, else CLAV) of
  each account (its IBAN) with their day; balances in another currency than the office are left out. A CSV can name an
  optional **balance** column (guessed from "Saldo" / "Kontostand" / "Balance"): the balance of the chronologically last
  booking counts (on the newest day the last row, or the first one when the file runs newest first, as most banks
  export). The account is the IBAN of an optional own-account column (e.g. "Auftragskonto") or the name typed in the
  dialog (default "Main account"). The preview names the balances; they count in the cash flow while the import is not
  taken back. Amount and account are encrypted at rest.
- **Which file** (2.144.1): **Import bank statement** first opens the dialog with a short hint: take the XML export
  **CAMT.053, booked transactions** (version V2 or V8 does not matter; only it brings the balance along); a CSV export works
  too (columns chosen by hand, a balance only with a balance column); better not CAMT.052 (day reports, see below) and
  not MT940 / MT942 (not read: such a file gets a clear message). The cash flow has the same button next to the balance
  according to the bank; it opens this dialog and loads the cash flow again.
- **CAMT.052 day reports** (2.146): an entry's status (`Sts`, in camt.052.001.08 `Sts/Cd`) is read. Pending entries (PDNG,
  anything not BOOK) are shown in the preview as "pending – not imported" and are never imported; the booked version comes
  with a later report. A booking found by its bank reference (`AcctSvcrRef`, else the `EndToEndId`; `NOTPROVIDED` /
  `NONREF` do not count; always together with the amount) in the office area or in an earlier file of the import counts
  once, also with another day or text (pending first, booked later). The references are kept as keyed hashes only
  (`office_bank_tx.rkeys`). When day reports were read the preview recommends the account statement (CAMT.053) for the
  bookkeeping. CSV: a debit / credit mark column (S/H, Soll/Haben, D/C, -/+) next to an amount without a sign is guessed
  (also an unnamed column right after the amount, and the Volksbank / Raiffeisenbank layouts); dates also as
  `DD-MM-YYYY` and `YYYYMMDD`.
- **Several files or a ZIP** (2.144.1): choose several statements at once, a ZIP file (e.g. one statement per day from the
  bank) or drop them onto the dialog. Everything becomes one preview sorted by day (then file, then row) and one import
  (one **Take back** / undo for all). A ZIP is read in memory only, never unpacked to disk: only `.xml`, `.csv` and `.txt`
  entries count (folders and hidden files of the packing system are ignored; other entries and nested ZIPs are named as
  skipped), only the file name is shown, encrypted entries are refused. Limits: 20 MB upload, 400 statements, 2 MB and 3000
  rows per statement, 60 MB unpacked and 20000 rows altogether, at most 2000 entries in a ZIP. A file that cannot be read
  is named with its reason and the others go on. CAMT and CSV may be mixed; the column choice of the first CSV holds for
  every CSV, CSV files with different columns are refused (import them one by one). Duplicates across files: a booking in
  a day and in a month statement counts once (per booking the larger number of the office area or of one earlier file of
  the import counts, never the sum); two equal bookings in one file stay two. The balances of every file are kept (each
  one is a real balance of its day; the cash flow uses them per month), so the newest file gives the current balance.

Routes (office admins only; members 403, other areas 404, agents 403): `POST /api/office/bank/import/preview`,
`POST /api/office/bank/import`, `GET /api/office/bank/imports`, `POST /api/office/bank/imports/<id>/undo|restore`,
`GET /api/office/bank/tx?state=open|matched|all&from&to`, `GET /api/office/bank/tx/<id>/candidates?q=`,
`POST /api/office/bank/tx/<id>/match` `{kind: invoice|receipt|private|ignored, id?}`, `POST /api/office/bank/tx/<id>/unmatch`.
Tables `office_bank_imports`, `office_bank_tx`, `office_bank_balances` (2.124, see Database). Both import routes take the JSON body `{text,
filename?, mapping?, account?}` (one file) or, since 2.144.1, `multipart/form-data` with the field `files` (several, a ZIP
is opened) and `mapping` (a JSON string) / `account` as form fields; the answer adds `files`, `file_errors [{file, error}]`
and `skipped_files`, each preview row its `file`. `fmt` of a mixed import is `mixed`. Since 2.146 the answers add `pending_count` and `camt052`,
each row `pending`; the mapping may name `sign` (the column of the debit / credit mark).

## Tax dates as tasks

*Since 2.90.*

At the bottom of **Bookkeeping**, **Tax dates** keeps the usual German deadlines in view: the VAT return (none, monthly,
quarterly or yearly, optionally with the permanent extension), the income tax prepayments (10 March, June, September, December)
and the trade tax prepayments (15 February, May, August, November). Each kind switched on becomes ONE recurring task in
the basket of the person chosen (an admin of the office; in a personal office its owner), due on the deadline minus the
lead time (default 3 days); the title names the real deadline, the VAT task links to the VAT return figures.
**Yearly (annual return only)** (2.122) is for businesses that file no advance returns: instead of the advance return one
yearly task "Submit the annual VAT return" (31 July of the following year; with a tax adviser the deadline is usually later,
so please agree it with them); the permanent extension does not apply there.
Switching a kind off or changing it ends the old task (done, never deleted) and creates a new one when needed; a task
completed or deleted by hand comes back on the next save. A deadline on a weekend or holiday moves to the next working
day (Kalmido does not shift it). No tax advice; figures without guarantee.

Routes (office admins only): `GET /api/office/tax-dates`, `PUT /api/office/tax-dates`.

## Contracts and insurance

*Since 2.92.0.*

The tab **Contracts & insurance** (office admins only; in a personal office its person) keeps the business contracts of the
office in one place: insurances, rent, leasing, service providers and others. Per contract: name, provider, policy or
contract number, the contribution per month / quarter / year (net when a VAT rate is set), start, the end of the current
term, the notice period (days, weeks, months), the automatic renewal (or "ends without renewal"), how many days before the
deadline to remind, a note and the contract document. The list is grouped by kind and shows the contribution per month and
the next deadline ("Cancel by 12 Mar 2027 · 41 days left", in red from the reminder lead on).

- **Deadline**: the last day to cancel is the end of the term minus the notice period (the same logic as the household
  contracts in Home & life). When it has passed and the contract renews, the term rolls on to the next one; a contract
  without renewal is simply over.
- **Deadline as a task** (on by default): one task in a project you pick (default: your Basket), due on the last day to cancel,
  with reminders and a repeat that follows the renewal. Changes to the contract update the task; switching it off,
  archiving or deleting the contract ends the task (it is completed, never deleted). Agents that may see that project can remind
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

## Equipment value, depreciation and insurance list

*Since 2.92.0.*

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

**Private device <-> equipment (2.140).** A device of *Home & life* can be added to the office equipment from its task
panel (*Add to the office equipment*: the own office, or an organisation where you are admin; the dialog asks for the
net price because the device keeps what you paid), and a piece of equipment can be taken over as a private device
(*Take over as a private device* in its editor; admins). The fields are copied once (name and model, serial number,
purchase date, price; the vendor becomes the device's note) and both sides show the link with a jump to the other side,
*Update from there* and *Remove link*. Nothing is mirrored by itself. Only you see your link; when you leave the
organisation or the other side is deleted, the link shows a hint (without names) and can be removed.

API (office admins; members 403, another office area 404): the fields go through `POST|PATCH /api/office/equipment[/<id>]`
(`purchase_date`, `purchase_net`, `new_value`, `current_value`, `serial_no`, `vendor`, `receipt_node_id`, `life_months`,
`agreement_id`); `GET` answers admins also `afa_plan`, `afa_year`, `book_value`, `new_value_eff`, `current_value_eff`,
`life_suggest`, `life_eff`, `agreement_name`. `GET /api/office/equipment/value` (sums and rows), `value.csv`, `value.pdf`
(`?agreement_id=`, 0 = not insured), `GET /api/office/equipment/policies`, `GET /api/office/equipment/receipts[/<id>]`.
## Logbook

*Since 2.93.*

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
- **Closing (2.152)**: a drive can be changed or deleted for a week after its day (or after it was entered, whichever is
  later); then it is closed. **Close month** (one vehicle or all) closes a month at once and cannot be undone; no new
  drives go into a closed month. A closed drive opens read-only with its change log right in the dialog; **Correct**
  makes a new entry with the old values and a required reason. The old drive stays visible ("Corrected"), leaves the
  sums and points to its correction; the CSV has fixed columns for a machine check (ID, corrects, corrected by, reason,
  closed) and the change log carries the drive's ID. Deleted drives are kept until the legal period (8 years from the
  end of their year) has passed.

Routes (office admins only; members 403, other areas 404, agents 403): `GET|POST /api/office/vehicles`,
`PATCH /api/office/vehicles/<id>` (also `archived`), `GET /api/office/drives?vehicle_id=&year=`, `POST /api/office/drives`,
`PATCH|DELETE /api/office/drives/<id>`, `POST /api/office/drives/<id>/restore`, `GET /api/office/drives/<id>/log`,
`POST /api/office/drives/<id>/trip`, `GET /api/office/logbook/report?year=&vehicle_id=`,
`GET /api/office/logbook.csv|pdf?year=&vehicle_id=`, `PUT /api/office/logbook/settings` `{km_rate, year}`,
`POST /api/office/logbook/close` `{month: "YYYY-MM", vehicle_id?}` (2.152; only past months since 2.186, the running one 400;
moving the personal office into an organisation turns "every vehicle" into each of its own vehicles; a closed drive: `PATCH` / `DELETE` 409, a
correction = `POST /api/office/drives` with `corrects_id` and `correct_note`; each drive answers `locked` auto | month,
`corrects_id`, `corrected_by`).

## Cash book

*Since 2.121.*

The menu group **Money** has the point **Cash book** (admins of the office area; without an organisation your personal
office) for cash income and expenses. Every office has a **default cash box** (made on the first look, opening balance 0
from that day); more boxes can be added under **Cash boxes** (name, opening balance, the day of the opening balance; saved
on change). Boxes are archived, never deleted; the default box stays.

- **Quick entry** on top (phone first): income or expense, amount, text, date (today), VAT rate 19 / 7 / 0 %, category
  (the receipt categories as suggestion, free text allowed). Every entry gets the **next number of its box, without
  gaps**, also when several people book at the same moment. The balance never drops below zero: such an entry is refused
  with a clear message (also when it would only be negative on an earlier day).
- An entry can point at a **receipt** of the office's documents (the receipt then shows "In the cash book ... no. X") or
  at an **issued invoice** paid in cash.
- **Nothing is deleted.** An entry is taken back only by **cancelling**: a counter entry with a new number that names the
  original ("Cancels no. X"); the original shows "Cancelled by no. Y", both stay. The undo of a booking is such a
  cancellation. Entries of an open day can still be changed; every change is logged with the values before ("History").
- **Close day**: shows the opening balance, income, expense and closing balance (and closes earlier open days with
  entries too). Closing is **final** - there is no undo: afterwards no entry up to that day changes, none is booked on or
  before it, corrections only by cancellation on a later day, and the opening balance of the box is fixed.
- **Export** as CSV (semicolon, decimal comma) or PDF for a year or a period: number, date, text, income, expense, VAT,
  balance, cancellation link, receipt / invoice, the day closings and the change log.
- The cash book is a record of the cash and its balance; it does **not** count in the income/expense statement (the
  receipts and invoice payments do, as before), so nothing counts twice. No tax advice; figures without guarantee.

Routes (office admins only; members 403, other areas 404, agents 403; no agent API): `GET|POST /api/office/cashbooks`,
`PATCH /api/office/cashbooks/<id>` (name, opening, opening_day, archived), `GET /api/office/cashbooks/links`,
`GET|POST /api/office/cashbooks/<id>/entries` (`?year=` or `?from=&to=`), `PATCH /api/office/cash-entries/<id>`,
`POST /api/office/cash-entries/<id>/cancel` `{day}`, `GET /api/office/cash-entries/<id>/log`,
`GET|POST /api/office/cashbooks/<id>/closing` `{day}`, `GET /api/office/cashbooks/<id>/log`,
`GET /api/office/cashbook.csv|pdf?book_id=&year=`, `GET /api/docs/<id>/cashbook` (the hint on a receipt).

## Procedure documentation (GoBD)

*Since 2.148.*

**Bookkeeping -> Procedure documentation** gives a prefilled *Verfahrensdokumentation* in the outline of the GoBD (sections
1 general description, 2 user documentation, 3 technical system documentation, 4 operating documentation, 5 internal
control system). Kalmido fills in what it knows: the company data, the members of the office with their role (names
only), the country pack, number ranges, e-invoice format, cash books, bank imports, the locked months, the DATEV numbers
(on file yes / no), the encryption and the automatic backup as set by the operator, the retention periods of the German
pack. Everything Kalmido cannot know (legal form, server location, where backup copies are kept, the last restore test)
is a marked gap "[ ... to fill in ]" in the view and in the exports; the view counts the open gaps.

- Each field has an own text; **Save new version** stores the own texts together with the prefilled texts of that
  moment as the next version (1, 2, ...). There is no autosave here on purpose: every save is a version.
- Older versions open read only from the version picker, exactly as they were saved.
- **Markdown** and **PDF** of the current state or of a version, with the company, the version, its date and the Kalmido
  version in the head.
- The document is in German when the app is in German, else in English. No legal advice: have it checked.

Everybody with access to the office reads (members, read-only, accounting); admins save (without an organisation: your
personal office, you are its admin). Saved data are encrypted at rest like the other office texts, every save and export
is in the office log. No agent API (the office is closed to agents).

Routes: `GET /api/office/procdoc?version=&lang=de|en`, `PUT /api/office/procdoc` `{own: {field: text}, base?}` (admins; 409
when `base` is not the latest version), `GET /api/office/procdoc/versions`, `GET /api/office/procdoc.md|pdf?version=&lang=`.


## Locking periods and the export for the tax auditor (GoBD)

*Since 2.148.*

**Bookkeeping -> Lock periods (GoBD)** shows the months of the year with their lock. **Lock up to ...** locks every open
month up to and including the chosen one (only finished months, always in order, from the first month with data). The
dialog explains it and asks to type the month: a locked month is never unlocked. The lock is an entry "period_lock" in the
office log.

In a locked month the server refuses (409) every change of booking data with a date in it: finalising an invoice or credit
note dated there, moving a draft's date into it, payments (by hand, from the bank reconciliation or an agent's
suggestion), matching or unmatching bank bookings, a receipt's amount, date, currency, category, VAT rate or payment day,
moving it to the trash (also inside a folder), restoring it, a new file version or a new recognition, moving it to another
workspace, cash entries, trips and their receipts (also imported or moved), entertainment receipts and the undo of a DATEV
import. Corrections go into an open month, e.g. a credit note dated today. Importing a bank statement stays possible (the
lines are not bookings until they are matched). A personal office with locked months cannot move into an organisation,
and nothing moves into a locked month of the organisation.

**Export for the tax auditor** (also in that section): one ZIP for a period (default: the previous calendar year, at most
eleven years) with the tables bookings (the lines of the DATEV batch), invoices / credit notes, positions, payments,
receipts, cash book, clients, opening balances and the office log as CSV (UTF-8, `;`, decimal comma, dates DD.MM.YYYY, no
header line; a text starting with `= + - @` gets a leading apostrophe), described in `index.xml` in the description
standard of the GDPdU. The DTD `gdpdu-01-09-2004.dtd` that `index.xml` names is not part of the ZIP; the auditor's
software brings it. Admins (and the accounting role) only.

## DATEV export with receipt images

*Since 2.148.*

The DATEV export dialog has **With receipt images (ZIP for DATEV Unternehmen online)** (on by default) and **Only locked
months**. The first press checks the period and lists receipts without a booking (no amount) and bookings without a
receipt (money paid out on the bank account without a matched receipt, cash paid out without a file); the second press
downloads one ZIP:

- `EXTF_Buchungsstapel_<from>_<to>.csv`: the booking batch as before; every line of an invoice / credit note or a receipt
  carries `BEDI "<GUID>"` in the column Beleglink.
- `Belege_<from>_<to>.zip`: `document.xml` (DATEV XML interface, schema Document_v05.0) with one document per GUID, and the
  files: the PDF of every finalised invoice / credit note and the file of every receipt you see.

The GUID of a document stays the same in every export of the office area (a repeated export links the same receipts). With
**Only locked months** the period ends at the last locked month and the batch says Festschreibung 1. Limits: 1500 files and
80 MB per export (choose a shorter period above).

## Travel expenses: per diem

*Since 2.95.*

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

## Travel expenses: purposes, person filter, row menu

*Since 2.117.*

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

## Entertainment receipts

*Since 2.119.*

Office -> Money -> **Entertainment receipts** (Bewirtungsbelege, section 4 (5) no. 2 EStG; admins of the office area, a
person without an organisation in the personal office). A receipt is entered as a mask:

- **Date**, **place** (choose one or *New place…* with the name and address of the restaurant), **occasion** (required and
  concrete - "business meal" alone is refused), **host** (choose, default: you; or *New person…* with company / function)
  and the **guests** (tick people of the office or of the choice list, *New person…* adds one with company / function).
- **Amounts** as on the bill: gross per line, split into food / drinks and the VAT rate (19 %, 7 %, 0 %; *Add line*), the
  **tip** on its own (not on the bill, no VAT). The total, the VAT in it and the deductible 70 % are shown live; from
  250 € gross a hint says the bill must be made out to the company.
- The **restaurant bill** can be attached (PDF, JPEG or PNG, one file; replace and remove with one undo step). It is stored
  encrypted with the office area's key like the other office files.
- **Save draft** keeps it changeable. **Approve** checks the required fields (date, place with address, occasion, host, at
  least one guest, an amount), takes new places and people into the choice lists and **locks** the receipt: it cannot be
  changed or deleted any more; the approval is the host's digital confirmation (name and time, printed on the PDF).
  **Undo approval…** (row menu or the receipt) asks for an optional reason and makes it a draft again; every approval and
  every undo stays in the receipt's **approval log** (who, when, why), also when it is approved again, and in the office's
  access log.
- **PDF**: the own receipt (Eigenbeleg) with the details block, the amounts per rate with VAT and net, the tip, 70 / 30,
  the host's confirmation and the log; a draft is marked as such.
- **Row menu**: Open, PDF, Duplicate (a new draft with the same data, without the bill), Move to another workspace
  (drafts), Undo approval (approved ones), Delete (drafts; one undo step).
- **Filters** like the travel expenses: year, person (host or guest; hidden when only one person occurs) and occasion
  (part of the text). They apply to the list, the **evaluation** and its downloads.
- **Evaluation** (approved receipts only; drafts are counted apart): gross, input VAT (100 %), 70 % deductible / 30 % not
  deductible of the net amount incl. the tip, food / drinks / tip, input VAT per rate and the months; **CSV** (one row
  per receipt, safe against spreadsheet formulas) and **PDF** for the tax adviser.
- **Choice lists**: Office -> Settings -> *Entertainment receipts* lists the places (with address) and people (with
  company / function): rename in place, remove (one undo step), add. Receipts keep the text they have.
- **Deleting and retention**: a draft that was never approved goes to the trash (undo) and is deleted for good with its
  bill after 30 days. A receipt that was approved once is kept until the end of the 8th year after its year (it cannot be
  deleted before). The organisation export contains the receipts, choices, logs and the bills.

Routes (admins of the office area; members 403, another office area 404, agents never): `GET /api/office/meals?year=`,
`POST /api/office/meals`, `GET/PATCH/DELETE /api/office/meals/<id>`, `POST /api/office/meals/<id>/restore`,
`POST /api/office/meals/<id>/approve`, `POST /api/office/meals/<id>/unlock` `{reason?}`, `POST /api/office/meals/<id>/file`
(multipart `file`), `GET/DELETE /api/office/meals/<id>/file/<fid>`, `POST /api/office/meals/<id>/file/<fid>/restore`,
`GET /api/office/meals/<id>/pdf`, `GET /api/office/meals/report?year=|from=&to=&person=u<id>|n:<name>&occasion=&format=csv|pdf`,
`GET/POST /api/office/meals/choices`, `PATCH/DELETE /api/office/meals/choices/<id>`. A locked receipt answers `409` to
changes, deleting and a new bill.

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

### The project of a document

*Since 2.168.*

A quotation, invoice or credit note can belong to a project (the editor's row "Project", `office_docs.list_id`): pick one
of the projects you see in the office's workspace (the client's open projects on top) or tick "Create new project" (named
"Client – project title", changeable; a project of the type agency in the office's workspace, a personal office's is private,
with the document's client, only you a member). It is an internal mark only, so it can be set and changed on finalised and
sent documents too; the document itself (number, sums, PDF) stays as it is. An invoice from a quotation (also progress and
final invoices), a credit note and a new quotation version keep the project, an invoice from the hours of exactly one project
gets it, a copy of an invoice does not. A deal's quotation starts with the deal's project; a project created on it goes to
the deal too when the deal has none. The project page shows "Quotations & invoices" (number, status, amount, a click opens
the document) only to people with office rights in the project's area; other project members see nothing of it.
Routes: `POST /api/office/docs/<id>/project`, `GET /api/lists/<id>/office-docs` ([API.md](API.md)).

### Trial documents

*Since 2.144.10.*

"Only to try it out": `POST /api/office/docs` (every kind) and `POST /api/office/docs/from-time` take `trial: true`. A trial
document is fixed at creation (no later switch) and:

- counts in its own series `TEST-001`, `TEST-002` ... (one counter per organisation or personal office for all kinds,
  `office_numbers` kind `trial`); it never takes a real number, a number by hand answers `400`, the real series stay
  without gaps and the number ranges page does not show the TEST series;
- passes trial on to everything made from it (invoice, progress / final invoice, credit note, reminder, delivery note,
  copy, document from a template); a reminder never mixes trial and real invoices (`400`); an invoice series from a
  trial invoice answers `409`;
- prints SAMPLE / MUSTER large and diagonal on every page (instead of the draft mark) and has no e-invoice
  (no ZUGFeRD / XRechnung XML; `GET .../xml` answers `409`); webhooks and agent events skip it;
- can be deleted by an admin at any time (finalised, sent, signed, with follow-ups; the follow-ups stay, their link
  is emptied). `POST /api/office/trial/delete-all` (admin; a person without an organisation is their own admin) deletes
  every trial document and trial document from a template of the area with payments, links, stored PDF / XML files
  and filed PDFs -> `{ok, docs, gen_docs}`; the TEST series starts again at 001.

Every document (detail and list) carries `trial`; `GET /api/office/docs?trial=1|0` filters, the list also answers
`trial_count` (trial documents + trial documents from templates), `first: {offer, invoice}` (true = no real quotation /
invoice yet: the dialog shows the hint once per person, setting `trial_hint_seen`) and `office_id`.
`GET /api/office/gen-docs` items carry `trial` too (`?trial=1|0`).

Purchase and surplus (2.47): a new position of a service takes the purchase (`cost`) of the service's freelancer role
for its unit (day / hour); a later change of the role's price reaches only new positions; the admin can change it per
position. Admins get the surplus of every position (`items[].margin` = total minus purchase x quantity) and their sum
(`items_margin`); members get neither `cost` nor `margin` (the fields are absent), and neither appears in the print model
or the PDF. A position of unit `percent` (e.g. the artists' social insurance) is its rate in percent of the positions
marked `extern` on the same sheet; its quantity does not count; an invoice made from the quotation turns it into a plain
amount. When a quotation becomes "accepted" its purchase is stored for the cash flow (`office_purchases`: one row per
position with a purchase and per part, amount encrypted at rest, dated at the start of the period of service, else the
day of acceptance), stored anew when the accepted quotation changes and removed when it leaves that status.

## Undo in the editors

*Since 2.138.1.*

Documents (quotations, invoices, credit notes, reminders and the parts of a quotation), clients, the master data
(services, texts, contracts, sets, roles) and tables keep saving every change at once. Every own saved change is one
step of the app's history: Ctrl+Z (Mac: Cmd+Z) takes it back while the focus is not in a text field (there the field's
own text undo works). Leaving a changed document or table (Back, the menu, a link, another document) turns its steps
into one entry and shows "... saved · Undo" for 10 seconds; its button brings back everything since the document was
opened. Leaving without a change shows nothing. The client and master data dialogs keep their Save button; after a save
the same hint brings back the values from before the dialog. Equipment, document templates and documents made from
templates keep their own undo.

Never undone: finalising, sending, payments, a status change, a number, the reminder fee and DATEV keep their dialogs
and end the way back for the open document. The server refuses an undo (409 with the reason) when someone else changed
the object in the meantime (their change stays), when the document was finalised or sent meanwhile, or when a client
moved to another workspace. Tables check the table's revision the same way.

How it works: the editor sends its saves with the header `X-Kalmido-Undo: <session token>`; the write routes keep a
copy of the stored rows before the step and a fingerprint of the state after it (table `office_undo`, one day).
`POST /api/office/undo/<doc|client|services|texts|contracts|sets|roles|crew>/<id>` with `{sess, op}` (`undo` = the newest
step, `all` = back to the opening, `redo`, `redoall`) writes a copy back in one transaction, only while the object is
exactly as this person's last step left it; rights as for the normal change. Saves without the header (agents, the
API, other apps) record nothing.

## Texts by an agent

*Since 2.126.1.*

On a draft (quotation, invoice, reminder) the section *Introduction and closing* offers *Draft text with an agent* when an
agent of the office area may draft office documents and the area lets agents read office data. Choose the agent (when
there are several), the text (introduction or closing) and, if you like, a short wish ("friendly, short"). The agent gets
the document without purchase prices, the client and the current text (a reminder also its invoices, open amounts and
days overdue) and answers with a proposal: you edit the text on the card and take it over (one undo step) or discard it.
Nothing is sent; a finalised or sent document can no longer take it. The same way a document or receipt you may change
offers *Summarise with an agent* in the document sheet (only agents that see the file); the summary taken over shows
there. Kalmido itself never runs a language model for this: the agent connected to Kalmido words the text.

## Recipient and client names

*Since 2.97.0.*

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

## Trial documents

*Since 2.144.10.*

To try the office out without touching the real number ranges, switch on **"Just to try"** when creating a document:
the dialog of "New quotation", of "New invoice" ("Empty invoice") and of "Invoice from time entries" has this switch. It
is off by default and the focus sits on "Create", so Enter creates a real document as before.

A trial document

- takes a number of its own range `TEST-001`, `TEST-002`, ... (one range per organisation or personal office, for all kinds);
  the real ranges keep counting without gaps;
- prints a large watermark "MUSTER" on every page and never becomes an e-invoice;
- stays out of bookkeeping, exports, VAT, figures and reminders; documents made from it (invoice, credit note, reminder,
  delivery note, progress invoice, document from a template) are trial documents too;
- can be deleted by an admin at any time, also when it is finalised, sent, accepted or signed (the question reads
  "Delete trial document?"). A person without an organisation is the admin of the personal office.

The lists mark trial documents with a small tag "Trial", the editor head as well; documents from templates show the same
tag. As soon as the office has trial documents, the list gets a filter "All / Real only / Trial only" (kept on this
device) and admins see the line "Delete all trial documents": after a confirmation that names the number, all trial
documents of the office go for good, with their payments, share links and stored PDFs. Real documents stay.

A real document cannot be turned into a trial one later, nor the other way round.

The first time someone creates a quotation or an invoice in an office that has no real one yet, the create dialog shows a
hint about "Just to try". It goes away with its X or with "Create" and does not come back for this person and office
(user setting `trial_hint_seen`).

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

(2.113.) In the editor a part opens **in place** on the title page (tap its line under Parts; several may be open at
once). Every part has a colour of its own by its place in the list: a dot on its line and on the title page's line that
uses it, a coloured frame and head ("Part 2 of 3") on the open part. Sent and finalised quotations open the same way,
with locked fields. The unit choice of a position follows its quantity like the PDF does ("1 Day", "5 Days"; decimals
count as plural).

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
The part's name is one source (2.144.9): a rename changes every title page line of the part, and a title page line
(`kind: part`) whose text was changed in `PUT .../items` renames the part; part pages print the name as typed.
`GET /api/office/docs/<id>` carries `parts: [{id, kind, title, print, sort, settings, items, totals, used}]`;
`POST /api/office/docs/<id>/invoice` takes `{parts_mode, parts_title}`. Duplicating copies the parts.

## Invoices and credit notes

(2.38.0, stage 2.) The Quotes & invoices tab lists quotations, invoices, credit notes and reminders (`kind` = `offer`, `invoice`,
`credit`, `reminder`). An invoice starts in one of three ways:

- **from a quotation** ("Create invoice" on the quotation, `POST /api/office/docs/<id>/invoice`): every line of the
  quotation becomes a plain position - the producing, raw data and discount lines the calculator made are condensed
  into positions with their amount, an uncounted raw data option is left out; rights, framework contract text,
  recipient, project title, language, currency and rate, period of service and the PO number are taken over
  (`source_doc_id` points back; the invoice's head names the quotation, "zu Angebot Nr. KV02-MG (20.10.2026)", 2.144.9);
- **from time entries** (`POST /api/office/docs/from-time` with `{client_id, from, to, project_id?}`): the finished time
  entries of the client's lists in the period, one position per list with the hours; the rate is the client's hourly
  rate when set, else 0 to fill in; 2.144.5: each such position remembers its list internally (never in the PDF, the
  e-invoice or an export for the client), so "Delete all times" keeps billed entries after a rename.
  2.144.6: only **billable**, still **open** entries count (each entry has the switch
  *Billable*, on by default; `GET /api/office/time-open?client_id=&from=&to=` shows open / billed / not billable hours
  first). The draft takes them (`billed`): they keep their duration, date and task (only the note can change), cannot be
  deleted and never land on a second invoice, also when two invoices are made at the same moment. The answer's `time`
  says how many entries were taken and skipped. Deleting the draft frees them again; a finalised invoice keeps them,
  also once cancelled - on a cancelled invoice the office admin frees them with *Release the time again*
  (`POST /api/office/docs/{id}/time-release`, undoable). Without an organisation the personal office bills the
  person's private lists the same way;
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
2.152: payments are never deleted. `DELETE .../payments/<pid>` (optional body `{note}` = the reason) books a **reversal**:
a second line with the negative amount on the day of the correction, `reverses_id` = the payment; the list shows both
(the payment marked `reversed`), the balance is right again, the books and the DATEV export see both lines. A reversal
or a payment already reversed cannot be reversed (409).

### Kept by law

*Since 2.152.*

Booked records are locked instead of deleted (section 147 AO, section 257 HGB, section 14b UStG, GoBD): a travel receipt
ticked "in DATEV" or billed on a finalised / sent document cannot be deleted (nor its trip, 409); a receipt of the
document store with a VAT rate or a payment day goes into the trash but is not deleted for good before the end of its
period (8 years from the end of its year; 409 "Kept by law until …"); the undo of an old-invoice import works within 24
hours and only while none of its invoices was edited or marked paid; a client used in quotations, invoices or contracts
is archived instead of deleted (the answer says `archived: true`). No tax advice.
Since 2.186 the lock of a receipt also covers one the cash book books, one of the equipment list (while the item is in
use, else until the end of its useful life plus the period) and one billed on a finalised / sent document; removing its
VAT rate or payment day later (also a bank match taken back) keeps the lock running; a booked receipt never moves into
another workspace (409) and the clean-up of old versions leaves all its versions alone. A client with drives of the
logbook or travel expenses is archived instead of deleted, too.

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

## Progress and final invoices, cash discount

*Since 2.120.*

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

### Suggested payment reminders

*Since 2.147.1.*

Overdue invoices get a reminder **draft** on their own, nothing is sent: once a finalised, open invoice (issued / sent,
an amount outstanding, not paid or cancelled) is more than "Suggest after" days past its due date (setting
`dunning_grace_days`, default 7, 0-90), the watchdog makes one draft per client and currency with the next level (1,
then 2 and 3, each only after the last finalised reminder's deadline -- its date plus its deadline days -- has passed by
those days too), with the office's fee and deadline. An invoice named in a reminder draft waits; an invoice and level are
suggested only once (`office_dunning_marks`), so a draft deleted by hand comes back no sooner than on the next level.
The office's admins (a personal office: its owner) get one task in their inbox with the link, never an amount. The
invoice list shows "N payment reminders suggested" with a jump to the drafts (`GET /api/office/docs` answers
`dunning: {suggested, first}` for the invoice and reminder lists, the drafts carry `suggested: 1`); check and send them
like any reminder. Switch: `dunning_suggest` (default on) in the office settings, section Invoices (admins only).

### GiroCode

*Since 2.147.1.*

Invoices and reminders print a GiroCode (EPC QR code, EPC069-12 version 002: UTF-8, SEPA credit transfer, the BIC
when given, the company name, the IBAN, the amount in EUR and the document number as the remittance) right of the
payment details: the invoice's gross, the reminder's total (the open amounts plus the fee). Only for EUR, a valid IBAN
in the company details and an amount above 0; never on credit notes. It is drawn as vector rectangles (no image), so
the PDF/A-3 of ZUGFeRD stays valid; the e-invoice XML is unchanged. Setting `girocode` (default on); a finalised
document keeps the decision of its finalising day (the stored PDF never changes), documents finalised before 2.147.1 have
none. The print model carries the code's text as `payment.girocode`.

## Invoice series

*Since 2.91.*

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

### DATEV import: master data and opening balances from the tax advisor

*Since 2.148.*

Settings → DATEV → **Read DATEV data** (admins; a personal office: its owner) takes a DATEV file the tax advisor sends
(EXTF, Windows-1252 or UTF-8 with / without BOM, semicolons, CRLF; at most 10 MB and 20 000 rows). The columns are read by
their names in line 2, not by position. A preview comes first (new / updated / skipped with the reason, the first 20
rows); nothing is stored until **Take over**. Every import is a run with **Undo** (the toast, and the list on the import
page).

- **Debtors / creditors** (category 16): a debtor account (ledger length + 1 digits, first digit 1-6) becomes a client
  with that customer number (company or first + last name, address, VAT id from EU country + VAT number, e-mail). A client
  with the same customer number (else the same name without a number) only gets its **empty** fields filled; what differs
  is named in the preview and stays as it is. A creditor account (first digit 7-9) becomes a **supplier** (list under the
  DATEV settings: rename, delete with undo; name, address, VAT id and IBAN are encrypted at rest). The DATEV booking batch
  books a receipt whose sender (else the recognised supplier) matches exactly one supplier's name - compared without legal
  form - on that supplier's creditor account instead of the collective creditor.
- **Booking batch** (category 21): only the opening bookings (account or counter account 9000 / 9008 / 9009, or a booking
  text starting with "EB") become the **opening balances** of their year (shown in the bookkeeping); all other bookings are
  counted and left out - Kalmido is no financial accounting. Importing the same account and year again replaces it (the
  preview says so; undoing the import puts the earlier balance back). An opening booking in a locked month refuses the
  whole file.

Routes (admin, never agents): `POST /api/office/datev/import/check` and `POST /api/office/datev/import` (multipart
`file`), `POST /api/office/datev/import/<run>/undo`, `GET /api/office/datev/suppliers`, `PUT` / `DELETE
/api/office/datev/suppliers/<id>` (`{name}`), `POST /api/office/datev/suppliers/<id>/restore` (deleted suppliers are
removed for good after 30 days), `GET /api/office/datev/opening?year=` (`{year, years, items, debit, credit}`). The import
is in the office log (`import` / `undo`, target `datev_in`).

Settings for all of this (`PUT /api/office/settings`): `invoice_scheme`, `credit_scheme`, `reminder_scheme`,
`payment_days` (14), `reminder_fee` (0), `reminder_deadline_days` (10), `einvoice_format`, `datev_email`, `datev_auto`,
`invoice_closing_de/en`, `reminder_text_de/en` (empty = the country pack's texts).

### Rules the server enforces

*Since 2.38.0.*

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
- Drafts (2.138.2): every PDF of a document that is not finalised and still in status `draft` is marked DRAFT / ENTWURF
  (the document's language) in bold at the number and as a light diagonal word on every page, whichever way it is fetched
  (preview, download, mail, `GET /api/v1/office/docs/<id>/pdf`). A quotation set to sent / accepted / declined without
  finalising is locked as well and prints unmarked (its customer link serves that PDF). A draft has no e-invoice: `GET .../xml` answers 409, a ZUGFeRD draft PDF carries
  no XML. In the app the PDF buttons of a draft ask first: *Finalise now* (the normal finalising, then the PDF) or
  *Show as draft*.

## Terms and conditions as PDF

*Since 2.113.*

*Settings > Terms and conditions (PDF)* holds the office's terms and conditions as a PDF file per language (German,
English) with the date they apply from ("as of"). The admin of the office uploads, replaces and removes them (removing
is one undo step); members see and open them. Each file is stored once by its content (`terms-<lang>-<hash>.pdf` in the
office folder, sealed like the stored documents, part of the backups); an older state is never overwritten, so what went
out with a quotation stays readable.

A replaced or removed state is kept for 30 days (the undo step) and then deleted from the disk, unless a document of the office
(the trash included) names it; the current state is never touched. Quotations, invoices and sent documents keep the state they went
out with. This applies to organisation offices and to the personal office alike.

- **Finalising** a document notes the state of its language (date, SHA-256); a draft follows the current state. A
  quotation prints the line "Es gelten unsere AGB (Stand ...), siehe Anhang." / "Our terms and conditions (as of ...)
  apply, see attachment." - only when terms exist in the document's language (terms in the other language only: no line,
  no attachment). Replacing the terms later does not change a finalised quotation, its line or its attachment.
- **Sending**: finalised quotations can be mailed too (status `sent`). The send dialog has the tick *Attach terms and
  conditions* - ticked for quotations, unticked for invoices, credit notes and reminders - when the document's language
  has terms. The file goes along as `AGB-Stand-<date>.pdf` / `Terms-<date>.pdf`; the log entry "send" names the state
  (language, date, SHA-256) and the document's history shows "with terms and conditions as of ...". The DATEV copy never
  carries them.
- **Approval link**: the customer page of a quotation offers the terms for download next to the PDF
  (`/s/q/<token>/terms`, the same rules as the PDF); the decision record (`signoff_accepted` / `signoff_declined`) names
  the state and the confirmation page says "Terms and conditions as of ...". Contracts and order confirmations made from
  templates keep the state when they are finished and offer it on their signature link (they have no mail dispatch).

Routes (office members read, the office's admin writes; a personal office works the same): `GET /api/office/terms`
(`{terms: {de, en}, admin, max_mb}`), `POST /api/office/terms/<lang>` (multipart `file` - a PDF up to 10 MB - and
`date` YYYY-MM-DD, default today), `GET /api/office/terms/<lang>/file` (`?inline=1`), `DELETE /api/office/terms/<lang>`
(answers `removed` for the undo; the file stays), `POST /api/office/terms/<lang>/restore` `{sha256, date, name}` (only a
state stored in this office) and `GET /api/office/docs/<id>/terms` (the state the document prints / sends, `default` = the
tick of the send dialog; `?file=1` downloads it). `POST /api/office/docs/<id>/send` takes `terms: true|false` (missing =
on for quotations). A document's answer carries `terms` (`{lang, date, sha256, name}` or null).

## Company fields

Settings > Company holds the company as single fields: name, street, postcode, city, country (ISO code), e-mail, phone,
tax number, VAT ID, bank, IBAN (check digits are verified), BIC, register court, register number, managing directors
(table `office_company`, key `company_fields` of `GET/PUT /api/office/settings`). The printed lines are made from them
group by group (address, contact, register, bank and tax); the free lines of the settings stay as the fallback for a group
whose fields are empty, so existing setups print as before. Clients (module "Clients") have folded "Billing details":
street, postcode, city, country, VAT ID, customer number, buyer reference (for example a routing ID), e-mail for
invoices and payment terms in days; the free address stays. These fields are for people only and are not part of agent
answers.

## Approval by the customer

*Since 2.50.0.*

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
project's Share dialog > Public link (*Request acceptance*); the customer's project page shows the open request.
2.99.1: a **video sign-off** (kind `video`, see [TEAM.md](TEAM.md) *Video sign-off*) uses the same link: the page shows the
newest version's player and the customer's comments at a timecode (`POST /s/q/<token>/comments`, limited per client address
and per link, a form check value of its own) and *Approve* / *Request changes*; the decision names the version shown.

## Documents in the customer portal

*Since 2.120.0.*

*Settings > Invoices > Show documents in the customer portal* (off by default) lets clients see their sent quotations,
invoices with the payment state and credit notes in the customer portal; *Send portal link* in the client's menu mails them
the sign-in link. Details: [TEAM.md](TEAM.md) *The customer portal*.

## Documents from templates

*Since 2.93.0.*

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

## Delivery notes and the timesheet

*Since 2.120.0.*

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

## Correspondence: letters

*Since 2.153.0.*

Tab *Correspondence* (admins of the office area; members `403`, agents `403`, another area `404`; a person without an
organisation writes in the personal office). For letters to authorities, insurers, landlords or clients.

**Writing**: *New letter* (from a letter template, optionally for a client: its variables are filled) opens the editor.
The recipient search offers the clients of the office (also with a contact person as "z. Hd.") and the address book
contacts the person sees in the office's space (an organisation's office: the organisation's address books; a personal
office: the private ones). Picking one copies name, address lines and e-mail into the letter; they stay free to edit and
do not change when the client changes later. Further fields: date (today), reference line (e.g. "Your letter of …"),
subject, text (paragraphs separated by an empty line, `-` starts a list item), greeting and name (from the own
*Signature*), *Use the signature picture*, channel (post, e-mail, registered mail with tracking number, fax) and the
follow-up in days. A draft saves itself while typing; *Save* saves at once with an undo step.

**PDF**: DIN 5008 form B like the other office PDFs: letterhead (logo or company name), fold marks, the sender line and
the recipient in the window, the date on the right, then reference line, subject (bold), text, greeting, the signature
picture and the name; following pages with a small head; the footer with the company fields. A draft says *ENTWURF*
(*DRAFT*).

**Sending**: *Mark as sent* asks for the channel (tracking number with registered mail) and the follow-up (suggested: 14
days). The letter is then fixed: its PDF is written once and filed into the office documents space, in the folder of the
client (without a client in the folder *Correspondence*). A change afterwards = *Edit a copy* (a new draft). *Delivered*
marks the arrival (undo possible). *Save as template* makes a document template of kind *Letter* from the text; the tab
*Documents* shows it too. *Delete* archives the letter (undo restores it; a filed PDF stays). The client page lists the
client's letters.

**Signature**: per person and office area a greeting, a name and optionally a picture of the handwritten signature (PNG
or JPEG, at most 300 KB). New letters take greeting and name from it; the picture is only printed in the letters of the
person it belongs to.

Routes (office admins only): `GET/POST /api/office/letters` (`?status=&client_id=&q=&archived=1&brief=1`; `POST` with
`{copy_of: id}`, `{template_id, client_id?}` or `{answers: <document id>}`), `GET /api/office/letters/recipients?q=`,
`GET/PUT /api/office/letters/profile`, `DELETE /api/office/letters/profile/image`,
`GET/PATCH/DELETE /api/office/letters/<id>` (`PATCH` of a sent letter `409`), `POST /api/office/letters/<id>/restore`,
`GET /api/office/letters/<id>/pdf` (`?dl=1` download), `POST /api/office/letters/<id>/sent`,
`POST/DELETE /api/office/letters/<id>/delivered`, `POST /api/office/letters/<id>/template`. Recipient, subject, text,
reference line and the signature picture are encrypted at rest in areas with encryption.

## Access log

Every change and every read of documents and master data is written to the office log (`office_doc_log`): who, when,
what (create, change with the values before and after, positions, number, status, finalise, duplicate, delete, open,
PDF, preview, export, import, logo) and on which document or master data. Repeated reads of the same person within ten
minutes are written once. Organisation admins see the history of a document in its editor ("History") and the latest
entries under Settings > Access log. The log is never part of alerts. An agent token on `/api/office/*` gets `403` without
content; every request of an agent on `/api/v1/office` is one line in the log (2.51.0).

## Letters and incoming documents: reference, history, deadlines

*Since 2.106.*

Letters of the tab "Correspondence" and documents of the documents area can be linked in both directions:

- **Write an answer** at an incoming document (documents area, detail) opens a new letter with the recipient (the
  client whose name is the sender's, with address and e-mail; otherwise the sender's name), the subject "Your letter of
  <date>" and the reference line prefilled, linked as "Answer to". The block "Correspondence" there lists the linked
  letters.
- At a letter, **Choose a reference** links a document of the office's documents space ("Answer to"); after sending,
  **Assign an answer** links the document that answers it. Links can be removed (one undo step each); deleting a
  document only removes the link, a document in the bin is not shown.
- **Reference line (DIN 5008):** made from the answered document: "Your reference" (the sender's "Unser Zeichen",
  "Aktenzeichen", "Az.", "Geschäftszeichen", "Our ref"), "Your message of <date>", "Our reference" (the sender's "Ihr
  Zeichen") and numbers such as policy, customer or tax number. Filled in at a draft without a reference line, or by the
  button "Reference line from the reference".
- **History:** all letters and documents connected over links, in time order; per client all such histories.
- **Deadlines:** a date after "bis zum", "spätestens", "Frist", "no later than", or "innerhalb von 14 Tagen" / "within two
  weeks" counted from the document date, becomes a task with that due date in one click (the document linked in the
  task). Payment terms stay the due date of the documents area. Plain rules, no language model.
- **Follow-up:** a letter sent with a follow-up (e.g. 14 days) that has no answer linked by then gets a task
  "Follow-up: <subject>" in the inbox of the person who wrote it, once. An answer that comes later leaves the task alone.

Rights: admins of the office area (a person without organisation: the own personal office and the own private
documents). A letter links only documents of its office's documents space that the person sees.

## Agents

*Since 2.51.0.*

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

**Letter drafts (2.153.0, #2031).** At an incoming document an admin of the office sees *Let an agent draft the answer*
when the document is shared with at least one agent of the office that has both switches (else, when such agents exist, a
short hint to share the document first; nothing is shared automatically). With several agents you choose one and may add a
note. The agent drafts ONE letter that answers the document (recipient and reference line prefilled, linked to it) and
posts a card in your chat with it (*Open in the office*). You check, sign and send it: an agent never sends, marks as sent
or deletes a letter, and it sees only the letters it made. People's routes: `GET /api/office/letters/doc/<id>/agents`,
`POST /api/office/letters/doc/<id>/ask-agent` `{agent_id, note?}`; agents: docs/AGENTS.md *Letter drafts*.

## Letters by e-mail and text blocks

*Since 2.106.*

A draft letter can go out by e-mail: **Send by e-mail** (only shown when the server has a mail server,
`KALMIDO_SMTP_HOST`) opens a form with the recipient (the letter's e-mail address), Cc, subject and a short covering
text. The letter's PDF is attached, the letter is marked as sent with the channel e-mail. Nothing is sent without this
button; the day's limits of the office mails apply (like invoices).

Answers find their way back: when you have a **document address** for the documents space of this office (Documents >
settings > mail address), the mail carries a reply address of its own that belongs to this one letter (since 2.312, so
the recipient never learns your document address). An answer to it becomes a document in that documents space and is
linked to the letter as its reply; an answer to the document address itself is linked when it names the letter's
Message-ID (In-Reply-To / References). The reply address stops working when the letter is deleted. Only a
letter of the same office (the same organisation, or your personal office) is ever linked. Without a document address
answers go to the company e-mail and are assigned to the letter by hand. A reply without a PDF or image attachment
creates no document (as every mail to the document address).

**Text blocks** are reusable paragraphs per office: **Insert text block** above the letter text opens a searchable list
and puts the chosen block at the cursor. New, change and delete (with undo) in the same list; four samples (cancellation,
objection, payment reminder, request for an extension; German and English) can be taken over. Sample text, no legal
advice. API: `GET/POST /api/office/letter-blocks`, `PATCH/DELETE /api/office/letter-blocks/<id>`, `POST .../<id>/restore`,
`GET .../starters`; `GET /api/office/letters/mail-info`, `GET /api/office/letters/<id>/mail-draft`,
`POST /api/office/letters/<id>/send-mail` (admins of the office, like every letter route).

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

### Own letterhead

*Since 2.120.*

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
- PDF/A: the letterhead's fonts are copied as they are. Export the letterhead with embedded fonts (the default of most
  programs); a letterhead with fonts that are not embedded still prints, but the invoice is then no strict PDF/A file.
- Organisation admins (and a person without organisation in the personal office) upload and change it; members see the
  state and the preview. The file is stored sealed like the documents below `<data>/office/<org_id>/`.

Routes: `GET / POST / PUT / DELETE /api/office/letterhead` (state, multipart `file`, `{m1, m2, hide_head, hide_footer}`
with `m1` / `m2` = `[top, right, bottom, left]` in mm, removal), `POST /api/office/letterhead/restore` (`{file}`: the
previous file again, the undo) and `GET /api/office/letterhead/preview` (the sample as PDF).

## Retention export before deleting an account or an organisation

*Since 2.146.0.*

Invoices and receipts must be kept for 8 years, books (cash book, logs, bank statements) for 10 years. The duty lies with
the person or organisation that issued / received them, not with the server: once an account or an organisation is
deleted, its records are gone. So before that, download the **retention export**: a readable ZIP (no recovery key needed)
with

- `invoices/`: every finalised document as its stored PDF (ZUGFeRD with the XML inside) and the XRechnung XML, rendered
  from the frozen snapshot where an older document has no stored file; the documents, positions, payments, clients and
  company data as CSV;
- `receipts/`: the receipts of the documents space with their files (also those in the trash) and `receipts.csv`;
  `project-receipts/`: the receipt files of lists and projects;
- `cashbook/`: every cash book as PDF and CSV over its whole time (entries, day closings, change log);
- `bank/`, `expenses/`, `archive/`, `logs/` (the office log and the change logs, GoBD) as CSV; `office-files/`: every other
  file of the office folder (archived PDFs, accepted quotations, entertainment bills ...);
- `00-index.txt` (contents, the retention note, files that could not be read) and `manifest.json` (SHA-256 of every file).

Who downloads it: the person themself for their own records (*Office -> Settings -> Data*, also without an organisation)
and the admins of an organisation for its office (*Settings -> Organisation*). Nobody else -- an instance admin neither
(the organisation boundary). The ZIP is streamed, nothing is written to the server's disk; only a download that ran to its
end counts.

Deleting an account (`DELETE /api/users/<id>`) or an organisation (`DELETE /api/admin/orgs/<id>`) that has such records
answers `409` (`code: "retention"`) until the request carries `?retention=exported` (a finished export of that account /
organisation within the last 7 days) or `?retention=waived` (the deleting admin does without it explicitly). Both, and every
finished export, are noted (table `retention_log`) and land in the security log. The delete dialogs ask for this step
first. An organisation admin can no longer delete an account whose personal office holds invoices or a cash book (only the
person can export it; a server admin deletes it after that).

Since 2.186.0 a deletion that **retires** instead (your own server: records still under their legal period, see TEAM.md)
needs neither step and notes no waiver: the records stay. A retired organisation is exported later only by the people who
were its admins when it was retired (*Settings > Organisation*, section of the retired organisation), never by other
server admins. After its period it is deleted without an export step, noted as `expired`.
`GET /api/retention/...` answers `state`: `retire`, `expired` or `null`.

On a hosted instance (`KALMIDO_HOSTED=1`) the keeping lies with the customer: deleting an account with
`?lists=delete` takes its projects with receipts along at once (files included) only after the retention export. After a
waiver they stay in the trash until the legal period of their receipts ends (the end of the year of the latest receipt
plus 8 years, column `lists.retain_until`; nobody can delete them for good before) and the trash run deletes them with
their files after that. On your own server they are still only handed over (receipts are kept).

Routes (people only, an API token 403): `GET /api/retention/me`, `GET /api/retention/me/export.zip`,
`GET /api/retention/org/<id>` (the organisation's admins; an instance admin sees only whether records exist),
`GET /api/retention/org/<id>/export.zip`.

## Database

New tables, all additive and keyed by `org_id` with `ON DELETE CASCADE`: `office_settings`, `office_services`,
`office_equipment`, `office_sets`, `office_texts`, `office_contracts`, `office_numbers`, `office_docs`,
`office_doc_items`. A backup (Settings > Administration > Backup) contains them; an older release runs on with them.
Since 2.36.2 also `office_company` and `office_doc_log`, the columns `locked_at`, `locked_by`, `sender`,
`recipient_snapshot`, `tax_snapshot`, `pack_version`, `service_from`, `service_to` of `office_docs`, `org_id`,
`tax_pct`, `net`, `tax_amount` of `office_doc_items` (positions written without `org_id` get it at the next start) and
the billing columns of `clients` - all nullable or with a default, so the previous release runs on with them.
Unfinished logo uploads (`*.tmp`) are not part of backups.
Since 2.138.1 also `office_undo` (the copies for the editors' undo, see "Undo in the editors"; `org_id` nullable for a
private client, rows live one day); 2.110 runs on with it.
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
Since 2.124.0 also `office_bank_balances` (the balances of an imported statement per import: account, day, amount, kind
open | close; under row-level security, `amount` and `account` encrypted at rest); 2.123 runs on with it.
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

## E-invoices over the Peppol network

*Since 2.154.*

A finalised invoice or credit note can go to the client over the Peppol network -- through **your own account** at a Peppol
access point provider. Kalmido is no access point and charges nothing for it; the provider bills you directly (per document
or as a package, see its price list). Nothing is sent before you set it up, and you can stop using it at any time.

**Set up** (Office -> Settings -> Invoices -> *E-invoices over the Peppol network*; admins of the office area, without an
organisation you yourself): choose the provider, enter the API key from your provider account (stored sealed with the
server key, never shown again; a new provider or address drops it unless you enter a new one), *Test mode* while you try it
with a sandbox key, and your own Peppol ID. **Check connection** asks the provider with the key (nothing is sent).

- *Storecove*: the account ID is the id of your company there (legal entity). Kalmido hands the UBL file over for sending
  (`document_submissions`, the raw document parsed by the provider), asks before sending whether the recipient is
  reachable (`discovery/receives`) and reads the delivery evidence when you refresh the status. Storecove reports a
  rejection or a failed delivery only through a webhook, which Kalmido does not receive: such a send stays *Sent over
  Peppol*, and the Peppol view says so - check the status with the recipient or in your Storecove account.
- *Own endpoint (URL)*: any bridge to an access point (your own one, another provider's API behind a small adapter) that
  speaks this protocol, `https` (plain `http` only for a host the instance admin allowed like a calendar host); every call
  carries `Authorization: Bearer <API key>`:

| Call | Answer |
|---|---|
| `GET <url>/check` | `200` when the key is accepted |
| `GET <url>/participants/<scheme>:<id>` | `{"reachable": true\|false}` (`404` = not reachable) |
| `POST <url>/documents` -- body: the UBL (`application/xml`), headers `X-Peppol-Sender`, `X-Peppol-Receiver` (`<scheme>:<id>`), `Idempotency-Key` (the same key = the same document, never send twice), `X-Peppol-Test` (`1` in test mode) | `{"id": "<your reference>", "status": "sent\|delivered\|rejected\|error", "message": "..."}` |
| `GET <url>/documents/<id>` | `{"status": "...", "message": "..."}` |

**Peppol IDs** are written `<scheme>:<number>` with the ICD / EAS code of the scheme: `0088` GLN, `0208` Belgian enterprise
number, `9930` German VAT ID (`9930:DE123456789`), `0204` Leitweg-ID, `0192` Norwegian organisation number, `0106` Dutch
KvK number and the other codes of the EAS list. Unknown codes and numbers with a wrong check digit (0088, 0208, 0192) are
refused. Your own ID is proposed from the company's VAT ID, the client's in the send dialog from its VAT ID where that is
unambiguous (Germany -> 9930, Belgium -> 0208); the client's ID is the field *Peppol ID* in its billing details.

**Send**: the menu of a finalised invoice / credit note -> *Send e-invoice over the Peppol network*. The dialog names what
is still missing (setup, your ID, the client's ID), checks that the recipient is reachable and sends the UBL e-invoice
(Peppol BIS Billing 3.0; a document in the XRechnung format as XRechnung UBL). The document is then *sent*, the office log
has the entry, and the status (sent, delivered, rejected with the reason, failed) is fetched when you open the dialog or
press *Refresh* -- nothing polls in the background. A document goes out once: a second send is refused unless the last one
failed or was rejected (then *Send again*, after checking with the provider). Peppol needs a buyer reference or an order
number; without them the client's customer number stands in. Agents read the status in the document (`peppol` in
`GET /api/v1/office/docs/{id}`) but never send. Receiving invoices over Peppol is not part of 2.154.

The UBL file of any finalised invoice / credit note is also downloadable (`GET /api/office/docs/<id>/ubl`, menu
*E-invoice UBL (Peppol)*): with the Peppol IDs when they are set, else the e-mail addresses as electronic addresses.

## Validators

Two real validators run in CI (job "E-invoice validators", blocking) on the files `tests/office_einvoice_test.py` writes
to `tests/.data/einvoice/`: veraPDF (PDF/A-3b, Docker image `ghcr.io/verapdf/cli`) for the PDFs and the KoSIT validator
(Java 17, the release jar plus the XRechnung scenario configuration, both downloaded once with their SHA-256 checked and
cached) for the XML -- the configuration validates XRechnung files against the XRechnung rules and plain EN 16931 files
against the EN 16931 Schematron. 2.154.0: the UBL files of `tests/p2154_b_ubl_test.py` as well (EN 16931, XRechnung UBL and
Peppol BIS Billing 3.0 -- the latter with the OpenPeppol rules `PEPPOL-EN16931-UBL`, taken from the phive rules jar on Maven
Central with its SHA-256 checked; `tools/kosit_peppol_scenarios.py` adds their scenarios to the configuration). Locally:

```
python3 tests/office_einvoice_test.py
python3 tests/p2154_b_ubl_test.py
tools/einvoice_validate.sh tests/.data/einvoice/*.pdf tests/.data/einvoice/*.xml
```

The script needs Docker (veraPDF) and Java 17 or newer (KoSIT); it keeps the downloads in `~/.cache/kalmido-validators`
(`KALMIDO_VALIDATOR_CACHE`) and writes the KoSIT reports to `reports/` there. Any file of your own installation can be
checked the same way (download the PDF / XML of a finalised invoice and pass it to the script).

More national e-invoice formats are welcome as pull requests with an official validator run in CI; see
[CONTRIBUTING.md](../CONTRIBUTING.md), *Contributing national e-invoice formats*.
