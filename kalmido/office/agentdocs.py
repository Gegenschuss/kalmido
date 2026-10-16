"""2.51.0 A (#1348, #1350): agents in the office -- drafts only, a person confirms.

An agent works in the office area of its workspace (agents.org_id; a personal agent without one: its owner's personal
office, office.model pb_personal) and only when BOTH switches are on: its own "May draft office documents"
(agents.office_drafts, set by an admin of that area -- in a personal office by the person) and the area's privacy switch
"Agents may read office data" (office_settings.data.agents_read; client and price data go to the agent's AI model). Plus
the token scope "office". It acts for one person (requested_by, default: its owner) who must work in that office.

What an agent may do: read services, text blocks, framework contracts, clients and the area's documents (never purchase
prices); create quotation drafts and change its own drafts (never a number, a status, finalising, sending, deleting);
draft an invoice from an accepted quotation and a reminder over open invoices; suggest payments it read from what a
person gave it (office_pay_props) for an admin to accept (booked through the normal payment) or reject. Positions without
a service, with another price than the catalogue / framework contract or with a discount are marked (office_doc_items.
agent_flag) until a person changes or confirms them. Every request of an agent is one line in the office log (user_id =
the agent, action agent_read / agent_write, no contents).

Routes: /api/v1/office/... (agents, scope office) and /api/office/agents/<id>, /api/office/pay-props (people).
"""
import json
import re
from decimal import Decimal

from flask import g, jsonify, request

from ..core.config import app
from ..core.db import body, bump, db, err, iso, local_now, now_utc
from ..core.i18n import N_, tr
from ..core.access import Denied, list_role
from ..core.pg import insert_id, system_ctx, write_lock
from ..core.orgcrypt import oc_log_detail
from ..accounts.session import me
from ..personal.timetrack import BadInput
from ..api.v1 import UnknownFields, v1_args, v1_json, v1_view
from .calc import dec, dstr, fmt_money, money
from .model import office_on, office_role, office_rows, office_seed_texts, office_settings, pb_cl_sql, pb_owner, pb_personal, sr_public

OFA_ITEM_KEYS = ("kind", "service_id", "text", "detail", "qty", "unit", "price", "discount")
OFA_DATA_KEYS = ("client_id", "title", "intro", "items", "list_id")
OFA_CONF = ("high", "medium", "low")
OFA_MASTER = ("services", "texts", "contracts")
OFA_LOG_TARGETS = ("office", "services", "texts", "contracts", "clients", "docs", "doc", "pdf", "offer", "invoice", "reminder", "payment")
# link buttons in the chat (agents/chat.py): only the office document view, a list, and a document's PDF preview -- no other
# app route (some do something when opened), no outside address
NOTIFY_HREF_RE = re.compile(r"^(#office/offers/\d{1,12}|#l/\d{1,12}|/api/office/docs/\d{1,12}/pdf\?inline=1)$")
OFA_RULES = N_("Drafts only: a person reserves the number, finalises, sends and books. Free positions, other prices and discounts are marked.")
OFA_OFF = N_("This agent may not work in the office (its switch “May draft office documents” is off)")
OFA_PRIVACY_OFF = N_("Agents may not read the office data of this area (switch in the office settings)")


# ---------------------------------------------------------------- the area, the switches, the log
def ofa_area(c, a):
    """The office area agent row a works in (None: none -- a team agent without a workspace, an owner without an office)."""
    if a is None:
        return None
    if a["org_id"]:
        return a["org_id"]
    if a["owner_id"]:
        return pb_personal(c, a["owner_id"], create=False)
    return None


def ofa_agent_ok(c, agent_id, oid):
    """Part B (iface 04:35): agent agent_id may work in office area oid -- its office switch on, oid its area, the area's
    privacy switch on. (The person's office role is checked by ofa_draft_create.)"""
    from ..agents.core import agent_row
    with system_ctx(c):  # the agent's settings row (structure), whoever asks
        a = agent_row(c, agent_id)
    return bool(a and a["office_drafts"] and oid and ofa_area(c, a) == oid and office_settings(c, oid).get("agents_read"))


def ofa_area_agents(c, oid):
    """The agents working in office area oid (ids), with their switch: [(id, office_drafts)]."""
    owner = pb_owner(c, oid)
    with system_ctx(c):  # which agents work in this area (structure: ids and the switch, no content)
        if owner is not None:
            rows = c.execute("SELECT user_id, office_drafts FROM agents WHERE org_id IS NULL AND owner_id=? ORDER BY user_id", (owner,)).fetchall()
        else:
            rows = c.execute("SELECT user_id, office_drafts FROM agents WHERE org_id=? ORDER BY user_id", (oid,)).fetchall()
    return [(r[0], int(r[1] or 0)) for r in rows]


def ofa_log(c, oid, aid, write, target, doc_id=None, uid=None):
    """One line of the office log for one request of agent aid (no contents: what kind of thing, which document)."""
    detail = json.dumps({"agent": aid, "for": uid, "what": target}, ensure_ascii=False)
    g.ofa_log = (oid, insert_id(c, "INSERT INTO office_doc_log(org_id, doc_id, user_id, at, action, target, detail) VALUES(?,?,?,?,?,?,?)",
                                (oid, doc_id, aid, iso(now_utc()), "agent_write" if write else "agent_read", target, oc_log_detail(c, oid, detail))))


