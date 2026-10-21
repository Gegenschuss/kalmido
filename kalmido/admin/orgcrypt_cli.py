"""2.42.0 (#828): the organisation keys' bulk work -- the start-up run that encrypts existing data (oc_migrate_loop, a
background thread) and the command line for the server admin:

    python -m kalmido.admin.orgcrypt_cli status
    python -m kalmido.admin.orgcrypt_cli encrypt-all
    python -m kalmido.admin.orgcrypt_cli decrypt-all            # the way back before a downgrade (sets org_encrypt=0)
    python -m kalmido.admin.orgcrypt_cli decrypt-private        # 2.64.0 (#1864): only the private spaces' files plain again
    python -m kalmido.admin.orgcrypt_cli encrypt-private        #   (private_encrypt=0) / sealed again (private_encrypt=1)
    python -m kalmido.admin.orgcrypt_cli decrypt-wiki           # 2.123.0 A (#2105): the knowledge pages' texts plain again
    python -m kalmido.admin.orgcrypt_cli encrypt-wiki           #   (wiki_encrypt=0, before running 2.122 or older) / sealed again
    python -m kalmido.admin.orgcrypt_cli docs-to-server-key     # 2.126.0 A (#1970): the private documents' values on the
    python -m kalmido.admin.orgcrypt_cli docs-to-account-key    #   server-derived key (before running 2.125 or older) / back
    python -m kalmido.admin.orgcrypt_cli reindex-private        # 2.138.4 C (#2382): after a new server key: the private
                                                                #   documents' word index again, unreadable previews made again
    python -m kalmido.admin.orgcrypt_cli rewrap-accounts --old-key-file FILE   # 2.64.0: account keys after a new server key
        (FILE "-" = stdin: the earlier KALMIDO_SECRET_KEY, base64; never as an argument)
    python -m kalmido.admin.orgcrypt_cli rewrap --org N --recovery-file FILE [--force]   (FILE "-" = stdin; never as an argument;
        the key is tested on the organisation's encrypted data first, --force only when there is none)
    python -m kalmido.admin.orgcrypt_cli rotate --org N [--recovery-out FILE]   # 2.138.0 C (#1972): a new key for the organisation
    python -m kalmido.admin.orgcrypt_cli recovery --org N [--new] [--recovery-out FILE]   # 2.138.0 C: show / renew its recovery key
        (the recovery key goes to stdout or into a new file with mode 0600, never into the log)

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

from ..core.config import ATT_DIR, OFFICE_DIR, app, SECRET_KEY
from ..core.pg import system_ctx, write_lock
from ..core import orgcrypt as oc
from ..core.env import env_bool
from ..core.db import connect, gset, gsetting, iso, now_utc  # 2.149.0 G (#2517): pulled up from functions

# `python -m kalmido.admin.orgcrypt_cli` finds this module already loaded by the package (kalmido/__init__.py ORDER):
# harmless here (no routes, nothing at import time), so runpy's warning about it is not shown
warnings.filterwarnings("ignore", message=r".*kalmido\.admin\.orgcrypt_cli.*found in sys\.modules", category=RuntimeWarning)
TAG = "orgcrypt:"
BATCH = 200

# (table, id column, column, kind): text = the whole column, log = office log detail (only entries with protected keys),
# json = protected keys inside a JSON column (orgcrypt.JSON_KEYS)
# 2.148.1 C (#2481): derived from oc.FIELDS / oc.JSON_KEYS (every protected table, a test compares them); the household
# budget (sid, bud_settle) and the knowledge pages (wkh_settle) have their own passes; tables with one row per organisation
# use org_id as their id column
FIELD_SETTLED = ("budget_", "wiki_")
FIELD_ORG_ROWS = ("office_company", "office_settings", "office_cf_start")
FIELD_JOBS = [(t, "org_id" if t in FIELD_ORG_ROWS else "id", col, "log" if (t, col) == ("office_doc_log", "detail") else "text")
              for t, cols in oc.FIELDS.items() if not t.startswith(FIELD_SETTLED) for col in cols] + [
    (t, "org_id" if t in FIELD_ORG_ROWS else "id", col, "json") for (t, col) in oc.JSON_KEYS]
# 2.126.0 A (#1971): (table, id column, column, sealing context) of the documents' values: sealed per workspace (column ws)
# by docs/store.py doc_seal, the organisation's key or the person's own key
DOC_JOBS = [("doc_meta", "node_id", col, f"doc_meta.{col}") for col in ("text", "amount", "suggest", "trained", "extracted", "summary")] + [  # 2.138.0: + summary (2.126.1 #2123)
    ("doc_senders", "id", "name", "doc_senders.name"),
    ("doc_rules", "id", "data", "doc_rules.data"),
    ("doc_models", "id", "data", "doc_models.data"),
    ("rc_suggest", "id", "note", "rc_suggest.note"),
    ("rc_suggest", "id", "amount", "rc_suggest.amount"),
    ("rc_suggest", "id", "prev_amount", "rc_suggest.prev_amount"),
    ("pl_uploads", "id", "info", "pl_uploads.info"),
    ("pl_uploads", "id", "mapping", "pl_sources.mapping"),  # the upload's mapping is sealed like the source's
    ("pl_sources", "id", "mapping", "pl_sources.mapping"),
    ("file_text", "id", "text", "file_text.text"),
    ("doc_field_values", "id", "value", "doc_field_values.value"),  # 2.153.0 (#2179): custom field values (docs/fields.py)
]


from ..core.db import now_iso as _now  # noqa: E402  2.149.0 G (#2517): was an own copy


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
                if enc:  # 2.148.1 G (#2481): sealed / empty values need no pass (every start runs this)
                    sql += f" AND {col} IS NOT NULL AND CAST({col} AS TEXT) NOT LIKE '{oc.PREFIX}%'"  # pg-ok: the prefix has no case
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
                         "UNION ALL SELECT path FROM wiki_files WHERE org_id=? "  # 2.99.0 A (#2182): files of knowledge pages
                         "UNION ALL SELECT path FROM sheet_files WHERE org_id=? "  # 2.124.0 B (#2110): files of table cells
                         "UNION ALL SELECT path FROM tchat_files WHERE org_id=? "  # 2.113.1 (#2059): team chat files sealed for it
                         "UNION ALL SELECT f.path FROM tchat_files f JOIN tchat_rooms r ON r.id=f.room_id JOIN lists l ON l.id=r.list_id "
                         "WHERE r.kind='list' AND l.org_id=?",  # and those of its lists' channels
                         (oid, oid, oid, oid, oid, oid, oid)).fetchall()
    return [os.path.join(ATT_DIR, r[0]) for r in rows if r[0]] + _office_files(oid) + list(f8f_icon_files(c, oid))


def all_files(c):
    """Every stored attachment / project file / office file of the instance (for decrypt-all and the key deletion).
    2.64.0 (#1864): also the file store's versions and the chat files."""
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        rows = c.execute("SELECT path FROM attachments UNION ALL SELECT path FROM list_files UNION ALL SELECT path FROM fs_versions "
                         "UNION ALL SELECT path FROM chat_files UNION ALL SELECT path FROM budget_files "  # 2.72.0 (#1333)
                         "UNION ALL SELECT path FROM wiki_files "  # 2.99.0 A (#2182)
                         "UNION ALL SELECT path FROM sheet_files "  # 2.124.0 B (#2110)
                         "UNION ALL SELECT path FROM tchat_files").fetchall()  # 2.113.1 (#2059): team chat files
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
    # 2.113.1 (#2059): team chat files (org_id = the organisation of the conversation, else the uploader's account; a list
    # channel's file: its list's space now)
    ("tchat_files", "f.id", "SELECT f.id AS rid, f.path, CASE WHEN l.id IS NULL THEN f.org_id ELSE l.org_id END AS org_id, "
                            "CASE WHEN l.id IS NULL THEN f.user_id ELSE l.owner_id END AS owner_id FROM tchat_files f "
                            "JOIN tchat_rooms r ON r.id=f.room_id LEFT JOIN lists l ON l.id=r.list_id AND r.kind='list' WHERE f.path<>''", "r.list_id"),
    # 2.72.0 (#1333): the receipts of the household budget
    ("budget_files", "f.id", "SELECT f.id AS rid, f.path, l.org_id, l.owner_id FROM budget_files f JOIN lists l ON l.id=f.list_id "
                             "WHERE f.path<>''", "f.list_id"),
    # 2.99.0 A (#2182): files of knowledge pages (the space of their page)
    ("wiki_files", "f.id", "SELECT f.id AS rid, f.path, f.org_id, f.owner_id FROM wiki_files f WHERE f.path<>''", None),
    # 2.124.0 B (#2110): files of table cells (the space of their sheet)
    ("sheet_files", "f.id", "SELECT f.id AS rid, f.path, s.org_id, s.owner_id FROM sheet_files f JOIN sheets s ON s.id=f.sheet_id "
                            "WHERE f.path<>''", None),
    # 2.83.0 (#1427): the lists' own header pictures (lists/listhead.py o3c_head_rel) move with their list
    ("lists", "l.id", "SELECT l.id AS rid, 'listheads/l' || l.id || '-' || l.header_file || '.jpg' AS path, l.org_id, l.owner_id "
                      "FROM lists l WHERE l.header_file<>''", "l.id"),
)


