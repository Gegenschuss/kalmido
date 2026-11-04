# About Kalmido

Accessibility, language, technology, limits, how this was built, contributing and the supporter licence.

## Accessibility

Kalmido aims at **WCAG 2.2 level AA**: everything works with the keyboard (one Tab stop per project, ↑ ↓ to move, Enter to
open, Esc to go back, `?` for all keys), the focus is always visible and never hidden, screen readers get names, roles,
states and announcements, errors are said in words, colour is never the only signal, every drag has another way
(menu items, Alt+↑ / Alt+↓, keys on the grips), touch targets are 44 px, *reduce motion* and Windows high contrast are
respected, and the app reflows at 320 px and 200 % zoom. An automated test with axe-core checks the main views in light
and dark and with every accent colour on every change. Details and known limits: [docs/ACCESSIBILITY.md](ACCESSIBILITY.md).

## Language

Kalmido starts in **English**. Open *Settings > General > Language* (in German: *Einstellungen > Allgemein > Sprache*) to switch; **Deutsch**
is included. The choice is stored per user on the server, so it applies to all your devices and also to your push
notifications (reminders, focus end, habit reminders, daily digest) and server messages.

Each language other than English is one JSON file in [`static/i18n/`](../static/i18n/) that is picked up
automatically. Want Kalmido in your language? [TRANSLATING.md](../TRANSLATING.md) explains how to add one in a few
steps (copy `de.json`, translate, run `python3 tools/i18n_check.py`, open a pull request).

Quick add always understands English and German; with French, Spanish, Italian or Dutch chosen here it also understands
that language (2.12.0). Priority, tags and the project are symbols in every language (`!!!` / `!!` / `!`, `#tag`, `~list`):

| | English | German |
|---|---|---|
| Dates | `today`, `tomorrow`, `day after tomorrow`, `friday`, `next monday`, `in 3 days`, `in 2 weeks`, `next week`, `weekend`, `12.10.` | `heute`, `morgen`, `übermorgen`, `freitag`, `nächsten montag`, `in 3 tagen`, `nächste woche`, `wochenende` |
| Times | `3pm`, `at 9:30am`, `15:00`, `at 15:00` | `15 uhr`, `um 9:30` |
| Repeat | `daily`, `every day`, `weekdays`, `weekly`, `every monday`, `every 2 weeks`, `monthly`, `yearly` | `täglich`, `werktags`, `wöchentlich`, `jeden montag`, `alle 2 wochen`, `monatlich`, `jährlich` |
| Priority | `!high`, `!medium`, `!low` (or `!!!`, `!!`, `!`) | `!hoch`, `!mittel`, `!niedrig` |
| Tag, project | `#tag`, `~list`, `in list Work`, `… in Work` at the end (only an exact project name) | `#tag`, `~liste`, `in Liste Arbeit`, `… in Arbeit` am Ende (nur ein genauer Listenname) |

| | French | Spanish | Italian | Dutch |
|---|---|---|---|---|
| Dates | `aujourd'hui`, `demain`, `après-demain`, `vendredi`, `lundi prochain`, `dans 3 jours`, `la semaine prochaine`, `3/10` | `hoy`, `mañana`, `pasado mañana`, `viernes`, `el próximo lunes`, `en 3 días`, `la próxima semana`, `3/10` | `oggi`, `domani`, `dopodomani`, `venerdì`, `lunedì prossimo`, `tra 3 giorni`, `la settimana prossima`, `3/10` | `vandaag`, `morgen`, `overmorgen`, `vrijdag`, `volgende maandag`, `over 3 dagen`, `volgende week`, `3/10` |
| Times | `15h`, `à 9h30` | `a las 15`, `a las 9:30` | `alle 15`, `alle 9:30` | `15 uur`, `om 9:30` |
| Repeat | `tous les jours`, `en semaine`, `chaque semaine`, `chaque lundi`, `toutes les 2 semaines`, `chaque mois`, `chaque année` | `todos los días`, `entre semana`, `cada semana`, `cada lunes`, `cada 2 semanas`, `cada mes`, `cada año` | `ogni giorno`, `nei giorni feriali`, `ogni settimana`, `ogni lunedì`, `ogni 2 settimane`, `ogni mese`, `ogni anno` | `dagelijks`, `elke werkdag`, `wekelijks`, `elke maandag`, `elke 2 weken`, `maandelijks`, `jaarlijks` |

