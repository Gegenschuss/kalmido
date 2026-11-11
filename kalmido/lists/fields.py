"""Custom fields of a list."""
import json
import math
import re
import secrets
from datetime import date
from flask import g, has_app_context, jsonify, request

from ..core.config import app
from ..core.pg import insert_id, like_escape, st_ids, system_ctx, write_lock
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, now_utc, uset, usettings
from ..core.access import collab_all, Denied, list_people, list_role, need_list, pvis, task_visible, vis_sql
from ..core.access import live_sql  # 2.783.0 (#5368)
from ..core.pages import valid_link
from ..lists.lists import COL_MAX, columns_out
from ..tasks.validation import log_act
from ..collab.comments import user_names
from ..core.errors import BadInput
from ..core.conflict import Conflict  # 2.564.0 (#4701)
from ..core.objparts import part_kind, part_write  # 2.610.0 (#4762): the core's write layer of side objects
from ..core.objparts import part_copy, part_copy_back  # 2.783.0 (#5368): the field trash is the core's copy trash
from ..core import objhooks  # 2.783.0 (#5368): ftr_move at every start
from ..core.numtext import user_num  # 2.263.0 (#2976)
from ..core.retention import ret_trash_days  # 2.550.0 (#4528)
from ..lists.folderdefs import fdf_named_gone  # 2.757.0 (#4501)
from .formula import fx_check_cycles, fx_compile, fx_display


# ---------------------------------------------------------------- custom fields, package 3
# Defined per list by its owner; values are shared by everyone who sees the list (one value per task and
# field), changed by whoever may change the task (not view-only). A task moved to another list keeps its
# values, but only the fields of its current list are shown / filtered (moving it back brings them back).
# Deleting a field deletes its values. Values are stored as text: number canonical ("12.5"), select =
# option id, date = YYYY-MM-DD, checkbox = "1" (unchecked = no row), person = user id (a member of the list).
# 2.156.0 B (#2069): multiselect = option ids joined by "," (in the order of the options), currency = number canonical (the
# currency is the field's option), rating = "1".."max" (0 = no row), task = id of a task the person who set it could see.
FIELD_TYPES = ("text", "number", "select", "date", "checkbox", "person", "url", "formula",  # 2.43.0 (#1328): + formula
               "multiselect", "currency", "rating", "task")  # 2.156.0 B (#2069)
FIELD_CURRENCY_RE = re.compile(r"[A-Z]{3}")  # 2.156.0 B (#2069): ISO code of a currency field, EUR when none
FIELD_RATING_MAX = (3, 10, 5)  # 2.156.0 B (#2069): lowest, highest, default maximum of a rating field
FIELD_MAX = 20          # per list
FIELD_PINNED_MAX = 2    # chips on the task rows
COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}")
FIELD_STAGE_SPECIAL = ("red", "orange")  # 2.410.0 A (#3514): the signal colours of a special state of a stage field


def field_dict(r, c=None, names=None):
    """names (2.640.0, #4185): the (id, name) rows of the fields of r's list when the caller has them (field_dicts: the state
    reads the fields of all lists once), else a formula field reads them itself."""
    d = {"id": r["id"], "list_id": r["list_id"], "name": r["name"], "type": r["type"],
         "options": json.loads(r["options"] or "{}"), "pinned": int(r["pinned"] or 0), "sort": r["sort"],
         "org_field_id": fd_col(r, "org_field_id"),  # 2.609.0 (#3373): linked to a field of the organisation (lists/orgfields.py)
         "required": bool(fd_col(r, "required", 0))}  # 2.609.0 (#3373): needed when a task is created (field_required_check)
    if r["type"] == "formula" and (c is not None or names is not None):  # 2.43.0 (#1328): the formula with today's field names
        if names is None:
            names = c.execute("SELECT id, name FROM list_fields WHERE list_id=?", (r["list_id"],)).fetchall()
        d["options"]["formula"] = fx_display(d["options"].get("expr"), names)
    return d


def field_dicts(rows):
    """2.640.0 (#4185): field_dict of every row, the formulas named from the same rows (rows = ALL the fields of each of their
    lists, as the state's query reads them) instead of one query per formula field."""
    by = {}
    for r in rows:
        by.setdefault(r["list_id"], []).append(r)
    return [field_dict(r, names=by[r["list_id"]]) for r in rows]


def fd_col(r, k, default=None):
    """2.609.0 (#3373): column k of a list_fields row (None when the query did not select it)."""
    try:
        return r[k]
    except (KeyError, IndexError):
        return default


