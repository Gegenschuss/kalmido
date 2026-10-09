# Self-hosting: lessons from running Kalmido

Practical notes for running Kalmido on your own server: what tends to go wrong behind a reverse proxy, with installed
apps and push, with backups, mail and moving to another machine, and how to harden the host. The README has the basics
([Quick start](../README.md#quick-start), [Reverse proxy](../README.md#reverse-proxy),
[Configuration](../README.md#configuration), [Backups and restore](../README.md#backups-and-restore),
[Updating](../README.md#updating)); this page collects what comes on top. Everything here is generic: adjust names,
addresses and paths to your setup.

## Contents

- [Reverse proxy and network](#reverse-proxy-and-network)
- [Installed app (PWA) and push](#installed-app-pwa-and-push)
- [Backup and encryption](#backup-and-encryption)
- [Server hardening](#server-hardening)
- [Mail](#mail)
- [Moving to a new server](#moving-to-a-new-server)
- [Production updates](#production-updates)

## Reverse proxy and network

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

## Backup and encryption

- **Fail closed when the data disk is missing.** Keep the data folder on its own disk or volume and mount it so that
  Docker refuses to start without it, instead of creating an empty folder (an empty start shows the setup page, and
  whoever comes first becomes admin):

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

## Mail

- **Give *Tasks by e-mail* its own mailbox.** Kalmido marks every mail it reads as read and imports it as a task; a
  mailbox you also use yourself gets mixed up.
- **Deliver directly, do not forward.** Many forwarding rules drop the plus part of an address (`tasks+token@…`), and
  then Kalmido cannot tell whose task it is.
- **Sender domain:** for the daily summary over SMTP, set up SPF, DKIM and DMARC for the sender domain, or the mails land
  in spam.

## Moving to a new server

1. **Before:** lower the DNS TTL of the name a day ahead; make a backup (*Back up now*).
2. **Copy:** the data folder (database, attachments, backups), the `.env` and above all **`KALMIDO_SECRET_KEY`**:
   without it, stored secrets (repository and Paperless tokens, sign-on client secret) cannot be decrypted and must be
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
