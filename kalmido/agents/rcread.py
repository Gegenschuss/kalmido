"""2.299.0 E (#3194): a connected agent reads a receipt (kind receipt_read, a request of agents/asstprop.py).

Kalmido calls no model and sends nothing out. A person taps "Read with an agent" on a document / receipt they may change;
the chosen agent (one of the person's office area with the receipts right and both office switches, office/agentdocs.py,
the file shared with it, files/store.py fs_role) gets the event job_request with what GET /api/v1/documents/<id> shows
it, the address of the file itself (content_url: API v1 with files:read, the agent reads the image / PDF where it runs,
e.g. with a local model), the categories in use and -- only for an agent whose office groups give it the bank and a
person who manages the bank -- a few open bank bookings with the receipt's amount.
It answers with the values it read (rcr_validate: types and lengths checked, unknown fields 400). The document sheet and
the receipt sheet of the bookkeeping show them as "Read by the agent (<name>)" with Take over / Discard (the proposal's
apply / discard). Taking over sets as the person, in one undo step, what the recognition's Take over sets (amount = gross,
VAT rate, sender) plus the document date and the category, and keeps the read values as the document's recognised values
(the invoice number, the VAT id and the mandatory checks follow them). Positions and the account are only shown (a
receipt has no field for them); a bank booking is only a suggestion the person matches in the bank (its own route).
The agent never takes anything over."""
import json
import re
from datetime import date, timedelta
from decimal import Decimal

from ..core.i18n import tr
from ..core.access import Denied
from ..core.db import local_now
from ..core.errors import BadInput
from ..core.pg import system_ctx
from ..collab.comments import user_names
from ..files.store import fs_log_add, need_node
from ..office.agentdocs import ofa_agent_on
from ..office.bank import _tx_dec
from ..office.calc import dec, dstr
from ..office.model import office_on, office_role
from ..office.periodlock import pl_receipt_need_open, pl_ws_office
from ..office.rights import ofr_allows, ofr_groups_of
from ..docs import store as S
from ..docs.dups import dup_on_done
from ..docs.web import doc_update
from ..receipts.extracted import _differs, rx_sender_find
from ..receipts.rchecks import _text as rck_text
from ..docs.rcheck import rck_check
from ..receipts.suggest import RC_AMOUNT_MAX, RC_CAT_MAX, RC_VAT, rc_categories, rc_currency_clean, rc_set
from ..agents.core import agent_row
from ..agents.proposals import _p_date, _p_keys, _p_str

RCR_KEYS = ("supplier", "vat_id", "tax_no", "invoice_no", "date", "net", "vat", "gross", "vat_pct", "vat_rates", "currency",
            "positions", "category", "account", "bank_tx")
RCR_FIELDS = ("amount", "vat_pct", "sender", "date", "category")  # what Take over may set
RCR_EXTRACTED = ("supplier", "vat_id", "tax_no", "invoice_no", "vat_pct", "vat_rates", "net", "vat", "gross", "currency")
RCR_NAME_MAX = 200
RCR_NO_MAX = 60
RCR_POS_MAX = 100
RCR_POS_TEXT_MAX = 300
RCR_RATES_MAX = 5
RCR_CATS_MAX = 50
RCR_BANK_MAX = 10           # open bank bookings offered to the agent
RCR_BANK_DAYS = 60          # around the document date (today without one)
RCR_SCAN = 20               # newest receipt_read jobs of a person looked at for one document
RCR_LIMITS = {"positions_max": RCR_POS_MAX, "position_text_max": RCR_POS_TEXT_MAX, "name_max": RCR_NAME_MAX,
              "invoice_no_max": RCR_NO_MAX, "vat_rates_max": RCR_RATES_MAX}
_AMT = re.compile(r"-?\d{1,12}(\.\d{1,2})?")
_PCT = re.compile(r"\d{1,2}(\.\d{1,2})?")
_QTY = re.compile(r"\d{1,7}(\.\d{1,3})?")
_VATID = re.compile(r"[A-Z]{2}[0-9A-Z+*.]{2,13}")
_TAXNO = re.compile(r"[0-9][0-9 /]{4,19}")
_ACCT = re.compile(r"[0-9A-Za-z][0-9A-Za-z .\-/]{0,29}")


def _bad(what):
    return BadInput(tr("Invalid value: {0}", what))


