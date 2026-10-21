"""2.42.0 (#1376): the delta state -- only the tasks that changed since the client's version v instead of the whole /api/state.

Which tasks changed is recorded by the database itself (robust against every write path: batch, retries, agents, undo, moves,
the watchdog): AFTER triggers on tasks and on every table a task's serialization reads from (tags, list tags, files, comments,
read marks (for their reader only), field values, dependencies, AI usage, code links, people, events, contacts, time) insert the task id into
dl_changes. Tables that decide what a person sees at all (lists, members, sections, fields, list tags, groups, folder
shares) insert a row without a task id: "full". bump() stamps the rows of its transaction (still without a version) with the
new version; rows of a write that bumped before it wrote stay unstamped and count as changed until the next bump stamps them.

GET /api/state/delta?since=<v> -> {full: true} (the client loads /api/state as before) or {v, tasks, gone, progress, counts,
mine_order, mine_hidden, evlinks, tcontacts, timer, time_totals, time_lists}: tasks = the changed tasks the person sees, in the
serialization of /api/state (same query, same visibility); gone = ids the client must drop (deleted, moved into a list it
does not see, no longer visible). Full when the answer is not certain: a scope change since v, since older than what is kept
(or than this server's start), since newer than the server's v (a restore), more than DL_MAX changed tasks, a person who is a
participant somewhere (their visibility hangs on assignments) or a token limited to lists. Rather full too often than stale."""
import json
from datetime import timedelta

from flask import jsonify, request

from ..core.config import app
from ..core.db import db, gset, gsetting, iso, now_utc
from ..accounts.session import me

DL_MAX = 200     # more changed tasks than this: the full state is cheaper
DL_ROWS = 5000  # rows of dl_changes read at most (more: full)
DL_KEEP = 5000   # versions kept in dl_changes (older: full)
DL_CLEAN = 256   # every DL_CLEAN-th version cleans up
DL_DAYS = 7      # versions older than this are dropped at the clean-up too (busy instances: many rows per version)
# table -> the columns holding a task id ("full": a change there may change what a person sees -> the full state)
DL_TABLES = {
    "tasks": ("id",), "task_tags": ("task_id",), "task_list_tags": ("task_id",), "attachments": ("task_id",),
    "comments": ("task_id",), "task_seen": ("task_id",), "task_field_values": ("task_id",),
    "task_deps": ("task_id", "blocker_id"), "agent_usage": ("task_id",), "git_links": ("task_id",), "git_closes": ("task_id",),
    "task_people": ("task_id",), "events": ("task_id",), "contact_tasks": ("task_id",), "time_entries": ("task_id",),
    "task_enc_notes": ("task_id",),  # 2.42.0 (#828): the encrypted note marker of a task
    "task_note_locks": ("task_id",),  # 2.48.0 (#1642): the locked note marker of a task
    "task_links": ("task_id",),  # 2.71.0 B (#1459): the further lists a task is shown in (its "also")
    "lists": "full", "list_members": "full", "sections": "full", "list_fields": "full", "list_tags": "full",
    "group_shares": "full", "group_members": "full", "folder_people": "full",
    "org_members": "full",  # 2.46.0 (#1603): lists seen by the whole organisation follow its members
    "list_keys": "full", "list_key_pending": "full",  # 2.64.1 (#1817): a list key handed out / the waiting list of the lock
}
# one function for all of them; TG_ARGV = the id columns (to_jsonb reads a column by name from any row type)
DL_FN = """CREATE OR REPLACE FUNCTION kalmido_dl_touch() RETURNS trigger LANGUAGE plpgsql AS $fn$
DECLARE k text; o bigint; n bigint; ol bigint; nl bigint; u bigint;
BEGIN
  IF TG_ARGV[0] = 'full' THEN  -- one unstamped "full" row is enough
    IF NOT EXISTS (SELECT 1 FROM dl_changes WHERE ver IS NULL AND task_id IS NULL) THEN INSERT INTO dl_changes(task_id) VALUES (NULL); END IF;
    RETURN NULL;
  END IF;
  FOREACH k IN ARRAY TG_ARGV LOOP
    o := NULL; n := NULL; ol := NULL; nl := NULL; u := NULL;
    IF TG_OP <> 'INSERT' THEN o := (to_jsonb(OLD)->>k)::bigint; END IF;
    IF TG_OP <> 'DELETE' THEN n := (to_jsonb(NEW)->>k)::bigint; END IF;
    IF TG_TABLE_NAME = 'tasks' THEN  -- the list before / after: who may learn that it left
      IF TG_OP <> 'INSERT' THEN ol := OLD.list_id; END IF;
      IF TG_OP <> 'DELETE' THEN nl := NEW.list_id; END IF;
    END IF;
    IF TG_TABLE_NAME = 'task_seen' THEN  -- a read mark changes the task for its reader only
      IF TG_OP <> 'DELETE' THEN u := NEW.user_id; ELSE u := OLD.user_id; END IF;
    END IF;
    IF o IS NOT NULL THEN INSERT INTO dl_changes(task_id, list_id, user_id) VALUES (o, ol, u); END IF;
    IF n IS NOT NULL AND (n IS DISTINCT FROM o OR nl IS DISTINCT FROM ol) THEN INSERT INTO dl_changes(task_id, list_id, user_id) VALUES (n, nl, u); END IF;
  END LOOP;
  RETURN NULL;
END $fn$"""