def _log_doc(c, did):
    """The document of this request's log line (known after the line was written, e.g. a new draft)."""
    lg = g.get("ofa_log")
    if lg:
        c.execute("UPDATE office_doc_log SET doc_id=? WHERE id=? AND org_id=?", (did, lg[1], lg[0]))


def _as_person(c, uid):
    """From here on the request reads and writes the office with the person's context (row-level security: their
    office areas; the routes below always filter by the agent's area oid). The agent stays in g.ofa_agent."""
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    g.ofa_agent = g.user
    g.user = u
    g.pop("acx", None)


def _v1ctx(c, rb=None, write=False, target="office"):
    """-> (aid, oid, uid) for an agent's office request; 403 without the scope's switches, 400 / 404 for a wrong person.
    Logs the request (one line)."""
    from ..agents.core import agent_row, agent_shares, need_agent
    aid = need_agent()
    a = agent_row(c, aid)
    if not a or not a["office_drafts"]:
        raise Denied(403, tr(OFA_OFF))
    oid = ofa_area(c, a)
    if not oid:
        raise Denied(403, tr("This agent has no office area (its workspace or its owner's personal office)"))
    if rb not in (None, "", 0, "0"):
        try:
            uid = int(rb)
        except (TypeError, ValueError):
            raise BadInput(tr("Invalid value: {0}", "requested_by")) from None
        u = c.execute("SELECT kind, kid, disabled FROM users WHERE id=?", (uid,)).fetchone()
        if not u or u["kind"] != "user" or u["kid"] or u["disabled"] or not agent_shares(c, aid, uid):
            raise Denied(404)
    elif a["owner_id"]:
        uid = a["owner_id"]
    else:
        raise BadInput(tr("requested_by is needed: the person this is for"))
    if office_role(c, uid, oid) not in ("admin", "member") or not office_on(c, uid):
        raise Denied(403, tr("This person does not work in this office"))
    _as_person(c, uid)
    if not office_settings(c, oid).get("agents_read"):
        raise Denied(403, tr(OFA_PRIVACY_OFF))
    ofa_log(c, oid, aid, write, target, uid=uid)
    return aid, oid, uid


def _args(allowed):
    return v1_args(allowed + ("requested_by",))


def _json(allowed):
    b = v1_json()
    extra = sorted(k for k in b if k not in allowed + ("requested_by",))
    if extra:
        raise UnknownFields(extra)
    return b


# ---------------------------------------------------------------- drafts (shared with part B: ofa_draft_create)
def _iid(v, name):
    if v in (None, "", 0):
        return None
    if isinstance(v, bool):
        raise BadInput(tr("Invalid value: {0}", name))
    try:
        return int(v)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", name)) from None


def _agent_sees(c, aid, lid):
    """The agent itself sees list lid (shared with it) and its list restriction (agents.list_ids) lets it in."""
    from ..agents.core import agent_row
    from ..agents.safety import ids_parse
    a = agent_row(c, aid)
    if not a or (a["list_ids"] and lid not in ids_parse(a["list_ids"])):
        return False
    return bool(list_role(c, lid, aid))


def _list_ok(c, oid, uid, lid, agent_id=None):
    """A project list the person sees, in the office area's workspace (a personal office: a private list), never health;
    with agent_id also one the agent sees within its list restriction."""
    lid = _iid(lid, "list_id")
    if lid is None:
        return None
    r = c.execute("SELECT org_id, life FROM lists WHERE id=?", (lid,)).fetchone()
    if not r or r["life"] == "health" or not list_role(c, lid, uid) or (agent_id and not _agent_sees(c, agent_id, lid)):
        raise Denied(404)
    personal = pb_owner(c, oid) is not None
    if (personal and r["org_id"] is not None) or (not personal and r["org_id"] != oid):
        raise BadInput(tr("The list belongs to another workspace than this office"))
    return lid


def ofa_items(c, oid, r, items):
    """The agent's positions [{kind?, service_id, text, detail?, qty, unit?, price, discount?}] -> (positions for
    clean_items, the mark of each). A service gives title, unit and price unless the agent sets them; a position without a
    service is "free", another price than the catalogue's (or the framework contract's) "price", a discount (percent,
    taken off the price) "discount:<pct>"."""
    from .docs import MAX_ITEMS, _num, clean_items
    if items in (None, ""):
        return [], []
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise BadInput(tr("Invalid value: {0}", "items"))
    out = []
    for it in items:
        if not isinstance(it, dict) or any(k not in OFA_ITEM_KEYS for k in it):
            raise BadInput(tr("Invalid value: {0}", "items"))
        kind = it.get("kind") or "service"
        if kind not in ("service", "text", "heading"):
            raise BadInput(tr("Invalid value: {0}", "items.kind"))
        x = {"kind": kind, "title": it.get("text") or "", "detail": it.get("detail") or ""}
        if kind == "service":
            sid = _iid(it.get("service_id"), "items.service_id")
            if sid is None and not str(x["title"]).strip():
                raise BadInput(tr("A position without a service needs a text"))
            x.update(service_id=sid, qty=it.get("qty"), unit=it.get("unit") or None, rate=it.get("price"))
        out.append(x)
    base = clean_items(c, oid, r, [{**x, "rate": None} if x.get("service_id") else x for x in out], False)
    flags = []
    for x, b0, it in zip(out, base, items):
        fl = []
        if x["kind"] == "service":
            if not x.get("service_id"):
                fl.append("free")
            elif x.get("rate") not in (None, ""):
                if abs(float(_num(x["rate"], "items.price", -1e8, 1e8) or 0) - float(b0["rate"] or 0)) > 0.00005:
                    fl.append("price")
            d = _num(it.get("discount"), "items.discount", 0, 100) if it.get("discount") not in (None, "") else None
            if d:
                rate = float(_num(x["rate"], "items.price", -1e8, 1e8) or 0) if x.get("rate") not in (None, "") else float(b0["rate"] or 0)
                x["rate"] = round(rate * (1 - d / 100), 4)
                fl.append(f"discount:{d:g}")
        flags.append(",".join(fl))
    return out, flags


