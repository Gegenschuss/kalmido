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

After changing `app.py` or anything in `static/`, rebuild: `docker compose up -d --build`. The browser
caches the app shell through the service worker; bump `CACHE` in `static/sw.js` when you change static files,
or use a private window.

Layout:

| Path | |
|---|---|
| `app.py` | the whole server: Flask routes, SQLite schema + migrations, watchdog thread (reminders, pushes) |
| `static/app.js` | the whole web app (vanilla JavaScript, no framework) |
| `static/i18n.js`, `static/i18n/*.json` | translation helpers and translations (English is the source language in the code) |
| `static/app.css`, `static/sw.js` | styles, service worker (offline app shell) |
| `tools/i18n_check.py` | translation checker |
| `tests/` | test suites, see [tests/README.md](tests/README.md) |
| `VERSION` | the released version (semantic versioning) |

## Tests

```sh
cd tests && pip install -r requirements.txt && npm ci && BUILD=1 ./run_all.sh
```

CI runs the same suites on every push and pull request, plus `python -m py_compile`, `node --check`,
`tools/i18n_check.py`, `bandit`, `pip-audit`, `semgrep` and a ZAP baseline scan. Please add or extend a
test for what you change; security fixes need a regression test in `tests/security_test.py`.

## Translations

User-facing strings go through `tr('English text')` / `trn(one, other, n)` in `app.js` and `tr()` in
`app.py`; every other language is one JSON file. `python3 tools/i18n_check.py` must report 100 % for every
included language (German is maintained by the author; please add the German text if you can, otherwise say
so in the pull request). Adding a language: see [TRANSLATING.md](TRANSLATING.md).

## Code style

- Keep it small and dependency-free: no frameworks, no bundler, no new Python dependencies without a very good
  reason (every dependency is a security and maintenance cost for self-hosters).
- Python: standard library style, 120 columns, parameters for every SQL value, `tr()` for messages.
- JavaScript: plain ES2020, `esc()` for everything that goes into HTML, no inline event handlers (the CSP
  forbids them).
- Migrations are additive and run on start (see `MIGRATIONS` / `init_db` in `app.py`); never break an
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