def dl_setup(c):
    """init_db (every start): the trigger function + triggers (idempotent); changes before this start are not known
    reliably (another version may have written without stamping) -> deltas from before now answer full."""
    c.execute(DL_FN)
    for t, cols in DL_TABLES.items():
        if cols == "full":  # per row (a statement that changes nothing, e.g. a start-up repair, is no change)
            c.execute(f"CREATE OR REPLACE TRIGGER kalmido_dl_{t} AFTER INSERT OR UPDATE OR DELETE ON {t} "
                      "FOR EACH ROW EXECUTE FUNCTION kalmido_dl_touch('full')")
        else:
            args = ", ".join(f"'{x}'" for x in cols)
            c.execute(f"CREATE OR REPLACE TRIGGER kalmido_dl_{t} AFTER INSERT OR UPDATE OR DELETE ON {t} "
                      f"FOR EACH ROW EXECUTE FUNCTION kalmido_dl_touch({args})")
    gset(c, "dl_floor", gsetting(c, "version") or "0")


def dl_stamp(c, v):
    """bump(): the rows of this transaction (and committed ones nobody stamped yet) belong to version v."""
    c.execute("UPDATE dl_changes SET ver=? WHERE ver IS NULL", (v,))
    if v % DL_CLEAN == 0:
        # dl_marks: [[version, time], ...] of the clean-ups (DL_DAYS + a few): versions older than DL_DAYS go as well
        now = now_utc()
        try:
            marks = [m for m in json.loads(gsetting(c, "dl_marks") or "[]") if isinstance(m, list) and len(m) == 2]
        except ValueError:
            marks = []
        cut = v - DL_KEEP
        old = [m for m in marks if m[1] < iso(now - timedelta(days=DL_DAYS))]
        if old:
            cut = max(cut, max(int(m[0]) for m in old))
        marks = [m for m in marks if m[1] >= iso(now - timedelta(days=DL_DAYS + 2))] + [[v, iso(now)]]
        gset(c, "dl_marks", json.dumps(marks[-200:]))
        c.execute("DELETE FROM dl_changes WHERE ver <= ?", (cut,))
        if cut > int(gsetting(c, "dl_floor") or 0):
            gset(c, "dl_floor", cut)


def dl_changed(c, since, uid=None):
    """({task id: {list ids it was / is in}}, full) of the changes after version since (rows of one person: only for uid)."""
    out = {}
    rows = c.execute("SELECT task_id, list_id FROM dl_changes WHERE (ver > ? OR ver IS NULL) AND (user_id IS NULL OR user_id=?) "
                     "GROUP BY task_id, list_id LIMIT ?", (since, uid, DL_ROWS)).fetchall()
    if len(rows) >= DL_ROWS:
        return {}, True
    for r in rows:
        if r[0] is None:
            return {}, True
        out.setdefault(r[0], set()).add(r[1])
    return out, False


