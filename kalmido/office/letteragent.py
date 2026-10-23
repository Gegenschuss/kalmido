"""2.153.0 (#2031): agents and letters: "Let the agent draft an answer" at an incoming document (an event to the agents
the documents are shared with), the API v1 for letter drafts (create / read / change a draft, set the link to the answered
document only while a draft); sending and finishing stay with a person.

The switches are those of the quotation drafts (office/agentdocs.py _v1ctx): scope office, the agent's "May draft office
documents", the area's "Agents may read office data". Letters are for the area's admins (like the document templates), so
the person an agent acts for (requested_by) must be an admin of the office. An agent sees only the letters it made itself
and links / answers only documents of the office's documents space that are shared with it (files/store.py fs_role) -- else
404, never shared on its behalf. Kalmido itself never phrases a letter: the agent writes subject and text."""
from flask import jsonify

from ..core.config import app
from ..core.db import body, bump, db
from ..core.i18n import N_, tr
from ..core.access import Denied
from ..personal.timetrack import BadInput
from ..api.v1 import v1_view
from .letters import lt_org
from .model import office_gate, office_on, office_role, office_settings, pb_owner
from .rights import ofr_rights

LTA_EVENT = "letter_draft_requested"
LTA_FIELDS = ("client_id", "rcpt_name", "rcpt_address", "rcpt_email", "letter_date", "subject", "body", "ref_line", "greeting", "lang")
LTA_IN = LTA_FIELDS + ("answers", "notify")
LTA_PATCH = LTA_FIELDS + ("notify",)
LTA_NOTE_MAX = 1000
LTA_ADMIN_ONLY = N_("Letters are for the admins of the office: the person you act for must be one")
LTA_SHARE_FIRST = N_("Share the document with the agent first")
LTA_HINT = ("A person asks you to draft an answer to this incoming document. Read it (GET /api/v1/documents/{node_id}, MCP "
            "get_document), then create ONE letter draft with POST /api/v1/office/letters {answers: node_id, subject, body, "
            "requested_by} (MCP create_letter_draft). Recipient and reference line are prefilled from the document. A draft only: "
            "the person checks, signs and sends it.")


# ---------------------------------------------------------------- the document and the agents
def lta_doc_ok(c, oid, nid, uid=None, aid=None):
    """Document node nid lies in the documents space of office area oid (a personal office: its owner's own documents, else
    the organisation's), is not in the bin, and person uid / agent aid sees it -> the fs_nodes row; Denied(404) otherwise."""
    from ..files.store import fs_chain, fs_deleted, fs_role
    try:
        nid = int(nid)
    except (TypeError, ValueError):
        raise Denied(404) from None
    chain = fs_chain(c, nid)
    if not chain or fs_deleted(chain) or chain[0]["kind"] != "file":
        raise Denied(404)
    n = chain[0]
    owner = pb_owner(c, oid)
    if (owner is not None and (n["org_id"] is not None or n["owner_id"] != owner)) or (owner is None and n["org_id"] != oid):
        raise Denied(404)
    if not c.execute("SELECT 1 FROM doc_meta WHERE node_id=?", (nid,)).fetchone():
        raise Denied(404)
    if uid and not fs_role(c, nid, uid=uid, chain=chain):
        raise Denied(404)
    if aid and not fs_role(c, nid, uid=aid, chain=chain):
        raise Denied(404)
    return n


def lta_agent_sees(c, nid, aid):
    from ..files.store import fs_role
    return bool(fs_role(c, nid, uid=aid))


def lta_agents(c, oid, uid):
    """The agents that may draft a letter for person uid in office area oid: active, their office switch on, the area's
    privacy switch on, reachable for uid (agents/core.py agent_shares) and -- a personal agent in an organisation -- its
    owner working in that office. -> [(id, name)]."""
    from ..agents.core import agent_active, agent_row, agent_shares
    from ..core.pg import system_ctx
    from .agentdocs import ofa_agent_on, ofa_area_agents
    if not office_settings(c, oid).get("agents_read"):
        return []
    out = []
    for aid, on in ofa_area_agents(c, oid):
        with system_ctx(c):  # the agent's settings row and name (structure), whoever asks
            a = agent_row(c, aid)
        if not a or not ofa_agent_on(c, a, oid, "letters", "edit"):  # 2.187.0 C (#2476): its switch or its office groups
            continue
        if not agent_active(a) or not agent_shares(c, aid, uid):
            continue
        if pb_owner(c, oid) is None and a["owner_id"] and (office_role(c, a["owner_id"], oid) not in ("admin", "member")
                                                            or not office_on(c, a["owner_id"])):
            continue
        out.append((aid, a["display_name"] or a["username"]))
    return out


