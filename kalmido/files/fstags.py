"""2.122.0 B (#2099): tags in the file store ("Ablage"). Files and folders carry the same tags as documents: the tag set of
their workspace ('o<org>' | 'u<owner>', docs/store.py) -- no second tag world. 2.1119.0 (#5277, stage Q5c): the tags are rows
of the shared core, obj_tags scope ws and obj_tag_links kind fs_entry (core/objtags.py; were doc_tags / doc_node_tags).
Setting tags needs write access to the node; whoever sees a node sees its tags. The tag names of the whole workspace only
its members see (dt_ws_member, decided 08.11.2026, question 11): a person a node is shared with sees the tags on the nodes
they see, not the workspace's other names. A node with a doc_meta row is a document: its tags change through docs/web.py doc_update (the models
learn the correction as in the documents area). A plain file / folder only gets the rows: the recognition, the models
(train / classify) and the documents' filters only ever read the tags of documents (doc_meta rows).

Agents use the API v1 (files/v1.py: tags in the list and the details, filter tag=; 2.443.0 #2338), not these routes."""
import re

from flask import g, jsonify, request

from ..core.config import app
from ..core.db import body, bump, db, err
from ..core.i18n import tr
from ..core.pg import write_lock  # 2.564.0 (#4701)
from ..core.access import Denied, acx_of
from ..accounts.session import me
from ..docs import store as S
from ..accounts.orgroles import org_role_key  # 2.1119.0 (#5277): dt_ws_member
from ..core.objtags import OTG_FS_IN, otg_ws_of, otg_ws_tag_of  # 2.1119.0 (#5277): the tags are the core's
from .store import fs_chain, fs_link_target, fs_log_add, fs_visible_sql, need_node
from .fslock import fsl_need_unlocked  # 2.353.0 F (#2758)
from .web import _items  # 2.369.5 (#2517): pulled up from functions
from .store import fs_visible_ids  # 2.369.5 (#2517): pulled up from functions

DT_MAX = 30       # tags per node (as a document)
DT_HITS = 500     # nodes of one tag filter


def _no_agent():
    from ..agents.core import need_person
    need_person(403)


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
    by = otg_ws_of(c, ids)  # 2.1119.0 (#5277): one query of the core (one array parameter)
    for x in items:
        x["tags"] = [{"id": t["id"], "name": t["name"]} for t in by.get(x.get("id"), [])]
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


def dt_merge(c, have, old, mine):
    """2.564.0 (#4701): the stored tag names have with what one client changed (old = the list it saw, mine = its new list;
    names or ids, compared by name in any case): removed ones go, added ones come, the rest stays as stored."""
    def nm(t):
        if isinstance(t, int) and not isinstance(t, bool):
            r = otg_ws_tag_of(c, t)  # 2.1119.0 (#5277)
            return r["name"] if r else None
        return t.strip() if isinstance(t, str) and t.strip() else None
    key = lambda x: x.casefold()  # noqa: E731
    old_k = {key(x) for x in map(nm, old) if x}
    mine_n = [x for x in map(nm, mine) if x]
    mine_k = {key(x) for x in mine_n}
    off = old_k - mine_k
    out, seen = [], set()
    for x in [x for x in have if key(x) not in off] + [x for x in mine_n if key(x) not in old_k]:
        if key(x) not in seen:
            seen.add(key(x))
            out.append(x)
    return out


def dt_move(c, nid, ws):
    """The tags of a node that moved into workspace ws (files/fsmove.py): found / made there by name. Documents are done by
    fsmove's fsm_doc."""
    if S.meta_row(c, nid):
        return
    tags = otg_ws_of(c, [nid]).get(int(nid), [])  # 2.1119.0 (#5277)
    if not tags or all(t["ws"] == ws for t in tags):
        return
    new = {}
    for t in tags:
        x = t["id"] if t["ws"] == ws else S.label_id(c, ws, "tag", t["name"])
        if x:
            new[x] = t["auto"] or ""
    S.set_tags(c, nid, list(new), new)


def dt_ws_member(c, ws, uid):
    """2.1119.0 (#5277, question 11): is person uid a member of workspace ws (an organisation's: a member that is no guest, as
    the documents area asks, docs/web.py ws_param; a person's own: that person)? Only members see all its tag names."""
    oid = S.ws_org(ws)
    if not oid:
        return ws == S.doc_ws(None, uid)
    if oid not in acx_of(c, uid).org_ids:
        return False
    return org_role_key(c, uid, oid) != "guest"


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


