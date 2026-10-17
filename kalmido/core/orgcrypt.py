"""2.42.0 (#828): server-side keys per organisation -- encryption at rest of the office's sensitive fields and of the
files in the storage of an organisation (attachments of its lists' tasks, project files, office PDFs / XML).

Key model:
  master key  = KALMIDO_SECRET_KEY (core/config.py SECRET_KEY; never in the database, the data folder or a backup)
  KEK         = HKDF-SHA256(master key, info=b"kalmido-orgkey-kek-v1")
  org key     = 32 random bytes per organisation, AES-256-GCM wrapped with the KEK (associated data binds the org id),
                table org_keys (wrapped + kek_check: tells a wrong master key apart from damaged data)
  fields      = "kenc1:" + base64url(nonce | ciphertext), AES-256-GCM with the org key, AAD = "kenc1|<org id>|<table.column>"
  files       = b"KENC1\\n" + org id (8 bytes, big endian) + nonce + ciphertext, AAD = header + ctx (b"file"); the org id in the
                header keeps a file readable after its list moved to another organisation
Without a master key nothing is encrypted (everything plain as before); reading plain values / files always works (no
prefix / magic = unchanged), so the start-up run (oc_migrate) and the way back (admin/orgcrypt_cli.py decrypt-all) can be
repeated at any point. The org key itself is the recovery key (grouped base32, Settings > Organisation): with it a new
master key can rewrap the org key (orgcrypt_cli rewrap). Deleting an organisation deletes its key row: what stays in
the database or on disk of that organisation can no longer be read (older backups still hold the wrapped key).
Never log, print or return a key, a recovery key or a decrypted protected value outside the routes that show it anyway.
"""
import base64
import hashlib
import hmac
import io
import json
import os
import re
import struct
import threading
from decimal import Decimal, InvalidOperation

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from flask import jsonify

from ..core.config import app, SECRET_KEY
from ..core.i18n import N_, tr
from ..core.pg import system_ctx

PREFIX = "kenc1:"
MAGIC = b"KENC1\n"
_HEAD = len(MAGIC) + 8 + 12  # magic + org id + nonce
FILE_CTX = b"file"

# the protected fields: table -> columns (TEXT, encrypted as a whole; JSON columns hold "kenc1:..." instead of the JSON).
# Inside JSON columns (JSON_KEYS): office_settings.data["company"] (the free company lines with bank / tax lines) and
# office_docs.totals["costs"] / ["margin"] (the purchase side of a document). office_doc_items.cost (NUMERIC) goes to
# cost_enc (cost = 0 then, oc_item_*). office_docs.sender = the frozen company (bank, tax ids) of a finalised document;
# office_doc_log.detail = before / after of changes (company fields, purchase prices)
FIELDS = {
    "office_company": ("tax_number", "vat_id", "iban", "bic", "bank_name"),
    "office_contracts": ("rates",),
    "office_signoffs": ("signer_name", "signer_email", "reason", "ip", "user_agent"),  # 2.50.0 (#1200): who signed, from where
    "office_docs": ("sender",),
    "office_doc_log": ("detail",),
    "office_roles": ("costs",),  # 2.47.0 (#1649): the purchase of a role
    "office_purchases": ("amount",),  # 2.47.0 (#1649): the purchase of an accepted quotation
    "office_doc_parts": ("sheet",),  # 2.47.0 (#1216): the shoot calculation sheet (markups, rates of external crew = purchase)
    "office_trips": ("people", "note"),  # 2.47.3 (#1022): participants and note of a trip
    "office_trip_items": ("amount", "amount_home"),  # 2.47.3 (#1022): the amounts of a travel receipt
    "office_fixed_costs": ("amount",),  # 2.47.3 (#1652): fixed costs of the cash flow
    "office_deals": ("value", "contact", "note", "lost_reason"),  # 2.50.0 (#1196): the sales pipeline
    "hub_absences": ("kind", "note"),  # 2.50.0 (#1195): the kind of an absence (sick leave = health data) and its note
}
JSON_KEYS = {("office_settings", "data"): ("company",), ("office_docs", "totals"): ("costs", "margin"),
             ("office_doc_parts", "totals"): ("costs", "margin")}  # 2.47.0 (#1215)
