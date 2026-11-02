"""2.392.2 (#3365): the delivery state of a task -- a field of its own next to the build state of its code (code.build.state:
released / main / branch / none stays as it is).

    ''           nothing said (the build state speaks alone)
    in_progress  a job works on it (delivery_job_id: a running / waiting job of that task)
    parked       held on purpose, with a reason (delivery_note)
    waiting      waits for a prerequisite: another task (delivery_task_id) or what delivery_note says

People and agents with write access set it (PUT / DELETE /api/tasks/<id>/delivery, the field delivery of PATCH
/api/v1/tasks/<id>, MCP set_delivery). An agent's job that starts running on a task with no state marks it in_progress by
itself; when that job ends (done / failed / stopped) the mark goes, or moves to another open job of the task. parked and
waiting stay until someone changes them: a job never overwrites what a person decided. The release pass of the git poll
never completes a parked task (integrations/gitbuild.py gb_close_held). A list with the lock takes no note (the server would
hold it in plain)."""
from ..core.access import Denied, task_visible
from ..core.db import iso, now_utc
from ..core.errors import BadInput
from ..core.i18n import tr
from ..tasks.validation import log_act

DV_STATES = ("in_progress", "parked", "waiting")
DV_NOTE_MAX = 500
DV_OPEN_JOB = "state IN ('running','waiting') AND kind IS NULL AND COALESCE(approval, '')=''"


def dv_view(r):
    """The state of a task row for the API: {state, note, job_id, task_id, since, by}, None = nothing said."""
    if "delivery" not in r.keys() or not r["delivery"]:
        return None
    return {"state": r["delivery"], "note": r["delivery_note"] or "", "job_id": r["delivery_job_id"], "task_id": r["delivery_task_id"],
            "since": r["delivery_at"], "by": r["delivery_by"]}


def dv_job_of_task(c, tid, jid=None):
    """The open job jid of task tid (its first task or, 2.392.2 #3366, one of its tasks), or without jid the newest one; None = none."""
    q = f"""SELECT * FROM agent_jobs WHERE {DV_OPEN_JOB} AND (task_id=? OR id IN (SELECT job_id FROM agent_job_tasks WHERE task_id=?))"""
    if jid:
        return c.execute(q + " AND id=?", (tid, tid, jid)).fetchone()
    return c.execute(q + " ORDER BY updated_at DESC, id DESC LIMIT 1", (tid, tid)).fetchone()


def dv_parse(c, tid, v, u):
    """Body {state, note?, job_id?, task_id?} -> the columns to store (None = clear). u = the users row of the caller."""
    if v is None:
        return None
    if not isinstance(v, dict) or set(v) - {"state", "note", "job_id", "task_id"} or v.get("state") not in DV_STATES:
        raise BadInput(tr("Invalid value: {0}", "delivery"))
    st, note = v["state"], v.get("note", "")
    if not isinstance(note, str) or len(note.strip()) > DV_NOTE_MAX:
        raise BadInput(tr("Invalid value: {0}", "note"))
    note = note.strip()
    out = {"delivery": st, "delivery_note": note, "delivery_job_id": None, "delivery_task_id": None}
    for k in ("job_id", "task_id"):
        x = v.get(k)
        if x is not None and (not isinstance(x, int) or isinstance(x, bool) or x < 1):
            raise BadInput(tr("Invalid value: {0}", k))
    if v.get("job_id") is not None and st != "in_progress" or v.get("task_id") is not None and st != "waiting":
        raise BadInput(tr("Invalid value: {0}", "delivery"))
    if st == "in_progress":
        j = dv_job_of_task(c, tid, v.get("job_id"))
        if v.get("job_id") and (not j or (u["kind"] == "agent" and j["agent_id"] != u["id"])):
            raise BadInput(tr("Invalid value: {0}", "job_id"))  # only an open job of this task (an agent: its own)
        if j and (u["kind"] != "agent" or j["agent_id"] == u["id"]):
            out["delivery_job_id"] = j["id"]
    elif st == "waiting" and v.get("task_id") is not None:
        d = v["task_id"]
        if d == tid or not task_visible(c, d, u["id"]):  # a task the caller sees, never the task itself
            raise BadInput(tr("Invalid value: {0}", "task_id"))
        out["delivery_task_id"] = d
    elif st == "parked" and not note and not _locked(c, tid):
        raise BadInput(tr("A parked task needs a reason"))
    if note and _locked(c, tid):
        from ..collab.liste2eguard import le2b_off
        raise Denied(409, le2b_off())
    return out