def field_clean_def(b, old=None):
    """(name, type, options) of a field definition from the client; raises BadInput."""
    name = str(b.get("name", old["name"] if old else "") or "").strip()[:60]
    if not name:
        raise BadInput(tr("Name missing"))
    ftype = old["type"] if old else b.get("type")
    if ftype not in FIELD_TYPES:
        raise BadInput(tr("Unknown field type"))
    raw = b.get("options") if "options" in b else (json.loads(old["options"] or "{}") if old else {})
    raw = raw if isinstance(raw, dict) else {}
    opts = {}
    if ftype in ("number", "formula"):
        unit = str(raw.get("unit") or "").strip()[:12]
        if unit:
            opts["unit"] = unit
    if ftype == "formula":  # 2.43.0 (#1328): expr = stored with field ids (fx_compile in create / update); empty fields = 0 or blank
        opts["expr"] = str(raw.get("expr") or (json.loads(old["options"] or "{}").get("expr") if old else "") or "")[:2000]
        if raw.get("formula"):  # a template carries the formula with names (fx_tpl_fix compiles it in the new list)
            opts["formula"] = str(raw["formula"])[:500]
        if raw.get("empty") == "blank":
            opts["empty"] = "blank"
    if ftype == "currency":  # 2.156.0 B (#2069)
        cur = str(raw.get("currency") or "EUR").strip().upper()[:3]
        opts["currency"] = cur if FIELD_CURRENCY_RE.fullmatch(cur) else "EUR"
    if ftype == "rating":  # 2.156.0 B (#2069): the number of stars, 3 to 10
        try:
            mx = int(raw.get("max") or FIELD_RATING_MAX[2])
        except (TypeError, ValueError):
            mx = FIELD_RATING_MAX[2]
        opts["max"] = min(max(mx, FIELD_RATING_MAX[0]), FIELD_RATING_MAX[1])
    if ftype in ("select", "multiselect"):  # 2.156.0 B (#2069): + multiselect, the same options
        items, seen = [], set()
        # 2.410.0 A (#3514): a client that leaves out "stages" / an option's "special" (API, MCP) keeps the stored ones
        was = json.loads(old["options"] or "{}") if old else {}
        was_sp = {o.get("id"): o.get("special") for o in was.get("options", []) if isinstance(o, dict)}
        for o in (raw.get("options") if isinstance(raw.get("options"), list) else [])[:50]:
            if not isinstance(o, dict):
                continue
            nm = str(o.get("name") or "").strip()[:60]
            if not nm:
                continue
            oid = str(o.get("id") or "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,16}", oid) or oid in seen:
                oid = secrets.token_hex(4)
            seen.add(oid)
            col = str(o.get("color") or "")
            items.append({"id": oid, "name": nm, "color": col if COLOR_RE.fullmatch(col) else ""})
            sp = o.get("special") if "special" in o else was_sp.get(oid)
            if ftype == "select" and sp in FIELD_STAGE_SPECIAL:  # 2.410.0 A (#3514): a special state (signal colour)
                items[-1]["special"] = sp
            elif ftype == "select" and sp:
                raise BadInput(tr("Unknown signal colour"))
        if not items:
            raise BadInput(tr("A selection field needs at least one option"))
        opts["options"] = items
        if ftype == "select" and (raw.get("stages") if "stages" in raw else was.get("stages")):  # 2.410.0 A (#3514): ordered = a stage bar
            opts["stages"] = 1
    return name, ftype, opts


def fx_set(c, lid, b, opts, fid=None):
    """2.43.0 (#1328): the typed formula (b["formula"], field names) -> opts["expr"] with field ids; checks names, types
    and circular references (BadInput with the position / field name)."""
    fs = c.execute("SELECT id, name, type, options FROM list_fields WHERE list_id=?", (lid,)).fetchall()
    # the typed formula, else the stored one again (an options-only change; a client's own expr is checked the same way)
    expr, refs = fx_compile(b["formula"] if "formula" in b else opts.get("expr") or "", fs, fid)
    opts.pop("formula", None)
    if fid is not None:
        fx_check_cycles(fs, fid, refs)
    opts["expr"] = expr


def fmt_num(x):
    s = ("%.6f" % x).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def field_value(c, f, v, lid):
    """Validated stored value of field f (row) for a task in list lid; None = no value. Raises BadInput."""
    t, name = f["type"], f["name"]
    if v is None or v == "" or v is False:
        return None
    if t == "multiselect":  # 2.156.0 B (#2069): a list of option ids (or "a,b"); an empty list = no value
        return fd_multi_value(f, v)
    if isinstance(v, (dict, list)):
        raise BadInput(tr("{0}: invalid value", name))
    if t == "formula":  # 2.43.0 (#1328): computed by the server, never written
        raise BadInput(tr("{0} is calculated and cannot be set", name))
    from ..collab.liste2e import le2a_field_value
    v = le2a_field_value(c, f, v, lid)  # 2.64.1 (#1817): text values of a list with the lock are ciphertexts (others readable, E2)
    if t == "text":
        return v if v.startswith("e2e1:") else str(v).strip()[:1000] or None
    if t == "url":
        s = str(v).strip()
        if not valid_link(s):  # 2.35.0 (#186): file links too
            raise BadInput(tr("The link must be a web address (https://…) or a file link (smb://…, file://…)"))
        return s
    if t in ("number", "currency"):  # 2.156.0 B (#2069): + currency
        try:
            x = user_num(v)  # 2.263.0 (#2976): "1,500" in English = 1500
        except ValueError:
            raise BadInput(tr("{0}: number expected", name)) from None
        if not math.isfinite(x) or abs(x) >= 1e12:
            raise BadInput(tr("{0}: number expected", name))
        return fmt_num(x)
    if t == "date":
        try:
            return date.fromisoformat(str(v)[:10]).isoformat()
        except ValueError:
            raise BadInput(tr("{0}: date expected", name)) from None
    if t == "checkbox":
        return "1" if v in (True, 1, "1", "true") else None
    if t == "select":
        if str(v) not in {o["id"] for o in json.loads(f["options"] or "{}").get("options", [])}:
            raise BadInput(tr("{0}: unknown option", name))
        return str(v)
    if t == "person":
        try:
            uid = int(v)
        except (TypeError, ValueError):
            raise BadInput(tr("unknown person")) from None
        if uid not in list_people(c, lid) or (not collab_all() and list_role(c, lid, uid) != "owner"):
            raise BadInput(tr("Only the owner or a member of the project can be assigned"))
        return str(uid)
    if t == "rating":  # 2.156.0 B (#2069): 1 to max, 0 = no value
        try:
            x = int(str(v).strip())
        except ValueError:
            raise BadInput(tr("{0}: number expected", name)) from None
        mx = json.loads(f["options"] or "{}").get("max") or FIELD_RATING_MAX[2]
        if not 0 <= x <= mx:
            raise BadInput(tr("{0}: a rating from 0 to {1}", name, mx))
        return str(x) if x else None
    if t == "task":  # 2.156.0 B (#2069): a task the person setting it may see (agents the same way)
        try:
            tid = int(str(v).strip().lstrip("#"))
        except ValueError:
            raise BadInput(tr("{0}: task not found", name)) from None
        if tid <= 0 or not c.execute(f"SELECT 1 FROM tasks WHERE id=? AND {live_sql()}", (tid,)).fetchone() \
                or not task_visible(c, tid, fd_uid()):
            raise BadInput(tr("{0}: task not found", name))
        return str(tid)
    raise BadInput(tr("Unknown field type"))