# 2.46.1 (#1641): what Settings > Administration shows as encrypted / not encrypted. Every FIELDS table and JSON_KEYS entry
# has its category here (a test checks it); plus the organisations' files and the tokens sealed with the server key itself
# (git.py git_seal, oidc.py oidc_seal). Everything else is stored as it is (the list "plain" names the main parts).
PM_CRYPT_CATS = {"office_company": N_("Bank and tax data of the company"), ("office_settings", "data"): N_("Bank and tax data of the company"),
                 ("office_docs", "totals"): N_("Purchase prices and margins"), "office_contracts": N_("Framework contract rates"),
                 "office_docs": N_("Senders of finished documents"), "office_doc_log": N_("The log of the documents"),
                 "office_signoffs": N_("Signatures of customers (name, address, device)"),  # 2.50.0 (#1200)
                 "files": N_("Files of organisations"), "tokens": N_("Stored access tokens (Git, client secret of the single sign-on)"),
                 # 2.47.0 (#1649, #1215, #1216): roles' purchase prices, purchases of accepted quotations, parts and shoot sheets
                 "office_roles": N_("Purchase prices and margins"), "office_purchases": N_("Purchase prices and margins"),
                 "office_doc_parts": N_("Purchase prices and margins"), ("office_doc_parts", "totals"): N_("Purchase prices and margins"),
                 # 2.47.3 (#1022, #1652): travel expenses (participants, amounts) and fixed costs
                 "office_trips": N_("Travel expenses"), "office_trip_items": N_("Travel expenses"), "office_fixed_costs": N_("Fixed costs"),
                 "office_deals": N_("Sales pipeline"),  # 2.50.0 (#1196)
                 "hub_absences": N_("Kind and note of absences")}  # 2.50.0 (#1195)
PM_CRYPT_PLAIN = (N_("Tasks"), N_("Notes"), N_("Descriptions"), N_("Comments"), N_("Contacts"), N_("Chats"))
# 2.64.1 (#1817): what the browser encrypts in lists with a lock (collab/liste2e.py LE2E_FIELDS); the plain list holds them apart
PM_CRYPT_BROWSER = (N_("Titles, descriptions, subtasks, comments, notes, section names, free-text fields, links and code snippets of lists with a lock"),)
PM_CRYPT_BROWSER += (N_("Names and texts of knowledge pages in spaces with a lock"),)  # 2.64.3 A (#1817): the lock per knowledge space
PM_CRYPT_PLAIN_NOTE = N_("Tasks, descriptions, notes and comments: except in lists with a lock")


def pm_crypt_scope():
    """{encrypted: [..], plain: [..]} in the user's language (no key material, the same for every organisation)."""
    return {"encrypted": list(dict.fromkeys(tr(v) for v in PM_CRYPT_CATS.values())), "plain": [tr(x) for x in PM_CRYPT_PLAIN],
            "browser": [tr(x) for x in PM_CRYPT_BROWSER], "plain_note": tr(PM_CRYPT_PLAIN_NOTE)}  # 2.64.1 (#1817)


class OrgCryptError(Exception):
    """Decrypting failed: a wrong / missing master key, a damaged value, or the organisation's key is gone."""


OC_ERR = N_("The organisation's data cannot be decrypted: the server key (KALMIDO_SECRET_KEY) does not match, or the organisation's key is missing. See SELF-HOSTING.md, encryption.")


@app.errorhandler(OrgCryptError)
def oc_error(e):
    # never the value or a key in the answer; the server log gets the reason (no secrets in it either)
    print("orgcrypt:", str(e), flush=True)
    return jsonify(error=tr(OC_ERR), code="orgcrypt"), 500


_LOCK = threading.Lock()
_CACHE = {}  # (org id, wrapped) -> org key; a deleted / rewrapped row is never found again (the wrapped text is the key)