# ---------------------------------------------------------------- people: the button at a document
@app.get("/api/office/letters/doc/<int:nid>/agents")
def lta_doc_agents(nid):
    """The agents that could draft an answer to document nid: {data: [{id, name}] (the document is shared with them),
    others: the number of agents that could, once it is shared}."""
    c = db()
    uid = office_gate(c)
    oid = lt_org(c, uid)
    lta_doc_ok(c, oid, nid, uid=uid)
    data, others = [], 0
    for aid, name in lta_agents(c, oid, uid):
        if lta_agent_sees(c, nid, aid):
            data.append({"id": aid, "name": name})
        else:
            others += 1
    return jsonify(data=data, others=others)


@app.post("/api/office/letters/doc/<int:nid>/ask-agent")
def lta_ask_agent(nid):
    """{agent_id, note?}: the event letter_draft_requested to that agent (it drafts the answer through the API v1). 403
    "Share the document with the agent first" when it may not see the document -- nothing is shared automatically."""
    from ..agents.core import agent_emit
    c = db()
    uid = office_gate(c)
    oid = lt_org(c, uid)
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    aid = b.get("agent_id")
    if isinstance(aid, bool) or not isinstance(aid, int):
        raise BadInput(tr("Invalid value: {0}", "agent_id"))
    note = b.get("note")
    if note is not None and not isinstance(note, str):
        raise BadInput(tr("Invalid value: {0}", "note"))
    note = (note or "").strip()[:LTA_NOTE_MAX]
    n = lta_doc_ok(c, oid, nid, uid=uid)
    if aid not in {a for a, _ in lta_agents(c, oid, uid)}:
        raise Denied(404)
    if not lta_agent_sees(c, nid, aid):
        raise Denied(403, tr(LTA_SHARE_FIRST))
    owner = pb_owner(c, oid)
    data = {"node_id": n["id"], "title": n["name"], "requested_by": uid, "note": note,
            "office": {"id": oid, "personal": owner is not None}, "org_id": None if owner is not None else oid,
            "hint": LTA_HINT}
    seq = agent_emit(c, aid, LTA_EVENT, data)
    if seq is None:
        raise Denied(409, tr("The agent is paused"))
    c.commit()
    return jsonify(ok=True, seq=seq)


# ---------------------------------------------------------------- agents: letter drafts (API v1, scope office)
def _v1ctx(c, rb, write=False):
    from .agentdocs import _v1ctx as ofa_ctx
    aid, oid, uid = ofa_ctx(c, rb, write=write, target="letter")
    if office_role(c, uid, oid) != "admin" and ofr_rights(c, uid, oid) is None:  # 2.187.0 C (#2476): groups: ofa_ctx checked the level
        raise Denied(403, tr(LTA_ADMIN_ONLY))
    return aid, oid, uid


def _own(c, oid, aid, lid):
    """Letter lid of the area made by agent aid (decrypted row); 404 for any other letter."""
    from .letters import lt_row
    d = lt_row(c, oid, lid)
    if d.get("agent_id") != aid:
        raise Denied(404)
    return d


def lta_v1(c, oid, aid, d):
    """The agent's view of its letter: the fields, the links to documents it sees, the app address."""
    from .letters import lt_public
    out = lt_public(c, oid, d)
    out.pop("created_by", None)
    links = []
    for r in c.execute("SELECT node_id, kind FROM office_letter_links WHERE letter_id=? AND org_id=? ORDER BY id", (d["id"], oid)):
        if lta_agent_sees(c, r["node_id"], aid):
            links.append({"node_id": r["node_id"], "kind": r["kind"]})
    out["links"] = links
    out["app_url"] = f"#office/letters/{d['id']}"
    return out


def _notify(c, aid, uid, d):
    """The card in the person's chat with the agent: "Letter draft from <agent>: <subject>", "Open in the office"."""
    from ..agents.chat import chat_post
    u = c.execute("SELECT display_name, username FROM users WHERE id=?", (aid,)).fetchone()
    name = (u["display_name"] or u["username"]) if u else tr("an agent")
    text = tr("Letter draft from {0}: “{1}”. A draft; you check and send it.", name, d.get("subject") or tr("without title"))
    ch = [{"id": "open", "label": tr("Open in the office"), "style": "primary", "href": f"#office/letters/{d['id']}"}]
    return chat_post(c, aid, uid, "agent", {"body": text, "choices": ch}, None)["id"]


