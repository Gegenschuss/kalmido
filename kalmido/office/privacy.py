"""2.154.0 C (#2192): data protection sheets of a client: data processing agreement (DPA, Art. 28 GDPR), privacy information
(Art. 13 / 14) and consent, made from the client card, mailed to the client and taken back signed.

A sheet (office_privacy_sheets) is a document of office/doctpl.py (office_gen_docs) with a kind (dpa | info | consent) and
a status per client: open -> sent (mailed with the customer link to sign) -> signed | declined; the privacy information
needs no signature: handed (handed over) on sending. The text comes from the samples of doctpl_samples.py (DMA_SAMPLES
keys privacy_dpa / privacy_info / privacy_consent) or an own template; a text that still has [placeholders] stays a draft
and opens in the document editor, else the PDF is written and filed with the client at once (doctpl.dt_final's steps).

Ways back: the customer signs through the link (office/signoff.py, kind document: the status follows the document), the
signed PDF is uploaded in the client card (status signed), or the customer answers the mail: the reply address is the
server's mailbox (KALMIDO_IMAP_*) with the sheet's code as plus address and "[DS-<code>]" in the subject (code = 12
characters of secrets, sealed at rest and looked up by its SHA-256, never a counter). integrations/mail.py mail_import
hands every mail to dsb_mail_import first: a known code of a mailed sheet that wants a signature files the first PDF /
picture (size limit, the upload checks of files/store.py fs_put) into that sheet's office area only and sets "signed (by
mail, please check)" -- a person confirms (or sets the status back). Anything else goes on to the other importers.

Every route: office_gate + office_org with the admin of the office area (like doctpl.py; members, agents and kids 403,
objects of another area 404). Agents never send: there is no route for them. Kalmido calls no language model here."""
import hashlib
import re
import secrets
from datetime import timedelta

from flask import Response, g, jsonify, request

from ..core.config import app, MAX_FILE_MB, PUBLIC_URL
from ..core.pg import insert_id, system_ctx, write_lock
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields
from ..core.i18n import N_, tr
from ..core.db import body, bump, iso, local_now, now_utc
from ..core.access import Denied
from ..accounts.login import seal, unseal
from ..personal.timetrack import BadInput
from .doctpl import (DT_NOTE, _ctx, _iid, dt_client, dt_doc, dt_fill, dt_file, dt_hash, dt_kick, dt_lang, dt_pdf, dt_signed_sync,
                     dt_tpl, dt_values)
from .doctpl_samples import DMA_SAMPLES
from .model import pb_owner

# kind -> (label, sample key in DMA_SAMPLES, needs a signature)
DSB_KINDS = {"dpa": (N_("Data processing agreement"), "privacy_dpa", True),
             "info": (N_("Privacy information"), "privacy_info", False),
             "consent": (N_("Consent"), "privacy_consent", True)}
DSB_STATUS = {"open": N_("Open"), "sent": N_("Sent"), "handed": N_("Handed over"), "signed": N_("Signed"), "declined": N_("Declined")}
DSB_HINT_DPA = N_("Only needed when you process personal data on behalf of the client (Art. 28 GDPR).")
DSB_REVIEW = N_("Signed (by mail, please check)")
DSB_REPLY = N_("Reply received (please check)")  # 2.154.0 E (#2192): review=2, a reply that was not filed
DSB_CODE_ABC = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0 / O / 1 / I
DSB_CODE_LEN = 12
DSB_SUBJ_RE = re.compile(r"\[DS-([A-Za-z2-9]{12})\]")
DSB_PLUS_RE = re.compile(r"\+ds-([A-Za-z2-9]{12})@", re.I)
DSB_PLACEHOLDER_RE = re.compile(r"\[[^\[\]\n]{2,120}\]")
DSB_MAIL_MB = min(MAX_FILE_MB, 20)  # a signed sheet by mail: one PDF / picture up to this size
DSB_LINK = "[Link]"
LIST_MAX = 2000
DSB_LINK_DAYS = 30  # 2.239.0 D (#2874): a mailed signature link ends after this many days unless {expires} says otherwise


def dsb_sheet(c, oid, sid):
    r = c.execute("SELECT * FROM office_privacy_sheets WHERE id=? AND org_id=?", (_iid(sid, "id"), oid)).fetchone()
    if not r:
        raise Denied(404)
    return r


def dsb_code_hash(code):
    return hashlib.sha256(("dsb:" + code.upper()).encode()).hexdigest()


def dsb_code(c, r):
    """The sheet's mail code (plain): the sealed one, else a new one (stored). None when it cannot be read any more
    (a changed server key) -- then a new one too."""
    if r["code"]:
        try:
            return unseal(c, f"privacy-sheet:{r['id']}", r["code"])
        except Exception:  # noqa: BLE001 -- a changed server key: a new code below
            pass
    code = "".join(secrets.choice(DSB_CODE_ABC) for _ in range(DSB_CODE_LEN))
    c.execute("UPDATE office_privacy_sheets SET code=?, code_hash=? WHERE id=? AND org_id=?",
              (seal(c, f"privacy-sheet:{r['id']}", code), dsb_code_hash(code), r["id"], r["org_id"]))
    return code