def _b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _b64u_dec(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _kek(master=None):
    m = master if master is not None else SECRET_KEY
    if not m:
        return None
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"kalmido-orgkey-kek-v1").derive(m)


def _kek_check(kek, org_id):
    return hmac.new(kek, b"kalmido-orgkey-check-v1|%d" % int(org_id), hashlib.sha256).hexdigest()[:32]


def _wrap(kek, org_id, key):
    n = os.urandom(12)
    return "v1." + _b64u(n + AESGCM(kek).encrypt(n, key, b"kalmido-orgkey|%d" % int(org_id)))


def _unwrap(kek, org_id, wrapped):
    if not wrapped.startswith("v1."):
        raise OrgCryptError("unknown key format")
    raw = _b64u_dec(wrapped[3:])
    try:
        return AESGCM(kek).decrypt(raw[:12], raw[12:], b"kalmido-orgkey|%d" % int(org_id))
    except InvalidTag:
        raise OrgCryptError("the organisation key cannot be unwrapped") from None


def oc_enabled():
    """True when the server has a master key (KALMIDO_SECRET_KEY): org keys exist and can be used."""
    return bool(SECRET_KEY)


def oc_active(c):
    """True when NEW values / files are encrypted: a master key and the instance switch org_encrypt (default "1")."""
    if not SECRET_KEY:
        return False
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        r = c.execute("SELECT value FROM settings WHERE key='org_encrypt'").fetchone()
    return (r[0] if r else "1") != "0"


def _row(c, org_id):
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        return c.execute("SELECT wrapped, kek_check FROM org_keys WHERE org_id=?", (int(org_id),)).fetchone()


def _open_row(org_id, r, kek=None):
    kek = kek or _kek()
    if not hmac.compare_digest(str(r["kek_check"]), _kek_check(kek, org_id)):
        raise OrgCryptError(f"org {int(org_id)}: the server key (KALMIDO_SECRET_KEY) is not the one this organisation's key was made with")
    ck = (int(org_id), r["wrapped"])
    with _LOCK:
        k = _CACHE.get(ck)
    if k is None:
        k = _unwrap(kek, org_id, r["wrapped"])
        with _LOCK:
            _CACHE[ck] = k
    return k


def _create(c, org_id):
    """A new key row. Made in an own, committed transaction (a key is never lost with a rolled back request while a file
    sealed with it stays on disk); when the organisation itself is not committed yet (made in the caller's transaction)
    the row goes into the caller's transaction."""
    kek = _kek()
    key = os.urandom(32)
    vals = (int(org_id), _wrap(kek, org_id, key), _kek_check(kek, org_id), _now())
    sql = ("INSERT INTO org_keys(org_id, wrapped, kek_check, created_at) VALUES(?,?,?,?) "
           "ON CONFLICT(org_id) DO NOTHING")
    from ..core.db import connect
    c2 = None
    try:
        c2 = connect()
        with system_ctx(c2):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
            c2.execute("SET LOCAL lock_timeout = '3s'")
            c2.execute(sql, vals)
        c2.commit()
    except Exception:  # noqa: BLE001 -- the organisation is not visible outside the caller's transaction (or busy)
        if c2 is not None:
            try:
                c2.rollback()
            except Exception:  # noqa: BLE001
                pass
        with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
            with c.savepoint():
                c.execute(sql, vals)
    finally:
        if c2 is not None:
            c2.close()
    return _row(c, org_id)


def _now():
    from ..core.db import iso, now_utc
    return iso(now_utc())


def oc_key(c, org_id, create=True):
    """The organisation's key (32 bytes), made on first use; None without a master key or without an organisation
    (create=False: None while it has none). OrgCryptError: the master key does not match."""
    if not SECRET_KEY or not org_id:
        return None
    r = _row(c, org_id)
    if r is None:
        if not create:
            return None
        with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
            if not c.execute("SELECT 1 FROM orgs WHERE id=?", (int(org_id),)).fetchone():
                return None
        r = _create(c, org_id)
        if r is None:
            return None
    return _open_row(org_id, r)


