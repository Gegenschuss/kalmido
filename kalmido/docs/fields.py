"""2.153.0 (#2179): custom fields of documents ("Eigene Felder").

Defined per documents workspace (docs/store.py doc_ws: an organisation's 'o<id>' or a person's own 'u<id>') by whoever
manages it -- the organisation's admins, for a person's own documents (also a person without an organisation) that person
-- and only when someone needs them: nothing is preset. Everyone who sees a document sees the fields of its workspace and
their values; whoever may change the document ('edit') sets them, an agent with 'edit' too (marked "set by an agent").

Values are stored as text, sealed with the workspace key like the document's text (doc_seal, ws in the context): number
canonical ("12.5"), money "12.50 EUR" (currency optional), date YYYY-MM-DD, checkbox "1" (unchecked = no row), select =
the option id, text / url as entered. Deleting a field deletes its values. A document moved into another workspace
(files/fsmove.py) takes its values along: the field is found there by name and type or made (df_move). The Paperless
import (paperless/ngx.py) makes its custom fields real fields here (df_from_paperless) instead of lines in the text."""
import json
import math
import re
import secrets
from datetime import date

from flask import jsonify

from ..core.config import app
from ..core.db import body, bump, db, err, insert_id, iso, now_utc
from ..core.i18n import tr
from ..core.access import Denied
from ..accounts.session import me
from . import store as S
from .web import _no_agent, _ws_manage, ws_param

DF_TYPES = ("text", "number", "money", "date", "checkbox", "select", "url")
DF_MAX = 50           # fields per workspace
DF_NAME_MAX = 60
DF_TEXT_MAX = 1000
CTX = "doc_field_values.value"
MONEY_RE = re.compile(r"(-?\d{1,12}(?:\.\d{1,2})?)\s*([A-Za-z€$£]{0,3})")


def _now():
    return iso(now_utc())


def _opts(r):
    try:
        o = json.loads(r["options"] or "{}")
    except ValueError:
        o = {}
    return o if isinstance(o, dict) else {}


def df_rows(c, ws):
    return c.execute("SELECT * FROM doc_fields WHERE ws=? ORDER BY sort, id", (ws,)).fetchall()


def df_def(r):
    d = {"id": r["id"], "name": r["name"], "type": r["type"]}
    if r["type"] == "select":
        d["options"] = _opts(r).get("options", [])
    return d


def df_list(c, ws):
    return [df_def(r) for r in df_rows(c, ws)]


def df_clean_def(b, old=None):
    """(name, type, options) of a definition from the client; raises ValueError(message)."""
    name = re.sub(r"\s+", " ", str(b.get("name", old["name"] if old else "") or "")).strip()[:DF_NAME_MAX]
    if not name:
        raise ValueError(tr("Name missing"))
    ftype = old["type"] if old else b.get("type")
    if ftype not in DF_TYPES:
        raise ValueError(tr("Unknown field type"))
    opts = {}
    if ftype == "select":
        raw = b.get("options") if "options" in b else (_opts(old).get("options") if old else [])
        if isinstance(raw, str):  # "A, B, C" from the simple form
            raw = [{"name": x} for x in raw.split(",")]
        items, seen, names = [], set(), set()
        for o in (raw if isinstance(raw, list) else [])[:50]:
            o = o if isinstance(o, dict) else {"name": o}
            nm = re.sub(r"\s+", " ", str(o.get("name") or "")).strip()[:DF_NAME_MAX]
            if not nm or nm.lower() in names:
                continue
            oid = str(o.get("id") or "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,16}", oid) or oid in seen:
                oid = secrets.token_hex(4)
            seen.add(oid)
            names.add(nm.lower())
            items.append({"id": oid, "name": nm})
        if not items:
            raise ValueError(tr("A selection field needs at least one option"))
        opts["options"] = items
    return name, ftype, opts


def _name_taken(c, ws, name, skip=None):
    return c.execute("SELECT 1 FROM doc_fields WHERE ws=? AND lower(name)=lower(?) AND id IS DISTINCT FROM ?",
                     (ws, name, skip)).fetchone() is not None


