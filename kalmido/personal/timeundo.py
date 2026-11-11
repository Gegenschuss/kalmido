"""2.809.0 (#5476): undo across devices -- a person's time entries in the core's step groups (core/undoareas.py).

A change of an own time entry (PATCH /api/time/entries/<id>: times, note, task / project, billable) records a snap step
(tracked kind "time_entry", obj_track) under the entry's lock (time-<id>, as oxb_time_prev), labelled with its duration.
Deleting a finished entry (DELETE /api/time/entries/<id>, a hard delete) records a diff part (kind "time_life",
core/undodiff.py) holding the row as it was. Taking back, with the rules of today (core/undoweb.py):
- only the person who tracked it, time tracking on (need_time), never in a closed month (timesheet.py tsl_check: the month
  of the entry now and the one it goes back to);
- a billed entry (billed by an invoice since) keeps everything but its note, as a save does (office/timebill.py);
- back into a project the person no longer sees or without time tracking: 409, it stays;
- an entry deleted comes back with its id (its task, if purged since, as a project entry), deleted again forward only while
  it is as the step left it. No new budget warning mail from an undo beyond what a save does (budgetwarn.bw_check).
The billing columns, the device's client id, the reminder marks and the focus session link are never written back.

Interface:
  teu_pre(c, uid, eid) / teu_post(c) -> group id | None    around the PATCH's write
  teu_deleted(c, uid, row) -> group id | None              after the DELETE (the row as it was)"""
import json

from flask import g

from ..collab.liste2e import LE2EDenied
from ..collab.liste2eguard import le2b_list_locked, le2b_scrub_undo, le2b_task_locked  # #5582: + le2b_scrub_undo
from ..core.access import list_role, need_time
from ..core.errors import Denied
from ..core.i18n import N_, tr
from ..core.objhooks import GONE
from ..core.pg import qi, table_columns, write_lock
from ..core.undoareas import ua_done, ua_pre
from ..core.undogroups import UG_LIFE
from ..core.undodiff import ug_diff_add, undo_diff_reg, undo_person
from ..core.undoweb import undo_need_reg
from ..core.writes import obj_track
from ..office.timebill import tbill_need_open
from .budgetwarn import bw_check
from .timesheet import tsl_check
from .timetrack import mt_time_on

TEU_KIND = "time_entry"
TEU_LIFE = "time_life"
TEU_AREA = "time"
TEU_CHANGED = N_("Time entry changed ({0})")
TEU_DELETED = N_("Time entry deleted ({0})")  # the key exists (static/js/time.js)
TEU_GONE = N_("The time entry is not as this step left it, so it cannot be undone")
TEU_PLACE = N_("The project of this time entry cannot take time any more, so it cannot be undone")
TEU_KEEP = frozenset({"user_id", "billed_doc_id", "billed_at", "billed_item_id", "pomo_id", "client_id", "reminded",
                      "auto_stopped", "task_title", "created_at", "source"})
TEU_NOFP = frozenset({"reminded", "auto_stopped", "task_title"})


def _hm(sec):
    sec = int(sec or 0)
    return f"{sec // 3600}:{sec // 60 % 60:02d}"


def teu_label(r):
    return TEU_CHANGED, [_hm(r.get("seconds"))]


obj_track(TEU_KIND, "time_entries", area=TEU_AREA, undo_keep={"time_entries": set(TEU_KEEP)},
          undo_nofp={"time_entries": set(TEU_NOFP)}, undo_label=teu_label)
GONE[TEU_KIND] = "time_entries"  # an account's deletion takes its history / undo rows (core/objhooks.py)
UG_LIFE[TEU_KIND] = TEU_LIFE  # 2.983.0 (#5589): the watchdog's undo run keeps a deleted entry's history while it can come back


def teu_pre(c, uid, eid):
    write_lock(c, f"time-{int(eid)}")
    ua_pre(c, uid, TEU_KIND, eid)


def teu_post(c):
    return ua_done(c)


def _place_ok(c, uid, lid):
    if lid and not (list_role(c, lid, uid) and mt_time_on(c, lid)):
        raise Denied(409, tr(TEU_PLACE))


