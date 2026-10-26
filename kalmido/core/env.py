"""2.149.0 D (#2511): the registry of the environment variables the server reads (name, default, one English sentence,
group) and the readers env_str / env_int / env_bool with ONE reading of a switch: 1 / true / yes / on = on and
0 / false / no / off = off (any case, blanks around ignored); an empty or unset variable means the default.

docs/ENV.md is generated from VARS (python3 tools/env_check.py --write-docs); the CI check (tools/env_check.py) fails when
the server reads a variable that is not declared here or when docs/ENV.md is stale. Most places still read os.environ
directly with their own default (the check sees both ways); the default written here is the documented one and is used
by the readers below when the caller passes none. A VARS entry is a plain call with literal values (the check reads them
without importing the app). No imports from the app: every module may use this one."""
import os
import sys

ON = ("1", "true", "yes", "on")
OFF = ("0", "false", "no", "off")


def _v(name, default, doc, group):
    return name, default, doc, group


VARS = (
    # ---- core: data, database, address
    _v("TASKS_DB", "/data/tasks.db", "Names the data directory (its folder holds attachments, office files, backups and the marker file) and an old SQLite file from before 2.37 that is moved to PostgreSQL on the first start.", "core"),
    _v("DATABASE_URL", "", "PostgreSQL connection (postgresql://user:password@host:5432/db). Required.", "core"),
    _v("KALMIDO_DB_WAIT", "60", "Seconds the start waits for the database to answer.", "core"),
    _v("KALMIDO_DB_POOL_MAX", "", "Largest number of pooled database connections per process (empty = threads x 3 + 8).", "core"),
    _v("KALMIDO_POOL_MAX", "", "Older name of KALMIDO_DB_POOL_MAX (used when that one is not set).", "core"),
    _v("KALMIDO_DB_STATEMENT_TIMEOUT", "30", "Seconds one database statement of a request may run (0 = no limit).", "core"),
    _v("KALMIDO_THREADS", "16", "Web server threads per process (2-256).", "core"),
    _v("PUBLIC_URL", "http://localhost:3040", "The address people use to open Kalmido (https://tasks.example.com). Used for links in notifications and mails, passkeys and the origin check; set it on every server.", "core"),
    _v("PORT", "3040", "Port the web server listens on inside the container.", "core"),
    _v("TZ", "Europe/Berlin", "Time zone of the server (due dates, daily jobs, reminders).", "core"),
    _v("TASKS_ATTACHMENTS", "<data dir>/attachments", "Folder of the uploaded files.", "core"),
    _v("TASKS_OFFICE_DIR", "<data dir>/office", "Folder of the office files (logos, documents); part of the backups.", "core"),
    _v("TASKS_EXPORT_DIR", "<data dir>/exports", "Folder of the organisation exports while they are offered for download.", "core"),
    _v("TASKS_TEXT_CACHE", "<data dir>/textcache", "Folder of the extracted text of attachments (search, previews).", "core"),
    _v("TASKS_MAX_FILE_MB", "50", "Largest upload in MB.", "core"),
    _v("KALMIDO_ALLOW_DOWNGRADE", "0", "Switch: start on a database (or restore a backup) that a newer minor version of Kalmido wrote. Only for an emergency; the older version may not understand newer data.", "core"),
    _v("KALMIDO_SLOW_REQUEST_MS", "500", "Requests slower than this many milliseconds get a log line with route, duration and statement count (0 = off).", "core"),
    _v("KALMIDO_ACX_TTL", "10", "Seconds the access context of a person (roles, organisations) is cached per process (0 = off).", "core"),
    _v("KALMIDO_ROLE", "all", "What this process runs: all (web + background work), web (requests only) or worker (background work only).", "core"),
    _v("KALMIDO_REPLICAS", "1", "Number of web processes behind one database (only for the connection check at start).", "core"),
    _v("KALMIDO_INSTANCE_MODE", "", "Older switch of the instance mode (shared / workspaces); since 2.46 only read for the row-level security check.", "core"),
    _v("KALMIDO_ORG_NAME", "", "Name of the first organisation created on a new server.", "core"),
    _v("KALMIDO_UPDATE_CHECK", "1", "Switch: admins see when a newer release exists (one request a few times a day, never updates anything).", "core"),
    _v("KALMIDO_UPDATE_URL", "https://api.github.com/repos/Gegenschuss/kalmido/releases/latest", "Address the update check asks for the latest release.", "core"),
    _v("KALMIDO_SEARCH_INDEX", "0", "Switch: allow search engines to index this server (public links and forms stay noindex).", "core"),
    _v("KALMIDO_ONBOARDING", "1", "Switch: new accounts get a sample list and the welcome tour.", "core"),
    _v("KALMIDO_IOS_SHORTCUT_URL", "", "Link to an iOS shortcut shown in Settings > Integrations (empty = hidden).", "core"),
    _v("KALMIDO_MIGRATE_CLI", "", "Internal: set by `python app.py migrate-sqlite` for the move from SQLite.", "core"),
    _v("PATH", "", "Search path for the helper programs (pg_dump, tesseract); passed on to them unchanged.", "core"),

    # ---- login, accounts and proxy
    _v("AUTH_PROXY_HEADER", "", "Header of a trusted proxy that carries the user name (single sign-on), e.g. Remote-User.", "auth"),
    _v("AUTH_TRUSTED_PROXIES", "", "Addresses / networks allowed to send AUTH_PROXY_HEADER.", "auth"),
    _v("AUTH_PROXY_PORT", "", "Port that only accepts proxy-header logins (the normal port then ignores the header).", "auth"),
    _v("AUTH_SESSION_DAYS", "30", "Days a login stays valid.", "auth"),
    _v("AUTH_BOOTSTRAP_USER", "admin", "User name of the admin created when an old single-user database is taken over.", "auth"),
    _v("AUTH_BOOTSTRAP_NAME", "", "Display name of that admin (empty = the user name).", "auth"),
    _v("AUTH_BOOTSTRAP_PROXY_LOGIN", "", "Proxy login name linked to that admin.", "auth"),
    _v("KALMIDO_TRUSTED_PROXIES", "127.0.0.1,::1", "Reverse proxies whose X-Forwarded-For / -Proto headers are believed.", "auth"),
    _v("KALMIDO_TRUSTED_PROXY_COUNT", "1", "Number of trusted proxies in a row in front of the server (1-5).", "auth"),
    _v("KALMIDO_SETUP_CODE", "", "One-time code of the first setup: empty = a random code in the log, a fixed value, or off (tests only).", "auth"),
    _v("KALMIDO_WEBAUTHN_RP_ID", "", "Passkey domain (empty = the host of PUBLIC_URL).", "auth"),
    _v("KALMIDO_WEBAUTHN_ORIGINS", "", "Additional origins allowed for passkeys, comma-separated (since 2.190 also needed for localhost origins when PUBLIC_URL is not localhost).", "auth"),
    _v("KALMIDO_OIDC_ALLOW_HOSTS", "", "Internal hosts an OpenID Connect provider may live on.", "auth"),
    _v("KALMIDO_OIDC_ISSUER", "", "OpenID Connect issuer URL (locks the setting in the app).", "auth"),
    _v("KALMIDO_OIDC_CLIENT_ID", "", "OpenID Connect client id.", "auth"),
    _v("KALMIDO_OIDC_CLIENT_SECRET", "", "OpenID Connect client secret.", "auth"),
    _v("KALMIDO_OIDC_SCOPES", "", "OpenID Connect scopes.", "auth"),
    _v("KALMIDO_OIDC_USERNAME_CLAIM", "", "Claim that holds the user name.", "auth"),
    _v("KALMIDO_OIDC_GROUPS_CLAIM", "", "Claim that holds the groups.", "auth"),
    _v("KALMIDO_OIDC_REQUIRED_GROUP", "", "Group a person must be in to sign in.", "auth"),
    _v("KALMIDO_OIDC_ADMIN_GROUP", "", "Group whose members become admins.", "auth"),
    _v("KALMIDO_OIDC_ADMIN_DOMAINS", "", "Verified e-mail domains whose people become admins.", "auth"),
    _v("KALMIDO_OIDC_BUTTON_LABEL", "", "Text of the sign-in button.", "auth"),
    _v("KALMIDO_DISC_PER_IP", "60", "Account searches and checks per client address in 15 minutes.", "auth"),
    _v("KALMIDO_IP_WARN_ACCOUNTS", "3", "Accounts signing in from one private address before the log warns (missing proxy setup).", "auth"),
    _v("KALMIDO_PORTAL_LOGIN_SPACE", "200", "Sign-in mails of the client portal per workspace and hour.", "auth"),
    _v("TASKS_DROP_TOKEN", "", "Upload token of the first admin when an old single-user database is taken over.", "auth"),

    # ---- server key, encryption and limits
    _v("KALMIDO_SECRET_KEY", "", "The server key (32 bytes, base64). Encrypts organisation data and stored tokens; wins over KALMIDO_SECRET_FILE. Keep a copy apart from the backups.", "security"),
    _v("KALMIDO_SECRET_FILE", "", "File that holds the server key; created once when missing. Must not lie inside the data or backup folder. In the image: /secret/kalmido.key when /secret is a mounted volume.", "security"),
    _v("KALMIDO_NO_SECRET_KEY", "0", "Switch: let a NEW server start without a server key (data then stays unencrypted). Tests and demos only.", "security"),
    _v("KALMIDO_SECRET_KEY_CHANGED", "0", "Switch: accept a server key that differs from the one this database was used with (a key changed on purpose; rewrap afterwards, then remove it again).", "security"),  # 2.190.0 B (#2592)
    _v("KALMIDO_ORGCRYPT_PAUSE", "0.2", "Seconds between two portions of the background encryption pass.", "security"),
    _v("KALMIDO_ORGCRYPT_DELAY", "", "Seconds before the background encryption pass starts after a start (default: 300).", "security"),
    _v("KALMIDO_ORGCRYPT_ROT_SETTLE", "5", "Seconds the key rotation waits after the switch to the new key.", "security"),
    _v("KALMIDO_TENANT_CHECK", "", "Daily check of the organisation boundaries: empty = daily, always = every watchdog tick, 0 / off = never.", "security"),
    _v("KALMIDO_TENANT_CHECK_HOUR", "3", "Local hour from which the daily boundary check runs.", "security"),
    _v("KALMIDO_PUBLIC_RATE", "60", "Page views of public links per client address and minute.", "security"),
    _v("KALMIDO_PUBLIC_BURST", "300", "Views of one public link in a short time that raise a security alert.", "security"),
    _v("KALMIDO_SUPPORTER_EXTRA_PUBKEYS", "", "Additional public keys accepted for supporter licences.", "security"),
    _v("KALMIDO_LOG_FULL_IP", "0", "Switch: addresses in the server log are shortened like the alerts (IPv4 /24, IPv6 /48); 1 keeps them in full (for fail2ban, which bans by the address).", "security"),  # 2.239.0 B (#2888)
    _v("KALMIDO_LOGIN_SLOW_S", "2.5", "Seconds a sign-in waits when its address had many failed logins (2.282.0: a delay instead of a lock; names known at that address are not delayed).", "security"),

    # ---- notifications and push
    _v("NTFY_URL", "https://ntfy.sh", "ntfy server for push notifications.", "notify"),
    _v("NTFY_TOKEN", "", "Write token for an own ntfy server.", "notify"),
    _v("NTFY_TOPIC", "", "ntfy topic of the first admin (later accounts get their own).", "notify"),
    _v("NTFY_INBOX_URL", "", "ntfy server of the share inbox (Android share to Kalmido).", "notify"),
    _v("NTFY_INBOX_TOKEN", "", "Read token of the share inbox.", "notify"),
    _v("NTFY_INBOX_TOPIC", "inbox", "Topic of the share inbox (16+ characters on the public ntfy.sh).", "notify"),
    _v("NTFY_INBOX_PUBLIC", "", "Public address of the inbox's ntfy server shown in the settings.", "notify"),
    _v("NTFY_INBOX_USER", "", "Account that receives the shared items (empty = the first admin).", "notify"),
    _v("KALMIDO_WEBPUSH", "1", "Switch: browser push notifications.", "notify"),
    _v("KALMIDO_WEBPUSH_HOSTS", "", "Additional push services allowed (host, *.domain or an exact origin).", "notify"),
    _v("KALMIDO_WEBPUSH_APPLE", "", "Endpoint prefixes that behave like Apple's push service (tests).", "notify"),
    _v("KALMIDO_VAPID_SUBJECT", "", "Contact of the push keys (empty = PUBLIC_URL if https, else mailto:admin@example.com).", "notify"),
    _v("KALMIDO_DISMISS_WAIT", "30", "Seconds before a read notification is removed from the other devices.", "notify"),
    _v("KALMIDO_DISMISS_GAP", "60", "Seconds between two such removals per person.", "notify"),
    _v("KALMIDO_DISMISS_DAY", "30", "Removals per person and day.", "notify"),
    _v("KALMIDO_NOTIF_TEMPLATE", "read", "Notification template of a share without one: read, work or all.", "notify"),
    _v("KALMIDO_CHANNELS", "1", "Switch: notification channels (Slack, Matrix, Telegram, Signal).", "notify"),
    _v("KALMIDO_CHANNEL_FAILS", "5", "Failed deliveries in a row after which a channel is switched off.", "notify"),
    _v("KALMIDO_CHANNEL_TICK", "5", "Seconds between two deliveries rounds of the channels.", "notify"),
    _v("KALMIDO_TELEGRAM_API", "https://api.telegram.org", "Address of the Telegram bot API.", "notify"),
    _v("KALMIDO_EVENT_MAIL_DELAY", "600", "Seconds after the first event before a summary mail goes out.", "notify"),
    _v("KALMIDO_EVENT_MAIL_GAP", "600", "Least seconds between two summary mails to one person.", "notify"),
    _v("KALMIDO_ADMIN_ALERTS", "1", "Switch: admins get alerts (security, failed backups, integrations).", "notify"),
    _v("KALMIDO_ADMIN_TOPIC", "", "ntfy topic for the admin alerts (empty = the admins' own topics).", "notify"),
    _v("KALMIDO_ADMIN_ALERT_WINDOW", "3600", "Seconds over which repeated alerts are summed up.", "notify"),
    _v("TASKS_PUSH_GAP", "60", "Least seconds between two comment notifications of one task.", "notify"),
    _v("TASKS_NEWS_DAYS", "90", "Days the News entries are kept.", "notify"),
    _v("TASKS_NEWS_MAX", "500", "News entries kept per person at most.", "notify"),

    # ---- e-mail
    _v("KALMIDO_SMTP_HOST", "", "SMTP server for outgoing mail (empty = no mail).", "mail"),
    _v("KALMIDO_SMTP_PORT", "0", "SMTP port (0 = the port of the TLS mode).", "mail"),
    _v("KALMIDO_SMTP_USER", "", "SMTP user.", "mail"),
    _v("KALMIDO_SMTP_PASSWORD", "", "SMTP password.", "mail"),
    _v("KALMIDO_SMTP_TLS", "starttls", "SMTP encryption: starttls, ssl or none.", "mail"),
    _v("KALMIDO_SMTP_INSECURE", "0", "Switch: do not check the certificate of the admin mail server (SMTP and IMAP; warned at start).", "mail"),
    _v("KALMIDO_MAIL_FROM", "", "Sender address (empty = KALMIDO_MAIL_ADDRESS).", "mail"),
    _v("KALMIDO_MAIL_ADDRESS", "", "Address of the mailbox that turns incoming mails into tasks.", "mail"),
    _v("KALMIDO_MAIL_AUTHSERV_ID", "", "Name of the own mail server in Authentication-Results headers that are believed.", "mail"),
    _v("KALMIDO_IMAP_HOST", "", "IMAP server of that mailbox.", "mail"),
    _v("KALMIDO_IMAP_PORT", "0", "IMAP port (0 = the default of the TLS mode).", "mail"),
    _v("KALMIDO_IMAP_USER", "", "IMAP user.", "mail"),
    _v("KALMIDO_IMAP_PASSWORD", "", "IMAP password.", "mail"),
    _v("KALMIDO_IMAP_SSL", "1", "Switch: IMAP over TLS.", "mail"),
    _v("KALMIDO_IMAP_KEEP", "0", "Switch: keep imported mails in the mailbox (only marked read) instead of deleting them. Mails not taken in whole (too large, refused, an attachment not stored) always stay, marked read.", "mail"),
    _v("KALMIDO_IMAP_FOLDER", "INBOX", "IMAP folder that is read.", "mail"),
    _v("KALMIDO_IMAP_INTERVAL", "60", "Seconds between two looks into the mailbox (at least 10).", "mail"),
    _v("KALMIDO_OFFICE_MAILS_DAY_ORG", "300", "Office documents sent by mail per organisation and day.", "mail"),
    _v("KALMIDO_OFFICE_MAILS_DAY_PERSON", "150", "Office documents sent by mail per person and day.", "mail"),
    _v("KALMIDO_OFFICE_MAILS_DAY_ADDRESS", "20", "Office documents sent by mail per organisation, receiving address and day.", "mail"),

    # ---- files, scanning and text recognition
    _v("KALMIDO_CLAMD", "", "Virus scanner (clamd) as host:port; empty = no scan (Docker Compose sets clamav:3310).", "files"),
    _v("KALMIDO_CLAMD_STRICT", "", "Switch: files the scanner could not check yet stay locked (empty = on whenever a scanner is set).", "files"),
    _v("KALMIDO_CLAMD_MAX_MB", "100", "Largest file in MB the scanner checks.", "files"),
    _v("KALMIDO_CLAMD_TIMEOUT", "60", "Seconds one scan may take.", "files"),
    _v("KALMIDO_CLAMD_DOWN_S", "30", "Seconds a failed scanner is not asked again.", "files"),
    _v("KALMIDO_WIKI_FILE_MAX_MB", "100", "Largest PDF or picture in MB of a knowledge page (upload and ZIP import), 2.177.0.", "files"),
    _v("KALMIDO_WIKI_IMPORT_MAX_MB", "4096", "Size in MB of a ZIP of knowledge pages that can be imported (and of everything unpacked from it), 2.177.0.", "files"),
    _v("KALMIDO_WIKI_IMPORT_MAX_FILES", "10000", "Entries of a ZIP of knowledge pages at most, 2.177.0.", "files"),
    _v("KALMIDO_CLAMD_TICK_S", "60", "Seconds between two catch-up runs of the scanner.", "files"),
    _v("KALMIDO_MIME_SWEEP", "on", "Switch: give older files the type their content shows (once, a few per minute), 2.209.0.", "files"),
    _v("KALMIDO_FILE_OCR", "on", "Switch: read the text of uploaded files (search).", "files"),
    _v("KALMIDO_FILE_OCR_BACKFILL", "on", "Switch: read files uploaded before in the background.", "files"),
    _v("KALMIDO_FILE_OCR_BACKFILL_S", "20", "Seconds between two files of that catch-up.", "files"),
    _v("KALMIDO_FILE_OCR_MAX_MB", "50", "Largest file in MB whose text is read.", "files"),
    _v("KALMIDO_FILE_OCR_REHOME_S", "300", "Seconds between two sweeps that move read texts to their workspace.", "files"),
    _v("KALMIDO_OCR_LANGS", "deu+eng", "Languages of the text recognition (tesseract codes).", "files"),
    _v("KALMIDO_OCR_PAGES", "30", "Pages recognised per document at most.", "files"),
    _v("KALMIDO_OCR_PAGE_S", "60", "Seconds per page at most.", "files"),
    _v("KALMIDO_OCR_PARALLEL", "1", "Documents recognised at the same time.", "files"),
    _v("KALMIDO_OCR_MEM_MB", "1024", "Memory in MB of one recognition tool.", "files"),
    _v("KALMIDO_PDF_TIMEOUT_S", "20", "Seconds for reading the text of one PDF.", "files"),
    _v("KALMIDO_PDF_PARALLEL", "2", "PDFs read at the same time.", "files"),
    _v("KALMIDO_PDF_MEM_MB", "512", "Memory in MB of the PDF reader.", "files"),
    _v("KALMIDO_PHOTO_MAX_PIXELS", "40000000", "Largest photo (pixels) that is re-encoded when it is turned.", "files"),
    _v("KALMIDO_DOCS_SCAN_S", "60", "Seconds between two looks into the document inbox folders.", "files"),
    _v("KALMIDO_DOCS_THUMB_FILL", "on", "Switch: create missing document previews in the background.", "files"),
    _v("KALMIDO_DOCS_THUMB_FILL_S", "15", "Seconds between two portions of previews.", "files"),
    _v("KALMIDO_DOCS_ZIP_MAX_FILES", "2000", "Files per document ZIP download at most.", "files"),
    _v("KALMIDO_DOCS_ZIP_MAX_MB", "1024", "Size in MB of a document ZIP download at most.", "files"),
    _v("KALMIDO_FILES_ZIP_MAX_FILES", "5000", "Files per ZIP download of attachments at most.", "files"),
    _v("KALMIDO_FILES_ZIP_MAX_MB", "1024", "Size in MB of a ZIP download of attachments at most.", "files"),
    _v("KALMIDO_EXT_ZIP_MAX_FILES", "1000", "Files per ZIP download through a shared link at most.", "files"),
    _v("KALMIDO_EXT_ZIP_MAX_MB", "256", "Size in MB of a ZIP download through a shared link at most.", "files"),
    _v("KALMIDO_FILE_REQUEST_MB_DAY", "1000", "MB per file request and day.", "files"),
    _v("KALMIDO_FORM_FILES_MB_HOUR", "200", "MB of files sent through public forms per hour.", "files"),
    _v("KALMIDO_FS_GC_EVERY", "86400", "Seconds between two clean-ups of moved files.", "files"),
    _v("KALMIDO_PAPERLESS_ZIP_DIR", "<data dir>/paperless-zip", "Folder of the Paperless export uploads while they are imported.", "files"),
    _v("KALMIDO_PAPERLESS_ZIP_MAX_MB", "4096", "Size in MB of one uploaded Paperless export.", "files"),
    _v("KALMIDO_FOLDERWATCH_DIR", "/app/folderwatch", "Folder with the folder watcher programs offered in the document settings (built by the image; 2.207.0).", "files"),
    _v("KALMIDO_PAPERLESS_ZIP_CHUNK_KB", "8192", "Size in KB of one upload part of a Paperless export.", "files"),

    # ---- backups and restore
    _v("KALMIDO_BACKUPS", "1", "Switch: automatic backups (the schedule is set in the app).", "backup"),
    _v("KALMIDO_BACKUP_DIR", "<data dir>/backups", "Folder of the backups.", "backup"),
    _v("KALMIDO_BACKUP_PASSPHRASE", "", "Passphrase that encrypts the backups.", "backup"),
    _v("KALMIDO_BACKUP_MAX_MB", "4096", "Size in MB of a backup that can be restored (upload and unpacked).", "backup"),
    _v("KALMIDO_BACKUP_TICK", "60", "Seconds between two looks at the backup schedule.", "backup"),
    _v("KALMIDO_BACKUP_PG_TIMEOUT", "21600", "Seconds one pg_dump / pg_restore run may take.", "backup"),
    _v("KALMIDO_OFFSITE_TIMEOUT", "120", "Seconds per network step of the off-site copy.", "backup"),
    _v("KALMIDO_OFFSITE_RETRY_S", "300", "Seconds before a failed off-site copy is tried again.", "backup"),
    _v("KALMIDO_ACCOUNT_IMPORT_MAX_MB", "4096", "Size in MB of an account move file that can be imported.", "backup"),
    _v("KALMIDO_ACCOUNT_IMPORT_MAX_ROWS", "500000", "Rows of one table in an account move file at most.", "backup"),
    _v("KALMIDO_BACKUP_ENCRYPT_REQUIRED", "0", "Switch: no backup without encryption (hosting; self-hosted installations keep working without it), 2.152.0.", "backup"),

    # ---- office
    _v("KALMIDO_PACKS_CATALOG", "", "Address of an online catalog of office packs (empty = only the built-in packs).", "office"),
    _v("KALMIDO_PACKS_ALLOW_HOSTS", "", "Internal hosts that catalog may live on.", "office"),

    # ---- integrations, calendars, webhooks
    _v("KALMIDO_API", "1", "Switch: the REST API (/api/v1) with access tokens.", "integrations"),
    _v("KALMIDO_API_RATE", "120", "API requests per token and minute.", "integrations"),
    _v("KALMIDO_PUBLIC_LINKS", "1", "Switch: public read-only links of lists.", "integrations"),
    _v("KALMIDO_WEBHOOKS", "1", "Switch: outgoing webhooks.", "integrations"),
    _v("KALMIDO_WEBHOOK_ALLOW_HOSTS", "", "Internal hosts webhooks may reach.", "integrations"),
    _v("KALMIDO_PEPPOL_ALLOW_HOSTS", "", "Internal hosts the own Peppol endpoint of any office area may reach (the calendar allow list counts only when an instance admin sets the endpoint, 2.306.0).", "integrations"),
    _v("KALMIDO_WEBHOOK_BACKOFF", "60,300,1800,7200", "Seconds between the retries of a failed webhook, comma-separated.", "integrations"),
    _v("KALMIDO_WEBHOOK_TICK", "5", "Seconds between two looks at the webhook queue.", "integrations"),
    _v("KALMIDO_HOOK_IN_PER_MIN", "60", "Incoming webhook calls per hook and minute.", "integrations"),
    _v("KALMIDO_HOOK_IN_PER_DAY", "1000", "Incoming webhook calls per hook and day.", "integrations"),
    _v("KALMIDO_CALDAV", "1", "Switch: the CalDAV server (/dav).", "integrations"),
    _v("KALMIDO_CALDAV_HTTP", "0", "Switch: allow CalDAV logins over plain http (only in a trusted network).", "integrations"),
    _v("KALMIDO_CALDAV_DONE_DAYS", "90", "Days completed tasks stay visible over CalDAV.", "integrations"),
    _v("KALMIDO_CALENDARS", "1", "Switch: calendar subscriptions (ICS / CalDAV).", "integrations"),
    _v("KALMIDO_CALENDAR_ALLOW_HOSTS", "", "Internal hosts calendar subscriptions may reach.", "integrations"),
    _v("KALMIDO_CALENDAR_MAX_MB", "10", "Size in MB of one calendar download.", "integrations"),
    _v("KALMIDO_CALENDAR_MAX_EVENTS", "5000", "Stored occurrences per subscription.", "integrations"),
    _v("KALMIDO_CALENDAR_RATE", "30", "Calendar adds, discoveries and manual refreshes per person in 15 minutes.", "integrations"),
    _v("KALMIDO_CALENDAR_REFRESH_GAP", "30", "Least seconds between two manual refreshes of one calendar.", "integrations"),
    _v("KALMIDO_CALENDAR_TICK", "60", "Seconds per minute of the refresh interval (tests use 1).", "integrations"),
    _v("KALMIDO_BOOKMARK_ALLOW_HOSTS", "", "Internal hosts bookmark previews may reach.", "integrations"),
    _v("KALMIDO_GIT_POLL", "180", "Seconds between two polls of a Git connection.", "integrations"),
    _v("KALMIDO_GIT_TICK", "15", "Seconds between two looks at which Git connection is due.", "integrations"),
    _v("KALMIDO_NTFYIN_TICK", "20", "Seconds between two rounds of the personal share inboxes.", "integrations"),
    _v("KALMIDO_IMPORT_MAX_MB", "20", "Size in MB of an import file (other task apps).", "integrations"),
    _v("KALMIDO_IMPORT_MAX_TASKS", "20000", "Tasks per import at most.", "integrations"),
    _v("KALMIDO_IMPORT_RATE", "30", "Imports and previews per person in 10 minutes.", "integrations"),
    _v("KALMIDO_ERROR_REPORTS_PER_HOUR", "30", "New error reports per hour.", "integrations"),

    # ---- agents and assistant
    _v("KALMIDO_AGENT_WAITERS", "6", "Agent connections waiting for events on the whole server at the same time.", "agents"),
    _v("KALMIDO_AGENT_EVENTS_STALE_H", "48", "Hours after which unread agent events count as stale.", "agents"),
    _v("KALMIDO_AGENT_CONTROL_NEW", "approve_all", "Control level a new agent starts with: approve_all, routine, free, or legacy (no level, works as before 2.235.0; the test containers use it).", "agents"),  # 2.235.0 A (#2891)
    _v("KALMIDO_AGENT_PUSH_DAY", "500", "Push notifications per agent and day.", "agents"),
    _v("KALMIDO_USAGE_DAYS", "400", "Days the agent usage records are kept.", "agents"),
    _v("KALMIDO_AUDIT_DAYS", "90", "Days the agent audit log is kept (0 = no log at all; the assistant log keeps only today's rows).", "agents"),
    _v("KALMIDO_TIDY_QUIET_S", "120", "Seconds a project must be quiet before its tidy agent is asked.", "agents"),
    _v("KALMIDO_DEPLOY_TAG", "deploy", "Tag that marks deploy gates of agents.", "agents"),
    _v("KALMIDO_STARTER_BASE", "https://github.com/Gegenschuss/kalmido/raw/v{version}/mcp/", "Download address of the agent starter files ({version} is replaced).", "agents"),
    _v("KALMIDO_AI_BASE_URL", "", "Address of an OpenAI-compatible service for the optional assistant (empty = assistant off); the assistant sends task texts to it.", "agents"),
    _v("KALMIDO_AI_KEY", "", "Key of that service.", "agents"),
    _v("KALMIDO_AI_KEY_FILE", "", "File that holds that key.", "agents"),
    _v("KALMIDO_AI_MODEL", "", "Model name of that service.", "agents"),
    _v("KALMIDO_AI_NAME", "", "Name of the assistant shown in the app (empty = the host).", "agents"),
    _v("KALMIDO_AI_TIMEOUT_S", "60", "Seconds per assistant call.", "agents"),
    _v("KALMIDO_AI_MAX_CHARS", "24000", "Characters of input text per assistant call.", "agents"),
    _v("KALMIDO_AI_MAX_TOKENS", "1500", "Answer tokens per assistant call.", "agents"),
    _v("KALMIDO_EMBED_URL", "", "Address of the optional embedding service (related tasks, meaning search; empty = off); task titles and descriptions are sent to it.", "agents"),
    _v("KALMIDO_EMBED_EXTERNAL", "0", "Switch: allow an embedding service on another host (task titles and descriptions go there).", "agents"),
    _v("KALMIDO_EMBED_IDLE", "15", "Seconds between two looks of the embedding pass when nothing waits.", "agents"),
    _v("KALMIDO_EMBED_BUSY", "2", "Seconds between two batches of a backlog.", "agents"),
    _v("KALMIDO_EMBED_DOWN", "60", "Seconds of pause after the embedding service failed.", "agents"),
    _v("KALMIDO_EMBED_CLEAN", "60", "Seconds between two clean-ups of the embeddings.", "agents"),
    _v("KALMIDO_RELATED_DUP", "0.96", "Similarity from which two tasks count as probable duplicates.", "agents"),
    _v("KALMIDO_RELATED_MIN", "0.90", "Lowest similarity of a related task.", "agents"),
    _v("KALMIDO_RELATED_SEARCH", "0.82", "Lowest similarity of a meaning search hit.", "agents"),
    _v("KALMIDO_RELATED_MIX", "nsum", "Order of the related tasks (how meaning and title similarity are mixed).", "agents"),
    _v("KALMIDO_RELATED_NORM", "0.84", "Normalisation point of the similarity for that order.", "agents"),

    # ---- background work and timing
    _v("TASKS_WATCHDOG", "1", "Switch: the background work of this process (reminders, backups, calendars, encryption pass). Helper processes set 0.", "workers"),
    _v("TASKS_WATCHDOG_INTERVAL", "30", "Seconds between two watchdog rounds (reminders, schedules).", "workers"),
    _v("KALMIDO_LOOP_LOCKS", "1", "Each background loop runs in one process of the instance; 0 = every process runs its loops.", "workers"),
    _v("KALMIDO_WORKER_HEARTBEAT", "30", "Seconds between two heartbeats of a background loop.", "workers"),
    _v("KALMIDO_STALE_HOUR", "09:00", "Local time from which the daily event about stale tasks goes out.", "workers"),
    _v("KALMIDO_ACCOUNT_IMPORT_PARALLEL", "2", "At most this many account checks / imports run at once on the whole server (2.148.1).", "workers"),

    # ---- hosting, retention and quotas
    _v("KALMIDO_HOSTED", "0", "Switch: a server run as a service for others; integrations may only reach public HTTPS addresses.", "hosting"),
    _v("KALMIDO_STORAGE_QUOTA_MB", "", "Storage per person in MB (empty / 0 = unlimited; admins can set it in the app).", "hosting"),
    _v("KALMIDO_SUPPORT_EMAIL", "", "Support address shown when the storage is full.", "hosting"),
    _v("KALMIDO_UPLOAD_HOURLY_MB", "1024", "Uploads per person and hour in MB (0 = no limit); over it uploads get 429.", "hosting"),  # 2.281.0 E (#3117)
    _v("KALMIDO_SUPPORT_URL", "", "Support page shown in Settings > Help.", "hosting"),
    _v("KALMIDO_PRIVACY_URL", "", "Address (http/https) of the operator's privacy statement, linked on the login page and in Settings > Help; the field in Administration > Server wins.", "hosting"),  # 2.306.0 B (#2887)
    _v("KALMIDO_IMPRINT_URL", "", "Address (http/https) of the operator's imprint (legal notice), linked like the privacy statement.", "hosting"),  # 2.306.0 B (#2887)
    _v("KALMIDO_OPERATOR_TOKEN_FILE", "", "File with the token of the hosting operator interface (empty = off).", "hosting"),
    _v("KALMIDO_TRASH_DAYS", "30", "Days items stay in the trash.", "hosting"),
    _v("KALMIDO_RETENTION_PURGE", "0", "Switch: really delete what is past its retention time (off = only count and report; the trash then says nothing is deleted). The installer writes 1 into a new .env.", "hosting"),  # 2.223.3 A (#2877)
    _v("KALMIDO_PURGE_TRASH", "", "Switch for the trash only; empty = KALMIDO_RETENTION_PURGE.", "hosting"),

    # ---- tests and development
    _v("KALMIDO_TEST_ROT_ABORT", "", "Tests: stop the key rotation right after the switch (1).", "test"),
    _v("KALMIDO_TEST", "0", "Switch: marks a test container (set by tests/start.sh); only then KALMIDO_TEST_NOW and KALMIDO_TEST_RATE_WINDOW_S work. Never on a real server.", "test"),
    _v("KALMIDO_TEST_NOW", "", "Test containers only (with KALMIDO_TEST=1): the server clock starts at this ISO time and runs on from there.", "test"),
    _v("KALMIDO_TEST_NOW_AT", "", "Test containers only: the real Unix second KALMIDO_TEST_NOW belongs to (app and worker share one shifted clock).", "test"),
    _v("KALMIDO_TEST_MODE", "0", "Test containers only: allows the test switches of the organisation key tool (1); left alone in a server's .env it is ignored.", "test"),
    _v("KALMIDO_TEST_FSREF", "0", "Test containers only (with KALMIDO_TEST=1): registers the test kind 'probe' of the folder references (2.199.0, files/fsref.py).", "test"),
    _v("KALMIDO_TEST_BK_ZIP_DELAY", "", "Test containers only (with KALMIDO_TEST=1): seconds the backup waits after its ZIP (2.281.0, #3118).", "test"),
    _v("KALMIDO_TEST_UMZ_END_DELAY", "", "Test containers only (with KALMIDO_TEST=1): seconds an account import's worker waits before it ends (2.308.0, #3261).", "test"),
    _v("KALMIDO_TEST_BK_IDLE_TX_MS", "", "Test containers only (with KALMIDO_TEST=1): idle-in-transaction limit of the backup's connection (2.281.0, #3118).", "test"),
    _v("KALMIDO_TEST_DUN_TICKS", "10", "Test containers only (with KALMIDO_TEST=1): watchdog intervals between two runs of the payment reminder suggestions (2.192.0).", "test"),
    _v("KALMIDO_SHEET_RANGE_BUDGET", "15000000", "Tests: range cells one evaluation of a table may read (2.148.1).", "test"),
    _v("KALMIDO_SHEET_CELLS_MAX", "1000000", "Tests: stored cells over all sheets of one table (2.148.1).", "test"),
    _v("KALMIDO_PEPPOL_STORECOVE_URL", "", "Tests: the address of a stand-in for the Storecove Peppol API (empty = the real one, 2.154.0).", "test"),
    _v("KALMIDO_AGENT_BURST_S", "60", "Seconds in which several new tasks of an agent count as one burst (one summary event).", "agents"),
    _v("KALMIDO_AGENT_BURST_QUIET_S", "15", "Seconds without more new tasks after which the burst summary of an agent is sent.", "agents"),
)

