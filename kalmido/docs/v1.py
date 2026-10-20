"""2.48.0 (#1111): documents for agents (API v1; scopes files:read / files:write of the file store).

An agent reads only the documents whose file (or a folder above it) is shared with it (kalmido/files/store.py): their
fields and the recognised text. With the role 'edit' it may set fields; they are marked "set by an agent". A feature the
workspace has on level "agent" is not set directly: the value lands as a suggestion in "To review" for a person to accept.
Every access of an agent goes into the file's history (fs_log). Documents are never moved by an agent."""
import base64
import binascii
import os

from flask import jsonify, request

from ..core.config import MAX_FILE_MB, app
from ..core.db import bump, db
from ..core.i18n import tr
from ..core.access import Denied
from ..accounts.session import me
from ..api.v1 import BadInput, UnknownFields, cursor_dec, cursor_enc, v1_args, v1_json, v1_limit, v1_view
from ..files.store import fs_log_add, need_node
from . import store as S
from .web import doc_json, doc_query, doc_update

CREATE_FIELDS = ("name", "title", "mime", "content_base64", "parent_id", "ws", "sender", "type", "tags", "date", "due", "amount", "currency")
V1_FIELDS = ("date", "due", "amount", "currency", "sender", "type", "tags", "text")


def _v1_doc(c, m, node, full=False, role=None):
    d = doc_json(c, m, node, full=full, role=role)
    d.pop("thumb", None)
    d["url"] = f"/api/v1/documents/{m['node_id']}"
    d["content_url"] = f"/api/v1/files/{m['node_id']}/content"
    return d


@app.get("/api/v1/documents")
@v1_view
def v1_docs_list():
    """Documents you may see (an agent: shared with it), newest document date first: ?q=&review=1&state=&from=&to=.
    2.122.0 B (#2294): + tag / not_tag / sender / type / folder (ids, "1,7;3" = two), tag_mode, added_from / added_to, no_tag,
    no_sender, no_type, ftype; q takes the search syntax (tag:, sender:, type:, date:, "phrase", -word: docs/dsearch.py)."""
    a = v1_args(("q", "review", "state", "from", "to", "limit", "cursor", "tag", "tag_mode", "not_tag", "sender", "type", "folder",
                 "added_from", "added_to", "no_tag", "no_sender", "no_type", "ftype"))
    c = db()
    limit = v1_limit(a)
    off = cursor_dec("d", a.get("cursor"))
    rows, total, _rev = doc_query(c, me(), {**a, "limit": limit, "offset": off})
    out = []
    for r in rows:
        node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (r["node_id"],)).fetchone()
        out.append(_v1_doc(c, r, node))
        fs_log_add(c, r["node_id"], "list")
    c.commit()
    return jsonify(data=out, next_cursor=cursor_enc("d", off + limit) if total > off + limit else None)


@app.post("/api/v1/documents")
@v1_view
def v1_doc_create():
    """2.122.0 (#2098): a new document, recognised like an upload. multipart (field file) or JSON {name, content_base64}; optional
    title, parent_id (a folder you may edit; an agent without it: its own result folder), ws (a person: private | org:<id>),
    sender, type, tags (names, list or comma text), date, due, amount, currency. An agent's sender / type / tags follow the levels like
    PATCH (level agent = a suggestion to review)."""
    v1_args(())
    from ..admin.hosting import QuotaExceeded
    from ..agents.core import is_agent
    from flask import g
    from ..files.upsafe import h6d_read
    from ..files.web import fs_agent_folder
    from .ingest import docs_ingest, docs_kick
    from .web import ws_param
    c = db()
    uid = me()
    if request.files:
        f = request.files.get("file") or next(iter(request.files.values()))
        b = dict(request.form)
        data, name, mime = h6d_read(f), f.filename or "document", f.mimetype
    else:
        b = v1_json()
        if not isinstance(b.get("content_base64"), str):
            raise BadInput(tr("Expected {0}", "file | content_base64"))
        if len(b["content_base64"]) > MAX_FILE_MB * 1024 * 1024 * 4 // 3 + 4:  # refused before decoding (memory)
            raise Denied(413, tr("The file is too large"))
        try:
            data = base64.b64decode(b["content_base64"], validate=True)
        except (binascii.Error, ValueError):
            raise BadInput(tr("Invalid value: {0}", "content_base64")) from None
        name, mime = str(b.get("name") or "document"), b.get("mime") if isinstance(b.get("mime"), str) else None
    extra = sorted(k for k in b if k not in CREATE_FIELDS)
    if extra:
        raise UnknownFields(extra)
    title = str(b.get("title") or "").strip()
    if title:  # the title names the file; the file's own ending stays (the type detection and the preview go by it)
        ext = os.path.splitext(name)[1]
        name = title if not ext or title.lower().endswith(ext.lower()) else title + ext
    meta = {k: b[k] for k in ("date", "due", "amount", "currency", "sender", "type", "tags") if b.get(k) not in (None, "", [])}
    if "tags" in meta and not isinstance(meta["tags"], (list, str)):
        raise BadInput(tr("Invalid value: {0}", "tags"))
    if isinstance(meta.get("tags"), list):
        meta["tags"] = [str(t).strip() for t in meta["tags"] if str(t).strip()][:50]
    agent = is_agent(g.user)
    if agent and meta:
        meta["_by"] = "agent"  # the recognition treats sender / type / tags as an agent's values (suggestions on level agent)
    pid, org = b.get("parent_id"), None
    if b.get("ws") not in (None, "") and (agent or pid not in (None, "", 0, "0")):
        raise BadInput(tr("Invalid value: {0}", "ws"))  # the folder (or the agent's own folder) decides the workspace
    if pid in (None, "", 0, "0"):
        pid = None
        if agent:
            pid = fs_agent_folder(c, uid)
            if not pid:
                raise Denied(409, tr("This agent has no folder of its own (no owner)"))
        else:
            org, _ws = ws_param(c, b.get("ws"), uid)
    else:
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            raise BadInput(tr("Invalid value: {0}", "parent_id")) from None
        need_node(c, pid, write=True)
    try:
        with c.savepoint():
            nid = docs_ingest(c, uid, org, name, data, mime, "api", meta, parent_id=pid)
            fs_log_add(c, nid, "upload")
    except QuotaExceeded:
        raise Denied(413, tr("{0}: no space left in your storage", name)) from None
    except ValueError as e:
        raise BadInput(str(e)) from None
    bump(c)
    c.commit()
    docs_kick()
    n = need_node(c, nid)
    return jsonify(_v1_doc(c, S.meta_row(c, nid), n, full=True, role=n["role"])), 201


