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
The fragment core/migrations.d/<task>_x.py carries the documentation and the drop-ok line of each table (a fragment's AFTER
runs before the start hooks and cannot hold the start check)."""
from .pg import qi, table_exists, write_lock

KERN_RETIRE_LOCK = "kalmido-kern5069"


def kern_retire(c, tables, left, label, drop=None, alert=None):
    """The start check and DROP of the old member tables `tables` (module docstring). label names the stage in the log."""
    tables = tuple(tables)
    if not any(table_exists(c, t) for t in tables):
        return {}
    write_lock(c, KERN_RETIRE_LOCK)
    have = [t for t in tables if table_exists(c, t)]
    if not have:  # another process dropped them meanwhile
        return {}
    n = left(c)
    if n:
        print(f"{label}: {n} old row(s) of {', '.join(have)} have no share in the shared core -- the table stays, nothing dropped; "
              "give those objects their node / shares (or delete the rows) and start again", flush=True)
        if alert:
            alert(n, have)
        return {"left": n}
    if drop:
        drop(c)
    for t in have:
        c.execute(f"DROP TABLE IF EXISTS {qi(t, tables)}")  # one-way (the fragment's drop-ok line)
    revoked = c.execute(f"DELETE FROM obj_revoked WHERE src IN ({','.join('?' * len(have))})", tuple(have)).rowcount
    print(f"{label}: every old row has its share in the shared core -- {', '.join(have)} dropped", flush=True)
    return {"dropped": len(have), "revoked": revoked}
