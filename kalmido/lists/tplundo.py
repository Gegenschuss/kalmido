"""2.809.0 (#5476): undo across devices -- the person's templates in the core's step groups (core/undoareas.py).

A template (table templates) is the tracked kind "list_template" (obj_track): renaming it (PATCH /api/templates/<id> with
only a name), putting it into the trash (DELETE) and taking it out (POST .../restore) record a snap step of the person under
the template's lock (template-<id>, core/objparts.py), labelled with its name. A change of its content or its space (its
file copies are pruned / re-sealed on such a save) records no step: the browser keeps its own way back for it. Only the
name and the trash flag go back (undo_keep = the rest). Taking back with the rules of today (core/undoweb.py): its own
private template, or an organisation's template the person may change (tpl_may_write); out of the trash only within the
limit of its space (TPL_MAX_PER_USER), as the restore route.

Interface:
  tpu_plain(b) -> bool              does a PATCH body change only the name
  tpu_pre(c, uid, tid, what=None)   under the template's lock, before the write ("delete" | "restore" names the step)
  tpu_post(c) -> group id | None    right before the commit"""
from ..accounts.orgroles import user_orgs_full
from ..core.access import live_sql
from ..core.errors import Denied
from ..core.i18n import tr
from ..core.objhooks import GONE
from ..core.undoareas import UA_DELETED, UA_RESTORED, ua_done, ua_plain, ua_pre
from ..core.undogroups import UG_LABEL
from ..core.undoweb import undo_need_reg
from ..core.writes import obj_track
from .templates import TPL_MAX_PER_USER, tpl_may_write

TPU_KIND = "list_template"
TPU_WHAT = {"delete": UA_DELETED, "restore": UA_RESTORED}
TPU_META = ("expect_updated_at", "_prev")


def tpu_label(r):
    return UG_LABEL, [ua_plain(r.get("name"), r.get("id"))]


obj_track(TPU_KIND, "templates", area="tasks",
          undo_keep={"templates": {"user_id", "org_id", "kind", "data", "extra", "created_at", "deleted_by"}},
          undo_label=tpu_label, undo_free=("deleted_at",))
GONE[TPU_KIND] = "templates"


def tpu_plain(b):
    keys = [k for k in b if k not in TPU_META]
    return keys == ["name"]


def tpu_pre(c, uid, tid, what=None):
    r = c.execute("SELECT name FROM templates WHERE id=?", (int(tid),)).fetchone()
    key = TPU_WHAT.get(what or "")
    ua_pre(c, uid, TPU_KIND, tid, *((key, ua_plain(r["name"] if r else "", tid)) if key else ()))


def tpu_post(c):
    return ua_done(c)


def tpu_need(c, uid, rid, oid):
    was = c.execute("SELECT * FROM templates WHERE id=?", (int(rid),)).fetchone()
    if was is None or not (was["user_id"] == int(uid) if was["org_id"] is None else was["org_id"] in user_orgs_full(c, uid)):
        raise Denied(404)
    if not tpl_may_write(c, was):
        raise Denied(403)

    def fix(c):
        now = c.execute("SELECT deleted_at, org_id FROM templates WHERE id=?", (int(rid),)).fetchone()
        if was["deleted_at"] and not now["deleted_at"]:  # the limit of its space, itself counted (tpl_room before a restore)
            q, a = ("org_id=?", now["org_id"]) if now["org_id"] else ("org_id IS NULL AND user_id=?", int(uid))
            if c.execute(f"SELECT COUNT(*) FROM templates WHERE {q} AND {live_sql()}", (a,)).fetchone()[0] > TPL_MAX_PER_USER:
                raise Denied(409, tr("At most {0} templates", TPL_MAX_PER_USER))
    return {"fix": fix, "lock": f"template-{int(rid)}"}


undo_need_reg(TPU_KIND, tpu_need)
