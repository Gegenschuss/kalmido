"""2.42.0 (#828): the organisation keys' bulk work -- the start-up run that encrypts existing data (oc_migrate_loop, a
background thread) and the command line for the server admin:

    python -m kalmido.admin.orgcrypt_cli status
    python -m kalmido.admin.orgcrypt_cli encrypt-all
    python -m kalmido.admin.orgcrypt_cli decrypt-all            # the way back before a downgrade (sets org_encrypt=0)
    python -m kalmido.admin.orgcrypt_cli decrypt-private        # 2.64.0 (#1864): only the private spaces' files plain again
    python -m kalmido.admin.orgcrypt_cli encrypt-private        #   (private_encrypt=0) / sealed again (private_encrypt=1)
    python -m kalmido.admin.orgcrypt_cli rewrap-accounts --old-key-file FILE   # 2.64.0: account keys after a new server key
        (FILE "-" = stdin: the earlier KALMIDO_SECRET_KEY, base64; never as an argument)
    python -m kalmido.admin.orgcrypt_cli rewrap --org N --recovery-file FILE [--force]   (FILE "-" = stdin; never as an argument;
        the key is tested on the organisation's encrypted data first, --force only when there is none)

Every run is idempotent and restartable: values carry the prefix "kenc1:", files the magic b"KENC1\\n", so a half-done
run simply continues; files are replaced atomically (tmp + os.replace), rows are updated only while they still hold the
value that was read (compare and set), in batches with a commit each. Output: counts only, never a value or a key.

2.64.0 (#1864): files_settle -- every stored file (task / comment attachments, project files, the file store, chat files)
is sealed with the key of the space it lies in now: plain files of private spaces get the owner's account key, a file that
moved (task into another list, list into / out of an organisation, a new list owner) is resealed for its new space. In
portions of BATCH files with a short pause (KALMIDO_ORGCRYPT_PAUSE seconds, default 0.2) when it runs in the background.
"""
import json
import os
import re
import sys
import threading
import time
import warnings

from ..core.config import ATT_DIR, OFFICE_DIR
from ..core.pg import system_ctx, write_lock
from ..core import orgcrypt as oc

# `python -m kalmido.admin.orgcrypt_cli` finds this module already loaded by the package (kalmido/__init__.py ORDER):
# harmless here (no routes, nothing at import time), so runpy's warning about it is not shown
warnings.filterwarnings("ignore", message=r".*kalmido\.admin\.orgcrypt_cli.*found in sys\.modules", category=RuntimeWarning)
TAG = "orgcrypt:"
BATCH = 200

# (table, id column, column, kind): text = the whole column, log = office log detail (only entries with protected keys),
# json = protected keys inside a JSON column (orgcrypt.JSON_KEYS)
FIELD_JOBS = [("office_company", "org_id", col, "text") for col in oc.FIELDS["office_company"]] + [
    ("office_contracts", "id", "rates", "text"),
    ("office_docs", "id", "sender", "text"),
    ("office_docs", "id", "totals", "json"),
    ("office_settings", "org_id", "data", "json"),
    ("office_doc_log", "id", "detail", "log"),
]


def _now():
    from ..core.db import iso, now_utc
    return iso(now_utc())


def _org_ids(c):
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        return [r[0] for r in c.execute("SELECT id FROM orgs ORDER BY id")]


# ---- one value ----------------------------------------------------------------------------------------------------------
def _json_tx(key, oid, table, col, v, enc):
    try:
        j = json.loads(v)
    except (TypeError, ValueError):
        return v
    if not isinstance(j, dict):
        return v
    changed = False
    for k in oc.JSON_KEYS[(table, col)]:
        x = j.get(k)
        ctx = f"{table}.{col}.{k}"
        if enc and x not in (None, "", {}, []) and not oc.oc_is_enc(x):
            j[k] = oc.oc_enc_k(key, oid, ctx, json.dumps(x, ensure_ascii=False))
            changed = True
        elif not enc and oc.oc_is_enc(x):
            p = oc.oc_dec_k(key, oid, ctx, x)
            try:
                j[k] = json.loads(p)
            except ValueError:
                j[k] = p
            changed = True
    return json.dumps(j, ensure_ascii=False) if changed else v


def _tx(key, oid, table, col, kind, v, enc):
    """The value to store (encrypting or decrypting); v itself when nothing changes."""
    if v in (None, ""):
        return v
    if kind == "json":
        return _json_tx(key, oid, table, col, v, enc)
    if enc:
        if oc.oc_is_enc(v) or (kind == "log" and not any(m in v for m in oc.LOG_MARKERS)):
            return v
        return oc.oc_enc_k(key, oid, f"{table}.{col}", v)
    return oc.oc_dec_k(key, oid, f"{table}.{col}", v) if oc.oc_is_enc(v) else v


