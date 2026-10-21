"""2.120.0 B (#2088): the customer's documents in the customer portal (module "portal" + office).

With the office setting portal_docs on (default off; the admin of an organisation's office, a person without organisation
for the personal office) /portal shows -- next to the reports -- the quotations, invoices and credit notes of the signed-in
address in the portal's space: the documents of the clients of that space whose e-mail or e-mail for invoices is the
address (pt_email_hash, the same keyed hash as the sign-in). Only sent documents (a quotation sent / accepted / declined,
an invoice or credit note finalised and sent or paid), never a draft, never a reminder, never another client's, space's
or person's. Each one opens as PDF through /portal/docs/<id>/pdf: the stored file as it was sent (else rendered from its
snapshot like the approval page does), any doc that is not in the list answers 404.

The portal's space is the sign-in's: (org_id, NULL) = that organisation's office, (NULL, owner_id) = the owner's personal
office (orgs.personal_of). Access stays the sign-in link by mail of team/portal.py; the office can send one to a client
("Send portal link", POST /api/office/clients/<cid>/portal-link) -- the same portal_logins row, rate limits and cookie.
No new account, no new sign-in way. Switched off (setting or public links) = the portal is exactly as before."""
import html
import re
import secrets
from datetime import timedelta

from flask import g, jsonify

from ..core.config import app, APP_NAME, PUBLIC_URL
from ..core.db import body, db, err, iso, now_utc
from ..core.i18n import N_, tr
from ..core.pg import system_ctx
from ..core.access import acx_anon_bind, Denied
from ..accounts.session import _accept_lang, _token_hash, rate_ip
from ..lists.public import PUB_ACTOR, pub_gone, pub_limited, public_links_on
from ..team.portal import (PT_LOGIN_ADDR, PT_LOGIN_SPACE, PT_LOGIN_TTL, PT_LOGIN_WIN, PT_VIEW_RATE, _pt_mail_html, pt_cookie_read,
                           pt_day, pt_email_hash, pt_email_norm)
from .model import office_settings, pb_cl_sql, pb_owner

KP_KINDS = ("offer", "invoice", "credit")
KP_MAX = 200
KP_SIGN_MAX = 20           # quotations checked for an open approval link per page (each one renders the quotation)
KP_KIND_TXT = {"offer": N_("Quotation"), "invoice": N_("Invoice"), "credit": N_("Credit note")}
KP_STATE_TXT = {"sent": N_("Open|payment state"), "issued": N_("Open|payment state"), "partial": N_("Partly paid"), "paid": N_("Paid"), "overdue": N_("Overdue"),
                "cancelled": N_("Cancelled|invoice"), "accepted": N_("Accepted"), "declined": N_("Declined"), "credit": N_("Sent")}
# the visible documents: sent quotations; finalised invoices / credit notes that went out (sent_at) or are paid;
# 2.144.10 (#2576, review): never a trial document
KP_SQL = ("trial=0 AND kind IN ('offer','invoice','credit') AND status<>'draft' AND ((kind='offer' AND status IN ('sent','accepted','declined')) "
          "OR (kind<>'offer' AND locked_at IS NOT NULL AND (sent_at IS NOT NULL OR status IN ('sent','paid'))))")


def kp_area(c, org_id, owner_id):
    """The office area (orgs.id) of a portal space, or None: the organisation itself, for a private space the owner's
    personal office (only while the owner's account is enabled)."""
    if org_id:
        return int(org_id)
    if not owner_id:
        return None
    with system_ctx(c):  # instance structure: which hidden orgs row is the owner's personal office (one row, by owner)
        r = c.execute("SELECT o.id FROM orgs o JOIN users u ON u.id=o.personal_of WHERE o.personal_of=? AND u.disabled=0",
                      (int(owner_id),)).fetchone()
    return r[0] if r else None


def kp_on(c, oid):
    """Documents show in the portal of office area oid (setting portal_docs, public links on)."""
    return bool(oid) and public_links_on(c) and bool(office_settings(c, oid).get("portal_docs"))


def kp_bind(c, who):
    """(office area, client ids) of a portal cookie (email_hash, org_id, owner_id) with the request bound as nobody to
    exactly that area -- or (None, []) when the documents are off. The clients: those of the area whose e-mail or e-mail
    for invoices is the signed-in address."""
    eh, org_id, owner_id = who
    oid = kp_area(c, org_id, owner_id)
    if not oid:
        return None, []
    acx_anon_bind(c, oid)  # nobody, inside exactly the office area of the sign-in's space
    g.user, g.auth_via = PUB_ACTOR, "public"
    if not kp_on(c, oid):
        return None, []
    rows = c.execute(f"SELECT id, email, email_invoice FROM clients WHERE {pb_cl_sql(c, oid)} AND archived=0").fetchall()
    return oid, [r["id"] for r in rows if eh and eh in (pt_email_hash(c, r["email"]), pt_email_hash(c, r["email_invoice"]))]


