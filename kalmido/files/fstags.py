"""2.122.0 B (#2099): tags in the file store ("Ablage"). Files and folders carry the same tags as documents: the tag set of
their workspace (doc_tags of 'o<org>' | 'u<owner>', docs/store.py) and the table doc_node_tags (node_id -> fs_nodes.id) --
no second tag world. Setting tags needs write access to the node; whoever sees a node sees its tags and the tag names of
its workspace. A node with a doc_meta row is a document: its tags change through docs/web.py doc_update (the models
learn the correction as in the documents area). A plain file / folder only gets the rows: the recognition, the models
(train / classify) and the documents' filters only ever read the tags of documents (doc_meta rows).

Agents use the API v1 (their file list shows no tags yet), not these routes."""
import re

from flask import g, jsonify, request

from ..core.config import app
from ..core.db import body, bump, db, err
from ..core.i18n import tr
from ..core.access import Denied, acx_of
from ..accounts.session import me
from ..docs import store as S
from .store import fs_chain, fs_link_target, fs_log_add, fs_visible_sql, need_node
from .fslock import fsl_need_unlocked  # 2.353.0 F (#2758)

DT_MAX = 30       # tags per node (as a document)
DT_HITS = 500     # nodes of one tag filter


def _no_agent():
    from ..agents.core import is_agent
    if is_agent(g.user):
        raise Denied(403)


def dt_ws(n):
    """The documents workspace of a node row: its organisation's, else its owner's."""
    return S.doc_ws(n["org_id"], n["owner_id"])


def dt_ws_nodes(ws):
    """(sql, params): the condition on fs_nodes n for the nodes of workspace ws."""
    oid = S.ws_org(ws)
    if oid:
        return "n.org_id = ?", [oid]
    return "n.org_id IS NULL AND n.owner_id = ?", [int(ws[1:])]


def dt_attach(c, items):
    """Adds "tags" ([{id, name}]) to node dicts of a list (one query)."""
    ids = [x["id"] for x in items if x.get("id")]
    if not ids:
        return items
    by = {}
    for i in range(0, len(ids), 1000):
        part = ids[i:i + 1000]
        for r in c.execute(f"""SELECT nt.node_id, t.id, t.name FROM doc_node_tags nt JOIN doc_tags t ON t.id=nt.tag_id
                               WHERE nt.node_id IN ({','.join('?' * len(part))}) ORDER BY lower(t.name)""", part):
            by.setdefault(r[0], []).append({"id": r[1], "name": r[2]})
    for x in items:
        x["tags"] = by.get(x.get("id"), [])
    return items


def dt_values(c, ws, raw):
    """Tag ids of ws from a list of ids / names (names make new tags; ids of another workspace are dropped)."""
    out = []
    for t in (raw or [])[:DT_MAX]:
        if isinstance(t, int) and not isinstance(t, bool):
            if S.label_ok(c, ws, "tag", t):
                out.append(t)
        elif isinstance(t, str) and t.strip():  # review: only text names (no str() of objects)
            out.append(S.label_id(c, ws, "tag", t))
    return list(dict.fromkeys(t for t in out if t))


def dt_set(c, n, raw, uid):
    """Replace the tags of node row n (write access checked by the caller) -> the error response or None."""
    if S.meta_row(c, n["id"]):  # a document: as the documents area does it (marks, models, index)
        from ..docs.web import doc_update
        return doc_update(c, n["id"], {"tags": list(raw or [])}, uid)
    S.set_tags(c, n["id"], dt_values(c, dt_ws(n), raw))
    return None


def dt_move(c, nid, ws):
    """The tags of a node that moved into workspace ws (files/fsmove.py): found / made there by name. Documents are done by
    fsmove's fsm_doc."""
    if S.meta_row(c, nid):
        return
    tags = c.execute("SELECT t.id, t.name, t.ws, nt.auto FROM doc_node_tags nt JOIN doc_tags t ON t.id=nt.tag_id WHERE nt.node_id=?",
                     (nid,)).fetchall()
    if not tags or all(t["ws"] == ws for t in tags):
        return
    new = {}
    for t in tags:
        x = t["id"] if t["ws"] == ws else S.label_id(c, ws, "tag", t["name"])
        if x:
            new[x] = t["auto"] or ""
    S.set_tags(c, nid, list(new), new)


def dt_space(c, uid, raw):
    """?space= of the file store -> (sql condition on n, params): private | org:<id> | shared (what others share with me)."""
    v = str(raw or "private").strip()
    if v == "private":
        return "n.org_id IS NULL AND n.owner_id = ?", [uid]
    if v == "shared":
        return "n.owner_id != ? AND n.org_id IS NULL", [uid]
    m = re.fullmatch(r"org:(\d+)", v)
    if m and int(m.group(1)) in acx_of(c, uid).org_ids:
        return "n.org_id = ?", [int(m.group(1))]
    raise Denied(404)