def _is_enc(table, col, kind, v):
    if not isinstance(v, str) or not v:
        return None  # empty: counts as neither
    if kind == "json":
        if oc.PREFIX in v:
            return True
        try:
            j = json.loads(v)
        except ValueError:
            return None
        return False if isinstance(j, dict) and any(j.get(k) not in (None, "", {}, []) for k in oc.JSON_KEYS[(table, col)]) else None
    if oc.oc_is_enc(v):
        return True
    if kind == "log" and not any(m in v for m in oc.LOG_MARKERS):
        return None
    return False


# ---- fields of one organisation -----------------------------------------------------------------------------------------
def fields_pass(c, oid, enc, key, stop=None):
    """Encrypt (enc) or decrypt every protected field of organisation oid. -> number of changed values."""
    n = 0
    for table, idc, col, kind in FIELD_JOBS:
        last = None
        while True:
            if stop and stop():
                return n
            with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
                write_lock(c, "orgcrypt")
                sql = f"SELECT {idc} AS rid, {col} AS v FROM {table} WHERE org_id=?"
                args = [oid]
                if last is not None:
                    sql += f" AND {idc} > ?"
                    args.append(last)
                rows = c.execute(sql + f" ORDER BY {idc} LIMIT {BATCH}", args).fetchall()
                for r in rows:
                    new = _tx(key, oid, table, col, kind, r["v"], enc)
                    if new != r["v"]:
                        n += c.execute(f"UPDATE {table} SET {col}=? WHERE {idc}=? AND org_id=? AND {col}=?",
                                       (new, r["rid"], oid, r["v"])).rowcount
            c.commit()
            if len(rows) < BATCH:
                break
            last = rows[-1]["rid"]
    n += _cost_pass(c, oid, enc, key, stop)
    return n


def _cost_pass(c, oid, enc, key, stop=None):
    """office_doc_items: cost (NUMERIC) <-> cost_enc (TEXT)."""
    n = 0
    ctx = "office_doc_items.cost_enc"
    while True:
        if stop and stop():
            return n
        with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
            write_lock(c, "orgcrypt")
            if enc:
                rows = c.execute("SELECT id, cost::text AS v FROM office_doc_items WHERE org_id=? AND cost_enc IS NULL AND cost<>0 "
                                 f"ORDER BY id LIMIT {BATCH}", (oid,)).fetchall()
                for r in rows:
                    n += c.execute("UPDATE office_doc_items SET cost=0, cost_enc=? WHERE id=? AND org_id=? AND cost_enc IS NULL AND cost::text=?",
                                   (oc.oc_enc_k(key, oid, ctx, r["v"]), r["id"], oid, r["v"])).rowcount
            else:
                rows = c.execute(f"SELECT id, cost_enc AS v FROM office_doc_items WHERE org_id=? AND cost_enc IS NOT NULL ORDER BY id LIMIT {BATCH}",
                                 (oid,)).fetchall()
                for r in rows:
                    v = r["v"]
                    plain = oc.oc_dec_k(key, oid, ctx, v) if oc.oc_is_enc(v) else v
                    n += c.execute("UPDATE office_doc_items SET cost=CAST(? AS NUMERIC), cost_enc=NULL WHERE id=? AND org_id=? AND cost_enc=?",
                                   (plain or "0", r["id"], oid, v)).rowcount
        c.commit()
        if len(rows) < BATCH:
            return n


def fields_count(c, oid):
    """{"enc": n, "plain": n} over the protected fields of organisation oid."""
    out = {"enc": 0, "plain": 0}
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        for table, idc, col, kind in FIELD_JOBS:
            for r in c.execute(f"SELECT {col} AS v FROM {table} WHERE org_id=?", (oid,)):
                s = _is_enc(table, col, kind, r["v"])
                if s is not None:
                    out["enc" if s else "plain"] += 1
        out["enc"] += c.execute("SELECT COUNT(*) FROM office_doc_items WHERE org_id=? AND cost_enc IS NOT NULL", (oid,)).fetchone()[0]
        out["plain"] += c.execute("SELECT COUNT(*) FROM office_doc_items WHERE org_id=? AND cost_enc IS NULL AND cost<>0", (oid,)).fetchone()[0]
    return out


# ---- files ------------------------------------------------------------------------------------------------------------
def _office_files(oid):
    """The stored office files of organisation oid (documents, XML, archive PDFs); the logos stay plain (shown openly)."""
    d = os.path.join(OFFICE_DIR, str(int(oid)))
    if not os.path.isdir(d):
        return []
    out = []
    for name in sorted(os.listdir(d)):
        p = os.path.join(d, name)
        if name.startswith("logo") or name.endswith((".part", ".tmp")) or not os.path.isfile(p) or os.path.islink(p):
            continue
        out.append(p)
    return out


def f8f_icon_files(c, oid=None):
    """2.58.0 (#1805): {path: org id} of the lists' own pictures (all lists, or only those of organisation oid)."""
    from ..accounts.pictures import list_icon_path
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        rows = c.execute("SELECT id, icon, org_id FROM lists WHERE icon LIKE 'u:%'" + ("" if oid is None else " AND org_id=?"),  # pg-ok: prefix marker u: is case-exact
                         () if oid is None else (oid,)).fetchall()
    from ..lists.listhead import o3c_head_files
    return ({list_icon_path(r[0], r[1][2:]): r[2] for r in rows if re.fullmatch(r"u:[A-Za-z0-9_-]{8,40}", r[1])} | o3c_head_files(c, oid)  # 2.83.0 C (#1427): + header pictures
            | f8f_org_icon_files(c, oid))


