"""2.947.0 (#5367, stage 5 of the core's trash): video sign-offs (video_reviews) on the ONE trash of the core (core/writes.py
obj_trash / obj_restore / obj_trash_prune, docs/dev/kern.md).

The review is registered here as a core object without routes, folder node or listing (like the office kinds,
office/okern.py): its own routes (videos/review.py) check their rules as before and then put the row into the core's trash
(vdr_delete: obj_trash, its open customer link stops) and take it back (vdr_restore: obj_restore, a review without a
place gets a project first) -- without a step of the undo list (step=False): the app's undo is the restore route with that
place check. The core's role: 'manage' for who may change it (vdr_may write: the task / project / client it hangs at, else
its workspace), 'view' for who sees it. Its versions and comments go by FK cascade, so the core's hourly run deletes it after
the trash period (trash_prune=True); videos/review.py vdr_trash_prune keeps only the comments deleted on their own.
The reviews put into the trash before 2.947.0 (and the ones videos/vdrescue.py rescues there before a hard delete) are the
core's trash as they are (deleted_at; deleted_by NULL)."""
from ..core.i18n import N_
from ..core.objects import obj_register, obj_row
from .review import VDR_KIND, vdr_may


def _space(c, rid):
    r = c.execute("SELECT org_id, owner_id FROM video_reviews WHERE id=?", (int(rid),)).fetchone()
    return (r["org_id"] or None, r["owner_id"]) if r is not None else None


def _visible(c, uid):
    """The candidates only (the base role decides each row): its own private ones, those of its organisations, those at a place."""
    u = int(uid)
    return (f"(SELECT id FROM video_reviews WHERE owner_id = {u} OR created_by = {u} OR task_id IS NOT NULL OR list_id IS NOT NULL "
            f"OR client_id IS NOT NULL OR org_id IN (SELECT org_id FROM org_members WHERE user_id = {u}))")


def _base(c, uid, vid):
    r = obj_row(c, VDR_KIND, vid)
    if r is None or not vdr_may(c, uid, r):
        return None
    return "manage" if vdr_may(c, uid, r, write=True) else "view"


obj_register(VDR_KIND, "video_reviews", label=N_("Video sign-off"), fields={}, area="other", routes=False, listed=False,
             fsref=False, space=_space, base_role=_base, visible=_visible, cap=lambda c, uid, rid: None,
             title=lambda c, rid: ((obj_row(c, VDR_KIND, rid) or {"title": ""})["title"] or ""),
             open_url=lambda rid: "videos", trash_prune=True)
