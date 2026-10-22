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
repeated at any point. Deleting an organisation deletes its key row: what stays in
the database or on disk of that organisation can no longer be read (older backups still hold the wrapped key).
Never log, print or return a key, a recovery key or a decrypted protected value outside the routes that show it anyway.

2.64.0 (#1864): account keys -- the files of a person's private space (lists without an organisation, the own file tree,
the chats with agents) are sealed the same way with a key per person: 32 random bytes, wrapped with the same KEK (associated
data binds the person), table user_keys (row deleted with the account: crypto-deletion on top of deleting the files).
Everywhere in this module a "space" id names the key: > 0 = an organisation, < 0 = the account -id (0 = none). A sealed
file's header carries the space id, so a file stays readable wherever it lies; the start-up pass (admin/orgcrypt_cli.py
files_settle) reseals a file that lies in another space now. Switch for private files only: the instance setting
private_encrypt (default "1"; orgcrypt_cli decrypt-private / encrypt-private), the org_encrypt switch covers both.

2.138.0 C (#1972): the recovery key is no longer the org key itself. Per organisation a random recovery secret R (32
bytes) wraps the org key: org_keys.recovery_wrapped = "r1." + AES-256-GCM(HKDF(R, info "kalmido-orgkey-recovery-v1"),
org key, AAD binds the org id) -- independent of the master key, so R plus a database copy restore the org key under a
new master key (orgcrypt_cli rewrap). R itself is kept wrapped with the KEK (recovery_secret) so that an admin can show it
again after a step-up (password + second factor, or a fresh sign-in); "new recovery key" replaces R (the old one stops
working). Shown as "R2-" + 13 groups of base32; rck_parse also takes the earlier format (the raw org key, 13 groups)
until the organisation's key is rotated. orgcrypt_cli rotate: a new org key K2 for an organisation; while the run
re-encrypts its data the earlier key stays in wrapped_rot and reading falls back to it (_ROT), at the end it is dropped
and a new R is made. Organisation exports carry recovery_wrapped in their header (admin/orgexport.py ox_header).
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

from ..core.config import app, SECRET_KEY, COOKIE
from ..core.i18n import N_, tr
from ..core.pg import system_ctx, write_lock
from ..core.db import body, bump, connect, db, err, gset, iso, iso_ms, now_utc  # 2.149.0 G (#2517): pulled up from functions

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
    # 2.119.0 A (#2288): entertainment receipts -- place, occasion, people, amounts, the log's names and reasons
    "office_meals": ("place_name", "place_address", "occasion", "host", "guests", "amounts", "tip", "note", "approved_name"),
    "office_meal_choices": ("name", "extra"), "office_meal_log": ("user_name", "reason"),
    "office_fixed_costs": ("amount",),  # 2.47.3 (#1652): fixed costs of the cash flow
    "office_cf_start": ("amount",), "office_cf_adjust": ("amount", "note"), "office_cf_actual": ("amount",),  # 2.123.0 D (#2341)
    "office_bank_tx": ("amount", "counterpart", "purpose", "iban"),  # 2.90.0 B (#1921): imported bank bookings
    "office_bank_balances": ("amount", "account"),  # 2.124.0 D (#2342): balances of the imported statements
    "office_doc_templates": ("body",), "office_gen_docs": ("body",),  # 2.93.0 A (#1927): document templates, documents
    "office_vehicles": ("plate",), "office_drives": ("start_place", "dest", "purpose", "correct_note"),  # 2.93.0 B (#1928): the logbook; 2.152.0 C (#2169): + reason
    "office_drive_log": ("prev",),  # 2.93.0 B (#1928): the change log of the logbook
    "office_cash_entries": ("text",), "office_cash_log": ("prev",),  # 2.121.0 B (#2095): the cash book
    "office_procdocs": ("data",),  # 2.148.0 C (#2472): the procedure documentation (own texts + prefilled snapshot)
    "office_suppliers": ("name", "street", "zip", "city", "vat_id", "iban"),  # 2.148.0 D (#2458): creditors of the DATEV import
    "office_letters": ("rcpt_name", "rcpt_address", "rcpt_email", "subject", "body", "ref_line"),  # 2.153.0 (#2028): letters
    "office_letter_blocks": ("body",), "office_letter_profiles": ("image",),  # 2.153.0 (#2030, #2028): text blocks, signature picture
    "office_deals": ("value", "contact", "note", "lost_reason",
                     "next_step", "email", "phone", "company"),  # 2.50.0 (#1196): the sales pipeline; 2.94.0 A (#1930): leads
    "time_sheets": ("note",),  # 2.125.0 R (#2119): the note of a timesheet decision
    "hub_absences": ("kind", "note", "decision_note"),  # 2.50.0 (#1195): the kind of an absence (sick leave = health data) and its note; 2.125.0 A (#2117): + the note of a decision
    # 2.72.0 (#1333): the household budget -- per row with the key of its list's space (column sid, life/budget.py bud_enc;
    # the passes of admin/orgcrypt_cli.py call life/budget.py bud_settle, not fields_pass: these tables have no org_id)
    "budget_entries": ("amount", "title", "note", "counterpart"),
    "budget_recurring": ("title", "amount"),
    "budget_cats": ("lim",),
    "hub_mails": ("from_addr", "from_name", "to_addrs", "subject", "body"),  # 2.84.0 A (#1198): filed e-mails
    "office_agreements": ("cost", "number", "note"),  # 2.92.0 A (#1925): business contracts and insurances
    "office_equipment": ("purchase_net", "new_value", "current_value", "serial_no"),  # 2.92.0 B (#1931): the value of equipment
    # 2.123.0 A (#2105, #2102): the text of knowledge pages in spaces without the lock and of their history; a private page
    # with the account key (space -owner), sealed / opened by wiki/wkhist.py (the passes: wkh_settle, not fields_pass)
    "wiki_pages": ("body",), "wiki_versions": ("body",),
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
                 "files": N_("Files of organisations"), "private_files": N_("Files in the private space"),  # 2.64.0 (#1864)
                 "tokens": N_("Stored access tokens (Git, client secret of the single sign-on)"),
                 # 2.47.0 (#1649, #1215, #1216): roles' purchase prices, purchases of accepted quotations, parts and shoot sheets
                 "office_roles": N_("Purchase prices and margins"), "office_purchases": N_("Purchase prices and margins"),
                 "office_doc_parts": N_("Purchase prices and margins"), ("office_doc_parts", "totals"): N_("Purchase prices and margins"),
                 # 2.47.3 (#1022, #1652): travel expenses (participants, amounts) and fixed costs
                 "office_trips": N_("Travel expenses"), "office_trip_items": N_("Travel expenses"), "office_fixed_costs": N_("Fixed costs"),
                 "office_cf_start": N_("Cash flow"), "office_cf_adjust": N_("Cash flow"), "office_cf_actual": N_("Cash flow"),  # 2.123.0 D (#2341)
                 "office_meals": N_("Entertainment receipts"), "office_meal_choices": N_("Entertainment receipts"),  # 2.119.0 A (#2288)
                 "office_meal_log": N_("Entertainment receipts"),
                 "office_deals": N_("Sales pipeline"),  # 2.50.0 (#1196)
                 "office_bank_tx": N_("Bank statements"),  # 2.90.0 B (#1921)
                 "office_bank_balances": N_("Bank statements"),  # 2.124.0 D (#2342)
                 "office_doc_templates": N_("Document templates and documents"), "office_gen_docs": N_("Document templates and documents"),  # 2.93.0 A (#1927)
                 "office_vehicles": N_("Logbook"), "office_drives": N_("Logbook"), "office_drive_log": N_("Logbook"),  # 2.93.0 B (#1928)
                 "office_cash_entries": N_("Cash book"), "office_cash_log": N_("Cash book"),  # 2.121.0 B (#2095)
                 "office_procdocs": N_("Procedure documentation"),  # 2.148.0 C (#2472)
                 "office_suppliers": N_("Suppliers of the DATEV import"),  # 2.148.0 D (#2458)
                 "office_letters": N_("Letters"), "office_letter_blocks": N_("Letters"), "office_letter_profiles": N_("Letters"),  # 2.153.0 (#2028)
                 "hub_absences": N_("Kind and note of absences"),  # 2.50.0 (#1195)
                 "time_sheets": N_("Notes on timesheet decisions"),  # 2.125.0 R (#2119)
                 # 2.72.0 (#1333): amounts, texts and limits of the household budget, its receipts
                 "budget_entries": N_("Household budget"), "budget_recurring": N_("Household budget"), "budget_cats": N_("Household budget"),
                 "hub_mails": N_("E-mails filed with clients and projects"),  # 2.84.0 A (#1198)
                 "office_agreements": N_("Business contracts and insurances"),  # 2.92.0 A (#1925)
                 "office_equipment": N_("Purchase prices and margins"),  # 2.92.0 B (#1931): purchase price, new and current value
                 # 2.123.0 A (#2105, #2102): texts of knowledge pages (spaces without the lock) and their history
                 "wiki_pages": N_("Texts of knowledge pages and their history"), "wiki_versions": N_("Texts of knowledge pages and their history")}