def fd_uid():
    """2.156.0 B (#2069): the person of the request (None outside one: nothing can be linked then)."""
    u = g.get("user") if has_app_context() else None
    return u["id"] if u else None


def fd_multi_value(f, v):
    """2.156.0 B (#2069): the stored value of a multiselect: known option ids in the order of the options, None when empty."""
    if isinstance(v, str):
        v = [x for x in v.split(",") if x.strip()]
    if not isinstance(v, list) or len(v) > 50:
        raise BadInput(tr("{0}: invalid value", f["name"]))
    ids = [o["id"] for o in json.loads(f["options"] or "{}").get("options", [])]
    want = {str(x).strip() for x in v}
    if want - set(ids):
        raise BadInput(tr("{0}: unknown option", f["name"]))
    return ",".join(i for i in ids if i in want) or None


def field_act(c, f, v):
    """Activity data of a changed value (display snapshot: option name, person name)."""
    d = {"id": f["id"], "name": f["name"], "type": f["type"], "v": v}
    if v is not None and f["type"] == "select":
        o = next((o for o in json.loads(f["options"] or "{}").get("options", []) if o["id"] == v), None)
        d["v"] = o["name"] if o else None
    if v is not None and f["type"] == "multiselect":  # 2.156.0 B (#2069): the option names
        on = {o["id"]: o["name"] for o in json.loads(f["options"] or "{}").get("options", [])}
        d["v"] = ", ".join(on.get(x, "?") for x in v.split(","))
    if v is not None and f["type"] == "person":
        d["v"] = user_names(c, [int(v)]).get(int(v), "?")
    if f["type"] == "number":
        d["unit"] = json.loads(f["options"] or "{}").get("unit", "")
    if f["type"] == "currency":  # 2.156.0 B (#2069); a task field keeps only the id (its title is not for everyone)
        d["unit"] = json.loads(f["options"] or "{}").get("currency", "EUR")
    return d


def set_field_values(c, tid, lid, vals, log=True):
    """{field_id: value|null} for task tid in list lid. Validates everything first (BadInput), then writes."""
    if not isinstance(vals, dict):
        raise BadInput(tr("Invalid data"))
    fields = {r["id"]: r for r in c.execute("SELECT * FROM list_fields WHERE list_id=?", (lid,))}
    new = {}
    top = None
    for k, v in list(vals.items())[:FIELD_MAX * 2]:
        try:
            fid = int(k)
        except (TypeError, ValueError):
            raise BadInput(tr("Invalid data")) from None
        if fid not in fields:
            raise BadInput(tr("Unknown field"))
        new[fid] = field_value(c, fields[fid], v, lid)
        if new[fid] is None and fd_col(fields[fid], "required", 0):  # 2.609.0 (#3373): a required field is not cleared
            if top is None:
                top = not c.execute("SELECT parent_id FROM tasks WHERE id=?", (tid,)).fetchone()[0]
            if top:
                raise BadInput(tr("Required field missing: {0}", fields[fid]["name"]))
    for fid, v in new.items():
        old = c.execute("SELECT value FROM task_field_values WHERE task_id=? AND field_id=?", (tid, fid)).fetchone()
        if (old[0] if old else None) == v:
            continue
        if v is None:
            c.execute("DELETE FROM task_field_values WHERE task_id=? AND field_id=?", (tid, fid))
        else:
            c.execute("INSERT INTO task_field_values(task_id,field_id,value) VALUES(?,?,?) "
                      "ON CONFLICT(task_id,field_id) DO UPDATE SET value=excluded.value", (tid, fid, v))
        if log:
            log_act(c, tid, "field", field_act(c, fields[fid], v))
    return bool(new)


FIELD_REQ_OFF = ("formula", "checkbox")  # 2.609.0 (#3373): computed / an unticked box is a value: never required


def field_required_set(c, fid, ftype, v):
    """2.609.0 (#3373): the required switch of field fid (BadInput for a formula / checkbox field)."""
    on = 1 if v else 0
    if on and ftype in FIELD_REQ_OFF:
        raise BadInput(tr("This kind of field cannot be required"))
    c.execute("UPDATE list_fields SET required=? WHERE id=?", (on, fid))


def field_required_check(c, tid, lid):
    """2.609.0 (#3373): a new top-level task of list lid needs a value in every required field (BadInput naming the missing
    ones). Only when it is created in the app or through API v1 / MCP (tasks.py FREQ_ENDPOINTS); existing tasks only when the
    field itself is changed (set_field_values); never when a task is completed. 2.609.0: a task an inner flow makes (CalDAV,
    a saved chat, an event, git, an incoming webhook, a template, a copy, a repeat, an agent proposal) is not checked."""
    miss = [r["name"] for r in c.execute("""SELECT f.name FROM list_fields f WHERE f.list_id=? AND f.required=1 AND NOT EXISTS
                                            (SELECT 1 FROM task_field_values v WHERE v.task_id=? AND v.field_id=f.id) ORDER BY f.sort, f.id""",
                                         (lid, tid))]
    if miss:
        raise BadInput(tr("Required field missing: {0}", ", ".join(miss)))


def need_field(c, fid, owner=True):
    r = c.execute("SELECT * FROM list_fields WHERE id=?", (fid,)).fetchone()
    if not r:
        raise Denied(404)
    need_list(c, r["list_id"], write=owner, manage=owner)  # 2.39.1 (#1327): owner and list admins
    return r


def tb_fields_module_on(c, lid):
    """2.39.1 (#1293): custom fields created or shown as columns switch the module "Custom fields" on for the list's owner
    (like project_type does for its modules); nothing is switched off. Returns ["fields"] when it was switched on, else []."""
    r = c.execute("SELECT owner_id FROM lists WHERE id=?", (lid,)).fetchone()
    if not r or not r[0]:
        return []
    write_lock(c, f"usettings-{int(r[0])}")  # 2.528.0 B (#4305, A11): the owner's modules read-change-write like PATCH /api/settings
    fs = [x for x in (usettings(c, r[0]).get("features") or "").split(",") if x]
    if "fields" in fs:
        return []
    uset(c, r[0], "features", ",".join(fs + ["fields"]))
    return ["fields"]