def _bud():
    """2.72.0 (#1333): life/budget.py (imported late: this module is also a command line tool)."""
    from ..life import budget
    return budget


def _wkh():
    """2.123.0 A (#2105): wiki/wkhist.py (imported late, like _bud)."""
    from ..wiki import wkhist
    return wkhist


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


# ---- 2.126.0 A (#1971): the documents' values -------------------------------------------------------------------------
def _ds():
    from ..docs import store
    return store


def docs_pass(c, enc, stop=None):
    """Seal (enc) every plain document value with its workspace's key, or open every sealed one (decrypt-all). Compare and
    set, batches with a commit each. -> {"changed": n, "failed": n} (a value that cannot be opened stays as it is)."""
    S = _ds()
    out = {"changed": 0, "failed": 0}
    if enc and not oc.oc_active(c):
        return out
    for table, idc, col, ctx in DOC_JOBS:
        last = None
        while True:
            if stop and stop():
                return out
            with system_ctx(c):  # orgcrypt: server-side bulk work over every workspace, never content handed to a person
                write_lock(c, "orgcrypt")
                sql = f"SELECT {idc} AS rid, ws, {col} AS v FROM {table} WHERE {col}<>'' AND left({col}, 6)" + ("<>?" if enc else "=?")
                args = [oc.PREFIX]
                if last is not None:
                    sql += f" AND {idc} > ?"
                    args.append(last)
                rows = c.execute(sql + f" ORDER BY {idc} LIMIT {BATCH}", args).fetchall()
                for r in rows:
                    if enc:
                        new = S.doc_seal(c, r["ws"], ctx, r["v"])
                    else:
                        new = S.doc_open(c, r["ws"], ctx, r["v"], default=None)
                        if new is None:
                            out["failed"] += 1
                            continue
                    if new != r["v"]:
                        out["changed"] += c.execute(f"UPDATE {table} SET {col}=? WHERE {idc}=? AND {col}=?", (new, r["rid"], r["v"])).rowcount
            c.commit()
            if len(rows) < BATCH:
                break
            last = rows[-1]["rid"]
    return out