PM_CRYPT_PLAIN = (N_("Tasks"), N_("Notes"), N_("Descriptions"), N_("Comments"), N_("Contacts"), N_("Chats"))
# 2.64.1 (#1817): what the browser encrypts in lists with a lock (collab/liste2e.py LE2E_FIELDS); the plain list holds them apart
PM_CRYPT_BROWSER = (N_("Titles, descriptions, subtasks, comments, notes, section names, free-text fields, links and code snippets of projects with a lock"),)
PM_CRYPT_BROWSER += (N_("Names and texts of knowledge pages in spaces with a lock"),)  # 2.64.3 A (#1817): the lock per knowledge space
PM_CRYPT_PLAIN_NOTE = N_("Tasks, descriptions, notes and comments: except in projects with a lock")


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
_ROT = {}  # 2.138.0 C (#1972): org id -> the earlier org key while orgcrypt_cli rotate runs (reading falls back to it)


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
    if int(org_id) < 0:  # 2.64.0 (#1864): an account key
        return hmac.new(kek, b"kalmido-userkey-check-v1|%d" % -int(org_id), hashlib.sha256).hexdigest()[:32]
    return hmac.new(kek, b"kalmido-orgkey-check-v1|%d" % int(org_id), hashlib.sha256).hexdigest()[:32]


def _wrap(kek, org_id, key):
    n = os.urandom(12)
    return "v1." + _b64u(n + AESGCM(kek).encrypt(n, key, _wrap_ad(org_id)))


def _unwrap(kek, org_id, wrapped):
    if not wrapped.startswith("v1."):
        raise OrgCryptError("unknown key format")
    try:
        raw = _b64u_dec(wrapped[3:])  # 2.126.0 A (#1979 L2): a damaged row is a clear key error too
        return AESGCM(kek).decrypt(raw[:12], raw[12:], _wrap_ad(org_id))
    except (InvalidTag, ValueError):
        raise OrgCryptError(f"{_label(org_id)}: the key cannot be unwrapped") from None


def _label(sid):
    """'org N' / 'account N' for log lines (never a key)."""
    return f"account {-int(sid)}" if int(sid) < 0 else f"org {int(sid)}"


def _wrap_ad(sid):
    # 2.64.0 (#1864): an account key is bound to its person, an org key to its organisation (the formats never mix)
    return b"kalmido-userkey|%d" % -int(sid) if int(sid) < 0 else b"kalmido-orgkey|%d" % int(sid)


def oc_user_space(uid):
    """2.64.0 (#1864): the space id of a person's private space (None without a person)."""
    return -int(uid) if uid else None


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


def oc_private_on(c):
    """2.64.0 (#1864): the instance setting private_encrypt (default "1"): files of private spaces are sealed."""
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        r = c.execute("SELECT value FROM settings WHERE key='private_encrypt'").fetchone()
    return (r[0] if r else "1") != "0"


def oc_active_for(c, sid):
    """True when NEW files of space sid are sealed: oc_active, and for a private space (sid < 0) also private_encrypt."""
    if not sid or not oc_active(c):
        return False
    return int(sid) > 0 or oc_private_on(c)


def _row(c, org_id):
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        if int(org_id) < 0:  # 2.64.0 (#1864): an account key
            return c.execute("SELECT wrapped, kek_check FROM user_keys WHERE user_id=?", (-int(org_id),)).fetchone()
        return c.execute("SELECT wrapped, kek_check, wrapped_rot, kek_check_rot FROM org_keys WHERE org_id=?", (int(org_id),)).fetchone()