def df_create(c, ws, name, ftype, opts, uid=None):
    sort = (c.execute("SELECT COALESCE(MAX(sort), 0) FROM doc_fields WHERE ws=?", (ws,)).fetchone()[0] or 0) + 1
    return insert_id(c, "INSERT INTO doc_fields(org_id, ws, name, type, options, sort, created_by, created_at) VALUES(?,?,?,?,?,?,?,?)",
                     (S.ws_org(ws), ws, name, ftype, json.dumps(opts, ensure_ascii=False), sort, uid, _now()))


def df_may_define(c, ws, uid):
    """2.184.0 B (#2580): may uid define fields of ws -- the check of the field routes (_ws_manage): an organisation's
    admin, for a person's own documents (also without an organisation) that person."""
    if not uid:
        return False
    try:
        _ws_manage(c, ws, uid)
    except Denied:
        return False
    return True


def df_find(c, ws, name, ftype, opts=None, uid=None, make=True):
    """The field (row) of ws with this name and type; made when missing (the name gets " (2)" when another type has it).
    A select field gains the options it lacks (by name). None when the workspace is full. make False (2.184.0 B, #2580:
    no right to define fields there): only an existing field, no new one, no new options; None when there is none."""
    rows = df_rows(c, ws)
    base = re.sub(r"\s+", " ", str(name or "")).strip()[:DF_NAME_MAX] or tr("Field")
    for n in range(1, 20):
        nm = base if n == 1 else f"{base[:DF_NAME_MAX - 5]} ({n})"
        same = [r for r in rows if r["name"].lower() == nm.lower()]
        if same and same[0]["type"] != ftype:
            continue
        if same:
            r = same[0]
            if ftype == "select" and opts and make:
                have = _opts(r).get("options", [])
                names = {o["name"].lower() for o in have}
                more = [o for o in opts.get("options", []) if o["name"].lower() not in names]
                if more:
                    have = have + [{"id": secrets.token_hex(4), "name": o["name"]} for o in more][:max(0, 50 - len(have))]
                    c.execute("UPDATE doc_fields SET options=? WHERE id=?", (json.dumps({"options": have}, ensure_ascii=False), r["id"]))
                    r = c.execute("SELECT * FROM doc_fields WHERE id=?", (r["id"],)).fetchone()
            return r
        if len(rows) >= DF_MAX or not make:
            return None
        if ftype == "select":  # review: options from an import get ids, no doubles, at most 50 (like df_clean_def)
            try:
                opts = df_clean_def({"name": nm, "type": "select", "options": (opts or {}).get("options") or []})[2]
            except ValueError:
                return None
        fid = df_create(c, ws, nm, ftype, opts or {}, uid)
        return c.execute("SELECT * FROM doc_fields WHERE id=?", (fid,)).fetchone()
    return None


def fmt_num(x):
    s = ("%.6f" % x).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def df_value(f, v):
    """The stored (plain) value of field f (row) from the client; None = no value. Raises ValueError(message)."""
    t, name = f["type"], f["name"]
    if v is None or v == "" or v is False:
        return None
    if isinstance(v, (dict, list)):
        raise ValueError(tr("{0}: invalid value", name))
    s = str(v).strip()
    if not s:
        return None
    if t == "text":
        return s[:DF_TEXT_MAX]
    if t == "url":
        from ..core.pages import valid_link
        if not valid_link(s):
            raise ValueError(tr("The link must be a web address (https://…) or a file link (smb://…, file://…)"))
        return s[:2000]
    if t == "number":
        try:
            x = float(s.replace(" ", "").replace(",", "."))
        except ValueError:
            raise ValueError(tr("{0}: number expected", name)) from None
        if not math.isfinite(x) or abs(x) >= 1e12:
            raise ValueError(tr("{0}: number expected", name))
        return fmt_num(x)
    if t == "money":
        raw = s.replace(" ", "")
        if re.search(r"\d,\d{1,2}(?!\d)", raw):  # "1.234,50" -> "1234.50"
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
        m = MONEY_RE.fullmatch(raw.replace("€", "EUR").replace("$", "USD").replace("£", "GBP")) or \
            re.fullmatch(r"([A-Za-z]{3})(-?\d{1,12}(?:\.\d{1,2})?)", raw)
        if not m:
            raise ValueError(tr("{0}: number expected", name))
        amount, cur = (m.group(1), m.group(2)) if m.re is MONEY_RE else (m.group(2), m.group(1))
        return f"{float(amount):.2f} {cur.upper()}".strip()
    if t == "date":
        try:
            return date.fromisoformat(s[:10]).isoformat()
        except ValueError:
            raise ValueError(tr("{0}: date expected", name)) from None
    if t == "checkbox":
        return "1" if v in (True, 1, "1", "true") else None
    if t == "select":
        opts = _opts(f).get("options", [])
        o = next((o for o in opts if o["id"] == s), None) or next((o for o in opts if o["name"].lower() == s.lower()), None)
        if not o:
            raise ValueError(tr("{0}: unknown option", name))
        return o["id"]
    raise ValueError(tr("Unknown field type"))


