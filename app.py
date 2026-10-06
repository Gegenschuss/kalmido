#!/usr/bin/env python3
"""Kalmido — self-hosted task manager (multi-user, shared lists).

Login: either a trusted reverse proxy that sends the user name in a header (AUTH_PROXY_HEADER, only
honoured from AUTH_TRUSTED_PROXIES and, if set, only on AUTH_PROXY_PORT) or the built-in
username/password login with a session cookie. The first start without users shows a setup page.
Storage: SQLite at /data/tasks.db. Dates are LOCAL ($TZ, Europe/Berlin):
tasks.due = 'YYYY-MM-DD', tasks.due_time = 'HH:MM' or NULL (all-day).

Modules: lists (+ sections = kanban columns), tasks with subtasks, tags, priority, reminders,
recurrence (RRULE via dateutil), habits, pomodoro. Lists have one owner and can be shared with other
users (role admin / edit / participant / view); tasks and subtasks in shared lists can be assigned. Tasks have comments (with @mentions
and files), an activity history and a website link. Habits, focus sessions, filters,
folders, tags and settings are per user. A watchdog thread sends ntfy pushes (per user topic) for due
reminders, finished focus sessions, habit reminders and the optional daily digest.
TickTick CSV backups can be imported (idempotent via tasks.tt_id per user); package C adds Todoist, Trello, Asana,
Microsoft To Do / Outlook and ICS / VTODO importers with preview, dry run and undo.

CSRF: every state-changing /api request must carry the header "X-Requested-With: kalmido" (the web
client always sends it; a cross-site page cannot set it without a CORS preflight, which is never
allowed). Session cookies are HttpOnly + SameSite=Lax.

Code layout: the server lives in the package kalmido/ (one module per area, see docs/ARCHITECTURE.md); this file is the
entry point (`python app.py`, `python app.py set-password <user>`, `python app.py import <file> [user]`)."""
import kalmido

# every module's names stay reachable as app.<name> (python -c "import app; app.connect()", the test suites, WSGI servers
# pointed at app:app)
for _m in kalmido.MODULES:
    globals().update({k: v for k, v in vars(_m).items() if not k.startswith("__")})
del _m

if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3 and sys.argv[1] == "import":
        c = connect()
        uid = default_uid(c)
        if len(sys.argv) == 4:
            uid = c.execute("SELECT id FROM users WHERE username=?", (sys.argv[3].lower(),)).fetchone()[0]
        print(import_ticktick(c, open(sys.argv[2], encoding="utf-8-sig").read(), uid))
        c.close()
        sys.exit(0)
    if len(sys.argv) == 3 and sys.argv[1] == "set-password":  # docker exec -it <container> python app.py set-password <user>
        import getpass
        c = connect()
        pw = getpass.getpass("new password: ")
        if len(pw) < MIN_PASSWORD or pw != getpass.getpass("again: "):
            sys.exit(f"passwords differ or shorter than {MIN_PASSWORD} characters")
        n = c.execute("UPDATE users SET password_hash=?, disabled=0 WHERE username=?",
                      (generate_password_hash(pw), sys.argv[2].lower())).rowcount
        c.commit()
        c.close()
        sys.exit(0 if n else f"no user {sys.argv[2]!r}")
    if len(sys.argv) >= 3 and sys.argv[1] == "announce":  # 2.24.0 (#907): docker exec <container> python app.py announce "text" --minutes 30
        sys.exit(announce_cli(sys.argv[2:]))
    from waitress import serve
    port = int(os.environ.get("PORT", 3040))
    listen = f"0.0.0.0:{port}" + (f" 0.0.0.0:{AUTH_PROXY_PORT}" if AUTH_PROXY_PORT and AUTH_PROXY_PORT != str(port) else "")
    # restore uploads may be larger than attachments (waitress spools the body to a temp file first)
    # 2.0.0: 16 threads (was 8): agents' long-polls (at most KALMIDO_AGENT_WAITERS) each hold one while waiting
    # 2.10.0 (#445): forwarded headers are handled by proxy_mw (several trusted proxies / networks, which waitress'
    # trusted_proxy cannot express); waitress must not clear them before the app sees them.
    serve(app, listen=listen, threads=16, max_request_body_size=max(BK_MAX_BYTES, app.config["MAX_CONTENT_LENGTH"]) + 1024 * 1024,
          clear_untrusted_proxy_headers=False)
