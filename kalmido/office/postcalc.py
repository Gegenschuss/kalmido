"""2.1158.0 (#4566 B): the post-calculation of an accepted quotation as an invoice draft (decision of 14.11.2026).

GET  /api/office/docs/<did>/postcalc: the preview -- the positions the invoice would get (as "Create invoice", a quotation
     with parts always in the form "full": the title page's positions and those of every printed part), each with its
     quantity from the quotation (planned) and, for a position with a linked task (task_offer_links.item_key, made by
     "Create tasks", office/offertasks.py), the tracked hours (actual) and the difference; the net sums planned / actual.
POST /api/office/docs/<did>/postcalc {client_ref?, force?}: the invoice draft -- like POST .../invoice, but a position with
     the unit "hour" and a linked task carries the tracked hours (rounded to a quarter hour) instead of the quoted ones, at
     the quotation's rate. Never finalised: a draft like every other one.

What changes: only positions with the unit hour and a linked living task. A position in another unit (day, piece, flat
rate ...) stays as quoted and is marked "not by time" when it has a task; a part that is one amount (a shoot part, a part
not printed) stays one amount ("part"); the automatic lines (producing, raw data, discount, a percent position) keep the
quotation's amounts. Actual = the finished time entries of the task and its subtasks (a subtask linked to a position of its
own counts there, not twice), everyone's, like the budget warning (personal/budgetwarn.py _bw_secs).

Rights: those of "Create invoice" (office_ctx, the area "offers" by the route's segment, the document of this office:
doc_row) and, as times are read, the area "time" (view) of the office and the quotation's project: the caller sees it, is
no participant there and sees everyone's time entries in it (its owner / admins / the organisation's admins:
n43_admin_lists) -- else 403. Only the tasks of that project and its entries (time_entries.list_id) count: never a time
of another workspace. A quotation with progress invoices (the full invoice would bill them twice) and a flat price
quotation (one price per tax rate, nothing to count) are refused (409)."""
from decimal import ROUND_HALF_UP, Decimal

from flask import jsonify

from ..core.config import app
from ..core.db import body, bump
from ..core.i18n import N_, tr
from ..core.access import Denied, list_role, live_sql, plists
from ..core.errors import DeniedKey
from ..personal.timetrack import evis, n43_admin_lists, th_sql
from . import abschlag as _abs
from .calc import calc_lang, dec, fmt_money, fmt_qty
from .docs import doc_row, recalc
from .homecur import hc_home
from .invoices import _answer, _insert_doc, _put_rows, inv_items_from_offer, inv_new_row, ofi_ref_doc, ofi_ref_keep
from .ledger import ofx_log
from .model import office_ctx, office_settings
from .offerlink import oil_need_no_invoice
from .offertasks import otk_links
from .parts import tp_has_parts
from .rights import ofr_need_area

PC_STEP = Decimal("0.25")  # the tracked hours are rounded to a quarter hour (half up)


def pc_round_h(seconds):
    """Seconds -> hours rounded to PC_STEP (Decimal)."""
    h = Decimal(int(seconds or 0)) / Decimal(3600)
    return (h / PC_STEP).quantize(Decimal(1), rounding=ROUND_HALF_UP) * PC_STEP


def _pc_offer(c, oid, did):
    r = doc_row(c, oid, did)  # the office's document only (another office: 404)
    if r["kind"] != "offer":
        raise Denied(409, tr("Only a quotation can be turned into an invoice"))
    if r["status"] != "accepted":
        raise DeniedKey(409, N_("The post-calculation needs an accepted quotation"))
    if _abs._col(r, "flat_print"):
        raise DeniedKey(409, N_("A flat price quotation is invoiced at its price; create the invoice instead"))
    if _abs.abs_progress_of(c, oid, r["id"], locked_only=True):  # as inv_offer_invoice: the full invoice would bill them twice
        raise Denied(409, tr("The quotation has progress invoices; create the final invoice instead"))
    return r


def _pc_need_times(c, uid, oid, lid):
    """The caller may read everyone's times of project lid (see the module text), else 403."""
    ofr_need_area(c, uid, oid, "time", "view")
    if not list_role(c, lid, uid) or lid in set(plists(c, uid)):
        raise DeniedKey(403, N_("You do not see the project of this quotation"))
    adm = n43_admin_lists(c, uid)
    if adm is not None and lid not in adm:
        raise DeniedKey(403, N_("Only the project's owner or admins see everyone's times"))


def pc_actual(c, uid, oid, r):
    """{item_key: {"task_id", "s"}} of the quotation's linked living tasks in its project (empty without a project)."""
    lid = r["list_id"]
    if not lid:
        return {}
    _pc_need_times(c, uid, oid, lid)
    links = {k: x for k, x in otk_links(c, oid, r, lid).items() if not x["deleted_at"] and x["list_id"] == lid}
    if not links:
        return {}
    linked = {x["task_id"] for x in links.values()}
    kids = {}
    for k, p in c.execute(f"SELECT id, parent_id FROM tasks WHERE list_id=? AND {live_sql()} AND parent_id IS NOT NULL", (lid,)):
        kids.setdefault(p, []).append(k)
    out = {}
    for key, x in links.items():
        ids, todo = {x["task_id"]}, [x["task_id"]]
        while todo:  # the branch, without a subtask that is linked to a position of its own (guarded against a cycle)
            for k in kids.get(todo.pop(), ()):
                if k not in ids and k not in linked:
                    ids.add(k)
                    todo.append(k)
        q = ",".join("?" * len(ids))
        s = c.execute(f"""SELECT COALESCE(SUM(seconds), 0) FROM time_entries WHERE "end" IS NOT NULL AND list_id=? AND task_id IN ({q})
                          AND {evis(c, uid, "")} AND {th_sql("")}""", (lid, *ids)).fetchone()[0] or 0
        out[key] = {"task_id": x["task_id"], "s": int(s)}
    return out