def f8f_org_icon_files(c, oid=None):
    """2.87.9 (#1913): {path: org id} of the organisations' own symbol pictures (all, or only that of organisation oid)."""
    from ..accounts.pictures import org_icon_path, org_icon_tok
    with system_ctx(c):  # orgcrypt: server-side bulk work on stored files, never content handed to a person
        rows = c.execute("SELECT id, icon FROM orgs WHERE icon LIKE 'u:%'" + ("" if oid is None else " AND id=?"),  # pg-ok: prefix marker u: is case-exact
                         () if oid is None else (oid,)).fetchall()
    return {org_icon_path(r[0], org_icon_tok(r[1])): r[0] for r in rows if org_icon_tok(r[1])}


def org_files(c, oid):
    """Every stored file that belongs to organisation oid now: attachments of tasks in its lists (comments included),
    project files of its lists, its office files, the lists' own pictures (2.58.0)."""
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        rows = c.execute("SELECT a.path FROM attachments a JOIN tasks t ON t.id=a.task_id JOIN lists l ON l.id=t.list_id "
                         "WHERE l.org_id=? UNION ALL SELECT f.path FROM list_files f JOIN lists l ON l.id=f.list_id WHERE l.org_id=? "
                         "UNION ALL SELECT f.path FROM budget_files f JOIN lists l ON l.id=f.list_id WHERE l.org_id=? "  # 2.72.0 (#1333)
                         "UNION ALL SELECT path FROM wiki_files WHERE org_id=?",  # 2.99.0 A (#2182): files of knowledge pages
                         (oid, oid, oid, oid)).fetchall()
    return [os.path.join(ATT_DIR, r[0]) for r in rows if r[0]] + _office_files(oid) + list(f8f_icon_files(c, oid))


def all_files(c):
    """Every stored attachment / project file / office file of the instance (for decrypt-all and the key deletion).
    2.64.0 (#1864): also the file store's versions and the chat files."""
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        rows = c.execute("SELECT path FROM attachments UNION ALL SELECT path FROM list_files UNION ALL SELECT path FROM fs_versions "
                         "UNION ALL SELECT path FROM chat_files UNION ALL SELECT path FROM budget_files "  # 2.72.0 (#1333)
                         "UNION ALL SELECT path FROM wiki_files").fetchall()  # 2.99.0 A (#2182)
    out = [os.path.join(ATT_DIR, r[0]) for r in rows if r[0]] + list(f8f_icon_files(c))  # 2.58.0 (#1805)
    if os.path.isdir(OFFICE_DIR):
        for name in sorted(os.listdir(OFFICE_DIR)):
            if name.isdigit():
                out += _office_files(int(name))
    return out


def _head(path):
    try:
        with open(path, "rb") as f:
            return f.read(oc._HEAD)
    except OSError:
        return None


def files_encrypt(c, oid, key, paths, stop=None):
    """Seal the plain files among paths with organisation oid's key. -> (sealed, failed)."""
    n = bad = 0
    for p in paths:
        if stop and stop():
            break
        h = _head(p)
        if h is None or h[:len(oc.MAGIC)] == oc.MAGIC:
            continue
        try:
            with open(p, "rb") as f:
                data = f.read()
            if not data:
                continue
            oc.oc_reseal_file(p, oc.oc_seal_k(key, oid, data))
            n += 1
        except OSError as e:
            bad += 1
            print(TAG, "cannot seal a file:", type(e).__name__, flush=True)
    return n, bad


def files_decrypt(c, paths, only_org=None, reseal=None, only=None, stats=None):
    """Open the sealed files among paths (with the key named in each header; only_org: only files of that organisation;
    only(header id) -> bool: 2.64.0 (#1864), e.g. only the account keys). reseal(path) -> org id to seal the plain
    content with instead (None = plain). -> (changed, failed)."""
    n = bad = 0
    keys = {}
    for p in paths:
        h = _head(p)
        if h is None or h[:len(oc.MAGIC)] != oc.MAGIC:
            continue
        hid = oc.oc_file_org(h)
        if (only_org is not None and hid != only_org) or (only is not None and not only(hid)):
            continue
        try:
            if hid not in keys:
                keys[hid] = oc.oc_key(c, hid, create=False)
            if keys[hid] is None:
                raise oc.OrgCryptError(f"org {hid}: no key")
            with open(p, "rb") as f:
                data = oc.oc_open_k(keys[hid], f.read())
            tgt = reseal(p) if reseal else None
            if tgt:
                if tgt not in keys:
                    keys[tgt] = oc.oc_key(c, tgt)
                data = oc.oc_seal_raw(keys[tgt], tgt, data) if keys[tgt] else data
            elif data[:len(oc.MAGIC)] == oc.MAGIC:
                # 2.64.0 (#1864): an uploaded file that itself looks sealed keeps its outer layer (stored plain, the server
                # would open it with the key named inside); counted as "kept", not as a failure
                if stats is not None:
                    stats["kept"] = stats.get("kept", 0) + 1
                continue
            oc.oc_reseal_file(p, data)
            n += 1
        except (OSError, oc.OrgCryptError) as e:
            bad += 1
            print(TAG, "cannot open a sealed file:", str(e) if isinstance(e, oc.OrgCryptError) else type(e).__name__, flush=True)
    return n, bad