def ofa_keep_flags(c, oid, did, items, rows):
    """A person saves the positions (docs._put_items): an agent's mark stays on an unchanged position and goes on a changed
    one or one the person confirmed (item.confirm)."""
    old = {r["id"]: r for r in c.execute("SELECT id, kind, service_id, title, qty, unit, rate, agent_flag FROM office_doc_items "
                                         "WHERE doc_id=? AND org_id=? AND part_id IS NULL AND agent_flag<>''", (did, oid))}
    out = []
    for it, row in zip(items if isinstance(items, list) else [], rows):
        prev = None
        if old and isinstance(it, dict) and not it.get("confirm"):
            try:
                prev = old.get(int(it.get("id") or 0))
            except (TypeError, ValueError):
                prev = None
        same = prev is not None and all(prev[k] == row.get(k) for k in ("kind", "service_id", "title", "unit")) \
            and all(abs(float(prev[k] or 0) - float(row.get(k) or 0)) < 0.00005 for k in ("qty", "rate"))
        out.append(prev["agent_flag"] if same else "")
    return out + [""] * (len(rows) - len(out))


def ofa_draft_create(c, uid, oid, data, agent_id=None):
    """A quotation draft in office area oid as person uid (agreed with part B): data = {client_id, title, intro?, items:
    [{service_id, text, qty, unit?, price, discount?}], list_id}. Never a number (a person reserves it or finalising does).
    PermissionError when uid does not work in that office; BadInput / Denied for wrong values. Returns the id (caller
    commits)."""
    from .docs import _put_items, _text, doc_create, doc_row, recalc
    from .model import NAME_MAX, TEXT_MAX
    if office_role(c, uid, oid) not in ("admin", "member") or not office_on(c, uid):
        raise PermissionError("office")
    if not isinstance(data, dict) or any(k not in OFA_DATA_KEYS for k in data):
        raise BadInput(tr("Invalid data"))
    lid = _list_ok(c, oid, uid, data.get("list_id"))  # a person applies it (part B) or the v1 route checked the agent's view
    office_seed_texts(c, oid)
    b = {"project_title": _text(data.get("title"), "title", NAME_MAX)}
    if data.get("client_id") not in (None, "", 0):
        b["client_id"] = data["client_id"]
    if data.get("intro") not in (None, ""):
        b["intro"] = _text(data["intro"], "intro", TEXT_MAX)
    did = doc_create(c, oid, uid, b, False, number=False)
    r = doc_row(c, oid, did)
    items, flags = ofa_items(c, oid, r, data.get("items"))
    if items:
        _put_items(c, oid, r, items, False, flags)
    c.execute("UPDATE office_docs SET agent_id=?, list_id=? WHERE id=? AND org_id=?", (agent_id, lid, did, oid))
    recalc(c, oid, did)
    return did


def ofa_doc_extra(c, d):
    """doc_public: the drafting agent's name and the project list (when the person sees it)."""
    aid = d.get("agent_id")
    d["agent_name"] = ""
    if aid:
        u = c.execute("SELECT display_name, username FROM users WHERE id=?", (aid,)).fetchone()
        d["agent_name"] = (u["display_name"] or u["username"]) if u else ""
    lid = d.get("list_id")
    d["list_name"] = ""
    if lid and getattr(g, "user", None) is not None and g.user["id"] and list_role(c, lid, g.user["id"]):
        r = c.execute("SELECT name FROM lists WHERE id=?", (lid,)).fetchone()
        d["list_name"] = r["name"] if r else ""


def ofa_offer_accepted(c, oid, did):
    """odoc_set_status -> accepted: the event offer_accepted to every agent of the area with its office switch on (only
    while the area lets agents read office data). A person's or the customer's acceptance alike."""
    if not office_settings(c, oid).get("agents_read"):
        return
    ids = [aid for aid, on in ofa_area_agents(c, oid) if on]
    if ids and pb_owner(c, oid) is None:  # 2.51.0 (#1348) review: a personal agent in an organisation only while its owner works in its office
        with system_ctx(c):  # the agents' owners and their office role (structure, no content)
            own = {r[0]: r[1] for r in c.execute(f"SELECT user_id, owner_id FROM agents WHERE user_id IN ({','.join('?' * len(ids))})", ids)}
            ids = [aid for aid in ids if not own.get(aid) or (office_role(c, own[aid], oid) in ("admin", "member") and office_on(c, own[aid]))]
    if not ids:
        return
    from ..agents.core import agent_emit
    r = c.execute("SELECT id, number, client_id, list_id, project_title, currency, totals FROM office_docs WHERE id=? AND org_id=?", (did, oid)).fetchone()
    try:
        t = json.loads(r["totals"] or "{}")
    except ValueError:
        t = {}
    data = {"doc_id": r["id"], "number": r["number"], "title": r["project_title"], "client_id": r["client_id"], "list_id": r["list_id"],
            "net": t.get("net"), "gross": t.get("gross"), "currency": r["currency"]}
    for aid in ids:
        agent_emit(c, aid, "offer_accepted", data, actor=None)


