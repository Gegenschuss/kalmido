"""2.972.0 (#5285, stage Q9a of the cross-cutting core, analysis #3563): following an object exists once, in the shared core.

One table obj_follow (migrations.d/5285_a.py) holds who follows an object and how loud, per person, kind and object:

    mode 'watch'                    the person watches the object: its comments and status changes reach them like someone
                                    who took part (tasks/watchers.py; was task_watchers)
    mode 'list' | 'mute' | 'urgent' the person's bell of the object (notify/taskbell.py; was task_bell): as the project, no
                                    pushes, or every change as an urgent push; until = the last day of an urgency (local day,
                                    NULL = until the task is completed), set_by = who set it, prev / act / act_by = the bell's
                                    one undo step ('list' rows stay for it)

Watching and the bell are separate rows (the primary key holds the mode, ofl_bell_one allows one bell row per person and
object), so a watched task can be muted at the same time, as before. Kinds: 'task' (core/objlight.py). Agents may watch a task
(an agent the project owner opened to them; agents/core.py hears of it as an event) but never get a bell, and obj_notify never
pushes to them (they get agent_emit events).

Who follows says nothing about who may read: every push goes through core/objnotify.py obj_notify, whose first step cuts the
recipients with obj_role >= 'view'. A watcher who lost the object hears nothing; the rows themselves end where a share or a
membership ends (ofl_drop: leaving a project, a member removed, a group / folder share gone, the boundary check, an
organisation left (core/objects.py obj_revoke_person 'leave'), the account deleted ('delete')).

The rows go with their object (trigger kalmido_ofl_gone, a task deleted for good). A watching row carries its task's
organisation (row-level security, core/rls.py; trigger kalmido_ofl_fill / kalmido_ofl_carry); a bell row the organisation it
was set in -- a bell of another workspace (the task moved) is ignored by ofl_bells.

Interface (c = the connection; kind = 'task'):
  ofl_watchers(c, kind, rid) -> {uid}               ofl_watchers_of(c, kind, ids) -> {rid: [uid, ...]}
  ofl_watch(c, kind, rid, uid) -> bool (new)        ofl_unwatch(c, kind, rid, uid) -> bool (was there)
  ofl_bells(c, kind, rid, org, uids=None) -> {uid: row (level, until, set_by, prev, act, act_by, ...)}
  ofl_bell_any(c) -> bool                           ofl_bell_put(...) / ofl_bell_back(...)
  ofl_drop(c, uids, kind, where, args, modes=None)  the persons' rows of the objects matching where (an SQL on ref_id)
  ofl_quiet(c, uid, kind, rid, s, done_ok, only_mute) the follow step of obj_notify (OFL_LEVEL: the kind's bell rule)
  ofl_move(c) / ofl_setup(c)                        the start (core/db.py init_db): the old tables in, the carry trigger
"""
import json

from .db import iso, now_utc, trigger_skip_present
from .kernretire import kern_retire_floor
from .pg import st_ids

OFL_KINDS = ("task",)
OFL_WATCH = "watch"
OFL_BELL = ("list", "mute", "urgent")
OFL_ISO = r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])T([01]\d|2[0-3]):[0-5]\d:[0-5]\d(\.\d{1,6})?(Z|[+-]\d\d:\d\d)$"
OFL_DAY = r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])"
# the SQL of "the tasks person ? watches" (API v1 filter watcher=, tasks/...): ref_id of the rows
OFL_WATCHING_SQL = "SELECT ref_id FROM obj_follow WHERE kind='task' AND mode='watch' AND user_id"
# kind -> fn(c, uid, rid, s, done_ok) -> 'mute' | 'urgent' | None: the bell as it counts for a push now (notify/taskbell.py
# registers 'task': an urgency ends with its day / the completion, urgency from others only while the person accepts it)
OFL_LEVEL = {}
_BELL_COLS = ("user_id, kind, ref_id, org_id, mode AS level, until::text AS until, set_by, prev::text AS prev, act, act_by, "
              "created_at, updated_at")
OFL_CARRY = ("CREATE OR REPLACE TRIGGER kalmido_ofl_carry_tasks AFTER UPDATE OF list_id, org_id ON tasks FOR EACH ROW "
             "WHEN (NEW.org_id IS DISTINCT FROM OLD.org_id) EXECUTE FUNCTION kalmido_ofl_carry();")


def _kind(kind):
    if kind not in OFL_KINDS:
        raise ValueError(f"obj_follow: unknown kind {kind!r}")
    return kind


# ---- watching