def _rck_note(org_id, r, kek=None):
    """2.138.0 C (#1972): remember the earlier key of an organisation whose rotation runs (row column wrapped_rot)."""
    if int(org_id) <= 0:
        return
    w = r["wrapped_rot"]
    if not w:
        with _LOCK:
            _ROT.pop(int(org_id), None)
        return
    kek = kek or _kek()
    if not hmac.compare_digest(str(r["kek_check_rot"] or ""), _kek_check(kek, org_id)):
        return
    ck = (int(org_id), w)
    with _LOCK:
        k = _CACHE.get(ck)
    if k is None:
        k = _unwrap(kek, org_id, w)
        with _LOCK:
            _CACHE[ck] = k
    with _LOCK:
        _ROT[int(org_id)] = k


def _rot_key(org_id):
    try:
        with _LOCK:
            return _ROT.get(int(org_id)) if org_id else None
    except (TypeError, ValueError):
        return None


def _open_row(org_id, r, kek=None):
    kek = kek or _kek()
    if not hmac.compare_digest(str(r["kek_check"]), _kek_check(kek, org_id)):
        raise OrgCryptError(f"{_label(org_id)}: the server key (KALMIDO_SECRET_KEY) is not the one this key was made with")
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
    if int(org_id) < 0:  # 2.64.0 (#1864): an account key (the row holds the person's id)
        vals = (-int(org_id), _wrap(kek, org_id, key), _kek_check(kek, org_id), _now())
        sql = ("INSERT INTO user_keys(user_id, wrapped, kek_check, created_at) VALUES(?,?,?,?) "
               "ON CONFLICT(user_id) DO NOTHING")
    else:
        vals = (int(org_id), _wrap(kek, org_id, key), _kek_check(kek, org_id), _now())
        sql = ("INSERT INTO org_keys(org_id, wrapped, kek_check, created_at) VALUES(?,?,?,?) "
               "ON CONFLICT(org_id) DO NOTHING")
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


from ..core.db import now_iso as _now  # noqa: E402  2.149.0 G (#2517): was an own copy


def oc_key(c, org_id, create=True):
    """The organisation's key (32 bytes), made on first use; None without a master key or without an organisation
    (create=False: None while it has none). OrgCryptError: the master key does not match. 2.64.0 (#1864): org_id < 0 =
    the account key of person -org_id (same rules)."""
    if not SECRET_KEY or not org_id:
        return None
    r = _row(c, org_id)
    if r is None:
        if not create:
            return None
        with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
            if int(org_id) < 0:
                if not c.execute("SELECT 1 FROM users WHERE id=?", (-int(org_id),)).fetchone():
                    return None
            elif not c.execute("SELECT 1 FROM orgs WHERE id=?", (int(org_id),)).fetchone():
                return None
        r = _create(c, org_id)
        if r is None:
            return None
    k = _open_row(org_id, r)
    _rck_note(org_id, r)  # 2.138.0 C (#1972)
    return k


def oc_forget(org_id=None):
    """Drop cached keys (one organisation or all): after deleting / rewrapping a key."""
    with _LOCK:
        for k in [k for k in _CACHE if org_id is None or k[0] == int(org_id)]:
            _CACHE.pop(k, None)
        for k in [k for k in _ROT if org_id is None or k == int(org_id)]:  # 2.138.0 C (#1972)
            _ROT.pop(k, None)


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
        try:
            return AESGCM(key).decrypt(raw[:12], raw[12:], _aad(org_id, ctx)).decode()
        except InvalidTag:
            old = _rot_key(org_id)  # 2.138.0 C (#1972): not re-encrypted yet by a running rotation
            if old is None or old == key:
                raise
            return AESGCM(old).decrypt(raw[:12], raw[12:], _aad(org_id, ctx)).decode()
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
               '"cost_day"', '"cost_hour"', '"markup_pct"',  # 2.47.0 (#1649): the roles' purchase prices / markup
               '"purchase_net"', '"new_value"', '"current_value"', '"serial_no"',  # 2.92.0 review (#1931): equipment value
               '"sig_proto"')  # 2.148.1 C (#2493): the decision of an approval link (the signer's name)


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
def oc_seal(c, org_id, data, ctx=FILE_CTX, fresh=False):
    """MAGIC + org id + nonce + ciphertext; unchanged when off, without an organisation or already sealed.
    2.64.0 (#1864): org_id = a space id (< 0: the person's account key). fresh = bytes from outside (an upload, a mail,
    an import): when they already start with MAGIC they get an outer layer with this space's key (also while the
    encryption is switched off); the download hands back exactly the uploaded bytes."""
    if data[:len(MAGIC)] == MAGIC:
        if fresh and org_id and SECRET_KEY:
            key = oc_key(c, org_id)
            return oc_seal_raw(key, org_id, data, ctx) if key is not None else data
        if fresh:
            _fresh_refused()
        return data
    if not org_id or not oc_active_for(c, org_id):
        return data
    return oc_seal_k(oc_key(c, org_id), org_id, data, ctx)


def _fresh_refused():
    """2.126.0 A (#1979 L5): bytes from outside that look like a sealed file can only be stored with an outer layer, which
    needs the server key and a space; without them such a file is refused (it could never be opened again)."""
    from .access import Denied
    raise Denied(400, tr("This file cannot be stored on this server (it starts like an encrypted Kalmido file)"))


def oc_seal_k(key, org_id, data, ctx=FILE_CTX):
    if key is None or data[:len(MAGIC)] == MAGIC:
        return data
    return oc_seal_raw(key, org_id, data, ctx)


def oc_seal_raw(key, org_id, data, ctx=FILE_CTX):
    """Seal data with key whatever it holds (also content that itself starts with MAGIC: an outer layer)."""
    head = MAGIC + struct.pack(">q", int(org_id))
    n = os.urandom(12)
    return head + n + AESGCM(key).encrypt(n, bytes(data), head + bytes(ctx))


def oc_file_org(data):
    """The organisation a sealed file belongs to (from its header), None for a plain file. 2.64.0 (#1864): < 0 = the
    account key of that person (0 = a private document preview, docs/store.py thumb_seal)."""
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
        raise OrgCryptError(f"{_label(oid)}: no key for a sealed file")
    return oc_open_k(key, data, ctx)


