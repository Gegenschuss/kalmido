"""2.924.0 (#5069, stage 7 of the shared core, one-way, decided 07.11.2026): the retirement of an area's old member table
once the shared core alone decides (docs/dev/kern.md). One helper for every area (team chat 7a: collab/tcxcore.py; calendars
and address books 7b), called from the area's start hook (core/objhooks.START, inside core/db.py init_db's one transaction):

  kern_retire(c, tables, left, label, drop=None, alert=None) -> {} | {"left": n} | {"dropped": k, "revoked": m}

- Nothing to do once none of `tables` exists (a fresh database, or done): {} (two catalog reads).
- Under the lock "kalmido-kern5069" (one process of the instance at a time; transaction-scoped, so it holds until init_db
  commits) the state is read again (another process may have dropped meanwhile).
- The start check: `left(c)` counts the old rows the core does not hold (the area's rule: no node, no share of that person on
  it). Not 0: a clear line in the log names the number, nothing is dropped, the tables stay (the next start checks again),
  and alert(n, tables) when given (the area's admin alert, notify/alerts.py aa_now: not only the container's log knows).
- 0: `drop(c)` first when given (the area's triggers / functions), then DROP TABLE of each table, and the rows of obj_revoked
  whose source is one of them (taken back from the old table; nothing restores them without it, no data rubbish).
- After the DROP the database's back limit (kalmido_meta back_floor, core/db.py appver_check "format") is raised to the
  minor of this image (x.y.0): an older image refuses to start instead of running on the dropped tables. Fable review of
  2.924 F1: 2.923 would create tchat_members empty again (schema.py) and its tcx_core_sync would then take every person's
  and agent's share of every room. The minor of the running image, not a fixed line in BACK_LIMITS: the release number is
  set by the train, the package label is not the version.
The fragment core/migrations.d/<task>_x.py carries the documentation and the drop-ok line of each table (a fragment's AFTER
runs before the start hooks and cannot hold the start check).

2.937.0 (#5244, stage 7c): an area whose old table STAYS with fewer rows and columns (tables: sheet_shares keeps the rows of an
address typed in; knowledge: wiki_shares keeps the public links) retires its part with

  kern_retire_rows(c, table, cols, left, label, prune=None, alter=(), alert=None) -> {} | {"left": n} | {"dropped": k, "pruned": m}

- Nothing to do once the table or every one of `cols` is gone (two catalog reads).
- The same lock and start check as kern_retire (`left(c)` not 0: a log line, alert(n, [table]), nothing changes).
- 0: `prune(c)` (deletes the old rows the core holds now; returns their number), then ALTER TABLE ... DROP COLUMN of each of
  `cols` still there, then each statement of `alter` (retyping, a CHECK the rows left must keep), the rows of obj_revoked with
  src = table, and the back limit as above (an older image would read the dropped columns).

kern_retire_due(c, table, cols, typed) -> bool (Fable review of 2.937 F1): whether the start hook has work. "Done" is the
target state (the column `typed` is TIMESTAMPTZ, as schema.py makes it), not the missing `cols`: a database from before the
columns came (a backup from before 2.565 played in, a jump over versions) has neither -- the hook adds `cols` back (nullable
BIGINT, under the lock) and runs as usual (forward copy, start check, drop), instead of losing every share of a person in
silence."""
import re

from .config import APP_VERSION
from .pg import qi, table_columns, table_exists, write_lock

KERN_RETIRE_LOCK = "kalmido-kern5069"
KERN_RETIRE_HOW = ("the shared core dropped the old member tables (team chat, calendars, address books; #5069) and the old share "
                   "rows of tables and knowledge pages (#5244), the old version table of the knowledge pages (#5281) and the version "
                   "columns of the playbooks and the procedure documentation (#5282) - an older version would rebuild them empty or read columns that "
                   "are gone; go back only with a backup from before")


def _kr_ver(v):
    m = re.fullmatch(r"(\d{1,4})\.(\d{1,4})\.(\d{1,4})", str(v or "").strip())
    t = tuple(int(x) for x in m.groups()) if m else None
    return t if t and t != (0, 0, 0) else None


