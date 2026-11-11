# Upgrading Kalmido

What an update needs from you, version by version, and how far back you can go. The steps of an update itself are in the
[README](../README.md) and in [Production updates](SELF-HOSTING.md#production-updates); the way back step by step in
[Back to the previous version](SELF-HOSTING.md#back-to-the-previous-version).

## Rule for every release

A release that needs a step from you lists it here, in the same release, whatever its version number says: **a version
number alone does not tell you whether a step is needed**, 2.37, 2.45 and 2.149 needed one and were minor versions.
Read this list before an update; nothing listed between your version and the new one means nothing to do.

A big jump (say 2.30 to 2.400) is allowed: every migration runs in order on the first start. Do the steps of **every**
version you pass, and make a backup first. There is no need to stop at each version in between.

## Versions that need a step

| Version | What to do | Details |
|---|---|---|
| 2.37 | PostgreSQL is required: add the database service, set `POSTGRES_PASSWORD` and `DATABASE_URL`. The installer does it. | [Upgrade to 2.37](SELF-HOSTING.md#upgrade-to-237-postgresql-required) |
| 2.45 | The server key moves into a file on its own folder: `mkdir secret && chown 1000 secret` next to `data`, then restart. The installer does it. | [The server key](SELF-HOSTING.md#first-setup-and-the-server-key) |
| 2.46 | One kind of server: the instance mode is gone; its variable is only read for the row-level security check (see ENV.md). | CHANGELOG 2.46.0 |
| 2.79 | Reverse proxy on the host in front of a published Docker port: `KALMIDO_TRUSTED_PROXIES` now defaults to loopback only, the Docker bridge gateway no longer counts: add it (`KALMIDO_TRUSTED_PROXIES=127.0.0.1,::1,172.17.0.1`). With a virus scanner an upload it could not check is held back (`KALMIDO_CLAMD_STRICT=0`: as before). | CHANGELOG 2.79.0 |
| 2.149 | `.env` needs a `COMPOSE_PROFILES` line (for example `COMPOSE_PROFILES=localdb,clamav`) and Docker Compose 2.20 or newer. The installer adds the line. | [Update, downgrade and restore](SELF-HOSTING.md#update-downgrade-and-restore) |
| 2.182 | The container runs read-only as user 1000. An installation that ran it as root: `sudo chown -R 1000:1000 data secret` once, or keep your own `user:` line. An own compose file needs a writable `/tmp`. | [First setup](SELF-HOSTING.md#first-setup-and-the-server-key) |
| 2.239 | The server log shortens IP addresses and names accounts by number: fail2ban and the like need `KALMIDO_LOG_FULL_IP=1`. | CHANGELOG 2.239.0 |
| 2.240 | The mail server is reached with a checked certificate: an own certificate or an IP address as host needs `KALMIDO_SMTP_INSECURE=1`, otherwise no mail goes out. Mails taken in from the instance mailbox are deleted there (`KALMIDO_IMAP_KEEP=1`: only marked read). An embedding service on another host needs `KALMIDO_EMBED_EXTERNAL=1`. | CHANGELOG 2.240.0 |
| 2.499 | On the channel *Web Push* nothing goes to the public `ntfy.sh` any more. If you had subscribed to your random topic there as a backup, for example for reminders, switch to the channel *ntfy* under *Settings > Notifications*. An own ntfy server changes nothing. | [Installed app and push](SELF-HOSTING.md#installed-app-pwa-and-push) |

## Format limits: going back

Going forward never needs one of these. Going **back** below a limit does: from that version on data has a form older
versions cannot read, so run the step on the newer version first.

| Back to | Run first (`docker compose exec -T kalmido python -m kalmido.admin.orgcrypt_cli …`) |
|---|---|
| below 2.42 | `decrypt-all` |
| below 2.64 | `decrypt-private` |
| 2.122 or older | `decrypt-wiki` (only after `encrypt-wiki`) |
| 2.125 or older | `docs-to-server-key` |

**Never go back below 2.149.** Those versions have no start check: on a newer database they start without a word (only a
note about row security) and do not know what came later, such as the closed periods of the office. Every database keeps
this limit (`back_floor` in the table `kalmido_meta`), and every version from 2.359.3 on refuses to start below the limit
of its database and names the step (emergency only: `KALMIDO_ALLOW_DOWNGRADE=1`). A later limit is added to this list and
to `BACK_LIMITS` in `kalmido/core/db.py` in the same release.

**Shared core, stage 7 (team chat, calendars, address books):** the first start of the version with this step copies the old
member rows into the shared core and then deletes the old member tables. From then on the database refuses every older
version (its limit is the version that deleted them, it names the reason): an older version would create the tables empty
again and take every member's access. The way back is a newer version or a backup from before the update.

**Never go back before the release with package 2.972** (the CHANGELOG names it): its first start moves the comments of tasks
into one shared table (`obj_comments`) and the watchers and bells of tasks into `obj_follow`, drops the old tables and raises
the database's limit to the minor of that release (like stage 7 above). An older version would make the old tables again empty
and write there what the next start of the newer version could not take over. Go back only by restoring a backup made before
the update.

**Never go back before the release with package 2.981** (the CHANGELOG names it): its first start moves the bells of projects
into `obj_follow` and the owners' notification templates of projects and folders into `obj_notif_cap`, drops `list_bell`,
`list_notif` and `folder_notif`, builds one shared search index (`obj_search`) for tasks, comments, notes, contacts, the names of
knowledge pages and messages, drops the old search tables (`task_fts`, `cmt_fts`), the trigram indexes and the column
`contacts.search`, and raises the database's limit to the minor of that release. An older version would make the old tables
again empty (no project bells, every share back on the default template "Read-only") and write contacts into the dropped column.
Go back only by restoring a backup made before the update. The first start reads every text once to build the search index (a
large instance: a few minutes).

The same release's first start also moves the comments of video / picture reviews and
the notes on documents into the same shared table (`obj_comments`), drops the old tables and raises the database's limit to the
minor of that release. An older version would make them again empty. Go back only by restoring a backup made before the update.
