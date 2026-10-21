"""Time helpers, the database connection, start-up checks and migrations (init_db, repair_data), settings storage.
2.37.0 (#1150): Postgres only; the driver layer is core/pg.py (placeholders, rows, pool, request context)."""
import json
import os
import re
import secrets
import tempfile
from datetime import datetime, timezone
from cryptography.hazmat.primitives.asymmetric import ec
from flask import g, has_request_context, jsonify, request
from werkzeug.security import generate_password_hash

from ..core.config import app, ATT_DIR, BOOT_NAME, BOOT_PROXY, BOOT_USER, DATABASE_URL, DB, NTFY_TOPIC, ONBOARDING_ENV, TZ
from ..core.config import APP_VERSION
from ..core.env import env_bool
from ..core.pg import (  # noqa: F401  (re-exported: the app imports the database API from here)
    Conn, DatabaseError, DataError, Error as DbError, IntegrityError, OperationalError, Row, UniqueViolation, connect_direct,
    connect_pooled, insert_id, like_escape, table_columns, table_exists, wait_ready, write_lock,
)
from ..core.schema import (
    GLOBAL_DEFAULTS, INDEXES, LIST_E2E_TRIGGER, WIKI_E2E_TRIGGER, MIGRATIONS, SCHEMA, SCHEMA_VERSION, TIME_TITLE_TRIGGER, USER_DEFAULTS,
)
from ..core.i18n import LANGS, tr


# 2.48.0 (#1207): modules of 2.48 that are on for everyone once (features_rev 11)
FEATS_2480 = ("files", "docs")  # 2.48.0 (#1207, #1111): the file store and the documents, on for everyone once


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def iso_ms(dt):
    """Timeline timestamps (comments, activity): milliseconds keep their order within one second."""
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def parse_iso(s):
    return datetime.fromisoformat(s)


def local_now():
    return datetime.now(TZ)


def local_day(ts):
    """The local day (server time zone) of a stored UTC timestamp; None for an empty or unreadable one. 2.21.0 (#671):
    the one tolerant version for statistics and the milestone report (a damaged row is left out instead of failing)."""
    if not ts:
        return None
    try:
        d = parse_iso(ts)
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(TZ).date()
    except (ValueError, TypeError, OverflowError):
        return None


def db():
    """The request's connection (from the pool; context "system" until authenticate() sets the person, see set_ctx)."""
    if "db" not in g:
        g.db = connect()
    return g.db


def connect():
    """A pooled connection with context "system": background threads, start-up, the CLI. close() gives it back."""
    if not DATABASE_URL:
        raise DataDirError(_no_url())
    return connect_pooled(DATABASE_URL)


def _no_url():
    print("FATAL: DATABASE_URL is not set. From 2.37 on Kalmido stores its data in Postgres: add the database service to "
          "docker-compose.yml (see the template in the repository), set POSTGRES_PASSWORD in .env and "
          "DATABASE_URL=postgresql://kalmido:<password>@db/kalmido, then start again.", flush=True)
    return 3


@app.errorhandler(DbError)
def db_error(e):
    """2.37.0 (#1150): a database error nobody caught. Postgres is strict where SQLite stored anything: a value of the wrong
    type (DataError) or a broken constraint (IntegrityError) is the client's input -> 400 instead of a crash; anything else
    stays a 500 (Flask logs it as before). The request's transaction is aborted either way: roll it back so after-request
    hooks can still use the connection. /api/v1 and /dav keep their own error formats."""
    c = g.get("db")
    if c is not None:
        try:
            c.rollback()
        except Exception:  # noqa: BLE001  (the connection itself may be gone)
            pass
    denied = getattr(e, "sqlstate", None) == "42501"  # 2.37.0 (review K2-1): InsufficientPrivilege, e.g. a row-level
    if not denied and not isinstance(e, (DataError, IntegrityError)):  # security policy stopped a write the app let through
        raise e
    import traceback
    code = 403 if denied else 400
    path = re.sub(r"^(/api/hooks/(?:issues|deploy)/[0-9]+/)[^/]+", r"\1***", request.path)  # 2.126.0 B (#1979 I8): no hook token in the log; 2.138.4 (#2381): the deploy hook too
    print(f"database error ({code}) {request.method} {path}:\n" + "".join(traceback.format_exception(e)).rstrip(), flush=True)
    if denied:  # the second floor caught what an app check missed: the admins hear it (security alerts)
        from ..notify.alerts import aa_count
        try:
            who = g.user["username"]
        except Exception:  # noqa: BLE001  (no user, or a public actor without a name)
            who = "?"
        aa_count("security", "rls", f"{request.method} {request.url_rule.rule if request.url_rule else request.path}"[:120],
                 user=who)
    msg = tr("no permission") if denied else tr("Invalid data")
    if request.path.startswith("/api/v1/"):
        from ..api.v1 import v1_err
        return v1_err(code, msg)
    if request.path == "/dav" or request.path.startswith("/dav/"):
        from flask import Response
        return Response(msg + "\n", code, content_type="text/plain; charset=utf-8")
    return err(msg, code)


@app.teardown_appcontext
def close_db(_):
    c = g.pop("db", None)
    if c is not None:
        c.close()


def random_topic():
    return "kalmido-" + secrets.token_urlsafe(9).replace("_", "").replace("-", "").lower()


def default_uid(c):
    """First enabled admin (owner of the migrated single-user data, target of env defaults)."""
    r = c.execute("SELECT id FROM users WHERE is_admin=1 AND disabled=0 ORDER BY id LIMIT 1").fetchone() \
        or c.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
    return r[0] if r else None


def ensure_inbox(c, uid):
    """2.15.0 (#632): a new inbox is named in its owner's language ("Inbox", "Eingang", "Boîte de réception" ...); every
    default name (inbox_default) is still shown in the viewer's language, a renamed inbox keeps its name."""
    if not c.execute("SELECT 1 FROM lists WHERE is_inbox=1 AND owner_id=?", (uid,)).fetchone():
        r = c.execute("SELECT value FROM user_settings WHERE user_id=? AND key='lang'", (uid,)).fetchone()
        c.execute("INSERT INTO lists(name,is_inbox,sort,created_at,owner_id) VALUES(?,1,-1,?,?)",
                  (tr("Basket", lg=r[0] if r and r[0] in LANGS else "en"), iso(now_utc()), uid))


def inbox_names():
    """Every default name of an inbox: "Eingang" (before 2.15), "Inbox" in each language (2.15 - 2.39.0) and since 2.39.1
    (#1219) "Basket" in each language."""
    if "n" not in _INBOX_NAMES:
        _INBOX_NAMES["n"] = sorted(KB_LEGACY_INBOX_NAMES | {tr("Basket", lg=k) for k in LANGS})
    return _INBOX_NAMES["n"]


_INBOX_NAMES = {}
# 2.39.1 (#1219): the inbox names before the rename to "Basket" (the old translations of "Inbox"), still default names
KB_LEGACY_INBOX_NAMES = frozenset({"Eingang", "Inbox", "Boîte de réception", "Bandeja de entrada", "In arrivo"})


def inbox_default(name):
    return name in inbox_names()


def adopt_orphans(c, uid):
    """Rows from the single-user era (no owner) belong to uid. Idempotent (only NULL owners)."""
    n = c.execute("UPDATE lists SET owner_id=? WHERE owner_id IS NULL", (uid,)).rowcount
    n += c.execute("UPDATE tasks SET created_by=? WHERE created_by IS NULL", (uid,)).rowcount
    for t in ("habits", "pomos", "filters"):
        n += c.execute(f"UPDATE {t} SET user_id=? WHERE user_id IS NULL", (uid,)).rowcount
    n += c.execute("UPDATE task_tags SET user_id=? WHERE user_id=0", (uid,)).rowcount
    return n


