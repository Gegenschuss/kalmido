"""2.153.0 (#2029, #2030): a letter sent by e-mail (its PDF attached, the Message-ID kept) and the answer that comes back
through the mail inbox linked to it (office/letterlinks.py ltl_link, kind reply); text blocks (office_letter_blocks) per
office area to insert into letters.

Sending is a person's button press only (no automatic mail): POST /api/office/letters/<id>/send-mail, a draft, the admin
of the office area (like every letter route). Sender name and the day's limits like the invoice mail (office/invoices.py
inv_send, h6c_send_budget). Reply-To = the sending person's document address of the office's documents space (doc_mail):
an answer then arrives in the documents space, docs/ingest.py docs_mail_import hands its documents to ltm_link_replies,
which links them when In-Reply-To / References name the Message-ID of a letter of the SAME office area. Without such an
address the answer goes to the company e-mail (like invoices) and is assigned by hand (part B)."""
import re

from flask import g, jsonify, request

from ..core.config import app
from ..core.pg import insert_id, write_lock
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields
from ..core.i18n import N_, tr
from ..core.db import body, bump, iso, now_utc
from ..core.access import Denied
from ..personal.timetrack import BadInput
from .letters import lt_ctx, lt_kick, lt_line, lt_multi, lt_mark_sent, lt_pdf, lt_public, lt_row

LTM_MAIL_RE = r"[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+"
LTM_MSGID_RE = re.compile(r"<[^<>\s]{3,250}>")
LTM_TEXT_MAX = 5000
LTB_LIST_MAX = 500
LTB_NAME_MAX, LTB_BODY_MAX = 120, 20000
LTB_NOTE = N_("Sample text, no legal advice.")


# ---------------------------------------------------------------- the reply address
def ltm_space(c, oid, uid):
    """(user id, org id or None) of the documents space that belongs to office area oid for person uid: a personal office
    -> its owner's private space, an organisation -> uid's space of that organisation (like office/doctpl.py dt_file)."""
    from .model import pb_owner
    owner = pb_owner(c, oid)
    return (owner, None) if owner is not None else (uid, oid)


def ltm_reply_address(c, oid, uid):
    """The document address (doc_mail token) of uid's documents space of office area oid, '' without one / no mail input."""
    from ..integrations.mail import MAIL_IN_ON, mail_addr
    if not MAIL_IN_ON:
        return ""
    who, org = ltm_space(c, oid, uid)
    r = c.execute("SELECT token FROM doc_mail WHERE user_id=? AND org_id IS NOT DISTINCT FROM ?", (who, org)).fetchone()
    return mail_addr(r[0]) if r else ""


def ltm_company_mail(c, oid):
    from .ledger import ofx_company
    v = ofx_company(c, oid).get("email") or ""
    return v if re.fullmatch(LTM_MAIL_RE, v) else ""


def ltm_default_text(c, oid, d, lg):
    from .ledger import ofx_company
    who = ofx_company(c, oid).get("name") or ""
    u = getattr(g, "user", None)
    if not who and u is not None and "display_name" in u.keys():
        who = u["display_name"] or ""
    subj = d.get("subject") or tr("Letter", lg=lg)
    return tr("Hello,\n\nplease find attached our letter \"{0}\" as a PDF.\n\nKind regards\n{1}", subj, who, lg=lg).rstrip()


def ltm_lang(c, oid, d):
    from .doctpl import dt_lang
    return dt_lang(c, oid, d.get("lang") if d.get("lang") in ("de", "en") else None)


def ltm_filename(d, lg):
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", " ", d.get("subject") or "").strip()[:80].strip(" .")
    return (name or tr("Letter", lg=lg)) + ".pdf"


@app.get("/api/office/letters/mail-info")
def ltm_info_get():
    """{mail_on, reply_address, company_email}: the client hides "Send by e-mail" without a mail server; reply_address =
    where answers arrive (linked automatically), '' = answers go to company_email and are assigned by hand."""
    from ..integrations.mail import MAIL_OUT_ON
    c, uid, oid = lt_ctx()
    return jsonify(mail_on=bool(MAIL_OUT_ON), reply_address=ltm_reply_address(c, oid, uid), company_email=ltm_company_mail(c, oid))


