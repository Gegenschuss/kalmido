# Reverse proxy templates

Plain templates for putting Kalmido behind HTTPS with the **built-in login** (no single sign-on). Replace
`kalmido.example.com` with your address and set the same address as `PUBLIC_URL` in `.env`.

| File | Proxy |
|---|---|
| [Caddyfile](Caddyfile) | Caddy 2 (certificates from Let's Encrypt automatically) |
| [nginx.conf](nginx.conf) | nginx (certificates e.g. with certbot) |
| [traefik.docker-compose.override.yml](traefik.docker-compose.override.yml) | Traefik 2 / 3 via Docker labels |

What every proxy needs:

- **WebSockets: not needed.** Kalmido uses plain HTTP requests only. Agents and open apps wait for news with long
  requests of up to 60 seconds (long polling), so the proxy's read timeout must be longer (the templates use 120 s).
  Proxies that upgrade WebSocket connections anyway do no harm.
- **Forwarded headers:** `X-Forwarded-For`, `X-Forwarded-Proto` and `X-Forwarded-Host`. Kalmido only believes them from
  the addresses in `KALMIDO_TRUSTED_PROXIES` (default: only localhost, which fits none of these templates). Until the right
  address is in there the app seems to run normally, but the session cookie has no `Secure` flag behind HTTPS, there is no
  HSTS, and every client seems to have the same address, so failed logins slow down everyone. See the table below.
- **Upload size:** one request may carry files up to 4 x `TASKS_MAX_FILE_MB` (default 50 MB, so 200 MB).
- **Restoring a backup from a file:** one request up to `KALMIDO_BACKUP_MAX_MB` (default 4096 MB) to
  `/api/admin/backups/upload`, and the restore itself runs inside its request. The Caddy and nginx templates allow that
  size on this path only and an hour on the paths below `/api/admin/backups`, the 120 s stay for everything else. If a proxy gives up on a
  long restore, the restore goes on on the server: wait, then reload the page; do not start it again. A larger
  `KALMIDO_BACKUP_MAX_MB` needs the same value in your proxy.
- **Paths:** with the built-in login everything goes to Kalmido unchanged. With a login proxy (single sign-on) in front,
  some paths must bypass it: see [Reverse proxy](../docs/SELF-HOSTING.md#reverse-proxy).

## Which address goes into `KALMIDO_TRUSTED_PROXIES`

It depends on where the proxy runs. Put what the command prints behind the default, in `.env`, and restart Kalmido:
`KALMIDO_TRUSTED_PROXIES=127.0.0.1,::1,<address>`, then `docker compose up -d kalmido`.

| Your setup | Requests reach Kalmido from | Command |
|---|---|---|
| Caddy or nginx on the host, Kalmido's published port (the two templates) | the gateway of Kalmido's Compose network | `docker network inspect kalmido_default --format '{{(index .IPAM.Config 0).Gateway}}'` |
| Traefik in a container, in one network with Kalmido (the template) | Traefik's container address; name the range of the network, and keep only containers you trust in it | `docker network inspect proxy --format '{{(index .IPAM.Config 0).Subnet}}'` |
| The installer's fallback `network_mode: bridge` (the line is in `docker-compose.override.yml`) with a proxy on the host | the gateway of Docker's default bridge | `docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}'` |

The network `kalmido_default` is named after the folder that holds `docker-compose.yml`; `docker network ls` lists the
networks. It can come back with another address after `docker compose down`: check again then.

**Check it:** open Kalmido through the proxy from outside your network and look at *Settings > Server > Server > Your IP*.

- Right: *As the server sees it* shows your public address, *Via proxy* shows the address from the table and says *trusted*.
- Wrong: a private address like `172.18.0.1`, or *not trusted*. Then the address in `.env` does not match: take the private
  address shown there as the one to compare with the table.
- Still private although trusted: the proxy itself only sees the Docker gateway, see
  [The real client address](../docs/SELF-HOSTING.md#reverse-proxy-and-network).

More: [docs/SELF-HOSTING.md](../docs/SELF-HOSTING.md).
