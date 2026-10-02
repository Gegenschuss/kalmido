# Translating Kalmido

Kalmido is written in English. Every text in the code is English and doubles as its own lookup key;
every other language is one JSON file in [`static/i18n/`](static/i18n/). German
([`de.json`](static/i18n/de.json)) is the reference translation; French, Spanish, Italian and Dutch (2.11.0) are
machine-translated and marked beta (`"beta": true` in `_meta`): reviews and fixes by native speakers are welcome, see
[CONTRIBUTING.md](CONTRIBUTING.md#translations). Adding a language needs no code changes:
drop in a file and it shows up under *Settings > Language*.

## Add a language

1. Copy the German file and name it after the language code (ISO 639-1, optionally with a region:
   `fr`, `pt-BR`):

   ```sh
   cp static/i18n/de.json static/i18n/fr.json
   ```

2. Fill in `_meta`, the weekday / month names and the date formats (see [File format](#file-format)).
3. Translate every value. Never change a key (the English text left of the colon): the code looks the
   text up by exactly that key.
4. Check the file:

   ```sh
   python3 tools/i18n_check.py fr
   ```

   It must report `100%`, no missing keys, no errors and no unused keys (exit code 0). `python3 tests/i18n_test.py`
   checks every language at once (keys, unused keys, placeholders, plurals, HTML tags, `_meta`).
5. Rebuild and run (`docker compose up -d --build`), open *Settings > Language* and pick your language.
   Click through the views (today, calendar, matrix, habits, focus, settings, a task's detail panel) and
   check that nothing is cut off or reads oddly.
6. Open a pull request with the new file. Mention anything you were unsure about.

## File format

```json
{
  "_meta": {"name": "Deutsch", "locale": "de-DE"},
  "_weekdays": ["Sonntag", "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag"],
  "_weekdays_short": ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"],
  "_months": ["Januar", "Februar", "...", "Dezember"],
  "_months_short": ["Jan", "Feb", "...", "Dez"],
  "_date_formats": {"near": "{wd}, {dd}.{mm}.", "short": "{wd}, {d}. {mon}", "year": "{wd}, {d}. {mon} {y}", "long": "{wdl}, {d}. {month}"},
  "Today": "Heute",
  "Delete list “{0}”?": "Liste „{0}“ löschen?",
  "{0} task today": ["{0} Aufgabe heute", "{0} Aufgaben heute"]
}
```

Keys that start with `_` are settings, everything else is a translation.

| Key | Meaning |
|---|---|
| `_meta.name` | Name of the language in the language itself, shown in the language selector (`Deutsch`, `Français`) |
| `_meta.locale` | BCP 47 locale for number and date formatting by the browser (`de-DE`, `fr-FR`), used for full dates such as "created on ...", the first day of the week and the plural rule |
| `_meta.beta` | optional, `true` for a machine-translated or unreviewed file: the language pickers show a *Beta* mark |
| `_weekdays`, `_weekdays_short` | 7 names, **starting with Sunday** (the order of JavaScript's `Date.getDay()`). The calendar still starts its weeks on Monday. |
| `_months`, `_months_short` | 12 names, January first |
| `_date_formats` | Patterns for the short date labels in task rows and the calendar, see below. A missing format falls back to English. |

Date format tokens: `{wd}` / `{wdl}` short / long weekday, `{d}` day, `{dd}` day with two digits, `{mm}` month
number with two digits, `{mon}` / `{month}` short / long month name, `{y}` year.

| Format | Used for | English |
|---|---|---|
| `near` | 2 to 6 days ahead | `{wd}, {mon} {d}` (Wed, Oct 1) |
| `short` | other dates this year | `{wd}, {mon} {d}` |
| `year` | dates in another year | `{wd}, {mon} {d}, {y}` |
| `long` | title of the calendar's day view | `{wdl}, {month} {d}` |

"Today", "Tomorrow" and "Yesterday" are normal translations.

### Placeholders

`{0}`, `{1}`, ... are filled in by the app (a name, a number, a date). Keep every placeholder of the key in
the translation; you may move them around:

```json
"Delete list “{0}”?": "Supprimer la liste « {0} » ?"
```

Some values contain HTML (`<b>`, `<br>`, `<code>`): keep the tags, translate only the text around them.

### Plurals

A value that is a list `[one, other]` is a plural. The app picks `one` when the number is exactly 1 and
`other` for everything else (0, 2, 3, ...); where the language's plural rule (the browser's `Intl.PluralRules` for
`_meta.locale`) also uses the singular for 0, as French does, 0 takes `one` too (the server does the same for `fr`). The key is the English singular; `{0}` is always the number:

```json
"{0} task today": ["{0} tâche aujourd'hui", "{0} tâches aujourd'hui"]
```

If your language has no difference (or needs a form that ignores the number), use the same text twice.

**Limitation:** only two forms exist. Languages with more plural categories (Polish, Russian, Arabic, ...)
have to choose the best fit for `other`. The checker fails if a plural key has a plain string or the other
way round.

### Keys with a context suffix

Sometimes one English word needs different translations, e.g. *Start* the focus timer vs. the *Start*
date of a task. Such keys carry a suffix after `|`, which English never shows:

```json
"Start": "Start",
"Start|date": "Beginn",
"all day": "ganztägig",
"all day|short": "ganzt."
```

Translate them like any other key; the suffix only tells you where the text appears (`|short` = a narrow
column, keep it short).

## The checker

`python3 tools/i18n_check.py [code ...]` reads every `tr("...")`, `trn("one", "other", n)` and `N_("...")` in
`static/app.js` and `app.py` and compares them with each file in `static/i18n/`:

- **missing**: used by the code, not translated (the app then shows English) -> error
- **placeholder mismatch**: `{0}` in the key but not in the translation, or the other way round -> error
- **plural shape**: a plural key needs `[one, other]`, all other keys a string -> error
- **_meta / names / date formats**: missing name or locale, wrong number of names, unknown tokens -> error
- **unused**: in the file but no longer used by the code -> warning, just delete it

Exit code 1 on any error. When the English texts change, run it for every language: new keys show up as
missing, removed ones as unused.

## For developers

- Wrap every user-visible text in `tr('English text', ...args)` (client: `static/i18n.js`, server: `app.py`),
  plurals in `trn('{0} item', '{0} items', n, ...args)`. Keys must be string literals, otherwise the checker
  cannot see them.
- Tables that are translated later (`tr(label)` on a variable) mark their texts with `N_('Text')`; the checker
  lists such non-literal calls as info.
- Server texts (error messages, push notifications, `/drop` replies) use the same JSON files. The language is
  a server setting because the push notifications are sent from there.
- English needs no file: the keys are the English texts, English weekday / month names and date formats live
  in `static/i18n.js`.
- Server-side number and date formats (pushes, CSV, public pages) use `short_day()`, `fmt_int()` and `dec_comma()` in
  `app.py`; a new language with a decimal comma goes into `COMMA_LANGS` there.
- The service worker precaches `de.json`; any other language file is cached on first use, and the app keeps
  the active one in `localStorage`, so the chosen language also works offline.

## Quick add stays English + German

The natural-language quick add (`tomorrow 3pm !high #tag ~list`) understands English and German keywords,
whatever the interface language. Those words are not translations but parser patterns in `static/app.js`:
`parseQuick()` (regular expressions for repeat, date, time and priority words), `WDAY` (weekday names) and
`PRIO_WORDS` (`!high`, `!hoch`, ...). To teach it another language, add that language's words there and extend
the matching regular expressions; the parser is shared by all languages, so avoid words that clash with
English or German. Keep the quick-add help text in the settings (the translation of the key that starts
with `today, tomorrow, day after tomorrow`) in line with what the parser really understands.