# ---------------------------------------------------------------- agents: reading (scope office)
def _doc_v1(c, oid, r, items=True):
    from .docs import doc_public
    d = doc_public(c, oid, r, False, items=items)
    for k in ("recipient_snapshot", "tax_snapshot", "sender", "cost_enc"):
        d.pop(k, None)
    d["app_url"] = f"#office/offers/{r['id']}"  # every kind opens in the tab "Quotes & invoices"
    return d


@app.get("/api/v1/office")
@v1_view
def v1_office_info():
    a = _args(())
    c = db()
    aid, oid, uid = _v1ctx(c, a.get("requested_by"))
    s = office_settings(c, oid)
    c.commit()
    return jsonify(area={"id": oid, "personal": pb_owner(c, oid) is not None}, person_id=uid, role=office_role(c, uid, oid),
                   currency=s.get("currency") or "EUR", lang=s.get("lang") or "de", small_business=bool(s.get("small_business")),
                   rules=tr(OFA_RULES))


@app.get("/api/v1/office/<kind>")
@v1_view
def v1_office_master(kind):
    if kind not in OFA_MASTER + ("clients",):
        raise Denied(404)
    a = _args(("q",))
    c = db()
    aid, oid, uid = _v1ctx(c, a.get("requested_by"), target=kind)
    q = (a.get("q") or "").strip()[:100]
    if kind == "clients":
        sql = (f"SELECT id, name, contact, email, address, street, zip, city, country, vat_id, customer_no FROM clients WHERE "
               f"{pb_cl_sql(c, oid)} AND archived=0")
        args = []
        if q:
            from ..core.pg import like_escape
            sql += " AND name ILIKE ? ESCAPE '\\'"
            args.append(f"%{like_escape(q)}%")
        rows = [dict(r) for r in c.execute(sql + " ORDER BY lower(name), id LIMIT 500", args)]
    else:
        rows = [sr_public(kind, r, False) for r in office_rows(c, oid, kind, archived=False, q=q)]
        for r in rows:  # never purchase prices or markups (members' view), whatever the master holds
            for k in [k for k in r if k.startswith("cost") or k in ("markup_pct", "costs")]:
                r.pop(k, None)
    c.commit()
    return jsonify(data=rows)


@app.get("/api/v1/office/docs")
@v1_view
def v1_office_docs():
    from .docs import DOC_KINDS, doc_brief
    from .invoices import inv_paid_map
    a = _args(("kind", "client_id", "open", "status"))
    c = db()
    aid, oid, uid = _v1ctx(c, a.get("requested_by"), target="docs")
    kind = a.get("kind") or "offer"
    if kind not in DOC_KINDS:
        raise BadInput(tr("Invalid value: {0}", "kind"))
    sql, args = "SELECT * FROM office_docs WHERE org_id=? AND kind=?", [oid, kind]
    cid = _iid(a.get("client_id"), "client_id")
    if cid:
        sql += " AND client_id=?"
        args.append(cid)
    if a.get("status"):
        sql += " AND status=?"
        args.append(str(a["status"])[:20])
    pm = inv_paid_map(c, oid) if kind in ("invoice", "credit") else {}
    rows = []
    for r in c.execute(sql + " ORDER BY date DESC, id DESC LIMIT 500", args).fetchall():
        b = doc_brief(r, pm)
        b["agent_id"] = r["agent_id"]
        if a.get("open") == "1" and b.get("state") not in ("issued", "sent", "partial", "overdue"):
            continue
        rows.append(b)
    c.commit()
    return jsonify(data=rows)


@app.get("/api/v1/office/docs/<int:did>")
@v1_view
def v1_office_doc(did):
    from .docs import doc_row
    a = _args(())
    c = db()
    aid, oid, uid = _v1ctx(c, a.get("requested_by"), target="doc")
    r = doc_row(c, oid, did)
    _log_doc(c, did)
    c.commit()
    return jsonify(_doc_v1(c, oid, r))


@app.get("/api/v1/office/docs/<int:did>/pdf")
@v1_view
def v1_office_pdf(did):
    """The PDF preview of a draft (marked as a draft like a person's preview)."""
    from .docs import doc_row
    from .ledger import ofx_locked
    from .pdfweb import _file_response, _render, epdf_name
    a = _args(())
    c = db()
    aid, oid, uid = _v1ctx(c, a.get("requested_by"), target="pdf")
    r = doc_row(c, oid, did)
    if ofx_locked(r) or r["status"] != "draft":
        raise Denied(409, tr("Only the preview of a draft"))
    _log_doc(c, did)
    c.commit()
    return _file_response(_render(c, oid, r)[0], epdf_name(r) + ".pdf", "application/pdf")


# ---------------------------------------------------------------- agents: drafts (scope office)
def _notify(c, aid, uid, did, oid, what):
    """The card in the person's chat with the agent: the sum, the PDF preview, "Open in the office"."""
    from ..agents.chat import chat_post
    from .docs import doc_public, doc_row
    d = doc_public(c, oid, doc_row(c, oid, did), False, items=False)
    title = d.get("project_title") or tr("without title")
    text = tr("{0} “{1}”: {2} net, {3} gross. A draft; you finalise and send it.", tr(what), title, d["net_text"], d["gross_text"])
    ch = [{"id": "open", "label": tr("Open in the office"), "style": "primary", "href": f"#office/offers/{did}"},
          {"id": "pdf", "label": tr("PDF preview"), "href": f"/api/office/docs/{did}/pdf?inline=1"}]
    r = chat_post(c, aid, uid, "agent", {"body": text, "choices": ch}, None)
    return r["id"]


