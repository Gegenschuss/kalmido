"""Backups and restore (admins)."""
import contextlib
import glob
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timedelta
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from flask import Response, g, jsonify, request, send_file

from ..core.config import app, APP_NAME, APP_VERSION, ATT_DIR, DATABASE_URL, DB, OFFICE_DIR, PUBLIC_URL, SECRET_KEY, SESSION_DAYS, TZ
from ..core.schema import PURGED_TABLES, SCHEMA_TRIGGERS, SCHEMA_VERSION
from ..core import pg as _pg
from ..core.i18n import LANGS, N_, tr
from ..core.db import body, connect, db, err, gset, gsetting, init_db, iso, local_now, now_utc, parse_iso, usettings
from ..core.mailframe import mail_html
from ..core.pg import system_ctx
from ..core.db import db_log_err  # 2.239.0 B (#2888): no values of database errors in the log
from ..core.db import appver_newer_minor, appver_parse, skfp_kek, skfp_of, skfp_row_opens, SKFP_KEY
from ..core.serializers import unlink_files
from ..core.env import env_bool
from ..core.retention import ret_on as bk_ret_on  # 2.186.0 C (#2602)
from ..accounts.session import _rate_fail, _rate_keys, GATE, login_wait, set_cookie, start_session
from ..accounts.bgjobs import BGJ_FNS, bgj_add, bgj_fn, bgj_pending
from ..accounts.login import _AUTH_KEY, seal, unseal
from ..accounts.oidc import oidc_reset
from ..core.ephem import eph_clear  # 2.622.0 (#3891)
from ..core.access import Denied, acx_drop
from ..tasks.validation import valid_hm
from ..tasks.lifecycle import UNDO_KEY
from ..collab.integfail import integ_tell
from ..collab.news import NEWS_CLEAN
from ..accounts.users import need_admin
from ..calendars.caldav import _DAV_CACHE, _DAV_CACHE_LOCK, _DAV_INST, dav_inst
from ..notify.push import _b64u, _b64u_dec, _VAPID
from ..notify.alerts import _clamp_int, _env_int, aa_count, aa_disk, aa_now, aa_oserr, aa_switch
from ..api.common import hit_limit  # 2.581.0 (#4826): the core layer's counter (the passphrase check)
from ..calendars.subscriptions import _CAL_KEY
from . import bkstore as bks  # 2.432.0 (#3584): the shared file store
from ..core.retention import ret_days, ret_on, ret_report  # 2.369.5 (#2517): pulled up from functions
from ..accounts.users import user_purge  # 2.369.5 (#2517): pulled up from functions
from ..accounts.orgretain import odl_dismantle  # 2.369.5 (#2517): pulled up from functions
from ..lists.lists import list_purge  # 2.369.5 (#2517): pulled up from functions
from ..core.orgcrypt import oc_plain_size  # 2.369.5 (#2517): pulled up from functions


# ---------------------------------------------------------------- backups + restore (admins)
# A backup is ONE zip file in BK_DIR (default: backups/ next to the data dir): kalmido.dump (2.37.0, #1150: pg_dump custom
# format of the Postgres database, a consistent snapshot taken while the app keeps running), attachments/<task>/<file>,
# office/<org>/<file> and manifest.json (format_version 2, app and schema version, counts, SHA-256 + size of every member).
# Optionally encrypted with a passphrase: the zip is then wrapped in an own format (".zip.enc": scrypt key derivation,
# AES-256-GCM in 1 MiB chunks, chunk counter and "last chunk" flag authenticated, so reordering / truncation is detected).
# Without the passphrase an encrypted backup cannot be restored by anyone, including this app. Automatic backups run daily
# at a set time (a thread, not the watchdog), rotated by retention (newest per day for N days + newest per ISO week for M
# weeks; safety backups: the last 3). Restore (from a listed backup or an uploaded file): every member name is checked
# against the expected layout (no paths outside, no links, no directories), sizes / member count / compression ratio are
# limited (zip bombs), the free disk space is checked, every SHA-256 is verified while extracting. Only tables, their data,
# sequences, indexes, constraints and defaults are taken from the dump (a filtered table of contents; functions, triggers,
# policies, extensions and privileges never come from a backup -- init_db creates them from this app's own source); an
# entry of any other kind (views, rules, foreign functions, ...) refuses the dump. That filtered part is read completely
# once (pg_restore to SQL text, nothing executed): every block readable, only plain table statements (no roles, no
# COPY ... PROGRAM, no session or role switches), a schema version this app can migrate. Then:
# maintenance mode (new requests 503, background threads paused, waits until nothing else runs), safety backup of the
# current state, attachments folder swapped by rename, pg_restore --clean in ONE transaction, connection pool renewed,
# migrations, in-process caches reset, every session ended except the restoring admin's (a fresh one).
# Backups of format 1 (tasks.db, SQLite, up to 2.36) can still be listed, uploaded and checked, but not restored here.
# Row-level security (2.37): pg_dump / pg_restore always run with --enable-row-security and PGOPTIONS="-c app.role=system"
# (the policies let the system role through; the password goes through the environment, never on the command line).
# 2.432.0 (#3584): files from BK_SHARED_MIN on are kept ONCE in the shared store BK_DIR/.store (bkstore.py, by content,
# encrypted with a store key of the passphrase when the backups are encrypted); such a backup is format 3: its zip holds
# the dump, the small files and the manifest with the list "shared". A shared file goes once no backup in the folder
# refers to it (bk_store_gc after the rotation and after a delete). Download = one complete format-2 file put together
# while it streams; check / restore read the shared files from the store (SHA-256 checked like the members).
BK_ON_ENV = env_bool("KALMIDO_BACKUPS", True)
BK_DIR = os.path.abspath(os.environ.get("KALMIDO_BACKUP_DIR", "").strip() or os.path.join(os.path.dirname(os.path.abspath(DB)), "backups"))
BK_DROPPED_FKS = os.path.join(BK_DIR, ".dropped-fks.json")  # 2.510.0 (#4286): see _fks_note
BK_PASS_ENV = os.environ.get("KALMIDO_BACKUP_PASSPHRASE", "")
BK_TICK = _env_int("KALMIDO_BACKUP_TICK", 60)                          # s between schedule checks
BK_MAX_BYTES = _env_int("KALMIDO_BACKUP_MAX_MB", 4096) * 1024 * 1024   # restore: upload size and unpacked total
BK_MAX_MEMBERS = 200000
BK_MISSING_SHOWN = 20          # 2.273.0 A (#3050): paths of vanished files named in the manifest and the log
# 2.273.0 A (#3051 p. 13): a restore cannot reach the offline buffers of the devices
BK_OFFLINE_NOTE = N_("Devices that still hold unsent changes send them after reloading: they can meet the restored state as conflicts or come back as new items. Check recent work on those devices.")
BK_MAX_RATIO = 500             # unpacked / packed per member above 1 MB (zip bomb)
BK_STALE_S = 2 * 86400         # "backup older than 2 days" alert
BK_SAFETY_KEEP = 3
# 2.152.0 B (#2172): weekly backups for at most a year (data protection: backups of deleted data are kept short and
# documented); older safety backups go after ret_days("backups") (core/retention.py, behind its switch)
BK_KEEP_WEEKLY_MAX = 52
# 2.306.0 G (#2946): without the retention switch weekly backups are kept for at most two years
BK_KEEP_WEEKLY_CAP = 104
# 2.152.0 B (#2172): hosting: no backup without encryption (off by default, self-hosted installations keep working)
BK_ENCRYPT_REQUIRED = os.environ.get("KALMIDO_BACKUP_ENCRYPT_REQUIRED", "").strip().lower() in ("1", "true", "yes", "on")
BK_UPLOAD_TTL = 3600
BK_CHUNK = 1024 * 1024
BK_MAGIC = b"KALMIDO-BACKUP-ENC\x00"
BK_SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}
BK_CONFIRM = "RESTORE"
# 2.550.0 (#4517): + the instance id of this database (calendars/caldav.dav_inst, 8 hex) before the kind, so the off-site
# clean-up (offsite.bko_prune) tells this server's backups from another server's in the same folder; names without it
# (before 2.550) stay valid (listed, restored)
BK_NAME_RE = re.compile(r"kalmido-backup-(\d{8})-(\d{6})-(?:([0-9a-f]{8})-)?(auto|manual|safety)\.zip(\.enc)?")
BK_UPLOAD_RE = re.compile(r"upload-([a-f0-9]{24})")
BK_DUMP = "kalmido.dump"    # format 2 (2.37.0, Postgres): pg_dump -Fc
BK_LEGACY = "tasks.db"      # format 1 (up to 2.36, SQLite): listed / checked, not restored here
BK_PG_TIMEOUT = _env_int("KALMIDO_BACKUP_PG_TIMEOUT", 6 * 3600)   # s for one pg_dump / pg_restore run
BK_RESTORE_TRIES = 3       # 2.209.0 E (#1627): pg_restore runs again after a deadlock (it changed nothing)
# 2.432.0 (#3584): files from this size on are kept once in the shared store (bkstore.py) instead of in every backup;
# a backup with such files is format 3 (manifest "shared"), one without stays format 2
BK_STORE = os.path.join(BK_DIR, ".store")
BK_SHARED_MIN = max(1, _env_int("KALMIDO_BACKUP_SHARED_MIN", 64 * 1024))
# members: attachments/<task>/<file>; 2.36.1 (#1021): office/<org>/<file> (the logos of the office module, same rules);
# 2.46.0 (#1605): + attachments/avatars/<file> and attachments/listicons/<file> (pictures of people, groups and lists)
# 2.48.0 (#1207): + attachments/files/<node>/<file> (the file store) and attachments/lists/<list>/<file> (project files, #410:
# they were left out of the archive before)
# 2.79.0 (#476 M8): + attachments/chat/<agent>-<person>/<file> (agent chat files), attachments/budget/<list>/<file> (household
# budget receipts) and attachments/docthumbs/<file> (document previews): their rows were in the dump, the files were not
# 2.99.0 (#2182, review H1): + attachments/wiki/<page>/<file> (the files of knowledge pages)
# 2.148.1 C (#2482): every folder below ATT_DIR in one place (a test compares them with the folders the code writes to):
# BK_FLAT = files directly in the folder, BK_PER_ID = <folder>/<id>/<file>; + tchat (team chat files), sheets (table
# files), listheads (list header pictures), bookmarks (bookmark pictures)
# 2.152.0 B (#2172, review C-H3) found the same gaps (listheads, sheets, tchat, bookmarks): one list for both
BK_FLAT = ("avatars", "listicons", "docthumbs", "listheads", "bookmarks")
# 2.363.3 (#3134): + tplfiles (the files of templates)
BK_PER_ID = ("files", "lists", "budget", "wiki", "tchat", "sheets", "tplfiles")
BK_MEMBER_RE = re.compile(r"(attachments|office)/(\d{1,12}|" + "|".join(BK_FLAT) + "|(?:" + "|".join(BK_PER_ID) + r")/\d{1,12}|chat/\d{1,12}-\d{1,12})"
                          r"/([^/\\\x00-\x1f]{1,255})")
# 2.359.2 (#2895): the own industry packs of the instance (office/sheet.py IND_DATA_DIR, /data/packs/industry): flat files
BK_PACK_RE = re.compile(r"packs/industry/([A-Za-z0-9][A-Za-z0-9_.-]{0,250})")
BK_PACK_PREFIX = "packs/industry/"


def bk_pack_dir():
    from ..office.sheet import IND_DATA_DIR
    return IND_DATA_DIR


BK_ERR = {"busy": N_("Another backup or restore is running, please try again in a moment."),
          # 2.644.0 (#4530): the readers' lock is taken by a clean-up of the shared store, not by a backup or restore
          "store_busy": N_("The backup folder is being cleaned up right now, please try again in a moment."),
          "disk": N_("Not enough free disk space for the backup."),
          "io": N_("The backup could not be written ({0})."),
          "format": N_("This is not an Kalmido backup (or the file is damaged)."),
          "members": N_("The backup contains unexpected files and was refused."),
          "too_large": N_("The backup is too large (limit {0} MB unpacked)."),
          "bomb": N_("The backup looks like a zip bomb and was refused."),
          "hash": N_("The backup is damaged: a file does not match its checksum."),
          "integrity": N_("The database in the backup is damaged (integrity check failed)."),
          "schema": N_("The backup is from a newer Kalmido version (database schema {0}); update Kalmido first."),
          # 2.149.0 D (#2509): the manifest's app_version is a newer minor than this server's
          "newer": N_("The backup was made with Kalmido {0}, a newer version than this server ({1}). Update Kalmido first, then restore it."),
          "objects": N_("The database in the backup contains unexpected objects or statements and was refused."),
          "legacy": N_("This backup is from a version before 2.37 (SQLite). Restore it with Kalmido 2.36, then update to 2.37: the data is moved over during the update."),
          "tools": N_("The database tools (pg_dump / pg_restore) are missing on this server."),
          # 2.359.3 (#2945)
          "tools_version": N_("No backup is possible: pg_dump {0} refuses the newer PostgreSQL {1} of this server. Use a Kalmido image with postgresql-client {1} (see SELF-HOSTING.md)."),
          "passphrase": N_("Wrong passphrase, or the encrypted backup is damaged."),
          "need_passphrase": N_("This backup is encrypted: enter its passphrase."),
          "no_passphrase": N_("Encryption needs a passphrase (at least 10 characters)."),
          # 2.152.0 B (#2172)
          "encrypt_required": N_("This server only writes encrypted backups: set a passphrase (at least 10 characters)."),
          # 2.359.3 (#2893)
          "server_key": N_("This backup was made with another server key, so its encrypted data could not be read here. Nothing was changed. Put the key of the old server in place, restart and restore again (see SELF-HOSTING.md)."),
          "server_key_none": N_("This server has no server key, so the encrypted data of this backup could not be read here. Nothing was changed. Set the key of the server that made the backup, restart and restore again (see SELF-HOSTING.md)."),
          "not_found": N_("Backup not found."),
          "confirm": N_("Type {0} to confirm."),
          "maint": N_("The server is still busy; the restore did not start. Please try again."),
          # 2.370.2 (#2779): a folder that is a mount of its own cannot be renamed (EXDEV / EBUSY)
          "mounts": N_("The attachments or office folder is a mount of its own, so a restore cannot swap it. Nothing was changed. Mount the data folder as a whole, see SELF-HOSTING.md."),
          # 2.148.1 C (#2482): the maintenance mode of a restore holds in this process only
          "procs": N_("A restore needs a single server process (KALMIDO_ROLE=all, KALMIDO_REPLICAS=1, KALMIDO_WEB_PROCS=1). Stop the other processes first, see SELF-HOSTING.md."),
          "restore": N_("The restore failed ({0}); nothing was changed."),
          # 2.273.0 A (#3050): the way back to the state before failed too
          "rollback": N_("The restore failed and so did the way back: the database may be incomplete, so the server stays closed. Restart it: the start completes the database. The safety backup {0} holds the state from before the restore."),
          # 2.432.0 (#3584): the shared files of a backup (bkstore.py)
          "shared_missing": N_("{0} shared files of this backup are missing in the backup folder. Download the backup from the server that made it (a complete file), or put the shared files back."),
          "old_passphrase": N_("This backup was encrypted with an earlier passphrase. Enter that passphrase to check, restore or download it.")}
BK_LEFTOVER_NOTE = N_("Folders from a restore are lying next to the data folder ({0}). After a hard stop the database and the files may not match: check them, a successful restore removes them.")  # 2.370.2 (#2779)
# 2.359.3 (#2893): what a restore warns about (bk_key_state; "foreign" only gets this far with KALMIDO_SECRET_KEY_CHANGED=1)
BK_KEY_WARN = {"foreign": N_("This backup was made with another server key: attachments, private files and encrypted fields stay unreadable until that key is back in place."),
               "secrets": N_("This backup may come from another server key: stored access tokens (Git, documents, single sign-on) may be unreadable. Enter them again or put the old key back.")}
_BK = {"running": "", "started": 0.0, "next_try": 0.0, "stale_at": 0.0, "meta": {}}
_BK_LOCK = threading.Lock()


class BackupError(Exception):
    def __init__(self, code, *args):
        super().__init__(code)
        self.code, self.args_ = code, args

    def text(self, lg=None):
        return tr(BK_ERR.get(self.code, BK_ERR["format"]), *self.args_, lg=lg)


@app.errorhandler(BackupError)
def backup_error(e):
    code = {"busy": 409, "store_busy": 409, "not_found": 404, "need_passphrase": 400, "passphrase": 400}.get(e.code, 400)
    return jsonify(error=e.text(), code=e.code), code


def bk_passphrase(c):
    """The passphrase for new backups: KALMIDO_BACKUP_PASSPHRASE, else the one set in the settings (sealed)."""
    if BK_PASS_ENV:
        return BK_PASS_ENV
    try:
        return unseal(c, "backup", gsetting(c, "bk_pass"))
    except (InvalidTag, ValueError):
        return ""


def bk_key(pw, salt, p=None):
    p = p or BK_SCRYPT
    return Scrypt(salt=salt, length=32, n=p["n"], r=p["r"], p=p["p"]).derive(pw.encode())


def bk_encrypt(src, dst, pw, meta):
    salt = os.urandom(16)
    head = json.dumps({"v": 1, "kdf": "scrypt", **BK_SCRYPT, "salt": _b64u(salt), "chunk": BK_CHUNK, "meta": meta},
                      separators=(",", ":")).encode()
    aes = AESGCM(bk_key(pw, salt))
    hh = hashlib.sha256(BK_MAGIC + head).digest()
    with open(src, "rb") as f, open(dst, "wb") as o:
        o.write(BK_MAGIC + struct.pack(">I", len(head)) + head)
        i, cur = 0, f.read(BK_CHUNK)
        while True:
            nxt = f.read(BK_CHUNK) if cur else b""
            last = not nxt
            ct = aes.encrypt(struct.pack(">IQ", 0, i), cur, hh + struct.pack(">QB", i, 1 if last else 0))
            o.write(struct.pack(">I", len(ct)) + ct)
            if last:
                break
            i, cur = i + 1, nxt


