"""2.809.0 (#5476): undo across devices -- a project's settings (PATCH /api/lists/<id>) in the core's step groups
(core/undoareas.py, the pattern of events/evundo.py).

A project's row (table lists) is the tracked kind "listset" (core/writes.py obj_track; the kind "list" of lists/lmcore.py
stays the one of the shares and the trash): a change of its plain settings records a snap step of the person under the
project's lock (obj-list-<id>, lists.py lv_check), labelled with its name. Plain = a column of the row itself without side
effects elsewhere (LPU_COLS: name, colour, view, archive, sort, grouping, columns, sums, key figures, properties, ticket
templates, hourly rate, hours per day ...). A save that also changes something with side effects (folder, workspace,
project type, agents, client, family / Home & life, time tracking, ticket key, visibility, a member's own view) records no
step: the browser keeps its own way back for it (static/js/dialogs.js listPatch) until those get a step of their own.
Only the plain columns go back (undo_keep = every other column), and only they and the lock's generation count for "changed
since" (undo_nofp): a new sidebar order or a description written meanwhile does not block the undo of a rename.
Taking back (core/undoweb.py): the person needs the role of today that may change those columns -- owner, or a project admin
when the step goes back only in columns an admin may change (name, colour, archive, completed at the bottom, mail for guests,
sort, grouping, columns, sums, key figures, properties); an agent records nothing (obj_undo_pre).

Interface:
  lpu_pre(c, uid, lid, b, role)   before the PATCH writes (after lv_check): a step when b holds only plain settings
  lpu_post(c) -> group id | None  right before its commit (a save of the same values leaves no step)"""
from ..core.access import _list_role
from ..core.errors import Denied
from ..core.objhooks import GONE
from ..core.undoareas import ua_done, ua_plain, ua_pre
from ..core.undoweb import undo_need_reg
from ..core.writes import obj_track
from ..core.errors import BadInput
from ..core.i18n import N_
from .lists import LIST_FIELDS, clean_list_value

LPU_KIND = "listset"
LPU_LABEL = N_("Settings of {0}")  # the keys exist (static/js/dialogs.js)
LPU_ARCH = N_("Archived {0}")
LPU_UNARCH = N_("Restored {0} from the archive")
# body key -> column of the row; only these make a step (lists.py list_update writes them on the row alone)
LPU_KEYS = {"name": "name", "color": "color", "view": "view", "kind": "kind", "dep_shift": "dep_shift", "rate": "rate",
            "archived": "archived", "tickets": "tickets", "nag": "nag", "day_hours": "day_hours", "checklist": "checklist",
            "done_at_bottom": "checklist", "sort_mode": "sort_mode", "done_in_section": "done_in_section",
            "group_field": "group_field", "columns": "col_cfg", "col_sums": "tb_sums", "kpis": "fx_kpis", "props": "props",
            "ticket_tpl": "ticket_tpl", "tap_done": "tap_done", "points_on": "points_on",
            "irreversible_needs_yes": "irreversible_needs_yes", "two_eyes": "two_eyes", "mail_guests": "mail_guests",
            "def_ttype": "def_ttype", "ttypes": "ttypes"}
LPU_META = ("_prev", "expect_updated_at", "folder_adopt")
LPU_COLS = frozenset(LPU_KEYS.values()) | {"archived_at"}
# what a project admin may change of them (list_update: adm, MANAGE_ROLES); the rest is the owner's
LPU_ADMIN = frozenset({"name", "color", "archived", "archived_at", "checklist", "mail_guests", "sort_mode", "group_field",
                       "done_in_section", "tap_done", "props", "col_cfg", "tb_sums", "fx_kpis"})
LPU_E2E = frozenset({"e2e", "e2e_gen", "e2e_rotate", "e2e_reenc"})  # a new key since: the copy's sealed name is old (409)


class _AllBut(frozenset):
    """Every column name except the ones given -- for undo_keep / undo_nofp, which are only asked with `in` (core/writes.py
    _write_back, _fp): the row of a project has some 80 columns and gets new ones, the plain settings are the short list."""
    def __contains__(self, k):
        return not frozenset.__contains__(self, k)


def lpu_label(r):
    return LPU_LABEL, [ua_plain(r.get("name"), r.get("id"))]


obj_track(LPU_KIND, "lists", area="tasks", undo_keep={"lists": _AllBut(LPU_COLS)},
          undo_nofp={"lists": _AllBut(LPU_COLS | LPU_E2E)}, undo_label=lpu_label)
GONE[LPU_KIND] = "lists"  # an account's deletion takes its history / undo rows of the projects that went (core/objhooks.py)


def lpu_plain(b):
    """Does the PATCH body b change only plain settings (and at least one)?"""
    keys = [k for k in b if k not in LPU_META]
    return bool(keys) and all(k in LPU_KEYS for k in keys)


def _same(r, b):
    """Does b only repeat the row's values (its plain columns, cleaned as list_update cleans them)? Then no step: opening a
    group would end the person's way forward (redo) for nothing. Columns with their own cleaning (columns, sums, key figures,
    properties, templates ...) count as a change."""
    for k in (k for k in b if k not in LPU_META):
        col = LPU_KEYS[k]
        if col not in LIST_FIELDS:
            return False
        try:
            v = clean_list_value(col, b[k])
        except BadInput:
            return False  # the route refuses it
        if (v if v not in ("", None) else None) != (r[col] if r[col] not in ("", None) else None):
            return False
    return True


def lpu_pre(c, uid, lid, b, role):
    if role not in ("owner", "admin") or not lpu_plain(b):
        return
    r = c.execute("SELECT * FROM lists WHERE id=?", (int(lid),)).fetchone()
    if r is None or _same(r, b):
        return
    key = LPU_LABEL
    if set(k for k in b if k not in LPU_META) == {"archived"} and bool(b["archived"]) != bool(r["archived"]):
        key = LPU_ARCH if b["archived"] else LPU_UNARCH
    ua_pre(c, uid, LPU_KIND, lid, key, ua_plain(r["name"], lid))


def lpu_post(c):
    return ua_done(c)


def lpu_need(c, uid, rid, oid):
    """Who may take a settings step back now: the owner, a project admin only for the columns an admin may change."""
    role = _list_role(c, int(rid), int(uid))
    if not role:
        raise Denied(404)
    if role not in ("owner", "admin"):
        raise Denied(403)
    if role == "owner":
        return {"lock": f"obj-list-{int(rid)}"}
    was = c.execute("SELECT * FROM lists WHERE id=?", (int(rid),)).fetchone()

    def fix(c):
        now = c.execute("SELECT * FROM lists WHERE id=?", (int(rid),)).fetchone()
        if any(now[k] != was[k] for k in LPU_COLS - LPU_ADMIN if k in now.keys()):
            raise Denied(403)  # the savepoint of the part takes the write back again
    return {"fix": fix, "lock": f"obj-list-{int(rid)}"}


undo_need_reg(LPU_KIND, lpu_need)