def _amount(v, what, neg=False):
    """'12.34' from a decimal text or a number (at most two decimals, at most 100 000 000; negative only with neg)."""
    if v in (None, ""):
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise _bad(what)
    t = str(v).strip().replace(",", ".")
    if not _AMT.fullmatch(t) or (t.startswith("-") and not neg):
        raise _bad(what)
    d = Decimal(t)
    if abs(d) > RC_AMOUNT_MAX:
        raise _bad(what)
    return format(d.quantize(Decimal("0.01")), "f")


def _pct(v, what):
    """A VAT rate '19' | '7' | '0' | '5.5' (0 to 30)."""
    if v in (None, ""):
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise _bad(what)
    t = str(v).strip().replace(",", ".").rstrip("%").strip()
    if not _PCT.fullmatch(t) or Decimal(t) > 30:
        raise _bad(what)
    s = format(Decimal(t).normalize(), "f")
    return "0" if Decimal(s) == 0 else s


def _line(v, what, mx, required=False):
    return _p_str(v, what, mx, required) or None


def _list(v, what, mx):
    if v in (None, ""):
        return []
    if not isinstance(v, list) or len(v) > mx:
        raise _bad(what)
    return v


def rcr_validate(b, inp):
    """The agent's answer {supplier?, vat_id?, tax_no?, invoice_no?, date?, net?, vat?, gross?, vat_pct?, vat_rates?,
    currency?, positions?, category?, account?, bank_tx?} -> the normalised values (at least one). Unknown fields 400; a
    bank booking only one of input.bank. Nothing is judged here (sums that do not add up are a hint of the checks)."""
    _p_keys(b, "", ("kind", "summary", *RCR_KEYS))
    out = {"supplier": _line(b.get("supplier"), "supplier", RCR_NAME_MAX), "invoice_no": _line(b.get("invoice_no"), "invoice_no", RCR_NO_MAX)}
    for k, rx in (("vat_id", _VATID), ("tax_no", _TAXNO)):
        v = b.get(k)
        if v in (None, ""):
            out[k] = None
            continue
        if not isinstance(v, str) or len(v) > 40:
            raise _bad(k)
        v = re.sub(r"\s+", "", v).upper() if k == "vat_id" else " ".join(v.split())
        if not rx.fullmatch(v):
            raise _bad(k)
        out[k] = v
    out["date"] = _p_date(b.get("date"), "date")
    if out["date"] and not ("2000-01-01" <= out["date"] <= (local_now().date() + timedelta(days=366)).isoformat()):
        raise _bad("date")
    for k in ("net", "vat", "gross"):
        out[k] = _amount(b.get(k), k)
    if out["gross"] is not None and Decimal(out["gross"]) == 0:
        raise _bad("gross")
    out["vat_pct"] = _pct(b.get("vat_pct"), "vat_pct")
    rates = []
    for i, r in enumerate(_list(b.get("vat_rates"), "vat_rates", RCR_RATES_MAX)):
        _p_keys(r, f"vat_rates[{i}]", ("pct", "net", "vat"))
        p = _pct(r.get("pct"), f"vat_rates[{i}].pct")
        if p is None:
            raise _bad(f"vat_rates[{i}].pct")
        rates.append({"pct": p, "net": _amount(r.get("net"), f"vat_rates[{i}].net"), "vat": _amount(r.get("vat"), f"vat_rates[{i}].vat")})
    out["vat_rates"] = rates
    try:
        out["currency"] = rc_currency_clean(b.get("currency")) or None
    except BadInput:
        raise _bad("currency") from None
    pos = []
    for i, p in enumerate(_list(b.get("positions"), "positions", RCR_POS_MAX)):
        _p_keys(p, f"positions[{i}]", ("text", "qty", "net", "vat_pct"))
        q = p.get("qty")
        if q not in (None, ""):
            if isinstance(q, bool) or not isinstance(q, (int, float, str)) or not _QTY.fullmatch(str(q).strip().replace(",", ".")):
                raise _bad(f"positions[{i}].qty")
            q = format(Decimal(str(q).strip().replace(",", ".")).normalize(), "f")
        pos.append({"text": _p_str(p.get("text"), f"positions[{i}].text", RCR_POS_TEXT_MAX, True), "qty": q if q not in (None, "") else None,
                    "net": _amount(p.get("net"), f"positions[{i}].net", neg=True), "vat_pct": _pct(p.get("vat_pct"), f"positions[{i}].vat_pct")})
    out["positions"] = pos
    out["category"] = _line(b.get("category"), "category", RC_CAT_MAX)
    a = b.get("account")
    if a not in (None, "") and (not isinstance(a, str) or not _ACCT.fullmatch(a.strip())):
        raise _bad("account")
    out["account"] = a.strip() if a not in (None, "") else None
    t = b.get("bank_tx")
    if t is not None:
        if isinstance(t, bool) or not isinstance(t, int) or t not in {x.get("id") for x in inp.get("bank") or []}:
            raise _bad("bank_tx")
    out["bank_tx"] = t
    if not any(out[k] not in (None, [], "") for k in RCR_KEYS):
        raise BadInput(tr("Read at least one value of the receipt"))
    return out


