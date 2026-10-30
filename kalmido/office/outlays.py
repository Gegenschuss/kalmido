"""2.121.0 C (#2094): bill receipts (documents with a row in rc_receipts, the bookkeeping's receipt sheet) on to a client as
outlays: positions "external costs" of a quotation / invoice in draft, like the travel receipts (office/travel.py rk_bill_post).
The amount is billed net when the receipt has a VAT rate and the office is no small business (the input tax is the office's
own), else gross. rc_receipts.billed_doc_id / billed_at mark a receipt so nothing is billed twice (409); POST .../unbill is the
undo (a finalised document keeps its positions, the receipt stays billed).

Every route: office_gate + office_org with the admin of the office area (like travel and the bookkeeping); only receipts of
this office's documents space the person sees. Never reached by agents."""
import re

from flask import jsonify, request

from ..core.config import app
from ..core.pg import insert_id, write_lock
from ..core.orgcrypt import oc_item_store
from ..core.i18n import tr
from ..core.db import body, bump, db, iso, now_utc
from ..core.access import Denied
from ..core.errors import BadInput
from .calc import dec, money
from .books import bk_receipts, bk_ws
from .ledger import ofx_items_brief, ofx_log
from .model import office_gate, office_org, office_settings
from .travel import MAX_ITEMS, _amount, _bill_doc, _fmt_day

AU_ALL = ("0001-01-01", "9999-12-31")


from .rights import ofr_need_area  # noqa: E402  2.187.0 (#2476)
from .model import office_ctx_admin as _ctx  # noqa: E402  2.149.0 G (#2517): was an own copy


def au_ids(v, name):
    if not isinstance(v, list) or not v or len(v) > MAX_ITEMS or not all(isinstance(x, int) and not isinstance(x, bool) for x in v):
        raise BadInput(tr("Invalid value: {0}", name))
    return v


def au_billed(c, oid, ids):
    """{node_id: {doc_id, number, kind, billed_at}} of the receipts among ids that sit on a document that still exists."""
    ids = [int(x) for x in ids]
    if not ids:
        return {}
    # 2.121.0 review N4: a receipt moved here from another office after its billing stays billed (never twice), without the
    # other office's document details
    # 2.362.0 (#3131): billed_at without a document = billed before an organisation import whose invoice did not come along
    # (admin/oi_store.py _receipt): billed, invoice missing; a document deleted later still frees its receipts (billed_doc_id kept)
    rows = c.execute(f"SELECT r.node_id, r.billed_at, d.id AS doc_id, d.number, d.kind, d.org_id FROM rc_receipts r LEFT JOIN office_docs d "
                     f"ON d.id=r.billed_doc_id WHERE r.ws=? AND r.node_id IN ({','.join('?' * len(ids))}) "
                     f"AND (d.id IS NOT NULL OR (r.billed_doc_id IS NULL AND r.billed_at IS NOT NULL AND r.billed_at != ''))",
                     [bk_ws(c, oid)] + ids).fetchall()
    return {r["node_id"]: ({"doc_id": r["doc_id"], "number": r["number"], "kind": r["kind"], "billed_at": r["billed_at"]} if r["org_id"] == oid
                           else {"doc_id": None, "number": None, "kind": None, "billed_at": r["billed_at"],
                                 **({"missing": 1} if r["doc_id"] is None else {})}) for r in rows}


def au_title(x, lg):
    name = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", x["title"] or "") or tr("Receipt", lg=lg)
    return ((x["category"] + ": " if x["category"] else "") + name)[:300]


@app.get("/api/office/receipts/billed")
def au_billed_get():
    """?ids=1,2,3 -> {billed: {node_id: {doc_id, number, kind, billed_at}}}: the receipts already billed on a document."""
    c, uid, oid = _ctx()
    ofr_need_area(c, uid, oid, "offers", "view")  # 2.187.0 (#2476, review): it reads / writes quotations and invoices too
    ids = [int(x) for x in re.findall(r"\d{1,12}", request.args.get("ids") or "")][:500]
    return jsonify(billed=au_billed(c, oid, ids))