# ---- 2.64.0 (#1864): every stored file in the space it lies in now ---------------------------------------------------
# (table, id column, SELECT of id, path, org_id, owner_id): the space = the organisation, else the owner's account
SPACE_SQL = (
    ("attachments", "a.id", "SELECT a.id AS rid, a.path, l.org_id, l.owner_id FROM attachments a JOIN tasks t ON t.id=a.task_id "
                            "JOIN lists l ON l.id=t.list_id WHERE a.path<>''", "t.list_id"),
    ("list_files", "f.id", "SELECT f.id AS rid, f.path, l.org_id, l.owner_id FROM list_files f JOIN lists l ON l.id=f.list_id "
                           "WHERE f.path<>''", "f.list_id"),
    ("fs_versions", "v.id", "SELECT v.id AS rid, v.path, n.org_id, n.owner_id FROM fs_versions v JOIN fs_nodes n ON n.id=v.node_id "
                            "WHERE v.path<>''", None),
    ("chat_files", "f.id", "SELECT f.id AS rid, f.path, NULL AS org_id, m.user_id AS owner_id FROM chat_files f "
                           "JOIN agent_chat m ON m.id=f.message_id WHERE f.path<>''", None),
    # 2.72.0 (#1333): the receipts of the household budget
    ("budget_files", "f.id", "SELECT f.id AS rid, f.path, l.org_id, l.owner_id FROM budget_files f JOIN lists l ON l.id=f.list_id "
                             "WHERE f.path<>''", "f.list_id"),
    # 2.99.0 A (#2182): files of knowledge pages (the space of their page)
    ("wiki_files", "f.id", "SELECT f.id AS rid, f.path, f.org_id, f.owner_id FROM wiki_files f WHERE f.path<>''", None),
    # 2.83.0 (#1427): the lists' own header pictures (lists/listhead.py o3c_head_rel) move with their list
    ("lists", "l.id", "SELECT l.id AS rid, 'listheads/l' || l.id || '-' || l.header_file || '.jpg' AS path, l.org_id, l.owner_id "
                      "FROM lists l WHERE l.header_file<>''", "l.id"),
)


def _bud():
    """2.72.0 (#1333): life/budget.py (imported late: this module is also a command line tool)."""
    from ..life import budget
    return budget


def _row_space(r):
    return int(r["org_id"]) if r["org_id"] else oc.oc_user_space(r["owner_id"])


def space_rows(c, list_ids=None, commit=False):
    """Yields lists of (full path, space id) in portions of BATCH rows (list_ids: only the files of these lists).
    commit: end the read transaction after each portion (the background pass; never inside a caller's transaction)."""
    for table, idc, sql, lcol in SPACE_SQL:
        if list_ids is not None and lcol is None:
            continue
        last = 0
        while True:
            q, args = sql + f" AND {idc} > ?", [last]
            if list_ids is not None:
                ids = sorted({int(x) for x in list_ids})
                q += f" AND {lcol} IN ({','.join('?' * len(ids)) or 'NULL'})"
                args += ids
            with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
                rows = c.execute(q + f" ORDER BY {idc} LIMIT {BATCH}", args).fetchall()
            if commit:
                c.commit()
            yield [(os.path.join(ATT_DIR, r["path"]), _row_space(r)) for r in rows]
            if len(rows) < BATCH:
                break
            last = rows[-1]["rid"]


def _pause():
    try:
        return max(0.0, float(os.environ.get("KALMIDO_ORGCRYPT_PAUSE", "0.2")))
    except ValueError:
        return 0.2


