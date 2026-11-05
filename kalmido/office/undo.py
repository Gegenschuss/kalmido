"""2.111.0 A (#2233): Undo for the office editors that save every field at once (documents with their parts, clients, the
master data like services). 2.567.0 (#4711, the shared core stage 2): the steps live in the core's obj_undo (core/writes.py
obj_undo_pre / obj_undo_post / obj_undo_run), one tracked kind per object kind (OUN_KINDS: its tables = the scope) instead of
the hand list of office_undo; the letters and the office rows of office/owrite.py ow_write have their steps there too. The
table office_undo stays (read by nothing any more, its rows go after a day; the way back = the old code).

The app sends the header X-Kalmido-Undo: <session token> with the saves of an open editor (static/js/office_undo.js). The
write routes call oun_pre() before they change anything (raw copy of the object's rows = the state before the step, its
fingerprint) and oun_post() right before their commit (fingerprint of the state after the step), both in the route's own
transaction. Without the header nothing is recorded (agents, API v1, other clients stay as they are).

POST /api/office/undo/<doc|client|letter|<master data kind>|<ow kind>>/<id> {sess, op: undo | redo | all | redoall} writes
such a copy back -- only while the object is exactly as this person's last step left it (fingerprint), so a change by
someone else (or an own action without undo: finalise, send, payment, status, DATEV) in between is never overwritten: 409
with a readable reason. A finalised / sent document stays as it is (409). Rights as for the normal change of the object.
Copies live one day (KEEP_H): the watchdog (oun_prune) and every new session remove older ones."""
from datetime import timedelta

from flask import jsonify

from ..core.config import app
from ..core.i18n import N_, tr
from ..core.db import body, bump, db, iso, now_utc
from ..core.access import Denied
from ..core.writes import OBJ_TRACK, UNDO_KEEP_H, _fp, _undo_args, obj_undo_post, obj_undo_pre, obj_undo_run, undo_scope
from .model import MD, office_role, office_row, sr_public  # 2.369.5 (#2517): pulled up from functions
from .ledger import ofx_locked, ofx_log  # 2.369.5 (#2517): pulled up from functions
from .owrite import OW_UNDO_CTX, ow_kind
from ..accounts.session import me  # 2.369.5 (#2517): pulled up from functions
from ..team.clients import _gate, client_public, need_client  # 2.369.5 (#2517): pulled up from functions

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
DOC_NOFP = {"office_docs": {"number", "totals"}}
OUN_KINDS = {"doc": "office_doc", "client": "client", "letter": "office_letter", **{k: f"office_md_{k}" for k in MD}}  # route kind -> core kind
ow_kind("office_doc", "office_docs", scope=_doc_scope, keep=DOC_KEEP, nofp=DOC_NOFP)
ow_kind("client", "clients", scope=lambda ref, oid: [("clients", "id=?", (ref,), False), ("office_client_contacts", "client_id=?", (ref,), True)])
for _k in MD:
    ow_kind(f"office_md_{_k}", MD[_k]["table"], scope=_md_scope(_k))


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


OUN_PRUNE = {"at": 0.0}


def oun_prune(c):
    """The watchdog (at most hourly, system context): copies older than KEEP_H go, also those of deleted documents and
    clients (nothing of a deleted object stays longer than a day); the old table office_undo drains the same way."""
    import time
    if time.time() - OUN_PRUNE["at"] < 3600:
        return
    OUN_PRUNE["at"] = time.time()
    lim = iso(now_utc() - timedelta(hours=KEEP_H))
    c.execute("DELETE FROM office_undo WHERE created_at<?", (lim,))
    c.execute("DELETE FROM obj_undo WHERE created_at<?", (lim,))
    c.commit()


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
    left = obj_undo_run(c, uid, oun_kind(kind), ref, oid, b.get("sess"), op, fix=fix)
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
