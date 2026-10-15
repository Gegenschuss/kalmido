"""Custom fields of a list."""
import json
import math
import re
import secrets
from datetime import date
from flask import jsonify

from ..core.config import app
from ..core.pg import insert_id, like_escape
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, now_utc, uset, usettings
from ..core.access import collab_all, Denied, list_people, list_role, need_list, vis_sql
from ..core.pages import valid_link
from ..lists.lists import COL_MAX, columns_out
from ..tasks.validation import log_act
from ..collab.comments import user_names
from ..personal.timetrack import BadInput
from .formula import fx_check_cycles, fx_compile, fx_display


# ---------------------------------------------------------------- custom fields, package 3
# Defined per list by its owner; values are shared by everyone who sees the list (one value per task and
# field), changed by whoever may change the task (not view-only). A task moved to another list keeps its
# values, but only the fields of its current list are shown / filtered (moving it back brings them back).
# Deleting a field deletes its values. Values are stored as text: number canonical ("12.5"), select =
# option id, date = YYYY-MM-DD, checkbox = "1" (unchecked = no row), person = user id (a member of the list).
FIELD_TYPES = ("text", "number", "select", "date", "checkbox", "person", "url", "formula")  # 2.43.0 (#1328): + formula
FIELD_MAX = 20          # per list
FIELD_PINNED_MAX = 2    # chips on the task rows
COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}")


def field_dict(r, c=None):
    d = {"id": r["id"], "list_id": r["list_id"], "name": r["name"], "type": r["type"],
         "options": json.loads(r["options"] or "{}"), "pinned": int(r["pinned"] or 0), "sort": r["sort"]}
    if r["type"] == "formula" and c is not None:  # 2.43.0 (#1328): the formula with today's field names
        d["options"]["formula"] = fx_display(d["options"].get("expr"), c.execute("SELECT id, name FROM list_fields WHERE list_id=?", (r["list_id"],)).fetchall())
    return d


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
    if ftype == "select":
        items, seen = [], set()
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
        if not items:
            raise BadInput(tr("A selection field needs at least one option"))
        opts["options"] = items
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
    if isinstance(v, (dict, list)):
        raise BadInput(tr("{0}: invalid value", name))
    if t == "formula":  # 2.43.0 (#1328): computed by the server, never written
        raise BadInput(tr("{0} is calculated and cannot be set", name))
    if t == "text":
        return str(v).strip()[:1000] or None
    if t == "url":
        s = str(v).strip()
        if not valid_link(s):  # 2.35.0 (#186): file links too
            raise BadInput(tr("The link must be a web address (https://…) or a file link (smb://…, file://…)"))
        return s
    if t == "number":
        try:
            x = float(str(v).strip().replace(",", "."))
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
            raise BadInput(tr("unknown user")) from None
        if uid not in list_people(c, lid) or (not collab_all() and list_role(c, lid, uid) != "owner"):
            raise BadInput(tr("Only the owner or a member of the list can be assigned"))
        return str(uid)
    raise BadInput(tr("Unknown field type"))


def field_act(c, f, v):
    """Activity data of a changed value (display snapshot: option name, person name)."""
    d = {"id": f["id"], "name": f["name"], "type": f["type"], "v": v}
    if v is not None and f["type"] == "select":
        o = next((o for o in json.loads(f["options"] or "{}").get("options", []) if o["id"] == v), None)
        d["v"] = o["name"] if o else None
    if v is not None and f["type"] == "person":
        d["v"] = user_names(c, [int(v)]).get(int(v), "?")
    if f["type"] == "number":
        d["unit"] = json.loads(f["options"] or "{}").get("unit", "")
    return d