def files_settle(c, stop=None, list_ids=None, pause=0.0):
    """Seal every stored file with the key of its space now: plain ones (when that space is active, oc_active_for) and
    ones sealed for another space (resealed). Files whose space is not active stay as they are. -> {sealed, resealed,
    failed}."""
    out = {"sealed": 0, "resealed": 0, "failed": 0}
    keys, active = {}, {}

    def key(sid, create):
        if sid not in keys or (keys[sid] is None and create):
            keys[sid] = oc.oc_key(c, sid, create=create)
            c.commit()
        return keys[sid]
    for part in space_rows(c, list_ids, commit=True):
        if stop and stop():  # once per portion (the start-up pass asks the database)
            return out
        for p, sid in part:
            if not sid:
                continue
            if sid not in active:
                active[sid] = oc.oc_active_for(c, sid)
            if not active[sid]:
                continue
            h = _head(p)
            if h is None:
                continue
            sealed = h[:len(oc.MAGIC)] == oc.MAGIC
            hid = oc.oc_file_org(h) if sealed else None
            if sealed and (hid == sid or not hid):  # header 0 = a private document preview (docs/store.py), not in these tables
                continue
            # a key that does not open with the server key raises here (the start-up pass stops with its alarm)
            k_old = key(hid, False) if sealed else None
            k = key(sid, True)
            if k is None:
                continue
            try:
                if sealed and k_old is None:
                    raise oc.OrgCryptError(f"{oc._label(hid)}: no key")
                with open(p, "rb") as f:
                    data = f.read()
                if not data:
                    continue
                if sealed:
                    data = oc.oc_open_k(k_old, data)
                oc.oc_reseal_file(p, oc.oc_seal_raw(k, sid, data))
                out["resealed" if sealed else "sealed"] += 1
            except (OSError, oc.OrgCryptError) as e:
                out["failed"] += 1
                print(TAG, "cannot seal a file:", str(e) if isinstance(e, oc.OrgCryptError) else type(e).__name__, flush=True)
        if pause:
            time.sleep(pause)
    return out


def private_count(c):
    """{"keys": n, "files": {"enc": n, "plain": n}} over the files of private spaces (2.64.0 #1864)."""
    out = {"keys": 0, "keys_other_server_key": 0, "files": {"enc": 0, "plain": 0}}
    kek = oc._kek()
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        for r in c.execute("SELECT user_id, kek_check FROM user_keys").fetchall():
            out["keys"] += 1
            if kek is not None and r["kek_check"] != oc._kek_check(kek, -int(r["user_id"])):
                out["keys_other_server_key"] += 1  # made with another KALMIDO_SECRET_KEY (rewrap-accounts)
    for part in space_rows(c, commit=True):
        for p, sid in part:
            if sid and sid < 0:
                h = _head(p)
                if h:
                    out["files"]["enc" if h[:len(oc.MAGIC)] == oc.MAGIC else "plain"] += 1
    return out


def decrypt_private(c):
    """The way back for the private spaces only: private_encrypt=0 first, then every file sealed with an account key plain
    again (files of organisations stay sealed). -> {"files", "failed"}."""
    from ..core.db import gset
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        gset(c, "private_encrypt", "0")
        c.execute("UPDATE user_keys SET migrated_at=NULL")
    c.commit()
    st = {}
    _bud().bud_settle(c, plain=lambda sid: sid < 0)  # 2.72.0 (#1333): budgets of private spaces plain again
    n, bad = files_decrypt(c, all_files(c), only=lambda hid: hid is not None and hid < 0, stats=st)
    return {"files": n, "failed": bad, "kept": st.get("kept", 0)}


def before_user_delete(c, uid):
    """2.64.0 (#1864): called by an account's deletion before its key row goes (the foreign key): files sealed with this
    account's key that lie in another space now (a list that got another owner or moved into an organisation, a task
    moved on) are sealed for that space (or stored plain when it is not active). Its own files go with the account.
    -> (changed, failed)."""
    if not oc.oc_enabled():
        return 0, 0
    me_sid = oc.oc_user_space(uid)
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        if not c.execute("SELECT 1 FROM user_keys WHERE user_id=?", (int(uid),)).fetchone():
            return 0, 0
    where = {}
    for part in space_rows(c):
        for p, sid in part:
            if sid != me_sid:
                where[p] = sid

    def target(p):  # sealed for the space it lies in now (also when that space is switched off: never lost, never plain)
        return where.get(p) or None
    _bud().bud_settle(c, force_from=me_sid, commit=False)  # 2.72.0 (#1333): budget rows of this key in lists of another space now
    return files_decrypt(c, list(where), only_org=me_sid, reseal=target)


def files_count(c, oid):
    out = {"enc": 0, "plain": 0}
    for p in org_files(c, oid):
        h = _head(p)
        if h:
            out["enc" if h[:len(oc.MAGIC)] == oc.MAGIC else "plain"] += 1
    return out


# ---- whole runs -------------------------------------------------------------------------------------------------------
def encrypt_org(c, oid, stop=None):
    """Encrypt everything of organisation oid (key made when missing), then note migrated_at. -> counts."""
    key = oc.oc_key(c, oid)
    c.commit()
    if key is None:
        return {"fields": 0, "files": 0, "failed": 0}
    nf = fields_pass(c, oid, True, key, stop)
    from ..tasks.related import emb_drop_org
    emb_drop_org(c, oid, sealed=False)  # 2.59.0 B (#1375): plain task vectors go, the embedding worker computes them sealed
    c.commit()
    ns, bad = files_encrypt(c, oid, key, org_files(c, oid), stop)
    if not (stop and stop()) and not bad:
        with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
            c.execute("UPDATE org_keys SET migrated_at=? WHERE org_id=?", (_now(), oid))
        c.commit()
    return {"fields": nf, "files": ns, "failed": bad}