_BY = {v[0]: v for v in VARS}
_WARNED = set()


def env_default(name):
    """The documented default of a declared variable ("" for an unknown one)."""
    v = _BY.get(name)
    return v[1] if v else ""


def env_str(name, default=None):
    """The value without blanks around it; unset or empty = default (None: the registry's default)."""
    v = (os.environ.get(name) or "").strip()
    if v:
        return v
    return env_default(name) if default is None else default


def env_int(name, default, lo=None, hi=None):
    """A whole number; unset, empty or not a number = default; then clamped to lo / hi."""
    try:
        n = int((os.environ.get(name) or "").strip() or default)
    except ValueError:
        n = int(default)
    if lo is not None:
        n = max(lo, n)
    if hi is not None:
        n = min(hi, n)
    return n


def env_bool(name, default):
    """A switch: 1 / true / yes / on = True, 0 / false / no / off = False (any case); unset or empty = default; any other
    value = default and one warning in the log."""
    v = (os.environ.get(name) or "").strip().lower()
    if not v:
        return default
    if v in ON:
        return True
    if v in OFF:
        return False
    if name not in _WARNED:
        _WARNED.add(name)
        print(f"warning: {name}={v[:20]!r} is not a switch value (1/true/yes/on or 0/false/no/off): using the default "
              f"({'on' if default else 'off'})", file=sys.stderr, flush=True)
    return default
