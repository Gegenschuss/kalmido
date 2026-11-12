"""2.1041.0 (#5812): repricing a quotation (Nachkalkulieren) -- the route. The calculation is office/repcalc.py.

POST /api/office/docs/<id>/reprice {mode: pct|net|gross|margin, value, round: cent|euro|five, rest, item_ids?, part_id?,
producing, apply, expect_updated_at?}: the unit prices of the chosen positions (all scalable ones of the title page, or of
the part part_id; item_ids = only these) change by one factor; no discount / markup line. The target modes mean the whole
quotation (a quotation with parts: tp_doc_totals with the part's trial prices). apply false = the preview, nothing written;
apply true = written as ONE undo step (office/undo.py oun_pre / oun_post), the office log "reprice" with the percentage.
Only a quotation in draft (409 otherwise), the rights of the positions' save (odoc_items_put); "margin" only for the office's
admins (403; the purchase side is theirs), and only with external costs (400). Unreachable target: reachable false, apply 409.
No agent tool (decision 12.11.2026): office_gate keeps agents out of the office routes."""
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify

from ..core.config import app
from ..core.access import Denied
from ..core.db import body, bump, iso, now_utc
from ..core.errors import BadInput
from ..core.i18n import N_, tr
from ..core.pg import write_lock
from .calc import calc_tax_day, dec, office_calc, _num
from .docs import _calc_doc, _ctx, doc_items, doc_public, doc_row, ofd_need_current, recalc
from .doclang import doc_lg, doc_pack
from .homecur import hc_home
from .ledger import ofx_log, ofx_need_editable
from .model import office_role, office_settings
from .packs import office_pack_for
from .repcalc import ORP_MODES, ORP_ROUND, orp_figures, orp_scalable, orp_solve
from .undo import oun_post, oun_pre

ORP_REASONS = {
    "nothing": N_("None of the chosen positions has a price to change."),
    "negative": N_("The target cannot be reached: the prices would have to go below zero."),
    "too_high": N_("The target cannot be reached: the prices would have to rise more than a thousandfold."),
    "margin_net": N_("Without a net sum there is no surplus to aim at."),
}
ORP_NO_COSTS = N_("The surplus can only be aimed at when the quotation has external costs (purchase prices).")
ORP_DRAFT = N_("Only a quotation in draft can be repriced; make a new version of it first.")


def _fig(t, admin):
    f = orp_figures(t)
    out = {"net": _num(f["net"]), "gross": _num(f["gross"])}
    if admin:
        out.update(costs=_num(f["costs"]), margin=_num(f["margin"]), margin_pct=_num(f["margin_pct"]))
    return out


def orp_clean(b, admin):
    """The request: (mode, value, rnd, rest, item_ids or None, part_id or None, producing, apply)."""
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    mode = b.get("mode") or "pct"
    if mode not in ORP_MODES:
        raise BadInput(tr("Invalid value: {0}", "mode"))
    if mode == "margin" and not admin:
        raise Denied(403)
    rnd = b.get("round") or "cent"
    if rnd not in ORP_ROUND:
        raise BadInput(tr("Invalid value: {0}", "round"))
    v = b.get("value")
    if isinstance(v, bool) or v in (None, ""):
        raise BadInput(tr("Invalid value: {0}", "value"))
    value = dec(v, "NaN")
    if not value.is_finite() or abs(value) > Decimal("1e9") or (mode == "margin" and value >= 100) or (mode in ("net", "gross") and value < 0):
        raise BadInput(tr("Invalid value: {0}", "value"))
    ids = b.get("item_ids")
    if ids is not None:
        if not isinstance(ids, list) or not all(isinstance(x, int) and not isinstance(x, bool) for x in ids):
            raise BadInput(tr("Invalid value: {0}", "item_ids"))
        ids = set(ids)
    pid = b.get("part_id")
    if pid is not None and (not isinstance(pid, int) or isinstance(pid, bool)):
        raise BadInput(tr("Invalid value: {0}", "part_id"))
    return mode, value, rnd, bool(b.get("rest")), ids, pid, b.get("producing") not in (None, False, 0, "0", "false"), bool(b.get("apply"))