def encrypt_all(c, stop=None, pause=0.0):
    tot = {"orgs": 0, "fields": 0, "files": 0, "failed": 0, "resealed": 0}
    for oid in _org_ids(c):
        if stop and stop():
            break
        r = encrypt_org(c, oid, stop)
        tot["orgs"] += 1
        for k in ("fields", "files", "failed"):
            tot[k] += r[k]
    # 2.64.0 (#1864): the private spaces' files, and files that lie in another space now
    st = files_settle(c, stop, pause=pause)
    tot["fields"] += _bud().bud_settle(c, stop=stop)  # 2.72.0 (#1333): the household budget's rows in their list's space
    tot["files"] += st["sealed"]
    tot["resealed"], tot["failed"] = st["resealed"], tot["failed"] + st["failed"]
    if not (stop and stop()) and not st["failed"] and oc.oc_active(c) and oc.oc_private_on(c):
        with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
            c.execute("UPDATE user_keys SET migrated_at=? WHERE migrated_at IS NULL", (_now(),))
        c.commit()
    return tot


def decrypt_all(c):
    """The way back: org_encrypt=0 first (nothing new gets encrypted, also not by a running server), then every field and
    file back to plain; migrated_at cleared. -> counts."""
    from ..core.db import gset
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        gset(c, "org_encrypt", "0")
        c.execute("UPDATE org_keys SET migrated_at=NULL")
        c.execute("UPDATE user_keys SET migrated_at=NULL")  # 2.64.0 (#1864): all_files includes the private spaces' files
    c.commit()
    tot = {"orgs": 0, "fields": 0, "files": 0, "failed": 0, "kept": 0}
    for oid in _org_ids(c):
        key = oc.oc_key(c, oid, create=False)
        tot["orgs"] += 1
        if key is None:
            continue
        tot["fields"] += fields_pass(c, oid, False, key)
    tot["fields"] += _bud().bud_settle(c, plain=lambda sid: True)  # 2.72.0 (#1333): the household budget plain again
    from ..tasks.related import emb_drop_sealed
    emb_drop_sealed(c)  # 2.59.0 B (#1375): no sealed task vector stays behind (computed again, plain)
    c.commit()
    st = {}
    n, bad = files_decrypt(c, all_files(c), stats=st)
    tot["files"], tot["failed"], tot["kept"] = n, bad, st.get("kept", 0)
    return tot


def status(c):
    out = {"server_key": oc.oc_enabled(), "org_encrypt": None, "private_encrypt": None, "orgs": []}
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        r = c.execute("SELECT value FROM settings WHERE key='org_encrypt'").fetchone()
    out["org_encrypt"] = (r[0] if r else "1") != "0"
    out["private_encrypt"] = oc.oc_private_on(c)  # 2.64.0 (#1864)
    out["private"] = private_count(c)
    for oid in _org_ids(c):
        st = oc.oc_status(c, oid)
        out["orgs"].append({"org": oid, "has_key": st["has_key"], "key_ok": st["key_ok"], "migrated_at": st["migrated_at"],
                            "fields": fields_count(c, oid), "files": files_count(c, oid)})
    return out


def before_org_delete(c, oid):
    """Called by the organisation's deletion before its key goes: files sealed with this organisation's key that lie in
    lists of another organisation (or private ones) now are sealed with that organisation's key (or stored plain). The
    organisation's own office folder is removed by the caller. -> (changed, failed). 2.64.0 (#1864): a file in a private
    list gets the owner's account key (when private files are sealed), the chat / file store files count as well."""
    if not oc.oc_enabled():
        return 0, 0
    att = {}
    for part in space_rows(c):
        att.update(part)
    att.update(f8f_icon_files(c))  # 2.58.0 (#1805): the lists' own pictures (a private list's picture: stored plain, as in 2.58)

    def target(p):  # 2.64.0 (#1864): sealed for the space it lies in now (also when that space is switched off)
        t = att.get(p)
        return t if (t and t != oid) else None
    _bud().bud_settle(c, force_from=oid, commit=False)  # 2.72.0 (#1333): budget rows of this key in lists of another space now
    return files_decrypt(c, list(att), only_org=oid, reseal=target)


# ---- start-up thread --------------------------------------------------------------------------------------------------
_RUN = threading.Lock()
_AGAIN = threading.Event()  # a kick while a pass runs: one more pass afterwards (that pass may be past the organisation)


def oc_migrate_once():
    """One encrypting pass over every organisation (when active). Safe to run any time; returns counts or None."""
    from ..core.db import connect
    if not oc.oc_enabled():
        return None
    if not _RUN.acquire(blocking=False):
        _AGAIN.set()
        return None
    _AGAIN.clear()
    c = connect()
    try:
        if not oc.oc_active(c):
            return None
        tot = encrypt_all(c, stop=lambda: not oc.oc_active(c), pause=_pause())
        if tot["fields"] or tot["files"] or tot["failed"] or tot["resealed"]:
            print(TAG, "encrypted at rest:", tot["fields"], "fields,", tot["files"], "files in", tot["orgs"], "organisations and the private spaces,",
                  tot["resealed"], "files resealed for their space", f"({tot['failed']} files failed)" if tot["failed"] else "", flush=True)
        return tot
    except oc.OrgCryptError as e:
        print(TAG, "start-up encryption stopped:", e, flush=True)
        from ..notify.alerts import aa_now
        from ..core.i18n import N_
        aa_now("security", "orgcrypt:key", N_("The organisation data cannot be encrypted: the server key (KALMIDO_SECRET_KEY) does not match the stored organisation keys."))
        return None
    except Exception as e:  # noqa: BLE001 -- a background thread never takes the server down
        print(TAG, "start-up encryption failed:", type(e).__name__, e, flush=True)
        return None
    finally:
        try:
            c.rollback()
        except Exception:  # noqa: BLE001
            pass
        c.close()
        _RUN.release()
        if _AGAIN.is_set():
            _AGAIN.clear()
            oc_migrate_start()