# ---------------------------------------------------------------- the input
def _rc_row(c, nid):
    return c.execute("SELECT * FROM rc_receipts WHERE node_id=?", (nid,)).fetchone()


def _bank_on(c, uid, aid, oid):
    """Bank bookings for this request: the agent's office groups give it the bank (never only the old drafts switch) and
    the person manages the bank of the area (an admin, as every bank route)."""
    with system_ctx(c):  # the agent's settings row (structure)
        a = agent_row(c, aid)
    if not a or not oid or not ofr_groups_of(c, oid, aid) or not ofa_agent_on(c, a, oid, "bank", "view"):
        return False
    return office_role(c, uid, oid) == "admin" and office_on(c, uid) and ofr_allows(c, uid, oid, "bank", "view")


def _bank_rows(c, oid, amount, day):
    """Open bookings paid out with exactly this amount, newest first, around day."""
    try:
        want = -abs(dec(amount))
    except Exception:  # noqa: BLE001  an amount of an import may be any text
        return []
    if not want:
        return []
    try:
        d0 = date.fromisoformat((day or "")[:10])
    except ValueError:
        d0 = local_now().date()
    rows = c.execute("SELECT * FROM office_bank_tx WHERE org_id=? AND deleted_at IS NULL AND match_kind IS NULL AND day BETWEEN ? AND ? "
                     "ORDER BY day DESC, id DESC LIMIT 500",
                     (oid, (d0 - timedelta(days=RCR_BANK_DAYS)).isoformat(), (d0 + timedelta(days=RCR_BANK_DAYS)).isoformat())).fetchall()
    out = []
    for r in rows:
        t = _tx_dec(c, oid, r)
        if t["amount"] != want:
            continue
        out.append({"id": t["id"], "day": t["day"], "amount": dstr(t["amount"]), "currency": t["currency"],
                    "counterpart": (t["counterpart"] or "")[:100], "purpose": (t["purpose"] or "")[:140]})
        if len(out) >= RCR_BANK_MAX:
            break
    return out


def rcr_input(c, uid, aid, oid, n, inp):
    """inp = asstprop._doc_input (what the documents API shows the agent) + the file's address, the receipt as it is, the
    categories in use and (see _bank_on) open bank bookings."""
    m = S.meta_row(c, n["id"])
    r = _rc_row(c, n["id"])
    d = inp["document"]
    d.update(mime=n["mime"] or "", size=n["size"], content_url=f"/api/v1/files/{n['id']}/content")
    d["receipt"] = {"is_receipt": bool(r), "category": (r["category"] or None) if r else None, "vat_pct": r["vat_pct"] if r else None}
    own = pl_ws_office(c, m["ws"]) == oid  # 2.299.0 (#3194 review): categories / bank only of the office the document lies in
    inp["categories"] = rc_categories(c, m["ws"])[:RCR_CATS_MAX] if own else []
    if own and _bank_on(c, uid, aid, oid):
        x = d.get("extracted") or {}
        inp["bank"] = _bank_rows(c, oid, x.get("gross") or d.get("amount"), d.get("date"))
    return inp


