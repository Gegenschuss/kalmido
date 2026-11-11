"""2.577.0 (#3356): the rules of a saved filter on the server: the same meaning as filterMatch in static/js/views.js (keep the
two in step). GET /api/v1/tasks?filter_id= turns them into SQL conditions on tasks; the caller's where clause keeps deciding
what the person may see, so a rule can only narrow it. Rules come from a client: whatever does not fit matches nothing and
never reaches the SQL as text; every value is a parameter.

Since 2.521.0 (#4479) a filter is a list of conditions, rules = {op: and | or, conds: [{f, op, v}]} (static/js/fltdlg.js);
the older rules (one key per category) convert into the same conditions (flt_conds of views.js, here _old_conds). A
condition that is off in the app (no values, an empty text, a gone field) is off here too; "is none of" (nin) always holds
on top, also with OR (#4478).

2.846.0 (#5520): the combination of the conditions (hard "none of", AND / OR, the limits) is the shared core's filter
(kalmido/core/filters.py kflt_where); this file is the tasks' catalog: one condition -> SQL."""
import json
from datetime import timedelta

from ..core.access import list_role, vis_sql
from ..core.db import local_now
from ..core.filters import COND_MAX, VAL_MAX, kflt_or as _or, kflt_where
from ..core.pg import like_escape
from ..core.objtags import obj_tag_sql, obj_utag_sql  # 2.947.0 (#5275); 2.955.0 (#5276): obj_utag_sql
from .lists import FOLDER_SEP
from .seckind import SEC_KINDS, SK_SQL

ID_MAX = 2 ** 63 - 1
# what a filter's sort (static/js sortMode) is in GET /api/v1/tasks; the other sorts of the app have no API name
RULE_SORTS = {"prio": "-priority", "custom": "manual", "date": "due", "title": "title", "created": "-created", "created_asc": "created"}
_NUM_RE = "'^-{0,1}[0-9]+([.][0-9]+){0,1}$'"  # no question mark: it is the placeholder
# FLT_OLD of views.js: an old rule key -> the "what" of its condition
_OLD = (("lists", "list"), ("dates", "date"), ("prios", "prio"), ("types", "type"), ("tags", "tag"), ("who", "who"), ("secs", "sec"),
        ("sprints", "sprint"), ("ms", "ms"), ("dlv", "dlv"), ("kinds", "kind"))
# FLT_EMPTY of views.js: the value "op empty" stands for
_EMPTY = {"folder": "", "type": "", "tag": "", "who": "none", "sec": "none", "sprint": "none", "ms": "none", "dlv": "none"}
_CF_TYPES = ("select", "checkbox", "date", "number", "multiselect", "currency", "rating")  # FLT_CFT of fltdlg.js


def _vals(r, k):
    v = r.get(k)
    return v if isinstance(v, list) else []


def _id(x):
    """An id from a rule (a number, or digits as the chips store them) or None."""
    if isinstance(x, bool) or not isinstance(x, (int, str)):
        return None
    if isinstance(x, str) and not (x.isascii() and x.isdigit() and len(x) < 20):
        return None
    return int(x) if 0 < int(x) <= ID_MAX else None


def _date(col, d, t0):
    """dateMatch of views.js on a text column."""
    day = f"NULLIF({col}, '')"
    f = t0.isoformat()

    def plus(n):
        return (t0 + timedelta(days=n)).isoformat()

    return {"nodate": (f"{day} IS NULL", []), "overdue": (f"{day}<?", [f]), "today": (f"{day}=?", [f]), "tomorrow": (f"{day}=?", [plus(1)]),
            "3d": (f"({day}>=? AND {day}<=?)", [f, plus(2)]), "7d": (f"({day}>=? AND {day}<=?)", [f, plus(6)]),
            "month": (f"LEFT({day}, 7)=?", [f[:7]]), "later": (f"{day}>?", [plus(6)])}.get(d) if isinstance(d, str) else None


def _cf_rule_on(cr):
    """cfRuleOn of projects.js."""
    if not isinstance(cr, dict):
        return False
    if any(_vals(cr, k) for k in ("sel", "chk", "date")):
        return True
    n = cr.get("num")
    return isinstance(n, dict) and (n.get("op") in ("set", "empty") or (bool(n.get("op")) and n.get("v") not in ("", None)))


def _old_conds(r):
    """flt_conds of views.js: the older rules as conditions."""
    out = [{"f": f, "op": "in", "v": r[k]} for k, f in _OLD if _vals(r, k)]
    for fid, cr in (r.get("cf") if isinstance(r.get("cf"), dict) else {}).items():
        if not _cf_rule_on(cr):
            continue
        k = next((x for x in ("sel", "chk", "date") if _vals(cr, x)), None)
        out.append({"f": "cf", "fid": fid, "k": k, "op": "in", "v": cr[k]} if k else
                   {"f": "cf", "fid": fid, "k": "num", "op": cr["num"].get("op"), "v": cr["num"].get("v")})
    q = r.get("text").strip() if isinstance(r.get("text"), str) else ""
    if q:
        out.append({"f": "text", "op": "has", "v": q})
    return out


