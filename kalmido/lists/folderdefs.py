"""2.757.0 (#4501): more folder defaults through FOLDER_PROPS (lists/folders.py), the same mechanism as the workspace, the
agent or "Hide completed": the default view, the repeat reminder, the hours per day, the hourly rate, "Show the progress
bar" (the owner's own choice, as hide_done), the columns, the custom fields and the project tags. They follow the folder
when a list is created in it, moved into it or the folder default changes; a list changed on its own differs from the
folder until "Back to the folder".

Fields and project tags are their own tables: the folder carries their definitions and a list gets the ones it lacks
(matched by name). Nothing is ever deleted or renamed in a list, so the values of existing tasks stay; a list "differs"
when a folder field / tag was renamed or deleted in it. Columns name custom fields by name ("fn:<name>"), mapped to the
field of the same name in each list (one the list lacks is left out). A value may come from one of my own lists:
{"from": <list id>} takes its columns, fields or tags."""
import json

from ..core.i18n import tr
from ..core.db import uset, usettings
from ..core.errors import BadInput
from ..core.pg import insert_id, qi, write_lock  # 2.757.0 (#4501): qi for the two varying names below
from ..core.db import iso, now_utc
from ..core.ctx import me  # 2.757.0 (#4501): module level (tools/check_layers.py)
from ..core.numtext import user_num
from ..lists.lists import COL_KEYS, COL_MAX, LIST_VIEWS, clean_color, columns_out

FDF_KEYS = ("view", "fields", "columns", "ltags", "nag", "day_hours", "rate", "show_progress")  # fields before columns (they map by name)
FDF_FROM = ("columns", "fields", "ltags")  # may come from one of my own lists: {"from": list id}
FDF_NO_FIELD = ("formula",)  # a formula names other fields by id: not carried by a folder


def fdf_from(c, uid, v):
    """{"from": id} -> the list id when it is my own list (BadInput else)."""
    lid = v.get("from") if isinstance(v, dict) else None
    if isinstance(lid, bool) or not isinstance(lid, int):
        return None
    r = c.execute("SELECT owner_id FROM lists WHERE id=? AND is_inbox=0", (lid,)).fetchone()
    if not r or r[0] != uid:
        raise BadInput(tr("Invalid value: {0}", "from"))
    return lid


def fdf_fields_of(c, lid):
    return [{"name": r["name"], "type": r["type"], "options": json.loads(r["options"] or "{}"), "pinned": bool(r["pinned"])}
            for r in c.execute("SELECT name, type, options, pinned FROM list_fields WHERE list_id=? ORDER BY sort, id", (lid,))
            if r["type"] not in FDF_NO_FIELD]


def fdf_cols_of(c, lid):
    names = {r[0]: r[1] for r in c.execute("SELECT id, name FROM list_fields WHERE list_id=?", (lid,))}
    cols = columns_out(c.execute("SELECT col_cfg FROM lists WHERE id=?", (lid,)).fetchone()[0], set(names))
    if cols is None:
        return "default"
    return [f"fn:{names[int(k[2:])]}" if k.startswith("f:") else k for k in cols]


def fdf_tags_of(c, lid):
    return [{"name": r[0], "color": r[1] or ""} for r in c.execute("SELECT name, color FROM list_tags WHERE list_id=? ORDER BY sort, lower(name)", (lid,))]


