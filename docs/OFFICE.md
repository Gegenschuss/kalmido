# Office & finance

The module **Office & finance** (`office`) turns an organisation's Kalmido into a small back office: master data
(services, equipment, text blocks, framework contracts), quotations with a calculator that follows the usual rules of a
media production (producing days, raw data, discount, transfer of rights) and a PDF of every document. Invoices,
e-invoices and bookkeeping exports are planned for later stages.

The module lives in the business area only: a person needs the module switched on (Settings > Modules > Office &
finance, or the setup purpose "Office & finance") **and** a membership in an organisation. Everything the module stores
belongs to that organisation; people of another organisation never see it. Agents (AI assistants with a token) and child
accounts have no access at all in this stage - there is no `/api/v1` route and no MCP tool for the module yet.

## Roles

| Who | May |
|---|---|
| Organisation admin | module settings, master data, framework contracts, logo, import, delete documents |
| Organisation member | read master data and settings, export the master data file, create / edit quotations, PDF |
| Agents, children | nothing (403) |

Which organisation you work in follows the workspace switch at the top of the sidebar (`org:<id>`); people in exactly one
organisation need not choose.

## Tabs

- **Quotations** - the documents (number, recipient, project, date, net total, status) and the editor.
- **Services** - what you sell: name in German and English, category (free text such as Video, Audio, Office), unit
  (day, hour, piece, minute, flat), daily and hourly rate, tax class (standard, reduced, exempt), the flags "raw data fee"
  (the position counts towards the raw data amount) and "producing" (the position's quantity counts towards the
  producing days), internal / external, role. Search box, archive.
- **Equipment** - devices with a daily rate, and **sets** (a bundle of devices with a discount in percent).
- **Text blocks** - reusable texts in German and English, grouped by kind: the rights catalogue (`rights_time`,
  `rights_territory`, `rights_media`), introduction, closing, note, free block between positions, raw data note.
  The first call of the module copies the country pack's catalogue into the organisation's text blocks.
- **Framework contracts** - one per agency or client: date, raw data included, default rights (three catalogue entries),
  rights note, closing text, special rates per service. A document can pick a contract and deviate from it.
- **Settings** - company name and address lines, contact / register / bank lines (printed in the footer), logo,
  brand colour (accent in the print only), document language (de / en), currency (EUR / USD + rate), number scheme with
  a live preview, producing quotient and rate, raw data factor, days a quotation stays valid, default text blocks,
  default rights, country pack with its tax rates, and the import / export of the master data.
  Since 2.40 producing (a markup by production days) and the raw data surcharge are switches per organisation
  (`producing_on`, `raw_on`): new organisations start without them; at the first start of 2.40 an organisation that uses
  them (services, positions, contracts with raw data included) keeps both on, once, so switching off later stays off.
  Off means: no automatic producing / raw data line in new quotations (raw data "none"), the flags of the catalogue are
  not taken over, the fields, flags and the contract's "raw data included" are hidden, the spreadsheet import ignores
  those columns; existing and finalised documents keep what they hold. The company data choose the word before the
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
on a pack you paste, a dry run for community packs; installing foreign packs is a later stage).

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
role, tax, archived), `equipment` (name, name_en, category, daily_rate, archived), `sets` (name, discount_pct, items
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
  rows like `---- VIDEO ----` are the category of the rows below, not services. `Staff` and `Freelancer` are only counted:
  Kalmido has no master data for them yet.
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
  0600, part of every backup) and is never re-rendered, renumbered, sent or turned into an e-invoice. The documents tab
  lists it under "Archive" with the sum of the archived invoices and of the paid ones; the other lists and the reminders
  do not count it. 2.40.0: Kalmido also reads the recipient's address from the text layer of page 1 (not the own sender
  line; split like a spreadsheet address, unsure splits marked) and proposes, each only with a tick: a new client (no
  client matches), a contact person for a client that has another one, a note when the address differs from the client
  card. A scan without text gets a hint - there is no text recognition. The archive file is written only after the
  database commit.
