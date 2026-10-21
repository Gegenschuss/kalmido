"""2.152.0 D (#2171 #2173): the daily clean-up of old logs and expired credentials, and the weekly orphan-file sweep
(no routes; the watchdog starts both, see notify/push.py watchdog_tick).

- lgc_tick (kind "logs"): activity, list_activity, fs_log, org_list_log, sheet_changes older than ret_days("logs"), the admin
  alerts and admin sign-in addresses after a year, finished agent jobs after half a year -- only while ret_on("logs"), else
  the run just counts (dry run, GET /api/admin/retention). The office logs (office_doc_log, office_drive_log,
  office_archive_log) are never touched here (GoBD). Expired sessions, API tokens, invitations / reset links and agent setup
  codes are no data of a person any more and go without the switch.
- orf_tick (kind "files"): see below."""
import time
from datetime import timedelta

from ..core.db import iso, now_utc
from ..core.pg import system_ctx
from ..core.retention import ret_days, ret_on, ret_report

LGC_RUN = {"at": 0.0}
# (table, time column, extra condition, age in days or None = ret_days("logs"))
LGC_LOGS = (
    ("activity", "created_at", "", None),
    ("list_activity", "created_at", "", None),
    ("fs_log", "at", "", None),
    ("org_list_log", "created_at", "", None),
    ("sheet_changes", "created_at", "", None),
    ("admin_alerts", "created_at", "", 365),
    ("admin_login_ips", "last_at", "", 365),
    ("agent_jobs", "updated_at", "state IN ('done','failed','stopped')", 180),
)
LGC_TOKEN_GRACE_DAYS = 30  # an expired API token keeps answering "has expired" for a while before it disappears


def lgc_count_del(c, table, col, cond, cut, kill):
    where = f"{col}<?" + (f" AND {cond}" if cond else "")
    n = c.execute(f"SELECT count(*) FROM {table} WHERE {where}", (cut,)).fetchone()[0]
    if n and kill:
        c.execute(f"DELETE FROM {table} WHERE {where}", (cut,))
    return n


def lgc_expired(c, now):
    """Credentials past their end (no switch). Returns {"what": n}."""
    old = iso(now - timedelta(days=LGC_TOKEN_GRACE_DAYS))
    out = {}
    for name, sql, args in (
            ("sessions", "DELETE FROM sessions WHERE expires_at<?", (iso(now),)),
            ("api_tokens", "DELETE FROM api_tokens WHERE expires_at IS NOT NULL AND expires_at<?", (old,)),
            ("invites", "DELETE FROM user_invites WHERE (used_at IS NULL AND expires_at<?) OR (used_at IS NOT NULL AND used_at<?)", (old, old)),
            ("setup_codes", "DELETE FROM agent_setup_codes WHERE expires_at<? OR (used_at IS NOT NULL AND used_at<?)", (old, old))):
        with c.savepoint():
            out[name] = c.execute(sql, args).rowcount or 0
    return out


def lgc_tick(c, force=False):
    """Daily (system context: the logs of every organisation). Returns the number of rows deleted (or counted)."""
    if not force and time.time() - LGC_RUN["at"] < 86400:
        return 0
    LGC_RUN["at"] = time.time()
    now = now_utc()
    kill = ret_on("logs")
    counts = {}
    # system context: the clean-up works across organisations by design and shows no content to anybody
    with system_ctx(c):
        lgc_expired(c, now)
        for table, col, cond, days in LGC_LOGS:
            cut = iso(now - timedelta(days=days if days is not None else ret_days("logs")))
            try:
                with c.savepoint():
                    counts[table] = lgc_count_del(c, table, col, cond, cut, kill)
            except Exception as e:  # noqa: BLE001  one table must not stop the others
                print("retention: logs", table, type(e).__name__, flush=True)
        ret_report(c, "logs", counts, kill)
        c.commit()
    return sum(counts.values())


# ---- #2173: files without a database row ------------------------------------------------------------------------------
ORF_RUN = {"at": 0.0}
ORF_RETRY_KEY = "unlink_retry"  # gsetting: JSON list of stored paths (relative to ATT_DIR) whose removal failed
ORF_RETRY_MAX = 500
ORF_EVERY = 7 * 86400


def orf_queue(paths):
    """Remember paths unlink_files could not remove (own connection: the caller's transaction is none of our business)."""
    import json
    try:
        from ..core.db import connect, gset, gsetting
        c = connect()
        try:
            try:
                have = json.loads(gsetting(c, ORF_RETRY_KEY) or "[]")
            except ValueError:
                have = []
            have = [p for p in have if isinstance(p, str)]
            for p in paths:
                if p not in have:
                    have.append(p)
            gset(c, ORF_RETRY_KEY, json.dumps(have[-ORF_RETRY_MAX:]))
            c.commit()
        finally:
            c.close()
    except Exception as e:  # noqa: BLE001  the queue is a help, never a reason to fail a delete
        print("retention: unlink queue", type(e).__name__, flush=True)


