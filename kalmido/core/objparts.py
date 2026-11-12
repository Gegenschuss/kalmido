"""2.610.0 (#4762): the shared core, stage 6b -- the side objects of a project on the core's write layer.

The side objects of a project (custom fields, the people of a task, waiting on, templates, comments, sections and planned
sprints) have no owner_id / rev and their rights are the project's (need_list, need_field, need_template, the comment's
author), so they are no registered kinds of core/objects.py (a registration would open them to shares and folders). Like
the office's rows (office/owrite.py ow_write) they are written through ONE call of the core instead of the pieces each
route had of its own since 2.564 (#4701, versions) and 2.567 (#4707, trash):

  part_write   the write_lock of the object -> the row again under it (gone = 404) -> the area's own check of what the
               client saw (check, e.g. the option list of a field) -> the version check (core/conflict.py ccf_check:
               expect_updated_at against the kind's version, 409 with the current state under the kind's key, e.g.
               "template" / "comment" / "sprint" -- the keys the dialogs read since 2.564 stay) -> the area's writer (apply).
               The caller bumps and commits (as before: a route that answers 400 in apply writes nothing).
  part_merge   a list sent whole against the list the client saw (_prev): the stored one with only this client's additions
               / removals (a person another device added meanwhile stays) -- tasks.people (2.564.0 #4701)
  part_trash / part_restore            a kind whose rows carry deleted_at / deleted_by (templates)
  part_copy / part_copy_take / part_copy_back   a kind kept as a copy in list_part_trash (sections, planned sprints: some
               seventy readers of sections would need a filter for a deleted_at column, lists/parttrash.py); restoring puts
               the row back under its id

The rights stay the area's own (checked before the call, unchanged). Agents never take a part out of the trash (agent=False
of the kind: 404, the way back stays with people, tests/parity_test.py). No history and no undo steps of their own yet:
the rows are deleted for good without the core knowing (field / comment deletes, the trash period), so an obj_history row
of them would outlive them (docs/dev/kern.md, stage 6b).

Interface:
  part_kind(kind, table, *, lock, version=None, key=None, agent=True, live=None)   register (at import of the area's module)
  part_write(c, kind, rid, b, apply=None, *, lock=None, read=None, check=None, public=None) -> (row, apply's result)
  part_merge(have, seen, mine) -> list
  part_trash(c, kind, rid, uid, where=None, args=()) -> deleted_at | None (already in the trash / gone)
  part_restore(c, kind, rid, uid, *, where=None, args=(), lock=None, guard=None) -> (row, guard's answer) (404: not in the trash)
               where / args: an extra condition of the area, always ANDed to id=rid (the row checked = the row written)
  part_copy(c, kind, rid, scope_id, held, uid)                             the copy of the row before the caller deletes it
  part_copy_take(c, kind, rid, uid, need) -> the trash row (404: none / an agent; need(c, scope_id) = the area's right)
  part_copy_back(c, kind, r, lock, fix=None) -> the row inserted again (404: restored meanwhile); the copy goes
  part_insert(c, table, snap)                                              a snapshot as a row (its own columns only)

2.783.0 (#5368, stage 6 of the trash core): the retention of the side objects is the core's run too. part_kind(...,
trash_prune=True) hands the kind's trash to core/writes.py obj_trash_tick / obj_trash_prune (the area's own run goes):
  rows with deleted_at   deleted for good after the trash period; prune = an extra SQL condition of the area (a thread's
                         first message stays while replies point at it), on_prune(c, where, args) -> [paths] = what the area
                         cleans up first (rows without FK; files the core unlinks after the commit)
  copy=True              the kind's copies in list_part_trash (sections, sprints, deleted custom fields, the Undo copies of
                         "Delete all times") are deleted after the period
  part_trash_due(c, kind, cut) -> [ids] / part_trash_purge(c, kind, ids, cut) -> ([paths], n)    used by obj_trash_prune
2.1075.0 (#5496): part_trash_purge reads the ids again under a row lock (still in the trash since before cut?) and returns
the number really deleted -- a row restored between part_trash_due and the delete stays and is not counted."""
import json
import re

from .access import Denied, acx_of, live_sql, trash_sql  # 2.783.0 (#5368): live_sql, trash_sql
from .conflict import ccf_check
from .db import iso, now_utc
from .pg import insert_id, qi, write_lock  # 2.783.0 (#5368): insert_id, qi

PART_KINDS = {}  # kind -> {kind, table, lock, version, key, agent, live, trash_prune, prune, on_prune, copy}
PART_COL = re.compile(r"^[a-z_][a-z0-9_]*$")
PART_TRASH = "list_part_trash"  # the copies of sections / planned sprints (scope = the list), 2.567.0 A (#4707)


