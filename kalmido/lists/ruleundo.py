"""2.809.0 (#5476): undo across devices -- a project's rules in the core's step groups (core/undoareas.py).

A rule (table list_rules) is the tracked kind "list_rule" (obj_track): a change (PATCH /api/rules/<id>), putting it into the
trash (DELETE) and taking it out (POST .../restore) record a snap step of the person, labelled with its name. Taking back
with the rules of today (core/undoweb.py): the project's owner or admins (need_list manage), rules available on the project
(rul_list_ok), never an agent; out of the trash only below the limit of rules per project. A rule runs with the rights of
the person who last set its trigger / action or switched it on (created_by): when the undo brings back another trigger,
action, conditions or switches it on, the actions are checked again with the rights of the person taking it back, who
becomes its owner (as a save does, rule_update); its owner column is never written back from the copy.

Interface:
  rlu_pre(c, uid, rid, what=None)    before the route writes (what: "delete" | "restore" names the step)
  rlu_post(c) -> group id | None     right before its commit"""
from ..core.access import live_sql, need_list
from ..core.errors import BadInput, Denied
from ..core.i18n import tr
from ..core.objhooks import GONE
from ..core.undoareas import UA_DELETED, UA_RESTORED, ua_done, ua_plain, ua_pre
from ..core.undogroups import UG_LABEL
from ..core.undoweb import undo_need_reg
from ..core.writes import obj_track
from .rules import RUL_LIST_MAX, rul_clean, rul_dict, rul_list_ok

RLU_KIND = "list_rule"
RLU_WHAT = {"delete": UA_DELETED, "restore": UA_RESTORED}
RLU_RUN = ("trig", "trig_val", "act", "act_val", "target_list_id", "more_acts", "conds")  # what runs with its owner's rights


def rlu_label(r):
    return UG_LABEL, [ua_plain(r.get("name"), r.get("id"))]


obj_track(RLU_KIND, "list_rules", area="tasks", undo_keep={"list_rules": {"list_id", "org_id", "created_by", "created_at"}},
          undo_label=rlu_label, undo_free=("deleted_at",))
GONE[RLU_KIND] = "list_rules"


def rlu_pre(c, uid, rid, what=None):
    r = c.execute("SELECT name FROM list_rules WHERE id=?", (int(rid),)).fetchone()
    key = RLU_WHAT.get(what or "")
    ua_pre(c, uid, RLU_KIND, rid, *((key, ua_plain(r["name"] if r else "", rid)) if key else ()))


def rlu_post(c):
    return ua_done(c)


def rlu_need(c, uid, rid, oid):
    was = c.execute("SELECT * FROM list_rules WHERE id=?", (int(rid),)).fetchone()
    if was is None:
        raise Denied(404)
    need_list(c, was["list_id"], write=False, manage=True)
    e = rul_list_ok(c, was["list_id"])
    if e:
        raise Denied(409, e)

    def fix(c):
        now = c.execute("SELECT * FROM list_rules WHERE id=?", (int(rid),)).fetchone()
        if was["deleted_at"] and not now["deleted_at"] and c.execute(
                f"SELECT COUNT(*) FROM list_rules WHERE list_id=? AND {live_sql()}", (now["list_id"],)).fetchone()[0] > RUL_LIST_MAX:
            raise Denied(409, tr("At most {0} rules per project", RUL_LIST_MAX))
        if any(now[k] != was[k] for k in RLU_RUN) or (now["active"] and not was["active"]):
            try:  # the chain it brings back, checked with the rights of the person taking it back (rule_update)
                rul_clean(c, now["list_id"], {"actions": rul_dict(c, now)["actions"]}, partial=now)
            except BadInput as e:
                raise Denied(409, str(e)) from None
            c.execute("UPDATE list_rules SET created_by=?, paused_reason='' WHERE id=?", (int(uid), int(rid)))
    return {"fix": fix}


undo_need_reg(RLU_KIND, rlu_need)
