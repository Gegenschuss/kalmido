"""2.126.1 A (#2123 #2124): texts drafted by a CONNECTED agent, on request of a person. Kalmido itself calls no model: a
person asks one of their agents (POST /api/proposals {kind, agent_id, ...}), the agent gets the event job_request with
exactly the data below, formulates and answers with one proposal (POST /api/v1/agent/jobs/<id>/proposal, MCP
submit_proposal). The person sees the text on a proposal card, edits it, takes it over (as that person, one undo step) or
discards it. Nothing is sent to a client, nothing is changed before "Take over".

Kinds:
- office_text: the introduction or closing of an office document draft (quotation, invoice, reminder). Only an agent that
  works in the person's office area with both switches on (its "May draft office documents" and the area's "Agents may read
  office data", office/agentdocs.py) and the person may change the document. Input: kind, number, title, language, the
  client's name / recipient lines, the positions WITHOUT purchase prices (as GET /api/v1/office/docs/<id>), the totals, the
  current text, the person's wish; a reminder also its invoices (open amount, due date, days overdue) and level.
  The agent answers {field, text}; taking it over writes the field (409 once the document is finalised or sent).
- doc_summary: a summary of a document / receipt of the documents (docs/). The same office switches plus: the agent sees
  the file itself (shared with it, files/store.py fs_role) -- the input is what GET /api/v1/documents/<id> shows it (name,
  date, due, amount, sender, type, tags, the recognised text, what the recognition read off a receipt), never more.
  The agent answers {text}; taking it over stores it as the document's summary (doc_meta.summary, sealed like the text).
- report: the status report of a list for a period, worded by an agent the list is shared with (lists/report.py
  project_status as that agent sees the list, the fixed Markdown text, no comments / notes / names). The agent answers
  {text} (Markdown); taking it over keeps the text with the job, the status report dialog then shows it instead of the
  fixed text (copy / share as before); undo goes back to the fixed text.
"""
import json
import re
from datetime import date

from flask import g, jsonify

from ..core.config import app  # noqa: F401  (the routes are hooks of agents/proposals.py and lists/report.py)
from ..core.i18n import N_, tr, LANGS
from ..core.db import bump, err, iso, local_now, now_utc
from ..core.pg import insert_id, system_ctx
from ..core.access import Denied, list_role
from ..core.errors import BadInput
from ..agents.core import agent_active, agent_emit, agent_row, agent_shares, job_dict, JOB_TITLE_MAX
from ..agents.proposals import PROP_LIMITS, PROP_OPEN_MAX, PROP_TEXT_MAX, _p_keys, _p_str, prop_mode
from ..collab.comments import user_names

AST_KINDS = ("office_text", "doc_summary", "report")
AST_DOC_KINDS = ("offer", "invoice", "reminder")   # documents with an introduction / closing the agent may word
AST_FIELDS = ("intro", "closing")
AST_WISH_MAX = 500                                 # the person's short wish ("friendly, short")
AST_DOC_TEXT_MAX = 20000                           # recognised text of a document sent to the agent
AST_SUMMARY_MAX = 4000                             # a document's summary
AST_ITEM_KEYS = ("kind", "title", "detail", "qty", "unit", "rate", "tax")  # never cost / cost_enc / margins
AST_TITLES = {"office_text": N_("Text draft: {0}"), "doc_summary": N_("Summary: {0}"), "report": N_("Client report: {0}")}
AST_NO_AGENT = N_("This agent cannot make proposals for you")


def _clean(v, what, mx, required=False):
    """A multi-line text of the agent / the person: control characters out (tabs and new lines stay), at most mx."""
    v = _p_str(v, what, mx, required, line=False)
    return re.sub(r"[\x7f]", "", v)


def _pub(c, a):
    from ..accounts.pictures import avatar_url
    from ..agents.core import agent_online
    from ..agents.usage import usage_block
    u = c.execute("SELECT * FROM users WHERE id=?", (a["user_id"],)).fetchone()
    return {"id": a["user_id"], "name": a["display_name"] or a["username"], "avatar": avatar_url(u),
            "limit_reached": bool(usage_block(c, a["user_id"])), "online": agent_online(a) is not False}


def _person_ok(c, a, uid):
    """May person uid ask agent a at all (its proposal switch; a personal agent: its owner; else a shared list)?"""
    if not agent_active(a) or prop_mode(a) == "off":
        return False
    if a["owner_id"] == uid:
        return True
    if a["owner_id"]:
        return False
    return prop_mode(a) == "all" or agent_shares(c, a["user_id"], uid)