def kern_retire_floor(c, mine=None, how=KERN_RETIRE_HOW):
    """Raise kalmido_meta back_floor to x.y.0 of this image (module docstring), never lower it. "" when nothing changed.
    2.972.0 (#5272 / #5285): how = the reason the start check names (the comments' and following's moves pass their own).
    2.1003.0 (#5718 ff.): the floor stands on this minor already (another step of this image raised it first; since 2.981
    obj_comment_trash's key does on every fresh database, #5274): a reason not in back_floor_how yet is added to it, so the
    start check (core/db.py appver_guard) names every step of this minor, not only the first. A newer floor stays as it is."""
    m = _kr_ver(APP_VERSION if mine is None else mine)
    if not m or not table_exists(c, "kalmido_meta"):
        return ""
    v = f"{m[0]}.{m[1]}.0"
    r = c.execute("SELECT value FROM kalmido_meta WHERE key='back_floor'").fetchone()
    have = _kr_ver(r[0]) if r else None
    if have and have > (m[0], m[1], 0):
        return ""
    if have == (m[0], m[1], 0):
        r = c.execute("SELECT value FROM kalmido_meta WHERE key='back_floor_how'").fetchone()
        old = str((r[0] if r else "") or "").strip()
        if not how or how in old:
            return ""
        how = f"{old}; {how}" if old else how
        c.execute("INSERT INTO kalmido_meta(key,value) VALUES('back_floor_how',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (how,))
        return v
    for k, x in (("back_floor", v), ("back_floor_how", how)):
        c.execute("INSERT INTO kalmido_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, x))
    return v


def kern_retire(c, tables, left, label, drop=None, alert=None, why=None):
    """The start check and DROP of the old member tables `tables` (module docstring). label names the stage in the log;
    why (2.958.0, #5281) = what the log says of rows left instead of "have no share in the shared core" (an old table whose
    rows move into a core table of their own, not into shares: wiki_versions -> obj_versions)."""
    tables = tuple(tables)
    if not any(table_exists(c, t) for t in tables):
        return {}
    write_lock(c, KERN_RETIRE_LOCK)
    have = [t for t in tables if table_exists(c, t)]
    if not have:  # another process dropped them meanwhile
        return {}
    n = left(c)
    if n:
        print(f"{label}: {n} old row(s) of {', '.join(have)} " + (why or "have no share in the shared core -- the table stays, nothing "
              "dropped; give those objects their node / shares (or delete the rows) and start again"), flush=True)
        if alert:
            alert(n, have)
        return {"left": n}
    if drop:
        drop(c)
    for t in have:
        c.execute(f"DROP TABLE IF EXISTS {qi(t, tables)}")  # one-way (the fragment's drop-ok line)
    revoked = c.execute(f"DELETE FROM obj_revoked WHERE src IN ({','.join('?' * len(have))})", tuple(have)).rowcount
    floor = kern_retire_floor(c)
    print(f"{label}: every old row has its share in the shared core -- {', '.join(have)} dropped"
          + (f"; versions before {floor} no longer start on this database" if floor else ""), flush=True)
    return {"dropped": len(have), "revoked": revoked}


def kern_retire_due(c, table, cols, typed):
    """2.937.0 (#5244, Fable F1): True when the old rows of `table` still wait for kern_retire_rows (module docstring); a
    database from before `cols` came gets them back first (empty, nullable BIGINT: every old row counts as not moved yet)."""
    cols = tuple(cols)
    if not table_exists(c, table):
        return False
    if set(cols) & table_columns(c, table):
        return True
    t = c.execute("SELECT data_type FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=? "
                  "AND column_name=?", (table, typed)).fetchone()
    if t is None or t[0] == "timestamp with time zone":
        return False  # done (or a fresh database: schema.py made the target types)
    write_lock(c, KERN_RETIRE_LOCK)
    for x in cols:
        c.execute(f"ALTER TABLE {qi(table, (table,))} ADD COLUMN IF NOT EXISTS {qi(x, cols)} BIGINT")
    print(f"{table}: a database from before the shared core's columns {', '.join(cols)} -- added back, its old rows are copied "
          "forward and checked now (#5244)", flush=True)
    return True


def kern_retire_rows(c, table, cols, left, label, prune=None, alter=(), alert=None, why=None):
    """2.937.0 (#5244): the start check, then the old rows and columns of a table that stays (module docstring). label names
    the stage in the log. alter: fixed statements of the caller (no values of users in them). why (2.977.0, #5282) = what the
    log says of rows left instead of "have no share in the shared core" (old version rows that move into obj_versions)."""
    cols = tuple(cols)
    if not table_exists(c, table) or not set(cols) & table_columns(c, table):
        return {}
    write_lock(c, KERN_RETIRE_LOCK)
    have = [x for x in cols if x in table_columns(c, table)]
    if not have:  # another process did it meanwhile
        return {}
    n = left(c)
    if n:
        print(f"{label}: {n} old row(s) of {table} " + (why or "have no share in the shared core -- nothing dropped; give those objects "
              "their node / shares (or delete the rows) and start again"), flush=True)
        if alert:
            alert(n, [table])
        return {"left": n}
    pruned = (prune(c) or 0) if prune else 0
    for x in have:
        c.execute(f"ALTER TABLE {qi(table, (table,))} DROP COLUMN IF EXISTS {qi(x, have)}")  # one-way (the fragment's drop-ok line)
    for stmt in alter:
        c.execute(stmt)
    c.execute("DELETE FROM obj_revoked WHERE src=?", (table,))
    floor = kern_retire_floor(c)
    print(f"{label}: every old row of {table} has its share in the shared core -- {pruned} row(s) and column(s) {', '.join(have)} "
          "dropped" + (f"; versions before {floor} no longer start on this database" if floor else ""), flush=True)
    return {"dropped": len(have), "pruned": pruned}
