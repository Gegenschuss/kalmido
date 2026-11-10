"""2.809.0 (#5476): undo across devices -- creating, deleting and restoring a project's section in the core's step groups
(diff parts, core/undodiff.py; a section's own values and the order of the sections: tasks/tundo.py).

POST /api/sections (a new section), DELETE /api/sections/<id> (into the trash: a copy, lists/parttrash.py) and POST
/api/sections/<id>/restore record a part of kind "section_life" ({op: create | delete | restore}, ref = the section) in the
person's step group, labelled with the section's name (a ciphertext name of a list with the lock: none). Taking back runs the
area's own ways, with the rights of now (whoever may change the project, as the routes): a new / restored section goes into
the trash again (sections.py sec_trash, its tasks stay without one), a deleted one comes back with its id, its limits and the
tasks still without a section (parttrash.py lpt_section_back); forward again the other way round. A section that is not
where the step left it (deleted meanwhile, already back) stays and is named.

Interface:
  secu_add(c, sid, op, name, lid) -> the request's group id | None     after the route's write, before its commit"""
from flask import g

from ..core.access import need_list
from ..core.errors import Denied
from ..core.i18n import N_, tr
from ..core.pg import write_lock
from ..core.undoareas import ua_plain
from ..core.undodiff import ug_diff_add, undo_diff_reg, undo_person
from .parttrash import lpt_section_back
from .sections import sec_trash

SECU_KIND = "section_life"
SECU_AREA = "tasks"
SECU_ADD = N_("Section {0} added")  # the key exists (static/js/dnd.js)
SECU_DEL = N_("Section {0} deleted")
SECU_GONE = N_("The section is not where this step left it, so it cannot be undone")


def secu_add(c, sid, op, name, lid):
    uid = undo_person(c)
    if uid is None:
        return None
    org = c.execute("SELECT org_id FROM lists WHERE id=?", (int(lid),)).fetchone()
    label = (SECU_DEL if op == "delete" else SECU_ADD, [ua_plain(name, sid)])
    if not ug_diff_add(c, uid, SECU_KIND, sid, org[0] if org else None, SECU_AREA, label, {"op": op, "list_id": int(lid)}):
        return None
    return (g.get("undo_group") or {}).get("id")


def secu_run(c, uid, sid, data, redo):
    """Back / forward: there = the section should exist after this run (a create / restore forward, a delete back)."""
    there = (data.get("op") == "delete") != bool(redo)
    lid = int(data.get("list_id") or 0)
    write_lock(c, f"section-{int(sid)}")
    row = c.execute("SELECT name, list_id FROM sections WHERE id=?", (int(sid),)).fetchone()
    if there:
        if row is not None:
            raise Denied(409, tr(SECU_GONE))
        need_list(c, lid)  # 404 / 403: may not change the project now
        try:
            lpt_section_back(c, sid, uid)
        except Denied as e:
            raise (Denied(409, tr(SECU_GONE)) if e.code == 404 else e) from None
    else:
        if row is None:
            raise Denied(409, tr(SECU_GONE))
        need_list(c, row["list_id"])
        sec_trash(c, sid, row["name"], uid)
    return data, []


undo_diff_reg(SECU_KIND, secu_run, SECU_AREA)