def orf_retry(c):
    """Tries the queued removals again; returns how many are still failing."""
    import json
    import os
    from ..core.config import ATT_DIR
    from ..core.db import gset, gsetting
    try:
        have = json.loads(gsetting(c, ORF_RETRY_KEY) or "[]")
    except ValueError:
        have = []
    keep = []
    for p in have:
        full = os.path.realpath(os.path.join(ATT_DIR, str(p)))
        if not full.startswith(os.path.realpath(ATT_DIR) + os.sep):
            continue
        try:
            os.remove(full)
        except FileNotFoundError:
            pass
        except OSError:
            keep.append(p)
    if keep != have:
        gset(c, ORF_RETRY_KEY, json.dumps(keep))
    return len(keep)


def orf_path_columns(c):
    """(table, column) of every text column that can name a stored file (path / *_path), read from the schema."""
    return [(r[0], r[1]) for r in c.execute(
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema=current_schema() "
        "AND data_type='text' AND (column_name='path' OR column_name LIKE '%\\_path')")]


def orf_known(c, cols, rel):
    for t, col in cols:
        if c.execute(f'SELECT 1 FROM "{t}" WHERE "{col}"=? LIMIT 1', (rel,)).fetchone():
            return True
    return False


def orf_candidates(age_s):
    """Stored files older than age_s seconds in the two layouts of uploads that always have a row: <task id>/<file>
    (task attachments, chat saves, page files) and chat/<agent>-<user>/<file>. Other folders are left alone on purpose
    (the file store has fsm_orphans_gc, list files / avatars / office files have their own rules)."""
    import os
    from ..core.config import ATT_DIR
    root = os.path.realpath(ATT_DIR)
    old = time.time() - age_s
    out = []
    if not os.path.isdir(root):
        return out
    subs = [d for d in os.listdir(root) if d.isdigit()]
    chat = os.path.join(root, "chat")
    if os.path.isdir(chat) and not os.path.islink(chat):
        subs += [os.path.join("chat", d) for d in os.listdir(chat)]
    for sub in subs:
        d = os.path.join(root, sub)
        if os.path.islink(d) or not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            full = os.path.join(d, fn)
            if (fn.endswith(".part") or os.path.islink(full) or not os.path.isfile(full) or os.path.getmtime(full) > old
                    or os.path.dirname(os.path.realpath(full)) != os.path.realpath(d)):
                continue
            out.append((os.path.join(sub, fn), full))
    return out


def orf_prune_versions(c, nid=None, kill=None):
    """Versions of a file beyond FS_VERSIONS_KEEP (never the newest). kill=None: only while ret_on("files"). Returns
    (how many, the stored paths of the deleted rows -- or of those that would go in a dry run)."""
    from ..files.store import FS_VERSIONS_KEEP
    kill = ret_on("files") if kill is None else kill
    one = " WHERE node_id=?" if nid is not None else ""
    rows = c.execute(f"SELECT id, path FROM (SELECT id, path, row_number() OVER (PARTITION BY node_id ORDER BY no DESC) AS rn "
                     f"FROM fs_versions{one}) v WHERE rn>?", ((nid,) if nid is not None else ()) + (FS_VERSIONS_KEEP,)).fetchall()
    if rows and kill:
        c.execute(f"DELETE FROM fs_versions WHERE id IN ({','.join('?' * len(rows))})", [r["id"] for r in rows])
    return len(rows), [r["path"] for r in rows]


def orf_tick(c, force=False):
    """Weekly (system context): stored files without any row, older than ret_days("files") days. Counts while the switch
    is off, removes them (after the check, nothing to commit) while ret_on("files"). Returns the number found."""
    import os
    from ..core.config import ATT_DIR
    if not force and time.time() - ORF_RUN["at"] < ORF_EVERY:
        return 0
    ORF_RUN["at"] = time.time()
    kill = ret_on("files")
    counts = {"orphans": 0, "retry_failed": 0, "versions": 0}
    # system context: the schema-wide check for a stored path crosses organisations by design (paths only, no content)
    with system_ctx(c):
        counts["retry_failed"] = orf_retry(c)
        cols = orf_path_columns(c)
        for rel, full in orf_candidates(ret_days("files") * 86400):
            if orf_known(c, cols, rel):
                continue
            counts["orphans"] += 1
            if kill:
                try:
                    os.remove(full)
                    d = os.path.dirname(full)
                    if not os.listdir(d):
                        os.rmdir(d)
                except OSError:
                    pass
        counts["versions"], vpaths = orf_prune_versions(c, None, kill)
        ret_report(c, "files", counts, kill)
        c.commit()
        if kill:  # the rows are gone for good: now the stored files
            for p in vpaths:
                try:
                    os.remove(os.path.join(ATT_DIR, p))
                except OSError:
                    pass
    return counts["orphans"] + counts["versions"]