def fdf_clean(c, uid, k, v):
    """One folder default from the client -> the stored value (BadInput)."""
    bad = BadInput(tr("Invalid value: {0}", k))
    src = fdf_from(c, uid, v) if k in FDF_FROM else None
    if k == "view":
        if v not in LIST_VIEWS:
            raise bad
        return v
    if k == "nag":
        from ..tasks.validation import NAG_VALUES
        v = "off" if v in ("", "off") else v  # stored "off": "" would read as "not set" in the dialog
        if v != "off" and v not in NAG_VALUES:
            raise bad
        return v
    if k == "day_hours":
        from ..personal.timetrack import clean_day_hours
        dh = clean_day_hours(v)
        if dh in (None, False) or isinstance(v, bool):
            raise BadInput(tr("Hours per day: a number from 1 to 24"))
        return dh
    if k == "rate":
        try:
            x = round(user_num(v), 2) if not isinstance(v, bool) else None
        except (TypeError, ValueError):
            x = None
        if x is None or not 0 <= x <= 1e6:
            raise BadInput(tr("Hourly rate: number expected"))
        return x
    if k == "show_progress":
        if not isinstance(v, bool) and v not in (0, 1):
            raise bad
        return bool(v)
    if k == "columns":
        if src is not None:
            return fdf_cols_of(c, src)
        if v == "default":
            return v
        if not isinstance(v, list) or len(v) > COL_MAX:
            raise bad
        out = []
        for x in v:
            if not isinstance(x, str) or not (x in COL_KEYS or (x.startswith("fn:") and 0 < len(x[3:].strip()) <= 60)):
                raise BadInput(tr("Unknown column: {0}", str(x)[:40]))
            if x.startswith("fn:"):
                x = "fn:" + x[3:].strip()  # review: a name with blanks around it would never match a field
            if x not in out:
                out.append(x)
        return out
    if k == "fields":
        from ..lists.fields import FIELD_MAX, field_clean_def
        v = fdf_fields_of(c, src) if src is not None else v
        if not isinstance(v, list) or len(v) > FIELD_MAX:
            raise bad
        out, seen = [], set()
        for x in v:
            if not isinstance(x, dict) or x.get("type") in FDF_NO_FIELD:
                raise bad
            name, ftype, opts = field_clean_def(x)
            if name.casefold() not in seen:
                seen.add(name.casefold())
                out.append({"name": name, "type": ftype, "options": opts, "pinned": bool(x.get("pinned"))})
        return out
    if k == "ltags":
        from ..collab.reactions import LTAG_MAX, clean_ltag_name  # LTAG_MAX through reactions: no upward import (check_layers)
        v = fdf_tags_of(c, src) if src is not None else v
        if not isinstance(v, list) or len(v) > LTAG_MAX:
            raise bad
        out, seen = [], set()
        for x in v:
            x = {"name": x} if isinstance(x, str) else x
            if not isinstance(x, dict):
                raise bad
            n = clean_ltag_name(x.get("name"))
            if n.casefold() not in seen:
                seen.add(n.casefold())
                out.append({"name": n, "color": clean_color(x.get("color") or "")})
        return out
    raise bad


def _names(c, table, lid):
    return {r[0].casefold() for r in c.execute(f"SELECT name FROM {qi(table, ('list_fields', 'list_tags'))} WHERE list_id=?", (lid,))}


def fdf_cols_want(c, lid, v):
    """The folder's columns as list lid would store them (field names -> its field ids); None = the default layout."""
    if v == "default":
        return None
    ids = {r[1].casefold(): r[0] for r in c.execute("SELECT id, name FROM list_fields WHERE list_id=?", (lid,))}
    out = []
    for x in v or []:
        if x.startswith("fn:"):
            fid = ids.get(x[3:].casefold())
            if fid is not None:
                out.append(f"f:{fid}")
        else:
            out.append(x)
    return out


def fdf_prog_ids(c, uid):
    return [x for x in (usettings(c, uid).get("show_progress") or "").split(",") if x]


def fdf_same(c, lid, k, v, uid):
    """True when list lid (of uid) already has the folder value v of key k."""
    if k in ("view", "nag", "day_hours", "rate"):
        cur = c.execute(f"SELECT {k} FROM lists WHERE id=?", (lid,)).fetchone()[0]
        if k == "nag":
            return (cur or "") == ("" if v == "off" else v)
        if k in ("day_hours", "rate"):
            return cur is not None and abs(float(cur) - float(v)) < 0.005
        return (cur or "list") == v
    if k == "show_progress":
        return (str(lid) in fdf_prog_ids(c, uid)) == bool(v)
    if k == "columns":
        fids = {r[0] for r in c.execute("SELECT id FROM list_fields WHERE list_id=?", (lid,))}
        return columns_out(c.execute("SELECT col_cfg FROM lists WHERE id=?", (lid,)).fetchone()[0], fids) == fdf_cols_want(c, lid, v)
    if k == "fields":
        return {x["name"].casefold() for x in v} <= _names(c, "list_fields", lid)
    if k == "ltags":
        return {x["name"].casefold() for x in v} <= _names(c, "list_tags", lid)
    return True