def oc_open_k(key, data, ctx=FILE_CTX):
    if data[:len(MAGIC)] != MAGIC:
        return data
    head = data[:len(MAGIC) + 8]
    try:
        try:
            return AESGCM(key).decrypt(data[len(head):_HEAD], data[_HEAD:], head + bytes(ctx))
        except InvalidTag:
            old = _rot_key(oc_file_org(data))  # 2.138.0 C (#1972): not resealed yet by a running rotation
            if old is None or old == key:
                raise
            return AESGCM(old).decrypt(data[len(head):_HEAD], data[_HEAD:], head + bytes(ctx))
    except InvalidTag:
        raise OrgCryptError(f"{_label(oc_file_org(data))}: a sealed file cannot be decrypted") from None


def oc_is_sealed_file(path):
    try:
        with open(path, "rb") as f:
            return f.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


def oc_read_file(c, path, ctx=FILE_CTX):
    with open(path, "rb") as f:
        return oc_open(c, f.read(), ctx)


def _write_atomic(path, data, mode=None, check=None):
    tmp = f"{path}.oc-{os.getpid()}-{threading.get_ident()}.tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        if check is not None and not check():  # 2.138.0 C (#1972): the file changed meanwhile: leave the newer one
            return False
        os.replace(tmp, path)
        return True
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def oc_write_file(c, org_id, path, data, ctx=FILE_CTX, fresh=False):
    """Write data (sealed when active and the file belongs to an organisation), atomically (tmp + os.replace).
    fresh: bytes from outside (oc_seal)."""
    _write_atomic(path, oc_seal(c, org_id, data, ctx, fresh=fresh))


def oc_reseal_file(path, new_data, check=None):
    """Replace a file's bytes atomically, keeping its permissions (the migration and the way back). 2.138.0 C (#1972):
    check() is asked right before the replace (False: the file stays, returns False)."""
    try:
        mode = os.stat(path).st_mode & 0o7777
    except OSError:
        mode = None
    return _write_atomic(path, new_data, mode, check)


OVERHEAD = _HEAD + 16  # bytes a sealed file is larger than its plain content


def oc_plain_size(path):
    """The size of a stored file's plain content (a sealed file without its header and tag)."""
    n = os.path.getsize(path)
    return n - OVERHEAD if n >= OVERHEAD and oc_is_sealed_file(path) else n


def oc_seal_path(c, org_id, path, ctx=FILE_CTX, fresh=False):
    """Seal a file that was just written in plain (upload, copy) when it belongs to an organisation and the encryption is
    active; a sealed file stays as it is. True when it was sealed. 2.64.0 (#1864): org_id = a space id (oc_task_space);
    fresh = the bytes came from outside: one that already looks sealed gets an outer layer (oc_seal)."""
    if fresh and oc_is_sealed_file(path) and not (org_id and SECRET_KEY):
        try:  # 2.126.0 A (#1979 L5)
            os.remove(path)
        except OSError:
            pass
        _fresh_refused()
    if fresh and org_id and SECRET_KEY and oc_is_sealed_file(path):
        with open(path, "rb") as f:
            data = f.read()
        sealed = oc_seal(c, org_id, data, ctx, fresh=True)
        if sealed is not data:
            oc_reseal_file(path, sealed)
            return True
        return False
    if not org_id or not oc_active_for(c, org_id) or oc_is_sealed_file(path):
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


def _space(r):
    return (int(r["org_id"]) if r["org_id"] else oc_user_space(r["owner_id"])) if r else None


def oc_task_space(c, tid):
    """2.64.0 (#1864): the space whose key seals a task's files: its list's organisation, else the list owner's account
    (a private list shared with others: the owner's key; the server opens the file for everyone who may see it)."""
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        return _space(c.execute("SELECT l.org_id, l.owner_id FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.id=?",
                                (int(tid),)).fetchone())


def oc_list_space(c, lid):
    """2.64.0 (#1864): the space of a list (organisation, else the owner's account)."""
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        return _space(c.execute("SELECT org_id, owner_id FROM lists WHERE id=?", (int(lid),)).fetchone())


def oc_copy_file(c, src, dst, sid):
    """2.64.0 (#1864): copy a stored file into space sid (opened with the key in its header, sealed for the target)."""
    _write_atomic(dst, oc_seal(c, sid, oc_read_file(c, src), fresh=True))  # the content may itself look sealed


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
# 2.138.0 C (#1972): a recovery secret R per organisation wraps the org key (org_keys.recovery_wrapped, independent of the
# master key); R itself is kept wrapped with the KEK (recovery_secret) so that it can be shown again. The earlier format
# (the raw org key) is still taken by rck_parse / rewrap until the organisation's key is rotated.
RCK_TAG = "R2"


def _rck_kek(secret):
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"kalmido-orgkey-recovery-v1").derive(secret)


def _rck_ad(org_id):
    return b"kalmido-orgkey-recovery|%d" % int(org_id)


def _rck_sad(org_id):
    return b"kalmido-orgkey-rsecret|%d" % int(org_id)


def _rck_seal(key, data, ad):
    n = os.urandom(12)
    return "r1." + _b64u(n + AESGCM(key).encrypt(n, data, ad))


def _rck_open(key, wrapped, ad, what):
    try:
        if not str(wrapped or "").startswith("r1."):
            raise ValueError
        raw = _b64u_dec(wrapped[3:])
        return AESGCM(key).decrypt(raw[:12], raw[12:], ad)
    except (InvalidTag, ValueError):
        raise OrgCryptError(what) from None


def rck_wrap(secret, org_id, key):
    """recovery_wrapped: the org key wrapped with a key derived from the recovery secret, bound to the organisation."""
    return _rck_seal(_rck_kek(secret), key, _rck_ad(org_id))


def rck_unwrap(secret, org_id, wrapped):
    """The org key from recovery_wrapped; OrgCryptError for another recovery key / another organisation."""
    return _rck_open(_rck_kek(secret), wrapped, _rck_ad(org_id), f"org {int(org_id)}: the recovery key does not belong to this organisation")


def rck_format(secret):
    """"R2-" + 13 groups of 4 (base32): told apart from the earlier format (13 groups, the raw org key)."""
    s = base64.b32encode(secret).decode().rstrip("=")
    return RCK_TAG + "-" + "-".join(s[i:i + 4] for i in range(0, len(s), 4))


def rck_parse(text):
    """("secret", R) for a recovery key "R2-...", ("key", org key) for the earlier format; spaces / dashes / case do not
    matter. ValueError when it is neither."""
    s = re.sub(r"[\s\-]", "", str(text or "")).upper()
    kind = "key"
    if len(s) == 54 and s.startswith(RCK_TAG):
        kind, s = "secret", s[len(RCK_TAG):]
    if not re.fullmatch(r"[A-Z2-7]{52}", s):
        raise ValueError("not a recovery key")
    k = base64.b32decode(s + "=" * (-len(s) % 8))
    if len(k) != 32:
        raise ValueError("not a recovery key")
    return kind, k


