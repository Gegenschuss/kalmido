# Changelog

All notable changes to Kalmido are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Kalmido uses
[semantic versioning](https://semver.org/): every published change gets at least a new patch version, new features a
minor one. Releases in which operators have to do something carry a fixed section "Action needed"; the update notice
in Settings > Help shows that section of the target version.

## Older versions

- [2.700-2.799](docs/changelog/2.700-2.799.md)
- [2.600-2.699](docs/changelog/2.600-2.699.md)
- [2.500-2.599](docs/changelog/2.500-2.599.md)
- [2.400-2.499](docs/changelog/2.400-2.499.md)
- [2.300-2.399](docs/changelog/2.300-2.399.md)
- [2.200-2.299](docs/changelog/2.200-2.299.md)
- [2.100-2.199](docs/changelog/2.100-2.199.md)
- [2.0-2.99](docs/changelog/2.0-2.99.md)
- [1.x](docs/changelog/1.x.md)

## [2.819.0] - 2026-11-10

Package 2.784 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Added
- Office: a complete business year 2025 of a fictitious "Muster GmbH" (SKR03, accrual accounting) as a hard check suite: the journal, account balances, P&L, balance sheet and the quarterly VAT returns are compared to the cent with expected values computed by hand, with the gaps Kalmido does not cover named explicitly; a demo loader plays the same data into a test instance and refuses live addresses (#5387)
- Office: a guard suite for the office head at 320/460/840 px - the sub area bar and buttons like Apply never overlap (#5402)

### Changed
- Office: suppliers go into the core's one trash - deleting and restoring them is a step of Recent steps, the core's retention run clears them after the trash period (#5366, first kind of the office)

### Fixed
- Office: a reminder fee marked as paid takes the day the money came (optional day) instead of always today, so a fee paid in December counts in December; a paid day in a locked month can no longer be moved or opened again (#5387)
- Trash: the retention run checks a row again under its lock, so a restore in the same moment is never lost (#5366)

Package 2.757 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Added
- Folders now also hand their default view, columns, custom fields and project tags to the projects inside them; repeat reminder, hours per day, hourly rate and the progress bar can be set once per folder (folder settings). A project that differs from its folder shows it and goes back with "Back to the folder" (#4501).
- docs/GLOSSAR.md explains every Python module, every script under static/js and the common function prefixes; linked from CONTRIBUTING.md, a lint guard (tools/check_glossar.py) asks for a line for every new module (#5295).

### Fixed
- Lists and the start page report their width to the header again: the top bar lines up with the content instead of standing 4 px beside it, and the width "Wide" of a note / knowledge page keeps its list + note layout (CI red p2599_b_kopf_ui, #5309).
- p151_ui says why the hint of the task just tracked is missing (toast, totals on the page and on the server); the Mac red was the sub-second discard fixed in #5186 (#5211).

[Unreleased]: https://github.com/Gegenschuss/kalmido/compare/v2.819.0...HEAD
[2.819.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.819.0
