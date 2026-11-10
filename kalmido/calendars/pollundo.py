"""2.809.0 (#5476): undo across devices, the rest of stage 7 -- scheduling polls in the core's step groups (core/undoareas.py).

A poll (table sched_polls with its proposed times sched_poll_options) is the tracked kind "poll" (core/writes.py obj_track):
a change in its dialog (PATCH /api/polls/<id>: title, text, place, duration, times, the link switch), putting it into the
trash and taking it out record a snap step of the person under the poll's lock (sched_polls-<id>), labelled with its title.
Not part of the copy: the votes (the voters' own), the link's secret (a new link never turns back into the old one), the
chosen time and its event (decide / reopen have their own steps in the browser); a time chosen since makes the step a
conflict (the fingerprint). Taking back (core/undoweb.py): the person needs write on the poll NOW (calendars/polls.py
tpo_need write=True: its owner, an admin of its organisation; a poll kept from an agent that changed hands: nobody), the
module of the calendar switched on (tpo_gate). Creating a poll records none (the browser's step deletes it)."""
from ..core.errors import Denied
from ..core.objhooks import GONE
from ..core.undoareas import UA_DELETED, UA_RESTORED, ua_plain, ua_post, ua_pre
from ..core.undogroups import UG_LABEL
from ..core.undoweb import undo_need_reg
from ..core.writes import obj_track
from .polls import tpo_gate, tpo_need

TPU_KIND = "poll"
TPU_WHAT = {"delete": UA_DELETED, "restore": UA_RESTORED}


def tpu_label(r):
    return UG_LABEL, [ua_plain(r.get("title"), r.get("id"))]


def tpu_scope(rid, _oid):
    return [("sched_polls", "id=?", (int(rid),), False), ("sched_poll_options", "poll_id=?", (int(rid),), True)]


obj_track(TPU_KIND, "sched_polls", undo_scope=tpu_scope,
          undo_keep={"sched_polls": {"user_id", "token", "token_hash", "trash_owner", "closed_at", "chosen_id", "event_id", "event_ref"}},
          undo_label=tpu_label, undo_free=("deleted_at",))
GONE[TPU_KIND] = "sched_polls"  # an account's deletion takes its history / undo rows (core/objhooks.py)


def tpu_pre(c, uid, pid, what=None):
    """The person's step before a write of poll pid (after its lock sched_polls-<id>); an agent records none."""
    r = c.execute("SELECT title FROM sched_polls WHERE id=?", (int(pid),)).fetchone()
    key = TPU_WHAT.get(what or "")
    ua_pre(c, uid, TPU_KIND, pid, *((key, ua_plain(r["title"] if r else "", pid)) if key else ()))


def tpu_post(c):
    ua_post(c)


def tpu_need(c, uid, rid, oid):
    """Who may take a poll's step back now: write on it (in the trash or not)."""
    tpo_gate()
    r = c.execute("SELECT deleted_at FROM sched_polls WHERE id=?", (int(rid),)).fetchone()
    if r is None:
        raise Denied(404)
    tpo_need(c, int(rid), write=True, deleted=bool(r["deleted_at"]))
    return {"lock": f"sched_polls-{int(rid)}"}


undo_need_reg(TPU_KIND, tpu_need)