def dt_where(groups, nots, every, where, params):
    """Adds the tag conditions on fs_nodes n: groups of ids (each = one tag name; every: all groups, else one of them), nots: none."""
    has = "n.id IN (" + OTG_FS_IN + " IN ({0}))"  # 2.1119.0 (#5277): the core's links
    if groups:
        where.append("(" + (" AND " if every else " OR ").join(has.format(",".join("?" * len(grp))) for grp in groups) + ")")
        params += [i for grp in groups for i in grp]
    if nots:
        where.append("NOT " + has.format(",".join("?" * len(nots))))
        params += nots


@app.get("/api/files/nodes/<int:nid>/tags")
def files_node_tags(nid):
    """{tags: the node's [{id, name}], all: the tags of its workspace [{id, name}], ws}."""
    c = db()
    _no_agent()
    n = need_node(c, nid)
    ws = dt_ws(n)
    can = n["role"] in ("owner", "edit")
    # review: the whole tag list of the workspace only for those who may tag here (a view share of one private file shows no other names);
    # 2.1119.0 (#5277, decided 08.11.2026, question 11): and only for a member of the workspace -- an edit share of a node gives
    # its tags, not the names of the workspace (a name typed in still finds / makes the tag)
    full = can and dt_ws_member(c, ws, me())
    return jsonify(tags=[{"id": t["id"], "name": t["name"]} for t in S.node_tags(c, nid)], all=S.labels(c, ws, "tag") if full else [],
                   ws=("org:%d" % n["org_id"]) if n["org_id"] else "private", can=can)


@app.put("/api/files/nodes/<int:nid>/tags")
def files_node_tags_put(nid):
    """{tags: [names | ids], _prev?: {tags: the list the client saw}} -- the tags of a file / folder (write access; names make
    new tags of its workspace). 2.564.0 (#4701): with _prev only the tags added / removed against it apply (a tag set
    elsewhere meanwhile stays), under write_lock('fs-tags-<id>'); without _prev the list replaces them as before."""
    c = db()
    _no_agent()
    n = need_node(c, nid, write=True)
    if n["kind"] == "link":
        fs_link_target(c, n)  # as a rename: a link changes only for someone who may open its original
    b = body()
    raw = b.get("tags")
    if not isinstance(raw, list):
        return err(tr("Invalid value: {0}", "tags"))
    write_lock(c, f"fs-tags-{nid}")
    prev = b.get("_prev") if isinstance(b.get("_prev"), dict) else None
    if prev and isinstance(prev.get("tags"), list):
        raw = dt_merge(c, [t["name"] for t in S.node_tags(c, nid)], prev["tags"], raw)
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
    rows = c.execute(f"""SELECT DISTINCT ot.id, ot.name FROM obj_tag_links k JOIN obj_tags ot ON ot.id=k.tag_id AND ot.scope_kind='ws'
                         JOIN fs_nodes n ON n.id=k.obj_id WHERE k.kind='fs_entry' AND n.id IN {fs_visible_sql(uid, c)} AND {cond}""",
                     params).fetchall()  # 2.1119.0 (#5277): the core's links -- only tags on nodes I see
    merged = {}
    for r in rows:
        merged.setdefault(r[1].lower(), {"name": r[1], "ids": []})["ids"].append(r[0])
    return jsonify(tags=sorted(merged.values(), key=lambda v: v["name"].lower()))


@app.get("/api/files/tagged")
def files_tagged():
    """?space=&tag=1,7&tag=3&mode=all|any&not=4 -> {items}: the files / folders of a space I see with these tags (a group
    of ids = one tag name; mode all: every group, any: one of them; not: none of these), at most DT_HITS, by name."""
    c = db()
    _no_agent()
    uid = me()
    cond, params = dt_space(c, uid, request.args.get("space"))
    groups, nots = dt_groups(request.args, "tag"), [i for grp in dt_groups(request.args, "not") for i in grp]
    if not groups and not nots:
        return err(tr("Invalid value: {0}", "tag"))
    where = [f"n.id IN {fs_visible_sql(uid, c)}", cond]
    dt_where(groups, nots, request.args.get("mode") == "all", where, params)
    rows = c.execute(f"SELECT n.* FROM fs_nodes n WHERE {' AND '.join(where)} ORDER BY lower(n.name), n.id LIMIT {DT_HITS + 1}", params).fetchall()
    more = len(rows) > DT_HITS
    items = _items(c, rows[:DT_HITS])
    vis = fs_visible_ids(c, me())
    for x in items:  # where it lies: the path above it, cut at the first folder the asker cannot see (review: like _crumbs)
        up = []
        for r in fs_chain(c, x["id"])[1:]:
            if r["id"] not in vis:
                break
            up.append(r["name"])
        x["path"] = " / ".join(reversed(up))
    return jsonify(items=items, more=more)