# ---------------------------------------------------------------- who may be asked
def ast_office_agents(c, uid, oid):
    """The agents of office area oid uid may ask for an office text: the agent's office switch on, the area's privacy switch
    on, uid works in that office; a personal agent in an organisation only while its owner works there (as offer_accepted)."""
    from ..office.agentdocs import ofa_area, ofa_area_agents
    from ..office.model import office_on, office_role, office_settings
    if not oid or office_role(c, uid, oid) not in ("admin", "member") or not office_on(c, uid):
        return []
    if not office_settings(c, oid).get("agents_read"):
        return []
    out = []
    for aid, on in ofa_area_agents(c, oid):
        if not on:
            continue
        with system_ctx(c):  # the agent's settings row (structure), whoever asks
            a = agent_row(c, aid)
        if not a or ofa_area(c, a) != oid or not _person_ok(c, a, uid):
            continue
        if a["owner_id"] and a["owner_id"] != uid and (office_role(c, a["owner_id"], oid) not in ("admin", "member") or not office_on(c, a["owner_id"])):
            continue
        out.append(a)
    return out


def _doc_area(c, uid, node):
    """The office area of a document: its organisation, a private one: the person's personal office."""
    from ..office.model import pb_personal
    return node["org_id"] or pb_personal(c, uid, create=False)


def ast_doc_agents(c, uid, nid):
    """Agents uid may ask for a summary of document nid: office agents of the document's area that see the file themselves."""
    from ..files.store import fs_role, need_node
    from ..docs import store as S
    n = need_node(c, nid, write=True)
    if n["kind"] != "file" or not S.meta_row(c, nid):
        raise Denied(404)
    return [a for a in ast_office_agents(c, uid, _doc_area(c, uid, n)) if fs_role(c, nid, uid=a["user_id"])], n


def ast_list_agents(c, uid, lid):
    """Agents uid may ask for a client report of list lid: the list is shared with them and uid may address them there."""
    from ..agents.core import agent_usable
    from ..agents.proposals import prop_agent_ok
    rows = c.execute("""SELECT a.*, u.username, u.display_name, u.avatar, u.disabled FROM agents a JOIN users u ON u.id=a.user_id
                        WHERE u.kind='agent' ORDER BY u.id""").fetchall()
    return [a for a in rows if prop_agent_ok(c, a, uid) and list_role(c, lid, a["user_id"])
            and (prop_mode(a) == "all" or agent_usable(c, a["user_id"], uid, lid))]


def _iid(v, what):
    try:
        v = int(v)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", what)) from None
    if v <= 0:
        raise BadInput(tr("Invalid value: {0}", what))
    return v


def ast_agents_get(c, uid, a):
    """GET /api/proposals/agents?kind=office_text&doc_id= | kind=doc_summary&doc_id= | kind=report&list_id=."""
    kind = a.get("kind")
    try:
        if kind == "office_text":
            from ..office.model import office_org
            r = _office_doc(c, uid, office_org(c, uid), a.get("doc_id"))[1]
            editable = not (r["locked_at"] or r["status"] == "sent")  # a finalised / sent document takes no text
            ags = ast_office_agents(c, uid, r["org_id"]) if r["kind"] in AST_DOC_KINDS and editable else []
        elif kind == "doc_summary":
            ags = ast_doc_agents(c, uid, _iid(a.get("doc_id"), "doc_id"))[0]
        else:
            from ..core.access import need_list
            lid = _iid(a.get("list_id"), "list_id")
            need_list(c, lid, write=False)
            ags = ast_list_agents(c, uid, lid)
    except (Denied, BadInput):
        ags = []
    return jsonify(agents=[_pub(c, x) for x in ags])


# ---------------------------------------------------------------- the inputs
def _office_doc(c, uid, oid, did):
    from ..office.docs import doc_row
    from ..office.model import office_on, office_role
    if not oid or office_role(c, uid, oid) not in ("admin", "member") or not office_on(c, uid):
        raise Denied(403)
    return oid, doc_row(c, oid, _iid(did, "doc_id"))