def _locked(c, lid, tid):
    """2.900.0 (#5550): the entry's project (or its task's) has the end-to-end lock: no note, no task title in plain text."""
    return le2b_list_locked(c, lid) or le2b_task_locked(c, tid)


def teu_need(c, uid, rid, oid):
    """Who may take a change back now: the person who tracked it, outside a closed month, a billed one only in its note."""
    need_time()
    was = c.execute("SELECT * FROM time_entries WHERE id=?", (int(rid),)).fetchone()
    if was is None or was["user_id"] != int(uid):
        raise Denied(404)
    tsl_check(c, uid, was["start"])

    def fix(c):
        now = c.execute("SELECT * FROM time_entries WHERE id=?", (int(rid),)).fetchone()
        tsl_check(c, uid, now["start"])  # TslClosed is a Denied (409): the part stays
        if now["billed_doc_id"] and any(now[k] != was[k] for k in now.keys() if k not in ("note", "updated_at")):
            tbill_need_open(c, now, None)  # billed: only its note (409 with the invoice's reason)
        if now["list_id"] != was["list_id"]:
            _place_ok(c, uid, now["list_id"])
        if now["end"] is not None or was["end"] is not None:
            bw_check(c, [(was["list_id"], was["task_id"]), (now["list_id"], now["task_id"])])
        if now["note"] and _locked(c, now["list_id"], now["task_id"]):
            # 2.900.0 (#5550): a step of before the lock writes no note back into a locked project: refused (409, the part
            # stays and the write back is rolled back with its history row; the task title is never written back, TEU_KEEP)
            raise LE2EDenied("list_e2e_plain")
        if (now["list_id"], now["task_id"]) != (was["list_id"], was["task_id"]) and _locked(c, now["list_id"], now["task_id"]):
            # 2.991.0 (#5634, review 2.936 finding 3): taken back (or forward) into a locked project: the entry's other
            # steps (a note written in the open project since) and its history rows go, as after a save (teu_scrub_moved);
            # the group running now stays (core/undoweb.py _part marks it); its own copies are cleaned in after()
            _teu_scrub(c, rid, g.get("undo_running_gid"))
            into.append(True)

    def after(c, part_id):
        """2.991.0 (#5634, review): the step running keeps no note either - its copy of the row before the undo (a move
        and a note in ONE save) is written after fix (core/writes.py _undo_one: redo), and its history row after that."""
        if not into:
            return
        st = c.execute("SELECT snap, redo FROM obj_undo WHERE id=?", (int(part_id),)).fetchone()
        if st is not None:
            c.execute("UPDATE obj_undo SET snap=?, redo=? WHERE id=?", (_teu_blank(st["snap"]), _teu_blank(st["redo"]), int(part_id)))
        c.execute("DELETE FROM obj_history WHERE kind=? AND ref_id=?", (TEU_KIND, int(rid)))
    into = []
    return {"fix": fix, "after": after, "lock": f"time-{int(rid)}"}


def _teu_blank(js):
    """A copy (obj_undo.snap / redo: {table: [rows]}) without the free texts the lock keeps out (note, task title)."""
    if not js:
        return js
    d = json.loads(js)
    for r in d.get("time_entries") or []:
        if r.get("note"):
            r["note"] = ""
        if r.get("task_title"):
            r["task_title"] = None
    return json.dumps(d, ensure_ascii=False, default=str)


undo_need_reg(TEU_KIND, teu_need)


def teu_scrub_moved(c, eid, lid, tid):
    """#5582 (review of 2.900, finding 3): an entry moved by a save into a locked project (or onto a task of one): its older
    steps (changes and a delete taken back) hold the note and task title of before in their copies -> they go, as the lock
    drops them for the entries already there (collab/liste2eguard.py le2b_scrub_undo_free). The step of this save is recorded
    after it. The caller commits.
    Review 2.936: also its history rows (core/writes.py obj_undo_hist keeps note / task title before and after an undo), under
    the entry's lock (an undo of the same entry waits); True = moved into a locked project: the save records no undo step
    (its copy would hold the note of before)."""
    if not _locked(c, lid, tid):
        return False
    write_lock(c, f"time-{int(eid)}")
    _teu_scrub(c, eid)
    return True


