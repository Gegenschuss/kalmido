"""2.444.0 (#3447): credit card statements in the office -- proof for the bookkeeping: only the total leaves the business
account, the positions need their receipts.

A card (office_cc_cards) = a holder (a person of the area or a free name) + provider + last four digits + the business account
the total leaves. A statement (office_cc_statements) = one PDF per card and month, kept as a document of the office's documents
space; office/ccread.py reads its positions (office_cc_lines), a person confirms them (state draft -> confirmed; a statement
that cannot be read: typed in by hand). A position is an open line "needs a receipt", no receipt itself; fees and interest need
none (the statement is the proof), private ones are marked and add up to what the holder pays back. office/cardlines.py finds
and matches the receipts, office/cardnorc.py reminds and hands over to the exports. The bank booking of the total is matched
through the bank's own route (office/bank.py kind "card": the sum is checked, the booking counts as having its receipt).
Rights: the people of the bookkeeping like the bank (area "cards"); the holder with an account in addition sees only their
own cards and works on them (level "own", or a member without office groups), never the cards themselves or the bank.
Agents and kids 403 (office_gate). Holder name, digits, account, amounts and merchants encrypted at rest (orgcrypt)."""
import re

from flask import Response, jsonify, request

from ..core.access import Denied
from ..core.config import app
from ..core.db import body, bump, iso, local_now, now_utc
from ..core.errors import BadInput
from ..core.i18n import N_, tr
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields
from ..core.pg import insert_id, system_ctx, write_lock
from ..docs.ingest import docs_ingest, docs_kick
from ..files.store import fs_log_add, fs_read
from ..files.upsafe import h6d_read
from .bank import _clean, _home, _tx_dec
from .books import bk_ws
from .calc import dec, dstr, money
from .ccread import CCR_READERS, ccr_read
from .cfbank import cfb_balances
from .ledger import ofx_log
from .model import office_ctx, office_ctx_admin, office_role, pb_owner
from .periodlock import period_need_open, pl_is_locked
from .rights import LV, ofr_rights

CC_PROVIDERS = {"mastercard": "Mastercard"}
CC_KINDS = ("purchase", "fee", "credit")
CC_STATES = ("open", "matched", "noreceipt", "private")
CC_FILE_MAX = 20 * 1024 * 1024
CC_NAME_MAX = 120
CC_AMOUNT_MAX = 100000000
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CC_DRAFT_ONLY = N_("Confirm the positions first")
CC_CONFIRMED = N_("The positions are confirmed; take the confirmation back to change them")


def cc_sees_all(c, uid, oid):
    """uid sees every card of area oid: the people of the bookkeeping (office groups: level view or more in the area cards)."""
    r = ofr_rights(c, uid, oid)
    if r is None:
        return office_role(c, uid, oid) in ("admin", "accounting")
    return LV[r["levels"].get("cards", "none")] >= LV["view"]


def cc_flag(c, uid, oid):
    """GET /api/office/settings "cards": the person holds a card here (the menu shows the point without the bookkeeping)."""
    return bool(c.execute("SELECT 1 FROM office_cc_cards WHERE org_id=? AND holder_id=? AND deleted_at IS NULL LIMIT 1", (oid, uid)).fetchone())


def cc_ctx():
    """(c, uid, oid, sees all): holders pass (cc_card narrows them to their own cards)."""
    c, uid, oid = office_ctx()
    return c, uid, oid, cc_sees_all(c, uid, oid)


def _members(c, oid):
    """[{id, name}]: who can be a card's holder (the people of the area; a personal office: its owner)."""
    owner = pb_owner(c, oid)
    with system_ctx(c):  # names of the area's people, also for an admin with another list of contacts
        if owner is not None:
            rows = c.execute("SELECT id, display_name, username FROM users WHERE id=?", (owner,)).fetchall()
        else:
            rows = c.execute("SELECT u.id, u.display_name, u.username FROM org_members m JOIN users u ON u.id=m.user_id "
                             "WHERE m.org_id=? AND u.disabled=0 AND COALESCE(u.kind, 'user')<>'agent' ORDER BY 2, 3", (oid,)).fetchall()
    return [{"id": r["id"], "name": r["display_name"] or r["username"]} for r in rows]