def _office_input(c, oid, r, field, wish):
    """What the agent may read of the document anyway (GET /api/v1/office/docs/<id>), trimmed to what a text needs."""
    from ..office.agentdocs import _doc_v1
    from ..office.docs import doc_public
    d = _doc_v1(c, oid, r)
    rec = d.get("recipient") or {}
    cl = c.execute("SELECT name FROM clients WHERE id=? AND org_id=?", (r["client_id"], oid)).fetchone() if r["client_id"] else None
    t = d.get("totals") or {}
    inp = {"doc": {"id": r["id"], "kind": r["kind"], "number": r["number"] or None, "title": r["project_title"] or "",
                   "lang": r["lang"], "currency": r["currency"], "date": r["date"] or None,
                   "valid_until": (r["valid_until"] or None) if r["kind"] == "offer" else None,
                   "due_date": d.get("due_date") or None},
           "client": {"name": (cl["name"] if cl else "") or rec.get("name") or "", "recipient": rec.get("name") or "",
                      "lines": [str(x) for x in (rec.get("lines") or [])][:8]},
           "items": [{k: it.get(k) for k in AST_ITEM_KEYS if k in it} for it in (d.get("items") or [])][:100],
           "totals": {k: t.get(k) for k in ("net", "vat", "gross") if k in t},
           "field": field, "text": d.get(field) or "", "other_text": d.get("closing" if field == "intro" else "intro") or "",
           "wish": wish or None}
    for it in inp["items"]:
        for k in ("qty", "rate"):
            if it.get(k) is not None:
                it[k] = str(it[k])
    if r["kind"] == "reminder":
        today = local_now().date()
        refs = []
        for i in (d.get("ref_doc_ids") or [])[:20]:
            x = c.execute("SELECT * FROM office_docs WHERE id=? AND org_id=? AND kind='invoice'", (int(i), oid)).fetchone() if str(i).isdigit() else None
            if not x:
                continue
            p = doc_public(c, oid, x, False, items=False)
            due = x["due_date"] or None
            try:
                days = (today - date.fromisoformat(due[:10])).days if due else 0
            except ValueError:
                days = 0
            refs.append({"number": x["number"] or None, "date": x["date"] or None, "due_date": due, "gross": (p.get("totals") or {}).get("gross"),
                         "open": p.get("open"), "days_overdue": max(days, 0)})
        inp["reminder"] = {"level": int(r["reminder_level"] or 1), "fee": str(r["reminder_fee"] or 0), "deadline_days": r["reminder_deadline_days"],
                           "invoices": refs}
    return inp


def _doc_input(c, aid, n, wish):
    """What GET /api/v1/documents/<id> shows the agent of this file (docs/v1.py) -- the agent's own role on it."""
    from ..docs import store as S
    from ..docs.web import doc_json
    from ..files.store import fs_role
    m = S.meta_row(c, n["id"])
    d = doc_json(c, m, n, full=True, role=fs_role(c, n["id"], uid=aid))
    x = d.get("extracted") or {}
    return {"document": {"id": d["id"], "name": d["name"], "date": d.get("date"), "due": d.get("due"), "amount": d.get("amount"),
                         "currency": d.get("currency"), "sender": (d.get("sender") or {}).get("name"), "type": (d.get("type") or {}).get("name"),
                         "tags": [t.get("name") for t in d.get("tags") or [] if isinstance(t, dict)][:20],
                         "text": (d.get("text") or "")[:AST_DOC_TEXT_MAX],
                         "extracted": {k: x.get(k) for k in ("supplier", "invoice_no", "vat_pct", "net", "vat", "gross", "currency") if x.get(k) is not None} or None,
                         "summary": ast_summary_of(c, m) or None},
            "wish": wish or None}


def _report_input(c, uid, aid, lid, b):
    """The status report of list lid as the AGENT sees it (no comments, notes, names) + the fixed Markdown text."""
    from ..lists.report import project_status, report_period, status_markdown, time_allowed, _time_of
    from ..collab.liste2eguard import le2b_net
    frm, to = report_period({k: b.get(k) for k in ("from", "to", "days") if b.get(k) not in (None, "")})
    lg = b.get("lang") or None
    if lg and lg != "en" and lg not in LANGS:
        raise BadInput(tr("Invalid value: {0}", "lang"))
    d = project_status(c, lid, aid, frm=frm, to=to, with_time=False)
    if time_allowed(c, uid):  # the tracked hours the person sees in the dialog, as totals only (no task titles)
        t = _time_of(c, lid, uid, frm, to)
        d["time"] = {k: t[k] for k in ("seconds", "rounded", "rounding")} if t else None
    d["markdown"] = le2b_net(status_markdown(d, lg))
    return {"report": d, "lang": lg, "wish": b.get("wish") or None}, frm, to