def fdf_apply(c, lid, k, v, uid):
    """Gives list lid (of uid) the folder value v of key k. Fields and tags: only the missing ones are added."""
    if k in ("view", "day_hours", "rate"):
        c.execute(f"UPDATE lists SET {qi(k, ('view', 'day_hours', 'rate'))}=? WHERE id=?", (v, lid))
    elif k == "nag":
        c.execute("UPDATE lists SET nag=? WHERE id=?", ("" if v == "off" else v, lid))
    elif k == "show_progress":
        write_lock(c, f"usettings-{int(uid)}")
        ids = [x for x in fdf_prog_ids(c, uid) if x != str(lid)] + ([str(lid)] if v else [])
        uset(c, uid, "show_progress", ",".join(ids))
    elif k == "columns":
        want = fdf_cols_want(c, lid, v)
        c.execute("UPDATE lists SET col_cfg=? WHERE id=?", (None if want is None else json.dumps(want), lid))
    elif k == "fields":
        from ..lists.fields import FIELD_MAX, fields_pinned_ok, tb_fields_module_on
        have = _names(c, "list_fields", lid)
        n = c.execute("SELECT COUNT(*) FROM list_fields WHERE list_id=?", (lid,)).fetchone()[0]
        added = False
        for x in v:
            if x["name"].casefold() in have:
                continue
            if n >= FIELD_MAX:
                raise BadInput(tr("At most {0} fields per project", FIELD_MAX))
            srt = c.execute("SELECT COALESCE(MAX(sort),0)+1 FROM list_fields WHERE list_id=?", (lid,)).fetchone()[0]
            pinned = 1 if x.get("pinned") and fields_pinned_ok(c, lid) else 0
            insert_id(c, "INSERT INTO list_fields(list_id,name,type,options,pinned,sort,created_at) VALUES(?,?,?,?,?,?,?)",
                      (lid, x["name"], x["type"], json.dumps(x["options"], ensure_ascii=False), pinned, srt, iso(now_utc())))
            have.add(x["name"].casefold())
            n, added = n + 1, True
        if added:
            tb_fields_module_on(c, lid)  # as a field made by hand: the module "Custom fields" is on for the owner
    elif k == "ltags":
        from ..collab.reactions import ltag_get_or_create
        have = _names(c, "list_tags", lid)
        for x in v:
            if x["name"].casefold() in have:
                continue
            i = ltag_get_or_create(c, lid, x["name"], True)  # BadInput at the limit
            if x["color"]:
                c.execute("UPDATE list_tags SET color=? WHERE id=?", (x["color"], i))
            have.add(x["name"].casefold())


def fdf_named_gone(c, lid, table, name):
    """A field / project tag named `name` of list lid was renamed or deleted: when the folder's default carries that name,
    the list differs from the folder from now on (it would come back with the next folder change otherwise)."""
    from ..lists.folders import folder_effective, list_own_mark
    r = c.execute("SELECT owner_id, folder FROM lists WHERE id=?", (lid,)).fetchone()
    if not r or not r["folder"] or r["owner_id"] != me():  # review: only the owner's own change unties the list
        return
    k = "fields" if table == "list_fields" else "ltags"
    v = folder_effective(c, r["owner_id"], r["folder"])[0].get(k)
    if v and (name or "").casefold() in {x["name"].casefold() for x in v}:
        list_own_mark(c, lid, k)


def fdf_prog_sync(c, uid, old_raw, new_raw):
    """The person switched "Show the progress bar" of lists (PATCH /api/settings show_progress): an own list in a folder
    with that default differs from it now (or no longer)."""
    from ..lists.folders import folder_effective, list_own_mark
    old = {x for x in (old_raw or "").split(",") if x}
    new = {x for x in (new_raw or "").split(",") if x}
    for x in old ^ new:
        if not x.isdigit():
            continue
        r = c.execute("SELECT id, owner_id, folder FROM lists WHERE id=?", (int(x),)).fetchone()
        if not r or r["owner_id"] != uid or not r["folder"]:
            continue
        eff = folder_effective(c, uid, r["folder"])[0]
        if "show_progress" in eff:
            list_own_mark(c, r["id"], "show_progress", (x in new) != bool(eff["show_progress"]))
