"""2.48.0 (#1356): agents suggest the project and category of a receipt; a person confirms.

A receipt here is a document (kalmido/docs) -- an incoming invoice, a receipt -- of a workspace. Its assignment
(rc_receipts) is a project (a list of kind 'project' of the same workspace) and a category (short free text; the
workspace's categories are the ones already used). Only people set it. An agent the document is shared with (view is
enough, its file or a folder above it) hands in a SUGGESTION (rc_suggest, POST /api/v1/documents/<id>/receipt-suggestion):
the document goes to "To review" and a person accepts (optionally changed) or rejects it, one undo step each (reopen). The
agent never sets, moves or deletes anything: there is no API route that writes rc_receipts, and the project must be a
project the agent may see itself (its list restriction, the document's workspace -- never across an organisation).
The travel costs / receipts of the office (2.47b) can later hang their receipts on rc_receipts.node_id."""
import re

from datetime import date

from flask import g, jsonify, request

from ..core.config import app
from ..core.db import body, bump, db, err, insert_id, iso, now_utc
from ..core.i18n import tr
from ..core.access import Denied, list_role
from ..accounts.session import me
from ..api.v1 import BadInput, UnknownFields
from ..api.common import v1_args, v1_json, v1_view
from ..files.store import fs_log_add, fs_on_delete, fs_subtree, need_node
from ..docs import store as S
from ..office.olock import OLK_BYPASS, olk_active, olk_kept_text, olk_until
from ..office.einvoice_in import ei_rc_offer, ei_take  # 2.185.0 A (#2583)

RC_CAT_MAX = 60
RC_NOTE_MAX = 500
RC_OPEN_MAX = 5          # open suggestions of one document (one per agent; the oldest go)
RC_VAT = ("19", "7", "0")  # 2.90.0 A (#1921): the VAT rates of a receipt (None = unknown)
RC_AMOUNT_MAX = 100_000_000  # as docs.extract.MAX_AMOUNT
_KEEP = object()


from ..core.db import now_iso as _now  # noqa: E402  2.149.0 G (#2517): was an own copy


def _is_agent():
    from ..agents.core import is_agent
    return is_agent(g.user)


def rc_doc(c, nid, write=False):
    """(node, meta) of a document the signed-in account may see (write: change)."""
    n = need_node(c, nid, write=write)
    m = S.meta_row(c, nid)
    if not m or n["kind"] != "file":
        raise Denied(404)
    return n, m


def rc_project_ok(c, lid, node, uid, agent=False):
    """Is lid a project uid may see, in the document's workspace? (agents: within their list restriction as well)"""
    r = c.execute("SELECT kind, org_id, archived FROM lists WHERE id=?", (lid,)).fetchone() if lid else None
    if not r or r["kind"] != "project" or r["archived"]:
        return False
    if (r["org_id"] or None) != (node["org_id"] or None):
        return False
    if not list_role(c, lid, uid):
        return False
    if agent:
        from ..agents.safety import agent_cap
        cap = agent_cap(c, uid)
        if cap is not None and lid not in cap:
            return False
    return True


def rc_clean(b, agent=False):
    """(project_id or None, category text) from a body; raises BadInput."""
    lid = b.get("project_id")
    if lid not in (None, "") and (not isinstance(lid, int) or isinstance(lid, bool) or lid < 1):
        raise BadInput(tr("Invalid value: {0}", "project_id"))
    cat = b.get("category") or ""
    if not isinstance(cat, str) or len(cat.strip()) > RC_CAT_MAX or any(ord(ch) < 32 for ch in cat):
        raise BadInput(tr("Invalid value: {0}", "category"))
    lid, cat = (lid or None), cat.strip()
    if agent and not lid and not cat:
        raise BadInput(tr("Suggest a project or a category"))
    return lid, cat


