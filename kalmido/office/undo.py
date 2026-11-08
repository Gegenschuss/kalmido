"""2.111.0 A (#2233): Undo for the office editors that save every field at once (documents with their parts, clients, the
master data like services). 2.567.0 (#4711, the shared core stage 2): the steps live in the core's obj_undo (core/writes.py
obj_undo_pre / obj_undo_post / obj_undo_run), one tracked kind per object kind (OUN_KINDS: its tables = the scope) instead of
the hand list of office_undo; the letters and the office rows of office/owrite.py ow_write have their steps there too.
2.747.0 (#5246): the table office_undo is gone (migrations.d/5246.py).

The app sends the header X-Kalmido-Undo: <session token> with the saves of an open editor (static/js/office_undo.js). The
write routes call oun_pre() before they change anything (raw copy of the object's rows = the state before the step, its
fingerprint) and oun_post() right before their commit (fingerprint of the state after the step), both in the route's own
transaction. Without the header nothing is recorded (agents, API v1, other clients stay as they are).

POST /api/office/undo/<doc|client|letter|<master data kind>|<ow kind>>/<id> {sess, op: undo | redo | all | redoall} writes
such a copy back -- only while the object is exactly as this person's last step left it (fingerprint), so a change by
someone else (or an own action without undo: finalise, send, payment, status, DATEV) in between is never overwritten: 409
with a readable reason. A finalised / sent document stays as it is (409). Rights as for the normal change of the object.
Copies live KEEP_H (2.747.0 #5249: 30 days, was a day): the watchdog (core/undogroups.py undo_prune) and every new session
remove older ones. 2.747.0 (#5252): finalising, sending, a payment, DATEV and the period lock also write a barrier into the
person's step groups (office/oubar.py); this session undo keeps its own guard (_ctx: OUN_FINAL, the fingerprint)."""
from flask import jsonify

from ..core.config import app
from ..core.i18n import N_, tr
from ..core.db import body, bump, db
from ..core.access import Denied
from ..core.writes import OBJ_TRACK, UNDO_KEEP_H, _fp, _undo_args, obj_undo_post, obj_undo_pre, obj_undo_run, undo_scope
from .model import MD, office_role, office_row, sr_public  # 2.369.5 (#2517): pulled up from functions
from .ledger import ofx_locked, ofx_log  # 2.369.5 (#2517): pulled up from functions
from .owrite import OW_UNDO_CTX, ow_kind
from .oubar import oub_label_client, oub_label_doc, oub_label_md  # 2.747.0 (#5252)
from ..accounts.session import me  # 2.369.5 (#2517): pulled up from functions
from ..team.clients import CLIENT_BILL_GATED, _gate, cl_bill_ok, client_public, need_client  # 2.369.5 (#2517): pulled up from functions

HDR = "X-Kalmido-Undo"
KEEP_H = UNDO_KEEP_H

OUN_CONFLICT = N_("Changed by someone else in the meantime, so it cannot be undone")
OUN_FINAL = N_("Finalised or sent in the meantime, so the changes stay")
OUN_MOVED = N_("Moved to another workspace in the meantime, so it cannot be undone")
OUN_NOTHING = N_("Nothing to undo")


# ---------------------------------------------------------------- the kinds (2.567.0 #4711: scope per kind, core obj_track)
def _doc_scope(ref, oid):
    return [("office_docs", "id=? AND org_id=?", (ref, oid), False), ("office_doc_parts", "doc_id=? AND org_id=?", (ref, oid), True),
            ("office_doc_items", "doc_id=?", (ref,), True)]


def _md_scope(kind):
    return lambda ref, oid: [(MD[kind]["table"], "id=? AND org_id=?", (ref, oid), False)]


# 2.190.0 R (#2496): a number drawn since stays on undo and never makes it fail; cached sums never make it fail either
DOC_KEEP = {"office_docs": {"number"}}
DOC_NOFP = {"office_docs": {"number", "totals"}, "office_doc_parts": {"totals"}}  # the parts' sums too (recalc after each undo)
OUN_KINDS = {"doc": "office_doc", "client": "client", "letter": "office_letter", **{k: f"office_md_{k}" for k in MD}}  # route kind -> core kind
ow_kind("office_doc", "office_docs", scope=_doc_scope, keep=DOC_KEEP, nofp=DOC_NOFP, label=oub_label_doc)  # 2.747.0 (#5252): labels
ow_kind("client", "clients", scope=lambda ref, oid: [("clients", "id=?", (ref,), False), ("office_client_contacts", "client_id=?", (ref,), True)],
        label=oub_label_client)
for _k in MD:
    ow_kind(f"office_md_{_k}", MD[_k]["table"], scope=_md_scope(_k), label=oub_label_md(MD[_k]["label"]))