- **Numbers**: an archived number is never given to a new document (the automatic number skips it, a manual one is
  refused). The import page proposes to continue the invoice / quotation counter after the highest archived number (a
  number that follows today's scheme, else the project number of the file name); the person confirms, the counter is
  never lowered.
- **Undo**: every confirmed import is a run (list with date, person, count). Undoing removes what the run added unless
  something builds on it by now - a client with a list, document, framework contract or archived document of another run
  stays, as does a service used in a document or as the producing rate, and equipment in a set; the answer says what
  stayed. Fields a merge filled are emptied again while they still hold the imported value.

Routes (organisation admin; members only read the archive): `POST /api/office/legacy/preview` (multipart `file`, stores
nothing), `POST /api/office/legacy/split` `{address}`, `POST /api/office/legacy/import` `{clients, services, equipment}`
(the preview's rows with `action` new / merge / skip and `merge_id`; 2.46.1: `areas` = only these of clients / services /
equipment, the others are neither written nor checked), `GET /api/office/legacy/runs` (2.46.1: a data run lists its
`areas` with `count` and `undone_at`), `POST /api/office/legacy/runs/<id>/undo` (2.46.1: `{kinds: [...]}` undoes only these
areas of a data run, `409` for an area undone already; the whole undo afterwards takes the areas left), `POST /api/office/legacy/archive/parse` `{names}`,
`POST /api/office/legacy/archive/run`, `POST /api/office/legacy/archive` (multipart `file` + `run_id`, `kind`, `number`,
`project_no`, `project`, `client_id`, `client_name`, `date`, `amount`, `paid`; 409 for a used number or the same PDF
twice), `GET /api/office/legacy/archive?kind=`, `PATCH /api/office/legacy/archive/<id>` (only `amount`, `paid`,
`client_id`), `GET /api/office/legacy/archive/<id>/pdf`, `GET/POST /api/office/legacy/counter` `{kind, last}`.
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

## Web API

All routes require a signed-in person with the module on and an organisation (`400` with a hint otherwise); writes
need the organisation's admin. `GET/PUT /api/office/settings`, `GET /api/office/packs`, `GET /api/office/packs/<code>`,
`POST /api/office/packs/validate`, `GET /api/office/number-preview?scheme=&kind=offer|invoice|credit|reminder` (the next number, `yearly` = the counter restarts every year, or a plain-language `error`), and for each of `services`, `equipment`,
`sets`, `texts`, `contracts`: `GET /api/office/<kind>?q=&archived=1`, `POST /api/office/<kind>`,
`GET/PATCH/DELETE /api/office/<kind>/<id>` (delete archives a row that documents, contracts or sets still use).
`GET /api/office/export`, `POST /api/office/import?overwrite=1` (JSON body or multipart `file`). Documents: see
`/api/office/docs` below. 2.38.0 adds `POST /api/office/docs/<id>/invoice`, `POST /api/office/docs/<id>/credit`,
`POST /api/office/docs/from-time`, `POST /api/office/docs/reminder`, `GET/POST /api/office/docs/<id>/payments`,
`DELETE /api/office/docs/<id>/payments/<pid>`, `POST /api/office/docs/<id>/send`, `POST /api/office/docs/<id>/datev` and
`GET /api/office/mail-status` (see "Invoices and credit notes" below); 2.40.0 adds `POST /api/office/docs/<id>/fee`
(see "Payments and reminders"). Agents never reach `/api/office/*`.

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

## Invoices and credit notes

(2.38.0, stage 2.) The documents tab lists quotations, invoices, credit notes and reminders (`kind` = `offer`, `invoice`,
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
there (`datev_sent_at`). No credentials, no bookkeeping export (a booking batch export is a later step). Every send is
in the office log (`send`, `datev`), payments as `payment` / `payment_delete`.

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

## Access log

Every change and every read of documents and master data is written to the office log (`office_doc_log`): who, when,
what (create, change with the values before and after, positions, number, status, finalise, duplicate, delete, open,
PDF, preview, export, import, logo) and on which document or master data. Repeated reads of the same person within ten
minutes are written once. Organisation admins see the history of a document in its editor ("History") and the latest
entries under Settings > Access log. The log is never part of alerts. Agents have no access to the module at all: an
agent token on `/api/office/*` gets `403` without content.

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
- The raw data option in its own dashed box below the totals, the transfer of rights as its own section (duration,
  territory, media, exceptions, exclusivity, note), closing text, greeting with the signer's name, an order confirmation
  area (place / date, signature) and a footer in up to four columns (company, contact, registration, bank; empty
  columns are left out). The company colour is the only accent (rules, title underline, category headings).
- Page breaks: following pages carry a small head (logo, title, number, recipient) and repeat the table head; every
  page says "Page x of y"; a category heading never stays alone at the end of a page, text blocks and the rights block
  are not torn, and the totals never stand alone on a page (the last position comes along). No carry-over lines.

Logo: `POST /api/office/logo` (organisation admin, multipart `file`) accepts PNG, JPEG or WebP up to 4 MB, scales it to
at most 1600 px width and stores it as PNG below `<data>/office/<org_id>/logo.png`; `GET /api/office/logo` serves it,
`DELETE /api/office/logo` removes it. For a sharp print upload a PNG at least 600 px wide; SVG is not accepted (the PDF
writer has no SVG renderer). The folder is part of the backups and restores like the attachments. Internal figures
(costs, margin) are never printed.

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