def _folder_sql(uid):
    """The folder a person sees a project in (core/state.py visible_lists: the owner's folder when set, else the person's own)."""
    return ("(SELECT COALESCE(NULLIF(l.folder, ''), CASE WHEN l.owner_id=? THEN '' ELSE (SELECT m.folder FROM list_members m "
            "WHERE m.list_id=l.id AND m.user_id=?) END, '') FROM lists l WHERE l.id=tasks.list_id)", [uid, uid])


def _has(f, x, uid, t0):
    """FLT_HAS of views.js: (sql, args) = the task has this one value, None = a value that makes no sense (matches nothing)."""
    if f == "list":
        n = _id(x)
        return ("list_id=?", [n]) if n else None
    if f == "folder":
        if not isinstance(x, str):
            return None
        col, a = _folder_sql(uid)
        if x == "":
            return f"{col}=''", a
        return f"({col}=? OR LEFT({col}, ?)=?)", [*a, x, *a, len(x) + len(FOLDER_SEP), x + FOLDER_SEP]
    if f == "date":
        return _date("due", x, t0)
    if f == "prio":
        return ("priority=?", [x]) if type(x) is int and abs(x) < 100 else None
    if f == "type":
        return ("COALESCE(ttype, '')=?", [x]) if isinstance(x, str) else None
    if f == "tag":  # a personal tag of the person reading, or a project tag (like tag= of GET /api/v1/tasks)
        if not isinstance(x, str):
            return None
        if x == "":
            return (f"(NOT {obj_utag_sql('tasks.id', 'any')} AND NOT "
                    f"{obj_tag_sql('tasks.id', 'any')})", [uid])  # 2.947.0 (#5275): the core's project tags and labels; 2.955.0 (#5276): + personal
        return (f"({obj_utag_sql('tasks.id')} OR {obj_tag_sql('tasks.id')})", [uid, x, x])  # 2.955.0 (#5276): personal tags of the core, any case
    if f in ("who", "sec", "ms"):
        col = {"who": "assignee_id", "sec": "section_id", "ms": "milestone_id"}[f]
        if x == "none":
            return f"{col} IS NULL", []
        n = uid if f == "who" and x == "me" else _id(x)
        return (f"{col}=?", [n]) if n else None
    if f == "sprint":  # any value but none = the active sprint of the task's project (views.js)
        return ("sprint_id IS NULL", []) if x == "none" else \
            ("sprint_id IN (SELECT id FROM sprints s WHERE s.list_id=tasks.list_id AND s.state='active')", [])
    if f == "dlv":
        return ("delivery=?", ["" if x == "none" else x]) if isinstance(x, str) else None
    if f == "kind":  # 2.577.0 (#3354 + #3356): the state, as ?section_kind= reads it
        return (f"{SK_SQL}=?", [x]) if x in SEC_KINDS else None
    return None


def _cf_kind(ft):
    """flt_cfKind of views.js."""
    return "sel" if ft in ("select", "multiselect") else "chk" if ft == "checkbox" else "date" if ft == "date" else "num"


def _cf_fields(c, uid, cnd):
    """The fields a custom field condition names: [(field row)], at most one per project (flt_cfField); [] = the condition is off."""
    n = _id(cnd.get("fid"))
    if cnd.get("fid") not in (None, "", 0):
        if n is None:
            return []
        f = c.execute("SELECT id, list_id, type, options FROM list_fields WHERE id=?", (n,)).fetchone()
        return [f] if f and list_role(c, f["list_id"]) else []
    name, ft = cnd.get("name"), cnd.get("ft")
    if not isinstance(name, str) or not name.strip() or ft not in _CF_TYPES:
        return []
    rows = c.execute(f"""SELECT id, list_id, type, options FROM list_fields WHERE type=? AND lower(trim(name))=? AND list_id IN {vis_sql()}
                         ORDER BY list_id, sort, id""", (ft, name.strip().lower(), uid, uid)).fetchall()
    seen, out = set(), []
    for r in rows:
        if r["list_id"] not in seen:
            seen.add(r["list_id"])
            out.append(r)
    return out