# ---------------------------------------------------------------- what Take over would change, the view
def _snap(c, nid):
    """The values Take over touches, as they are now (the undo record keeps two of these)."""
    m = S.meta_row(c, nid)
    r = _rc_row(c, nid)
    return {"amount": S.doc_open(c, m["ws"], "doc_meta.amount", m["amount"]) or "", "currency": m["currency"] or "", "sender": m["sender_id"],
            "date": m["doc_date"] or "", "vat_pct": r["vat_pct"] if r else None, "category": (r["category"] or "") if r else "",
            "is_receipt": bool(r), "extracted": S.meta_json(c, m, "extracted", {})}


def _new(c, m, p):
    """The fields Take over would change (amount, vat_pct, sender, date, category)."""
    r = _rc_row(c, m["node_id"])
    new = []
    amount = S.doc_open(c, m["ws"], "doc_meta.amount", m["amount"]) or ""
    if p.get("gross") and (not amount or _differs(amount, p["gross"])):
        new.append("amount")
    if p.get("vat_pct") in RC_VAT and p["vat_pct"] != (r["vat_pct"] if r else None):
        new.append("vat_pct")
    if p.get("supplier") or p.get("vat_id"):
        sid, name = rx_sender_find(c, m["ws"], p, m["node_id"])
        if (sid and sid != m["sender_id"]) or (not sid and name):
            new.append("sender")
    if p.get("date") and p["date"] != (m["doc_date"] or "")[:10]:
        new.append("date")
    if p.get("category") and p["category"] != ((r["category"] or "") if r else ""):
        new.append("category")
    return new


def rcr_checks(p):
    """The mandatory checks of part D over the read values (rcheck.rck_check)."""
    try:  # 2.299.0 (#3194 review): translated like the document's own hints (receipts/rchecks.py)
        items = rck_check({**{k: p.get(k) for k in RCR_EXTRACTED}, "date": p.get("date"), "amount": p.get("gross"), "sender": p.get("supplier")})
        return [{"code": x["code"], "level": x["level"], "text": rck_text(x)} for x in items]
    except Exception:  # noqa: BLE001  a hint must never break the sheet
        return []


def rcr_bank_view(c, uid, oid, tid, nid):
    """The booking the agent suggested, as the person sees it now (None: not theirs to see / gone)."""
    if not tid or not oid or office_role(c, uid, oid) != "admin" or not office_on(c, uid) or not ofr_allows(c, uid, oid, "bank", "view"):
        return None
    r = c.execute("SELECT * FROM office_bank_tx WHERE id=? AND org_id=? AND deleted_at IS NULL", (tid, oid)).fetchone()
    if r is None:
        return None
    t = _tx_dec(c, oid, r)
    return {"id": t["id"], "day": t["day"], "amount": dstr(t["amount"]), "currency": t["currency"], "counterpart": t["counterpart"] or "",
            "matched": bool(t["match_kind"]), "this": t["match_kind"] == "receipt" and t["match_id"] == nid}


def rcr_target(c, j, n, m, uid):
    """For the card and the document: the document, what Take over would change, the checks, the bank booking."""
    from .asstprop import _doc_area
    p = json.loads(j["proposal"] or "null") or {}
    out = {"doc_id": n["id"], "name": n["name"], "editable": n["role"] not in (None, "view"), "new": _new(c, m, p) if p else [],
           "checks": rcr_checks(p) if p else []}
    if p.get("bank_tx"):
        out["bank"] = rcr_bank_view(c, uid, _doc_area(c, uid, n), p["bank_tx"], n["id"])
    return out


def rcr_doc_view(c, m, uid):
    """doc_json (people): the newest open receipt_read request of uid for this document -- {job, state: requested | ready,
    agent, values, new, checks, bank?} -- or None."""
    rows = c.execute("SELECT * FROM agent_jobs WHERE user_id=? AND kind='receipt_read' AND prop_state IN ('requested','ready') "
                     "AND state IN ('running','waiting') ORDER BY id DESC LIMIT ?", (uid, RCR_SCAN)).fetchall()
    for j in rows:
        if (json.loads(j["input"] or "{}").get("document") or {}).get("id") != m["node_id"]:
            continue
        try:
            n = need_node(c, m["node_id"])
        except Denied:
            return None
        out = {"job": j["id"], "state": j["prop_state"], "agent": {"id": j["agent_id"], "name": user_names(c, [j["agent_id"]]).get(j["agent_id"], "")}}
        if j["prop_state"] == "ready":
            p = json.loads(j["proposal"] or "null") or {}
            out["values"] = {k: p.get(k) for k in RCR_KEYS}
            out.update({k: v for k, v in rcr_target(c, j, n, m, uid).items() if k in ("new", "checks", "bank")})
        return out
    return None


