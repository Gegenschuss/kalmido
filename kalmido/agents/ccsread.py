"""2.469.0 (#3749): a connected agent reads a credit card statement (kind card_statement_read, a request of agents/asstprop.py).

The fallback of office/ccread.py for a layout no reader knows. Kalmido calls no model and sends nothing out. A person with the
receipts right who works on the statement (office/cards.py cc_stmt) taps "Read with an agent" on a draft without positions; the
chosen agent (as receipt_read: the office switches, the receipts right, the PDF shared with it) gets the event job_request with
what the documents API shows it of the PDF, the file's address and the statement's month, total and currency. It answers with
the positions it read (ccs_validate: values only, amounts, days and lengths checked strictly, unknown fields 400). Nothing is
stored in the statement before a person takes them over: then they become positions of the draft as a reader's would (one undo
step), and count only once the person confirms them on the statement (POST .../confirm with its sum check). Everything an agent
sends is shown escaped as plain text. The agent never takes anything over and sees nothing of the cards themselves."""
import json
from datetime import timedelta
from decimal import Decimal

from flask import g

from ..core.access import Denied, live_sql
from ..core.db import local_now
from ..core.errors import BadInput
from ..core.i18n import N_, tr
from ..core.orgcrypt import oc_enc_fields
from ..core.pg import system_ctx, write_lock
from ..office.agentdocs import ofa_area
from ..office.calc import dec, dstr, money
from ..office.cards import CC_CONFIRMED, CC_KINDS, _line_insert, cc_lines, cc_sees_all, cc_stmt, cc_writable
from ..office.ccread import CCR_LINES_MAX, CCR_TEXT_MAX
from ..office.ledger import ofx_log
from ..office.model import office_org
from ..office.rights import NO_RIGHT, ofr_allows
from ..receipts.suggest import rc_currency_clean
from ..agents.core import agent_row
from ..agents.proposals import _p_date, _p_keys, _p_str
from ..agents.rcread import _amount, _bad

CCS_LINE_KEYS = ("day", "booked", "merchant", "amount", "orig_amount", "orig_currency", "kind")
CCS_LIMITS = {"card_lines_max": CCR_LINES_MAX, "card_merchant_max": CCR_TEXT_MAX}
CCS_HAS_LINES = N_("This statement already has positions")


def _day(v, what, required=False):
    d = _p_date(v, what)
    if d is None:
        if required:
            raise _bad(what)
        return None
    if not "2000-01-01" <= d <= (local_now().date() + timedelta(days=366)).isoformat():
        raise _bad(what)
    return d


def _line(i, x):
    w = f"lines[{i}]"
    _p_keys(x, w, CCS_LINE_KEYS)
    amount = _amount(x.get("amount"), f"{w}.amount", neg=True)
    if amount is None or Decimal(amount) == 0:
        raise _bad(f"{w}.amount")
    orig = _amount(x.get("orig_amount"), f"{w}.orig_amount", neg=True)
    try:
        cur = rc_currency_clean(x.get("orig_currency")) or None
    except BadInput:
        raise _bad(f"{w}.orig_currency") from None
    if (orig is None) != (cur is None):  # a foreign amount without its currency says nothing
        raise _bad(f"{w}.orig_currency")
    kind = x.get("kind") or ("credit" if Decimal(amount) < 0 else "purchase")
    if kind not in CC_KINDS:
        raise _bad(f"{w}.kind")
    return {"day": _day(x.get("day"), f"{w}.day", True), "booked": _day(x.get("booked"), f"{w}.booked"),
            "merchant": _p_str(x.get("merchant"), f"{w}.merchant", CCR_TEXT_MAX, True), "amount": amount,
            "orig_amount": orig, "orig_currency": cur, "kind": kind}


def ccs_validate(b, inp):
    """The agent's answer {total?, lines: [{day, booked?, merchant, amount, orig_amount?, orig_currency?, kind?}]} -> the
    normalised values. + = charged, - = money back. Unknown fields 400. Whether they add up is the person's check."""
    _p_keys(b, "", ("kind", "summary", "total", "lines"))
    rows = b.get("lines")
    if not isinstance(rows, list) or not rows:
        raise BadInput(tr("Read at least one position of the statement"))
    if len(rows) > CCR_LINES_MAX:
        raise _bad("lines")
    return {"total": _amount(b.get("total"), "total"), "lines": [_line(i, x) for i, x in enumerate(rows)]}


def _lines_n(c, oid, sid):
    return c.execute(f"SELECT COUNT(*) AS n FROM office_cc_lines WHERE org_id=? AND statement_id=? AND {live_sql()}", (oid, sid)).fetchone()["n"]  # 2.1005.0 (#5415): not the trash


def _need_empty_draft(c, oid, s):
    """Asked and taken over only on a draft without positions, in an open month (409 else)."""
    cc_writable(c, oid, s)
    if s["state"] != "draft":
        raise Denied(409, tr(CC_CONFIRMED))
    if _lines_n(c, oid, s["id"]):
        raise Denied(409, tr(CCS_HAS_LINES))