def oc_forget(org_id=None):
    """Drop cached keys (one organisation or all): after deleting / rewrapping a key."""
    with _LOCK:
        for k in [k for k in _CACHE if org_id is None or k[0] == int(org_id)]:
            _CACHE.pop(k, None)


# ---- fields -----------------------------------------------------------------------------------------------------------
def _aad(org_id, ctx):
    return f"kenc1|{int(org_id)}|{ctx}".encode()


def oc_enc_k(key, org_id, ctx, value):
    """Encrypt with a key the caller already holds (loops). '' / None stay as they are; an encrypted value is kept."""
    if value is None or value == "" or key is None:
        return value
    value = str(value)
    if value.startswith(PREFIX):
        return value
    n = os.urandom(12)
    return PREFIX + _b64u(n + AESGCM(key).encrypt(n, value.encode(), _aad(org_id, ctx)))


def oc_dec_k(key, org_id, ctx, value):
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return value
    if key is None:
        raise OrgCryptError(f"org {org_id}: no key for an encrypted value ({ctx})")
    try:
        raw = _b64u_dec(value[len(PREFIX):])
        return AESGCM(key).decrypt(raw[:12], raw[12:], _aad(org_id, ctx)).decode()
    except (InvalidTag, ValueError, UnicodeDecodeError):
        raise OrgCryptError(f"org {org_id}: an encrypted value ({ctx}) cannot be decrypted") from None


def oc_enc(c, org_id, ctx, value):
    """'kenc1:' + base64url(nonce|ciphertext), bound to the organisation and ctx ('table.column'). '' stays ''; plain when
    the encryption is off (no master key / org_encrypt=0) or there is no organisation."""
    if value is None or value == "" or not org_id or not oc_active(c):
        return value
    return oc_enc_k(oc_key(c, org_id), org_id, ctx, value)


def oc_dec(c, org_id, ctx, value):
    """The plain value; a value without the prefix is returned unchanged. OrgCryptError when it cannot be decrypted."""
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return value
    return oc_dec_k(oc_key(c, org_id, create=False), org_id, ctx, value)


def oc_is_enc(value):
    return isinstance(value, str) and value.startswith(PREFIX)


def oc_dec_fields(c, org_id, table, row):
    """A dict copy of row with every protected column of table decrypted (the load helper for exports / serializers):
    whole columns (FIELDS), the protected keys inside JSON columns (JSON_KEYS, the column stays JSON text) and
    office_doc_items.cost_enc -> cost (cost_enc dropped)."""
    d = dict(row)
    key = None
    for k in FIELDS.get(table, ()):
        if oc_is_enc(d.get(k)):
            key = key or oc_key(c, org_id, create=False)
            d[k] = oc_dec_k(key, org_id, f"{table}.{k}", d[k])
    for (t, col), keys in JSON_KEYS.items():
        if t == table and isinstance(d.get(col), str) and PREFIX in d[col]:
            try:
                j = json.loads(d[col])
            except ValueError:
                continue
            if isinstance(j, dict):
                oc_json_load(c, org_id, table, col, j)
                d[col] = json.dumps(j, ensure_ascii=False)
    if table == "office_doc_items" and "cost_enc" in d:
        oc_item_load(c, org_id, d)
    return d


oc_dec_row = oc_dec_fields  # the name agent C asked for (#833)


def oc_enc_fields(c, org_id, table, values):
    """values (dict column -> plain value) with the protected columns of table encrypted (when active)."""
    d = dict(values)
    if not org_id or not oc_active(c):
        return d
    key = None
    for k in FIELDS.get(table, ()):
        if d.get(k) not in (None, "") and not oc_is_enc(d.get(k)):
            key = key or oc_key(c, org_id)
            d[k] = oc_enc_k(key, org_id, f"{table}.{k}", d[k])
    return d