def fields_pinned_ok(c, lid, fid=None):
    n = c.execute("SELECT COUNT(*) FROM list_fields WHERE list_id=? AND pinned=1 AND id IS DISTINCT FROM ?", (lid, fid)).fetchone()[0]
    return n < FIELD_PINNED_MAX


@app.post("/api/lists/<int:lid>/fields")
def field_create(lid):
    """{name, type, options?, pinned?}: owner and list admins (2.39.1)."""
    b = body()
    c = db()
    need_list(c, lid, manage=True)  # 2.39.1 (#1217): plain lists too; (#1327): owner and list admins
    write_lock(c, f"list-fields-{int(lid)}")  # 2.577.0 (#4708 2): the count, the sort place and col_cfg read-change-write
    if c.execute("SELECT COUNT(*) FROM list_fields WHERE list_id=?", (lid,)).fetchone()[0] >= FIELD_MAX:
        return err(tr("At most {0} fields per project", FIELD_MAX))
    name, ftype, opts = field_clean_def(b)
    if ftype == "formula":
        fx_set(c, lid, b, opts)  # a new field: nothing can use it yet (no cycle)
    pinned = 1 if b.get("pinned") else 0
    if pinned and not fields_pinned_ok(c, lid):
        return err(tr("At most {0} fields can be shown on the task rows", FIELD_PINNED_MAX))
    srt = c.execute("SELECT COALESCE(MAX(sort),0)+1 FROM list_fields WHERE list_id=?", (lid,)).fetchone()[0]
    fid = insert_id(c, "INSERT INTO list_fields(list_id,name,type,options,pinned,sort,created_at) VALUES(?,?,?,?,?,?,?)",
                    (lid, name, ftype, json.dumps(opts, ensure_ascii=False), pinned, srt, iso(now_utc())))
    if b.get("required"):
        field_required_set(c, fid, ftype, True)  # 2.609.0 (#3373)
    cc = c.execute("SELECT col_cfg FROM lists WHERE id=?", (lid,)).fetchone()[0]
    if cc:  # 2.14.0 (#425): a list with its own columns shows a new field as its last column
        cols = columns_out(cc, {r[0] for r in c.execute("SELECT id FROM list_fields WHERE list_id=?", (lid,))})
        if cols is not None and len(cols) < COL_MAX:
            c.execute("UPDATE lists SET col_cfg=? WHERE id=?", (json.dumps([*cols, f"f:{fid}"]), lid))
    on = tb_fields_module_on(c, lid)  # 2.39.1 (#1293)
    from .fieldundo import fdu_life  # 2.809.0 (#5476): a step of the person's undo list
    ug = fdu_life(c, fid, "create", name, lid, None)
    bump(c)
    c.commit()
    return jsonify({**field_dict(c.execute("SELECT * FROM list_fields WHERE id=?", (fid,)).fetchone(), c), "modules_on": on,
                    **({"undo_group": ug} if ug else {})})


FIELD_KIND = "list_field"  # 2.610.0 (#4762): a custom field, a side object of the core (core/objparts.py); its lock since #4701
# 2.783.0 (#5368): a deleted field waits as the core's copy (list_part_trash, held = its values); the core's run ends it
part_kind(FIELD_KIND, "list_fields", lock="field-{id}", trash_prune=True, copy=True)


@app.patch("/api/fields/<int:fid>")
def field_update(fid):
    """{name?, options?, pinned?, sort?}: owner and list admins (2.39.1); the type cannot change. Removed select options
    lose their values.
    2.564.0 (#4701): under write_lock('field-<id>'); _prev.options = the option list the client saw: a select / multiselect whose
    options changed meanwhile (another admin) -> 409 {"field": the current field}, nothing written. Values are cleared only for
    options of the seen list that this change removes (an option another admin added stays with its values). Without _prev (old
    clients, API) the old behaviour, under the lock."""
    b = body()
    c = db()
    need_field(c, fid)
    # read again under the lock (the state it protects) and checked against what the client saw: the core's write path
    # (2.610.0 #4762, core/objparts.py part_write); the writes below follow under the same lock
    r, _ = part_write(c, FIELD_KIND, fid, b, check=lambda c, r: fd_check_seen(c, r, b))
    name, _, opts = field_clean_def(b, r)
    if fd_col(r, "org_field_id") and (name != r["name"] or opts != json.loads(r["options"] or "{}")):
        # 2.609.0 (#3373): name and options of a linked field are the organisation's (changed there for every project)
        return err(tr("This field belongs to the organisation: change it in the organisation's fields"), 409)
    from .fieldundo import fdu_post, fdu_pre  # 2.809.0 (#5476): a step of the person's undo list
    n0 = fdu_pre(c, fid, r)
    if r["type"] == "formula":
        fx_set(c, r["list_id"], b, opts, fid)
    if "pinned" in b:
        pinned = 1 if b["pinned"] else 0
        if pinned and not r["pinned"] and not fields_pinned_ok(c, r["list_id"], fid):
            return err(tr("At most {0} fields can be shown on the task rows", FIELD_PINNED_MAX))
        c.execute("UPDATE list_fields SET pinned=? WHERE id=?", (pinned, fid))
    if "sort" in b:
        try:
            c.execute("UPDATE list_fields SET sort=? WHERE id=?", (float(b["sort"]), fid))
        except (TypeError, ValueError):
            return err(tr("Invalid data"))
    if "required" in b:
        field_required_set(c, fid, r["type"], b["required"])  # 2.609.0 (#3373)
    # 2.564.0 (#4701): only now, under the lock and after the check above (with _prev the stored list is the seen one), so only
    # options this change removes lose their values, never one another admin added meanwhile
    field_prune_opts(c, fid, r["type"], opts)
    c.execute("UPDATE list_fields SET name=?, options=? WHERE id=?", (name, json.dumps(opts, ensure_ascii=False), fid))
    if name.casefold() != (r["name"] or "").casefold():  # 2.757.0 (#4501): a folder's field renamed -> the list differs
        fdf_named_gone(c, r["list_id"], "list_fields", r["name"])
    ug = fdu_post(c, fid, n0)
    bump(c)
    c.commit()
    return jsonify({**field_dict(c.execute("SELECT * FROM list_fields WHERE id=?", (fid,)).fetchone(), c), **({"undo_group": ug} if ug else {})})


