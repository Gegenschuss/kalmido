"""2.444.0 (#3447): the positions of a credit card statement -- by hand, marks, the search for their receipts, the match.

A position is an open line "needs a receipt". The search runs over ALL documents of the office's documents space the person
sees, also unsorted ones and the inbox: amount (also the original amount in its currency), date +- CL_DAYS, merchant name;
best hit first. A receipt is matched ONLY when a person confirms it, never by itself: the document becomes a receipt, its
payment day = the position's day, like a bank match; one document on one position, and never also on a bank booking. Fees and
interest need no receipt, private ones add up to what the holder pays back. Taken back like every match; a document moved to
the trash shows the position as open again.
The rights: office/cards.py (the people of the bookkeeping; the holder for their own cards); a locked month stays as it is."""
from datetime import date

from flask import jsonify, request

from ..core.access import Denied
from ..core.config import app
from ..core.db import body, bump, iso, now_utc
from ..core.errors import BadInput
from ..core.i18n import tr
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields
from ..core.pg import write_lock
from ..docs.ingest import docs_ingest, docs_kick
from ..docs.store import doc_open, label_name
from ..files.store import fs_chain, fs_deleted, fs_log_add, fs_role
from ..files.upsafe import h6d_read
from .bank import _clean, _name_hit, _norm
from .books import bk_receipt_set_paid, bk_to_home, bk_ws
from .calc import dec, dstr, money
from .cards import (CC_CONFIRMED, CC_DRAFT_ONLY, CC_KINDS, CC_NAME_MAX, _line_insert, _money, cc_ctx, cc_stmt, cc_writable, cl_day)
from .model import office_settings

CL_DAYS = 10  # +- days around a position that count as "date close"
CL_SCAN = 5000  # newest documents looked at
CL_SHOW = 30  # candidates of one position
CL_MIN = 3  # a suggestion needs at least the amount or the name


def cl_docs(c, oid):
    """The documents of the area that can still be a position's receipt, newest first: [{node_id, amount (home), orig (amount as
    printed), currency, date, title, sender, ws}]. Rows of the documents' list: nothing matched yet (position or bank), no statement."""
    ws = bk_ws(c, oid)
    s = office_settings(c, oid)
    out = []
    for r in c.execute("SELECT d.node_id, d.ws, d.amount, d.currency, d.doc_date, d.sender_id, n.name FROM doc_meta d JOIN fs_nodes n ON n.id=d.node_id "
                       "WHERE d.ws=? AND n.kind='file' AND n.deleted_at IS NULL "
                       "AND NOT EXISTS (SELECT 1 FROM office_cc_lines l WHERE l.org_id=? AND l.node_id=d.node_id AND l.state='matched') "
                       "AND NOT EXISTS (SELECT 1 FROM office_cc_statements t WHERE t.org_id=? AND t.node_id=d.node_id) "
                       "AND NOT EXISTS (SELECT 1 FROM office_bank_tx b WHERE b.org_id=? AND b.match_kind='receipt' AND b.match_id=d.node_id AND b.deleted_at IS NULL) "
                       f"ORDER BY d.node_id DESC LIMIT {CL_SCAN}", (ws, oid, oid, oid)).fetchall():
        raw = doc_open(c, r["ws"], "doc_meta.amount", r["amount"]) or ""
        a = dec(raw, "0") if raw else None
        cur = (r["currency"] or "").strip().upper()
        out.append({"node_id": r["node_id"], "amount": money(bk_to_home(a, cur, s)) if a else None, "orig": money(a) if a else None, "currency": cur,
                    "date": r["doc_date"] or "", "title": r["name"] or "", "sender": label_name(c, r["ws"], "sender", r["sender_id"]) or ""})
    return out


def cl_score(x, d):
    """(score, [reasons]) of document d for position x."""
    score, why = 0, []
    a = abs(x["amount"])
    if d["amount"] is not None and d["amount"] == a:
        score += 5
        why.append(tr("same amount"))
    elif x["orig_amount"] is not None and d["orig"] is not None and d["currency"] == x["orig_currency"] and d["orig"] == abs(x["orig_amount"]):
        score += 5
        why.append(tr("same original amount"))
    if x["merchant"] and _name_hit(x["merchant"], f"{d['sender']} {d['title']}"):
        score += 3
        why.append(tr("name matches"))
    if d["date"][:10] and x["day"]:
        try:
            off = abs((date.fromisoformat(d["date"][:10]) - date.fromisoformat(x["day"])).days)
        except ValueError:
            off = None
        if off is not None and off <= CL_DAYS:
            score += 2 if off > 2 else 3
            why.append(tr("date close"))
    return score, why