def ofl_watchers(c, kind, rid):
    """{uid} of who watches (kind, rid) (raw rows: rights are checked when something is sent, obj_notify)."""
    return {r[0] for r in c.execute("SELECT user_id FROM obj_follow WHERE kind=? AND ref_id=? AND mode='watch'", (_kind(kind), int(rid)))}


def ofl_watchers_of(c, kind, ids):
    """{rid: [uid, ...] (ascending)} of the objects ids that have watchers."""
    out = {}
    ids = sorted({int(x) for x in ids or () if x})
    if ids:
        for r in c.execute("SELECT ref_id, user_id FROM obj_follow WHERE kind=? AND mode='watch' AND ref_id = ANY(CAST(? AS BIGINT[])) "
                           "ORDER BY ref_id, user_id", (_kind(kind), st_ids(ids))):
            out.setdefault(r[0], []).append(r[1])
    return out


def ofl_watch(c, kind, rid, uid, at=None):
    """uid watches (kind, rid) from now (at: the time of an imported row). True = a new row (organisation: kalmido_ofl_fill)."""
    ts = at or iso(now_utc())
    return c.execute("INSERT INTO obj_follow(user_id, kind, ref_id, mode, created_at, updated_at) VALUES(?,?,?,'watch',?,?) "
                     "ON CONFLICT DO NOTHING", (int(uid), _kind(kind), int(rid), ts, ts)).rowcount > 0


def ofl_unwatch(c, kind, rid, uid):
    """uid stops watching (kind, rid). True = there was a row."""
    return c.execute("DELETE FROM obj_follow WHERE kind=? AND ref_id=? AND user_id=? AND mode='watch'",
                     (_kind(kind), int(rid), int(uid))).rowcount > 0


# ---- the bell

def ofl_bells(c, kind, rid, org, uids=None):
    """{uid: row} of the bells of (kind, rid) set in workspace org (None = private; a row of another workspace does not
    count), level 'list' included. A row reads like the old task_bell: level, until ('YYYY-MM-DD' | None), set_by, prev (JSON
    text | None), act, act_by."""
    q = f"SELECT {_BELL_COLS} FROM obj_follow WHERE kind=? AND ref_id=? AND mode<>'watch' AND COALESCE(org_id,0)=?"
    args = [_kind(kind), int(rid), org or 0]
    if uids is not None:
        uids = sorted({int(u) for u in uids})
        if not uids:
            return {}
        q += " AND user_id = ANY(CAST(? AS BIGINT[]))"
        args.append(st_ids(uids))
    return {r["user_id"]: r for r in c.execute(q, args)}


def ofl_bell_any(c):
    """True when any bell is muted or urgent at all (the cheap look before every push)."""
    return bool(c.execute("SELECT 1 FROM obj_follow WHERE mode IN ('mute','urgent') LIMIT 1").fetchone())


def ofl_bell_put(c, kind, rid, uid, org, level, until, set_by, act=None, act_by=None, prev=None, at=None, upd=None):
    """Sets uid's bell of (kind, rid): level of OFL_BELL, until 'YYYY-MM-DD' | None, set_by; act / act_by / prev = the change's
    undo step (prev: the row before or None). at / upd: created / changed at of an imported row (else now). The row takes
    workspace org."""
    if level not in OFL_BELL:
        raise ValueError(f"obj_follow: unknown bell level {level!r}")
    ts = iso(now_utc())
    pj = json.dumps({"level": prev["level"], "until": prev["until"], "set_by": prev["set_by"]}) if prev else None
    return c.execute(
        """INSERT INTO obj_follow(user_id, kind, ref_id, org_id, mode, until, set_by, prev, act, act_by, created_at, updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (user_id, kind, ref_id) WHERE mode <> 'watch' DO UPDATE SET
           org_id=excluded.org_id, mode=excluded.mode, until=excluded.until, set_by=excluded.set_by, prev=excluded.prev,
           act=excluded.act, act_by=excluded.act_by, updated_at=excluded.updated_at""",
        (int(uid), _kind(kind), int(rid), org, level, until or None, set_by, pj, act, act_by, at or ts, upd or ts)).rowcount > 0


def ofl_bell_back(c, kind, rid, uid, level, until, set_by):
    """The undo step of a bell: the row of uid back to (level, until, set_by), its step consumed."""
    if level not in OFL_BELL:
        level, until, set_by = "list", None, None
    c.execute("UPDATE obj_follow SET mode=?, until=?, set_by=?, act=NULL, act_by=NULL, prev=NULL, updated_at=? "
              "WHERE kind=? AND ref_id=? AND user_id=? AND mode<>'watch'",
              (level, until or None, set_by, iso(now_utc()), _kind(kind), int(rid), int(uid)))


