"""Time helpers, the database connection, start-up checks and migrations (init_db, repair_data), settings storage."""
import os
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from cryptography.hazmat.primitives.asymmetric import ec
from flask import g, has_request_context, jsonify, request
from werkzeug.security import generate_password_hash

from ..core.config import app, ATT_DIR, BOOT_NAME, BOOT_PROXY, BOOT_USER, DB, NTFY_TOPIC, ONBOARDING_ENV, TZ
from ..core.schema import (
    GLOBAL_DEFAULTS, INDEXES, MIGRATIONS, SCHEMA, SCHEMA_VERSION, TIME_TITLE_TRIGGER, USER_DEFAULTS,
)
from ..core.i18n import LANGS, tr


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
    if "db" not in g:
        g.db = connect()
    return g.db


def connect():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA journal_mode=WAL")
    return c


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
                  (tr("Inbox", lg=r[0] if r and r[0] in LANGS else "en"), iso(now_utc()), uid))


def inbox_names():
    """Every default name of an inbox: "Eingang" (before 2.15) and "Inbox" in each language."""
    if "n" not in _INBOX_NAMES:
        _INBOX_NAMES["n"] = sorted({"Eingang"} | {tr("Inbox", lg=k) for k in LANGS})
    return _INBOX_NAMES["n"]


