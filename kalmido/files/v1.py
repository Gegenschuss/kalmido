"""2.48.0 (#1207): the file store in the REST API (agents and personal tokens; scopes files:read / files:write).

An agent sees only what is shared with exactly it plus its own result folder (created on first use, named like the agent,
at the top of its owner's space -- an organisation's agent: of the organisation). Every access of an agent is written into
the node's history (fs_log), which the owner sees on the file. Writing needs the role 'edit' (or the own folder).
"""
import base64
import binascii

from flask import g, jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.db import bump, db
from ..accounts.session import me
from ..core.access import Denied, acx_of
from ..api.v1 import BadInput, UnknownFields
from ..api.common import v1_args, v1_json, v1_view
from .store import (fs_chain, fs_log_add, fs_mail_rows, fs_new_version, fs_put, fs_read, fs_visible_ids, need_node, safe_fs_name,
                    _now, _place)
from .fsroots import fs_area_folder_name, fs_area_of  # 2.200.0 A (#2747, review 6)
from .fsref import fs_ref_content  # 2.199.0 A (#2742)
from .web import fs_agent_folder, fs_node_json, _crumbs, _items, _send, _versions

V1_TEXT_MAX = 20 * 1024 * 1024  # bytes a request may send as content / content_base64


def _v1_node(c, n):
    out = fs_node_json(c, n, n.get("role"))
    out["url"] = f"/api/v1/files/{n['id']}"
    if n["kind"] in ("file", "link") or (n["kind"] == "ref" and n.get("ref_id")):  # 2.199.0 A (#2742): + a filed document
        out["content_url"] = f"/api/v1/files/{n['id']}/content"
    return out


def _is_agent(c):
    return acx_of(c, me()).role == "agent"


V1_AREA_SCOPES = {"wiki": ("wiki:read", "wiki:write")}  # 2.200.0 F (#1781, review 1/3): a closed area's own scopes


def _area_scope(c, nid, write=False):
    """2.200.0 F (#1781, review 1/3): a node of the knowledge tree (a folder below the root "Knowledge") needs the area's
    scope besides files:read / files:write -- 403 otherwise (the page nodes themselves are hidden without wiki:read)."""
    s = V1_AREA_SCOPES.get(fs_area_of(c, nid) or "") if nid else None
    if s and g.get("auth_via") == "token" and (s[1] if write else s[0]) not in (g.get("scopes") or set()):
        raise Denied(403, tr("This token lacks the permission “{0}”", s[1] if write else s[0]))


def _area_ok(c, nid):
    s = V1_AREA_SCOPES.get(fs_area_of(c, nid) or "")
    return not s or s[0] in (g.get("scopes") or set()) or g.get("auth_via") != "token"


@app.get("/api/v1/files")
@v1_view
def v1_files_list():
    """?parent_id=<folder>: its children; without: the top -- what is shared with you whose folder above is not (an agent:
    plus its own result folder)."""
    a = v1_args(("parent_id",))
    c = db()
    uid = me()
    if a.get("parent_id"):
        try:
            pid = int(a["parent_id"])
        except ValueError:
            raise BadInput(tr("Invalid value: {0}", "parent_id")) from None
        n = need_node(c, pid)
        if n["kind"] != "folder":
            raise Denied(409, tr("Not a folder"))
        _area_scope(c, pid)  # 2.200.0 F (#1781)
        rows = fs_mail_rows(c, me(), c.execute("SELECT * FROM fs_nodes WHERE parent_id=? AND deleted_at IS NULL ORDER BY id", (pid,)).fetchall())  # 2.148.1 D (#2488)
        fs_log_add(c, pid, "list")
        c.commit()
        items = _items(c, rows, n["role"])
    else:
        if _is_agent(c):
            if fs_agent_folder(c, uid):
                c.commit()
        vis = fs_visible_ids(c, uid)
        rows = []
        if vis:
            q = ",".join(str(int(x)) for x in vis)
            rows = [r for r in c.execute(f"SELECT * FROM fs_nodes WHERE id IN ({q}) ORDER BY id") if r["parent_id"] not in vis]
            rows = [r for r in rows if _area_ok(c, r["id"])]  # 2.200.0 F (#1781): knowledge folders only with wiki:read
        for r in rows:
            fs_log_add(c, r["id"], "list")
        c.commit()
        items = _items(c, rows)
    for x in items:
        x["url"] = f"/api/v1/files/{x['id']}"
    return jsonify(data=items, next_cursor=None)


