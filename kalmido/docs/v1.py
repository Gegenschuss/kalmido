"""2.48.0 (#1111): documents for agents (API v1; scopes files:read / files:write of the file store).

An agent reads only the documents whose file (or a folder above it) is shared with it (kalmido/files/store.py): their
fields and the recognised text. With the role 'edit' it may set fields; they are marked "set by an agent". A feature the
workspace has on level "agent" is not set directly: the value lands as a suggestion in "To review" for a person to accept.
Every access of an agent goes into the file's history (fs_log). Documents are never moved by an agent."""
from flask import jsonify

from ..core.config import app
from ..core.db import bump, db
from ..core.i18n import tr
from ..core.access import Denied
from ..accounts.session import me
from ..api.v1 import BadInput, UnknownFields, cursor_dec, cursor_enc, v1_args, v1_json, v1_limit, v1_view
from ..files.store import fs_log_add, need_node
from . import store as S
from .web import doc_json, doc_query, doc_update

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
    """Documents you may see (an agent: shared with it), newest document date first: ?q=&review=1&state=&from=&to=."""
    a = v1_args(("q", "review", "state", "from", "to", "limit", "cursor"))
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
        "content_url": {"type": "string"}, "asn": {"type": ["integer", "null"], "description": "Archive serial number (unique per workspace)"}}}
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
                                     [q("q", "Words of the text (whole words; 4+ letters also as a prefix)"),
                                      q("review", "1: only documents waiting in To review"),
                                      q("state", "wait, run, done or failed"), q("from", "Document date from (YYYY-MM-DD)"),
                                      q("to", "Document date to (YYYY-MM-DD)"), q("limit", "Page size", {"type": "integer"}), q("cursor", "Next page")],
                                     scope="files:read",
                                     desc="Documents are files of the file store with recognised text and fields. An agent sees only those "
                                          "shared with it (the file or a folder above it); every access is in the file's history.")}
    paths["/documents/{id}"] = {
        "get": op("A document with its fields and the recognised text (2.48.0)", T, ok(ref("Document")) | errs("403", "404"), [did],
                  scope="files:read"),
        "patch": op("Set fields of a document (2.48.0)", T, ok(ref("Document")) | errs("400", "403", "404"), [did], body=patch,
                    scope="files:write",
                    desc="Needs the role edit. An agent's values are marked as set by an agent; a feature the workspace leaves to an "
                         "agent lands as a suggestion in To review instead, for a person to accept.")}