def kp_login_docs(c, r):
    """2.120.0 (#2088): the button page of a sign-in link names documents instead of reports when its space shows them
    (portal_logins row r; bound as nobody to exactly that area, like kp_bind)."""
    oid = kp_area(c, r["org_id"], r["owner_id"])
    if not oid:
        return False
    acx_anon_bind(c, oid)
    return kp_on(c, oid)


def kp_docs(c, oid, cids, did=None):
    """The visible documents of clients cids in area oid (newest first), or the one with id did."""
    if not oid or not cids:
        return []
    q = f"SELECT * FROM office_docs WHERE org_id=? AND client_id IN ({','.join('?' * len(cids))}) AND {KP_SQL}"
    args = [oid, *cids]
    if did is not None:
        q += " AND id=?"
        args.append(int(did))
    return c.execute(q + " ORDER BY date DESC, id DESC LIMIT ?", args + [KP_MAX]).fetchall()


def kp_sign_url(c, oid, d):
    """The open approval page of quotation d (office/signoff.py), or None."""
    from ..core.db import parse_iso
    from .signoff import sig_check, sig_url
    r = c.execute("SELECT * FROM office_signoffs WHERE org_id=? AND doc_id=? AND kind='offer' AND state='open' AND revoked_at IS NULL "
                  "ORDER BY id DESC LIMIT 1", (oid, d["id"])).fetchone()
    if not r or (r["expires_at"] and parse_iso(r["expires_at"]) <= now_utc()):
        return None
    try:
        if sig_check(c, r):
            return None
    except Denied:
        return None
    return sig_url(c, r)


def kp_items(c, oid, rows, lg):
    """The portal's list entries of document rows: [{id, kind, title, sub, state, state_text, sign_url}]."""
    from .calc import fmt_money
    from .docs import _j
    from .invoices import inv_money_fields, inv_paid_map, inv_state
    pm = inv_paid_map(c, oid, [r["id"] for r in rows if r["kind"] in ("invoice", "credit")])
    out, signs = [], 0
    for r in rows:
        t = _j(r["totals"], {})
        cur, dl = r["currency"] or "EUR", r["lang"] or "de"
        st = inv_state(r, pm) if r["kind"] != "offer" else r["status"]
        if r["kind"] == "credit" and st not in ("paid", "cancelled"):
            st = "credit"  # a credit note is not "open" for the customer: it was sent
        sub = [pt_day(r["date"] or "", lg), r["project_title"] or "", fmt_money(t.get("gross") or 0, dl, cur)]
        if r["kind"] == "invoice" and st in ("sent", "issued", "partial", "overdue"):
            mf = inv_money_fields(r, pm)
            if st == "partial":
                sub.append(tr("{0} open", fmt_money(mf["open"], dl, cur), lg=lg))
            if r["due_date"]:
                sub.append(tr("due {0}", pt_day(r["due_date"], lg), lg=lg))
        url = None
        if r["kind"] == "offer" and st == "sent" and signs < KP_SIGN_MAX:
            signs += 1
            url = kp_sign_url(c, oid, r)
        out.append({"id": r["id"], "kind": r["kind"], "title": f'{tr(KP_KIND_TXT[r["kind"]], lg=lg)} {r["number"] or ""}'.strip(),
                    "sub": " · ".join(x for x in sub if x), "state": st, "state_text": tr(KP_STATE_TXT.get(st, "Open|payment state"), lg=lg), "sign_url": url})
    return out


def kp_portal_html(c, who, lg):
    """The documents section of /portal, or None when the documents are off for the sign-in's space (the page stays as before)."""
    oid, cids = kp_bind(c, who)
    if not oid:
        return None
    e = html.escape
    items = kp_items(c, oid, kp_docs(c, oid, cids), lg)
    li = []
    for x in items:
        cls = {"paid": "done", "accepted": "done", "partial": "progress", "overdue": "late"}.get(x["state"], "open")
        li.append(f'<li><a href="/portal/docs/{x["id"]}/pdf"><b>{e(x["title"])}</b><span class="sub">{e(x["sub"])}</span></a>'
                  + (f'<a class="kpgo" href="{e(x["sign_url"])}">{e(tr("Review and approve", lg=lg))}</a>' if x["sign_url"] else "")
                  + f'<span class="ptst ptst-{cls}">{e(x["state_text"])}</span></li>')
    return (f'<h2>{e(tr("Documents", lg=lg))}</h2>'
            + (f'<ul class="ptall kpdocs">{"".join(li)}</ul>' if li else f'<p class="empty">{e(tr("No documents for this address.", lg=lg))}</p>'))


