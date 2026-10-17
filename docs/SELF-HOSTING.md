# Self-hosting: lessons from running Kalmido

Practical notes for running Kalmido on your own server: what tends to go wrong behind a reverse proxy, with installed
apps and push, with backups, mail and moving to another machine, and how to harden the host. The README has the basics
([Quick start](../README.md#quick-start), [Reverse proxy](../README.md#reverse-proxy),
[Configuration](../README.md#configuration), [Backups and restore](../README.md#backups-and-restore),
[Updating](../README.md#updating)); this page collects what comes on top. Everything here is generic: adjust names,
addresses and paths to your setup.

## Contents

- [Requirements](#requirements)
- [First setup and the server key](#first-setup-and-the-server-key)
  - [Organisations and private spaces (2.46)](#organisations-and-private-spaces-246)
- [Reverse proxy and network](#reverse-proxy-and-network)
- [Installed app (PWA) and push](#installed-app-pwa-and-push)
- [Database (PostgreSQL)](#database-postgresql)
- [Upgrade to 2.37 (PostgreSQL required)](#upgrade-to-237-postgresql-required)
- [Backup and encryption](#backup-and-encryption)
- [Encryption of organisation data](#encryption-of-organisation-data)
- [Organisation export](#organisation-export)
- [Server hardening](#server-hardening)
- [Intrusion alerts](#intrusion-alerts)
- [Mail](#mail)
- [Documents: text recognition](#documents-text-recognition)
  - [Import from Paperless-ngx (2.48)](#import-from-paperless-ngx-248)
- [Moving to a new server](#moving-to-a-new-server)
- [Production updates](#production-updates)
- [Support Kalmido (supporter licence)](#support-kalmido-supporter-licence)

## Requirements

Measured with an empty server, plus headroom for daily use. Kalmido is one Python process (waitress, 16 threads)
next to PostgreSQL 17.

| | Minimum | Recommended |
|---|---|---|
| Memory | 1 GB RAM in total (both containers use about 250 MB idle) | 2 GB or more for a team, big imports and restores |
| CPU | 1 core | 2 cores or more (backups, imports and full-text search are quicker) |
| Disk | 1.5 GB for the images (kalmido about 420 MB, postgres:17 about 650 MB) plus the data | an SSD; room for the backups (below) |
| System | 64-bit Linux, macOS or Windows with Docker and Compose v2 | Linux with Docker Engine |
| Architecture | linux/amd64 or linux/arm64 (prebuilt images for both) | |

- **Backups take room.** Each automatic backup holds the database and every attachment; with the default retention (14
  daily, 8 weekly) plan roughly 20 times the size of the data, or lower the retention, encrypt and move the folder
  (`KALMIDO_BACKUP_DIR`) to another disk.
- **Raspberry Pi.** A Pi 4 or 5 with 4 GB or more and a 64-bit OS (Raspberry Pi OS 64-bit, Debian or Ubuntu arm64)
  runs Kalmido well for a household or a small team. Boot or at least keep `pgdata/` and `data/` on an **SSD** (USB 3
  or NVMe on the Pi 5): PostgreSQL writes constantly in small pieces, which is slow on an SD card and wears it out. A
  32-bit OS (armv7) is not supported. Use a good power supply: a power cut while writing is the usual way an SD card
  or a cheap USB adapter loses data.

## First setup and the server key

**One-time setup code (2.45.0).** As long as no account exists, the server prints a code into its log at every start:

```text
================================================================
  Kalmido first setup: no account exists yet.
  Setup code: abcd-efgh-jkmn
  ...
```

Read it with `docker compose logs kalmido` (the installer shows it at the end) and type it on the setup page. Only its
hash is kept in memory; it works once, wrong codes count against a limit per address (like logins), a restart prints a
new one. Blanks, dashes and capitals do not matter. Servers that already have an account are not affected, nor is the
login. For tests and automation only: `KALMIDO_SETUP_CODE=<fixed code>` makes that the code (it is not printed),
`KALMIDO_SETUP_CODE=off` switches the check off (whoever reaches the page first becomes the admin again).

**The server key (`KALMIDO_SECRET_KEY`).** It seals stored tokens, the sign-on client secret, and wraps the keys of
the organisations (encryption at rest, below). Two ways to provide it:

1. In `.env`: `KALMIDO_SECRET_KEY=` followed by `openssl rand -base64 32`. Always wins.
2. As a file (2.45.0, the default of `docker-compose.yml`): `KALMIDO_SECRET_FILE=/secret/kalmido.key`, mounted from
   `./secret`. If the file is missing, the server creates it on the first start (32 random bytes, base64, mode 0600,
   never overwritten) and uses it from then on. Create the folder yourself (`mkdir secret`; the installer does), so the
   container's user may write it.

The key must not live in the data folder: the in-app backups contain the data folder, and a backup that carries its
own key protects nothing. A key file inside the data or backup folder is therefore refused (warning in the log and in
the app). Keep a copy of the key apart from the backups (a password manager): backup + key restore everything, the
backup alone does not reveal the encrypted data. Without any key *Administration > Server* shows a red warning, no
token can be stored and organisation data stays unencrypted.

A new key never makes data unreadable that was readable before: without a key nothing can be sealed. If you lose a key
and the server creates a new one in the file, what was sealed with the old one stays lost (tokens are entered again,
organisations need their recovery keys, see below); if the old key turns up, put it into `.env`, where it wins over the
file.

### Organisations and private spaces (2.46)

Every server works the same way: each person has a private space, and organisations are shared workspaces with their own
admins. A new server has no organisation; the first-run setup creates one when you give it a name (you become its admin),
and an instance admin creates further ones under *Settings > Administration > Organisations*. Nobody joins an organisation
by themselves: an admin picks it when adding a person, a registration joins one only through its e-mail domains, and an
organisation admin adds and removes members. A server without any organisation lets everyone see everyone (one household);
once there is one, people see the members of their organisations and the people they share something with; private lists
reach anybody else by e-mail address.

**Lists of the organisation (2.35, 2.56).** Organisation admins find the organisation's shared lists under *Settings >
Organisation > Lists of the organisation*: names, owners and numbers, never the contents. They can archive, restore, delete
from the archive and hand a list over to another member; since 2.56 also *Edit* its name, icon (emoji or picture) and
colour, without needing a role in the list. That is all: tasks, sections, members and settings stay with the owner and the
list's admins. Private lists are never shown or changed, agents cannot use these functions, every change lands in the
dialog's history (old and new value) and the owner and the members get a News entry.

**Finding people by e-mail (2.49).** Under *Settings > Account > Find people* a person can find someone by their full
e-mail address and send a connection request; once it is accepted, both see each other like after sharing a list. Only
accounts that switched on *Findable by e-mail* (off by default) and confirmed their address with a mailed link can be
found, so the server needs mail (SMTP, see *Mail*) for anyone to become findable. A search never shows whether an address
has an account: everything that is not findable gets the same answer. The address book check matches the addresses of the
person's own contacts on the server (they never leave it). Limits: 30 searches and 300 checked addresses per account and
day, plus a brake per client address (`KALMIDO_DISC_PER_IP`, default 60 per 15 minutes). Agents and kid accounts cannot search and are never found.

`KALMIDO_INSTANCE_MODE` is deprecated: `organisation` (and an empty value) are ignored, only `shared` (no organisations,
people see only their own contacts) still applies. `KALMIDO_ORG_NAME` only names the organisation the first-run setup
creates. On the update from a server in the former mode *organisation* (one organisation, no variable), the first start
makes every account a member and the instance's admins its admins once, exactly as every start did before; nothing changes
for anybody.

## Reverse proxy and network

Templates for Caddy, nginx and Traefik: [examples/](../examples/).

**Let CardDAV past the login, too.** Besides `/dav` and `/.well-known/caldav`, contact apps look for
`/.well-known/carddav`. Behind a login proxy add it to the paths that bypass the login, for example in Caddy:

```caddyfile
@kalmido_dav path /dav /dav/* /.well-known/caldav /.well-known/caldav/* /.well-known/carddav /.well-known/carddav/*
reverse_proxy @kalmido_dav 127.0.0.1:3040
```

**The real client address.** Kalmido believes `X-Forwarded-For` only from `KALMIDO_TRUSTED_PROXIES` (default loopback
and the Docker bridge gateway). Two setups go wrong:

- *The proxy runs in a container on its own Docker network.* Its requests arrive from that network's gateway (for
  example `172.18.0.1`), which is not trusted by default. Symptom: every client has the same address in the logs, and a
  few failed logins **lock out everyone** at once. Fix: add that gateway to `KALMIDO_TRUSTED_PROXIES`, or run the proxy
  with host networking.
- *The proxy itself only sees the Docker gateway.* When client connections reach a containerised proxy through Docker's
  userland proxy (for example over IPv6 without IPv6 NAT, or from the host itself), the proxy never learns the client's
  address and forwards the gateway. Run the proxy with host networking (or make sure published ports are NAT-ed, not
  proxied), then check that Kalmido's log (`docker logs kalmido`) shows real client addresses.

The most common case: a proxy such as Caddy in Docker with published ports (`ports: ["80:80", "443:443"]`). Docker's
userland proxy (`docker-proxy`) accepts the connections, so the proxy sees the Docker gateway (`172.x.0.1`) as the client
for every request and passes exactly that on. Two ways out:

```yaml
# 1. the proxy on the host network: it sees the real client addresses (no "ports:" needed)
services:
  caddy:
    image: caddy:2
    network_mode: host
```

```json
// 2. or switch Docker's userland proxy off (/etc/docker/daemon.json, then restart Docker): published ports are NAT-ed
//    by the kernel and keep the client address. For IPv6 also enable "ip6tables": true (Docker 27+ does by default).
{ "userland-proxy": false }
```

Then set `KALMIDO_TRUSTED_PROXIES` to the address Kalmido sees the proxy at (host networking: `127.0.0.1,::1`; a proxy
container on its own network: that network's gateway or the proxy's container address) and nothing else.

**Check it in the app (2.33).** *Administration > Server > Your IP* shows the address the server sees for your own
request, and the proxy it came through (trusted or not). From outside your network it must be your public address, not
a private one like `172.18.0.1`. Kalmido also watches successful sign-ins: when several accounts (default 3,
`KALMIDO_IP_WARN_ACCOUNTS`) sign in from exactly one private address within 7 days, it warns in the server log
(`WARNING client addresses do not arrive ...`, at the start and when it first happens) and under *Administration >
Server* ("Client addresses do not arrive - check the proxy"). Only private sign-in addresses are kept for this, for 14
days; public addresses are never stored. A small office or family behind one NAT address on the same LAN can trigger it
too: then the warning is expected and harmless.

**A CDN proxy sees everything.** With a CDN in proxy mode (for example Cloudflare's orange cloud or a Cloudflare
Tunnel) TLS ends at the CDN: it sees every request and answer in plain text. For privacy use DNS only and terminate
TLS in your own proxy with your own certificate.

**Only over a VPN.** If Kalmido should be reachable only inside your VPN, point the name's A record at the server's
VPN address and get the certificate with a DNS-01 challenge (no open port needed). Do not use the VPN's own sharing
URLs (a mesh VPN's "serve" / "funnel" names, its own device names) for Kalmido: they reach the app directly and
**bypass the login of your proxy**.

**DNS rebind protection.** Many routers and DNS filters drop answers that point a public name to a private or CGNAT
address (the RFC 1918 ranges, CGNAT `100.64.0.0/10`); the name then simply does not resolve at home. Allow your domain in
the rebind protection. On Android, a VPN's DNS can stay stuck after switching from Wi-Fi to mobile data: switch the VPN
off and on.

**Reachable from the internet, or not.** Public list links, forms, incoming webhooks and share links work only for
people who can reach the server. In a VPN-only setup they work for VPN members only.

**HTTP/3 needs UDP.** If your proxy announces HTTP/3 (`Alt-Svc: h3`) but the firewall keeps UDP 443 closed, some
clients (iOS in particular) fail or hang. Open UDP 443, or switch HTTP/3 off in the proxy.

**Mount the proxy configuration as a directory.** A bind mount of a single file keeps pointing at the old file when an
editor or `sed -i` replaces it, so a reload in the container still reads the old content. Mount the folder that holds
the Caddyfile (or nginx configuration) instead.

**Two host names (internal and single sign-on).** Links in mails, push messages and calendar feeds use `PUBLIC_URL`,
so set it to the name people should open. Logging out of Kalmido does not log you out of the sign-on portal. Point API
clients and agents at the host or path where `/api/v1/` bypasses the portal (see [API.md](API.md#behind-a-reverse-proxy)),
never at the portal-protected name.

**Proxy header login.** With `AUTH_PROXY_HEADER` the proxy port must be reachable **only by the proxy**: bind it to
`127.0.0.1` (or the address the proxy connects from) and keep it closed in the firewall. Anyone else who reaches that
port can claim to be any user.

**Sign-on portals: deny by default.** Before family or team members get accounts in your portal, set its default policy
to *deny* and allow each app per group, so a new account does not open every app behind the portal.

## Installed app (PWA) and push

- **Late reminders are skipped.** A reminder more than 6 hours late (after the server was down) is not sent any more;
  check the overdue tasks after an outage.
- **Android energy saving swallows Web Push.** Apps that Android puts to sleep (*sleeping apps*, *battery
  optimisation*) get no push. Exempt the browser that installed Kalmido.
- **On Android, install with Chrome.** Web Push and the installed app work most reliably there.
- **Name, icon and manifest changes show only after a reinstall** of the installed app.
- **A new version on the phone:** close the app completely (or reload it), then check the version under *Settings >
  Help*. An old cached app shows old screens.
- **Offline changes live in the browser** until they are synced: do not clear the site data while you have unsynced
  changes.
- **Only Web Push?** Then remove ntfy topics you do not use: a topic on the public `ntfy.sh` can be read by anyone who
  knows its name.
- **Your own ntfy server:** for the phone's battery set the server's `keepalive-interval` to about 3 minutes, use the
  WebSocket protocol in the Android app, and let your proxy pass WebSocket upgrades.
- **iPhone shortcut for sharing:** build it once in the Shortcuts app and share it for everyone, with import questions
  (placeholders) for the server address and the token, never with your own token inside.
- **The upload token is not an API token.** *Share from your phone* uses each person's upload token for `/drop` only;
  scripts need a personal access token ([API.md](API.md#personal-access-tokens)).

## Database (PostgreSQL)

Since 2.37.0 Kalmido needs PostgreSQL 17 (`DATABASE_URL=postgresql://user:password@host:5432/db`); without it the app
does not start and says why. The `docker-compose.yml` of the repository brings its own server (service `db`,
`postgres:17`, data in `./pgdata`, password `POSTGRES_PASSWORD` in `.env`); nothing else is needed. Coming from an older
version: [Upgrade to 2.37](#upgrade-to-237-postgresql-required).

- **Password in the URL.** Use letters and digits only (`openssl rand -hex 24`): characters like `@`, `/`, `:` or `#`
  break the URL. `POSTGRES_PASSWORD` is only read when `./pgdata` is created; to change it later, also run
  `ALTER ROLE kalmido PASSWORD '...'` inside the database.
- **Settings of the `db` service.** `POSTGRES_INITDB_ARGS=--data-checksums` (damaged pages are reported, not read
  silently; only takes effect when `./pgdata` is created), `max_connections=100`, a `pg_isready` health check that
  Kalmido waits for, and no published port. Keep the image on major version 17 (see "major upgrade" below).
- **Extensions need the database owner.** `init_db` creates `unaccent` and `pg_trgm` (both trusted extensions in the
  official image). With an external server, the user in `DATABASE_URL` must own the database, or create them once yourself.
- **Connections.** Kalmido keeps up to 56 connections (`KALMIDO_DB_POOL_MAX`); `max_connections` of the server must be
  higher (the default 100 is enough for one instance).
- **Timeouts.** A statement may run 30 s (`KALMIDO_DB_STATEMENT_TIMEOUT`, seconds, `0` = no limit; raise it for very
  large instances, for example when deleting a user with many tasks or opening office numbers over many years), a
  transaction may idle 5 minutes. At the start Kalmido waits up to 60 s for the database (`KALMIDO_DB_WAIT`).
- **Backups outside the app** (scripts, a pull from a second machine): use `pg_dump -Fc` with row-level security
  switched on and the system context, otherwise the dump stops or misses rows:

  ```bash
  docker compose exec -T -e PGOPTIONS="-c app.role=system" db pg_dump -Fc --enable-row-security -U kalmido -d kalmido > kalmido.dump
  ```

  Against an external server:

  ```bash
  PGOPTIONS="-c app.role=system" pg_dump -Fc --enable-row-security -h db.example.com -U kalmido -d kalmido -f kalmido.dump
  ```

  Restore with `pg_restore --clean --if-exists --no-owner --no-privileges --single-transaction --enable-row-security`
  and the same `PGOPTIONS`, as the database owner, with Kalmido stopped, then start Kalmido (it creates its functions,
  policies and rights again). The attachments are not in the database: copy the data folder as well.
- **After a PostgreSQL major upgrade, reindex.** The search index depends on the `unaccent` rules of the server:
  run `REINDEX DATABASE kalmido;` once after moving to a new major version. A new major version (18, ...) cannot open the
  `./pgdata` of 17: dump with 17, start the new version on an empty folder, restore.

### Own or managed PostgreSQL server

Set `DATABASE_URL` in `.env` and remove the `db` service and the `depends_on` block from `docker-compose.yml`.

- **Best: a user that owns the database and has neither superuser nor `BYPASSRLS`.** The organisation policies then
  apply to it directly (Kalmido forces row-level security also for the table owner); nothing else to set up.

  ```sql
  CREATE ROLE kalmido LOGIN PASSWORD '...';
  CREATE DATABASE kalmido OWNER kalmido;
  ```
- **A user that bypasses row-level security** (a superuser, as in the official image, or a role with `BYPASSRLS`):
  Kalmido then creates the role `kalmido_app` (no login, no bypass) and its connections switch to it. Creating it needs
  superuser or `CREATEROLE`. If the user has neither, create the role once yourself:

  ```sql
  CREATE ROLE kalmido_app NOLOGIN NOSUPERUSER NOBYPASSRLS;
  GRANT kalmido_app TO kalmido;
  ```

  Without that role row-level security cannot be enforced. With several organisations (or `KALMIDO_INSTANCE_MODE=workspaces`
  set) Kalmido then refuses to start (exit code 3, the log says what to do); with at most one it starts, but raises a
  security alert on every start and shows a notice under *Settings > Users > Whole server > Admin alerts*.
- **One role for several databases.** `kalmido_app` belongs to the whole server; several Kalmido databases on one
  server share it, which is fine (the policies depend on the session, not on the role).

## Upgrade to 2.37 (PostgreSQL required)

2.37 moves the data from the SQLite file `data/tasks.db` into PostgreSQL. On the first start Kalmido does this by
itself, in one transaction, and checks the result (row counts and checksums per table) before it commits. Plan a short
maintenance window: the app is offline while it copies (seconds for a family instance, a few minutes for large ones).

1. **Back up first.** In the app: *Back up now* (Settings > Users > Whole server > Backups) and copy the zip off the
   server. Then stop Kalmido and keep a plain copy of the database file:

   ```bash
   docker compose stop kalmido
   ```

   ```bash
   mkdir -p ../kalmido-before-2.37 && cp -p data/tasks.db* ../kalmido-before-2.37/
   ```
2. **Add the database service.** Take the `docker-compose.yml` of 2.37 (the `db` service, the `DATABASE_URL` line and
   the `depends_on` block of the `kalmido` service); keep your own changes (ports, volumes) as they were.
3. **Set the password and the version** in `.env`:

   ```bash
   echo "POSTGRES_PASSWORD=$(openssl rand -hex 24)" >> .env
   ```

   and `KALMIDO_IMAGE=ghcr.io/gegenschuss/kalmido:2.37.0` (if you pin the version).
4. **Fetch the images and start the database:**

   ```bash
   docker compose pull
   ```

   ```bash
   docker compose up -d db
   ```
5. **Optional dry run.** It reads `tasks.db`, checks and counts everything, reports what it would correct and writes
   nothing:

   ```bash
   docker compose run --rm kalmido python app.py migrate-sqlite --check
   ```
6. **Start Kalmido.** The move runs on this start:

   ```bash
   docker compose up -d
   ```

   ```bash
   docker compose logs -f kalmido
   ```

   The lines starting with `migrate-sqlite:` show the progress and the result.
7. **Check** that the app opens and the numbers look right (users, lists, tasks, attachments).

What happens to the old files:

- `data/tasks.db` is renamed to `data/tasks.db.migrated-<date-time>`; it is never deleted. Later starts ignore it.
- `data/backups/pre-postgres-<date-time>.db` is a copy of the source taken before the move,
  `data/backups/migration-report-<date-time>.json` the report (counts and checksums per table, corrections).
- Backups from before 2.37 (zips with a `tasks.db`) can still be restored in the app; they go through the same move.
- If the move fails, nothing is kept in PostgreSQL, `tasks.db` stays untouched and the container stops with exit code 3
  and the reason (table and row) in the log; with `restart: unless-stopped` it keeps restarting and trying again
  (no new files pile up: the copy of the old database is only made after a successful move, a failed one overwrites
  `migration-report-failed.json`). Stop it (`docker compose stop kalmido`), fix the cause or go back (below), then
  start again.

**Going back to 2.36** (only if 2.37 does not work for you; everything entered since the move is lost):

```bash
docker compose down
```

Pin the previous version in `.env` (for example `KALMIDO_IMAGE=ghcr.io/gegenschuss/kalmido:2.36.2`), then put the old
file back and move the new database folder aside (a later upgrade needs an empty database again):

```bash
mv data/tasks.db.migrated-<date-time> data/tasks.db
```

```bash
mv pgdata pgdata.unused-$(date +%Y%m%d)
```

```bash
docker compose up -d kalmido
```

2.36 ignores `DATABASE_URL` and the `db` service; you can leave them in place for the next attempt.

## Backup and encryption

- **In-app backups (2.37.0).** *Back up now* and the automatic backups write a zip with a `pg_dump` of the database
  (`kalmido.dump`), the attachments, the office files and a manifest with checksums (format 2); restoring runs in
  maintenance mode with a safety backup first. Backups from before 2.37 (SQLite, a `tasks.db` in the zip) can
  still be restored: the database file goes through the same move to PostgreSQL as an upgrade. Since 2.48 the archive
  also holds the file store (`attachments/files/<id>/`, every version) and the project files (`attachments/lists/<id>/`,
  which earlier archives left out); a server before 2.48 restores such an archive without them.

- **Fail closed when the data disk is missing.** Keep the data folder on its own disk or volume and mount it so that
  Docker refuses to start without it, instead of creating an empty folder (an empty start shows the setup page again;
  since 2.45 it asks for the code from the log, but the data would still look gone):

  ```yaml
  volumes:
    - type: bind
      source: /srv/kalmido/data
      target: /data
      bind:
        create_host_path: false
  ```
- **After a move, check the attachments.** Compare the number and the total size of the files in the data folder's
  `attachments/` with the old server, not only the database (a copy that stopped half-way still starts fine).
- **Encryption at rest.** Put the data disk on LUKS (or your platform's disk encryption) and keep the key off the
  server. For unattended reboots, let the server unlock from a second machine (a key fetched over the network, for
  example with clevis / tang), so a stolen disk alone is unreadable.
- **Offsite backups by pull.** Let a second machine pull the backups (the server cannot delete them), encrypt them
  there (for example with `age`, or Kalmido's own *Encrypt backups*), and run a restore test now and then.
- **Old snapshots contain plain text.** Filesystem, VM or provider snapshots taken before you switched on encryption
  still hold the data unencrypted: delete them.

## Encryption of organisation data

Since 2.42 the server encrypts the sensitive data of every organisation **at rest** with a key of its own (AES-256-GCM).
Nothing changes for the people: whoever may see a value or a file (also an agent through the API) sees it as before;
only the database and the data folder hold ciphertext.

At a glance (the same two lists as in Settings > Administration > Organisation, since 2.46.1):

| Encrypted (with `KALMIDO_SECRET_KEY`) | Not encrypted |
|---|---|
| Bank and tax data of the company | Tasks |
| Purchase prices and margins | Notes |
| Framework contract rates | Descriptions |
| Senders of finished documents | Comments |
| The log of the documents | Contacts |
| Files of organisations | Chats |
| Stored access tokens (Git, client secret of the single sign-on) | |

- **What is encrypted:** the office's bank and tax data (IBAN, BIC, bank, tax number, VAT ID), the free company lines,
  the frozen sender of finalised documents, purchase prices of positions (and the costs / margin of a document), the
  special rates of framework contracts, office log entries that carry such values, and the stored files: attachments
  of tasks in the organisation's lists (comments included), project files of its lists, stored invoices / credit notes
  (PDF/A-3 and e-invoice XML) and the archived PDFs of the legacy import. A stored PDF stays a PDF/A-3 without a
  password: it is sealed only on disk and served as the original (same checksum). Not encrypted: names, addresses,
  task texts, logos, profile pictures, files in agent chats and private lists, the search index. The cache of texts read
  from attachments (`textcache/`, at most 30 days) is sealed with a key derived from the master key.
- **The keys.** `KALMIDO_SECRET_KEY` (32 random bytes, base64) is the master key. Each organisation gets a random key,
  stored in the database only wrapped with a key derived from the master key. Without `KALMIDO_SECRET_KEY` nothing is
  encrypted (everything as before); *Settings > Organisation > Encryption* says so.
- **Existing data** is encrypted by a background pass five minutes after the start, so an update that fails its health check
  is rolled back before anything changes (idempotent, in batches; the log says `orgcrypt: encrypted at rest: ...`). The instance admin can pause it (*Settings > Administration > Organisation >
  Encrypt organisation data*): then new data is stored unencrypted, encrypted data stays readable.
- **Keep the master key apart from the backups.** A backup contains the wrapped organisation keys but never
  `KALMIDO_SECRET_KEY`: backup + master key restore everything; a backup alone does not reveal the encrypted data.
- **Recovery key.** An organisation's admins can show its recovery key in *Settings > Organisation > Encryption*
  (after their password; the showing is noted in the office log). Store it offline. If the master key is lost: set a
  new `KALMIDO_SECRET_KEY`, start, then for each organisation

  ```
  docker compose exec -T kalmido python -m kalmido.admin.orgcrypt_cli rewrap --org <id> --recovery-file - < recovery.txt
  ```

  (the key is read from a file or stdin, never from the command line). `rewrap` first tests the key on the
  organisation's encrypted data and changes nothing when it does not fit (exit 1, e.g. a typo); an organisation without
  any encrypted data needs `--force`. The replaced wrapped key stays in the key row, so an old master key that turns up
  later still opens it. Without the master key **and** without the
  recovery key the encrypted data is lost. A wrong master key never shows garbage: the app answers with a clear error.
- **Commands:** `python -m kalmido.admin.orgcrypt_cli status` (per organisation: key, encrypted / plain fields and
  files), `encrypt-all`, `decrypt-all`, `rewrap`. All of them can be repeated and print counts only.
- **Before a downgrade below 2.42** run `decrypt-all` (it switches the encryption off first, then turns every field and
  file back into plain text and exits with 0 only when nothing is left encrypted); then start the older image.
- **Deleting an organisation** deletes its key and its office folder: whatever of it is left encrypted can no longer
  be read on this server. Files of lists that moved to another workspace are re-sealed first. Older backups still
  contain the wrapped key, so with the master key a restored old backup can read that organisation's data again.

## Organisation export

Since 2.42 an admin of an organisation can export it as one encrypted archive: *Settings > Organisation > Export the
organisation*. The server builds it in the background (one at a time per organisation) and keeps the file for 24 hours
in the data folder (`exports/`, not part of the backups); after that, or with *Delete now*, it is removed. Every export
and download is written to the office log (who, when, size).

- **What is in it.** A zip with `manifest.json` (format version, Kalmido version, counts, SHA-256 of every entry), one
  JSON file per area and the files: the organisation's lists (sections, members and roles, fields, tags, status
  updates, links, milestones, history, project notes, project files, forms, playbooks), all tasks of those lists
  (subtasks, field values, dependencies, history, the trash), comments, attachments, time entries on those lists, the
  team chat channels of those lists, the organisation's calendars with their events, its address books with their
  contacts, its clients, the whole office (company data, services, equipment, packages, texts, framework contracts,
  quotations / invoices / credit notes with positions, payments, PDF and XML files, the archive, the office log), its
  file store (2.48: folders, files with every version, shares, the access history, the trash; `store/*.json`,
  `files/store/`) and the members with their roles (name, user name, e-mail address).
- **What is not in it.** Lists outside the organisation (the members' private space), other organisations, passwords,
  sessions, tokens, two-factor data, push subscriptions, webhook secrets, connection credentials, and the members'
  personal data (settings, own tags, filters, templates, direct messages, agent chats).
- **Encrypted content.** Fields and files that the server encrypts with the organisation's key are plain text inside
  the archive (the archive itself is encrypted). Content encrypted in the browser by its author (encrypted task notes
  and files) stays ciphertext; the manifest lists it under `client_encrypted`.
- **Opening it.** The archive is encrypted with AES-256-GCM under the organisation's key. You need the organisation's
  recovery key (*Settings > Organisation > Encryption*) and the tool `tools/kalmido_export_decrypt.py` from the
  repository (Python 3.8+ and the package `cryptography`):

  ```sh
  python3 tools/kalmido_export_decrypt.py acme-2026-10-14.kalmido-export -o acme.zip
  # asks for the recovery key; or: --key-file key.txt (never put the key on the command line)
  ```

  The tool checks every block (a wrong key, a damaged or shortened file is refused) and then the checksums of the
  manifest.
- **Without `KALMIDO_SECRET_KEY`** the organisation data is not encrypted and the export is refused: set the server key
  first (see the section on the encryption of the organisation data).
- **Import** of such an archive into another Kalmido follows in a later version.

## Server hardening

A short checklist for a new server:

- **Two SSH keys** (one as a spare, kept apart), password login off where you can, **two-factor login at your hosting
  provider**, and **automatic security updates** with a nightly reboot window.
- **Create the first admin before the world can reach the app.** Open the setup page through the local port (for
  example `ssh -L 3040:127.0.0.1:3040 server`, then `http://127.0.0.1:3040`) before you point DNS at the server or open
  the firewall.
- **Docker ports bypass ufw.** A published port (`3040:3040`) is reachable from outside even when ufw blocks it,
  because Docker writes its own firewall rules. Publish ports only on `127.0.0.1` (as the shipped `docker-compose.yml`
  does) and write the reason as a comment next to the line, so nobody "fixes" it later.
- **fail2ban for failed logins.** Kalmido logs `login failed for '<user>' from <address>` and has its own lockout; to
  block repeat offenders at the firewall, send the container log to journald (`logging: {driver: journald}`) and add a
  filter and a jail:

  ```ini
  # /etc/fail2ban/filter.d/kalmido.conf
  [Definition]
  failregex = login failed for .* from <HOST>$

  # /etc/fail2ban/jail.d/kalmido.conf
  [kalmido]
  enabled = true
  backend = systemd
  journalmatch = CONTAINER_NAME=kalmido
  filter = kalmido
  maxretry = 5
  findtime = 10m
  bantime = 1h
  ```

  This needs the real client address (see above). If the proxy runs in Docker, ban in the `DOCKER-USER` chain.
- **The image registry is IPv4 only.** `ghcr.io` has no IPv6 address: an IPv6-only server needs NAT64 or another route
  to pull the image.
- **Limit the containers.** Give Kalmido and the proxy a memory and process limit (`mem_limit`, `pids_limit`), and
  `cap_drop: [ALL]` with `no-new-privileges` on the proxy too, not only on Kalmido.
- **A maintenance page.** Let the proxy answer 502 / 503 / 504 with a short "back in a minute" page (Caddy
  `handle_errors`, nginx `error_page`) instead of a bare error during updates.
- **Monitoring.** `GET /api/health` needs no login, contains no data and answers `{"ok": true}` after a database query;
  point your uptime monitor at it (let it pass a login proxy).
- **Raspberry Pi and small boards:** run from an SSD, not an SD card; some USB-to-NVMe bridges drop out under load (pick
  one known to work, or one with a quirk setting); a busy USB 3 port can disturb 2.4 GHz Wi-Fi and Bluetooth nearby.
- **Changed `.env`? Recreate, do not restart.** `docker compose restart` keeps the old environment; run
  `docker compose up -d` so the container is recreated with the new values.

## Intrusion alerts

Uptime monitoring tells you when the app is down, not when someone got in while it keeps running. Two layers help.

**In the app (2.36.2).** Kalmido reports security events through the admin alerts (*Settings > Users > Whole server >
Admin alerts*, kind *Security events*, can be switched off like the other kinds; same cooldown and hourly cap):

- a new instance admin, however the flag was set (a role change, a new account, single sign-on group sync, a change in
  the database)
- a new admin of an organisation
- a new agent and a new agent token
- an admin (of the instance or an organisation) signing in from an address that is not among their last ten

Admins, agents and tokens are compared on every watchdog tick, so every way of getting the role counts. The first tick
after the update and the first sign-in of each admin after the update only record the current state, nothing is
reported for them. Sign-in addresses are stored as a keyed hash (with `KALMIDO_SECRET_KEY`); the alert itself names the
address. Alerts carry ids, user names and addresses only, never content.

Each event also writes one line into the server log, whether admin alerts are on or not, so a log watcher outside the
app can pick it up without access to the data:

```
kalmido-security: {"event": "new_admin", "user_id": 7, "username": "jana"}
```

Events: `new_admin`, `new_org_admin` (+ `org_id`), `new_agent`, `new_agent_token` (+ `agent_id`, `token_id`),
`admin_login_new_ip` (+ `ip`, `via`). For example with journald (`logging: {driver: journald}`):
`journalctl -f CONTAINER_NAME=kalmido | grep --line-buffered kalmido-security:` piped into your notifier.

**On the host.** Recommended for a public server, all reported to a second machine (a small board at home is enough)
or a push service, not only to the server itself:

- **SSH logins:** a watcher on the journal reports every successful login with user, key and source address; known
  addresses and keys can be quiet. No PAM change needed, so a broken watcher never blocks a login.
- **Keys and accounts:** changes to `authorized_keys`, `/etc/passwd`, `/etc/shadow`, `/etc/sudoers*` and the sshd
  configuration, reported at once (file name and key count, not the content).
- **Checksums:** a daily comparison (for example AIDE) of the system binaries, `/etc`, the compose file, `.env` and the
  proxy configuration; take a new baseline after system updates and after your own app updates.
- **Containers:** a container or image you did not start, or an image hash that changed without an update by you.
- **fail2ban:** a daily summary only when the bans are far above normal.
- **Dead man's switch:** the server sends a signed sign of life every few minutes; the second machine alarms when it
  stops while the app is still reachable. Check the time of each sign of life (not in the future) and remember that
  the signature protects the transport, not against someone with root on the server.

Trigger every alert once on purpose after setting it up, the dead man's switch too.

## Mail

- **Give *Tasks by e-mail* its own mailbox.** Kalmido marks every mail it reads as read and imports it as a task; a
  mailbox you also use yourself gets mixed up.
- **Shorten forwarded mails (optional, per person).** Settings > Integrations > *Tasks by e-mail* > *Shorten forwarded mails*: the
  forwarding header becomes one line, signatures, legal notices and older quoted replies are cut, the original mail stays
  attached as `.eml`. Off by default.
- **Deliver directly, do not forward.** Many forwarding rules drop the plus part of an address (`tasks+token@…`), and
  then Kalmido cannot tell whose task it is.
- **Sender domain:** for the daily summary over SMTP, set up SPF, DKIM and DMARC for the sender domain, or the mails land
  in spam.
- **Forgot your password? (2.49):** the login page shows the link only when outgoing mail (SMTP) is set up. A person
  enters their e-mail address or user name and gets the same one-time link an admin can send (*Settings > Users >
  Send a link to set a new password*): valid for 7 days, used once, only its hash is stored, built from `PUBLIC_URL`
  (never from the request's host). The page answers the same whether the account exists or not, at most one link per
  account in five minutes, rate limited per address and sender. Kid accounts, agents, disabled accounts and accounts
  without a password (single sign-on only) get no link: their parents or an admin reset them. Two-factor sign-in stays
  required: after the new password the second step follows, and all other sessions of the account end.

## Documents: text recognition

The area *Documents* (2.48.0) reads the text of uploaded PDFs and images: the text layer of a PDF, and for scans the
local text recognition Tesseract (German and English) with `pdftoppm` -- both are part of the image (about 120 MB more).
Nothing leaves the server, no external service and no language model is involved. An image without them (an older own
build) keeps working: such documents show *Text recognition is not available on this server*.

Each tool runs as a short-lived process with limits; tune them for small hosts:

| Variable | Default | Meaning |
|---|---|---|
| `KALMIDO_OCR_PARALLEL` | `1` | Documents recognised at the same time |
| `KALMIDO_OCR_PAGES` | `30` | Pages of one document recognised at most |
| `KALMIDO_OCR_PAGE_S` | `60` | Seconds per page (raster + recognition) |
| `KALMIDO_OCR_MEM_MB` | `1024` | Memory of one tool |
| `KALMIDO_OCR_LANGS` | `deu+eng` | Tesseract languages (installed ones only) |
| `KALMIDO_DOCS_SCAN_S` | `60` | Seconds between two looks into the inbox folders "Dokumente/Eingang" |

The recognised text, amounts, sender names, rules and the learnt models are sealed with the workspace's key when
`KALMIDO_SECRET_KEY` is set (see [Encryption of organisation data](#encryption-of-organisation-data)); the search uses
keyed hashes of the words, no plain index. Without `KALMIDO_SECRET_KEY` the hash key of the word index is a fixed one
(the same on every server): whoever reads the database can then test words against it -- set the server key. With *Tasks by e-mail* set up, every person and organisation can create a
forwarding address for documents in the documents' settings: PDFs and images attached to mails sent there become
documents.

### Import from Paperless-ngx (2.48)

Only on a self-hosted server (a hosted server shows nothing of it): an existing Paperless-ngx instance can be connected
once per workspace -- by an organisation's admin for the organisation, by a person for their own space -- under
*Documents > Settings > Paperless-ngx* with its address and an API token (Paperless-ngx: *My profile > API auth token*).

- **Read only:** Kalmido only sends GET requests. Nothing in Paperless-ngx is changed, moved or deleted.
- **Preview first:** the number of documents and how tags, correspondents and document types are taken over: a tag
  becomes a tag, a folder of the documents or is left out; correspondents become senders, document types types (names can be
  changed in the preview).
- **What comes along:** the original file, the recognised text (no new recognition), the date, tags, correspondent, type,
  and custom fields, notes and the archive serial number as text below the document's text.
- **Never twice:** a document already imported (Paperless-ngx id per instance address) or the same file already in the
  workspace (checksum) is left out, also when the import runs again.
- **In the background:** progress and *Stop* in the settings; optionally *Bring in new documents automatically* every
  15 minutes up to once a day (only Paperless-ngx -> Kalmido).
- **Network:** http/https only, timeouts, no redirects, at most `TASKS_MAX_FILE_MB` per file. An instance in the local
  network is an internal address: allow its host under *Settings > Administration > Advanced* (or
  `KALMIDO_CALENDAR_ALLOW_HOSTS=paperless.example.com:8000`), the same allow-list as for calendar subscriptions.
- The token is always stored sealed with a key derived from `KALMIDO_SECRET_KEY` (also when the encryption of
  organisation data is off) and never shown again. Without a server key the connection cannot be set up.

### Newsletter: listmonk, Brevo, CleverReach (2.55)

Kalmido sends no newsletters itself. It keeps the contacts, segments and consent and syncs them with a newsletter
service, which does the sending, the double opt-in, the unsubscribe link, bounces and statistics (the proof of consent,
one-click unsubscribe and deliverability belong there, not on a shared task server). Under *Contacts > More >
Newsletter…* an organisation's admin connects the service for the organisation, a person for their own space.

- **Contacts that go out:** only from the workspace's own address books (an organisation's address books, or a person's
  own books outside every organisation -- never a member's private book), only with an e-mail address and the consent
  *Consented* (with a source, e.g. the sign-up form). Option for listmonk: also *Double opt-in pending* -- they go as
  unconfirmed and listmonk sends its opt-in mail.
- **Segments:** groups, companies and address books (any match within one kind, all kinds must match) -> one list at the
  service (an existing one, or a new one named like the segment).
- **Both directions:** each run first takes unsubscriptions, bounces and confirmed opt-ins from the service back to the
  contacts, then adds, renames and takes off the list what Kalmido put there and no longer matches. An unsubscribed or
  bounced address is never subscribed again by Kalmido and stays blocked in Kalmido; if the person
  subscribes again through the service's own form, Kalmido leaves that subscription alone. Manually with
  *Sync now*, or once a day. Every run is logged (numbers and error codes, never addresses or access data).
- **Access data** are stored sealed with a key derived from `KALMIDO_SECRET_KEY` (needed) and never shown again; the
  address goes through the same SSRF guard as calendar subscriptions (an instance in the local network: allow its host,
  e.g. `KALMIDO_CALENDAR_ALLOW_HOSTS=listmonk.example.com:9000`).
- **Brevo and CleverReach** follow their public API documentation and are marked *Preview*: they are not yet tried
  against the real services.

Setting up listmonk (version 4 or newer) for Kalmido:

1. Run listmonk (its own docker compose file) next to Kalmido, reachable over https or in the local network.
2. In listmonk: *Admin > Users > New*, type **API**, a role that may manage lists and subscribers (and *subscribers:sql_query*,
   used to find an address that is already known). Copy the token shown once.
3. In Kalmido: *Contacts > More > Newsletter…*, service *listmonk*, its address (e.g. `https://listmonk.example.com`),
   the API user's name and the token.
4. Mark the consent of your contacts (contact card > *Newsletter*), create a segment and press *Sync now*.

## Moving to a new server

1. **Before:** lower the DNS TTL of the name a day ahead; make a backup (*Back up now*).
2. **Copy:** the data folder (attachments, backups) and the database (`pg_dump`, see above, or the database folder
   with PostgreSQL stopped), the `.env` and above all **`KALMIDO_SECRET_KEY`** (or the file `secret/kalmido.key`):
   without it, stored secrets (repository tokens, sign-on client secret) cannot be decrypted and must be
   entered again.
3. **Start** the new server and check the attachments (number and size, see above) and the counts (users, lists,
   tasks; `GET /api/v1/admin/status` with an admin token) against the old server.
4. **Switch DNS.** Old answers stay cached for a while: test the new server directly with
   `curl --resolve tasks.example.com:443:<new address> https://tasks.example.com/api/health`.
5. **Tell people what to redo,** because it is bound to the old server or name: passkeys (if the name changed), the
   installed app and push permissions (reinstall), calendar and contact accounts (CalDAV / CardDAV), shortcut URLs for
   sharing, and calendar subscription (ICS) links.

## Production updates

- **Pin the version** (`KALMIDO_IMAGE=ghcr.io/gegenschuss/kalmido:<version>`, not `latest`), so an update happens when
  you decide.
- **A safe order:** backup, then pull and start, then check `GET /api/health` and a few counts (users, lists, tasks,
  attachments) against the values before. If anything is off, roll back automatically to the previous version and the
  backup.
- **Keep the previous image** until the new version has proven itself; do not prune images right after an update.

## Support Kalmido (supporter licence)

Since 2.74. A supporter licence is voluntary and paid once. It **unlocks nothing**: every feature stays free (AGPL-3.0).
It only shows a small "Supporter" badge in Settings > Help > About and in Settings > Account. It exists on self-hosted
servers only; with `KALMIDO_HOSTED=1` the section, the badge and the hint are hidden and the routes answer 404.

- **Two kinds.** A *server licence* counts for the whole instance (only admins enter or remove it); a *personal licence*
  counts for one account (every person enters their own).
- **Checked offline.** A key looks like `KSUP1.<data>.<signature>` (Ed25519). The server checks the signature against
  the public key built into Kalmido; nothing is sent anywhere. A key carries only its kind, a date and a label, nothing
  about the server, so it keeps working after a move. The key itself is never shown again, logged or exported; the app
  shows the kind, the date and the label.
- **Remove / Undo.** Removing a licence is one undo step (the server keeps the previous key for that).
- **The hint.** Admins see a quiet, dismissable line at the top at most once a year, never in the first 30 days of a
  new server, and only while there is neither a server licence nor their own personal licence. No push, no e-mail.
  Settings > Help > Support Kalmido > "Remind me once a year" turns it off. Members never see it.
- **Payment link.** `KALMIDO_SUPPORT_URL=https://…` shows a "Become a supporter" button in that section. Unset (the
  default) means only the explanation and the key field are shown; only `https://` addresses are accepted.

| Variable | Default | Meaning |
|---|---|---|
| `KALMIDO_SUPPORT_URL` | empty | Payment page for supporter licences (https only); empty = no button |
| `KALMIDO_SUPPORTER_EXTRA_PUBKEYS` | empty | Further trusted public keys (base64, comma separated) -- for tests; a licence unlocks nothing |

Keys are made with `tools/supporter_key.py` (`genkey --out FILE` keeps the private key outside the repository with mode
600 and prints only the public key; `sign --key FILE --type server|person [--id X] [--date YYYY-MM-DD]` prints a key).