def field_prune_opts(c, fid, ftype, opts):
    """Removed select / multiselect options leave the values of field fid that hold them (2.609.0 (#3373): also used when a
    field of the organisation changes its linked fields)."""
    if ftype == "select":
        keep = {o["id"] for o in opts["options"]}
        for (oid,) in c.execute("SELECT DISTINCT value FROM task_field_values WHERE field_id=?", (fid,)).fetchall():
            if oid not in keep:
                c.execute("DELETE FROM task_field_values WHERE field_id=? AND value=?", (fid, oid))
    if ftype == "multiselect":  # 2.156.0 B (#2069): a removed option leaves the values that hold it
        keep = {o["id"] for o in opts["options"]}
        for (val,) in c.execute("SELECT DISTINCT value FROM task_field_values WHERE field_id=?", (fid,)).fetchall():
            left = ",".join(x for x in val.split(",") if x in keep)
            if left != val:
                if left:
                    c.execute("UPDATE task_field_values SET value=? WHERE field_id=? AND value=?", (left, fid, val))
                else:
                    c.execute("DELETE FROM task_field_values WHERE field_id=? AND value=?", (fid, val))


def fd_check_seen(c, r, b):
    """2.564.0 (#4701): a select / multiselect whose options changed since the client read them (_prev.options) -> 409
    {"field": the current field}. 2.610.0 (#4762): the check of the core's part_write."""
    seen = fd_seen_options(b)
    if seen is not None and r["type"] in ("select", "multiselect") and "options" in b:
        have = json.loads(r["options"] or "{}").get("options") or []
        if fd_opt_sig(have) != fd_opt_sig(seen):
            raise Conflict("field", field_dict(r, c))


def fd_seen_options(b):
    """2.564.0 (#4701): the option list the client saw (_prev.options: the list, or the options object holding it); None = none sent."""
    prev = b.get("_prev") if isinstance(b.get("_prev"), dict) else None
    if not prev or "options" not in prev:
        return None
    v = prev["options"]
    if isinstance(v, dict):
        v = v.get("options")
    return [o for o in v if isinstance(o, dict)] if isinstance(v, list) else None


def fd_opt_sig(opts):
    """2.564.0 (#4701): an option list compared as the client shows it (id, name, colour, signal colour, order)."""
    return [(str(o.get("id") or ""), str(o.get("name") or ""), str(o.get("color") or ""), str(o.get("special") or ""))
            for o in opts if isinstance(o, dict)]


@app.get("/api/fields/<int:fid>/count")
def field_count(fid):
    """2.40.0 (#1192): how many tasks hold a value of the field (for the delete confirmation); owner and list admins."""
    c = db()
    need_field(c, fid)
    return jsonify(tasks=c.execute("SELECT COUNT(DISTINCT task_id) FROM task_field_values WHERE field_id=?", (fid,)).fetchone()[0],
                   used_by=fx_used_by(c, fid), moved=fd_moved_count(c, field_id=fid))


def fd_moved_count(c, field_id=None, list_id=None):
    """2.552.0 (#4561 B12): how many tasks moved to another list since still hold a value of field field_id (or of a field of
    list list_id): the value stays hidden at the old field and goes when that field / list is deleted. A number only, in the
    system context (the task may lie in a list the person does not see)."""
    with system_ctx(c):
        return c.execute("SELECT COUNT(DISTINCT v.task_id) FROM task_field_values v JOIN list_fields f ON f.id=v.field_id "
                         "JOIN tasks t ON t.id=v.task_id WHERE t.list_id IS DISTINCT FROM f.list_id AND "
                         + ("f.id=?" if field_id is not None else "f.list_id=?"), (field_id if field_id is not None else list_id,)).fetchone()[0]


@app.get("/api/fields/task-refs")
def field_task_refs():
    """2.156.0 B (#2069): ?ids=1,2,3 -> {tasks: [{id, title, status, list_id}]} of the linked tasks (task fields) the person may
    see; the others are left out (the client shows "Task not visible", never a title)."""
    c = db()
    try:
        ids = sorted({int(x) for x in (request.args.get("ids") or "").split(",") if x.strip()})[:200]
    except ValueError:
        return err(tr("Invalid data"))
    out = []
    uid = fd_uid()
    seen = {}  # 2.191.0 C (#2593): list id -> visible task ids (None = whole list), decided once per list
    for r in c.execute(f"SELECT id, title, status, list_id FROM tasks WHERE id IN ({','.join('?' * len(ids))}) AND {live_sql()}",
                       ids).fetchall() if ids else []:
        if r["list_id"] not in seen:
            seen[r["list_id"]] = fd_list_vis(c, r["list_id"], uid)
        vis = seen[r["list_id"]]
        if vis is None or r["id"] in vis:
            out.append({"id": r["id"], "title": r["title"], "status": r["status"], "list_id": r["list_id"]})
    return jsonify(tasks=out)


def fd_list_vis(c, lid, uid):
    """2.191.0 C (#2593): the read check of task_visible(c, tid, uid) for all tasks of list lid at once (was per task):
    no role -> empty set, participant -> the pvis visible set of that list, any full role -> None (every task)."""
    role = list_role(c, lid, uid)
    if not role:
        return set()
    if role == "participant":
        return pvis(c, uid, lid)[0]
    return None


def fx_used_by(c, fid):
    """2.43.0 (#1328): names of the formula fields that read field fid (the delete confirmation warns)."""
    r = c.execute("SELECT list_id FROM list_fields WHERE id=?", (fid,)).fetchone()
    if not r:
        return []
    return [f["name"] for f in c.execute("SELECT name, options FROM list_fields WHERE list_id=? AND type='formula' AND id<>?", (r[0], fid))
            if "{#%d}" % fid in (json.loads(f["options"] or "{}").get("expr") or "")]


