"""2.635.0 (#4807 d): notes on a document -- several per document, each with its author and time.

Who sees a document (the file store's rights, files/store.py need_node: the documents' own visibility check) sees its notes;
who may change it (role edit / owner) writes one. A note goes again with its author or with someone who may change the
document. The text is sealed with the workspace key like the document's other contents (docs/store.py doc_seal,
"doc_notes.text"); the notes are part of the document's word index (store.index_text). The Paperless-ngx import brings its
notes along (dn_import: author name + time of Paperless, source 'paperless'). Other devices learn of a change via db.bump.
Agents read the notes with the document (docs/v1.py: doc_json full); writing them is the people's alone for now.

2.981.0 (#5273, stage Q4b of the cross-cutting core): a note is a row of the comments' core (obj_comments kind 'doc_note',
ref_id = the document's node; the name it came with in ext_name, its source in extra). Deleting puts it into the core's trash
(was a hard DELETE, B6): its sealed text waits in obj_comment_trash, POST .../restore brings it back, the core's trash run
deletes it after the trash period. The text stays sealed with the context "doc_notes.text" (no new sealing)."""
from datetime import timezone

from flask import jsonify

from ..core.config import app
from ..core.db import body, bump, db, iso, parse_iso
from ..core.access import Denied, acx_of, live_sql
from ..core.objcomments import OCM_TS, ocm_add, ocm_edit, ocm_kind, ocm_may_read, ocm_restore, ocm_trash  # 2.981.0 (#5273): the comments' core
from ..core.objsearch import osr_kind  # 2.981.0 (#5273 x #5278): the shared search
from ..core.errors import BadInput  # 2.981.0 (#5273)
from ..core.i18n import tr
from ..accounts.session import me
from ..collab.comments import user_names
from ..files.store import fs_chain, fs_deleted, fs_role, need_node  # 2.981.0 (#5273): + the role of the notes' kind
from . import store as S

DN_MAX = 5000            # characters of one note
DN_PER_DOC = 500         # notes of one document at most
CTX = "doc_notes.text"
DN_KIND = "doc_note"  # 2.981.0 (#5273): the kind of obj_comments
DN_COLS = (f"id, ref_id AS node_id, user_id, ext_name AS author, body AS text, COALESCE(extra->>'source', '') AS source, "
           f"to_char(created_at AT TIME ZONE 'UTC', '{OCM_TS}') AS created_at")  # the old columns of doc_notes (exports read them too)


def dn_rows(c, nids):
    """2.981.0 (#5273): the live notes of the documents nids (old columns, DN_COLS), oldest first."""
    ids = [int(n) for n in nids]
    if not ids:
        return []
    return c.execute(f"SELECT {DN_COLS} FROM obj_comments WHERE kind=? AND ref_id IN ({','.join('?' * len(ids))}) AND {live_sql()} "
                     "ORDER BY id", (DN_KIND, *ids)).fetchall()


def dn_view(c, m, role, uid):
    """The notes of the document of doc_meta row m, oldest first: [{id, text, author: {id, name}, created_at, source,
    can_delete}] (role = the asker's role on the document)."""
    rows = dn_rows(c, [m["node_id"]])
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
    cid = ocm_add(c, DN_KIND, nid, uid, S.doc_seal(c, m["ws"], CTX, text), ext_name=str(author or "")[:200] or None,
                  extra={"source": source or None}, created_at=at, org_id=node["org_id"])  # 2.981.0 (#5273)
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
        ocm_add(c, DN_KIND, nid, None, S.doc_seal(c, m["ws"], CTX, t), ext_name=str(x.get("author") or "")[:200] or None,
                extra={"source": "paperless"}, created_at=at, org_id=node["org_id"])  # 2.981.0 (#5273)
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


def dn_new(c, nid, b):
    """A note {text} (or body: the core's generic route) by the signed-in person on document nid (the right to change it, 403)
    -> its id."""
    m, n = _note_doc(c, nid, write=True)
    text = str(b.get("text") or b.get("body") or "").strip()
    if not text:
        raise BadInput(tr("Write a note first"))
    if len(text) > DN_MAX:
        raise BadInput(tr("A note may have at most {0} characters", DN_MAX))
    if len(dn_rows(c, [nid])) >= DN_PER_DOC:
        raise Denied(409, tr("This document has too many notes"))
    return dn_add(c, n, m, text, uid=me())


