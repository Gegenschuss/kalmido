"""2.997.0 (#5609 #5709): undo across devices -- a person's "Delete" of a project into the list trash (lists/listtrash.py)
is a step of the core's step groups (a diff part, core/undodiff.py), so the arrow, the toast's Undo and the list "Recent
steps" take it back on every device. Before, the browser kept its own way back (static/js/listadmin.js otr_offerUndo, #5667):
its redo archived the project again (PATCH, a settings step of lists/lpundo.py), and that NEW group outranked the entry at
the next undo (undo.js histNext compares the browser's clock with the server's) -- only the archive went back and the
project stayed in the trash.

  back     out of the trash as the restore route does it (otr_back: its rights of now, only the same trash stamp, not a
           project kept by law)
  forward  into the trash again (the delete's rights: owner or project admin; archived, not the basket, not a project with
           the lock -- that one is deleted for good, never into the trash)
Undo of an active project's delete: the newest group (the trash) goes back first, then the archive -> active again; redo the
other way round (core/undoweb.py: undo newest first, the app's redo oldest first).

Interface:
  otr_step(c, lid, uid)   lists.py list_delete, after otr_trash: the step of the person (none for an agent / outside a request)"""
from ..core.access import need_list
from ..core.db import bump
from ..core.errors import Denied
from ..core.i18n import N_, tr
from ..core.undoareas import ua_plain
from ..core.undodiff import ug_diff_add, undo_diff_reg, undo_person
from ..core.undogroups import UG_TRACKED
from ..core.writes import UNDO_CONFLICT
from ..collab.liste2e import le2e_mode
from .listtrash import OTR_HELD, otr_back, otr_can, otr_held, otr_trash

OTR_KIND = "list_trash"
OTR_AREA = "tasks"
OTR_LABEL = N_("Deleted {0}")


def otr_step(c, lid, uid):
    if undo_person(c) is None:
        return
    r = c.execute("SELECT name, org_id, deleted_at FROM lists WHERE id=?", (int(lid),)).fetchone()
    if r is None or not r["deleted_at"]:
        return
    ug_diff_add(c, uid, OTR_KIND, lid, r["org_id"], OTR_AREA, (OTR_LABEL, [ua_plain(r["name"], lid)]),
                {"op": "trash", "at": str(r["deleted_at"])})


def otr_run(c, uid, lid, data, redo):
    """core/undodiff.py run: out of the trash (undo) / into it again (redo); 409 when the project is elsewhere meanwhile."""
    r = c.execute("SELECT * FROM lists WHERE id=? FOR UPDATE", (int(lid),)).fetchone()
    if r is None:
        raise Denied(404)
    if not redo:
        if not r["deleted_at"] or str(r["deleted_at"]) != str(data.get("at") or ""):
            raise Denied(409, tr(UNDO_CONFLICT))  # restored or purged meanwhile, or deleted again since
        if not otr_can(c, uid, r):
            raise Denied(404)
        if otr_held(r, uid):
            raise Denied(409, tr(OTR_HELD))
        # 2.997.2 (#5609 #5709): rights and trash stamp checked above under the row lock; otr_back takes the person since
        # #5491 (the core's restore) - the old call without her failed every undo of a delete (TypeError, a 500)
        otr_back(c, r, uid, checked=True)
    else:
        if r["deleted_at"] or not r["archived"] or r["is_inbox"]:
            raise Denied(409, tr(UNDO_CONFLICT))
        need_list(c, int(lid), write=False, manage=True)  # as the delete route: the owner or a project admin
        if le2e_mode(c, int(lid)):
            raise Denied(409, tr(UNDO_CONFLICT))
        data = {**data, "at": str(otr_trash(c, int(lid), uid))}
    bump(c)
    return data, []


undo_diff_reg(OTR_KIND, otr_run, OTR_AREA)
UG_TRACKED[OTR_KIND] = "lists"  # the watchdog drops the parts of a project deleted for good (core/undogroups.py ug_drop_orphans)