def _holder(c, oid, r):
    if r["holder_id"]:
        for p in _members(c, oid):
            if p["id"] == r["holder_id"]:
                return p["name"]
    return r["holder_name"] or ""


def _accounts(c, oid):
    return sorted({b["account"] for b in cfb_balances(c, oid) if b["account"]})


def cc_card_row(c, oid, cid):
    r = c.execute("SELECT * FROM office_cc_cards WHERE id=? AND org_id=? AND deleted_at IS NULL", (cid, oid)).fetchone()
    if r is None:
        raise Denied(404)
    return oc_dec_fields(c, oid, "office_cc_cards", r)


def cc_card(c, oid, cid, uid, every):
    """The card; 404 outside the area, deleted or somebody else's for a holder."""
    r = cc_card_row(c, oid, cid)
    if not every and r["holder_id"] != uid:
        raise Denied(404)
    return r


def _card_public(c, oid, r):
    n = c.execute("SELECT COUNT(*) AS n FROM office_cc_statements WHERE org_id=? AND card_id=? AND deleted_at IS NULL", (oid, r["id"])).fetchone()["n"]
    op = c.execute("SELECT COUNT(*) AS n FROM office_cc_lines l JOIN office_cc_statements s ON s.id=l.statement_id WHERE l.org_id=? AND s.card_id=? "
                   "AND s.deleted_at IS NULL AND s.state='confirmed' AND l.state='open'", (oid, r["id"])).fetchone()["n"]
    return {"id": r["id"], "holder_id": r["holder_id"], "holder": _holder(c, oid, r), "holder_name": r["holder_name"] or "", "provider": r["provider"],
            "provider_name": CC_PROVIDERS.get(r["provider"], r["provider"]), "last4": r["last4"] or "", "account": r["account"] or "", "statements": n, "open": op}


def _card_fields(c, oid, b, cur=None):
    """The fields of a card out of body b (cur: a PATCH keeps what is not named)."""
    cur = cur or {}
    v = {k: cur.get(k) for k in ("holder_id", "holder_name", "provider", "last4", "account")}
    if "holder_id" in b:
        h = b["holder_id"]
        if h is not None and (isinstance(h, bool) or not isinstance(h, int) or h not in {p["id"] for p in _members(c, oid)}):
            raise BadInput(tr("Invalid value: {0}", "holder_id"))
        v["holder_id"] = h
    if "holder_name" in b:
        v["holder_name"] = _clean(b["holder_name"], CC_NAME_MAX)
    if "provider" in b:
        v["provider"] = b["provider"]
    if "last4" in b:
        v["last4"] = b["last4"].strip() if isinstance(b["last4"], str) else ""
    if "account" in b:
        v["account"] = _clean(b["account"], CC_NAME_MAX)
    v["provider"] = v["provider"] or "mastercard"
    if v["provider"] not in CC_PROVIDERS:
        raise BadInput(tr("Invalid value: {0}", "provider"))
    if not re.fullmatch(r"\d{4}", v["last4"] or ""):
        raise BadInput(tr("Please enter the last four digits of the card"))
    if not v["holder_id"] and not v["holder_name"]:
        raise BadInput(tr("Please choose the holder or enter a name"))
    if v["holder_id"]:
        v["holder_name"] = ""
    return v


@app.get("/api/office/cards")
def cc_list():
    """{items: [{id, holder_id, holder, provider, last4, account, statements, open}], manage, currency} + for the people who
    manage the cards people (possible holders) and accounts (the business accounts of the statements). A holder: only their own."""
    c, uid, oid, every = cc_ctx()
    q = "SELECT * FROM office_cc_cards WHERE org_id=? AND deleted_at IS NULL" + ("" if every else " AND holder_id=?") + " ORDER BY id"
    rows = [oc_dec_fields(c, oid, "office_cc_cards", r) for r in c.execute(q, (oid,) if every else (oid, uid)).fetchall()]
    out = {"items": [_card_public(c, oid, r) for r in rows], "manage": every, "currency": _home(c, oid), "providers": [{"id": k, "name": v} for k, v in CC_PROVIDERS.items()]}
    if every:
        out.update(people=_members(c, oid), accounts=_accounts(c, oid))
    return jsonify(out)