def _cf_hit(fd, k, cnd, t0):
    """cfMatch of projects.js for one field: (sql, args) on the task's value of that field (the caller binds the project)."""
    n = int(fd["id"])
    val = f"(SELECT v.value FROM task_field_values v WHERE v.task_id=tasks.id AND v.field_id={n})"
    op, v = cnd.get("op"), cnd.get("v")
    if k == "num":
        if op in ("empty", "set"):
            return f"{val} IS {'' if op == 'empty' else 'NOT '}NULL", []
        try:
            y = float(str(v).replace(",", "."))
        except ValueError:
            return "FALSE", []
        if y != y or y in (float("inf"), float("-inf")):
            return "FALSE", []
        return f"(CASE WHEN {val} ~ {_NUM_RE} THEN CAST({val} AS DOUBLE PRECISION) END) {dict(gt='>', lt='<', eq='=')[op]} ?", [y]
    if op == "empty":
        return (_date(val, "nodate", t0) if k == "date" else (f"NULLIF({val}, '') IS NULL", []))
    vs = [x for x in (v if isinstance(v, list) else [])[:VAL_MAX]]
    if k == "chk":
        on, off = "1" in vs, "0" in vs
        return ("TRUE" if on and off else f"{val}='1'" if on else f"{val} IS DISTINCT FROM '1'" if off else "FALSE"), []
    if k == "date":
        return _or([p for p in (_date(val, d, t0) for d in vs) if p])
    ss = [str(x) for x in vs if isinstance(x, (str, int)) and not isinstance(x, bool)]
    if not cnd.get("fid"):  # by option name: this field's options of those names
        try:
            opts = (json.loads(fd["options"] or "{}") or {}).get("options") or []
        except (ValueError, AttributeError):
            opts = []
        names = {s.lower() for s in ss}
        ss = ([""] if "" in names else []) + [str(o.get("id")) for o in opts if isinstance(o, dict) and str(o.get("name") or "").lower() in names]
    ids = [x for x in ss if x]
    parts = [(f"? = ANY(string_to_array({val}, ','))", [x]) for x in ids] if fd["type"] == "multiselect" else [(f"{val}=?", [x]) for x in ids]
    if "" in ss:
        parts.append((f"NULLIF({val}, '') IS NULL", []))
    return _or(parts)


def _cond(c, uid, cnd, t0):
    """flt_cond of views.js: one condition -> (sql, args) that is TRUE / FALSE, or None (off)."""
    if not isinstance(cnd, dict):
        return None
    f, op, v = cnd.get("f"), cnd.get("op"), cnd.get("v")
    if f == "text":
        q = v.strip() if isinstance(v, str) else ""
        if not q:
            return None
        like = "%" + like_escape(q) + "%"
        w = "COALESCE((title ILIKE ? ESCAPE '\\' OR content ILIKE ? ESCAPE '\\'), FALSE)"
        return (f"NOT {w}" if op == "nhas" else w), [like, like]
    if f == "cf":
        if op in ("in", "nin") and not (isinstance(v, list) and v):
            return None
        if op in ("gt", "lt", "eq") and v in ("", None):
            return None
        if op not in ("in", "nin", "empty", "gt", "lt", "eq", "set"):
            return None
        fields = _cf_fields(c, uid, cnd)
        if not fields:
            return None
        parts = []
        for fd in fields:
            k = cnd.get("k") if cnd.get("k") in ("sel", "chk", "date", "num") else _cf_kind(fd["type"])
            w, a = _cf_hit(fd, k, cnd, t0)
            parts.append((f"(list_id=? AND {w})", [fd["list_id"], *a]))
        w, a = _or(parts)
        return (f"NOT {w}" if op == "nin" else w), a  # a task of a project without the field: none of the values
    if f not in _EMPTY and f not in ("list", "date", "prio", "kind"):
        return None
    if op == "empty":
        if f not in _EMPTY:
            return None
        p = _has(f, _EMPTY[f], uid, t0)
        return _or([p] if p else [])
    if op not in ("in", "nin") or not isinstance(v, list) or not v:
        return None
    w, a = _or([p for p in (_has(f, x, uid, t0) for x in v[:VAL_MAX]) if p])
    return (f"NOT {w}" if op == "nin" else w), a


def filter_where(c, uid, rules):
    """The rules of a filter -> (one SQL condition on tasks or None, args): the "none of" conditions always, the others combined
    by rules.op (filterMatch of views.js; the core's kflt_where, only nin holds on top for tasks)."""
    t0 = local_now().date()
    return kflt_where(rules, lambda cnd: _cond(c, uid, cnd, t0), _old_conds, hard_ops=("nin",))


def rule_kinds(rules):
    """True when the rules ask for a column meaning (a kind condition "is one of" / old rules.kinds): GET /api/v1/tasks then looks
    at every status, like ?section_kind= (done means the completed ones)."""
    r = rules if isinstance(rules, dict) else {}
    if isinstance(r.get("conds"), list):
        return any(isinstance(x, dict) and x.get("f") == "kind" and x.get("op") == "in" and x.get("v") for x in r["conds"][:COND_MAX])
    return bool(_vals(r, "kinds"))


def rule_sort(rules):
    """The sort a filter brings along, as GET /api/v1/tasks names it, or None."""
    return RULE_SORTS.get(rules.get("sort")) if isinstance(rules, dict) and isinstance(rules.get("sort"), str) else None
