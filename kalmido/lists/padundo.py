"""2.809.0 (#5476): undo across devices, the rest of stage 7 -- the notepads of a project's pin board in the core's step
groups (core/undoareas.py).

A notepad (table list_notepads) is the tracked kind "notepad" (core/writes.py obj_track): a save of its title or text
(PATCH /api/notepads/<id>, accounts/layouts.py WG_PAD_STEP: renamed, or the text when its field is left) records a snap step of the person under its lock
(list_notepads-<id>), labelled with its title. Taking back (core/undoweb.py): write on the project NOW (accounts/layouts.py
_wg_pad), and no text into a project that got the end-to-end lock since (collab/liste2e.py le2a_locked_text: notepads are not
encrypted). Adding and deleting a notepad record none (deleting removes the row; the browser's step adds it again)."""
from ..collab.liste2e import le2a_locked_text
from ..core.errors import Denied
from ..core.objhooks import GONE
from ..core.undoareas import ua_plain, ua_post, ua_pre
from ..core.undogroups import UG_LABEL
from ..core.undoweb import undo_need_reg
from ..core.writes import obj_track
from ..accounts.layouts import WG_PAD_STEP, _wg_pad

NPU_KIND = "notepad"


def npu_label(r):
    return UG_LABEL, [ua_plain(r.get("title") or "", r.get("id"))]


obj_track(NPU_KIND, "list_notepads", undo_keep={"list_notepads": {"list_id", "created_by", "agent_id"}}, undo_label=npu_label)
GONE[NPU_KIND] = "list_notepads"  # history / undo rows of objects that went (core/objhooks.py)


def npu_pre(c, uid, pid):
    """The person's step before a save of notepad pid (after its lock list_notepads-<id>); an agent records none."""
    ua_pre(c, uid, NPU_KIND, pid)


def npu_post(c):
    ua_post(c)


def npu_need(c, uid, rid, oid):
    """Who may take a notepad's step back now: write on its project; no text into a project with the lock."""
    r, _role = _wg_pad(c, int(rid), True)

    def fix(c):
        n = c.execute("SELECT list_id, title, body FROM list_notepads WHERE id=?", (int(rid),)).fetchone()
        if n is None:
            raise Denied(404)
        le2a_locked_text(c, n["list_id"], n["title"], n["body"])
    return {"fix": fix, "lock": f"list_notepads-{int(rid)}"}


undo_need_reg(NPU_KIND, npu_need)
WG_PAD_STEP.update(pre=npu_pre, post=npu_post)  # accounts/layouts.py wg_pad_patch calls them (a lower layer, no import of this one)
