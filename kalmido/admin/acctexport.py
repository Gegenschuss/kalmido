"""2.73.0 B (#1473): account export -- everything of one person as ONE file (moving between a hosted server such as
app.kalmido.com and an own server, both ways; usable as the GDPR copy of Art. 15 / 20).

The person (cookie session only: agents and tokens never) starts it in Settings > Data; a background thread writes a ZIP
(below the data folder, exports/account/<user id>/, not in the backups; sealed at rest, see below, mode 0600), the file
waits UMZ_KEEP_H hours and the watchdog removes it after that. The download is the plain ZIP (the person's own data).

ZIP layout (format "kalmido-account", v 1; admin/acctimport.py reads it):
    manifest.json      {format, v, kalmido_version, created_at, source: {url, hosted}, user: {id, name, email},
                        tables: {name: rows}, files: [{path, size, sha256}], client_encrypted: {...}, export_id, not_included}
    data/<table>.json  one JSON array per table: the tables of GET /api/export.json (accounts/settings.py
                        umz_export_queries) plus list tags, the lists shared with me (a reference only) with my own comments
                        there, the people of my lists (for the mapping on import; other people's e-mail addresses only as
                        email_hash, see umz_email_hash) and the server accounts (no token)
    files/...          attachments of the tasks and project files of the lists (decrypted: oc_read_file)
    checksum.sha256    "sha256  path" lines (sha256sum -c): manifest.json and every file of the manifest

Never in the file: passwords, sessions, token hashes, two-factor data, push subscriptions, webhook secrets and addresses
(url_hint only), server-side settings, access data
(orgexport OX_SECRET_COLS is dropped from every row). Browser-encrypted content stays ciphertext (client_encrypted).

At rest (export here and the uploads of acctimport.py): with a server key (KALMIDO_SECRET_KEY) the file is AES-256-GCM in
UMZ_BLOCK blocks with a key derived per person and purpose (HKDF), so it is readable with random access (zipfile seeks);
without a server key it is plain with mode 0600 like the attachments next to it."""
import hashlib
import io
import json
import os
import secrets
import shutil
import struct
import threading
import time
import zipfile
from datetime import timedelta

from flask import g, jsonify, Response

from ..core.config import app, APP_VERSION, ATT_DIR, PUBLIC_URL, SECRET_KEY
from ..core.db import connect, db, err, iso, now_utc
from ..core.pg import system_ctx
from ..core.i18n import tr
from ..core.access import Denied, acx_of
from ..accounts.session import me
from .orgexport import EXPORT_DIR, OX_SECRET_COLS, _jdef, _safe_part, _under
from ..core.orgcrypt import oc_read_file  # 2.149.0 G (#2517): pulled up from functions
from ..files.scan import sc_locked_all  # 2.209.0 D (#1856)

UMZ_DIR = os.path.join(EXPORT_DIR, "account")
UMZ_KEEP_H = 24
PART_STALE_S = 6 * 3600  # 2.148.1 C (#2482): an unfinished export file older than this is left over (runs end long before)
UMZ_BLOCK = 1 << 20  # 1 MiB of plaintext per sealed block
UMZ_MAGIC = b"KALMIDO-UMZ1\n"
UMZ_FORMAT = "kalmido-account"
UMZ_V = 1
UMZ_SUFFIX = ".zip"
UMZ_SPACE_SPARE = 64 * 1024 * 1024  # free disk space kept on top of the expected size
UMZ_NOT_INCLUDED = (
    "passwords, sessions, API tokens (only their names), two-factor data, push subscriptions, webhook secrets and addresses",
    "server-side settings (such as the ntfy topic an admin set)",
    "access data of connections (calendar and address book subscriptions, Karakeep, newsletter, Git, server accounts)",
    "lists of other people that are shared with you (only a reference and your own comments there)",
    "organisation data that is not yours (use the organisation export for a whole organisation)",
    "the receipt files of household budgets (their entries are included)",  # 2.72.0 (#1333)
    # 2.148.1 C (#2494): what is not in the file either (the manifest names it honestly)
    "the content of your private files (only their list: name, type, size, dates), files of knowledge pages and tables",
    "messages of other people in direct messages and team chats (only what you wrote in direct messages)",
    "booking pages and their bookings, polls and forms with their answers, holiday allowances",
    "the organisation's office (documents, receipts, cash book) and organisation knowledge pages: the organisation export",
)

