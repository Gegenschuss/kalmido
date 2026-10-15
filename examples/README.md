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
  the addresses in `KALMIDO_TRUSTED_PROXIES` (default: localhost and Docker's default bridge). Through Docker's port
  publishing, or from a proxy container on another Docker network, requests arrive from that network's gateway: add it
  (`docker network inspect <network>`, field `Gateway`). Under *Administration > Server* Kalmido warns when client
  addresses do not arrive.
- **Upload size:** one request may carry files up to 4 x `TASKS_MAX_FILE_MB` (default 50 MB, so 200 MB).
- **Paths:** with the built-in login everything goes to Kalmido unchanged. With a login proxy (single sign-on) in front,
  some paths must bypass it: see the README, section *Reverse proxy*.

More: [docs/SELF-HOSTING.md](../docs/SELF-HOSTING.md).