def oc_parse_recovery(text):
    """The 32 key bytes of a recovery key of the earlier format (the raw org key). ValueError for anything else."""
    kind, k = rck_parse(text)
    if kind != "key":
        raise ValueError("not a recovery key")
    return k


def rck_resolve(parsed, org_id, wrapped):
    """The org key a parsed recovery key (rck_parse) stands for: the earlier format is the key itself, a recovery secret
    opens wrapped (recovery_wrapped of the database or of an export header). OrgCryptError when it does not fit."""
    kind, b = parsed
    if kind == "key":
        return b
    if not wrapped:
        raise OrgCryptError(f"org {int(org_id)}: the recovery key does not belong to this organisation")
    return rck_unwrap(b, org_id, wrapped)


def rck_row(c, org_id):
    """The recovery / rotation columns of the organisation's key row (None without one). No key material leaves."""
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        return c.execute("SELECT recovery_wrapped, recovery_secret, recovery_shown_at, wrapped_rot, rot_started_at, rotated_at "
                         "FROM org_keys WHERE org_id=?", (int(org_id),)).fetchone()


def _rck_store(c, org_id, secret, key, kek):
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        c.execute("UPDATE org_keys SET recovery_wrapped=?, recovery_secret=? WHERE org_id=? AND wrapped_rot IS NULL",
                  (rck_wrap(secret, org_id, key), _rck_seal(kek, secret, _rck_sad(org_id)), int(org_id)))


class RckStale(OrgCryptError):
    """2.138.0 C (#1972): recovery_wrapped exists, but its recovery secret cannot be shown (no copy under this server key,
    or it does not fit the org key): only a deliberate new one (new=True) replaces it."""


def rck_secret(c, org_id, new=False):
    """-> (R, made): the organisation's recovery secret R (32 bytes), the stored one or a new one (new=True or none yet)
    -- a new R replaces recovery_wrapped, the earlier R stops working (the caller commits). RckStale when one exists but
    cannot be shown (stored under an earlier server key / for an earlier org key): never replaced silently. (None, False)
    without a server key / an org key and while a rotation runs (its end makes one). The caller checks the rights and
    notes the showing (never the value)."""
    key = oc_key(c, org_id)
    if key is None:
        return None, False
    r = rck_row(c, org_id)
    if r is None or r["wrapped_rot"]:
        return None, False
    kek = _kek()
    if not new and r["recovery_wrapped"]:
        try:
            if not r["recovery_secret"]:
                raise OrgCryptError("recovery secret")
            sec = _rck_open(kek, r["recovery_secret"], _rck_sad(org_id), "recovery secret")
            if not hmac.compare_digest(rck_unwrap(sec, org_id, r["recovery_wrapped"]), key):
                raise OrgCryptError("recovery secret")
        except OrgCryptError:
            raise RckStale(f"org {int(org_id)}: the recovery key cannot be shown - make a new one") from None
        return sec, False
    sec = os.urandom(32)
    _rck_store(c, org_id, sec, key, kek)
    return sec, True


def rck_wrapped(c, org_id):
    """recovery_wrapped for an export header (made when there is none yet; one that cannot be shown is kept as it is: it
    still opens with the R it was made with); None without one (no server key, rotation)."""
    try:
        sec, made = rck_secret(c, org_id)
        if sec is None:
            return None
        if made:  # 2.138.0 C (#1972, review F4): a key made for the export is noted like one made in the settings
            from ..office.ledger import ofx_log
            ofx_log(c, org_id, "recovery_key", target="org", detail={"new": 1, "export": 1})
    except RckStale:
        pass
    r = rck_row(c, org_id)
    return r["recovery_wrapped"] if r else None


def rck_drop_secret(c, org_id):
    """2.138.0 C (#1972): after rewrap with the earlier format the stored copy of R lies under the earlier server key: it
    goes (recovery_wrapped stays valid for the R in the safe; oc_status recovery_stale until a new one is made)."""
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        c.execute("UPDATE org_keys SET recovery_secret=NULL WHERE org_id=?", (int(org_id),))


def rck_keep_secret(c, org_id, secret, master=None):
    """After rewrap with a recovery secret: store R again with the current (or the given) master key (the caller commits)."""
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        c.execute("UPDATE org_keys SET recovery_secret=? WHERE org_id=?", (_rck_seal(_kek(master), secret, _rck_sad(org_id)), int(org_id)))


def oc_rewrap(c, org_id, key, master=None):
    """Store key (the org key, from a recovery key) as the organisation's key, wrapped with the current (or the given) master key.
    A key row that opens with the current master key must hold the same key (no silent replacement)."""
    kek = _kek(master)
    if kek is None:
        raise OrgCryptError("no server key (KALMIDO_SECRET_KEY) set")
    r = _row(c, org_id)
    if r is not None and r["wrapped_rot"]:  # 2.138.0 C (#1972): first finish the rotation (orgcrypt_cli rotate)
        raise OrgCryptError(f"org {int(org_id)}: a key rotation is not finished - run rotate again first")
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


# ---- 2.138.0 C (#1972): rotation of an organisation's key (admin/orgcrypt_cli.py rotate) ----------------------------------
def rck_rot_begin(c, org_id):
    """Start or continue the rotation: -> (earlier key, new key, started). From the start on the row holds the new key in
    wrapped (new data is sealed with it) and the earlier one in wrapped_rot (reading falls back to it, _ROT)."""
    kek = _kek()
    if kek is None:
        raise OrgCryptError("no server key (KALMIDO_SECRET_KEY) set")
    r = _row(c, org_id)
    if r is None:
        raise OrgCryptError(f"org {int(org_id)}: no key")
    if r["wrapped_rot"]:
        if not hmac.compare_digest(str(r["kek_check_rot"] or ""), _kek_check(kek, org_id)):
            raise OrgCryptError(f"{_label(org_id)}: the server key (KALMIDO_SECRET_KEY) is not the one this key was made with")
        return _unwrap(kek, org_id, r["wrapped_rot"]), _open_row(org_id, r, kek), False
    k1, k2 = _open_row(org_id, r, kek), os.urandom(32)
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        n = c.execute("UPDATE org_keys SET wrapped_rot=wrapped, kek_check_rot=kek_check, wrapped=?, kek_check=?, rot_started_at=? "
                      "WHERE org_id=? AND wrapped=? AND wrapped_rot IS NULL",
                      (_wrap(kek, org_id, k2), _kek_check(kek, org_id), _now(), int(org_id), r["wrapped"])).rowcount
    if n != 1:
        c.rollback()
        raise OrgCryptError(f"org {int(org_id)}: the key row changed meanwhile - try again")
    c.commit()
    oc_forget(org_id)
    return k1, k2, True