def _seen(c, nid, uid):
    chain = fs_chain(c, nid)
    return bool(chain) and not fs_deleted(chain) and bool(fs_role(c, nid, uid, chain=chain))


def cl_found(c, uid, x, docs, q=""):
    """The documents for position x the person sees, best first: [{id, label, amount, date, reason}]."""
    hits = []
    for d in docs:
        if q and q not in _norm(f"{d['title']} {d['sender']} {dstr(d['orig']) if d['orig'] is not None else ''}"):
            continue
        sc, why = cl_score(x, d)
        if sc >= CL_MIN or q:
            hits.append((sc, d, why))
    hits.sort(key=lambda h: (-h[0], -h[1]["node_id"]))
    out = []
    for sc, d, why in hits:
        if _seen(c, d["node_id"], uid):
            out.append({"id": d["node_id"], "label": d["sender"] or d["title"], "title": d["title"], "amount": dstr(d["amount"]) if d["amount"] is not None else None,
                        "date": d["date"], "reason": ", ".join(why), "score": sc})
            if len(out) >= CL_SHOW:
                break
    return out


def _public(c, x, gone=False):
    r = {"id": x["id"], "day": x["day"], "booked": x["booked"], "merchant": x["merchant"] or "", "amount": dstr(x["amount"]),
         "orig_amount": dstr(x["orig_amount"]) if x["orig_amount"] is not None else None, "orig_currency": x["orig_currency"] or None, "kind": x["kind"],
         "state": x["state"], "node_id": x["node_id"], "gone": gone}
    if x["node_id"] and not gone:
        n = c.execute("SELECT name FROM fs_nodes WHERE id=?", (x["node_id"],)).fetchone()
        r["receipt"] = (n["name"] if n else "") or ""
    return r


def cl_view(c, oid, uid, s, lines):
    """The positions as the sheet shows them; an open one carries its best receipt (suggestion, nothing matched)."""
    docs = cl_docs(c, oid) if s["state"] == "confirmed" and any(x["state"] == "open" for x in lines) else []
    out = []
    for x in lines:
        gone = bool(x["state"] == "matched" and x["node_id"] and fs_deleted(fs_chain(c, x["node_id"]) or [{"deleted_at": "x"}]))
        p = _public(c, x, gone)
        if x["state"] == "open" and docs:
            best = cl_found(c, uid, x, docs)
            p["suggestion"] = best[0] if best and best[0]["score"] >= 5 else None
        out.append(p)
    return out


def cl_row(c, oid, lid, uid, every):
    """(position, statement): 404 outside the person's cards."""
    r = c.execute("SELECT * FROM office_cc_lines WHERE id=? AND org_id=?", (lid, oid)).fetchone()
    if r is None:
        raise Denied(404)
    s = cc_stmt(c, oid, r["statement_id"], uid, every)
    x = oc_dec_fields(c, oid, "office_cc_lines", r)
    x["amount"] = money(dec(x["amount"], "0"))
    x["orig_amount"] = money(dec(x["orig_amount"])) if x["orig_amount"] else None
    return x, s


def _answer(c, oid, uid, lid, every):
    from .cards import _stmt_public
    x, s = cl_row(c, oid, lid, uid, every)
    return jsonify(line=_public(c, x), statement=_stmt_public(c, oid, s))


def _fields(b, cur=None):
    """The typed fields of a position out of body b (cur: PATCH)."""
    v = dict(cur or {})
    if "day" in b or not cur:
        v["day"] = cl_day(b.get("day"), "day")
    if "merchant" in b or not cur:
        v["merchant"] = _clean(b.get("merchant"), CC_NAME_MAX)
        if not v["merchant"]:
            raise BadInput(tr("Please enter the merchant"))
    if "amount" in b or not cur:
        v["amount"] = _money(b.get("amount"), "amount")
    if "orig_amount" in b or "orig_currency" in b or not cur:
        oa, oc = b.get("orig_amount", v.get("orig_amount")), b.get("orig_currency", v.get("orig_currency"))
        v["orig_amount"] = _money(oa, "orig_amount") if oa not in (None, "") else None
        v["orig_currency"] = oc.strip().upper()[:3] if isinstance(oc, str) and v["orig_amount"] is not None else ""
    if "kind" in b or not cur:
        k = b.get("kind") or ("credit" if v["amount"] < 0 else "purchase")
        if k not in CC_KINDS:
            raise BadInput(tr("Invalid value: {0}", "kind"))
        v["kind"] = k
    return v


def _draft(s):
    if s["state"] != "draft":
        raise Denied(409, tr(CC_CONFIRMED))