def ast_request(c, uid, b):
    """POST /api/proposals for the kinds of this module -> a proposal job + job_request to the chosen agent."""
    from ..agents.usage import usage_block
    from ..collab.liste2eguard import le2b_list_locked, le2b_off
    kind = b.get("kind")
    common = ("agent_id", "kind", "wish")
    try:
        aid = int(b.get("agent_id") or 0)
    except (TypeError, ValueError):
        aid = 0
    wish = _p_str(b.get("wish"), "wish", AST_WISH_MAX, line=False) or None
    tid = lid = None
    oid = doc_id = None
    if kind == "office_text":
        _p_keys(b, "", (*common, "doc_id", "field"))
        from ..office.model import office_org
        oid, r = _office_doc(c, uid, office_org(c, uid), b.get("doc_id"))
        if r["kind"] not in AST_DOC_KINDS:
            raise BadInput(tr("Invalid value: {0}", "doc_id"))
        field = b.get("field") or "intro"
        if field not in AST_FIELDS:
            raise BadInput(tr("Invalid value: {0}", "field"))
        from ..office.ledger import ofx_need_editable
        ofx_need_editable(r)
        ok = [a for a in ast_office_agents(c, uid, oid) if a["user_id"] == aid]
        if not ok:
            return err(tr(AST_NO_AGENT), 404)
        inp = _office_input(c, oid, r, field, wish)
        title, doc_id = tr(AST_TITLES[kind], r["number"] or r["project_title"] or tr("Draft")), r["id"]
    elif kind == "doc_summary":
        _p_keys(b, "", (*common, "doc_id"))
        ags, n = ast_doc_agents(c, uid, _iid(b.get("doc_id"), "doc_id"))
        if not [a for a in ags if a["user_id"] == aid]:
            return err(tr(AST_NO_AGENT), 404)
        oid = _doc_area(c, uid, n)
        inp = _doc_input(c, aid, n, wish)
        title = tr(AST_TITLES[kind], n["name"][:80])
    else:
        _p_keys(b, "", (*common, "list_id", "from", "to", "days", "lang"))
        from ..core.access import need_list
        lid = _iid(b.get("list_id"), "list_id")
        need_list(c, lid, write=False)
        if le2b_list_locked(c, lid):  # 2.64.1 B (#1817): agents never get texts of a list with the lock
            return err(le2b_off(), 409)
        if not [a for a in ast_list_agents(c, uid, lid) if a["user_id"] == aid]:
            return err(tr(AST_NO_AGENT), 404)
        inp, frm, to = _report_input(c, uid, aid, lid, {**b, "wish": wish})
        title = tr(AST_TITLES[kind], inp["report"]["list"]["name"][:80])
    a = agent_row(c, aid)
    if usage_block(c, aid):
        return err(tr("{0} reached its usage limit", a["display_name"] or a["username"]), 409)
    if c.execute("SELECT COUNT(*) FROM agent_jobs WHERE user_id=? AND kind IS NOT NULL AND state IN ('running','waiting')",
                 (uid,)).fetchone()[0] >= PROP_OPEN_MAX:
        return err(tr("You have {0} open proposal requests: apply or discard some first", PROP_OPEN_MAX), 429)
    ts = iso(now_utc())
    jid = insert_id(c, """INSERT INTO agent_jobs(agent_id,task_id,user_id,title,state,log,created_at,updated_at,kind,input,prop_state,list_id)
                       VALUES(?,?,?,?,'running','',?,?,?,?,'requested',?)""",
                    (aid, tid, uid, title[:JOB_TITLE_MAX], ts, ts, kind, json.dumps(inp, ensure_ascii=False), lid))
    if oid:  # one line in the office log: the agent reads the document's data for this person (no contents)
        from ..office.agentdocs import ofa_log
        ofa_log(c, oid, aid, False, "doc" if kind == "office_text" else "document", doc_id=doc_id, uid=uid)
    j = c.execute("SELECT * FROM agent_jobs WHERE id=?", (jid,)).fetchone()
    agent_emit(c, aid, "job_request", {"job": job_dict(c, j), "kind": kind, "input": inp, "limits": {**PROP_LIMITS, **AST_LIMITS},
                                       "requested_by": {"id": uid, "name": user_names(c, [uid]).get(uid, "")}})
    bump(c)
    c.commit()
    print("proposal request", jid, kind, "agent", aid, "by user", uid, flush=True)
    return jsonify(job_dict(c, j)), 201


