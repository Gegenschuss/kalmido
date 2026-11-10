"""2.857.0 (#5518): the filter of the documents' saved views on the shared core's filter (docs/dev/kern.md "Filter",
core/filters.py kflt_where; the dialog: static/js/docviews.js dcv_cat on fltdlg.js kflt_dialog). No condition logic of its
own: kflt_where combines the conditions (AND / OR, "is none of" always on top), every condition is built from the documents
search's own pieces (docs/dsearch.py dsr_filters with the parameters that condition stands for, dsr_hits for
the text with its syntax), so a condition means exactly what the same filter of the search means.

rules = {op: and | or, conds: [{f, op, v, ...}], sort?, dir?, area?, unbooked?, state?} -- f, the comparisons, v:
  sender / type    in / nin / empty   v = ["1,7", ...]  one name each (its ids in several workspaces, as the search's filters)
  tag              in / nin / empty   v = ["1,7", ...]
  folder           in / nin           v = ["12", "3,9"] with its subfolders; sub: 0 = only the folder itself (an older view)
  date / added     in / nin           v = ["m0", "y1", "2025", "2025-01..2025-03"] a preset or the search's date syntax
                   from / to          v = "2025-01-31"  (the document date / the date of arrival)
  ftype            in / nin           v = ["pdf", "image", "office", "text", "other"]
  asn              eq / from / to     v = 143;  set / empty = with / without an archive number
  review           in / nin           v = ["1"]  to review
  text             has / nhas         v = the search field's text with its syntax (tag:, absender:, "exact", -word)
  cf               in / nin           ids = "4,9" (one field per workspace), v = [option name | "1" / "0" of a checkbox]
The rest of the keys (sort, ...) are the view's own search parameters (docs/web.py doc_query takes them as args).
An older view keeps only its query string (doc_views.query): dvf_from_query converts it into the same hits.
Every value goes to SQL as a parameter; whatever does not fit is off. The rows are always those the person may see
(doc_query's own WHERE), a filter only narrows them."""
import json
import re
from datetime import timedelta
from urllib.parse import parse_qsl

from werkzeug.datastructures import MultiDict

from ..core.db import local_now
from ..core.errors import BadInput
from ..core.filters import COND_MAX, VAL_MAX, kflt_where
from ..core.i18n import tr
from ..core.pg import st_ids
from .dsearch import dsr_asn, dsr_filters, dsr_hits, dsr_range

DVF_OPS = {"sender": ("in", "nin", "empty"), "type": ("in", "nin", "empty"), "tag": ("in", "nin", "empty"), "folder": ("in", "nin"),
           "date": ("in", "nin", "from", "to"), "added": ("in", "nin", "from", "to"), "ftype": ("in", "nin"),
           "asn": ("eq", "from", "to", "set", "empty"), "review": ("in", "nin"), "text": ("has", "nhas"), "cf": ("in", "nin")}
DVF_EXTRA = ("sort", "dir", "area", "unbooked", "state")  # the view's own search parameters next to its conditions
DVF_JSON_MAX = 20000
DVF_PRESETS = ("d7", "d30", "d90", "m0", "m1", "y0", "y1")
_IDS = re.compile(r"[0-9]{1,12}(?:[,;][0-9]{1,12}){0,99}")
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")
_EXTRA = re.compile(r"[a-z_]{1,20}|1|0")


def dvf_preset(v, today=None):
    """A date preset -> (from, to) as ISO: d7 / d30 / d90 = the last days up to today, m0 / m1 = this / last month,
    y0 / y1 = this / last year; None when it is none."""
    t = today or local_now().date()
    if v in ("d7", "d30", "d90"):
        return (t - timedelta(days=int(v[1:]) - 1)).isoformat(), t.isoformat()
    if v == "m0":
        return t.replace(day=1).isoformat(), t.isoformat()
    if v == "m1":
        last = t.replace(day=1) - timedelta(days=1)
        return last.replace(day=1).isoformat(), last.isoformat()
    if v in ("y0", "y1"):
        y = t.year - (v == "y1")
        return f"{y}-01-01", f"{y}-12-31"
    return None


# ---- cleaning (a stored view, a count): only what the conditions know
def _val(x):
    if isinstance(x, bool) or not isinstance(x, (str, int)):
        return None
    x = str(x).strip()[:200]
    return x or None


