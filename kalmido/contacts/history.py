"""2.119.1 B (#2083): the history on a contact's card -- the filed e-mails from / to the contact's addresses (hub/hubmail.py),
the quotations, invoices and credit notes of the clients the contact is a contact person of (office_docs) and the events
the contact attends, newest first, in pages. Read only, nothing is summarised.

Shows only what the person sees anyway: the contact itself (its address book, module Contacts), a mail only when
hbm_can lets the person read it (never one filed with a health or budget list), documents only with the module Office
and a role in the client's office area (an organisation's office: its members; a private client: the person's own
personal office) and only of clients the person may open (ckl_contact_clients), events only when need_event allows them.
People only: agents and kid accounts get 403 (no v1 route, no MCP tool)."""
import re

from flask import g, jsonify, request

from ..core.config import app
from ..core.db import db
from ..core.access import Denied, need_feat
from ..core.i18n import tr
from ..accounts.session import me

CTK_PAGE = 20           # entries per page (the card's "More" asks for the next one)
CTK_MAILS_SCAN = 1000   # newest filed mails uid may reach, looked at for the contact's addresses (sealed: no SQL match)
CTK_SOURCE_MAX = 200    # entries per source (mails, documents, events) at most
CTK_DOC_KINDS = ("offer", "invoice", "credit")


def ctk_mails(c, uid, emails):
    """The filed mails uid may read whose sender or recipients carry one of emails (lower case) -> entries."""
    if not emails:
        return []
    from ..hub.hubmail import _open, hbm_can
    from ..team.clients import client_rows
    # 2.119.1 review F1 (#2083): only the mails uid can reach at all (own, of a visible client, of a list with a possible
    # role; never health / budget lists) are read and opened; hbm_can below stays the real check
    cids = [r["id"] for r in client_rows(c, uid)]
    q = ("SELECT * FROM hub_mails WHERE deleted_at IS NULL AND (owner_id=? OR list_id IN (SELECT l.id FROM lists l "
         "WHERE l.deleted_at IS NULL AND COALESCE(l.life, '') NOT IN ('health', 'budget') AND (l.owner_id=? "
         "OR l.id IN (SELECT list_id FROM list_members WHERE user_id=?) OR l.org_id IN (SELECT org_id FROM org_members WHERE user_id=?)))")
    args = [uid, uid, uid, uid]
    if cids:
        q += f" OR client_id IN ({','.join('?' * len(cids))})"
        args += cids
    rows = c.execute(q + ") ORDER BY COALESCE(sent_at, created_at) DESC, id DESC LIMIT ?", [*args, CTK_MAILS_SCAN]).fetchall()
    lists, out = {}, []
    for m in rows:
        if m["list_id"]:
            if m["list_id"] not in lists:
                r = c.execute("SELECT life FROM lists WHERE id=?", (m["list_id"],)).fetchone()
                lists[m["list_id"]] = bool(r) and (r["life"] or "") not in ("health", "budget")
            if not lists[m["list_id"]]:
                continue  # health / budget lists never show here
        if not hbm_can(c, uid, m):
            continue
        d = _open(c, m)
        frm = (d["from_addr"] or "").strip().lower()
        # 2.119.1 review F6 (#2083): whole addresses, not substrings ("a@b.de" is not in "mia@b.de")
        tos = {x.strip("<>\"'") for x in re.split(r"[,;\s]+", (d["to_addrs"] or "").lower()) if "@" in x}
        if frm not in emails and not (emails & tos):
            continue
        out.append({"kind": "mail", "id": m["id"], "title": d["subject"] or "", "sub": d["from_name"] or d["from_addr"] or "",
                    "at": m["sent_at"] or m["created_at"], "incoming": frm in emails})
        if len(out) >= CTK_SOURCE_MAX:
            break
    return out


def ctk_docs(c, uid, clients):
    """The quotations / invoices / credit notes of the given clients ({client_id, name}) in an office area where uid has a
    role (module Office on) -> entries."""
    from ..office.model import office_on, office_role, pb_personal
    from ..office.docs import doc_brief
    from ..office.invoices import inv_paid_map
    from ..team.clients import client_rows
    if not clients or not office_on(c, uid):
        return []
    mine = {r["id"]: r for r in client_rows(c, uid)}
    areas = {}
    for x in clients:
        cl = mine.get(x["client_id"])
        if not cl:
            continue
        oid = cl["org_id"] or (pb_personal(c, uid, create=False) if cl["created_by"] == uid else None)
        if oid and office_role(c, uid, oid):
            areas.setdefault(oid, set()).add(cl["id"])
    out = []
    for oid, cids in areas.items():
        pm = inv_paid_map(c, oid)
        ids = sorted(cids)
        for r in c.execute(f"SELECT * FROM office_docs WHERE org_id=? AND kind IN ({','.join('?' * len(CTK_DOC_KINDS))}) "
                           f"AND client_id IN ({','.join('?' * len(ids))}) ORDER BY date DESC, id DESC LIMIT ?",
                           [oid, *CTK_DOC_KINDS, *ids, CTK_SOURCE_MAX]).fetchall():
            b = doc_brief(r, pm)
            name = mine[r["client_id"]]["name"]
            out.append({"kind": r["kind"], "id": r["id"], "title": b["number"] or "", "sub": " · ".join(x for x in (b["project_title"], name, b["status_text"],
                        b["gross_text"]) if x), "at": r["date"] or r["created_at"]})
    return out


def ctk_events(c, uid, kid):
    from ..events.model import need_event
    out = []
    for e in c.execute("""SELECT e.id FROM events e WHERE e.id IN (SELECT a.event_id FROM event_attendees a WHERE a.contact_id=?)
                          AND e.deleted_at IS NULL ORDER BY e.first_day DESC LIMIT ?""", (kid, CTK_SOURCE_MAX)):
        try:
            er, _ = need_event(c, e[0], uid=uid)
        except Denied:
            continue
        out.append({"kind": "event", "id": er["id"], "title": er["title"], "sub": "", "at": er["start"], "all_day": bool(er["all_day"])})
    return out


@app.get("/api/contacts/<int:cid>/history")
def ctk_history(cid):
    """?offset= -> {items: [{kind: mail|offer|invoice|credit|event, id, title, sub, at, ...}], more, offset} newest first,
    CTK_PAGE per page; only what the person may see (see the module text)."""
    need_feat("contacts")
    u = g.user
    if u["kid"] or (u["kind"] or "user") == "agent":
        raise Denied(403, tr("Agents cannot use this endpoint"))
    c = db()
    uid = me()
    from .model import _jl, contact_visible
    r = contact_visible(c, cid, uid)
    if not r or r["kind"] == "group":
        raise Denied(404)
    try:
        off = max(0, min(int(request.args.get("offset") or 0), 10000))
    except ValueError:
        off = 0
    emails = {(x.get("value") or "").strip().lower() for x in _jl(r["emails"]) if isinstance(x, dict) and "@" in (x.get("value") or "")}
    from ..office.contacts_cl import ckl_contact_clients
    items = ctk_mails(c, uid, emails) + ctk_docs(c, uid, ckl_contact_clients(c, cid, uid)) + ctk_events(c, uid, cid)
    items.sort(key=lambda x: (x["at"] or "", x["kind"], x["id"]), reverse=True)
    return jsonify(items=items[off:off + CTK_PAGE], more=len(items) > off + CTK_PAGE, offset=off)