def _flag(b):
    v = b.get("notify")
    if v not in (None, True, False):
        raise BadInput(tr("Invalid value: {0}", "notify"))
    return v is not False


@app.post("/api/v1/office/letters")
@v1_view
def v1_letter_post():
    """{answers?, client_id?, rcpt_name?, rcpt_address?, rcpt_email?, letter_date?, subject, body, ref_line?, greeting?, lang?,
    notify? (default true), requested_by?} -> 201 the draft (+ chat_message_id). answers = a document shared with you in the
    office's documents space (404 otherwise): recipient and reference line are prefilled from it and the letter is linked."""
    from .agentdocs import _json
    from .letterlinks import ltl_link, ltl_prefill
    from .letters import lt_create, lt_row
    b = _json(LTA_IN)
    c = db()
    notify = _flag(b)
    aid, oid, uid = _v1ctx(c, b.get("requested_by"), write=True)
    data = {k: b[k] for k in LTA_FIELDS if k in b}
    nid = b.get("answers")
    if nid not in (None, ""):
        if isinstance(nid, bool) or not isinstance(nid, int):
            raise BadInput(tr("Invalid value: {0}", "answers"))
        lta_doc_ok(c, oid, nid, uid=uid, aid=aid)
        pre = ltl_prefill(c, oid, uid, nid, agent_id=aid) or {}
        data = {**{k: v for k, v in pre.items() if k in LTA_FIELDS + ("contact_id",)}, **{k: v for k, v in data.items() if v not in (None, "")}}
    else:
        nid = None
    if not any(isinstance(data.get(k), str) and data[k].strip() for k in ("subject", "body")):
        raise BadInput(tr("A subject or a text is needed"))
    lid = lt_create(c, oid, None, data, agent_id=aid)
    if nid is not None:
        ltl_link(c, oid, lid, nid, "answers", agent_id=aid)
    d = lt_row(c, oid, lid)
    out = lta_v1(c, oid, aid, d)
    if notify:
        out["chat_message_id"] = _notify(c, aid, uid, d)
    bump(c)
    c.commit()
    return jsonify(out), 201


@app.get("/api/v1/office/letters")
@v1_view
def v1_letter_list():
    """The letters you made in this office, newest first: ?status=draft (default) | sent | delivered | all."""
    from .agentdocs import _args
    from .letters import LT_STATUS_KEYS, lt_row
    a = _args(("status",))
    st = a.get("status") or "draft"
    if st not in LT_STATUS_KEYS + ("all",):
        raise BadInput(tr("Invalid value: {0}", "status"))
    c = db()
    aid, oid, uid = _v1ctx(c, a.get("requested_by"))
    sql, args = "SELECT id FROM office_letters WHERE org_id=? AND agent_id=? AND archived=0", [oid, aid]
    if st != "all":
        sql += " AND status=?"
        args.append(st)
    ids = [r[0] for r in c.execute(sql + " ORDER BY id DESC LIMIT 200", args)]
    out = [lta_v1(c, oid, aid, lt_row(c, oid, i)) for i in ids]
    c.commit()
    return jsonify(data=out)


@app.get("/api/v1/office/letters/<int:lid>")
@v1_view
def v1_letter_get(lid):
    from .agentdocs import _args
    a = _args(())
    c = db()
    aid, oid, uid = _v1ctx(c, a.get("requested_by"))
    out = lta_v1(c, oid, aid, _own(c, oid, aid, lid))
    c.commit()
    return jsonify(out)


@app.patch("/api/v1/office/letters/<int:lid>")
@v1_view
def v1_letter_patch(lid):
    """Only your own draft, only while it is a draft (400 after sending): the fields of the create call except answers."""
    from .agentdocs import _json
    from .letters import lt_update
    from ..core.pg import write_lock
    b = _json(LTA_PATCH)
    c = db()
    notify = b.get("notify") is True
    if b.get("notify") not in (None, True, False):
        raise BadInput(tr("Invalid value: {0}", "notify"))
    aid, oid, uid = _v1ctx(c, b.get("requested_by"), write=True)
    write_lock(c, f"office_letter_{int(lid)}")
    _own(c, oid, aid, lid)
    d = lt_update(c, oid, lid, {k: b[k] for k in LTA_FIELDS if k in b})
    out = lta_v1(c, oid, aid, d)
    if notify:
        out["chat_message_id"] = _notify(c, aid, uid, d)
    c.commit()
    return jsonify(out)