@app.get("/api/state/delta")
def state_delta():
    from ..core.access import plists, token_lists, tvis, vis_sql, wr_sql, time_all
    from ..core.serializers import load_tasks
    from ..core.db import usettings
    from ..core.state import ev_links
    from ..lists.projects import list_progress
    from ..tasks.mineorder import mt_mine_hidden, vw_mine_order
    from ..contacts.model import task_contacts
    from ..events.model import events_on
    from ..personal.timetrack import time_list_totals, time_running, time_totals
    c, uid = db(), me()
    v = int(gsetting(c, "version"))  # first: the tasks read below are at least this new (a later change comes again)
    try:
        since = int(request.args.get("since", ""))
    except ValueError:
        return jsonify(full=True, v=v)
    if since > v or since < int(gsetting(c, "dl_floor") or 0) or plists(c, uid) or token_lists() is not None:
        return jsonify(full=True, v=v)
    chg, full = dl_changed(c, since, uid)
    if full:
        return jsonify(full=True, v=v)
    vis = {r[0] for r in c.execute(f"SELECT id FROM lists WHERE id IN {vis_sql()}", (uid, uid))}
    ids = set()
    if chg:  # only tasks that were or are in a list the person sees (a change in someone else's list is not theirs to learn)
        q = ",".join("?" * len(chg))
        now = {r[0]: r[1] for r in c.execute(f"SELECT id, list_id FROM tasks WHERE id IN ({q})", list(chg))}
        ids = {i for i, ls in chg.items() if (ls | {now.get(i)}) & vis}
    if ids:  # dependencies: "blocked" / "blocking" of the other side moves with an open / closed / moved task
        q = ",".join("?" * len(ids))
        for r in c.execute(f"""SELECT d.task_id, d.blocker_id FROM task_deps d JOIN tasks a ON a.id=d.task_id JOIN tasks b ON b.id=d.blocker_id
                              WHERE (d.task_id IN ({q}) OR d.blocker_id IN ({q})) AND a.list_id IN {vis_sql()} AND b.list_id IN {vis_sql()}""",
                           [*ids, *ids, uid, uid, uid, uid]):
            ids.update((r[0], r[1]))
    if len(ids) > DL_MAX:
        return jsonify(full=True, v=v)
    s = usettings(c, uid)
    cutoff = iso(now_utc() - timedelta(days=14))
    tasks = []
    if ids:
        q = ",".join("?" * len(ids))
        # the where clause of /api/state, limited to the changed ids
        tasks = load_tasks(c, f"list_id IN {vis_sql()} AND deleted_at IS NULL AND (status=0 OR completed_at>=? OR "
                              f"list_id IN (SELECT id FROM lists WHERE checklist=1)) AND id IN ({q}) ORDER BY id",
                           (uid, uid, cutoff, *ids))
    seen = {t["id"] for t in tasks}
    lids = {t["list_id"] for t in tasks}
    for i in ids:  # the lists the changed tasks left too (their progress)
        lids |= chg.get(i, set())
    if ids:
        q = ",".join("?" * len(ids))
        lids |= {r[0] for r in c.execute(f"SELECT list_id FROM tasks WHERE id IN ({q})", list(ids))}
    lids &= vis
    tall = time_all()
    return jsonify(
        v=v, full=False, tasks=tasks, gone=sorted(i for i in ids if i not in seen),
        progress={str(k): p for k, p in list_progress(c, sorted(lids), s.get("progress_subtasks") == "1", uid).items()},
        counts=dict(
            done=c.execute(f"SELECT COUNT(*) FROM tasks WHERE list_id IN {vis_sql()} AND deleted_at IS NULL AND status!=0 "
                           f"AND {tvis(c, uid)}", (uid, uid)).fetchone()[0],
            trash=c.execute(f"SELECT COUNT(*) FROM tasks WHERE list_id IN {wr_sql()} AND deleted_at IS NOT NULL",
                            (uid, uid)).fetchone()[0]),
        mine_order=vw_mine_order(c, uid), mine_hidden=mt_mine_hidden(c, uid),
        evlinks=ev_links(c, uid, sorted(seen)) if seen and events_on(c, uid) else {},
        tcontacts=task_contacts(c, uid, seen) if seen else {},
        timer=time_running(c, uid) if tall else None,
        time_totals=time_totals(c, uid) if tall else {},
        time_lists=time_list_totals(c, uid, own=True) if tall else {},  # 2.144.5 C (#1523)
    )
