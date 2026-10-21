"""2.43.0 (#1328): calculating with custom fields -- the sum row of a list's number columns and the key figures (tiles)
on a project page. Both are list settings, the same for everyone (owner / list admins change them, PATCH /api/lists/<id>
{col_sums, kpis}); the key figures are computed here over the tasks the viewer may see (a participant: only theirs)."""
import json
import secrets

from flask import g, jsonify

from ..core.config import app
from ..core.db import db, err
from ..core.i18n import tr
from ..core.access import Denied, MANAGE_ROLES, need_list
from ..lists.fields import fmt_num
from ..api.v1 import v1_args, v1_view

FX_AGGS = ("sum", "avg", "count", "min", "max")         # the sum row
FX_KPI_AGGS = ("sum", "count", "avg", "ratio")          # a tile: ratio = sum(field) / sum(field2) in %
FX_KPI_STATES = ("all", "open", "done")
FX_KPI_MAX = 12


def fx_json(s, default):
    try:
        v = json.loads(s) if s else default
    except ValueError:
        return default
    return v if isinstance(v, type(default)) else default


def fx_clean_sums(v):
    """{column key: aggregate} -> the stored text; keys are "f:<field id>" (number / formula fields), "time" or "est"."""
    if not isinstance(v, dict):
        raise ValueError
    out = {}
    for k, a in list(v.items())[:40]:
        if not isinstance(k, str) or len(k) > 20 or a not in FX_AGGS:
            raise ValueError
        out[k] = a
    return json.dumps(out)


def fx_clean_kpis(c, lid, v):
    """[{id?, title, agg, field?, field2?, state?, cond_field?, cond_value?}] -> the stored text (raises ValueError with a
    message for the person)."""
    if not isinstance(v, list) or len(v) > FX_KPI_MAX:
        raise ValueError(tr("At most {0} key figures", FX_KPI_MAX))
    fs = {r["id"]: r for r in c.execute("SELECT id, name, type, options FROM list_fields WHERE list_id=?", (lid,)).fetchall()}
    num = {i for i, f in fs.items() if f["type"] in ("number", "formula", "currency", "rating")}  # 2.156.0 B (#2069): + currency, rating
    out, seen = [], set()
    for k in v:
        if not isinstance(k, dict):
            raise ValueError(tr("Invalid data"))
        title = str(k.get("title") or "").strip()[:60]
        agg = k.get("agg")
        if agg not in FX_KPI_AGGS:
            raise ValueError(tr("Invalid value: {0}", "agg"))
        d = {"id": str(k.get("id") or "")[:16], "title": title, "agg": agg}
        if not d["id"] or d["id"] in seen or not d["id"].replace("-", "").isalnum():
            d["id"] = secrets.token_hex(4)
        seen.add(d["id"])

        def fid(name, need):
            x = k.get(name)
            if x in (None, ""):
                if need:
                    raise ValueError(tr("Choose a number field"))
                return None
            try:
                x = int(x)
            except (TypeError, ValueError):
                raise ValueError(tr("Choose a number field")) from None
            if x not in num:
                raise ValueError(tr("Choose a number field"))
            return x
        d["field"] = fid("field", agg in ("sum", "avg", "ratio"))
        if agg == "ratio":
            d["field2"] = fid("field2", True)
        st = k.get("state") or "all"
        if st not in FX_KPI_STATES:
            raise ValueError(tr("Invalid value: {0}", "state"))
        d["state"] = st
        cf = k.get("cond_field")
        if cf not in (None, ""):
            try:
                cf = int(cf)
            except (TypeError, ValueError):
                raise ValueError(tr("Invalid value: {0}", "cond_field")) from None
            f = fs.get(cf)
            if not f or f["type"] not in ("select", "checkbox"):
                raise ValueError(tr("Only selection fields and checkboxes can be a condition"))
            cv = str(k.get("cond_value") or "")
            if f["type"] == "select" and cv not in {o["id"] for o in fx_json(f["options"], {}).get("options", [])}:
                raise ValueError(tr("{0}: unknown option", f["name"]))
            d["cond_field"], d["cond_value"] = cf, (cv if f["type"] == "select" else ("1" if cv in ("1", "true") else ""))
        if not title:
            d["title"] = fs[d["field"]]["name"] if d.get("field") else tr("Tasks")
        out.append(d)
    return json.dumps(out, ensure_ascii=False)


def fx_list_patch(c, lid, role, b):
    """PATCH /api/lists/<id> {col_sums?, kpis?}: owner / list admins. Returns an error response or None."""
    if role not in MANAGE_ROLES:
        return err(tr("Only the owner and list admins can change this setting"), 403)
    if "col_sums" in b:
        try:
            c.execute("UPDATE lists SET tb_sums=? WHERE id=?", (fx_clean_sums(b["col_sums"]) if b["col_sums"] else None, lid))
        except ValueError:
            return err(tr("Invalid value: {0}", "col_sums"))
    if "kpis" in b:
        try:
            c.execute("UPDATE lists SET fx_kpis=? WHERE id=?", (fx_clean_kpis(c, lid, b["kpis"]) if b["kpis"] else None, lid))
        except ValueError as e:
            return err(str(e) or tr("Invalid value: {0}", "kpis"))
    return None