def dvf_cond_clean(cnd):
    """One condition -> its clean form or None (it is left out)."""
    if not isinstance(cnd, dict) or cnd.get("f") not in DVF_OPS or cnd.get("op") not in DVF_OPS[cnd["f"]]:
        return None
    f, op, v = cnd["f"], cnd["op"], cnd.get("v")
    out = {"f": f, "op": op}
    if op in ("in", "nin"):
        vs = [x for x in (_val(y) for y in (v if isinstance(v, list) else [])[:VAL_MAX]) if x]
        out["v"] = list(dict.fromkeys(vs))
    elif op in ("has", "nhas"):
        out["v"] = v.strip()[:500] if isinstance(v, str) else ""
    elif op in ("from", "to", "eq"):
        out["v"] = _val(v) or ""
    if f == "folder" and cnd.get("sub") in (0, "0", False):
        out["sub"] = 0
    if f == "cf":
        ids = str(cnd.get("ids") or "")
        if not _IDS.fullmatch(ids):
            return None
        out["ids"] = ids
    return out


def dvf_clean(v):
    """rules from a client (a dict or its JSON) -> the clean dict; BadInput when it is no filter at all."""
    if isinstance(v, str):
        if len(v) > DVF_JSON_MAX:
            raise BadInput(tr("Invalid value: {0}", "rules"))
        try:
            v = json.loads(v) if v.strip() else {}
        except ValueError:
            raise BadInput(tr("Invalid value: {0}", "rules")) from None
    if not isinstance(v, dict):
        raise BadInput(tr("Invalid value: {0}", "rules"))
    conds = v.get("conds") if isinstance(v.get("conds"), list) else []
    out = {"op": "or" if v.get("op") == "or" else "and", "conds": [x for x in (dvf_cond_clean(c) for c in conds[:COND_MAX]) if x]}
    for k in DVF_EXTRA:
        x = v.get(k)
        if isinstance(x, str) and _EXTRA.fullmatch(x):
            out[k] = x
    if len(json.dumps(out)) > DVF_JSON_MAX:
        raise BadInput(tr("Invalid value: {0}", "rules"))
    return out


def dvf_field(c, v, row=None):
    """The core's field cleaner of doc_views.rules (dviews.py obj_register): stored as JSON text, None / '' = none."""
    if v is None or v == "":
        return ""
    return json.dumps(dvf_clean(v), ensure_ascii=False, separators=(",", ":"))


# ---- an older view: its query string -> the same filter
def dvf_from_query(qs):
    """The query string of an older view (dviews.py DV_KEYS) -> rules that hit the same documents: every parameter one
    condition (all of them AND, as the search combined them), sort / area / state kept as they were."""
    p = MultiDict(parse_qsl(str(qs or "").lstrip("?")))
    cs = []
    one = lambda **k: cs.append(k)  # noqa: E731
    if (p.get("q") or "").strip():
        one(f="text", op="has", v=p["q"].strip())
    for k in ("sender", "type"):
        if p.getlist(k):
            one(f=k, op="in", v=p.getlist(k))
    if p.getlist("tag"):
        if p.get("tag_mode") == "all":
            for g in p.getlist("tag"):
                one(f="tag", op="in", v=[g])
        else:
            one(f="tag", op="in", v=p.getlist("tag"))
    if p.getlist("not_tag"):
        one(f="tag", op="nin", v=p.getlist("not_tag"))
    for k, f, op in (("from", "date", "from"), ("to", "date", "to"), ("added_from", "added", "from"), ("added_to", "added", "to")):
        if _ISO.fullmatch(p.get(k) or ""):
            one(f=f, op=op, v=p[k])
    if p.get("review") in ("1", "true"):
        one(f="review", op="in", v=["1"])
    for k, f in (("no_tag", "tag"), ("no_sender", "sender"), ("no_type", "type")):
        if p.get(k) in ("1", "true"):
            one(f=f, op="empty")
    if p.getlist("folder"):
        one(f="folder", op="in", v=p.getlist("folder"), sub=0)
    if (p.get("under") or "").isdigit():
        one(f="folder", op="in", v=[p["under"]])
    ft = [x for x in (p.get("ftype") or "").split(",") if x]
    if ft:
        one(f="ftype", op="in", v=ft)
    rng = dsr_asn(p.get("asn"))
    if rng:
        if rng[0] == rng[1]:
            one(f="asn", op="eq", v=str(rng[0]))
        else:
            one(f="asn", op="from", v=str(rng[0]))
            one(f="asn", op="to", v=str(rng[1]))
    if p.get("has_asn") in ("1", "true"):
        one(f="asn", op="set")
    if p.get("no_asn") in ("1", "true"):
        one(f="asn", op="empty")
    for x in p.getlist("cf"):  # every one AND, as the search took them
        ids, _, val = x.partition(":")
        if ids and val:
            one(f="cf", op="in", ids=ids, v=[val])
    out = dvf_clean({"op": "and", "conds": cs, **{k: p[k] for k in DVF_EXTRA if p.get(k)}})
    return out