@app.post("/api/office/cards/statements/<int:sid>/lines")
def cl_add(sid):
    """{day, merchant, amount, orig_amount?, orig_currency?, kind?}: a position typed in (a draft only) -> 201."""
    c, uid, oid, every = cc_ctx()
    s = cc_stmt(c, oid, sid, uid, every)
    cc_writable(c, oid, s)
    _draft(s)
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    v = _fields(b)
    n = c.execute("SELECT COALESCE(MAX(sort), -1)+1 AS n FROM office_cc_lines WHERE org_id=? AND statement_id=?", (oid, sid)).fetchone()["n"]
    lid = _line_insert(c, oid, sid, n, v)
    bump(c)
    c.commit()
    return _answer(c, oid, uid, lid, every), 201


@app.patch("/api/office/cards/lines/<int:lid>")
def cl_patch(lid):
    """{state: open|noreceipt|private} marks a position of a confirmed statement (not a matched one); the fields of POST
    change a position of a draft."""
    c, uid, oid, every = cc_ctx()
    x, s = cl_row(c, oid, lid, uid, every)
    cc_writable(c, oid, s)
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    if "state" in b:
        if b["state"] not in ("open", "noreceipt", "private"):
            raise BadInput(tr("Invalid value: {0}", "state"))
        if x["state"] == "matched":
            raise Denied(409, tr("This position has its receipt; undo the match first"))
        c.execute("UPDATE office_cc_lines SET state=? WHERE id=? AND org_id=?", (b["state"], lid, oid))
    keys = {k for k in b if k != "state"}
    if keys:
        _draft(s)
        v = _fields(b, {k: x[k] for k in ("day", "merchant", "amount", "orig_amount", "orig_currency", "kind")})
        row = oc_enc_fields(c, oid, "office_cc_lines", {"merchant": v["merchant"], "amount": dstr(v["amount"]), "orig_amount": dstr(v["orig_amount"]) if v["orig_amount"] is not None else ""})
        c.execute("UPDATE office_cc_lines SET day=?, merchant=?, amount=?, orig_amount=?, orig_currency=?, kind=?, state=? WHERE id=? AND org_id=?",
                  (v["day"], row["merchant"], row["amount"], row["orig_amount"], v["orig_currency"], v["kind"], "noreceipt" if v["kind"] == "fee" else "open", lid, oid))
    bump(c)
    c.commit()
    return _answer(c, oid, uid, lid, every)


@app.delete("/api/office/cards/lines/<int:lid>")
def cl_del(lid):
    """A position of a draft goes (the reader's mistake); the answer carries it for the undo (POST .../lines)."""
    c, uid, oid, every = cc_ctx()
    x, s = cl_row(c, oid, lid, uid, every)
    cc_writable(c, oid, s)
    _draft(s)
    c.execute("DELETE FROM office_cc_lines WHERE id=? AND org_id=?", (lid, oid))
    bump(c)
    c.commit()
    return jsonify(ok=True, line=_public(c, x))


@app.get("/api/office/cards/lines/<int:lid>/candidates")
def cl_candidates(lid):
    """?q= -> {items: [{id, label, title, amount, date, reason, score}]} the documents that can be this position's receipt, best
    first. Without q only those that fit; with q everything the words find."""
    c, uid, oid, every = cc_ctx()
    x, _s = cl_row(c, oid, lid, uid, every)
    return jsonify(items=cl_found(c, uid, x, cl_docs(c, oid), _norm(request.args.get("q") or "")[:100]))


def _match(c, oid, uid, x, s, nid):
    """The confirmed receipt nid on position x: the document becomes a receipt, its payment day the position's day."""
    from ..receipts.suggest import rc_set
    from .bank import _rc_paid_amount
    if s["state"] != "confirmed":
        raise Denied(409, tr(CC_DRAFT_ONLY))
    if x["state"] != "open":
        raise Denied(409, tr("This position needs no receipt or already has one"))
    ws = bk_ws(c, oid)
    write_lock(c, f"office_bank_receipt_{nid}")  # one lock with the bank's match of a receipt
    d = c.execute("SELECT d.org_id FROM doc_meta d JOIN fs_nodes n ON n.id=d.node_id WHERE d.node_id=? AND d.ws=? AND n.kind='file' AND n.deleted_at IS NULL", (nid, ws)).fetchone()
    if d is None or not _seen(c, nid, uid):
        raise Denied(404)
    if c.execute("SELECT 1 FROM office_cc_lines WHERE org_id=? AND node_id=? AND state='matched' LIMIT 1", (oid, nid)).fetchone() \
            or c.execute("SELECT 1 FROM office_bank_tx WHERE org_id=? AND deleted_at IS NULL AND match_kind='receipt' AND match_id=? LIMIT 1", (oid, nid)).fetchone():
        raise Denied(409, tr("This receipt is matched with another booking"))
    if not c.execute("SELECT 1 FROM rc_receipts WHERE node_id=?", (nid,)).fetchone():
        rc_set(c, {"id": nid, "org_id": d["org_id"]}, ws, None, "", uid, keep=True)
    rc = _rc_paid_amount(c, oid, nid)
    if not rc["paid_at"]:
        bk_receipt_set_paid(c, oid, nid, x["day"])
    c.execute("UPDATE office_cc_lines SET state='matched', node_id=?, matched_by=?, matched_at=? WHERE id=? AND org_id=?", (nid, uid, iso(now_utc()), x["id"], oid))
    a = abs(x["amount"])
    return {"receipt": dstr(rc["amount"]), "position": dstr(a)} if rc["amount"] is not None and rc["amount"] != a else None