def rc_amount_clean(v):
    """2.121.0 C (#2096): "123.45" ('' = none) from a decimal text or a number > 0 with at most two decimals; raises BadInput."""
    from decimal import Decimal, InvalidOperation
    if v in (None, ""):
        return ""
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise BadInput(tr("Invalid value: {0}", "amount"))
    t = str(v).strip().replace(",", ".")
    if not re.fullmatch(r"\d{1,12}(\.\d{1,2})?", t):
        raise BadInput(tr("Invalid value: {0}", "amount"))
    try:
        d = Decimal(t)
    except InvalidOperation:
        raise BadInput(tr("Invalid value: {0}", "amount"))
    if d <= 0 or d > RC_AMOUNT_MAX:
        raise BadInput(tr("Invalid value: {0}", "amount"))
    return format(d.quantize(Decimal("0.01")), "f")


def rc_currency_clean(v):
    """2.121.0 C (#2096): three capital letters or '' (not given)."""
    if v in (None, ""):
        return ""
    t = v.strip().upper() if isinstance(v, str) else ""
    if not re.fullmatch(r"[A-Z]{3}", t):
        raise BadInput(tr("Invalid value: {0}", "currency"))
    return t


def rc_categories(c, ws):
    rows = c.execute("SELECT DISTINCT category FROM rc_receipts WHERE ws=? AND category<>'' UNION "
                     "SELECT DISTINCT category FROM rc_suggest WHERE ws=? AND category<>'' AND state='accepted'", (ws, ws)).fetchall()
    return sorted({r[0] for r in rows}, key=str.lower)[:200]


def _list_name(c, lid):
    r = c.execute("SELECT name FROM lists WHERE id=?", (lid,)).fetchone() if lid else None
    return r[0] if r else None