def rck_rot_finish(c, org_id):
    """End of the rotation: the earlier key (and the copy of a key under an earlier server key) goes, a new recovery secret
    wraps the new key. -> the new recovery secret (committed)."""
    kek, key = _kek(), oc_key(c, org_id, create=False)
    sec = os.urandom(32)
    if key is None:
        raise OrgCryptError(f"org {int(org_id)}: no key")
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        n = c.execute("UPDATE org_keys SET wrapped_rot=NULL, kek_check_rot=NULL, wrapped_prev=NULL, kek_check_prev=NULL, rot_started_at=NULL, "
                      "rotated_at=?, recovery_wrapped=?, recovery_secret=?, recovery_shown_at=NULL WHERE org_id=? AND wrapped_rot IS NOT NULL",
                      (_now(), rck_wrap(sec, org_id, key), _rck_seal(kek, sec, _rck_sad(org_id)), int(org_id))).rowcount
    if n != 1:  # 2.138.0 C (#1972): the row changed meanwhile: no recovery key that is stored nowhere
        c.rollback()
        raise OrgCryptError(f"org {int(org_id)}: the key row changed meanwhile (no rotation to finish) - check status")
    c.commit()
    oc_forget(org_id)
    return sec


def rck_rekey(k1, k2, org_id, ctx, value):
    """A field value during a rotation: unchanged when plain or already encrypted with k2, else re-encrypted from k1 to
    k2 (same organisation and ctx). OrgCryptError when it opens with neither."""
    if not oc_is_enc(value):
        return value
    aad = _aad(org_id, ctx)
    try:
        raw = _b64u_dec(value[len(PREFIX):])
    except ValueError:
        raise OrgCryptError(f"org {org_id}: a damaged encrypted value ({ctx})") from None
    try:
        AESGCM(k2).decrypt(raw[:12], raw[12:], aad)
        return value
    except InvalidTag:
        pass
    try:
        plain = AESGCM(k1).decrypt(raw[:12], raw[12:], aad)
    except InvalidTag:
        raise OrgCryptError(f"org {org_id}: an encrypted value ({ctx}) opens with neither key") from None
    n = os.urandom(12)
    return PREFIX + _b64u(n + AESGCM(k2).encrypt(n, plain, aad))


def rck_rekey_file(k1, k2, data, ctxs=(FILE_CTX,)):
    """A sealed file's bytes during a rotation: None when already sealed with k2, else the bytes sealed with k2 (same
    header and ctx). OrgCryptError when it opens with neither key under any of ctxs."""
    head = data[:len(MAGIC) + 8]
    n0, body = data[len(head):_HEAD], data[_HEAD:]
    for ctx in ctxs:
        try:
            AESGCM(k2).decrypt(n0, body, head + bytes(ctx))
            return None
        except InvalidTag:
            pass
    for ctx in ctxs:
        try:
            plain = AESGCM(k1).decrypt(n0, body, head + bytes(ctx))
        except InvalidTag:
            continue
        n = os.urandom(12)
        return head + n + AESGCM(k2).encrypt(n, plain, head + bytes(ctx))
    raise OrgCryptError(f"{_label(oc_file_org(data))}: a sealed file opens with neither key")


def oc_rewrap_accounts(c, old_master):
    """2.64.0 (#1864): the account keys wrapped with an earlier server key (old_master, 32 bytes) are stored again with the
    current one (the replaced row stays in wrapped_prev / kek_check_prev). Account keys have no recovery key: the earlier
    server key is the way to keep private files after changing KALMIDO_SECRET_KEY. -> {"rewrapped", "current", "other"}."""
    kek, old = _kek(), _kek(old_master)
    if kek is None or old is None:
        raise OrgCryptError("no server key (KALMIDO_SECRET_KEY) set")
    out = {"rewrapped": 0, "current": 0, "other": 0}
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        rows = c.execute("SELECT user_id, wrapped, kek_check FROM user_keys ORDER BY user_id").fetchall()
    for r in rows:
        sid = -int(r["user_id"])
        if hmac.compare_digest(str(r["kek_check"]), _kek_check(kek, sid)):
            out["current"] += 1
            continue
        if not hmac.compare_digest(str(r["kek_check"]), _kek_check(old, sid)):
            out["other"] += 1
            continue
        key = _unwrap(old, sid, r["wrapped"])
        with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
            c.execute("UPDATE user_keys SET wrapped_prev=wrapped, kek_check_prev=kek_check, wrapped=?, kek_check=? WHERE user_id=? AND wrapped=?",
                      (_wrap(kek, sid, key), _kek_check(kek, sid), r["user_id"], r["wrapped"]))
        oc_forget(sid)
        out["rewrapped"] += 1
    return out


def oc_drop_key(c, org_id):
    """Delete the organisation's key (Delete organisation): its encrypted values and sealed files become unreadable.
    2.64.0 (#1864): org_id < 0 = the account key (the account's deletion also removes it by its foreign key)."""
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        if int(org_id) < 0:
            c.execute("DELETE FROM user_keys WHERE user_id=?", (-int(org_id),))
        else:
            c.execute("DELETE FROM org_keys WHERE org_id=?", (int(org_id),))
    oc_forget(org_id)


