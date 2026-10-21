"""2.121.0 A (#2092): what the recognition read off a receipt -- supplier, VAT ids, VAT rate, net / VAT / gross, invoice
number (docs/extract.py ex_details) -- as a SUGGESTION a person takes or drops.

The recognition run (docs/store.py process) keeps it in doc_meta.extracted (JSON, sealed like doc_meta.suggest) for
invoices / receipts only; nothing of it is set on its own. The document sheet and the office's receipt sheet show one line
"Recognised: supplier · no. · net · VAT 19 % · gross" with Take over / Dismiss while a value differs from what is set.
Take over sets the amount (gross), the receipt's VAT rate and the document's sender (an existing sender found by its VAT
id on another document or by its name, else a new one) -- one undo step: the answer carries the values before, "restore"
puts them back. Dismiss hides the line (undo: "show"). People with the right edit on the document only; agents read the
values with the document (API v1) but never take them over."""
import re

from flask import jsonify

from ..core.config import app
from ..core.db import body, bump, db, err
from ..core.i18n import tr
from ..core.access import Denied
from ..accounts.session import me
from ..files.store import fs_log_add
from ..docs import store as S

RX_KEYS = ("supplier", "vat_id", "tax_no", "invoice_no", "vat_pct", "vat_rates", "net", "vat", "gross", "currency")
RX_FIELDS = ("amount", "vat_pct", "sender")      # what Take over may set
RX_SCAN = 100                                    # documents looked at to find a sender by its VAT id
_FORM = re.compile(r"\b(gmbh(\s*&\s*co\.?\s*kg)?|mbh|ug|ag|kg|ohg|gbr|e\.?\s?k\.?|ltd|limited|inc|llc|se|b\.?v\.?|s\.?a\.?)\b\.?", re.I)


def rx_compact(det):
    """The details worth keeping (None values dropped); {} when there is nothing beyond the gross (the amount has it)."""
    if not isinstance(det, dict):
        return {}
    out = {k: det[k] for k in RX_KEYS if det.get(k) not in (None, "", [])}
    return out if set(out) - {"gross", "currency"} else {}


def _rx_norm(name):
    return re.sub(r"[^\w]+", " ", _FORM.sub(" ", str(name or "").lower())).strip()


def rx_sender_find(c, ws, det, nid=None):
    """(sender label id | None, name to create | None): the sender with the same name (also without its legal form: "Muster
    Bau" = "Muster Bau GmbH"), else the one on another document of ws with the same VAT id, else the supplier's name."""
    name = str(det.get("supplier") or "").strip()
    want = _rx_norm(name)
    if name:
        for x in S.labels(c, ws, "sender"):
            if (x["name"] or "").lower() == name.lower() or (want and _rx_norm(x["name"]) == want):
                return x["id"], None
    vid = det.get("vat_id")
    if vid:
        for r in c.execute("SELECT * FROM doc_meta WHERE ws=? AND extracted<>'' AND sender_id IS NOT NULL AND node_id<>? "
                           "ORDER BY updated_at DESC LIMIT ?", (ws, nid or 0, RX_SCAN)):
            if S.meta_json(c, r, "extracted", {}).get("vat_id") == vid and S.label_ok(c, ws, "sender", r["sender_id"]):
                return r["sender_id"], None
    return None, name or None


def _differs(amount, gross):
    """2.121.0 review N1: an amount of an import may be any text ("12,34") -- unreadable counts as different, never a 500."""
    try:
        return abs(float(str(amount).replace(",", ".")) - float(gross)) >= 0.005
    except (TypeError, ValueError):
        return True


def rx_view(c, m, rc_vat=None, is_receipt=False):
    """The suggestion for the client / an agent: the values, 'new' = the fields Take over would change (amount, vat_pct,
    sender; empty = the line stays hidden), 'hidden' = dismissed. None without one."""
    det = S.meta_json(c, m, "extracted", {})
    if not rx_compact(det):
        return None
    ws = m["ws"]
    new = []
    amount = S.doc_open(c, ws, "doc_meta.amount", m["amount"]) or ""
    if det.get("gross") and (not amount or _differs(amount, det["gross"])):
        new.append("amount")
    if det.get("vat_pct") and det["vat_pct"] != rc_vat:
        new.append("vat_pct")
    if det.get("supplier") or det.get("vat_id"):
        sid, name = rx_sender_find(c, ws, det, m["node_id"])
        if (sid and sid != m["sender_id"]) or (not sid and name):
            new.append("sender")
    out = {k: det.get(k) for k in RX_KEYS}
    out["vat_rates"] = det.get("vat_rates") or []
    out.update(new=new, hidden=bool(det.get("_hidden")))
    return out


