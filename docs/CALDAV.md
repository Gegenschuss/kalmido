# Calendar apps (CalDAV)

Kalmido 2.9.0 is a CalDAV server for tasks. Every list you can see appears as a task list in calendar and to-do apps, and changes sync both ways:

- Reminders on iPhone, iPad and Mac
- Thunderbird
- Evolution
- Tasks.org (its own CalDAV account, or through DAVx⁵)
- jtx Board and OpenTasks through DAVx⁵

## For users

1. **Settings › Account › App passwords › New app password.** Give it the name of the device. The password is shown once. Each device gets its own password, so you can revoke a lost phone without touching the others.
2. **Settings › Integrations › Calendar apps (CalDAV)** shows three things: the server, the CalDAV address (`https://your-server/dav/`) and your user name. It also has step-by-step guides.
3. Log in with your **Kalmido user name** and the **app password**. Your account password never works for CalDAV, and neither does single sign-on.

| Client | Where | What to enter |
| --- | --- | --- |
| iPhone / iPad | Settings › Apps › Calendar › Calendar Accounts › Add Account › Other › Add CalDAV Account | Server: your host name (for example `kalmido.example.com`), user name, app password. Then switch on **Reminders** in the account. If the account is not found, use Advanced Settings › Account URL `https://host/dav/principals/<user>/`. |
| Mac | System Settings › Internet Accounts › Add Other Account › CalDAV account | Account type Manual: user name, app password, server address. Fallback: account type Advanced, server path `/dav/principals/<user>/`, port 443, SSL on. Tick Reminders. |
| Thunderbird (Windows, macOS, Linux) | Tasks › New Calendar › On the Network | User name, location `https://host/dav/`, Find Calendars, then pick the lists. Enter the app password when Thunderbird asks for it. |
| Tasks.org (Android) | Settings › Synchronization › Add account › CalDAV | URL `https://host/dav/`, user name, app password. |
| DAVx⁵ (Android) | + › Login with URL and user name | Base URL `https://host/dav/` (or just `https://host/`), user name, app password. Tick the lists under CalDAV and pick the task app (Tasks.org, jtx Board, OpenTasks). |
| Evolution (Linux) | File › New › Task List, type CalDAV | URL `https://host/dav/`, user name, Find Task Lists. |
| Windows | – | The Windows Calendar app and Outlook do not sync tasks over CalDAV. Use Thunderbird. |

### What syncs

| Kalmido | iCalendar (VTODO) |
| --- | --- |
| Title / notes | `SUMMARY` / `DESCRIPTION` |
| Due date (all-day or with a time) | `DUE` (`VALUE=DATE` or a date-time). Kalmido writes the server's time zone with a `VTIMEZONE` and converts any `TZID` or UTC time it receives into that zone. |
| Start (timeline) | `DTSTART` (same value type as `DUE`; a `DTSTART` equal to `DUE` is not a start) |
| Priority high / medium / low | `PRIORITY` 1 / 5 / 9 (incoming 1–4 / 5 / 6–9) |
| Open / done / won't do | `STATUS` NEEDS-ACTION / COMPLETED / CANCELLED, plus `COMPLETED` and `PERCENT-COMPLETE:100` (`IN-PROCESS` counts as open) |
| Your tags | `CATEGORIES` |
| Subtasks | `RELATED-TO;RELTYPE=PARENT` (a child may arrive before its parent) |
| Repeat (daily, weekly, monthly, yearly) | `RRULE`. Completing a repeating task in a client moves it to the next date, as in the app, and the done occurrence appears as a new completed task. |
| Reminders | `VALARM` with a relative (`RELATED=END`/`START`) or absolute `TRIGGER`. For all-day tasks the offset counts from your all-day reminder time (Settings › Notifications). |
| Link | `URL` |
| UID | Stable. The client's UID is kept; tasks made in Kalmido get `kalmido-<id>-<instance>`. |

**Round trip.** Everything else a client writes is stored as it came and sent back unchanged: `X-` properties, `SEQUENCE`, `CLASS`, location alarms, alarms Kalmido cannot map, and `RRULE`s Kalmido cannot repeat (hourly, `RDATE`, `EXDATE`). The client keeps repeating such a task itself.

**Not synced.** Assignee, sections, comments, files, custom fields, dependencies and time entries stay in Kalmido. Changed single occurrences (`RECURRENCE-ID`) are dropped, except "this occurrence is done", which completes the current date.

**Tags and subtasks in Reminders.** Reminders on iPhone and Mac do not send tags or subtasks over CalDAV. Kalmido remembers per app password whether a client ever sent `CATEGORIES` or `RELATED-TO`. A client that never did cannot clear tags or a parent by leaving them out, so what you set in Kalmido stays.

**Completed tasks** stay visible in the apps for `KALMIDO_CALDAV_DONE_DAYS` days (default 90).