@app.get("/portal/docs/<int:did>/pdf")
def kp_pdf(did):
    """The PDF of one visible document of the signed-in address (404 for anything else, also without cookie / switched off)."""
    from .pdfweb import _file_response, _render, _stored_or_missing, epdf_name
    from ..core.orgcrypt import oc_read_file
    from ..api.v1 import hit_limit
    c = db()
    lg = _accept_lang()
    if hit_limit("ptv:" + rate_ip(), PT_VIEW_RATE):
        return pub_limited(lg)
    who = pt_cookie_read(c) if public_links_on(c) else None
    oid, cids = kp_bind(c, who) if who else (None, [])
    rows = kp_docs(c, oid, cids, did) if oid else []
    if not rows:
        return pub_gone(lg)
    d = rows[0]
    try:
        p = _stored_or_missing(c, oid, d, "pdf")
    except Denied:  # the stored file of a finalised document is gone (logged): no new rendering that could differ
        return pub_gone(lg)
    data = oc_read_file(c, p) if p else _render(c, oid, d)[0]
    resp = _file_response(data, epdf_name(d) + ".pdf", "application/pdf", inline=True)
    resp.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


# ---- the office side: send a client the sign-in link of the portal
def kp_space(c, oid):
    """The portal space (org_id, owner_id) of office area oid."""
    owner = pb_owner(c, oid)
    return (None, owner) if owner is not None else (oid, None)


@app.post("/api/office/clients/<int:cid>/portal-link")
def kp_link_send(cid):
    """{to?: "invoice" | "main"} mails the client a sign-in link to the customer portal (members of the office; the setting
    portal_docs on, mail set up). The address is one of the client's own (default: the e-mail for invoices, else the e-mail)."""
    from .docs import _ctx
    from .invoices import _mail
    from .ledger import ofx_company, ofx_log
    from ..admin.hosting import mail_budget
    from ..api.v1 import hit_limit
    from ..integrations.mail import MAIL_OUT_ON
    c, uid, oid = _ctx()
    cl = c.execute(f"SELECT * FROM clients WHERE id=? AND {pb_cl_sql(c, oid)}", (cid,)).fetchone()
    if not cl:
        raise Denied(404)
    b = body()
    b = b if isinstance(b, dict) else {}
    if not public_links_on(c) or not office_settings(c, oid).get("portal_docs"):
        raise Denied(409, tr("Documents in the customer portal are switched off in the office settings"))
    if not MAIL_OUT_ON:
        raise Denied(409, tr("Sending e-mail is not set up on this server (KALMIDO_SMTP_HOST)"))
    inv, main = pt_email_norm(cl["email_invoice"]), pt_email_norm(cl["email"])
    em = (main if b.get("to") == "main" else inv if b.get("to") == "invoice" else (inv or main)) or ""
    if not em:
        return err(tr("The client has no e-mail address"))
    eh = pt_email_hash(c, em)
    org_id, owner_id = kp_space(c, oid)
    space = f"{org_id or ''}:{owner_id or ''}"
    full = False
    if (hit_limit(f"ptla:{eh}", PT_LOGIN_ADDR, PT_LOGIN_WIN) or (full := hit_limit(f"ptls:{space}", PT_LOGIN_SPACE, PT_LOGIN_WIN))
            or not mail_budget(c, uid, em)):
        if full:  # 2.138.4 C (#2380): the space's budget is used up: its admins / owner get a News item
            from ..team.portal import pt_limit_note
            pt_limit_note(c, org_id, owner_id)
            c.commit()
        raise Denied(429, tr("Too many portal links for this address; try again in an hour"))
    tok = secrets.token_urlsafe(32)
    now = now_utc()
    c.execute("INSERT INTO portal_logins(email_hash,org_id,owner_id,token_hash,created_at,expires_at) VALUES(?,?,?,?,?,?)",
              (eh, org_id, owner_id, _token_hash(tok), iso(now), iso(now + timedelta(seconds=PT_LOGIN_TTL))))
    co = ofx_company(c, oid)
    name = (co.get("name") or "").split("\n")[0].strip() or (office_settings(c, oid).get("company") or {}).get("name") or APP_NAME
    lg = "en" if office_settings(c, oid).get("lang") == "en" else "de"
    url = f"{PUBLIC_URL}/portal/login/{tok}"
    lines = [tr("Hello,", lg=lg), tr("{0} sends you the link to your quotations, invoices and their payment status. It is valid for 30 minutes and can be used once.", name, lg=lg),
             tr("If you did not expect it, you can ignore this mail.", lg=lg)]
    rt = co.get("email") or ""
    rt = rt if re.fullmatch(r"[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+", rt) else None
    ofx_log(c, oid, "portal_link", target="client", detail={"client": cid, "to": em})
    _mail(em, tr("Your documents: sign-in link", lg=lg), "\n\n".join(lines[:2]) + f"\n\n{url}\n\n" + lines[2],
          html_body=_pt_mail_html(lines[:2], url, tr("Show my documents", lg=lg), html.escape(lines[2])), from_name=name[:80], reply_to=rt)
    c.commit()
    return jsonify(ok=True, to=em)
