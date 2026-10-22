"""2.168.0 A (#2665): quotations, invoices and credit notes bound to a project (office_docs.list_id).

POST /api/office/docs/<did>/project picks a project ({list_id}), takes it off ({list_id: null}) or makes a new one
({create: {name}}: like the pipeline's "Create project", in the office area's workspace, only its maker a member, the
document's client). It is an internal mark only: also on a finalised / sent document, which stays as it is (no new totals,
no rendering). A quotation of a deal without a project gives a new project to the deal too.
GET /api/lists/<lid>/office-docs: the project's documents for its overview -- only for people with office rights in the
project's own area; everybody else gets {office: false} and no hint that there are any."""
from flask import g, jsonify

from ..accounts.orgroles import office_allowed
from ..core.config import app
from ..core.db import body, bump, db, err, iso, now_utc
from ..core.i18n import tr
from ..core.access import need_list
from ..core.errors import BadInput
from ..core.pg import write_lock
from ..lists.lists import LIST_NAME_MAX
from ..lists.templates import ptype_create
from ..team.clients import list_client_set
from .agentdocs import _list_ok
from .docs import doc_brief, doc_public, doc_row
from .invoices import inv_paid_map
from .ledger import ofx_log
from .model import office_ctx, office_on, office_role, pb_owner, pb_personal
from .pipeline import _client_ok

DPJ_KINDS = ("offer", "invoice", "credit")
DPJ_MAX = 100  # documents in a project's overview


def dpj_name(v):
    """The new project's name: trimmed, required, as long as a list name may be."""
    if not isinstance(v, str) or not v.strip():
        raise BadInput(tr("Please enter a name"))
    return " ".join(v.split())[:LIST_NAME_MAX]


def dpj_create(c, uid, oid, r, name):
    """A new project of the type "agency" in the office area's workspace (a personal office: private), with the
    document's client -> (list id, modules switched on)."""
    lid, on = ptype_create(c, uid, "agency", name, org_id=None if pb_owner(c, oid) is not None else oid)
    if r["client_id"] and _client_ok(c, oid, r["client_id"]):
        list_client_set(c, lid, r["client_id"])
    return lid, on


@app.post("/api/office/docs/<int:did>/project")
def dpj_set(did):
    """{list_id: id|null} or {create: {name}} -> the document (+ list_id, modules_on). Also on finalised documents."""
    c, uid, oid = office_ctx()
    b = body()
    if not isinstance(b, dict):
        return err(tr("Invalid data"))
    write_lock(c, f"office_doc_{int(did)}")  # like odoc_update: never in between finalising / sending
    r = doc_row(c, oid, did)
    if r["kind"] not in DPJ_KINDS:
        raise BadInput(tr("Only quotations, invoices and credit notes belong to a project"))
    on, made = [], False
    if isinstance(b.get("create"), dict):
        lid, on = dpj_create(c, uid, oid, r, dpj_name(b["create"].get("name")))
        made = True
    elif "list_id" in b:
        lid = _list_ok(c, oid, uid, b["list_id"])  # 404 unseen / 400 another workspace / None = no project
    else:
        raise BadInput(tr("Invalid value: {0}", "list_id"))
    before = r["list_id"]
    if lid != before:
        c.execute("UPDATE office_docs SET list_id=?, updated_at=? WHERE id=? AND org_id=?", (lid, iso(now_utc()), did, oid))
        ofx_log(c, oid, "project", doc_id=did, detail={"before": {"list_id": before}, "after": {"list_id": lid}, "created": made})
    if made and r["kind"] == "offer":  # the deal of this quotation gets the new project unless it has one
        c.execute("UPDATE office_deals SET list_id=?, updated_at=? WHERE org_id=? AND offer_id=? AND list_id IS NULL AND deleted_at IS NULL",
                  (lid, iso(now_utc()), oid, did))
    bump(c)
    c.commit()
    out = doc_public(c, oid, doc_row(c, oid, did), office_role(c, uid, oid) == "admin")
    out.update(list_id=lid, modules_on=on)
    return jsonify(out), 201 if made else 200


def dpj_area(c, uid, lid):
    """The office area of project lid in which uid has office rights (reading), else None: an organisation's project ->
    that organisation (a role there, no refusal by office_allowed); a private project -> the owner's personal office."""
    u = g.user
    if (u["kind"] if "kind" in u.keys() else "user") == "agent" or ("kid" in u.keys() and u["kid"]) or not office_on(c, uid):
        return None
    lr = c.execute("SELECT org_id, owner_id FROM lists WHERE id=?", (lid,)).fetchone()
    if lr is None:
        return None
    if lr["org_id"] is None:
        return pb_personal(c, uid, create=False) if lr["owner_id"] == uid else None
    oid = lr["org_id"]
    if not office_role(c, uid, oid) or office_allowed(c, uid, oid, write=False):
        return None
    return oid


@app.get("/api/lists/<int:lid>/office-docs")
def dpj_list_docs(lid):
    """{office, docs: [{id, kind, number, status, state, status_text, date, gross_text, project_title, trial}]} newest
    first; office false (and no documents) without office rights in the project's area."""
    c = db()
    need_list(c, lid, write=False)
    oid = dpj_area(c, g.user["id"], lid)
    if oid is None:
        return jsonify(office=False, docs=[])
    rows = c.execute("SELECT * FROM office_docs WHERE org_id=? AND list_id=? AND kind IN ('offer','invoice','credit') "
                     "ORDER BY date DESC, id DESC LIMIT ?", (oid, lid, DPJ_MAX)).fetchall()
    pm = inv_paid_map(c, oid, [r["id"] for r in rows if r["kind"] != "offer"]) if rows else {}
    keep = ("id", "kind", "number", "status", "state", "status_text", "date", "gross_text", "project_title", "trial")
    return jsonify(office=True, docs=[{k: v for k, v in doc_brief(r, pm).items() if k in keep} for r in rows])