@app.post("/api/office/cards/lines/<int:lid>/match")
def cl_match(lid):
    """{node_id}: a person confirms the receipt of this position -> {line, statement, amount_differs}. 409 on a position that
    needs none or a receipt in use, 404 for a document the person does not see."""
    c, uid, oid, every = cc_ctx()
    b = body()
    nid = b.get("node_id") if isinstance(b, dict) else None
    if isinstance(nid, bool) or not isinstance(nid, int):
        raise BadInput(tr("Invalid value: {0}", "node_id"))
    write_lock(c, f"office_cc_{oid}")
    x, s = cl_row(c, oid, lid, uid, every)
    cc_writable(c, oid, s)
    differs = _match(c, oid, uid, x, s, nid)
    bump(c)
    c.commit()
    r = _answer(c, oid, uid, lid, every).get_json()
    return jsonify({**r, "amount_differs": differs})


@app.post("/api/office/cards/lines/<int:lid>/unmatch")
def cl_unmatch(lid):
    """Takes the receipt off the position; the payment day this match set goes (one typed by hand stays). Answers node_id for the undo."""
    from .bank import _rc_paid_amount
    c, uid, oid, every = cc_ctx()
    write_lock(c, f"office_cc_{oid}")
    x, s = cl_row(c, oid, lid, uid, every)
    cc_writable(c, oid, s)
    if x["state"] != "matched":
        raise Denied(409, tr("This position has no receipt"))
    try:
        if x["node_id"] and _rc_paid_amount(c, oid, x["node_id"])["paid_at"] == x["day"]:
            bk_receipt_set_paid(c, oid, x["node_id"], None)
    except Denied as e:  # the receipt is gone
        if e.code != 404:
            raise
    c.execute("UPDATE office_cc_lines SET state='open', node_id=NULL, matched_by=NULL, matched_at=NULL WHERE id=? AND org_id=?", (lid, oid))
    bump(c)
    c.commit()
    r = _answer(c, oid, uid, lid, every).get_json()
    return jsonify({**r, "node_id": x["node_id"]})


@app.post("/api/office/cards/lines/<int:lid>/upload")
def cl_upload(lid):
    """Multipart file: the receipt of this position, uploaded by the holder or the bookkeeping: a document of the office's
    documents space, a receipt, matched at once (the person has chosen the position). 201 {line, statement, node_id, fresh}."""
    from ..admin.hosting import QuotaExceeded
    c, uid, oid, every = cc_ctx()
    write_lock(c, f"office_cc_{oid}")
    x, s = cl_row(c, oid, lid, uid, every)
    cc_writable(c, oid, s)
    if s["state"] != "confirmed":
        raise Denied(409, tr(CC_DRAFT_ONLY))
    f = request.files.get("file")
    if f is None:
        raise BadInput(tr("No file"))
    ws = bk_ws(c, oid)
    info = {}
    try:
        nid = docs_ingest(c, uid, None if ws[0] == "u" else oid, f.filename or "receipt.jpg", h6d_read(f), f.mimetype, "upload", dedup=True, info=info)
    except QuotaExceeded:
        raise BadInput(tr("{0}: no space left in your storage", f.filename or "")) from None
    except ValueError as e:
        raise BadInput(str(e)) from None
    if not info.get("dup"):
        fs_log_add(c, nid, "upload")
    _match(c, oid, uid, x, s, nid)
    bump(c)
    c.commit()
    docs_kick()
    r = _answer(c, oid, uid, lid, every).get_json()
    return jsonify({**r, "node_id": nid, "fresh": not info.get("dup")}), 201