AST_LIMITS = {"text_max": PROP_TEXT_MAX, "summary_text_max": AST_SUMMARY_MAX}


# ---------------------------------------------------------------- the agent's answer
def ast_validate(kind, b, inp):
    """prop_validate: office_text {field?, text}; doc_summary / report {text}. Unknown fields 400."""
    from ..office.model import TEXT_MAX
    if kind == "office_text":
        _p_keys(b, "", ("kind", "summary", "field", "text"))
        f = b.get("field") or inp.get("field")
        if f != inp.get("field"):
            raise BadInput(tr("Invalid value: {0}", "field"))
        return {"field": f, "text": _clean(b.get("text"), "text", TEXT_MAX, True)}
    _p_keys(b, "", ("kind", "summary", "text"))
    return {"text": _clean(b.get("text"), "text", AST_SUMMARY_MAX if kind == "doc_summary" else PROP_TEXT_MAX, True)}


def ast_need_agent(c, j, aid):
    """Before the agent's proposal is stored: its office switches still on (office kinds), the list still shared (report)."""
    from ..office.agentdocs import ofa_agent_ok, ofa_area
    if j["kind"] == "report":
        if not list_role(c, j["list_id"], aid):
            raise Denied(403)
        return
    from ..api.scopes import need_scope
    need_scope("office")  # as every office route of an agent
    with system_ctx(c):  # the agent's switch, its area and the area's privacy switch (structure; an agent's token does not see the settings of a personal office)
        a = agent_row(c, aid)
        ok = ofa_agent_ok(c, aid, ofa_area(c, a))
    if not ok:
        from ..office.agentdocs import OFA_OFF
        raise Denied(403, tr(OFA_OFF))


# ---------------------------------------------------------------- the person takes it over
def _text_of(j, ed):
    """The (edited) text of the card; the stored proposal's when the person did not touch it."""
    prop = json.loads(j["proposal"])
    e = (ed or {}).get("0") or {}
    if not isinstance(e, dict) or any(k != "text" for k in e):
        raise BadInput(tr("Invalid value: {0}", "edits"))
    return prop, e.get("text", prop["text"])


def _office_target(c, j):
    """(oid, document row) of an office_text job for the signed-in person; 403 / 404 as for the document itself."""
    from ..office.agentdocs import ofa_area
    with system_ctx(c):  # the agent's settings row (structure)
        a = agent_row(c, j["agent_id"])
    inp = json.loads(j["input"] or "{}")
    return _office_doc(c, g.user["id"], ofa_area(c, a), (inp.get("doc") or {}).get("id"))


def _doc_target(c, j, write=True):
    from ..files.store import need_node
    from ..docs import store as S
    inp = json.loads(j["input"] or "{}")
    nid = _iid((inp.get("document") or {}).get("id"), "doc_id")
    n = need_node(c, nid, write=write)
    m = S.meta_row(c, nid)
    if not m:
        raise Denied(404)
    return n, m


def ast_summary_of(c, m):
    from ..docs import store as S
    try:
        v = m["summary"]
    except (KeyError, IndexError):
        return ""
    return S.doc_open(c, m["ws"], "doc_meta.summary", v or "") or ""


def _set_office(c, oid, r, field, text):
    from ..office.ledger import ofx_diff, ofx_log
    c.execute(f"UPDATE office_docs SET {field}=?, updated_at=? WHERE id=? AND org_id=?", (text, iso(now_utc()), r["id"], oid))
    ofx_log(c, oid, "update", doc_id=r["id"], detail=ofx_diff({field: r[field]}, {field: text}))


def _set_summary(c, m, text):
    from ..docs import store as S
    c.execute("UPDATE doc_meta SET summary=?, updated_at=? WHERE node_id=?",
              (S.doc_seal(c, m["ws"], "doc_meta.summary", text), iso(now_utc()), m["node_id"]))