def dvf_rules(row):
    """The filter of a stored view: its rules, else its query converted (an older view)."""
    if row["rules"]:
        try:
            return dvf_clean(row["rules"])
        except BadInput:
            pass
    return dvf_from_query(row["query"])


# ---- the conditions in SQL (doc_meta d, fs_nodes n), each from the search's own pieces
def _dsr(c, pairs, base_where, base_params):
    """The search's filters for these parameters -> (where list, params, words, text)."""
    w, p = [], []
    q, text = dsr_filters(c, MultiDict(pairs), w, p, base_where, base_params)
    return w, p, q, text


def _all(w, p):
    return ("(" + " AND ".join(w) + ")", p) if w else None


def _any(parts):
    parts = [x for x in parts if x]
    if not parts:
        return None
    return "(" + " OR ".join(x[0] for x in parts) + ")", [a for x in parts for a in x[1]]


def _pos(c, cnd, base_where, base_params):
    """The condition as if it were "is one of" / "contains" -> (sql, params) or None (off)."""
    f, op, v = cnd["f"], cnd["op"], cnd.get("v")
    one = lambda pairs: _all(*_dsr(c, pairs, base_where, base_params)[:2])  # noqa: E731
    if op == "empty":
        k = {"sender": "no_sender", "type": "no_type", "tag": "no_tag", "asn": "no_asn"}.get(f)
        return one([(k, "1")]) if k else None
    if f == "asn":
        if op == "set":
            return one([("has_asn", "1")])
        n = str(v or "")
        if not n.isdigit():
            return None
        return one([("asn", {"eq": f"{n}-{n}", "from": f"{n}-999999999", "to": f"0-{n}"}[op])])
    if f in ("date", "added") and op in ("from", "to"):
        if not _ISO.fullmatch(str(v or "")):
            return None
        return one([(("" if f == "date" else "added_") + op, v)])
    if f == "text":
        w, p, q, text = _dsr(c, [("q", v)], base_where, base_params)
        if not str(v or "").strip():
            return None
        hit = dsr_hits(c, f"FROM doc_meta d JOIN fs_nodes n ON n.id=d.node_id WHERE {' AND '.join(base_where + w)}", base_params + p, q, text)
        if hit is not None:
            w, p = w + ["d.node_id = ANY(CAST(? AS BIGINT[]))"], p + [st_ids(hit)]
        return _all(w, p) or ("TRUE", [])
    if not isinstance(v, list) or not v:
        return None
    if f in ("sender", "type", "tag"):  # one of the names (the search: several sender / type = one of them, tag_mode any)
        return one([(f, x) for x in v])
    if f == "folder":
        if cnd.get("sub") == 0:
            return one([("folder", x) for x in v])
        return _any(one([("under", i)]) for x in v for i in re.split(r"[,;]", x) if i.isdigit())
    if f in ("date", "added"):
        parts = []
        for x in v:
            rng = dvf_preset(x) or dsr_range(x)
            if rng:
                key = "" if f == "date" else "added_"
                parts.append(one([(key + k, d) for k, d in zip(("from", "to"), rng) if d]))
        return _any(parts)
    if f == "ftype":
        return one([("ftype", ",".join(v))])
    if f == "review":
        return one([("review", "1")]) if "1" in v else None
    if f == "cf":
        return _any(one([("cf", f"{cnd['ids']}:{x}")]) for x in v)
    return None


def dvf_where(c, rules, base_where, base_params):
    """rules -> (one SQL condition or None, params) over doc_meta d / fs_nodes n, inside the person's rows (base_where /
    base_params: doc_query's, the rights and the workspace). The core's kflt_where combines the conditions."""
    r = dvf_clean(rules) if not isinstance(rules, dict) or "conds" not in rules else rules

    def cond(cnd):
        cnd = dvf_cond_clean(cnd)
        if not cnd:
            return None
        p = _pos(c, cnd, base_where, base_params)
        if not p:
            return None
        sql = f"COALESCE({p[0]}, FALSE)"  # TRUE / FALSE, never NULL: "is none of" stays exact (no sender = none of them)
        return (f"NOT {sql}", p[1]) if cnd["op"] in ("nin", "nhas") else (sql, p[1])
    return kflt_where(r, cond)


def dvf_args(rules, extra=None):
    """The view's own search parameters (sort, area, ...) as request arguments, with extra on top."""
    md = MultiDict({k: rules[k] for k in DVF_EXTRA if isinstance(rules, dict) and rules.get(k)})
    for k, v in (extra or {}).items():
        md[k] = v
    return md