def orp_ev(c, oid, r, part_id):
    """-> (positions in scope, ev(items, prod_rate) -> the totals of the whole quotation with those positions and that day rate)."""
    s = office_settings(c, oid)
    home = hc_home(s)
    pack = doc_pack(office_pack_for(s, calc_tax_day(dict(r))), doc_lg(r["lang"]))  # as docs.doc_totals
    from .parts import tp_doc_totals, tp_has_parts, tp_part
    title = doc_items(c, r["id"], oid)
    if part_id is not None:
        p = tp_part(c, oid, r["id"], part_id)
        if p["kind"] != "items":
            raise BadInput(tr("Invalid value: {0}", "part_id"))
        scope = doc_items(c, r["id"], oid, part=p["id"])
    else:
        scope = title
    parts = tp_has_parts(c, oid, r["id"])

    def ev(items, prod_rate):
        rd = {**dict(r), "producing_rate": prod_rate}
        if parts:
            if part_id is not None:
                t = tp_doc_totals(c, oid, rd, title, pack, home=home, part_items={p["id"]: items})
            else:
                t = tp_doc_totals(c, oid, rd, items, pack, home=home)
            if t is not None:
                return t
        return office_calc(_calc_doc(rd, home), items, pack)
    return scope, ev


@app.post("/api/office/docs/<int:did>/reprice")
def orp_reprice(did):
    """See the module. -> {pct, factor, before, after, deviation, reachable, reason?, items: [{id, title, before, after}],
    producing_rate: {before, after}?} (+ doc: the document after apply)."""
    c, uid, oid = _ctx()
    admin = office_role(c, uid, oid) == "admin"
    b = body()
    mode, value, rnd, rest, ids, pid, prod, apply_ = orp_clean(b, admin)
    if apply_:
        write_lock(c, f"office_doc_{int(did)}")  # like odoc_items_put: never in between finalising / sending
    r = doc_row(c, oid, did)
    if r["kind"] != "offer":
        raise Denied(409, tr(ORP_DRAFT))
    ofx_need_editable(r)
    if r["status"] != "draft":
        raise Denied(409, tr(ORP_DRAFT))
    scope, ev = orp_ev(c, oid, r, pid)
    if mode == "margin" and not dec(ev(scope, dec(r["producing_rate"], "600")).get("costs")):
        raise BadInput(tr(ORP_NO_COSTS))
    sel = {i for i, it in enumerate(scope) if orp_scalable(it) and (ids is None or it["id"] in ids)}
    prod_on = dict(r).get("producing_on")
    prod = prod and (prod_on is None or bool(prod_on))
    old_rate = dec(r["producing_rate"], "600")
    out = orp_solve(ev, scope, sel, old_rate, mode, value, rnd, rest, prod)
    ans = {"mode": mode, "reachable": out["reachable"], "factor": _num(out["factor"]),
           "pct": _num(((out["factor"] - 1) * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
           "before": _fig(out["before"], admin), "after": _fig(out["after"], admin),
           "deviation": None if out["deviation"] is None else _num(out["deviation"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
           "items": [{"id": a["id"], "title": a.get("title") or "", "before": _num(dec(a["rate"])), "after": _num(dec(n["rate"]))}
                     for i, (a, n) in enumerate(zip(scope, out["items"])) if i in sel]}
    if prod and out["prod_rate"] != old_rate:
        ans["producing_rate"] = {"before": _num(old_rate), "after": _num(out["prod_rate"])}
    if not out["reachable"]:
        ans["reason"] = tr(ORP_REASONS.get(out.get("reason"), ORP_REASONS["negative"]))
    if not apply_:
        return jsonify(ans)
    if not out["reachable"]:
        return jsonify({**ans, "error": ans["reason"]}), 409
    ofd_need_current(c, oid, r, b, admin)  # 409 + the current state when someone saved in between
    oun_pre(c, uid, oid, "doc", did)  # ONE step of the document's undo for every position
    changed = 0
    for a, n in zip(scope, out["items"]):
        if dec(a["rate"]) != dec(n["rate"]):
            c.execute("UPDATE office_doc_items SET rate=? WHERE id=? AND doc_id=? AND org_id=?", (_num(dec(n["rate"])), a["id"], did, oid))
            changed += 1
    if "producing_rate" in ans:
        c.execute("UPDATE office_docs SET producing_rate=? WHERE id=? AND org_id=?", (_num(out["prod_rate"]), did, oid))
    if pid is not None:
        c.execute("UPDATE office_doc_parts SET updated_at=? WHERE id=? AND org_id=?", (iso(now_utc()), pid, oid))
    ofx_log(c, oid, "reprice", doc_id=did, detail={"pct": ans["pct"], "mode": mode, "round": rnd, "positions": changed,
                                                     **({"part": pid} if pid is not None else {}),
                                                     "before": {k: ans["before"][k] for k in ("net", "gross")},
                                                     "after": {k: ans["after"][k] for k in ("net", "gross")}})
    recalc(c, oid, did)
    bump(c)
    oun_post(c)
    c.commit()
    return jsonify({**ans, "changed": changed, "doc": doc_public(c, oid, doc_row(c, oid, did), admin)})
