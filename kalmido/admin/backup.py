"""Backups and restore (admins)."""
import contextlib
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
from flask import g, jsonify, request, send_file

from ..core.config import app, APP_VERSION, ATT_DIR, DATABASE_URL, DB, OFFICE_DIR, SESSION_DAYS, TZ
from ..core.schema import SCHEMA_TRIGGERS, SCHEMA_VERSION
from ..core import pg as _pg
from ..core.i18n import N_, tr
from ..core.db import body, connect, db, err, gset, gsetting, init_db, iso, local_now, now_utc, parse_iso
from ..accounts.session import _rate_blocked, _rate_fail, _rate_keys, GATE, set_cookie, start_session
from ..accounts.login import _AUTH_KEY, _PEND, _PEND_LOCK, seal, unseal
from ..accounts.oidc import _OIDC_LOCK, _OIDC_STATES, oidc_reset
from ..core.access import Denied
from ..tasks.validation import valid_hm
from ..tasks.lifecycle import UNDO_KEY
from ..collab.news import NEWS_CLEAN
from ..accounts.users import need_admin
from ..calendars.caldav import _DAV_CACHE, _DAV_CACHE_LOCK, _DAV_INST
from ..notify.push import _b64u, _b64u_dec, _VAPID
from ..notify.alerts import _clamp_int, _env_int, aa_count, aa_disk, aa_now, aa_oserr, aa_switch
from ..calendars.subscriptions import _CAL_KEY


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
BK_ON_ENV = os.environ.get("KALMIDO_BACKUPS", "1").strip().lower() not in ("0", "false", "no", "off")
BK_DIR = os.path.abspath(os.environ.get("KALMIDO_BACKUP_DIR", "").strip() or os.path.join(os.path.dirname(os.path.abspath(DB)), "backups"))
BK_PASS_ENV = os.environ.get("KALMIDO_BACKUP_PASSPHRASE", "")
BK_TICK = _env_int("KALMIDO_BACKUP_TICK", 60)                          # s between schedule checks
BK_MAX_BYTES = _env_int("KALMIDO_BACKUP_MAX_MB", 4096) * 1024 * 1024   # restore: upload size and unpacked total
BK_MAX_MEMBERS = 200000
BK_MAX_RATIO = 500             # unpacked / packed per member above 1 MB (zip bomb)
BK_STALE_S = 2 * 86400         # "backup older than 2 days" alert
BK_SAFETY_KEEP = 3
BK_UPLOAD_TTL = 3600
BK_CHUNK = 1024 * 1024
BK_MAGIC = b"KALMIDO-BACKUP-ENC\x00"
BK_SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}
BK_CONFIRM = "RESTORE"
BK_NAME_RE = re.compile(r"kalmido-backup-(\d{8})-(\d{6})-(auto|manual|safety)\.zip(\.enc)?")
BK_UPLOAD_RE = re.compile(r"upload-([a-f0-9]{24})")
BK_DUMP = "kalmido.dump"    # format 2 (2.37.0, Postgres): pg_dump -Fc
BK_LEGACY = "tasks.db"      # format 1 (up to 2.36, SQLite): listed / checked, not restored here
BK_PG_TIMEOUT = _env_int("KALMIDO_BACKUP_PG_TIMEOUT", 6 * 3600)   # s for one pg_dump / pg_restore run
# members: attachments/<task>/<file>; 2.36.1 (#1021): office/<org>/<file> (the logos of the office module, same rules);
# 2.46.0 (#1605): + attachments/avatars/<file> and attachments/listicons/<file> (pictures of people, groups and lists)
# 2.48.0 (#1207): + attachments/files/<node>/<file> (the file store) and attachments/lists/<list>/<file> (project files, #410:
# they were left out of the archive before)
BK_MEMBER_RE = re.compile(r"(attachments|office)/(\d{1,12}|avatars|listicons|(?:files|lists)/\d{1,12})/([^/\\\x00-\x1f]{1,255})")
BK_ERR = {"busy": N_("Another backup or restore is running, please try again in a moment."),
          "disk": N_("Not enough free disk space for the backup."),
          "io": N_("The backup could not be written ({0})."),
          "format": N_("This is not an Kalmido backup (or the file is damaged)."),
          "members": N_("The backup contains unexpected files and was refused."),
          "too_large": N_("The backup is too large (limit {0} MB unpacked)."),
          "bomb": N_("The backup looks like a zip bomb and was refused."),
          "hash": N_("The backup is damaged: a file does not match its checksum."),
          "integrity": N_("The database in the backup is damaged (integrity check failed)."),
          "schema": N_("The backup is from a newer Kalmido version (database schema {0}); update Kalmido first."),
          "objects": N_("The database in the backup contains unexpected objects or statements and was refused."),
          "legacy": N_("This backup is from a version before 2.37 (SQLite). Restore it with Kalmido 2.36, then update to 2.37: the data is moved over during the update."),
          "tools": N_("The database tools (pg_dump / pg_restore) are missing on this server."),
          "passphrase": N_("Wrong passphrase, or the encrypted backup is damaged."),
          "need_passphrase": N_("This backup is encrypted: enter its passphrase."),
          "no_passphrase": N_("Encryption needs a passphrase (at least 10 characters)."),
          "not_found": N_("Backup not found."),
          "confirm": N_("Type {0} to confirm."),
          "maint": N_("The server is still busy; the restore did not start. Please try again."),
          "restore": N_("The restore failed ({0}); nothing was changed.")}
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
    code = {"busy": 409, "not_found": 404, "need_passphrase": 400, "passphrase": 400}.get(e.code, 400)
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
                raise BackupError("passphrase")
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


