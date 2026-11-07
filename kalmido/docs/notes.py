"""2.635.0 (#4807 d): notes on a document -- several per document, each with its author and time.

Who sees a document (the file store's rights, files/store.py need_node: the documents' own visibility check) sees its notes;
who may change it (role edit / owner) writes one. A note goes again with its author or with someone who may change the
document. The text is sealed with the workspace key like the document's other contents (docs/store.py doc_seal,
"doc_notes.text"); the notes are part of the document's word index (store.index_text). The Paperless-ngx import brings its
notes along (dn_import: author name + time of Paperless, source 'paperless'). Other devices learn of a change via db.bump.
Agents read the notes with the document (docs/v1.py: doc_json full); writing them is the people's alone for now."""
from datetime import timezone

from flask import jsonify

from ..core.config import app
from ..core.db import body, bump, db, err, insert_id, iso, now_iso, parse_iso
from ..core.access import Denied, acx_of
from ..core.i18n import tr
from ..accounts.session import me
from ..collab.comments import user_names
from ..files.store import need_node
from . import store as S

DN_MAX = 5000            # characters of one note
DN_PER_DOC = 500         # notes of one document at most
CTX = "doc_notes.text"


def dn_view(c, m, role, uid):
    """The notes of the document of doc_meta row m, oldest first: [{id, text, author: {id, name}, created_at, source,
    can_delete}] (role = the asker's role on the document)."""
    rows = c.execute("SELECT * FROM doc_notes WHERE node_id=? ORDER BY id", (m["node_id"],)).fetchall()
    if not rows:
        return []
    names = user_names(c, [r["user_id"] for r in rows])
    op = S.doc_opener(c, m["ws"], CTX)
    edit = role != "view"  # the roles of files/store.py fs_role: owner / edit may change the document
    return [{"id": r["id"], "text": op(r["text"]) or "",
             "author": {"id": r["user_id"], "name": names.get(r["user_id"]) or r["author"] or tr("Unknown")},
             "created_at": r["created_at"], "source": r["source"] or None,
             "can_delete": edit or (r["user_id"] is not None and r["user_id"] == uid)} for r in rows]


def dn_add(c, node, m, text, uid=None, author="", source="", at=None):
    """One note on the document (the caller checked the rights); returns its id. The word index is renewed."""
    nid = node["id"]
    cid = insert_id(c, "INSERT INTO doc_notes(org_id, ws, node_id, user_id, author, text, source, created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (node["org_id"], m["ws"], nid, uid, str(author or "")[:200], S.doc_seal(c, m["ws"], CTX, text), source, at or now_iso()))
    _reindex(c, nid)
    return cid


def _reindex(c, nid):
    m = S.meta_row(c, nid)
    node = c.execute("SELECT name FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    if m and node:
        S.doc_index(c, nid, m["ws"], S.index_text(c, dict(m), node["name"], S.meta_text_shown(c, m)))


def _when(v):
    """An imported note's time as UTC ISO text (None when it is no time: the note gets now)."""
    try:
        dt = parse_iso(str(v or "").strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return iso(dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


def dn_import(c, nid, notes):
    """The notes of an imported Paperless-ngx document ([{text, author, created}]) on the new document nid."""
    m = S.meta_row(c, nid)
    node = c.execute("SELECT id, org_id FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    if not m or not node:
        return 0
    n = 0
    for x in (notes or [])[:DN_PER_DOC]:
        x = x if isinstance(x, dict) else {"text": x}  # a ZIP scan of an older version kept the notes as plain texts
        t = str(x.get("text") or "").strip()[:DN_MAX]
        if not t:
            continue
        at = _when(x.get("created"))
        c.execute("INSERT INTO doc_notes(org_id, ws, node_id, user_id, author, text, source, created_at) VALUES(?,?,?,?,?,?,?,?)",
                  (node["org_id"], m["ws"], nid, None, str(x.get("author") or "")[:200], S.doc_seal(c, m["ws"], CTX, t), "paperless",
                   at or now_iso()))
        n += 1
    if n:
        _reindex(c, nid)
    return n


def _note_doc(c, nid, write=False):
    """(meta, node) of a document the signed-in person may see (write: change); never for an agent's token (its read is the
    document of /api/v1/documents)."""
    if acx_of(c, me()).role == "agent":  # like docs/web.py _no_agent (core/access.py AccessCtx: the asker's kind)
        raise Denied(403)
    n = need_node(c, nid, write=write)
    m = S.meta_row(c, nid)
    if not m:
        raise Denied(404)
    return m, n


@app.get("/api/docs/<int:nid>/notes")
def dn_list(nid):
    """The notes of a document: {notes: [...]}. Same rights as the document (404 when it cannot be seen)."""
    c = db()
    m, n = _note_doc(c, nid)
    return jsonify(notes=dn_view(c, m, n["role"], me()))


@app.post("/api/docs/<int:nid>/notes")
def dn_create(nid):
    """{text} -> 201 {note, notes}: a new note by the signed-in person; needs the right to change the document (403)."""
    c = db()
    m, n = _note_doc(c, nid, write=True)
    text = str(body().get("text") or "").strip()
    if not text:
        return err(tr("Write a note first"))
    if len(text) > DN_MAX:
        return err(tr("A note may have at most {0} characters", DN_MAX))
    if c.execute("SELECT COUNT(*) FROM doc_notes WHERE node_id=?", (nid,)).fetchone()[0] >= DN_PER_DOC:
        return err(tr("This document has too many notes"), 409)
    cid = dn_add(c, n, m, text, uid=me())
    bump(c)
    c.commit()
    notes = dn_view(c, m, n["role"], me())
    return jsonify(note=next((x for x in notes if x["id"] == cid), None), notes=notes), 201


@app.delete("/api/docs/<int:nid>/notes/<int:note_id>")
def dn_delete(nid, note_id):
    """Removes a note: its author (while they still see the document) or someone who may change the document; else 403."""
    c = db()
    m, n = _note_doc(c, nid)
    r = c.execute("SELECT id, user_id FROM doc_notes WHERE id=? AND node_id=?", (note_id, nid)).fetchone()
    if not r:
        raise Denied(404)
    if n["role"] == "view" and r["user_id"] != me():
        raise Denied(403)
    c.execute("DELETE FROM doc_notes WHERE id=?", (note_id,))
    _reindex(c, nid)
    bump(c)
    c.commit()
    return jsonify(notes=dn_view(c, m, n["role"], me()))
