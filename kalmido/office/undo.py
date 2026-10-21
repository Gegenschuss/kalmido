"""2.111.0 A (#2233): Undo for the office editors that save every field at once (documents with their parts, clients, the
master data like services). Table office_undo (schema.py): one row per own saved change of one editor session.

The app sends the header X-Kalmido-Undo: <session token> with the saves of an open editor (static/js/office_undo.js). The
write routes call oun_pre() before they change anything (raw copy of the object's rows = the state before the step, its
fingerprint) and oun_post() right before their commit (fingerprint of the state after the step), both in the route's own
transaction. Without the header nothing is recorded (agents, API v1, other clients stay as they are).

POST /api/office/undo/<doc|client|<master data kind>>/<id> {sess, op: undo | redo | all | redoall} writes such a copy
back -- only while the object is exactly as this person's last step left it (fingerprint), so a change by someone else
(or an own action without undo: finalise, send, payment, status, DATEV) in between is never overwritten: 409 with a
readable reason. A finalised / sent document stays as it is (409). Rights as for the normal change of the object.
Copies live one day (KEEP_H): the watchdog (oun_prune) and every new session remove older ones."""
import base64
import hashlib
import json
import re
from datetime import timedelta

from flask import g, jsonify, request

from ..core.config import app
from ..core.pg import insert_id, table_columns, write_lock
from ..core.i18n import N_, tr
from ..core.db import body, bump, db, iso, now_utc
from ..core.access import Denied
from ..core.errors import BadInput

HDR = "X-Kalmido-Undo"
TOK_RE = re.compile(r"[a-f0-9]{16,64}")
OPS = ("undo", "redo", "all", "redoall")
KEEP_H = 24
MAX_STEPS = 60  # more: the two oldest steps become one (Undo all still goes back to the opening)
NO_FP = {"updated_at", "totals"}  # time stamps and cached sums never make an undo fail
FIXED = {"id", "org_id", "kind", "created_at", "created_by"}  # never written back: the identity of a row

OUN_CONFLICT = N_("Changed by someone else in the meantime, so it cannot be undone")
OUN_FINAL = N_("Finalised or sent in the meantime, so the changes stay")
OUN_MOVED = N_("Moved to another workspace in the meantime, so it cannot be undone")
OUN_NOTHING = N_("Nothing to undo")


# ---------------------------------------------------------------- copies of an object
def oun_scope(kind, ref, oid):
    """[(table, where, args, several rows?)] of an object; the first table is its main row (locked while recording)."""
    if kind == "doc":
        return [("office_docs", "id=? AND org_id=?", (ref, oid), False), ("office_doc_parts", "doc_id=? AND org_id=?", (ref, oid), True),
                ("office_doc_items", "doc_id=?", (ref,), True)]
    if kind == "client":
        return [("clients", "id=?", (ref,), False), ("office_client_contacts", "client_id=?", (ref,), True)]
    from .model import MD
    if kind in MD:
        return [(MD[kind]["table"], "id=? AND org_id=?", (ref, oid), False)]
    raise Denied(404)


def _val(v):
    if isinstance(v, (bytes, bytearray, memoryview)):
        return {"$b": base64.b64encode(bytes(v)).decode()}
    return v


def _unval(v):
    return base64.b64decode(v["$b"]) if isinstance(v, dict) and "$b" in v else v


def oun_snap(c, sc):
    """{table: [rows as dicts]} -- the raw rows (encrypted columns stay sealed as they are stored)."""
    out = {}
    for t, where, args, _many in sc:
        rows = c.execute(f"SELECT * FROM {t} WHERE {where} ORDER BY id", args).fetchall()
        out[t] = [{k: _val(r[k]) for k in r.keys()} for r in rows]
    return out


def oun_fp(snap):
    s = {t: [{k: v for k, v in r.items() if k not in NO_FP} for r in rows] for t, rows in snap.items()}
    return hashlib.sha256(json.dumps(s, sort_keys=True, default=str).encode()).hexdigest()


def _lock(c, sc):
    t, where, args, _many = sc[0]
    c.execute(f"SELECT id FROM {t} WHERE {where} FOR UPDATE", args).fetchall()