def _dir_size(d):
    n = 0
    for root, _, files in os.walk(d):
        for fn in files:
            try:
                st = os.lstat(os.path.join(root, fn))
                n += st.st_size
            except OSError:
                pass
    return n


def bk_name(kind, encrypted):
    ts = local_now()
    for _ in range(120):
        n = f"kalmido-backup-{ts.strftime('%Y%m%d-%H%M%S')}-{kind}.zip" + (".enc" if encrypted else "")
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
        raise BackupError(err_code, _pg_errline(p.stderr, args[0]))


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
            _pg_run(["pg_dump", "-Fc", "-Z", "6", "--enable-row-security", f"--snapshot={snap}", "-f", dest])
        return counts, schema
    finally:
        s.close()


def bk_create(kind="manual", c=None, keep_dump=None):
    """Writes one backup (caller holds _BK_LOCK); returns its name. BackupError on failure. keep_dump: also keep a copy of
    the dump at this path (the restore's way back)."""
    own = c is None
    c = c or connect()
    tmp = None
    try:
        os.makedirs(BK_DIR, mode=0o700, exist_ok=True)
        encrypt = gsetting(c, "bk_encrypt") == "1"
        pw = bk_passphrase(c) if encrypt else ""
        if encrypt and len(pw) < 10:
            raise BackupError("no_passphrase")
        need = bk_db_bytes(c) + sum(_dir_size(d) for d in (ATT_DIR, OFFICE_DIR) if os.path.isdir(d))
        free = shutil.disk_usage(BK_DIR).free
        if free < need * (2.2 if encrypt else 1.2) + 64 * 1024 * 1024:
            raise BackupError("disk")
        tmp = tempfile.mkdtemp(prefix=".tmp-", dir=BK_DIR)
        dbp = os.path.join(tmp, BK_DUMP)
        counts, schema = bk_dump(dbp)
        if keep_dump:
            shutil.copyfile(dbp, keep_dump)
        files, att_bytes = [], 0
        zp = os.path.join(tmp, "backup.zip")
        with zipfile.ZipFile(zp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
            z.write(dbp, BK_DUMP, compress_type=zipfile.ZIP_STORED)  # pg_dump -Fc compresses itself
            files.append([BK_DUMP, os.path.getsize(dbp), _sha256_file(dbp)])
            for base, prefix in ((ATT_DIR, "attachments/"), (OFFICE_DIR, "office/")):
                if not os.path.isdir(base):
                    continue
                for root, dirs, fns in os.walk(base):
                    dirs[:] = sorted(d for d in dirs if not os.path.islink(os.path.join(root, d)))
                    for fn in sorted(fns):
                        full = os.path.join(root, fn)
                        rel = prefix + os.path.relpath(full, base).replace(os.sep, "/")
                        if os.path.islink(full) or not os.path.isfile(full) or not BK_MEMBER_RE.fullmatch(rel):
                            continue
                        if prefix == "office/" and fn.endswith((".tmp", ".part")):  # 2.36.2 E (#1146): unfinished uploads
                            continue
                        try:
                            digest, size = _sha256_file(full), os.path.getsize(full)
                            z.write(full, rel, compress_type=zipfile.ZIP_STORED if size > 64 * 1024 and
                                    re.search(r"\.(jpe?g|png|gif|webp|avif|heic|mp4|mov|webm|mp3|m4a|ogg|zip|gz|7z|pdf|docx|xlsx|pptx|odt)$", fn, re.I)
                                    else zipfile.ZIP_DEFLATED)
                        except FileNotFoundError:  # deleted meanwhile
                            continue
                        files.append([rel, size, digest])
                        att_bytes += size
            meta = {"format": "kalmido-backup", "format_version": 2, "app_version": APP_VERSION, "schema_version": schema,
                    "created_at": iso(now_utc()), "kind": kind, "counts": counts, "db_bytes": files[0][1],
                    "attachment_files": len(files) - 1, "attachment_bytes": att_bytes}
            z.writestr("manifest.json", json.dumps({**meta, "files": files}, ensure_ascii=False))
        name = bk_name(kind, encrypt)
        final = os.path.join(BK_DIR, name)
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
    except (_pg.Error, zipfile.BadZipFile, ValueError) as e:
        raise BackupError("io", type(e).__name__) from None
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
        if own:
            c.close()


def bk_parse_name(n):
    m = BK_NAME_RE.fullmatch(n or "")
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=TZ)
    except ValueError:
        return None
    return {"name": n, "at": dt, "kind": m.group(3), "encrypted": bool(m.group(4))}


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
        p["size"] = os.path.getsize(full)
        p["meta"] = bk_meta(full, p["encrypted"])
        out.append(p)
    out.sort(key=lambda x: (x["at"], x["name"]), reverse=True)
    return out


