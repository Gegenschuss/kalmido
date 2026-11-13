"""2.1119.0 (#5277, stage Q5c of the cross-cutting core): the move of the file store's tags (doc_tags / doc_node_tags) into the
core (obj_tags scope ws, obj_tag_links kind fs_entry; core/objtags.py otg_move_ws) and the rewrite of the places that keep a
tag's id, for a tag whose id was taken in obj_tags already (by a project tag, a label or a personal tag):
  doc_models (feature tags)   the learned yes / no model per tag id (sealed): its keys
  doc_meta.suggest            a suggested tag (sealed): {"tags": {"value": [ids]}}
  doc_meta.redo_prev          "Recognise again" kept for 24 h: {"tags": [ids]}
  doc_meta.learn_prev         "Apply what was learned" kept for 24 h: {"after": {"tags": [ids]}}
  doc_flow_runs.data          a flow's run (sealed, its undo): {"b": {"tags": [ids]}, "a": {"tags": [ids]}}
  doc_views                   a saved view: its query string (tag= / not_tag= "1,7") and its rules (f tag, v ["1,7"])
The ids of doc_tags were unique over every workspace, so one map {old: new} serves every row. A sealed value that cannot be
opened any more (another server key, a lost organisation key) is left as it is -- nobody can read it either (an old id in it
is no tag of its workspace any more: the readers check every id against the workspace, store.py label_ok).

core/db.py init_db runs dtg_move at every start (core/objhooks.MOVE) as "system", before the fragment 5277_a drops the two
tables; it does nothing once they are gone."""
import json
from urllib.parse import parse_qsl, urlencode

from ..core.objhooks import MOVE
from ..core.objtags import otg_move_ws
from . import store as S

def _ids(v, m):
    """A list of tag ids (int or text) with the old ids of m replaced (each value keeps its type)."""
    if not isinstance(v, list):
        return v
    out = []
    for x in v:
        try:
            n = m.get(int(x))
        except (TypeError, ValueError):
            n = None
        out.append(x if n is None else (str(n) if isinstance(x, str) else n))
    return out


def _group(v, m):
    """'1,7' (one tag name, its ids in several workspaces) with the old ids of m replaced."""
    return ",".join(str(m.get(int(p), p)) if p.strip().isdigit() else p for p in str(v).split(","))


def _open(c, ws, ctx, value):
    """The opened JSON object of a sealed value, {} when it cannot be opened (or is none)."""
    try:
        return S._jopen(c, ws, ctx, value, {})
    except Exception:  # noqa: BLE001 -- a broken value stays as it is
        return {}


def dtg_rekey(c, m):
    """Rewrites the places that keep a tag id (module docstring) with m {old id: new id}. {place: rows changed}."""
    n = {"models": 0, "suggest": 0, "prev": 0, "runs": 0, "views": 0}
    if not m:
        return n
    for r in c.execute("SELECT ws, data FROM doc_models WHERE feature='tags'").fetchall():
        d = _open(c, r["ws"], "doc_models.data", r["data"])
        new = {(str(m[int(k)]) if str(k).isdigit() and int(k) in m else k): v for k, v in d.items()}
        if new != d:
            S.model_put(c, r["ws"], "tags", new)
            n["models"] += 1
    for r in c.execute("SELECT node_id, ws, suggest FROM doc_meta WHERE suggest<>''").fetchall():
        d = _open(c, r["ws"], "doc_meta.suggest", r["suggest"])
        t = d.get("tags") if isinstance(d, dict) else None
        if isinstance(t, dict) and isinstance(t.get("value"), list) and _ids(t["value"], m) != t["value"]:
            t["value"] = _ids(t["value"], m)
            c.execute("UPDATE doc_meta SET suggest=? WHERE node_id=?", (S._jseal(c, r["ws"], "doc_meta.suggest", d), r["node_id"]))
            n["suggest"] += 1
    for col, q in (("redo_prev", "SELECT node_id, redo_prev AS v FROM doc_meta WHERE redo_prev LIKE '%tags%'"),
                   ("learn_prev", "SELECT node_id, learn_prev AS v FROM doc_meta WHERE learn_prev LIKE '%tags%'")):
        for r in c.execute(q).fetchall():
            try:
                d = json.loads(r["v"])
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            box = d.get("after") if col == "learn_prev" else d
            if isinstance(box, dict) and _ids(box.get("tags"), m) != box.get("tags"):
                box["tags"] = _ids(box["tags"], m)
                c.execute("UPDATE doc_meta SET redo_prev=? WHERE node_id=?" if col == "redo_prev" else
                          "UPDATE doc_meta SET learn_prev=? WHERE node_id=?", (json.dumps(d, separators=(",", ":")), r["node_id"]))
                n["prev"] += 1
    for r in c.execute("SELECT id, ws, data FROM doc_flow_runs WHERE data<>''").fetchall():
        d = _open(c, r["ws"], "doc_flow_runs.data", r["data"])
        if not isinstance(d, dict):
            continue
        hit = False
        for k in ("b", "a"):
            if isinstance(d.get(k), dict) and _ids(d[k].get("tags"), m) != d[k].get("tags"):
                d[k]["tags"] = sorted(_ids(d[k]["tags"], m))
                hit = True
        if hit:
            c.execute("UPDATE doc_flow_runs SET data=? WHERE id=?", (S._jseal(c, r["ws"], "doc_flow_runs.data", d), r["id"]))
            n["runs"] += 1
    for r in c.execute("SELECT id, query, rules FROM doc_views WHERE query LIKE '%tag%' OR rules LIKE '%tag%'").fetchall():
        pairs = parse_qsl(r["query"] or "", keep_blank_values=True)
        new = [(k, _group(v, m) if k in ("tag", "not_tag") else v) for k, v in pairs]
        q = urlencode(new) if new != pairs else (r["query"] or "")
        rules = r["rules"] or ""
        try:
            d = json.loads(rules) if rules else None
        except ValueError:
            d = None
        if isinstance(d, dict) and isinstance(d.get("conds"), list):
            for x in d["conds"]:
                if isinstance(x, dict) and x.get("f") == "tag" and isinstance(x.get("v"), list):
                    x["v"] = [_group(v, m) for v in x["v"]]
            rules = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
        if q != (r["query"] or "") or rules != (r["rules"] or ""):
            c.execute("UPDATE doc_views SET query=?, rules=? WHERE id=?", (q, rules, r["id"]))
            n["views"] += 1
    return n


def dtg_move(c):
    """2.1119.0 (#5277): doc_tags / doc_node_tags into the core and the ids of the tags that got a new one rewritten (module
    docstring). Runs as "system" in the start transaction (core/objhooks.MOVE). The map {old: new}."""
    remap = otg_move_ws(c)
    m = {o: x for (_ws, o), x in remap.items()}
    dtg_rekey(c, m)
    return m


MOVE.append(dtg_move)  # core/db.py init_db, before the fragments' AFTER (core/objhooks.py)