@app.get("/api/v1/files/<int:nid>")
@v1_view
def v1_file_get(nid):
    """A node: a folder with its children, a file with its versions."""
    v1_args(())
    c = db()
    n = need_node(c, nid)
    _area_scope(c, nid)  # 2.200.0 F (#1781)
    out = _v1_node(c, n)
    if n["kind"] == "folder":
        rows = fs_mail_rows(c, me(), c.execute("SELECT * FROM fs_nodes WHERE parent_id=? AND deleted_at IS NULL ORDER BY id", (nid,)).fetchall())  # 2.148.1 D (#2488)
        out["children"] = _items(c, rows, n["role"])
    elif n["kind"] == "file":
        out["versions"] = _versions(c, nid)
    out["path"] = [x["name"] for x in _crumbs(c, fs_chain(c, nid))]  # only the folders the caller sees
    fs_log_add(c, nid, "meta")
    c.commit()
    return jsonify(out)


@app.get("/api/v1/files/<int:nid>/content")
@v1_view
def v1_file_content(nid):
    """The file's bytes (?version=<no>: an older version)."""
    a = v1_args(("version",))
    c = db()
    n = need_node(c, nid)
    _area_scope(c, nid)  # 2.200.0 F (#1781): a page's text needs wiki:read
    if n["kind"] not in ("file", "link", "ref"):  # 2.199.0 A (#2742): + a filed document (its area's content hook)
        raise Denied(409, tr("Not a file"))
    ver = None
    if a.get("version"):
        try:
            ver = int(a["version"])
        except ValueError:
            raise BadInput(tr("Invalid value: {0}", "version")) from None
    fs_log_add(c, nid, "download", str(ver or ""))
    c.commit()
    return _send(c, n, ver, dl=True)  # always as a download for the API


@app.get("/api/v1/files/<int:nid>/text")
@v1_view
def v1_file_text(nid):
    """The text of a file: UTF-8 text as it is, the text layer of a PDF (like /attachments/{id}/text)."""
    v1_args(())
    c = db()
    n = need_node(c, nid)
    _area_scope(c, nid)  # 2.200.0 F (#1781): a page's text needs wiki:read
    if n["kind"] not in ("file", "link", "ref"):
        raise Denied(409, tr("Not a file"))
    from ..tasks.attachtext import text_of_bytes
    if n["kind"] == "ref":  # 2.199.0 A (#2742): the text of a filed document (its area's content hook)
        data, name, mime = fs_ref_content(c, me(), n)
    else:
        data, name, mime = fs_read(c, nid), n["name"], n["mime"]
    out = text_of_bytes(name, mime, data, owner=me())
    if n["kind"] == "file":
        from .textscan import ts_fill
        ts_fill(c, "fs", nid, out)  # 2.61.0 (#1820): a scan / photo: the text recognised in the background
    fs_log_add(c, nid, "text")
    c.commit()
    return jsonify({"id": nid, "name": n["name"], **out})