@app.post("/api/office/receipts/bill")
def au_bill_post():
    """{doc_id, node_ids: [...], markup_pct?, one?} the receipts as external costs on a quotation / invoice in draft: one
    position per receipt (one=1: one position for all), unit flat, purchase = the amount (net with a VAT rate unless the office
    is a small business, else gross; in the office currency), rate = purchase plus markup_pct. Receipts already billed on an
    existing document: 409. Answers {doc_id, number, positions, items: [node ids]}; POST .../unbill takes it back."""
    from .docs import doc_items, recalc
    c, uid, oid = _ctx()
    ofr_need_area(c, uid, oid, "offers", "edit")  # 2.187.0 (#2476, review): it reads / writes quotations and invoices too
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    r = _bill_doc(c, oid, b.get("doc_id"))
    ids = au_ids(b.get("node_ids"), "node_ids")
    mk = _amount(b.get("markup_pct"), "markup_pct", 0, 1000, allow_none=True) or dec(0)
    write_lock(c, f"office_receipts_bill_{int(oid)}")  # two parallel billings of one receipt: the second sees it billed (409)
    have = {x["node_id"]: x for x in bk_receipts(c, oid, *AU_ALL, uid=uid)}
    if not set(ids) <= set(have):
        raise Denied(404)
    if au_billed(c, oid, ids):
        raise Denied(409, tr("A receipt has already been billed"))
    small = bool(office_settings(c, oid).get("small_business"))
    lg = r["lang"] or "de"
    its = [have[i] for i in dict.fromkeys(ids)]
    its.sort(key=lambda x: (x["date"] or "", x["node_id"]))
    cost = lambda x: x["net"] if (x["vat_pct"] is not None and not small) else x["amount"]  # noqa: E731
    if b.get("one"):
        pos = [(tr("Outlays", lg=lg), ", ".join(au_title(x, lg) for x in its)[:300], sum((cost(x) for x in its), dec(0)))]
    else:
        pos = [(au_title(x, lg), _fmt_day(x["date"], lg), cost(x)) for x in its]
    before = ofx_items_brief(doc_items(c, r["id"], oid))
    mx = c.execute("SELECT COALESCE(MAX(sort), 0) FROM office_doc_items WHERE doc_id=? AND org_id=? AND part_id IS NULL", (r["id"], oid)).fetchone()[0]
    pids = []
    for i, (title, detail, amt) in enumerate(pos):
        row = {"doc_id": r["id"], "org_id": oid, "sort": (mx or 0) + 1 + i, "kind": "service", "service_id": None, "title": title, "detail": detail,
               "qty": 1.0, "unit": "flat", "rate": float(money(amt * (1 + mk / 100))), "tax": "standard", "raw_fee": 0, "producing": 0,
               "intext": "extern", "cost": float(money(amt)), "discountable": 0}
        row = oc_item_store(c, oid, row)
        pids.append(insert_id(c, f"INSERT INTO office_doc_items({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values())))
    ts = iso(now_utc())
    nids = [x["node_id"] for x in its]
    ws = bk_ws(c, oid)
    for i, nid in enumerate(nids):  # 2.269.0 A (#3012): + the position it became (one=1: the same for all)
        c.execute("UPDATE rc_receipts SET billed_doc_id=?, billed_item_id=?, billed_at=? WHERE ws=? AND node_id=?",
                  (r["id"], pids[0 if b.get("one") else i], ts, ws, nid))
    ofx_log(c, oid, "items", doc_id=r["id"], detail={"before": before, "after": ofx_items_brief(doc_items(c, r["id"], oid))})
    recalc(c, oid, r["id"])
    bump(c)
    c.commit()
    return jsonify(doc_id=r["id"], number=r["number"], positions=pids, items=nids)


@app.post("/api/office/receipts/unbill")
def au_unbill_post():
    """{node_ids, positions?} the undo of a billing: the receipts are free again; positions (ids from the billing's answer)
    are removed from the document while it is a draft. Receipts on a finalised document stay billed."""
    from .docs import doc_items, ofd_free_receipts, recalc
    c, uid, oid = _ctx()
    ofr_need_area(c, uid, oid, "offers", "edit")  # 2.187.0 (#2476, review): it reads / writes quotations and invoices too
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    ids = au_ids(b.get("node_ids"), "node_ids")
    pids = b.get("positions") or []
    if not isinstance(pids, list) or not all(isinstance(x, int) and not isinstance(x, bool) for x in pids):
        raise BadInput(tr("Invalid value: {0}", "positions"))
    ws = bk_ws(c, oid)
    q = ",".join("?" * len(ids))
    docs = {x[0] for x in c.execute(f"SELECT billed_doc_id FROM rc_receipts WHERE ws=? AND node_id IN ({q}) AND billed_doc_id IS NOT NULL", [ws] + ids)}
    for did in sorted(docs):
        write_lock(c, f"office_doc_{int(did)}")  # 2.269.0 A (#3012): never in between a save of the document
    pos = {x[0] for x in c.execute(f"SELECT billed_item_id FROM rc_receipts WHERE ws=? AND node_id IN ({q}) AND billed_item_id IS NOT NULL", [ws] + ids)}
    if pos:  # 2.269.0 A (#3012): the kept positions of these receipts, unless another receipt is still billed as the same one
        busy = {x[0] for x in c.execute(f"SELECT billed_item_id FROM rc_receipts WHERE ws=? AND billed_item_id IN ({','.join('?' * len(pos))}) AND node_id NOT IN ({q})",
                                        [ws, *pos, *ids])}
        pids = pids + sorted(pos - busy)
    c.execute(f"UPDATE rc_receipts SET billed_doc_id=NULL, billed_at=NULL, billed_item_id=NULL WHERE ws=? AND node_id IN ({q}) AND NOT EXISTS "
              "(SELECT 1 FROM office_docs d WHERE d.id=rc_receipts.billed_doc_id AND d.trial=0 AND ((d.locked_at IS NOT NULL AND d.locked_at != '') OR d.status='sent'))",
              [ws] + ids)  # 2.121.0 review M1: a sent document counts as final like in bill (ofx_need_editable); 2.144.10 (#2576, review): a trial one frees them
    removed = 0
    for did in docs:
        r = c.execute("SELECT * FROM office_docs WHERE id=? AND org_id=?", (did, oid)).fetchone()
        if not r or r["locked_at"] or r["status"] == "sent" or not pids:  # 2.121.0 review M1
            continue
        before = ofx_items_brief(doc_items(c, did, oid))
        n = c.execute(f"DELETE FROM office_doc_items WHERE doc_id=? AND org_id=? AND part_id IS NULL AND intext='extern' AND id IN ({','.join('?' * len(pids))})",
                      [did, oid] + pids).rowcount
        if n:
            removed += n
            ofx_log(c, oid, "items", doc_id=did, detail={"before": before, "after": ofx_items_brief(doc_items(c, did, oid))})
            ofd_free_receipts(c, oid, did)  # 2.269.0 A (#3012): other receipts of a removed position are open again
            recalc(c, oid, did)
    bump(c)
    c.commit()
    return jsonify(ok=True, removed=removed)
