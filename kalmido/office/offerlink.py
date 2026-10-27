"""2.356.0 C (#3003): the link between a quotation and the invoices made from it (office_docs.source_doc_id).

- doc_public: an invoice names its quotation (source_offer), a quotation lists its invoices (offer_invoices) with state.
- "Create invoice" asks first when the quotation already has a full invoice that is not cancelled: 409 code invoice_exists
  with the invoices; force=true makes another one (a person's route and the agents' alike). Progress / final invoices are
  several per quotation on purpose and are not asked about.
"""
import json

from flask import jsonify

from ..core.config import app
from ..core.i18n import tr
from .calc import fmt_money
from .docs import STATUS_TXT
from .invoices import inv_paid_map, inv_state
from .ledger import ofx_locked


class OilExists(Exception):
    """409 invoice_exists: the quotation already has a full invoice that is not cancelled."""
    def __init__(self, invoices):
        super().__init__("invoice_exists")
        self.invoices = invoices

    def text(self):
        return tr("This quotation already has an invoice ({0}). Create another one?", ", ".join(x["number"] or tr("Draft") for x in self.invoices))


@app.errorhandler(OilExists)
def oil_exists_answer(e):
    return jsonify(error=e.text(), code="invoice_exists", invoices=e.invoices), 409


def oil_source_offer(c, oid, r):
    """{id, number, status, list_id} of the quotation invoice r was made from, else None."""
    sid = r["source_doc_id"] if "source_doc_id" in r.keys() else None
    if r["kind"] != "invoice" or not sid:
        return None
    x = c.execute("SELECT id, number, status, list_id FROM office_docs WHERE id=? AND org_id=? AND kind='offer'", (sid, oid)).fetchone()
    return {"id": x["id"], "number": x["number"] or "", "status": x["status"], "list_id": x["list_id"]} if x else None


def oil_offer_invoices(c, oid, offer_id):
    """The invoices made from quotation offer_id, oldest first: {id, number, state, status_text, gross_text, inv_type, locked, list_id}."""
    rows = c.execute("SELECT * FROM office_docs WHERE org_id=? AND kind='invoice' AND source_doc_id=? ORDER BY id", (oid, offer_id)).fetchall()
    pm = inv_paid_map(c, oid, [x["id"] for x in rows]) if rows else {}
    out = []
    for x in rows:
        st = inv_state(x, pm)
        gross = (_totals(x).get("gross") or 0)
        out.append({"id": x["id"], "number": x["number"] or "", "state": st, "status_text": tr(STATUS_TXT.get(st, st)),
                    "gross_text": fmt_money(gross, x["lang"], x["currency"]), "inv_type": x["inv_type"] or "",
                    "locked": ofx_locked(x), "list_id": x["list_id"]})
    return out


def _totals(x):
    try:
        return json.loads(x["totals"] or "{}") or {}
    except (TypeError, ValueError):
        return {}


def oil_doc_extra(c, oid, r, d):
    """doc_public (with items): source_offer on an invoice, offer_invoices on a quotation."""
    if r["kind"] == "invoice":
        d["source_offer"] = oil_source_offer(c, oid, r)
    elif r["kind"] == "offer":
        d["offer_invoices"] = oil_offer_invoices(c, oid, r["id"])


def oil_agent_filter(d, sees):
    """_doc_v1: an agent with a project restriction sees only the linked documents inside it (sees(row) = agentdocs.ofa_doc_in_lists);
    list_id stays internal."""
    so = d.get("source_offer")
    if so:
        d["source_offer"] = {k: v for k, v in so.items() if k != "list_id"} if sees({"list_id": so["list_id"], "kind": "offer"}) else None
    if d.get("offer_invoices") is not None:
        d["offer_invoices"] = [{k: v for k, v in x.items() if k != "list_id"} for x in d["offer_invoices"] if sees({"list_id": x["list_id"], "kind": "invoice"})]


def oil_list_marks(c, oid, rows):
    """2.356.0 C (#3005): the quotation list marks the rows with a full invoice that is not cancelled (invoiced; "From a quotation…")."""
    used = {x[0] for x in c.execute("SELECT DISTINCT source_doc_id FROM office_docs WHERE org_id=? AND kind='invoice' AND source_doc_id IS NOT NULL "
                                    "AND status<>'cancelled' AND COALESCE(inv_type, '')=''", (oid,)).fetchall()}
    for b in rows:
        b["invoiced"] = b["id"] in used


def oil_need_no_invoice(c, oid, r, b):
    """Before a full invoice from quotation r: 409 invoice_exists when one that is not cancelled exists, unless b.force."""
    if (b.get("inv_type") or "") or b.get("force") in (True, 1, "1", "true"):
        return
    have = [x for x in oil_offer_invoices(c, oid, r["id"]) if x["state"] != "cancelled" and not x["inv_type"]]
    if have:
        raise OilExists([{k: v for k, v in x.items() if k != "list_id"} for x in have])