def docs_settle(c, account, stop=None):
    """2.126.0 A (#1970): the sealed values of the persons' own documents (workspaces u<id>) into one form: account=True
    the person's account key (the start-up pass, docs-to-account-key), False the key derived from the server key (the way
    back for an older version, docs-to-server-key). Compare and set, batches with a commit each. -> {"changed", "failed"}."""
    S = _ds()
    out = {"changed": 0, "failed": 0}
    for table, idc, col, ctx in DOC_JOBS:
        last = None
        while True:
            if stop and stop():
                return out
            with system_ctx(c):  # orgcrypt: server-side bulk work over the private workspaces, never content handed to a person
                write_lock(c, "orgcrypt")
                sql = f"SELECT {idc} AS rid, ws, {col} AS v FROM {table} WHERE ws LIKE 'u%' AND left({col}, 6)=?"  # pg-ok: ws prefix u is case-exact
                args = [oc.PREFIX]
                if last is not None:
                    sql += f" AND {idc} > ?"
                    args.append(last)
                rows = c.execute(sql + f" ORDER BY {idc} LIMIT {BATCH}", args).fetchall()
                for r in rows:
                    try:
                        plain, is_acct = S.doc_open_as(c, r["ws"], ctx, r["v"])
                    except oc.OrgCryptError:
                        out["failed"] += 1
                        continue
                    if is_acct == account or (account and S._acct_key(c, r["ws"], True) is None):
                        continue
                    new = S.doc_seal_as(c, r["ws"], ctx, plain, account)
                    out["changed"] += c.execute(f"UPDATE {table} SET {col}=? WHERE {idc}=? AND {col}=?", (new, r["rid"], r["v"])).rowcount
            c.commit()
            if len(rows) < BATCH:
                break
            last = rows[-1]["rid"]
    return out


def docs_settle_once(c, stop=None):
    """2.126.0 A (#1970): the start-up pass moves the persons' document values to their account keys once (setting
    docs_account_key_at notes a finished pass; docs-to-server-key / docs-to-account-key clear it)."""
    S = _ds()
    with system_ctx(c):  # orgcrypt: instance settings, no content
        done = c.execute("SELECT 1 FROM settings WHERE key='docs_account_key_at'").fetchone()
    if done or not S.docs_ukey_on(c):
        return {"changed": 0, "failed": 0}
    t = docs_settle(c, True, stop)
    if not (stop and stop()):
        with system_ctx(c):  # orgcrypt: an instance setting
            gset(c, "docs_account_key_at", _now())
        c.commit()
    return t


def docs_switch(c, account):
    """2.126.0 A (#1970): docs-to-account-key / docs-to-server-key -- the switch first (a running server seals new values
    in that form from now on), then the pass. -> counts plus what is left in the other form."""
    with system_ctx(c):  # orgcrypt: instance settings
        gset(c, "docs_account_key", "1" if account else "0")
        c.execute("DELETE FROM settings WHERE key='docs_account_key_at'")
    c.commit()
    t = docs_settle(c, account)
    if account and not t["failed"]:
        with system_ctx(c):  # orgcrypt: an instance setting
            gset(c, "docs_account_key_at", _now())
        c.commit()
    f = docs_forms(c)
    return {**t, "left": f["server_key"] if account else f["account_key"]}


def docs_forms(c):
    """2.126.0 A (#1970): {"account_key": n, "server_key": n, "unreadable": n} over the sealed values of the persons' own
    documents (status)."""
    S = _ds()
    out = {"account_key": 0, "server_key": 0, "unreadable": 0}
    for table, idc, col, ctx in DOC_JOBS:
        with system_ctx(c):  # orgcrypt: counts only (each value is opened, never shown)
            rows = c.execute(f"SELECT ws, {col} AS v FROM {table} WHERE ws LIKE 'u%' AND left({col}, 6)=?", (oc.PREFIX,)).fetchall()  # pg-ok: ws prefix u is case-exact
        for r in rows:
            try:
                out["account_key" if S.doc_open_as(c, r["ws"], ctx, r["v"])[1] else "server_key"] += 1
            except oc.OrgCryptError:
                out["unreadable"] += 1
    return out


# 2.138.4 C (#2382): what stays on the server key in the private spaces: the Paperless token (pl_sources.token, also an
# organisation's) and the word index / previews of private documents. After a new server key (and rewrap-accounts) the
# token has to be entered again (counted here, the settings say so) and reindex-private rebuilds the index with the new key.
DOCS_INDEX_MARK = "docs_private_index_key"  # settings: a fingerprint of the server key the private index was last built with


def _index_mark():
    import hashlib
    import hmac
    return hmac.new(SECRET_KEY, b"kalmido-docs-index-mark-v1", hashlib.sha256).hexdigest()[:16] if SECRET_KEY else ""


def pl_tokens(c):
    """{"ok": n, "unreadable": n} over the stored Paperless tokens (status; each is opened, never shown)."""
    from ..paperless.ngx import pl_token_lost
    out = {"ok": 0, "unreadable": 0}
    with system_ctx(c):  # orgcrypt: counts only
        for r in c.execute("SELECT id, ws, token FROM pl_sources WHERE COALESCE(token, '')<>''").fetchall():
            out["unreadable" if pl_token_lost(c, r) else "ok"] += 1
    return out


def reindex_private(c, stop=None):
    """The word index of every private document again with the current server key, and the previews that no longer open
    removed so the preview catch-up (docs/thumbfill.py) makes them again. Texts, labels and files stay. Batches with a
    commit each. -> {"indexed": n, "previews": n, "failed": n}."""
    import json as _json
    from ..docs.thumbfill import FILL_KEY
    S = _ds()
    out = {"indexed": 0, "previews": 0, "failed": 0}
    last = 0
    while True:
        if stop and stop():
            return out
        with system_ctx(c):  # orgcrypt: server-side bulk work over the private workspaces, never content handed to a person
            rows = c.execute("SELECT d.*, n.name AS n_name FROM doc_meta d JOIN fs_nodes n ON n.id=d.node_id "
                             "WHERE d.ws LIKE 'u%' AND d.node_id > ? ORDER BY d.node_id LIMIT ?", (last, BATCH)).fetchall()  # pg-ok: ws prefix u is case-exact
            for m in rows:
                txt = S.meta_text(c, m)
                if m["text"] and not txt:  # the text itself does not open (an account key not rewrapped): keep the old index
                    out["failed"] += 1
                    continue
                try:
                    with c.savepoint():  # one broken document never stops the run
                        S.doc_index(c, m["node_id"], m["ws"], S.index_text(c, dict(m), m["n_name"], txt))
                        out["indexed"] += 1
                        if m["thumb"]:
                            try:
                                S.thumb_read(c, m["ws"], os.path.join(ATT_DIR, m["thumb"]))
                            except OSError:
                                S.thumb_drop(m["thumb"])
                                c.execute("UPDATE doc_meta SET thumb='' WHERE node_id=?", (m["node_id"],))
                                out["previews"] += 1
                except Exception:  # noqa: BLE001 -- counted; the document keeps its old index
                    out["failed"] += 1
            if len(rows) < BATCH:
                gset(c, DOCS_INDEX_MARK, _index_mark())
                if out["previews"]:
                    gset(c, FILL_KEY, _json.dumps({}))  # the catch-up runs once more over the documents without a preview
        c.commit()
        if len(rows) < BATCH:
            return out
        last = rows[-1]["node_id"]