@app.get("/api/office/letters/<int:lid>/mail-draft")
def ltm_draft_get(lid):
    """The prefilled form of the mail of draft lid: {to, subject, text, filename, reply_address}."""
    c, uid, oid = lt_ctx()
    d = lt_row(c, oid, lid)
    lg = ltm_lang(c, oid, d)
    return jsonify(to=d.get("rcpt_email") or "", subject=d.get("subject") or tr("Letter", lg=lg), text=ltm_default_text(c, oid, d, lg),
                   filename=ltm_filename(d, lg), reply_address=ltm_reply_address(c, oid, uid))


def ltm_drop_filed(c, nid):
    """2.184.0 C (#2582): the file lt_mark_sent has just filed (node nid, still uncommitted) is removed from the disk after the
    database rolled back; never a file that was filed before (the caller passes the node of this request only)."""
    if not nid:
        return
    from ..files.store import fs_purge_files, fs_subtree
    ids = fs_subtree(c, nid)
    paths = [r[0] for i in ids for r in c.execute("SELECT path FROM fs_versions WHERE node_id=?", (i,))]
    c.rollback()
    fs_purge_files(ids, paths)


@app.post("/api/office/letters/<int:lid>/send-mail")
def ltm_send_post(lid):
    """{to?, cc?, subject?, text?} mails draft lid with its PDF (to = the recipient's e-mail by default), keeps the Message-ID
    and marks it sent (channel email). 400 without a mail server / not a draft / no address; 409 when the server refuses."""
    from ..integrations.mail import MAIL_OUT_ON
    from .invoices import _mail, h6c_send_budget
    from .ledger import ofx_log
    c, uid, oid = lt_ctx()
    b = body() or {}
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    if not MAIL_OUT_ON:
        raise BadInput(tr("Sending e-mail is not set up on this server (KALMIDO_SMTP_HOST)"))
    write_lock(c, f"office_letter_{int(lid)}")  # like /sent: two presses never mail twice
    d = lt_row(c, oid, lid)
    if d["status"] != "draft":
        raise BadInput(tr("The letter has already been sent"))
    to = lt_line(b.get("to"), "to", 254) or (d.get("rcpt_email") or "")
    cc = lt_line(b.get("cc"), "cc", 254)
    if not to:
        raise BadInput(tr("Enter the recipient's e-mail address"))
    if not re.fullmatch(LTM_MAIL_RE, to):
        raise BadInput(tr("Invalid value: {0}", "to"))
    if cc and not re.fullmatch(LTM_MAIL_RE, cc):
        raise BadInput(tr("Invalid value: {0}", "cc"))
    lg = ltm_lang(c, oid, d)
    subject = lt_line(b.get("subject"), "subject", 200) or d.get("subject") or tr("Letter", lg=lg)
    text = lt_multi(b.get("text"), "text", LTM_TEXT_MAX).strip() or ltm_default_text(c, oid, d, lg)
    h6c_send_budget(c, oid, uid, [to] + ([cc] if cc else []))  # the day's limits of the office mails (2.86.0 N27)
    pdf = lt_pdf(c, oid, {**d, "status": "sent"})  # the mailed PDF is the final letter (no draft mark)
    u = g.user
    rt = ltm_reply_address(c, oid, uid) or ltm_company_mail(c, oid) or None
    # review 2.153.0: mark sent + file the PDF BEFORE the mail goes out (a full quota / filing error then sends nothing);
    # a refused mail raises and rolls all of it back, the Message-ID is written after the server took the mail
    d = lt_mark_sent(c, oid, d, channel="email", uid=uid)
    try:
        sent = _mail(to, subject, text, attachments=[(ltm_filename(d, lg), pdf, "application/pdf")], cc=cc or None,
                     from_name=(u["display_name"] if u is not None and "display_name" in u.keys() else None), reply_to=rt)
    except BaseException:
        ltm_drop_filed(c, d.get("node_id"))  # 2.184.0 C (#2582): the refused mail takes the just filed PDF with it
        raise
    mid = str(sent["Message-ID"] or "") if sent is not None else ""  # mail_send returns the message since 2.141.0
    if mid:
        c.execute("UPDATE office_letters SET msg_id=? WHERE id=? AND org_id=?", (mid[:250], d["id"], oid))
        d = {**d, "msg_id": mid[:250]}
    ofx_log(c, oid, "send", target="letter", detail={"letter": d["id"], "to": to, "cc": cc})
    c.commit()
    lt_kick()
    return jsonify(lt_public(c, oid, d))