def fx_list_out(d, r):
    """The list dict for the web client: col_sums + kpis (definitions); the raw columns go."""
    d["col_sums"] = fx_json(r["tb_sums"], {}) if "tb_sums" in r.keys() else {}
    d["kpis"] = fx_json(r["fx_kpis"], []) if "fx_kpis" in r.keys() else []
    d.pop("tb_sums", None)
    d.pop("fx_kpis", None)


def fx_kpi_values(c, lid):
    """[{id, title, agg, value, unit, n}] of list lid over the tasks the current user may see. value = null when nothing
    to compute (no tasks, a ratio over 0)."""
    from ..core.serializers import load_tasks
    r = c.execute("SELECT fx_kpis FROM lists WHERE id=?", (lid,)).fetchone()
    kp = fx_json(r[0] if r else None, [])
    if not kp:
        return []
    fs = {f["id"]: f for f in c.execute("SELECT id, name, type, options FROM list_fields WHERE list_id=?", (lid,)).fetchall()}
    ts = [t for t in load_tasks(c, "list_id=? AND deleted_at IS NULL", (lid,)) if not t.get("context")]
    out = []
    for k in kp:
        sel = []
        for t in ts:
            st = t["status"]
            if (k.get("state") == "open" and st != 0) or (k.get("state") == "done" and st != 2):
                continue
            if k.get("cond_field") and (t.get("fields") or {}).get(str(k["cond_field"])) != (k.get("cond_value") or None):
                continue
            sel.append(t)

        def nums(fid):
            xs = []
            for t in sel:
                v = (t.get("fields") or {}).get(str(fid))
                try:
                    xs.append(float(v)) if v not in (None, "") else None
                except ValueError:
                    pass
            return xs
        val, unit = None, ""
        f = fs.get(k.get("field"))
        if f:
            unit = fx_json(f["options"], {}).get("unit", "") or fx_json(f["options"], {}).get("currency", "")  # 2.156.0 B (#2069)
        if k["agg"] == "count":
            val = len(sel)
            unit = ""
        elif k["agg"] == "sum" and f:
            val = sum(nums(f["id"]))
        elif k["agg"] == "avg" and f:
            xs = nums(f["id"])
            val = sum(xs) / len(xs) if xs else None
        elif k["agg"] == "ratio" and f and fs.get(k.get("field2")):
            a, b2 = sum(nums(f["id"])), sum(nums(k["field2"]))
            val = a / b2 * 100 if b2 else None
            unit = "%"
        out.append({"id": k["id"], "title": k.get("title") or "", "agg": k["agg"],
                    "value": None if val is None else float(fmt_num(val)), "unit": unit, "n": len(sel)})
    return out


def fx_need_kpis(c, lid):
    need_list(c, lid, write=False)
    r = c.execute("SELECT life FROM lists WHERE id=?", (lid,)).fetchone()
    if r and r[0] == "health" and fx_is_agent(getattr(g, "user", None)):  # health lists never reach an agent
        raise Denied(404)


def fx_is_agent(u):
    from ..agents.core import is_agent
    return is_agent(u)


@app.get("/api/lists/<int:lid>/kpis")
def fx_kpis_get(lid):
    """The key figures of a list with their values (everyone who sees the list)."""
    c = db()
    fx_need_kpis(c, lid)
    return jsonify(data=fx_kpi_values(c, lid))


@app.get("/api/v1/lists/<int:lid>/kpis")
@v1_view
def fx_v1_kpis(lid):
    """The key figures of a list for the token API / agents (read; only inside the list, never of a health list)."""
    v1_args(())
    c = db()
    fx_need_kpis(c, lid)
    return jsonify(data=fx_kpi_values(c, lid), next_cursor=None)


def fx_spec(paths, schemas, op, ok, errs, ref, pid):
    """OpenAPI: the key figures of a list (called from openapi_spec)."""
    schemas["KeyFigure"] = {"type": "object", "description": "2.43.0 (#1328): a key figure of a list, computed over the tasks the caller "
                            "may see", "properties": {
        "id": {"type": "string"}, "title": {"type": "string"},
        "agg": {"type": "string", "enum": list(FX_KPI_AGGS), "description": "ratio = sum of field ÷ sum of field2 in %"},
        "value": {"type": ["number", "null"], "description": "null = nothing to compute (no value, a ratio over 0)"},
        "unit": {"type": "string", "description": "the field's unit, % for a ratio, empty for a count"},
        "n": {"type": "integer", "description": "how many tasks were counted"}}}
    paths["/lists/{id}/kpis"] = {"get": op(
        "The key figures of a list (2.43.0)", "Lists",
        ok({"type": "object", "properties": {"data": {"type": "array", "items": ref("KeyFigure")}, "next_cursor": {"type": "null"}}})
        | errs("404"), [pid("id", "List id")],
        desc="Tiles of a project page set up by the owner / list admins (sum, count, average, ratio over number and formula "
             "fields, open / done tasks, a choice as condition). Read-only; only inside a list shared with you; health lists: 404.")}