def df_label(f, v):
    """The value as a person reads it (select: the option's name)."""
    if v is None:
        return None
    if f["type"] == "select":
        o = next((o for o in _opts(f).get("options", []) if o["id"] == v), None)
        return o["name"] if o else None
    return v


def df_values(c, nid, ws):
    """{field id: plain value} of document nid (values that cannot be opened are left out)."""
    out = {}
    for r in c.execute("SELECT field_id, value FROM doc_field_values WHERE node_id=? AND ws=?", (nid, ws)).fetchall():
        v = S.doc_open(c, ws, CTX, r["value"], default=None)
        if v is not None:
            out[r["field_id"]] = v
    return out


def df_json(c, m):
    """The fields of the document's workspace with its values: [{id, name, type, options?, value, label}]."""
    ws = m["ws"]
    vals = df_values(c, m["node_id"], ws)
    out = []
    for r in df_rows(c, ws):
        d = df_def(r)
        d["value"] = vals.get(r["id"])
        d["label"] = df_label(r, d["value"])
        out.append(d)
    return out


def df_index_text(c, nid, ws):
    """The values for the word index of the document (docs/store.py index_text)."""
    rows = {r["id"]: r for r in df_rows(c, ws)}
    return "\n".join(str(df_label(rows[k], v) or "") for k, v in df_values(c, nid, ws).items() if k in rows and rows[k]["type"] != "checkbox")


def df_index_texts(c, ws, nids):
    """2.184.0 B (#2580): df_index_text of many documents of ws at once ({node id: text}): the fields read once, the values
    in one query (the search's check of word prefixes, docs/store.py search_ids)."""
    rows = {r["id"]: r for r in df_rows(c, ws)}
    vals = {int(n): [] for n in nids}
    if not rows or not vals:
        return {n: "" for n in vals}
    q = f"SELECT node_id, field_id, value FROM doc_field_values WHERE ws=? AND node_id IN ({','.join('?' * len(vals))})"
    for r in c.execute(q, (ws, *vals)).fetchall():
        f = rows.get(r["field_id"])
        if not f or f["type"] == "checkbox":
            continue
        v = S.doc_open(c, ws, CTX, r["value"], default=None)
        if v is not None:
            vals[r["node_id"]].append(str(df_label(f, v) or ""))
    return {n: "\n".join(x) for n, x in vals.items()}


def _put(c, nid, ws, fid, v):
    if v is None:
        c.execute("DELETE FROM doc_field_values WHERE node_id=? AND field_id=?", (nid, fid))
        return
    c.execute("""INSERT INTO doc_field_values(node_id, field_id, org_id, ws, value) VALUES(?,?,?,?,?)
                 ON CONFLICT (node_id, field_id) DO UPDATE SET value=excluded.value, org_id=excluded.org_id, ws=excluded.ws""",
              (nid, fid, S.ws_org(ws), ws, S.doc_seal(c, ws, CTX, v)))