# ---------------------------------------------------------------- the answer comes back
def ltm_msg_ids(msg):
    """The Message-IDs an incoming mail answers (In-Reply-To, then References), at most 20."""
    out = []
    for h in ("In-Reply-To", "References"):
        for v in msg.get_all(h, []) or []:
            for x in LTM_MSGID_RE.findall(str(v)):
                if x not in out:
                    out.append(x)
    return out[:20]


def ltm_link_replies(c, uid, org, msg, node_ids):
    """Called by docs/ingest.py docs_mail_import (inside its system_ctx) with the documents made from one mail to the
    document address of (uid, org): links each with the letter of the SAME office area (the organisation org, or uid's
    personal office when org is None) whose Message-ID the mail answers. Another area never matches. No commit -> count."""
    node_ids = [n for n in node_ids if n]
    ids = ltm_msg_ids(msg)
    if not node_ids or not ids:
        return 0
    if org:
        oid = int(org)
    else:
        from .model import pb_personal
        oid = pb_personal(c, uid, create=False)
        if not oid:
            return 0
    rows = c.execute(f"SELECT id FROM office_letters WHERE org_id=? AND msg_id<>'' AND msg_id IN ({','.join('?' * len(ids))}) ORDER BY id",
                     [oid] + ids).fetchall()
    if not rows:
        return 0
    from .letterlinks import ltl_link
    n = 0
    for r in rows:
        for nid in node_ids:
            ltl_link(c, oid, r[0], nid, "reply")
            n += 1
    bump(c)
    return n


# ---------------------------------------------------------------- text blocks (#2030)
LTB_STARTERS = {
    "cancel": {
        "de": ("Kündigung", "hiermit kündige ich den oben genannten Vertrag fristgerecht zum nächstmöglichen Zeitpunkt. "
                            "Bitte bestätigen Sie mir die Kündigung und das Datum, zu dem sie wirksam wird, schriftlich."),
        "en": ("Cancellation", "I hereby cancel the contract referred to above with due notice at the earliest possible date. "
                               "Please confirm the cancellation and the date it takes effect in writing."),
    },
    "objection": {
        "de": ("Widerspruch", "gegen Ihren Bescheid vom [Datum], Aktenzeichen [Aktenzeichen], lege ich hiermit Widerspruch ein. "
                              "Die Begründung reiche ich nach. Bitte bestätigen Sie mir den Eingang dieses Schreibens."),
        "en": ("Objection", "I hereby object to your decision of [date], reference [reference]. I will submit the reasons "
                            "separately. Please confirm receipt of this letter."),
    },
    "reminder": {
        "de": ("Zahlungserinnerung", "sicher ist es Ihrer Aufmerksamkeit entgangen: Der Betrag von [Betrag] aus unserer Rechnung "
                                     "[Nummer] vom [Datum] ist noch offen. Bitte überweisen Sie ihn bis zum [Datum]. Sollten Sie "
                                     "die Zahlung bereits veranlasst haben, betrachten Sie dieses Schreiben bitte als gegenstandslos."),
        "en": ("Payment reminder", "perhaps it has escaped your notice: the amount of [amount] from our invoice [number] of [date] "
                                   "is still open. Please transfer it by [date]. If you have already paid, please disregard this letter."),
    },
    "extension": {
        "de": ("Bitte um Fristverlängerung", "für die Frist zum [Datum] bitte ich um eine Verlängerung bis zum [Datum], da mir "
                                             "noch Unterlagen fehlen. Für Ihr Verständnis bedanke ich mich."),
        "en": ("Request for an extension", "I kindly ask you to extend the deadline of [date] to [date], as some documents are "
                                           "still missing. Thank you for your understanding."),
    },
}


def ltb_row(c, oid, bid):
    try:
        bid = int(bid)
    except (TypeError, ValueError):
        raise Denied(404) from None
    r = c.execute("SELECT * FROM office_letter_blocks WHERE id=? AND org_id=?", (bid, oid)).fetchone()
    if not r:
        raise Denied(404)
    return oc_dec_fields(c, oid, "office_letter_blocks", r)