def _draft_answer(c, aid, uid, oid, did, notify, what, code=201):
    from .docs import doc_row
    out = {"doc": _doc_v1(c, oid, doc_row(c, oid, did))}
    if notify:
        out["chat_message_id"] = _notify(c, aid, uid, did, oid, what)
    _log_doc(c, did)
    bump(c)
    c.commit()
    return jsonify(out), code


def _flag_notify(b):
    v = b.get("notify")
    if v not in (None, True, False):
        raise BadInput(tr("Invalid value: {0}", "notify"))
    return bool(v)


@app.post("/api/v1/office/offers")
@v1_view
def v1_office_offer_post():
    """{client_id?, title, intro?, items, list_id?, notify?, requested_by?} -> 201 {doc, chat_message_id?}."""
    b = _json(OFA_DATA_KEYS + ("notify",))
    c = db()
    notify = _flag_notify(b)
    aid, oid, uid = _v1ctx(c, b.get("requested_by"), write=True, target="offer")
    _list_ok(c, oid, uid, b.get("list_id"), aid)  # the agent itself must see the project list
    try:
        did = ofa_draft_create(c, uid, oid, {k: v for k, v in b.items() if k in OFA_DATA_KEYS}, agent_id=aid)
    except PermissionError:
        raise Denied(403, tr("This person does not work in this office")) from None
    return _draft_answer(c, aid, uid, oid, did, notify, N_("Quotation draft"))


@app.patch("/api/v1/office/offers/<int:did>")
@v1_view
def v1_office_offer_patch(did):
    """Only a draft this agent made, still a draft (no number change, no status): {client_id?, title?, intro?, items? (the
    whole list), list_id?, notify?}."""
    from .docs import _put_items, _text, clean_doc, doc_row, recalc
    from .ledger import ofx_locked
    from .model import NAME_MAX, TEXT_MAX
    b = _json(OFA_DATA_KEYS + ("notify",))
    c = db()
    notify = _flag_notify(b)
    aid, oid, uid = _v1ctx(c, b.get("requested_by"), write=True, target="offer")
    write_lock(c, f"office_doc_{int(did)}")
    r = doc_row(c, oid, did)
    if r["kind"] != "offer" or r["agent_id"] != aid:
        raise Denied(403, tr("An agent changes only its own drafts"))
    if ofx_locked(r) or r["status"] != "draft":
        raise Denied(409, tr("Only a draft can be changed"))
    f = {}
    if "title" in b:
        f["project_title"] = _text(b.get("title"), "title", NAME_MAX)
    if "intro" in b:
        f["intro"] = _text(b.get("intro"), "intro", TEXT_MAX)
    if "client_id" in b:
        f.update(clean_doc(c, oid, {"client_id": b["client_id"]}, r, False))
    if "list_id" in b:
        f["list_id"] = _list_ok(c, oid, uid, b.get("list_id"), aid)
    if f:
        f["updated_at"] = iso(now_utc())
        c.execute(f"UPDATE office_docs SET {','.join(k + '=?' for k in f)} WHERE id=? AND org_id=?", [*f.values(), did, oid])
    if "items" in b:
        r = doc_row(c, oid, did)
        items, flags = ofa_items(c, oid, r, b["items"])
        _put_items(c, oid, r, items, False, flags)
    recalc(c, oid, did)
    return _draft_answer(c, aid, uid, oid, did, notify, N_("Quotation draft"), 200)


@app.post("/api/v1/office/offers/<int:did>/invoice")
@v1_view
def v1_office_invoice_post(did):
    """#1350: an invoice draft from an accepted quotation (the same as a person's "Create invoice": positions, recipient,
    project, rights ...; parts_mode for a quotation with parts). Never finalised or sent."""
    from .docs import doc_row, recalc
    from .invoices import inv_from_offer
    b = _json(("parts_mode", "notify"))
    c = db()
    notify = _flag_notify(b)
    aid, oid, uid = _v1ctx(c, b.get("requested_by"), write=True, target="invoice")
    r = doc_row(c, oid, did)
    if r["kind"] != "offer":
        raise Denied(409, tr("Only a quotation can be turned into an invoice"))
    if r["status"] != "accepted":
        raise Denied(409, tr("Only an accepted quotation becomes an invoice draft"))
    pm = b.get("parts_mode")
    if pm not in (None, "", "full", "title", "summary"):
        raise BadInput(tr("Invalid value: {0}", "parts_mode"))
    nid = inv_from_offer(c, oid, uid, r, pm or None, None)
    c.execute("UPDATE office_docs SET agent_id=?, list_id=? WHERE id=? AND org_id=?", (aid, r["list_id"], nid, oid))
    recalc(c, oid, nid)
    return _draft_answer(c, aid, uid, oid, nid, notify, N_("Invoice draft"))


@app.post("/api/v1/office/reminders")
@v1_view
def v1_office_reminder_post():
    """#1350: a reminder draft over open, finalised invoices of one client {invoice_ids, level?: 1-3}. Never sent."""
    from .docs import recalc
    from .invoices import inv_make_reminder
    b = _json(("invoice_ids", "level", "notify"))
    c = db()
    notify = _flag_notify(b)
    aid, oid, uid = _v1ctx(c, b.get("requested_by"), write=True, target="reminder")
    nid = inv_make_reminder(c, oid, uid, {"doc_ids": b.get("invoice_ids"), "level": b.get("level", 1)})
    c.execute("UPDATE office_docs SET agent_id=? WHERE id=? AND org_id=?", (aid, nid, oid))
    recalc(c, oid, nid)
    return _draft_answer(c, aid, uid, oid, nid, notify, N_("Reminder draft"))


