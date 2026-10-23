"""2.162.0 A (#2603): test phase - deleting a finalised or sent invoice (office/invoices.py INVOICE_DELETE_TESTPHASE).

Only the admin of the office area (a person without an organisation is the admin of the personal office), only through
DELETE /api/office/docs/<id> (office/docs.py odoc_delete) with confirm_number = the invoice's number (wrong / missing: 409
code "confirm_number" - no agent deletes one by mistake). What goes with it: the credit notes cancelling it (cancels_id)
and the reminders listing only it (ref_doc_ids), their payments, items and links (ON DELETE CASCADE), the bank bookings
matched on them (open again), the time entries, receipts and trip costs billed on them (free again), the stored PDF / XML
files (after the commit), copies a move between offices filed into an archive the person administers. Cash book entries
of these documents only on request: without cash=0|1 a 409 code "cash" with the count; cash=1 deletes them, cash=0 keeps
them without the reference; entries on a closed day always stay. Anything else depending on the invoice (a final invoice
deducting it, a reminder listing other invoices too, a document or a series made from it) answers 409 with a clear text.
The number stays a gap; the office log keeps a "delete" entry per document (detail testphase, number, kind)."""
import glob
import json
import os

from flask import jsonify, request

from ..core.config import OFFICE_DIR
from ..core.db import body
from ..core.i18n import N_, tr
from ..core.pg import write_lock
from ..core.orgcrypt import oc_dec_fields
from .ledger import ofx_locked, ofx_log
from ..files.fsref import fs_ref_drop  # 2.199.0 B (#2742)

IDT_FINAL = N_("The final invoice {0} deducts this invoice; delete it first")
IDT_REMINDER = N_("The reminder {0} lists other invoices too; delete it first")
IDT_MADE = N_("The document {0} was made from this invoice; delete it first")
IDT_SERIES = N_("An invoice series uses this invoice as its template")
IDT_CHANGED = N_("Something was added to this invoice meanwhile; open it again and retry")
IDT_CASH_NEG = N_("Without the cash book entries of this invoice the cash balance would drop below zero; keep them")


def idt_applies(r):
    """The test phase rule decides for invoice r (a trial document has its own rule; a draft without number the old one)."""
    from .invoices import INVOICE_DELETE_TESTPHASE
    return bool(INVOICE_DELETE_TESTPHASE and r["kind"] == "invoice" and not r["trial"]
                and (ofx_locked(r) or r["status"] != "draft" or r["number"]))


def _j(s, default):
    try:
        v = json.loads(s) if s else default
    except ValueError:
        return default
    return v if isinstance(v, type(default)) else default


def _ids_in(v):
    out = set()
    for x in v if isinstance(v, list) else []:
        try:
            out.add(int(x))
        except (TypeError, ValueError):
            pass
    return out


def _name(r):
    return r["number"] or f"#{r['id']}"


def idt_plan(c, oid, r):
    """{ids, credits, reminders, block}: the documents going with invoice r, or the first reason it cannot go."""
    did = r["id"]
    credits = c.execute("SELECT id, number, kind, status, totals, locked_at FROM office_docs WHERE org_id=? AND kind='credit' AND cancels_id=? "
                        "ORDER BY id", (oid, did)).fetchall()
    ids = {did} | {x["id"] for x in credits}
    reminders, block = [], None
    for x in c.execute("SELECT id, number, kind, status, totals, locked_at, ref_doc_ids FROM office_docs WHERE org_id=? AND kind='reminder' "
                       "AND ref_doc_ids LIKE ? ORDER BY id", (oid, f"%{int(did)}%")).fetchall():  # pg-ok: digits only, case does not matter
        refs = _ids_in(_j(x["ref_doc_ids"], []))
        if did not in refs:
            continue
        if refs - ids:
            block = block or tr(IDT_REMINDER, _name(x))
        else:
            reminders.append(x)
    ids |= {x["id"] for x in reminders}
    q = ",".join("?" * len(ids))
    if not block:
        for x in c.execute(f"SELECT id, number FROM office_docs WHERE org_id=? AND abs_refs LIKE ? AND id NOT IN ({q})",  # pg-ok: digits only, case does not matter
                           [oid, f"%{int(did)}%", *ids]).fetchall():
            row = c.execute("SELECT abs_refs FROM office_docs WHERE id=?", (x["id"],)).fetchone()
            if did in _ids_in(_j(row["abs_refs"], [])):
                block = tr(IDT_FINAL, _name(x))
                break
    if not block:
        x = c.execute(f"SELECT id, number FROM office_docs WHERE org_id=? AND id NOT IN ({q}) AND (source_doc_id IN ({q}) OR "
                      f"version_of IN ({q}) OR cancels_id IN ({q})) ORDER BY id LIMIT 1", [oid, *ids, *ids, *ids, *ids]).fetchone()
        g_ = c.execute(f"SELECT id FROM office_gen_docs WHERE org_id=? AND doc_id IN ({q}) LIMIT 1", [oid, *ids]).fetchone()
        if x or g_:
            block = tr(IDT_MADE, _name(x) if x else f"#{g_['id']}")
    if not block and c.execute(f"SELECT 1 FROM office_inv_series WHERE org_id=? AND template_id IN ({q}) LIMIT 1", [oid, *ids]).fetchone():
        block = tr(IDT_SERIES)
    return {"ids": sorted(ids), "credits": list(credits), "reminders": reminders, "block": block}


