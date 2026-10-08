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

CI runs the same suites on every push and pull request, plus `python -m py_compile`, `node --check`,
`tools/i18n_check.py`, `bandit`, `pip-audit`, `semgrep` and a ZAP baseline scan. Please add or extend a
test for what you change; security fixes need a regression test in `tests/security_test.py`.

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

## Pull requests

- One topic per pull request, with a short description of the *why* and how you tested it.
- CI must be green (tests, i18n, scanners).
- Update the README when behaviour changes, and add a line to the *Unreleased* section of
  [CHANGELOG.md](CHANGELOG.md) if you like (the maintainer adds it otherwise).
- Sign off every commit (`git commit -s`), see *License of contributions* below.

## License of contributions

Kalmido is licensed under the [GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0). Contributions are
accepted under the same license.

- **Developer Certificate of Origin.** Sign off every commit with `git commit -s`. The `Signed-off-by:` line
  certifies that you wrote the change or otherwise have the right to submit it, as stated in the
  [Developer Certificate of Origin 1.1](https://developercertificate.org/).
- **Additional license grant.** By submitting a contribution you also grant the maintainer (the copyright holder named in
  LICENSE) the
  right to license your contribution under other terms, including commercial licenses. The AGPL-3.0 version
  stays available to everyone.

Security problems: please report them privately, see [SECURITY.md](SECURITY.md). General contact:
hello@kalmido.com.