def _net(row, qty):
    v = dec(qty) * dec(row.get("rate")) * (1 - dec(row.get("discount_pct")) / 100)
    return -v if row.get("kind") == "discount" else v


def pc_build(c, uid, oid, r):
    """-> (invoice rows with the actual hours, preview rows, sums) of quotation r."""
    rows = inv_items_from_offer(c, oid, r, "full" if tp_has_parts(c, oid, r["id"]) else None, None, tag=True)
    act = pc_actual(c, uid, oid, r)
    lg = calc_lang(r["lang"])
    home = hc_home(office_settings(c, oid))
    out, prev = [], []
    plan = actual = Decimal(0)
    for row in rows:
        key, part = row.pop("_key", None), row.pop("_part", None)
        if row.get("kind") in ("heading", "text"):
            out.append(row)
            continue
        q0 = dec(row.get("qty"), "1")
        a = act.get(key) if key else None
        st = "part" if part else "none" if a is None else "time" if row.get("unit") == "hour" else "not_time"
        q1 = pc_round_h(a["s"]) if st == "time" else q0
        if st == "time":
            row["qty"] = float(q1)
        out.append(row)
        n0, n1 = _net(row, q0), _net(row, q1)
        plan, actual = plan + n0, actual + n1
        prev.append({"key": key, "title": row.get("title") or "", "kind": row.get("kind"), "unit": row.get("unit"), "rate": float(dec(row.get("rate"))),
                     "state": st, "task_id": a["task_id"] if a else None, "plan_qty": float(q0), "actual_qty": float(q1),
                     "actual_h": float(round(Decimal(a["s"]) / 3600, 2)) if a else None, "diff_qty": float(q1 - q0),
                     "plan_text": fmt_qty(q0, lg), "actual_text": fmt_qty(q1, lg), "diff_text": fmt_qty(q1 - q0, lg),
                     "plan_net_text": fmt_money(n0, lg, home), "actual_net_text": fmt_money(n1, lg, home)})
    sums = {"plan_net": float(round(plan, 2)), "actual_net": float(round(actual, 2)), "diff_net": float(round(actual - plan, 2)),
            "plan_net_text": fmt_money(plan, lg, home), "actual_net_text": fmt_money(actual, lg, home), "diff_net_text": fmt_money(actual - plan, lg, home),
            "currency": home, "linked": len(act), "timed": len([x for x in prev if x["state"] == "time"]), "step_h": float(PC_STEP)}
    return out, prev, sums


@app.get("/api/office/docs/<int:did>/postcalc")
def pc_get(did):
    """The preview: {doc_id, rows: [{key, title, unit, rate, state: time|not_time|none|part, task_id, plan_qty, actual_qty,
    actual_h, diff_qty, *_text}], sums: {plan_net, actual_net, diff_net, *_text, currency, linked, timed, step_h}}."""
    c, uid, oid = office_ctx()
    r = _pc_offer(c, oid, did)
    _, prev, sums = pc_build(c, uid, oid, r)
    return jsonify({"doc_id": r["id"], "list_id": r["list_id"], "rows": prev, "sums": sums})


@app.post("/api/office/docs/<int:did>/postcalc")
def pc_post(did):
    """The invoice draft of the post-calculation (see the module text). 201 the invoice; sent again with the same client_ref
    = the invoice made the first time; another invoice of the quotation: 409 invoice_exists unless force."""
    c, uid, oid = office_ctx()
    r = _pc_offer(c, oid, did)
    b = body()
    b = b if isinstance(b, dict) else {}
    ref, hit = ofi_ref_doc(c, oid, uid, b)
    if hit:
        return _answer(c, oid, uid, hit)
    oil_need_no_invoice(c, oid, r, {"force": b.get("force")})  # inv_type is no choice here: always the full invoice
    rows, _, sums = pc_build(c, uid, oid, r)
    row = inv_new_row(c, oid, office_settings(c, oid), "invoice", r["lang"], r)
    row["source_doc_id"] = r["id"]
    nid = _insert_doc(c, oid, uid, row)
    _put_rows(c, oid, nid, rows)
    recalc(c, oid, nid)
    ofx_log(c, oid, "create", doc_id=nid, detail={"kind": "invoice", "from_id": r["id"], "from_number": r["number"], "postcalc": True, "timed": sums["timed"]})
    ofi_ref_keep(c, nid, ref)
    bump(c)
    c.commit()
    return _answer(c, oid, uid, nid, 201)
