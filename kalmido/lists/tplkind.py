"""2.905.0 (#5288, stage Q10 of the cross-cutting core, analysis #3563, decided 08.11.2026): task, project and section templates
are ONE kind of the shared core, "template" (docs/dev/kern.md), on the table templates (kind task | list | sections).

Who reads / changes a template is the core's role (core/objects.py obj_role), no rule of its own any more (was tpl_may_write /
tpl_space / tpl_visible_sql in lists/templates.py and a copy sct_* in lists/sectpl.py):
  - a private template (org_id NULL): its owner ('manage'); an agent's own too (agent_own: one it made through the API)
  - an organisation's (2.609.0, #3373): every member with the full view reads and uses it (org_access "view"), its admins
    change and delete it, and only they bring one into the organisation or take it out (org_join "admin",
    core/writes.py obj_space_set, out of it logged by accounts/orgout.py); never a template of another organisation (404)
  - routes=False, listed=False: no generic routes and no folder place; the areas' routes stay (lists/templates.py
    /api/templates, lists/sectpl.py /api/section-templates). The trash is the side object's of core/objparts.py (part_kind
    "template" in lists/templates.py); after the trash period the core's run deletes it for good (trash_prune, tk_on_purge:
    its file copies).

This module stands after the core in kalmido ORDER: core/objects.py reaches lists/templates.py at its import (files.fslock ->
collab.e2e -> agents.core -> api.v1 -> PTYPES), so lists/templates.py and lists/sectpl.py call these helpers from inside
their functions. The caller commits."""
from ..accounts.session import me
from ..core.access import Denied
from ..accounts.orgroles import FULL_READ, org_role_key
from ..core.i18n import N_, tr
from ..core.objhooks import obj_rows_drop_many
from ..core.objects import OBJ_RANK, obj_need, obj_register, obj_role, obj_rows
from ..core.writes import obj_on_purge, obj_space_set, obj_touch
from .tplextra import tx_paths

TK_KIND = "template"  # = lists/templates.py TPL_KIND


def _title(c, rid):
    return (c.execute("SELECT name FROM templates WHERE id=?", (int(rid),)).fetchone() or [""])[0]


obj_register(TK_KIND, "templates", label=N_("Template"), fields={}, title=_title, org_access="view", org_join="admin",
             routes=False, listed=False, agent_own=True, trash_prune=True)  # 2.905.0 (#5288): the core's trash run (was tpl_trash_tick)


def tk_on_purge(c, rid):
    """2.905.0 (#5288): the area's part of deleting template rid for good (core/writes.py obj_on_purge; obj_trash_tick after the
    trash period): its undo rows of the person's list (lists/tplundo.py kind list_template) go with it, template_files cascades
    -> the paths of its file copies, removed after the commit."""
    paths = tx_paths(c, rid)
    obj_rows_drop_many(c, "list_template", [rid])
    return paths


obj_on_purge(TK_KIND, tk_on_purge)


def tk_can_edit(c, r, role=None):
    """Does the person have at least 'edit' on template row r (role: already known)? In the trash only 'manage' counts."""
    if role is None:
        role = obj_role(c, me(), TK_KIND, r["id"], row=r)
    return OBJ_RANK[role] >= OBJ_RANK["edit"] and tk_org_admin_ok(c, r)


def tk_org_admin_ok(c, r):
    """2.905.0 (#5288 review F2): an organisation's template is changed only by its admins -- the core's default gives a
    member who owns an object 'manage' (a demoted admin, a member's section template from before 2.905.0); not here."""
    return not r["org_id"] or org_role_key(c, me(), r["org_id"]) == "admin"


def tk_org_sees(c, r):
    """2.905.0 (#5288, Fable review F1): an organisation's template only for its members with the full view (admin, member,
    readonly) -- the core gives its owner 'view' in any role, so a demoted admin (guest, bookkeeping) or an heir would still
    read it; before 2.905.0 the rule asked for the full view (user_orgs_full) too."""
    return not r["org_id"] or org_role_key(c, me(), r["org_id"]) in FULL_READ


def tk_need(c, tid, write, kinds):
    """The live template tid of one of kinds the person sees, else 404; write: edit or more, else 403."""
    row, _ = obj_need(c, me(), TK_KIND, tid, "view")
    if row["kind"] not in kinds or not tk_org_sees(c, row):  # another kind's route: 404 before the right (no 403 that tells it exists)
        raise Denied(404)
    if write:
        obj_need(c, me(), TK_KIND, tid, "write")
        if not tk_org_admin_ok(c, row):  # review F2
            raise Denied(403, tr("Only an administrator of the organisation can change its templates"))
    return row


def tk_rows(c, kinds, limit):
    """[(row, role)] of the live templates of kinds the person sees."""
    rows = obj_rows(c, me(), TK_KIND, where="o.kind IN (" + ",".join("?" * len(kinds)) + ")", args=tuple(kinds), limit=limit)
    return [(r, role) for r, role in rows if tk_org_sees(c, r)]  # Fable review F1


def tk_space_set(c, tid, to):
    """Template tid into space to (None = private) through the core -> (row, moved, new owner?). An admin who takes an
    organisation's template out owns it from now on (2.609.0, #3373 review F2: no longer its first maker; the caller seals its
    file copies for them)."""
    uid = me()
    row, moved = obj_space_set(c, uid, TK_KIND, tid, to)
    if moved and to is None and row["owner_id"] != uid:
        c.execute("UPDATE templates SET owner_id=? WHERE id=?", (uid, tid))
        return row, moved, True
    return row, moved, False


def tk_touch(c, tid):
    """A write path of the area changed template tid: rev, updated_at, updated_by (the core's columns), bump."""
    obj_touch(c, me(), TK_KIND, tid)