@app.get("/api/v1/documents/<int:nid>")
@v1_view
def v1_doc_get(nid):
    """One document with its fields, suggestions and the recognised text."""
    v1_args(())
    c = db()
    n = need_node(c, nid)
    m = S.meta_row(c, nid)
    if not m:
        raise Denied(404)
    fs_log_add(c, nid, "text")
    c.commit()
    return jsonify(_v1_doc(c, m, n, full=True, role=n["role"]))


@app.patch("/api/v1/documents/<int:nid>")
@v1_view
def v1_doc_patch(nid):
    """Set fields (role edit): date, due, amount, currency, sender, type, tags (names), text (only while none was
    recognised). An agent's values are marked "set by an agent"; features on level agent become suggestions."""
    b = v1_json()
    extra = sorted(k for k in b if k not in V1_FIELDS)
    if extra:
        raise UnknownFields(extra)
    c = db()
    need_node(c, nid, write=True)
    if not S.meta_row(c, nid):
        raise Denied(404)
    if "tags" in b and not isinstance(b["tags"], list):
        raise BadInput(tr("Invalid value: {0}", "tags"))
    from ..agents.core import is_agent
    from flask import g
    e = doc_update(c, nid, b, me(), by="agent" if is_agent(g.user) else None)
    if e:
        raise BadInput(e[0].get_json().get("error") or tr("Invalid value: {0}", "document"))
    fs_log_add(c, nid, "edit", ",".join(sorted(b))[:200])
    bump(c)
    c.commit()
    n = need_node(c, nid)
    return jsonify(_v1_doc(c, S.meta_row(c, nid), n, full=True, role=n["role"]))