def oc_migrate_loop(delay=3.0):
    """The background thread: a wait (the server answers first), then one pass."""
    time.sleep(float(os.environ.get("KALMIDO_ORGCRYPT_DELAY", delay)))
    oc_migrate_once()


def oc_migrate_start(delay=3.0):
    threading.Thread(target=oc_migrate_loop, args=(delay,), daemon=True, name="orgcrypt").start()


def oc_migrate_kick():
    """2.42.0 (#828): a list moved into an organisation -> its plain files / fields are encrypted now, not at the next start
    (a pass in the background after the usual short wait, so the moving request has committed). Not in helper processes."""
    if oc.oc_enabled() and os.environ.get("TASKS_WATCHDOG", "1") == "1":
        oc_migrate_start()


def oc_settle_lists(list_ids):
    """2.64.0 (#1864): one pass over the files of these lists (tasks moved between spaces, a list moved into / out of an
    organisation or handed to another owner): each sealed for its space now. Never raises."""
    from ..core.db import connect
    c = None
    try:
        c = connect()
        files_settle(c, list_ids=list_ids, pause=_pause())
        _bud().bud_settle(c, list_ids=list_ids)  # 2.72.0 (#1333): a moved budget list's rows for its new space
    except Exception as e:  # noqa: BLE001 -- a background thread never takes the server down
        print(TAG, "resealing moved files failed:", type(e).__name__, flush=True)
    finally:
        if c is not None:
            try:
                c.rollback()
            except Exception:  # noqa: BLE001
                pass
            c.close()


def oc_settle_kick(list_ids, delay=3.0):
    """2.64.0 (#1864): oc_settle_lists in the background after the usual short wait (the moving request has committed).
    Not in helper processes; nothing without a server key."""
    ids = {int(x) for x in list_ids or () if x}
    if not ids or not oc.oc_enabled() or os.environ.get("TASKS_WATCHDOG", "1") != "1":
        return
    from flask import g, has_request_context
    if has_request_context() and not getattr(g, "_oc_settle_after", False):
        # after the request's commit; a request that fails (rolled back) never runs it
        from flask import after_this_request
        g._oc_settle_after = True
        g._oc_settle_ids = set()

        @after_this_request
        def _go(resp):
            if resp.status_code < 400:
                _settle_queue(g._oc_settle_ids, delay)
            return resp
    if has_request_context():
        g._oc_settle_ids.update(ids)
        return
    _settle_queue(ids, delay)


def _settle_queue(ids, delay):
    with _SETTLE_LOCK:  # many moves at once (a batch): one waiting thread takes them all
        start = not _SETTLE
        _SETTLE.update(ids)
    if not start:
        return

    def run():
        time.sleep(float(os.environ.get("KALMIDO_ORGCRYPT_DELAY", delay)))
        with _SETTLE_LOCK:
            todo = sorted(_SETTLE)
            _SETTLE.clear()
        oc_settle_lists(todo)
    threading.Thread(target=run, daemon=True, name="orgcrypt-settle").start()


_SETTLE = set()
_SETTLE_LOCK = threading.Lock()


# ---- rewrap: test a recovery key before it replaces anything ---------------------------------------------------------
def rewrap_probe(c, oid, key):
    """True = the key opens an encrypted value or a sealed file of organisation oid, False = it does not (a typo in the
    recovery key), None = the organisation has nothing encrypted to test it on."""
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        for table, idc, col, kind in FIELD_JOBS:
            if kind != "text":
                continue
            r = c.execute(f"SELECT {col} AS v FROM {table} WHERE org_id=? AND substr({col}, 1, {len(oc.PREFIX)})=? LIMIT 1", (oid, oc.PREFIX)).fetchone()
            if r:
                try:
                    oc.oc_dec_k(key, oid, f"{table}.{col}", r["v"])
                    return True
                except oc.OrgCryptError:
                    return False
    for p in org_files(c, oid):
        try:
            with open(p, "rb") as f:
                data = f.read()
        except OSError:
            continue
        if oc.oc_file_org(data) != oid:
            continue
        try:
            oc.oc_open_k(key, data)
            return True
        except oc.OrgCryptError:
            return False
    return None


# ---- command line -----------------------------------------------------------------------------------------------------
def _read_recovery(src):
    data = sys.stdin.read() if src == "-" else open(src, encoding="utf-8").read()
    return oc.oc_parse_recovery(data.strip().splitlines()[0] if data.strip() else "")