def bk_public(x):
    m = x.get("meta") or {}
    return {"name": x["name"], "kind": x["kind"], "encrypted": x["encrypted"], "size": x["size"], "created_at": iso(x["at"]),
            "app_version": m.get("app_version", ""), "schema_version": m.get("schema_version"), "counts": m.get("counts") or {},
            "attachment_files": m.get("attachment_files"), "attachment_bytes": m.get("attachment_bytes"),
            "unreadable": bool(m.get("unreadable")),
            # 2.37.0: a backup from before 2.37 (SQLite): listed and checked, restored only through 2.36 + the update
            "legacy": not m.get("unreadable") and m.get("format_version", 1) < 2}


def bk_prune(c):
    """Retention: every backup of the last 24 hours, then the newest backup per day for the last keep_daily days that
    have one, the newest per ISO week for keep_weekly weeks, the last BK_SAFETY_KEEP safety backups. Returns the
    deleted names."""
    daily = _clamp_int(gsetting(c, "bk_keep_daily"), 1, 365, 14)
    weekly = _clamp_int(gsetting(c, "bk_keep_weekly"), 0, 520, 8)
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
    keep.update([x["name"] for x in items if x["kind"] == "safety"][:BK_SAFETY_KEEP])
    keep.update(x["name"] for x in items if x["kind"] != "safety" and local_now() - x["at"] < timedelta(hours=24))
    gone = []
    for x in items:
        if x["name"] not in keep:
            try:
                os.remove(os.path.join(BK_DIR, x["name"]))
                gone.append(x["name"])
            except OSError:
                pass
    return gone


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
            name = bk_create(kind, c)
            bk_prune(c)
            for k, v in (("bk_last_ok", iso(now_utc())), ("bk_last_name", name), ("bk_last_error", ""), ("bk_last_error_at", "")):
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
            c.commit()
        except Exception:  # noqa: BLE001 -- no database: the alert below still goes out (log + admin alert queue)
            pass
        _BK["next_try"] = time.time() + 3600
        print("backup FAILED:", e.text("en"), flush=True)
        aa_now("storage", f"backup:{e.code}", N_("Backup failed: {0}"), [{"t": BK_ERR.get(e.code, BK_ERR["format"])} if not e.args_
                                                                       else e.text("en")])
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


