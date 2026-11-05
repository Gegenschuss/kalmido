"""2.568.0 B (#4673): an agent (e.g. the Kalmido AI, a server agent) prepares an invoice DRAFT without a quotation.

POST /api/v1/office/invoices (MCP create_invoice_draft), scope office, the same switches as the quotation drafts
(office/agentdocs.py _v1ctx: the agent's office switch or its office groups, the area's privacy switch, the person it acts
for works in the office with the right "Quotations & invoices"). Two ways, both through the person's own functions -- no
second way of computing anything:
 - from_time: the billable, still open time entries of ONE project (list_id, optionally one task: task_id) of the client in
   the period from .. to -> invoices.inv_from_time, the same as a person's "Invoice from time" (one position per project
   with the hours, the client's hourly rate, the entries bound to the draft so they are never billed twice). Needs the
   area "Times to bill" (view) for the person and, when the agent has office groups, for the agent too. The agent must
   see the project itself (and within its list restriction).
 - free: positions like a quotation draft (agentdocs.ofa_items: a service gives title, unit and catalogue / framework
   contract price; free positions, other prices and discounts are marked for the person) on an empty invoice draft
   (docs.doc_create kind invoice, the head from the office settings and the client).
Kalmido computes sums, VAT and the service period's rates (docs.recalc), the number is never set here (it comes when a
person finalises, ledger.ofx_finalize) and the answer lists what finalising would still miss (invoices.inv_missing, the
check of a person's finalising). Finalising, the number, sending and cancelling have no agent route at all; the person's
routes (/api/office/...) take no token.
"""
from flask import g, jsonify

from ..core.config import app
from ..core.db import bump, db, iso, now_utc
from ..core.i18n import N_, tr
from ..core.access import Denied
from ..core.errors import BadInput
from ..api.common import v1_err, v1_view
from .agentdocs import _doc_v1, _flag_notify, _iid, _json, _list_ok, _log_doc, _notify, _v1_ref, _v1ctx, ofa_agent_on, ofa_items
from .calc import calc_tax_day
from .docs import _date, _put_items, _text, doc_create, doc_items, doc_row, pt_text, recalc
from .invoices import inv_from_time, inv_missing, ofi_ref_keep
from .ledger import ofx_log
from .model import TEXT_MAX, office_settings
from .packs import office_pack_for
from .rights import NO_RIGHT, office_can, ofr_groups_of

OFV_KEYS = ("client_id", "title", "intro", "items", "list_id", "task_id", "from_time", "from", "to", "notify", "client_ref")
OFV_NO_TIME = N_("No billable, still open time of this project in this period")


def ofv_period(b, need):
    """(from, to) as ISO dates; both or none (need: both)."""
    f, t = _date(b.get("from"), "from"), _date(b.get("to"), "to")
    if (need and not (f and t)) or bool(f) != bool(t) or (f and t and t < f):
        raise BadInput(tr("Invalid value: {0}", "from/to"))
    return f, t


def ofv_task(c, lid, tid):
    """Task tid must lie in project lid (not deleted) -> its id; 404 otherwise."""
    tid = _iid(tid, "task_id")
    if tid is None:
        return None
    if not lid:
        raise BadInput(tr("task_id needs list_id"))
    r = c.execute("SELECT list_id, deleted_at FROM tasks WHERE id=?", (tid,)).fetchone()
    if not r or r["list_id"] != lid or r["deleted_at"]:
        raise Denied(404)
    return tid


def ofv_client(c, lid, cid):
    """Review 2.568.0 (N2): project lid of another client than cid -> 400 with that reason (not 409 no_time: the time is
    there, only under the other client). A project without a client stays 409 no_time (nothing of it can be billed)."""
    try:
        cid = int(cid)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", "client_id"))
    r = c.execute("SELECT client_id FROM lists WHERE id=?", (lid,)).fetchone()
    if r and r[0] and r[0] != cid:
        raise BadInput(tr("The project belongs to another client"))


def ofv_missing(c, oid, did):
    """What finalising would still miss (the same check as a person's finalising, invoices.inv_missing), translated."""
    r = doc_row(c, oid, did)
    s = office_settings(c, oid)
    pack = office_pack_for(s, calc_tax_day(dict(r))) or {}
    return [tr(*m) for m in inv_missing(c, oid, r, s, pack, doc_items(c, did, oid))]


