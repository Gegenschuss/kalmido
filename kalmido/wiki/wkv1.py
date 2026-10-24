"""2.200.0 C (#1781): knowledge pages for agents and scripts (API v1; scopes wiki:read / wiki:write).

An AGENT sees a knowledge page only when the page or a folder above it is shared with exactly it (fs_shares.agent_id on a
node of the knowledge tree, wkfolder.py; the share dialog of the app): no right from its workspace or the area (wkf_base
gives agents nothing), a page of an organisation only for an agent of that organisation (the file store's boundary), a
private page only for an agent of its own person. Anything else answers 404. The paths an agent gets start at the shared
node (the shared folder's name, or the page's own name): nothing about the folders above it.
A person's token sees what the person sees in the app (full paths of their own spaces, shared pages like an agent's).
Locked spaces (wikie2e.py: path and text are ciphertexts) never come here, not even for their own people.
Writing needs the role 'edit' on the page; a new page needs 'edit' on its folder (checked before the name, and again on the
new page before the commit). Renaming (path, relink: people's tokens) needs the area's own right, a share edits the text only.
The text keeps the web route's rules: size, the frontmatter, the history (wiki_versions), the word index, the links;
expect_updated_at guards against overwriting a change made in between (409 with the current page, checked in the UPDATE).
A token without wiki:read gets no text back (writing answers the page without body / attrs).
Every read, write and creation by an agent is noted in the history of the page's node (fs_log), not a listing. No event.
2.200.0 F (#1781, review): the private-page rule and the scopes hold in the file store's API too (wkfolder._hidden, files/v1.py).
"""
import json

from flask import g, jsonify

from ..core.config import app
from ..core.access import Denied, acx_of
from ..core.db import bump, db, insert_id, iso_ms, now_utc
from ..core.errors import BadInput, reject_unknown
from ..core.i18n import tr
from ..accounts.session import me
from ..api.common import V1Error, v1_args, v1_call, v1_err, v1_json, v1_out, v1_view
from ..collab.comments import user_names
from ..accounts.orgroles import org_role_key
from ..files.store import _shares_role, fs_chain, fs_deleted, fs_log_add, fs_role, _now
from .pages import wiki_body, wiki_clean_path, wiki_insert, wiki_space_key, wiki_update, wiki_create
from .wikie2e import wke_mode
from .wkfolder import WKF_KIND, wkf_base, wkf_folder_path, wkf_locked, wkf_node_of, wkf_role, wkf_shared_ids, wkf_visible_sql
from .wkhist import wkh_body

WKV_LIST_MAX = 2000  # pages of one list answer (more = "more": true; narrow it with space)
WKV_FIELDS_AGENT = ("body", "expect_updated_at")
WKV_FIELDS_PERSON = WKV_FIELDS_AGENT + ("path", "relink")


def _is_agent(c, uid):
    return acx_of(c, uid).role == "agent"


def _reads():
    """2.200.0 F (#1781, review 4): the token may read texts (wiki:read) -- a write-only token gets no text back."""
    return g.get("auth_via") != "token" or "wiki:read" in (g.get("scopes") or set())


def _agent_private_ok(c, uid, owner):
    """A private page (owner) for agent uid: only the personal agent of that person."""
    a = c.execute("SELECT owner_id FROM agents WHERE user_id=?", (uid,)).fetchone()
    return bool(a and a["owner_id"] and a["owner_id"] == owner)


def _shared_top(c, uid, chain):
    """Index in chain (node first) of the highest node shared with uid (an agent: with exactly it; a person: with them or a
    group of theirs), None without one. Expired shares do not count."""
    ids = [int(x["id"]) for x in chain]
    if not ids:
        return None
    q = ",".join(str(i) for i in ids)
    rows = c.execute(f"""SELECT node_id FROM fs_shares WHERE node_id IN ({q}) AND (expires_at IS NULL OR expires_at > ?)
                         AND (agent_id=? OR user_id=? OR group_id IN (SELECT group_id FROM group_members WHERE user_id=?))""",
                     (_now(), uid, uid, uid)).fetchall()
    hit = {int(r[0]) for r in rows}
    top = None
    for i, x in enumerate(chain):
        if int(x["id"]) in hit:
            top = i
    return top


def _path_for(c, uid, r, agent):
    """The path uid gets for page row r: the full path in a space of their own, else from the shared node down (None: no
    share reaches it)."""
    if not agent and wkf_base(c, uid, r) is not None:
        return r["path"]
    n = wkf_node_of(c, r["id"])
    if n is None:
        return None
    chain = fs_chain(c, n["id"])
    top = _shared_top(c, uid, chain)
    if top is None:
        return None
    return "/".join(x["name"] for x in reversed(chain[:top + 1]))


