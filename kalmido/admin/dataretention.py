"""2.152.0 D (#2171 #2173): the daily clean-up of old logs and expired credentials, and the weekly orphan-file sweep
(no routes; the watchdog starts both, see notify/push.py watchdog_tick).

- lgc_tick (kind "logs"): activity, list_activity, fs_log, org_list_log, sheet_changes older than ret_days("logs"), the admin
  alerts and admin sign-in addresses after a year, finished agent jobs after half a year, the journal of deleted accounts
  after the backup period (lgc_journal_cut, 2.312.0 B #3264) -- only while ret_on("logs"), else
  the run just counts (dry run, GET /api/admin/retention). The office logs (office_doc_log, office_drive_log,
  office_archive_log) are never touched here (GoBD). Expired sessions, API tokens, invitations / reset links and agent setup
  codes are no data of a person any more and go without the switch.
- orf_tick (kind "files"): see below.
- ckd_tick (kind "chat", 2.186.0 C #2602): the day limit of the agent chat, daily."""
import os
import time
from datetime import timedelta

from ..core.db import gset, gsetting, iso, iso_ms, now_utc
from ..core.pg import system_ctx
from ..core.retention import ret_days, ret_on, ret_report
from ..core.serializers import unlink_files
from ..team.portal import _PT_EDITS
from .backup import BK_DIR, BK_KEEP_WEEKLY_CAP, bk_parse_name  # 2.312.0 B (#3264)

# 2.239.0 D (#2874): file store nodes that are office records (receipts assigned or not, filed letters, cash book / equipment /
# DATEV receipts, a kept lock): their file log and their versions stay while the node exists (it goes after its period)
DRT_OFFICE_NODES = ("SELECT node_id FROM rc_receipts UNION SELECT node_id FROM office_letter_links "
                    "UNION SELECT node_id FROM office_cash_entries WHERE node_id IS NOT NULL "
                    "UNION SELECT receipt_node_id FROM office_equipment WHERE receipt_node_id IS NOT NULL "
                    "UNION SELECT node_id FROM office_datev_guids WHERE node_id IS NOT NULL "
                    "UNION SELECT node_id FROM doc_meta WHERE kept_until IS NOT NULL")
