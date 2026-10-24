# Contributing

Thanks for taking a look. Bug reports, translations and small, focused pull requests are very welcome.

## Development setup

Everything runs in Docker; there is no build step.

```sh
git clone https://github.com/Gegenschuss/kalmido.git
cd kalmido
cp .env.example .env
docker compose up -d --build        # http://127.0.0.1:3040
```

After changing the server (`app.py`, `kalmido/`) or anything in `static/`, rebuild: `docker compose up -d --build`. The browser
caches the app shell through the service worker; bump `CACHE` in `static/sw.js` when you change static files,
or use a private window.

Layout (the full map, the data flow and how to add a route or a file: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)):

| Path | |
|---|---|
| `app.py` | the entry point (`python app.py`, `set-password`, `import`) |
| `kalmido/` | the server: one module per area (Flask routes, SQLite schema + migrations, background threads), loaded in the order of `kalmido/__init__.py` |
| `static/js/*.js` | the web app (vanilla JavaScript, no framework, no build step): classic scripts loaded in the order of `static/index.html` |
| `static/i18n.js`, `static/i18n/*.json` | translation helpers and translations (English is the source language in the code) |
| `static/app.css`, `static/sw.js` | styles, service worker (offline app shell) |
| `tools/i18n_check.py`, `tools/check_layout.py` | translation checker, module lists checker |
| `tests/` | test suites, see [tests/README.md](tests/README.md) |
| `VERSION` | the released version (semantic versioning) |

## Tests

```sh
cd tests && pip install -r requirements.txt && npm ci && BUILD=1 ./run_all.sh
```

CI runs the suites in two stages, plus `python -m py_compile`, `node --check`, `tools/i18n_check.py`, `bandit`,
`pip-audit`, `semgrep` and a ZAP baseline scan: every push and pull request runs the push stage (all security, rights,
tenant, organisation and freelancer suites, the core flows and the suites of the areas the change touches); the nightly
run, a release (a change of `VERSION`), a change of the CI files and a commit message with `[full]` run every suite.
`python3 tests/stages.py --why --changed origin/main` shows the stage and the suites of your branch. Please add or extend
a test for what you change; security fixes need a regression test in `tests/security_test.py`.

- **Only some suites:** `ONLY="api security" ./run_all.sh` runs just the named suites (the names after `run` in
  `run_all.sh`; the test containers of their groups are still started). Run the suites you touched while you work and
  the full run once before the pull request.
- **bandit locally**, as CI does: `pip install bandit && bandit -q --severity-level high -r app.py kalmido tools`.
- **Push tests** (`webpush`, `webpush_ui`) decrypt the payloads with `http-ece` from `tests/requirements.txt`;
  install that file, not only `requests`.
- **Close headless browsers.** UI tests and your own checks with a headless browser must close it at the end (also on
  errors, e.g. in a `finally`); left-over browser processes slowly fill memory and swap.

## Translations

Kalmido ships in English (the source), German (maintained by the author) and, since 2.11.0, French, Spanish, Italian
and Dutch. Those four are machine-translated and marked *Beta* in the language picker, so **corrections from native
speakers are very welcome**, from a single wrong word to a full review.

How it works:

- Every user-facing string in the code is English and is its own key: `tr('English text')` / `trn(one, other, n)` in
  `static/js/`, `tr()` / `trn()` in `kalmido/` (push notifications, e-mails, error messages, setup).
- Every other language is one file `static/i18n/<code>.json` (`de.json`, `fr.json`, `es.json`, `it.json`, `nl.json`):
  the English key on the left, the translation on the right. `_meta` holds the name shown in the picker, the locale
  for dates and numbers and `"beta": true` for machine-translated files; `_weekdays`, `_months` and `_date_formats` set
  the date labels. Details and the file format: [TRANSLATING.md](TRANSLATING.md).

To **fix a translation**, edit the value in the language's JSON file (never the key) and open a pull request; a
screenshot of where the text appears helps. To **add a language**, copy `de.json` to `<code>.json`, set `_meta`
(with `"beta": true` until a native speaker has reviewed it) and translate every value.

Check your change before the pull request:

```sh
python3 tools/i18n_check.py fr        # one language: 100 %, 0 missing, 0 errors, 0 unused
python3 tests/i18n_test.py            # all languages: keys, unused keys, placeholders, plurals, HTML tags, _meta
node tests/demo_test.js               # the browser demo: build, boot without a server, reload, reset, no network
node tests/quick_lang_test.js         # quick add words in all six languages
```

When you change or add an English text in the code, every language file needs the new key (the checker lists it as
missing); add the German text if you can, otherwise say so in the pull request and the maintainer fills the rest.
A hosted translation platform (such as Weblate) may come later to make reviews easier; until then, pull requests
and issues are the way.

## Code style

- Keep it small and dependency-free: no frameworks, no bundler, no new Python dependencies without a very good
  reason (every dependency is a security and maintenance cost for self-hosters).
- Python: standard library style, 120 columns, parameters for every SQL value, `tr()` for messages.
- JavaScript: plain ES2020, `esc()` for everything that goes into HTML, no inline event handlers (the CSP
  forbids them).
- Migrations are additive and run on start (see `MIGRATIONS` in `kalmido/core/schema.py`, `init_db` in `kalmido/core/db.py`); never break an
  existing database.
- Comments explain *why*; the user-facing behaviour belongs in the README.