def wkv_need(c, uid, pid, write=False):
    """(row, role, path) of page pid for token account uid -- 404 without a role / in a locked space / in the trash, 403 when
    writing needs 'edit'."""
    r = c.execute("SELECT * FROM wiki_pages WHERE id=?", (int(pid),)).fetchone()
    if r is None or r["deleted_at"] or wkf_locked(c, r):
        raise Denied(404)
    agent = _is_agent(c, uid)
    if agent and r["org_id"] is None and not _agent_private_ok(c, uid, r["owner_id"]):
        raise Denied(404)
    role = wkf_role(c, uid, r)
    path = _path_for(c, uid, r, agent) if role else None
    if role is None or path is None:
        raise Denied(404)
    if write and role != "edit":
        raise Denied(403)
    return r, role, path


def _page(c, r, role, path, names, full=False):
    d = {"id": r["id"], "path": path, "name": path.rsplit("/", 1)[-1], "space": wiki_space_key(r["org_id"]), "role": role,
         "created_at": r["created_at"], "updated_at": r["updated_at"], "updated_by_name": names.get(r["updated_by"], ""),
         "url": f"/api/v1/wiki/pages/{r['id']}"}
    if full and _reads():
        try:
            d["attrs"] = json.loads(r["attrs"] or "{}")
        except ValueError:
            d["attrs"] = {}
        d["body"] = wkh_body(c, r)
    return d


def _log(c, uid, r, action):
    """An agent's access in the history of the page's node (people's changes stay in the page history)."""
    if not _is_agent(c, uid):
        return
    n = wkf_node_of(c, r["id"])
    if n is not None:
        fs_log_add(c, n["id"], action)


def _space_filter(v):
    """None (all) | 'shared' | ('org', id | None)."""
    if v in (None, "", "all"):
        return None
    if v == "shared":
        return "shared"
    if v in ("private", "0"):
        return ("org", None)
    if isinstance(v, str) and v.startswith("org:") and v[4:].isdigit():
        return ("org", int(v[4:]))
    raise BadInput(tr("Invalid value: {0}", "space"))


@app.get("/api/v1/wiki/pages")
@v1_view
def wkv_list():
    """The knowledge pages you may read, without their text: ?space=all (default) | shared (only shared with you one by one or
    by folder) | private | org:<id>. An agent sees only what is shared with it."""
    a = v1_args(("space",))
    sp = _space_filter(a.get("space"))
    c = db()
    uid = me()
    agent = _is_agent(c, uid)
    # 2.200.0 F (#1781, review 6): the candidates from part B's visibility (shares + the area's own), sorted, cut = more
    if sp == "shared":
        ids = wkf_shared_ids(c, uid)
        w = [f"p.id IN ({','.join(str(int(x)) for x in sorted(ids))})" if ids else "FALSE"]
    else:
        w = [wkf_visible_sql(c, uid, "p")]
    args = []
    if isinstance(sp, tuple):
        w.append("p.org_id=?" if sp[1] else "p.org_id IS NULL")
        args += [sp[1]] if sp[1] else []
    cap = WKV_LIST_MAX * 3
    rows = c.execute(f"SELECT p.* FROM wiki_pages p WHERE p.deleted_at IS NULL AND left(p.path, 5)<>'e2e1:' AND {' AND '.join(w)} "
                     f"ORDER BY lower(p.path), p.id LIMIT {cap + 1}", args).fetchall()
    cut = len(rows) > cap
    out = []
    for r in rows[:cap]:
        if sp == "shared" and not agent and wkf_base(c, uid, r) is not None:
            continue
        try:
            r, role, path = wkv_need(c, uid, r["id"])
        except Denied:
            continue
        out.append((path.lower(), r, role, path))
    out.sort(key=lambda x: (x[0], x[1]["id"]))
    more = cut or len(out) > WKV_LIST_MAX
    out = out[:WKV_LIST_MAX]
    names = user_names(c, {x[1]["updated_by"] for x in out})
    return jsonify(data=[_page(c, r, role, path, names) for _, r, role, path in out], more=more)


@app.get("/api/v1/wiki/pages/<int:pid>")
@v1_view
def wkv_get(pid):
    """One page: its Markdown text, the frontmatter as attrs, your role (view | edit) and when / by whom it changed last."""
    v1_args(())
    c = db()
    uid = me()
    r, role, path = wkv_need(c, uid, pid)
    d = _page(c, r, role, path, user_names(c, [r["updated_by"]]), full=True)
    _log(c, uid, r, "text")
    c.commit()
    return jsonify(d)