def oun_write(c, sc, snap):
    """Writes copy snap back: the main row is updated (not its identity), the rows of the other tables are replaced by the
    copied ones with their old ids (positions, parts and contact persons keep their ids, references stay valid)."""
    for t, where, args, many in reversed(sc):
        if many:
            c.execute(f"DELETE FROM {t} WHERE {where}", args)
    for t, where, args, many in sc:
        cols = table_columns(c, t)
        rows = snap.get(t) or []
        if not many:
            if not rows:
                continue
            row = {k: _unval(v) for k, v in rows[0].items() if k in cols and k not in FIXED}
            if "updated_at" in cols:
                row["updated_at"] = iso(now_utc())
            if row:
                c.execute(f"UPDATE {t} SET {','.join(k + '=?' for k in row)} WHERE {where}", [*row.values(), *args])
            continue
        for r in rows:
            row = {k: _unval(v) for k, v in r.items() if k in cols}
            c.execute(f"INSERT INTO {t}({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))


OUN_PRUNE = {"at": 0.0}


def oun_prune(c):
    """The watchdog (at most hourly, system context): copies older than KEEP_H go, also those of deleted documents and
    clients (nothing of a deleted object stays longer than a day)."""
    import time
    if time.time() - OUN_PRUNE["at"] < 3600:
        return
    OUN_PRUNE["at"] = time.time()
    c.execute("DELETE FROM office_undo WHERE created_at<?", (iso(now_utc() - timedelta(hours=KEEP_H)),))
    c.commit()


# ---------------------------------------------------------------- recording (hooks of the write routes)
def _token():
    tok = (request.headers.get(HDR) or "").strip().lower()
    return tok if TOK_RE.fullmatch(tok) else ""


def oun_pre(c, uid, oid, kind, ref):
    """Before a write route changes object (kind, ref): with the header, the state before = one step of the session."""
    tok = _token()
    u = getattr(g, "user", None)
    if not tok or not u or (u["kind"] or "user") == "agent":
        return
    sc = oun_scope(kind, ref, oid)
    _lock(c, sc)  # nobody writes between the copy and this change
    snap = oun_snap(c, sc)
    main = (snap.get(sc[0][0]) or [None])[0]
    if not main:
        return
    key = (uid, tok, kind, ref)
    c.execute("DELETE FROM office_undo WHERE user_id=? AND sess=? AND kind=? AND ref_id=? AND state<>'done'", key)  # a new step ends the way forward
    rows = c.execute("SELECT id, seq, fp_after FROM office_undo WHERE user_id=? AND sess=? AND kind=? AND ref_id=? ORDER BY seq", key).fetchall()
    if not rows:
        c.execute("DELETE FROM office_undo WHERE created_at<?", (iso(now_utc() - timedelta(hours=KEEP_H)),))
    elif len(rows) >= MAX_STEPS:  # the second step merges into the first (its state after = the first's state after)
        c.execute("UPDATE office_undo SET fp_after=? WHERE id=?", (rows[1]["fp_after"], rows[0]["id"]))
        c.execute("DELETE FROM office_undo WHERE id=?", (rows[1]["id"],))
    sid = insert_id(c, "INSERT INTO office_undo(org_id, user_id, sess, kind, ref_id, seq, state, snap, fp_before, fp_after, created_at) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (main.get("org_id"), uid, tok, kind, ref, (rows[-1]["seq"] + 1) if rows else 1, "done",
                     json.dumps(snap, ensure_ascii=False), oun_fp(snap), "", iso(now_utc())))
    g.oun_step = (sid, sc)


def oun_post(c):
    """Right before the write route's commit: the state after the step (what an undo expects to find)."""
    st = g.pop("oun_step", None)
    if st:
        c.execute("UPDATE office_undo SET fp_after=? WHERE id=?", (oun_fp(oun_snap(c, st[1])), st[0]))


# ---------------------------------------------------------------- undo / redo
def _ctx(kind, ref):
    """-> (c, uid, oid, after) with the rights of a normal change of the object; after(c) = the answer."""
    c = db()
    if kind == "doc":
        from .docs import _ctx as dctx, doc_public, doc_row
        from .ledger import ofx_locked
        from .model import office_role
        c, uid, oid = dctx()
        r = doc_row(c, oid, ref)
        if ofx_locked(r) or r["status"] == "sent":
            raise Denied(409, tr(OUN_FINAL))
        return c, uid, oid, lambda c: doc_public(c, oid, doc_row(c, oid, ref), office_role(c, uid, oid) == "admin")
    if kind == "client":
        from ..accounts.session import me
        from ..team.clients import _gate, client_public, need_client
        uid = me()
        _gate(c)
        need_client(c, ref, uid)
        return c, uid, None, lambda c: client_public(c, uid, need_client(c, ref, uid), stats=True)
    from .model import MD, office_role, office_row, sr_public
    if kind not in MD:
        raise Denied(404)
    from .web import _ctx as wctx
    c, uid, oid = wctx(admin=True)
    office_row(c, oid, kind, ref)
    return c, uid, oid, lambda c: sr_public(kind, office_row(c, oid, kind, ref), office_role(c, uid, oid) == "admin")