FTR_MAX = 100  # 2.550.0 (#4528, review F2): deleted fields kept per project (the trash list shows up to 100 as well)
FTR_COLS = ("id", "list_id", "name", "type", "options", "pinned", "sort", "created_at", "required", "org_field_id")  # 2.783.0 (#5368)


@app.delete("/api/fields/<int:fid>")
def field_delete(fid):
    """2.550.0 (#4528): the field goes into the field trash (its definition and every value, also of tasks in the
    trash); Undo / restore within the trash period (POST /api/fields/trash/<id>/restore). Answer: values, trash_id.
    2.783.0 (#5368): the trash is the core's copy trash (core/objparts.py part_copy: list_part_trash, kind FIELD_KIND, snap = the
    field's row, held = {vals, n, grouped}); trash_id = the copy's id."""
    c = db()
    r = need_field(c, fid)
    n, tid = fd_trash(c, r)
    from .fieldundo import fdu_life  # 2.809.0 (#5476): a step of the person's undo list
    ug = fdu_life(c, fid, "delete", r["name"], r["list_id"], tid)
    bump(c)
    c.commit()
    return jsonify(ok=True, values=n, trash_id=tid, **({"undo_group": ug} if ug else {}))


def fd_trash(c, r):
    """2.809.0 (#5476, from field_delete): field row r into the field trash (the core's copy trash) with its values -> (values
    removed, trash id). The caller checked the rights (need_field), bumps and commits."""
    fid = r["id"]
    fdf_named_gone(c, r["list_id"], "list_fields", r["name"])  # 2.757.0 (#4501): a folder's field deleted -> the list differs
    vals = [[v[0], v[1]] for v in c.execute("SELECT task_id, value FROM task_field_values WHERE field_id=? ORDER BY task_id", (fid,))]
    grouped = c.execute("SELECT 1 FROM lists WHERE id=? AND group_field=?", (r["list_id"], f"cf:{fid}")).fetchone()
    tid = part_copy(c, FIELD_KIND, fid, r["list_id"], {"vals": vals, "n": len({v[0] for v in vals}), "grouped": 1 if grouped else 0},
                    fd_uid())
    # review F2: at most FTR_MAX rows per project in the field trash, the oldest go first (no unbounded growth by delete loops)
    c.execute("DELETE FROM list_part_trash WHERE list_id=? AND kind=? AND id NOT IN (SELECT id FROM list_part_trash WHERE list_id=? "
              "AND kind=? ORDER BY deleted_at DESC, id DESC LIMIT ?)", (r["list_id"], FIELD_KIND, r["list_id"], FIELD_KIND, FTR_MAX))
    n = c.execute("DELETE FROM task_field_values WHERE field_id=?", (fid,)).rowcount
    c.execute("DELETE FROM list_fields WHERE id=?", (fid,))
    c.execute("UPDATE lists SET group_field='' WHERE group_field=?", (f"cf:{fid}",))  # 2.144.0 A2 (#2414): no grouping by a gone field
    return n, tid


def fd_trash_purge_text(c, lid):
    """#5565: when the lock of project lid is switched on or a key change is done (collab/liste2e.py le2a_finish), its deleted
    text fields leave the field trash, like its deleted sections (lists/parttrash.py lpt_section_purge_list): their values are
    plain text the lock does not show, or of the old key. Switching off drops only the copies holding ciphertexts
    (collab/liste2eguard.py le2b_trash_cipher_purge, #5563): plain values written while decrypting stay. Fields of other types stay (their values
    are readable in a locked project too, decision E2). At the switch on le2b_scrub (le2b_scrub_trash) ran before and dropped
    the copies already; the call is the safety net there and does the work at the end of a key change (Fable review, finding 6).
    The caller commits. Returns the copies dropped."""
    ids = [r["id"] for r in c.execute("SELECT id, snap, held FROM list_part_trash WHERE list_id=? AND kind=?", (lid, FIELD_KIND)).fetchall()
           if ftr_parts(r)[0].get("type") == "text"]
    if ids:
        c.execute("DELETE FROM list_part_trash WHERE id = ANY(CAST(? AS BIGINT[]))", (st_ids(ids),))
    return len(ids)


def ftr_person():
    """2.550.0 (#4528): the field trash is the app's (people's) way back: an agent's delete waits for a person's approval already."""
    u = getattr(g, "user", None)
    if u is not None and (u["kind"] if "kind" in u.keys() else "user") == "agent":
        raise Denied(403, tr("Not available for agent accounts"))


def ftr_row(c, tid):
    """2.550.0 (#4528): a row of the field trash for its project's owner and admins (404 for everyone else, agents 403)."""
    ftr_person()
    r = c.execute("SELECT * FROM list_part_trash WHERE id=? AND kind=?", (tid, FIELD_KIND)).fetchone()  # 2.783.0 (#5368)
    if not r:
        raise Denied(404)
    need_list(c, r["list_id"], manage=True)
    return r


def ftr_parts(r):
    """2.783.0 (#5368): (the field's row as it was, what hung on it) of a copy in the core's trash."""
    try:
        snap, held = json.loads(r["snap"] or "{}"), json.loads(r["held"] or "{}")
    except ValueError:
        snap, held = {}, {}
    return (snap if isinstance(snap, dict) else {}), (held if isinstance(held, dict) else {})


def ftr_move(c):
    """2.783.0 (#5368): the rows of the old field trash (field_trash, written by a version before 2.783 -- also after a rollback)
    into the core's copy trash with their time; at every start (core/objhooks.START), a no-op once the table is empty. One-way:
    the version before no longer finds the moved rows (their fields stay restorable here until the trash period ends)."""
    if not c.execute("SELECT to_regclass('field_trash')").fetchone()[0]:
        return 0
    n = 0
    with system_ctx(c):  # every workspace's field trash (a start-up step; nothing is handed to a person)
        for r in c.execute("SELECT * FROM field_trash ORDER BY id").fetchall():
            try:
                d = json.loads(r["def"] or "{}")
                vals = json.loads(r["vals"] or "[]")
            except ValueError:
                d, vals = {}, []
            snap = {"id": r["field_id"], "list_id": r["list_id"], "name": r["name"], "type": r["type"],
                    **{k: d.get(k) for k in ("options", "pinned", "sort", "created_at") if k in d}}
            insert_id(c, "INSERT INTO list_part_trash(list_id,kind,ref_id,snap,held,deleted_by,deleted_at) VALUES(?,?,?,?,?,?,?)",
                      (r["list_id"], FIELD_KIND, r["field_id"], json.dumps(snap, ensure_ascii=False, default=str),
                       json.dumps({"vals": vals, "n": r["n"], "grouped": r["grouped"]}, ensure_ascii=False), r["deleted_by"],
                       r["deleted_at"]))
            c.execute("DELETE FROM field_trash WHERE id=?", (r["id"],))
            n += 1
    return n