@app.post("/api/v1/office/invoices")
@v1_view
def v1_office_invoice_draft_post():
    """{client_id, title?, intro?, list_id?, task_id?, from_time?, from?, to?, items?, notify?, client_ref?, requested_by?}
    -> 201 {doc, missing, time?, chat_message_id?}. A draft only (no number, never finalised or sent)."""
    b = _json(OFV_KEYS)
    c = db()
    notify = _flag_notify(b)
    ft = b.get("from_time", False)
    if ft not in (True, False):
        raise BadInput(tr("Invalid value: {0}", "from_time"))
    aid, oid, uid = _v1ctx(c, b.get("requested_by"), write=True, target="invoice")
    ref, hit = _v1_ref(c, aid, oid, uid, b)  # sent again with the same client_ref = the draft made the first time
    if hit:
        return hit
    if b.get("client_id") in (None, "", 0):
        raise BadInput(tr("client_id is needed"))
    lid = _list_ok(c, oid, uid, b.get("list_id"), aid)  # the person and the agent itself see the project
    tid = ofv_task(c, lid, b.get("task_id"))
    if tid and not ft:  # review 2.568.0 (N1): a free draft never belongs to a task -- say so instead of dropping it
        raise BadInput(tr("task_id needs from_time"))
    stat = None
    if ft:
        if not lid:
            raise BadInput(tr("from_time needs list_id (the project whose time is billed)"))
        if b.get("items") not in (None, []):
            raise BadInput(tr("from_time takes the positions from the time: leave out items"))
        if not office_can(c, uid, oid, "time", "view"):  # like the person's route (inv_from_time_post)
            raise Denied(403, tr(NO_RIGHT))
        if ofr_groups_of(c, oid, aid):  # an agent with office groups needs "Times to bill" too
            from ..agents.core import agent_row
            if not ofa_agent_on(c, agent_row(c, aid), oid, "time", "view"):
                raise Denied(403, tr(NO_RIGHT))
        f, t = ofv_period(b, True)
        ofv_client(c, lid, b["client_id"])
        did, n = inv_from_time(c, oid, uid, {"client_id": b["client_id"], "from": f, "to": t, "project_id": lid, "task_id": tid})
        stat = g.get("tbill_stat")
        if not n:
            c.rollback()
            return v1_err(409, tr(OFV_NO_TIME), name="no_time", time=stat)
        head = {}
        if b.get("title") not in (None, ""):
            head["project_title"] = pt_text(b["title"], "title")
        if b.get("intro") not in (None, ""):
            head["intro"] = _text(b["intro"], "intro", TEXT_MAX)
        if head:
            head["updated_at"] = iso(now_utc())
            c.execute(f"UPDATE office_docs SET {','.join(k + '=?' for k in head)} WHERE id=? AND org_id=? AND status='draft'", [*head.values(), did, oid])
    else:
        f, t = ofv_period(b, False)
        h = {"kind": "invoice", "client_id": b["client_id"]}
        if b.get("title") not in (None, ""):
            h["project_title"] = pt_text(b["title"], "title")
        if b.get("intro") not in (None, ""):
            h["intro"] = _text(b["intro"], "intro", TEXT_MAX)
        if f:
            h.update(service_from=f, service_to=t)
        did = doc_create(c, oid, uid, h, False, number=False)
        r = doc_row(c, oid, did)
        items, flags = ofa_items(c, oid, r, b.get("items"))
        if items:
            _put_items(c, oid, r, items, False, flags)
        n = len(items)
    c.execute("UPDATE office_docs SET agent_id=?, list_id=COALESCE(list_id, ?) WHERE id=? AND org_id=?", (aid, lid, did, oid))
    ofi_ref_keep(c, did, ref)
    recalc(c, oid, did)
    ofx_log(c, oid, "create", doc_id=did, detail={"kind": "invoice", "from": "time" if ft else "agent", "positions": n})
    out = {"doc": _doc_v1(c, oid, doc_row(c, oid, did)), "missing": ofv_missing(c, oid, did)}
    if stat is not None:
        out["time"] = stat
    if notify:
        out["chat_message_id"] = _notify(c, aid, uid, did, oid, N_("Invoice draft"))
    _log_doc(c, did)
    bump(c)
    c.commit()
    return jsonify(out), 201


def ofv_spec(paths, schemas, op, ok, errs, ref, pid, q):
    T = "Office"
    o = {"type": "object"}
    paths["/office/invoices"] = {"post": op(
        "An invoice draft without a quotation: from the time of a project or with free positions (2.568.0)", T,
        ok(o, "Created", "201") | errs("400", "403", "404", "409"),
        body={"type": "object", "required": ["client_id"], "properties": {
            "client_id": {"type": "integer"}, "title": {"type": "string"}, "intro": {"type": "string"},
            "list_id": {"type": "integer", "description": "The project (needed with from_time)"},
            "task_id": {"type": "integer", "description": "Only the time of this task of the project (from_time)"},
            "from_time": {"type": "boolean", "description": "The positions from the billable, still open time of the project in from .. to"},
            "from": {"type": "string", "format": "date", "description": "The service period's start"},
            "to": {"type": "string", "format": "date", "description": "The service period's end"},
            "items": {"type": "array", "items": {"type": "object"}, "description": "Positions like create_offer_draft (not with from_time)"},
            "notify": {"type": "boolean"}, "requested_by": {"type": "integer"},
            "client_ref": {"type": "string", "maxLength": 64, "description": "Your own id of this request; sent again = 200 the draft made the first time"}}},
        scope="office",
        desc="Kalmido computes sums, VAT and the hours; the number comes only when a person finalises. missing = what finalising "
             "still needs (recipient address, VAT ID ...). 409 no_time: no open, billable time in the period.")}