def ltb_public(d):
    return {k: d.get(k) for k in ("id", "name", "body", "archived", "created_by", "created_at", "updated_at")}


def ltb_clean(b, cur=None):
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    out = {}
    if "name" in b or cur is None:
        out["name"] = lt_line(b.get("name"), "name", LTB_NAME_MAX)
        if not out["name"]:
            raise BadInput(tr("Name missing"))
    if "body" in b or cur is None:
        out["body"] = lt_multi(b.get("body"), "body", LTB_BODY_MAX)
    return out


@app.get("/api/office/letter-blocks")
def ltb_list():
    """?archived=1 also the deleted ones -> {blocks, note}."""
    c, uid, oid = lt_ctx()
    arch = request.args.get("archived") == "1"
    rows = c.execute("SELECT * FROM office_letter_blocks WHERE org_id=?" + ("" if arch else " AND archived=0") + " ORDER BY lower(name), id LIMIT ?",
                     (oid, LTB_LIST_MAX)).fetchall()
    return jsonify(blocks=[ltb_public(oc_dec_fields(c, oid, "office_letter_blocks", r)) for r in rows], note=tr(LTB_NOTE))


@app.get("/api/office/letter-blocks/starters")
def ltb_starters_get():
    """?lang=de|en (default: the office's document language) -> {starters: [{key, name, lang, body}], note}."""
    from .doctpl import dt_lang
    c, uid, oid = lt_ctx()
    lg = dt_lang(c, oid, request.args.get("lang") or None)
    return jsonify(starters=[{"key": k, "name": v[lg][0], "lang": lg, "body": v[lg][1]} for k, v in LTB_STARTERS.items()],
                   note=tr(LTB_NOTE), lang=lg)


@app.post("/api/office/letter-blocks")
def ltb_post():
    """{name, body} or {starter: cancel|objection|reminder|extension, lang?} (a sample as own block) -> 201."""
    from .doctpl import dt_lang
    c, uid, oid = lt_ctx()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    if b.get("starter") is not None:
        st = LTB_STARTERS.get(b["starter"]) if isinstance(b["starter"], str) else None
        if not st:
            raise BadInput(tr("Invalid value: {0}", "starter"))
        lg = dt_lang(c, oid, b.get("lang"))
        b = {"name": st[lg][0], "body": st[lg][1]}
    row = ltb_clean(b)
    ts = iso(now_utc())
    row.update(org_id=oid, created_by=uid, created_at=ts, updated_at=ts)
    row = oc_enc_fields(c, oid, "office_letter_blocks", row)
    bid = insert_id(c, f"INSERT INTO office_letter_blocks({','.join(row)}) VALUES({','.join('?' * len(row))})", list(row.values()))
    bump(c)
    c.commit()
    return jsonify(ltb_public(ltb_row(c, oid, bid))), 201


@app.patch("/api/office/letter-blocks/<int:bid>")
def ltb_patch(bid):
    c, uid, oid = lt_ctx()
    cur = ltb_row(c, oid, bid)
    row = ltb_clean(body(), cur)
    if row:
        row["updated_at"] = iso(now_utc())
        row = oc_enc_fields(c, oid, "office_letter_blocks", row)
        c.execute(f"UPDATE office_letter_blocks SET {','.join(k + '=?' for k in row)} WHERE id=? AND org_id=?", list(row.values()) + [cur["id"], oid])
        bump(c)
        c.commit()
    return jsonify(ltb_public(ltb_row(c, oid, bid)))


@app.delete("/api/office/letter-blocks/<int:bid>")
def ltb_delete(bid):
    """Archives a block (letters keep their text); POST .../restore takes it back (the client's undo)."""
    return ltb_set_archived(bid, 1)


@app.post("/api/office/letter-blocks/<int:bid>/restore")
def ltb_restore(bid):
    return ltb_set_archived(bid, 0)


def ltb_set_archived(bid, v):
    c, uid, oid = lt_ctx()
    cur = ltb_row(c, oid, bid)
    c.execute("UPDATE office_letter_blocks SET archived=?, updated_at=? WHERE id=? AND org_id=?", (v, iso(now_utc()), cur["id"], oid))
    bump(c)
    c.commit()
    return jsonify(ltb_public(ltb_row(c, oid, bid)))