Dates with a slash (`3/10`, `3/10/27`) are day / month in every language, like the dotted `3.10.`.

Task titles, project names, tags and notes are never translated.

## Tech

Python (Flask, waitress, python-dateutil, cryptography for Web Push, the stored secrets, backup encryption and the OIDC token checks, icalendar and recurring-ical-events for calendar subscriptions, py_webauthn for passkeys, segno for the QR code of the authenticator app, Pillow for profile photos) and PostgreSQL 17 (psycopg) on the server, plain JavaScript in the browser (`static/js/`, translation helpers in `i18n.js`, translations in `static/i18n/*.json`): no build step, no framework. How the code is organised: [docs/ARCHITECTURE.md](ARCHITECTURE.md). The browser makes no external requests (website links are never fetched, no favicons, no CDN); the server only contacts services you configure, plus the optional update check against GitHub. Icons from [Lucide](https://lucide.dev).

### Logo variants

| File | Use |
|---|---|
| `static/icon.svg` | The app icon: the Kalmido bot (two eyes, an antenna) on the petrol tile |
| `static/logo-white.svg` | The white bot, transparent, for dark backgrounds |
| `static/icon-light.svg` | White tile, dark bot |
| `static/favicon.svg` | Favicon without a tile: the bot is dark in a light browser and white in a dark one |

## Limits

One Kalmido instance is built for one person, a household or a small team. Many separate groups run best as one instance each, not as thousands of accounts on a single instance.

- **Tasks:** every device loads all open tasks plus the last 14 days of completed ones (and a year of habit
  history) in one request and re-renders from it. A few thousand open tasks per user feel instant; around
  10,000 open tasks the payload reaches several megabytes and rendering slows down, especially on phones.
  Completed tasks older than 14 days are not loaded, so a long history costs nothing. An account with more than
  3,000 tasks (`KALMIDO_STATE_LAZY_MIN`) gets a start set first (Today, Upcoming, My tasks, the projects it had open);
  a project's tasks load when it is opened.
- **Users:** devices poll for changes every few seconds and fetch only what changed since their last state (a delta),
  not the whole state again. That is fine for a handful of people; with more than roughly 20 to 30 users active at the same time
  it becomes wasteful.
- **Database:** PostgreSQL handles hundreds of thousands of tasks without trouble, with a connection pool (up to 56
  connections, `KALMIDO_DB_POOL_MAX`). Attachments are stored as files, not in the database.

If you run into these limits, the next steps would be per-user change tracking, sending only changes
instead of the full state, and rendering long lists incrementally. Issues and pull requests are welcome.

## How this was built

Kalmido is built with AI assistance (Claude Code). The owner decides what it does, uses it every day, and every
change runs the automated test suite (API, UI, security regression tests) in CI. Before 1.0.0 an independent AI
security review (separate agent, black-box + code review) was run and all findings were fixed and re-verified;
automated scanners (bandit, pip-audit, semgrep, OWASP ZAP baseline) run too. There has been no independent human
security audit yet — reviews and reports are welcome ([SECURITY.md](../SECURITY.md)).

## Contributing and contact

Issues, translations and pull requests are welcome, see [CONTRIBUTING.md](../CONTRIBUTING.md) and
[tests/README.md](../tests/README.md). Pull requests need a one-time agreement to the [CLA](../CLA.md) (you keep your copyright; the
project stays AGPL-3.0). A red test suite stops a release; a suite proven flaky is skipped for at most 14 days while its fix is open (`tests/skip.txt`). Security problems: please report them privately, see [SECURITY.md](../SECURITY.md).
Contact: hello@kalmido.com.

## Supporter licence

Kalmido is free and stays free. If you want to support it, there is a voluntary one-time supporter licence: 25 EUR per
person or 100 EUR per server, VAT included, no subscription. It unlocks nothing - every feature is in the free app - and
shows a small badge under *Settings > Help > About*, where you also enter the key. The key is checked offline on your
server. Purchases will run through a merchant of record with its buyer terms (refund within 14 days); until the shop is
open the dialog shows only the prices. Hosted servers do not show the licence at all.
