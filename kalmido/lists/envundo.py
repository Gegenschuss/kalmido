"""2.809.0 (#5476): undo across devices, the rest of stage 7 -- a project's environments in the core's step groups
(core/undoareas.py).

An environment (table list_envs) is the tracked kind "env" (core/writes.py obj_track): a change of its name or switches
(PATCH /api/envs/<id>; the webhook alone is no step), removing it and restoring it record a snap step of the person under its
lock (list_envs-<id>), labelled with its name. The webhook's secret is never part of what goes back (an undo never turns an
old link on again: restored, the hook stays off as with the restore route). Taking back (core/undoweb.py): write on the
project NOW (lists/envs.py env_row), a name taken meanwhile by another environment of the project refuses (409). Adding an
environment records none (the browser's step removes it)."""
from ..core.access import live_sql
from ..core.errors import Denied
from ..core.i18n import tr
from ..core.objhooks import GONE
from ..core.undoareas import UA_DELETED, UA_RESTORED, ua_plain, ua_post, ua_pre
from ..core.undogroups import UG_LABEL
from ..core.undoweb import undo_need_reg
from ..core.writes import obj_track
from .envs import env_row

ENU_KIND = "env"
ENU_WHAT = {"delete": UA_DELETED, "restore": UA_RESTORED}


def enu_label(r):
    return UG_LABEL, [ua_plain(r.get("name"), r.get("id"))]


obj_track(ENU_KIND, "list_envs", undo_keep={"list_envs": {"list_id", "sort", "token_hash"}}, undo_nofp={"list_envs": {"token_hash"}},
          undo_label=enu_label, undo_free=("deleted_at",))
GONE[ENU_KIND] = "list_envs"  # history / undo rows of objects that went (core/objhooks.py)


def enu_pre(c, uid, eid, what=None):
    """The person's step before a write of environment eid (after its lock list_envs-<id>); an agent records none."""
    r = c.execute("SELECT name FROM list_envs WHERE id=?", (int(eid),)).fetchone()
    key = ENU_WHAT.get(what or "")
    ua_pre(c, uid, ENU_KIND, eid, *((key, ua_plain(r["name"] if r else "", eid)) if key else ()))


def enu_post(c):
    ua_post(c)


def enu_need(c, uid, rid, oid):
    """Who may take an environment's step back now: write on its project (removed or not)."""
    r = c.execute("SELECT deleted_at FROM list_envs WHERE id=?", (int(rid),)).fetchone()
    if r is None:
        raise Denied(404)
    env_row(c, int(rid), write=True, trashed=bool(r["deleted_at"]))

    def fix(c):
        n = c.execute("SELECT * FROM list_envs WHERE id=?", (int(rid),)).fetchone()
        if n["deleted_at"] is None and c.execute(f"SELECT 1 FROM list_envs WHERE list_id=? AND id<>? AND {live_sql()} AND lower(name)=lower(?)",
                                                  (n["list_id"], int(rid), n["name"])).fetchone():
            raise Denied(409, tr("This name is taken"))
    return {"fix": fix, "lock": f"list_envs-{int(rid)}"}


undo_need_reg(ENU_KIND, enu_need)