objhooks.START.append(("ftr_move5368", False, ftr_move))  # 2.783.0 (#5368): every start (rows of an older version too)


@app.get("/api/lists/<int:lid>/fields/trash")
def field_trash_list(lid):
    """2.550.0 (#4528): the deleted fields of a project (newest first) for its owner and admins: {fields: [{id, name, type,
    tasks, deleted_at, deleted_by}], days}."""
    ftr_person()
    c = db()
    need_list(c, lid, manage=True)
    rows = c.execute("SELECT * FROM list_part_trash WHERE list_id=? AND kind=? ORDER BY deleted_at DESC, id DESC "
                     "LIMIT 100", (lid, FIELD_KIND)).fetchall()  # 2.783.0 (#5368): the core's copy trash
    names = user_names(c, list({r["deleted_by"] for r in rows if r["deleted_by"]}))
    out = []
    for r in rows:
        snap, held = ftr_parts(r)
        out.append({"id": r["id"], "name": snap.get("name") or "", "type": snap.get("type") or "", "tasks": int(held.get("n") or 0),
                    "deleted_at": r["deleted_at"], "deleted_by": names.get(r["deleted_by"], "")})
    return jsonify(fields=out, days=ret_trash_days())


@app.post("/api/fields/trash/<int:tid>/restore")
def field_trash_restore(tid):
    """2.550.0 (#4528): a deleted field back with its id and its values -- of the tasks that are still in the project (person
    values only of people who still reach it); the grouping by it when the project has no other one. The row leaves the trash."""
    c = db()
    r = ftr_row(c, tid)
    try:
        fid, n = fd_back(c, r)
    except BadInput as e:
        return err(str(e))
    from .fieldundo import fdu_life  # 2.809.0 (#5476): a step of the person's undo list
    fdu_life(c, fid, "restore", str(ftr_parts(r)[0].get("name") or ""), r["list_id"], None)
    bump(c)
    c.commit()
    return jsonify(ok=True, field=field_dict(c.execute("SELECT * FROM list_fields WHERE id=?", (fid,)).fetchone(), c), values=n)


def fd_back_lock(c, r):
    """#5565 (Fable review, finding 1/2, the class of #5583): before a field copy r comes back (fd_back, and the undo way
    lists/fieldundo.py fdu_life_run before the field's lock) its project's row (FOR UPDATE: a switch / key change finish of the
    lock waits) and the tasks its values name (FOR SHARE, id order: a move of such a task into a locked project waits, or is
    seen when it came first) are held - the order of le2a_finish and le2a_move: project, tasks, then the field's lock.
    Holding them twice in one transaction is a no-op."""
    c.execute("SELECT 1 FROM lists WHERE id=? FOR UPDATE", (r["list_id"],)).fetchone()
    held = ftr_parts(r)[1]
    ids = sorted({v[0] for v in held.get("vals") or [] if isinstance(v, list) and v and isinstance(v[0], int)
                  and not isinstance(v[0], bool) and 0 < v[0] < 2 ** 63})
    if ids:
        c.execute("SELECT id FROM tasks WHERE id = ANY(CAST(? AS BIGINT[])) ORDER BY id FOR SHARE", (st_ids(ids),)).fetchall()


def fd_back(c, r):
    """2.809.0 (#5476, from field_trash_restore): copy r of the field trash (list_part_trash, kind FIELD_KIND) back as the field
    (its id, its values that still fit) -> (field id, values); the copy goes. Denied 409 when the field exists, BadInput at the
    limit of fields; the caller checked the rights (ftr_row), bumps and commits."""
    fd_back_lock(c, r)  # #5565 review: project row, then the tasks named, then (part_copy_back) the field's lock
    r = c.execute("SELECT * FROM list_part_trash WHERE id=? AND kind=?", (r["id"], FIELD_KIND)).fetchone()  # as a mover left it
    if not r:
        raise Denied(404)
    lid, fid = r["list_id"], r["ref_id"]
    snap, held = ftr_parts(r)
    ftype = str(snap.get("type") or "")
    if c.execute("SELECT 1 FROM list_fields WHERE id=?", (fid,)).fetchone():
        raise Denied(409, tr("This field exists already"))
    if c.execute("SELECT COUNT(*) FROM list_fields WHERE list_id=?", (lid,)).fetchone()[0] >= FIELD_MAX:
        raise BadInput(tr("At most {0} fields per project", FIELD_MAX))

    def fix(c, s):  # 2.783.0 (#5368): the row as it was, with what may no longer hold (the pin limit, a gone organisation field)
        for k in [k for k in s if k not in FTR_COLS]:
            s.pop(k)
        s.update(pinned=1 if s.get("pinned") and fields_pinned_ok(c, lid) else 0, options=s.get("options") or "{}",
                 sort=float(s.get("sort") or 0), created_at=s.get("created_at") or iso(now_utc()), name=str(s.get("name") or ""),
                 type=ftype)
        if s.get("org_field_id") and not c.execute("SELECT 1 FROM org_fields WHERE id=?", (s["org_field_id"],)).fetchone():
            s["org_field_id"] = None
    vals = [v[:2] for v in held.get("vals") or [] if isinstance(v, list) and len(v) > 1]
    if ftype == "text" and vals:  # #5565: only values that fit the project's lock now (a 409 while it switches keeps the copy)
        from ..collab.liste2e import le2a_field_back
        vals = le2a_field_back(c, lid, vals)
    part_copy_back(c, FIELD_KIND, r, f"field-{int(fid)}", fix=fix)  # the copy goes (core/objparts.py)
    live = {x[0] for x in c.execute("SELECT id FROM tasks WHERE list_id=? AND id = ANY(CAST(? AS BIGINT[]))",
                                    (lid, st_ids([v[0] for v in vals])))} if vals else set()
    people = None
    if ftype == "person":  # review F1: the rule of fd_value (without collaboration only the owner)
        people = {str(x) for x in list_people(c, lid) if collab_all() or list_role(c, lid, x) == "owner"}
    n = 0
    for t, v in vals:
        if ftype == "task" and not (str(v).isdigit() and c.execute(  # review F1: a task value only to a task still there and visible
                f"SELECT 1 FROM tasks WHERE id=? AND {live_sql()}", (int(v),)).fetchone() and task_visible(c, int(v), fd_uid())):
            continue
        if t in live and (people is None or v in people):
            n += c.execute("INSERT INTO task_field_values(task_id,field_id,value) VALUES(?,?,?) ON CONFLICT DO NOTHING", (t, fid, v)).rowcount
    if held.get("grouped"):
        c.execute("UPDATE lists SET group_field=? WHERE id=? AND COALESCE(group_field,'')=''", (f"cf:{fid}", lid))
    cc = c.execute("SELECT col_cfg FROM lists WHERE id=?", (lid,)).fetchone()[0]
    if cc and f"f:{fid}" not in cc:  # like field_create: a list with its own columns shows it again as its last column
        cols = columns_out(cc, {x[0] for x in c.execute("SELECT id FROM list_fields WHERE list_id=?", (lid,))})
        if cols is not None and f"f:{fid}" not in cols and len(cols) < COL_MAX:
            c.execute("UPDATE lists SET col_cfg=? WHERE id=?", (json.dumps([*cols, f"f:{fid}"]), lid))
    return fid, n