def _conflict(c, uid, r, role, path):
    cur = _page(c, r, role, path, user_names(c, [r["updated_by"]]), full=True)
    return v1_err(409, tr("Changed in the meantime by {0}", cur.get("updated_by_name") or "?"), name="conflict", page=cur)


@app.patch("/api/v1/wiki/pages/<int:pid>")
@v1_view
def wkv_update(pid):
    """{body, expect_updated_at?} -- the new text (role edit). A person's token may also rename: path (the full path), relink."""
    b = v1_json()
    c = db()
    uid = me()
    agent = _is_agent(c, uid)
    reject_unknown(b, WKV_FIELDS_AGENT if agent else WKV_FIELDS_PERSON)
    r, role, path = wkv_need(c, uid, pid, write=True)
    if ("path" in b or "relink" in b) and wkf_base(c, uid, r) != "edit":
        raise Denied(403, tr("Through a share only the page's text can change here"))  # 2.200.0 F (#1781, review 2)
    if "body" in b:
        wiki_body(b)  # the size check before anything else
    exp = b.get("expect_updated_at")
    if exp and exp != r["updated_at"]:
        return _conflict(c, uid, r, role, path)
    try:
        v1_call(wiki_update, pid, body=dict(b))
    except V1Error as e:  # 2.200.0 F (#1781, review 5): saved in between (wiki_update checks it in its UPDATE)
        if exp and e.resp.status_code == 409:
            r, role, path = wkv_need(c, uid, pid)
            if r["updated_at"] != exp:
                return _conflict(c, uid, r, role, path)
        raise
    r, role, path = wkv_need(c, uid, pid)
    _log(c, uid, r, "write")
    c.commit()
    return jsonify(_page(c, r, role, path, user_names(c, [r["updated_by"]]), full=True))


def _may_add(c, uid, agent, chain, oid, owner):
    """'edit' on a new page in the folder of chain: the area's own right (private: its person; an organisation: who writes
    there) or an edit share of the chain (a read-only member: at most view, like fsref)."""
    if not agent and wkf_base(c, uid, {"org_id": oid, "owner_id": owner or uid}) == "edit":
        return True
    if _shares_role(c, [x["id"] for x in chain], uid, agent) not in ("edit", "owner"):
        return False
    return agent or not oid or org_role_key(c, uid, oid) != "readonly"