def _who(c, uid):
    r = c.execute("SELECT id, display_name, username FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    return {"id": r["id"], "name": r["display_name"] or r["username"]} if r else None


def rc_sug_json(c, s, uid=None):
    vis = lambda lid: lid and (uid is None or list_role(c, lid, uid))  # noqa: E731 -- a person sees a project name only when they see the project
    return {"id": s["id"], "document_id": s["node_id"], "agent": _who(c, s["agent_id"]), "state": s["state"],
            "project": {"id": s["list_id"], "name": _list_name(c, s["list_id"]) if vis(s["list_id"]) else None} if s["list_id"] else None,
            "category": s["category"] or None, "amount": S.doc_open(c, s["ws"], "rc_suggest.amount", s["amount"]) or None,
            "currency": s["currency"] or None, "vat_pct": s["vat_pct"], "note": S.doc_open(c, s["ws"], "rc_suggest.note", s["note"]) or "",
            "created_at": s["created_at"], "decided_at": s["decided_at"]}


def rc_review(c, nid):
    """doc_meta.review again after a decision: the documents' own rule (open suggestions, sender / type missing) + ours."""
    m = S.meta_row(c, nid)
    if not m:
        return
    sug = S.meta_json(c, m, "suggest", {})
    sug.pop("_given", None)
    open_rc = c.execute("SELECT 1 FROM rc_suggest WHERE node_id=? AND state='open' LIMIT 1", (nid,)).fetchone()
    review = 1 if (sug or open_rc or not (m["sender_id"] or m["type_id"])) else 0
    c.execute("UPDATE doc_meta SET review=? WHERE node_id=?", (review, nid))


def rc_vat_clean(v):
    """2.90.0 A (#1921): "19" | "7" | "0" | None from a body value; raises BadInput."""
    if v in (None, ""):
        return None
    v = str(v) if isinstance(v, (int, str)) and not isinstance(v, bool) else ""
    if v not in RC_VAT:
        raise BadInput(tr("Invalid value: {0}", "vat_pct"))
    return v


def rc_set(c, node, ws, lid, cat, uid, vat=_KEEP, keep=False):
    """Write the assignment of a receipt (people only); returns the previous (list_id, category). 2.90.0 A (#1921): vat =
    the VAT rate (left as it is when not given); the row stays while a VAT rate or a payment day is set, or with keep (the
    bookkeeping's receipt sheet: a receipt without category and rate is still a receipt)."""
    old = c.execute("SELECT list_id, category, vat_pct, paid_at, billed_doc_id FROM rc_receipts WHERE node_id=?", (node["id"],)).fetchone()
    prev = (old["list_id"], old["category"]) if old else (None, "")
    vat = (old["vat_pct"] if old else None) if vat is _KEEP else vat
    # 2.121.0 review N5: a receipt billed on to a client (#2094) stays a receipt like one with a payment day
    if old and old["vat_pct"] is not None and vat is None:
        olk_rc_keep(c, node["id"])  # 2.186.0 B (#2600): removing the VAT rate keeps the lock
    if not keep and not lid and not cat and vat is None and not (old and (old["paid_at"] or old["billed_doc_id"])):
        c.execute("DELETE FROM rc_receipts WHERE node_id=?", (node["id"],))
    elif old:
        c.execute("UPDATE rc_receipts SET list_id=?, category=?, vat_pct=?, set_by=?, set_at=? WHERE node_id=?",
                  (lid, cat, vat, uid, _now(), node["id"]))
    else:
        c.execute("INSERT INTO rc_receipts(node_id, org_id, ws, list_id, category, vat_pct, set_by, set_at) VALUES(?,?,?,?,?,?,?,?)",
                  (node["id"], node["org_id"], ws, lid, cat, vat, uid, _now()))
    return prev


def rc_state(c, node, m, uid):
    r = c.execute("SELECT * FROM rc_receipts WHERE node_id=?", (node["id"],)).fetchone()
    lid = r["list_id"] if r else None
    cur = {"project": {"id": lid, "name": _list_name(c, lid) if list_role(c, lid, uid) else None} if lid else None,
           "category": (r["category"] or None) if r else None, "set_by": _who(c, r["set_by"]) if r else None,
           "vat_pct": r["vat_pct"] if r else None, "paid_at": r["paid_at"] if r else None, "is_receipt": bool(r)}  # 2.90.0 A (#1921)
    sugs = [rc_sug_json(c, s, uid) for s in c.execute("SELECT * FROM rc_suggest WHERE node_id=? AND state='open' ORDER BY id", (node["id"],))]
    projects = [{"id": x["id"], "name": x["name"]} for x in c.execute(
        "SELECT id, name FROM lists WHERE kind='project' AND archived=0 AND org_id IS NOT DISTINCT FROM ? ORDER BY lower(name)",
        (node["org_id"],)) if list_role(c, x["id"], uid)][:300]
    return {"receipt": cur, "suggestions": sugs, "categories": rc_categories(c, m["ws"]), "projects": projects,
            "can_edit": node["role"] in ("owner", "edit"), "confirmed": rc_confirmed(c, node["id"], r),
            "einvoice_offer": not r and ei_rc_offer(c, m) is not None}  # 2.185.0 A (#2583): "Take over as receipt"


def rc_confirmed(c, nid, r):
    """2.154.0 A (#1356): {agent, by, at} when the receipt's assignment is still the one a person took over from an agent's
    suggestion (nobody changed it since: same person, set before the decision was written), else None."""
    if not r or not r["set_by"]:
        return None
    s = c.execute("SELECT agent_id, decided_by, decided_at FROM rc_suggest WHERE node_id=? AND state='accepted' AND decided_by=? "
                  "ORDER BY decided_at DESC, id DESC LIMIT 1", (nid, r["set_by"])).fetchone()
    if not s or not s["decided_at"] or str(r["set_at"] or "") > str(s["decided_at"]):
        return None
    return {"agent": _who(c, s["agent_id"]), "by": _who(c, s["decided_by"]), "at": s["decided_at"]}


# ---- people (the app) ---------------------------------------------------------------------------------------------------
def _person():
    if _is_agent():
        raise Denied(403, tr("Agents only suggest: a person confirms"))


@app.get("/api/docs/<int:nid>/receipt")
def rc_get(nid):
    """The receipt assignment of a document (project, category), the open suggestions of agents, the choices."""
    _person()
    c = db()
    n, m = rc_doc(c, nid)
    return jsonify(rc_state(c, n, m, me()))


@app.put("/api/docs/<int:nid>/receipt")
def rc_put(nid):
    """{project_id: id|null, category: text, vat_pct?: "19"|"7"|"0"|null, keep?: bool} -- a person sets the assignment (role
    edit); all empty = none. 2.90.0 A (#1921): vat_pct (left as it is when missing); keep = it stays a receipt when empty."""
    _person()
    c = db()
    uid = me()
    n, m = rc_doc(c, nid, write=True)
    b = body()
    extra = sorted(set(b) - {"project_id", "category", "vat_pct", "keep"})
    if extra:
        return err(tr("Unknown field: {0}", ", ".join(extra)[:200]))
    try:
        lid, cat = rc_clean(b)
        vat = rc_vat_clean(b["vat_pct"]) if "vat_pct" in b else _KEEP
    except BadInput as e:
        return err(str(e))
    if lid and not rc_project_ok(c, lid, n, uid):
        return err(tr("Choose a project of this workspace"))
    from ..office.periodlock import pl_receipt_need_open
    pl_receipt_need_open(c, nid, becoming=bool(cat or lid or b.get("keep") is True or vat not in (_KEEP, None)))  # 2.148.0 A (#2471)
    rc_set(c, n, m["ws"], lid, cat, uid, vat, keep=b.get("keep") is True)
    fs_log_add(c, nid, "receipt")
    bump(c)
    c.commit()
    return jsonify(rc_state(c, n, m, uid))


@app.post("/api/docs/<int:nid>/receipt/einvoice")
def rc_einv_take(nid):
    """2.185.0 A (#2583): an e-invoice in the documents of an office that is no receipt yet (read before 2.153, moved in, taken
    out by an older version) becomes one now, with the VAT rate of the invoice (role edit, people only); 409 when it is one."""
    _person()
    c = db()
    uid = me()
    n, m = rc_doc(c, nid, write=True)
    c.execute("SELECT node_id FROM doc_meta WHERE node_id=? FOR UPDATE", (nid,))  # two taps: one receipt
    if c.execute("SELECT 1 FROM rc_receipts WHERE node_id=?", (nid,)).fetchone():
        raise Denied(409, tr("This document is a receipt already"))
    if not ei_take(c, n, S.meta_row(c, nid), uid):
        return err(tr("Only an e-invoice in the documents of the office becomes a receipt here"))
    fs_log_add(c, nid, "receipt")
    bump(c)
    c.commit()
    return jsonify(rc_state(c, n, S.meta_row(c, nid), uid))


def _need_sug(c, sid, write=True):
    s = c.execute("SELECT * FROM rc_suggest WHERE id=?", (sid,)).fetchone()
    if not s:
        raise Denied(404)
    n, m = rc_doc(c, s["node_id"], write=write)
    return s, n, m


@app.post("/api/receipt-suggestions/<int:sid>/accept")
def rc_accept(sid):
    """{project_id?, category?} (changed values, else the agent's) -- a person takes the suggestion over (role edit)."""
    _person()
    c = db()
    uid = me()
    s, n, m = _need_sug(c, sid)
    if s["state"] != "open":
        return err(tr("This suggestion was already decided"), 409)
    b = body()
    cur = c.execute("SELECT list_id, category, vat_pct FROM rc_receipts WHERE node_id=?", (n["id"],)).fetchone()
    # 2.121.0 C (#2096): a suggestion of only amount / VAT rate leaves the project and category as they are
    only_money = not s["list_id"] and not s["category"]
    dl, dc = (cur["list_id"], cur["category"]) if (only_money and cur) else (s["list_id"], s["category"])
    try:
        lid, cat = rc_clean({"project_id": b.get("project_id", dl), "category": b.get("category", dc)})
        amt = rc_amount_clean(b["amount"] if "amount" in b else S.doc_open(c, s["ws"], "rc_suggest.amount", s["amount"]))
        ccy = rc_currency_clean(b["currency"] if "currency" in b else s["currency"])
        vat = rc_vat_clean(b["vat_pct"]) if "vat_pct" in b else (s["vat_pct"] or _KEEP)
    except BadInput as e:
        return err(str(e))
    if lid and not rc_project_ok(c, lid, n, uid):
        return err(tr("Choose a project of this workspace"))
    from ..office.periodlock import pl_receipt_need_open
    pl_receipt_need_open(c, n["id"], becoming=True)  # 2.148.0 A (#2471)
    pa = pc = pv = None
    if amt or ccy:
        dm = c.execute("SELECT amount, currency FROM doc_meta WHERE node_id=?", (n["id"],)).fetchone()
        pa, pc = S.doc_open(c, m["ws"], "doc_meta.amount", dm["amount"]) or "", dm["currency"] or ""
        c.execute("UPDATE doc_meta SET amount=?, currency=? WHERE node_id=?",
                  (S.doc_seal(c, m["ws"], "doc_meta.amount", amt or pa), ccy or pc, n["id"]))
    if vat is not _KEEP:
        pv = ((cur["vat_pct"] or "-") if cur else "x")  # 2.121.0 review M2: "x" = there was no receipt row before
    prev = rc_set(c, n, m["ws"], lid, cat, uid, vat, keep=bool(cur))  # 2.121.0 review M2: an amount-only accept keeps the receipt
    c.execute("UPDATE rc_suggest SET state='accepted', decided_by=?, decided_at=?, prev_list_id=?, prev_category=?, prev_amount=?, prev_currency=?, "
              "prev_vat_pct=? WHERE id=?",
              (uid, _now(), prev[0], prev[1], S.doc_seal(c, m["ws"], "rc_suggest.prev_amount", pa), pc, pv, sid))
    rc_review(c, n["id"])
    fs_log_add(c, n["id"], "receipt", "accepted")
    bump(c)
    c.commit()
    return jsonify(rc_state(c, n, m, uid))


@app.post("/api/receipt-suggestions/<int:sid>/reject")
def rc_reject(sid):
    _person()
    c = db()
    uid = me()
    s, n, m = _need_sug(c, sid)
    if s["state"] != "open":
        return err(tr("This suggestion was already decided"), 409)
    c.execute("UPDATE rc_suggest SET state='rejected', decided_by=?, decided_at=? WHERE id=?", (uid, _now(), sid))
    rc_review(c, n["id"])
    bump(c)
    c.commit()
    return jsonify(rc_state(c, n, m, uid))


@app.post("/api/receipt-suggestions/<int:sid>/reopen")
def rc_reopen(sid):
    """Undo of accept / reject: the suggestion is open again; after an accept the assignment before it comes back."""
    _person()
    c = db()
    uid = me()
    s, n, m = _need_sug(c, sid)
    if s["state"] == "accepted":
        from ..office.periodlock import pl_receipt_need_open
        pl_receipt_need_open(c, n["id"])  # 2.148.0 A (#2471): a receipt of a locked month keeps what was accepted
        vat = _KEEP if s["prev_vat_pct"] is None else (None if s["prev_vat_pct"] in ("-", "x") else s["prev_vat_pct"])
        only_money = not s["list_id"] and not s["category"]  # 2.121.0 review M2: its accept never created / removed the row
        rc_set(c, n, m["ws"], s["prev_list_id"], s["prev_category"] or "", uid, vat, keep=only_money and s["prev_vat_pct"] != "x" and bool(
            c.execute("SELECT 1 FROM rc_receipts WHERE node_id=?", (n["id"],)).fetchone()))
        if s["prev_amount"] is not None or s["prev_currency"] is not None:  # 2.121.0 C (#2096): the amount before the accept
            pa = S.doc_open(c, m["ws"], "rc_suggest.prev_amount", s["prev_amount"]) or ""
            c.execute("UPDATE doc_meta SET amount=?, currency=? WHERE node_id=?",
                      (S.doc_seal(c, m["ws"], "doc_meta.amount", pa), s["prev_currency"] or "", n["id"]))
    c.execute("UPDATE rc_suggest SET state='open', decided_by=NULL, decided_at=NULL WHERE id=?", (sid,))
    rc_review(c, n["id"])
    bump(c)
    c.commit()
    return jsonify(rc_state(c, n, m, uid))


# ---- agents (API v1) ----------------------------------------------------------------------------------------------------
@app.post("/api/v1/documents/<int:nid>/receipt-suggestion")
@v1_view
def v1_rc_suggest(nid):
    """An agent suggests project and / or category of a receipt shared with it; a person confirms in the app."""
    b = v1_json()
    extra = sorted(k for k in b if k not in ("project_id", "category", "note", "amount", "currency", "vat_pct"))
    if extra:
        raise UnknownFields(extra)
    if not _is_agent():
        raise Denied(403, tr("Only agents suggest; people set the receipt directly in the app"))
    c = db()
    aid = me()
    n, m = rc_doc(c, nid)
    lid, cat = rc_clean(b)
    amt = rc_amount_clean(b.get("amount"))  # 2.121.0 C (#2096): amount, currency and VAT rate may be suggested as well
    ccy = rc_currency_clean(b.get("currency"))
    vat = rc_vat_clean(b.get("vat_pct"))
    if not (lid or cat or amt or vat):
        raise BadInput(tr("Suggest a project, a category, an amount or a VAT rate"))
    if lid and not rc_project_ok(c, lid, n, aid, agent=True):
        raise BadInput(tr("Choose a project of this workspace"))
    note = b.get("note") or ""
    if not isinstance(note, str) or len(note) > RC_NOTE_MAX:
        raise BadInput(tr("Invalid value: {0}", "note"))
    c.execute("DELETE FROM rc_suggest WHERE node_id=? AND agent_id=? AND state='open'", (nid, aid))
    for x in c.execute("SELECT id FROM rc_suggest WHERE node_id=? AND state='open' ORDER BY id DESC OFFSET ?", (nid, RC_OPEN_MAX - 1)).fetchall():
        c.execute("DELETE FROM rc_suggest WHERE id=?", (x[0],))
    sid = insert_id(c, "INSERT INTO rc_suggest(node_id, org_id, ws, agent_id, list_id, category, note, state, created_at, amount, currency, vat_pct) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (nid, n["org_id"], m["ws"], aid, lid, cat, S.doc_seal(c, m["ws"], "rc_suggest.note", note.strip()), "open", _now(),
                     S.doc_seal(c, m["ws"], "rc_suggest.amount", amt), ccy, vat))
    c.execute("UPDATE doc_meta SET review=1 WHERE node_id=?", (nid,))
    fs_log_add(c, nid, "suggest", "receipt")
    bump(c)
    c.commit()
    return jsonify(rc_sug_json(c, c.execute("SELECT * FROM rc_suggest WHERE id=?", (sid,)).fetchone(), aid)), 201