LGC_RUN = {"at": 0.0}
# (table, time column, extra condition, age in days or None = ret_days("logs"))
LGC_LOGS = (
    ("activity", "created_at", "", None),
    ("list_activity", "created_at", "", None),
    ("fs_log", "at", f"node_id NOT IN ({DRT_OFFICE_NODES})", None),  # 2.239.0 D (#2874): not the office records' log
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


def lgc_portal_keep():
    """2.186.0 C (#2602): the condition that spares, per customer portal ticket, the oldest history row of an edit of the
    description -- the portal's "your text" check (team/portal.py pt_original) reads only whether such a row exists, so
    its answer stays the same after the clean-up."""
    kinds = ",".join("'" + k + "'" for k in _PT_EDITS)  # fixed history kinds, no input
    return ("id NOT IN (SELECT min(a.id) FROM activity a JOIN portal_tickets p ON p.task_id=a.task_id "
            f"WHERE a.kind IN ({kinds}) GROUP BY a.task_id)")


def lgc_expired(c, now):
    """Credentials past their end (no switch). Returns {"what": n}."""
    old = iso(now - timedelta(days=LGC_TOKEN_GRACE_DAYS))
    out = {}
    for name, sql, args in (
            ("sessions", "DELETE FROM sessions WHERE expires_at<?", (iso(now),)),
            # 2.190.0 A (#1991): push subscriptions of sessions that are gone ('' = made before 2.115, unknown session: stay)
            ("push_subs", "DELETE FROM push_subs WHERE session_hash<>'' AND session_hash NOT IN (SELECT token_hash FROM sessions)", ()),
            ("api_tokens", "DELETE FROM api_tokens WHERE expires_at IS NOT NULL AND expires_at<?", (old,)),
            ("invites", "DELETE FROM user_invites WHERE (used_at IS NULL AND expires_at<?) OR (used_at IS NOT NULL AND used_at<?)", (old, old)),
            ("setup_codes", "DELETE FROM agent_setup_codes WHERE expires_at<? OR (used_at IS NOT NULL AND used_at<?)", (old, old)),
            # 2.273.0 F1 (#3042): the move memos of tasks / lists / files (people, tag and file names) once their day for the
            # move back is over (TMM_KEEP_H / FSM_KEEP_H = 24 h; two days to be safe)
            ("move_memos", "DELETE FROM space_moves WHERE kind IN ('task','list','files') AND at<?", (iso(now - timedelta(days=2)),))):
        with c.savepoint():
            out[name] = c.execute(sql, args).rowcount or 0
    return out


def lgc_journal_cut(now):
    """2.312.0 B (#3264): the time before which a row of deleted_accounts (admin/backup.py bkr_*) is no longer needed. The
    journal only deletes again what a restored backup brings back, so a row goes once no backup can hold that account any
    more: older than the longest backup period (BK_KEEP_WEEKLY_CAP weeks) AND older than every backup still in the backup
    folder (the rotation keeps the newest backup per day / week "that has one", so a rare backup can be older; safety
    backups count too). None = the folder cannot be read: nothing goes."""
    cut = now - timedelta(weeks=BK_KEEP_WEEKLY_CAP)
    try:
        names = os.listdir(BK_DIR)
    except FileNotFoundError:
        if os.environ.get("KALMIDO_BACKUP_DIR", "").strip():
            return None  # 2.312.0 (#3264, review): a set backup folder that is missing (mount away) counts as unreadable
        names = []
    except OSError:
        return None
    for n in names:
        p = bk_parse_name(n)
        if p and p["at"] < cut:
            cut = p["at"]
    return iso(cut)


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
            if table == "activity":
                cond = lgc_portal_keep()
            cut = iso(now - timedelta(days=days if days is not None else ret_days("logs")))
            try:
                with c.savepoint():
                    counts[table] = lgc_count_del(c, table, col, cond, cut, kill)
            except Exception as e:  # noqa: BLE001  one table must not stop the others
                print("retention: logs", table, type(e).__name__, flush=True)
        cut = lgc_journal_cut(now)  # 2.312.0 B (#3264)
        if cut:
            try:
                with c.savepoint():
                    counts["deleted_accounts"] = lgc_count_del(c, "deleted_accounts", "at", "", cut, kill)
            except Exception as e:  # noqa: BLE001
                print("retention: logs deleted_accounts", type(e).__name__, flush=True)
        ret_report(c, "logs", counts, kill)
        c.commit()
    return sum(counts.values())


# ---- 2.186.0 C (#2602): the day limit of the agent chat also without a new message ------------------------------------
CKD_RUN = {"at": 0.0}


def ckd_tick(c, force=False):
    """Daily (system context): agent chat messages older than KALMIDO_CHAT_KEEP_DAYS (0 = no day limit) with their files,
    as chat_add does on a new message -- only while ret_on("chat"), else they are counted. Returns the number found."""
    days = ret_days("chat")
    if not days or (not force and time.time() - CKD_RUN["at"] < 86400):
        return 0
    CKD_RUN["at"] = time.time()
    kill = ret_on("chat")
    old = iso_ms(now_utc() - timedelta(days=days))  # the stored form of agent_chat.created_at
    paths = []
    # system context: the day limit holds for every conversation by design and shows no content to anybody
    with system_ctx(c):
        n = c.execute("SELECT count(*) FROM agent_chat WHERE created_at<?", (old,)).fetchone()[0]
        if n and kill:
            paths = [r[0] for r in c.execute("SELECT f.path FROM chat_files f JOIN agent_chat m ON m.id=f.message_id "
                                             "WHERE m.created_at<?", (old,))]
            c.execute("DELETE FROM agent_chat WHERE created_at<?", (old,))
        ret_report(c, "chat", {"messages": n}, kill)
        c.commit()
    if paths:  # the rows are gone for good: now the stored files
        unlink_files(paths)
    return n


# ---- #2173: files without a database row ------------------------------------------------------------------------------
ORF_RUN = {"at": 0.0}
ORF_RETRY_KEY = "unlink_retry"  # gsetting: JSON list of stored paths (relative to ATT_DIR) whose removal failed
ORF_RETRY_MAX = 500
ORF_EVERY = 7 * 86400
# 2.186.0 C (#2602): the sweep remembers its last finish and its progress, so a restart neither starts a new sweep at once
# nor begins a running one from the start; stored paths are checked in batches (one query per column and batch)
ORF_AT_KEY = "orphan_sweep_at"    # gsetting: epoch seconds of the last finished sweep
ORF_POS_KEY = "orphan_sweep_pos"  # gsetting: JSON {"sub": last finished folder, "orphans": n} of a sweep under way
ORF_BATCH = 500
ORF_MIN_AGE_S = 3600  # 2.239.0 D (#2874): an upload younger than this is never an orphan (KALMIDO_ORPHAN_DAYS=0: not before its commit)


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
        "AND data_type='text' AND (column_name='path' OR column_name LIKE '%\\_path')")]  # pg-ok: schema column names are lower case


