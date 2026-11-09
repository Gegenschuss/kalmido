# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Write to **hello@kalmido.com** instead
(or use GitHub's *Report a vulnerability* button on the Security tab, if it is enabled).

Helpful to include:

- what an attacker can do (for example: read another user's tasks, run script in someone's browser, reach
  internal services from the server) and what they need for it (an account? which role? a login proxy?)
- steps to reproduce, ideally with requests (`curl`) or a short script
- the Kalmido version (*Settings > Help*, or the `VERSION` file) and how it runs (Docker, reverse proxy,
  single sign-on header or built-in login)
- whether you want to be credited, and under which name

## What to expect

Kalmido is a young project without a dedicated security team. Realistically:

- an answer within about a week (usually sooner)
- a fix for serious issues as fast as possible, released as a new patch version with a note in
  [CHANGELOG.md](CHANGELOG.md) and the GitHub release; admins see the new version in *Settings > Server > Server*
  (update check every 6 hours)
- credit in the changelog if you like

There is no bug bounty.

## Disclosure: fixes go live first

The maintainers also run Kalmido themselves as a hosted instance (app.kalmido.com, today for their own work; a hosted
offer for others is coming). A release that closes a security problem is rolled out to that instance **before** its code
is published here, so the fix is not readable while the hosted instance still runs the old version. For such releases:

- the changelog and the commit messages name only *Security fix* and the area (for example "Security fix:
  organisations"), no details on how the problem could be used
- details follow, if at all, only after the hosted instance runs the fix and self-hosters had time to update
- self-hosters: update as soon as a release says *Security fix*

Reported problems are handled the same way: fixed, rolled out, then published (with credit if you like).

## Supported versions

Only the **latest release** gets fixes. Updating is quick (see *Updating* in the README), and the database
migrates itself.

## How Kalmido is checked

- Every push runs the automated test suite in CI (API, UI and a security regression suite that replays
  every finding of the last review), plus `bandit`, `pip-audit` on the hashed lock files of the image and the embedding service, `semgrep` and an
  OWASP ZAP baseline scan. CodeQL (Python, JavaScript; own workflow on every push to main and weekly) and a Trivy scan
  of the app image report their high / critical findings in the job summary - reporting only, no gate yet (#5300).
- Before 1.0.0 an independent AI security review (a separate agent, black-box testing plus code review) was
  run; all findings were fixed and re-verified (see CHANGELOG.md).
- There has been **no independent human security audit** yet. Reviews are very welcome.

### Scanner exception lists (2.543.0, #4625)

`semgrep` and the OWASP ZAP baseline scan are **red for new findings only**. Every known, reviewed finding stands in an
exception list in the repository, with its reason and date:

- **semgrep: `tools/semgrep_baseline.json`.** One entry per finding: the rule id, the file, the code line (whitespace
  collapsed), the reason, the date and, when the finding is a real gap that is being fixed, the task number. A finding
  is known when rule, file and code line match - the line number does not count, so edits above a finding do not make it
  new. `tools/semgrep_baseline.py` compares semgrep's JSON output against the list (CI job "semgrep"; an entry whose
  finding is gone is reported as a notice and should be removed). Matching counts occurrences: a second copy of a known
  code line in the same file is a new finding. A semgrep error, a scan without a results list or with no scanned file,
  and most known findings vanishing at once are red too - a broken scan never looks like a clean tree.
- **ZAP: `.zap/rules.tsv`.** One line per ZAP plugin id (`id`, `IGNORE`, reason with the date). The scan runs without `-I`,
  so every alert that is not ignored there fails the job "OWASP ZAP baseline".

Adding an entry, in this order:

1. Read the finding and decide: a real gap is **fixed**, or gets a task and the entry names that task - it is never
   only listed. Only a reviewed false positive or an accepted, explained behaviour is listed without a fix.
2. semgrep: run the scan as in `.github/workflows/ci.yml` with `--json --output semgrep.json`, then
   `python3 tools/semgrep_baseline.py semgrep.json --accept "reason" [--task N]` writes every new finding with that
   reason and today's date (or add the entry by hand with the same fields). ZAP: add the line `id<TAB>IGNORE<TAB>reason,
   date` to `.zap/rules.tsv`; an ignored plugin id silences all alerts of that plugin, so name what the id covers.
3. The reason says *why* the finding is not a bug here (which guard, which escaping, which fixed value), not that the
   scanner is wrong. `tests/semgrep_baseline_test.py` checks that every entry is complete and still matches a code line.

### Known scanner findings (reviewed, not bugs)

- `semgrep` flags SQL built with f-strings: the interpolated parts are fixed SQL fragments or `?`
  placeholder lists, never user input; values always go through parameters.
  2.755.0 (#5296): a varying table / column name goes through `qi()` (`kalmido/core/pg.py`, allowlist + quoting); the own
  rule `.semgrep/sql_ident.yml` (`kalmido-sql-ident-without-qi`) is red for every new f-string with `FROM / JOIN / INTO /
  UPDATE / SET / TABLE / TRUNCATE / INDEX x ON {...}` without it. Its ~440 existing places (names from fixed code, the schema or the registries) are listed
  in `tools/semgrep_baseline.json` with that reason and task 5296, not rewritten; a place that is touched moves to `qi()`.
  The rule is a net for the f-string form, no proof: `WHERE` / `ORDER BY` / `SELECT` names, `+` concatenation, `%` and
  `.format()` are not seen.
- `semgrep` / `bandit` flag `urllib` requests with a URL from configuration: server-side requests only go to
  the services in the [list of outgoing connections](docs/SELF-HOSTING.md#outgoing-connections), through a wrapper that
  allows http/https only and same-host redirects, or, for addresses people give (calendars, feeds, invoice links in mails),
  a guard that connects to public addresses only.
- `semgrep` flags SHA-1 (`usedforsecurity=False`): ETags, sync tokens, import uids and change stamps, no security use.
- ZAP reports the `style-src 'unsafe-inline'` part of the Content-Security-Policy: scripts are strictly
  `'self'`; inline styles are used for user-chosen list colours (validated hex values). `media-src https:` is on
  purpose for embedded video. The missing `Cross-Origin-Embedder-Policy` is accepted: it would block the embedded
  players and mail images, and Kalmido sets `Cross-Origin-Opener-Policy`, `Cross-Origin-Resource-Policy` and
  `frame-ancestors 'none'`.

## Design notes for operators

- AI agents: see **[docs/AGENT-SECURITY.md](docs/AGENT-SECURITY.md)** for the threat model (only designated people by
  account id instruct an agent; task text, comments and other agents are data), what Kalmido enforces (never admin, only
  shared lists, kill switch, usage limits, audit log; 2.30.0: no agent between lists with different people unless a
  person approves the bridge, list restriction per agent and token, an access log per list) and a tested host sandbox
  recipe for Claude Code. Self-hosting hardening (reverse proxy, firewall, backups, updates): **[docs/SELF-HOSTING.md](docs/SELF-HOSTING.md)**.

- The single sign-on header (`AUTH_PROXY_HEADER`) is a password. Only trust it from your proxy, and make
  the proxy strip client-supplied copies. See *Login* and *Reverse proxy* in [docs/SELF-HOSTING.md](docs/SELF-HOSTING.md).
- Use HTTPS for anything beyond your own machine.
- Lists with the lock (2.64.1, "Encrypted in the browser") rely on trust on first use: each device trusts the first public
  key it sees for a member until the safety numbers are compared, and the ciphertexts are not bound to a task, so the server
  could swap texts of the same kind inside one list. Neither protects against a changed web app delivered by the server
  itself. Since 2.64.2 files and the list channel are encrypted with the list key too, and when a member leaves the key
  changes and older contents are encrypted again in the background; until that run is done a former member who kept a
  copy of the database could still read older ciphertexts with the old key. Details: *Lock per list* in docs/ARCHITECTURE.md.
- Since 2.761.0 every image and the web manifest of a weekly release (the SHA-256 of every file the browser gets) carry a
  GitHub build attestation (Sigstore, keyless, public transparency log): `gh attestation verify` shows that the release
  workflow of this repository built them from the tagged commit (*Production updates* in docs/SELF-HOSTING.md). It does
  not by itself let the browser check the app a server delivers. Since 2.766.0 *Settings > Help > Check code* shows the
  version and one hash of the code this browser holds, comparable with the line `web-manifest-X.Y.Z.json` in `SHA256SUMS`
  of the release, and the service worker warns when the code changes without a new version. Both come from the same server
  as the code: they catch mistakes and slips, not an operator who means to deceive; the manual way from outside is in
  **[docs/CODE-VERIFY.md](docs/CODE-VERIFY.md)**.
- API tokens act as their user. Give scripts the smallest access they need (*read* unless they must change
  things), an expiry, and revoke tokens you no longer use. Behind a login proxy, only let `/api/v1/` requests that carry
  an `abk_` token bypass the login (see docs/API.md).
- Webhook receivers should check `X-Kalmido-Signature` and the timestamp (5 minute window) before trusting a payload.
- Public list links are readable by anyone who has the link. Use *Read-only* unless ticking off is wanted, a password
  for anything sensitive, and *New link* if a link got out.
- Backups contain everything (all users' data, the server secrets in the settings table). They are only served to
  admins; keep copies you move elsewhere encrypted (*Encrypt backups*) and the passphrase outside the server. A
  restore replaces all data and is refused for anything but a complete, untampered Kalmido archive (see *Backups and
  restore*).
- Two-factor authentication protects the built-in login only; with the proxy header or OIDC it is the job of your
  login provider. Passkeys only work over HTTPS (or `localhost`).
- The OIDC provider is trusted to say who a user is: anyone it vouches for with a matching user name / verified e-mail
  gets that account (or a new one with *Create accounts on the first OIDC login*). Use the required group if the
  provider has users who should not use Kalmido.