def ofl_quiet(c, uid, kind, rid, s, done_ok=False, only_mute=False):
    """The follow step of obj_notify: True = no push for uid about (kind, rid) now -- the bell is muted, or (only_mute False)
    urgent, which pushes on its own (notify/taskbell.py tbl_note). A kind without a bell rule never holds a push back."""
    fn = OFL_LEVEL.get(kind)
    lv = fn(c, uid, rid, s, done_ok) if fn else None
    return lv == "mute" if only_mute else bool(lv)


# ---- the end of a share / membership

def ofl_drop(c, uids, kind, where, args=(), modes=None):
    """The rows of the people uids on the objects of kind whose ref_id matches where (an SQL condition on ref_id with its
    args, e.g. "ref_id IN (SELECT id FROM tasks WHERE list_id=?)"); modes: only these ('watch' / the bell's), None = all.
    Returns the rows deleted. The caller commits."""
    ids = sorted({int(u) for u in ([uids] if isinstance(uids, int) else uids or ()) if u})
    if not ids:
        return 0
    q = f"DELETE FROM obj_follow WHERE kind=? AND user_id = ANY(CAST(? AS BIGINT[])) AND ({where})"
    a = [_kind(kind), st_ids(ids), *args]
    if modes is not None:
        q += " AND mode = ANY(CAST(? AS TEXT[]))"
        a.append("{" + ",".join(modes) + "}")
    return c.execute(q, a).rowcount


# ---- the start

OFL_OLD_WATCH = """INSERT INTO obj_follow(user_id, kind, ref_id, mode, created_at, updated_at)
    SELECT w.user_id, 'task', w.task_id, 'watch', x.at, x.at
    FROM task_watchers w JOIN tasks t ON t.id=w.task_id JOIN users u ON u.id=w.user_id
    CROSS JOIN LATERAL (SELECT CASE WHEN w.created_at ~ ? THEN w.created_at::timestamptz ELSE now() END AS at) x
    ON CONFLICT DO NOTHING"""
OFL_OLD_BELL = """INSERT INTO obj_follow(user_id, kind, ref_id, org_id, mode, until, set_by, prev, act, act_by, created_at, updated_at)
    SELECT b.user_id, 'task', b.task_id, o.id, CASE WHEN b.level IN ('list','mute','urgent') THEN b.level ELSE 'list' END,
           CASE WHEN b.until ~ ? THEN substr(b.until, 1, 10)::date END, b.set_by,
           CASE WHEN left(b.prev, 1) = '{' THEN b.prev::jsonb END, b.act, b.act_by,
           CASE WHEN b.created_at ~ ? THEN b.created_at::timestamptz ELSE now() END,
           CASE WHEN b.updated_at ~ ? THEN b.updated_at::timestamptz ELSE now() END
    FROM task_bell b JOIN tasks t ON t.id=b.task_id JOIN users u ON u.id=b.user_id LEFT JOIN orgs o ON o.id=b.org_id
    ON CONFLICT DO NOTHING"""


OFL_FLOOR_HOW = ("task watchers and bells moved into the shared core (obj_follow, #5285) and the old tables were dropped - an "
                 "older version would make them again empty and lose what it writes there; go back only with a backup from before")


def ofl_move(c):
    """2.972.0 (#5285): the rows of task_watchers and task_bell into obj_follow, while those tables are there (the first start
    of 2.972, or again after a version before 2.972 ran and made them anew). Only rows whose task and person still exist; a
    row there already stays. One statement per table inside the start transaction; an old time that is not in the app's ISO
    form becomes now instead of failing the cast. The fragment 5285_a drops the old tables right after (one-way). Returns the
    rows moved."""
    n, old = 0, False
    if c.execute("SELECT to_regclass('task_watchers')").fetchone()[0]:
        n += c.execute(OFL_OLD_WATCH, (OFL_ISO,)).rowcount
        old = True
    if c.execute("SELECT to_regclass('task_bell')").fetchone()[0]:
        n += c.execute(OFL_OLD_BELL, (OFL_DAY, OFL_ISO, OFL_ISO)).rowcount
        old = True
    if old:  # review 2.972 (Fable F1/F2): the back limit = the minor of the image that moves (core/kernretire.py), not the label
        kern_retire_floor(c, how=OFL_FLOOR_HOW)
    return n


def ofl_setup(c):
    """init_db (every start, as "system", after the migrations): the old rows in (ofl_move), then the trigger that carries a
    task's new workspace to its watching rows (tasks.org_id exists only after the migrations)."""
    n = ofl_move(c)
    if n:
        print(f"watchers and bells moved into obj_follow: {n}", flush=True)
    c.executescript(trigger_skip_present(c, OFL_CARRY))
    return n