def main(argv):
    import argparse
    from ..core.db import connect
    ap = argparse.ArgumentParser(prog="python -m kalmido.admin.orgcrypt_cli", description="Kalmido: organisation keys (encryption at rest)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="per organisation: key, encrypted / plain fields and files")
    sub.add_parser("encrypt-all", help="encrypt every organisation's fields and files (org_encrypt=1)")
    sub.add_parser("decrypt-all", help="the way back before a downgrade: everything plain again, org_encrypt=0")
    sub.add_parser("decrypt-private", help="2.64.0: only the private spaces' files plain again, private_encrypt=0")
    sub.add_parser("encrypt-private", help="2.64.0: seal the private spaces' files again, private_encrypt=1")
    ra = sub.add_parser("rewrap-accounts", help="2.64.0: store the account keys again with the current server key (needs the earlier one)")
    ra.add_argument("--old-key-file", required=True, help='a file holding the earlier KALMIDO_SECRET_KEY, "-" = stdin')
    rw = sub.add_parser("rewrap", help="store an organisation's key again (new KALMIDO_SECRET_KEY) from its recovery key")
    rw.add_argument("--org", type=int, required=True)
    rw.add_argument("--recovery-file", required=True, help='a file holding the recovery key, "-" = stdin')
    rw.add_argument("--force", action="store_true", help="store it although the organisation has nothing encrypted to test the key on")
    a = ap.parse_args(argv)
    if not oc.oc_enabled():
        print(TAG, "KALMIDO_SECRET_KEY is not set (or invalid): organisation encryption is off, nothing to do", flush=True)
        return 0 if a.cmd == "status" else 2
    c = connect()
    try:
        if a.cmd == "status":
            print(json.dumps(status(c), indent=2))
        elif a.cmd == "encrypt-all":
            from ..core.db import gset
            with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
                gset(c, "org_encrypt", "1")
            c.commit()
            print(TAG, "encrypt-all:", json.dumps(encrypt_all(c)))
        elif a.cmd == "decrypt-all":
            t = decrypt_all(c)
            print(TAG, "decrypt-all:", json.dumps(t))
            st = status(c)
            left = sum(o["fields"]["enc"] + o["files"]["enc"] for o in st["orgs"]) + st["private"]["files"]["enc"] - t["kept"]  # 2.64.0 (#1864)
            print(TAG, "still encrypted:", left, "(org_encrypt is now 0)")
            if left or t["failed"]:
                return 1
        elif a.cmd == "decrypt-private":
            t = decrypt_private(c)
            print(TAG, "decrypt-private:", json.dumps(t))
            left = private_count(c)["files"]["enc"] - t["kept"]  # kept: uploads whose content itself looks sealed
            print(TAG, "still encrypted in private spaces:", left, "(private_encrypt is now 0)")
            if left > 0 or t["failed"]:
                return 1
        elif a.cmd == "encrypt-private":
            from ..core.db import gset
            with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
                gset(c, "private_encrypt", "1")
            c.commit()
            if not oc.oc_active(c):
                print(TAG, "encrypt-private: org_encrypt is 0, nothing is sealed until it is switched on again", flush=True)
                return 1
            print(TAG, "encrypt-private:", json.dumps(files_settle(c)))
        elif a.cmd == "rewrap-accounts":
            from ..core.config import _secret_key_parse
            try:
                raw = sys.stdin.read() if a.old_key_file == "-" else open(a.old_key_file, encoding="utf-8").read()
            except OSError:
                raw = ""
            old = _secret_key_parse((raw.strip().splitlines() or [""])[0].strip())
            if not old:
                print(TAG, "rewrap-accounts: that is not a server key (32 bytes, base64)", flush=True)
                return 2
            t = oc.oc_rewrap_accounts(c, old)
            c.commit()
            print(TAG, "rewrap-accounts:", json.dumps(t))
            if t["other"]:
                return 1
        elif a.cmd == "rewrap":
            try:
                key = _read_recovery(a.recovery_file)
            except (OSError, ValueError):
                print(TAG, "rewrap: that is not a recovery key", flush=True)
                return 2
            with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
                if not c.execute("SELECT 1 FROM orgs WHERE id=?", (a.org,)).fetchone():
                    print(TAG, "rewrap: no organisation", a.org)
                    return 2
            ok = rewrap_probe(c, a.org, key)
            if ok is False:
                print(TAG, "rewrap: this recovery key does not open the organisation's encrypted data (typo?) - nothing changed", flush=True)
                return 1
            if ok is None and not a.force:
                print(TAG, "rewrap: organisation", a.org, "has nothing encrypted to test the key on - check it and repeat with --force", flush=True)
                return 1
            changed = oc.oc_rewrap(c, a.org, key)
            c.commit()
            print(TAG, "rewrap: organisation", a.org, "key stored with the current server key" if changed else "key was already usable (unchanged)")
        return 0
    except oc.OrgCryptError as e:
        print(TAG, "error:", e, flush=True)
        return 1
    finally:
        c.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