def _cash(c, oid, ids):
    """The cash book entries of the documents (with the cancellations of them): (open [(row, book)], closed count)."""
    from .cashbook import cb_last_closed
    q = ",".join("?" * len(ids))
    rows = c.execute(f"SELECT id, book_id, day, no, dir, amount, storno_of FROM office_cash_entries WHERE org_id=? AND invoice_id IN ({q}) "
                     "ORDER BY book_id, day, no", [oid, *ids]).fetchall()
    seen = {x["id"] for x in rows}
    if seen:
        rows += [x for x in c.execute(f"SELECT id, book_id, day, no, dir, amount, storno_of FROM office_cash_entries WHERE org_id=? AND "
                                      f"storno_of IN ({','.join('?' * len(seen))})", [oid, *seen]).fetchall() if x["id"] not in seen]
    closed_day = {}
    for x in rows:
        if x["book_id"] not in closed_day:
            closed_day[x["book_id"]] = cb_last_closed(c, x["book_id"])
    # an entry and its cancellation stay together: one on a closed day keeps both
    pair = {}
    for x in rows:
        k = x["storno_of"] or x["id"]
        pair[k] = pair.get(k, False) or bool(closed_day[x["book_id"]] and x["day"] <= closed_day[x["book_id"]])
    open_, closed = [], 0
    for x in rows:
        if pair[x["storno_of"] or x["id"]]:
            closed += 1
        else:
            open_.append(x)
    return open_, closed


def _flags(c, oid, r):
    """sent / einvoice / export of invoice r for the confirmation's hint (from its columns and the office log)."""
    did = r["id"]
    log = {x[0] for x in c.execute("SELECT DISTINCT action FROM office_doc_log WHERE org_id=? AND doc_id=? AND action IN ('send', 'xml', 'datev')",
                                   (oid, did)).fetchall()}
    sent = bool(r["sent_at"] or r["status"] == "sent" or "send" in log)
    einvoice = bool(r["xml_sha256"]) and (sent or "xml" in log)
    export = bool(r["datev_sent_at"] or "datev" in log)
    if not export and r["locked_at"] and r["date"]:
        for x in c.execute("SELECT * FROM office_doc_log WHERE org_id=? AND action='export' AND target IN ('datev', 'books') AND at>=? "
                           "ORDER BY id DESC LIMIT 200", (oid, r["locked_at"])).fetchall():
            d = _j(oc_dec_fields(c, oid, "office_doc_log", x).get("detail"), {})
            frm, to = str(d.get("from") or ""), str(d.get("to") or "")
            if (frm and to and frm <= r["date"] <= to) or str(d.get("year") or "") == r["date"][:4]:
                export = True
                break
    return {"sent": sent, "einvoice": einvoice, "export": export}


def idt_info(c, oid, r):
    """What the confirmation dialog shows (admins; doc_public of a deletable invoice)."""
    p = idt_plan(c, oid, r)
    ids = p["ids"]
    q = ",".join("?" * len(ids))
    open_, closed = _cash(c, oid, ids)
    n = lambda sql, args: int(c.execute(sql, args).fetchone()[0])  # noqa: E731
    return {"number": r["number"] or "", **_flags(c, oid, r),
            "credits": [x["number"] or "" for x in p["credits"]], "reminders": [x["number"] or "" for x in p["reminders"]],
            "payments": n(f"SELECT COUNT(*) FROM office_payments WHERE org_id=? AND doc_id IN ({q})", [oid, *ids]),
            "bank": n(f"SELECT COUNT(*) FROM office_bank_tx WHERE org_id=? AND match_kind='invoice' AND match_id IN ({q})", [oid, *ids]),
            "time": n(f"SELECT COUNT(*) FROM time_entries WHERE billed_doc_id IN ({q})", ids),
            "cash": len(open_), "cash_closed": closed}


def _archive_copies(c, oid, uid, ids):
    """Copies of the documents a move between offices filed into an archive (office_archive.copy_of) the person administers."""
    from .model import office_role
    from .officemove import ofm_ws, ofm_ws_key
    key = ofm_ws_key(ofm_ws(c, oid))
    out = []
    for did in ids:
        for x in c.execute("SELECT id, org_id, file, copy_of FROM office_archive WHERE copy_of LIKE ?", (f'%"doc": {int(did)},%',)).fetchall():  # pg-ok: digits only, case does not matter
            cp = _j(x["copy_of"], {})
            if cp.get("doc") == did and cp.get("from") == key and office_role(c, uid, x["org_id"]) == "admin":
                out.append(x)
    return out