def search_field_ids(c, uid, q):
    """Task ids whose text / link / select value matches q (fields of the task's current list, visible lists)."""
    ql = q.casefold()
    hits = set()
    # 2.281.0 C (#3113): one query per field type instead of one per field (same matches: the field of the task's list)
    fields = c.execute(f"SELECT id, list_id, type, options FROM list_fields WHERE list_id IN {vis_sql()}", (uid, uid)).fetchall()
    if any(f["type"] in ("text", "url") for f in fields):
        hits.update(r[0] for r in c.execute(f"""SELECT v.task_id FROM task_field_values v JOIN tasks t ON t.id=v.task_id
                                               JOIN list_fields f ON f.id=v.field_id AND f.list_id=t.list_id
                                               WHERE f.type IN ('text', 'url') AND f.list_id IN {vis_sql()} AND v.value ILIKE ? ESCAPE '\\'""",
                                            (uid, uid, f"%{like_escape(q)}%")))
    sel, multi = {}, {}  # field id -> matching option ids
    for f in fields:
        if f["type"] in ("select", "multiselect"):
            oids = {o["id"] for o in json.loads(f["options"] or "{}").get("options", []) if ql in o["name"].casefold()}
            if oids:
                (sel if f["type"] == "select" else multi)[f["id"]] = oids
    for want, one in ((sel, True), (multi, False)):
        if not want:
            continue
        for r in c.execute(f"""SELECT v.task_id, v.field_id, v.value FROM task_field_values v JOIN tasks t ON t.id=v.task_id
                               JOIN list_fields f ON f.id=v.field_id AND f.list_id=t.list_id
                               WHERE v.field_id IN ({','.join('?' * len(want))})""", tuple(want)):
            if (r[2] in want[r[1]]) if one else (want[r[1]] & set((r[2] or "").split(","))):  # 2.156.0 B (#2069): multiselect
                hits.add(r[0])
    return hits


def tpl_fields_of(c, lid):
    """List template: the field definitions (in order) + {field id: index}."""
    rows = c.execute("SELECT * FROM list_fields WHERE list_id=? ORDER BY sort, id", (lid,)).fetchall()

    def opts(r):  # 2.43.0 (#1328): a formula travels with field names (the new list's ids differ)
        o = json.loads(r["options"] or "{}")
        if r["type"] == "formula":
            o = {**{k: v for k, v in o.items() if k != "expr"}, "formula": fx_display(o.get("expr"), rows)}
        return o
    return ([{"name": r["name"], "type": r["type"], "options": opts(r), "pinned": int(r["pinned"] or 0)} for r in rows],
            {r["id"]: i for i, r in enumerate(rows)}, {r["id"]: r["type"] for r in rows})


def tpl_clean_fields(defs):
    out = []
    for d in (defs if isinstance(defs, list) else [])[:FIELD_MAX]:
        if not isinstance(d, dict):
            continue
        try:
            name, ftype, opts = field_clean_def(d)
        except BadInput as e:
            raise ValueError(str(e)) from None
        out.append({"name": name, "type": ftype, "options": opts, "pinned": 1 if d.get("pinned") else 0})
    pins = 0
    for d in out:  # at most FIELD_PINNED_MAX pinned
        pins += d["pinned"]
        if pins > FIELD_PINNED_MAX:
            d["pinned"] = 0
    return out


def fx_tpl_fix(c, lid):
    """2.43.0 (#1328): formula fields made from a template (options.formula = names) get their expr with the new list's
    field ids; a formula that does not fit stays empty (no error: the template may be old)."""
    fs = c.execute("SELECT id, name, type, options FROM list_fields WHERE list_id=?", (lid,)).fetchall()
    for f in fs:
        o = json.loads(f["options"] or "{}")
        if f["type"] != "formula" or "formula" not in o:
            continue
        try:
            o["expr"], _ = fx_compile(o["formula"], fs, f["id"])
        except BadInput:
            o["expr"] = ""
        o.pop("formula", None)
        c.execute("UPDATE list_fields SET options=? WHERE id=?", (json.dumps(o, ensure_ascii=False), f["id"]))
