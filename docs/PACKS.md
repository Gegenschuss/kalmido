# Pack catalogue (technical, 2.76)

Country packs (tax rates, formats, labels, default texts; see [OFFICE.md](OFFICE.md#country-packs)) and industry packs
(the shoot calculation, see [OFFICE.md](OFFICE.md#shoot-calculation-and-industry-packs)) ship with the app. Since
2.76 an office admin can also search a **pack catalogue** and install further packs - or newer versions of the shipped
ones - into their office area (an organisation, or the personal office of a person without one). This page is for
operators and for people who publish packs. How it looks in the app: *Office & finance > Settings > Packs*
([OFFICE.md](OFFICE.md)).

A pack is **data, never code**: the same JSON format as the shipped files, checked by the same validators. Kalmido never
runs anything from a pack.

## Setting up a catalogue

Two environment variables of the server (see [SELF-HOSTING.md](SELF-HOSTING.md#office-pack-catalogue)):

| Variable | Meaning |
|---|---|
| `KALMIDO_PACKS_CATALOG` | Address of the index file, `https://.../index.json`. Empty (default) = only the shipped packs, **no network access at all**. |
| `KALMIDO_PACKS_ALLOW_HOSTS` | Hosts (`host`, `host:port`, `[v6]:port`, comma separated) that may be internal addresses and may use `http://` - an own mirror in the local network. |

The index is fetched when somebody opens the Packs section, at most once an hour per server process (the *Refresh*
button of an admin fetches it again). Pack files are fetched only when an admin installs or updates a pack.

## Index format

```json
{"format": 1, "name": "Kalmido packs", "updated": "2026-10-17",
 "packs": [{"kind": "country", "code": "AT", "name": {"de": "Österreich", "en": "Austria"},
            "description": {"de": "Short text, *simple* Markdown", "en": "..."}, "author": "Name or group",
            "license": "CC0-1.0", "verified": false, "homepage": "https://example.com/at",
            "versions": [{"version": 2, "url": "https://example.com/packs/country/at-2.json", "sha256": "<64 hex>",
                          "size": 12345, "released": "2026-10-17", "min_app": "2.76.0",
                          "changes": {"de": "...", "en": "..."}}]}]}
```

- `kind`: `country` or `industry`. `code`: country = two upper-case letters, industry = lower-case letters, digits and
  `_` (2-31 characters, starting with a letter).
- `version`: an integer >= 1, the field `version` inside the pack file. `url`: absolute, `https://` (`http://` only for a
  host in `KALMIDO_PACKS_ALLOW_HOSTS`). `sha256`: of the raw bytes of the file. `size` (optional): its length in bytes.
  `min_app` (optional): the oldest Kalmido version that may install it; newer versions are listed but not offered.
- Texts may be one string or `{de, en}`. They are cleaned when read: control characters and anything in `<...>` are
  removed; at most 80 characters for `name`, 1000 for `description`, 500 for `changes`, 120 for `author` / `license`.
  `description` and `changes` are shown with simple Markdown (bold, italics, lists), always as escaped text.
  `homepage` is kept only when it is `https://`.
- Unknown fields are ignored. An invalid entry (or version) is skipped on its own; the app shows how many were skipped.
- Limits: index at most 1 MiB and 500 packs, 20 versions per pack; a pack file at most 512 KiB; 10 s per fetch.

Example (the two shipped packs, made with the tool below): [packs/index.example.json](packs/index.example.json).

## Badges

- **Verified** - the entry says `"verified": true` **and** the pack file does not say `"community": true`. Meant for
  packs a maintainer of the catalogue has checked.
- **Community** - everything else. Installing a community pack needs an explicit confirmation of the admin (the app shows
  a warning: tax rates and texts are not checked by the Kalmido team).
- **Built in** - shipped with the app (always verified).

## What an installation checks

1. The pack is in the index with exactly that `kind`, `code` and `version` (404 otherwise).
2. The file is fetched through the same guard as calendar subscriptions: every resolved address must be public (unless
   the host is allowed), redirects are followed by hand and never from `https` to `http` or to an address that is not
   allowed, at most 512 KiB, 10 s.
3. SHA-256 and size match the index; the file is a JSON object; `code`, `kind` and `version` match the entry; `min_app`
   is not newer than the running app; the validator of the pack kind passes (country: `office_pack_validate`, industry:
   `dk_pack_validate`) - which also refuses markup (`<...>`, `javascript:`) in any text. Control characters are removed.
4. Community packs: the admin confirmed.

Anything that fails: nothing is stored, the admin sees the list of problems (422).

## Storage, resolution and documents

- Table `office_pack_installs` (one row per installation; `org_id` = the office area, row-level security). The pack is
  stored as checked JSON together with its checksum, badge, the cleaned catalogue entry and the catalogue host.
  Uninstalling sets `removed_at`; *Undo* makes the row active again. At most one active row per area, kind and code.
- When the office settings of an area are read, the area's installations are bound to the request. The country pack
  and industry pack lookups then see those installations first and the shipped files second - an installed `DE` v2
  replaces the shipped `DE` **only in that area**; uninstalling goes back to the shipped one. Another area never sees
  them.
- An installation cannot be removed while it is the country pack of the office, switched on in the calculation rules,
  or used by an open quotation - unless a shipped pack of the same code takes over.
- **Finalised documents never change.** Finalising stores a snapshot of the pack (rates, labels, texts, formats) in the
  document, now with `pack_sha256` and `pack_source` (`builtin` or the catalogue host). Updates and uninstalls do not
  touch finalised documents, their PDF or their e-invoice.
- Every install, update, restore and uninstall is written to the office log (`pack_install`, `pack_remove`).

## Routes (web app, signed in)

All behind the office gate: session only (no agent tokens, no kids accounts), the feature *Office* on. Reading = any
member of the office area, writing = its admin. There is no REST API / MCP tool for packs.

| Route | |
|---|---|
| `GET /api/office/packs` | country packs of my area (+ `source: builtin\|installed`, `badge`) and `industry: [{code, name, name_en, version, badge, source}]` |
| `GET /api/office/catalog?q=&kind=` | the catalogue merged with the shipped and installed packs: `{configured, source, fetched_at, error, skipped, can_manage, items: [...]}` |
| `POST /api/office/catalog/refresh` | admin: fetch the index again (answer as above) |
| `POST /api/office/packs/install` | admin: `{kind, code, version, accept_community}`; also the update (another version replaces the installed one) |
| `DELETE /api/office/packs/installed/<kind>/<code>` | admin: uninstall (409 with the reason while it is in use) |
| `POST /api/office/packs/installed/<kind>/<code>/restore` | admin: undo of an uninstall |

Each catalogue item also carries `in_use` / `in_use_text` (why it cannot be uninstalled now) and `affects` /
`affects_text`: how many open (not finalised) documents an update or uninstall of the pack in effect would recalculate
- a hint for the confirmation, never blocking. The organisation export contains the installed packs (`office/pack-installs.json`).

## Security model

What the catalogue code defends against:

- **Server-side requests into the local network** (SSRF, DNS rebinding): every connection goes to an address that was
  resolved and checked right before (private, loopback, link-local, CGNAT, multicast, reserved, IPv4 inside IPv6 are
  refused); redirects are re-checked; `https` only unless the operator allows a host.
- **Large or slow answers**: size limits before and while reading, timeouts per fetch.
- **Changed or swapped files**: the SHA-256 of the index entry must match the downloaded bytes; code, kind and version
  inside the file must match the entry (a file cannot pose as another pack).
- **Markup and scripts**: refused in pack texts, removed from catalogue texts; the client prints catalogue texts as
  escaped text.
- **The boundary between organisations**: installations belong to one office area (row-level security, every query by
  `org_id`); installing needs the admin of the area the person works in; the lookup only ever sees the bound area.
- **Agents and kids accounts**: refused by the office gate.

The catalogue itself is trusted only as far as its operator: whoever controls the index decides which files and
checksums are offered. Use a catalogue you trust, or run your own mirror.

## Building a catalogue

`tools/packs_catalog.py` builds the index from a folder of pack files and checks every file with the validators of the
app:

```
packs/
  country/de.json            or  de-2.json (version in the name)
  country/meta.json          {"DE": {"description": {"de", "en"}, "author", "license", "verified": true, "homepage",
                                     "min_app", "released", "changes": {"2": {"de", "en"}}}}
  industry/film.json
  industry/meta.json
```

```
python3 tools/packs_catalog.py packs https://example.com/kalmido-packs --updated 2026-10-17 > packs/index.json
```

The file `packs/country/de.json` is then expected at `https://example.com/kalmido-packs/country/de.json`. A file that
fails the check stops the run with its problems (exit code 1) - run it in the CI of the catalogue repository. Publish
the folder on any static https host (for example GitHub Pages) and set `KALMIDO_PACKS_CATALOG` to the address of
`index.json`.

An own mirror: copy the published folder to a host in your network, build the index again with your base address, and
set both variables (`KALMIDO_PACKS_ALLOW_HOSTS=mirror.example.com:8080` when it is internal or http).

## Own packs of an instance

*Since 2.138.1.*

Besides the shipped packs (`kalmido/office/packs/industry/*.json`) and the catalogue, an instance can load its own
industry packs from its data folder: `<data folder>/packs/industry/<code>.json` (the folder next to the database,
`/data/packs/industry/` in Docker). Such a file is checked like a shipped pack (same validator, at most 512 KB, the code
must match the file name) and then appears in the office settings like any other industry pack (source "local"). A file
whose code is the code of a shipped pack is refused (log line `own industry pack <code> refused: ...`), the shipped pack
stays. A changed file is read again at the next request; it never lands in the repository. This is the place for packs only one business needs (own rates, own wording).

### Calculation options of an industry pack (`calc`, optional)

```json
"calc": {
  "share":    {"label": {"de": "...", "en": "..."}, "rate": 500, "factor": 0.5},
  "handling": {"label": {"de": "Handlungskosten", "en": "Handling costs"}, "pct": 4, "on": true},
  "markup":   {"label": {"de": "Markup", "en": "Markup"}, "pct": 10, "on": false, "stacked": false}
}
```

- `share` ("share by amount"): a line computed from the amount (net, quantity x rate, before discount, without raw data)
  of the positions marked for it: amount / day rate x factor, rounded to half days, times the day rate (amount and rate
  in the document's currency). `rate` > 0, `factor` 0.01..10. The office settings may set their own day rate / factor.
- `handling`: a percentage (0..100) on the positions marked "in handling costs".
- `markup`: a percentage on the positions marked "in markup"; `stacked` = also on the handling costs.
- Order in a quotation: positions, share, handling costs, markup, then discount (positions only) and raw data as before.
- Only when a pack switched on offers an option does a new quotation get it (switch, fields, marks per position). Each
  quotation keeps its own values and can rename the line titles. Quotations made before keep their calculation, also
  when a pack is switched off later. The shipped pack "Film & Video" offers handling costs (4 %, on) and markup (10 %, off).

## Building a country pack for your country

*Since 2.147.*

The shipped international base pack (`kalmido/office/packs/xx.json`) is the best starting point: copy it to
`<code>.json` (two upper-case letters, ISO 3166), set `code`, `name`, `name_en`, remove `neutral`, and fill in:

- `tax`: the rates of your country (`standard`, `reduced`, `exempt` = 0) and their labels in German and English; keep
  `editable: true` only when offices must set their own rates
- `formats`, `labels`, `texts`, `numbering`: how documents look and read in your country (both languages, plain text)
- `einvoice.formats`: the e-invoice formats you can vouch for (`zugferd` = EN 16931 / Factur-X; `xrechnung` is German)
- `features`: only the functions that are correct for your country, each `{"status": "ready"}` (or `planned`). Known keys:
  `books.datev`, `docs.einvoice`, `books.vat_return`, `books.tax_dates`, `books.export_csv`, `books.gobd` (`money.cashflow`,
  `money.kpi`, `money.travel`, `money.meals`, `money.subs` are offered by every pack, since 2.380); planned for
  later packages: `books.receipt_images`, `books.period_lock`, `books.procedure_doc`. Unknown keys fail the check.
- `retention`: years for receipts and books, the legal minimum as `min_years`

Check the file with `POST /api/office/packs/validate` (or `tools/packs_catalog.py`) and publish it in a catalogue (see
above). Ideas the community could take on - none of them is built yet: **Austria** with a BMD export, **France** with
the FEC file (fichier des écritures comptables). Such an export needs code in the app; the pack then names it as a
function, the way `DE` names `books.datev`.