def bk_enc_header(f):
    """(header dict, raw header bytes) of an encrypted backup, or BackupError('format')."""
    if f.read(len(BK_MAGIC)) != BK_MAGIC:
        raise BackupError("format")
    try:
        n = struct.unpack(">I", f.read(4))[0]
        if not 0 < n <= 65536:
            raise ValueError
        raw = f.read(n)
        h = json.loads(raw)
        if h.get("v") != 1 or h.get("kdf") != "scrypt" or not isinstance(h.get("meta"), dict):
            raise ValueError
        if not (2 ** 10 <= int(h["n"]) <= 2 ** 20 and 1 <= int(h["r"]) <= 16 and 1 <= int(h["p"]) <= 4 and 1024 <= int(h["chunk"]) <= 16 * BK_CHUNK):
            raise ValueError
    except (ValueError, TypeError, KeyError, struct.error):
        raise BackupError("format") from None
    return h, raw


def bk_decrypt(src, dst, pw):
    with open(src, "rb") as f, open(dst, "wb") as o:
        h, raw = bk_enc_header(f)
        aes = AESGCM(bk_key(pw, _b64u_dec(h["salt"]), h))
        hh = hashlib.sha256(BK_MAGIC + raw).digest()
        i, total = 0, 0
        while True:
            ln = f.read(4)
            if len(ln) != 4:
                raise BackupError("passphrase")  # truncated: the last chunk never came
            n = struct.unpack(">I", ln)[0]
            if n > int(h["chunk"]) + 16:
                raise BackupError("format")
            ct = f.read(n)
            pt, last = None, 0
            for last in (0, 1):
                try:
                    pt = aes.decrypt(struct.pack(">IQ", 0, i), ct, hh + struct.pack(">QB", i, last))
                    break
                except InvalidTag:
                    continue
            if pt is None:
                e = BackupError("passphrase")
                e.first = i == 0  # 2.525.0 (#4303): the very first chunk = another passphrase (bk_old_pass), later = damaged
                raise e
            total += len(pt)
            if total > BK_MAX_BYTES:
                raise BackupError("too_large", BK_MAX_BYTES // 1048576)
            o.write(pt)
            if last:
                if f.read(1):
                    raise BackupError("format")
                return h
            i += 1


def _sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(BK_CHUNK), b""):
            h.update(b)
    return h.hexdigest()


def bk_outside(base, prefix, listed):
    """2.148.1 C (#2482): {top folder: n} of the regular files below base that the archive does not bring (names never).
    2.148.1 G (#2482): judged by the archive's own file list, so an archive of an older version keeps the old folder."""
    out = {}
    if not os.path.isdir(base):
        return out
    for root, dirs, fns in os.walk(base):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d)) and not (root == base and d == ".wikitmp")]
        for fn in fns:
            full = os.path.join(root, fn)
            rel = prefix + os.path.relpath(full, base).replace(os.sep, "/")
            if os.path.islink(full) or not os.path.isfile(full) or rel in listed:
                continue
            if prefix == "office/" and fn.endswith((".tmp", ".part")):
                continue
            top = prefix + (rel[len(prefix):].split("/", 1)[0] if "/" in rel[len(prefix):] else ".")
            out[top] = out.get(top, 0) + 1
    return out


def bk_instance(c):
    """2.550.0 (#4517): the instance id of this database (settings.dav_instance, the one of the CalDAV UIDs: random, no
    secret), read from the database every time (another process may have made it meanwhile); made once when missing."""
    v = gsetting(c, "dav_instance")
    if re.fullmatch(r"[0-9a-f]{8}", v or ""):
        return v
    _DAV_INST.pop("i", None)
    return dav_inst(c)


def bk_name(kind, encrypted, inst=""):
    ts = local_now()
    for _ in range(120):
        n = f"kalmido-backup-{ts.strftime('%Y%m%d-%H%M%S')}-" + (f"{inst}-" if inst else "") + f"{kind}.zip" + (".enc" if encrypted else "")  # 2.550.0 (#4517)
        if not os.path.exists(os.path.join(BK_DIR, n)):
            return n
        ts += timedelta(seconds=1)
    raise BackupError("busy")


# ---- pg_dump / pg_restore (2.37.0, #1150)
# libpq keyword -> environment variable: the connection of DATABASE_URL goes to the tools through the environment, so the
# password never shows up in the process list, a log line or an error text
_PG_ENV = {"host": "PGHOST", "hostaddr": "PGHOSTADDR", "port": "PGPORT", "dbname": "PGDATABASE", "user": "PGUSER",
           "password": "PGPASSWORD", "passfile": "PGPASSFILE", "service": "PGSERVICE", "options": "PGOPTIONS",
           "sslmode": "PGSSLMODE", "sslrootcert": "PGSSLROOTCERT", "sslcert": "PGSSLCERT", "sslkey": "PGSSLKEY",
           "sslcrl": "PGSSLCRL", "sslnegotiation": "PGSSLNEGOTIATION", "gssencmode": "PGGSSENCMODE",
           "channel_binding": "PGCHANNELBINDING", "connect_timeout": "PGCONNECT_TIMEOUT",
           "target_session_attrs": "PGTARGETSESSIONATTRS", "application_name": "PGAPPNAME"}


def bk_pg_env():
    """Environment for pg_dump / pg_restore: only the basics of this process (never its own PG* variables) + the
    connection of DATABASE_URL; row security stays on and the session runs as the "system" role of the policies."""
    try:
        d = _pg.conninfo_dict(DATABASE_URL)
    except Exception:  # noqa: BLE001 -- the URL itself must not end up in an error text
        raise BackupError("io", "DATABASE_URL") from None
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "TMPDIR")}
    for k, v in d.items():
        if k in _PG_ENV and v not in (None, ""):
            env[_PG_ENV[k]] = str(v)
    env["PGOPTIONS"] = (env.get("PGOPTIONS", "") + " -c app.role=system").strip()
    env.setdefault("PGCONNECT_TIMEOUT", "15")
    return env


def _pg_tool(name):
    exe = shutil.which(name)
    if not exe:
        raise BackupError("tools")
    return exe


def bk_tools_majors(c):
    """2.359.3 (#2945): (major of pg_dump, major of the server); None for what cannot be told (pg_dump then speaks for itself)."""
    txt = os.environ.get("KALMIDO_TEST_PG_DUMP_VERSION", "") if os.environ.get("KALMIDO_TEST") == "1" else ""  # tests only
    try:
        txt = txt or subprocess.run([_pg_tool("pg_dump"), "--version"], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                    timeout=15, check=False, env={"PATH": os.environ.get("PATH", "")}).stdout
    except (BackupError, OSError, subprocess.TimeoutExpired):
        txt = ""
    m = re.search(r"(?:^|\s)(\d{1,3})(?:\.\d+|\s|$)", txt or "")
    try:
        num = int(c.execute("SHOW server_version_num").fetchone()[0])
    except Exception:  # noqa: BLE001 -- no answer: the dump names the problem
        c.rollback()
        num = 0
    return int(m.group(1)) if m else None, num // 10000 or None


def bk_tools_check(c):
    """2.359.3 (#2945): pg_dump refuses a server of a newer major version: BackupError before anything is written."""
    tool, server = bk_tools_majors(c)
    if tool and server and tool < server:
        raise BackupError("tools_version", str(tool), str(server))


def bk_tools_note():
    """2.359.3 (#2945): once per instance start: Admin > Server names the problem before the next backup fails."""
    c = connect()
    try:
        tool, server = bk_tools_majors(c)
        bad = bool(tool and server and tool < server)
        gset(c, "bk_tools_problem", f"{tool}|{server}" if bad else "")
        c.commit()
    finally:
        c.close()
    if bad:
        aa_now("storage", "backup:tools_version", BK_ERR["tools_version"], [str(tool), str(server)])


def _pg_errline(raw, tool):
    """First meaningful line of a tool's stderr (short; libpq never prints the password)."""
    for ln in (raw or b"").decode("utf-8", "replace").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith(("WARNING", "HINT", "DETAIL")):
            return ln[:200]
    return f"{tool} failed"


