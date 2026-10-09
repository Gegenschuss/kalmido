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

## Number scheme

Placeholders: `{yyyy}` `{yy}` year, `{seq}` or `{seq:03}` the counter (zero-padded to the given width), `{project}`,
`{client}`, `{date}` (`yyyymmdd`), `{initials}`. Default `KVA-{yyyy}-{seq:03}` -> `KVA-2026-001`. The counter runs per
organisation, document kind and period: with `{yyyy}` / `{yy}` in the scheme it starts again every year, without it
never. A number is reserved once and never reused.

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

Minimal file:

```
{"kalmido_office": 1,
 "services": [{"name_de": "Kamera", "name_en": "Camera", "category": "Video", "unit": "day", "daily_rate": 980, "tax": "standard",
               "raw_fee": 1, "producing": 1}],
 "equipment": [{"name": "Kamera-Set A", "category": "Kamera", "daily_rate": 250}],
 "texts": [{"kind": "rights_time", "key": "unlimited", "text_de": "unbegrenzt", "text_en": "in perpetuity"}]}
```

Tables and keys: `services` (name_de, name_en, category, sort, unit, daily_rate, hourly_rate, raw_fee, producing, intext,
role, tax, archived), `equipment` (name, category, daily_rate, archived), `sets` (name, discount_pct, items
[{equipment_id, qty}], archived), `texts` (kind, key, text_de, text_en, sort, archived), `contracts` (name, date,
raw_included, rights_time_id, rights_territory_id, rights_media_id, rights_note_de, rights_note_en, closing_de,
closing_en, rates {service_id: rate}, note, archived), `settings` (the keys of the settings tab).

## Web API

All routes require a signed-in person with the module on and an organisation (`400` with a hint otherwise); writes
need the organisation's admin. `GET/PUT /api/office/settings`, `GET /api/office/packs`, `GET /api/office/packs/<code>`,
`POST /api/office/packs/validate`, `GET /api/office/number-preview?scheme=`, and for each of `services`, `equipment`,
`sets`, `texts`, `contracts`: `GET /api/office/<kind>?q=&archived=1`, `POST /api/office/<kind>`,
`GET/PATCH/DELETE /api/office/<kind>/<id>` (delete archives a row that documents, contracts or sets still use).
`GET /api/office/export`, `POST /api/office/import?overwrite=1` (JSON body or multipart `file`). Documents: see
`/api/office/docs` below.

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
print model as JSON: all texts, labels and amounts already in the document's language and format).

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