# ---------------------------------------------------------------- take over / undo (as the person)
def _fail(e):
    """doc_update answers an error response: as an exception of the proposal's apply (rolled back there)."""
    try:
        msg, code = e[0].get_json().get("error"), e[1]
    except (AttributeError, IndexError, TypeError):
        msg, code = None, 400
    if code == 400:
        raise BadInput(msg or tr("Invalid data"))
    raise Denied(code, msg)


def _set(c, n, uid, want, cur):
    """Put the values of snapshot want on document n (cur = as it is now)."""
    nid = n["id"]
    m = S.meta_row(c, nid)
    pl_receipt_need_open(c, nid, *[x for x in (want["date"],) if x], becoming=want["is_receipt"])  # a locked month: 409, nothing changes
    d = {k: want[k] for k in ("amount", "currency", "sender", "date") if want[k] != cur[k]}
    e = doc_update(c, nid, d, uid) if d else None
    if e:
        _fail(e)
    if (want["vat_pct"], want["category"], want["is_receipt"]) != (cur["vat_pct"], cur["category"], cur["is_receipt"]):
        r = _rc_row(c, nid)
        rc_set(c, n, m["ws"], r["list_id"] if r else None, want["category"], uid, vat=want["vat_pct"], keep=want["is_receipt"])
    if want["extracted"] != cur["extracted"]:
        S.meta_set_json(c, nid, m["ws"], "extracted", want["extracted"])


def rcr_run(c, j, n, uid, ed):
    """Take it over: the chosen fields (edits {"0": {fields: [...]}}, default all) + the read values as the document's
    recognised values. Returns the undo record {doc, before, after}."""
    p = json.loads(j["proposal"])
    e = (ed or {}).get("0") or {}
    _p_keys(e, "edits.0", ("fields",))
    want = e.get("fields") or list(RCR_FIELDS)
    if not isinstance(want, list) or not all(isinstance(x, str) for x in want) or set(want) - set(RCR_FIELDS):
        raise _bad("fields")
    nid = n["id"]
    m = S.meta_row(c, nid)
    before = _snap(c, nid)
    after = json.loads(json.dumps(before))
    if "amount" in want and p.get("gross"):
        after["amount"] = p["gross"]
        if p.get("currency"):
            after["currency"] = p["currency"]
    if "date" in want and p.get("date"):
        after["date"] = p["date"]
    if "sender" in want and (p.get("supplier") or p.get("vat_id")):
        sid, name = rx_sender_find(c, m["ws"], p, nid)
        if sid or name:
            after["sender"] = sid or name
    if "vat_pct" in want and p.get("vat_pct") in RC_VAT:
        after["vat_pct"], after["is_receipt"] = p["vat_pct"], True
    if "category" in want and p.get("category"):
        after["category"], after["is_receipt"] = p["category"], True
    det = {k: v for k, v in before["extracted"].items() if k != "_hidden"}
    det.update({k: p[k] for k in RCR_EXTRACTED if p.get(k) not in (None, "", [])})
    det["_agent"] = {"job": j["id"], "agent": j["agent_id"]}
    after["extracted"] = det
    _set(c, n, uid, after, before)
    after = _snap(c, nid)  # a new sender is an id now: the undo compares with what is there
    dup_on_done(c, nid, False)  # amount / sender changed: look for a duplicate again (as rx_post)
    fs_log_add(c, nid, "edit")
    return {"doc": nid, "before": before, "after": after}


def rcr_undo(c, n, uid, o, back=True):
    """Undo (back) / redo: the values before come back unless someone changed one of them since (then False)."""
    want, now = (o["before"], o["after"]) if back else (o["after"], o["before"])
    cur = _snap(c, n["id"])
    # 2.299.0 (#3194 review): + the recognised values (a new recognition run or a take-over by hand since stays)
    if any(cur.get(k) != now.get(k) for k in ("amount", "currency", "sender", "date", "vat_pct", "category", "extracted")):
        return False
    _set(c, n, uid, want, cur)
    dup_on_done(c, n["id"], False)
    fs_log_add(c, n["id"], "edit")
    return True