def ccs_ask(c, uid, sid):
    """(oid, statement) a person may ask an agent for: their office area, a statement they work on, the PDF kept."""
    oid = office_org(c, uid, area="receipts")
    s = cc_stmt(c, oid, sid, uid, cc_sees_all(c, uid, oid))
    if not s["node_id"]:
        raise Denied(404)
    _need_empty_draft(c, oid, s)
    return oid, s


def ccs_input(oid, s, n, inp):
    """inp = asstprop._doc_input (what the documents API shows the agent of the PDF) + the file's address and the statement."""
    d = inp["document"]
    d.update(mime=n["mime"] or "", size=n["size"], content_url=f"/api/v1/files/{n['id']}/content")
    inp["statement"] = {"id": s["id"], "month": s["month"], "day": s["day"], "total": s["total"] or None, "currency": s["currency"]}
    return inp


def _target(c, j):
    """(oid, statement) of a job for the signed-in person, asked anew at every step: the office area of the agent, as for
    office_text, the receipts right and the statement itself (a holder: their own card)."""
    uid = g.user["id"]
    with system_ctx(c):  # the agent's settings row (structure)
        a = agent_row(c, j["agent_id"])
    oid = ofa_area(c, a)
    if not ofr_allows(c, uid, oid, "receipts", "edit"):
        raise Denied(403, tr(NO_RIGHT))
    sid = (json.loads(j["input"] or "{}").get("statement") or {}).get("id")
    return oid, cc_stmt(c, oid, sid, uid, cc_sees_all(c, uid, oid))


def _insert(c, oid, s, p):
    ids = []
    for n, x in enumerate(p["lines"]):
        ids.append(_line_insert(c, oid, s["id"], n, {**x, "amount": money(dec(x["amount"])),
                                                     "orig_amount": money(dec(x["orig_amount"])) if x["orig_amount"] else None}))
    return ids


def _set_total(c, oid, sid, total):
    row = oc_enc_fields(c, oid, "office_cc_statements", {"total": total})
    c.execute("UPDATE office_cc_statements SET total=? WHERE id=? AND org_id=?", (row["total"], sid, oid))


def ccs_run(c, j, ed):
    """Take it over as the person: the positions into the empty draft, the total only where the statement has none. Returns
    the undo record {statement, ids, total}: no value of a position (those stay sealed in the statement)."""
    if ed and (not isinstance(ed, dict) or any(ed.values())):
        raise _bad("edits")
    oid, s = _target(c, j)
    write_lock(c, f"office_cc_{oid}")
    oid, s = _target(c, j)  # as it is under the lock
    _need_empty_draft(c, oid, s)
    p = json.loads(j["proposal"])
    cc_writable(c, oid, s, *(x["day"] for x in p["lines"]))
    ids = _insert(c, oid, s, p)
    set_total = bool(p.get("total") and not s["total"])
    if set_total:
        _set_total(c, oid, s["id"], p["total"])
    ofx_log(c, oid, "update", target="cards", detail={"statement": s["id"], "lines": len(ids), "agent_job": j["id"]})
    return {"statement": s["id"], "ids": ids, "total": set_total}


def _same(p, x):
    """A position still as it was taken over?"""
    a = p["orig_amount"]
    return (x["day"], x["merchant"], x["amount"], x["kind"]) == (p["day"], p["merchant"], money(dec(p["amount"])), p["kind"]) \
        and x["orig_amount"] == (money(dec(a)) if a else None) and (x["orig_currency"] or None) == p["orig_currency"]


def ccs_undo(c, j, o, back=True):
    """Undo (back): the positions go again unless the person changed one, added one or confirmed since (then False). Redo:
    they come back into a draft that is empty again."""
    p = json.loads(j["proposal"])
    oid, s = _target(c, j)
    write_lock(c, f"office_cc_{oid}")
    oid, s = _target(c, j)
    if not back:
        _need_empty_draft(c, oid, s)
        cc_writable(c, oid, s, *(x["day"] for x in p["lines"]))
        o["ids"] = _insert(c, oid, s, p)
        if o["total"]:
            _set_total(c, oid, s["id"], p["total"])
        return True
    cc_writable(c, oid, s, *(x["day"] for x in p["lines"]))
    now = cc_lines(c, oid, s["id"])
    if s["state"] != "draft" or [x["id"] for x in now] != o["ids"] or not all(_same(a, x) for a, x in zip(p["lines"], now)):
        return False
    if o["total"] and money(dec(s["total"] or "0")) != money(dec(p["total"])):
        return False
    c.execute("DELETE FROM office_cc_lines WHERE org_id=? AND statement_id=?", (oid, s["id"]))
    if o["total"]:
        _set_total(c, oid, s["id"], "")
    return True


def ccs_target(c, j):
    """For the card: the statement as it is now, the sum of the proposal against the total, whether Take over still works."""
    oid, s = _target(c, j)
    p = json.loads(j["proposal"] or "null") or {}
    total = s["total"] or p.get("total")
    sm = sum((money(dec(x["amount"])) for x in p.get("lines") or []), money(dec(0)))
    try:
        _need_empty_draft(c, oid, s)
        ok = True
    except Denied:
        ok = False
    return {"statement_id": s["id"], "month": s["month"], "currency": s["currency"], "editable": ok, "sum": dstr(sm), "total": total or None,
            "fits": bool(total) and money(dec(total)) == sm}