def _pg_run(args, err_code="io", timeout=None):
    """Runs pg_dump / pg_restore with the database environment; BackupError(err_code, first stderr line) on failure."""
    exe = _pg_tool(args[0])
    try:
        p = subprocess.run([exe, *args[1:]], env=bk_pg_env(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.PIPE, timeout=timeout or BK_PG_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        raise BackupError(err_code, f"{args[0]}: timeout") from None
    if p.returncode:
        e = BackupError(err_code, _pg_errline(p.stderr, args[0]))
        e.raw = p.stderr or b""  # 2.209.0 E (#1627): the whole stderr (_pg_restore looks for a deadlock in it)
        raise e


def bk_db_bytes(c):
    """Size of the database on the server (for the free space check; the dump is usually much smaller)."""
    try:
        return int(c.execute("SELECT pg_database_size(current_database())").fetchone()[0] or 0)
    except Exception:  # noqa: BLE001 -- only an estimate
        c.rollback()
        return 0


def bk_dump(dest):
    """pg_dump -Fc of the whole database into dest, from one snapshot that also gives the manifest its counts and schema
    version. Returns (counts, schema version)."""
    _pg_tool("pg_dump")
    s = _pg.connect_direct(DATABASE_URL)
    try:
        # the next transaction is REPEATABLE READ (one snapshot for the counts and, exported, for pg_dump); no timeouts
        # for this session while pg_dump runs
        s.execute("SET SESSION CHARACTERISTICS AS TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        s.execute("SET statement_timeout = 0")
        s.execute("SET idle_in_transaction_session_timeout = 0")
        s.commit()
        with _pg.system_ctx(s):  # the whole database (all organisations), also when a request makes the safety backup
            snap = s.execute("SELECT pg_export_snapshot()").fetchone()[0]
            counts = {k: int(s.execute(q).fetchone()[0]) for k, q in (
                ("users", "SELECT COUNT(*) FROM users"), ("lists", "SELECT COUNT(*) FROM lists"),
                ("tasks", "SELECT COUNT(*) FROM tasks WHERE deleted_at IS NULL"), ("attachments", "SELECT COUNT(*) FROM attachments"))}
            r = s.execute("SELECT value FROM kalmido_meta WHERE key='schema_version'").fetchone()
            schema = int(r[0]) if r and str(r[0]).isdigit() else SCHEMA_VERSION
            # the snapshot stays valid while this transaction is open
            # 2.193.0 D (#2220): without the rows of the queue (a restored backup would run its own "Back up now" again)
            # 2.622.0 (#3891): nor the short-lived state of the processes (core/ephem.py: sign-in steps, tickets)
            _pg_run(["pg_dump", "-Fc", "-Z", "6", "--enable-row-security", f"--snapshot={snap}", "--exclude-table-data=bg_jobs", "--exclude-table-data=eph_state", "-f", dest])
        return counts, schema
    finally:
        s.close()


def bk_create(kind="manual", c=None, keep_dump=None):
    """Writes one backup (caller holds _BK_LOCK); returns its name. BackupError on failure. keep_dump: also keep a copy of
    the dump at this path (the restore's way back)."""
    own = c is None
    c = c or connect()
    tmp = slock = None
    try:
        os.makedirs(BK_DIR, mode=0o700, exist_ok=True)
        encrypt = gsetting(c, "bk_encrypt") == "1" or BK_ENCRYPT_REQUIRED  # 2.152.0 B (#2172)
        pw = bk_passphrase(c) if encrypt else ""
        if BK_ENCRYPT_REQUIRED and len(pw) < 10:
            raise BackupError("encrypt_required")
        if encrypt and len(pw) < 10:
            raise BackupError("no_passphrase")
        bk_tools_check(c)  # 2.359.3 (#2945)
        inst = bk_instance(c)  # 2.550.0 (#4517): the instance id in the name and the manifest (made once, then kept)
        # 2.432.0 (#3584): every file is hashed first; only what the shared store does not hold yet needs room (before:
        # all files again, twice with encryption). The zip holds the database and the small files, so it stays small
        db_bytes = bk_db_bytes(c)
        c.rollback()  # (2.281.0 D, #3118: no read transaction stays open while the files are hashed)
        slock = bks.lock(BK_STORE)  # 2.432.0 (#3584): no clean-up (any process) between the first store file and the refs
        key = bks.store_key(BK_STORE, pw) if encrypt else None
        seen, small, new = {}, 0, 0
        for full, rel in bk_walk()[0]:  # (only the larger files are hashed here; the small ones are read once, below)
            try:
                st = os.stat(full)
                if st.st_size < BK_SHARED_MIN or rel.startswith(BK_PACK_PREFIX):  # 2.359.2 (#2895): packs stay in the zip
                    small += st.st_size
                    continue
                seen[full] = (st.st_size, st.st_mtime_ns, _sha256_file(full))
            except FileNotFoundError:
                continue
            if not os.path.isfile(os.path.join(BK_STORE, bks.rel(key, seen[full][2]))):
                new += bks.stored_size(key, st.st_size)
        need = db_bytes * (3 if keep_dump else 2) + small * (2 if encrypt else 1) + (db_bytes if encrypt else 0) + new
        free = shutil.disk_usage(BK_DIR).free
        if free < need * 1.1 + 64 * 1024 * 1024:
            raise BackupError("disk")
        tmp = tempfile.mkdtemp(prefix=".tmp-", dir=BK_DIR)
        dbp = os.path.join(tmp, BK_DUMP)
        c.rollback()  # 2.281.0 D (#3118): close the read transaction; dump + ZIP take minutes and an idle one is cut after 5 min
        counts, schema = bk_dump(dbp)
        if keep_dump:
            shutil.copyfile(dbp, keep_dump)
        files, att_bytes = [], 0
        shared, refs, new = [], set(), 0  # 2.432.0 (#3584): [archive name, size, sha256] in the store, its store paths
        zp = os.path.join(tmp, "backup.zip")
        with zipfile.ZipFile(zp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
            z.write(dbp, BK_DUMP, compress_type=zipfile.ZIP_STORED)  # pg_dump -Fc compresses itself
            files.append([BK_DUMP, os.path.getsize(dbp), _sha256_file(dbp)])
            missing = []  # 2.273.0 A (#3050): (full path, archive name) of files gone between listing and reading

            def take(full, rel, again=False):
                """One file into the zip (small) or the store; False = gone meanwhile."""
                nonlocal att_bytes, new
                try:
                    st = os.stat(full)
                    old = seen.get(full)
                    # (a small file is hashed here first, as before 2.432: gone after the dump = FileNotFoundError, nothing written)
                    digest = old[2] if old and old[:2] == (st.st_size, st.st_mtime_ns) and not again else _sha256_file(full)
                    size = st.st_size
                    if size >= BK_SHARED_MIN and not rel.startswith(BK_PACK_PREFIX):  # 2.359.2 (#2895): packs stay in the zip
                        got = bks.put(BK_STORE, key, full, digest, size)
                        if got is None:  # changed while it was copied: hashed once more
                            digest = _sha256_file(full)
                            size = os.path.getsize(full)
                            got = bks.put(BK_STORE, key, full, digest, size)
                        if got is None:
                            return False
                        shared.append([rel, size, digest])
                        refs.add(got[0])
                        new += got[1]
                    else:  # hashed while written: the manifest names exactly what the zip got
                        zi = zipfile.ZipInfo.from_file(full, rel)
                        zi.compress_type, h, size = zipfile.ZIP_DEFLATED, hashlib.sha256(), 0
                        with open(full, "rb") as f, z.open(zi, "w") as o:
                            for b in iter(lambda: f.read(BK_CHUNK), b""):
                                h.update(b)
                                size += len(b)
                                o.write(b)
                        files.append([rel, size, h.hexdigest()])
                except FileNotFoundError:
                    return False
                att_bytes += size
                return True

            todo, skipped = bk_walk()  # (again: files that came after the hashing above; skipped = top folder -> n)
            for full, rel in todo:
                if not take(full, rel):  # gone meanwhile (deleted): tried once more below (2.273.0 A, #3050)
                    missing.append((full, rel))
            gone = []
            # 2.273.0 A (#3050): a second try of the same path (helps only when a file was replaced in place meanwhile; a deleted or
            # moved one stays missing); what is still missing is named, never silently
            for full, rel in missing:
                if not take(full, rel, again=True):
                    gone.append(rel)
            if gone:  # 2.273.0 F1 (#3050): the log gets the count and the folders only, the paths stay in the manifest (admins)
                tops = sorted({"/".join(r.split("/")[:2]) if r.count("/") > 1 else r.split("/")[0] + "/." for r in gone})
                print(f"backup: {len(gone)} file(s) vanished while the backup was written (deleted or moved after the database dump),",
                      "folders:", ", ".join(tops), flush=True)
            npacks = sum(1 for f in files if f[0].startswith(BK_PACK_PREFIX))
            meta = {"format": "kalmido-backup", "format_version": 3 if shared else 2, "app_version": APP_VERSION, "schema_version": schema,
                    "created_at": iso(now_utc()), "kind": kind, "counts": counts, "db_bytes": files[0][1],
                    "attachment_files": len(files) - 1 + len(shared) - npacks,
                    "attachment_bytes": att_bytes - sum(f[1] for f in files if f[0].startswith(BK_PACK_PREFIX)),
                    "pack_files": npacks,  # 2.359.2 (#2895)
                    "skipped_files": sum(skipped.values()),  # 2.79.0 (#476 M8)
                    "missing_files": len(gone), "missing_paths": gone[:BK_MISSING_SHOWN]}  # 2.273.0 A (#3050)
            meta["instance"] = inst  # 2.550.0 (#4517)
            if shared:  # 2.432.0 (#3584): the files kept once in the store, and which store (the key's salt is no secret)
                meta.update(shared_files=len(shared), shared_bytes=sum(x[1] for x in shared), store_new_bytes=new,
                            store="plain" if key is None else key.desc)
            if skipped:  # folder names only (never file names): a new kind of stored file the archive does not know yet
                print("backup: files outside the known folders were not saved:", json.dumps(skipped, sort_keys=True), flush=True)
            z.writestr("manifest.json", json.dumps({**meta, "files": files, **({"shared": shared} if shared else {})}, ensure_ascii=False))
        if os.environ.get("KALMIDO_TEST") == "1" and os.environ.get("KALMIDO_TEST_BK_ZIP_DELAY"):  # tests only (2.281.0 D, #3118)
            time.sleep(float(os.environ["KALMIDO_TEST_BK_ZIP_DELAY"]))
        name = bk_name(kind, encrypt, inst)
        final = os.path.join(BK_DIR, name)
        if shared:  # 2.432.0 (#3584): before the backup shows up, so the clean-up never sees it without its references
            bks.refs_write(BK_STORE, name, refs)
        if encrypt:
            bk_encrypt(zp, final + ".part", pw, meta)
        else:
            os.replace(zp, final + ".part")
        os.chmod(final + ".part", 0o600)
        with open(final + ".part", "rb") as f:
            os.fsync(f.fileno())
        os.replace(final + ".part", final)
        _BK["meta"].pop(name, None)
        return name
    except BackupError:
        raise
    except OSError as e:
        raise BackupError("io", aa_oserr(e)) from None
    except (_pg.Error, zipfile.BadZipFile, ValueError, bks.StoreError) as e:
        raise BackupError("io", type(e).__name__) from None
    finally:
        bks.unlock(slock)
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
        if own:
            c.close()


def bk_walk():
    """(full path, archive name) of every file a backup takes, sorted, + {top folder: n} of the regular files outside
    the known folders (2.79.0, #476 M8: never silently). 2.432.0 (#3584): one walk for the hashing and the writing."""
    out, skipped = [], {}
    packs = bk_pack_dir()
    for base, prefix in ((ATT_DIR, "attachments/"), (OFFICE_DIR, "office/"), (packs, BK_PACK_PREFIX)):  # 2.359.2 (#2895)
        if not os.path.isdir(base):
            continue
        for root, dirs, fns in os.walk(base):
            dirs[:] = sorted(d for d in dirs if not os.path.islink(os.path.join(root, d))
                             and not (root == base and d == ".wikitmp"))  # 2.99.0 (#2182): a wiki export being written
            for fn in sorted(fns):
                full = os.path.join(root, fn)
                rel = prefix + os.path.relpath(full, base).replace(os.sep, "/")
                if prefix == "office/" and fn.endswith((".tmp", ".part")):  # 2.36.2 E (#1146): unfinished uploads
                    continue
                if os.path.islink(full) or not os.path.isfile(full) or not (BK_PACK_RE if base is packs else BK_MEMBER_RE).fullmatch(rel):
                    if not os.path.islink(full) and os.path.isfile(full):
                        top = prefix + (rel[len(prefix):].split("/", 1)[0] if "/" in rel[len(prefix):] else ".")
                        skipped[top] = skipped.get(top, 0) + 1
                    continue
                out.append((full, rel))
    return out, skipped


def bk_parse_name(n):
    m = BK_NAME_RE.fullmatch(n or "")
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=TZ)
    except ValueError:
        return None
    return {"name": n, "at": dt, "kind": m.group(4), "encrypted": bool(m.group(5)), "instance": m.group(3) or ""}  # 2.550.0 (#4517)


def bk_meta(path, encrypted):
    """Manifest summary without the file list (zip: manifest.json; encrypted: the authenticated plain header)."""
    st = os.stat(path)
    key = (os.path.basename(path), st.st_mtime, st.st_size)
    hit = _BK["meta"].get(key[0])
    if hit and hit[0] == key:
        return hit[1]
    meta = {}
    try:
        if encrypted:
            with open(path, "rb") as f:
                meta = bk_enc_header(f)[0]["meta"]
        else:
            with zipfile.ZipFile(path) as z:
                i = z.getinfo("manifest.json")
                if i.file_size <= 64 * 1024 * 1024:
                    meta = json.loads(z.read(i))
                    meta.pop("files", None)
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, BackupError):
        meta = {"unreadable": True}
    if len(_BK["meta"]) > 500:
        _BK["meta"].clear()
    _BK["meta"][key[0]] = (key, meta)
    return meta


def bk_list():
    out = []
    try:
        names = os.listdir(BK_DIR)
    except FileNotFoundError:
        return out
    for n in names:
        p = bk_parse_name(n)
        if not p:
            continue
        full = os.path.join(BK_DIR, n)
        if os.path.islink(full) or not os.path.isfile(full):
            continue
        try:
            p["size"] = os.path.getsize(full)
            p["meta"] = bk_meta(full, p["encrypted"])
        except FileNotFoundError:  # 2.358.0 A (#3279): deleted meanwhile (retention of a running backup): not listed, no 500
            continue
        out.append(p)
    out.sort(key=lambda x: (x["at"], x["name"]), reverse=True)
    return out


def bk_public(x):
    m = x.get("meta") or {}
    return {"name": x["name"], "kind": x["kind"], "encrypted": x["encrypted"], "size": x["size"], "created_at": iso(x["at"]),
            "app_version": m.get("app_version", ""), "schema_version": m.get("schema_version"), "counts": m.get("counts") or {},
            "attachment_files": m.get("attachment_files"), "attachment_bytes": m.get("attachment_bytes"),
            "pack_files": m.get("pack_files") or 0,  # 2.359.2 (#2895)
            "unreadable": bool(m.get("unreadable")), "missing_files": m.get("missing_files") or 0,  # 2.273.0 A (#3050)
            # 2.432.0 (#3584): files kept once in the shared store (size = this file only) and what this backup added there
            "shared_files": m.get("shared_files") or 0, "shared_bytes": m.get("shared_bytes") or 0,
            "store_new_bytes": m.get("store_new_bytes") or 0,
            # 2.37.0: a backup from before 2.37 (SQLite): listed and checked, restored only through 2.36 + the update
            "legacy": not m.get("unreadable") and m.get("format_version", 1) < 2}


def bk_prune(c):
    """Retention: every backup of the last 24 hours, then the newest backup per day for the last keep_daily days that
    have one, the newest per ISO week for keep_weekly weeks, the last BK_SAFETY_KEEP safety backups and (2.525.0, #4303)
    the last BK_SAFETY_KEEP manual ones. Returns the deleted names. 2.152.0 B (#2172): keep_weekly at most
    BK_KEEP_WEEKLY_MAX; a safety (2.525.0: or manual) backup older than ret_days("backups") goes even among the last ones
    -- only while ret_on("backups"), else it is counted (ret_report; the caller commits)."""
    daily = _clamp_int(gsetting(c, "bk_keep_daily"), 1, 365, 14)
    # 2.152.0 review F3: an older setting above the cap is cut to it only with the switch (an update never deletes by surprise)
    weekly = _clamp_int(gsetting(c, "bk_keep_weekly"), 0, BK_KEEP_WEEKLY_MAX if ret_on("backups") else BK_KEEP_WEEKLY_CAP, 8)
    items = bk_list()
    keep, days, weeks = set(), [], []
    for x in items:
        if x["kind"] == "safety":
            continue
        d, w = x["at"].date(), tuple(x["at"].isocalendar())[:2]
        if d not in days:
            days.append(d)
            if len(days) <= daily:
                keep.add(x["name"])
        if w not in weeks:
            weeks.append(w)
            if len(weeks) <= weekly:
                keep.add(x["name"])
    purge, n_old = ret_on("backups"), {}
    # 2.525.0 (#4303): a "Back up now" (kind manual) is kept like a safety backup: the last BK_SAFETY_KEEP stay, also when
    # an automatic one of the same day / week is newer; the older manual ones are in the rotation above as before
    for kind in ("safety", "manual"):
        last = [x for x in items if x["kind"] == kind][:BK_SAFETY_KEEP]
        old = [x for x in last if local_now() - x["at"] >= timedelta(days=ret_days("backups"))]
        keep.update(x["name"] for x in last if not (purge and x in old))
        n_old[kind] = len(old)
    ret_report(c, "backups", n_old, purge)
    keep.update(x["name"] for x in items if x["kind"] != "safety" and local_now() - x["at"] < timedelta(hours=24))
    gone = []
    for x in items:
        if x["name"] not in keep:
            try:
                os.remove(os.path.join(BK_DIR, x["name"]))
                gone.append(x["name"])
            except OSError:
                pass
    bk_store_gc(c)  # 2.432.0 (#3584)
    return gone


def bk_store_gc(c):
    """2.432.0 (#3584): a shared file goes once no backup in the folder refers to it any more (caller holds _BK_LOCK).
    The references come from .store/refs/<backup> (no passphrase needed); a backup that may refer to the store but has
    no reference file stops the clean-up (nothing goes). Reference files stay while the backup is here or on the off-site
    target (bko_remote, its names after the last upload). -> (files removed, bytes freed) or None."""
    if not os.path.isdir(BK_STORE):
        return None
    slock = bks.lock(BK_STORE, wait=False)
    if slock is None:  # a backup is being written (maybe in the worker process): the next clean-up takes it
        return None
    try:
        rlock = bks.lock(BK_STORE, wait=False, name=bks.READ_LOCK)  # 2.525.0 (#4303): a download / check reads the store
        if rlock is None:
            print("backup: shared store not cleaned up now (a download or check reads it; the next rotation does it)", flush=True)
            return None
        try:
            return _bk_store_gc(c)
        finally:
            bks.unlock(rlock)
    finally:
        bks.unlock(slock)


def bk_read_lock():
    """2.525.0 (#4303): a download, check or restore that reads files of the shared store holds the readers' lock (shared,
    across processes): the clean-up (bk_store_gc, after the rotation or a delete) then removes nothing and runs again next
    time; while a clean-up runs, the reader gets "store_busy" (2.644.0, #4530: was "busy", whose text names a backup or
    restore) instead of a file that breaks off. -> a handle for bks.unlock() (None without a store)."""
    if not os.path.isdir(BK_STORE):
        return None
    fd = bks.lock(BK_STORE, wait=False, name=bks.READ_LOCK, shared=True)
    if fd is None:
        raise BackupError("store_busy")
    return fd


def bk_test_gate(env="KALMIDO_TEST_BK_DL_GATE"):
    """Tests only (2.525.0, #4303): a download waits before its first shared file until the file KALMIDO_TEST_BK_DL_GATE
    exists (the test deletes the backup meanwhile). 2.549.0 (#4529): env=KALMIDO_TEST_BKO_UP_GATE for the off-site upload.
    2.644.0 (#4530): env=KALMIDO_TEST_BK_DL_TICKET_GATE: the GET of a download between the used ticket and the stream; the
    file <gate>.at says the request waits there."""
    gate = os.environ.get(env) if os.environ.get("KALMIDO_TEST") == "1" else ""
    if gate:
        with contextlib.suppress(OSError):
            open(gate + ".at", "w").close()
    end = time.monotonic() + 60
    while gate and not os.path.exists(gate) and time.monotonic() < end:
        time.sleep(0.05)


def _bk_store_gc(c):
    items, needed = bk_list(), set()
    for x in items:
        r = bks.refs_read(BK_STORE, x["name"])
        if r is None:
            m = x["meta"]
            if m.get("unreadable") or m.get("format_version", 1) >= 3:
                print("backup: shared store not cleaned up (a backup without its reference file)", flush=True)
                return None
            continue
        needed |= r
    try:
        remote = json.loads(gsetting(c, "bko_remote") or "[]")
    except ValueError:
        remote = []
    n, freed = bks.gc(BK_STORE, needed, {x["name"] for x in items} | {str(r) for r in remote if isinstance(r, str)})
    if n:
        print(f"backup: shared store: {n} file(s) no backup needs any more removed ({freed // 1048576} MB)", flush=True)
    return n, freed


@bgj_fn("backup")  # 2.193.0 D (#2220): "Back up now" through the queue (the worker runs it)
def bk_run(kind):
    """Backup + retention with its bookkeeping and alerts (own connection; any thread). Returns the name or None. Never
    raises: a database that cannot be reached (2.37.0: Postgres down) is a failed backup like any other."""
    if not _BK_LOCK.acquire(blocking=False):
        return None
    _BK.update(running=kind, started=time.time())
    c = None
    try:
        try:
            c = connect()
            if os.environ.get("KALMIDO_TEST") == "1" and os.environ.get("KALMIDO_TEST_BK_IDLE_TX_MS"):  # tests only (2.281.0 D, #3118)
                c.execute("SET idle_in_transaction_session_timeout=%d" % int(os.environ["KALMIDO_TEST_BK_IDLE_TX_MS"]))
                c.commit()  # a SET survives only a committed transaction
            name = bk_create(kind, c)
            bk_prune(c)
            for k, v in (("bk_last_ok", iso(now_utc())), ("bk_last_name", name), ("bk_last_error", ""), ("bk_last_error_at", ""), ("bk_tools_problem", "")):
                gset(c, k, v)
            c.commit()
        except BackupError:
            raise
        except Exception as e:  # noqa: BLE001 -- the database is gone (pool timeout, connection refused, ...)
            raise BackupError("io", type(e).__name__) from None
        _BK["next_try"] = 0.0
        print("backup written:", name, flush=True)
        return name
    except BackupError as e:
        try:
            c.rollback()
            gset(c, "bk_last_error", e.text("en"))
            gset(c, "bk_last_error_at", iso(now_utc()))
            if e.code == "tools_version":  # 2.359.3 (#2945): Admin > Server (about: backup_tools_problem)
                gset(c, "bk_tools_problem", "|".join(str(x) for x in e.args_))
            c.commit()
        except Exception:  # noqa: BLE001 -- no database: the alert below still goes out (log + admin alert queue)
            pass
        _BK["next_try"] = time.time() + 3600
        print("backup FAILED:", e.text("en"), flush=True)
        aa_now("storage", f"backup:{e.code}", N_("Backup failed: {0}"), [{"t": BK_ERR.get(e.code, BK_ERR["format"])} if not e.args_
                                                                       else e.text("en")])
        bk_fail_tell(c, e)
        return None
    finally:
        if c is not None:
            c.close()
        _BK.update(running="", started=0.0)
        _BK_LOCK.release()


def bk_uploads_gc():
    d = os.path.join(BK_DIR, ".uploads")
    try:
        for n in os.listdir(d):
            p = os.path.join(d, n)
            if time.time() - os.path.getmtime(p) > BK_UPLOAD_TTL:
                os.remove(p)
    except OSError:
        pass
    try:  # leftovers of an interrupted backup
        for n in os.listdir(BK_DIR):
            p = os.path.join(BK_DIR, n)
            if (n.startswith(".tmp-") or n.endswith(".part")) and time.time() - os.path.getmtime(p) > 6 * 3600:
                shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.remove(p)
    except OSError:
        pass


def bkr_daily_prune(c):
    """2.152.0 B (#2172): the rotation runs once a day also while the automatic backups are switched off (old backups
    and safety backups must not stay for good just because nobody switched the schedule on)."""
    day = local_now().date().isoformat()
    if gsetting(c, "bk_prune_day") == day or not _BK_LOCK.acquire(blocking=False):
        return
    try:
        bk_prune(c)
        gset(c, "bk_prune_day", day)
        c.commit()
    finally:
        _BK_LOCK.release()


def backup_tick(c):
    if BK_ON_ENV and (gsetting(c, "bk_on") == "1" or ret_on("backups")):
        bkr_daily_prune(c)  # 2.152.0 B (#2172); review F3: with the schedule off only with the switch (manual backups stay)
    if not BK_ON_ENV:
        return
    from .offsite import bko_tick
    bko_tick(c)  # 2.143.0 B (#2152): the newest backup to the off-site target (also when only manual backups are made)
    if gsetting(c, "bk_on") != "1":
        return
    bk_uploads_gc()
    now = local_now()
    at = gsetting(c, "bk_time")
    at = at if valid_hm(at) else "03:30"
    if gsetting(c, "bk_last_day") != now.date().isoformat() and now.strftime("%H:%M") >= at and time.time() >= _BK["next_try"]:
        if bk_run("auto"):
            gset(c, "bk_last_day", now.date().isoformat())
            c.commit()
    if time.time() - _BK["stale_at"] >= 3600:  # "no backup for 2 days" at most hourly (+ the alert cooldown)
        _BK["stale_at"] = time.time()
        ref = max(gsetting(c, "bk_last_ok") or "", gsetting(c, "bk_enabled_at") or "")  # 2.81.0 (#1627): switched on again = the clock starts then (ISO text sorts by time)
        if ref and (now_utc() - parse_iso(ref)).total_seconds() > BK_STALE_S:
            last = gsetting(c, "bk_last_ok")
            aa_now("storage", "backup:stale", N_("The last successful backup is older than 2 days ({0})."),
                   [last[:16].replace("T", " ") + " UTC" if last else {"t": N_("none yet")}])


def bk_fail_tell(c, e):
    """2.367.3 (#2971): a failed backup reaches every instance admin as a News item, a push and a mail, whatever the admin alerts
    are set to (an error with a backup is worth a second way); once a day per error, the next try comes within the hour."""
    key = f"{local_now().date().isoformat()}:{e.code}"
    try:
        if c is None or gsetting(c, "bk_fail_told") == key:
            return
        gset(c, "bk_fail_told", key)
        with system_ctx(c):  # every instance admin
            rows = c.execute("SELECT id, email FROM users WHERE is_admin=1 AND disabled=0 AND kind<>'agent' ORDER BY id").fetchall()
            langs = {r["id"]: usettings(c, r["id"]).get("lang") for r in rows}
        integ_tell(c, [r["id"] for r in rows], "backup", e.text, click="settings/backup", focus="backup")  # 2.582.0 (#4827): Server > Backup
        c.commit()
    except Exception as x:  # noqa: BLE001 -- no database: the log and the admin alert above are what is left
        print("backup: telling the admins failed:", type(x).__name__, flush=True)
        return
    link = f"{PUBLIC_URL}/#settings/backup"
    for r in rows if "mail:security" in BGJ_FNS else ():  # the background mail of integrations/mail.py: only with outgoing mail
        if not (r["email"] or "").strip():
            continue
        lg = langs[r["id"]] if langs[r["id"]] in LANGS else "en"
        subject, line = f"{APP_NAME}: {tr('Backup failed: {0}', e.text(lg), lg=lg)}", tr("Please check the backup settings.", lg=lg)
        bgj_add("mail:security", r["email"], subject, f"{line}\n\n{link}", mail_html(subject, [line], tr("Open settings", lg=lg), link, lang=lg), user_id=r["id"])


def backup_loop():
    while True:
        time.sleep(BK_TICK)
        try:
            with GATE.bg():
                c = connect()
                try:
                    backup_tick(c)
                finally:
                    c.close()
        except Exception as e:  # noqa: BLE001
            print("backup loop error:", db_log_err(e), flush=True)
            aa_count("watchdog", f"backup|{type(e).__name__}", "backup")


# ---- inspection / extraction of an archive (restore, verify)
def bk_open(path, pw, work):
    """Path of the plain zip (decrypted into `work` when needed) + the encryption header or None."""
    with open(path, "rb") as f:
        head = f.read(len(BK_MAGIC))
    if head == BK_MAGIC:
        if not pw:
            raise BackupError("need_passphrase")
        zp = os.path.join(work, "archive.zip")
        return zp, bk_decrypt(path, zp, pw)
    if head[:4] != b"PK\x03\x04":
        raise BackupError("format")
    return path, None


def bk_check_zip(z, space=True):
    """Validates the member list; returns the manifest (with files) or BackupError. space=False: no free space and no
    version check (the download of a format-3 backup writes and restores nothing). 2.432.0 (#3584): format 3 = + the
    list "shared" (bkstore.py)."""
    infos = z.infolist()
    if len(infos) > BK_MAX_MEMBERS:
        raise BackupError("members")
    seen, total = set(), 0
    for i in infos:
        n = i.filename
        m = BK_MEMBER_RE.fullmatch(n)
        ok = n in ("manifest.json", BK_DUMP, BK_LEGACY) or (m and m.group(3) not in (".", "..")) or bool(BK_PACK_RE.fullmatch(n))
        if not ok or n in seen or i.is_dir() or i.flag_bits & 0x1 or i.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise BackupError("members")
        if (i.external_attr >> 16) & 0o170000 not in (0, 0o100000):  # symlinks / devices (unix mode bits)
            raise BackupError("members")
        seen.add(n)
        total += i.file_size
        if total > BK_MAX_BYTES:
            raise BackupError("too_large", BK_MAX_BYTES // 1048576)
        if i.file_size > 1024 * 1024 and i.file_size > BK_MAX_RATIO * max(1, i.compress_size):
            raise BackupError("bomb")
    legacy = BK_LEGACY in seen  # format 1 (SQLite, before 2.37)
    if "manifest.json" not in seen or (BK_DUMP in seen) == legacy:
        raise BackupError("format")
    mi = z.getinfo("manifest.json")
    if mi.file_size > 64 * 1024 * 1024:
        raise BackupError("format")
    try:
        man = json.loads(z.read(mi))
    except (ValueError, zipfile.BadZipFile):
        raise BackupError("format") from None
    if not isinstance(man, dict) or man.get("format") != "kalmido-backup" or not isinstance(man.get("files"), list):
        raise BackupError("format")
    if man.get("format_version", 1) not in ((1,) if legacy else (2, 3)):
        raise BackupError("format")
    sv = man.get("schema_version")
    if isinstance(sv, bool) or not isinstance(sv, int):
        raise BackupError("format")
    if sv > SCHEMA_VERSION and space:
        raise BackupError("schema", sv)
    av = str(man.get("app_version") or "")[:20]
    if space and appver_newer_minor(av) and not env_bool("KALMIDO_ALLOW_DOWNGRADE", False):  # 2.149.0 D (#2509)
        raise BackupError("newer", av, APP_VERSION)
    listed = {}
    for f in man["files"]:
        if not (isinstance(f, list) and len(f) == 3 and isinstance(f[0], str) and isinstance(f[1], int) and isinstance(f[2], str)):
            raise BackupError("format")
        listed[f[0]] = f
    if set(listed) != seen - {"manifest.json"}:
        raise BackupError("hash")
    shared = man.get("shared") if man.get("format_version") == 3 else None
    if shared is not None:  # 2.432.0 (#3584): the same rules as for the members, and a known store
        st = man.get("store")
        if not isinstance(shared, list) or len(shared) + len(seen) > BK_MAX_MEMBERS or not (st == "plain" or bks.desc_ok(st)):
            raise BackupError("format")
        for f in shared:
            if not (isinstance(f, list) and len(f) == 3 and isinstance(f[0], str) and type(f[1]) is int and f[1] >= 0
                    and isinstance(f[2], str) and bks.SHA_RE.fullmatch(f[2])):
                raise BackupError("format")
            m = BK_MEMBER_RE.fullmatch(f[0])
            if not m or m.group(3) in (".", "..") or f[0] in listed:
                raise BackupError("members")
            listed[f[0]] = f
            total += f[1]
            if total > BK_MAX_BYTES:
                raise BackupError("too_large", BK_MAX_BYTES // 1048576)
    elif "shared" in man:
        raise BackupError("format")
    free = shutil.disk_usage(os.path.dirname(os.path.abspath(DB))).free
    if space and free < total * 1.1 + 64 * 1024 * 1024:
        raise BackupError("disk")
    man["_listed"], man["_total"], man["_legacy"] = listed, total, legacy
    man["_shared"] = shared or []
    return man


def bk_extract(z, info, dest, listed):
    """One member to dest with the size limit and the SHA-256 of the manifest."""
    want = listed[info.filename]
    h, n = hashlib.sha256(), 0
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with z.open(info) as src, os.fdopen(fd, "wb") as out:
        while True:
            b = src.read(BK_CHUNK)
            if not b:
                break
            n += len(b)
            if n > info.file_size or n > want[1]:
                raise BackupError("bomb")
            h.update(b)
            out.write(b)
    if n != want[1] or not hmac.compare_digest(h.hexdigest(), want[2]):
        raise BackupError("hash")


# ---- the dump of a backup: read it completely once (pg_restore to SQL text, nothing is executed) before a restore
# 2.37.0 (#1150, review W2-1): a restore never takes CODE from a dump. The table of contents (pg_restore --list) is filtered
# down to tables, their data, sequences, indexes, constraints and column defaults (bk_toc); functions, triggers, policies,
# row security, extensions, schemas, privileges and comments are left out -- init_db creates all of them again from this
# app's own source right after the restore (rls.apply, msgsearch, the schema triggers). An entry of an unknown kind (views,
# rules, types, procedures, ...) or a function / trigger that is not Kalmido's refuses the whole dump ("objects").
# Second floor: the SQL text of exactly the filtered list is read once and every statement must be one of the statements
# below (anything else, e.g. COPY ... PROGRAM, SET ROLE, RESET, a DO block, would run inside this database -> refused)
_ID = r'(?:"[^"]{1,63}"|\w{1,63})'
_T = rf"public\.{_ID}"
_STMT_OK = [re.compile(x, re.I | re.S) for x in (
    r"SET (?!(?:app\.|role\b|session_authorization\b))[\w]+ = [\w'.,\- ]*",
    rf"SELECT pg_catalog\.setval\('{_T}', \d+, (true|false)\)",
    r"BEGIN", r"COMMIT",  # pg-ok: patterns of a dump's statements (checked, not executed)
    rf"DROP (TABLE|INDEX|SEQUENCE) IF EXISTS [\w.\" ]+",
    rf"ALTER TABLE (IF EXISTS )?(ONLY )?{_T} (DROP CONSTRAINT IF EXISTS {_ID}|ALTER COLUMN {_ID} DROP DEFAULT)",
    rf"CREATE TABLE {_T} \(.*\)",
    rf"ALTER TABLE (ONLY )?{_T} ALTER COLUMN {_ID} (ADD GENERATED (BY DEFAULT|ALWAYS) AS IDENTITY \(.*\)|SET DEFAULT .*)",
    rf"ALTER TABLE (ONLY )?{_T} ADD CONSTRAINT {_ID} (PRIMARY KEY|UNIQUE|FOREIGN KEY|CHECK) .*",
    rf"CREATE (UNIQUE )?INDEX {_ID} ON (ONLY )?{_T} USING \w+ \(.*\)",
    rf"CREATE SEQUENCE {_T} .*", rf"ALTER SEQUENCE {_T} OWNED BY {_T}\.{_ID}",
    rf"COMMENT ON (TABLE|COLUMN) {_T}(\.{_ID})? IS '.*'",
)]
_STMT_FORCE = re.compile(rf"ALTER TABLE (ONLY )?{_T} FORCE ROW LEVEL SECURITY")
_OWN_FN = re.compile(r"(kalmido|rls)_\w+")
# (whole words: a future column or comment containing one of them would make own backups unrestorable -> rename it or
# narrow the word here; the round trip of tests/backup_test.py shows it at once)
_STMT_BAD = re.compile(
    r"\b(FROM|TO)\s+PROGRAM\b|\bSECURITY\s+DEFINER\b|\bEXECUTE\b|\bALTER\s+(SYSTEM|ROLE|USER|DATABASE|FUNCTION|PROCEDURE)\b"
    r"|\b(CREATE|DROP)\s+(ROLE|USER|DATABASE|SERVER|SUBSCRIPTION|PUBLICATION|EVENT\s+TRIGGER|RULE|VIEW|LANGUAGE)\b|\bGRANT\b"
    r"|\bRESET\b|\bSET\s+(LOCAL\s+|SESSION\s+)?(ROLE|SESSION[\s_]+AUTHORIZATION|app\.)|[\w.]*session_authorization"
    r"|\bROW\s+LEVEL\s+SECURITY\b|\bPOLICY\b|\bEXTENSION\b|\bLANGUAGE\s+\"?c\b|\bTRIGGER\b|\bFUNCTION\b|\bPROCEDURE\b|\bDO\b"
    r"|\bCOPY\s+[\w.\"]+\s*(\(|FROM|TO)|\b(pg_read_file|pg_read_binary_file|pg_ls_\w+"
    r"|pg_stat_file|lo_import|lo_export|lo_\w*open|dblink\w*|pg_execute_server_program|pg_terminate_backend|pg_cancel_backend"
    r"|pg_reload_conf|pg_promote|pg_file_\w+|set_config|query_to_xml\w*)\s*\(", re.I)
_COPY = re.compile(rb'COPY public\.("[^"]{1,63}"|\w{1,63}) \((?:[^()\n]*)\) FROM stdin;\n')
# the kinds of table-of-contents entries a restore takes over (longest first: "TABLE DATA" before "TABLE")
_TOC_KEEP = ("SEQUENCE OWNED BY", "FK CONSTRAINT", "SEQUENCE SET", "TABLE DATA", "CONSTRAINT", "SEQUENCE", "DEFAULT",
             "INDEX", "TABLE")
# the kinds it leaves out (code, privileges, schema-level entries: init_db / the running database have their own)
_TOC_SKIP = ("DATABASE PROPERTIES", "ROW SECURITY", "DEFAULT ACL", "STDSTRINGS", "SEARCHPATH", "EXTENSION", "FUNCTION",
             "ENCODING", "TRIGGER", "COMMENT", "DATABASE", "POLICY", "SCHEMA", "ACL")
_TOC_KINDS = tuple(sorted(_TOC_KEEP + _TOC_SKIP, key=len, reverse=True))
_TOC_LINE = re.compile(r"(\d+); (\d+) (\d+) (.*)")
# 2.116.0 (#2065, job #692): the full-text indexes (tasks/ftsearch.py) call to_tsvector / setweight / "left": not in the
# call list of _calls_ok, and they need not be: a restore leaves them out and init_db creates them again (fts_index_init;
# 2.981.0, #5278: gone, the shared search index obj_search indexes a plain column)
_TOC_REBUILT = {"fts_tasks", "fts_comments"}


def bk_toc(dump):
    """The filtered table of contents of a dump (see above): (list text for pg_restore --use-list, table names).
    BackupError("integrity") when pg_restore cannot read it, "objects" for an entry of an unknown or foreign kind."""
    exe = _pg_tool("pg_restore")
    lst = subprocess.run([exe, "--list", dump], stdin=subprocess.DEVNULL, capture_output=True, timeout=600, check=False,
                         env={"PATH": os.environ.get("PATH", "")})
    if lst.returncode:
        raise BackupError("integrity")
    try:
        text = lst.stdout.decode("utf-8")
    except UnicodeDecodeError:
        raise BackupError("integrity") from None
    keep, tables = [], set()
    for ln in text.splitlines():
        if not ln.strip() or ln.startswith(";"):
            continue
        m = _TOC_LINE.fullmatch(ln)
        kind = m and next((k for k in _TOC_KINDS if m.group(4).startswith(k + " ")), None)
        if not kind:
            print("restore: refused dump entry:", ln[:200], flush=True)
            raise BackupError("objects")
        rest = m.group(4)[len(kind) + 1:].split(" ")
        if kind == "FUNCTION":  # FUNCTION public name(args) owner
            ok = len(rest) >= 2 and rest[0] == "public" and bool(_OWN_FN.fullmatch(rest[1].split("(", 1)[0]))
        elif kind == "TRIGGER":  # TRIGGER public table name owner
            ok = len(rest) >= 3 and rest[0] == "public" and (rest[2] in SCHEMA_TRIGGERS or bool(_OWN_FN.fullmatch(rest[2])))
        elif kind == "COMMENT" and rest[:2] in (["public", "TABLE"], ["public", "COLUMN"]):
            keep.append(ln)  # a comment on a table / column (plain text, checked below like everything else)
            continue
        elif kind == "INDEX" and len(rest) >= 2 and rest[0] == "public" and rest[1] in _TOC_REBUILT:
            continue  # rebuilt by init_db after the restore (its expression calls functions a dump statement may not have)
        elif kind in _TOC_KEEP:  # (a name with a space would split: refused, Kalmido has none)
            ok = len(rest) >= 2 and rest[0] == "public" and (kind != "TABLE" or len(rest) <= 3)
            if ok:
                keep.append(ln)
                if kind == "TABLE":
                    tables.add(rest[1])
        else:
            ok = True
        if not ok:
            print("restore: refused dump entry:", ln[:200], flush=True)
            raise BackupError("objects")
    return "\n".join(keep) + "\n", tables


def _toc_file(dump):
    """bk_toc written next to the dump (the work folder of the restore); returns (path, table names)."""
    text, tables = bk_toc(dump)
    path = dump + ".toc"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path, tables


def bk_statements(sql):
    """SQL text -> statements (split at ; outside quotes, dollar quotes and comments; comments dropped)."""
    out, cur, i, n = [], [], 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "-" and sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if ch == "/" and sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if ch in "'\"":
            j = i + 1
            while j < n:
                if sql[j] == ch:
                    if j + 1 < n and sql[j + 1] == ch:
                        j += 2
                        continue
                    break
                j += 1
            cur.append(sql[i:j + 1])
            i = j + 1
            continue
        if ch == "$":
            m = re.match(r"\$(\w*)\$", sql[i:i + 70])
            if m and not (i and (sql[i - 1].isalnum() or sql[i - 1] == "_")):
                tag = m.group(0)
                j = sql.find(tag, i + len(tag))
                j = n if j < 0 else j + len(tag)
                cur.append(sql[i:j])
                i = j
                continue
        if ch == ";":
            s = " ".join("".join(cur).split())
            if s:
                out.append(s)
            cur = []
        else:
            cur.append(ch)
        i += 1
    s = " ".join("".join(cur).split())
    if s:
        out.append(s)
    return out


def bk_check_statement(s):
    """True when the statement is one a (filtered) Kalmido dump consists of."""
    if s == "SELECT pg_catalog.set_config('search_path', '', false)":  # the preamble (set_config is refused elsewhere)
        return True
    if _STMT_FORCE.fullmatch(s):  # part of a TABLE entry; only ever tightens (rls.apply sets it anyway)
        return True
    if _STMT_BAD.search(s) or not _calls_ok(s):
        return False
    return any(rx.fullmatch(s) for rx in _STMT_OK)


# 2.37.0 (review W2-1, Fable B1): every call in an expression (DEFAULT, CHECK, index, CREATE TABLE) must be one a Kalmido dump
# has -- a positive list of call heads, not only the forbidden names above (pg_catalog."set_config"(...) as a column default
# would run as whoever inserts). String literals are blanked first; escape / Unicode strings and quoted call heads never
# occur in a Kalmido dump and are refused.
_CALL_HEADS = {"IDENTITY", "KEY", "UNIQUE", "WHERE", "CHECK", "INCLUDE", "AND", "OR", "NOT", "IN", "ANY", "ARRAY", "btree",
               "gin", "gist", "hash", "lower", "pg_catalog.lower", "numeric", "varying", "varchar", "timestamp", "COALESCE",
               "pg_catalog.setval", "public.kalmido_fold", "kalmido_fold", "__T"}
_TABLE_HEAD = re.compile(rf"(CREATE TABLE|REFERENCES|ON(?: ONLY)?) {_T}\s*\(")


def _calls_ok(s):
    if re.search(r"(?<![\w'])[EeUu]&?'|U&\"|\"\s*\(", s):
        return False
    t = _TABLE_HEAD.sub(r"\1 __T(", re.sub(r"'(?:[^']|'')*'", "''", s))
    if re.search(r'"\s*\(', t):
        return False
    t = re.sub(r'"([^"]{1,63})"', r"\1", t)  # 2.37.0 (review W3-2): "pg_catalog".fn( counts as pg_catalog.fn(
    return all(m.group(1) in _CALL_HEADS for m in re.finditer(r'(?<![\w."])([A-Za-z_][\w.]*)\s*\(', t))


def _restore_args(toc):
    return ["--clean", "--if-exists", "--no-owner", "--no-privileges", "--single-transaction", f"--use-list={toc}"]


# 2.359.3 (#2893): the same columns as core/db.py skfp_keys_match, the start check of the server key
BK_KEY_COLS = {"org_keys": ("org_id", "kek_check", "kek_check_rot"), "user_keys": ("user_id", "kek_check")}


def bk_key_cols(table, copy_line):
    """Positions of the id and the check values in a COPY block of org_keys / user_keys; None for every other table."""
    want = BK_KEY_COLS.get(table)
    if not want:
        return None
    cols = [x.strip().strip('"') for x in copy_line[copy_line.index(b"(") + 1:copy_line.rindex(b")")].decode("utf-8", "replace").split(",")]
    return [cols.index(x) for x in want if x in cols]


def bk_key_row(kek, table, kcols, line):
    """Does this data row of org_keys / user_keys open with kek? (column values of a server-made COPY block: digits and hex)"""
    v = line.rstrip(b"\n").split(b"\t")
    try:
        sid = int(v[kcols[0]])
        return skfp_row_opens(kek, sid if table == "org_keys" else -sid, [v[i].decode("ascii", "replace") for i in kcols[1:] if v[i] != b"\\N"])
    except (IndexError, TypeError, ValueError):  # (a crafted archive; TypeError: compare_digest refuses non-ASCII text)
        return False


def bk_key_state(man):
    """2.359.3 (#2893): does a checked backup fit the server key here (read from the dump, nothing restored)? "ok"; "foreign":
    it holds organisation / account keys and none opens; "secrets": no such keys, but its fingerprint is another one (or a
    version before the fingerprint, 2.190, made it): only stored tokens are at stake."""
    d = man.get("db")
    if not d:
        return "ok"  # format 1, before 2.37: no sealed data yet
    if d["key_rows"]:
        return "ok" if d["key_opens"] else "foreign"
    if d["secret_fp"]:
        return "ok" if SECRET_KEY and skfp_of(SECRET_KEY) == d["secret_fp"] else "secrets"
    v = appver_parse(man.get("app_version"))
    return "secrets" if v and v < (2, 190, 0) else "ok"


def bk_scan_dump(dump):
    """Reads the whole dump through pg_restore (to SQL text; no database involved): every data block must be readable
    (else "integrity"), every statement one of a Kalmido dump ("objects"), the schema version (kalmido_meta) not newer
    than this app's ("schema"). Returns {"schema_version", "rows": {table: n}, "users"}."""
    exe = _pg_tool("pg_restore")
    toc, _ = _toc_file(dump)
    rows, ddl, ddl_n, meta, table = {}, [], 0, {}, None
    kek, key_rows, key_opens, kcols = skfp_kek(SECRET_KEY) if SECRET_KEY else None, 0, False, None  # 2.359.3 (#2893)
    with tempfile.TemporaryFile() as errf:
        p = subprocess.Popen([exe, *_restore_args(toc), "-f", "-", dump], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=errf, env={"PATH": os.environ.get("PATH", "")})
        bad = None
        try:
            for line in p.stdout:
                if table is not None:
                    if line == b"\\.\n":
                        table = None
                    else:
                        rows[table] += 1
                        if table == "kalmido_meta" and len(meta) < 100:
                            k, _, v = line.rstrip(b"\n").partition(b"\t")
                            meta[k.decode("utf-8", "replace")] = v.decode("utf-8", "replace")
                        if kcols:
                            key_rows += 1
                            if kek and not key_opens:
                                key_opens = bk_key_row(kek, table, kcols, line)
                    continue
                if line.startswith(b"COPY "):
                    m = _COPY.fullmatch(line)
                    if not m:
                        bad = "objects"
                        break
                    table = m.group(1).decode().strip('"')
                    if table in rows:
                        bad = "objects"
                        break
                    rows[table] = 0
                    kcols = bk_key_cols(table, line)
                    continue
                if line.startswith(b"\\"):  # psql meta commands: only the \restrict / \unrestrict pair of pg_dump 17.6+
                    if not re.fullmatch(rb"\\(un)?restrict [A-Za-z0-9]{1,128}\n", line):
                        bad = "objects"
                        break
                    continue
                ddl_n += len(line)
                if ddl_n > 64 * 1024 * 1024:
                    bad = "objects"
                    break
                ddl.append(line)
        finally:
            if bad:
                p.kill()
            p.stdout.close()
            rc = p.wait()
        if bad:
            raise BackupError(bad)
        if rc or table is not None:
            raise BackupError("integrity")
    try:
        sql = b"".join(ddl).decode("utf-8")
    except UnicodeDecodeError:
        raise BackupError("integrity") from None
    stmts = bk_statements(sql)
    if not any(s.startswith("CREATE TABLE public.users ") for s in stmts):
        raise BackupError("format")
    for s in stmts:
        if not bk_check_statement(s):
            print("restore: refused statement:", s[:200], flush=True)
            raise BackupError("objects")
    if not {"users", "lists", "tasks", "settings", "sessions", "attachments", "kalmido_meta"} <= set(rows):
        raise BackupError("format")
    sv = meta.get("schema_version", "")
    if not sv.isdigit():
        raise BackupError("format")
    if int(sv) > SCHEMA_VERSION:
        raise BackupError("schema", int(sv))
    return {"schema_version": int(sv), "rows": rows, "users": rows.get("users", 0), "key_rows": key_rows, "key_opens": key_opens,
            "secret_fp": meta.get(SKFP_KEY, "")}


def bk_prepare(path, pw, work, att_dest=None, office_dest=None, restore=False, pack_dest=None):
    """Checks an archive completely; extracts the dump into work (and the attachments into att_dest, the office files into
    office_dest, the own industry packs into pack_dest, if given) and reads it through once. Returns (manifest, dump path). A format-1 archive (SQLite, before
    2.37) is checked (members, checksums); 2.1034.0 (#5304): its restore is refused (the move tool is gone)."""
    zp, _ = bk_open(path, pw, work)
    try:
        with zipfile.ZipFile(zp) as z:
            man = bk_check_zip(z)
            if man["_legacy"] and restore:  # 2.1034.0 (#5304): before anything is extracted
                raise BackupError("legacy")
            dbp = os.path.join(work, BK_DUMP)
            for i in z.infolist():
                if i.filename == BK_DUMP:
                    bk_extract(z, i, dbp, man["_listed"])
                elif i.filename != "manifest.json":
                    m = BK_MEMBER_RE.fullmatch(i.filename)
                    pm = BK_PACK_RE.fullmatch(i.filename)
                    if pm and pack_dest is not None:  # 2.359.2 (#2895): flat, the name checked by BK_PACK_RE (no / and no leading dot)
                        bk_extract(z, i, os.path.join(pack_dest, pm.group(1)), man["_listed"])
                        continue
                    if att_dest is None or m is None:  # verify only (or the tasks.db of an old archive): hash, write nothing
                        want, h, n = man["_listed"][i.filename], hashlib.sha256(), 0
                        with z.open(i) as src:
                            for b in iter(lambda: src.read(BK_CHUNK), b""):
                                n += len(b)
                                if n > want[1]:
                                    raise BackupError("bomb")
                                h.update(b)
                        if n != want[1] or h.hexdigest() != want[2]:
                            raise BackupError("hash")
                        continue
                    base = office_dest if m.group(1) == "office" else att_dest
                    if base is None:  # (an office member, but the caller restores attachments only)
                        continue
                    d = os.path.join(base, m.group(2))
                    dest = os.path.join(d, m.group(3))
                    root = os.path.realpath(base) + os.sep
                    if not os.path.realpath(dest).startswith(root) or not os.path.realpath(d).startswith(root):
                        raise BackupError("members")
                    os.makedirs(d, mode=0o700 if base is office_dest else 0o755, exist_ok=True)  # 2.39.1 (#1210 N8): office 0700
                    bk_extract(z, i, dest, man["_listed"])
            if man["_shared"]:  # 2.432.0 (#3584): the files kept once in the store, checked like the members
                key = bk_store_key(man, pw)
                miss = bk_shared_missing(man, key)
                if miss:
                    raise BackupError("shared_missing", miss)
                for name, size, sha in man["_shared"]:
                    m = BK_MEMBER_RE.fullmatch(name)
                    base = None if att_dest is None else office_dest if m.group(1) == "office" else att_dest
                    if base is None:
                        for _ in bk_shared_chunks(key, sha, size):
                            pass
                        continue
                    d = os.path.join(base, m.group(2))
                    dest = os.path.join(d, m.group(3))
                    root = os.path.realpath(base) + os.sep
                    if not os.path.realpath(dest).startswith(root) or not os.path.realpath(d).startswith(root):
                        raise BackupError("members")
                    os.makedirs(d, mode=0o700 if base is office_dest else 0o755, exist_ok=True)
                    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
                    with os.fdopen(fd, "wb") as out:
                        for b in bk_shared_chunks(key, sha, size):
                            out.write(b)
    except zipfile.BadZipFile:
        raise BackupError("format") from None
    except (zipfile.LargeZipFile, NotImplementedError, EOFError):
        raise BackupError("format") from None
    if not man["_legacy"]:
        man["db"] = bk_scan_dump(dbp)
        man["key_state"] = bk_key_state(man)  # 2.359.3 (#2893)
    return man, dbp


def bk_store_key(man, pw):
    """2.432.0 (#3584): the store key of a format-3 manifest (None = plain store)."""
    st = man.get("store")
    if st == "plain":
        return None
    if not pw:
        raise BackupError("need_passphrase")
    return bks.key_from_desc(pw, st)


def bk_shared_chunks(key, sha, size):
    """The content of one shared file (bkstore.chunks) with the errors of this module."""
    try:
        yield from bks.chunks(BK_STORE, key, sha, size)
    except bks.StoreError as e:
        if e.code == "missing":
            raise BackupError("shared_missing", 1) from None
        raise BackupError("hash") from None


def bk_shared_missing(man, key):
    """How many shared files of a manifest are not in the store (checked before a download starts)."""
    n = 0
    for _, _, sha in man["_shared"]:
        try:
            bks.find(BK_STORE, bks.rel(key, sha))
        except bks.StoreError:
            n += 1
    return n


def bk_path(name):
    """Full path of a listed backup (strict name) or BackupError."""
    if not bk_parse_name(name):
        raise BackupError("not_found")
    p = os.path.join(BK_DIR, name)
    if os.path.islink(p) or not os.path.isfile(p):
        raise BackupError("not_found")
    return p


def bk_upload_path(uid):
    if not BK_UPLOAD_RE.fullmatch(uid or ""):
        raise BackupError("not_found")
    p = os.path.join(BK_DIR, ".uploads", uid)
    if os.path.islink(p) or not os.path.isfile(p):
        raise BackupError("not_found")
    return p


def _pool_renew():
    """After pg_restore: no pooled connection of before may keep cached state of the old tables (plans, OIDs); every
    idle one is closed now, a borrowed one when it comes back."""
    p = _pg._POOL.get("p")
    if p is not None:
        p.drain()


def _q(name):
    return '"' + name.replace('"', '""') + '"'


def _fk_list(c):
    """[(table, key, its definition)] of the foreign keys in the database (caller in system_ctx)."""
    return c.execute("""SELECT r.relname, k.conname, pg_get_constraintdef(k.oid) FROM pg_constraint k JOIN pg_class r ON r.oid=k.conrelid -- pg-ok: pg_catalog oid
                        JOIN pg_namespace n ON n.oid=r.relnamespace WHERE k.contype='f' AND n.nspname='public'""").fetchall()


def _fks_note(dropped):
    """2.510.0 (#4286): the keys _pg_restore takes away, on disk: nothing else knows them after a hard stop (fk_ensure and the
    column migrations only bring their own). A second call (the way back) adds to the list."""
    if not dropped:
        return
    try:
        with open(BK_DROPPED_FKS, encoding="utf-8") as f:
            dropped = json.load(f) + dropped
    except (OSError, ValueError):
        pass
    tmp = BK_DROPPED_FKS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dropped, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, BK_DROPPED_FKS)


def bk_fks_back():
    """2.510.0 (#4286): after a restore and at a server start: the keys _fks_note names come back unless the database has them
    (under this name or the same definition). Rows an older backup left without their target must not stop it: such a key
    holds for new rows only (NOT VALID) and the log says so. The caller makes sure no restore runs."""
    try:
        with open(BK_DROPPED_FKS, encoding="utf-8") as f:
            fks = json.load(f)
    except FileNotFoundError:
        return
    except (OSError, ValueError) as e:
        print("restore: the list of dropped foreign keys cannot be read:", type(e).__name__, flush=True)
        return
    c = _pg.connect_direct(DATABASE_URL)
    try:
        with _pg.system_ctx(c):  # the keys span every organisation (row-level security would hide the rows of the others)
            have = {x for t, k, d in _fk_list(c) for x in ((t, k), (t, d))}
        c.commit()
        for t, k, d in fks:
            if (t, k) in have or (t, d) in have:
                continue
            for how in ("", " NOT VALID"):
                try:
                    with _pg.system_ctx(c):  # the check of the key reads the rows of every organisation
                        c.execute(f"ALTER TABLE {_q(t)} ADD CONSTRAINT {_q(k)} {d}{how}")
                    c.commit()
                    if how:
                        print(f"restore: foreign key {t}.{k} back for new rows only: older rows have no target", flush=True)
                    break
                except Exception as e:  # a table or column this version no longer has, rows without a target
                    c.rollback()
                    if how:
                        print(f"restore: foreign key {t}.{k} did not come back:", db_log_err(e), flush=True)
    finally:
        c.close()
    os.unlink(BK_DROPPED_FKS)


def _pg_restore(dump):
    """pg_restore --clean of a checked dump into the running database, in ONE transaction (an error leaves it as it was),
    with the filtered table of contents only (bk_toc: no code from the dump; init_db creates it afterwards). Tables of this
    version that the dump does not have (a backup of an older version) lose their foreign keys first, so --clean cannot
    trip over them, and are dropped once the restore went through (2.273.0 A, #3050: before, they were dropped in an own
    transaction ahead of pg_restore - a stop in between left them empty); init_db creates them again, empty."""
    toc, tables = _toc_file(dump)
    if not {"users", "tasks", "kalmido_meta"} <= tables:  # (never drop anything on a list that was not understood)
        raise BackupError("format")
    # 2.510.0 (#4286): --clean only knows the foreign keys of the dump. One added since (a backup of an older version) would stop
    # it dropping the key it points at ("cannot drop constraint users_pkey"): such a backup could not be restored at all.
    # These go first like those of the tables the dump lacks; the dump brings its own, BK_DROPPED_FKS the rest (bk_fks_back)
    dump_fks = {(m.group(1), m.group(2)) for m in re.finditer(r"^\d+; \d+ \d+ FK CONSTRAINT public (\S+) (\S+) ", toc, re.M)}
    # #3506 (CI red of 2.614.0): taking the keys away needs the strongest lock on each table; work outside the maintenance
    # gate (as for pg_restore below) can hold a weaker one and wait for a table this transaction has: a deadlock rolls it
    # back completely (nothing dropped, nothing noted yet), so it is tried again like pg_restore instead of ending the restore
    for i in range(BK_RESTORE_TRIES):
        c = _pg.connect_direct(DATABASE_URL)
        try:
            with _pg.system_ctx(c):  # the restore works on the whole database (every organisation)
                c.execute("SET LOCAL statement_timeout = 0")
                extra = [r[0] for r in c.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
                         if r[0] not in tables]
                dropped = []
                for t, k, d in _fk_list(c):
                    if t in extra or (t, k) not in dump_fks:  # 2.273.0 A (#3050): only the keys now, the rows stay until pg_restore went through
                        if t not in extra:  # (the tables the dump lacks are built anew)
                            dropped.append([t, k, d])
                        c.execute(f"ALTER TABLE {_q(t)} DROP CONSTRAINT IF EXISTS {_q(k)}")
                _fks_note(dropped)  # before the commit: a key noted and still there costs nothing
            c.commit()
            break
        except Exception as e:
            if i + 1 >= BK_RESTORE_TRIES or getattr(e, "sqlstate", None) != "40P01":
                raise
            print(f"restore: deadlock while taking the keys away (nothing changed), try {i + 2} of {BK_RESTORE_TRIES}", flush=True)
            time.sleep(2 * (i + 1))
        finally:
            c.close()
    _pool_renew()
    try:
        # 2.209.0 E (#1627): work that runs outside the maintenance gate (queued work, pushes after a request) can meet
        # the restore's locks; a deadlock rolls the single transaction back completely, so the same run is tried again
        for i in range(BK_RESTORE_TRIES):
            try:
                _pg_run(["pg_restore", *_restore_args(toc), "--enable-row-security", "--exit-on-error",
                         "-d", bk_pg_env().get("PGDATABASE") or bk_pg_env().get("PGUSER") or "postgres", dump], err_code="restore")
                break
            except BackupError as e:
                raw = getattr(e, "raw", b"")
                if i + 1 >= BK_RESTORE_TRIES or not (b"deadlock detected" in raw or b"40P01" in raw):
                    raise
                print(f"restore: deadlock in pg_restore (nothing changed), try {i + 2} of {BK_RESTORE_TRIES}", flush=True)
                _pool_renew()
                time.sleep(2 * (i + 1))
        if extra:  # 2.273.0 A (#3050): the restore went through; the tables the backup does not have go now
            c = _pg.connect_direct(DATABASE_URL)
            try:
                with _pg.system_ctx(c):
                    c.execute("SET LOCAL statement_timeout = 0")
                    for t in extra:
                        c.execute('DROP TABLE IF EXISTS "' + t.replace('"', '""') + '" CASCADE')
                c.commit()
            finally:
                c.close()
            print("restore: dropped table(s) the backup does not have:", ", ".join(extra), flush=True)
    finally:
        _pool_renew()


def _reset_caches():
    """In-process state that belongs to the database (after a restore)."""
    for d in (_CAL_KEY, UNDO_KEY, _AUTH_KEY, _BK["meta"]):
        d.clear()
    acx_drop()  # 2.149.0 review: cached access contexts belong to the old database
    _VAPID.clear()
    eph_clear()  # 2.622.0 (#3891): sign-in steps, OIDC states, tickets of before (core/ephem.py) are gone with the old database
    oidc_reset()
    _DAV_INST.clear()
    with _DAV_CACHE_LOCK:
        _DAV_CACHE.clear()
    NEWS_CLEAN["at"] = 0.0


# ---- 2.152.0 B (#2172): the journal of deleted accounts. A backup still holds the accounts deleted after it was written;
# after a restore they are deleted again. Only salted hashes (HMAC-SHA-256, the instance's own salt in the settings key
# bk_journal_salt, which the restore keeps like every bk_ setting) and the account id are kept, never a plain address.
def bkr_hash(salt, v):
    v = (v or "").strip().lower()
    return hmac.new(salt.encode(), v.encode(), hashlib.sha256).hexdigest() if v else ""


def bkr_salt(c):
    salt = gsetting(c, "bk_journal_salt")
    if not salt:
        salt = secrets.token_hex(32)
        gset(c, "bk_journal_salt", salt)
    return salt


def bkr_journal(c, uid):
    """accounts/users.py user_purge: note the account before it goes (same transaction; the caller commits)."""
    u = c.execute("SELECT id, username, email FROM users WHERE id=?", (int(uid),)).fetchone()
    if not u:
        return
    salt = bkr_salt(c)
    eh, nh = bkr_hash(salt, u["email"]), bkr_hash(salt, u["username"])
    if not c.execute("SELECT 1 FROM deleted_accounts WHERE user_id=? AND username_hash=? AND email_hash=?", (u["id"], nh, eh)).fetchone():
        c.execute("INSERT INTO deleted_accounts(user_id, email_hash, username_hash, at) VALUES(?,?,?,?)", (u["id"], eh, nh, iso(now_utc())))


def bkr_read(c):
    """The journal before a restore (the restored database has an older one or none)."""
    try:
        with c.savepoint():
            return [tuple(r) for r in c.execute("SELECT user_id, email_hash, username_hash, at FROM deleted_accounts ORDER BY id")]
    except _pg.Error:  # a database from before 2.152 (no table yet)
        return []


# ---- 2.360.0 A (#2496): API tokens (agents' too) and app passwords revoked after the backup was written stay revoked.
# 2.360.0 R (#2496, review): by the list of what was revoked (revoked_creds, filled by a database trigger on every delete,
# core/schema.py REVOKED_TRIGGER), not by what is valid now: a restore onto a fresh server or of the safety backup keeps
# every token the backup holds. The list is read before and written back after (union with the backup's own list).
def bkr_creds_read(c):
    """The revoked token / app password hashes now [(hash, at)]; caller is in system_ctx."""
    try:
        with c.savepoint():  # 2.674.0 (#4028): + exp (core/migrations.d/4028_a.py), so the clean-up can still take the row later
            return [tuple(r) for r in c.execute("SELECT hash, at, exp FROM revoked_creds")]
    except _pg.Error:
        pass
    try:
        with c.savepoint():
            return [tuple(r) for r in c.execute("SELECT hash, at FROM revoked_creds")]
    except _pg.Error:  # a database from before 2.360 (no table yet): nothing to keep revoked
        return []


def bkr_creds_after(c, creds):
    """After pg_restore and init_db (system_ctx, caller commits): the list back, then the restored tokens / app
    passwords it names go again."""
    for h, at, *exp in creds:  # 2.674.0 (#4028): (hash, at, exp) or (hash, at) of a database before it
        c.execute("INSERT INTO revoked_creds(hash, at, exp) VALUES(?,?,?) ON CONFLICT (hash) DO NOTHING", (h, at, exp[0] if exp else None))
    for t, q in (("api_tokens", "DELETE FROM api_tokens WHERE token_hash IN (SELECT hash FROM revoked_creds)"),
                 ("app_passwords", "DELETE FROM app_passwords WHERE pw_hash IN (SELECT hash FROM revoked_creds)")):
        n = c.execute(q).rowcount  # plain statements: pg_prepare checks them
        if n:
            print(f"restore: {n} {t} revoked after the backup stay revoked", flush=True)
    # 2.488.0 (#3363, review F2): a hosted MCP access whose access token went above (revoked or rotated after the backup) ends
    # too: its refresh token of the backup's time must not hand out new tokens (agents/mcpremote.py; the table may be missing
    # in a database from before 2.488.0 only before init_db, which ran)
    n = c.execute("UPDATE oauth_grants SET revoked_at=COALESCE(revoked_at, ?), refresh_hash=NULL, prev_refresh_hash=NULL "
                  "WHERE revoked_at IS NULL AND (token_id IS NULL OR token_id NOT IN (SELECT id FROM api_tokens))",
                  (iso(now_utc()),)).rowcount
    if n:
        print(f"restore: {n} hosted MCP accesses ended (their token was revoked after the backup)", flush=True)


BKR_RECENT_DAYS = 7
BK_KEPT_NOTE = N_("You kept what the backup holds, accounts excepted: accounts deleted since the backup was written are deleted again. What lay in a trash in the backup is deleted again when its trash period is over: take it out of the trash now if it is to stay.")  # 2.505.0 (#4302); 2.538.0 (#4367): the accounts are no part of the choice


# ---- 2.360.4 (#3243): organisations and entries deleted for good after the backup was written stay deleted: by the list
# of what went (purged_rows, filled by a database trigger, core/schema.py PURGED_TRIGGER; read before, written back after).
# The account rule applies: what went in the last BKR_RECENT_DAYS days stays (the restore may be meant to bring it back,
# the admin learns the number); only the same row counts (same made-at time: ids are given out again after a restore).
def bkr_purged_read(c):
    """The list now [(table, id, at)]; caller is in system_ctx."""
    try:
        with c.savepoint():
            return [tuple(r) for r in c.execute("SELECT tbl, ref_id, made, at FROM purged_rows")]
    except _pg.Error:  # a database from before 2.360.4 (no table yet)
        return []


def bkr_purged_note(c, rows):
    c.executemany("INSERT INTO purged_rows(tbl, ref_id, made, at) VALUES(?,?,?,?) ON CONFLICT (tbl, ref_id) "
                  "DO UPDATE SET made=excluded.made, at=excluded.at", rows)


def bkr_purged_drop(c, tbl, rid):
    """Row rid of tbl goes again; -> the files for unlink_files. Stored files of tasks and projects go along; the other
    tables keep theirs in rows that cascade and in the storage sweep."""
    if tbl == "orgs":
        return odl_dismantle(c, rid)
    if tbl == "fs_nodes":
        from ..files.store import fs_purge, fs_purge_files
        ids, paths = fs_purge(c, rid)
        return [lambda: fs_purge_files(ids, paths)]
    if tbl == "lists":  # as the owner's delete: the tasks go to the trash of the inbox, what became of them has its own rows
        inbox = c.execute("SELECT i.id FROM lists i JOIN lists l ON l.owner_id=i.owner_id WHERE l.id=? AND i.is_inbox=1", (rid,)).fetchone()
        return list_purge(c, rid, inbox[0] if inbox else None)[1]
    files = []
    if tbl == "tasks":
        files = [r[0] for r in c.execute("""WITH RECURSIVE t(id) AS (SELECT id FROM tasks WHERE id=?
                                            UNION SELECT k.id FROM tasks k JOIN t ON k.parent_id=t.id)
                                            SELECT a.path FROM attachments a JOIN t ON t.id=a.task_id""", (rid,))]
    c.execute(f"DELETE FROM {tbl} WHERE id=?", (rid,))
    return files


def bkr_purged_preview(c, since):
    """2.505.0 (#4302): what a restore of a backup written at `since` would delete again, for the restore dialog (numbers
    only). A row counts when it went after the backup was written and was made before it (a backup cannot hold anything
    else); `since` empty (an archive without a date): every row. Caller is in system_ctx."""
    cut = iso(now_utc() - timedelta(days=BKR_RECENT_DAYS))
    kinds, recent, first, last = {}, 0, "", ""
    for tbl, _, made, at in bkr_purged_read(c):
        if since and (at < since or made > since):
            continue
        if at >= cut:
            recent += 1
            continue
        kinds[tbl] = kinds.get(tbl, 0) + 1
        first, last = min(first or at, at), max(last, at)
    accounts = sum(1 for r in bkr_read(c) if not since or (r[3] or "") >= since)
    return {"kinds": kinds, "total": sum(kinds.values()), "first": first, "last": last, "recent": recent,
            "recent_days": BKR_RECENT_DAYS, "accounts": accounts}


def bkr_purged_after(c, rows, keep=False):
    """After the accounts (own commits): the list back, then what the backup brought back goes one row at a time.
    2.505.0 (#4302): keep = the admin's choice in the restore dialog: everything stays and leaves the list (it lives again:
    a later restore must not take it). -> (deleted again, kept as deleted recently, could not be deleted, kept by choice)."""
    gone, recent, stuck, files, back = 0, 0, 0, [], []
    cut = iso(now_utc() - timedelta(days=BKR_RECENT_DAYS))
    with _pg.system_ctx(c):  # entries of every organisation; numbers only
        bkr_purged_note(c, rows)
        c.commit()
        for tbl in PURGED_TABLES:  # the big ones first: what goes with them needs no step of its own
            todo = {r[1]: r for r in rows if r[0] == tbl}
            ids = sorted(todo)
            here = []
            for i in range(0, len(ids), 1000):
                part = ids[i:i + 1000]
                here += [r[0] for r in c.execute(f"SELECT id, created_at FROM {tbl} WHERE id IN ({','.join('?' * len(part))})", part).fetchall()
                         if r[1] == todo[r[0]][2]]
            if keep:
                back += [(tbl, rid) for rid in here]
                continue
            for rid in here:
                at = todo[rid][3]
                if at >= cut:
                    recent += 1
                    continue
                if not c.execute(f"SELECT 1 FROM {tbl} WHERE id=?", (rid,)).fetchone():  # went with one before it
                    gone += 1  # 2.505.0 (#4302, review): counted as the dialog's preview did
                    continue
                try:
                    with c.savepoint():
                        files += bkr_purged_drop(c, tbl, rid)
                    c.commit()
                    gone += 1
                except Exception as e:  # noqa: BLE001 -- one row must not stop the others (a legal lock, a key that is gone)
                    c.rollback()
                    print("restore: deleting an entry again failed:", tbl, type(e).__name__, flush=True)
                    stuck += 1
        if back:
            c.executemany("DELETE FROM purged_rows WHERE tbl=? AND ref_id=?", back)
        else:
            bkr_purged_note(c, rows)  # the deletions just now noted their own time: the first one counts
        c.commit()
    unlink_files(files)
    return gone, recent, stuck, len(back)


def bkr_after_restore(c, rows):
    """After a restore: the journal written back as it was before, then every account the backup brought back that the
    journal names (same id, same user name or e-mail, created no later than it was deleted) goes again (user_purge). One that owns
    lists besides its inbox is only disabled (the lists were handed over or deleted at the time; which, the backup does not
    know): the admin decides. -> (deleted again, disabled as owners or after a failure, disabled as deleted recently; 2.186.0 C
    #2602: counted apart). The caller commits nothing: this function does."""
    with system_ctx(c):  # the journal and the accounts of every organisation; nothing is shown to a person
        c.execute("DELETE FROM deleted_accounts")
        for r in rows:
            c.execute("INSERT INTO deleted_accounts(user_id, email_hash, username_hash, at) VALUES(?,?,?,?)", r)
        c.commit()
        salt = gsetting(c, "bk_journal_salt") or ""
        if not rows or not salt:
            return 0, 0, 0
        gone, off, recent, files = 0, 0, 0, []
        for uid, eh, nh, at in rows:
            u = c.execute("SELECT * FROM users WHERE id=? AND created_at<=?", (uid, at)).fetchone()  # ISO text: same second = same account
            if not u or not ((nh and bkr_hash(salt, u["username"]) == nh) or (eh and bkr_hash(salt, u["email"]) == eh)):
                continue
            # review F7: an account deleted in the last BKR_RECENT_DAYS days is only disabled -- the restore may be meant to
            # bring exactly that account back; the admin deletes it again by hand otherwise
            owns = c.execute("SELECT COUNT(*) FROM lists WHERE owner_id=? AND is_inbox=0", (uid,)).fetchone()[0]
            if owns or (at or "") >= iso(now_utc() - timedelta(days=BKR_RECENT_DAYS)):
                c.execute("UPDATE users SET disabled=1 WHERE id=?", (uid,))
                c.commit()
                if owns:  # owning projects is the reason that holds without the period as well
                    off += 1
                else:
                    recent += 1
                continue
            try:
                with c.savepoint():
                    f = user_purge(c, uid)
                c.commit()
            except Exception as e:  # noqa: BLE001 -- one account must not stop the others; it is disabled instead
                c.rollback()
                print("restore: deleting an account again failed:", type(e).__name__, flush=True)
                c.execute("UPDATE users SET disabled=1 WHERE id=?", (uid,))
                c.commit()
                off += 1
                continue
            files += f
            gone += 1
    unlink_files(files)
    return gone, off, recent


_BK_RESEAL = {"bk_pass": "backup", "bko_sec": "backup-offsite"}  # 2.359.0 (#2894): kept settings sealed with auth_secret (offsite.BKO_SEAL)


def bk_own_mounts():
    """2.370.2 (#2779): the folders a restore swaps by a rename that are a mount of their own (the rename always fails there)."""
    if os.environ.get("KALMIDO_TEST") == "1" and os.environ.get("KALMIDO_TEST_BK_OWN_MOUNT"):  # tests only: a container has no second mount
        return [ATT_DIR]
    return [p for p in (ATT_DIR, OFFICE_DIR) if os.path.ismount(p)]


def bk_leftovers():
    """2.370.2 (#2779): folders of a restore next to the data folders: a hard stop left them behind, or a restore kept them
    for files the backup format does not cover. -> [(path, prefix of bk_outside)], the packs have their own rule."""
    out = []
    for base, prefix in ((ATT_DIR, "attachments/"), (OFFICE_DIR, "office/")):
        base = base.rstrip(os.sep)
        out += [(p, prefix) for p in sorted(glob.glob(glob.escape(base) + ".pre-restore-*") + glob.glob(glob.escape(base) + ".restore-*"))
                if os.path.isdir(p)]
    return out


def bk_leftovers_alert():
    """At the start of the server: an admin alert when such folders lie around (Backups in the settings names them too)."""
    left = [os.path.basename(p) for p, _ in bk_leftovers()]
    if left:
        print("restore: folders left from a restore:", ", ".join(left), flush=True)
        aa_now("storage", "restore:leftover", BK_LEFTOVER_NOTE, [", ".join(left)])


def bk_start_clean():
    """2.510.0 (#4286): what a hard stop of a restore or check left, from the server's own start only (app.py, never on the import:
    a helper such as `app.py set-password` also imports the package, beside a running restore): the keys it took away
    (bk_fks_back) and its work folder, the database as a plain dump, also next to encrypted backups. No restore runs while a server
    starts (it needs a single process); a check may on another process, so with several processes only one a day old goes."""
    from .worker import WRK_SINGLE
    single, day_ago = WRK_SINGLE, time.time() - 86400  # 2.642.0 (#4975): KALMIDO_WEB_PROCS counts like KALMIDO_REPLICAS
    for p in glob.glob(glob.escape(BK_DIR) + "/.restore-*"):
        shutil.rmtree(p, ignore_errors=True)
    for p in glob.glob(glob.escape(BK_DIR) + "/.verify-*"):
        if single or os.path.getmtime(p) < day_ago:
            shutil.rmtree(p, ignore_errors=True)
    bk_fks_back()


def bk_leftovers_clean(listed):
    """After a good restore: what is left from earlier ones goes, unless it holds files the archive does not bring (kept like
    the folder of before, never deleted unseen). An unfinished copy (.restore-) is nothing of value."""
    for p, prefix in bk_leftovers():
        left = bk_outside(p, prefix, listed) if ".pre-restore-" in os.path.basename(p) else {}
        if left:
            print(f"restore: kept {os.path.basename(p)}: files the backup format does not cover:", json.dumps(left, sort_keys=True), flush=True)
        else:
            shutil.rmtree(p, ignore_errors=True)


def bk_restore(path, pw, admin, via, keep_purged=False):
    """The whole restore (see the section comment). Returns (new session token or None, safety backup name).
    2.505.0 (#4302): keep_purged = what was deleted for good since the backup stays (the admin's choice, bkr_restore_journal)."""
    from .worker import WRK_SINGLE
    if not WRK_SINGLE:  # 2.148.1 C (#2482): other processes would keep writing during the swap (2.642.0 #4975: + KALMIDO_WEB_PROCS)
        raise BackupError("procs")
    if bk_own_mounts():  # 2.370.2 (#2779)
        raise BackupError("mounts")
    if not _BK_LOCK.acquire(blocking=False):
        raise BackupError("busy")
    _BK.update(running="restore", started=time.time())
    work = tempfile.mkdtemp(prefix=".restore-", dir=BK_DIR)
    att_new = ATT_DIR.rstrip(os.sep) + ".restore-" + secrets.token_hex(4)
    att_old = ATT_DIR.rstrip(os.sep) + ".pre-restore-" + secrets.token_hex(4)
    off_new = OFFICE_DIR.rstrip(os.sep) + ".restore-" + secrets.token_hex(4)
    off_old = OFFICE_DIR.rstrip(os.sep) + ".pre-restore-" + secrets.token_hex(4)
    gate = False
    try:
        os.makedirs(att_new, mode=0o755)
        os.makedirs(off_new, mode=0o700)  # 2.39.1 (#1210 N8)
        pack_new = os.path.join(work, "packs")  # 2.359.2 (#2895)
        os.makedirs(pack_new, mode=0o755)
        rlock = bk_read_lock()  # 2.525.0 (#4303): no clean-up of the store (worker process) while its shared files are read
        try:
            man, dbp = bk_prepare(path, pw, work, att_new, off_new, restore=True, pack_dest=pack_new)
        finally:
            bks.unlock(rlock)
        kstate = man.get("key_state", "ok")
        if kstate == "foreign" and not env_bool("KALMIDO_SECRET_KEY_CHANGED", False):  # 2.359.3 (#2893): before anything changes
            raise BackupError("server_key" if SECRET_KEY else "server_key_none")
        cur = connect()
        try:
            keep = {r[0]: r[1] for r in cur.execute("SELECT key, value FROM settings WHERE key ILIKE 'bk\\_%' ESCAPE '\\' OR key ILIKE 'bko\\_%' ESCAPE '\\'")}  # 2.223.2 C (#2871): bko_ = the off-site target
            # 2.359.0 (#2894): the passphrase and the off-site secrets are sealed with this instance's auth_secret, but the
            # restore brings the auth_secret of the backup: open them now, seal them again with the restored one below
            plain = {}
            for k, purpose in _BK_RESEAL.items():
                try:
                    plain[k] = unseal(cur, purpose, keep.get(k) or "")
                except (InvalidTag, ValueError):
                    pass  # unreadable already: kept as it is (the settings page asks for it again)
            ver = int(gsetting(cur, "version") or 0)
            journal = bkr_read(cur)  # 2.152.0 B (#2172)
            # 2.273.0 A (#3051 p. 12): the queue is never in a backup (#2220): what waits now is gone after the restore
            with _pg.system_ctx(cur):
                jobs = cur.execute("SELECT count(*) FROM bg_jobs WHERE state IN ('wait','run')").fetchone()[0]
                creds = bkr_creds_read(cur)  # 2.360.0 A (#2496)
                purged = bkr_purged_read(cur)  # 2.360.4 (#3243)
        finally:
            cur.close()
        if not GATE.begin(own=1, timeout=60):
            raise BackupError("maint")
        gate = True
        pre = os.path.join(work, "pre-restore.dump")  # the current database, for a rollback if anything below fails
        safety = bk_create("safety", keep_dump=pre)
        moved = aswapped = swapped = omoved = oswapped = False
        try:
            if os.path.isdir(ATT_DIR):
                os.rename(ATT_DIR, att_old)
                moved = True
            os.rename(att_new, ATT_DIR)
            aswapped = True
            if os.path.isdir(OFFICE_DIR):
                os.rename(OFFICE_DIR, off_old)
                omoved = True
            os.rename(off_new, OFFICE_DIR)
            oswapped = True
            swapped = True  # (from here on a failure restores the dump of before; pg_restore itself is all or nothing)
            _pg_restore(dbp)  # 2.1034.0 (#5304): a format-1 archive never gets here (bk_prepare refuses it)
            _reset_caches()
            init_db(guard=False)
            c = connect()
            try:
                with _pg.system_ctx(c):  # every session of every organisation ends
                    for k, v in keep.items():  # the backup settings stay as they are now (not the ones in the backup)
                        gset(c, k, seal(c, _BK_RESEAL[k], plain[k]) if plain.get(k) else v)  # 2.359.0 (#2894)
                    # 2.359.2 (#2892): what this instance did not have goes too - a production backup restored on a fresh test
                    # instance brought its off-site target and credentials along (uploads + keep-N pruning at production's target)
                    for r in c.execute("SELECT key FROM settings WHERE key ILIKE 'bk\\_%' ESCAPE '\\' OR key ILIKE 'bko\\_%' ESCAPE '\\'").fetchall():
                        if r[0] not in keep:
                            c.execute("DELETE FROM settings WHERE key=?", (r[0],))
                    gset(c, "version", max(ver, int(gsetting(c, "version") or 0)) + 1)
                    c.execute("DELETE FROM sessions")
                    c.execute("DELETE FROM push_subs WHERE session_hash<>''")  # 2.190.0 R (#1991): their sessions ended just now
                    bkr_creds_after(c, creds)  # 2.360.0 A (#2496): what was revoked since the backup stays revoked
                    tok = None
                    u = c.execute("SELECT * FROM users WHERE username=? AND is_admin=1 AND disabled=0", (admin,)).fetchone()
                    if u and via == "session":
                        tok, _ = start_session(c, u["id"], True, "restore")  # 2.144.5 A2 (#2387, review R2): no password typed
                c.commit()
                # 2.1073.0 (#5865, Fable review F3): a backup from before 2.1067 brings office_trash with copies back: back
                # into the core's trash, then the table goes, as at a start (never fails the restore)
                try:
                    from ..office.okern import ofk_trash_retire
                    n = ofk_trash_retire(c)
                    if n["dropped"] is not None or n["held"]:
                        print(f"restore: office trash copies back {n['back']}, held {n['held']}, table dropped: {n['dropped'] is not None}", flush=True)
                except Exception as e:  # noqa: BLE001
                    c.rollback()
                    print("restore: office trash copies back FAILED, the table stays (the next start tries again):", type(e).__name__, flush=True)
            finally:
                c.close()
        except Exception:
            back_failed = False
            if swapped:
                try:
                    _pg_restore(pre)
                    _reset_caches()
                    init_db(guard=False)
                except Exception as e2:  # noqa: BLE001 -- the original error is the one to report
                    back_failed = True  # 2.273.0 A (#3050): never "nothing was changed" then
                    print("restore: rolling back to the state before FAILED:", type(e2).__name__, getattr(e2, "args_", e2),
                          f"(the safety backup {safety} holds it)", flush=True)
            if aswapped:  # 2.370.2 (#2779): also on a fresh instance (nothing moved), and the old folder back when the new one never came in
                os.rename(ATT_DIR, att_new)
            if moved:
                os.rename(att_old, ATT_DIR)
            if oswapped:
                os.rename(OFFICE_DIR, off_new)
            if omoved:
                os.rename(off_old, OFFICE_DIR)
            if back_failed:  # 2.510.0 (#4286): without init_db the tables have no rights, policies and triggers: nothing may run on them
                GATE.broken = True  # (the gate stays shut and /api/health says so, a restart ends it and brings bk_fks_back)
                raise BackupError("rollback", safety) from None
            raise
        bk_leftovers_clean(man["_listed"])  # 2.148.1 C (#2482): files outside the archive format stay in the folder of before; 2.370.2 (#2779): also older leftovers
        bk_restore_packs(pack_new)  # 2.359.2 (#2895)
        print(f"restore: {os.path.basename(path)} restored by an admin (safety backup {safety})", flush=True)  # 2.239.0 B (#2888): no name in the log
        man["_again"] = bkr_restore_journal(journal, purged, keep_purged, admin)  # 2.152.0 B (#2172)
        if kstate != "ok":  # 2.359.3 (#2893)
            print(f"restore: server key check: {kstate}", flush=True)
            aa_now("security", f"restore-key:{int(time.time())}", BK_KEY_WARN[kstate], [])
        # 2.273.0 A (#3051 p. 12, 13): what a restore cannot bring back, in the result and the log
        man["_notes"] = ([(N_("{0} waiting background jobs were not restored (a backup never holds them): start what is still needed again."), jobs)]
                         if jobs else []) + [(BK_OFFLINE_NOTE,)] + ([(BK_KEPT_NOTE,)] if keep_purged else [])  # 2.505.0 (#4302)
        print(f"restore: {jobs} waiting background job(s) not restored; devices may send unsent changes after reloading", flush=True)
        aa_now("security", f"restore:{int(time.time())}", N_("{0} restored a backup from {1} (safety backup of the previous state: {2})."),
               [admin, str(man.get("created_at", "?"))[:16].replace("T", " ") + " UTC", safety])
        return tok, safety, man
    except BackupError:
        raise
    except Exception as e:  # noqa: BLE001
        print("restore failed:", db_log_err(e), flush=True)
        raise BackupError("restore", str(e)[:300] if type(e).__name__ == "MigError" else type(e).__name__) from None
    finally:
        if gate and not GATE.broken:
            try:
                bk_fks_back()
            except Exception as e:  # the answer of the restore stands; the list stays for the next start
                print("restore: foreign keys not back yet:", db_log_err(e), flush=True)
            GATE.end()
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(att_new, ignore_errors=True)
        shutil.rmtree(off_new, ignore_errors=True)
        _BK.update(running="", started=0.0)
        _BK_LOCK.release()


def bk_restore_packs(src):
    """2.359.2 (#2895): the own industry packs of the backup into the data folder (after the database is back). A pack added
    since the backup stays; one the backup replaces with other content is kept in packs/industry.pre-restore-<hex>/ (never
    deleted unseen). Never fails the restore (the log names a failure)."""
    names = sorted(os.listdir(src)) if os.path.isdir(src) else []
    if not names:
        return 0
    dest = bk_pack_dir()
    old = dest.rstrip(os.sep) + ".pre-restore-" + secrets.token_hex(4)
    n = 0
    try:
        os.makedirs(dest, mode=0o755, exist_ok=True)
        for fn in names:
            d = os.path.join(dest, fn)
            if os.path.lexists(d) and os.path.isfile(d) and not os.path.islink(d) and _sha256_file(d) == _sha256_file(os.path.join(src, fn)):
                continue
            tmp = os.path.join(dest, "." + fn + ".restore")  # first next to it: a failed copy never leaves the pack missing
            shutil.copyfile(os.path.join(src, fn), tmp)
            if os.path.lexists(d):
                os.makedirs(old, mode=0o755, exist_ok=True)
                shutil.copy2(d, os.path.join(old, fn), follow_symlinks=False)
            os.replace(tmp, d)
            n += 1
    except OSError as e:
        print("restore: the industry packs could not all be written back:", aa_oserr(e), flush=True)
    if os.path.isdir(old):
        print(f"restore: kept {os.path.basename(old)}: industry packs the backup replaced", flush=True)
    return n


def bkr_restore_journal(journal, purged=(), keep=False, admin=""):
    """bkr_after_restore with its own connection, its numbers in the log and as an admin alert; never fails the restore.
    2.360.4 (#3243): then what purged names (bkr_purged_after), with numbers of its own.
    2.505.0 (#4302): keep = the admin chose to keep what was deleted for good; the choice is in the log and the alert either way."""
    try:
        c = connect()
        try:
            gone, off, recent = bkr_after_restore(c, journal)
            pgone, precent, pstuck, pkept = bkr_purged_after(c, purged, keep)
        finally:
            c.close()
    except Exception as e:  # noqa: BLE001 -- the restore itself is done; the admin learns it from the alert
        print("restore: the journal of deleted accounts could not be applied:", type(e).__name__, flush=True)
        aa_now("security", f"restore-journal:{int(time.time())}", N_("After the restore, the accounts deleted earlier could not be deleted again; check the server log."), [])
        return {"deleted": 0, "disabled": 0, "failed": True}
    if gone or off or recent:  # 2.186.0 C (#2602): the recently deleted ones apart from the owners of projects
        print(f"restore: accounts deleted earlier: {gone} deleted again, {off} disabled (they own lists), "
              f"{recent} disabled (deleted in the last {BKR_RECENT_DAYS} days)", flush=True)
        aa_now("security", f"restore-journal:{int(time.time())}",
               N_("After the restore, {0} accounts deleted earlier were deleted again; {1} that own projects were disabled; {2} deleted in the last {3} days were disabled, in case the restore was meant to bring them back (delete them in the user administration otherwise)."),
               [str(gone), str(off), str(recent), str(BKR_RECENT_DAYS)])
    if keep:  # 2.505.0 (#4302): also when the backup held none of them: the choice was made
        print(f"restore: entries deleted earlier: {pkept} kept (choice: keep everything)", flush=True)
        aa_now("security", f"restore-purged:{int(time.time())}",
               N_("{0} chose to keep everything in the restored backup: {1} organisations and entries deleted earlier came back and stay."),
               [admin, str(pkept)])
    elif pgone or precent or pstuck:
        print(f"restore: entries deleted earlier: {pgone} deleted again, {precent} kept (deleted in the last {BKR_RECENT_DAYS} days), "
              f"{pstuck} could not be deleted (choice: delete again)", flush=True)
        aa_now("security", f"restore-purged:{int(time.time())}",
               N_("After the restore (choice: delete again), {0} organisations and entries deleted earlier were deleted again; {1} deleted in the last {2} days stay, in case the restore was meant to bring them back; {3} could not be deleted again (see the server log)."),
               [str(pgone), str(precent), str(BKR_RECENT_DAYS), str(pstuck)])
    return {"deleted": gone, "disabled": off + recent, "owners": off, "recent": recent,
            "entries": pgone, "entries_recent": precent, "entries_failed": pstuck, "entries_kept": pkept}


# ---- API (admins; CSRF header on every change)
def bk_weekly_max():
    """2.186.0 C (#2602): weekly backups are capped at BK_KEEP_WEEKLY_MAX only while ret_on("backups") (as bk_prune reads it)."""
    return BK_KEEP_WEEKLY_MAX if bk_ret_on("backups") else BK_KEEP_WEEKLY_CAP


def bk_state(c):
    items = bk_list()
    store = bks.usage(BK_STORE)
    return {"env": BK_ON_ENV, "dir": BK_DIR, "on": gsetting(c, "bk_on") == "1", "time": gsetting(c, "bk_time"),
            "keep_daily": _clamp_int(gsetting(c, "bk_keep_daily"), 1, 365, 14), "keep_weekly": _clamp_int(gsetting(c, "bk_keep_weekly"), 0, bk_weekly_max(), 8),
            "encrypt": gsetting(c, "bk_encrypt") == "1", "passphrase_set": bool(bk_passphrase(c)), "passphrase_env": bool(BK_PASS_ENV),
            "last_ok": gsetting(c, "bk_last_ok"), "last_name": gsetting(c, "bk_last_name"), "last_error": gsetting(c, "bk_last_error"),
            "last_error_at": gsetting(c, "bk_last_error_at"),
            "running": _BK["running"] or ("manual" if bgj_pending(c, "backup") else ""),  # 2.193.0 D (#2220): also queued / in the worker
            "confirm_word": BK_CONFIRM, "leftovers": [os.path.basename(p) for p, _ in bk_leftovers()],  # 2.370.2 (#2779)
            "total_bytes": sum(x["size"] for x in items) + store[1], "free_bytes": aa_disk().get("free"),
            "store_files": store[0], "store_bytes": store[1],  # 2.432.0 (#3584): the shared store (one line in the list)
            "max_mb": BK_MAX_BYTES // 1048576, "items": [bk_public(x) for x in items],
            # 2.152.0 B (#2172): the limits the admin view explains
            "encrypt_required": BK_ENCRYPT_REQUIRED, "keep_weekly_max": bk_weekly_max()}  # 2.306.0 G (#2946): always set


def need_backups():
    need_admin()
    if not BK_ON_ENV:
        raise Denied(404, tr("Backups are switched off on this server (KALMIDO_BACKUPS=0)"))


# 2.13.0: Settings > Administration > "Check storage": every task attachment and project file whose file is missing,
# empty or of another size than recorded (e.g. after copying the data folder to another machine). Read-only.
@app.get("/api/admin/storage-check")
def storage_check():
    need_admin()
    c, out, n = db(), [], 0
    from .hosting import hosted
    apart = hosted()
    for kind, sql in (("attachment", "SELECT a.id, a.task_id AS owner, a.name, a.size, a.path, t.title AS where_ FROM attachments a "
                                     "LEFT JOIN tasks t ON t.id=a.task_id"),
                      ("list_file", "SELECT f.id, f.list_id AS owner, f.name, f.size, f.path, l.name AS where_ FROM list_files f "
                                    "LEFT JOIN lists l ON l.id=f.list_id"),
                      # 2.13.1 (#465): files in the agent chats (where = the agent's name)
                      ("chat_file", "SELECT f.id, m.agent_id AS owner, f.name, f.size, f.path, u.display_name AS where_ FROM chat_files f "
                                    "JOIN agent_chat m ON m.id=f.message_id LEFT JOIN users u ON u.id=m.agent_id"),
                      # 2.72.0 (#1333): receipts of the household budget (where = the budget list's name)
                      ("budget_file", "SELECT f.id, f.list_id AS owner, f.name, f.size, f.path, l.name AS where_ FROM budget_files f "
                                      "LEFT JOIN lists l ON l.id=f.list_id"),
                      # 2.99.0 A (#2182): files of knowledge pages (where = the page's name; a locked space's name is a ciphertext)
                      ("wiki_file", "SELECT f.id, f.page_id AS owner, f.name, f.size, f.path, CASE WHEN left(p.path, 5)='e2e1:' THEN '' "
                                    "ELSE p.path END AS where_ FROM wiki_files f LEFT JOIN wiki_pages p ON p.id=f.page_id"),
                      # 2.124.0 B (#2110): files of table cells (where = the table's title)
                      ("sheet_file", "SELECT f.id, f.sheet_id AS owner, f.name, f.size, f.path, s.title AS where_ FROM sheet_files f "
                                     "LEFT JOIN sheets s ON s.id=f.sheet_id"),
                      # 2.113.1 (#2059): files in the team chat (where = the conversation's name)
                      ("team_file", "SELECT f.id, f.room_id AS owner, f.name, f.size, f.path, r.name AS where_ FROM tchat_files f "
                                    "LEFT JOIN tchat_rooms r ON r.id=f.room_id")):
        for r in c.execute(sql):
            n += 1
            full = os.path.join(ATT_DIR, r["path"] or "")
            disk = oc_plain_size(full) if r["path"] and os.path.isfile(full) else None  # 2.42.0 (#828): sealed = plain size
            if disk is None or (r["size"] and disk != r["size"]):
                out.append({"kind": kind, "id": r["id"], "owner": r["owner"], "where": "" if apart else r["where_"] or "",
                            "name": "" if apart else r["name"],  # 2.399.0 (#2687): hosted: numbers only, no titles / file names
                            "size": r["size"], "disk": disk, "problem": "missing" if disk is None else "empty" if not disk else "size"})
    return jsonify(checked=n, problems=out)


@app.get("/api/admin/backups")
def backups_get():
    need_backups()
    return jsonify(bk_state(db()))


@app.patch("/api/admin/backups")
def backups_settings():
    need_backups()
    c, b = db(), body()
    was_on = gsetting(c, "bk_on") == "1"
    for k in ("on", "encrypt"):
        if k in b and not isinstance(b[k], bool):
            return err(tr("Invalid value: {0}", k))
    if "time" in b and not valid_hm(b["time"]):
        return err(tr("Invalid value: {0}", "time"))
    for k, lo, hi in (("keep_daily", 1, 365), ("keep_weekly", 0, 520)):
        if k in b and (isinstance(b[k], bool) or not isinstance(b[k], int) or not lo <= b[k] <= hi):
            return err(tr("Invalid value: {0}", k))
    if "keep_weekly" in b:  # 2.306.0 G (#2946): older clients may still send up to 520 weeks: the server caps them (104, or 52 with the switch)
        b["keep_weekly"] = min(b["keep_weekly"], bk_weekly_max())  # 2.186.0 C (#2602): only with the switch
    if "passphrase" in b:
        pw = b["passphrase"]
        if not isinstance(pw, str) or (pw and not 10 <= len(pw) <= 200):
            return err(BK_ERR_TEXT("no_passphrase"))
        if pw:
            gset(c, "bk_pass", seal(c, "backup", pw))
    if b.get("encrypt") and not bk_passphrase(c):
        c.rollback()
        return err(BK_ERR_TEXT("no_passphrase"))
    for k, sk in (("on", "bk_on"), ("encrypt", "bk_encrypt")):
        if k in b:
            gset(c, sk, "1" if b[k] else "0")
    for k in ("time", "keep_daily", "keep_weekly"):
        if k in b:
            gset(c, "bk_" + k, str(b[k]))
    if b.get("on") and not was_on:
        gset(c, "bk_enabled_at", iso(now_utc()))
        if gsetting(c, "bk_time") <= local_now().strftime("%H:%M"):
            gset(c, "bk_last_day", local_now().date().isoformat())  # today's time is over: the first one runs tomorrow
        _BK["stale_at"] = 0.0  # 2.45.0 (#1515): switched on again: the "no backup for 2 days" check runs at once (on since the setup)
    c.commit()
    if "on" in b and b["on"] != was_on:
        aa_switch(c, g.user, "bk_on", b["on"])
    return jsonify(bk_state(c))


def BK_ERR_TEXT(code, *a):
    return tr(BK_ERR[code], *a)


BKPC_TRIES, BKPC_WINDOW = 5, 15 * 60  # 2.581.0 (#4826): tries of "Check passphrase" per account in the window (seconds)
BKPC_OK, BKPC_NO = N_("{0} checked the backup passphrase: it matches."), N_("{0} checked the backup passphrase: it does not match.")


@app.post("/api/admin/backups/passphrase-check")
def backups_passphrase_check():
    """2.581.0 (#4826): {passphrase} -> {ok: true|false}: does the typed passphrase match the one for new backups
    (bk_passphrase: KALMIDO_BACKUP_PASSPHRASE before the stored one)? The instance admin only (need_backups), behind the
    step-up (offsite.py stepup_need, as restore and download), at most BKPC_TRIES tries per account in BKPC_WINDOW (429; the
    shared counter of api/common.py hit_limit, counted after the step-up so asking for the password costs no try),
    compared in constant time (hmac.compare_digest). No passphrase set: 409 code no_passphrase. The answer and the admin
    log (admin alerts, "security") carry only matches / does not match -- never the value or a part of it."""
    from .offsite import stepup_need
    need_backups()
    c, b = db(), body()
    b = b if isinstance(b, dict) else {}
    e = stepup_need(c, b, proxy_ok=True)
    if e is not None:
        return e
    uid = g.user["id"]
    pw = b.get("passphrase")
    try:  # 2.581.0 (#4826, review): a lone surrogate from JSON cannot be encoded - 400, not a 500; bad input costs no try
        pwb = pw.encode() if isinstance(pw, str) and pw and len(pw) <= 200 else None
    except UnicodeEncodeError:
        pwb = None
    if pwb is None:
        return err(tr("Invalid value: {0}", "passphrase"))
    if hit_limit(f"bkpc:{uid}", BKPC_TRIES, BKPC_WINDOW):
        return jsonify(error=tr("Too many attempts, please wait a few minutes"), code="rate"), 429
    cur = bk_passphrase(c)
    if not cur:
        return jsonify(error=tr("No backup passphrase is set yet."), code="no_passphrase"), 409
    ok = hmac.compare_digest(pwb, cur.encode())
    # the own harmless check is not pushed to oneself; one that does not match goes to every admin (a stolen session guessing)
    aa_now("security", f"bk-passcheck:{uid}:{time.time_ns()}", BKPC_OK if ok else BKPC_NO, [g.user["username"]], skip=uid if ok else None)
    return jsonify(ok=ok)


@app.post("/api/admin/backups")
def backups_now():
    """Back up now (in the background; the list shows it when done)."""
    need_backups()
    if _BK["running"] or bgj_pending(db(), "backup"):  # 2.193.0 D (#2220): one waiting in the queue counts too
        raise BackupError("busy")
    bgj_add("backup", "manual", once=True)  # 2.193.0 D (#2220): the queue in the database (the worker runs it)
    time.sleep(0.05)
    return jsonify(ok=True, **bk_state(db())), 202


@app.get("/api/admin/backups/<name>/download")
@app.post("/api/admin/backups/<name>/download")  # 2.360.0 A (#2496): POST = the step-up -> a ticket for the GET
def backups_download(name):
    from .offsite import stepup_download
    need_backups()
    from .hosting import hosted
    if hosted():  # 2.399.0 (#2687): a backup holds every client's content: on a hosted instance it stays on the server / offsite
        raise Denied(403, tr("On a hosted instance a backup is not downloaded in the app: it holds the content of every client (it stays on the server and its offsite copy)"))
    p = bk_path(name)
    enc = bool(bk_parse_name(name)["encrypted"])
    fmt3 = bk_meta(p, enc).get("format_version") == 3
    # 2.525.0 (#4303): a clean-up of the store runs: "store_busy" already on the POST (the dialog says it), not a broken file.
    # 2.644.0 (#4530): taken ONCE before the step-up and handed on: a clean-up that starts between a check and the download
    # can no longer use up the one-time ticket of the GET and then answer busy (the ticket stays for the next try)
    rlock = bk_read_lock() if fmt3 else None
    try:
        e = stepup_download(db(), proxy_ok=True, ticket=(lambda: bk_download_pass(p)) if enc and fmt3 else None)
        if e is None and fmt3:  # 2.432.0 (#3584): put together from the store, a complete file; it owns the lock from here
            pw = (g.sudl.get("passphrase") or bk_passphrase(db())) if enc else ""
            bk_test_gate("KALMIDO_TEST_BK_DL_TICKET_GATE")  # tests only: a clean-up tries to start here (it may not)
            lk, rlock = rlock, None
            return bk_download_assembled(p, name, enc, pw, rlock=lk)
    finally:
        bks.unlock(rlock)
    if e is not None:
        return e
    return send_file(p, as_attachment=True, download_name=name, mimetype="application/octet-stream",
                     conditional=False, max_age=0)


def bk_download_pass(p):
    """2.446.0 (#3613): the passphrase of the POST (behind the step-up): the download of a format-3 backup opens it, so
    the one that fits is asked for here, in JSON, and not on the GET of the browser. {passphrase?} goes into the ticket:
    only an earlier one the person typed in, in memory until the GET; the download stays encrypted with it."""
    given = str(body().get("passphrase") or "")
    pw = given or bk_passphrase(db())
    if not pw:
        raise BackupError("need_passphrase")
    work = tempfile.mkdtemp(prefix=".tmp-dl-", dir=BK_DIR)
    try:
        bk_decrypt(p, os.path.join(work, "archive.zip"), pw)
    except BackupError as e:
        raise bk_old_pass(e, given, True) from None  # 2.525.0 (#4303): the same rule as check and restore
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {"passphrase": given} if given else {}


def bk_download_assembled(p, name, enc, pw, rlock=None):
    """2.432.0 (#3584): the download of a format-3 backup is ONE complete archive of format 2 (every file inside, as
    every version can restore it), streamed while it is put together: the shared files come out of the store (checked
    against their SHA-256), an encrypted backup is encrypted again with the same passphrase. Nothing lands on the disk
    but the small zip of the backup (decrypted into a work folder that goes at the end).
    2.525.0 (#4303): it holds the readers' lock (bk_read_lock) from the start to the last byte, so the rotation or a
    delete meanwhile removes none of its store files (that clean-up runs next time); while a clean-up runs: "busy" (409).
    The lock goes with the end of the stream, an error, or a client that went away (also before the first byte).
    2.644.0 (#4530): rlock = the lock backups_download took before the ticket was used (this function owns it from the call)."""
    work = tempfile.mkdtemp(prefix=".tmp-dl-", dir=BK_DIR)
    held = {"z": None}

    def release():  # once: from the generator's finally or the response's close, whichever comes first
        if held.get("done"):
            return
        held["done"] = True
        if held["z"] is not None:
            held["z"].close()
        shutil.rmtree(work, ignore_errors=True)
        bks.unlock(rlock)
    try:
        head = None
        if enc:
            if not pw:
                raise BackupError("need_passphrase")
            zp = os.path.join(work, "archive.zip")
            try:
                head = bk_decrypt(p, zp, pw)
            except BackupError as e:
                raise BackupError("old_passphrase" if e.code == "passphrase" else e.code, *e.args_) from None
        else:
            zp = p
        z = held["z"] = zipfile.ZipFile(zp)
        man = bk_check_zip(z, space=False)
        key = bk_store_key(man, pw)
        miss = bk_shared_missing(man, key)
        if miss:
            raise BackupError("shared_missing", miss)
    except zipfile.BadZipFile:
        release()
        raise BackupError("format") from None
    except BaseException:
        release()
        raise

    def opener(sha, size):
        bk_test_gate()
        return bk_shared_chunks(key, sha, size)

    def gen():
        pipe = bks.Pipe()
        try:
            meta = {k: v for k, v in (head or {}).get("meta", {}).items() if k not in ("store", "shared_files", "shared_bytes", "store_new_bytes")}
            sink = bks.EncWriter(pipe, pw, {**meta, "format_version": 2}, {k: head[k] for k in ("n", "r", "p")}) if enc else pipe
            for _ in bks.assemble(z, man, sink, opener):
                b = pipe.drain()
                if b:
                    yield b
            if enc:
                sink.close()
            yield pipe.drain()
        except BackupError as e:  # the stream breaks off: the file is incomplete (a restore of it refuses it)
            print("backup download broken off:", e.text("en"), flush=True)
            raise
        finally:
            release()
    resp = Response(gen(), mimetype="application/octet-stream", headers={
        "Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})
    resp.call_on_close(release)  # a generator that never started has no finally
    return resp


@app.delete("/api/admin/backups/<name>")
def backups_delete(name):
    need_backups()
    p = bk_path(name)
    if _BK["running"]:
        raise BackupError("busy")
    os.remove(p)
    _BK["meta"].pop(name, None)
    if _BK_LOCK.acquire(blocking=False):  # 2.432.0 (#3584): its shared files go when no other backup needs them
        try:
            bk_store_gc(db())
        finally:
            _BK_LOCK.release()
    return jsonify(bk_state(db()))


def bk_old_pass(e, given, own):
    """2.525.0 (#4303): the saved passphrase does not open one of the server's own backups -> "old_passphrase" (it was
    made with an earlier one; check and restore say it as the download does since #3613). A typed-in passphrase that
    does not fit, an uploaded archive or a file that breaks off after its first chunk stays "passphrase" (wrong or damaged)."""
    return BackupError("old_passphrase") if e.code == "passphrase" and getattr(e, "first", False) and not given and own else e


def bk_key_warning(man):
    t = BK_KEY_WARN.get(man.get("key_state", "ok"))
    return tr(t) if t else ""


@app.post("/api/admin/backups/<name>/verify")
def backups_verify(name):
    """Full check without changing anything: decrypt, member list, every checksum, database integrity."""
    need_backups()
    c = db()
    if name.startswith("upload-"):
        bk_no_upload_hosted()  # 2.480.0 review (#3944, F6): hosted -> no uploaded archive at all
    own = not name.startswith("upload-")
    p = bk_path(name) if own else bk_upload_path(name)
    given = str(body().get("passphrase") or "")
    keys = _rate_keys(g.user["username"])
    if given:  # 2.644.0 (#4530): a typed-in passphrase is a guess, as on the restore: the same gate and counter
        e = login_wait(keys, g.user["username"])
        if e:
            return e
    pw = given or bk_passphrase(c)
    # 2.525.0 (#4303): no clean-up of the store while its shared files are checked. 2.644.0 (#4530): only an own format-3
    # backup reads the store; an uploaded or format-2 one checks without holding the lock (a clean-up is not held up).
    # 2.944.0 (#5054): the lock goes by format, not by origin: an uploaded format-3 archive reads the store as well (else a
    # clean-up meanwhile answers "shared_missing" instead of store_busy); format 2 still checks without it
    if own:
        fmt3 = bk_meta(p, bool(bk_parse_name(name)["encrypted"])).get("format_version") == 3
    else:  # an upload's name says nothing: its first bytes do (as on the upload)
        try:
            with open(p, "rb") as f:
                enc = f.read(len(BK_MAGIC)) == BK_MAGIC
            fmt3 = bk_meta(p, enc).get("format_version") == 3
        except FileNotFoundError:  # expired (clean-up of .uploads/) between the path check and the read
            raise BackupError("not_found") from None
        finally:
            _BK["meta"].pop(name, None)  # review: an upload's manifest is not kept in the summary cache (read once here)
    work = tempfile.mkdtemp(prefix=".verify-", dir=BK_DIR)
    rlock = None
    try:
        rlock = bk_read_lock() if fmt3 else None
        man, _ = bk_prepare(p, pw, work)
    except BackupError as e:
        if e.code == "passphrase" and given:  # 2.644.0 (#4530): only a typed-in passphrase counts as a try (as the restore)
            _rate_fail(keys)
        raise bk_old_pass(e, given, own) from None
    finally:
        bks.unlock(rlock)
        shutil.rmtree(work, ignore_errors=True)
    return jsonify(ok=True, created_at=man.get("created_at"), app_version=man.get("app_version"),
                   schema_version=man.get("schema_version"), counts=man.get("counts") or {}, legacy=man["_legacy"],
                   attachment_files=man.get("attachment_files"), attachment_bytes=man.get("attachment_bytes"),
                   pack_files=man.get("pack_files") or 0,  # 2.359.2 (#2895)
                   key_warning=bk_key_warning(man),  # 2.359.3 (#2893)
                   missing_files=man.get("missing_files") or 0, missing_paths=man.get("missing_paths") or [])  # 2.273.0 A (#3050)


def bk_no_upload_hosted():
    """2.480.0 (#3944, F6): hosted -> an archive from outside is neither taken nor restored: a self-made archive would replace
    every client's password hash and content. Restoring goes only from the server's own backups (and its offsite copy)."""
    from .hosting import hosted  # inside the function (#3506): admin.hosting -> api.scopes -> api.v1 -> admin.backup is a cycle at import time
    if hosted():
        raise Denied(403, tr("On a hosted instance no archive is uploaded: restoring goes only from the server's own backups"))


@app.post("/api/admin/backups/upload")
def backups_upload():
    """An archive to restore from (raw request body). Kept for an hour in .uploads/; returns its id + summary."""
    need_backups()
    bk_no_upload_hosted()
    request.max_content_length = BK_MAX_BYTES
    os.makedirs(os.path.join(BK_DIR, ".uploads"), mode=0o700, exist_ok=True)
    bk_uploads_gc()
    uid = "upload-" + secrets.token_hex(12)
    p = os.path.join(BK_DIR, ".uploads", uid)
    n = 0
    try:
        with open(p, "xb") as f:
            while True:
                b = request.stream.read(BK_CHUNK)
                if not b:
                    break
                n += len(b)
                if n > BK_MAX_BYTES:
                    raise BackupError("too_large", BK_MAX_BYTES // 1048576)
                f.write(b)
        with open(p, "rb") as f:
            head = f.read(len(BK_MAGIC))
        if head == BK_MAGIC:
            with open(p, "rb") as f:
                meta, enc = bk_enc_header(f)[0]["meta"], True
        elif head[:4] == b"PK\x03\x04":
            enc = False
            try:
                with zipfile.ZipFile(p) as z:
                    man = bk_check_zip(z)
                meta = {k: v for k, v in man.items() if not k.startswith("_") and k != "files"}
                meta["format_version"] = 1 if man["_legacy"] else man.get("format_version", 2)  # 2.432.0 (#3584, review N7): 3 stays 3
            except zipfile.BadZipFile:
                raise BackupError("format") from None
        else:
            raise BackupError("format")
    except BackupError:
        with contextlib.suppress(OSError):
            os.remove(p)
        raise
    except OSError as e:
        with contextlib.suppress(OSError):
            os.remove(p)
        raise BackupError("io", aa_oserr(e)) from None
    return jsonify(upload=uid, size=n, encrypted=enc, legacy=meta.get("format_version", 1) < 2,
                   created_at=meta.get("created_at", ""), app_version=meta.get("app_version", ""),
                   schema_version=meta.get("schema_version"), counts=meta.get("counts") or {},
                   attachment_files=meta.get("attachment_files"), attachment_bytes=meta.get("attachment_bytes"))


@app.get("/api/admin/backups/purged-preview")
def backups_purged_preview():
    """2.505.0 (#4302): ?since=<the backup's created_at>: what its restore would delete again (numbers per kind, the time span)."""
    need_backups()
    c = db()
    with _pg.system_ctx(c):
        return jsonify(bkr_purged_preview(c, str(request.args.get("since") or "")[:40]))


@app.post("/api/admin/backups/restore")
def backups_restore():
    """{name | upload, confirm: "RESTORE", passphrase?, keep_purged?} 2.505.0 (#4302): keep_purged true = what was deleted
    for good since the backup stays (default: it goes again)."""
    need_backups()
    c, b = db(), body()
    if b.get("upload"):
        bk_no_upload_hosted()  # 2.480.0 (#3944, F6)
    if b.get("confirm") != BK_CONFIRM:
        return err(BK_ERR_TEXT("confirm", BK_CONFIRM))
    from .offsite import stepup_need
    e = stepup_need(c, b, proxy_ok=True)  # 2.360.0 A (#2496): a stolen admin session alone restores nothing
    if e is not None:
        return e
    keys = _rate_keys(g.user["username"])
    e = login_wait(keys, g.user["username"])  # 2.282.0 (#3111)
    if e:
        return e
    up = str(b.get("upload") or "")
    p = bk_upload_path(up) if up else bk_path(str(b.get("name") or ""))
    given = str(b.get("passphrase") or "")
    pw = given or bk_passphrase(c)
    admin, via, keep = g.user["username"], g.auth_via, b.get("keep_purged") is True
    c.close()
    g.pop("db", None)
    try:
        tok, safety, man = bk_restore(p, pw, admin, via, keep_purged=keep)
    except BackupError as e:
        if e.code == "passphrase" and given:  # 2.525.0 (#4303): only a typed-in passphrase counts as a try
            _rate_fail(keys)
        raise bk_old_pass(e, given, not up) from None
    if up:
        with contextlib.suppress(OSError):
            os.remove(p)
    resp = jsonify(ok=True, safety=safety, relogin=tok is None and via != "proxy", created_at=man.get("created_at"),
                   key_warning=bk_key_warning(man),  # 2.359.3 (#2893)
                   deleted_again=man.get("_again") or {},  # 2.152.0 B (#2172): accounts of the journal
                   notes=[tr(*n) for n in man.get("_notes") or []])  # 2.273.0 A (#3051 p. 12, 13)
    if tok:
        set_cookie(resp, tok, SESSION_DAYS * 86400)
    return resp