# ---------------------------------------------------------------- #1350: payment suggestions
def _pp_public(c, r, names=None):
    d = {k: r[k] for k in ("id", "doc_id", "agent_id", "requested_by", "date", "reference", "confidence", "note", "state", "payment_id",
                          "decided_by", "decided_at", "created_at")}
    d["amount"] = dstr(dec(r["amount"] or 0))
    doc = c.execute("SELECT number, currency, recipient, client_id FROM office_docs WHERE id=? AND org_id=?", (r["doc_id"], r["org_id"])).fetchone()
    d["number"] = doc["number"] if doc else ""
    d["currency"] = doc["currency"] if doc else "EUR"
    try:
        d["client_name"] = (json.loads(doc["recipient"] or "{}").get("name") or "") if doc else ""
    except ValueError:
        d["client_name"] = ""
    if names is not None:
        d["agent_name"] = names.get(r["agent_id"], "")
    return d


def _pp_open_amount(c, oid, r):
    from .invoices import inv_money_fields, inv_paid_map
    return dec(inv_money_fields(r, inv_paid_map(c, oid, [r["id"]]))["open"])


@app.post("/api/v1/office/payment-suggestions")
@v1_view
def v1_office_pp_post():
    """{invoice_id, amount, date, reference?, confidence?: high|medium|low, note?} -> 201 the suggestion (open). An admin of
    the area accepts it in the office (then it is booked as a payment) or rejects it."""
    from .docs import _date, doc_row
    from .ledger import ofx_locked
    b = _json(("invoice_id", "amount", "date", "reference", "confidence", "note"))
    c = db()
    aid, oid, uid = _v1ctx(c, b.get("requested_by"), write=True, target="payment")
    did = _iid(b.get("invoice_id"), "invoice_id")
    if not did:
        raise BadInput(tr("Invalid value: {0}", "invoice_id"))
    r = doc_row(c, oid, did)
    if r["kind"] != "invoice" or not ofx_locked(r) or r["status"] in ("cancelled", "paid", "draft"):
        raise Denied(409, tr("Payments go on finalised, open invoices only"))
    amt = dec(b.get("amount"), "NaN") if b.get("amount") not in (None, "") else Decimal("NaN")
    if amt.is_nan() or amt <= 0 or amt > Decimal("100000000"):
        raise BadInput(tr("Invalid value: {0}", "amount"))
    d = _date(b.get("date"), "date") or local_now().date().isoformat()
    if d > local_now().date().isoformat():
        raise BadInput(tr("The date must not lie in the future"))
    conf = b.get("confidence") or "medium"
    if conf not in OFA_CONF:
        raise BadInput(tr("Invalid value: {0}", "confidence"))
    ref = re.sub(r"[\x00-\x1f\x7f]", " ", b.get("reference") or "").strip()[:300] if isinstance(b.get("reference"), str) else ""
    note = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", b.get("note") or "").strip()[:500] if isinstance(b.get("note"), str) else ""
    if c.execute("SELECT COUNT(*) FROM office_pay_props WHERE org_id=? AND state='open'", (oid,)).fetchone()[0] >= 200:
        raise Denied(409, tr("Too many open payment suggestions: let a person decide on them first"))
    pid = insert_id(c, "INSERT INTO office_pay_props(org_id, doc_id, agent_id, requested_by, date, amount, reference, confidence, note, state, created_at) "
                       "VALUES(?,?,?,?,?,?,?,?,?,'open',?)", (oid, did, aid, uid, d, float(money(amt)), ref, conf, note, iso(now_utc())))
    _log_doc(c, did)
    bump(c)
    c.commit()
    out = _pp_public(c, c.execute("SELECT * FROM office_pay_props WHERE id=?", (pid,)).fetchone())
    out["exceeds_open"] = money(amt) > _pp_open_amount(c, oid, r)
    return jsonify(out), 201


@app.get("/api/v1/office/payment-suggestions")
@v1_view
def v1_office_pp_list():
    a = _args(("state",))
    c = db()
    aid, oid, uid = _v1ctx(c, a.get("requested_by"), target="payment")
    st = a.get("state") or "open"
    if st not in ("open", "accepted", "rejected", "all"):
        raise BadInput(tr("Invalid value: {0}", "state"))
    sql, args = "SELECT * FROM office_pay_props WHERE org_id=? AND agent_id=?", [oid, aid]
    if st != "all":
        sql += " AND state=?"
        args.append(st)
    rows = [_pp_public(c, r) for r in c.execute(sql + " ORDER BY id DESC LIMIT 200", args)]
    c.commit()
    return jsonify(data=rows)


# ---------------------------------------------------------------- people: the agent's switch, the suggestions
def _person():
    from .model import office_gate
    c = db()
    return c, office_gate(c)


def _agent_area(c, aid):
    from ..agents.core import agent_row
    with system_ctx(c):  # the agent's place (structure); who may see / set it is checked below by the office role
        a = agent_row(c, aid)
    if not a:
        raise Denied(404)
    return a, ofa_area(c, a)