def orf_known(c, cols, rel):
    return rel in orf_known_set(c, cols, [rel])


def orf_known_set(c, cols, rels):
    """2.186.0 C (#2602): the stored paths among rels that some row names (one query per column and ORF_BATCH paths)."""
    rels = list(dict.fromkeys(rels))
    found = set()
    for i in range(0, len(rels), ORF_BATCH):
        part = rels[i:i + ORF_BATCH]
        for t, col in cols:
            left = [p for p in part if p not in found]
            if not left:
                break
            found.update(r[0] for r in c.execute(
                f'SELECT DISTINCT "{col}" FROM "{t}" WHERE "{col}" IN ({",".join("?" * len(left))})', left))
    return found


def orf_candidates(age_s, after=""):
    """Stored files older than age_s seconds in the two layouts of uploads that always have a row: <task id>/<file>
    (task attachments, chat saves, page files) and chat/<agent>-<user>/<file>. Other folders are left alone on purpose
    (the file store has fsm_orphans_gc, list files / avatars / office files have their own rules). Folders in sorted
    order; after: skip the folders up to and including this one (2.186.0 C #2602: a resumed sweep)."""
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
    for sub in sorted(subs):
        if after and sub <= after:
            continue
        d = os.path.join(root, sub)
        if os.path.islink(d) or not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            full = os.path.join(d, fn)
            if (fn.endswith(".part") or os.path.islink(full) or not os.path.isfile(full) or os.path.getmtime(full) > old
                    or os.path.dirname(os.path.realpath(full)) != os.path.realpath(d)):
                continue
            out.append((os.path.join(sub, fn), full, sub))
    return out


def orf_prune_versions(c, nid=None, kill=None):
    """Versions of a file beyond FS_VERSIONS_KEEP (never the newest). kill=None: only while ret_on("files"). Returns
    (how many, the stored paths of the deleted rows -- or of those that would go in a dry run)."""
    from ..files.store import FS_VERSIONS_KEEP
    kill = ret_on("files") if kill is None else kill
    one = " WHERE node_id=?" if nid is not None else ""
    rows = c.execute(f"SELECT id, path, node_id FROM (SELECT id, path, node_id, row_number() OVER (PARTITION BY node_id ORDER BY no DESC) AS rn "
                     f"FROM fs_versions{one}) v WHERE rn>?", ((nid,) if nid is not None else ()) + (FS_VERSIONS_KEEP,)).fetchall()
    if rows:  # 2.186.0 B (#2600): a booked receipt keeps every version (which one was booked is not known)
        from ..receipts.suggest import olk_fs_locked
        ids = sorted({r["node_id"] for r in rows})
        # 2.239.0 D (#2874): so does every office record (an incoming invoice not booked yet, a filed letter)
        office = set()
        for i in range(0, len(ids), ORF_BATCH):
            part = ids[i:i + ORF_BATCH]
            office.update(x[0] for x in c.execute(f"SELECT node_id FROM ({DRT_OFFICE_NODES}) o WHERE node_id IN ({','.join('?' * len(part))})", part))
        kept = office | {n for n in ids if n not in office and olk_fs_locked(c, n)}
        rows = [r for r in rows if r["node_id"] not in kept]
    if rows and kill:
        c.execute(f"DELETE FROM fs_versions WHERE id IN ({','.join('?' * len(rows))})", [r["id"] for r in rows])
    return len(rows), [r["path"] for r in rows]