def ast_run(c, j, sel, ed, extra, rec):
    """Take it over as the person: office_text writes the field of the draft (409 when finalised / sent), doc_summary the
    document's summary (the person needs the right edit), report keeps the text with the job."""
    from ..office.ledger import ofx_need_editable
    from ..office.model import TEXT_MAX
    kind = j["kind"]
    prop, text = _text_of(j, ed)
    if kind == "office_text":
        text = _clean(text, "text", TEXT_MAX, True)
        oid, r = _office_target(c, j)
        ofx_need_editable(r)
        f = prop["field"]
        rec["office"] = {"doc": r["id"], "field": f, "before": r[f] or "", "after": text}
        _set_office(c, oid, r, f, text)
    elif kind == "doc_summary":
        text = _clean(text, "text", AST_SUMMARY_MAX, True)
        n, m = _doc_target(c, j)
        rec["document"] = {"id": n["id"], "before": ast_summary_of(c, m), "after": text}
        _set_summary(c, m, text)
    else:
        rec["text"] = _clean(text, "text", PROP_TEXT_MAX, True)
        rec["list"] = None
    return rec


def ast_undo(c, j, rec, back=True):
    """Undo (back) / redo: the old text comes back unless someone changed the field since (then skipped)."""
    kind, skipped, n = j["kind"], [], 0
    if kind == "office_text":
        from ..office.ledger import ofx_need_editable
        o = rec["office"]
        try:
            oid, r = _office_target(c, j)
            ofx_need_editable(r)
        except Denied:
            return 0, [j["title"][:40]]
        want, now = (o["before"], o["after"]) if back else (o["after"], o["before"])
        if (r[o["field"]] or "") != now:
            return 0, [j["title"][:40]]
        _set_office(c, oid, r, o["field"], want)
        n = 1
    elif kind == "doc_summary":
        o = rec["document"]
        try:
            _, m = _doc_target(c, j)
        except Denied:
            return 0, [j["title"][:40]]
        want, now = (o["before"], o["after"]) if back else (o["after"], o["before"])
        if ast_summary_of(c, m) != now:
            return 0, [j["title"][:40]]
        _set_summary(c, m, want)
        n = 1
    else:
        n = 1  # the report text only stops (or starts again) being used by the dialog
    if not back:
        rec.update(undone=False)
    return n, skipped


def ast_result(rec):
    return {"changed": 1 if (rec.get("office") or rec.get("document") or rec.get("text")) else 0, "created": 0}


def ast_view_extra(c, j):
    """For the card: the target as it is now (the current text, whether taking it over still works)."""
    out = {"target": None}
    try:
        if j["kind"] == "office_text":
            oid, r = _office_target(c, j)
            f = json.loads(j["input"] or "{}").get("field")
            out["target"] = {"doc_id": r["id"], "kind": r["kind"], "number": r["number"] or "", "field": f, "text": r[f] or "",
                             "editable": not (r["locked_at"] or r["status"] == "sent")}
        elif j["kind"] == "doc_summary":
            n, m = _doc_target(c, j)
            out["target"] = {"doc_id": n["id"], "name": n["name"], "text": ast_summary_of(c, m), "editable": True}
        else:
            rec = json.loads(j["applied"] or "null") or {}
            out["target"] = {"list_id": j["list_id"], "text": rec.get("text") or "", "editable": True}
    except (Denied, BadInput):
        out["target"] = {"editable": False, "gone": True}
    return out


# ---------------------------------------------------------------- the status report dialog and the document sheet
def ast_report_extra(c, d, lid, uid):
    """GET /api/lists/<id>/status-report (people): + agents (who may word it), agent_text (the text taken over for this
    period, else None: the fixed text stays the default)."""
    d["agents"] = [_pub(c, a) for a in ast_list_agents(c, uid, lid)] if not g.get("auth_via") == "token" else []
    d["agent_text"] = None
    rows = c.execute("""SELECT id, input, applied FROM agent_jobs WHERE user_id=? AND list_id=? AND kind='report' AND prop_state='applied'
                        ORDER BY id DESC LIMIT 20""", (uid, lid)).fetchall()
    for r in rows:
        rec = json.loads(r["applied"] or "null") or {}
        rp = (json.loads(r["input"] or "{}").get("report") or {})
        if rec.get("undone") or rp.get("from") != d["from"] or rp.get("to") != d["to"]:
            continue
        d["agent_text"] = {"job": r["id"], "text": rec.get("text") or "", "at": rec.get("at")}
        break
    return d


def ast_doc_extra(c, d, m):
    """doc_json: the document's summary (a person's take-over of an agent's draft), '' without one."""
    d["summary"] = ast_summary_of(c, m)