def df_set(c, m, vals, by=None):
    """{field id (or, for agents, its name): value|null} on document m (doc_meta row; rights checked by the caller).
    Validates everything first, then writes. by: None = a person (the mark "automatic" goes), "agent" / "import" = marked.
    Returns an error message or None."""
    if not isinstance(vals, dict):
        return tr("Invalid value: {0}", "custom_fields")
    ws, nid = m["ws"], m["node_id"]
    rows = df_rows(c, ws)
    by_id = {str(r["id"]): r for r in rows}
    by_name = {r["name"].lower(): r for r in rows}
    clean = {}
    for k, v in list(vals.items())[:DF_MAX]:
        f = by_id.get(str(k)) or by_name.get(str(k).strip().lower())
        if not f:
            return tr("Unknown field: {0}", str(k)[:60])
        try:
            clean[f["id"]] = df_value(f, v)
        except ValueError as e:
            return str(e)
    if not clean:
        return None
    for fid, v in clean.items():
        _put(c, nid, ws, fid, v)
    auto = S.meta_json(c, m, "auto", {})
    for fid, v in clean.items():
        if by and v is not None:
            auto[f"cf{fid}"] = by
        else:
            auto.pop(f"cf{fid}", None)
    S.meta_set_json(c, nid, ws, "auto", auto)
    return None


def df_move(c, nid, old, new, uid=None, define=None):
    """The values of document nid from workspace old into new (files/fsmove.py fsm_doc, inside its transaction): each field
    found in new by name and type or made there, select values mapped by the option's name, sealed again. 2.184.0 B
    (#2580): only who may define fields of new (df_may_define; define True: the caller decided, e.g. a system move) makes
    a missing field / option there; anyone else gets a refusal naming the field (the whole move is rolled back)."""
    may = df_may_define(c, new, uid) if define is None else bool(define)
    rows = {r["id"]: r for r in df_rows(c, old)}
    vals = []
    for r in c.execute("SELECT field_id, value FROM doc_field_values WHERE node_id=?", (nid,)).fetchall():
        v = S.doc_open(c, old, CTX, r["value"], default=None)
        f = rows.get(r["field_id"])
        if v is None or not f:
            raise Denied(409, tr("A document cannot be opened with its key; nothing was moved"))
        vals.append((f, v))
    c.execute("DELETE FROM doc_field_values WHERE node_id=?", (nid,))
    auto_map = {}
    for f, v in vals:
        opts = _opts(f) if f["type"] == "select" else None
        t = df_find(c, new, f["name"], f["type"], opts, uid, make=may)
        if not t and not may:
            raise Denied(409, tr("An admin adds the field “{0}” in the target workspace first; nothing was moved", f["name"]))
        if not t:  # review: the target has DF_MAX fields already -- refuse (the whole move is rolled back) instead of losing it
            raise Denied(409, tr("The target workspace has no room for another custom field; nothing was moved"))
        if f["type"] == "select":
            label = df_label(f, v)
            v = next((o["id"] for o in _opts(t).get("options", []) if o["name"].lower() == str(label or "").lower()), None)
            if v is None and not may:
                raise Denied(409, tr("An admin adds the field “{0}” in the target workspace first; nothing was moved", f["name"]))
            if v is None:
                raise Denied(409, tr("The target workspace has no room for another custom field; nothing was moved"))
        _put(c, nid, new, t["id"], v)
        auto_map[f"cf{f['id']}"] = f"cf{t['id']}"
    return auto_map


# ---- Paperless-ngx: its custom fields as fields here -----------------------------------------------------------------
PL_TYPES = {"string": "text", "longtext": "text", "url": "url", "date": "date", "boolean": "checkbox", "integer": "number",
            "float": "number", "monetary": "money", "select": "select", "documentlink": "text"}


def _pl_options(fd):
    out = []
    for i, o in enumerate(fd.get("options") or []):
        if isinstance(o, dict) and o.get("label") is not None:
            out.append({"name": str(o["label"])[:DF_NAME_MAX], "pl": o.get("id")})
        elif isinstance(o, str):
            out.append({"name": o[:DF_NAME_MAX], "pl": i})
    return [o for o in out if o["name"].strip()][:50]