**Roles.**
- Lists you can only view are read-only in the apps.
- Participants see and change only the tasks assigned to them, and new tasks they create are assigned to them.
- Deleting a task in an app moves it to the trash in Kalmido.
- Lists are created, renamed and deleted in Kalmido (`MKCALENDAR`, `PROPPATCH` and deleting a collection are refused).
- Moving a task to another list in a client (the same UID in another calendar) moves the Kalmido task, with its history and comments.

Changes made over CalDAV show "via CalDAV" in the task history. Webhooks and agent events carry `"via": "caldav"`.

## For admins

### Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `KALMIDO_CALDAV` | `1` | `0` turns CalDAV off: `/dav` and `/.well-known/caldav` answer 404, and no new app passwords can be created. |
| `KALMIDO_CALDAV_DONE_DAYS` | `90` | How many days completed tasks stay in the apps. |
| `KALMIDO_CALDAV_HTTP` | `0` | CalDAV sends the app password with every request (HTTP Basic). It is accepted only over https: a trusted proxy (`KALMIDO_TRUSTED_PROXIES`) that sends `X-Forwarded-Proto: https`, or, for requests without that header, while `PUBLIC_URL` is `https://`. A trusted proxy that reports `http` is refused. Set `1` to allow plain http inside a trusted network. |

App passwords are stored only as a hash, using the same key derivation as account passwords. Failed CalDAV logins count like failed web logins, per client address (behind a proxy the address it forwards, see `KALMIDO_TRUSTED_PROXIES` in the README): 10 per user name and address, 30 per address, and 150 per user name from all addresses together within 15 minutes, then 429. One attacker therefore cannot lock a person out. They are reported in the admin alerts. Passwords never appear in the log. Agents never get CalDAV.

### Reverse proxy: let /dav past the login proxy

Calendar apps cannot log in at a login portal (Authelia, Authentik, oauth2-proxy and similar). If Kalmido sits behind **forward auth**, the CalDAV paths must skip it. Kalmido checks the app password itself and never trusts the proxy's user header on these paths.

Paths to bypass:

```
/dav
/dav/*
/.well-known/caldav
/.well-known/caldav/*
```

Clients that only get the host name also send `PROPFIND /` (Kalmido redirects it to `/dav/`). If your proxy gates `/`, enter `https://host/dav/` in those clients instead.

**Caddy with forward_auth** (Authelia shown; same pattern for Authentik):

```caddy
kalmido.example.com {
	@dav path /dav /dav/* /.well-known/caldav /.well-known/caldav/*
	route {
		# never pass client-sent identity headers
		request_header -Remote-User
		request_header -Remote-Groups
		request_header -Remote-Email
		request_header -Remote-Name
		# calendar apps: straight to Kalmido (app password = the credential)
		reverse_proxy @dav 127.0.0.1:3040
		# everything else: the login portal first
		forward_auth 127.0.0.1:9091 {
			uri /api/authz/forward-auth
			copy_headers Remote-User Remote-Groups Remote-Email Remote-Name
		}
		reverse_proxy 127.0.0.1:3040
	}
}
```

The `route` block keeps the order: a `/dav` request is answered by the first `reverse_proxy` and never reaches `forward_auth`.

**Authelia access control.** Use this if your proxy asks Authelia for every path and you prefer the rule there:

```yaml
access_control:
  default_policy: deny
  rules:
    - domain: kalmido.example.com
      resources:
        - '^/dav([/?].*)?$'
        - '^/\.well-known/caldav([/?].*)?$'
      policy: bypass
    - domain: kalmido.example.com
      policy: one_factor   # or two_factor
```

**nginx with auth_request:**

```nginx
location ~ ^/(dav|\.well-known/caldav)(/|$) {
    auth_request off;
    proxy_pass http://127.0.0.1:3040;
    proxy_set_header Host $host;
    proxy_set_header Authorization $http_authorization;
    proxy_pass_request_headers on;
}
```

**Traefik.** Add a second router for `PathPrefix(`/dav`) || PathPrefix(`/.well-known/caldav`)` on the same host, without the forward-auth middleware, and give it a higher priority than the main router.

The proxy must pass the `Authorization` header and the WebDAV methods `PROPFIND`, `REPORT`, `PROPPATCH`, `PUT`, `DELETE` and `OPTIONS`. Caddy and nginx do this by default. Some web application firewalls block these methods.

### Checking it

```sh
curl -u 'user:app-password' -X PROPFIND -H 'Depth: 0' https://kalmido.example.com/dav/
```

This should answer `207 Multi-Status` with `current-user-principal`. A `302` to a login page means the proxy still gates `/dav`.

### API

App passwords can also be managed with a personal access token (`read` to list them, `write` to create or revoke). See [API.md](API.md):

- `GET /api/v1/me/app-passwords`
- `POST /api/v1/me/app-passwords` with `{"name": "..."}`
- `DELETE /api/v1/me/app-passwords/{id}`

Agents' tokens get 403.