def docs_count(c):
    """{"enc": n, "plain": n} over the documents' values of every workspace (status)."""
    out = {"enc": 0, "plain": 0}
    with system_ctx(c):  # orgcrypt: counts only
        for table, idc, col, ctx in DOC_JOBS:
            for r in c.execute(f"SELECT left({col}::text, 6) AS p, COUNT(*) AS n FROM {table} WHERE {col}::text<>'' "
                                 f"GROUP BY left({col}::text, 6)"):
                out["enc" if r["p"] == oc.PREFIX else "plain"] += int(r["n"])
    return out


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
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        gset(c, "private_encrypt", "0")
        c.execute("UPDATE user_keys SET migrated_at=NULL")
    c.commit()
    st = {}
    _bud().bud_settle(c, plain=lambda sid: sid < 0)  # 2.72.0 (#1333): budgets of private spaces plain again
    _wkh().wkh_settle(c, plain=lambda sid: sid < 0)  # 2.123.0 A (#2105): texts of private knowledge pages plain again
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
    tot["fields"] += _wkh().wkh_settle(c, stop=stop)["changed"]  # 2.123.0 A (#2105): the knowledge pages' texts and history
    tot["fields"] += docs_pass(c, True, stop)["changed"]  # 2.126.0 A (#1971): the documents' values
    tot["fields"] += docs_settle_once(c, stop)["changed"]  # 2.126.0 A (#1970): private ones on the account keys
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
    tot["fields"] += _wkh().wkh_settle(c, plain=lambda sid: True)["changed"]  # 2.123.0 A (#2105): the knowledge pages plain again
    d = docs_pass(c, False)  # 2.126.0 A (#1971): the documents' values plain again
    tot["fields"] += d["changed"]
    tot["failed"] += d["failed"]
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
    out["wiki_encrypt"], out["wiki"] = _wkh().wkh_switch(c), _wkh().wkh_count(c)  # 2.123.0 A (#2105)
    out["docs"] = docs_count(c)  # 2.126.0 A (#1971): the documents' values of every workspace
    out["docs_account_key"] = _ds().docs_ukey_on(c)  # 2.126.0 A (#1970)
    out["docs"]["private"] = docs_forms(c)
    with system_ctx(c):  # 2.138.4 C (#2382): an instance setting
        mk = gsetting(c, DOCS_INDEX_MARK) or ""
    out["docs"]["private_index"] = "unknown" if not mk else "current" if mk == _index_mark() else "other_server_key"
    out["paperless_tokens"] = pl_tokens(c)
    for oid in _org_ids(c):
        st = oc.oc_status(c, oid)
        out["orgs"].append({"org": oid, "has_key": st["has_key"], "key_ok": st["key_ok"], "migrated_at": st["migrated_at"],
                            "fields": fields_count(c, oid), "files": files_count(c, oid),
                            "recovery": st["recovery"], "rotating": st["rotating"], "rotated_at": st["rotated_at"]})  # 2.138.0 C (#1972)
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
    # 2.148.1 C (#2487): only files that live on in another space; the organisation's own ones are never opened (they go
    # with it and stay sealed with the dropped key)
    return files_decrypt(c, [p for p, t in att.items() if t != oid], only_org=oid, reseal=target)


# ---- start-up thread --------------------------------------------------------------------------------------------------
_RUN = threading.Lock()
_AGAIN = threading.Event()  # a kick while a pass runs: one more pass afterwards (that pass may be past the organisation)


def oc_migrate_once():
    """One encrypting pass over every organisation (when active). Safe to run any time; returns counts or None."""
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
    if oc.oc_enabled() and env_bool("TASKS_WATCHDOG", True):
        oc_migrate_start()


def oc_settle_lists(list_ids):
    """2.64.0 (#1864): one pass over the files of these lists (tasks moved between spaces, a list moved into / out of an
    organisation or handed to another owner): each sealed for its space now. Never raises."""
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
    if not ids or not oc.oc_enabled() or not env_bool("TASKS_WATCHDOG", True):
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