_UMZ = {}  # user id -> the running export thread
_UMZ_LOCK = threading.Lock()


# ---------------------------------------------------------------- sealing at rest (shared with acctimport.py)
def umz_key(uid, purpose):
    """32 bytes for the person's files of this purpose ("export" / "upload"); None without a server key (then plain)."""
    if not SECRET_KEY:
        return None
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=b"kalmido-umz-v1|" + purpose.encode() + b"|" + str(int(uid)).encode()).derive(SECRET_KEY)


UMZ_HEAD = len(UMZ_MAGIC) + 8  # magic + nonce prefix


class UmzWriter:
    """Write-only stream into the open binary file f: sealed blocks (key) or plain (key None). No tell()/seek(), so
    zipfile streams with data descriptors. size = plaintext bytes written. resume(): go on appending (the upload)."""

    def __init__(self, f, key, size=0, prefix=None):
        self.f, self.key, self.size = f, key, size
        self.buf = bytearray()
        self.aes = None
        if key:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            self.aes = AESGCM(key)
            if prefix is None:
                prefix = os.urandom(8)
                f.write(UMZ_MAGIC + prefix)
            self.prefix = prefix
            self.n = size // UMZ_BLOCK

    @classmethod
    def resume(cls, f, path, key, size):
        """Appending to a file with `size` plaintext bytes (a whole number of blocks when sealed)."""
        prefix = None
        if key:
            with open(path, "rb") as r:
                head = r.read(UMZ_HEAD)
            if head[:len(UMZ_MAGIC)] != UMZ_MAGIC or size % UMZ_BLOCK:
                raise ValueError("not resumable")
            prefix = head[len(UMZ_MAGIC):]
        return cls(f, key, size, prefix)

    def write(self, b):
        if not self.aes:
            self.f.write(b)
            self.size += len(b)
            return len(b)
        self.buf += b
        self.size += len(b)
        while len(self.buf) >= UMZ_BLOCK:
            self._emit(bytes(self.buf[:UMZ_BLOCK]))
            del self.buf[:UMZ_BLOCK]
        return len(b)

    def flush(self):
        pass

    def finish(self):
        if self.aes and self.buf:
            self._emit(bytes(self.buf))
            self.buf = bytearray()
        self.f.flush()

    def _emit(self, chunk):
        nonce = self.prefix + struct.pack(">I", self.n)
        self.f.write(self.aes.encrypt(nonce, chunk, UMZ_MAGIC + struct.pack(">Q", self.n)))
        self.n += 1


class UmzReader(io.RawIOBase):
    """Random-access reading of a file written by UmzWriter (size = its plaintext bytes); zipfile can seek in it."""

    def __init__(self, path, key, size):
        super().__init__()
        self.f, self.size, self.pos = open(path, "rb"), int(size), 0
        self.aes, self.cache = None, (None, b"")
        if key:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            head = self.f.read(UMZ_HEAD)
            if head[:len(UMZ_MAGIC)] != UMZ_MAGIC:
                raise ValueError("not a sealed file")
            self.aes, self.prefix = AESGCM(key), head[len(UMZ_MAGIC):]

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = max(0, off if whence == 0 else self.pos + off if whence == 1 else self.size + off)
        return self.pos

    def _block(self, i):
        if self.cache[0] != i:
            self.f.seek(UMZ_HEAD + i * (UMZ_BLOCK + 16))
            ct = self.f.read(UMZ_BLOCK + 16)
            self.cache = (i, self.aes.decrypt(self.prefix + struct.pack(">I", i), ct, UMZ_MAGIC + struct.pack(">Q", i)))
        return self.cache[1]

    def readinto(self, b):
        n = min(len(b), max(0, self.size - self.pos))
        if n <= 0:
            return 0
        if not self.aes:
            self.f.seek(self.pos)
            data = self.f.read(n)
        else:
            i, o = divmod(self.pos, UMZ_BLOCK)
            data = self._block(i)[o:o + n]
        b[:len(data)] = data
        self.pos += len(data)
        return len(data)

    def close(self):
        try:
            self.f.close()
        finally:
            super().close()


