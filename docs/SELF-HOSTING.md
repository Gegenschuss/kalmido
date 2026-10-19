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
- [Encryption of private files](#encryption-of-private-files)
- [Encryption in the browser (2.64)](#encryption-in-the-browser-264)
- [Exporting encrypted content](#exporting-encrypted-content)
- [Organisation export](#organisation-export)
- [Moving from and to app.kalmido.com](#moving-from-and-to-appkalmidocom)
- [Server hardening](#server-hardening)
- [Intrusion alerts](#intrusion-alerts)
- [Errors in the browser (2.102)](#errors-in-the-browser-2102)
- [Mail](#mail)
- [Virus scan of uploads](#virus-scan-of-uploads)
- [Documents: text recognition](#documents-text-recognition)
  - [Import from Paperless-ngx (2.48)](#import-from-paperless-ngx-248)
- [Related tasks: the embedding service (2.59)](#related-tasks-the-embedding-service-259)
- [Several servers in one app (2.73)](#several-servers-in-one-app-273)
- [Capacity, health and a worker process (2.102)](#capacity-health-and-a-worker-process-2102)
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

**Compression (2.65).** Kalmido compresses its JSON answers itself (gzip, from 1 KB on) when the client accepts it; with
many tasks the start state shrinks to about a twentieth. A proxy that compresses too (Caddy `encode`, nginx `gzip`) sees the
`Content-Encoding` header and leaves those answers alone, so it can stay on for the static files.

**Two host names (internal and single sign-on).** Links in mails, push messages and calendar feeds use `PUBLIC_URL`,
so set it to the name people should open. Logging out of Kalmido does not log you out of the sign-on portal. Point API
clients and agents at the host or path where `/api/v1/` bypasses the portal (see [API.md](API.md#behind-a-reverse-proxy)),
never at the portal-protected name.

**Proxy header login.** With `AUTH_PROXY_HEADER` the proxy port must be reachable **only by the proxy**: bind it to
`127.0.0.1` (or the address the proxy connects from) and keep it closed in the firewall. Anyone else who reaches that
port can claim to be any user.

**Kid accounts and the parents' PIN behind a header login.** The PIN (Family > the kid's card > PIN) is entered into a
Kalmido sign-in session. A kid who is signed in only through the proxy header has no such session and can never enter
the PIN: with a PIN set, its settings, account and logout stay closed for good (ticking off and asking for rewards keep
working). Way out: give the kid a Kalmido password and let it sign in on the Kalmido login page (no header for that
account), or remove the PIN on the kid's card.

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
  higher (the default 100 is enough for one instance). Since 2.102 the pool follows the web threads (`KALMIDO_THREADS`,
  see [Capacity, health and a worker process](#capacity-health-and-a-worker-process-2102)), and the start warns in the log
  when the containers could open more connections than the server allows.
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
  which earlier archives left out); a server before 2.48 restores such an archive without them. 2.79.0: also the files of
  agent chats (`attachments/chat/`), the receipts of the household budget (`attachments/budget/<id>/`) and the document
  previews (`attachments/docthumbs/`), which archives up to 2.78 left out although their rows were in the dump; the manifest
  counts files outside the known folders (`skipped_files`, the server log names their folders). An older server refuses
  an archive with these members, restore it with 2.79 or newer.

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
- **Leftover file versions (2.97.0).** Once a night the server compares the file store folders (`attachments/files/<id>/`)
  with the versions in the database and removes stored files no version names and that are older than a day (left behind
  when the server stopped in the middle of a move between workspaces); at most 200 folders per watchdog tick, the server log
  names the number (`files cleanup: N stored file(s) without a version removed`).
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
| Files in the private space (2.64) | |
| Household budget (2.72) | |
| Stored access tokens (Git, client secret of the single sign-on) | |

- **What is encrypted:** the office's bank and tax data (IBAN, BIC, bank, tax number, VAT ID), the free company lines,
  the frozen sender of finalised documents, purchase prices of positions (and the costs / margin of a document), the
  special rates of framework contracts, office log entries that carry such values, and the stored files: attachments
  of tasks in the organisation's lists (comments included), project files of its lists, the lists' own pictures
  (2.58.0; older ones are sealed by the encryption pass at the next start), stored invoices / credit notes
  (PDF/A-3 and e-invoice XML) and the archived PDFs of the legacy import. A stored PDF stays a PDF/A-3 without a
  password: it is sealed only on disk and served as the original (same checksum). Not encrypted: names, addresses,
  task texts, logos, profile pictures, the search index. Files in the private space: see the next section (2.64). The cache of texts read
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

## Encryption of private files

Since 2.64 the files of the **private space** are encrypted at rest as well, with a key per person (account key,
AES-256-GCM, wrapped with the same master key `KALMIDO_SECRET_KEY` as the organisation keys). This is encryption **on the
server**, not in the browser: the server opens a file for everyone who may see it, exactly as before (a private list
shared with others, an agent the list is shared with); the database and the data folder hold ciphertext only.

- **Which files:** attachments of tasks and comments in lists without an organisation, project files of those lists,
  files shared or mailed into them, the own file store (documents included) and the files in chats with agents. A
  file of a private list is sealed with the key of the list's owner. Not encrypted: task texts, comments, notes, profile
  pictures (as for organisations).
- **Household budget (2.72).** Amounts, titles, notes and counterparts of the entries, the recurring items and the
  monthly limits of a budget are encrypted with the key of the budget list's owner, its receipts are sealed like
  attachments. Category names and dates stay plain. The same background pass, `decrypt-all` and `decrypt-private`
  cover them; a budget handed to another owner is resealed for that person.
- **Moving.** A file follows its task: moved into an organisation's list it gets the organisation's key, moved into
  another person's list that person's key, a list moved into or out of an organisation or handed to a new owner the
  same (a short background pass after the change; until then the file stays readable with its old key).
- **Existing files** are encrypted by the same background pass as the organisation data (five minutes after the start,
  idempotent, in portions of 200 files with a short pause; `KALMIDO_ORGCRYPT_PAUSE` in seconds, default 0.2). The log
  says `orgcrypt: encrypted at rest: ... files in ... organisations and the private spaces, ... files resealed`.
- **Deleting an account** deletes its key: whatever is left encrypted with it can no longer be read. Files of lists the
  person handed over earlier are re-sealed for their new owner first.
- **Switch.** Private files follow *Encrypt organisation data* (`org_encrypt`) and have a switch of their own,
  `private_encrypt` (default on), set by the commands below.
- **The way back** (before a downgrade below 2.64, or to switch it off):

  ```bash
  docker compose exec -T kalmido python -m kalmido.admin.orgcrypt_cli decrypt-private
  ```

  It sets `private_encrypt` to 0 first (new private files stay plain), then turns every file sealed with an account
  key back into plain text and exits with 0 only when none is left. `encrypt-private` switches it on again and seals
  them. `decrypt-all` (see above) also covers the private files. `status` shows `private_encrypt` and the counts.
- **There is no recovery key for account keys.** Keep `KALMIDO_SECRET_KEY` safe (a password manager, apart from the
  backups). If you change it on purpose, keep the earlier key and rewrap the account keys with it after the start:

  ```bash
  docker compose exec -T kalmido python -m kalmido.admin.orgcrypt_cli rewrap-accounts --old-key-file - < old-key.txt
  ```

  (the earlier key is read from a file or stdin, never from the command line; `status` counts account keys made with
  another server key as `keys_other_server_key`). Without the master key the private files are lost.
- **Your own data export** (*Settings > Data > Export*) is JSON and lists the files without their content, as before.
  To take the files themselves out of the data folder in plain text, run `decrypt-private` first.
## Encryption in the browser (2.64)

Kalmido has two kinds of encryption. They are independent and can be used together:

| | Server-side, per organisation (2.42) | In the browser, per list / list chat / knowledge space (2.64) |
|---|---|---|
| Key | derived from `KALMIDO_SECRET_KEY`, one per organisation | a random key per list or space, created in the browser, wrapped for each member with their personal keys |
| Who can read | the server, so everyone who may see the value (also agents) | only members whose browser is unlocked; not the server, its database, its backups, the operator or administrators |
| Protects | database leaks, backups, the data folder | the same, and also the operator and the host |
| Does not protect | an operator or host with access to the running server | members who already saw the content, metadata (dates, assignees, who writes when, text lengths) and a changed script delivered by the server itself |
| Covers | office data and files of organisations | lists (titles, descriptions, comments, notes, free-text fields), the chat and the files of such a list, and knowledge spaces (page names and texts) |

In the app the second kind is called "Encrypted in the browser". "End-to-end" is only used in the explanation, together with its
limit: a web app loads its code from the server, so a server whose code was changed could capture the passphrase. Nothing in a
browser can notice that.

- **Setting up.** Every person sets up their encryption once (*Settings > Account*): a passphrase and a recovery code. The owner
  or admin of a list (or of an organisation's knowledge space, or the owner of the private space) then switches the lock on; all
  members need their encryption set up, and the browser converts the existing content with a progress bar. Members without it
  wait on a list ("key pending") until an admin releases the key.
- **Server settings.** None. The feature needs HTTPS (the browser's WebCrypto) and works with or without `KALMIDO_SECRET_KEY`.
- **What drops out** where the lock is on: agents and API tokens (no texts, no writes), e-mail intake, public links, texts in
  calendar subscriptions, notifications and digests, server-side search (search runs in the browser over the unlocked content),
  and for knowledge spaces export and import on the server (the browser does both).
- **Members.** A new member gets the key from an admin (a waiting list shows who is missing it). When a member leaves, the key
  changes and older content is encrypted again in the background as soon as an admin opens it with their encryption unlocked (for a
  key seen there for the first time, by a button); this protects new content, not what the person already saw.
- **Operation.** Nothing to do for the operator. The server stores ciphertext (`e2e1:...` in the usual columns) and wrapped keys
  and cannot repair a lost key. Do not hand out a database dump of such content as if it were readable.
- **Limits stay as documented in *Architecture*:** the server could swap ciphertexts inside a list or space (integrity) and the
  first public key a device sees for a person is trusted until the safety numbers are compared.

## Exporting encrypted content

Encrypted content is only readable inside Kalmido, after the person has unlocked their encryption in the browser. There is no
offline tool that opens it; the keys exist only in the members' browsers.

- **Knowledge space.** Unlock the encryption, open the space and use the menu entry to export it as a ZIP. The ZIP is built in
  the browser from the decrypted pages and contains plain Markdown files. This is the way to take a space with you.
- **Lists, list chat, list files.** Kalmido offers no decrypted export of these. The server's own exports hold ciphertext for
  them: *Settings > Account > Export > Download JSON* (the data of your own lists) and the backups. What you see in the unlocked app
  can be copied from there. Plan for it: if you need a plain copy of a list, switch its lock off first (the browser converts the
  content back, the list is then readable on the server again) and export it.
- **Account export, organisation export, backups.** They contain the ciphertext as stored (the organisation export lists it in the
  manifest under `client_encrypted`; the organisation recovery key and `tools/kalmido_export_decrypt.py` open the archive, not the
  browser ciphertext inside). The content stays readable only in Kalmido, with the passphrases of the members. A restored
  backup therefore works as long as the members still have their passphrase or recovery code.
- **What is lost without the key.** If a person loses passphrase **and** recovery code, they can set up their encryption anew,
  but cannot read what was only encrypted for them. In a list or an organisation's space another member can release the key to the new
  setup again. In a private knowledge space there is nobody else: the content is gone. If all members lose their keys, the content
  is gone and nobody (not the operator) can restore it.
- **Recovery code.** Print it or store it in a password manager when the app shows it; it is shown only once.
- **Moving to another server.** Copy the database and the data folder as usual (see *Moving to a new server*). Members keep their
  passphrase and recovery code; their wrapped keys are part of the database, so everything stays readable after the move.

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
  `files/store/`), the customer reports of those lists (2.81: `portal/tickets.json` with the reporter's name and
  address; never the status link, a new server would send new links) and the members with their roles (name, user
  name, e-mail address).
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
- **Import** (2.73, stage 1): see [Moving from and to app.kalmido.com](#moving-from-and-to-appkalmidocom) -- an admin of an
  organisation on the other server uploads the archive under *Settings > Data* and opens it with the recovery key.

## Moving from and to app.kalmido.com

Since 2.73 every person can take their own data from one Kalmido server to another -- from the hosted app.kalmido.com
to an own server, back, or between two own servers -- and keep the same file as their copy of their data (GDPR Art. 15
and 20). Agents and API tokens cannot do this; it is a person's step in the app.

1. **Export.** *Settings > Data > Move and export everything > Export everything.* The server builds one ZIP file in the
   background and keeps it for 24 hours (`exports/account/` in the data folder, not part of the backups, sealed with a
   key derived from `KALMIDO_SECRET_KEY` and readable only by the server, mode 0600); *Download* gives you the plain ZIP,
   *Delete now* removes it at once.
2. **Set up the other server** (this guide) and sign in there (or ask its admin for an account).
3. **Import.** *Settings > Data > Take over from a Kalmido export*: the file is uploaded in pieces (large exports work),
   checked (every checksum, format and version) and shown as a preview: the counts, the lists with their folders, the
   people of your lists and whether an account with the same e-mail address exists here. Choose the target -- your
   private space or an organisation you administer -- and start. Everything is created anew; one *Undo* (24 hours)
   removes everything the import created.
4. **People.** Your lists are shared with a person found by e-mail only when you tick them in the preview (an address on
   another server can belong to somebody else here). The file names other people only by a hash of their address, so
   the preview shows their name and the account found here, never an address. A server admin can also invite people that
   are missing (an account with an invitation link by e-mail): type their address in the preview -- it must match the
   hash in the file, otherwise nobody is invited; everybody else invites them later as usual. Assignments to people that
   are not taken over stay empty; comments of such people keep their name.

**What moves:** your lists (sections, fields, tags, status updates, links, milestones, project files), their tasks with
subtasks, dependencies, field values and your tags, comments, attachments, time entries, habits, filters, templates,
your own calendars with events, your own address books with contacts, the journal and a few plain settings (language,
work hours, display options, the folder order). Browser-encrypted content (locked notes, encrypted files) stays
encrypted and opens with your passwords as before.

**What does not move:** passwords, passkeys, two-factor settings, sessions, API tokens, webhooks, push subscriptions,
access data of connections (calendar and address book subscriptions, Karakeep, newsletter, Git, other Kalmido servers:
set them up again), lists of other people (the file names them and contains your own comments there), the trash, and
organisation data that is not yours (use the organisation export for a whole organisation).

**The file** (`kalmido-account-<date>.zip`, readable without Kalmido):

- `manifest.json`: `format` (`kalmido-account`), `v` (1), Kalmido version, `created_at`, `source` (`url`, `hosted`),
  `user` (id, name, e-mail), `tables` (rows per table), `files` (path, size, SHA-256 of every part), `client_encrypted`,
  `export_id` (an import of the same file twice is pointed out), `not_included`.
- `data/<table>.json`: one JSON array per table (the tables of *Download JSON*, plus `list_tags`, `task_list_tags`,
  `people` -- the members of your lists with name and `email_hash` --, `shared_lists` (the owner as
  `owner_email_hash`), `shared_comments`,
  `server_links` without their access keys). Webhooks appear only with name, events and `url_hint` (scheme and
  host; the address itself is the secret of many chat services), settings without the server-side ones (such as the
  ntfy topic an admin set).
- `files/attachments/`, `files/list_files/`: the files (decrypted).
- `checksum.sha256`: check the file with `sha256sum -c checksum.sha256` after unpacking.

Other people's addresses never leave the server in plain text: `email_hash` is the SHA-256 (hex) of
`kalmido-people|` followed by the address in lower case without spaces around it; the import compares it with the accounts
you may see on the new server. Your own address in `manifest.json` stays readable. Files of 2.73 test builds with a plain
`email` field are still read.

**A whole organisation** (2.73, stage 1): upload its organisation export (see above) the same way and enter the organisation's
recovery key of the old server. The archive is opened on the server (a wrong key is refused, ten attempts per upload),
checked and shown as a preview; it goes into an organisation you administer or (2.96) into your private space. Into the
private space nobody joins an organisation: ticked people only get the lists shared, the organisation's own address
books become your own ones. Lists with sections, fields, tags, status updates, links,
milestones and project files, tasks with subtasks, dependencies and field values, comments, attachments (sealed with the
new organisation's key), the organisation's calendars with events and its address books with contacts move along; the
lists belong to you as the importing admin. Members are matched by e-mail address: a ticked person joins the
organisation and gets their lists shared again. Not yet taken over (the preview names them with their counts): the
office, the file store, team chat, knowledge pages, documents, newsletter, clients, absences and bookings, forms,
playbooks, project notes and notepads, time entries, customer reports and browser-encrypted notes.

**Limits:** `KALMIDO_ACCOUNT_IMPORT_MAX_MB` (default 4096) caps the size of an import file; the data parts may hold at
most 32 MB of JSON per table and 96 MB together, and `KALMIDO_ACCOUNT_IMPORT_MAX_ROWS` (default 500000) rows per table
(also for an organisation export); the storage quota of the
person (hosting) is checked before the upload and for every file during the import -- when it is full, the import stops
and what came over so far can be undone. The import refuses ZIP files with unsafe names, duplicate parts, encryption,
extreme compression ratios or wrong checksums; ids, owners, organisations and authors in the file are never taken over
as they are. Values in a form the app never writes (a date like 2026-99-99, a time 25:99, an unknown priority, a colour
that is no #rrggbb, a repeat rule the app refuses) are left out, so the default applies.

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
- **Abuse limits (2.86).** Generous defaults that normal use never reaches; raise them in `.env` if a busy server needs
  more (a value that is not a whole number keeps the default):

  | Variable | Default | What it limits |
  |---|---|---|
  | `KALMIDO_FORM_FILES_MB_HOUR` | `200` | MB of files anonymous visitors may send through one public form per hour |
  | `KALMIDO_FILE_REQUEST_MB_DAY` | `1000` | MB clients may upload through one file request link a day (2.122.0) |
  | `KALMIDO_AGENT_PUSH_DAY` | `500` | pushes per agent and person a day (past it the message still arrives, without a push) |
  | `KALMIDO_OFFICE_MAILS_DAY_PERSON` | `150` | office document mails (invoices, quotations) one person sends a day |
  | `KALMIDO_OFFICE_MAILS_DAY_ORG` | `300` | office document mails of one organisation a day |
  | `KALMIDO_OFFICE_MAILS_DAY_ADDRESS` | `20` | office document mails one receiving address gets from an organisation a day |

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

## Errors in the browser (2.102)

An unexpected error in the web app (an unhandled script error or a rejected promise) can become a bug ticket, so it
does not vanish in a browser console nobody opens. Off until an admin picks a list: *Settings > Administration > Server >
Errors in the browser > Report to* offers the project lists the admin manages that have **error reports** switched on
(list dialog > Repository > Error reports). Switching error reports off in that list, or choosing *Off*, stops it at once;
the browsers then send nothing.

- **What is sent:** the error message, the place in the code (`/static/js/file.js:line:column`), a short stack of such
  places (at most 2 KB), the client's and the server's version, the name of the open area (`tasks`, `office`, ...) and
  whether it was an error or a rejected promise. The server cuts the message once more: quoted texts that are no plain
  names, e-mail addresses, links and long numbers or ids become placeholders. No task texts, form values, user names or
  addresses with ids; the ticket is created by nobody.
- **Who may send:** people signed in (no agents, no public pages), at most 5 reports per person and minute and 60 per
  hour, at most 20 per page load, the same error once per page load. The list's own limits apply as for every error
  report: the same error again only counts up at its open ticket, at most 30 new tickets per hour.
- **Reports from every workspace** of the server go into this one list, without any person's name. Pick a list only the
  people who look after the server see.

- **Give *Tasks by e-mail* its own mailbox.** Kalmido marks every mail it reads as read and imports it as a task; a
  mailbox you also use yourself gets mixed up.
- **Shorten forwarded mails (optional, per person).** Settings > Integrations > *Tasks by e-mail* > *Shorten forwarded mails*: the
  forwarding header becomes one line, signatures, legal notices and older quoted replies are cut, the original mail stays
  attached as `.eml`. Off by default.
- **Deliver directly, do not forward.** Many forwarding rules drop the plus part of an address (`tasks+token@…`), and
  then Kalmido cannot tell whose task it is.
- **E-mails at clients and projects (2.84):** the same mailbox also takes the addresses of clients, projects and the
  personal e-mail inboxes (docs/OFFICE.md); nothing else to set up. The mails go into the database (table `hub_mails`), their
  `.eml` and attachments into the file store, so they count against the storage limit and go through the virus scan.
- **Sender domain:** for the daily summary over SMTP, set up SPF, DKIM and DMARC for the sender domain, or the mails land
  in spam.
- **Forgot your password? (2.49):** the login page shows the link only when outgoing mail (SMTP) is set up. A person
  enters their e-mail address or user name and gets the same one-time link an admin can send (*Settings > Users >
  Send a link to set a new password*): valid for 7 days, used once, only its hash is stored, built from `PUBLIC_URL`
  (never from the request's host). The page answers the same whether the account exists or not, at most one link per
  account in five minutes, rate limited per address and sender. Kid accounts, agents, disabled accounts and accounts
  without a password (single sign-on only) get no link: their parents or an admin reset them. Two-factor sign-in stays
  required: after the new password the second step follows, and all other sessions of the account end. App passwords
  (CalDAV) and API tokens stay valid; the page for the new password says so and points to *Settings > Account* (2.58).

## Virus scan of uploads

Since 2.61.0 every uploaded file (task and comment files, project files, the file store and documents, chat files, files from
mail and the share sheet) goes to [ClamAV](https://www.clamav.net/) before it is stored. The `docker-compose.yml` brings the
service `clamav` along; Kalmido talks to its daemon over the internal network (`KALMIDO_CLAMD=clamav:3310`, no port is
published). ClamAV needs **about 1 to 1.5 GB of RAM**; `freshclam` inside the container keeps the signatures up to date
(volume `clamav-db`). After a start it needs a few minutes to load them (`docker compose ps` shows *healthy* when it is ready).

- **A find**: the upload is refused with the name of the signature ("file.pdf: malware found (...), not uploaded").
- **Scanner not reachable** (still loading, stopped, crashed) or a file larger than `KALMIDO_CLAMD_MAX_MB`: the upload is
  taken and marked *Unchecked* in the app. 2.79.0: with the scanner configured, an unchecked file is **held back** (403 "not
  checked for malware yet") until the later scan finds it clean - downloads, previews, public links and agents alike
  (`KALMIDO_CLAMD_STRICT=0` gives the old behaviour: unchecked files stay readable with their mark). A file too large for the
  scanner is never scanned and stays readable with its mark, so keep the upload limit at or below `KALMIDO_CLAMD_MAX_MB`
  (raise it together with clamd's `StreamMaxLength` if you allow large uploads).
  Once the scanner answers again, the server checks these files in the background
  (up to 20 per minute). Clean: the mark goes. A find: the file is **locked** - it stays stored, but nobody can download or
  preview it any more (403), and the person who uploaded it gets a News item. Deleting it is up to the people of the list.
  *Settings > Users > Whole server* shows the scanner's state and how many files wait or are locked.
- Files encrypted in the browser (end-to-end) cannot be read by the server and are not scanned.
- Independent of the scanner, the server looks at the first bytes of every upload: a program or HTML page that claims to be a
  picture or PDF is stored as a plain download (never shown inline).

| Variable | Default | Meaning |
|---|---|---|
| `KALMIDO_CLAMD` | `clamav:3310` in the compose file, else empty | `host:port` of clamd (TCP) or the path of its unix socket; empty = no scan |
| `KALMIDO_CLAMD_MAX_MB` | `100` | larger files are not sent to the scanner (marked *Unchecked*); keep it at or below clamd's `StreamMaxLength` |
| `KALMIDO_CLAMD_TIMEOUT` | `60` | seconds one scan may take |
| `KALMIDO_CLAMD_STRICT` | on when `KALMIDO_CLAMD` is set | 2.79.0: `1` = unchecked files are held back until the later scan (not those too large for the scanner), `0` = they stay readable (as up to 2.78) |

**Switch it off** on a small server (e.g. a Raspberry Pi with 1 GB): set `KALMIDO_CLAMD=` (empty) in `.env` and delete the
`clamav:` block (and the `clamav-db` volume entry) from `docker-compose.yml`, then `docker compose up -d --remove-orphans`.
Uploads are then taken without a scan and without a mark. An own ClamAV elsewhere: `KALMIDO_CLAMD=host:3310`.

**Photos turned by the camera** are turned upright and saved again when their metadata are removed (see TEAM.md). The
re-encode holds the whole picture in memory, so it is done only up to `KALMIDO_PHOTO_MAX_PIXELS` pixels (2.81; default
`40000000`, at least `1000000`); larger photos keep a small orientation mark instead. Lower it on a host with little memory.

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
| `KALMIDO_DOCS_THUMB_FILL` | `on` | 2.66.1: `off` skips the one-time catch-up of missing previews of imported documents |
| `KALMIDO_DOCS_THUMB_FILL_S` | `15` | Seconds between two portions (5 documents) of that catch-up |
| `KALMIDO_FILE_OCR` | `on` | 2.61.0: `off` switches the text recognition of normal files off (below) |
| `KALMIDO_FILE_OCR_BACKFILL` | `on` | 2.61.0: `off` switches only the catch-up of files stored before off |
| `KALMIDO_FILE_OCR_BACKFILL_S` | `20` | Seconds between two files of the catch-up |
| `KALMIDO_FILE_OCR_MAX_MB` | `50` | Larger files are not read |

2.61.0: the same tools also read the text of normal files in the background -- task and comment files, project files and
files in the file store (PDF, JPEG, PNG; HEIC cannot be read by them and gets no mark). The upload never waits for it;
documents go first, and the same file content in a workspace is read only once. The text makes the file findable: a task
by the text of its files (task search, "Found in the file ..."), a file by its text in the file store's search -- only
for people who can open the file anyway. The file shows *Text recognised* or *No text found*. Files stored before 2.61.0
are caught up slowly (one file every 20 seconds, only while nothing else waits, newest first; the position survives a
restart). Browser-encrypted files and chat files are never read. The text is sealed like the documents' text below.

The recognised text, amounts, sender names, rules and the learnt models are sealed with the workspace's key when
`KALMIDO_SECRET_KEY` is set (see [Encryption of organisation data](#encryption-of-organisation-data)); the search uses
keyed hashes of the words, no plain index. Without `KALMIDO_SECRET_KEY` the hash key of the word index is a fixed one
(the same on every server): whoever reads the database can then test words against it -- set the server key. With *Tasks by e-mail* set up, every person and organisation can create a
forwarding address for documents in the documents' settings: PDFs and images attached to mails sent there become
documents.

### Import from Paperless-ngx (2.48)

An existing Paperless-ngx instance can be connected (2.69: also on a hosted server, see below)
once per workspace -- by an organisation's admin for the organisation, by a person for their own space -- under
*Settings > Integrations > Paperless-ngx* (2.87.9; before: *Documents > Settings*) with its address and an API token
(Paperless-ngx: *My profile > API auth token*). The section names the workspace and switches between them; the documents
settings keep only the progress of a running import and a jump there. The search (Ctrl/Cmd+K) finds *Import from
Paperless-ngx…* and *Connect Paperless-ngx*.

- **Read only:** Kalmido only sends GET requests. Nothing in Paperless-ngx is changed, moved or deleted.
- **Preview first:** the number of documents and how tags, correspondents and document types are taken over: a tag
  becomes a tag, a folder of the documents or is left out; correspondents become senders, document types types (names can be
  changed in the preview).
- **What comes along:** the original file, the recognised text (no new recognition), the date, tags, correspondent, type,
  and custom fields, notes and the archive serial number as text below the document's text.
- **Preview images (2.66.1):** imported PDFs and images get their preview image and the QR-code archive number check like an
  upload (also from a ZIP). Documents imported before get their missing previews once after the update, in small portions in
  the background while the documents queue is idle; nothing else of them changes. `KALMIDO_DOCS_THUMB_FILL=off` skips it.
  The catch-up runs once (row `docs_thumb_fill` of the table `settings`); delete that row to run it again, e.g. after installing
  the PDF tools later.
- **Never twice:** a document already imported (Paperless-ngx id per instance address) or the same file already in the
  workspace (checksum) is left out, also when the import runs again.
- **Rules and learning (2.69):** the matching of tags, correspondents and document types becomes document rules of the
  workspace (*any*, *all*, *literal* -> *exact*, *regex*, *fuzzy*, case-sensitive kept), aimed at the names chosen in the
  preview; a switch in the preview turns this off. *Auto* has no rule counterpart: Kalmido's own learning covers it. Patterns
  Kalmido does not accept (too long, too complex for its safe regex check) are listed in the preview and the result. A rule
  is taken over once: a later import does not double it, nor bring it back after it was changed or deleted in Kalmido. At
  the end of every import the imported senders, types, tags and folders train the classifier once, as confirmed examples.
- **Where it goes (2.87.9):** before the start Kalmido says in words where the documents go ("182 documents into the
  organisation …" / "into your private space") and asks once more. With an organisation as the target, *Rather into
  private* imports from the organisation's connection or export into the starter's own private space instead (an admin's
  own space only, never someone else's). Every other importer (tasks, contacts, calendar files, budget, office, knowledge
  pages, an account move, feeds) asks the same way.
- **In the background:** progress, the target and *Stop* in the settings; the import runs on on the server (the window can be
  closed), only the upload of an export ZIP needs the window open; optionally *Bring in new documents automatically* every
  15 minutes up to once a day (only Paperless-ngx -> Kalmido).
- **Network:** http/https only, timeouts, no redirects, at most `TASKS_MAX_FILE_MB` per file. An instance in the local
  network is an internal address: allow its host under *Settings > Administration > Advanced* (or
  `KALMIDO_CALENDAR_ALLOW_HOSTS=paperless.example.com:8000`), the same allow-list as for calendar subscriptions.
- The token is always stored sealed with a key derived from `KALMIDO_SECRET_KEY` (also when the encryption of
  organisation data is off) and never shown again. Without a server key the connection cannot be set up.
- **Hosted servers (2.69, `KALMIDO_HOSTED=1`):** only public HTTPS addresses; the list of allowed internal hosts does not
  apply there (http://, loopback, private, link-local and similar addresses are refused, also after a DNS lookup).
- **Storage quota (2.69):** the preview shows how much storage the documents need (over the address an estimate from a
  sample of up to 10 documents, from a ZIP the exact size) and how much is free. A full storage refuses the start; when it
  fills up during the run, the import stops after the last document that fitted and says how far it came.
- **One import at a time (2.69):** a server runs one Paperless-ngx import at a time (over all processes); further ones wait
  in a queue and the settings show their place. A run that was cut off (restart) goes back to the queue after 10 minutes.

#### From an export ZIP (2.69)

For a Paperless-ngx that Kalmido cannot reach (a VPN, a Tailnet, a login in front of it) the documents can come from an
export instead -- on hosted and self-hosted servers, without a connection or token. Create the export on the Paperless-ngx
server (in its Docker setup with `docker compose exec webserver ...`):

```bash
document_exporter ../export --zip
```

Then upload the ZIP under *Settings > Integrations > Paperless-ngx > From a Paperless-ngx export (ZIP)*. The same preview
follows (tags, correspondents, document types with their mapping), then the import in the background. Exports with
`--split-manifest`, `--use-folder-prefix` and ZIPs with everything in one top folder work as well.

- The upload goes in parts of 8 MB (an interrupted upload continues when the same file is chosen again), at most
  `KALMIDO_PAPERLESS_ZIP_MAX_MB` (default 4096) per ZIP. It belongs to the workspace and the person who uploaded it.
- The parts are stored sealed (the workspace's key) in `KALMIDO_PAPERLESS_ZIP_DIR` (default `paperless-zip` next to the
  database file in the data folder), not in the backups, and are deleted right after the run (done, stopped, failed) or
  when the upload is discarded; uploads without a run are removed after 24 hours.
- The ZIP is never unpacked onto the disk: only the manifest and the files it names are read. Encrypted ZIPs, more than
  300 000 entries (2.81; before 500 000), a manifest above 64 MB, a file above `TASKS_MAX_FILE_MB` and files that unpack to
  far more than their size (zip bombs) are refused.
- The check of the uploaded ZIP runs in the background (2.81): after the last part the settings show *Checking the
  export…* until it is ready (then the preview opens) or refused with the reason.
- Never twice: a document of an earlier ZIP import with the same id and the same file, or the same file already in the
  workspace, is left out.

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

### Office: pack catalogue (2.76)

Country and industry packs beyond the shipped ones come from a catalogue the operator chooses (details, index format and
the security model: [PACKS.md](PACKS.md)). Without a catalogue Kalmido makes no network request for packs.

- `KALMIDO_PACKS_CATALOG=https://example.com/kalmido-packs/index.json` - the index file; empty (default) = only the
  shipped packs.
- `KALMIDO_BOOKMARK_ALLOW_HOSTS=wiki.example.com:8080` (2.97.0) - internal hosts the bookmark preview may fetch (empty =
  public addresses only; the calendar allow-list does not apply to bookmarks).
- `KALMIDO_PACKS_ALLOW_HOSTS=mirror.example.com:8080` - hosts that may be internal addresses and may use `http://` (an
  own mirror); every other host: `https://` and a public address only.
- Installations are stored per office area in the database (table `office_pack_installs`) and travel with backups;
  finalised documents keep their own copy of the pack.

### Built-in assistant (2.75)

Kalmido calls no language model itself -- except the built-in assistant, and only when you configure it. It talks to any
OpenAI-compatible chat-completions endpoint (`POST <base>/chat/completions`): a local model (Ollama, vLLM, LocalAI) or a
provider of your choice. Nothing is wired in; without the two variables below the assistant does not exist (no menu, no
routes, nothing in `/api/state`). Each person switches it on for themselves (*Settings > Assistant*) and shares single lists
with it; only those lists, basket items they pick and texts they type are sent, as a summary, a draft or a proposal they
apply or discard (nothing is changed directly). Locked notes, health lists, attachments, files and office documents are never
sent. Every call leaves a log row with numbers only (no texts), kept `KALMIDO_AUDIT_DAYS` days; admins see the daily counts.

| Variable | Default | Purpose |
|---|---|---|
| `KALMIDO_AI_BASE_URL` | (empty = off) | Base address of the endpoint, e.g. `http://ollama:11434/v1` |
| `KALMIDO_AI_MODEL` | (empty = off) | Model name sent with every call |
| `KALMIDO_AI_KEY_FILE` | | File holding the API key (one line); read once at start |
| `KALMIDO_AI_KEY` | | The key directly (instead of the file); empty for a local model without a key |
| `KALMIDO_AI_NAME` | host of the base address | Provider name shown to people ("texts are sent to ...") |
| `KALMIDO_AI_TIMEOUT_S` | `60` | Time limit per call (seconds) |
| `KALMIDO_AI_MAX_CHARS` | `24000` | Input characters per call; longer input is cut and the person is told |
| `KALMIDO_AI_MAX_TOKENS` | `1500` | Answer tokens per call |

The key is sent only as `Authorization: Bearer ...` to that address and never appears in logs, error texts, API answers or
exports. The address is yours (an environment variable), so addresses in the local or Docker network are allowed; only
http(s), no redirects to other hosts, one attempt per call, no streaming.

Local model with Ollama in the same compose file (no key, nothing leaves your network):

```yaml
  kalmido:
    environment:
      KALMIDO_AI_BASE_URL: http://ollama:11434/v1
      KALMIDO_AI_MODEL: llama3.1
      KALMIDO_AI_NAME: Ollama (this server)
  ollama:
    image: ollama/ollama
    volumes: ["ollama:/root/.ollama"]
```

An OpenAI-compatible provider in the EU (check its data processing terms and sign a processing agreement first; the
people's texts go there):

```yaml
  kalmido:
    environment:
      KALMIDO_AI_BASE_URL: https://inference.provider.example/v1
      KALMIDO_AI_MODEL: provider-model-name
      KALMIDO_AI_KEY_FILE: /secret/ai.key
      KALMIDO_AI_NAME: Example AI (EU)
    volumes: ["./secret:/secret:ro"]
```

## Related tasks: the embedding service (2.59)

Optional. With it Kalmido shows *Related tasks* in a task, a hint on likely duplicates while you type a new task, and *also
similar meaning* in the search; agents get the related tasks in their events and the tool `related_tasks`. A small
multilingual embedding model (multilingual-e5-small, MIT) runs in its own container on your CPU and turns the text of each
task (folder, list, parent, title, description) into numbers. It writes no text, keeps no data and has no way out to the
internet: the model is part of its image, the container sits only on an internal network that Kalmido reaches. Kalmido
itself never calls a language model or an outside service for this.

1. Build and start it: `docker compose --profile embed up -d --build` (downloads the model once while building, about
   120 MB; the container needs about 0.6 GB RAM, one CPU thread).
2. Set `KALMIDO_EMBED_URL=http://embed:8090` in `.env` and restart Kalmido (`docker compose up -d`).
3. *Settings > Administration > Server > Related tasks* shows whether the service answers, the model and how many tasks
   are computed. The first start computes every task in the background, throttled (a few minutes per thousand tasks on a
   small 4-core server); then only new or changed tasks.

Without the service (or with the switch off) everything works as before and the new parts are hidden. The vectors are
stored in the table `task_vectors`: per organisation like its tasks (row-level security), sealed with the organisation's
key when its data is encrypted, deleted with the task; they are not part of the organisation export (Kalmido computes them
again). Thresholds for another model: `KALMIDO_RELATED_MIN`, `KALMIDO_RELATED_DUP`, `KALMIDO_RELATED_SEARCH`,
`KALMIDO_RELATED_MIX`, `KALMIDO_RELATED_NORM` (see `.env.example`). A Raspberry Pi works too, only slower; leave the service out if the box is busy.

## Several servers in one app (2.73)

A person with accounts on more than one Kalmido server (for example a company server and a private one) can see them
together in one app: *Settings > Account > Servers*. The data stays on each server; nothing is copied or synchronised,
and no server needs to trust another one.

- **How it works.** The server the app runs on (the "home" server) talks to the other server's `/api/v1` on the person's
  behalf, with a personal API token of the person's account there. The browser only ever talks to its own server: no
  CORS, no change of the Content Security Policy, no token in the browser. The token is stored sealed with a key derived
  from `KALMIDO_SECRET_KEY` (without a server key the feature refuses to store one) and never leaves the server: not in
  answers, logs or the account export. Nothing of the other server is stored either; answers are held in memory for at
  most 15 seconds, at most 4 requests per person and 6 on the whole server run at once (a further one answers "busy"
  at once instead of waiting), at most 120 reads per person and minute, each request with 3 seconds to connect, an
  8-second limit and at most 8 MB.
- **Connecting.** On the other server: *Settings > Account > Servers > Create a connection code for another server*. That
  creates a personal API token with exactly the scopes `read`, `tasks:write`, `delete`, `calendar` and `comments` and
  packs it with the server's `PUBLIC_URL` into a code that is shown once. Paste it on the home server. Instead of a code,
  the address and a token made by hand work too (any Kalmido server with the REST API, the code button needs 2.73).
  The token stays visible under *API tokens* on the other server and can be revoked there at any time. A removed account
  can be restored for 30 days; then its stored token is wiped and the account has to be connected anew.
- **Network.** Every request goes through the same guard as calendar subscriptions: public addresses only, no
  redirects, every resolved address is checked (no DNS rebinding). A **self-hosted** server reaches internal servers only
  when they are on the allow-list of internal hosts (*Settings > Administration > Advanced*, or
  `KALMIDO_CALENDAR_ALLOW_HOSTS`), and uses `http://` only for those: the token never crosses the internet unencrypted. A **hosted** server (`KALMIDO_HOSTED=1`) connects to `https://` addresses only and
  never to an internal one.
- **Agents** see nothing of it: there is no `/api/v1` route, no MCP tool and no event for it; an agent only ever works on
  its own server.

### Several servers in one app: the merged view (2.73.0)

Once an account on another Kalmido server is linked (Settings > Account > Servers), the app shows it next to your own data.
Nothing is copied or synced: every task stays on its server, and the app asks that server whenever it shows or changes one.

- **Badges:** every task, list and detail panel of another server carries that server's short name in its colour. In the merged
  views (Today, Basket, Search, Calendar) your own tasks get your own badge too; in a normal list view there is none.
- **Sidebar:** one group per server below your lists, with its lists. A list opens with its open tasks; you can tick them off and
  add new ones there.
- **Today and Basket:** the other servers' tasks join by the same rules (due today or overdue on that server's date; its basket).
  The numbers in the sidebar count them.
- **Details:** a tap on a task of another server opens a small panel: title, notes, date, priority, its subtasks, complete or
  reopen, move it to the trash there, "Open on …" (the full task on its server; comments and attachments are only counted here).
- **Quick add:** with a server linked, the composer shows where the task goes ("→ Work · Projects"); tap it to pick another
  server and list. Date and priority words work; the rest stays in the title.
- **Search, News, Calendar:** hits, unread news and the month's events and due tasks of each server appear in their own section
  with the badge; a slow or offline server never holds up your own results.
- **Move to another server:** from the task menu (own tasks) or the panel (tasks of another server). The task is created anew on
  the target (title, notes, date, priority, open subtasks); comments, attachments and history stay in the trash of the source,
  where it can still be restored. The app says this before it moves anything, and for a task of an organisation's list also
  that it leaves the organisation. Should the other server refuse a subtask once the copy exists, the move still completes
  and the app names how many subtasks are missing.
- A server that does not answer shows one quiet line ("Work not reachable – last update 10:42") instead of error messages; a
  change on it is never queued offline, it is either done or reported.
- Agents only ever see the server they are connected to.

## Capacity, health and a worker process (2.102)

One container serves the web app **and** runs the background work (reminders and pushes, calendar and contact sync,
backups, webhooks, mail in, repositories, text recognition, the Paperless import). That stays the default. For bigger
instances the numbers can be set and the work can be split:

| Variable | Default | Meaning |
|---|---|---|
| `KALMIDO_THREADS` | `16` | request threads of the web server |
| `KALMIDO_DB_POOL_MAX` | threads x 3 + 8 (= 56) | database connections per container (`KALMIDO_POOL_MAX` works too) |
| `KALMIDO_REPLICAS` | `1` | how many Kalmido containers share the database: only for the start-up check of `max_connections` |
| `KALMIDO_ROLE` | `all` | `all` = web + background work, `web` = requests only, `worker` = background work only |
| `KALMIDO_LOOP_LOCKS` | `1` | `0` = every container runs its background loops (the behaviour before 2.102; only for diagnosis) |

- **Start-up check.** When `KALMIDO_REPLICAS` x (pool + 6) is above `max_connections` minus a reserve, the log says
  `WARNING database connections: ...` with the numbers. Raise `max_connections` of the database or lower the pool.
- **Loop locks need a direct database connection.** They are session-level advisory locks: behind a connection pooler in
  transaction mode (for example pgbouncer `pool_mode = transaction`) they do not hold; point Kalmido at Postgres directly.
- **A request that waits 30 s for a connection** is no longer silent: the log shows `WARNING database pool exhausted`
  with the pool's counters (at most once a minute).
- **Health numbers.** `GET /api/admin/health` (signed in as an admin of the server) answers with the version, the role,
  the threads (configured, busy now, the peak, requests served), the pool (size, available, waiting, timeouts), the
  connection budget and the state of every background loop (`running` here, `waiting` = another container runs it).
  With a worker it also shows the worker's last heartbeat. It holds numbers only, no user data.
- **Each background loop runs once per instance.** Every loop takes a lock of its own in the database before its rounds
  (also in the role `all`). Two containers on one database therefore never send a reminder twice, deliver a webhook
  twice or write two backups; the second one waits and takes over when the first one stops.

### Example: a web container and a worker

Split the work only when the web container is busy with imports or text recognition. Both containers use the same image,
the same `.env`, the same database and the same `./data` and `./secret` folders (backups, attachments and the server key
live there). Only the web container gets the port and the reverse proxy:

```yaml
services:
  kalmido:                       # the web part (as before, plus the role)
    # ... everything as in docker-compose.yml ...
    environment:
      KALMIDO_ROLE: web
      KALMIDO_REPLICAS: "2"
  kalmido-worker:
    image: ${KALMIDO_IMAGE:-kalmido:local}
    container_name: kalmido-worker
    command: ["python", "app.py", "worker"]
    restart: unless-stopped
    user: "1000:1000"
    security_opt: [no-new-privileges:true]
    cap_drop: [ALL]
    env_file: .env
    environment:
      DATABASE_URL: ${DATABASE_URL:-postgresql://kalmido:${POSTGRES_PASSWORD}@db:5432/kalmido}
      KALMIDO_SECRET_FILE: ${KALMIDO_SECRET_FILE:-/secret/kalmido.key}
      KALMIDO_CLAMD: ${KALMIDO_CLAMD-clamav:3310}
      KALMIDO_REPLICAS: "2"
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - ./data:/data
      - ./secret:/secret
    networks: [default, embed]
    # no ports, no healthcheck on /api/health (no web server); the web's GET /api/admin/health shows its heartbeat
```

Notes:

- The worker has no web server. Work that a request starts (the queues for text recognition, documents, Paperless and
  related tasks) is stored in the database; the worker picks it up on its next round (seconds to a minute later).
- A few short jobs still run in the web container: mails sent right after an action, exports and imports started by
  a person, the manual *Back up now*.
- Back to one container: remove `kalmido-worker` and `KALMIDO_ROLE`; nothing else changes.

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