def oc_status(c, org_id):
    """{"enabled", "active", "has_key", "key_ok", "migrated_at", "recovery_shown_at"} for the settings (no secrets).
    2.138.0 C (#1972): + recovery (a recovery key of the current format exists), rotating, rotated_at; R: recovery_stale
    (it exists but cannot be shown with this server key: only "New recovery key" helps)."""
    out = {"enabled": oc_enabled(), "active": oc_active(c), "has_key": False, "key_ok": None, "migrated_at": None,
           "recovery_shown_at": None, "recovery": False, "recovery_stale": False, "rotating": False, "rotated_at": None}
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        r = c.execute("SELECT kek_check, migrated_at, recovery_shown_at, recovery_wrapped, recovery_secret, rot_started_at, rotated_at FROM org_keys "
                      "WHERE org_id=?", (int(org_id),)).fetchone()
    if r:
        out.update(has_key=True, migrated_at=r["migrated_at"], recovery_shown_at=r["recovery_shown_at"], recovery=bool(r["recovery_wrapped"]),
                   rotating=r["rot_started_at"], rotated_at=r["rotated_at"])
        if SECRET_KEY:
            out["key_ok"] = hmac.compare_digest(str(r["kek_check"]), _kek_check(_kek(), org_id))
        if SECRET_KEY and r["recovery_wrapped"] and not r["rot_started_at"]:  # 2.138.0 C (#1972)
            try:
                _rck_open(_kek(), r["recovery_secret"], _rck_sad(org_id), "recovery secret")
            except OrgCryptError:
                out["recovery_stale"] = True
    return out



# ---- routes: Settings > Organisation > Encryption (organisation admins), the instance switch (instance admin) ----------
def _org_admin(c, oid):
    """The organisation id to work on (the person administers it). 2.138.0 C (#1972): oid 0 = the own personal office
    (orgs.personal_of, office/model.py pb_personal; 404 while there is none)."""
    from flask import g
    from ..accounts.orgs import _need_org_admin
    from ..core.access import Denied
    if g.user is None:
        raise Denied(401)
    if oid == 0:
        from ..agents.core import is_agent
        from ..office.model import pb_personal
        if is_agent(g.user):
            raise Denied(403, tr("Agents cannot use this endpoint"))
        p = pb_personal(c, g.user["id"], create=False)
        if not p:
            raise Denied(404)
        return p
    _need_org_admin(c, oid)
    return oid


RCK_FRESH_MIN = 10  # 2.138.0 C (#1972): minutes a sign-in counts as fresh for accounts without a password


def rck_step(c, u):
    """2.138.0 C (#1972): what showing the recovery key asks of this person: password, totp / passkey (the password and
    that second factor), fresh (no password: a sign-in of the last RCK_FRESH_MIN minutes) or proxy (signed in by the
    server's login proxy: only the server admin, orgcrypt_cli recovery)."""
    from flask import g
    from ..accounts.login import twofa_methods
    if u["password_hash"]:
        m = twofa_methods(c, u)
        return "totp" if "totp" in m else "passkey" if "passkey" in m else "password"
    return "proxy" if g.auth_via == "proxy" else "fresh"


def _rck_fresh(c, want=""):
    """2.144.5 A2 (#2387, review R2/R5): a fresh sign-in of this session: a step-up at the login provider for want
    ("<org id>:<show|new>"; one for new also allows show) or a sign-in with password / second factor / passkey in the
    last RCK_FRESH_MIN minutes (a sign-in link, a restore or an OIDC session without step-up never count)."""
    from flask import g, request
    from datetime import timedelta
    from ..accounts.session import _token_hash
    tok = request.cookies.get(COOKIE)
    if g.auth_via != "session" or not tok:
        return False
    r = c.execute("SELECT created_at, via, stepup_at, stepup_for FROM sessions WHERE token_hash=?", (_token_hash(tok),)).fetchone()
    since = iso(now_utc() - timedelta(minutes=RCK_FRESH_MIN))
    if not r:
        return False
    # 2.144.5 A (#2387): an OIDC sign-in counts only as the step-up sign-in (prompt=login + a fresh auth_time, oidc.py):
    # a new session alone may come from a live session at the provider without anyone typing anything
    oid = want.split(":")[0]
    if want and str(r[2] or "") >= since and str(r[3] or "") in (want, f"{oid}:new"):
        return True
    return r[1] in ("password", "2fa", "passkey") and str(r[0]) >= since


def rck_stepup_via(c, u):
    """2.144.5 A (#2387): how an account without a password signs in again for the step-up: oidc (linked, provider on) or ''."""
    from ..accounts.oidc import oidc_cfg
    return "oidc" if not u["password_hash"] and u["oidc_subject"] and oidc_cfg(c)["on"] else ""


def rck_stepup(c, u, b, want=""):
    """2.138.0 C (#1972): the step-up before a recovery key is shown or made new (rck_step); an error response or None.
    Rate-limited like a login (password and second factor count as failed logins)."""
    from ..accounts.login import _reauth, pend_take, rc_use, totp_match, unseal, wa_auth_verify
    from ..accounts.session import _rate_fail, _rate_keys
    step = rck_step(c, u)
    if step == "proxy":
        return jsonify(error=tr("You are signed in through the server’s login proxy. Ask the server admin for the recovery key (command line, SELF-HOSTING.md)."),
                       need="proxy"), 403
    if step == "fresh":
        if _rck_fresh(c, want):
            return None
        if rck_stepup_via(c, u):  # 2.144.5 A (#2387)
            return jsonify(error=tr("Sign in again with your login provider, then try again."), need="fresh", stepup="oidc"), 403
        return jsonify(error=tr("Please sign in again, then try again."), need="fresh"), 403
    e = _reauth(u, b)
    if e is not None:
        return e
    if step == "password":
        return None
    cred, code = b.get("credential"), b.get("code") if isinstance(b.get("code"), str) else ""
    if isinstance(cred, dict):
        p = pend_take(f"rck:{u['id']}")
        ok = bool(p) and wa_auth_verify(c, cred, p.get("chal"), p.get("rp"), uid=u["id"], uv=True) == u["id"]
    elif code and u["totp_secret"]:
        try:
            secret = unseal(c, f"totp:{u['id']}", u["totp_secret"])
        except (InvalidTag, ValueError):
            secret = ""
        st = totp_match(secret, code, u["totp_step"]) if secret else None
        ok = bool(st) and c.execute("UPDATE users SET totp_step=? WHERE id=? AND totp_step<?", (st, u["id"], st)).rowcount == 1
        ok = ok or rc_use(c, u["id"], code)
    else:
        return jsonify(error=tr("Confirm with your second factor."), need=step), 403
    if not ok:
        _rate_fail(_rate_keys(u["username"]))
        return jsonify(error=tr("Wrong code"), need=step), 403
    return None