def idt_delete(c, oid, uid, r):
    """The test phase branch of odoc_delete (role checked, locks held): -> (response, file paths) or raises / answers 409."""
    from ..core.access import Denied
    b = body()
    p = idt_plan(c, oid, r)
    if p["block"]:
        raise Denied(409, p["block"])
    typed = str(request.args.get("confirm_number") or b.get("confirm_number") or "").strip()
    if not r["number"] or typed != str(r["number"]).strip():
        return (jsonify(error=tr("Type the number {0} to delete this invoice", r["number"] or ""), code="confirm_number", info=idt_info(c, oid, r)), 409), []
    ids = p["ids"]
    for did in ids:
        if did != r["id"]:
            write_lock(c, f"office_doc_{int(did)}")
    books = sorted({x[0] for x in c.execute(f"SELECT DISTINCT book_id FROM office_cash_entries WHERE org_id=? AND invoice_id IN ({','.join('?' * len(ids))})",
                                            [oid, *ids]).fetchall()})
    for bid in books:
        write_lock(c, f"office_cash_{int(bid)}")  # the cash book's own lock (cashbook.py)
    p2 = idt_plan(c, oid, r)  # #2603 review: the plan again under the locks - a credit note / reminder / final invoice made meanwhile
    if p2["block"] or p2["ids"] != ids:
        raise Denied(409, p2["block"] or tr(IDT_CHANGED))
    open_, closed = _cash(c, oid, ids)
    cash = str(request.args.get("cash", b.get("cash", "")) or "").lower()
    if open_ and cash not in ("0", "1", "true", "false"):
        return (jsonify(error=tr("Delete the cash book entries of this invoice too?"), code="cash", cash=len(open_), cash_closed=closed), 409), []
    if open_ and cash in ("1", "true"):
        _cash_drop(c, oid, uid, open_)
    paths = _drop(c, oid, uid, r, p)
    return (jsonify(ok=True, deleted=len(ids), cash_deleted=len(open_) if cash in ("1", "true") else 0, cash_kept=closed), 200), paths


def _cash_drop(c, oid, uid, rows):
    from .cashbook import _book, _log, _rows, cb_negative
    gone = {x["id"] for x in rows}
    for bid in sorted({x["book_id"] for x in rows}):
        if cb_negative(_book(c, oid, bid)["opening"], [x for x in _rows(c, oid, bid) if x["id"] not in gone]):
            from ..core.access import Denied
            raise Denied(409, tr(IDT_CASH_NEG))
    for x in sorted(rows, key=lambda y: (y["storno_of"] is None, y["id"])):  # cancellations first (storno_of)
        _log(c, oid, x["book_id"], None, "delete", {"no": x["no"], "day": x["day"], "dir": x["dir"], "amount": x["amount"], "testphase": True}, uid)
        c.execute("DELETE FROM office_cash_entries WHERE id=? AND org_id=?", (x["id"], oid))


def _drop(c, oid, uid, r, p):
    """Deletes the invoice with its credit notes and reminders -> the file paths to remove after the commit."""
    from .books import bk_ws
    from .timebill import tbill_free
    ids = p["ids"]
    q = ",".join("?" * len(ids))
    ws = bk_ws(c, oid)
    for x in c.execute(f"SELECT id FROM office_bank_tx WHERE org_id=? AND match_kind='invoice' AND match_id IN ({q}) ORDER BY id", [oid, *ids]).fetchall():
        write_lock(c, f"office_bank_tx_{x['id']}")  # the lock of bank.py's match / unmatch
        c.execute("UPDATE office_bank_tx SET match_kind=NULL, match_id=NULL, payment_id=NULL, matched_by=NULL, matched_at=NULL WHERE id=? AND org_id=?",
                  (x["id"], oid))
    paths = []
    for x in _archive_copies(c, oid, uid, ids):
        from .legacyimport import fi_archive_path
        pth = fi_archive_path(x["org_id"], x["file"])
        if pth:
            paths.append(pth)
        c.execute("DELETE FROM office_archive WHERE id=? AND org_id=?", (x["id"], x["org_id"]))
    docs = [r, *p["credits"], *p["reminders"]]
    for d in docs:
        did = d["id"]
        tbill_free(c, did)
        c.execute("UPDATE rc_receipts SET billed_doc_id=NULL, billed_at=NULL WHERE ws=? AND billed_doc_id=?", (ws, did))
        c.execute("UPDATE office_trip_items SET billed_doc_id=NULL, billed_at=NULL WHERE org_id=? AND billed_doc_id=?", (oid, did))
        totals = _j(d["totals"], {})
        ofx_log(c, oid, "delete", doc_id=did, detail={"number": d["number"], "status": d["status"], "net": totals.get("net"), "kind": d["kind"],
                                                      "testphase": True, **({"locked": True} if d["locked_at"] else {}),
                                                      **({"with": r["number"]} if did != r["id"] else {})})
        paths += glob.glob(os.path.join(OFFICE_DIR, str(int(oid)), f"doc{int(did)}-*"))
    c.execute(f"DELETE FROM office_docs WHERE org_id=? AND id IN ({q})", [oid, *ids])
    for i in ids:
        fs_ref_drop(c, "office_doc", i)  # 2.199.0 B (#2742): their folder entries go along (office/docref.py)
    return paths