def dsb_status_label(r):
    if r["review"] == 2:
        return tr(DSB_REPLY)
    return tr(DSB_REVIEW) if r["status"] == "signed" and r["review"] else tr(DSB_STATUS.get(r["status"], r["status"]))


def dsb_replies(c, oid):
    """2.209.0 C (#2589): the newest reply mail that was not filed per sheet, from the office log (dsb_reply_note):
    {sheet id: {at, from, subject, text}} -- the customer's words, data only (the client escapes them). 2.239.0 D (#2874):
    from the sheet (office_privacy_sheets.reply); log entries of older versions still carry the text."""
    import json
    out = {}
    for r in c.execute("SELECT id, reply FROM office_privacy_sheets WHERE org_id=? AND reply IS NOT NULL AND reply<>'' ORDER BY id DESC LIMIT ?",
                       (oid, LIST_MAX)):
        try:
            d = json.loads(unseal(c, f"privacy-reply:{r['id']}", r["reply"]))
        except Exception:  # noqa: BLE001 -- a changed server key: the reply cannot be read any more
            continue
        if isinstance(d, dict):
            out[r["id"]] = {k: str(d.get(k) or "") for k in ("at", "from", "subject", "text")}
    for r in c.execute("SELECT * FROM office_doc_log WHERE org_id=? AND action='privacy_reply' ORDER BY id DESC LIMIT ?", (oid, LIST_MAX)):
        try:
            d = json.loads(oc_dec_fields(c, oid, "office_doc_log", r).get("detail") or "{}")
        except (TypeError, ValueError):
            continue
        sid = d.get("privacy_sheet") if isinstance(d, dict) else None
        if isinstance(sid, int) and sid not in out and "text" in d:
            out[sid] = {"at": r["at"], "from": str(d.get("from") or ""), "subject": str(d.get("subject") or ""), "text": str(d.get("text") or "")}
    return out


def dsb_public(c, oid, r, gd=None, reply=None):
    """A sheet for the app; gd = its office_gen_docs row (read when not given); reply = its entry of dsb_replies."""
    if gd is None and r["gen_doc_id"]:
        gd = c.execute("SELECT id, status, title, node_id, signed_node_id, archived FROM office_gen_docs WHERE id=? AND org_id=?",
                       (r["gen_doc_id"], oid)).fetchone()
    k = DSB_KINDS.get(r["kind"]) or DSB_KINDS["info"]
    return {"id": r["id"], "client_id": r["client_id"], "kind": r["kind"], "kind_label": tr(k[0]), "sign": int(k[2]),
            "status": r["status"], "status_label": dsb_status_label(r), "review": int(r["review"] or 0), "signed_via": r["signed_via"],
            "sent_at": r["sent_at"], "signed_at": r["signed_at"], "signed_node_id": r["signed_node_id"] or (gd["signed_node_id"] if gd else None),
            "gen_doc_id": r["gen_doc_id"], "gen_status": gd["status"] if gd else "", "title": gd["title"] if gd else tr(k[0]),
            "node_id": gd["node_id"] if gd else None, "archived": int(r["archived"] or 0), "created_at": r["created_at"],
            "updated_at": r["updated_at"], "reply": reply}


def dsb_sync(c, oid, uid, rows):
    """The customer decided through the link (the document's status signed / declined): the sheet follows; the signed
    PDF is filed by doctpl.dt_signed_sync. -> True when something changed (the caller reads again)."""
    ids = [r["gen_doc_id"] for r in rows if r["gen_doc_id"] and r["status"] in ("open", "sent", "handed")]
    if not ids:
        return False
    gds = c.execute(f"SELECT * FROM office_gen_docs WHERE org_id=? AND id IN ({','.join('?' * len(ids))})", [oid] + ids).fetchall()
    dt_signed_sync(c, oid, uid, gds)
    st = {g_["id"]: g_["status"] for g_ in gds}
    done = False
    ts = iso(now_utc())
    for r in rows:
        s = st.get(r["gen_doc_id"])
        if r["status"] in ("open", "sent", "handed") and s in ("signed", "declined"):
            if s == "signed":
                c.execute("UPDATE office_privacy_sheets SET status='signed', signed_via='link', signed_at=?, review=0, updated_at=? "
                          "WHERE id=? AND org_id=?", (ts, ts, r["id"], oid))
            else:
                c.execute("UPDATE office_privacy_sheets SET status='declined', updated_at=? WHERE id=? AND org_id=?", (ts, r["id"], oid))
            done = True
    if done:
        c.commit()
    return done