# ---- 2.138.0 C (#1972): rotate -- a new key for one organisation, everything of it re-encrypted ------------------------
# Every place that holds values sealed with an organisation's key: FIELDS (+ JSON_KEYS, cost_enc) with the row's org_id
# (the household budget: sid), the values of the documents / paperless / newsletter areas sealed per workspace ("o<id>",
# docs/store.py doc_seal: ctx "<table.column>|<ws>"), the stored files (header = org id; paperless upload parts with their
# own ctx) and the task vectors (dropped, the worker computes them again). New places that seal with an org key belong here.
ROT_WS = (("doc_rules", "id", "data", "doc_rules.data"), ("doc_models", "id", "data", "doc_models.data"),
          ("doc_senders", "id", "name", "doc_senders.name"), ("rc_suggest", "id", "note", "rc_suggest.note"),
          ("doc_meta", "node_id", "text", "doc_meta.text"), ("doc_meta", "node_id", "amount", "doc_meta.amount"),
          ("doc_meta", "node_id", "suggest", "doc_meta.suggest"), ("file_text", "id", "text", "file_text.text"),
          ("pl_sources", "id", "mapping", "pl_sources.mapping"), ("pl_sources", "id", "token", ("pl_sources.token.v2", "pl_sources.token")),
          ("pl_uploads", "id", "info", "pl_uploads.info"), ("nl_conns", "id", "secret", "nl_conns.secret.v1"),
          # 2.138.0 C (#1972): sealed per workspace since 2.97 (receipt recognition / suggestions) or missed before (trained)
          ("doc_meta", "node_id", "trained", "doc_meta.trained"), ("doc_meta", "node_id", "extracted", "doc_meta.extracted"),
          ("rc_suggest", "id", "amount", "rc_suggest.amount"), ("rc_suggest", "id", "prev_amount", "rc_suggest.prev_amount"),
          ("doc_meta", "node_id", "summary", "doc_meta.summary"),  # 2.138.0 (#1972): document summaries of 2.126.1 (#2123)
          ("pl_uploads", "id", "mapping", "pl_sources.mapping"),  # 2.138.0 (#1972): the mapping chosen for an uploaded export
          ("doc_field_values", "id", "value", "doc_field_values.value"))  # 2.153.0 (#2179): custom field values (docs/fields.py)
ROT_SETTLE = float(os.environ.get("KALMIDO_ORGCRYPT_ROT_SETTLE", "5"))  # seconds after the key switch (requests that hold the old key end)


# 2.138.0 C (#1972): tables with one row per organisation (no id column; office_cf_start since 2.123)
ROT_ORG_ROWS = FIELD_ORG_ROWS  # 2.148.1 C (#2481): one list


def _rot_jobs(oid):
    """(table, id column, column, AAD org column, kind, ctx) of every value the rotation re-encrypts."""
    out = []
    for t, cols in oc.FIELDS.items():
        idc = "org_id" if t in ROT_ORG_ROWS else "id"
        oc_col = "sid" if t.startswith("budget_") else "org_id"
        out += [(t, idc, col, oc_col, "text", f"{t}.{col}") for col in cols]
    out.append(("office_doc_items", "id", "cost_enc", "org_id", "text", "office_doc_items.cost_enc"))
    for (t, col), keys in oc.JSON_KEYS.items():
        out.append((t, "org_id" if t in ROT_ORG_ROWS else "id", col, "org_id", "json", f"{t}.{col}"))
    out += [(t, idc, col, "ws", "ws", ctx) for t, idc, col, ctx in ROT_WS]
    # 2.138.0 C (#1972, review F6): page texts (wiki_pages / wiki_versions .body) come with oc.FIELDS
    return out


def _rot_value(k1, k2, oid, kind, ctx, ws, v, bad):
    if not isinstance(v, str) or oc.PREFIX not in v:
        return v
    try:
        if kind == "json":
            j = json.loads(v)
            if not isinstance(j, dict):
                return v
            changed = False
            for k in oc.JSON_KEYS[tuple(ctx.split(".", 1))]:
                if oc.oc_is_enc(j.get(k)):
                    n = oc.rck_rekey(k1, k2, oid, f"{ctx}.{k}", j[k])
                    changed, j[k] = changed or n != j[k], n
            return json.dumps(j, ensure_ascii=False) if changed else v
        if kind == "ws":  # 2.138.0 C (#1972): a tuple = the column holds values of earlier ctxs too (the current one first)
            *first, last = ctx if isinstance(ctx, tuple) else (ctx,)
            for x in first:
                try:
                    return oc.rck_rekey(k1, k2, oid, f"{x}|{ws}", v)
                except oc.OrgCryptError:
                    pass
            return oc.rck_rekey(k1, k2, oid, f"{last}|{ws}", v)
        return oc.rck_rekey(k1, k2, oid, ctx, v)
    except (oc.OrgCryptError, ValueError):
        bad[0] += 1
        return v


def rot_fields(c, oid, k1, k2, stop=None):
    """Re-encrypt every value of organisation oid from k1 to k2 (compare and set, in batches). -> (changed, unreadable)."""
    n, bad = 0, [0]
    ws = f"o{int(oid)}"
    for table, idc, col, ocol, kind, ctx in _rot_jobs(oid):
        last = None
        while True:
            if stop and stop():
                return n, bad[0]
            with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
                write_lock(c, "orgcrypt")
                sql = f"SELECT {idc} AS rid, {col} AS v FROM {table} WHERE {ocol}=? AND {col} LIKE ?"  # pg-ok: the prefix is case-exact
                args = [ws if kind == "ws" else oid, "%" + oc.PREFIX + "%"]
                if last is not None:
                    sql += f" AND {idc} > ?"
                    args.append(last)
                rows = c.execute(sql + f" ORDER BY {idc} LIMIT {BATCH}", args).fetchall()
                for r in rows:
                    new = _rot_value(k1, k2, oid, kind, ctx, ws, r["v"], bad)
                    if new != r["v"]:
                        n += c.execute(f"UPDATE {table} SET {col}=? WHERE {idc}=? AND {ocol}=? AND {col}=?",
                                       (new, r["rid"], args[0], r["v"])).rowcount
            c.commit()
            if len(rows) < BATCH:
                break
            last = rows[-1]["rid"]
    return n, bad[0]


def _rot_dirs():
    from ..paperless.zipimp import PLH_DIR
    return [d for d in (ATT_DIR, OFFICE_DIR, PLH_DIR) if os.path.isdir(d)]