def docs_spec(paths, schemas, op, ok, errs, ref, pid, q):
    """OpenAPI of the documents (called from api/openapi.py)."""
    label = {"type": ["object", "null"], "properties": {"id": {"type": "integer"}, "name": {"type": "string"}}}
    schemas["Document"] = {"type": "object", "properties": {
        "id": {"type": "integer", "description": "The file's id in the file store (/files/{id})"}, "name": {"type": "string"},
        "mime": {"type": "string"}, "size": {"type": "integer"}, "org_id": {"type": ["integer", "null"]},
        "state": {"type": "string", "enum": list(S.STATES), "description": "Recognition: wait, run, done, failed (error says why)"},
        "error": {"type": "string"}, "method": {"type": "string", "description": "pdf (text layer), ocr, text, import"},
        "date": {"type": ["string", "null"], "format": "date"}, "due": {"type": ["string", "null"], "format": "date"},
        "taken_at": {"type": ["string", "null"], "description": "Capture time of a photo (from its EXIF, read before the metadata was removed)"},
        "amount": {"type": ["string", "null"], "description": "Decimal text, e.g. 119.00"}, "currency": {"type": ["string", "null"]},
        "sender": label, "type": label, "tags": {"type": "array", "items": {"type": "object"}}, "folder": label,
        "auto": {"type": "object", "description": "Feature -> how it was set automatically: rule, learn, agent, import, code, photo"},
        "suggest": {"type": "object", "description": "Feature -> a suggestion waiting for review"}, "review": {"type": "boolean"},
        "text": {"type": "string", "description": "The recognised text (single document only)"}, "url": {"type": "string"},
        "content_url": {"type": "string"}, "asn": {"type": ["integer", "null"], "description": "Archive serial number (unique per workspace)"},
        # 2.121.0 A (#2092)
        "extracted": {"type": ["object", "null"], "description": "Single document only: what the recognition read off an invoice / receipt, "
                      "a suggestion a person takes over (supplier, vat_id, tax_no, invoice_no, vat_pct 19|7|0, vat_rates [{pct, net, vat}], "
                      "net, vat, gross, currency; new = fields a take-over would change, hidden = dismissed)"}}}
    schemas["DocumentPage"] = {"type": "object", "properties": {"data": {"type": "array", "items": ref("Document")},
                                                                "next_cursor": {"type": ["string", "null"]}}}
    T = "Documents"
    did = pid("id", "Document (file) id")
    patch = {"type": "object", "properties": {
        "date": {"type": ["string", "null"], "format": "date"}, "due": {"type": ["string", "null"], "format": "date"},
        "amount": {"type": ["string", "null"]}, "currency": {"type": ["string", "null"]}, "sender": {"type": ["string", "null"]},
        "type": {"type": ["string", "null"]}, "tags": {"type": "array", "items": {"type": "string"}},
        "text": {"type": "string", "description": "Only taken while the document has no recognised text"}}}
    paths["/documents"] = {"get": op("Documents shared with you (2.48.0)", T, ok(ref("DocumentPage")) | errs("400", "403"),
                                     [q("q", "Words of the text (whole words; 4+ letters also as a prefix). 2.122.0: search syntax tag:Name, "
                                         "sender:Name, type:Name, date:2025 | 2025-03 | 2025-01..2025-06 | >2025-01-01, added:<date>, "
                                         "\"exact phrase\", -word, -tag:Name (several tag: = every one; German keys absender:, typ:, datum:, eingang: too)"),
                                      q("tag", "2.122.0: tag ids; \"1,7;3\" = (1 or 7) and/or 3, see tag_mode"),
                                      q("tag_mode", "2.122.0: all = every tag group, any (default) = one of them"),
                                      q("not_tag", "2.122.0: tag ids the documents must not have"),
                                      q("sender", "2.122.0: sender ids (one of them)"), q("type", "2.122.0: document type ids (one of them)"),
                                      q("folder", "2.122.0: folder ids (the folder a document lies in)"),
                                      q("added_from", "2.122.0: arrived (added) from (YYYY-MM-DD)"), q("added_to", "2.122.0: arrived (added) to (YYYY-MM-DD)"),
                                      q("no_tag", "2.122.0: 1 = only documents without a tag"), q("no_sender", "2.122.0: 1 = only documents without a sender"),
                                      q("no_type", "2.122.0: 1 = only documents without a type"),
                                      q("ftype", "2.122.0: file types, comma-separated: pdf, image, office, text, other"),
                                      q("review", "1: only documents waiting in To review"),
                                      q("state", "wait, run, done or failed"), q("from", "Document date from (YYYY-MM-DD)"),
                                      q("to", "Document date to (YYYY-MM-DD)"), q("limit", "Page size", {"type": "integer"}), q("cursor", "Next page")],
                                     scope="files:read",
                                     desc="Documents are files of the file store with recognised text and fields. An agent sees only those "
                                          "shared with it (the file or a folder above it); every access is in the file's history.")}
    created = {"type": "object", "properties": {
        "content_base64": {"type": "string", "description": "The file (or send multipart with the field file)"}, "name": {"type": "string"},
        "title": {"type": "string", "description": "Name of the document (default: the file name)"}, "mime": {"type": "string"},
        "parent_id": {"type": "integer", "description": "A folder you may edit; an agent without it: its own result folder"},
        "ws": {"type": "string", "description": "A person without parent_id only: private (default) or org:<id>"},
        "sender": {"type": "string"}, "type": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}},
        "date": {"type": "string", "format": "date"}, "due": {"type": "string", "format": "date"},
        "amount": {"type": "string"}, "currency": {"type": "string"}}}
    paths["/documents"]["post"] = op("Create a document (2.122.0)", T, ok(ref("Document"), "Created", "201") | errs("400", "403", "404", "409", "413"), [], body=created,
                                      scope="files:write",
                                      desc="Stores the file like an upload and recognises it in the background (text, date, amount, sorting). "
                                           "An agent writes only into folders shared with it (role edit) or its own result folder; the "
                                           "creation is in the file's history.")
    paths["/documents/{id}"] = {
        "get": op("A document with its fields and the recognised text (2.48.0)", T, ok(ref("Document")) | errs("403", "404"), [did],
                  scope="files:read"),
        "patch": op("Set fields of a document (2.48.0)", T, ok(ref("Document")) | errs("400", "403", "404"), [did], body=patch,
                    scope="files:write",
                    desc="Needs the role edit. An agent's values are marked as set by an agent; a feature the workspace leaves to an "
                         "agent lands as a suggestion in To review instead, for a person to accept.")}