def umz_stream(path, key, size):
    """The plaintext of a stored file in pieces (a download)."""
    r = UmzReader(path, key, size)
    try:
        while True:
            b = r.read(UMZ_BLOCK)
            if not b:
                return
            yield b
    finally:
        r.close()


def umz_person():
    """People only: an agent or a request with a token gets 403 (the routes are no part of /api/v1 either)."""
    from ..agents.core import is_agent
    if g.get("token") or is_agent(g.user):
        raise Denied(403, tr("Agents cannot use this endpoint"))


def umz_space_ok(folder, need):
    try:
        os.makedirs(folder, mode=0o700, exist_ok=True)
        return shutil.disk_usage(folder).free >= int(need) + UMZ_SPACE_SPARE
    except OSError:
        return False


# ---------------------------------------------------------------- what goes into the file
def umz_clean(table, r):
    """A row as it goes into the account export (None = left out)."""
    from ..accounts.settings import SETTINGS_SERVER_ONLY, umz_export_clean
    from ..calendars.subscriptions import cal_url_hint
    d = {k: v for k, v in dict(r).items() if k not in OX_SECRET_COLS}
    if table == "settings" and d.get("key") in SETTINGS_SERVER_ONLY:
        return None  # review N5: server-side state (ntfy_topic is set by an admin only, digest marks, ...)
    if table == "webhooks" and "url" in d:
        d["url_hint"] = cal_url_hint(d.pop("url"))  # review N5: a Slack / Teams webhook address is itself the secret
    return umz_export_clean(table, d)


def umz_email_hash(email):
    """Review M1: other people's addresses leave the server only as this hash (the import finds the accounts it may see)."""
    e = (email or "").strip().lower() if isinstance(email, str) else ""
    return hashlib.sha256(("kalmido-people|" + e).encode()).hexdigest() if e else ""


def umz_people(c, uid):
    """The people of my lists (members, comment authors, assignees) with name + e-mail hash: the mapping on import."""
    own = "(SELECT id FROM lists WHERE owner_id=? AND (deleted_at IS NULL OR org_id IS NULL))"  # 2.102.0 review F3: an organisation's list in its trash is the organisation's
    out = {}
    for r in c.execute(f"""SELECT m.user_id, m.list_id, m.role, u.display_name, u.username, u.email, COALESCE(u.kind,'user') AS kind
                           FROM list_members m JOIN users u ON u.id=m.user_id WHERE m.list_id IN {own}""", (uid,)):
        if r["kind"] == "agent":
            continue
        p = out.setdefault(r["user_id"], {"user_id": r["user_id"], "name": r["display_name"] or r["username"],
                                           "email_hash": umz_email_hash(r["email"]), "lists": {}})
        p["lists"][str(r["list_id"])] = r["role"]
    for r in c.execute(f"""SELECT DISTINCT u.id, u.display_name, u.username, u.email, COALESCE(u.kind,'user') AS kind FROM users u
                           WHERE u.id IN (SELECT user_id FROM comments WHERE task_id IN (SELECT id FROM tasks WHERE list_id IN {own}))
                              OR u.id IN (SELECT assignee_id FROM tasks WHERE list_id IN {own})""", (uid, uid)):
        if r["id"] != uid and r["id"] not in out:
            out[r["id"]] = {"user_id": r["id"], "name": r["display_name"] or r["username"],
                            "email_hash": "" if r["kind"] == "agent" else umz_email_hash(r["email"]),
                            "lists": {}, **({"agent": True} if r["kind"] == "agent" else {})}
    return list(out.values())