def _teu_scrub(c, eid, keep_gid=None):
    """The entry's undo steps (but group keep_gid, the one running) and its history rows go. The caller holds time-<eid>."""
    if keep_gid:
        # review: ug_drop_ids unlinks the parts of an editor session (group_id NULL) instead of deleting them: NULL is not kept
        le2b_scrub_undo(c, "kind IN (?, ?) AND ref_id=? AND (group_id IS NULL OR group_id<>?)",
                        (TEU_KIND, TEU_LIFE, int(eid), int(keep_gid)))
    else:
        le2b_scrub_undo(c, "kind IN (?, ?) AND ref_id=?", (TEU_KIND, TEU_LIFE, int(eid)))
    c.execute("DELETE FROM obj_history WHERE kind=? AND ref_id=?", (TEU_KIND, int(eid)))


def teu_deleted(c, uid, row):
    """The diff part of a deleted finished entry (row = the row as it was)."""
    if undo_person(c) is None or row is None or row["end"] is None:
        return None
    data = {k: row[k] for k in row.keys()}
    if not ug_diff_add(c, uid, TEU_LIFE, row["id"], None, TEU_AREA, (TEU_DELETED, [_hm(row["seconds"])]), {"row": data}):
        return None
    return (g.get("undo_group") or {}).get("id")


def _same(now, data):
    return all(now[k] == data.get(k) for k in now.keys() if k not in ("updated_at", "reminded", "auto_stopped", "task_title"))


def teu_life_run(c, uid, eid, data, redo):
    """A deleted entry back (undo) / deleted again (redo)."""
    need_time()
    row = dict(data.get("row") or {})
    if int(row.get("user_id") or 0) != int(uid):
        raise Denied(404)
    write_lock(c, f"time-{int(eid)}")
    now = c.execute("SELECT * FROM time_entries WHERE id=?", (int(eid),)).fetchone()
    tsl_check(c, uid, row.get("start"))
    if redo:
        if now is not None and _locked(c, now["list_id"], now["task_id"]):
            # #5582 (review of 2.900, finding 4): in a locked project now (the lock emptied the note): compared and kept
            # without its plain texts, as the undo branch writes it back
            row.update(note="", task_title="")
            data = {**data, "row": {**(data.get("row") or {}), "note": "", "task_title": ""}}
        if now is None or now["billed_doc_id"] or not _same(now, row):
            raise Denied(409, tr(TEU_GONE))
        c.execute("DELETE FROM time_entries WHERE id=? AND billed_doc_id IS NULL", (int(eid),))
    else:
        if now is not None:
            raise Denied(409, tr(TEU_GONE))
        _place_ok(c, uid, row.get("list_id"))
        if row.get("task_id") and not c.execute("SELECT 1 FROM tasks WHERE id=?", (row["task_id"],)).fetchone():
            row["task_id"] = None  # purged since: a project entry (its title stays in task_title)
        if row.get("pomo_id") and c.execute("SELECT 1 FROM time_entries WHERE pomo_id=?", (row["pomo_id"],)).fetchone():
            row["pomo_id"] = None
        if row.get("client_id") and c.execute("SELECT 1 FROM time_entries WHERE user_id=? AND client_id=?", (uid, row["client_id"])).fetchone():
            row["client_id"] = None
        for k in ("billed_doc_id", "billed_at", "billed_item_id"):
            row[k] = None
        if _locked(c, row.get("list_id"), row.get("task_id")):  # 2.900.0 (#5550): back without its plain texts
            row.update(note="", task_title="")
            data = {**data, "row": {**(data.get("row") or {}), "note": "", "task_title": ""}}
        have = table_columns(c, "time_entries")
        cols = [k for k in row if k in have]
        c.execute(f"INSERT INTO time_entries({','.join(qi(k, have) for k in cols)}) VALUES({','.join('?' * len(cols))})",
                  [row[k] for k in cols])
    bw_check(c, [(row.get("list_id"), row.get("task_id"))])
    return {"row": data.get("row")}, []


undo_diff_reg(TEU_LIFE, teu_life_run, TEU_AREA)