def dsb_rows(c, oid, uid, client_id=None, archived=False):
    sql, args = "SELECT * FROM office_privacy_sheets WHERE org_id=?", [oid]
    if not archived:
        sql += " AND archived=0"
    if client_id is not None:
        sql += " AND client_id=?"
        args.append(client_id)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(LIST_MAX)
    rows = c.execute(sql, args).fetchall()
    if dsb_sync(c, oid, uid, rows):
        rows = c.execute(sql, args).fetchall()
    return rows


def dsb_mail_on():
    from ..integrations.mail import MAIL_IN_ON, MAIL_OUT_ON
    return bool(MAIL_OUT_ON), bool(MAIL_IN_ON)


@app.get("/api/office/privacy-sheets")
def dsb_list():
    """?client_id= (one client) &archived=1 &brief=1 (only the sheets) -> {sheets, kinds, templates, smtp, reply_in, note}."""
    c, uid, oid = _ctx()
    cid = dt_client(c, oid, request.args.get("client_id"))["id"] if request.args.get("client_id") else None
    rows = dsb_rows(c, oid, uid, cid, request.args.get("archived") == "1")
    gds = {}
    ids = sorted({r["gen_doc_id"] for r in rows if r["gen_doc_id"]})
    if ids:
        gds = {g_["id"]: g_ for g_ in c.execute("SELECT id, status, title, node_id, signed_node_id, archived FROM office_gen_docs "
                                                f"WHERE org_id=? AND id IN ({','.join('?' * len(ids))})", [oid] + ids)}
    reps = dsb_replies(c, oid) if rows else {}  # 2.209.0 C (#2589): the text of a reply at its sheet
    out = {"sheets": [dsb_public(c, oid, r, gds.get(r["gen_doc_id"]), reps.get(r["id"])) for r in rows]}
    if request.args.get("brief") != "1":
        smtp, rin = dsb_mail_on()
        tpls = c.execute("SELECT id, name, lang, sign FROM office_doc_templates WHERE org_id=? AND archived=0 ORDER BY lower(name), id LIMIT 500",
                         (oid,)).fetchall()
        out.update(kinds=[{"key": k, "label": tr(v[0]), "sign": int(v[2]), "hint": tr(DSB_HINT_DPA) if k == "dpa" else ""} for k, v in DSB_KINDS.items()],
                   templates=[{"id": t["id"], "name": t["name"], "lang": t["lang"]} for t in tpls],
                   statuses=[{"key": k, "label": tr(v)} for k, v in DSB_STATUS.items()], smtp=smtp, reply_in=rin, note=tr(DT_NOTE))
    return jsonify(out)


def dsb_finish(c, oid, uid, gid):
    """doctpl.dt_final's steps for a fresh document of a sheet: fill, freeze, PDF, file with the client. -> node id."""
    from .ledger import ofx_log
    from .terms import agb_gen_freeze
    d = dict(oc_dec_fields(c, oid, "office_gen_docs", dt_doc(c, oid, gid)))
    lang = dt_lang(c, oid, d.get("lang") or None)
    text, _miss = dt_fill(d["body"], dt_values(c, oid, lang, d["client_id"], None, None), mark=False)
    text = "\n".join(ln.rstrip() for ln in text.split("\n")).strip("\n")
    if not text.strip():
        raise BadInput(tr("The document has no text."))
    ts = iso(now_utc())
    d.update(body=text, body_hash=dt_hash(text), status="final", final_at=ts, lang=lang)
    nid = dt_file(c, oid, uid, d, dt_pdf(c, oid, d))
    vals = oc_enc_fields(c, oid, "office_gen_docs", {"body": text})
    c.execute("UPDATE office_gen_docs SET body=?, body_hash=?, status='final', node_id=?, final_at=?, lang=?, updated_at=? WHERE id=? AND org_id=?",
              (vals["body"], d["body_hash"], nid, ts, lang, ts, gid, oid))
    c.execute("UPDATE office_gen_docs SET terms=? WHERE id=? AND org_id=?", (agb_gen_freeze(c, oid, d["kind"], lang), gid, oid))
    ofx_log(c, oid, "gen_doc_final", target="gen_doc", detail={"gen_doc": gid, "title": d["title"], "body_hash": d["body_hash"], "node_id": nid})
    return nid