def df_from_paperless(c, ws, nid, doc, fields, uid=None):
    """The custom fields of a Paperless document (doc["custom_fields"], definitions fields = ngx.pl_fields) as fields of ws
    on document nid (marked "imported"); a value the document has already is kept. Returns the number of values set.
    2.184.0 B (#2580): a field is only made by who may define fields of ws (df_may_define); a value that finds no field
    (workspace full, no right, option missing, a value the type does not take) stays as a line in the document's text."""
    from ..paperless.ngx import _field_text
    m = S.meta_row(c, nid)
    if not m or m["ws"] != ws:
        return 0
    may = df_may_define(c, ws, uid)
    have = df_values(c, nid, ws)
    vals, rest = {}, []
    cfs = doc.get("custom_fields")
    for x in (cfs if isinstance(cfs, list) else [])[:200]:
        if not isinstance(x, dict) or not isinstance(x.get("field"), int) or x.get("value") in (None, "", []):
            continue
        fd = (fields or {}).get(x.get("field"))
        if not isinstance(fd, dict) or not str(fd.get("name") or "").strip():
            continue
        t = PL_TYPES.get(str(fd.get("type") or ""), "text")
        v = x["value"]
        if t == "select":
            opts = _pl_options(fd)
            o = next((o for o in opts if o["pl"] == v), None)
            if not o:
                continue
            f = df_find(c, ws, fd["name"], "select", {"options": [{"name": o["name"]} for o in opts]}, uid, make=may)
            v = o["name"]
            if f and not any(p["name"].lower() == v.lower() for p in _opts(f).get("options", [])):
                f = None  # the option is missing there (no right / no room for it)
        else:
            f = df_find(c, ws, fd["name"], t, None, uid, make=may)
            if t == "checkbox":
                v = "1" if v is True or str(v).lower() == "true" else None
            elif t == "money":
                mm = re.fullmatch(r"([A-Za-z]{3})?\s*(-?\d+(?:\.\d+)?)", str(v).strip())
                v = f"{float(mm.group(2)):.2f} {(mm.group(1) or '').upper()}".strip() if mm else None
                if v is None:  # not an amount: kept as text below
                    f = None
            elif t == "text":
                v = _field_text(fd, v)
        if f and (f["id"] in have or v is None):
            continue
        if not f and t == "checkbox" and v is None:
            continue  # unchecked: nothing to keep
        try:
            if not f:
                raise ValueError
            vals[f["id"]] = df_value(f, v)
        except ValueError:
            tf = df_find(c, ws, fd["name"], "text", None, uid, make=may) if t != "text" else None
            if tf and tf["id"] not in have and tf["id"] not in vals:  # a value this type does not take: a text field of the same name
                vals[tf["id"]] = str(_field_text(fd, x["value"]))[:DF_TEXT_MAX]
            elif not tf or tf["id"] not in have:
                rest.append(f"{str(fd['name']).strip()[:DF_NAME_MAX]}: {str(_field_text(fd, x['value']))[:DF_TEXT_MAX]}")
    vals = {k: v for k, v in vals.items() if v is not None}
    if rest:
        df_text_rest(c, nid, ws, rest)
    if vals:
        e = df_set(c, S.meta_row(c, nid), vals, by="import")
        if e:
            return 0
    return len(vals)


def df_text_rest(c, nid, ws, lines):
    """2.184.0 B (#2580): values without a field as lines "Name: value" below the text of document nid -- into the text the
    import hands over (still waiting for its recognition) or, once recognised, into its text and word index."""
    block = tr("Custom fields") + ":\n" + "\n".join(f"- {x}" for x in lines)
    m = S.meta_row(c, nid)
    sug = S.meta_json(c, m, "suggest", {})
    if m["state"] == "wait" and isinstance(sug.get("_given"), dict):
        g = sug["_given"]
        g["text"] = "\n\n".join(p for p in (str(g.get("text") or "").strip(), block) if p)[:200_000]  # as the import's text
        S.meta_set_json(c, nid, ws, "suggest", sug)
        return
    text = "\n\n".join(p for p in (S.meta_text(c, m).strip(), block) if p)[:200_000]
    c.execute("UPDATE doc_meta SET text=? WHERE node_id=?", (S.doc_seal(c, ws, "doc_meta.text", text), nid))
    _reindex_nodes(c, [nid])


