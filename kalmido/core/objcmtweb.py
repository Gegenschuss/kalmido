"""2.981.0 (#5273, stage Q4b of the cross-cutting core): the generic routes of the comments' core (core/objcomments.py) -- one
address for the comments of every kind that registered its web hooks (ocm_kind(..., web={...}): 'video' = the comments of a
video / picture review, 'doc_note' = the notes on a document). The task's comments keep their own routes (files, answer
buttons, pushes: collab/comments.py); a kind without web hooks is 404 here.

  GET    /api/obj/<kind>/<id>/comments        the comments of the object, in the area's answer (a review: the review with its
                                              comments; a document: {notes})
  POST   /api/obj/<kind>/<id>/comments        a new comment {body | text, ...the area's fields} -> 201 (+ comment_id)
  PATCH  /api/obj/comments/<cid>              {body?, expect_updated_at?, ...the area's fields (a review: done)} -> 409 {comment}
                                              when it changed meanwhile
  DELETE /api/obj/comments/<cid>              into the trash (its author or 'manage' on the object)
  POST   /api/obj/comments/<cid>/restore      back from the trash (the same rule; 404 when the trash run was quicker)

The rules are the core's and the area's: reading the object first (the area's read hook: the review / the document as its own
routes check them, 404), then ocm_trash / ocm_restore / ocm_edit with the one rule (author or 'manage', the version). The
area's old addresses (/api/videos/<id>/comments..., /api/docs/<id>/notes...) stay and call the same functions."""
from flask import jsonify

from ..accounts.session import me
from .access import Denied
from .config import app
from .db import body, db
from .objcomments import OCM_HOOKS, ocm_restore, ocm_trash


def _web(kind):
    w = (OCM_HOOKS.get(kind) or {}).get("web")
    if not w:
        raise Denied(404)
    return w


def _row(c, cid, deleted=False):
    r = c.execute("SELECT id, kind, ref_id, deleted_at FROM obj_comments WHERE id=?", (int(cid),)).fetchone() if 0 < cid < 2 ** 62 else None
    if r is None or bool(r["deleted_at"]) != deleted:
        raise Denied(404)
    w = _web(r["kind"])
    w["read"](c, r["ref_id"], me())  # the object first: who may not see it gets 404 (never more than its area shows)
    return r, w


def _b():
    b = body()
    return b if isinstance(b, dict) else {}


@app.get("/api/obj/<kind>/<int:rid>/comments")
def ocw_list(kind, rid):
    c, uid = db(), me()
    w = _web(kind)
    w["read"](c, rid, uid)
    return jsonify(w["out"](c, rid, uid))


@app.post("/api/obj/<kind>/<int:rid>/comments")
def ocw_add(kind, rid):
    c, uid = db(), me()
    w = _web(kind)
    w["read"](c, rid, uid)
    cid = w["add"](c, rid, uid, _b())
    w["changed"](c, rid)
    c.commit()
    return jsonify({**w["out"](c, rid, uid), "comment_id": cid}), 201


@app.patch("/api/obj/comments/<int:cid>")
def ocw_patch(cid):
    c, uid = db(), me()
    r, w = _row(c, cid)
    w["patch"](c, r["ref_id"], r["id"], uid, _b())
    w["changed"](c, r["ref_id"])
    c.commit()
    return jsonify(w["out"](c, r["ref_id"], uid))


@app.delete("/api/obj/comments/<int:cid>")
def ocw_delete(cid):
    c, uid = db(), me()
    r, w = _row(c, cid)
    ocm_trash(c, r["id"], uid)  # the core's rule: its author or 'manage' on the object (403)
    w["changed"](c, r["ref_id"])
    c.commit()
    return jsonify(w["out"](c, r["ref_id"], uid))


@app.post("/api/obj/comments/<int:cid>/restore")
def ocw_restore(cid):
    c, uid = db(), me()
    r, w = _row(c, cid, deleted=True)
    if not ocm_restore(c, r["id"], uid):  # nothing kept: the trash run was quicker
        raise Denied(404)
    w["changed"](c, r["ref_id"])
    c.commit()
    return jsonify(w["out"](c, r["ref_id"], uid))