def umz_extra_queries(uid):
    own = "(SELECT id FROM lists WHERE owner_id=? AND (deleted_at IS NULL OR org_id IS NULL))"  # 2.102.0 review F3: an organisation's list in its trash is the organisation's
    shared = "(SELECT m.list_id FROM list_members m JOIN lists l ON l.id=m.list_id WHERE m.user_id=? AND l.owner_id!=?)"
    sheets = "org_id IS NULL AND owner_id=?"
    return {
        "list_tags": (f"SELECT * FROM list_tags WHERE list_id IN {own}", (uid,)),
        "task_list_tags": (f"SELECT * FROM task_list_tags WHERE task_id IN (SELECT id FROM tasks WHERE list_id IN {own})", (uid,)),
        # Art. 15: the lists other people share with me (a reference) and what I wrote there
        "shared_lists": (f"""SELECT l.id, l.name, m.role, u.display_name AS owner_name, u.email AS owner_email FROM lists l
                             JOIN list_members m ON m.list_id=l.id AND m.user_id=? JOIN users u ON u.id=l.owner_id
                             WHERE l.id IN {shared}""", (uid, uid, uid)),
        "shared_comments": (f"""SELECT c.id, c.task_id, t.title AS task_title, t.list_id, c.body, c.created_at, c.edited_at FROM comments c
                                JOIN tasks t ON t.id=c.task_id WHERE c.user_id=? AND c.deleted_at IS NULL AND t.list_id IN {shared}""",
                            (uid, uid, uid)),
        # 2.84.0 (#1903): my own private filed e-mails (organisation mails, also the not assigned ones, are in the organisation export)
        "hub_mails": ("""SELECT id, client_id, list_id, message_id, from_addr, from_name, to_addrs, subject, sent_at, body, created_at
                         FROM hub_mails WHERE owner_id=? AND org_id IS NULL AND deleted_at IS NULL""", (uid,)),
        # 2.89.0 (#1916): my private tables (organisation tables are in the organisation export)
        "sheets": (f"SELECT * FROM sheets WHERE {sheets} AND deleted_at IS NULL", (uid,)),
        "sheet_columns": (f"SELECT * FROM sheet_columns WHERE sheet_id IN (SELECT id FROM sheets WHERE {sheets})", (uid,)),
        "sheet_rows": (f"SELECT * FROM sheet_rows WHERE sheet_id IN (SELECT id FROM sheets WHERE {sheets})", (uid,)),
        "sheet_cells": (f"SELECT * FROM sheet_cells WHERE sheet_id IN (SELECT id FROM sheets WHERE {sheets})", (uid,)),
        # 2.124.0 B (#2110): the file rows of my private tables' file cells
        "sheet_files": (f"SELECT id, sheet_id, name, mime, size, created_at, deleted_at FROM sheet_files WHERE sheet_id IN (SELECT id FROM sheets WHERE {sheets})", (uid,)),
        # 2.124.0 B (#2112): the cell history of my private tables
        "sheet_hist": (f"SELECT * FROM sheet_hist WHERE sheet_id IN (SELECT id FROM sheets WHERE {sheets})", (uid,)),
        # 2.99.1 A (#1959): my private video sign-offs (organisation ones are in the organisation export)
        "video_reviews": ("SELECT * FROM video_reviews WHERE owner_id=? AND org_id IS NULL AND deleted_at IS NULL", (uid,)),
        "video_versions": ("SELECT * FROM video_versions WHERE review_id IN (SELECT id FROM video_reviews WHERE owner_id=? AND org_id IS NULL)", (uid,)),
        "video_comments": ("SELECT * FROM video_comments WHERE review_id IN (SELECT id FROM video_reviews WHERE owner_id=? AND org_id IS NULL) "
                           "AND deleted_at IS NULL", (uid,)),
        # 2.148.1 C (#2494): Art. 15 -- the list of my private files (not their content), my private knowledge pages, my chats
        # with agents, what I wrote in direct messages, my absences and timesheets (protected fields decrypted, UMZ_DECRYPT)
        "private_files": ("SELECT id, parent_id, kind, name, mime, size, created_at, updated_at FROM fs_nodes WHERE owner_id=? "
                          "AND org_id IS NULL AND deleted_at IS NULL ORDER BY id", (uid,)),
        "wiki_pages": ("SELECT id, org_id, owner_id, path, body, attrs, created_at, updated_at FROM wiki_pages WHERE owner_id=? "
                       "AND org_id IS NULL AND deleted_at IS NULL ORDER BY id", (uid,)),
        "agent_chats": ("SELECT id, agent_id, sender, body, task_id, created_at FROM agent_chat WHERE user_id=? ORDER BY id", (uid,)),
        "direct_messages": ("SELECT m.id, m.room_id, m.body, m.enc, m.created_at, m.edited_at FROM tchat_msgs m JOIN tchat_rooms r ON r.id=m.room_id "
                            "WHERE r.kind='dm' AND m.user_id=? AND m.deleted_at IS NULL ORDER BY m.id", (uid,)),
        "absences": ("SELECT id, org_id, kind, start_date, end_date, half_day, note, status, decided_at, decision_note, created_at "
                     "FROM hub_absences WHERE user_id=? AND deleted_at IS NULL ORDER BY start_date", (uid,)),
        "timesheets": ("SELECT id, org_id, month, state, closed_at, decided_at, note, created_at, updated_at FROM time_sheets "
                       "WHERE user_id=? ORDER BY month", (uid,)),
    }


