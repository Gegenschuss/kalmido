"""2.1074.0 (#5493): undo across devices, stage 3c -- a project's settings WITH side effects as steps of the person
(core/undodiff.py diff parts, kind "listside", area tasks).

Decision (08.11.2026, #5369): a project's settings are server steps -- also folder, type, workspace, agents, client,
Home & life, time tracking, ticket key and visibility, each with a clean way back of its side effects. The plain settings
(lists/lpundo.py, kind "listset") keep their copy step; a save that also changes one of LPS_KEYS records a diff part instead:
the settings' values before and after as the app reads and sends them (lists.py lp_current), only the ones that changed --
also the ones the save changed as a side effect (a folder's defaults adopted with folder_adopt, the listening agents of a new
project type, the agents a health list sends away, "Everyone in the organisation" ended by a move to Private).
Taking it back runs the project's own write path (lists.py list_apply) with the values before and _prev = the values the step
left, so every side effect goes the way it went (lm_folder_moved, list_org_set + movememo.lmm_restore: what the workspace
change ended comes back, list_ptype_set, the agents' own switches, ov_list_patch) with the rights and checks of now. A value
changed elsewhere since stays and is named (UG_KEPT); nothing of the step left = 409.

Interface:
  lps_pre(c, lid, role, b) -> state | None    after lv_check: the values before (None: nothing to record)
  lps_post(c, lid, role, st) -> group | None  right before the commit: the diff part (None: nothing changed / no group)"""
import json

from flask import g

from ..core.access import need_list
from ..core.errors import Denied
from ..core.i18n import N_, tr
from ..core.undodiff import ug_diff_add, undo_diff_reg, undo_person
from ..core.undogroups import UG_TRACKED
from ..core.undoweb import UG_KEPT, UG_KEPT_REDO
from ..core.undoareas import ua_plain
from .lists import list_apply, lp_current, lp_norm
from .lpundo import LPU_META

LPS_KIND = "listside"
LPS_AREA = "tasks"
LPS_LABEL = N_("Settings of {0}")  # the keys exist (static/js/dialogs.js)
LPS_WS = N_("Workspace of {0}")
LPS_GONE = N_("Changed in the meantime, nothing to undo")  # the key exists (tasks/tundo.py)
# the body keys with side effects elsewhere (lists.py list_apply): one of them in a save makes the save a diff step
LPS_KEYS = ("folder", "org_id", "ptype", "family", "life", "trip", "time_tracking", "client_id", "ticket_key", "agent_tidy",
            "tidy_agent_id", "listen_agent_ids", "agent_members", "agent_followup", "stale_days", "org_visibility", "org_edit")
# the agents a save names only through the project's agents (a member that went, a new project type's default): a step
# keeps them only when the save set them itself or adopted a folder's (else its way back would name an agent gone since)
LPS_DERIVED = ("listen_agent_ids", "tidy_agent_id")
LPS_FIRST = ("org_id",)  # taken back before the other values (lps_run)
# the plain settings a side effect may change too (a project type's defaults, a folder's), read and sent in the same form
# (lp_current); the ones with their own cleaning (props, ticket templates and types) are not taken back by this step
LPS_PLAIN = ("name", "color", "view", "kind", "dep_shift", "rate", "archived", "tickets", "nag", "day_hours", "checklist",
             "sort_mode", "done_in_section", "group_field", "columns", "col_sums", "kpis", "tap_done", "points_on",
             "irreversible_needs_yes", "two_eyes", "mail_guests", "def_ttype")


def _norm(v):
    """A value for "changed?" (lists.py lp_norm: '' / None / 0 / False / [] the same)."""
    return lp_norm(sorted(v) if isinstance(v, list) and all(isinstance(x, int) for x in v) else v)