def _new_in_folder(c, uid, agent, b):
    """{folder_id, name, body?}: a page in a folder of a knowledge tree where uid has 'edit' -> the new page id."""
    fid, name = b.get("folder_id"), b.get("name")
    if isinstance(fid, bool) or not isinstance(fid, int) or fid <= 0:
        raise BadInput(tr("Invalid value: {0}", "folder_id"))
    if not isinstance(name, str) or "/" in name or "\\" in name:
        raise BadInput(tr("Invalid value: {0}", "name"))
    name = wiki_clean_path(name)
    fp = wkf_folder_path(c, fid)
    chain = fs_chain(c, fid)
    if fp is None or not chain or fs_deleted(chain) or not fs_role(c, fid, uid, chain=chain):
        raise Denied(404)
    if agent and _shared_top(c, uid, chain) is None:
        raise Denied(404)  # an agent's way in is a share, never the organisation's access to the tree
    top = chain[-1]
    oid, owner = (top["org_id"] or None), (None if top["org_id"] else top["owner_id"])
    if agent and oid is None and not _agent_private_ok(c, uid, owner):
        raise Denied(404)
    if wke_mode(c, oid, owner)[0]:
        raise Denied(404)  # a locked space has no folders of nodes (and never comes here)
    if not _may_add(c, uid, agent, chain, oid, owner):
        raise Denied(403)  # 2.200.0 F (#1781, review 7): the right before the name (no 409 for a folder shared to read)
    path = wiki_clean_path(f"{fp}/{name}" if fp else name)
    text = wiki_body(b)
    ts = iso_ms(now_utc())
    with c.savepoint():
        pid = wiki_insert(c, oid, owner or uid, path, text, ts)
        if pid is None:
            raise Denied(409, tr("A page with this name already exists"))
        if owner and owner != uid:  # a private page made by its person's agent: the agent made it, the page stays the person's
            c.execute("UPDATE wiki_pages SET created_by=?, updated_by=? WHERE id=?", (uid, uid, pid))
        nts = _now()
        nid = insert_id(c, """INSERT INTO fs_nodes(parent_id,kind,name,owner_id,org_id,ref_kind,ref_id,created_by,created_at,updated_at)
                              VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (fid, "ref", path.rsplit("/", 1)[-1], top["owner_id"], top["org_id"], WKF_KIND, pid, uid, nts, nts))
        r = c.execute("SELECT * FROM wiki_pages WHERE id=?", (pid,)).fetchone()
        if wkf_role(c, uid, r) != "edit":
            raise Denied(403)  # a folder shared to read: nothing was made
    return pid


@app.post("/api/v1/wiki/pages")
@v1_view
def wkv_create():
    """A new page: {folder_id (a knowledge folder where you may edit, e.g. one shared with you), name, body?}; a person's
    token may also give {space: private | org:<id>, path, body?} like the app. 409: the name is taken there."""
    b = v1_json()
    c = db()
    uid = me()
    agent = _is_agent(c, uid)
    if "folder_id" in b or agent:
        reject_unknown(b, ("folder_id", "name", "body"))
        pid = _new_in_folder(c, uid, agent, b)
        bump(c)
        c.commit()
    else:  # a person's token like the app (wiki_create answers 201 with the app's page)
        reject_unknown(b, ("space", "path", "body"))
        g.body = dict(b)
        try:
            res = wiki_create()
        finally:
            g.body = None
        if isinstance(res, tuple) and res[1] >= 400:
            return v1_out(res)
        pid = (res[0] if isinstance(res, tuple) else res).get_json()["id"]
    r, role, path = wkv_need(c, uid, pid)
    _log(c, uid, r, "create")
    c.commit()
    return jsonify(_page(c, r, role, path, user_names(c, [r["updated_by"]]), full=True)), 201


def wkv_spec(paths, schemas, op, ok, errs, ref, pid, q):
    schemas["WikiPage"] = {"type": "object", "properties": {
        "id": {"type": "integer"},
        "path": {"type": "string", "description": "Folders by \"/\" and the page's name. An agent / a shared page: from the shared "
                                                  "folder (or the page) down, nothing above it"},
        "name": {"type": "string"}, "space": {"type": "string", "description": "private or org:<id>"},
        "role": {"type": "string", "enum": ["view", "edit"]}, "created_at": {"type": "string"}, "updated_at": {"type": "string"},
        "updated_by_name": {"type": "string"}, "url": {"type": "string"},
        "body": {"type": "string", "description": "Markdown ([[Page]] links a page of the same space, #123 a task); not in lists"},
        "attrs": {"type": "object", "description": "The frontmatter (a leading --- block of key: value lines); not in lists"}}}
    T = "Knowledge"
    wid = pid("id", "Page id")
    shared = "An agent sees only pages shared with it (the page or a folder above it, in the app's share dialog); without a share 404."
    paths["/wiki/pages"] = {
        "get": op("Knowledge pages you may read, without their text (2.200.0)", T,
                  ok({"type": "object", "properties": {"data": {"type": "array", "items": ref("WikiPage")}, "more": {"type": "boolean"}}})
                  | errs("400"), [q("space", "all (default), shared, private or org:<id>")], scope="wiki:read",
                  desc=shared + " Pages of end-to-end encrypted spaces never come through the API."),
        "post": op("Create a knowledge page (2.200.0)", T, ok(ref("WikiPage"), "Created", "201") | errs("400", "403", "404", "409"), [],
                   body={"type": "object", "properties": {
                       "folder_id": {"type": "integer", "description": "A knowledge folder where you may edit (see the file store: "
                                                                       "the folders of a shared knowledge folder)"},
                       "name": {"type": "string", "maxLength": 200, "description": "The page's name (no \"/\")"},
                       "body": {"type": "string", "maxLength": 500000},
                       "space": {"type": "string", "description": "People's tokens only, instead of folder_id: private or org:<id>"},
                       "path": {"type": "string", "description": "People's tokens only, with space: the full path"}}},
                   scope="wiki:write", desc="A folder shared with you to read only: 403, nothing is created.")}
    paths["/wiki/pages/{id}"] = {
        "get": op("A knowledge page with its Markdown text (2.200.0)", T, ok(ref("WikiPage")) | errs("404"), [wid], scope="wiki:read",
                  desc=shared),
        "patch": op("Change a knowledge page's text (2.200.0)", T, ok(ref("WikiPage")) | errs("400", "403", "404", "409"), [wid],
                    body={"type": "object", "properties": {
                        "body": {"type": "string", "maxLength": 500000},
                        "expect_updated_at": {"type": "string", "description": "The updated_at you read: 409 with the current page "
                                                                               "(error.page) when someone saved in between"},
                        "path": {"type": "string", "description": "People's tokens only: rename / move (the full path)"},
                        "relink": {"type": "boolean", "description": "People's tokens only, with path (default true)"}}},
                    scope="wiki:write", desc="Needs the role edit (403 otherwise). Every save is one entry of the page's history in the app.")}