@app.post("/api/v1/office/letters/<int:lid>/links")
@v1_view
def v1_letter_link(lid):
    """{node_id, kind: answers | reply}: links your own draft and a document shared with you in the office's documents
    space (404 otherwise); 400 once the letter is sent."""
    from .agentdocs import _json
    from .letterlinks import LTL_KINDS, ltl_link
    b = _json(("node_id", "kind"))
    c = db()
    aid, oid, uid = _v1ctx(c, b.get("requested_by"), write=True)
    kind = b.get("kind") or "answers"
    if kind not in LTL_KINDS:
        raise BadInput(tr("Invalid value: {0}", "kind"))
    nid = b.get("node_id")
    if isinstance(nid, bool) or not isinstance(nid, int):
        raise BadInput(tr("Invalid value: {0}", "node_id"))
    d = _own(c, oid, aid, lid)
    if d["status"] != "draft":
        raise BadInput(tr("Only a draft can be changed"))
    lta_doc_ok(c, oid, nid, uid=uid, aid=aid)
    ltl_link(c, oid, d["id"], nid, kind, agent_id=aid)
    bump(c)
    c.commit()
    return jsonify(lta_v1(c, oid, aid, d)), 201


# ---------------------------------------------------------------- OpenAPI (called from api/openapi.py)
def lta_spec(paths, schemas, op, ok, errs, ref, pid, q):
    T = "Office"
    o = {"type": "object"}
    rb = q("requested_by", "The person this is for (an admin of the office; default: the agent's owner)", {"type": "integer"})
    fields = {"client_id": {"type": ["integer", "null"], "description": "A client of the office (list_office_data clients)"},
              "rcpt_name": {"type": "string"}, "rcpt_address": {"type": "string", "description": "Address lines, one per line"},
              "rcpt_email": {"type": "string"}, "letter_date": {"type": "string", "format": "date", "description": "Default: today"},
              "subject": {"type": "string"}, "body": {"type": "string", "description": "The text of the letter (without greeting and signature)"},
              "ref_line": {"type": "string", "description": "The reference line (DIN 5008: your sign, your message of)"},
              "greeting": {"type": "string"}, "lang": {"type": "string", "enum": ["", "de", "en"]},
              "notify": {"type": "boolean", "description": "A card in the person's chat (default true on create)"}, "requested_by": {"type": "integer"}}
    schemas["LetterDraftInput"] = {"type": "object", "properties": {
        "answers": {"type": "integer", "description": "The incoming document (file id) this letter answers; must be shared with you"}, **fields}}
    schemas["LetterDraftPatch"] = {"type": "object", "properties": fields}
    rules = ("Both office switches must be on (the agent's \"May draft office documents\", the area's \"Agents may read office "
             "data\") and the person you act for must be an admin of the office. Drafts only: never sending, marking as sent, "
             "deleting. You see only the letters you made. Every request is in the office log.")
    lid = pid("id", "Letter id")
    paths["/office/letters"] = {
        "get": op("Your letters in the office, newest first (2.153.0)", T, ok(o) | errs("400", "403"),
                  [q("status", "draft (default), sent, delivered, all", {"type": "string"}), rb], scope="office", desc=rules),
        "post": op("Create a letter draft (2.153.0)", T, ok(o, "Created", "201") | errs("400", "403", "404"), body=ref("LetterDraftInput"),
                   scope="office", desc=rules + " After the event letter_draft_requested: answers = its node_id.")}
    paths["/office/letters/{id}"] = {
        "get": op("One of your letters (2.153.0)", T, ok(o) | errs("400", "403", "404"), [lid, rb], scope="office"),
        "patch": op("Change your own letter draft (2.153.0)", T, ok(o) | errs("400", "403", "404"), [lid], body=ref("LetterDraftPatch"),
                    scope="office", desc="Only while it is a draft (400 once a person sent it).")}
    paths["/office/letters/{id}/links"] = {
        "post": op("Link your letter draft with a document (2.153.0)", T, ok(o, "Created", "201") | errs("400", "403", "404"), [lid],
                   body={"type": "object", "required": ["node_id"], "properties": {
                       "node_id": {"type": "integer", "description": "A document shared with you in the office's documents space"},
                       "kind": {"type": "string", "enum": ["answers", "reply"], "description": "answers (default): the letter answers the document; "
                                                                                             "reply: the document is the answer to the letter"},
                       "requested_by": {"type": "integer"}}}, scope="office")}