@app.post("/api/docs/<int:nid>/notes")
def dn_create(nid):
    """{text} -> 201 {note, notes}: a new note by the signed-in person; needs the right to change the document (403)."""
    c = db()
    b = body()
    cid = dn_new(c, nid, b if isinstance(b, dict) else {})
    m, n = _note_doc(c, nid)
    bump(c)
    c.commit()
    notes = dn_view(c, m, n["role"], me())
    return jsonify(note=next((x for x in notes if x["id"] == cid), None), notes=notes), 201


def _dn_note(c, nid, note_id, deleted=False):
    r = c.execute("SELECT id, user_id, deleted_at FROM obj_comments WHERE id=? AND kind=? AND ref_id=?", (note_id, DN_KIND, nid)).fetchone()
    if not r or bool(r["deleted_at"]) != deleted:
        raise Denied(404)
    return r


@app.delete("/api/docs/<int:nid>/notes/<int:note_id>")
def dn_delete(nid, note_id):
    """Removes a note: its author (while they still see the document) or someone who may change the document; else 403.
    2.981.0 (#5273): into the core's trash (restore: POST .../restore; gone for good after the trash period)."""
    c = db()
    m, n = _note_doc(c, nid)
    _dn_note(c, nid, note_id)
    ocm_trash(c, note_id, me())  # the core's rule: the author or 'manage' (who may change the document)
    _reindex(c, nid)
    bump(c)
    c.commit()
    return jsonify(notes=dn_view(c, m, n["role"], me()))


@app.post("/api/docs/<int:nid>/notes/<int:note_id>/restore")
def dn_restore(nid, note_id):
    """2.981.0 (#5273): a note back from the trash (its author or who may change the document) -> {notes}."""
    c = db()
    m, n = _note_doc(c, nid)
    _dn_note(c, nid, note_id, deleted=True)
    if not ocm_restore(c, note_id, me()):
        raise Denied(404)
    _reindex(c, nid)
    bump(c)
    c.commit()
    return jsonify(notes=dn_view(c, m, n["role"], me()))


def _dn_base(c, uid, nid):
    """The role of uid on a document for its notes (core/objcomments.py, hook role): the file store's -- 'manage' for who may
    change it (owner / edit), 'view' for who reads it, None in the trash or for an agent (its read is docs/v1.py)."""
    if not uid or acx_of(c, uid).role == "agent":
        return None
    ch = fs_chain(c, int(nid))
    if not ch or fs_deleted(ch):
        return None
    r = fs_role(c, int(nid), uid, chain=ch)
    return "manage" if r in ("owner", "edit") else "view" if r else None


def _dn_seal(c, nid, text):
    m = S.meta_row(c, nid)
    if not m:
        raise Denied(404)
    return S.doc_seal(c, m["ws"], CTX, text)


def _dn_out(c, nid, uid):
    m, n = _note_doc(c, nid)
    return {"notes": dn_view(c, m, n["role"], uid)}


def _dn_patch(c, nid, cid, uid, b):
    """A note's text changed by its author (the core's edit: version, lock comment-<id>, 409 with the note)."""
    if "body" in b or "text" in b:
        ocm_edit(c, cid, uid, {**b, "body": str(b.get("body") if "body" in b else b.get("text") or "")})


def _dn_changed(c, nid):
    _reindex(c, nid)
    bump(c)


# 2.981.0 (#5273): the generic routes of core/objcmtweb.py (/api/obj/doc_note/<document>/comments, /api/obj/comments/<cid>)
DN_WEB = {"read": lambda c, nid, uid: _note_doc(c, nid), "add": lambda c, nid, uid, b: dn_new(c, nid, b), "patch": _dn_patch,
          "out": _dn_out, "changed": _dn_changed}
# 2.981.0 (#5273 x #5278): a note is found by the shared search for who sees the document (the file store's role); a note
# sealed with the workspace key (a server key set) has no readable words there -- the documents' own word index finds it
osr_kind(DN_KIND, may_read=lambda c, uid, nid: ocm_may_read(c, uid, DN_KIND, nid))
ocm_kind(DN_KIND, obj="fs_entry", role=_dn_base, people=lambda c, nid: set(), sealed=lambda c, nid: False,
         sealed_in=lambda c, nid, t: (t, []), text_max=lambda t: DN_MAX, seal=_dn_seal, web=DN_WEB)