def backup_tick(c):
    if not BK_ON_ENV or gsetting(c, "bk_on") != "1":
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
        ref = gsetting(c, "bk_last_ok") or gsetting(c, "bk_enabled_at")
        if ref and (now_utc() - parse_iso(ref)).total_seconds() > BK_STALE_S:
            last = gsetting(c, "bk_last_ok")
            aa_now("storage", "backup:stale", N_("The last successful backup is older than 2 days ({0})."),
                   [last[:16].replace("T", " ") + " UTC" if last else {"t": N_("none yet")}])


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
            print("backup loop error:", type(e).__name__, e, flush=True)
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


def bk_check_zip(z):
    """Validates the member list; returns the manifest (with files) or BackupError."""
    infos = z.infolist()
    if len(infos) > BK_MAX_MEMBERS:
        raise BackupError("members")
    seen, total = set(), 0
    for i in infos:
        n = i.filename
        m = BK_MEMBER_RE.fullmatch(n)
        ok = n in ("manifest.json", BK_DUMP, BK_LEGACY) or (m and m.group(3) not in (".", ".."))
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
    if man.get("format_version", 1) != (1 if legacy else 2):
        raise BackupError("format")
    sv = man.get("schema_version")
    if isinstance(sv, bool) or not isinstance(sv, int):
        raise BackupError("format")
    if sv > SCHEMA_VERSION:
        raise BackupError("schema", sv)
    listed = {}
    for f in man["files"]:
        if not (isinstance(f, list) and len(f) == 3 and isinstance(f[0], str) and isinstance(f[1], int) and isinstance(f[2], str)):
            raise BackupError("format")
        listed[f[0]] = f
    if set(listed) != seen - {"manifest.json"}:
        raise BackupError("hash")
    free = shutil.disk_usage(os.path.dirname(os.path.abspath(DB))).free
    if free < total * 1.1 + 64 * 1024 * 1024:
        raise BackupError("disk")
    man["_listed"], man["_total"], man["_legacy"] = listed, total, legacy
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


def bk_scan_dump(dump):
    """Reads the whole dump through pg_restore (to SQL text; no database involved): every data block must be readable
    (else "integrity"), every statement one of a Kalmido dump ("objects"), the schema version (kalmido_meta) not newer
    than this app's ("schema"). Returns {"schema_version", "rows": {table: n}, "users"}."""
    exe = _pg_tool("pg_restore")
    toc, _ = _toc_file(dump)
    rows, ddl, ddl_n, meta, table = {}, [], 0, {}, None
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
    return {"schema_version": int(sv), "rows": rows, "users": rows.get("users", 0)}


def bk_prepare(path, pw, work, att_dest=None, office_dest=None, restore=False):
    """Checks an archive completely; extracts the dump into work (and the attachments into att_dest, the office files into
    office_dest, if given) and reads it through once. Returns (manifest, dump path). A format-1 archive (SQLite, before
    2.37) is checked (members, checksums); for a restore its tasks.db is extracted (the returned path) for the move tool."""
    zp, _ = bk_open(path, pw, work)
    try:
        with zipfile.ZipFile(zp) as z:
            man = bk_check_zip(z)
            # 2.37.0 (#1150): a format-1 archive is restored through the move tool (admin/migrate.py), which reads its tasks.db
            legacy_restore = man["_legacy"] and restore
            dbp = os.path.join(work, BK_LEGACY if legacy_restore else BK_DUMP)
            for i in z.infolist():
                if i.filename == BK_DUMP or (legacy_restore and i.filename == BK_LEGACY):
                    bk_extract(z, i, dbp, man["_listed"])
                elif i.filename != "manifest.json":
                    m = BK_MEMBER_RE.fullmatch(i.filename)
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
    except zipfile.BadZipFile:
        raise BackupError("format") from None
    except (zipfile.LargeZipFile, NotImplementedError, EOFError):
        raise BackupError("format") from None
    if not man["_legacy"]:
        man["db"] = bk_scan_dump(dbp)
    elif restore:
        from .migrate import is_kalmido_sqlite
        if not is_kalmido_sqlite(dbp):
            raise BackupError("legacy")
    return man, dbp


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