@app.post("/api/office/privacy-sheets")
def dsb_post():
    """{client_id, kind: dpa|info|consent, template_id?, lang?} -> 201 {sheet, edit}: a new sheet; its document is
    finished (PDF with the client) unless the text still has [placeholders] (edit = true: a draft for the editor)."""
    c, uid, oid = _ctx()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    kind = b.get("kind")
    if kind not in DSB_KINDS:
        raise BadInput(tr("Invalid value: {0}", "kind"))
    cl = dt_client(c, oid, b.get("client_id"))
    label, skey, sign = DSB_KINDS[kind]
    tid = None
    if b.get("template_id") not in (None, "", 0):
        t = dt_tpl(c, oid, b["template_id"])
        tid, lang = t["id"], dt_lang(c, oid, t["lang"])
        title, text = t["name"], t["body"]
    else:
        lang = dt_lang(c, oid, b.get("lang") or None)
        title, text = DMA_SAMPLES[skey][lang]
    ts = iso(now_utc())
    row = {"org_id": oid, "template_id": tid, "kind": "other",
           "title": title[:300], "body": text, "client_id": cl["id"], "lang": lang, "sign": int(sign), "status": "draft",
           "created_by": uid, "created_at": ts, "updated_at": ts}
    row = oc_enc_fields(c, oid, "office_gen_docs", row)
    gid = insert_id(c, f"INSERT INTO office_gen_docs({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    sid = insert_id(c, "INSERT INTO office_privacy_sheets(org_id, client_id, kind, gen_doc_id, status, created_by, created_at, updated_at) "
                       "VALUES(?,?,?,?,'open',?,?,?)", (oid, cl["id"], kind, gid, uid, ts, ts))
    filled = dt_fill(text, dt_values(c, oid, lang, cl["id"], None, None))[0]
    edit = bool(DSB_PLACEHOLDER_RE.search(filled))
    if not edit:
        dsb_finish(c, oid, uid, gid)
    bump(c)
    c.commit()
    if not edit:
        dt_kick()
    return jsonify(sheet=dsb_public(c, oid, dsb_sheet(c, oid, sid)), edit=edit), 201


@app.patch("/api/office/privacy-sheets/<int:sid>")
def dsb_patch(sid):
    """{status: open|sent|handed|signed|declined} by hand (e.g. handed over in person, declined on the phone, a mail that
    was no signature: back to sent). Setting it also ends "please check"."""
    c, uid, oid = _ctx()
    write_lock(c, f"office_privacy_{int(sid)}")
    dsb_sheet(c, oid, sid)
    b = body()
    st = b.get("status") if isinstance(b, dict) else None
    if st not in DSB_STATUS:
        raise BadInput(tr("Invalid value: {0}", "status"))
    ts = iso(now_utc())
    c.execute("UPDATE office_privacy_sheets SET status=?, review=0, signed_via=CASE WHEN ?='signed' THEN COALESCE(NULLIF(signed_via, ''), 'manual') "
              "ELSE signed_via END, signed_at=CASE WHEN ?='signed' THEN COALESCE(signed_at, ?) ELSE signed_at END, updated_at=? WHERE id=? AND org_id=?",
              (st, st, st, ts, ts, sid, oid))
    bump(c)
    c.commit()
    return jsonify(dsb_public(c, oid, dsb_sheet(c, oid, sid)))


@app.post("/api/office/privacy-sheets/<int:sid>/confirm")
def dsb_confirm(sid):
    """A person checked the signed sheet that came by mail (or a reply that was not filed): "please check" ends (the
    status stays)."""
    c, uid, oid = _ctx()
    r = dsb_sheet(c, oid, sid)
    if r["status"] != "signed" and r["review"] != 2:
        raise Denied(409, tr("Only a signed sheet can be confirmed"))
    c.execute("UPDATE office_privacy_sheets SET review=0, updated_at=? WHERE id=? AND org_id=?", (iso(now_utc()), sid, oid))
    bump(c)
    c.commit()
    return jsonify(dsb_public(c, oid, dsb_sheet(c, oid, sid)))


@app.delete("/api/office/privacy-sheets/<int:sid>")
def dsb_delete(sid):
    """Archives a sheet (its documents and files stay); POST .../restore takes it back (the client's undo)."""
    c, uid, oid = _ctx()
    dsb_sheet(c, oid, sid)
    c.execute("UPDATE office_privacy_sheets SET archived=1, updated_at=? WHERE id=? AND org_id=?", (iso(now_utc()), sid, oid))
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.post("/api/office/privacy-sheets/<int:sid>/restore")
def dsb_restore(sid):
    c, uid, oid = _ctx()
    dsb_sheet(c, oid, sid)
    c.execute("UPDATE office_privacy_sheets SET archived=0, updated_at=? WHERE id=? AND org_id=?", (iso(now_utc()), sid, oid))
    bump(c)
    c.commit()
    return jsonify(dsb_public(c, oid, dsb_sheet(c, oid, sid)))


# ---------------------------------------------------------------- mailing the sheet
def dsb_mail_parts(c, oid, r, d, link):
    """(to, subject, text, reply address or None, code) of the mail of sheet r (d = its decrypted document) as proposed;
    link = a signature link goes along: the text holds DSB_LINK where it goes."""
    from .contacts_cl import fk_contact
    from .ledger import ofx_company
    from ..integrations.mail import MAIL_IN_ON, mail_addr
    cl = dt_client(c, oid, r["client_id"])
    k = fk_contact(c, cl["id"])
    to = (k or {}).get("email") or cl.get("email_invoice") or cl.get("email") or ""
    sign = DSB_KINDS.get(r["kind"], DSB_KINDS["info"])[2]
    lg = "en" if d.get("lang") == "en" else "de"
    co = ofx_company(c, oid).get("name") or ""
    title = d.get("title") or tr(DSB_KINDS[r["kind"]][0], lg=lg)
    rin = sign and MAIL_IN_ON
    code = dsb_code(c, r) if rin else ""
    subject = f"{title} [DS-{code}]" if rin else title
    reply = (mail_addr(f"ds-{code}") or None) if rin else None
    parts = [tr("Hello,", lg=lg), tr("Please find attached our document “{0}”.", title, lg=lg)]
    if sign and link:
        parts.append(tr("You can sign it online here: {0}", DSB_LINK, lg=lg))
    if sign and rin:
        parts.append(tr("Or reply to this mail with the signed document as a PDF attached; please keep the subject as it is.", lg=lg))
    parts.append(tr("Kind regards", lg=lg) + ("\n" + co if co else ""))
    return to, subject, "\n\n".join(parts), reply, code