def oc_json_load(c, org_id, table, col, j):
    """Decrypt the protected keys of a parsed JSON column in place (JSON_KEYS); returns j. A key holding a JSON value
    (office_settings.company is a dict) comes back parsed."""
    for k in JSON_KEYS.get((table, col), ()):
        if oc_is_enc(j.get(k)):
            v = oc_dec(c, org_id, f"{table}.{col}.{k}", j[k])
            try:
                j[k] = json.loads(v)
            except ValueError:
                j[k] = v
    return j


def oc_json_store(c, org_id, table, col, j):
    """A copy of the parsed JSON column j with its protected keys encrypted (when active), for json.dumps."""
    j = dict(j)
    if not org_id or not oc_active(c):
        return j
    key = None
    for k in JSON_KEYS.get((table, col), ()):
        v = j.get(k)
        if v in (None, "", {}, []) or oc_is_enc(v):
            continue
        key = key or oc_key(c, org_id)
        j[k] = oc_enc_k(key, org_id, f"{table}.{col}.{k}", json.dumps(v, ensure_ascii=False, default=str))
    return j


# keys whose presence in an office log entry (office_doc_log.detail, JSON text) makes the whole entry encrypted: company
# fields, purchase prices, contract rates. Other entries stay plain (the daily count of own-text mails reads them)
LOG_MARKERS = ('"iban"', '"bic"', '"bank_name"', '"tax_number"', '"vat_id"', '"cost"', '"costs"', '"margin"', '"rates"', '"company"', '"bank_lines"',
               '"cost_day"', '"cost_hour"', '"markup_pct"')  # 2.47.0 (#1649): the roles' purchase prices / markup


def oc_log_detail(c, org_id, text):
    """The detail text to store for an office log entry: encrypted when it carries a protected key (and active)."""
    if not text or oc_is_enc(text) or not any(m in text for m in LOG_MARKERS):
        return text
    return oc_enc(c, org_id, "office_doc_log.detail", text)


# ---- purchase prices of positions (office_doc_items.cost NUMERIC -> cost_enc TEXT) ---------------------------------------
def oc_num(s):
    """A decimal text -> int when whole, else float (what the database layer returns for NUMERIC)."""
    d = Decimal(str(s))
    return int(d) if d == d.to_integral_value() else float(d)


def oc_item_load(c, org_id, item):
    """item (dict) with cost taken from cost_enc when that holds a value (cost_enc dropped from the dict)."""
    enc = item.pop("cost_enc", None)
    if enc:
        item["cost"] = oc_num(oc_dec(c, org_id, "office_doc_items.cost_enc", enc))
    return item


def oc_item_store(c, org_id, row):
    """row (dict for an INSERT into office_doc_items) with cost moved to cost_enc (cost 0) when active."""
    row = dict(row)
    row.pop("cost_enc", None)
    cost = row.get("cost")
    if not org_id or cost in (None, "") or not oc_active(c):
        return row
    try:
        if Decimal(str(cost)) == 0:
            return row
    except InvalidOperation:
        return row
    row["cost_enc"] = oc_enc(c, org_id, "office_doc_items.cost_enc", format(Decimal(str(cost)), "f"))
    row["cost"] = 0
    return row


# ---- files ------------------------------------------------------------------------------------------------------------
def oc_seal(c, org_id, data, ctx=FILE_CTX):
    """MAGIC + org id + nonce + ciphertext; unchanged when off, without an organisation or already sealed."""
    if not org_id or not oc_active(c) or data[:len(MAGIC)] == MAGIC:
        return data
    return oc_seal_k(oc_key(c, org_id), org_id, data, ctx)


def oc_seal_k(key, org_id, data, ctx=FILE_CTX):
    if key is None or data[:len(MAGIC)] == MAGIC:
        return data
    head = MAGIC + struct.pack(">q", int(org_id))
    n = os.urandom(12)
    return head + n + AESGCM(key).encrypt(n, bytes(data), head + bytes(ctx))


def oc_file_org(data):
    """The organisation a sealed file belongs to (from its header), None for a plain file."""
    if data[:len(MAGIC)] != MAGIC or len(data) < _HEAD:
        return None
    return struct.unpack(">q", data[len(MAGIC):len(MAGIC) + 8])[0]


