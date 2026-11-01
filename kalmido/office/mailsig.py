"""2.439.0 (#3617): what a person adds to the office's document mails (quotations, invoices, credit notes, reminders, letters
by e-mail): their signature, their sender name, their answer address and the way the mail leaves.

Per person and office area, in the row of office_letter_profiles (the signature picture of letters there stays apart): the
signature is plain text, prefilled from the person's name and the company data until they save their own (mail_sig_set);
every mail then carries it under the text behind "-- ", and goes out as text + HTML with the company logo as an embedded
picture (mail_sig_logo, never a link to an outside picture). The send dialogs show it and can leave it off for one mail.

The sender address follows the way: the server's own address through KALMIDO_SMTP_* (SPF / DMARC), the address of a mailbox
with SMTP (hub/mailbox.py) when one is set up: the mailbox of the office's workspace, or in an organisation the person's own
private one when they choose it (mail_via; a personal office: its owner's). Reply-To: the one given for this mail, else the
person's, else the company's e-mail; a letter's own reply address stays first (office/lettermail.py)."""
import base64
import html
import io
import os
import re

from flask import jsonify

from ..core.config import app
from ..core.db import body
from ..core.i18n import N_, tr
from ..core.access import Denied
from ..core.orgcrypt import oc_plain_safe
from ..hub.hubmail import _ws
from ..hub.mailbox import mbx_row, mbx_smtp
from ..personal.timetrack import BadInput
from .lettermail import ltm_space
from .letters import lt_line, lt_multi, lt_profile, lt_profile_save, lt_user_name
from .ledger import ofx_company, ofx_web_print
from .model import office_ctx, office_role, office_settings
from .pdfweb import opdf_logo_path

OFM_SIG_MAX, OFM_SIG_LINES, OFM_NAME_MAX = 1000, 12, 120
OFM_MAIL_RE = r"[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+"
OFM_VIA = ("", "server", "workspace", "private")
OFM_LOGO_PX = 96  # twice the 48 px of the mail: sharp on a phone, small as a picture
OFM_CID = "kalmido-sig-logo"
OFM_NOTE_SERVER = N_("E-mails leave from the server's address so they do not land in spam; answers go to the answer address. An own sender address needs a mailbox with SMTP (E-mail filing).")
OFM_NOTE_BOX = N_("E-mails leave from {0} through your mailbox.")


def ofm_default_sig(c, oid, uid):
    """The prefilled signature: the person's name, company, address, phone, website (only what is known, each once)."""
    co = ofx_company(c, oid)
    town = " ".join(x for x in (co.get("zip"), co.get("city")) if x)
    lines = [lt_user_name(c, uid), re.sub(r"\s*\n\s*", " ", co.get("name") or "").strip(), ", ".join(x for x in (co.get("street"), town) if x),
             co.get("phone") or "", ofx_web_print(co.get("website")) or ""]
    return "\n".join(dict.fromkeys(x for x in lines if x))[:OFM_SIG_MAX]


def ofm_sig(c, oid, uid, p=None):
    """The signature text of uid in area oid: their own once saved ('' = none), else the prefilled one."""
    p = (lt_profile(c, oid, uid) or {}) if p is None else p
    return (p.get("mail_sig") or "") if p.get("mail_sig_set") else ofm_default_sig(c, oid, uid)


def ofm_logo(c, oid):
    """The company logo as a small PNG for the mail, None without one (a broken file never stops a mail)."""
    lp = opdf_logo_path(oid)
    if not office_settings(c, oid).get("logo") or not os.path.isfile(lp):
        return None
    try:
        from PIL import Image
        with Image.open(lp) as im:
            im.thumbnail((OFM_LOGO_PX * 6, OFM_LOGO_PX))
            out = io.BytesIO()
            im.save(out, "PNG", optimize=True)
        return out.getvalue()
    except Exception as e:  # noqa: BLE001
        app.logger.warning("office mail logo failed: %s", type(e).__name__)
        return None


def ofm_ways(c, oid, uid):
    """{way: address ('' = the server's)} the mail of uid in area oid can leave by: server, workspace, private."""
    from ..integrations.mail import MAIL_OUT_ON
    who, org = ltm_space(c, oid, uid)
    out = {"server": ""} if MAIL_OUT_ON else {}

    def box(way, ws):
        r = mbx_row(c, ws)
        if r and r["active"] and r["smtp_host"] and r["from_addr"]:
            out[way] = r["from_addr"]
    box("workspace", _ws(org, who))
    if org:
        box("private", _ws(None, uid))
    return out


def ofm_way(p, ways):
    """The way chosen in the profile while it exists, else the workspace's mailbox, else the server, '' = no way at all."""
    want = p.get("mail_via") or ""
    if want in ways:
        return want
    return "workspace" if "workspace" in ways else "server" if "server" in ways else ""


def ofm_sender(c, oid, uid, p=None):
    """{via, smtp, addr, name}: how a mail of uid leaves. via '' = no way; smtp None = KALMIDO_SMTP_*."""
    p = (lt_profile(c, oid, uid) or {}) if p is None else p
    ways = ofm_ways(c, oid, uid)
    via = ofm_way(p, ways)
    smtp, name = None, ""
    if via in ("workspace", "private"):
        who, org = ltm_space(c, oid, uid)
        r = mbx_row(c, _ws(org, who) if via == "workspace" else _ws(None, uid))
        smtp, name = mbx_smtp(c, r), r["from_name"] or ""
    return {"via": via, "smtp": smtp, "addr": ways.get(via, ""), "name": (p.get("mail_from_name") or name or lt_user_name(c, uid) or None)}