def _locked(c, tid):
    from ..collab.liste2eguard import le2b_task_locked
    return le2b_task_locked(c, tid)


def dv_apply(c, tid, v, u):
    """Sets (dict) or clears (None) the state of task tid; the caller checked the write right and commits. Same state again =
    nothing. -> True when it changed."""
    f = dv_parse(c, tid, v, u)
    t = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    now = iso(now_utc())
    if f is None:
        if not t["delivery"]:
            return False
        c.execute("""UPDATE tasks SET delivery='', delivery_note='', delivery_job_id=NULL, delivery_task_id=NULL, delivery_at=?, delivery_by=?,
                     updated_at=? WHERE id=?""", (now, u["id"], now, tid))
        log_act(c, tid, "delivery", {"state": ""})
        return True
    if all((t[k] or None) == (f[k] or None) for k in f):
        return False
    c.execute("""UPDATE tasks SET delivery=?, delivery_note=?, delivery_job_id=?, delivery_task_id=?, delivery_at=?, delivery_by=?, updated_at=?
                 WHERE id=?""", (f["delivery"], f["delivery_note"], f["delivery_job_id"], f["delivery_task_id"], now, u["id"], now, tid))
    log_act(c, tid, "delivery", {"state": f["delivery"], **({"note": f["delivery_note"]} if f["delivery_note"] else {}),
                                 **({"task": f["delivery_task_id"]} if f["delivery_task_id"] else {})})
    return True


def dv_job_started(c, j, tids):
    """An agent's job j (a row) runs on the tasks tids: each of them without a state (or still in_progress of a job that ended)
    is in_progress by j now. parked / waiting stay as they are. -> the ids that changed."""
    if j["state"] != "running" or j["kind"] is not None or (j["approval"] or "") or not tids:
        return []
    now = iso(now_utc())
    q = ",".join("?" * len(tids))
    rows = c.execute(f"""UPDATE tasks SET delivery='in_progress', delivery_note='', delivery_job_id=?, delivery_task_id=NULL, delivery_at=?,
                         delivery_by=? WHERE id IN ({q}) AND deleted_at IS NULL AND status=0 AND (delivery='' OR (delivery='in_progress'
                         AND (delivery_job_id IS NULL OR delivery_job_id NOT IN (SELECT id FROM agent_jobs WHERE {DV_OPEN_JOB})))) RETURNING id""",
                     (j["id"], now, j["agent_id"], *tids)).fetchall()
    return [r[0] for r in rows]


def dv_job_ended(c, jid=None):
    """Job jid is no longer open (or, without jid, every job that ended): its in_progress marks go to the newest other open job
    of the task, else they are cleared. -> the task ids that changed. Called where a job's state changes, and by the watchdog
    (agents/watch.py) as the net under every other way a job ends."""
    if jid:
        rows = c.execute(f"""SELECT id FROM tasks WHERE delivery='in_progress' AND delivery_job_id=? AND NOT EXISTS
                             (SELECT 1 FROM agent_jobs WHERE id=? AND {DV_OPEN_JOB})""", (jid, jid)).fetchall()
    else:
        rows = c.execute(f"""SELECT id FROM tasks WHERE delivery='in_progress' AND delivery_job_id IS NOT NULL
                             AND delivery_job_id NOT IN (SELECT id FROM agent_jobs WHERE {DV_OPEN_JOB}) LIMIT 500""").fetchall()
    now, out = iso(now_utc()), []
    for (tid,) in rows:
        nj = dv_job_of_task(c, tid)
        if nj:
            c.execute("UPDATE tasks SET delivery_job_id=?, delivery_at=?, delivery_by=? WHERE id=?", (nj["id"], now, nj["agent_id"], tid))
        else:
            c.execute("""UPDATE tasks SET delivery='', delivery_note='', delivery_job_id=NULL, delivery_task_id=NULL, delivery_at=?,
                         delivery_by=NULL WHERE id=?""", (now, tid))
        out.append(tid)
    return out


def dv_filter(v, where, args):
    """?delivery= of the task lists: one or several of in_progress, parked, waiting, none (comma separated)."""
    vs = [x.strip() for x in str(v).split(",") if x.strip()]
    if not vs or any(x not in (*DV_STATES, "none") for x in vs):
        raise BadInput(tr("Invalid value: {0}", "delivery"))
    where.append("delivery IN (" + ",".join("?" * len(vs)) + ")")
    args += ["" if x == "none" else x for x in vs]
