"""2.42.0 (#828): the organisation keys' bulk work -- the start-up run that encrypts existing data (oc_migrate_loop, a
background thread) and the command line for the server admin:

    python -m kalmido.admin.orgcrypt_cli status
    python -m kalmido.admin.orgcrypt_cli encrypt-all
    python -m kalmido.admin.orgcrypt_cli decrypt-all            # the way back before a downgrade (sets org_encrypt=0)
    python -m kalmido.admin.orgcrypt_cli rewrap --org N --recovery-file FILE [--force]   (FILE "-" = stdin; never as an argument;
        the key is tested on the organisation's encrypted data first, --force only when there is none)

Every run is idempotent and restartable: values carry the prefix "kenc1:", files the magic b"KENC1\\n", so a half-done
run simply continues; files are replaced atomically (tmp + os.replace), rows are updated only while they still hold the
value that was read (compare and set), in batches with a commit each. Output: counts only, never a value or a key.
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
        rows = c.execute("SELECT id, icon, org_id FROM lists WHERE icon LIKE 'u:%'" + ("" if oid is None else " AND org_id=?"),
                         () if oid is None else (oid,)).fetchall()
    return {list_icon_path(r[0], r[1][2:]): r[2] for r in rows if re.fullmatch(r"u:[A-Za-z0-9_-]{8,40}", r[1])}


def org_files(c, oid):
    """Every stored file that belongs to organisation oid now: attachments of tasks in its lists (comments included),
    project files of its lists, its office files, the lists' own pictures (2.58.0)."""
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        rows = c.execute("SELECT a.path FROM attachments a JOIN tasks t ON t.id=a.task_id JOIN lists l ON l.id=t.list_id "
                         "WHERE l.org_id=? UNION ALL SELECT f.path FROM list_files f JOIN lists l ON l.id=f.list_id WHERE l.org_id=?",
                         (oid, oid)).fetchall()
    return [os.path.join(ATT_DIR, r[0]) for r in rows if r[0]] + _office_files(oid) + list(f8f_icon_files(c, oid))


def all_files(c):
    """Every stored attachment / project file / office file of the instance (for decrypt-all and the key deletion)."""
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        rows = c.execute("SELECT path FROM attachments UNION ALL SELECT path FROM list_files").fetchall()
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


def files_decrypt(c, paths, only_org=None, reseal=None):
    """Open the sealed files among paths (with the key named in each header; only_org: only files of that organisation).
    reseal(path) -> org id to seal the plain content with instead (None = plain). -> (changed, failed)."""
    n = bad = 0
    keys = {}
    for p in paths:
        h = _head(p)
        if h is None or h[:len(oc.MAGIC)] != oc.MAGIC:
            continue
        hid = oc.oc_file_org(h)
        if only_org is not None and hid != only_org:
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
                data = oc.oc_seal_k(keys[tgt], tgt, data) if keys[tgt] else data
            oc.oc_reseal_file(p, data)
            n += 1
        except (OSError, oc.OrgCryptError) as e:
            bad += 1
            print(TAG, "cannot open a sealed file:", str(e) if isinstance(e, oc.OrgCryptError) else type(e).__name__, flush=True)
    return n, bad


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
    ns, bad = files_encrypt(c, oid, key, org_files(c, oid), stop)
    if not (stop and stop()) and not bad:
        with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
            c.execute("UPDATE org_keys SET migrated_at=? WHERE org_id=?", (_now(), oid))
        c.commit()
    return {"fields": nf, "files": ns, "failed": bad}


def encrypt_all(c, stop=None):
    tot = {"orgs": 0, "fields": 0, "files": 0, "failed": 0}
    for oid in _org_ids(c):
        if stop and stop():
            break
        r = encrypt_org(c, oid, stop)
        tot["orgs"] += 1
        for k in ("fields", "files", "failed"):
            tot[k] += r[k]
    return tot


def decrypt_all(c):
    """The way back: org_encrypt=0 first (nothing new gets encrypted, also not by a running server), then every field and
    file back to plain; migrated_at cleared. -> counts."""
    from ..core.db import gset
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        gset(c, "org_encrypt", "0")
        c.execute("UPDATE org_keys SET migrated_at=NULL")
    c.commit()
    tot = {"orgs": 0, "fields": 0, "files": 0, "failed": 0}
    for oid in _org_ids(c):
        key = oc.oc_key(c, oid, create=False)
        tot["orgs"] += 1
        if key is None:
            continue
        tot["fields"] += fields_pass(c, oid, False, key)
    n, bad = files_decrypt(c, all_files(c))
    tot["files"], tot["failed"] = n, bad
    return tot


def status(c):
    out = {"server_key": oc.oc_enabled(), "org_encrypt": None, "orgs": []}
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        r = c.execute("SELECT value FROM settings WHERE key='org_encrypt'").fetchone()
    out["org_encrypt"] = (r[0] if r else "1") != "0"
    for oid in _org_ids(c):
        st = oc.oc_status(c, oid)
        out["orgs"].append({"org": oid, "has_key": st["has_key"], "key_ok": st["key_ok"], "migrated_at": st["migrated_at"],
                            "fields": fields_count(c, oid), "files": files_count(c, oid)})
    return out


def before_org_delete(c, oid):
    """Called by the organisation's deletion before its key goes: files sealed with this organisation's key that lie in
    lists of another organisation (or private ones) now are sealed with that organisation's key (or stored plain). The
    organisation's own office folder is removed by the caller. -> (changed, failed)."""
    if not oc.oc_enabled():
        return 0, 0
    with system_ctx(c):  # orgcrypt: key rows / server-side bulk work are infrastructure, never content handed to a person
        att = {os.path.join(ATT_DIR, r[0]): r[1] for r in c.execute(
            "SELECT a.path, l.org_id FROM attachments a JOIN tasks t ON t.id=a.task_id JOIN lists l ON l.id=t.list_id WHERE a.path<>''")}
        att.update({os.path.join(ATT_DIR, r[0]): r[1] for r in c.execute(
            "SELECT f.path, l.org_id FROM list_files f JOIN lists l ON l.id=f.list_id WHERE f.path<>''")})
    att.update(f8f_icon_files(c))  # 2.58.0 (#1805): the lists' own pictures
    active = oc.oc_active(c)

    def target(p):
        t = att.get(p)
        return t if (active and t and t != oid) else None
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
        tot = encrypt_all(c, stop=lambda: not oc.oc_active(c))
        if tot["fields"] or tot["files"] or tot["failed"]:
            print(TAG, "encrypted at rest:", tot["fields"], "fields,", tot["files"], "files in", tot["orgs"], "organisations",
                  f"({tot['failed']} files failed)" if tot["failed"] else "", flush=True)
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
            left = sum(o["fields"]["enc"] + o["files"]["enc"] for o in st["orgs"])
            print(TAG, "still encrypted:", left, "(org_encrypt is now 0)")
            if left or t["failed"]:
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
