"""2.644.0 (#3663): agents read and add inquiries and deals of the sales pipeline (office/pipeline.py, office_deals, the
stages inquiry | offer | won | lost) and set a deal's stage -- the rest of #1786 after the leads (office/leads.py, 2.94.0).
Exactly the leads' way: scope office, the switches of office/agentdocs.py (_v1ctx with the target "deals" = the office
group area "pipeline", the area's "Agents may read office data"), acting only for an admin of the office area (a personal
office: its owner), every request one line in the office log. Writes go straight in like the leads' (no proposal): a new
deal through lead_insert (history), a stage through pipeline.pl2_write (lock, expect_updated_at required = 400 without,
409 with the deal now under "current", history + undo step, bump).
Never: a lead (the leads' own routes; converting a lead into an inquiry or a deal back into a lead stays with people),
deleting, a quotation or a project for the deal, another field than the stage (+ lost_reason)."""
from flask import jsonify

from ..core.config import app
from ..core.db import bump, db
from ..core.i18n import N_, tr
from ..core.access import Denied
from ..core.errors import BadInput
from ..api.common import v1_view
from .pipeline import PL2_STAGES, _one, _row, pl2_clean, pl2_list, pl2_write
from .leads import LEAD_ADMIN_ONLY, lead_insert
from .model import office_role
from .rights import ofr_rights

DLA_STAGES = tuple(s for s in PL2_STAGES if s != "lead")  # inquiry, offer, won, lost
DLA_FIELDS = ("id", "title", "stage", "probability", "value", "weighted", "client_id", "client_name", "contact", "company",
              "email", "phone", "expected_date", "next_step", "follow_up", "note", "lost_reason", "source", "offer_id",
              "offer_number", "offer_status", "list_id", "created_at", "updated_at")
DLA_IN = ("title", "stage", "client_id", "contact", "company", "email", "phone", "value", "probability", "expected_date",
          "next_step", "follow_up", "note", "source")
DLA_PATCH = ("stage", "lost_reason")
DLA_PATCH_IN = DLA_PATCH + ("expect_updated_at",)
DLA_NO_LEAD = N_("This is a lead: a person converts it into an enquiry")


def _v1deal(c, rb, write=False):
    """-> (aid, oid, uid) like the leads' _v1lead: the office switches and an admin of the area (else 403)."""
    from .agentdocs import _v1ctx
    aid, oid, uid = _v1ctx(c, rb, write=write, target="deals")
    if office_role(c, uid, oid) != "admin" and ofr_rights(c, uid, oid) is None:
        raise Denied(403, tr(LEAD_ADMIN_ONLY))
    return aid, oid, uid


def dla_public(d):
    out = {k: d.get(k) for k in DLA_FIELDS}
    out["app_url"] = "#office/pipeline"
    return out


def _stage(v):
    if v not in DLA_STAGES:
        raise BadInput(tr("Invalid value: {0}", "stage"))
    return v


@app.get("/api/v1/office/deals")
@v1_view
def v1_deal_list():
    """?stage=inquiry|offer|won|lost|open (open = inquiry + offer; default: all four) -> {data: [deal]} in the pipeline's order."""
    from .agentdocs import _args
    a = _args(("stage",))
    c = db()
    aid, oid, uid = _v1deal(c, a.get("requested_by"))
    st = a.get("stage") or ""
    want = ("inquiry", "offer") if st == "open" else (_stage(st),) if st else DLA_STAGES
    rows = [d for d in pl2_list(c, oid) if d["stage"] in want]
    c.commit()
    return jsonify(data=[dla_public(d) for d in rows])


@app.post("/api/v1/office/deals")
@v1_view
def v1_deal_post():
    """{title, stage? (inquiry default | offer | won | lost), client_id?, contact?, company?, email?, phone?, value?,
    probability?, expected_date?, next_step?, follow_up?, note?, source?} -> 201 the deal."""
    from .agentdocs import _json
    b = _json(DLA_IN)
    c = db()
    aid, oid, uid = _v1deal(c, b.get("requested_by"), write=True)
    x = {k: b[k] for k in DLA_IN if k in b}
    x["stage"] = _stage(x.get("stage") or "inquiry")
    if "source" not in x:
        x["source"] = "agent"
    did = lead_insert(c, oid, aid, pl2_clean(c, oid, x))
    bump(c)
    c.commit()
    return jsonify(dla_public(_one(c, oid, did))), 201