@app.get("/api/office/privacy-sheets/<int:sid>/mail")
def dsb_mail_get(sid):
    """The proposed mail of a finished sheet: {to, subject, text, smtp, reply_in, link: whether a signature link goes along}."""
    from ..lists.public import public_links_on
    c, uid, oid = _ctx()
    r = dsb_sheet(c, oid, sid)
    d = oc_dec_fields(c, oid, "office_gen_docs", dt_doc(c, oid, r["gen_doc_id"])) if r["gen_doc_id"] else None
    if not d or d["status"] == "draft":
        raise Denied(409, tr("Finish the document first"))
    sign = DSB_KINDS[r["kind"]][2]
    link = bool(sign and public_links_on(c))
    to, subject, text, reply, _code = dsb_mail_parts(c, oid, r, d, link)
    c.commit()  # a new code is kept
    smtp, rin = dsb_mail_on()
    return jsonify(to=to, subject=subject, text=text, smtp=smtp, reply_in=bool(rin and sign), link=link)


@app.post("/api/office/privacy-sheets/<int:sid>/send")
def dsb_send(sid):
    """{to, subject?, text?} mails the finished sheet (its PDF attached) to the client; a sheet to sign gets a new
    signature link ([Link] in the text, appended when it is missing) and the reply address with its code. Status: sent
    (handed for the privacy information). 409 without SMTP / not finished; 429 like the invoice mails."""
    from .invoices import _mail, h6c_send_budget, inv_clean_subject
    from .ledger import ofx_log
    from .signoff import SIG_PREFIX, sig_create, sig_expiry
    from ..files.store import fs_read, fs_role
    from ..lists.public import public_links_on
    from ..integrations.mail import MAIL_OUT_ON
    c, uid, oid = _ctx()
    write_lock(c, f"office_privacy_{int(sid)}")
    r = dsb_sheet(c, oid, sid)
    if not MAIL_OUT_ON:
        raise Denied(409, tr("Sending e-mail is not set up on this server (KALMIDO_SMTP_HOST)"))
    if r["archived"] or not r["gen_doc_id"]:
        raise Denied(409, tr("Finish the document first"))
    gd = dt_doc(c, oid, r["gen_doc_id"])
    d = dict(oc_dec_fields(c, oid, "office_gen_docs", gd))
    if d["status"] != "final" and not (d["status"] == "signed" and not DSB_KINDS[r["kind"]][2]):
        raise Denied(409, tr("Finish the document first") if d["status"] == "draft" else tr("This sheet is already decided"))
    b = body()
    b = b if isinstance(b, dict) else {}
    to = (b.get("to") or "").strip() if isinstance(b.get("to"), str) else ""
    if not re.fullmatch(r"[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+", to):
        raise BadInput(tr("Invalid value: {0}", "to"))
    sign = DSB_KINDS[r["kind"]][2]
    link = bool(sign and public_links_on(c))
    _to, subject0, text0, reply, code = dsb_mail_parts(c, oid, r, d, link)
    subject = inv_clean_subject(b.get("subject")) or subject0
    if code and f"[DS-{code}]" not in subject:
        subject = (subject + f" [DS-{code}]")[:240]  # the reply is found by it
    text = (b.get("text") or "").strip()[:5000] if isinstance(b.get("text"), str) else ""
    text = text or text0
    url = None
    if link:
        # 2.239.0 D (#2874): the link ends like the other approval links of the office ({expires} YYYY-MM-DD, else DSB_LINK_DAYS)
        exp = sig_expiry(b.get("expires") or (local_now().date() + timedelta(days=DSB_LINK_DAYS)).isoformat())
        srow, tok = sig_create(c, oid, "document", d["title"] or "", d["body_hash"], uid, exp, gen_doc_id=gd["id"])
        url = PUBLIC_URL.rstrip("/") + SIG_PREFIX + tok
        ofx_log(c, oid, "signoff_link", target="gen_doc", detail={"signoff": srow["id"], "gen_doc": gd["id"], "expires_at": exp,
                                                                  "doc_hash": d["body_hash"]})
    if DSB_LINK in text:
        text = text.replace(DSB_LINK, url or "")
    elif url:
        text += "\n\n" + url
    h6c_send_budget(c, oid, uid, [to])
    data = None
    if d["node_id"]:
        n = c.execute("SELECT deleted_at FROM fs_nodes WHERE id=?", (d["node_id"],)).fetchone()
        if n and not n["deleted_at"] and fs_role(c, d["node_id"], uid):
            try:
                data = fs_read(c, d["node_id"])
            except Denied:
                data = None
    if data is None:
        data = dt_pdf(c, oid, d)
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]+', "-", d["title"] or "document")[:120] + ".pdf"
    u = g.user
    _mail(to, subject, text, attachments=[(name, data, "application/pdf")],
          from_name=(u["display_name"] if u is not None and "display_name" in u.keys() else None), reply_to=reply or dsb_company_mail(c, oid))
    ts = iso(now_utc())
    st = "sent" if sign else "handed"
    c.execute("UPDATE office_privacy_sheets SET status=CASE WHEN status IN ('open', 'sent', 'handed', 'declined') THEN ? ELSE status END, "
              "sent_at=?, updated_at=? WHERE id=? AND org_id=?", (st, ts, ts, sid, oid))
    ofx_log(c, oid, "send", target="privacy_sheet", detail={"privacy_sheet": sid, "gen_doc": gd["id"], "to": to, "files": [name]})
    bump(c)
    c.commit()
    return jsonify(dsb_public(c, oid, dsb_sheet(c, oid, sid)))