@app.get("/api/v1/receipt-suggestions")
@v1_view
def v1_rc_list():
    """?state=open|accepted|rejected|all -- an agent's own suggestions (a person: theirs to decide in documents they see)."""
    a = v1_args(("state",))
    st = a.get("state") or "open"
    if st not in ("open", "accepted", "rejected", "all"):
        raise BadInput(tr("Invalid value: {0}", "state"))
    c = db()
    uid = me()
    where, args = ([], [])
    if _is_agent():
        where.append("agent_id=?")
        args.append(uid)
    else:  # 2.126.0 A (#1979 L7): a person -- only documents they see, before the limit
        from ..files.store import fs_visible_sql_c
        where.append(f"node_id IN {fs_visible_sql_c(c, uid)}")
    if st != "all":
        where.append("state=?")
        args.append(st)
    rows = c.execute("SELECT * FROM rc_suggest" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC LIMIT 500", args).fetchall()
    out = []
    for s in rows:
        try:
            rc_doc(c, s["node_id"])
        except Denied:
            continue  # no longer shared / not visible
        out.append(rc_sug_json(c, s, uid))
        if len(out) >= 200:
            break
    return jsonify(data=out)


def rc_spec(paths, schemas, op, ok, errs, ref, pid, q):
    """OpenAPI of the receipt suggestions (called from api/openapi.py)."""
    schemas["ReceiptSuggestion"] = {"type": "object", "properties": {
        "id": {"type": "integer"}, "document_id": {"type": "integer"}, "agent": {"type": ["object", "null"]},
        "state": {"type": "string", "enum": ["open", "accepted", "rejected"]},
        "project": {"type": ["object", "null"], "properties": {"id": {"type": "integer"}, "name": {"type": ["string", "null"]}}},
        "category": {"type": ["string", "null"]}, "amount": {"type": ["string", "null"]}, "currency": {"type": ["string", "null"]},
        "vat_pct": {"type": ["string", "null"], "enum": ["19", "7", "0", None]}, "note": {"type": "string"}, "created_at": {"type": "string"},
        "decided_at": {"type": ["string", "null"]}}}
    T = "Documents"
    paths["/documents/{id}/receipt-suggestion"] = {"post": op(
        "Suggest project, category, amount and VAT rate of a receipt (2.48.0)", T, {"201": {"description": "The suggestion",
                                                                          "content": {"application/json": {"schema": ref("ReceiptSuggestion")}}}}
        | errs("400", "403", "404"), [pid("id", "Document (file) id")],
        body={"type": "object", "properties": {
            "project_id": {"type": ["integer", "null"], "description": "A list of kind project you can see, in the document's workspace"},
            "category": {"type": "string", "description": f"Short text (max {RC_CAT_MAX}), e.g. Travel, Material, Software"},
            "amount": {"type": ["string", "number"], "description": "Gross amount of the receipt, more than 0, at most two decimals (2.121.0)"},
            "currency": {"type": "string", "description": "Three letters, e.g. EUR (optional)"},
            "vat_pct": {"type": "string", "enum": ["19", "7", "0"], "description": "VAT rate of the receipt in percent"},
            "note": {"type": "string", "description": "Why (shown to the person who decides)"}}},
        scope="files:read",
        desc="Agents only. The document must be shared with you. The suggestion waits in To review until a person accepts or "
             "rejects it; you never set the assignment yourself. A new suggestion of yours replaces your open one.")}
    paths["/receipt-suggestions"] = {"get": op(
        "Your receipt suggestions and what became of them (2.48.0)", T,
        ok({"type": "object", "properties": {"data": {"type": "array", "items": ref("ReceiptSuggestion")}}}) | errs("400", "403"),
        [q("state", "open (default), accepted, rejected or all")], scope="files:read")}


# ---- the event document_added ------------------------------------------------------------------------------------------
def rc_doc_agents(c, nid):
    """The agents that see document nid: a share on it or a folder above it, or their own result folder (fs_role decides)."""
    from ..files.store import fs_chain, fs_role
    chain = fs_chain(c, nid)
    ids = [x["id"] for x in chain]
    if not ids:
        return []
    q = ",".join("?" * len(ids))
    cand = {r[0] for r in c.execute(f"SELECT agent_id FROM fs_shares WHERE node_id IN ({q}) AND agent_id IS NOT NULL", ids)}
    cand |= {x["agent_id"] for x in chain if x["agent_id"]}
    return sorted(a for a in cand if fs_role(c, nid, a))


def rc_on_done(c, nid, first):
    """After the first recognition of a document: event document_added to every agent that sees it (an agent then reads
    it and may suggest, e.g. the project of a receipt). Never on a later run (a new version, Recognise again)."""
    if not first:
        return
    from ..agents.core import agent_emit
    m = S.meta_row(c, nid)
    n = c.execute("SELECT id, name, org_id FROM fs_nodes WHERE id=? AND deleted_at IS NULL", (nid,)).fetchone()
    if not m or not n:
        return
    for aid in rc_doc_agents(c, nid):
        try:
            with c.savepoint():
                agent_emit(c, aid, "document_added", {"document": {"id": nid, "name": n["name"], "state": m["state"], "date": m["doc_date"],
                                                                   "url": f"/api/v1/documents/{nid}"}}, actor=None)
        except Exception as e:  # noqa: BLE001 -- an event never stops the recognition
            print(f"WARNING document_added event for agent {aid}: {type(e).__name__}", flush=True)


def _rc_hook():
    from ..docs.ingest import doc_on_done
    if rc_on_done not in doc_on_done:
        doc_on_done.append(rc_on_done)


_rc_hook()


# ---------------------------------------------------------------- 2.152.0 C (#2168): booked receipts are kept by law
def olk_fs_locked(c, node_id):
    """The last day (ISO) a booked receipt (paid or with its VAT rate set) has to be kept, while that period runs; else None.
    The period runs from the end of the receipt's year (its document date, else paid / assigned day). Moving it into the
    trash stays possible; deleting it for good (the trash's purge, the trash period run) is refused until then.
    2.186.0 B (#2600): also a receipt the cash book books (from the entry's day), one of the equipment list (from the
    purchase year plus the useful life; while the item is not archived, at least from this year), one billed on a
    finalised / sent document, and the lock kept when its payment day / VAT rate were removed later (doc_meta.kept_until)."""
    nid = int(node_id)
    r = c.execute("""SELECT r.paid_at, r.vat_pct, r.set_at, r.billed_doc_id, r.billed_at, m.doc_date FROM rc_receipts r
                     LEFT JOIN doc_meta m ON m.node_id=r.node_id WHERE r.node_id=?""", (nid,)).fetchone()
    k = c.execute("SELECT kept_until FROM doc_meta WHERE node_id=?", (nid,)).fetchone()
    ends = [olk_day(k["kept_until"])] if k and k["kept_until"] else []
    if r and (r["paid_at"] is not None or r["vat_pct"] is not None):
        ends.append(olk_until(r["doc_date"] or r["paid_at"] or r["set_at"], "receipt"))
    if r and r["billed_doc_id"]:
        d = c.execute("SELECT locked_at, status FROM office_docs WHERE id=?", (r["billed_doc_id"],)).fetchone()
        if d and (d["locked_at"] or d["status"] == "sent"):
            ends.append(olk_until(r["doc_date"] or r["billed_at"] or r["set_at"], "receipt"))
    for e in c.execute("SELECT day FROM office_cash_entries WHERE node_id=?", (nid,)):
        ends.append(olk_until(e["day"], "receipt"))
    this_year = now_utc().year
    for a in c.execute("SELECT purchase_date, life_months, archived FROM office_equipment WHERE receipt_node_id=?", (nid,)):
        m = re.match(r"(\d{4})", a["purchase_date"] or (r["doc_date"] if r else "") or "")
        year = int(m.group(1)) + -(-int(a["life_months"] or 0) // 12) if m else this_year
        ends.append(olk_until(str(max(year, this_year) if not a["archived"] else year), "receipt"))
    until = max((e for e in ends if e), default=None)
    return until.isoformat() if olk_active(until) else None


def olk_day(v):
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def olk_rc_keep(c, nid):
    """2.186.0 B (#2600): before the payment day or the VAT rate of receipt nid is removed: the lock running now stays
    (doc_meta.kept_until), so taking the booking back never frees the receipt for deleting. The receipt row itself
    follows the usual rules (the books count only what is booked now)."""
    until = olk_fs_locked(c, nid)
    if until:
        c.execute("UPDATE doc_meta SET kept_until=? WHERE node_id=? AND (kept_until IS NULL OR kept_until<?)", (until, int(nid), until))


def olk_on_delete(c, nid):
    """fs_on_delete hook (first in the list): 409 before anything of the purge happens. A folder checks its whole subtree, so
    the purge of a folder stops before the hooks of its first file ran (fs_purge calls the root first)."""
    if OLK_BYPASS.get():  # 2.152.0 (#2164 #2167, review A2): a hosted deletion after rx_gate
        return
    n = c.execute("SELECT kind FROM fs_nodes WHERE id=?", (int(nid),)).fetchone()
    for i in (fs_subtree(c, nid) if n and n["kind"] == "folder" else [nid]):
        until = olk_fs_locked(c, i)
        if until:
            raise Denied(409, olk_kept_text(date.fromisoformat(until)))


if olk_on_delete not in fs_on_delete:
    fs_on_delete.insert(0, olk_on_delete)