def lps_state(c, lid, role):
    """The values of LPS_KEYS + LPS_PLAIN as the person's PATCH sends them."""
    from ..agents.core import listen_agents_of, tidy_agent_of
    cur = lp_current(c, lid, role)
    st = {k: cur.get(k) for k in LPS_KEYS + LPS_PLAIN if k in cur}
    st["listen_agent_ids"] = sorted(listen_agents_of(c, lid))
    st["tidy_agent_id"] = tidy_agent_of(c, lid)
    try:
        st["trip"] = json.loads(cur["trip"]) if cur.get("trip") else None
    except ValueError:
        st["trip"] = None
    return st


def lps_pre(c, lid, role, b):
    if undo_person(c) is None or not any(k in b for k in LPS_KEYS):
        return None
    return {"st": lps_state(c, lid, role), "keys": [k for k in b if k not in LPU_META], "adopt": b.get("folder_adopt") is True}


def lps_post(c, lid, role, st0):
    """The diff part of the save (its values before / after that differ); the request's group id or None."""
    uid = undo_person(c)
    if not st0 or uid is None:
        return None
    now = lps_state(c, lid, role)
    ch = [k for k in now if _norm(st0["st"].get(k)) != _norm(now[k])
          and (k not in LPS_DERIVED or k in st0["keys"] or st0["adopt"])]
    if not ch:
        return None
    row = c.execute("SELECT name, org_id FROM lists WHERE id=?", (int(lid),)).fetchone()
    label = (LPS_WS if "org_id" in ch else LPS_LABEL, [ua_plain(st0["st"].get("name") or row["name"], lid)])
    pid = ug_diff_add(c, uid, LPS_KIND, lid, row["org_id"], LPS_AREA, label,
                      {"op": "fields", "b": {k: st0["st"].get(k) for k in ch}, "a": {k: now[k] for k in ch}})
    grp = g.get("undo_group")
    return grp["id"] if pid and grp else None


def lps_run(c, uid, lid, data, redo):
    """The step back (redo: forward): list_apply with the values the step ended (src -> dst). A value changed elsewhere since
    stays (named); one already at the target is not written again."""
    role = need_list(c, lid, write=False)  # 404 without access now
    src, dst = (data.get("b") or {}, data.get("a") or {}) if redo else (data.get("a") or {}, data.get("b") or {})
    left, went = [], False
    # the workspace first, on its own: its way back (lmm_restore) brings back what the move ended (a private client); the
    # rest after it, read again (a client back already is not written twice, one of the workspace now fits)
    for phase in (LPS_FIRST, None):
        now = lps_state(c, lid, role)
        put = {}
        for k, v in dst.items():
            if (k in LPS_FIRST) != (phase is not None) or k not in now or _norm(now[k]) == _norm(v):
                continue  # another phase, or already as the step left it before
            if _norm(now[k]) != _norm(src.get(k)):
                left.append(k)  # changed elsewhere since: stays
                continue
            put[k] = v
        if put:
            left += _apply(c, lid, put, src)
            went = True
    if not went:
        raise Denied(409, tr(UG_KEPT_REDO if redo else UG_KEPT, ", ".join(left)) if left else tr(LPS_GONE))
    return data, left


def _apply(c, lid, put, src):
    """list_apply of the values put (_prev = the step's values) -> the fields that stayed; its refusal = Denied (403 / 404
    kept, else 409)."""
    out = list_apply(c, lid, {**put, "_prev": {k: src.get(k) for k in put}})
    if not isinstance(out, dict):
        try:
            msg = out[0].get_json().get("error")
            code = out[1]
        except (AttributeError, IndexError, TypeError):
            msg, code = None, 409
        raise Denied(code if code in (403, 404) else 409, msg if isinstance(msg, str) else tr(LPS_GONE))
    return [x["field"] for x in out.get("conflicts") or []]  # changed elsewhere meanwhile (lp_prev_conflicts): stays, named


undo_diff_reg(LPS_KIND, lps_run, LPS_AREA)
UG_TRACKED.update({LPS_KIND: "lists"})  # the watchdog drops the parts of a project deleted for good