def dsb_company_mail(c, oid):
    from .ledger import ofx_company
    rt = ofx_company(c, oid).get("email") or ""
    return rt if re.fullmatch(r"[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+", rt) else None


# ---------------------------------------------------------------- the signed sheet back: upload or reply mail
def dsb_kind_of(data, mime=""):
    """'application/pdf' | 'image/jpeg' | 'image/png' by the first bytes, else None (only these come in)."""
    if data[:5] == b"%PDF-":
        return "application/pdf"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return None


def dsb_file(c, r, uid, name, data, mime, ext):
    """Files the signed sheet into the documents space of r's office area (the client's folder, like doctpl.dt_file;
    the upload checks of fs_put apply) -> node id. ext makes it idempotent."""
    from ..docs import store as S
    from ..docs.ingest import docs_ingest
    oid = r["org_id"]
    owner = pb_owner(c, oid)
    who, org = (owner, None) if owner is not None else (uid, oid)
    nid = docs_ingest(c, who, org, name, data, mime, "office", {"ext_id": ext, "type": tr(DSB_KINDS[r["kind"]][0])})
    cl = c.execute("SELECT name FROM clients WHERE id=?", (r["client_id"],)).fetchone() if r["client_id"] else None
    if cl:
        node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
        fid = S.folder_by_name(c, node, who, cl["name"]) if node else None
        if fid and node["parent_id"] != fid:
            S.move_to_folder(c, node, fid)
    return nid


def dsb_signed_name(r, d, ext):
    lg = "en" if (d or {}).get("lang") == "en" else "de"  # the sheet's language (also from the mail poller, no request)
    base = re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]+', "-", (d or {}).get("title") or tr(DSB_KINDS[r["kind"]][0], lg=lg))[:120]
    return f"{base} ({tr('signed', lg=lg)}){ext}"


@app.post("/api/office/privacy-sheets/<int:sid>/signed")
def dsb_upload(sid):
    """multipart file = the signed sheet (PDF / JPEG / PNG): filed with the client, status signed (by upload)."""
    from ..admin.hosting import quota_guard
    c, uid, oid = _ctx()
    write_lock(c, f"office_privacy_{int(sid)}")
    r = dsb_sheet(c, oid, sid)
    if r["archived"]:  # 2.154.0 E (#2192)
        raise Denied(409, tr("This sheet is archived"))
    if not DSB_KINDS.get(r["kind"], ("", "", False))[2]:
        raise Denied(409, tr("This sheet needs no signature"))
    f = request.files.get("file")
    if f is None:
        raise BadInput(tr("Invalid value: {0}", "file"))
    quota_guard(c, uid)
    data = f.stream.read(MAX_FILE_MB * 1024 * 1024 + 1)
    if len(data) > MAX_FILE_MB * 1024 * 1024:
        raise BadInput(tr("{0}: larger than {1} MB", f.filename or "file", MAX_FILE_MB))
    mime = dsb_kind_of(data)
    if not mime:
        raise BadInput(tr("Only PDF, JPEG or PNG files"))
    d = oc_dec_fields(c, oid, "office_gen_docs", dt_doc(c, oid, r["gen_doc_id"])) if r["gen_doc_id"] else None
    ext = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png"}[mime]
    nid = dsb_file(c, r, uid, dsb_signed_name(r, d, ext), data, mime, f"privacy:{sid}:upload:{hashlib.sha256(data).hexdigest()[:16]}")
    ts = iso(now_utc())
    c.execute("UPDATE office_privacy_sheets SET status='signed', signed_via='upload', signed_at=?, signed_node_id=?, review=0, updated_at=? "
              "WHERE id=? AND org_id=?", (ts, nid, ts, sid, oid))
    from .ledger import ofx_log
    ofx_log(c, oid, "privacy_signed", target="privacy_sheet", detail={"privacy_sheet": sid, "via": "upload", "node_id": nid})
    bump(c)
    c.commit()
    dt_kick()
    return jsonify(dsb_public(c, oid, dsb_sheet(c, oid, sid)))