def oc_open(c, data, ctx=FILE_CTX):
    """The plain bytes; data without MAGIC is returned unchanged. The org id comes from the header."""
    if data[:len(MAGIC)] != MAGIC:
        return data
    if len(data) < _HEAD + 16:
        raise OrgCryptError("a sealed file is truncated")
    oid = oc_file_org(data)
    key = oc_key(c, oid, create=False)
    if key is None:
        raise OrgCryptError(f"org {oid}: no key for a sealed file")
    return oc_open_k(key, data, ctx)


def oc_open_k(key, data, ctx=FILE_CTX):
    if data[:len(MAGIC)] != MAGIC:
        return data
    head = data[:len(MAGIC) + 8]
    try:
        return AESGCM(key).decrypt(data[len(head):_HEAD], data[_HEAD:], head + bytes(ctx))
    except InvalidTag:
        raise OrgCryptError(f"org {oc_file_org(data)}: a sealed file cannot be decrypted") from None


def oc_is_sealed_file(path):
    try:
        with open(path, "rb") as f:
            return f.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


def oc_read_file(c, path, ctx=FILE_CTX):
    with open(path, "rb") as f:
        return oc_open(c, f.read(), ctx)


def _write_atomic(path, data, mode=None):
    tmp = f"{path}.oc-{os.getpid()}-{threading.get_ident()}.tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def oc_write_file(c, org_id, path, data, ctx=FILE_CTX):
    """Write data (sealed when active and the file belongs to an organisation), atomically (tmp + os.replace)."""
    _write_atomic(path, oc_seal(c, org_id, data, ctx))


def oc_reseal_file(path, new_data):
    """Replace a file's bytes atomically, keeping its permissions (the migration and the way back)."""
    try:
        mode = os.stat(path).st_mode & 0o7777
    except OSError:
        mode = None
    _write_atomic(path, new_data, mode)


OVERHEAD = _HEAD + 16  # bytes a sealed file is larger than its plain content


def oc_plain_size(path):
    """The size of a stored file's plain content (a sealed file without its header and tag)."""
    n = os.path.getsize(path)
    return n - OVERHEAD if n >= OVERHEAD and oc_is_sealed_file(path) else n


def oc_seal_path(c, org_id, path, ctx=FILE_CTX):
    """Seal a file that was just written in plain (upload, copy) when it belongs to an organisation and the encryption is
    active; a sealed file stays as it is. True when it was sealed."""
    if not org_id or not oc_active(c) or oc_is_sealed_file(path):
        return False
    key = oc_key(c, org_id)
    if key is None:
        return False
    with open(path, "rb") as f:
        data = f.read()
    oc_reseal_file(path, oc_seal_k(key, org_id, data, ctx))
    return True


def oc_task_org(c, tid):
    """The organisation of a task's list (None: a private list / no task)."""
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        r = c.execute("SELECT l.org_id FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.id=?", (int(tid),)).fetchone()
    return r[0] if r else None


def oc_list_org(c, lid):
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        r = c.execute("SELECT org_id FROM lists WHERE id=?", (int(lid),)).fetchone()
    return r[0] if r else None


def oc_send_file(c, path, **kw):
    """flask.send_file for a stored file: a plain file is streamed as before, a sealed one is decrypted in memory.
    kw = the usual send_file arguments (mimetype, as_attachment, download_name, ...)."""
    from flask import send_file
    if not oc_is_sealed_file(path):
        return send_file(path, **kw)
    kw.setdefault("last_modified", os.path.getmtime(path))
    kw.pop("conditional", None)
    return send_file(io.BytesIO(oc_read_file(c, path)), conditional=True, etag=False, **kw)


# ---- server-side caches (the text cache of attachments): sealed with a key derived from the master key ----------------
_CACHE_KEY = []


def _cache_key():
    if not _CACHE_KEY:
        _CACHE_KEY.append(HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"kalmido-cache-v1").derive(SECRET_KEY))
    return _CACHE_KEY[0]