def _content_arg(b):
    if "content" in b and "content_base64" in b:
        raise BadInput(tr("Expected {0}", "content | content_base64"))
    if isinstance(b.get("content"), str):
        data = b["content"].encode("utf-8")
    elif isinstance(b.get("content_base64"), str):
        try:
            data = base64.b64decode(b["content_base64"], validate=True)
        except (binascii.Error, ValueError):
            raise BadInput(tr("Invalid value: {0}", "content_base64")) from None
    else:
        raise BadInput(tr("Expected {0}", '{"name": "...", "content": "..."}'))
    if len(data) > V1_TEXT_MAX:
        raise BadInput(tr("{0}: larger than {1} MB", "content", V1_TEXT_MAX // (1024 * 1024)))
    return data


def _v1_body(allowed):
    b = v1_json()
    extra = sorted(k for k in b if k not in allowed)
    if extra:
        raise UnknownFields(extra)
    return b


@app.post("/api/v1/files")
@v1_view
def v1_file_create():
    """{parent_id?, name, kind?: file | folder, content? (UTF-8 text) | content_base64?, mime?}: a new file (or folder) in a
    folder you may edit; without parent_id: an agent's own result folder (a person: the top of their own space)."""
    v1_args(())
    b = _v1_body(("parent_id", "name", "kind", "content", "content_base64", "mime"))
    c = db()
    uid = me()
    name = str(b.get("name") or "").strip()
    if not name:
        raise BadInput(tr("Name missing"))
    kind = b.get("kind") or "file"
    if kind not in ("file", "folder"):
        raise BadInput(tr("Invalid value: {0}", "kind"))
    pid = b.get("parent_id")
    if pid in (None, "", 0):
        pid = fs_agent_folder(c, uid) if _is_agent(c) else None
        if _is_agent(c) and not pid:
            raise Denied(409, tr("This agent has no folder of its own (no owner)"))
    else:
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            raise BadInput(tr("Invalid value: {0}", "parent_id")) from None
    _area_scope(c, pid, write=True)  # 2.200.0 F (#1781, review 3): a folder in the knowledge tree needs wiki:write
    added = 0  # 2.353.0 D (#2759)
    if kind == "folder":
        owner, org = _place(c, uid, pid, None)
        from ..core.db import insert_id
        ts = _now()
        nid = insert_id(c, "INSERT INTO fs_nodes(parent_id,kind,name,owner_id,org_id,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                        (pid, "folder", fs_area_folder_name(c, pid, owner, org, safe_fs_name(name)), owner, org, uid, ts, ts))  # 2.200.0 A (#2747, review 6)
        fs_log_add(c, nid, "create")
    else:
        data = _content_arg(b)
        mime = b.get("mime") if isinstance(b.get("mime"), str) else None
        if mime is None and "content" in b:
            mime = "text/plain" if not name.lower().endswith((".md", ".markdown")) else "text/markdown"
        try:
            nid = fs_put(c, uid, pid, name, data, mime)
        except ValueError as e:
            c.rollback()
            raise BadInput(str(e)) from None
        fs_log_add(c, nid, "write")
        from ..docs.recog import rc_after_add
        added = rc_after_add(c, nid, uid)  # 2.353.0 D (#2759): into a recognising folder = a document
    bump(c)
    c.commit()
    if added:
        from ..docs.recog import rc_kick
        rc_kick(added)
    return jsonify(_v1_node(c, need_node(c, nid))), 201


@app.post("/api/v1/files/<int:nid>/versions")
@v1_view
def v1_file_version(nid):
    """{content | content_base64, mime?}: a new version of the file (the older ones stay; role edit)."""
    v1_args(())
    b = _v1_body(("content", "content_base64", "mime"))
    c = db()
    n = need_node(c, nid, write=True)
    if n["kind"] != "file":
        raise Denied(409, tr("Not a file"))
    data = _content_arg(b)
    try:
        no = fs_new_version(c, nid, data, b.get("mime") if isinstance(b.get("mime"), str) else None)
    except ValueError as e:
        c.rollback()
        raise BadInput(str(e)) from None
    fs_log_add(c, nid, "version", str(no))
    bump(c)
    c.commit()
    return jsonify({**_v1_node(c, need_node(c, nid)), "version": no}), 201


@app.get("/api/v1/files/search")
@v1_view
def v1_files_search():
    """2.61.0 (#1820): files whose name or recognised text matches ?q= -- only what the asker may see (agents: what is shared
    with them and their own folder); every hit an agent gets is in the file's history like a listing."""
    from .textscan import ts_files_find
    a = v1_args(("q", "space"))
    q = (a.get("q") or "").strip()
    if not q or len(q) > 200:
        raise BadInput(tr("Invalid value: {0}", "q"))
    c = db()
    rows, hit = ts_files_find(c, me(), q, (a.get("space") or "").strip())
    out = []
    for r in rows:
        try:
            n = need_node(c, r["id"])
        except Denied:  # a link whose original the asker may not open
            continue
        if not _area_ok(c, r["id"]):
            continue  # 2.200.0 F (#1781): a knowledge folder only with wiki:read
        fs_log_add(c, r["id"], "list")
        out.append({**_v1_node(c, n), "hit": hit.get(r["id"], "name")})
    c.commit()
    return jsonify(data=out, next_cursor=None)


def files_spec(paths, schemas, op, ok, errs, ref, pid, q):
    """OpenAPI of the file store (called from api/openapi.py)."""
    node = {"type": "object", "properties": {
        "id": {"type": "integer"}, "parent_id": {"type": ["integer", "null"]}, "kind": {"type": "string", "enum": ["folder", "file", "link", "ref"],
        "description": "ref (2.199): an office document / sheet filed in this folder -- no content here; ref_kind, ref_id, open, label"},
        "name": {"type": "string"}, "org_id": {"type": ["integer", "null"]}, "owner_id": {"type": "integer"}, "agent_id": {"type": ["integer", "null"],
        "description": "Set on an agent's own result folder"}, "mime": {"type": "string"}, "size": {"type": "integer"},
        "version": {"type": "integer"}, "role": {"type": ["string", "null"], "enum": ["owner", "edit", "view", None]},
        "updated_at": {"type": "string"}, "url": {"type": "string"}, "content_url": {"type": "string"},
        "sort_no": {"type": ["integer", "null"], "description": "Order by hand within the folder (null: by name after the sorted ones)"},
        "ref_kind": {"type": "string"}, "ref_id": {"type": ["integer", "null"]},
        "open": {"type": "string", "description": "kind ref: the app route of the object"}, "label": {"type": "string"},
        "recog": {"type": "string", "enum": ["on", "off"], "description": "2.353.0: the folder's / file's own recognition switch "
                  "(absent: as the folder above; set by people in the app)"}}}
    schemas["FileNode"] = node
    schemas["FileNodePage"] = {"type": "object", "properties": {"data": {"type": "array", "items": ref("FileNode")}, "next_cursor": {"type": "null"}}}
    T = "Files"
    nid = pid("id", "File or folder id")
    new = {"type": "object", "required": ["name"], "properties": {
        "parent_id": {"type": "integer", "description": "Folder (role edit); default: an agent's own result folder"},
        "name": {"type": "string"}, "kind": {"type": "string", "enum": ["file", "folder"]},
        "content": {"type": "string", "description": "UTF-8 text"}, "content_base64": {"type": "string", "description": "Any bytes, base64"},
        "mime": {"type": "string"}}}
    ver = {"type": "object", "properties": {"content": {"type": "string"}, "content_base64": {"type": "string"}, "mime": {"type": "string"}}}
    paths["/files"] = {
        "get": op("Folders and files shared with you (2.48.0)", T, ok(ref("FileNodePage")) | errs("400", "403", "404", "409"),
                  [q("parent_id", "A folder: its children (default: the top of what you may see)", {"type": "integer"})], scope="files:read",
                  desc="An agent sees exactly the folders and files shared with it plus its own result folder (created on first use). "
                       "Every access of an agent is in the file's history, visible to its owner."),
        "post": op("Create a file or folder (2.48.0)", T, ok(ref("FileNode"), "Created", "201") | errs("400", "403", "404", "409", "413"),
                   body=new, scope="files:write",
                   desc="Needs the role edit on the folder (or an agent's own folder). A name that is taken gets \" (2)\"; an agent's "
                        "executable ending gets \".txt\".")}
    paths["/files/search"] = {"get": op("Find files by name or recognised text (2.61.0)", T, ok(ref("FileNodePage")) | errs("400", "403", "404"),
                                         [q("q", "Words (a word of 4+ letters also matches as a prefix)", {"type": "string"}),
                                          q("space", "private | org:<id> | shared (default: all)", {"type": "string"})], scope="files:read",
                                         desc="Names, the text of PDFs and the text the server recognised in scans and photos (local OCR). "
                                              "Each item has hit: name | text | doc (2.353.0: sender, type or a tag of a document). Only files you may open; at most 100, newest first.")}
    paths["/files/{id}"] = {"get": op("A folder with its children or a file with its versions (2.48.0)", T, ok(ref("FileNode")) | errs("403", "404"),
                                      [nid], scope="files:read")}
    paths["/files/{id}/content"] = {"get": {**op("Download a file (2.48.0)", T, errs("400", "403", "404", "409"),
                                                 [nid, q("version", "An older version number", {"type": "integer"})], scope="files:read"),
                                            "responses": {"200": {"description": "The file's bytes"}, **errs("400", "403", "404", "409")}}}
    paths["/files/{id}/text"] = {"get": op("The text of a file: UTF-8 text, the text layer of a PDF (2.48.0)", T,
                                           ok({"type": "object", "properties": {  # 2.81.0 (#1856): the fields, with source
                                               "id": {"type": "integer"}, "name": {"type": "string"}, "kind": {"type": "string", "enum": ["pdf", "text", "image", "other"]},
                                               "text": {"type": ["string", "null"]}, "chars": {"type": "integer"}, "truncated": {"type": "boolean"},
                                               "pages": {"type": "integer"}, "no_text_layer": {"type": "boolean"},
                                               "source": {"type": "string", "enum": ["ocr"], "description": "2.61.0: the text was recognised in the background (scanned PDF, photo)"},
                                               "message": {"type": ["string", "null"]}}}) | errs("403", "404", "409"), [nid], scope="files:read")}
    paths["/files/{id}/versions"] = {"post": op("Upload a new version of a file (2.48.0)", T, ok(ref("FileNode"), "Created", "201") | errs("400", "403", "404", "409", "413"),
                                                [nid], body=ver, scope="files:write", desc="Role edit; the older versions stay and can be restored in the app.")}
