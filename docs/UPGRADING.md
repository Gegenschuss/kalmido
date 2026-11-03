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
| 2.149 | `.env` needs a `COMPOSE_PROFILES` line (for example `COMPOSE_PROFILES=localdb,clamav`) and Docker Compose 2.20 or newer. The installer adds the line. | [Update, downgrade and restore](SELF-HOSTING.md#update-downgrade-and-restore) |
| 2.499 | On the channel *Web Push* nothing goes to the public `ntfy.sh` any more. If you had subscribed to your random topic there as a backup, switch to the channel *ntfy* under *Settings > Notifications*. An own ntfy server changes nothing. | [Installed app and push](SELF-HOSTING.md#installed-app-pwa-and-push) |

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