def _pg_restore(dump):
    """pg_restore --clean of a checked dump into the running database, in ONE transaction (an error leaves it as it was),
    with the filtered table of contents only (bk_toc: no code from the dump; init_db creates it afterwards). Tables of this
    version that the dump does not have (a backup of an older version) are dropped first, so --clean cannot trip over
    their foreign keys; init_db creates them again, empty."""
    toc, tables = _toc_file(dump)
    if not {"users", "tasks", "kalmido_meta"} <= tables:  # (never drop anything on a list that was not understood)
        raise BackupError("format")
    c = _pg.connect_direct(DATABASE_URL)
    try:
        with _pg.system_ctx(c):  # the restore works on the whole database (every organisation)
            c.execute("SET LOCAL statement_timeout = 0")
            extra = [r[0] for r in c.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
                     if r[0] not in tables]
            for t in extra:
                c.execute('DROP TABLE IF EXISTS "' + t.replace('"', '""') + '" CASCADE')
        c.commit()
    finally:
        c.close()
    if extra:
        print("restore: dropped table(s) the backup does not have:", ", ".join(extra), flush=True)
    _pool_renew()
    try:
        _pg_run(["pg_restore", *_restore_args(toc), "--enable-row-security", "--exit-on-error",
                 "-d", bk_pg_env().get("PGDATABASE") or bk_pg_env().get("PGUSER") or "postgres", dump], err_code="restore")
    finally:
        _pool_renew()


def _reset_caches():
    """In-process state that belongs to the database (after a restore)."""
    for d in (_CAL_KEY, UNDO_KEY, _AUTH_KEY, _BK["meta"]):
        d.clear()
    _VAPID.clear()
    with _PEND_LOCK:
        _PEND.clear()
    with _OIDC_LOCK:
        _OIDC_STATES.clear()
    oidc_reset()
    _DAV_INST.clear()
    with _DAV_CACHE_LOCK:
        _DAV_CACHE.clear()
    NEWS_CLEAN["at"] = 0.0