@app.post("/api/office/cards")
def cc_add():
    """{holder_id | holder_name, provider?, last4, account?} -> 201 the card."""
    c, uid, oid = office_ctx_admin()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    v = _card_fields(c, oid, b)
    ts = iso(now_utc())
    row = oc_enc_fields(c, oid, "office_cc_cards", {"org_id": oid, **v, "created_by": uid, "created_at": ts, "updated_at": ts})
    cid = insert_id(c, f"INSERT INTO office_cc_cards({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    ofx_log(c, oid, "create", target="cards", detail={"card": cid})
    bump(c)
    c.commit()
    return jsonify(_card_public(c, oid, cc_card_row(c, oid, cid))), 201


@app.patch("/api/office/cards/<int:cid>")
def cc_patch(cid):
    c, uid, oid = office_ctx_admin()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    v = _card_fields(c, oid, b, cc_card_row(c, oid, cid))
    row = oc_enc_fields(c, oid, "office_cc_cards", dict(v))
    c.execute(f"UPDATE office_cc_cards SET {', '.join(k + '=?' for k in row)}, updated_at=? WHERE id=? AND org_id=?", (*row.values(), iso(now_utc()), cid, oid))
    ofx_log(c, oid, "update", target="cards", detail={"card": cid})
    bump(c)
    c.commit()
    return jsonify(_card_public(c, oid, cc_card_row(c, oid, cid)))


@app.delete("/api/office/cards/<int:cid>")
def cc_del(cid):
    """Takes a card out of the list (its statements stay in the books and exports; POST .../restore brings it back)."""
    c, uid, oid = office_ctx_admin()
    cc_card_row(c, oid, cid)
    c.execute("UPDATE office_cc_cards SET deleted_at=? WHERE id=? AND org_id=?", (iso(now_utc()), cid, oid))
    ofx_log(c, oid, "delete", target="cards", detail={"card": cid})
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.post("/api/office/cards/<int:cid>/restore")
def cc_restore(cid):
    c, uid, oid = office_ctx_admin()
    if not c.execute("UPDATE office_cc_cards SET deleted_at=NULL WHERE id=? AND org_id=? AND deleted_at IS NOT NULL", (cid, oid)).rowcount:
        raise Denied(404)
    bump(c)
    c.commit()
    return jsonify(_card_public(c, oid, cc_card_row(c, oid, cid)))


# ---------------------------------------------------------------- statements
def cc_stmt_row(c, oid, sid):
    r = c.execute("SELECT * FROM office_cc_statements WHERE id=? AND org_id=? AND deleted_at IS NULL", (sid, oid)).fetchone()
    if r is None:
        raise Denied(404)
    return oc_dec_fields(c, oid, "office_cc_statements", r)


def cc_stmt(c, oid, sid, uid, every):
    """The statement of a card the person may work on (404 else; the card itself may be out of the list for the bookkeeping)."""
    s = cc_stmt_row(c, oid, sid)
    r = c.execute("SELECT holder_id, deleted_at FROM office_cc_cards WHERE id=? AND org_id=?", (s["card_id"], oid)).fetchone()
    if r is None or (not every and (r["holder_id"] != uid or r["deleted_at"])):
        raise Denied(404)
    return s


def cc_lines(c, oid, sid):
    """The positions of statement sid, decrypted, amounts as Decimal."""
    out = []
    for r in c.execute("SELECT * FROM office_cc_lines WHERE org_id=? AND statement_id=? ORDER BY sort, id", (oid, sid)).fetchall():
        x = oc_dec_fields(c, oid, "office_cc_lines", r)
        x["amount"] = money(dec(x["amount"], "0"))
        x["orig_amount"] = money(dec(x["orig_amount"])) if x["orig_amount"] else None
        out.append(x)
    return out


def cc_bank_of(c, oid, sid):
    """The bank booking matched with statement sid (bank.py kind card) or None."""
    r = c.execute("SELECT * FROM office_bank_tx WHERE org_id=? AND match_kind='card' AND match_id=? AND deleted_at IS NULL LIMIT 1", (oid, sid)).fetchone()
    return _tx_dec(c, oid, r) if r else None


def cc_sum(lines):
    return sum((x["amount"] for x in lines), money(dec(0)))


def _stmt_public(c, oid, s, lines=None):
    lines = cc_lines(c, oid, s["id"]) if lines is None else lines
    tot, sm = money(dec(s["total"], "0")), cc_sum(lines)
    t = cc_bank_of(c, oid, s["id"])
    return {"id": s["id"], "card_id": s["card_id"], "month": s["month"], "day": s["day"], "total": dstr(tot), "sum": dstr(sm), "diff": dstr(sm - tot),
            "currency": s["currency"], "state": s["state"], "reader": s["reader"], "node_id": s["node_id"], "locked": pl_is_locked(c, oid, s["day"]) if s["day"] else False,
            "lines": len(lines), "open": sum(1 for x in lines if x["state"] == "open"),
            "private": dstr(sum((x["amount"] for x in lines if x["state"] == "private"), money(dec(0)))),
            "bank": {"id": t["id"], "day": t["day"], "amount": dstr(t["amount"])} if t else None}


@app.get("/api/office/cards/<int:cid>/statements")
def cc_stmts(cid):
    """{items: [statement ...]} newest first."""
    c, uid, oid, every = cc_ctx()
    cc_card(c, oid, cid, uid, every)
    rows = c.execute("SELECT * FROM office_cc_statements WHERE org_id=? AND card_id=? AND deleted_at IS NULL ORDER BY month DESC, id DESC", (oid, cid)).fetchall()
    return jsonify(items=[_stmt_public(c, oid, oc_dec_fields(c, oid, "office_cc_statements", r)) for r in rows])


def _line_insert(c, oid, sid, n, x, state=None):
    row = {"org_id": oid, "statement_id": sid, "sort": n, "day": x["day"], "booked": x.get("booked"), "merchant": x["merchant"], "amount": dstr(x["amount"]),
           "orig_amount": dstr(x["orig_amount"]) if x.get("orig_amount") is not None else "", "orig_currency": x.get("orig_currency") or "", "kind": x["kind"],
           "state": state or ("noreceipt" if x["kind"] == "fee" else "open")}  # fees and interest need no receipt: the statement is the proof
    row = oc_enc_fields(c, oid, "office_cc_lines", row)
    return insert_id(c, f"INSERT INTO office_cc_lines({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))


@app.post("/api/office/cards/<int:cid>/statements")
def cc_upload(cid):
    """Multipart file (the statement as PDF), month? (YYYY-MM, default the statement's) -> 201 {statement, read: true | false,
    digits_differ}. The file becomes a document of the office's documents space, its positions wait for a person's
    confirmation (read false: nothing could be read, the positions are typed in). One statement per card and month (409)."""
    c, uid, oid, every = cc_ctx()
    card = cc_card(c, oid, cid, uid, every)
    f = request.files.get("file")
    if f is None:
        raise BadInput(tr("No file"))
    data = h6d_read(f)
    if len(data) > CC_FILE_MAX or data[:5] != b"%PDF-":
        raise BadInput(tr("Please upload the statement as a PDF"))
    r = ccr_read(card["provider"], data)
    mo = (request.form.get("month") or "").strip() or (r["day"] or "")[:7] or local_now().date().isoformat()[:7]
    if not MONTH_RE.match(mo):
        raise BadInput(tr("Invalid value: {0}", "month"))
    day = r["day"] or f"{mo}-01"
    period_need_open(c, oid, day)
    write_lock(c, f"office_cc_{oid}")
    if c.execute("SELECT 1 FROM office_cc_statements WHERE org_id=? AND card_id=? AND month=? AND deleted_at IS NULL LIMIT 1", (oid, cid, mo)).fetchone():
        raise Denied(409, tr("This card already has a statement for this month"))
    ws = bk_ws(c, oid)
    nid = docs_ingest(c, uid, None if ws[0] == "u" else oid, f.filename or "statement.pdf", data, "application/pdf", "upload", dedup=True, info={})
    fs_log_add(c, nid, "upload")
    total = r["total"] if r["total"] is not None else cc_sum(r["lines"])
    row = oc_enc_fields(c, oid, "office_cc_statements", {"org_id": oid, "card_id": cid, "month": mo, "day": day, "total": dstr(total), "currency": _home(c, oid), "node_id": nid,
                                                         "reader": card["provider"] if r["lines"] else "manual", "state": "draft", "created_by": uid, "created_at": iso(now_utc())})
    sid = insert_id(c, f"INSERT INTO office_cc_statements({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    for n, x in enumerate(r["lines"]):
        _line_insert(c, oid, sid, n, x)
    ofx_log(c, oid, "create", target="cards", detail={"statement": sid, "card": cid, "month": mo, "lines": len(r["lines"])})
    bump(c)
    c.commit()
    docs_kick()
    return jsonify(statement=_stmt_public(c, oid, cc_stmt_row(c, oid, sid)), read=bool(r["lines"]), digits_differ=bool(r["last4"] and r["last4"] != card["last4"])), 201


@app.get("/api/office/cards/statements/<int:sid>")
def cc_stmt_get(sid):
    """{statement, lines: [...], card}: the positions, for open ones the best receipt found (cardlines.cl_public)."""
    from .cardlines import cl_view
    c, uid, oid, every = cc_ctx()
    s = cc_stmt(c, oid, sid, uid, every)
    lines = cc_lines(c, oid, sid)
    card = oc_dec_fields(c, oid, "office_cc_cards", c.execute("SELECT * FROM office_cc_cards WHERE id=?", (s["card_id"],)).fetchone())
    return jsonify(statement=_stmt_public(c, oid, s, lines), lines=cl_view(c, oid, uid, s, lines), card=_card_public(c, oid, card), manage=every)


@app.get("/api/office/cards/statements/<int:sid>/file")
def cc_stmt_file(sid):
    """The statement's PDF (for the card's holder too, whoever uploaded it)."""
    c, uid, oid, every = cc_ctx()
    s = cc_stmt(c, oid, sid, uid, every)
    if not s["node_id"]:
        raise Denied(404)
    return Response(fs_read(c, s["node_id"]), mimetype="application/pdf", headers={"Content-Disposition": f'inline; filename="statement-{s["month"]}.pdf"', "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


def cc_writable(c, oid, s):
    """A write on statement s: not in a locked month."""
    period_need_open(c, oid, s["day"])


def _money(v, what):
    a = dec(v if isinstance(v, (str, int, float)) and not isinstance(v, bool) else "NaN", "NaN")
    if a.is_nan() or a.is_infinite() or abs(a) > CC_AMOUNT_MAX:
        raise BadInput(tr("Invalid value: {0}", what))
    return money(a)


@app.patch("/api/office/cards/statements/<int:sid>")
def cc_stmt_patch(sid):
    """{day?, total?}: the head of a draft (the printed total, for the check of the sum)."""
    c, uid, oid, every = cc_ctx()
    s = cc_stmt(c, oid, sid, uid, every)
    cc_writable(c, oid, s)
    if s["state"] != "draft":
        raise Denied(409, tr(CC_CONFIRMED))
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    day, total = s["day"], s["total"]
    if "day" in b:
        day = cl_day(b["day"], "day")
        period_need_open(c, oid, day)
    if "total" in b:
        total = dstr(_money(b["total"], "total"))
    row = oc_enc_fields(c, oid, "office_cc_statements", {"total": total})
    c.execute("UPDATE office_cc_statements SET day=?, total=? WHERE id=? AND org_id=?", (day, row["total"], sid, oid))
    bump(c)
    c.commit()
    return jsonify(_stmt_public(c, oid, cc_stmt_row(c, oid, sid)))


def cl_day(v, what):
    from datetime import date
    if not isinstance(v, str) or not DAY_RE.match(v):
        raise BadInput(tr("Invalid value: {0}", what))
    try:
        date.fromisoformat(v)
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", what)) from None
    return v


@app.post("/api/office/cards/statements/<int:sid>/confirm")
def cc_confirm(sid):
    """{accept_diff?}: the person confirms the positions; from now on they count. 409 when they do not add up to the printed
    total, unless accept_diff (the person has seen the difference)."""
    c, uid, oid, every = cc_ctx()
    s = cc_stmt(c, oid, sid, uid, every)
    cc_writable(c, oid, s)
    if s["state"] != "draft":
        raise Denied(409, tr(CC_CONFIRMED))
    b = body()
    lines = cc_lines(c, oid, sid)
    if not lines:
        raise Denied(409, tr("Enter the positions first"))
    if cc_sum(lines) != money(dec(s["total"], "0")) and not (isinstance(b, dict) and b.get("accept_diff") is True):
        raise Denied(409, tr("The positions do not add up to the total of the statement"))
    c.execute("UPDATE office_cc_statements SET state='confirmed', confirmed_by=?, confirmed_at=? WHERE id=? AND org_id=?", (uid, iso(now_utc()), sid, oid))
    ofx_log(c, oid, "update", target="cards", detail={"statement": sid, "confirmed": True})
    bump(c)
    c.commit()
    return jsonify(_stmt_public(c, oid, cc_stmt_row(c, oid, sid)))


def _untouched(c, oid, sid):
    """Nothing hangs on the statement yet: no bank booking, no receipt matched (409 else)."""
    if cc_bank_of(c, oid, sid):
        raise Denied(409, tr("A bank booking is matched with this statement; undo that first"))
    if c.execute("SELECT 1 FROM office_cc_lines WHERE org_id=? AND statement_id=? AND state='matched' LIMIT 1", (oid, sid)).fetchone():
        raise Denied(409, tr("Receipts are matched with this statement; undo that first"))


@app.post("/api/office/cards/statements/<int:sid>/reopen")
def cc_reopen(sid):
    """Takes the confirmation back (the undo of confirm) while nothing hangs on the statement."""
    c, uid, oid, every = cc_ctx()
    s = cc_stmt(c, oid, sid, uid, every)
    cc_writable(c, oid, s)
    _untouched(c, oid, sid)
    c.execute("UPDATE office_cc_statements SET state='draft', confirmed_by=NULL, confirmed_at=NULL WHERE id=? AND org_id=?", (sid, oid))
    bump(c)
    c.commit()
    return jsonify(_stmt_public(c, oid, cc_stmt_row(c, oid, sid)))


@app.delete("/api/office/cards/statements/<int:sid>")
def cc_stmt_del(sid):
    """Takes a statement back while nothing hangs on it (POST .../restore brings it back); its document stays."""
    c, uid, oid, every = cc_ctx()
    s = cc_stmt(c, oid, sid, uid, every)
    cc_writable(c, oid, s)
    _untouched(c, oid, sid)
    c.execute("UPDATE office_cc_statements SET deleted_at=? WHERE id=? AND org_id=?", (iso(now_utc()), sid, oid))
    ofx_log(c, oid, "delete", target="cards", detail={"statement": sid})
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.post("/api/office/cards/statements/<int:sid>/restore")
def cc_stmt_restore(sid):
    c, uid, oid, every = cc_ctx()
    r = c.execute("SELECT * FROM office_cc_statements WHERE id=? AND org_id=? AND deleted_at IS NOT NULL", (sid, oid)).fetchone()
    if r is None:
        raise Denied(404)
    cc_card(c, oid, r["card_id"], uid, every)
    write_lock(c, f"office_cc_{oid}")
    if c.execute("SELECT 1 FROM office_cc_statements WHERE org_id=? AND card_id=? AND month=? AND deleted_at IS NULL LIMIT 1", (oid, r["card_id"], r["month"])).fetchone():
        raise Denied(409, tr("This card already has a statement for this month"))
    c.execute("UPDATE office_cc_statements SET deleted_at=NULL WHERE id=? AND org_id=?", (sid, oid))
    bump(c)
    c.commit()
    return jsonify(_stmt_public(c, oid, cc_stmt_row(c, oid, sid)))


def cc_stmt_label(c, oid, sid):
    """'2026-10 ·· 1234': a statement as the bank list names it ('' when it is gone)."""
    r = c.execute("SELECT s.month, k.last4 FROM office_cc_statements s JOIN office_cc_cards k ON k.id=s.card_id WHERE s.id=? AND s.org_id=?", (sid, oid)).fetchone()
    if r is None:
        return ""
    return f"{r['month']} ·· {oc_dec_fields(c, oid, 'office_cc_cards', r)['last4']}"


def cc_bank_open(c, oid, t, q=""):
    """The confirmed statements without their bank booking as candidates of booking t (bank.py), the fitting total first."""
    from .bank import _norm
    out = []
    for r in c.execute("SELECT s.* FROM office_cc_statements s WHERE s.org_id=? AND s.deleted_at IS NULL AND s.state='confirmed' AND NOT EXISTS "
                       "(SELECT 1 FROM office_bank_tx b WHERE b.org_id=s.org_id AND b.match_kind='card' AND b.match_id=s.id AND b.deleted_at IS NULL) ORDER BY s.month DESC", (oid,)).fetchall():
        s = oc_dec_fields(c, oid, "office_cc_statements", r)
        tot, lbl = money(dec(s["total"], "0")), cc_stmt_label(c, oid, s["id"])
        if q and q not in _norm(f"{lbl} {dstr(tot)}"):
            continue
        out.append(((-t["amount"]) != tot, {"kind": "card", "id": s["id"], "label": lbl, "amount": dstr(tot), "date": s["day"]}))
    out.sort(key=lambda x: x[0])
    return [x[1] for x in out[:10]]


def cc_bank_check(c, oid, t, sid, accept_diff):
    """Booking t (money paid out, not matched) may become statement sid's total: a confirmed statement of the area without a
    booking, and the sums agree (409 else; accept_diff: the person has seen the difference)."""
    write_lock(c, f"office_cc_{oid}")
    s = cc_stmt_row(c, oid, sid)
    if s["state"] != "confirmed":
        raise Denied(409, tr(CC_DRAFT_ONLY))
    if t["amount"] >= 0:
        raise Denied(409, tr("Only money paid out can be a card statement"))
    if cc_bank_of(c, oid, sid):
        raise Denied(409, tr("This statement is matched with another booking"))
    if -t["amount"] != money(dec(s["total"], "0")) and not accept_diff:
        raise Denied(409, tr("The booking does not match the total of the statement"))


@app.get("/api/office/cards/statements/<int:sid>/bank")
def cc_bank_candidates(sid):
    """{items: [{id, day, amount, counterpart, purpose, fits}]}: the open bookings out of the business account that can be this
    statement's total, the fitting amount first. The match itself: POST /api/office/bank/tx/<id>/match {kind: card, id}."""
    from .bank import BNK_LIST_MAX
    c, _uid, oid = office_ctx_admin()
    s = cc_stmt_row(c, oid, sid)
    tot = money(dec(s["total"], "0"))
    out = []
    for r in c.execute(f"SELECT * FROM office_bank_tx WHERE org_id=? AND deleted_at IS NULL AND match_kind IS NULL ORDER BY day DESC, id DESC LIMIT {BNK_LIST_MAX}", (oid,)).fetchall():
        t = _tx_dec(c, oid, r)
        if t["amount"] < 0:
            out.append({"id": t["id"], "day": t["day"], "amount": dstr(t["amount"]), "counterpart": t["counterpart"] or "", "purpose": t["purpose"] or "", "fits": -t["amount"] == tot})
    out.sort(key=lambda x: (not x["fits"], x["day"] < s["day"], x["day"]))
    return jsonify(items=out[:30], total=dstr(tot))


from . import cardlines as _cl  # noqa: E402,F401  the routes of the positions