_INBOX_NAMES = {}


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
    uid = c.execute("""INSERT INTO users(username,display_name,password_hash,proxy_login,is_admin,drop_token,created_at,
                                         paperless_access) VALUES(?,?,?,?,?,?,?,?)""",
                    (username, display_name or username, generate_password_hash(password) if password else None,
                     proxy_login or None, 1 if is_admin else 0, drop_token or secrets.token_urlsafe(24),
                     iso(now_utc()), 1 if pl else 0)).lastrowid
    vals = dict(USER_DEFAULTS)
    # chosen in the first-run setup ("What do you want to use?"): modules + language of new users
    for k, gk in (("features", "default_features"), ("lang", "default_lang")):
        v = gsetting(c, gk)
        if v:
            vals[k] = v
    if seed_global:  # the single-user settings become this user's settings
        for r in c.execute("SELECT key, value FROM settings"):
            if r["key"] in USER_DEFAULTS:
                vals[r["key"]] = r["value"]
    if ntfy_topic is not None:
        vals["ntfy_topic"] = ntfy_topic
    if onboard and ONBOARDING_ENV:  # new account (setup / user admin): sample list + welcome tour on first start
        vals["tour"] = vals["onboard"] = "pending"
    if not vals["ntfy_topic"]:
        vals["ntfy_topic"] = random_topic()
    for k, v in vals.items():
        c.execute("INSERT OR REPLACE INTO user_settings(user_id,key,value) VALUES(?,?,?)", (uid, k, v))
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
    genuinely new install (empty data dir), False for an existing, readable database."""
    from ..admin.backup import BK_DIR
    data = [p for p, ok in ((DATA_MARKER, os.path.exists(DATA_MARKER)), (ATT_DIR, _has_files(ATT_DIR)),
                            (BK_DIR, _has_files(BK_DIR))) if ok]
    try:
        size = os.path.getsize(DB) if os.path.exists(DB) else None
    except OSError as e:
        size = f"unreadable ({e})"
    problem = None
    if size is None or size == 0:
        if data:
            problem = "is missing" if size is None else "is empty"
    elif isinstance(size, str):
        problem = size
    else:
        try:
            c = sqlite3.connect(f"file:{os.path.abspath(DB)}?mode=ro", uri=True, timeout=10)
            try:
                # constraint findings (a NOT NULL / CHECK violation) leave the file readable: start, the admin alert reports them
                # (see "admin alerts"); anything else (damaged pages, broken indexes, unreadable) refuses the start
                rows = [r[0] for r in c.execute("PRAGMA quick_check").fetchall()]
                hard = [x for x in rows if x != "ok" and not re.match(r"(NULL value in |CHECK constraint failed in )", str(x))]
                if not rows or hard:
                    problem = f"failed the integrity check ({(hard or ['?'])[0]})"
                elif not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone() and data:
                    problem = "has no Kalmido tables"
            finally:
                c.close()
        except sqlite3.Error as e:
            problem = f"cannot be read ({e})"
    if problem:
        msg = (f"FATAL: the database {DB} {problem}, but the data dir holds Kalmido data ({', '.join(data) or 'the database file'}). "
               "Refusing to start so that no new, empty database replaces it. Check the disk / volume, restore tasks.db from a "
               "backup (data/backups/), then start again.")
        print(msg, flush=True)
        raise DataDirError(3)
    return size is None or size == 0


def init_db(guard=True):
    from ..core.access import _COLLAB_ALL, _TIME_ALL
    from ..lists.lists import folder_path_migration
    from ..lists.projects import ms_migrate
    from ..notify.push import _b64u, _vapid_load
    from ..agents.core import tidy_agent_of
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    if guard:  # a restore checked its database itself (and must never exit the process)
        startup_guard()
    os.makedirs(ATT_DIR, exist_ok=True)
    c = connect()
    c.executescript(SCHEMA)
    c.isolation_level = None
    c.execute("BEGIN IMMEDIATE")
    try:
        for table, col, ddl in MIGRATIONS:
            if col not in {r[1] for r in c.execute(f"PRAGMA table_info({table})")}:
                c.execute(ddl)
        # task_tags from the single-user era: (task_id, tag) -> (task_id, user_id, tag); 0 = adopted below
        if "user_id" not in {r[1] for r in c.execute("PRAGMA table_info(task_tags)")}:
            c.execute("""CREATE TABLE task_tags_mu (task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                         user_id INTEGER NOT NULL DEFAULT 0, tag TEXT NOT NULL, PRIMARY KEY (task_id, user_id, tag))""")
            c.execute("INSERT INTO task_tags_mu(task_id,user_id,tag) SELECT task_id, 0, tag FROM task_tags")
            c.execute("DROP TABLE task_tags")
            c.execute("ALTER TABLE task_tags_mu RENAME TO task_tags")
        # 2.10.0 (#441): member rows from before groups (or written by a path that sets no own_role) are personal shares
        c.execute("UPDATE list_members SET own_role=role WHERE own_role IS NULL AND grole IS NULL")
        c.execute("CREATE INDEX IF NOT EXISTS tasks_agroup ON tasks(assignee_group_id) WHERE assignee_group_id IS NOT NULL")
        c.execute("DROP INDEX IF EXISTS tasks_tt")  # tt_id is unique per user now (tasks_tt_user)
        c.execute("DROP TRIGGER IF EXISTS time_task_title")
        c.execute(TIME_TITLE_TRIGGER)
        for stmt in INDEXES.strip().split(";"):
            if stmt.strip():
                c.execute(stmt)
        for k, v in GLOBAL_DEFAULTS.items():
            c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
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
        for (uid,) in c.execute("SELECT id FROM users").fetchall():
            ensure_inbox(c, uid)
            for k, v in USER_DEFAULTS.items():
                c.execute("INSERT OR IGNORE INTO user_settings(user_id,key,value) VALUES(?,?,?)", (uid, k, v))
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
        # 2.15.0 (#479), once: fine scopes. Old read tokens could download files (now attachments:read), old agents had
        # read + write (stored "write" = every scope but admin-read, so they keep what they could do)
        if gsetting(c, "migr_scopes215") != "1":
            n = c.execute("""UPDATE api_tokens SET scopes=scopes || ',attachments:read'
                             WHERE ',' || scopes || ',' NOT LIKE '%,write,%' AND ',' || scopes || ',' NOT LIKE '%,attachments:read,%'""").rowcount
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
        if gsetting(c, "migr_auditfix") != "1":  # security audit 2026-09-28, one-shot
            n = c.execute("UPDATE users SET paperless_access=1 WHERE is_admin=1 AND paperless_access=0").rowcount
            counts = repair_data(c)
            gset(c, "migr_auditfix", "1")
            print("audit migration: Paperless access granted to", n, "admin(s); repaired:", counts, flush=True)
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        raise
    if c.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION:
        c.execute(f"PRAGMA user_version={int(SCHEMA_VERSION)}")
    c.close()
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
            if rr_problem(rep) or (due and not rr_feasible(rep, due)):
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
    for h in c.execute("SELECT id, color, remind_at, goal, per_week, days FROM habits").fetchall():
        f = {}
        if h["color"] and not (isinstance(h["color"], str) and LIST_COLOR_RE.fullmatch(h["color"])):
            f["color"] = ""
        if h["remind_at"] and not valid_hm(h["remind_at"]):
            f["remind_at"] = ""
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
    c.execute("UPDATE settings SET value=CAST(value AS INTEGER)+1 WHERE key='version'")


def err(msg, code=400):
    return jsonify(error=msg), code  # msg is already translated


def body():
    """The JSON body of the request (the REST API hands its translated body to the internal views via g.body)."""
    b = g.get("body") if has_request_context() else None
    if b is not None:
        return b
    return request.get_json(silent=True) or {}