def _same_space(snap, cur, sc):
    t = sc[0][0]
    a, b = (snap.get(t) or [{}])[0], (cur.get(t) or [{}])[0]
    return a.get("org_id") == b.get("org_id")


def _undo_one(c, sc, st, fix):
    cur = oun_snap(c, sc)
    if not st["fp_after"] or oun_fp(cur) != st["fp_after"]:
        raise Denied(409, tr(OUN_CONFLICT))
    old = json.loads(st["snap"])
    if not _same_space(old, cur, sc):
        raise Denied(409, tr(OUN_MOVED))
    oun_write(c, sc, old)
    fix(c)
    c.execute("UPDATE office_undo SET state='undone', redo=?, fp_undone=? WHERE id=?",
              (json.dumps(cur, ensure_ascii=False), oun_fp(oun_snap(c, sc)), st["id"]))


def _redo_one(c, sc, st, fix):
    cur = oun_snap(c, sc)
    if not st["fp_undone"] or oun_fp(cur) != st["fp_undone"] or not st["redo"]:
        raise Denied(409, tr(OUN_CONFLICT))
    new = json.loads(st["redo"])
    if not _same_space(new, cur, sc):
        raise Denied(409, tr(OUN_MOVED))
    oun_write(c, sc, new)
    fix(c)
    c.execute("UPDATE office_undo SET state='done', redo=NULL, fp_undone=NULL, fp_after=? WHERE id=?", (oun_fp(oun_snap(c, sc)), st["id"]))


@app.post("/api/office/undo/<kind>/<int:ref>")
def oun_restore(kind, ref):
    """{sess, op}: undo = the newest own step back, all = every own step of the session (back to the opening), redo /
    redoall = the way forward again. 409 when someone else changed it meanwhile or it is finalised / sent / moved."""
    b = body()
    b = b if isinstance(b, dict) else {}
    tok, op = str(b.get("sess") or "").strip().lower(), b.get("op") or "undo"
    if not TOK_RE.fullmatch(tok) or op not in OPS:
        raise BadInput(tr("Invalid data"))
    c, uid, oid, after = _ctx(kind, ref)
    write_lock(c, f"oun:{kind}:{ref}")
    sc = oun_scope(kind, ref, oid)
    _lock(c, sc)
    steps = c.execute("SELECT id, seq, state, snap, redo, fp_after, fp_undone FROM office_undo WHERE user_id=? AND sess=? AND kind=? AND ref_id=? "
                      "ORDER BY seq", (uid, tok, kind, ref)).fetchall()
    done = [s for s in steps if s["state"] == "done"]
    undone = [s for s in steps if s["state"] == "undone"]
    fix = lambda c: None  # noqa: E731
    if kind == "doc":
        from .docs import recalc
        fix = lambda c: recalc(c, oid, ref)  # noqa: E731 -- the sums and the parts' title page lines, as after a normal change
    if op in ("undo", "all"):
        if not done:
            raise Denied(409, tr(OUN_NOTHING))
        if op == "all" and undone:  # steps undone one by one before: their way forward ends here
            c.execute(f"DELETE FROM office_undo WHERE id IN ({','.join('?' * len(undone))})", [s["id"] for s in undone])
        for st in reversed(done if op == "all" else done[-1:]):
            _undo_one(c, sc, c.execute("SELECT * FROM office_undo WHERE id=?", (st["id"],)).fetchone(), fix)
    else:
        if not undone:
            raise Denied(409, tr(OUN_NOTHING))
        for st in undone if op == "redoall" else undone[:1]:
            _redo_one(c, sc, c.execute("SELECT * FROM office_undo WHERE id=?", (st["id"],)).fetchone(), fix)
    if oid is not None:
        from .ledger import ofx_log
        if kind == "doc":
            ofx_log(c, oid, "update", doc_id=ref, detail={"undo": op})
        else:
            ofx_log(c, oid, "update", target=kind, detail={"id": ref, "undo": op})
    bump(c)
    c.commit()
    out = after(c)
    left = c.execute("SELECT state, COUNT(*) FROM office_undo WHERE user_id=? AND sess=? AND kind=? AND ref_id=? GROUP BY state",
                     (uid, tok, kind, ref)).fetchall()
    out["undo_steps"] = {r[0]: r[1] for r in left}
    return jsonify(out)
