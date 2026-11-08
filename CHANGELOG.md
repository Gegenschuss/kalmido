# Changelog

All notable changes to Kalmido are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Kalmido uses
[semantic versioning](https://semver.org/): every published change gets at least a new patch version, new features a
minor one. Releases in which operators have to do something carry a fixed section "Action needed"; the update notice
in Settings > Help shows that section of the target version.

## Older versions

- [2.600-2.699](docs/changelog/2.600-2.699.md)
- [2.500-2.599](docs/changelog/2.500-2.599.md)
- [2.400-2.499](docs/changelog/2.400-2.499.md)
- [2.300-2.399](docs/changelog/2.300-2.399.md)
- [2.200-2.299](docs/changelog/2.200-2.299.md)
- [2.100-2.199](docs/changelog/2.100-2.199.md)
- [2.0-2.99](docs/changelog/2.0-2.99.md)
- [1.x](docs/changelog/1.x.md)

## [2.734.0] - 2026-11-08

Package 2.727 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Changed
- Tables: the sheet bar under the grid is always there, also with one sheet - its tab ("Sheet 1" for a new table) and the "+" beside it, like a spreadsheet; a tap on the open tab gives its menu (rename, duplicate, pivot; the first sheet keeps no delete). Who may only read sees the tab without "+" and menu (#5203).
- Documents and file store: a swipe leafs like turning a page - the previous / next document lies beside the open one as a placeholder (title, type, date, its preview fetched ahead, else an empty page) and glides along with the finger over the whole width; let go and it snaps in, then its content loads. The end of the list still springs back; the full view (PDF) and the picture viewer do the same; reduced motion changes at once (#5202).
- German wording: "Freigabe" means approval only; sharing says "Teilen" / "Zugriff" (e.g. "Links und Zugriffe"), a lone bank "Konto" is "Bankkonto", agent bundles are "Teil {0} von {1}"; English "activity" for the history of one thing is "history". TRANSLATING.md has the glossary lines and tools/i18n_check.py reports "Freigabe" in a sharing text (#5197).

## [2.731.0] - 2026-11-08

Package 2.707 (Bündel: CI: ZAP-Schritt 'Start PostgreSQL' scheitert geleg).

### Fixed
- CI: the OWASP ZAP job pulls the PostgreSQL image with up to 3 tries and a growing pause before starting it, and prints the container log when the database does not start; a short registry hang no longer fails the step and holds the release. The ZAP finding itself stays a hard check. Suite p2707_zap_db_start runs the step with a stand-in docker (#5185).

Package 2.715 (Bündel: CI: ZAP-Datenbank wird zu früh als bereit gemeldet).

### Fixed
- CI, job "OWASP ZAP baseline": the step "Start PostgreSQL" checks the database over TCP (pg_isready -h 127.0.0.1) instead of the socket. The postgres:17 image first runs a setup server on the socket only and restarts it; the socket check took that server as ready and the one final check then met the restart ("rejecting connections") and failed the job. The wait loop (90 s) is now the final check itself; tests/p2707_zap_db_start_test.py plays the setup server and its restart (#5187).

Package 2.724 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Fixed
- #5184: the start state no longer sends the internal organisation column of every task (row-level security of #4602); a big organisation account's start set is back under its 2 MB budget (2.02 -> 1.96 MB in p3136_state_size), the suite now prints the start set's bytes per task key.
- #5186: test p151_ui waits until the timer ran a full second before Stop - a shorter entry is discarded as a misclick, so on a fast runner the hint of the task just tracked was missing.

Package 2.730 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Fixed
- #5195: test p2139_b_api gives its agent the scope attachments:read - a team chat file download needs it since #4382 (finding 8), the test was not pulled along; it now also checks that a token without it gets 403.
- #5196: test p21481_d_api stubs the bookmark sync's allow list with an empty set like the real one - the http check of #4382 (finding 6) looks into it and crashed on None.

## [2.719.0] - 2026-11-08

Package 2.702 (Bündel: Bilanz: Auszahlungen der Online-Zahlungen und CSV-).

### Changed
- Bank reconciliation: importing a CSV statement now asks which bank account it belongs to when the office has two or more bank accounts (Office > Bank > Import, step "columns"). Without a choice the import is refused instead of putting the lines silently on the default account; the balance sheet books the lines on the chosen account (#5183).

### Fixed
- Balance sheet: the collective payout of the online payment provider now lands on the bank account whose statement carries it; before, it stayed on the default account when it arrived on a second account (#5183).
- Balance sheet: a restaurant bill that is both an approved entertainment receipt and a receipt on the same bank, cash or card booking now counts once (the entertainment receipt wins, as the strict income statement does); before, the expense and the input tax were booked twice (#5183).

Package 2.689 (Bündel: Bündel: Bündel: Teil 1/6: Sammelpaket: Aufgaben ohne Paket (Dispatcher), CI-only rot: p2191_c_perf, CI-only rot: p2290_c_fold_ui u. ).

### Changed
- Task search: the server tests the search word only on the tasks of the projects you can see. Since tasks stand under row-level security (2.662), the database could no longer use its text indexes for the search and read every task of the instance once per field; with 32,000 tasks a search took 29 ms in the database, now 2.5 ms, and it no longer grows with other workspaces' tasks. Same results as before (#5116).

### Security
- Names, titles and other typed values that a translated sentence puts into the page (for example "SSO: {0}", "row {0}", "Access data set (…{0})") are now always escaped: 88 places moved from tr() / trn() to trh() / trnh(). A new lint step (tools/check_trh.py, in the CI) reports any new tr() with an unescaped value inside an HTML template; values that are HTML on purpose stand in tools/trh_ok.txt (#5125).

Package 2.705 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Security
- #5151: Receipt fetcher keys (kbh_...) get an optional address rule like API tokens and scan inbox keys: Settings > Integrations > Receipt fetcher, lock button "Only from" (IPs / networks); from any other address the key answers 403 (PATCH /api/docs/fetchers/{id} {allowed_ips}).
- #5151: The plus address tokens of an older version (mail_tokens, hub_tokens, doc_mail still in plain text) are sealed with the server key and hashed by the daily watchdog run, 14 days after the first start of this version (one-way: a version before 2.674 no longer finds those old addresses after that; 2.674 and later still do). The address rule helpers moved to core/ipallow.py (api/scopes.py re-exports them).

## [2.710.0] - 2026-11-08

Package 2.674 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Security
- #4028 Hosted MCP: a body without Content-Length is read in pieces up to the limit; issuer and accepted Origin come from PUBLIC_URL only when it is set (Settings > Organisation > Agents warns when it is missing); an access ends 90 days after it was made; the consent page writes the agent's log; ended or revoked accesses are cleaned up after 30 days, a restored backup still cannot revive them; wiki files through API v1 send an SVG as a download and note no download for HEAD or 404; after an OIDC sign-in the consent page opens again (only that path of this server).
- #4382 Hardening from audit #2483 (14 low findings): letter PDFs only the filed version with a sandbox CSP; shared wiki images raster only with magic bytes; renewing or deleting a client mail address needs write access; webhook and channel tests answer blocked hosts uniformly; new mail plus tokens are stored sealed and matched by hash; Paperless, newsletter and Karakeep refuse plain http to public hosts; messages to a running job need agent use; scopes attachments:read, account and calendar (day plan without calendar shows "Busy"); office agent list limits apply to linked documents; read-only agents cannot post playbook proposals; admin agent audit API filtered like the web route; document fetcher keys expire after 365 days; sheet proposals only to people who may use the agent; hint on the EXIF switch.
### Changed
- #4190 DATEV, GoBD and knowledge exports are written to temporary files and share two export places (busy = 429 with a message); JSON request bodies are limited to 10 MB (routes with larger bodies keep their own limit); the ZIP plan stops at the first file too many; the account export reads its tables in pages.
- #4194 Agent list, job list and news check in batches; the job list no longer carries each job's log (the log loads when a job is opened) and older own jobs no longer go missing behind many newer ones.
### Added
- #4028 Settings > Organisation > Agents lists the connected apps of team agents (who, when, last use, end) and can revoke them.

Package 2.683 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Fixed
- Documents on the phone: a document opened from a card of a file store folder now shows "3 of 48", the arrow buttons and the sideways swipe through the folder's documents in the order shown (before: no leafing at all, the sheet only knew the documents' own list); "Open as document" in the folder's list view leafs the same way; a document opened by its address (link, reload, search hit) that stands further down than the loaded page loads the next pages until it is found (#5150).
- Locked folders: a picture opens with all pictures of the folder (arrows, swipe), a PDF leafs through the folder's PDFs and pictures like an open folder; each file is decrypted in the browser only when it is turned to, never all of them in advance (#5150).

Package 2.671 (Bündel: Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), CI-only rot: p2551_c_favout_ui, Teil 1/6: Sammelpaket: Aufgaben ohne ).
### Added
- Tables: group the rows by one column (dates by day, month or year) with collapsible groups and a subtotal row per group - sum, count or average per number column. A view only, like the filter: nothing is saved, the subtotals take no part in formulas, copying or the export; moving rows is held while grouped (#3463).
- Tables: pivot sheet - a sheet of a workbook computed from another sheet of the same workbook on every read (rows, an optional column field, up to six values as sum / count / average, filters), read-only with totals, always current; its setting is saved with a version (409 on a stale one); the xlsx / CSV export writes its values. Agents see `kind` of every tab and the pivot result when reading a sheet (#3463).
### Fixed
- Organisation import: disposition bookings made from a quotation keep their link to the imported quotation and part (offer_root / offer_doc / offer_pos on the new ids, emptied when nothing of the import fits), and open places of a crew function come along - the disposition on the target no longer books the shoot days twice (#5097).

Package 2.620 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Bündel: Releases für Selbst-Hoster: Tag-Version braucht ei, Sammelpaket: Aufgaben ohn).
### Changed
- A long press (phone) or right click (computer) opens the row's "…" menu also for mailbox addresses, repositories, webhooks, file requests, table folder cards and file cards (#4616).
- Members without office groups (level "own" for travel) can take their own trip from the trip planning into the office's travel expenses; approval and DATEV stay with the admin (#4642).
### Fixed
- Tasks from a quotation that were moved into another project no longer count for the old project, the next version of the quotation shows them as "moved to another project" and never writes into them; the quotation's task count needs sight of the project, the project's budget sums all quotation chains of the project; the link follows the moved task, so deleting the old project keeps it (#4586).

Package 2.693 (Bündel: Bündel: Kommentare: Schalter 'Mit Aktivität' auch in nicht, Sammelpaket: Aufgaben ohne Paket (Dispatcher)).

### Fixed
- Tables: printing a pivot sheet no longer gives an empty page or "Nothing to print". The pivot sheet's menu (the three dots) now offers "Print / PDF…"; the PDF holds the computed table as the view shows it, with the header and the bold total row (#5148).

Package 2.685 (Bündel: Kommentare: Aktivität in drei Stufen (nur Kommenta, Bündel: Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), CI-only r).
### Added
- Balance sheet: the journal now also books the approved entertainment receipts (70 % deductible with the full input tax, the 30 % on an account of their own), the mileage allowance of the logbook (31 December) and paid reminder fees (other income, no VAT) - the same figures as the income statement (#5128).
- Balance sheet: every bank account of the office is a ledger account of its own (its DATEV account, else the next free one after the default, SKR03 1200ff / SKR04 1800ff); a bank line belongs to the account whose IBAN its statement carries, invoice payments and card totals follow their bank line (#5128).
- Balance sheet and profit and loss account as PDF next to the CSV (`GET /api/office/books/ledger/<bs|pl>.pdf?year=`, office admin, logged as an export); entries made by hand can be edited in a dialog (409 when someone changed them meanwhile); a difference on the opening balance account 9000 shows before the year-end closing (#5128).
### Changed
- Comments: the history between the comments has three levels in the "…" menu, in shared and private lists alike: comments only, changes of others, all changes incl. my own. Default per device: shared list = all changes, private list = changes of others; the old on/off setting carries over. The head says "Comments only" or (shared list) "Only changes of others" (#5162).
### Fixed
- Office: switching "Office & finance" on no longer leaves the office saying it is switched off when it loaded before the switch was saved (#5176).
- Balance sheet: a receipt booked against the bank (counter account "bank") and paid from the cash box is now booked bank to cash instead of being left out (#5128).

[Unreleased]: https://github.com/Gegenschuss/kalmido/compare/v2.734.0...HEAD
[2.734.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.734.0
[2.731.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.731.0
[2.719.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.719.0
[2.710.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.710.0
