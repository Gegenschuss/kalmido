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

Kalmido is a hobby project maintained by one person, not a company with a security team. Realistically:

- an answer within about a week (usually sooner)
- a fix for serious issues as fast as possible, released as a new patch version with a note in
  [CHANGELOG.md](CHANGELOG.md) and the GitHub release; admins see the new version in *Settings > Help*
  (daily update check)
- credit in the changelog if you like

There is no bug bounty.

## Supported versions

Only the **latest release** gets fixes. Updating is quick (see *Updating* in the README), and the database
migrates itself.

## How Kalmido is checked

- Every push runs the automated test suite in CI (API, UI and a security regression suite that replays
  every finding of the last review), plus `bandit`, `pip-audit` on the pinned dependencies, `semgrep` and an
  OWASP ZAP baseline scan.
- Before 1.0.0 an independent AI security review (a separate agent, black-box testing plus code review) was
  run; all findings were fixed and re-verified (see CHANGELOG.md).
- There has been **no independent human security audit** yet. Reviews are very welcome.

### Known scanner findings (reviewed, not bugs)

- `semgrep` flags SQL built with f-strings: the interpolated parts are fixed SQL fragments or `?`
  placeholder lists, never user input; values always go through parameters.
- `semgrep` / `bandit` flag `urllib` requests with a URL from configuration: server-side requests only go to
  the ntfy / Paperless servers the admin configures and to the GitHub releases API, through a wrapper that
  allows http/https only and same-host redirects.
- ZAP reports the `style-src 'unsafe-inline'` part of the Content-Security-Policy: scripts are strictly
  `'self'`; inline styles are used for user-chosen list colours (validated hex values).

## Design notes for operators

- AI agents: see **[docs/AGENT-SECURITY.md](docs/AGENT-SECURITY.md)** for the threat model (only designated people by
  account id instruct an agent; task text, comments and other agents are data), what Kalmido enforces (never admin, only
  shared lists, kill switch, usage limits, audit log) and a tested host sandbox recipe for Claude Code.

- The single sign-on header (`AUTH_PROXY_HEADER`) is a password. Only trust it from your proxy, and make
  the proxy strip client-supplied copies. See *Login* and *Reverse proxy* in the README.
- Use HTTPS for anything beyond your own machine.
- API tokens act as their user. Give scripts the smallest access they need (*read* unless they must change
  things), an expiry, and revoke tokens you no longer use. Behind a login proxy, only let `/api/v1/` requests that carry
  an `abk_` token bypass the login (see docs/API.md).
- Webhook receivers should check `X-Kalmido-Signature` and the timestamp (5 minute window) before trusting a payload.
- Public list links are readable by anyone who has the link. Use *View only* unless ticking off is wanted, a password
  for anything sensitive, and *New link* if a link got out.
- The Paperless integration uses one API token: every user an admin grants Paperless access can see that
  token's whole archive.
- Backups contain everything (all users' data, the server secrets in the settings table). They are only served to
  admins; keep copies you move elsewhere encrypted (*Encrypt backups*) and the passphrase outside the server. A
  restore replaces all data and is refused for anything but a complete, untampered Kalmido archive (see *Backups and
  restore*).
- Two-factor authentication protects the built-in login only; with the proxy header or OIDC it is the job of your
  login provider. Passkeys only work over HTTPS (or `localhost`).
- The OIDC provider is trusted to say who a user is: anyone it vouches for with a matching user name / verified e-mail
  gets that account (or a new one with *Create accounts on the first OIDC login*). Use the required group if the
  provider has users who should not use Kalmido.