def dt_groups(args, key):
    """Repeated ?key=1,7 values -> [[1, 7], ...] (one group = one tag name, its ids in several workspaces)."""
    out = []
    for v in args.getlist(key) if hasattr(args, "getlist") else [args.get(key)]:
        ids = [int(x) for x in str(v or "").split(",") if x.strip().isdigit()][:50]
        if ids:
            out.append(ids)
    return out[:20]


@app.get("/api/files/nodes/<int:nid>/tags")
def files_node_tags(nid):
    """{tags: the node's [{id, name}], all: the tags of its workspace [{id, name}], ws}."""
    c = db()
    _no_agent()
    n = need_node(c, nid)
    ws = dt_ws(n)
    can = n["role"] in ("owner", "edit")
    # review: the whole tag list of the workspace only for those who may tag here (a view share of one private file shows no other names)
    return jsonify(tags=[{"id": t["id"], "name": t["name"]} for t in S.node_tags(c, nid)], all=S.labels(c, ws, "tag") if can else [],
                   ws=("org:%d" % n["org_id"]) if n["org_id"] else "private", can=can)


@app.put("/api/files/nodes/<int:nid>/tags")
def files_node_tags_put(nid):
    """{tags: [names | ids]} -- the tags of a file / folder (write access; names make new tags of its workspace)."""
    c = db()
    _no_agent()
    n = need_node(c, nid, write=True)
    if n["kind"] == "link":
        fs_link_target(c, n)  # as a rename: a link changes only for someone who may open its original
    raw = body().get("tags")
    if not isinstance(raw, list):
        return err(tr("Invalid value: {0}", "tags"))
    if raw:
        fsl_need_unlocked(c, nid)  # 2.353.0 F (#2758, review N10): tags are plain -- none in a locked folder (taking them off stays possible)
    e = dt_set(c, n, raw, me())
    if e:
        return e
    tags = [{"id": t["id"], "name": t["name"]} for t in S.node_tags(c, nid)]
    fs_log_add(c, nid, "tags", ", ".join(t["name"] for t in tags)[:300])
    bump(c)
    c.commit()
    return jsonify(tags=tags)


@app.get("/api/files/tags")
def files_tags_used():
    """?space=private | org:<id> | shared -> {tags: [{name, ids}]}: the tags on files / folders I see there, merged by name."""
    c = db()
    _no_agent()
    uid = me()
    cond, params = dt_space(c, uid, request.args.get("space"))
    rows = c.execute(f"""SELECT DISTINCT t.id, t.name FROM doc_node_tags nt JOIN doc_tags t ON t.id=nt.tag_id JOIN fs_nodes n ON n.id=nt.node_id
                         WHERE n.id IN {fs_visible_sql(uid, c)} AND {cond}""", params).fetchall()
    merged = {}
    for r in rows:
        merged.setdefault(r[1].lower(), {"name": r[1], "ids": []})["ids"].append(r[0])
    return jsonify(tags=sorted(merged.values(), key=lambda v: v["name"].lower()))


@app.get("/api/files/tagged")
def files_tagged():
    """?space=&tag=1,7&tag=3&mode=all|any&not=4 -> {items}: the files / folders of a space I see with these tags (a group
    of ids = one tag name; mode all: every group, any: one of them; not: none of these), at most DT_HITS, by name."""
    from .web import _items
    c = db()
    _no_agent()
    uid = me()
    cond, params = dt_space(c, uid, request.args.get("space"))
    groups, nots = dt_groups(request.args, "tag"), [i for grp in dt_groups(request.args, "not") for i in grp]
    if not groups and not nots:
        return err(tr("Invalid value: {0}", "tag"))
    where = [f"n.id IN {fs_visible_sql(uid, c)}", cond]
    has = "n.id IN (SELECT node_id FROM doc_node_tags WHERE tag_id IN ({0}))"
    parts = []
    for grp in groups:
        parts.append(has.format(",".join("?" * len(grp))))
    if parts:
        where.append("(" + (" AND " if request.args.get("mode") == "all" else " OR ").join(parts) + ")")
        params += [i for grp in groups for i in grp]
    if nots:
        where.append("NOT " + has.format(",".join("?" * len(nots))))
        params += nots
    rows = c.execute(f"SELECT n.* FROM fs_nodes n WHERE {' AND '.join(where)} ORDER BY lower(n.name), n.id LIMIT {DT_HITS + 1}", params).fetchall()
    more = len(rows) > DT_HITS
    items = _items(c, rows[:DT_HITS])
    from .store import fs_visible_ids
    vis = fs_visible_ids(c, me())
    for x in items:  # where it lies: the path above it, cut at the first folder the asker cannot see (review: like _crumbs)
        up = []
        for r in fs_chain(c, x["id"])[1:]:
            if r["id"] not in vis:
                break
            up.append(r["name"])
        x["path"] = " / ".join(reversed(up))
    return jsonify(items=items, more=more)