def set_field_values(c, tid, lid, vals, log=True):
    """{field_id: value|null} for task tid in list lid. Validates everything first (BadInput), then writes."""
    if not isinstance(vals, dict):
        raise BadInput(tr("Invalid data"))
    fields = {r["id"]: r for r in c.execute("SELECT * FROM list_fields WHERE list_id=?", (lid,))}
    new = {}
    for k, v in list(vals.items())[:FIELD_MAX * 2]:
        try:
            fid = int(k)
        except (TypeError, ValueError):
            raise BadInput(tr("Invalid data")) from None
        if fid not in fields:
            raise BadInput(tr("Unknown field"))
        new[fid] = field_value(c, fields[fid], v, lid)
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
    if c.execute("SELECT COUNT(*) FROM list_fields WHERE list_id=?", (lid,)).fetchone()[0] >= FIELD_MAX:
        return err(tr("At most {0} fields per list", FIELD_MAX))
    name, ftype, opts = field_clean_def(b)
    if ftype == "formula":
        fx_set(c, lid, b, opts)  # a new field: nothing can use it yet (no cycle)
    pinned = 1 if b.get("pinned") else 0
    if pinned and not fields_pinned_ok(c, lid):
        return err(tr("At most {0} fields can be shown on the task rows", FIELD_PINNED_MAX))
    srt = c.execute("SELECT COALESCE(MAX(sort),0)+1 FROM list_fields WHERE list_id=?", (lid,)).fetchone()[0]
    fid = insert_id(c, "INSERT INTO list_fields(list_id,name,type,options,pinned,sort,created_at) VALUES(?,?,?,?,?,?,?)",
                    (lid, name, ftype, json.dumps(opts, ensure_ascii=False), pinned, srt, iso(now_utc())))
    cc = c.execute("SELECT col_cfg FROM lists WHERE id=?", (lid,)).fetchone()[0]
    if cc:  # 2.14.0 (#425): a list with its own columns shows a new field as its last column
        cols = columns_out(cc, {r[0] for r in c.execute("SELECT id FROM list_fields WHERE list_id=?", (lid,))})
        if cols is not None and len(cols) < COL_MAX:
            c.execute("UPDATE lists SET col_cfg=? WHERE id=?", (json.dumps([*cols, f"f:{fid}"]), lid))
    on = tb_fields_module_on(c, lid)  # 2.39.1 (#1293)
    bump(c)
    c.commit()
    return jsonify({**field_dict(c.execute("SELECT * FROM list_fields WHERE id=?", (fid,)).fetchone(), c), "modules_on": on})


@app.patch("/api/fields/<int:fid>")
def field_update(fid):
    """{name?, options?, pinned?, sort?}: owner and list admins (2.39.1); the type cannot change. Removed select options
    lose their values."""
    b = body()
    c = db()
    r = need_field(c, fid)
    name, _, opts = field_clean_def(b, r)
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
    if r["type"] == "select":
        keep = {o["id"] for o in opts["options"]}
        for (oid,) in c.execute("SELECT DISTINCT value FROM task_field_values WHERE field_id=?", (fid,)).fetchall():
            if oid not in keep:
                c.execute("DELETE FROM task_field_values WHERE field_id=? AND value=?", (fid, oid))
    c.execute("UPDATE list_fields SET name=?, options=? WHERE id=?", (name, json.dumps(opts, ensure_ascii=False), fid))
    bump(c)
    c.commit()
    return jsonify(field_dict(c.execute("SELECT * FROM list_fields WHERE id=?", (fid,)).fetchone(), c))


@app.get("/api/fields/<int:fid>/count")
def field_count(fid):
    """2.40.0 (#1192): how many tasks hold a value of the field (for the delete confirmation); owner and list admins."""
    c = db()
    need_field(c, fid)
    return jsonify(tasks=c.execute("SELECT COUNT(DISTINCT task_id) FROM task_field_values WHERE field_id=?", (fid,)).fetchone()[0],
                   used_by=fx_used_by(c, fid))


def fx_used_by(c, fid):
    """2.43.0 (#1328): names of the formula fields that read field fid (the delete confirmation warns)."""
    r = c.execute("SELECT list_id FROM list_fields WHERE id=?", (fid,)).fetchone()
    if not r:
        return []
    return [f["name"] for f in c.execute("SELECT name, options FROM list_fields WHERE list_id=? AND type='formula' AND id<>?", (r[0], fid))
            if "{#%d}" % fid in (json.loads(f["options"] or "{}").get("expr") or "")]


@app.delete("/api/fields/<int:fid>")
def field_delete(fid):
    c = db()
    need_field(c, fid)
    n = c.execute("DELETE FROM task_field_values WHERE field_id=?", (fid,)).rowcount
    c.execute("DELETE FROM list_fields WHERE id=?", (fid,))
    bump(c)
    c.commit()
    return jsonify(ok=True, values=n)


def search_field_ids(c, uid, q):
    """Task ids whose text / link / select value matches q (fields of the task's current list, visible lists)."""
    ql = q.casefold()
    hits = set()
    for f in c.execute(f"SELECT * FROM list_fields WHERE list_id IN {vis_sql()}", (uid, uid)).fetchall():
        if f["type"] in ("text", "url"):
            hits.update(r[0] for r in c.execute("""SELECT v.task_id FROM task_field_values v JOIN tasks t ON t.id=v.task_id
                                                   WHERE v.field_id=? AND t.list_id=? AND v.value ILIKE ? ESCAPE '\\'""", (f["id"], f["list_id"], f"%{like_escape(q)}%")))
        elif f["type"] == "select":
            oids = [o["id"] for o in json.loads(f["options"] or "{}").get("options", []) if ql in o["name"].casefold()]
            for oid in oids:
                hits.update(r[0] for r in c.execute("""SELECT v.task_id FROM task_field_values v JOIN tasks t ON t.id=v.task_id
                                                       WHERE v.field_id=? AND t.list_id=? AND v.value=?""", (f["id"], f["list_id"], oid)))
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