def create_user(c, username, display_name="", password=None, proxy_login=None, is_admin=False,
                ntfy_topic=None, seed_global=False, drop_token=None, paperless_access=None, onboard=False):
    """Inserts a user with settings (+ inbox unless the caller adopts an existing one). Returns the id.
    Paperless access defaults to admins only."""
    pl = is_admin if paperless_access is None else paperless_access
    # 2.138.0 C (#1907): no upload token until the person creates one (shown once); a seeded one (TASKS_DROP_TOKEN) as hash
    from ..core.tokenhash import tkh_hash
    uid = insert_id(c, """INSERT INTO users(username,display_name,password_hash,proxy_login,is_admin,drop_token_hash,drop_token_at,
                                         created_at,paperless_access) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (username, display_name or username, generate_password_hash(password) if password else None,
                     proxy_login or None, 1 if is_admin else 0, tkh_hash(drop_token), iso(now_utc()) if drop_token else None,
                     iso(now_utc()), 1 if pl else 0))
    vals = dict(USER_DEFAULTS)
    # chosen in the first-run setup ("What do you want to use?"): modules + language of new users
    for k, gk in (("features", "default_features"), ("lang", "default_lang")):
        v = gsetting(c, gk)
        if v:
            vals[k] = v
    vals["show_done_default"] = "0"  # 2.49.0 (#1535): a NEW account starts with completed tasks hidden (existing accounts keep their choice)
    if seed_global:  # the single-user settings become this user's settings
        for r in c.execute("SELECT key, value FROM settings"):
            if r["key"] in USER_DEFAULTS:
                vals[r["key"]] = r["value"]
    if ntfy_topic is not None:
        vals["ntfy_topic"] = ntfy_topic
    if onboard and ONBOARDING_ENV:  # new account (setup / user admin): sample list + welcome tour on first start
        vals["tour"] = vals["onboard"] = "pending"
    if onboard and not seed_global and not is_admin:  # 2.25.0 (UX-26): people who are added start with a lean sidebar
        vals["sidebar"] = json.dumps({"order": [], "hidden": ["e:tomorrow", "e:week", "e:doable"]})
    if not vals["ntfy_topic"]:
        vals["ntfy_topic"] = random_topic()
    for k, v in vals.items():
        c.execute("INSERT INTO user_settings(user_id,key,value) VALUES(?,?,?) "
                  "ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value", (uid, k, v))
    # 2.46.0 (#1562): a new account joins no organisation by itself -- only by its e-mail domain, an invitation or the
    # admin who creates it (the callers)
    return uid


def feats8(c, uid, fs):
    """features_rev 8: "deps" / "fields" are switched on for a user who already has such data (dependencies of
    tasks in lists they can see / custom fields of those lists) or uses the timeline or project progress, so
    nothing disappears; everyone else follows the instance default (the setup's choice, else on)."""
    from ..core.access import vis_sql
    fs = list(fs)
    dflt = [x for x in (gsetting(c, "default_features") or USER_DEFAULTS["features"]).split(",") if x]
    vis = vis_sql()
    has = {"deps": bool(c.execute(f"""SELECT 1 FROM task_deps d JOIN tasks t ON t.id=d.task_id
                                      WHERE t.list_id IN {vis} OR d.created_by=? LIMIT 1""", (uid, uid, uid)).fetchone()),
           "fields": bool(c.execute(f"SELECT 1 FROM list_fields WHERE list_id IN {vis} LIMIT 1", (uid, uid)).fetchone())}
    for f in ("deps", "fields"):
        if f not in fs and (has[f] or "timeline" in fs or "progress" in fs or f in dflt):
            fs.append(f)
    return fs


# 2.0.0 (#279): never start over on top of existing data. The data dir gets a marker on the first start (and on the first
# start of 2.0 of an existing install); when the marker, attachments or backups are there but tasks.db is missing, empty,
# unreadable or damaged (e.g. I/O errors of a failing disk), the app REFUSES to start instead of creating a fresh, empty
# database -- whose first visitor would become the admin. A new database is only created in a data dir without any data.
DATA_MARKER = os.path.join(os.path.dirname(os.path.abspath(DB)), ".kalmido-initialized")


class DataDirError(SystemExit):
    pass


def _has_files(d):
    try:
        for _root, _dirs, files in os.walk(d):
            if files:
                return True
    except OSError:
        return True  # cannot even list it: treat as "there is something" (never start empty)
    return False


def startup_guard():
    """Raises DataDirError (exit code 3) when the database must not be (re)created or opened; returns True when this is a
    genuinely new install (an empty database and a data dir without Kalmido data), False for an existing database.
    2.37.0 (#1150): Postgres. Refused: no DATABASE_URL; the database unreachable; an empty database next to a data dir that
    holds Kalmido data (the marker, attachments, backups) or a SQLite database from before 2.37 that was not moved yet."""
    from ..admin.backup import BK_DIR
    if not DATABASE_URL:
        raise DataDirError(_no_url())
    try:
        wait_ready(DATABASE_URL, int(os.environ.get("KALMIDO_DB_WAIT", "60")))
        c = connect_direct(DATABASE_URL)
        try:
            has_tables = table_exists(c, "users")
            meta = dict(c.execute("SELECT key, value FROM kalmido_meta WHERE key IN ('schema_version','app_version',"
                                  "'app_version_prev')").fetchall()) if has_tables and table_exists(c, "kalmido_meta") else {}
            r = (meta["schema_version"],) if "schema_version" in meta else None
        finally:
            c.close()
    except DbError as e:
        print(f"FATAL: the database cannot be reached or read ({str(e).strip()[:300]}). Check DATABASE_URL and the database "
              "service, then start again.", flush=True)
        raise DataDirError(3) from None
    try:
        have = int(r[0]) if r else 0
    except (TypeError, ValueError):
        have = 0
    if have > SCHEMA_VERSION:  # 2.37.0 (#1150): an older image on a database a newer version already migrated
        print(f"FATAL: database schema {have} is newer than this version ({SCHEMA_VERSION}); start the matching or a newer "
              "image.", flush=True)
        raise DataDirError(3)
    appver_guard(meta.get("app_version"), meta.get("app_version_prev"))
    if has_tables:
        secret_new_guard()
    from ..admin.migrate import mig_startup
    if mig_startup(has_tables):  # 2.37.0 (#1150): the tasks.db of 2.36 next to an empty database was moved over just now
        return False
    if has_tables:
        return False
    data = [p for p, ok in ((DATA_MARKER, os.path.exists(DATA_MARKER)), (ATT_DIR, _has_files(ATT_DIR)),
                            (BK_DIR, _has_files(BK_DIR))) if ok]
    try:
        old = os.path.exists(DB) and os.path.getsize(DB) > 0
    except OSError:
        old = True
    if old or data:
        what = f"a SQLite database from before 2.37 ({DB})" if old else f"Kalmido data ({', '.join(data)})"
        print(f"FATAL: the Postgres database is empty, but the data dir holds {what}. Refusing to start so that no new, empty "
              "database replaces it. Point DATABASE_URL at the database of this install (or move the old data first), "
              "then start again.", flush=True)
        raise DataDirError(3)
    return True


def appver_parse(v):
    """2.149.0 D (#2509): "x.y.z" -> (x, y, z); None for anything else (missing, "0.0.0" of a checkout without VERSION)."""
    m = re.fullmatch(r"(\d{1,4})\.(\d{1,4})\.(\d{1,4})", str(v or "").strip())
    t = tuple(int(x) for x in m.groups()) if m else None
    return t if t and t != (0, 0, 0) else None


def appver_newer_minor(other, mine=None):
    """2.149.0 D (#2509): True when the version other belongs to a newer minor (or major) release than mine (this image).
    Patch versions of the same minor never count as newer."""
    o, m = appver_parse(other), appver_parse(APP_VERSION if mine is None else mine)
    return bool(o and m and o[:2] > m[:2])


def appver_check(stored, prev, mine=None):
    """2.149.0 D (#2509): may this image start on a database stamped with app_version stored (the newest version that
    ran on it) and app_version_prev prev (the version that ran before the last upgrade)? "ok", "back" (the one step
    back to the previous version: the automatic rollback of an update, an operator who keeps the previous image) or
    "newer" (an older image on a database a newer minor already ran on: refused unless KALMIDO_ALLOW_DOWNGRADE).
    Patches of one minor never block each other."""
    if not appver_newer_minor(stored, mine):
        return "ok"
    p, m = appver_parse(prev), appver_parse(APP_VERSION if mine is None else mine)
    return "back" if p and m and m[:2] >= p[:2] else "newer"  # any patch of the previous minor


def appver_guard(stored, prev):
    """2.149.0 D (#2509): the start check (startup_guard). Raises DataDirError (exit code 3) for "newer"."""
    v = appver_check(stored, prev)
    if v == "back":
        print(f"note: this database last ran Kalmido {stored}; starting {APP_VERSION} (the version before it) as a step back. "
              "Its newer columns and tables stay untouched.", flush=True)
    elif v == "newer":
        if env_bool("KALMIDO_ALLOW_DOWNGRADE", False):
            print(f"WARNING: this database last ran Kalmido {stored}, a newer version than {APP_VERSION}; starting anyway "
                  "(KALMIDO_ALLOW_DOWNGRADE). Older code may not understand newer data: go back to the newer image soon.",
                  flush=True)
        else:
            print(f"FATAL: this database last ran Kalmido {stored}, a newer version than this image ({APP_VERSION}). An older "
                  f"version may damage data it does not know. Start the image of {stored} or newer (or restore a backup "
                  "made with this version). Emergency only: KALMIDO_ALLOW_DOWNGRADE=1.", flush=True)
            raise DataDirError(3)


def secret_new_guard():
    """2.149.0 D (#2510): a key file created during THIS start never meets a database that already holds organisation or
    account keys (they were sealed with another server key): the new file is removed again and the start is refused."""
    from . import config
    from .pg import system_ctx as pg_system_ctx
    if not config.SECRET_KEY_NEW:
        return
    try:
        c = connect_direct(DATABASE_URL)
        try:
            n = 0
            for t in ("org_keys", "user_keys"):
                if table_exists(c, t):
                    with pg_system_ctx(c):
                        n += c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        finally:
            c.close()
    except DbError:
        n = 1  # cannot tell: never risk a new key on sealed data
    if not n:
        return
    try:
        os.remove(config.SECRET_FILE)
    except OSError:
        pass
    print(f"FATAL: a new server key would have been created in {config.SECRET_FILE}, but this database holds data sealed "
          "with another server key. Put the old key back (the key file or KALMIDO_SECRET_KEY) and start again. Lost for good? "
          "See SELF-HOSTING.md (set a new KALMIDO_SECRET_KEY yourself, then rewrap with the recovery keys).", flush=True)
    raise DataDirError(3)


def secret_need_guard(new):
    """2.149.0 D (#2510): a NEW install does not start without a server key (its data would stay unencrypted without
    anyone deciding it); KALMIDO_NO_SECRET_KEY=1 allows it (tests, demos). Existing installs only get the warning."""
    from . import config
    if not new or config.SECRET_KEY or env_bool("KALMIDO_NO_SECRET_KEY", False):
        return
    why = {"file_in_data": "the key file lies inside the data or backup folder",
           "invalid": "the key is not valid (32 bytes, base64)",
           "file_error": f"the key file {config.SECRET_FILE} cannot be read or written"}.get(config.SECRET_KEY_PROBLEM,
                                                                                               "no key is set")
    print(f"FATAL: no server key ({why}). Set KALMIDO_SECRET_KEY (openssl rand -base64 32) or KALMIDO_SECRET_FILE on its "
          "own volume (the image uses /secret/kalmido.key when a volume is mounted at /secret). Without a key organisation "
          "data is not encrypted; to start like that anyway set KALMIDO_NO_SECRET_KEY=1.", flush=True)
    raise DataDirError(3)


def data_dir_check():
    """2.149.0 D (#2510): the data dir must exist and be writable (a bind mount Docker created as root is not): a clear
    message instead of a traceback."""
    d = os.path.dirname(os.path.abspath(DB))
    try:
        os.makedirs(d, exist_ok=True)
        os.makedirs(ATT_DIR, exist_ok=True)
        fd, probe = tempfile.mkstemp(prefix=".kalmido-write-", dir=d)
        os.close(fd)
        os.remove(probe)
    except OSError as e:
        uid = os.getuid() if hasattr(os, "getuid") else "?"
        gid = os.getgid() if hasattr(os, "getgid") else "?"
        print(f"FATAL: the data folder {d} is not writable for this process (uid {uid}): {e.strerror or e}. On the host: "
              f"mkdir -p data secret && sudo chown {uid}:{gid} data secret (the folders next to docker-compose.yml), then "
              "start again.", flush=True)
        raise DataDirError(3) from None


def appver_stamp(c):
    """2.149.0 D (#2509): after a successful start (inside the init transaction): kalmido_meta.app_version = the newest
    version that ran on this database, app_version_prev = the one that ran before the last upgrade. A step back (an older
    image, same or older minor) changes nothing, so the next upgrade works as before."""
    mine = appver_parse(APP_VERSION)
    if not mine:
        return
    r = c.execute("SELECT value FROM kalmido_meta WHERE key='app_version'").fetchone()
    have = appver_parse(r[0]) if r else None
    if have and have >= mine:
        return
    if have:
        c.execute("INSERT INTO kalmido_meta(key,value) VALUES('app_version_prev',?) ON CONFLICT(key) DO UPDATE SET "
                  "value=excluded.value", (r[0],))
    c.execute("INSERT INTO kalmido_meta(key,value) VALUES('app_version',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
              (APP_VERSION,))


def mig_ids():
    """2.102.0 D (#1996): (id, table, column, ddl) per MIGRATIONS step; id = "table.column", the n-th step of the same column
    "table.column#n" -- stable wherever a release inserts its steps."""
    seen, out = {}, []
    for table, col, ddl in MIGRATIONS:
        k = f"{table}.{col}"
        seen[k] = seen.get(k, 0) + 1
        out.append((k if seen[k] == 1 else f"{k}#{seen[k]}", table, col, ddl))
    return out


def mig_apply(c):
    """2.102.0 D (#1996): runs the MIGRATIONS steps whose column is missing and records every step in kalmido_migrations
    ("applied", or "present" for a column that existed already: every database before 2.102 on its first start, or one an
    older version added after a rollback). The column check stays the judge -- one catalog read per start -- so a recorded
    step whose column is gone again (a hand-made change, a partial restore) runs again ("again") instead of failing later.
    Returns (applied, recorded as present)."""
    done = {r[0] for r in c.execute("SELECT id FROM kalmido_migrations").fetchall()}
    have = {}
    for t, col in c.execute("SELECT table_name, column_name FROM information_schema.columns "
                            "WHERE table_schema=current_schema()").fetchall():
        have.setdefault(t, set()).add(col)
    at, n, m = iso(now_utc()), 0, 0
    for mid, table, col, ddl in mig_ids():
        if col not in have.get(table, ()):
            c.execute(ddl)
            n += 1
            c.execute("INSERT INTO kalmido_migrations(id,applied_at,note) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET "
                      "applied_at=excluded.applied_at, note=excluded.note", (mid, at, "again" if mid in done else "applied"))
        elif mid not in done:
            m += 1
            c.execute("INSERT INTO kalmido_migrations(id,applied_at,note) VALUES(?,?,'present') ON CONFLICT DO NOTHING", (mid, at))
    if n:
        print("migrations:", n, "step(s) applied", flush=True)
    return n, m


def mig_flags_sync(c, before=None):
    """2.102.0 D (#1996): the one-shot data migrations (settings flags migr_* = "1") are recorded in kalmido_migrations as
    "flag:migr_*" too. The settings flag stays the switch that is read and written: an older version (rollback) reads it and
    runs nothing twice, and deleting the flag still repeats a one-shot (then its row gets the new time). Called before the
    one-shots (returns the flags set then) and after them with that set."""
    flags = {r[0] for r in c.execute("SELECT key FROM settings WHERE key ILIKE 'migr\\_%' ESCAPE '\\' AND value='1'").fetchall()}
    at = iso(now_utc())
    for k in sorted(flags):
        if before is None or k in before:
            c.execute("INSERT INTO kalmido_migrations(id,applied_at,note) VALUES(?,?,'one-shot') ON CONFLICT DO NOTHING", ("flag:" + k, at))
        else:  # ran during this start (new, or repeated after its flag was deleted)
            c.execute("INSERT INTO kalmido_migrations(id,applied_at,note) VALUES(?,?,'one-shot') ON CONFLICT(id) DO UPDATE SET "
                      "applied_at=excluded.applied_at", ("flag:" + k, at))
    return flags


def init_db(guard=True, load=None):
    """load: admin/migrate.py -- load(c) copies an old SQLite database inside this transaction, after the tables and columns
    exist and before the one-shot data migrations, triggers, indexes and row-level security."""
    from ..core.access import _COLLAB_ALL, _TIME_ALL
    from ..lists.lists import folder_path_migration
    from ..lists.projects import ms_migrate
    from ..notify.push import _b64u, _vapid_load
    from ..agents.core import tidy_agent_of
    if guard:  # 2.149.0 D (#2510): a clear message for a data folder without write access
        data_dir_check()
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    if guard:  # a restore checked its database itself (and must never exit the process)
        secret_need_guard(startup_guard())  # 2.149.0 D (#2510): a new install needs a server key
    os.makedirs(ATT_DIR, exist_ok=True)
    # 2.37.0 (#1150): one transaction for the schema, the additive migrations and the one-shot data migrations (Postgres has
    # transactional DDL); an advisory lock keeps two starting containers apart (was BEGIN IMMEDIATE)
    c = connect_direct(DATABASE_URL)
    try:
        c.execute("SET LOCAL statement_timeout = 0")  # big migrations / index builds (and waiting for another starting container)
        write_lock(c, "kalmido-init")
        for ext in ("unaccent", "pg_trgm"):  # message search (collab/msgsearch.py); both ship with the postgres image
            c.execute(f"CREATE EXTENSION IF NOT EXISTS {ext}")
        c.executescript(SCHEMA)
        flags0 = mig_flags_sync(c)  # 2.102.0 D (#1996): the one-shots done before this start (recorded if not yet)
        mig_apply(c)  # 2.102.0 D (#1996): only the MIGRATIONS steps not yet recorded in kalmido_migrations
        if load is not None:
            load(c)  # 2.37.0 (#1150): the move from SQLite (migrate-sqlite)
        # 2.10.0 (#441): member rows from before groups (or written by a path that sets no own_role) are personal shares
        c.execute("UPDATE list_members SET own_role=role WHERE own_role IS NULL AND grole IS NULL")
        c.execute("CREATE INDEX IF NOT EXISTS tasks_agroup ON tasks(assignee_group_id) WHERE assignee_group_id IS NOT NULL")
        c.execute("DROP INDEX IF EXISTS tasks_tt")  # tt_id is unique per user now (tasks_tt_user)
        c.executescript(TIME_TITLE_TRIGGER)
        c.executescript(LIST_E2E_TRIGGER)  # 2.64.1 (#1817): members of lists with the lock
        c.executescript(WIKI_E2E_TRIGGER)  # 2.64.3 (#1817): members of organisations whose knowledge space has the lock
        from ..tasks.delta import dl_setup
        dl_setup(c)  # 2.42.0 (#1376): the change triggers of the delta state
        from ..core.access import acx_gen_setup
        acx_gen_setup(c)  # 2.149.0 C (#2508): membership changes renew the generation the access-context cache checks
        from ..tasks.multilist import ml_setup
        ml_setup(c)  # 2.71.0 B (#1459): links never cross a workspace boundary
        for stmt in INDEXES.strip().split(";"):
            if stmt.strip():
                c.execute(stmt)
        from ..life.rss import rg4_feed_unique
        rg4_feed_unique(c)  # 2.122.4 A (#1906): one followed feed per address (skipped while old duplicates exist)
        from ..core.tokenhash import tkh_migrate
        tkh_migrate(c)  # 2.138.0 C (#1907): plain upload / calendar tokens become hashes
        from ..office.ledger import ofx_migrate
        ofx_migrate(c)  # 2.36.2 (#1142, E): office positions carry their organisation
        from ..office.contacts_cl import fk_migrate
        fk_migrate(c)  # 2.40.0 (#1380): the contact field of a client becomes its default contact person
        from ..office.model import fe_office_rules_migrate
        fe_office_rules_migrate(c)  # 2.40.0 (#1379): producing / raw data stay on where they are used
        from ..office.costs import ek_producing_migrate
        ek_producing_migrate(c)  # 2.47.0 (#1645): producing per document, older documents keep how they compute
        for k, v in GLOBAL_DEFAULTS.items():
            c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT DO NOTHING", (k, v))
        from ..admin.hosting import quota_backfill
        quota_backfill(c)  # 2.24.0 (#910): who uploaded the files from before
        from ..accounts.colors import ac_assign
        ac_assign(c)  # 2.47.1 (#1721): the accounts from before get their fixed colour (agents first)
        _COLLAB_ALL["on"] = gsetting(c, "collab_all") != "0"
        _TIME_ALL["on"] = gsetting(c, "time_all") != "0"
        # migration of a single-user install: its data belongs to the bootstrap admin
        if not c.execute("SELECT 1 FROM users").fetchone():
            has_data = (c.execute("SELECT COUNT(*) FROM lists").fetchone()[0] > 1
                        or c.execute("SELECT 1 FROM tasks").fetchone() or c.execute("SELECT 1 FROM habits").fetchone()
                        or c.execute("SELECT 1 FROM filters").fetchone() or c.execute("SELECT 1 FROM pomos").fetchone())
            if has_data:
                legacy_topic = (c.execute("SELECT value FROM settings WHERE key='ntfy_topic'").fetchone() or [""])[0]
                uid = create_user(c, BOOT_USER, BOOT_NAME, None, BOOT_PROXY, True,
                                  ntfy_topic=legacy_topic or NTFY_TOPIC or None, seed_global=True,
                                  drop_token=os.environ.get("TASKS_DROP_TOKEN") or None)
                n = adopt_orphans(c, uid)
                print(f"multi-user migration: created user {BOOT_USER!r} (id {uid}), adopted {n} rows", flush=True)
        first = default_uid(c)
        if first:
            n = adopt_orphans(c, first)
            if n:
                print("adopted", n, "ownerless rows for user", first, flush=True)
            if NTFY_TOPIC:  # env topic seeds the first admin's topic when it is still empty
                c.execute("UPDATE user_settings SET value=? WHERE user_id=? AND key='ntfy_topic' AND value=''",
                          (NTFY_TOPIC, first))
        # list types (package D2, once): checklists stay checklists; lists that already hold project data (time entries,
        # dependencies, custom fields or values, a project status; time only from 5 minutes tracked in total, so a
        # misclicked timer of a few seconds does not turn a household list into a project) become projects; the rest: list
        if gsetting(c, "migr_kind") != "1":
            c.execute("UPDATE lists SET kind='checklist' WHERE checklist=1")
            n = c.execute("""UPDATE lists SET kind='project' WHERE checklist=0 AND (
                               id IN (SELECT list_id FROM time_entries WHERE list_id IS NOT NULL
                                      GROUP BY list_id HAVING SUM(seconds) >= 300)
                               OR id IN (SELECT t.list_id FROM task_deps d JOIN tasks t ON t.id=d.task_id)
                               OR id IN (SELECT t.list_id FROM task_deps d JOIN tasks t ON t.id=d.blocker_id)
                               OR id IN (SELECT list_id FROM list_fields)
                               OR id IN (SELECT t.list_id FROM task_field_values v JOIN tasks t ON t.id=v.task_id)
                               OR status!='')""").rowcount
            gset(c, "migr_kind", "1")
            print("list types:", n, "lists with project data became projects", flush=True)
        # 2.7.2 (#414), once: the type "checklist" is gone; such lists become plain lists with "Show completed at the
        # bottom" on (the column checklist stays 1), so nothing changes for their items
        if gsetting(c, "migr_kind272") != "1":
            n = c.execute("UPDATE lists SET kind='list', checklist=1 WHERE kind='checklist'").rowcount
            gset(c, "migr_kind272", "1")
            if n:
                print("list types:", n, "checklists became lists with 'Show completed at the bottom'", flush=True)
        # 2.41.0 (#1471), once: time tracking became a switch of each list (default off); every list that already holds time
        # entries gets it on, so no list loses its timer or its tracked time
        if gsetting(c, "migr_time241") != "1":
            n = c.execute("UPDATE lists SET time_tracking=1 WHERE time_tracking=0 AND id IN "
                          "(SELECT DISTINCT list_id FROM time_entries WHERE list_id IS NOT NULL)").rowcount
            gset(c, "migr_time241", "1")
            if n:
                print("time tracking:", n, "lists with time entries keep it (switched on)", flush=True)
        # features_rev 8: the setup's default modules (from before 1.2) get "deps" / "fields" like the users below
        dfs = gsetting(c, "default_features")
        if dfs and gsetting(c, "migr_feat8") != "1":
            d = [x for x in dfs.split(",") if x]
            d += [f for f in ("deps", "fields") if f not in d and ("timeline" in d or "progress" in d)]
            gset(c, "default_features", ",".join(d))
        gset(c, "migr_feat8", "1")
        # features_rev 9 (2.0.6): comments became a module of their own, on by default (also in the setup's default)
        if dfs and gsetting(c, "migr_feat9") != "1":
            d = [x for x in (gsetting(c, "default_features") or "").split(",") if x]
            if "comments" not in d:
                gset(c, "default_features", ",".join(d + ["comments"]))
        gset(c, "migr_feat9", "1")
        # features_rev 10 (2.21.0, #659 / #658): events and contacts are modules of their own, on by default
        if dfs and gsetting(c, "migr_feat10") != "1":
            d = [x for x in (gsetting(c, "default_features") or "").split(",") if x]
            gset(c, "default_features", ",".join(d + [f for f in ("events", "contacts") if f not in d]))
        gset(c, "migr_feat10", "1")
        # features_rev 11 (2.48.0, #1207): the new modules of 2.48 in the setup's default too
        if dfs and gsetting(c, "migr_feat11") != "1":
            d = [x for x in (gsetting(c, "default_features") or "").split(",") if x]
            gset(c, "default_features", ",".join(d + [f for f in FEATS_2480 if f not in d]))
        gset(c, "migr_feat11", "1")
        # 2.22.0 (#752), once: one organisation (named after the instance's domain, e.g. kalmido.example.com -> "Example")
        # with every account (agents too); people see only people of their organisations
        if gsetting(c, "migr_orgs2220") != "1":
            from ..accounts.orgs import INSTANCE_ENV
            # 2.46.0 (#1592): only an existing instance from before 2.22 (accounts, no organisation); a new one starts without
            if not c.execute("SELECT 1 FROM orgs WHERE personal_of IS NULL").fetchone() and INSTANCE_ENV != "shared" and c.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                from ..core.config import PUBLIC_URL
                host = PUBLIC_URL.split("://", 1)[-1].split("/")[0].split(":")[0]
                parts = [p for p in host.split(".") if p and not p.isdigit()]
                name = (parts[-2] if len(parts) >= 2 else (parts[0] if parts else "Kalmido")).capitalize()
                oid = insert_id(c, "INSERT INTO orgs(name,icon,created_at) VALUES(?,?,?)", (name, "", iso(now_utc())))
                c.execute("INSERT INTO org_members(org_id,user_id) SELECT ?, id FROM users WHERE true ON CONFLICT DO NOTHING", (oid,))
                if gsetting(c, "people_visibility") in (None, ""):
                    gset(c, "people_visibility", "org")
                print("organisations:", name, "with every account", flush=True)
            gset(c, "migr_orgs2220", "1")
        from ..accounts.orgs import instance_sync, ws_migrate
        instance_sync(c)  # 2.46.0 (#1592): only the hint on a former mode setting
        ws_migrate(c)  # 2.28.0 (#935), once: every list and agent gets its workspace
        from ..accounts.tenancy import ws_migrate_objs
        ws_migrate_objs(c)  # 2.30.0 (#1036), once: every calendar and address book gets its workspace
        if gsetting(c, "migr_listen2300") != "1":  # 2.30.0 (#1034), once: "listens in" keeps who listened before
            from ..agents.core import listen_migrate
            n = listen_migrate(c)
            gset(c, "migr_listen2300", "1")
            if n:
                print("agents listening in:", n, "lists written explicitly", flush=True)
        # 2.22.0 (#740), once: lists shared before go into the folder of the same name as with their owner (created when
        # missing) -- only where the person has not put the list into a folder of their own
        if gsetting(c, "migr_folders2220") != "1":
            from ..lists.lists import member_folder_adopt
            n = sum(1 for r in c.execute("""SELECT m.list_id, m.user_id FROM list_members m JOIN lists l ON l.id=m.list_id
                                            WHERE COALESCE(m.folder,'')='' AND l.folder!=''""").fetchall() if member_folder_adopt(c, r[0], r[1]))
            gset(c, "migr_folders2220", "1")
            if n:
                print("shared lists:", n, "sorted into the folders of their owners", flush=True)
        # 2.25.0 (#931), once: lists created in a shared folder by a project type / template, an agent's briefing, an import,
        # family or life were not shared with the folder's people. Only lists created AFTER the folder was shared and
        # without that person get it now (one shared before and missing now was taken away on purpose); idempotent.
        if gsetting(c, "migr_folder931") != "1":
            from ..lists.lists import _folder_member_add, _in_folder, collab_all as _ca
            n = 0
            if _ca():
                for fp in c.execute("SELECT * FROM folder_people").fetchall():
                    for l in c.execute("SELECT id, folder FROM lists WHERE owner_id=? AND is_inbox=0 AND COALESCE(folder,'')!='' AND created_at>?",
                                       (fp["owner_id"], fp["created_at"])).fetchall():
                        if _in_folder(l["folder"], fp["folder"]) and _folder_member_add(c, l["id"], fp["user_id"], fp["role"], fp["owner_id"]):
                            n += 1
            gset(c, "migr_folder931", "1")
            if n:
                print("lists in shared folders shared afterwards (#931):", n, flush=True)
        # 2.27.0 (#988), once: every member's copy of a list in its owner's folder is put where the owner has it (folder +
        # place); from now on the owner's arrangement is mirrored for everyone (visible_lists, list_reorder)
        if gsetting(c, "migr_order988") != "1":
            n = c.execute("""UPDATE list_members SET folder=(SELECT l.folder FROM lists l WHERE l.id=list_members.list_id),
                                 sort=(SELECT l.sort FROM lists l WHERE l.id=list_members.list_id)
                             WHERE list_id IN (SELECT id FROM lists WHERE COALESCE(folder,'')!='')
                               AND (folder IS DISTINCT FROM (SELECT l.folder FROM lists l WHERE l.id=list_members.list_id)
                                    OR sort IS DISTINCT FROM (SELECT l.sort FROM lists l WHERE l.id=list_members.list_id))""").rowcount
            gset(c, "migr_order988", "1")
            if n:
                print("shared lists arranged like their owners have them (#988):", n, flush=True)
        # 2.33.0 (#927), once: lists / folders shared so far keep every notification ("all", written explicitly; new shares
        # start with "read"), their owners are asked once in the app
        if gsetting(c, "migr_notiftpl2330") != "1":
            from ..notify.caps import notif_tpl_migrate
            nl, nf = notif_tpl_migrate(c)
            gset(c, "migr_notiftpl2330", "1")
            if nl or nf:
                print("notification templates: shared lists", nl, "and folders", nf, "kept on \"all\" (#927)", flush=True)
        for (uid,) in c.execute("SELECT id FROM users ORDER BY id").fetchall():
            ensure_inbox(c, uid)
            for k, v in USER_DEFAULTS.items():
                c.execute("INSERT INTO user_settings(user_id,key,value) VALUES(?,?,?) ON CONFLICT DO NOTHING", (uid, k, v))
            # features_rev 2: paperless module added -> on by default for existing installs
            # features_rev 3: collab added (2026-09-26) -> on by default
            # features_rev 4: the "links" switch is gone (website link always on) -> dropped from the list
            # features_rev 5: statistics module added (2026-09-26) -> on by default
            # features_rev 6: time tracking module added (2026-09-27) -> on by default
            # features_rev 7: project progress / overview added (2026-09-27) -> on by default
            s = usettings(c, uid)
            rev, fs = int(s.get("features_rev") or 1), [x for x in s["features"].split(",") if x]
            if rev < 7:
                for f, since in (("paperless", 2), ("collab", 3), ("stats", 5), ("time", 6), ("progress", 7)):
                    if rev < since and f not in fs:
                        fs.append(f)
                fs = [f for f in fs if f != "links"]
                uset(c, uid, "features", ",".join(fs))
                uset(c, uid, "features_rev", "7")
            # features_rev 8 (package D2, 2026-09-29): dependencies + custom fields became modules of their own
            if rev < 8:
                fs = feats8(c, uid, fs)
                uset(c, uid, "features", ",".join(fs))
                uset(c, uid, "features_rev", "8")
            # features_rev 9 (2.0.6, #315): comments became a module of their own -> on for everyone
            if rev < 9:
                if "comments" not in fs:
                    fs.append("comments")
                uset(c, uid, "features", ",".join(fs))
                uset(c, uid, "features_rev", "9")
            # features_rev 10 (2.21.0, #659 / #658): events + contacts -> on for everyone (data of their own, nothing changes
            # for tasks; switched off in Settings > Modules)
            if rev < 10:
                fs += [f for f in ("events", "contacts") if f not in fs]
                uset(c, uid, "features", ",".join(fs))
                uset(c, uid, "features_rev", "10")
            # features_rev 11 (2.48.0, #1207): the file store ("Ablage") -> on for everyone (switched off in Settings > Modules)
            if rev < 11:
                fs += [f for f in FEATS_2480 if f not in fs]
                uset(c, uid, "features", ",".join(fs))
                uset(c, uid, "features_rev", "11")
        # 2.15.0 (#479), once: fine scopes. Old read tokens could download files (now attachments:read), old agents had
        # read + write (stored "write" = every scope but admin-read, so they keep what they could do)
        if gsetting(c, "migr_scopes215") != "1":
            n = c.execute("""UPDATE api_tokens SET scopes=scopes || ',attachments:read'
                             WHERE ',' || scopes || ',' NOT ILIKE '%,write,%' AND ',' || scopes || ',' NOT ILIKE '%,attachments:read,%'""").rowcount
            m = c.execute("UPDATE agents SET scopes='read,write' WHERE scopes=''").rowcount
            gset(c, "migr_scopes215", "1")
            print("scopes: attachments:read for", n, "read tokens,", m, "agents keep read + write", flush=True)
        if not gsetting(c, "cal_secret"):  # calendar subscriptions: key material for the stored links / passwords
            gset(c, "cal_secret", secrets.token_hex(32))
        if not gsetting(c, "auth_secret"):  # sign-in: key material for the TOTP secrets and the backup passphrase
            gset(c, "auth_secret", secrets.token_hex(32))
        if not gsetting(c, "undo_key"):  # signs the undo payloads handed to the client
            gset(c, "undo_key", secrets.token_hex(32))
        if not gsetting(c, "vapid_private"):  # Web Push: the instance's VAPID key (P-256), generated once
            gset(c, "vapid_private", _b64u(ec.generate_private_key(ec.SECP256R1()).private_numbers()
                                           .private_value.to_bytes(32, "big")))
            print("Web Push: generated the VAPID key", flush=True)
        _vapid_load(gsetting(c, "vapid_private"))
        # one-shot: completions from before completed_by existed belong to the task's creator (else the list owner)
        if gsetting(c, "migr_completed_by") != "1":
            n = c.execute("""UPDATE tasks SET completed_by=COALESCE(created_by, (SELECT owner_id FROM lists WHERE lists.id=tasks.list_id))
                             WHERE completed_by IS NULL AND status!=0 AND completed_at IS NOT NULL""").rowcount
            gset(c, "migr_completed_by", "1")
            print("completed_by: attributed", n, "earlier completions", flush=True)
        # 1.8.1: the global "Show completed" switch is gone (per view only, default shown): drop the stored values
        c.execute("DELETE FROM user_settings WHERE key='show_completed'")
        c.execute("DELETE FROM settings WHERE key='show_completed'")
        # 2.4.0 (#361): folders nest one level ("Clients/Company X", FOLDER_SEP). A "/" in an existing folder name would now
        # mean a subfolder, so it becomes the look-alike U+2215 once: every existing folder stays top-level, as it was
        if gsetting(c, "migr_folder_path") != "1":
            n = folder_path_migration(c)
            gset(c, "migr_folder_path", "1")
            if n:
                print("folders: kept", n, "folder names with a slash top-level", flush=True)
        # 2.4.1 (#379): tidying up is done by exactly one agent per list. Lists with tidy on get the agent that already
        # received their tidy events first (the first agent with edit rights), once
        if gsetting(c, "migr_tidy_agent") != "1":
            n = 0
            for (lid,) in c.execute("SELECT id FROM lists WHERE agent_tidy!='off' AND tidy_agent IS NULL").fetchall():
                aid = tidy_agent_of(c, lid)
                if aid:
                    c.execute("UPDATE lists SET tidy_agent=? WHERE id=?", (aid, lid))
                    n += 1
            gset(c, "migr_tidy_agent", "1")
            if n:
                print("tidy: assigned the tidy agent of", n, "list(s)", flush=True)
        # 2.18.0 (#430): the milestones of the project overview (list_milestones, 2.7.1) become milestone tasks. Runs whenever
        # rows exist (no flag): a restored backup from before 2.18.0 brings them back and is migrated again
        c.execute("CREATE INDEX IF NOT EXISTS tasks_msid ON tasks(milestone_id) WHERE milestone_id IS NOT NULL")
        n = ms_migrate(c)
        if n:
            print("milestones:", n, "milestones of project overviews became milestone tasks", flush=True)
        # 2.41.0 (#1420): a folder's default agent (folder_props) is also its first agent in folder_agents; every start
        # (a 2.40 that ran on this database after a rollback may have changed it), additive only
        from ..lists.foldershare import sh_folder_agents_sync
        n = sh_folder_agents_sync(c)
        if n:
            print("folders: took over", n, "folder agent(s)", flush=True)
        if gsetting(c, "migr_auditfix") != "1":  # security audit 2026-09-28, one-shot
            n = c.execute("UPDATE users SET paperless_access=1 WHERE is_admin=1 AND paperless_access=0").rowcount
            counts = repair_data(c)
            gset(c, "migr_auditfix", "1")
            print("audit migration: Paperless access granted to", n, "admin(s); repaired:", counts, flush=True)
        # 2.97.0 B (#1951): clients with only a free address get street / postcode / city split from it (idempotent)
        from ..team.clients import cdn_backfill
        n = cdn_backfill(c)
        if n:
            print("clients: address fields filled from the free address for", n, "client(s)", flush=True)
        from ..collab.msgsearch import msg_index_init
        msg_index_init(c)  # 2.33.0 (#1080) / 2.37.0: the message search (kalmido_fold + trigram GIN indexes)
        from ..tasks.ftsearch import fts_index_init
        fts_index_init(c)  # 2.116.0 B (#2065): full-text search of tasks + comments (GIN indexes over kalmido_fold)
        from .rls import apply as rls_apply, OFF_HELP
        rls_on = rls_apply(c)  # 2.37.0 (#1150): row-level security per organisation (policies + the app role)
        if not rls_on and guard:  # 2.37.0 (review W2-2): several organisations rely on it -> no start without it
            from ..accounts.orgs import INSTANCE_ENV
            # 2.46.0 (#1592): needed with several organisations (or the mode workspaces set explicitly, as before)
            if INSTANCE_ENV == "workspaces" or c.execute("SELECT COUNT(*) FROM orgs WHERE personal_of IS NULL").fetchone()[0] > 1:
                print(f"FATAL: {OFF_HELP} Several organisations need it. Refusing to start.", flush=True)
                raise DataDirError(3)
        mig_flags_sync(c, flags0)  # 2.102.0 D (#1996): the one-shots of this start into the table
        c.execute("INSERT INTO kalmido_meta(key,value) VALUES('schema_version',?) ON CONFLICT(key) DO UPDATE SET value="
                  "CASE WHEN CAST(kalmido_meta.value AS BIGINT) < CAST(excluded.value AS BIGINT) THEN excluded.value "
                  "ELSE kalmido_meta.value END", (str(int(SCHEMA_VERSION)),))
        appver_stamp(c)  # 2.149.0 D (#2509): which version ran on this database (start check of the next start, restore)
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
    if not rls_on:  # 2.37.0 (review W2-2): single organisation / shared: it starts, but the admins hear it at every start
        from ..notify.alerts import aa_now
        from .i18n import N_
        aa_now("security", "rls:off", N_("Row-level security is OFF: the database user bypasses it and the role kalmido_app cannot be used. Allow the database user to create roles or create the role (see SELF-HOSTING), then restart."))
    from .pg import pool_refresh
    pool_refresh()  # 2.37.0 (#1150): pooled connections opened before the app role existed would bypass row-level security
    if not os.path.exists(DATA_MARKER):  # new install, or the first start of 2.0 on a readable database
        try:
            with open(DATA_MARKER, "w", encoding="utf-8") as f:
                f.write("This data dir belongs to Kalmido. While this file exists, Kalmido never creates a new empty database here.\n")
        except OSError as e:
            print("warning: could not write", DATA_MARKER, e, flush=True)


def repair_data(c):
    """Nulls / normalizes values the validation now rejects (they could break the shared watchdog, the
    calendar expansion or the client) and breaks parent_id cycles. Returns counts per kind of fix."""
    from ..lists.lists import clean_folder, LIST_COLOR_RE, LIST_NAME_MAX, LIST_VIEWS
    from ..tasks.validation import (
        DURATION_MAX, PRIORITIES, REM_COUNT, REM_MAX, REM_MIN, rr_feasible, rr_norm, rr_problem, valid_date, valid_hm,
    )
    n = {}

    def bump_n(k, x=1):
        if x:
            n[k] = n.get(k, 0) + x
    for t in c.execute("SELECT id, due, due_time, start, duration, reminders, repeat, repeat_from, priority FROM tasks").fetchall():
        f = {}
        if t["due"] is not None and not valid_date(t["due"]):
            f.update(due=None, due_time=None, start=None, reminders="")
            bump_n("due")
        if "due_time" not in f and t["due_time"] is not None and not valid_hm(t["due_time"]):
            f["due_time"] = None
            bump_n("due_time")
        if "start" not in f and t["start"] is not None and not valid_date(t["start"]):
            f["start"] = None
            bump_n("start")
        d = t["duration"]
        if d is not None and (isinstance(d, bool) or not isinstance(d, int) or not 1 <= d <= DURATION_MAX):
            f["duration"] = None
            bump_n("duration")
        if "reminders" not in f and t["reminders"]:
            ok = [x.strip() for x in str(t["reminders"]).split(",")
                  if re.fullmatch(r"-?\d{1,6}", x.strip()) and REM_MIN <= int(x.strip()) <= REM_MAX]
            ok = ",".join(list(dict.fromkeys(str(int(x)) for x in ok))[:REM_COUNT])
            if ok != t["reminders"]:
                f["reminders"] = ok
                bump_n("reminders")
        if t["repeat"]:
            rep = rr_norm(t["repeat"])
            due = f.get("due", t["due"])
            if rr_problem(rep, True) or (due and not rr_feasible(rep, due)):  # 2.116.0 D (#2066): TIMES ok
                f["repeat"] = ""
                bump_n("repeat")
            elif rep != t["repeat"]:
                f["repeat"] = rep
        if t["repeat_from"] not in ("due", "done"):
            f["repeat_from"] = "due"
            bump_n("repeat_from")
        if t["priority"] not in PRIORITIES:
            f["priority"] = 0
            bump_n("priority")
        if f:
            c.execute(f"UPDATE tasks SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), t["id"]])
    # parent cycles (and parents that point at themselves): the task where a walk up meets itself goes top level
    parent = {r[0]: r[1] for r in c.execute("SELECT id, parent_id FROM tasks WHERE parent_id IS NOT NULL")}
    for tid in list(parent):
        seen, cur = [], tid
        while cur in parent and cur not in seen and len(seen) < 50:
            seen.append(cur)
            cur = parent[cur]
        if cur in seen:  # cycle: cut it at the node where it closes
            c.execute("UPDATE tasks SET parent_id=NULL WHERE id=?", (cur,))
            parent.pop(cur, None)
            bump_n("parent_cycle")
    for r in c.execute("SELECT id, name, color, folder, view FROM lists").fetchall():
        f = {}
        if r["color"] and not (isinstance(r["color"], str) and LIST_COLOR_RE.fullmatch(r["color"])):
            f["color"] = ""
        if r["view"] not in LIST_VIEWS:
            f["view"] = "list"
        fo = r["folder"] if isinstance(r["folder"], str) else ""
        if fo != clean_folder(fo, False) or not isinstance(r["folder"], str):
            f["folder"] = clean_folder(fo, False)
        if not isinstance(r["name"], str):
            f["name"] = str(r["name"])[:LIST_NAME_MAX]
        if f:
            c.execute(f"UPDATE lists SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), r["id"]])
            bump_n("list")
    for r in c.execute("SELECT list_id, user_id, folder, view FROM list_members").fetchall():
        fo = r["folder"] if isinstance(r["folder"], str) else ""
        v = r["view"] if r["view"] in LIST_VIEWS else None
        if fo != r["folder"] or fo != clean_folder(fo, False) or v != r["view"]:
            c.execute("UPDATE list_members SET folder=?, view=? WHERE list_id=? AND user_id=?",
                      (clean_folder(fo, False), v, r["list_id"], r["user_id"]))
            bump_n("list_member")
    for h in c.execute("SELECT id, color, remind_at, remind_times, goal, per_week, days FROM habits").fetchall():
        f = {}
        if h["color"] and not (isinstance(h["color"], str) and LIST_COLOR_RE.fullmatch(h["color"])):
            f["color"] = ""
        if h["remind_at"] and not valid_hm(h["remind_at"]):
            f["remind_at"] = ""
        if h["remind_times"] and not all(valid_hm(x) for x in h["remind_times"].split(",")):  # 2.140.0 C (#2135)
            f["remind_times"] = h["remind_at"] if "remind_at" not in f else ""
        if isinstance(h["goal"], bool) or not isinstance(h["goal"], int) or not 1 <= h["goal"] <= 1000:
            f["goal"] = 1
        if isinstance(h["per_week"], bool) or not isinstance(h["per_week"], int) or not 0 <= h["per_week"] <= 7:
            f["per_week"] = 0
        if not isinstance(h["days"], str) or not re.fullmatch(r"[1-7]+", h["days"]):
            f["days"] = "1234567"
        if f:
            c.execute(f"UPDATE habits SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), h["id"]])
            bump_n("habit")
    for k, dflt, ok in (("allday_time", "09:00", valid_hm), ("digest_time", "", lambda v: v == "" or valid_hm(v))):
        for r in c.execute("SELECT user_id, value FROM user_settings WHERE key=?", (k,)).fetchall():
            if not ok(r["value"]):
                c.execute("UPDATE user_settings SET value=? WHERE user_id=? AND key=?", (dflt, r["user_id"], k))
                bump_n("setting_" + k)
    return n


def gsetting(c, key):
    r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r[0] if r else GLOBAL_DEFAULTS.get(key, "")


def gset(c, key, value):
    c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
              (key, str(value)))


def usettings(c, uid):
    s = dict(USER_DEFAULTS)
    s.update({r["key"]: r["value"] for r in c.execute("SELECT key, value FROM user_settings WHERE user_id=?", (uid,))})
    return s


def uset(c, uid, key, value):
    c.execute("INSERT INTO user_settings(user_id,key,value) VALUES(?,?,?) "
              "ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value", (uid, key, str(value)))


def bump(c):
    r = c.execute("UPDATE settings SET value=CAST(CAST(value AS BIGINT)+1 AS TEXT) WHERE key='version' RETURNING value").fetchone()
    if r:  # 2.42.0 (#1376): the task changes of this transaction belong to the new version (GET /api/state/delta)
        from ..tasks.delta import dl_stamp
        dl_stamp(c, int(r[0]))
    # 2.41.0 (#1376): a change counter per area besides the old total v (GET /api/version a): the app reloads and redraws only
    # what an area needs. The area comes from the request's route; outside a request (watchdog, imports in the background)
    # it is "other" (= everything, as before)
    c.execute("INSERT INTO settings(key,value) VALUES(?, '1') ON CONFLICT(key) DO UPDATE SET value=CAST(CAST(settings.value AS BIGINT)+1 AS TEXT)",
              ("version:" + lv_area(),))


# 2.41.0 (#1376): route -> area (first match wins). Reactions / apply / decide on comments may change the task: not "comments".
LV_AREAS = (
    ("comments", re.compile(r"^/api/(v1/)?(tasks/\d+/comments$|comments/\d+(/choice|/withdraw)?$)")),
    ("agentchat", re.compile(r"^/api/(agents/\d+/chat|v1/agent/chats|v1/agents/\d+/chat)")),
    ("team", re.compile(r"^/api/(v1/)?team")),
    ("office", re.compile(r"^/api/(v1/)?(office|clients)")),
    ("calendar", re.compile(r"^/api/(v1/)?(events|evcals|cal/|calendars|appt/)")),  # 2.94.0 B (#1929): + the booking page settings
    ("news", re.compile(r"^/api/(v1/)?news")),
    ("tasks", re.compile(r"^/api/(v1/)?(tasks|lists|sections|folders|batch|projects|tags)")),
    ("budget", re.compile(r"^/api/budget")),  # 2.72.0 (#1333): the household budget (the open budget view reloads)
    ("sheets", re.compile(r"^/api/(v1/)?sheets")),  # 2.89.0 (#1916): tables (the open sheet reloads)
)
LV_AREA_KEYS = tuple(k for k, _ in LV_AREAS) + ("other",)


def lv_area():
    if not has_request_context():
        return "other"
    p = request.path
    return next((k for k, rx in LV_AREAS if rx.match(p)), "other")


def lv_versions(c):
    """{area: counter} of every area (0 = never changed)."""
    return lv_versions_fmt(c.execute(*lv_versions_q()).fetchone())


def lv_versions_q():
    """2.149.0 C (#2507): the query of lv_versions (one row: the keys, the values; /api/version runs it inside one statement)."""
    keys = ["version:" + k for k in LV_AREA_KEYS]  # 2.41.1 (#1376): the known keys, no LIKE (pg_dialect)
    return f"SELECT array_agg(key), array_agg(value) FROM settings WHERE key IN ({','.join('?' * len(keys))})", tuple(keys)


def lv_versions_fmt(r):
    out = dict.fromkeys(LV_AREA_KEYS, 0)
    for key, value in zip((r[0] or []) if r else [], (r[1] or []) if r else []):
        k = key[8:]
        if k in out:
            out[k] = int(value)
    return out


def err(msg, code=400):
    return jsonify(error=msg), code  # msg is already translated


def body():
    """The JSON body of the request (the REST API hands its translated body to the internal views via g.body)."""
    b = g.get("body") if has_request_context() else None
    if b is not None:
        return b
    return request.get_json(silent=True) or {}


# 2.40.0 (#1432): "Load more" pages (jobs, completed, trash) -- a composite cursor "<timestamp>|<id>" so rows with the
# same timestamp are neither repeated nor skipped; next page = rows ordered (ts DESC, id DESC) after the cursor
def ag_cursor(ts, rid):
    return f"{ts or ''}|{int(rid)}"


def ag_cursor_parse(raw):
    """(timestamp, id) of a cursor of ag_cursor, None when there is none; ValueError when it is broken."""
    if not raw:
        return None
    ts, _, rid = str(raw).rpartition("|")
    if not _ or not rid.isdigit() or len(ts) > 40:
        raise ValueError(raw)
    return ts, int(rid)


def ag_limit(raw, dflt, hi):
    """?limit= for a paged list: dflt without, at most hi (ValueError when not a number)."""
    return max(1, min(int(raw), hi)) if raw not in (None, "") else dflt