def part_kind(kind, table, *, lock, version=None, key=None, agent=True, live=None, trash_prune=False, prune="", on_prune=None,
              copy=False):
    """Register a side object kind. lock: the name of its write lock as a format string over {id} (the name the area's other
    writes use already, e.g. "task-{id}" like tasks/lifecycle.py apply_update); version(row) -> the version the client sends
    back as expect_updated_at (None = the kind has none); key: the key of the current state in a 409; agent=False: agents never
    restore it from the trash; live: the condition of a live row (e.g. live_sql() of core/access.py) - part_write reads the row under the
    lock with it, so a row another device put into the trash meanwhile answers 404 instead of being changed (review 2.610).
    2.783.0 (#5368): trash_prune / prune / on_prune / copy = the core's retention run takes the kind (module docstring)."""
    PART_KINDS[kind] = {"kind": kind, "table": table, "lock": lock, "version": version, "key": key or kind, "agent": agent,
                        "live": live, "trash_prune": bool(trash_prune), "prune": prune or "", "on_prune": on_prune,
                        "copy": bool(copy)}
    return PART_KINDS[kind]


def _kind(kind):
    k = PART_KINDS.get(kind)
    if k is None:
        raise ValueError(f"objparts: kind {kind!r} not registered (part_kind)")
    return k


def _lock(c, k, rid, lock):
    write_lock(c, lock or k["lock"].format(id=int(rid)))


def part_write(c, kind, rid, b, apply=None, *, lock=None, read=None, check=None, public=None):
    """Change side object rid of kind (module docstring). b = the request body; apply(c, row) -> the area's writes (its result
    comes back); read(c, rid) -> the row (default SELECT * of its table; None = 404); check(c, row) = the area's own check of
    what the client saw (raises its Conflict); public(c, row) -> the current state of a 409 (default the row);
    lock = the lock's name when it depends on more than the id (a sprint: the list's sprint lock). apply None: the route writes
    on after the call (still under the lock, the row it got is the checked one). Returns (row, result)."""
    k = _kind(kind)
    _lock(c, k, rid, lock)
    live = f" AND {k['live']}" if k.get("live") else ""
    row = read(c, int(rid)) if read else c.execute(f"SELECT * FROM {k['table']} WHERE id=?{live}", (int(rid),)).fetchone()
    if row is None:
        raise Denied(404)
    if check is not None:
        check(c, row)
    if k["version"] is not None:
        ccf_check(b, k["version"](row), k["key"], lambda: public(c, row) if public else dict(row))
    return row, (apply(c, row) if apply is not None else None)


def part_merge(have, seen, mine):
    """A list sent whole (mine) with the list the client saw (seen) against the stored one (have): unchanged meanwhile -> mine;
    else the stored list without what this client removed, plus what it added (order kept, no doubles)."""
    if set(have) == set(seen):
        return mine
    off, on = set(seen) - set(mine), [x for x in mine if x not in seen]
    return list(dict.fromkeys([x for x in have if x not in off] + on))


# ---------------------------------------------------------------- trash: rows with deleted_at
def _part_where(rid, where, args):
    """Review 2.610 (#4762): the row is always bound to its id; the area's rule (e.g. "user_id=?") only narrows it."""
    return "id=?" + (f" AND ({where})" if where else ""), (int(rid), *tuple(args or ()))


def part_trash(c, kind, rid, uid, where=None, args=()):
    """Into the trash (deleted_at, deleted_by) under the kind's lock; the caller checked the right. Returns the time, None when
    it was in the trash already or is gone."""
    k = _kind(kind)
    _lock(c, k, rid, None)
    ts = iso(now_utc())
    w, a = _part_where(rid, where, args)
    n = c.execute(f"UPDATE {qi(k['table'], (k['table'],))} SET deleted_at=?, deleted_by=? WHERE {w} AND {live_sql()}", (ts, uid, *a)).rowcount
    return ts if n else None


def part_restore(c, kind, rid, uid, *, where=None, args=(), lock=None, guard=None):
    """Out of the trash under the kind's lock: where / args = the area's rule which row the person may take back (e.g. their
    own template), else 404; guard(c, row) = the area's check before (a limit: raises or returns an answer to give instead).
    updated_at is stamped (the next save's version). Returns (row, guard's answer or None)."""
    k = _kind(kind)
    if not k["agent"] and acx_of(c, uid).role == "agent":
        raise Denied(404)
    _lock(c, k, rid, lock)
    w, a = _part_where(rid, where, args)
    row = c.execute(f"SELECT * FROM {k['table']} WHERE {w} AND deleted_at IS NOT NULL", a).fetchone()
    if row is None:
        raise Denied(404)
    if guard is not None:
        stop = guard(c, row)
        if stop is not None:
            return row, stop
    c.execute(f"UPDATE {k['table']} SET deleted_at=NULL, deleted_by=NULL, updated_at=? WHERE id=?", (iso(now_utc()), int(rid)))
    return c.execute(f"SELECT * FROM {k['table']} WHERE id=?", (int(rid),)).fetchone(), None