def oc_cache_seal(text):
    """A cache entry (text) sealed when the server has a master key (else unchanged): extracted texts of files are not
    left in plain on disk."""
    if not SECRET_KEY:
        return text
    n = os.urandom(12)
    return PREFIX + _b64u(n + AESGCM(_cache_key()).encrypt(n, text.encode(), b"kalmido-cache"))


def oc_cache_open(text):
    """The plain cache entry; None when it cannot be opened (another master key: a cache miss)."""
    if not isinstance(text, str) or not text.startswith(PREFIX):
        return text
    if not SECRET_KEY:
        return None
    try:
        raw = _b64u_dec(text[len(PREFIX):])
        return AESGCM(_cache_key()).decrypt(raw[:12], raw[12:], b"kalmido-cache").decode()
    except (InvalidTag, ValueError, UnicodeDecodeError):
        return None


# ---- recovery key -----------------------------------------------------------------------------------------------------
def oc_recovery_key(c, org_id):
    """The org key as grouped base32 (13 groups of 4); '' when the encryption is off. The caller checks the rights and
    logs the showing (never the value)."""
    key = oc_key(c, org_id)
    if key is None:
        return ""
    s = base64.b32encode(key).decode().rstrip("=")
    return "-".join(s[i:i + 4] for i in range(0, len(s), 4))


def oc_parse_recovery(text):
    """The 32 key bytes from a recovery key (spaces / dashes / case do not matter). ValueError when it is not one."""
    s = re.sub(r"[\s\-]", "", str(text or "")).upper()
    if not re.fullmatch(r"[A-Z2-7]{52}", s):
        raise ValueError("not a recovery key")
    k = base64.b32decode(s + "=" * (-len(s) % 8))
    if len(k) != 32:
        raise ValueError("not a recovery key")
    return k


def oc_rewrap(c, org_id, key, master=None):
    """Store key (the recovery key's bytes) as the organisation's key, wrapped with the current (or the given) master key.
    A key row that opens with the current master key must hold the same key (no silent replacement)."""
    kek = _kek(master)
    if kek is None:
        raise OrgCryptError("no server key (KALMIDO_SECRET_KEY) set")
    r = _row(c, org_id)
    if r is not None and hmac.compare_digest(str(r["kek_check"]), _kek_check(kek, org_id)):
        if not hmac.compare_digest(_unwrap(kek, org_id, r["wrapped"]), key):
            raise OrgCryptError(f"org {int(org_id)}: the recovery key does not belong to this organisation")
        return False
    # the replaced wrapped key + its check stay in wrapped_prev / kek_check_prev: should the old server key turn up again,
    # the old key can still be unwrapped (the caller tested the new key on the organisation's data first, orgcrypt_cli)
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        c.execute("INSERT INTO org_keys(org_id, wrapped, kek_check, created_at) VALUES(?,?,?,?) ON CONFLICT(org_id) DO UPDATE "
                  "SET wrapped_prev=org_keys.wrapped, kek_check_prev=org_keys.kek_check, wrapped=excluded.wrapped, kek_check=excluded.kek_check",
                  (int(org_id), _wrap(kek, org_id, key), _kek_check(kek, org_id), _now()))
    oc_forget(org_id)
    return True


def oc_drop_key(c, org_id):
    """Delete the organisation's key (Delete organisation): its encrypted values and sealed files become unreadable."""
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        c.execute("DELETE FROM org_keys WHERE org_id=?", (int(org_id),))
    oc_forget(org_id)


def oc_status(c, org_id):
    """{"enabled", "active", "has_key", "key_ok", "migrated_at", "recovery_shown_at"} for the settings (no secrets)."""
    out = {"enabled": oc_enabled(), "active": oc_active(c), "has_key": False, "key_ok": None,
           "migrated_at": None, "recovery_shown_at": None}
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        r = c.execute("SELECT kek_check, migrated_at, recovery_shown_at FROM org_keys WHERE org_id=?", (int(org_id),)).fetchone()
    if r:
        out.update(has_key=True, migrated_at=r["migrated_at"], recovery_shown_at=r["recovery_shown_at"])
        if SECRET_KEY:
            out["key_ok"] = hmac.compare_digest(str(r["kek_check"]), _kek_check(_kek(), org_id))
    return out