def rot_files(c, oid, k1, k2, stop=None):
    """Reseal every stored file whose header names organisation oid (all of the data folders, whatever refers to them)
    from k1 to k2. -> (changed, unreadable)."""
    from ..paperless.zipimp import _CTX as PL_CTX
    ctxs = (oc.FILE_CTX, PL_CTX + f"o{int(oid)}".encode())
    n = bad = 0
    for top in _rot_dirs():
        for d, dirs, names in os.walk(top):
            dirs[:] = [x for x in dirs if not os.path.islink(os.path.join(d, x))]
            for name in names:
                if stop and stop():
                    return n, bad
                p = os.path.join(d, name)
                if name.endswith((".tmp", ".part")) or ".oc-" in name or os.path.islink(p):
                    continue
                h = _head(p)
                if not h or h[:len(oc.MAGIC)] != oc.MAGIC or oc.oc_file_org(h) != oid:
                    continue
                try:
                    st = os.stat(p)
                    with open(p, "rb") as f:
                        data = f.read()
                    new = oc.rck_rekey_file(k1, k2, data, ctxs)
                    if new is None:
                        continue
                    def same(p=p, st=st):  # 2.138.0 C (#1972): asked again after the new bytes are written, right before the replace
                        s2 = os.stat(p)
                        return (s2.st_ino, s2.st_mtime_ns, s2.st_size) == (st.st_ino, st.st_mtime_ns, st.st_size)
                    if not same() or not oc.oc_reseal_file(p, new, check=same):
                        continue  # written meanwhile (then with the new key); the next round looks again
                    n += 1
                except oc.OrgCryptError:
                    bad += 1
                except OSError as e:
                    bad += 1
                    print(TAG, "cannot reseal a file:", type(e).__name__, flush=True)
    return n, bad


def rot_indexes(c, oid):
    """2.138.0 C (#1972): the keyed indexes derived from the organisation's key made again with the new one: the word
    indexes of documents, recognised file texts and filed mails (docs/store.py _index_key) and the duplicate check of the
    household budget (life/budget.py bud_dkey). A value that does not open is left out (its row keeps no words). -> rows."""
    from ..docs import store as S
    from ..files.textscan import _index as ft_index
    from ..hub.hubmail import _index as hub_index
    from ..life.budget import bud_dec, bud_dkey
    ws, n = f"o{int(oid)}", 0
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        for m in c.execute("SELECT * FROM doc_meta WHERE ws=? ORDER BY node_id", (ws,)).fetchall():
            node = c.execute("SELECT name FROM fs_nodes WHERE id=?", (m["node_id"],)).fetchone()
            if node:
                S.doc_index(c, m["node_id"], ws, S.index_text(c, dict(m), node["name"], S.meta_text(c, m)))
                n += 1
        for r in c.execute("SELECT id, text FROM file_text WHERE ws=? AND state='found' ORDER BY id", (ws,)).fetchall():
            v = S.doc_open(c, ws, "file_text.text", r["text"], default=None)
            if v is not None:
                ft_index(c, r["id"], ws, v)
                n += 1
        for m in c.execute("SELECT * FROM hub_mails WHERE org_id=? AND ws=? ORDER BY id", (oid, ws)).fetchall():
            try:
                hub_index(c, m["id"], ws, oc.oc_dec_fields(c, oid, "hub_mails", m))
                n += 1
            except oc.OrgCryptError:
                pass
        for r in c.execute("SELECT * FROM budget_entries WHERE sid=? ORDER BY id", (oid,)).fetchall():
            try:
                d = bud_dec(c, "budget_entries", r)
            except oc.OrgCryptError:
                continue
            c.execute("UPDATE budget_entries SET dkey=? WHERE id=?", (bud_dkey(c, d["list_id"], oid, d["day"], d["amount"], d["kind"], d["title"]), r["id"]))
            n += 1
        # 2.138.0 C (#1972): the word index of the knowledge pages (wiki/wksearch.py, keyed per space like the documents)
        from ..wiki.wkhist import wkh_body
        from ..wiki.wksearch import wks_index
        c.execute("DELETE FROM wiki_words WHERE page_id IN (SELECT id FROM wiki_pages WHERE org_id=?)", (oid,))
        for r in c.execute("SELECT id, org_id, owner_id, body, updated_at FROM wiki_pages WHERE org_id=? AND deleted_at IS NULL "
                           "AND left(path, 5)<>'e2e1:' ORDER BY id", (oid,)).fetchall():
            try:
                wks_index(c, r["id"], r["org_id"], r["owner_id"], wkh_body(c, r), r["updated_at"])
                n += 1
            except oc.OrgCryptError:
                pass  # no words: the next search indexes it again (wks_catch_up)
    c.commit()
    return n


def rotate_org(c, oid, stop=None, rounds=3, force=False):
    """orgcrypt_cli rotate --org N: a new key K2 for organisation oid; every value / file re-encrypted from K1 to K2, the
    task vectors dropped; while it runs the server reads with K2 and falls back to K1 (core/orgcrypt.py _ROT). Restartable
    after an abort (the row keeps K1 in wrapped_rot until the end). One run at a time (a session lock). -> counts and the
    new recovery secret (key "secret", 32 bytes: the caller shows it, never logs it); finished False when K1 must stay:
    still changing, or values / files that open with neither key (force: finish anyway, they stay unreadable)."""
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        got = c.execute("SELECT pg_try_advisory_lock(hashtext(?))", ("orgcrypt-rotate",)).fetchone()[0]
    c.commit()
    if not got:
        raise oc.OrgCryptError("a key rotation runs already")
    try:
        k1, k2, started = oc.rck_rot_begin(c, oid)
        if started and ROT_SETTLE > 0:
            time.sleep(ROT_SETTLE)
        out = {"org": oid, "fields": 0, "files": 0, "unreadable": 0, "finished": False, "secret": None}
        empty = 0
        for _ in range(rounds + 1 if rounds else 0):  # (rounds=0: stop right after the key switch)
            nf, bf = rot_fields(c, oid, k1, k2, stop)
            ns, bs = rot_files(c, oid, k1, k2, stop)
            out["fields"] += nf
            out["files"] += ns
            out["unreadable"] = bf + bs
            if stop and stop():
                return out
            if nf or ns:
                empty = 0
                continue
            empty += 1
            # 2.148.1 C (#2481): K1 goes only after two empty rounds with a settle pause between them (a request that
            # still held K1 during the last round has ended and its value is re-encrypted in the second one)
            if empty >= 2 or ROT_SETTLE <= 0:
                break
            time.sleep(ROT_SETTLE)
        else:
            return out  # still changing: K1 stays, the next run continues
        if out["unreadable"] and not force:
            return out  # K1 stays: nothing that might still need it is dropped without the admin's word
        from ..tasks.related import emb_drop_org
        emb_drop_org(c, oid, sealed=True)  # the worker computes the sealed task vectors again with K2
        c.commit()
        out["indexes"] = rot_indexes(c, oid)  # 2.138.0 C (#1972): before K1 goes (a rerun repeats it while K1 stays)
        out["secret"] = oc.rck_rot_finish(c, oid)
        out["finished"] = True
        return out
    finally:
        with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
            c.execute("SELECT pg_advisory_unlock(hashtext(?))", ("orgcrypt-rotate",))
        c.commit()