@app.get("/api/office/privacy-sheets/<int:sid>/pdf")
def dsb_pdf_get(sid):
    """?signed=1: the signed file (upload / mail / link), else the sheet's PDF -- the filed file while the admin reaches it."""
    from ..files.store import fs_read, fs_role
    c, uid, oid = _ctx()
    r = dsb_sheet(c, oid, sid)
    rows = dsb_rows(c, oid, uid, r["client_id"], True)
    r = next((x for x in rows if x["id"] == r["id"]), r)
    gd = dt_doc(c, oid, r["gen_doc_id"]) if r["gen_doc_id"] else None
    nid = (r["signed_node_id"] or (gd["signed_node_id"] if gd else None)) if request.args.get("signed") == "1" else (gd["node_id"] if gd else None)
    if not nid:
        raise Denied(404)
    n = c.execute("SELECT deleted_at, name, mime FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    if not n or n["deleted_at"] or not fs_role(c, nid, uid):
        raise Denied(404)
    data = fs_read(c, nid)
    mime = dsb_kind_of(data) or "application/octet-stream"
    resp = Response(data, mimetype=mime)
    from .doctpl import dt_disposition
    disp = dt_disposition(re.sub(r"\.(pdf|jpe?g|png)$", "", n["name"] or "sheet", flags=re.I))
    if mime != "application/pdf":
        disp = disp[:-4] + {"image/jpeg": ".jpg", "image/png": ".png"}.get(mime, "")
    resp.headers["Content-Disposition"] = disp
    resp.headers["Cache-Control"] = "private, no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


def dsb_mail_pick(c, r, files):
    """2.154.0 E (#2192): the attachment that is most likely the signed sheet -- PDFs first (not the sheet as it was
    sent: same SHA-256 as its filed PDF), then pictures of 30 KB or more (no logos / signature images); None = none."""
    from ..files.store import fs_read
    ok = [(dsb_kind_of(data), data) for _name, _mime, data in files if 0 < len(data) <= DSB_MAIL_MB * 1024 * 1024]
    pdfs = [x for x in ok if x[0] == "application/pdf"]
    if pdfs:
        sent = None
        nid = c.execute("SELECT node_id FROM office_gen_docs WHERE id=? AND org_id=?", (r["gen_doc_id"], r["org_id"])).fetchone() if r["gen_doc_id"] else None
        if nid and nid["node_id"]:
            try:
                sent = hashlib.sha256(fs_read(c, nid["node_id"])).hexdigest()
            except (Denied, OSError, ValueError):
                sent = None
        pdfs = [x for x in pdfs if hashlib.sha256(x[1]).hexdigest() != sent]
    return next(iter(pdfs), None) or next((x for x in ok if x[0] in ("image/jpeg", "image/png") and len(x[1]) >= 30 * 1024), None)


def dsb_reply_note(c, r, msg, subj, text):
    """2.154.0 E (#2192): a reply with a known code that is not filed (a revocation, a question, a DOCX / HEIC file, an
    archived sheet) never goes silently: an office log entry with sender, subject and the start of its text, and a sheet
    that is not archived shows "Reply received (please check)" (review=2) until a person confirms it. 2.239.0 D (#2874):
    sender, subject and text are kept with the sheet (sealed, they go with it), the office log only notes the event."""
    import email.utils
    import json
    from .ledger import ofx_log
    sender = email.utils.parseaddr(str(msg.get("From", "")))[1]
    body_ = (text or "").strip()
    reply = json.dumps({"at": iso(now_utc()), "from": sender[:200], "subject": subj[:200], "text": body_[:2000]})
    c.execute("UPDATE office_privacy_sheets SET reply=? WHERE id=?", (seal(c, f"privacy-reply:{r['id']}", reply), r["id"]))
    ofx_log(c, r["org_id"], "privacy_reply", target="privacy_sheet", detail={"privacy_sheet": r["id"], "chars": len(body_), "taken": 0})
    if not r["archived"]:
        c.execute("UPDATE office_privacy_sheets SET review=2, updated_at=? WHERE id=?", (iso(now_utc()), r["id"]))
    c.commit()
    return 0


def dsb_sent_to(c, oid, sid):
    """2.239.0 D (#2874): the addresses sheet sid was mailed to (the office log's send entries, lower case)."""
    import json
    out = set()
    for x in c.execute("SELECT * FROM office_doc_log WHERE org_id=? AND action='send' AND target='privacy_sheet' ORDER BY id DESC LIMIT ?",
                       (oid, LIST_MAX)):
        try:
            d = json.loads(oc_dec_fields(c, oid, "office_doc_log", x).get("detail") or "{}")
        except (TypeError, ValueError):
            continue
        if isinstance(d, dict) and d.get("privacy_sheet") == sid and isinstance(d.get("to"), str):
            out.add(d["to"].strip().lower())
    return out


def dsb_mail_once(c, r, msg, raw):
    """2.209.0 C (#2589): claims a reply mail for sheet r once by its Message-ID (else its bytes) in mail_in_seen
    (box "privacy:<sheet id>", kept MAIL_SEEN_DAYS like the mailboxes' claims; committed with the import) -> False when
    it was handled already."""
    mid = str(msg.get("Message-ID", "")).strip()[:200] or ("sha:" + hashlib.sha256(raw).hexdigest())
    return c.execute("INSERT INTO mail_in_seen(box, mid, seen_at) VALUES(?,?,?) ON CONFLICT DO NOTHING RETURNING box",
                     (f"privacy:{r['id']}", hashlib.sha256(mid.encode()).hexdigest(), iso(now_utc()))).fetchone() is not None


def dsb_mail_import(c, msg, raw):
    """integrations/mail.py mail_import, first: a reply with the code of a mailed sheet that wants a signature (subject
    "[DS-<code>]" or the plus address "+ds-<code>@") -> its first PDF / picture is filed into that sheet's office area,
    status "signed (by mail, please check)". None = no such code (the other importers go on); else the node id or 0."""
    from ..integrations.mail import mail_text
    from ..core.access import acx_of
    from ..admin.hosting import QuotaExceeded
    subj = str(msg.get("Subject", "")).replace("\n", " ")
    hdrs = " ".join(str(msg.get_all(h, [])) for h in ("To", "Cc", "Delivered-To", "X-Original-To", "Envelope-To"))
    codes = [x.upper() for x in DSB_SUBJ_RE.findall(subj) + DSB_PLUS_RE.findall(hdrs)]
    if not codes:
        return None
    with system_ctx(c):  # a secret code like a public link; the sheet's area and its creator's membership checked below
        r = next((x for x in (c.execute("SELECT * FROM office_privacy_sheets WHERE code_hash=?", (dsb_code_hash(k),)).fetchone()
                              for k in dict.fromkeys(codes)) if x), None)
        if not r:
            return None
        uid = r["created_by"]
        u = c.execute("SELECT disabled FROM users WHERE id=?", (uid,)).fetchone() if uid else None
        owner = pb_owner(c, r["org_id"])
        if not u or u["disabled"] or (owner is None and int(r["org_id"]) not in acx_of(c, uid).org_ids):
            return 0
        if not dsb_mail_once(c, r, msg, raw):
            return 0  # 2.209.0 C (#2589): the same mail fetched again (another copy, a second mailbox): handled already
        text, files = mail_text(msg)
        if r["archived"] or r["status"] != "sent" or not DSB_KINDS.get(r["kind"], ("", "", False))[2] \
                or c.execute("SELECT 1 FROM clients WHERE id=? AND deleted_at IS NOT NULL", (r["client_id"],)).fetchone():  # 2.272.0 F (#3029, M2): client in the trash
            return dsb_reply_note(c, r, msg, subj, text)  # known, but nothing to take in (already signed / not mailed): never a task
        pick = dsb_mail_pick(c, r, files[:20])
        import email.utils
        frm = email.utils.parseaddr(str(msg.get("From", "")))[1].strip().lower()
        if pick and frm not in dsb_sent_to(c, r["org_id"], r["id"]):
            pick = None  # 2.239.0 D (#2874): signed only by the address it was mailed to; another sender is a reply to check
        if not pick:
            return dsb_reply_note(c, r, msg, subj, text)
        d = c.execute("SELECT title, lang FROM office_gen_docs WHERE id=? AND org_id=?", (r["gen_doc_id"], r["org_id"])).fetchone() if r["gen_doc_id"] else None
        ext = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png"}[pick[0]]
        mid = str(msg.get("Message-ID", "")).strip()[:200] or ("sha:" + hashlib.sha256(raw).hexdigest())
        try:
            with c.savepoint():
                nid = dsb_file(c, r, uid, dsb_signed_name(r, dict(d) if d else None, ext), pick[1], pick[0],
                               f"privacy:{r['id']}:mail:{hashlib.sha256(mid.encode()).hexdigest()[:24]}")
        except (Denied, ValueError, QuotaExceeded) as e:
            print("privacy sheet: mail attachment refused", type(e).__name__, flush=True)
            return dsb_reply_note(c, r, msg, subj, text)
        ts = iso(now_utc())
        c.execute("UPDATE office_privacy_sheets SET status='signed', signed_via='mail', signed_at=?, signed_node_id=?, review=1, updated_at=? "
                  "WHERE id=? AND status='sent'", (ts, nid, ts, r["id"]))
    c.commit()
    dt_kick()
    return nid
