# Notifications

Web Push, ntfy and the other channels.

## Notifications

Kalmido has two ways to reach you. Pick one per account under *Settings > Notifications > Channel*:

| Channel | What it needs | |
|---|---|---|
| **Web Push** (default) | nothing extra: the browser or the installed app shows the notifications | turn it on per device |
| **ntfy** | the [ntfy](https://ntfy.sh) app and a topic | one topic for all your devices |
| **Both** | both of the above | every push twice |

**Web Push**, on every device that should ring:

1. Open Kalmido (on a phone: installed to the home screen is best), *Settings > Notifications*.
2. Tick *Notify on this device* and allow notifications when the browser asks.
3. Press *Send test to this device*.

Works in Chrome, Edge, Samsung Internet, Opera and Firefox on Android and the desktop, and in Safari on macOS 13+.
**iPhone and iPad:** only in the app added to the Home Screen (iOS / iPadOS 16.4 or newer): in Safari *Share > Add to
Home Screen*, open Kalmido from there, then turn it on as above. The settings show a hint when this is missing.
The project below the switch shows all your devices; remove one there (logging out removes the current device too).

As long as none of your devices is subscribed (or none of them accepts a push, e.g. after a browser reset), the pushes
go to your ntfy topic instead, so switching from ntfy loses nothing: *Settings > Notifications* says "No device
subscribed yet — using ntfy for now" until the first device is on.

Reminders carry two buttons: *Done* completes the task right from the notification (with your login session; if it
expired, the app opens and completes it), *Snooze* opens the snooze options. Comment and mention pushes carry *Reply*
(opens the task with the comment box ready) and *Done*. Tapping a notification opens the task,
project or view it is about. Several pushes about the same task replace each other instead of piling up.

**ntfy:**

1. Install the ntfy app ([Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy), [iOS](https://apps.apple.com/app/ntfy/id1625396347)).
2. Open Kalmido > *Settings > Notifications*: your topic is shown there (every user has an own one). Subscribe to it in the ntfy app.
3. Press *Send test* next to the topic.

On ntfy.sh anyone who knows the topic name can read it, so keep it random or run your own ntfy server with a token.

Besides reminders, focus end, habit reminders and the daily digest, Kalmido pushes new comments, @mentions,
assignments and completions in shared projects (see *Comments and activity*; off with the *Collaboration* module), and
the time tracking reminders (timer still running, stopped automatically). Every kind goes over your channel.

**How urgent** (*Settings > Notifications*): *Normal* (ntfy 3), *Loud* (ntfy 4, the default) or *Urgent* (ntfy 5), used by both
channels (ntfy priority; Web Push: *High* and *Urgent* are sent with `Urgency: high`, *Urgent* notifications also stay
on screen until you dismiss them). Two kinds never go out below *High*, even when you choose *Normal*: reminders of
tasks with priority *high*, and the notice that a forgotten timer was stopped automatically.

**Privacy of Web Push:** the notification text is end-to-end encrypted on your server (RFC 8291) with the keys of
your browser; the push service in between (Google FCM for Chrome / Edge on Android and most Chromium browsers,
Mozilla for Firefox, Apple for Safari and iOS, Microsoft WNS for Edge on Windows) only sees that a message of a
certain size goes to a certain device at a certain time, never its content. The payload holds only what the
notification shows (title, text, the in-app link, the buttons). Your server signs each push with its own VAPID key,
created on the first start and stored in the database; the private half never leaves the server. The server only
sends to https endpoints of those services (`fcm.googleapis.com`, `*.push.services.mozilla.com`,
`web.push.apple.com` / `*.push.apple.com`, `*.notify.windows.com`); add others with `KALMIDO_WEBPUSH_HOSTS`.
Delivery goes through the push service, so it also reaches a phone that cannot reach your server at that moment
(a server only reachable at home or over a VPN); only opening the task needs the server.

### Admin alerts

Things that need an admin's eye go to the admins over their own notification channel (2.5.2). With the public
`ntfy.sh` (the default `NTFY_URL`) nothing goes there unless someone chose it: an admin on *Web Push* (the default) gets
the alerts on their subscribed devices, and none at all until they subscribe a device under *Settings > Notifications*
(the alerts are then only listed in the settings); the channels *ntfy* / *Both* send them to the admin's own topic. With
your own ntfy server (`NTFY_URL` elsewhere) each admin's own topic gets them whatever channel they use, as before.
*Settings > Server > Admin alerts* shows where they go per admin and can set one shared admin
topic instead (or `KALMIDO_ADMIN_TOPIC` fixes it), the priority (default *High*, 4) and *Send test alert* (labelled
"Kalmido test alert").
Regular users never get them. Each alert comes in the admin's language.

| Kind (each can be switched off) | When |
|---|---|
| Update available | the update check found a new release (once per version) |
| Web Push delivery | a device was removed because its push service refused it (404 / 410, or 4xx five times in a row), or pushes fell back to ntfy although the user has devices |
| Watchdog errors | rows the background job had to skip (e.g. a reminder with a broken value), summed up per hour with their ids |
| Integration problems | five ntfy or Web Push deliveries in a row failed (or sign-ins with the OIDC provider; 2.574.0: the ntfy share inbox is gone) |
| Security events | five or more failed logins within an hour and every login rate-limit trip (per user / IP), bursts of invalid `/drop` or calendar feed tokens, a new admin, a changed server switch (collaboration, time tracking, update check, admin alerts, admin topic) |
| Storage and health | less than 5 % or 1 GB free on the data volume, data page checksum failures reported by PostgreSQL (daily check), the attachment folder not writable |

Alerts only carry counts, ids, usernames, device labels, IP addresses and error classes, never task titles,
comments, project names or file names; login names that do not exist are shown as `?` (it could be a password typed
into the wrong field). Against floods: an identical alert (same kind and subject) goes out at most once per 6 hours
(the project counts the repeats), at most 10 alerts per hour (the rest is only listed), or everything in one *daily
summary* at a time you choose. All limits and thresholds are under *Limits and thresholds*. The last 50 alerts are
listed below the settings with their state (delivered, not delivered, waiting for the summary, hourly limit
reached) and can be cleared. The background job (watchdog) sends them, so they need `TASKS_WATCHDOG` on (default).