def rck_tell(c, oid, actor, action):
    """2.138.0 C (#1972): a News item (in the app only, no push / mail) for the other admins of organisation oid: who
    showed / made new the recovery key or rotated the key (action shown | new | rotated). Never the value. Caller commits."""
    import json as _json
    with system_ctx(c):  # orgcrypt: who administers the organisation (structure), the notice names no content
        org = c.execute("SELECT name, personal_of FROM orgs WHERE id=?", (int(oid),)).fetchone()
        if not org or org["personal_of"]:
            return 0
        ids = [r[0] for r in c.execute("SELECT m.user_id FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND m.role='admin' "
                                       "AND u.kind!='agent' AND u.disabled=0 ORDER BY m.user_id", (int(oid),))]
        by = ""
        if actor:
            a = c.execute("SELECT display_name, username FROM users WHERE id=?", (int(actor),)).fetchone()
            by = (a["display_name"] or a["username"]) if a else ""
        n = 0
        for uid in ids:
            if uid == actor:
                continue
            c.execute("INSERT INTO notifications(user_id,kind,task_id,list_id,actor_id,comment_id,data,created_at) VALUES(?,?,?,?,?,?,?,?)",
                      (uid, "orgkey", None, None, actor or None, None,
                       _json.dumps({"org_id": int(oid), "org": org["name"], "action": action, "by_name": by}, ensure_ascii=False), iso_ms(now_utc())))
            n += 1
    return n


@app.get("/api/orgs/<int:oid>/encryption")
def oc_route_status(oid):
    """Organisation admins: {enabled (server key set), active (new data is encrypted), has_key, key_ok, migrated_at,
    recovery_shown_at}. No key material. 2.138.0 C (#1972): + recovery, rotating, rotated_at, step (what showing the
    recovery key asks: password | totp | passkey | fresh | proxy); oid 0 = the own personal office."""
    from flask import g
    c = db()
    oid = _org_admin(c, oid)
    u = c.execute("SELECT * FROM users WHERE id=?", (g.user["id"],)).fetchone()
    step = rck_step(c, u)
    extra = {"stepup": rck_stepup_via(c, u), "fresh": _rck_fresh(c, f"{oid}:show"),  # 2.144.5 A (#2387)
             "fresh_new": _rck_fresh(c, f"{oid}:new")} if step == "fresh" else {}  # 2.144.5 A2 (#2387, review R5)
    return jsonify(**oc_status(c, oid), password=bool(u and u["password_hash"]),  # password: showing the key asks for it
                   step=step, scope=pm_crypt_scope(), **extra)  # 2.46.1 (#1641)


@app.post("/api/orgs/<int:oid>/encryption/recovery/passkey")
def oc_route_recovery_passkey(oid):
    """2.138.0 C (#1972): the passkey challenge of the step-up (accounts whose second factor is a passkey)."""
    from flask import g
    from ..accounts.login import pend_set, wa_auth_options
    c = db()
    _org_admin(c, oid)
    if not c.execute("SELECT 1 FROM webauthn_creds WHERE user_id=?", (g.user["id"],)).fetchone():
        return err(tr("No passkey is set up"), 409)
    chal, rp, opts = wa_auth_options(c, g.user["id"], uv=True)  # 2.138.0 C (#1972, review F3): PIN / biometrics
    pend_set(f"rck:{g.user['id']}", chal=chal, rp=rp)
    return jsonify(opts)


@app.post("/api/orgs/<int:oid>/encryption/recovery")
def oc_route_recovery(oid):
    """Organisation admins, {password, code | credential, new}: the organisation's recovery key. 2.138.0 C (#1972): no
    longer the organisation's key itself but the recovery secret that wraps it ("R2-" + 13 groups, rck_format); new=true
    makes a new one (the earlier one stops working). Step-up rck_stepup: the password and, when set up, the second factor;
    accounts without a password need a fresh sign-in. The showing is noted in the office log and in
    org_keys.recovery_shown_at, the other admins get a News item -- never the value. 409 without a server key / while a
    rotation runs. oid 0 = the own personal office."""
    from flask import g
    c, b = db(), body()
    oid = _org_admin(c, oid)
    if not SECRET_KEY:
        return err(tr("Organisation encryption is off: the server has no KALMIDO_SECRET_KEY."), 409)
    u = c.execute("SELECT * FROM users WHERE id=?", (g.user["id"],)).fetchone()
    new = b.get("new") in (True, 1, "1", "true")
    e = rck_stepup(c, u, b, f"{oid}:{'new' if new else 'show'}")  # 2.144.5 A2 (#2387, review R5): bound to org + purpose
    if e is not None:
        c.commit()  # a used second factor stays used
        return e
    write_lock(c, f"orgkey-recovery-{oid}")
    r = rck_row(c, oid)
    if r is not None and r["wrapped_rot"]:
        return err(tr("The organisation’s key is being renewed on the server. Try again when that is finished."), 409)
    had = bool(r is not None and r["recovery_wrapped"])
    try:
        sec, made = rck_secret(c, oid, new=new)
    except RckStale:  # 2.138.0 C (#1972): never replaced without "New recovery key"
        return err(tr("The recovery key cannot be shown with the current server key. Make a new one; the earlier one stops working then."), 409)
    made = made and had  # a first recovery key replaces none (one of the earlier format stays valid until a rotation)
    if sec is None:
        return err(tr("Organisation encryption is off: the server has no KALMIDO_SECRET_KEY."), 409)
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        c.execute("UPDATE org_keys SET recovery_shown_at=? WHERE org_id=?", (iso(now_utc()), oid))
    from ..office.ledger import ofx_log
    ofx_log(c, oid, "recovery_key", target="org", detail={"new": 1} if made else {"shown": 1})
    rck_tell(c, oid, g.user["id"], "new" if made else "shown")
    c.commit()
    print("orgcrypt: recovery key of organisation", oid, "made new" if made else "shown", "for user", g.user["id"], flush=True)
    from ..notify.sev import sev_log
    sev_log("org_recovery_key", org=oid, user=g.user["id"], new=bool(made))
    r = jsonify(recovery_key=rck_format(sec), new=bool(made))
    r.headers["Cache-Control"] = "no-store"
    return r


@app.get("/api/admin/orgcrypt")
def oc_route_admin_get():
    from ..accounts.users import need_admin
    need_admin()
    c = db()
    return jsonify(enabled=oc_enabled(), org_encrypt=_setting(c) != "0", scope=pm_crypt_scope())  # 2.46.1 (#1641): scope


@app.put("/api/admin/orgcrypt")
def oc_route_admin_put():
    """Instance admin, {org_encrypt: bool}: encrypt organisation data at rest (on: the start-up pass runs again at once
    for what was stored plain meanwhile; off: nothing new is encrypted, encrypted data stays readable)."""
    from flask import g
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