def bk_restore(path, pw, admin, via):
    """The whole restore (see the section comment). Returns (new session token or None, safety backup name)."""
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
        man, dbp = bk_prepare(path, pw, work, att_new, off_new, restore=True)
        cur = connect()
        try:
            keep = {r[0]: r[1] for r in cur.execute("SELECT key, value FROM settings WHERE key ILIKE 'bk\\_%' ESCAPE '\\'")}
            ver = int(gsetting(cur, "version") or 0)
        finally:
            cur.close()
        if not GATE.begin(own=1, timeout=60):
            raise BackupError("maint")
        gate = True
        pre = os.path.join(work, "pre-restore.dump")  # the current database, for a rollback if anything below fails
        safety = bk_create("safety", keep_dump=pre)
        moved = swapped = omoved = oswapped = False
        try:
            if os.path.isdir(ATT_DIR):
                os.rename(ATT_DIR, att_old)
                moved = True
            os.rename(att_new, ATT_DIR)
            if os.path.isdir(OFFICE_DIR):
                os.rename(OFFICE_DIR, off_old)
                omoved = True
            os.rename(off_new, OFFICE_DIR)
            oswapped = True
            swapped = True  # (from here on a failure restores the dump of before; pg_restore itself is all or nothing)
            if man["_legacy"]:  # 2.37.0 (#1150): an archive of 2.36 or older: moved over from its tasks.db
                from .migrate import mig_restore
                mig_restore(dbp)
            else:
                _pg_restore(dbp)
            _reset_caches()
            init_db(guard=False)
            c = connect()
            try:
                with _pg.system_ctx(c):  # every session of every organisation ends
                    for k, v in keep.items():  # the backup settings stay as they are now (not the ones in the backup)
                        gset(c, k, v)
                    gset(c, "version", max(ver, int(gsetting(c, "version") or 0)) + 1)
                    c.execute("DELETE FROM sessions")
                    tok = None
                    u = c.execute("SELECT * FROM users WHERE username=? AND is_admin=1 AND disabled=0", (admin,)).fetchone()
                    if u and via == "session":
                        tok, _ = start_session(c, u["id"], True, "password")
                c.commit()
            finally:
                c.close()
        except Exception:
            if swapped:
                try:
                    _pg_restore(pre)
                    _reset_caches()
                    init_db(guard=False)
                except Exception as e2:  # noqa: BLE001 -- the original error is the one to report
                    print("restore: rolling back to the state before FAILED:", type(e2).__name__, getattr(e2, "args_", e2),
                          f"(the safety backup {safety} holds it)", flush=True)
            if os.path.isdir(ATT_DIR) and moved:
                os.rename(ATT_DIR, att_new)
                os.rename(att_old, ATT_DIR)
            if oswapped:
                os.rename(OFFICE_DIR, off_new)
            if omoved:
                os.rename(off_old, OFFICE_DIR)
            raise
        shutil.rmtree(att_old, ignore_errors=True)
        shutil.rmtree(off_old, ignore_errors=True)
        print(f"restore: {os.path.basename(path)} restored by {admin} (safety backup {safety})", flush=True)
        aa_now("security", f"restore:{int(time.time())}", N_("{0} restored a backup from {1} (safety backup of the previous state: {2})."),
               [admin, str(man.get("created_at", "?"))[:16].replace("T", " ") + " UTC", safety])
        return tok, safety, man
    except BackupError:
        raise
    except Exception as e:  # noqa: BLE001
        print("restore failed:", type(e).__name__, e, flush=True)
        raise BackupError("restore", str(e)[:300] if type(e).__name__ == "MigError" else type(e).__name__) from None
    finally:
        if gate:
            GATE.end()
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(att_new, ignore_errors=True)
        shutil.rmtree(off_new, ignore_errors=True)
        _BK.update(running="", started=0.0)
        _BK_LOCK.release()