@app.get("/api/office/agents/<int:aid>")
def ofa_agent_get(aid):
    """The office switch of agent aid for its settings dialog: {office_drafts, can_set, agents_read, personal, area_id}.
    Only for people of its office area (others: 404)."""
    c, uid = _person()
    a, oid = _agent_area(c, aid)
    role = office_role(c, uid, oid) if oid else None
    if not role:
        raise Denied(404)
    return jsonify(office_drafts=bool(a["office_drafts"]), can_set=role == "admin", agents_read=bool(office_settings(c, oid).get("agents_read")),
                   personal=pb_owner(c, oid) is not None, area_id=oid)


@app.patch("/api/office/agents/<int:aid>")
def ofa_agent_patch(aid):
    """{office_drafts: bool} -- an admin of the agent's office area (a personal office: its owner) switches it."""
    c, uid = _person()
    a, oid = _agent_area(c, aid)
    role = office_role(c, uid, oid) if oid else None
    if not role:
        raise Denied(404)
    if role != "admin":
        raise Denied(403, tr("Only an admin of this organisation can do this"))
    b = body()
    v = b.get("office_drafts") if isinstance(b, dict) else None
    if not isinstance(v, bool):
        return err(tr("Invalid value: {0}", "office_drafts"))
    with system_ctx(c):  # the agent's settings row (the right to change it was checked above)
        c.execute("UPDATE agents SET office_drafts=? WHERE user_id=?", (1 if v else 0, aid))
    from .ledger import ofx_log
    ofx_log(c, oid, "update", target="agent", detail={"agent": aid, "before": {"office_drafts": int(a["office_drafts"] or 0)}, "after": {"office_drafts": int(v)}})
    print("agent", aid, "office drafts", "on" if v else "off", "by", g.user["username"], flush=True)
    bump(c)
    c.commit()
    return jsonify(office_drafts=v)


def _pp_ctx(admin=False):
    from .model import office_gate, office_org
    c = db()
    uid = office_gate(c)
    oid = office_org(c, uid, admin=admin)
    return c, uid, oid


@app.get("/api/office/pay-props")
def ofa_pp_get():
    """?state=open (default) | all: the payment suggestions of the agents in my office area (admins decide)."""
    from ..collab.comments import user_names
    c, uid, oid = _pp_ctx()
    st = request.args.get("state") or "open"
    sql, args = "SELECT * FROM office_pay_props WHERE org_id=?", [oid]
    if st != "all":
        sql += " AND state='open'"
    rows = c.execute(sql + " ORDER BY id DESC LIMIT 200", args).fetchall()
    names = user_names(c, list({r["agent_id"] for r in rows if r["agent_id"]}))
    return jsonify(items=[_pp_public(c, r, names) for r in rows], admin=office_role(c, uid, oid) == "admin")


@app.post("/api/office/pay-props/<int:pid>")
def ofa_pp_decide(pid):
    """{action: accept | reject} by an admin of the area. accept books the payment like "Record payment" (the same checks:
    finalised open invoice, not above the open amount, no future date)."""
    from .invoices import inv_payment_post
    from .ledger import ofx_log
    c, uid, oid = _pp_ctx(admin=True)
    write_lock(c, f"office_pp_{int(pid)}")
    r = c.execute("SELECT * FROM office_pay_props WHERE id=? AND org_id=?", (pid, oid)).fetchone()
    if not r:
        raise Denied(404)
    if r["state"] != "open":
        raise Denied(409, tr("Already decided"))
    b = body()
    act = b.get("action") if isinstance(b, dict) else None
    if act not in ("accept", "reject"):
        return err(tr("Invalid value: {0}", "action"))
    ts = iso(now_utc())
    if act == "reject":
        c.execute("UPDATE office_pay_props SET state='rejected', decided_by=?, decided_at=? WHERE id=?", (uid, ts, pid))
        ofx_log(c, oid, "update", target="pay_prop", doc_id=r["doc_id"], detail={"id": pid, "after": {"state": "rejected"}})
        bump(c)
        c.commit()
        return jsonify(_pp_public(c, c.execute("SELECT * FROM office_pay_props WHERE id=?", (pid,)).fetchone()))
    note = (tr("Suggested by an agent") + (": " + r["reference"] if r["reference"] else ""))[:500]
    g.body = {"date": r["date"], "amount": dstr(dec(r["amount"])), "method": "transfer", "note": note}
    try:
        resp = inv_payment_post(r["doc_id"])  # books, logs and commits like a person's payment (403 / 409 / 400 raise)
    finally:
        g.body = None
    if isinstance(resp, tuple) and resp[1] >= 400:
        return resp
    pay = c.execute("SELECT id FROM office_payments WHERE org_id=? AND doc_id=? ORDER BY id DESC LIMIT 1", (oid, r["doc_id"])).fetchone()
    c.execute("UPDATE office_pay_props SET state='accepted', payment_id=?, decided_by=?, decided_at=? WHERE id=?", (pay["id"] if pay else None, uid, ts, pid))
    bump(c)
    c.commit()
    return jsonify(_pp_public(c, c.execute("SELECT * FROM office_pay_props WHERE id=?", (pid,)).fetchone()))