# ---------------------------------------------------------------- trash: a copy of the row
def part_copy(c, kind, rid, scope_id, held, uid):
    """The copy of row rid of kind (snap = the row as it is, held = what hung on it) before the caller deletes the row, in the
    same transaction. scope_id = the list it belongs to (who may restore it: the area's need on it).
    2.783.0 (#5368): returns the id of the copy (a deleted custom field's trash id)."""
    k = _kind(kind)
    row = c.execute(f"SELECT * FROM {k['table']} WHERE id=?", (int(rid),)).fetchone()
    return insert_id(c, f"INSERT INTO {qi(PART_TRASH, (PART_TRASH,))}(list_id,kind,ref_id,snap,held,deleted_by,deleted_at) VALUES(?,?,?,?,?,?,?)",
                     (scope_id, kind, int(rid), json.dumps(dict(row), ensure_ascii=False, default=str),
                      json.dumps(held, ensure_ascii=False, default=str), uid, iso(now_utc())))


def part_copy_take(c, kind, rid, uid, need):
    """The newest copy of kind / rid that uid may restore: need(c, scope_id) is the area's right on its list (raises);
    agents never (kind agent=False). 404 without a copy."""
    k = _kind(kind)
    if not k["agent"] and acx_of(c, uid).role == "agent":  # core/access.py: the account kind, through its token too
        raise Denied(404)
    r = c.execute(f"SELECT * FROM {PART_TRASH} WHERE kind=? AND ref_id=? ORDER BY id DESC LIMIT 1", (kind, int(rid))).fetchone()
    if not r:
        raise Denied(404)
    need(c, r["list_id"])
    return r


def part_copy_back(c, kind, r, lock, fix=None):
    """Under lock (the area's lock of the list's parts): the copy r of part_copy_take as a row again with its id -- 404 when it
    is back meanwhile (a row with the id, or the copy gone). fix(c, snap) adjusts the snapshot first (a number taken
    meanwhile). The copy is deleted. Returns (snap, held)."""
    k = _kind(kind)
    write_lock(c, lock)
    rid = r["ref_id"]
    if c.execute(f"SELECT 1 FROM {k['table']} WHERE id=?", (rid,)).fetchone() or \
            not c.execute(f"SELECT 1 FROM {PART_TRASH} WHERE id=?", (r["id"],)).fetchone():
        raise Denied(404)  # restored meanwhile
    snap, held = json.loads(r["snap"] or "{}"), json.loads(r["held"] or "{}")
    snap.update(id=rid, list_id=r["list_id"])
    if fix is not None:
        fix(c, snap)
    part_insert(c, k["table"], snap)
    c.execute(f"DELETE FROM {PART_TRASH} WHERE id=?", (r["id"],))
    return snap, held


def part_insert(c, table, snap):
    """A snapshot (a row read before) as a row again: its column names only (a name that is no plain column is skipped)."""
    cols = [x for x in snap if PART_COL.match(x)]
    c.execute(f"INSERT INTO {table}({','.join(cols)}) VALUES({','.join('?' * len(cols))})", [snap[x] for x in cols])


# ---------------------------------------------------------------- 2.783.0 (#5368): the retention of the side objects
def part_trash_due(c, kind, cut):
    """The ids of kind's trash older than cut: rows with deleted_at (its table, the area's prune condition) or its copies
    (list_part_trash rows of the kind). The caller reads under system_ctx (every workspace)."""
    k = _kind(kind)
    if k["copy"]:
        q = f"SELECT id FROM {qi(PART_TRASH, (PART_TRASH,))} WHERE kind=? AND deleted_at<? ORDER BY id"
        return [r[0] for r in c.execute(q, (kind, cut)).fetchall()]
    q = f"SELECT id FROM {qi(k['table'], (k['table'],))} WHERE {trash_sql()} AND deleted_at<?{k['prune']} ORDER BY id"
    return [r[0] for r in c.execute(q, (cut,)).fetchall()]


def part_trash_purge(c, kind, ids, cut):
    """Delete ids of part_trash_due for good: the area's on_prune first (rows without FK; returns file paths for after the
    commit), then the rows (what hangs on them cascades). -> ([paths], number deleted).
    2.1075.0 (#5496): only the ids still in the trash since before cut, read again under a row lock (FOR UPDATE): a restore
    between part_trash_due and here keeps its row (it was deleted all the same before); the number is the rows deleted, not
    the ids handed over (the retention report, ret_report run obj_trash)."""
    k = _kind(kind)
    ids = [int(x) for x in ids]
    if not ids:
        return [], 0
    paths, n = [], 0
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        if k["copy"]:
            n += c.execute(f"DELETE FROM {qi(PART_TRASH, (PART_TRASH,))} WHERE kind=? AND id = ANY(CAST(? AS BIGINT[])) "
                           "AND deleted_at<?", (kind, part, cut)).rowcount
            continue
        t = qi(k["table"], (k["table"],))
        part = [r[0] for r in c.execute(f"SELECT id FROM {t} WHERE id = ANY(CAST(? AS BIGINT[])) AND {trash_sql()} "
                                        f"AND deleted_at<?{k['prune']} ORDER BY id FOR UPDATE", (part, cut)).fetchall()]
        if not part:
            continue
        if k["on_prune"] is not None:
            paths += list(k["on_prune"](c, "id = ANY(CAST(? AS BIGINT[]))", (part,)) or ())
        n += c.execute(f"DELETE FROM {t} WHERE id = ANY(CAST(? AS BIGINT[]))", (part,)).rowcount
    return paths, n