def _rc_row(c, nid):
    return c.execute("SELECT * FROM rc_receipts WHERE node_id=?", (nid,)).fetchone()


def rx_doc_view(c, m):
    r = _rc_row(c, m["node_id"])
    return rx_view(c, m, r["vat_pct"] if r else None, bool(r))


def _rx_vat(c, node, ws, uid, vat, keep):
    from .suggest import rc_set
    r = _rc_row(c, node["id"])
    rc_set(c, node, ws, r["list_id"] if r else None, (r["category"] or "") if r else "", uid, vat=vat, keep=keep)


@app.post("/api/docs/<int:nid>/extracted")
def rx_post(nid):
    """{do: "apply", fields?: [amount, vat_pct, sender]} takes the recognised values over (the answer's "before" is the undo);
    {do: "restore", before: {..}} puts them back; {do: "dismiss"} hides the suggestion, {do: "show"} shows it again.
    2.146.0 B (#2452): {do: "nodup"} = "no duplicate" (the warning goes, also after a new recognition run), {do: "dup"} its undo.
    People with the right edit on the document (agents 403: they only read the values)."""
    from ..docs.web import _doc, _no_agent, doc_json, doc_update
    c = db()
    _no_agent()
    m, n = _doc(c, nid, write=True)
    uid, ws = me(), m["ws"]
    b = body()
    act = b.get("do")
    det = S.meta_json(c, m, "extracted", {})
    if act not in ("apply", "restore", "dismiss", "show", "nodup", "dup"):
        return err(tr("Invalid value: {0}", "do"))
    if not det and act not in ("nodup", "dup"):
        raise Denied(404)
    before = None
    if act in ("nodup", "dup"):
        c.execute("UPDATE doc_meta SET dup_ok=? WHERE node_id=?", (1 if act == "nodup" else 0, nid))
    elif act in ("dismiss", "show"):
        det = {k: v for k, v in det.items() if k != "_hidden"}
        if act == "dismiss":
            det["_hidden"] = 1
        S.meta_set_json(c, nid, ws, "extracted", det)
    elif act == "apply":
        want = b.get("fields") or list(RX_FIELDS)
        if not isinstance(want, list) or not all(isinstance(x, str) for x in want) or set(want) - set(RX_FIELDS):  # review N2
            return err(tr("Invalid value: {0}", "fields"))
        r = _rc_row(c, nid)
        before = {"amount": S.doc_open(c, ws, "doc_meta.amount", m["amount"]) or "", "currency": m["currency"] or "",
                  "sender": m["sender_id"], "vat_pct": r["vat_pct"] if r else None, "is_receipt": bool(r)}
        d = {}
        if "amount" in want and det.get("gross"):
            d["amount"] = det["gross"]
            if det.get("currency"):
                d["currency"] = det["currency"]
        if "sender" in want:
            sid, name = rx_sender_find(c, ws, det, nid)
            if sid or name:
                d["sender"] = sid or name
        e = doc_update(c, nid, d, uid) if d else None
        if e:
            return e
        if "vat_pct" in want and det.get("vat_pct") in ("19", "7", "0"):
            from ..office.periodlock import pl_receipt_need_open
            pl_receipt_need_open(c, nid, becoming=True)  # 2.148.0 A (#2471)
            _rx_vat(c, n, ws, uid, det["vat_pct"], True)
    else:                                         # restore: the values before a Take over (the undo)
        bf = b.get("before")
        if not isinstance(bf, dict):
            return err(tr("Invalid value: {0}", "before"))
        from ..api.v1 import BadInput
        from .suggest import rc_vat_clean
        try:
            vat = rc_vat_clean(bf.get("vat_pct"))
        except BadInput:
            return err(tr("Invalid value: {0}", "vat_pct"))
        sender = bf.get("sender")
        if sender is not None and (not isinstance(sender, int) or isinstance(sender, bool)):
            return err(tr("Invalid value: {0}", "sender"))
        e = doc_update(c, nid, {"amount": bf.get("amount") or "", "currency": bf.get("currency") or "", "sender": sender}, uid)
        if e:
            return e
        from ..office.periodlock import pl_receipt_need_open
        pl_receipt_need_open(c, nid)  # 2.148.0 A (#2471)
        _rx_vat(c, n, ws, uid, vat, bf.get("is_receipt") is True)
    if act in ("apply", "restore"):  # 2.146.0 B (#2452): amount / sender changed: look for a duplicate again
        from ..docs.dups import dup_on_done
        dup_on_done(c, nid, False)
    fs_log_add(c, nid, "edit")
    bump(c)
    c.commit()
    m, n = _doc(c, nid)
    out = {"doc": doc_json(c, m, n, full=True, role=n["role"])}
    if before is not None:
        out["before"] = before
    return jsonify(out)