# ---- routes: Settings > Organisation > Encryption (organisation admins), the instance switch (instance admin) ----------
def _org_admin(c, oid):
    from flask import g
    from ..accounts.orgs import _need_org_admin
    from ..core.access import Denied
    if g.user is None:
        raise Denied(401)
    _need_org_admin(c, oid)


@app.get("/api/orgs/<int:oid>/encryption")
def oc_route_status(oid):
    """Organisation admins: {enabled (server key set), active (new data is encrypted), has_key, key_ok, migrated_at,
    recovery_shown_at}. No key material."""
    from ..core.db import db
    from flask import g
    c = db()
    _org_admin(c, oid)
    u = c.execute("SELECT password_hash FROM users WHERE id=?", (g.user["id"],)).fetchone()
    return jsonify(**oc_status(c, oid), password=bool(u and u["password_hash"]),  # password: showing the key asks for it
                   scope=pm_crypt_scope())  # 2.46.1 (#1641)


@app.post("/api/orgs/<int:oid>/encryption/recovery")
def oc_route_recovery(oid):
    """Organisation admins, {password}: the organisation's recovery key (= its key, grouped base32). The current password is
    checked like other security steps (accounts without a password -- single sign-on / proxy -- rely on their session);
    the showing is noted in the office log and in org_keys.recovery_shown_at, never the value. 409 without a server key."""
    from flask import g
    from ..core.db import body, db, err, iso, now_utc
    from ..accounts.login import _reauth
    c, b = db(), body()
    _org_admin(c, oid)
    if not SECRET_KEY:
        return err(tr("Organisation encryption is off: the server has no KALMIDO_SECRET_KEY."), 409)
    u = c.execute("SELECT * FROM users WHERE id=?", (g.user["id"],)).fetchone()
    if u["password_hash"]:
        e = _reauth(u, b)
        if e is not None:
            return e
    rk = oc_recovery_key(c, oid)
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        c.execute("UPDATE org_keys SET recovery_shown_at=? WHERE org_id=?", (iso(now_utc()), oid))
    from ..office.ledger import ofx_log
    ofx_log(c, oid, "recovery_key", target="org", detail={"shown": 1})
    c.commit()
    print("orgcrypt: recovery key of organisation", oid, "shown to user", g.user["id"], flush=True)
    r = jsonify(recovery_key=rk)
    r.headers["Cache-Control"] = "no-store"
    return r


@app.get("/api/admin/orgcrypt")
def oc_route_admin_get():
    from ..core.db import db
    from ..accounts.users import need_admin
    need_admin()
    c = db()
    return jsonify(enabled=oc_enabled(), org_encrypt=_setting(c) != "0", scope=pm_crypt_scope())  # 2.46.1 (#1641): scope


@app.put("/api/admin/orgcrypt")
def oc_route_admin_put():
    """Instance admin, {org_encrypt: bool}: encrypt organisation data at rest (on: the start-up pass runs again at once
    for what was stored plain meanwhile; off: nothing new is encrypted, encrypted data stays readable)."""
    from flask import g
    from ..core.db import body, bump, db, gset
    from ..accounts.users import need_admin
    need_admin()
    c, b = db(), body()
    on = b.get("org_encrypt") in (1, True, "1", "true")
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        gset(c, "org_encrypt", "1" if on else "0")
    bump(c)
    c.commit()
    print("orgcrypt: org_encrypt set to", int(on), "by user", g.user["id"], flush=True)
    if on and SECRET_KEY:
        from ..admin.orgcrypt_cli import oc_migrate_start
        oc_migrate_start()
    return jsonify(enabled=oc_enabled(), org_encrypt=on)


def _setting(c):
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        r = c.execute("SELECT value FROM settings WHERE key='org_encrypt'").fetchone()
    return r[0] if r else "1"