def oun_kind(kind):
    """The core kind of an office undo kind ('doc', 'client', a master data kind, or a tracked ow kind itself); 404 else."""
    k = OUN_KINDS.get(kind) or (kind if kind in OBJ_TRACK and kind.startswith("office_") else None)
    if not k:
        raise Denied(404)
    return k


def oun_scope(kind, ref, oid):
    """[(table, where, args, several rows?)] of an object; the first table is its main row (locked while recording)."""
    return undo_scope(oun_kind(kind), ref, oid)


def oun_fp(snap):
    """The fingerprint of a copy (a document: without its number and sums)."""
    return _fp(snap, DOC_NOFP)


# 2.747.0 (#5252): oun_prune went -- the watchdog's core/undogroups.py undo_prune removes every copy older than KEEP_H (30
# days, core/writes.py UNDO_KEEP_H) with its group, the groups over the cap per person and the parts without a group.


# ---------------------------------------------------------------- recording (hooks of the write routes)
def oun_pre(c, uid, oid, kind, ref):
    """Before a write route changes object (kind, ref): with the header, the state before = one step of the session."""
    obj_undo_pre(c, uid, oun_kind(kind), ref, oid)


def oun_post(c):
    """Right before the write route's commit: the state after the step (what an undo expects to find)."""
    obj_undo_post(c)


# ---------------------------------------------------------------- undo / redo
def _ctx(kind, ref):
    """-> (c, uid, oid, after) with the rights of a normal change of the object; after(c) = the answer."""
    c = db()
    if kind == "doc":
        from .docs import _ctx as dctx, doc_public, doc_row
        c, uid, oid = dctx()
        r = doc_row(c, oid, ref)
        if ofx_locked(r) or r["status"] == "sent":
            raise Denied(409, tr(OUN_FINAL))
        return c, uid, oid, lambda c: doc_public(c, oid, doc_row(c, oid, ref), office_role(c, uid, oid) == "admin")
    if kind == "client":
        uid = me()
        _gate(c)
        need_client(c, ref, uid)
        return c, uid, None, lambda c: client_public(c, uid, need_client(c, ref, uid), stats=True)
    if kind in OW_UNDO_CTX:  # 2.567.0 (#4711): the letters and the other office rows on office/owrite.py
        return OW_UNDO_CTX[kind](ref)
    if kind not in MD:
        raise Denied(404)
    from .web import _ctx as wctx
    c, uid, oid = wctx(admin=True)
    office_row(c, oid, kind, ref)
    return c, uid, oid, lambda c: sr_public(kind, office_row(c, oid, kind, ref), office_role(c, uid, oid) == "admin")


@app.post("/api/office/<kind>/<int:ref>/undo")
def oun_restore_md(kind, ref):
    """2.747.0 (#5246): the browser's objsave.js objUndo of a master data dialog (POST <its save url>/undo) -- the same as
    /api/office/undo/<kind>/<id>, only for the master data kinds."""
    if kind not in MD:
        raise Denied(404)
    return oun_restore(kind, ref)


@app.post("/api/clients/<int:ref>/undo")
def oun_restore_client(ref):
    """2.747.0 (#5246): objsave.js objUndo of the client dialog (POST <its save url>/undo)."""
    return oun_restore("client", ref)


@app.post("/api/office/undo/<kind>/<int:ref>")
def oun_restore(kind, ref):
    """{sess, op}: undo = the newest own step back, all = every own step of the session (back to the opening), redo /
    redoall = the way forward again. 409 when someone else changed it meanwhile or it is finalised / sent / moved."""
    b = body()
    b = b if isinstance(b, dict) else {}
    op = b.get("op") or "undo"
    _undo_args(b.get("sess"), op)
    oun_kind(kind)
    c, uid, oid, after = _ctx(kind, ref)
    fix = None
    if kind == "doc":
        from .docs import recalc
        fix = lambda c: recalc(c, oid, ref)  # noqa: E731 -- the sums and the parts' title page lines, as after a normal change
    keep = None
    if kind == "client" and not cl_bill_ok(c, uid, need_client(c, ref, uid)["org_id"], "edit"):
        keep = {"clients": set(CLIENT_BILL_GATED)}  # 2.577.0 (#3964): like cl_bill_strip -- fields uid may not change stay as they are
    left = obj_undo_run(c, uid, oun_kind(kind), ref, oid, b.get("sess"), op, fix=fix, keep=keep,
                        lock=f"office_doc_{int(ref)}" if kind == "doc" else None)  # 2.747.0 (#5252, review F3): with finalising / numbering / status
    if oid is not None:
        if kind == "doc":
            ofx_log(c, oid, "update", doc_id=ref, detail={"undo": op})
        else:
            ofx_log(c, oid, "update", target=kind, detail={"id": ref, "undo": op})
    bump(c)
    c.commit()
    out = after(c)
    out["undo_steps"] = left
    return jsonify(out)