def ofm_reply(c, oid, p, b=None):
    """Reply-To of a mail: the one given in b (400 when it is no address), the person's, the company's; None without one."""
    v = (b or {}).get("reply_to")
    if v is not None and not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", "reply_to"))
    v = (v or "").strip()
    if v and not re.fullmatch(OFM_MAIL_RE, v):
        raise BadInput(tr("Invalid value: {0}", "reply_to"))
    v = v or p.get("mail_reply_to") or ofx_company(c, oid).get("email") or ""
    return v if re.fullmatch(OFM_MAIL_RE, v) else None


def ofm_html(text, sig, logo):
    def e(t):
        return html.escape(t).replace("\n", "<br>\n")
    img = f'<img src="cid:{OFM_CID}" alt="" height="48" style="display:block;height:48px;width:auto;margin:6px 0 8px">' if logo else ""
    return (f'<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.45;color:#1f2933">{e(text)}'
            f'<div style="margin-top:20px;font-size:13px;color:#52606d">-- <br>\n{img}{e(sig)}</div></div>')


def ofm_mail(c, oid, uid, text, b=None, auto=False):
    """The mail of uid in area oid with their signature (b["signature"] false: without): {text, kw (html_body, images, smtp
    for mail_send), name, custom, profile}. custom = the signature is their own words. auto = no person pressed send (a
    series, uid = whichever admin acts for it; review): none of a person's own settings, least of all a private mailbox:
    the workspace's mailbox or the server, the prefilled signature, the company as Reply-To (profile {})."""
    b = b or {}
    p = {} if auto else (lt_profile(c, oid, uid) or {})
    snd = ofm_sender(c, oid, uid, p)
    kw = {"smtp": snd["smtp"]} if snd["smtp"] else {}
    sig = "" if b.get("signature") in (0, False, "0", "false") else ofm_sig(c, oid, uid, p)
    if sig:
        logo = ofm_logo(c, oid) if p.get("mail_sig_logo", 1) else None
        kw["html_body"] = ofm_html(text, sig, logo)
        if logo:
            kw["images"] = {OFM_CID: (logo, "png")}
        text = f"{text.rstrip()}\n\n-- \n{sig}"
    return {"text": text, "kw": kw, "name": snd["name"], "profile": p, "via": snd["via"],
            "custom": bool(sig) and sig != ofm_default_sig(c, oid, uid)}


def ofm_own_text(c, oid, uid, mail):
    """A member's own signature counts as an own text for the day's limit (invoices.inv_own_text_quota): it is free text in
    a mail of the organisation; admins' are not limited and do not fill the limit of the others."""
    return mail["custom"] and office_role(c, uid, oid) != "admin"


def _json(c, oid, uid):
    p = lt_profile(c, oid, uid) or {}
    logo = ofm_logo(c, oid)
    ways = ofm_ways(c, oid, uid)
    via = ofm_way(p, ways)
    co = ofx_company(c, oid).get("email") or ""
    return {"signature": ofm_sig(c, oid, uid, p), "default_signature": ofm_default_sig(c, oid, uid), "saved": bool(p.get("mail_sig_set")),
            "logo": bool(p.get("mail_sig_logo", 1)), "has_logo": bool(logo),
            "logo_data": "data:image/png;base64," + base64.b64encode(logo).decode("ascii") if logo else "",  # members may not read /api/office/logo
            "from_name": p.get("mail_from_name") or "", "default_from_name": lt_user_name(c, uid), "reply_to": p.get("mail_reply_to") or "",
            "default_reply_to": co if re.fullmatch(OFM_MAIL_RE, co) else "", "via": via, "choice": p.get("mail_via") or "",
            "ways": [{"key": k, "address": v} for k, v in ways.items()], "note": tr(OFM_NOTE_BOX, ways[via]) if via in ("workspace", "private") else tr(OFM_NOTE_SERVER)}


@app.get("/api/office/mail-profile")
def ofm_get():
    """The person's own mail settings of this office and what the send dialogs show."""
    c, uid, oid = office_ctx()
    return jsonify(_json(c, oid, uid))


@app.put("/api/office/mail-profile")
def ofm_put():
    """{signature? (null = the prefilled one again), logo?, from_name?, reply_to?, via?}: only ever the person's own row."""
    c, uid, oid = office_ctx()
    b = body() or {}
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    upd = {}
    if "signature" in b:
        v = b["signature"]
        sig = "" if v is None else "\n".join(x.rstrip() for x in lt_multi(v, "signature", OFM_SIG_MAX).strip().split("\n"))
        if sig.count("\n") >= OFM_SIG_LINES:
            raise BadInput(tr("Invalid value: {0}", "signature"))
        upd.update(mail_sig=oc_plain_safe(sig), mail_sig_set=0 if v is None else 1)
    if "logo" in b:
        if not isinstance(b["logo"], bool):
            raise BadInput(tr("Invalid value: {0}", "logo"))
        upd["mail_sig_logo"] = int(b["logo"])
    if "from_name" in b:
        upd["mail_from_name"] = oc_plain_safe(lt_line(b["from_name"], "from_name", OFM_NAME_MAX))
    if "reply_to" in b:
        v = lt_line(b["reply_to"], "reply_to", 254)
        if v and (not re.fullmatch(OFM_MAIL_RE, v) or oc_plain_safe(v) != v):
            raise BadInput(tr("Invalid value: {0}", "reply_to"))
        upd["mail_reply_to"] = oc_plain_safe(v)
    if "via" in b:
        if b["via"] not in OFM_VIA:
            raise BadInput(tr("Invalid value: {0}", "via"))
        upd["mail_via"] = b["via"]
    if not upd:
        raise Denied(400, tr("Invalid data"))
    lt_profile_save(c, oid, uid, upd)
    c.commit()
    return jsonify(_json(c, oid, uid))