# ---------------------------------------------------------------- OpenAPI (called from api/openapi.py)
def ofa_spec(paths, schemas, op, ok, errs, ref, pid, q):
    T = "Office"
    o = {"type": "object"}
    rb = q("requested_by", "The person this is for (default: the agent's owner; a team agent must name one)", {"type": "integer"})
    item = {"type": "object", "properties": {
        "kind": {"type": "string", "enum": ["service", "text", "heading"]}, "service_id": {"type": ["integer", "null"], "description": "A service of the catalogue (its title, unit and price are taken over)"},
        "text": {"type": "string", "description": "The title (required without service_id)"}, "detail": {"type": "string"},
        "qty": {"type": "number"}, "unit": {"type": "string"}, "price": {"type": ["number", "null"], "description": "Another price than the catalogue's is marked"},
        "discount": {"type": "number", "description": "Percent off the price (marked)"}}}
    draft = {"type": "object", "properties": {
        "client_id": {"type": ["integer", "null"]}, "title": {"type": "string"}, "intro": {"type": "string"}, "items": {"type": "array", "items": item},
        "list_id": {"type": ["integer", "null"], "description": "The project list (in the office's workspace)"},
        "notify": {"type": "boolean", "description": "A card in the person's chat: sum, PDF preview, Open in the office"},
        "requested_by": {"type": "integer"}}}
    schemas["OfficeDraftInput"] = draft
    rules = ("Both switches must be on: the agent's \"May draft office documents\" and the area's privacy switch \"Agents may read "
             "office data\". Drafts only: never a number, status, finalising, sending, deleting or booking. Every request is in the "
             "office log.")
    paths["/office"] = {"get": op("The office area you work in (2.51.0)", T, ok(o) | errs("400", "403", "404"), [rb], scope="office", desc=rules)}
    paths["/office/{kind}"] = {"get": op("Services, text blocks, framework contracts or clients of the office (2.51.0)", T, ok(o) | errs("400", "403", "404"),
                                         [{"name": "kind", "in": "path", "required": True, "schema": {"type": "string", "enum": list(OFA_MASTER) + ["clients"]}},
                                          q("q", "Search", {"type": "string"}), rb], scope="office", desc="Never purchase prices or markups.")}
    paths["/office/docs"] = {"get": op("Quotations, invoices or reminders of the office, newest first (2.51.0)", T, ok(o) | errs("400", "403", "404"),
                                       [q("kind", "offer (default), invoice, credit, reminder", {"type": "string"}), q("client_id", "Only this client", {"type": "integer"}),
                                        q("status", "Stored status", {"type": "string"}), q("open", "1 = only open invoices (issued, sent, partial, overdue)", {"type": "string"}), rb],
                                       scope="office")}
    paths["/office/docs/{id}"] = {"get": op("One document with its positions (2.51.0)", T, ok(o) | errs("400", "403", "404"), [pid("id", "Document id"), rb], scope="office")}
    paths["/office/docs/{id}/pdf"] = {"get": {**op("The PDF preview of a draft (2.51.0)", T, errs("400", "403", "404", "409"), [pid("id", "Document id"), rb], scope="office"),
                                              "responses": {"200": {"description": "application/pdf"}, **errs("400", "403", "404", "409")}}}
    paths["/office/offers"] = {"post": op("Create a quotation draft (2.51.0)", T, ok(o, "Created", "201") | errs("400", "403", "404"), body=ref("OfficeDraftInput"),
                                          scope="office", desc=rules + " Free positions, other prices and discounts are marked for the person.")}
    paths["/office/offers/{id}"] = {"patch": op("Change your own quotation draft (2.51.0)", T, ok(o) | errs("400", "403", "404", "409"), [pid("id", "Document id")],
                                                body=ref("OfficeDraftInput"), scope="office", desc="items replaces the whole list. Only while it is a draft.")}
    paths["/office/offers/{id}/invoice"] = {"post": op("An invoice draft from an accepted quotation (2.51.0)", T, ok(o, "Created", "201") | errs("400", "403", "404", "409"),
                                                       [pid("id", "Quotation id")], body={"type": "object", "properties": {
                                                           "parts_mode": {"type": "string", "enum": ["full", "title", "summary"]}, "notify": {"type": "boolean"},
                                                           "requested_by": {"type": "integer"}}}, scope="office")}
    paths["/office/reminders"] = {"post": op("A reminder draft over open invoices of one client (2.51.0)", T, ok(o, "Created", "201") | errs("400", "403", "404", "409"),
                                             body={"type": "object", "required": ["invoice_ids"], "properties": {
                                                 "invoice_ids": {"type": "array", "items": {"type": "integer"}}, "level": {"type": "integer", "enum": [1, 2, 3]},
                                                 "notify": {"type": "boolean"}, "requested_by": {"type": "integer"}}}, scope="office")}
    paths["/office/payment-suggestions"] = {
        "get": op("Your payment suggestions (2.51.0)", T, ok(o) | errs("400", "403", "404"),
                  [q("state", "open (default), accepted, rejected, all", {"type": "string"}), rb], scope="office"),
        "post": op("Suggest an incoming payment for an open invoice (2.51.0)", T, ok(o, "Created", "201") | errs("400", "403", "404", "409"),
                   body={"type": "object", "required": ["invoice_id", "amount"], "properties": {
                       "invoice_id": {"type": "integer"}, "amount": {"type": "string", "description": "Decimal text, e.g. 1190.00"},
                       "date": {"type": "string", "format": "date"}, "reference": {"type": "string", "description": "The payment's reference text"},
                       "confidence": {"type": "string", "enum": list(OFA_CONF)}, "note": {"type": "string"}, "requested_by": {"type": "integer"}}},
                   scope="office", desc="Kalmido has no bank access: you read the payment from what a person gave you. An admin accepts "
                                        "(then it is booked) or rejects it; you never book.")}