def _reindex_nodes(c, nids):
    from .web import _reindex
    for nid in nids:
        _reindex(c, nid)


# ---- routes: the definitions of a workspace (values: PATCH /api/docs/<id> {custom_fields}) ---------------------------
def _field(c, fid):
    r = c.execute("SELECT * FROM doc_fields WHERE id=?", (fid,)).fetchone()
    if not r:
        raise Denied(404)
    _ws_manage(c, r["ws"], me())
    return r


@app.post("/api/docs/fields")
def docs_field_add():
    """{ws: private|org:<id>, name, type: text|number|money|date|checkbox|select|url, options?: select [{name}] or "A, B"}"""
    c = db()
    _no_agent()
    uid = me()
    d = body()
    _org, ws = ws_param(c, d.get("ws"), uid, manage=True)
    try:
        name, ftype, opts = df_clean_def(d)
    except ValueError as e:
        return err(str(e))
    if _name_taken(c, ws, name):
        return err(tr("A field with this name exists already"), 409)
    if c.execute("SELECT COUNT(*) FROM doc_fields WHERE ws=?", (ws,)).fetchone()[0] >= DF_MAX:
        return err(tr("At most {0} fields", DF_MAX), 409)
    fid = df_create(c, ws, name, ftype, opts, uid)
    bump(c)
    c.commit()
    return jsonify(id=fid, fields=df_list(c, ws)), 201


@app.patch("/api/docs/fields/<int:fid>")
def docs_field_edit(fid):
    """{name?, options? (select; options left out are removed from the documents), sort?}"""
    c = db()
    _no_agent()
    r = _field(c, fid)
    d = body()
    try:
        name, _t, opts = df_clean_def(d, old=r)
    except ValueError as e:
        return err(str(e))
    if _name_taken(c, r["ws"], name, skip=fid):
        return err(tr("A field with this name exists already"), 409)
    sort = d.get("sort")
    sort = float(sort) if isinstance(sort, (int, float)) and not isinstance(sort, bool) and math.isfinite(sort) else r["sort"]
    c.execute("UPDATE doc_fields SET name=?, options=?, sort=? WHERE id=?", (name, json.dumps(opts, ensure_ascii=False), sort, fid))
    nids = [x[0] for x in c.execute("SELECT node_id FROM doc_field_values WHERE field_id=?", (fid,))]
    if r["type"] == "select":  # values of removed options go
        keep = {o["id"] for o in opts["options"]}
        for v in c.execute("SELECT node_id, value FROM doc_field_values WHERE field_id=?", (fid,)).fetchall():
            x = S.doc_open(c, r["ws"], CTX, v["value"], default=None)
            if x is not None and x not in keep:  # review B1: a value that cannot be opened is never dropped here
                c.execute("DELETE FROM doc_field_values WHERE node_id=? AND field_id=?", (v["node_id"], fid))
    if r["type"] == "select":
        _reindex_nodes(c, nids)  # the word index holds the option names
    bump(c)
    c.commit()
    return jsonify(id=fid, fields=df_list(c, r["ws"]))


@app.delete("/api/docs/fields/<int:fid>")
def docs_field_del(fid):
    """Delete a field and its values on every document of the workspace (the app asks first)."""
    c = db()
    _no_agent()
    r = _field(c, fid)
    nids = [x[0] for x in c.execute("SELECT node_id FROM doc_field_values WHERE field_id=?", (fid,))]
    n = len(nids)
    c.execute("DELETE FROM doc_fields WHERE id=?", (fid,))  # the values go with it (foreign key)
    _reindex_nodes(c, nids)  # their words leave the search
    bump(c)
    c.commit()
    return jsonify(ok=True, values=n, fields=df_list(c, r["ws"]))
