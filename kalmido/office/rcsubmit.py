"""2.356.0 D (#3129): members hand in receipts to the bookkeeping ("Submit receipt").

POST /api/office/receipts/submit (multipart "files": a photo or a file, at most RSB_FILES): a person of an organisation's
office files a receipt into the office's documents space as their own document (members see only their own documents
there, the admins all: docs/store.py root_folder) and marks it as a receipt handed in (rc_receipts.submitted_by /
submitted_at). GET /api/office/receipts/mine: the person's own receipts handed in with their status (submitted | processed
| paid | removed) -- never anybody else's. GET /api/office/receipts/submitted: the receipts handed in and not processed yet,
for the people who see the bookkeeping (Office > Receipts, "handed in by ..."); they work on them as on every receipt.
Read-only people, guests and accounting (it uploads in the bookkeeping itself) get 403 on submit (office_allowed), office
groups need "own" or more in the area receipts (rights.py OWN_ROUTES), agents and kids 403 (office_gate). A personal office:
its owner is its own admin -- the same upload works there and is a normal receipt."""
from flask import jsonify, request

from ..core.access import Denied
from ..core.config import app
from ..core.db import local_now
from ..core.i18n import N_, tr
from ..core.errors import BadInput
from ..docs.ingest import docs_ingest, docs_kick
from ..files.store import fs_log_add, fs_role
from ..files.upsafe import h6d_read
from .books import bk_ws
from .periodlock import pl_sees_books
from .model import OFFICE_ADMIN_ONLY, office_ctx, office_role, pb_owner
from .rights import LV, ofr_level, ofr_rights

RSB_FILES = 20  # files per submit
RSB_LIST = 200  # rows of the lists
RSB_NO = N_("Your role in this office cannot hand in receipts")


rsb_sees_books = pl_sees_books  # 2.356.0 (#3129): one rule with the receipt guard (periodlock.py)


def rsb_may(c, uid, oid):
    """May uid hand in a receipt in office area oid? The personal office's owner, an org admin / member (not read-only,
    guest, accounting), a person ruled by office groups with at least "own" in the area receipts (not "view")."""
    if pb_owner(c, oid) is not None:
        return pb_owner(c, oid) == uid
    r = ofr_rights(c, uid, oid)
    if r is None:
        return office_role(c, uid, oid) in ("admin", "member")
    lv = ofr_level(c, uid, oid, "receipts")
    return lv == "own" or LV[lv] >= LV["edit"]


def rsb_flag(c, uid, oid):
    """GET /api/office/settings "submit": show "Submit receipt" (may hand in, does not see the bookkeeping)."""
    return rsb_may(c, uid, oid) and not rsb_sees_books(c, uid, oid)


def rsb_who(c, uid):
    """{id, name} of the person who handed a receipt in (None: unknown)."""
    r = c.execute("SELECT id, display_name, username FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    return {"id": r["id"], "name": r["display_name"] or r["username"]} if r else None


def _status(r):
    if r["deleted_at"]:
        return "removed"
    if r["paid_at"]:
        return "paid"
    if r["set_by"] and r["set_by"] != r["submitted_by"]:
        return "processed"  # the bookkeeping changed the receipt (category, VAT rate, project)
    return "submitted"


def _rows(c, ws, where, args):
    return c.execute("SELECT r.node_id, r.paid_at, r.set_by, r.submitted_by, r.submitted_at, n.name, n.deleted_at "
                     "FROM rc_receipts r JOIN fs_nodes n ON n.id=r.node_id WHERE r.ws=? AND r.submitted_by IS NOT NULL AND "
                     + where + " ORDER BY r.submitted_at DESC, r.node_id DESC LIMIT ?", (ws, *args, RSB_LIST)).fetchall()


@app.post("/api/office/receipts/submit")
def rsb_submit():
    from ..receipts.suggest import rc_set
    c, uid, oid = office_ctx()
    if not rsb_may(c, uid, oid):
        raise Denied(403, tr(RSB_NO))
    ws = bk_ws(c, oid)
    org = None if ws[0] == "u" else oid
    files = request.files.getlist("files") or request.files.getlist("file")
    if not files:
        raise BadInput(tr("No file"))
    from ..admin.hosting import QuotaExceeded
    ids, dups, errors, at = [], [], [], local_now().isoformat(timespec="seconds")
    for f in files[:RSB_FILES]:
        info = {}
        name = f.filename or "receipt.jpg"
        try:
            with c.savepoint():
                nid = docs_ingest(c, uid, org, name, h6d_read(f), f.mimetype, "upload", dedup=True, info=info)
                if info.get("dup"):
                    dups.append({"id": nid, "name": name})
                    continue
                fs_log_add(c, nid, "upload")
                rc_set(c, {"id": nid, "org_id": org}, ws, None, "", uid, keep=True)
                c.execute("UPDATE rc_receipts SET submitted_by=?, submitted_at=? WHERE node_id=?", (uid, at, nid))
                ids.append(nid)
        except QuotaExceeded:
            errors.append(tr("{0}: no space left in your storage", name))
        except ValueError as e:
            errors.append(str(e))
    c.commit()
    docs_kick()
    return jsonify(ids=ids, dups=dups, errors=errors), 201 if ids else (200 if dups else 400)


@app.get("/api/office/receipts/mine")
def rsb_mine():
    """My receipts handed in (newest first) with their status; only my own (submitted_by = me)."""
    c, uid, oid = office_ctx()
    rows = _rows(c, bk_ws(c, oid), "r.submitted_by=?", (uid,))
    return jsonify(rows=[{"node_id": r["node_id"], "name": r["name"] or "", "submitted_at": r["submitted_at"],
                          "status": _status(r)} for r in rows], submit=rsb_may(c, uid, oid))


@app.get("/api/office/receipts/submitted")
def rsb_submitted():
    """The receipts handed in that the bookkeeping has not worked on yet (status submitted), with who handed them in;
    only for the people who see the bookkeeping and only the documents they see."""
    c, uid, oid = office_ctx()
    if not rsb_sees_books(c, uid, oid):
        raise Denied(403, tr(OFFICE_ADMIN_ONLY))
    out = []
    for r in _rows(c, bk_ws(c, oid), "n.deleted_at IS NULL AND r.paid_at IS NULL AND (r.set_by IS NULL OR r.set_by=r.submitted_by)", ()):
        if not fs_role(c, r["node_id"], uid):
            continue
        out.append({"node_id": r["node_id"], "name": r["name"] or "", "submitted_at": r["submitted_at"], "by": rsb_who(c, r["submitted_by"])})
    return jsonify(rows=out)