## AI-assisted development

Kalmido is built with AI assistance (Claude Code). The owner decides what goes in and uses it every day, and
every change has to pass the test suite. Contributions made with AI tools are welcome under the same rules
as any other: you understand and can explain the change, it has tests, and you have checked the result
yourself. Please mention it in the pull request.

## Packs

Country and industry packs (tax rates, formats, printed words, default texts, calculation defaults) are **data
only** and are meant to be shared through a separate packs repository with a catalogue index, not through this one
(the README names it once it exists; see [docs/OFFICE.md](docs/OFFICE.md), *Packs*, for how an office installs them).

- A pack is one JSON file in exactly the shape of the built-in ones: `kalmido/office/packs/<code>.json` for a country
  (checked by `office_pack_validate`), `kalmido/office/packs/industry/<code>.json` for an industry (checked like
  `film.json`). `POST /api/office/packs/validate` runs the check on a pack you paste. Raise `version` with every change.
- No markup, no scripts, no links that load anything: the texts are printed as they are, and a pack is never code.
- The catalogue entry names the version, the download address (https), its SHA-256 checksum and size, the author and
  the license (CC0-1.0 or another open data license). Kalmido refuses a file whose checksum, size, code, kind or
  version does not match the entry.
- New packs start with the badge *Community*; *Verified* is only given after a review by the maintainers.
- The [CLA](CLA.md) applies to packs as to any other contribution.

Code parts - new e-invoice formats, exports, bookkeeping interfaces, new rules of the calculator - are not packs: they
come as a pull request to this repository, with tests, like any other change.

## Contributing national e-invoice formats

Kalmido writes e-invoices in the formats below. More European (and other) national formats are welcome, as a pull
request to this repository. Formats are code, not packs: they are reviewed, tested and shipped with Kalmido. There are
no scripts or plugins that run on a server, and a format never sends invoice data to a third party.

Formats today (`EIN_FORMATS` in `kalmido/office/einvoice.py`), each with its specification:

- `zugferd`: ZUGFeRD 2.x / Factur-X, profile EN 16931 (UN/CEFACT CII D16B inside a PDF/A-3 file),
  specification: [EN 16931](https://ec.europa.eu/digital-building-blocks/sites/display/DIGITAL/Obligation+to+accept+e-invoices)
  and the [FeRD ZUGFeRD](https://www.ferd-net.de/) documentation, version 2.x.
- `xrechnung`: XRechnung 3.0, the German CIUS of EN 16931 (CII syntax),
  specification: [KoSIT XRechnung](https://xeinkauf.de/xrechnung/) version 3.0.

How the code is laid out:

- `ein_build(model, fmt)` builds the XML from the print model of a finalised document (no database, pure function).
  A new format is a new entry in `EIN_FORMATS` and `EIN_PROFILE` plus its own builder branch or function next to the
  existing ones. Keep amounts as `Decimal` strings, never float.
- `ein_check(xml)` is the plausibility check without a validator; extend it for the new format's mandatory fields.
- The format choice is offered by `epdf_format` in `kalmido/office/pdfweb.py` (the list there must contain the new key).
- `tests/office_einvoice_test.py` writes example invoices to `tests/.data/einvoice/`; add yours there.

What every contribution needs:

1. **Example invoices** in the test: invented companies, people and addresses only (`@example.com`), never real data.
2. **A validator run in CI.** Use the official validator or Schematron of the format, pinned by SHA-256 like the
   existing ones, and call it from `tools/einvoice_validate.sh` so that the `einvoice` job in `.github/workflows/ci.yml`
   (blocking) checks your files. You can run it locally: `tools/einvoice_validate.sh tests/.data/einvoice/*.xml`.
3. **The source of the specification** (link and version) in this section, and the name of the person who maintains the
   format (answers issues and follows new versions of the specification).
4. The checklist *New e-invoice format* of the pull request template.

Countries with clearance or reporting duties over an authority interface (real-time submission) only after agreeing in
an issue first: use the issue template *E-invoice format proposal*. Kalmido does not send invoice data to third
parties without a decision of the project.

## Pull requests

- One topic per pull request, with a short description of the *why* and how you tested it.
- CI must be green (tests, i18n, scanners).
- Update the README when behaviour changes, and add a line to the *Unreleased* section of
  [CHANGELOG.md](CHANGELOG.md) if you like (the maintainer adds it otherwise).
- Sign off every commit (`git commit -s`) and agree to the [CLA](CLA.md), see *License of contributions* below.

## License of contributions

Kalmido is licensed under the [GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0). Contributions are
accepted under the same license, plus the CLA below.

- **Developer Certificate of Origin.** Sign off every commit with `git commit -s`. The `Signed-off-by:` line
  certifies that you wrote the change or otherwise have the right to submit it, as stated in the
  [Developer Certificate of Origin 1.1](https://developercertificate.org/).
- **Contributor License Agreement.** Before a pull request can be merged you agree to the [CLA](CLA.md): you keep
  the copyright, and you grant the maintainer (the copyright holder named in NOTICE) the right to license your
  contribution under other terms as well, including commercial licenses. The AGPL-3.0 version stays available to
  everyone. When you open a pull request, the CLA Assistant bot comments with a link; follow it once with your GitHub
  account. The DCO sign-off above stays required.

Security problems: please report them privately, see [SECURITY.md](SECURITY.md). General contact:
hello@kalmido.com.