@app.patch("/api/v1/office/deals/<int:did>")
@v1_view
def v1_deal_patch(did):
    """{stage, lost_reason?, expect_updated_at}: the stage of a deal (not of a lead; a lead stays with its own routes).
    The probability follows the stage's preset unless a person set its own (pl2_clean). 400 without expect_updated_at,
    409 with the deal now under current when a person changed it since."""
    from .agentdocs import _json
    b = _json(DLA_PATCH_IN)
    c = db()
    aid, oid, uid = _v1deal(c, b.get("requested_by"), write=True)
    _row(c, oid, did)
    if "stage" not in b:
        raise BadInput(tr("Invalid value: {0}", "stage"))
    _stage(b.get("stage"))

    def clean(c, b, cur):
        if cur["stage"] == "lead":
            raise Denied(409, tr(DLA_NO_LEAD))
        return pl2_clean(c, oid, {k: b[k] for k in DLA_PATCH if k in b}, cur)

    pl2_write(c, oid, did, b, clean, uid=aid, version=True)
    c.commit()
    return jsonify(dla_public(_one(c, oid, did)))


# ---------------------------------------------------------------- OpenAPI (called from api/openapi.py)
def dla_spec(paths, schemas, op, ok, errs, ref, pid, q):
    T = "Office"
    o = {"type": "object"}
    rb = q("requested_by", "The person this is for (an admin of the office; default: the agent's owner)", {"type": "integer"})
    st = {"type": "string", "enum": list(DLA_STAGES)}
    props = {"title": {"type": "string"}, "stage": {**st, "description": "Default: inquiry"}, "client_id": {"type": "integer"},
             "contact": {"type": "string"}, "company": {"type": "string"}, "email": {"type": "string"}, "phone": {"type": "string"},
             "value": {"type": "string", "description": "Net value in the office currency, decimal text"},
             "probability": {"type": "integer", "minimum": 0, "maximum": 100, "description": "Default: the stage's preset"},
             "expected_date": {"type": "string", "format": "date"}, "next_step": {"type": "string"},
             "follow_up": {"type": "string", "format": "date"}, "note": {"type": "string"},
             "source": {"type": "string", "description": "Default: agent"}, "requested_by": {"type": "integer"}}
    schemas["OfficeDealInput"] = {"type": "object", "properties": props, "required": ["title"]}
    rules = ("The switches of the office (the agent's \"May draft office documents\" and the area's \"Agents may read office "
             "data\") and a person who is an admin of the office. No leads (their own routes), never delete, convert or another field.")
    paths["/office/deals"] = {
        "get": op("The inquiries and deals of the sales pipeline (2.644.0)", T, ok(o) | errs("400", "403", "404"),
                  [q("stage", "inquiry, offer, won, lost or open (= inquiry + offer); default: all", {"type": "string"}), rb],
                  scope="office", desc=rules),
        "post": op("Add an inquiry or a deal (2.644.0)", T, ok(o, "Created", "201") | errs("400", "403", "404"), body=ref("OfficeDealInput"),
                   scope="office", desc=rules)}
    paths["/office/deals/{id}"] = {"patch": op("Set the stage of a deal (2.644.0)", T, ok(o) | errs("400", "403", "404", "409"),
                                               [pid("id", "Deal id")], body={"type": "object", "properties": {
                                                   "stage": st, "lost_reason": {"type": "string"}, "requested_by": {"type": "integer"},
                                                   "expect_updated_at": {"type": "string", "description": "updated_at of the deal as you read it"}},
                                                   "required": ["stage", "expect_updated_at"]}, scope="office",
                                               desc="Not for a lead (409). Only with expect_updated_at (400 without; 409 with the current "
                                                    "deal under current when a person changed it since).")}