def orf_tick(c, force=False):
    """Weekly (system context): stored files without any row, older than ret_days("files") days. Counts while the switch
    is off, removes them (after the check, nothing to commit) while ret_on("files"). Returns the number found."""
    import json
    import os
    from ..core.config import ATT_DIR
    if not force and time.time() - ORF_RUN["at"] < ORF_EVERY:
        return 0
    ORF_RUN["at"] = time.time()
    try:  # 2.186.0 C (#2602): the last finish survives a restart
        last = float(gsetting(c, ORF_AT_KEY) or 0)
    except ValueError:
        last = 0.0
    if not force and time.time() - last < ORF_EVERY:
        ORF_RUN["at"] = last
        return 0
    kill = ret_on("files")
    counts = {"orphans": 0, "retry_failed": 0, "versions": 0}
    # system context: the schema-wide check for a stored path crosses organisations by design (paths only, no content)
    with system_ctx(c):
        try:
            pos = json.loads(gsetting(c, ORF_POS_KEY) or "{}")
        except ValueError:
            pos = {}
        if not isinstance(pos, dict):
            pos = {}
        counts["orphans"] = int(pos.get("orphans") or 0)
        counts["retry_failed"] = orf_retry(c)
        cols = orf_path_columns(c)
        base, found = counts["orphans"], []
        cands = orf_candidates(max(ret_days("files") * 86400, ORF_MIN_AGE_S), str(pos.get("sub") or ""))
        for i in range(0, len(cands), ORF_BATCH):
            part = cands[i:i + ORF_BATCH]
            known = orf_known_set(c, cols, [p[0] for p in part])
            for rel, full, sub in part:
                if rel in known:
                    continue
                counts["orphans"] += 1
                found.append(sub)
                if kill:
                    try:
                        os.remove(full)
                        d = os.path.dirname(full)
                        if not os.listdir(d):
                            os.rmdir(d)
                    except OSError:
                        pass
            # progress: the folders before the last one of this batch are done (the last may go on in the next batch)
            done = [p[2] for p in part if p[2] < part[-1][2]]
            if done and i + ORF_BATCH < len(cands):
                top = max(done)
                gset(c, ORF_POS_KEY, json.dumps({"sub": top, "orphans": base + sum(1 for f in found if f <= top)}))
                c.commit()
        counts["versions"], vpaths = orf_prune_versions(c, None, kill)
        gset(c, ORF_POS_KEY, "")
        gset(c, ORF_AT_KEY, str(int(time.time())))
        ret_report(c, "files", counts, kill)
        c.commit()
        if kill:  # the rows are gone for good: now the stored files
            for p in vpaths:
                try:
                    os.remove(os.path.join(ATT_DIR, p))
                except OSError:
                    pass
    return counts["orphans"] + counts["versions"]


# ---- 2.239.0 D (#2874): office records outlive what they point to ------------------------------------------------------
# (table, column, referenced table, ON DELETE now): a closed month of the logbook stays when its vehicle would go (nothing
# deletes a vehicle on its own; an organisation's deletion still takes both in one statement, NO ACTION checks at its end)
DRT_FK = (("office_drive_closed", "vehicle_id", "office_vehicles", "NO ACTION"),)
DRT_FK_TYPE = {"NO ACTION": "a", "RESTRICT": "r", "CASCADE": "c", "SET NULL": "n"}


def drt_fk_once(c):
    """At the start (core/db.py init, idempotent): the foreign keys of DRT_FK get their new rule. 2.236 runs on with them
    (it never deletes a vehicle). Returns how many changed."""
    n = 0
    for table, col, ref, rule in DRT_FK:
        rows = c.execute("SELECT con.conname, con.confdeltype FROM pg_constraint con JOIN pg_class t ON t.oid=con.conrelid "  # pg-ok: catalog oid (Postgres only)
                         "JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=ANY(con.conkey) "  # pg-ok: catalog oid (Postgres only)
                         "WHERE con.contype='f' AND t.relname=? AND a.attname=? AND t.relnamespace=to_regnamespace(current_schema())",
                         (table, col)).fetchall()
        if not rows or any(r[1] == DRT_FK_TYPE[rule] for r in rows):
            continue
        for r in rows:
            c.execute(f'ALTER TABLE {table} DROP CONSTRAINT "{r[0]}"')
        c.execute(f"ALTER TABLE {table} ADD CONSTRAINT {table}_{col}_fkey FOREIGN KEY ({col}) REFERENCES {ref}(id) ON DELETE {rule}")
        n += 1
    if n:
        print(f"retention (#2874): {n} foreign key(s) keep office records", flush=True)
    return n