def rot_announce(c, oid, what):
    """Office log entry + News for the organisation's admins (no person signed in: the command line)."""
    from ..office.ledger import ofx_log
    with app.app_context(), system_ctx(c):  # orgcrypt: the command line writes the organisation's log entry (no person)
        ofx_log(c, oid, "recovery_key", target="org", detail={what: 1})
    oc.rck_tell(c, oid, None, what)
    c.commit()


def _test_switch(name):
    """2.144.5 A (#2387, review F7): a KALMIDO_TEST_* switch counts only in a test run (KALMIDO_TEST_MODE=1 next to it);
    set alone, e.g. left over in a server's .env, it is ignored with a note."""
    if os.environ.get(name) != "1":
        return False
    if os.environ.get("KALMIDO_TEST_MODE") == "1":
        return True
    print(TAG, name, "is ignored: not a test run (KALMIDO_TEST_MODE)", flush=True)
    return False


def _write_secret(path, text):
    """The recovery key into a new file with mode 0600 (never over an existing one)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text + "\n")


# ---- command line -----------------------------------------------------------------------------------------------------
def _read_recovery(src):
    """2.138.0 C (#1972): rck_parse -> ("secret", R) or ("key", the raw org key of the earlier format)."""
    data = sys.stdin.read() if src == "-" else open(src, encoding="utf-8").read()
    return oc.rck_parse(data.strip().splitlines()[0] if data.strip() else "")


def _give_secret(sec, out):
    """The recovery key to stdout, or into the new file out (0600). -> exit code."""
    text = oc.rck_format(sec)
    if not out:
        print(text, flush=True)
        return 0
    try:
        _write_secret(out, text)
    except OSError as e:
        print(TAG, "cannot write the recovery key file:", type(e).__name__, "- an existing file is never overwritten", flush=True)
        return 1
    print(TAG, "recovery key written to the file (mode 0600)", flush=True)
    return 0


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="python -m kalmido.admin.orgcrypt_cli", description="Kalmido: organisation keys (encryption at rest)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="per organisation: key, encrypted / plain fields and files; the documents' values (docs)")
    sub.add_parser("encrypt-all", help="encrypt every organisation's fields and files (org_encrypt=1)")
    sub.add_parser("decrypt-all", help="the way back before a downgrade: everything plain again, org_encrypt=0")
    sub.add_parser("decrypt-private", help="2.64.0: only the private spaces' files plain again, private_encrypt=0")
    sub.add_parser("encrypt-private", help="2.64.0: seal the private spaces' files again, private_encrypt=1")
    sub.add_parser("decrypt-wiki", help="2.123.0: the knowledge pages' texts and history plain again (before 2.122 or older), wiki_encrypt=0")
    sub.add_parser("encrypt-wiki", help="2.123.0: seal the knowledge pages' texts and history again, wiki_encrypt=1")
    sub.add_parser("docs-to-server-key", help="2.126.0: the private documents' values back on the server-derived key (before running 2.125 or older)")
    sub.add_parser("docs-to-account-key", help="2.126.0: the private documents' values on the persons' account keys again")
    sub.add_parser("reindex-private", help="2.138.4: after a new server key: the private documents' word index again, "
                                           "previews that no longer open are made again")
    ra = sub.add_parser("rewrap-accounts", help="2.64.0: store the account keys again with the current server key (needs the earlier one)")
    ra.add_argument("--old-key-file", required=True, help='a file holding the earlier KALMIDO_SECRET_KEY, "-" = stdin')
    rw = sub.add_parser("rewrap", help="store an organisation's key again (new KALMIDO_SECRET_KEY) from its recovery key")
    rw.add_argument("--org", type=int, required=True)
    rw.add_argument("--recovery-file", required=True, help='a file holding the recovery key, "-" = stdin')
    rw.add_argument("--force", action="store_true", help="store it although the organisation has nothing encrypted to test the key on")
    ro = sub.add_parser("rotate", help="2.138.0: a new key for an organisation, its data re-encrypted (restartable), a new recovery key")
    ro.add_argument("--org", type=int, required=True)
    ro.add_argument("--recovery-out", help="write the new recovery key into this new file (mode 0600) instead of stdout")
    ro.add_argument("--force", action="store_true", help="finish although some values / files open with neither key")
    rc_ = sub.add_parser("recovery", help="2.138.0: show (or with --new renew) an organisation's recovery key")
    rc_.add_argument("--org", type=int, required=True)
    rc_.add_argument("--new", action="store_true", help="make a new recovery key (the earlier one stops working)")
    rc_.add_argument("--recovery-out", help="write the recovery key into this new file (mode 0600) instead of stdout")
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
            left += st["docs"]["enc"]  # 2.126.0 A (#1971)
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
        elif a.cmd in ("decrypt-wiki", "encrypt-wiki"):  # 2.123.0 A (#2105): the switch first, then the pass
            from ..core.db import gset
            on = a.cmd == "encrypt-wiki"
            with system_ctx(c):  # orgcrypt: an instance setting
                gset(c, "wiki_encrypt", "1" if on else "0")
            c.commit()
            t = _wkh().wkh_settle(c, plain=None if on else (lambda sid: True))
            left = _wkh().wkh_count(c)
            print(TAG, a.cmd + ":", json.dumps({**t, **left}), "(wiki_encrypt is now", "1)" if on else "0)")
            if t["failed"] or (not on and left["sealed"]):
                return 1
        elif a.cmd == "reindex-private":  # 2.138.4 C (#2382)
            t = reindex_private(c)
            print(TAG, "reindex-private:", json.dumps(t))
            if t["failed"]:
                return 1
        elif a.cmd in ("docs-to-server-key", "docs-to-account-key"):  # 2.126.0 A (#1970): the switch first, then the pass
            t = docs_switch(c, a.cmd == "docs-to-account-key")
            print(TAG, a.cmd + ":", json.dumps(t), "(docs_account_key is now", "1)" if a.cmd == "docs-to-account-key" else "0)")
            if t["failed"] or t["left"]:
                return 1
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
            pt = pl_tokens(c)  # 2.138.4 C (#2382): what stays on the server key
            print(TAG, "next: reindex-private (the private documents' search index); Paperless tokens to enter again:", pt["unreadable"])
            if t["other"]:
                return 1
        elif a.cmd == "rewrap":
            try:
                parsed = _read_recovery(a.recovery_file)
            except (OSError, ValueError):
                print(TAG, "rewrap: that is not a recovery key", flush=True)
                return 2
            with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
                if not c.execute("SELECT 1 FROM orgs WHERE id=?", (a.org,)).fetchone():
                    print(TAG, "rewrap: no organisation", a.org)
                    return 2
            # 2.138.0 C (#1972): a recovery key "R2-..." opens the copy of the key in the (restored) database; the earlier
            # format is the key itself and counts only until the organisation's key was rotated
            rr = oc.rck_row(c, a.org)
            if parsed[0] == "key" and rr is not None and (rr["rotated_at"] or rr["wrapped_rot"]):
                print(TAG, "rewrap: the organisation's key was renewed (rotate) - this earlier recovery key no longer counts, nothing changed", flush=True)
                return 1
            try:
                key = oc.rck_resolve(parsed, a.org, rr["recovery_wrapped"] if rr is not None else None)
            except oc.OrgCryptError:
                print(TAG, "rewrap: this recovery key does not open the organisation's key (typo? an earlier one?) - nothing changed", flush=True)
                return 1
            ok = rewrap_probe(c, a.org, key)
            if ok is False:
                print(TAG, "rewrap: this recovery key does not open the organisation's encrypted data (typo?) - nothing changed", flush=True)
                return 1
            if ok is None and not a.force:
                print(TAG, "rewrap: organisation", a.org, "has nothing encrypted to test the key on - check it and repeat with --force", flush=True)
                return 1
            changed = oc.oc_rewrap(c, a.org, key)
            if parsed[0] == "secret":
                oc.rck_keep_secret(c, a.org, parsed[1])  # 2.138.0 C (#1972): showable again under the current server key
            elif changed:
                oc.rck_drop_secret(c, a.org)  # 2.138.0 C (#1972): its copy of R lay under the earlier server key
            c.commit()
            print(TAG, "rewrap: organisation", a.org, "key stored with the current server key" if changed else "key was already usable (unchanged)")
        elif a.cmd == "rotate":
            with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
                if not c.execute("SELECT 1 FROM org_keys WHERE org_id=?", (a.org,)).fetchone():
                    print(TAG, "rotate: organisation", a.org, "has no key", flush=True)
                    return 2
            if a.recovery_out and os.path.exists(a.recovery_out):
                print(TAG, "rotate: the file for the recovery key exists already - nothing changed", flush=True)
                return 2
            print(TAG, "rotate: do not go back to a version before 2.138 until this has finished - it reads the organisation's data only after the end", flush=True)  # 2.138.0 C (#1972, review F5)
            t = rotate_org(c, a.org, force=a.force, rounds=0 if _test_switch("KALMIDO_TEST_ROT_ABORT") else 3)  # tests: stop after the key switch
            sec = t.pop("secret")
            print(TAG, "rotate:", json.dumps(t), flush=True)
            if not t["finished"]:
                print(TAG, "rotate: not finished - run it again (the server reads with both keys meanwhile)" if not t["unreadable"] else
                      "rotate: not finished - some values / files open with neither key; check them, then repeat (--force: finish anyway)", flush=True)
                return 1
            rot_announce(c, a.org, "rotated")
            print(TAG, "rotate: the earlier recovery keys no longer count on this server (older exports / backups stay readable with the "
                  "key of their time). The new recovery key:", flush=True)
            return _give_secret(sec, a.recovery_out)
        elif a.cmd == "recovery":
            if a.recovery_out and os.path.exists(a.recovery_out):
                print(TAG, "recovery: the file exists already - nothing changed", flush=True)
                return 2
            with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
                if not c.execute("SELECT 1 FROM orgs WHERE id=?", (a.org,)).fetchone():
                    print(TAG, "recovery: no organisation", a.org)
                    return 2
            write_lock(c, f"orgkey-recovery-{a.org}")
            try:
                sec, made = oc.rck_secret(c, a.org, new=a.new)
            except oc.RckStale:  # 2.138.0 C (#1972)
                print(TAG, "recovery: the recovery key cannot be shown with the current server key - make a new one with --new "
                      "(the earlier one stops working then), nothing changed", flush=True)
                return 1
            if sec is None:
                print(TAG, "recovery: not possible now (no key, or a rotation is not finished)", flush=True)
                return 1
            with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
                c.execute("UPDATE org_keys SET recovery_shown_at=? WHERE org_id=?", (_now(), a.org))
            c.commit()
            rot_announce(c, a.org, "new" if made else "shown")
            return _give_secret(sec, a.recovery_out)
        return 0
    except oc.OrgCryptError as e:
        print(TAG, "error:", e, flush=True)
        return 1
    finally:
        c.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