# ---- API (admins; CSRF header on every change)
def bk_state(c):
    items = bk_list()
    return {"env": BK_ON_ENV, "dir": BK_DIR, "on": gsetting(c, "bk_on") == "1", "time": gsetting(c, "bk_time"),
            "keep_daily": _clamp_int(gsetting(c, "bk_keep_daily"), 1, 365, 14), "keep_weekly": _clamp_int(gsetting(c, "bk_keep_weekly"), 0, 520, 8),
            "encrypt": gsetting(c, "bk_encrypt") == "1", "passphrase_set": bool(bk_passphrase(c)), "passphrase_env": bool(BK_PASS_ENV),
            "last_ok": gsetting(c, "bk_last_ok"), "last_name": gsetting(c, "bk_last_name"), "last_error": gsetting(c, "bk_last_error"),
            "last_error_at": gsetting(c, "bk_last_error_at"), "running": _BK["running"], "confirm_word": BK_CONFIRM,
            "total_bytes": sum(x["size"] for x in items), "free_bytes": aa_disk().get("free"),
            "max_mb": BK_MAX_BYTES // 1048576, "items": [bk_public(x) for x in items]}


def need_backups():
    need_admin()
    if not BK_ON_ENV:
        raise Denied(404, tr("Backups are turned off on this server (KALMIDO_BACKUPS=0)"))


# 2.13.0: Settings > Administration > "Check storage": every task attachment and project file whose file is missing,
# empty or of another size than recorded (e.g. after copying the data folder to another machine). Read-only.
@app.get("/api/admin/storage-check")
def storage_check():
    need_admin()
    c, out, n = db(), [], 0
    for kind, sql in (("attachment", "SELECT a.id, a.task_id AS owner, a.name, a.size, a.path, t.title AS where_ FROM attachments a "
                                     "LEFT JOIN tasks t ON t.id=a.task_id"),
                      ("list_file", "SELECT f.id, f.list_id AS owner, f.name, f.size, f.path, l.name AS where_ FROM list_files f "
                                    "LEFT JOIN lists l ON l.id=f.list_id"),
                      # 2.13.1 (#465): files in the agent chats (where = the agent's name)
                      ("chat_file", "SELECT f.id, m.agent_id AS owner, f.name, f.size, f.path, u.display_name AS where_ FROM chat_files f "
                                    "JOIN agent_chat m ON m.id=f.message_id LEFT JOIN users u ON u.id=m.agent_id")):
        for r in c.execute(sql):
            n += 1
            full = os.path.join(ATT_DIR, r["path"] or "")
            from ..core.orgcrypt import oc_plain_size
            disk = oc_plain_size(full) if r["path"] and os.path.isfile(full) else None  # 2.42.0 (#828): sealed = plain size
            if disk is None or (r["size"] and disk != r["size"]):
                out.append({"kind": kind, "id": r["id"], "owner": r["owner"], "where": r["where_"] or "", "name": r["name"],
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


@app.post("/api/admin/backups")
def backups_now():
    """Back up now (in the background; the list shows it when done)."""
    need_backups()
    if _BK["running"]:
        raise BackupError("busy")
    threading.Thread(target=bk_run, args=("manual",), daemon=True).start()
    time.sleep(0.05)
    return jsonify(ok=True, **bk_state(db())), 202


@app.get("/api/admin/backups/<name>/download")
def backups_download(name):
    need_backups()
    p = bk_path(name)
    return send_file(p, as_attachment=True, download_name=name, mimetype="application/octet-stream",
                     conditional=False, max_age=0)


@app.delete("/api/admin/backups/<name>")
def backups_delete(name):
    need_backups()
    p = bk_path(name)
    if _BK["running"]:
        raise BackupError("busy")
    os.remove(p)
    _BK["meta"].pop(name, None)
    return jsonify(bk_state(db()))


@app.post("/api/admin/backups/<name>/verify")
def backups_verify(name):
    """Full check without changing anything: decrypt, member list, every checksum, database integrity."""
    need_backups()
    c = db()
    p = bk_path(name) if not name.startswith("upload-") else bk_upload_path(name)
    pw = str(body().get("passphrase") or "") or bk_passphrase(c)
    work = tempfile.mkdtemp(prefix=".verify-", dir=BK_DIR)
    try:
        man, _ = bk_prepare(p, pw, work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return jsonify(ok=True, created_at=man.get("created_at"), app_version=man.get("app_version"),
                   schema_version=man.get("schema_version"), counts=man.get("counts") or {}, legacy=man["_legacy"],
                   attachment_files=man.get("attachment_files"), attachment_bytes=man.get("attachment_bytes"))


@app.post("/api/admin/backups/upload")
def backups_upload():
    """An archive to restore from (raw request body). Kept for an hour in .uploads/; returns its id + summary."""
    need_backups()
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
                meta["format_version"] = 1 if man["_legacy"] else 2
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


@app.post("/api/admin/backups/restore")
def backups_restore():
    """{name | upload, confirm: "RESTORE", passphrase?}"""
    need_backups()
    c, b = db(), body()
    if b.get("confirm") != BK_CONFIRM:
        return err(BK_ERR_TEXT("confirm", BK_CONFIRM))
    keys = _rate_keys(g.user["username"])
    if _rate_blocked(keys):
        return err(tr("Too many failed logins, please wait a few minutes"), 429)
    up = str(b.get("upload") or "")
    p = bk_upload_path(up) if up else bk_path(str(b.get("name") or ""))
    pw = str(b.get("passphrase") or "") or bk_passphrase(c)
    admin, via = g.user["username"], g.auth_via
    c.close()
    g.pop("db", None)
    try:
        tok, safety, man = bk_restore(p, pw, admin, via)
    except BackupError as e:
        if e.code == "passphrase":
            _rate_fail(keys)
        raise
    if up:
        with contextlib.suppress(OSError):
            os.remove(p)
    resp = jsonify(ok=True, safety=safety, relogin=tok is None and via != "proxy", created_at=man.get("created_at"))
    if tok:
        set_cookie(resp, tok, SESSION_DAYS * 86400)
    return resp