# 2.148.1 C (#2494): tables whose protected fields are decrypted for the export (the key of the row's organisation)
UMZ_DECRYPT = ("absences", "hub_absences"), ("timesheets", "time_sheets")


def _umz_plain(c, table, d):
    """A row of the export with its encrypted fields opened (an unreadable value is left out, never the export)."""
    from ..core.orgcrypt import OrgCryptError, oc_dec_fields
    if table == "wiki_pages":
        from ..wiki.wkhist import wsb_body_or
        d["body"] = wsb_body_or(c, d)
        return d
    src = dict(UMZ_DECRYPT).get(table)
    if src and d.get("org_id"):
        try:
            return oc_dec_fields(c, d["org_id"], src, d)
        except OrgCryptError:
            from ..core.orgcrypt import FIELDS
            return {k: v for k, v in d.items() if k not in FIELDS[src]}
    return d


class _Out:
    def __init__(self):
        self.files, self.tables = [], {}


def _put(zf, out, name, data):
    zi = zipfile.ZipInfo(name, date_time=time.localtime()[:6])
    zi.compress_type = zipfile.ZIP_DEFLATED
    zf.writestr(zi, data)
    out.files.append({"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})


def _put_rows(zf, out, table, rows):
    """data/<table>.json streamed into the ZIP (one row per line)."""
    name = f"data/{table}.json"
    h, size, n = hashlib.sha256(), 0, 0
    with zf.open(zipfile.ZipInfo(name, date_time=time.localtime()[:6]), "w", force_zip64=True) as w:
        def put(s):
            nonlocal size
            b = s.encode()
            h.update(b)
            size += len(b)
            w.write(b)
        put("[")
        for r in rows:
            put(("," if n else "") + "\n" + json.dumps(r, ensure_ascii=False, default=_jdef, sort_keys=True))
            n += 1
        put("\n]\n")
    out.files.append({"path": name, "size": size, "sha256": h.hexdigest()})
    out.tables[table] = n


def umz_att_name(kind, rid, name):
    return f"files/{kind}/{int(rid)}-{_safe_part(name)}"


def umz_build(c, uid, stream, export_id):
    """Writes the ZIP of person uid into stream; returns the manifest."""
    from ..accounts.settings import umz_export_queries
    from ..admin.hosting import hosted
    out = _Out()
    have = {r[0] for r in c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()")}
    u = c.execute("SELECT id, username, display_name, email FROM users WHERE id=?", (uid,)).fetchone()
    q = umz_export_queries(uid)
    q.update(umz_extra_queries(uid))
    client_enc = {"attachments": [], "locked_notes": 0}
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        files = {}  # (kind, row id) -> path in the ZIP
        inf, locked = sc_locked_all(c), []  # 2.209.0 D (#1856): files the virus scanner locked stay out, listed in the manifest
        for kind, table in (("attachments", "attachments"), ("list_files", "list_files")):
            sql, args = q[table]
            for r in c.execute(sql, args).fetchall():
                full = _under(ATT_DIR, r["path"])
                if not full:
                    continue
                sig = inf.get(("att" if table == "attachments" else "list", int(r["id"]), 0))
                if sig is not None:
                    locked.append({"area": table, "id": r["id"], "name": r["name"] or "", "signature": sig})
                    continue
                name = umz_att_name(kind, r["id"], r["name"])
                _put(zf, out, name, oc_read_file(c, full))
                files[(table, r["id"])] = name
                if table == "attachments" and "enc" in r.keys() and r["enc"]:
                    client_enc["attachments"].append(name)
        for table, (sql, args) in q.items():
            def rows(table=table, sql=sql, args=args):
                for r in c.execute(sql, args):
                    d = umz_clean(table, r)
                    if d is None:
                        continue
                    if table == "shared_lists":  # review M1: the owner's address only as a hash
                        d["owner_email_hash"] = umz_email_hash(d.pop("owner_email", ""))
                    if (table, d.get("id")) in files:
                        d["file"] = files[(table, d["id"])]
                    yield _umz_plain(c, table, d)  # 2.148.1 C (#2494)
            _put_rows(zf, out, table, rows())
        _put_rows(zf, out, "people", umz_people(c, uid))
        if "msv_links" in have:  # 2.73.0: msv_links comes with part A -- the server accounts, never their token
            try:
                with c.savepoint():
                    links = [dict(r) for r in c.execute("SELECT id, name, short, color, base_url, created_at FROM msv_links "
                                                        "WHERE user_id=? AND deleted_at IS NULL ORDER BY id", (uid,))]
            except Exception:  # noqa: BLE001 -- another shape of the table: no server accounts in the file
                links = []
            _put_rows(zf, out, "server_links", links)
        from ..life.budget import bud_export  # 2.72.0 (#1333): my budgets, decrypted like Settings > Export
        _put_rows(zf, out, "budgets", bud_export(c, uid))
        client_enc["locked_notes"] = out.tables.get("task_note_locks", 0)
        manifest = {
            "format": UMZ_FORMAT, "v": UMZ_V, "kalmido_version": APP_VERSION, "created_at": iso(now_utc()),
            "source": {"url": PUBLIC_URL, "hosted": bool(hosted())},
            "user": {"id": u["id"], "name": u["display_name"] or u["username"], "email": u["email"] or ""},
            "tables": out.tables, "files": out.files,
            "client_encrypted": {**client_enc, "note": "Encrypted in the browser: stored here as ciphertext, only with your password readable."},
            "export_id": export_id, "not_included": list(UMZ_NOT_INCLUDED),
            "locked_files": locked,  # 2.209.0 D (#1856)
        }
        mb = json.dumps(manifest, ensure_ascii=False, indent=1, default=_jdef).encode()
        zi = zipfile.ZipInfo("manifest.json", date_time=time.localtime()[:6])
        zi.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(zi, mb)
        lines = [f"{hashlib.sha256(mb).hexdigest()}  manifest.json"] + [f"{f['sha256']}  {f['path']}" for f in out.files]
        zi = zipfile.ZipInfo("checksum.sha256", date_time=time.localtime()[:6])
        zf.writestr(zi, ("\n".join(lines) + "\n").encode())
    return manifest


# ---------------------------------------------------------------- state, thread, clean-up
def _udir(uid):
    return os.path.join(UMZ_DIR, str(int(uid)))


def _state(uid):
    try:
        with open(os.path.join(_udir(uid), "state.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def umz_write_state(folder, d):
    os.makedirs(folder, mode=0o700, exist_ok=True)
    p = os.path.join(folder, "state.json")
    tmp = p + ".tmp"
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(tmp, p)


def _running(uid):
    t = _UMZ.get(int(uid))
    return bool(t and t.is_alive())


def umz_log_org_lists(c, uid):
    """2.148.1 C (#2492): an export that carries lists of an organisation (lists I own there) is noted in the organisation's
    list history (org_list_log "export"), the admins see it. The caller commits."""
    with system_ctx(c):  # the organisation's history (also of one I left while I still own a list there)
        rows = c.execute("SELECT id, name, org_id FROM lists WHERE owner_id=? AND org_id IS NOT NULL AND deleted_at IS NULL", (uid,)).fetchall()
        at = iso(now_utc())
        for r in rows:
            c.execute("INSERT INTO org_list_log(org_id,list_id,list_name,action,by_id,owner_id,to_id,created_at) VALUES(?,?,?,'export',?,?,NULL,?)",
                      (r["org_id"], r["id"], r["name"], uid, uid, at))
    return len(rows)


def umz_user_conn(c, uid):
    """The background thread works in the person's own access context (row-level security as in their requests)."""
    with system_ctx(c):  # the person's memberships (structure) for their context
        ax = acx_of(c, uid)
    c.set_ctx(uid, ax.org_ids, "user")


def umz_run(uid, export_id):
    c = connect()
    part = None
    try:
        umz_user_conn(c, uid)
        key = umz_key(uid, "export")
        part = os.path.join(_udir(uid), secrets.token_hex(8) + ".part")
        with os.fdopen(os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as f:
            w = UmzWriter(f, key)
            man = umz_build(c, uid, w, export_id)
            w.finish()
            os.fsync(f.fileno())
        name = f"kalmido-account-{now_utc():%Y-%m-%d}{UMZ_SUFFIX}"
        for old in os.listdir(_udir(uid)):
            if old.endswith(UMZ_SUFFIX):
                os.remove(os.path.join(_udir(uid), old))
        os.replace(part, os.path.join(_udir(uid), name))
        part = None
        umz_log_org_lists(c, uid)
        c.commit()
        done = now_utc()
        st = _state(uid) or {}
        umz_write_state(_udir(uid), {"state": "done", "started_at": st.get("started_at"), "done_at": iso(done),
                                     "expires_at": iso(done + timedelta(hours=UMZ_KEEP_H)), "file": name, "bytes": w.size,
                                     "sealed": bool(key), "export_id": export_id, "rows": sum(man["tables"].values()),
                                     "files": sum(1 for x in man["files"] if x["path"].startswith("files/"))})
        c.rollback()
        print(f"account export of user {uid}: {w.size} bytes", flush=True)
    except Exception as e:  # noqa: BLE001 -- the state says it failed; never content in the message
        try:
            c.rollback()
        except Exception:  # noqa: BLE001
            pass
        print(f"account export of user {uid} failed: {type(e).__name__}", flush=True)
        st = _state(uid) or {}
        umz_write_state(_udir(uid), {"state": "failed", "started_at": st.get("started_at"), "error": type(e).__name__, "done_at": iso(now_utc())})
    finally:
        if part and os.path.exists(part):
            os.remove(part)
        c.close()
        with _UMZ_LOCK:
            _UMZ.pop(int(uid), None)


def umz_status(uid):
    st = _state(uid) or {"state": "none"}
    if st.get("state") == "running" and not _running(uid):
        st = {**st, "state": "failed", "error": "interrupted"}
    if st.get("state") == "done":
        p = os.path.join(_udir(uid), st.get("file") or "-")
        if not os.path.isfile(p) or st.get("expires_at", "") <= iso(now_utc()):
            st = {"state": "none"}
    out = {k: st.get(k) for k in ("state", "started_at", "done_at", "expires_at", "file", "bytes", "files", "rows") if st.get(k) is not None}
    if st.get("state") == "failed":
        out["error"] = tr("The export was interrupted. Please start it again.") if st.get("error") == "interrupted" else \
            tr("The export failed. Please try again later or ask the server admin (server log).")
    return out


UMZ_CLEAN = {"at": 0.0}


def umz_cleanup(c=None, force=False):
    """Watchdog (at most every 10 minutes): account exports after UMZ_KEEP_H hours, leftovers of interrupted runs, and
    the uploads of account imports (acctimport.py) that are finished, cancelled or older than a day."""
    if not force and time.time() - UMZ_CLEAN["at"] < 600:
        return 0
    UMZ_CLEAN["at"] = time.time()
    n = 0
    if os.path.isdir(UMZ_DIR):
        now = iso(now_utc())
        for d in os.listdir(UMZ_DIR):
            p = os.path.join(UMZ_DIR, d)
            if not d.isdigit() or not os.path.isdir(p) or _running(int(d)):
                continue
            st = _state(int(d)) or {}
            for fn in os.listdir(p):
                fp = os.path.join(p, fn)
                old = time.time() - os.path.getmtime(fp) > UMZ_KEEP_H * 3600
                # 2.148.1 C (#2482): a .part only when stale (a run of another process writes it right now)
                if (fn.endswith(".part") and time.time() - os.path.getmtime(fp) > PART_STALE_S) or (
                        fn.endswith(UMZ_SUFFIX) and (fn != st.get("file") or st.get("expires_at", "") <= now or old)):
                    os.remove(fp)
                    n += 1
            if not any(f.endswith((UMZ_SUFFIX, ".part")) for f in os.listdir(p)):  # 2.148.1 C (#2482): + a running .part
                shutil.rmtree(p, ignore_errors=True)
    from .acctimport import umz_import_cleanup
    from .wkimport import wki_cleanup  # 2.177.0 (#2685): uploads of the knowledge import
    return n + umz_import_cleanup() + wki_cleanup()


# ---------------------------------------------------------------- routes (people only)
@app.get("/api/account/export")
def umz_get():
    """The state of my account export: none | running | done (file, bytes, expires_at) | failed (error)."""
    umz_person()
    return jsonify(keep_hours=UMZ_KEEP_H, **umz_status(me()))


@app.post("/api/account/export")
def umz_start():
    """Starts my account export in the background (one at a time; 409 while one runs, 507 without the disk space)."""
    umz_person()
    c = db()
    uid = me()
    from ..accounts.settings import umz_export_queries
    q = umz_export_queries(uid)
    need = 0
    for t in ("attachments", "list_files"):
        sql, args = q[t]
        need += c.execute(f"SELECT COALESCE(SUM(size),0) FROM ({sql}) x", args).fetchone()[0] or 0
    if not umz_space_ok(UMZ_DIR, need * 1.1):
        return err(tr("There is not enough space on the server for the export. Please ask the server admin."), 507)
    with _UMZ_LOCK:
        if _running(uid):
            return err(tr("Your export is already running"), 409)
        os.makedirs(_udir(uid), mode=0o700, exist_ok=True)
        umz_write_state(_udir(uid), {"state": "running", "started_at": iso(now_utc())})
        t = threading.Thread(target=umz_run, args=(uid, secrets.token_hex(16)), daemon=True)
        _UMZ[uid] = t
        t.start()
    c.rollback()
    return jsonify(umz_status(uid)), 202


@app.get("/api/account/export/file")
def umz_download():
    umz_person()
    uid = me()
    st = umz_status(uid)
    if st.get("state") != "done":
        raise Denied(404)
    raw = _state(uid) or {}
    path = os.path.join(_udir(uid), st["file"])
    key = umz_key(uid, "export") if raw.get("sealed") else None
    return Response(umz_stream(path, key, raw["bytes"]), mimetype="application/zip", direct_passthrough=True,
                    headers={"Content-Disposition": f'attachment; filename="{st["file"]}"', "Content-Length": str(raw["bytes"]),
                             "Cache-Control": "no-store"})


@app.delete("/api/account/export")
def umz_delete():
    """Removes my finished export now (instead of after UMZ_KEEP_H hours)."""
    umz_person()
    uid = me()
    if _running(uid):
        return err(tr("Your export is already running"), 409)
    shutil.rmtree(_udir(uid), ignore_errors=True)
    return jsonify(ok=True)

