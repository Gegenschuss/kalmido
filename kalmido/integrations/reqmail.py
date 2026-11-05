"""2.553.0 B (#3460): requests by e-mail -- a customer's mail becomes a ticket of the customer portal (team/portal.py), the team's
public answers go back by mail, the customer's replies become comments of the same ticket.

The switch "Requests by e-mail" of a project (lists.req_mail, owner / project admins, people only; only where a project can have
an e-mail address and the instance's customer portal is on) gives the list ONE request address: a hub address (hub_tokens kind
'ticket', the same plus token as the hub's client / project addresses, hub/hubmail.py). hbm_mail_import hands a mail to it to
rq_take (HBM_TICKET_HOOK). The address leads only into its own list (the token names it; nothing else is looked up across lists).

A new mail = a task in the list + a portal ticket (pt_create, like a form with a status link; via 'mail'): subject = title, the
plain text = the description (no HTML is shown, mail_text keeps the text part or the HTML without tags), its files = files of the
task (save_attachment_bytes: the virus scan, the list owner's storage quota, sealed), the sender = the reporter (name, address).
The sender's domain is checked like the hub's (hbm_from_verified, KALMIDO_MAIL_AUTHSERV_ID): without that proof the ticket is
still made, but marked (portal_tickets.unverified, a line in the description). The sender gets ONE confirmation with the status
link and the ticket's reference "[T<id>-<check>]" in the subject (Reply-To = the request address; per address and hour and per
list and day limited like the form's confirmation).

A reply (to the request address) is a comment of a ticket only when BOTH fit: the reference (the "[T<id>-<check>]" of the
subject -- the check is an HMAC with the server key, no bare number -- or a Message-ID Kalmido sent / took in for that ticket in
In-Reply-To / References) names a live ticket of THIS list, and the sender is the ticket's reporter. Then: a comment the customer
sees (portal = 1, ext_name, no account), the quote cut off (tmr_trim), its files files of the comment (the same checks), News for
the team. Anything else (another sender with a valid reference, a reference of another list, none) is a new ticket as above; a
reference with a wrong sender says so in the new task ("Reply to ticket T<id>, the sender is not its reporter").

Mail loops: a mail from one of the server's own addresses is not taken; an automatic mail (Auto-Submitted other than "no",
Precedence bulk / junk / list / auto_reply, X-Autoreply / X-Autorespond, a delivery report, mailer-daemon / postmaster) never gets
a confirmation, and an automatic reply never becomes a comment (an out-of-office answer to an answer). The confirmation carries
Auto-Submitted: auto-replied.

Out: team/portal.py pt_mail_tick (public answers, notify on, at most one mail per PT_MAIL_GAP) asks PT_MAIL_HOOK for a mail
ticket: the reference in the subject, Reply-To = the request address while the switch is on, In-Reply-To / References = the
ticket's Message-IDs (task_mail), its own Message-ID stored ('out'). Internal comments never go out (pt_answers reads portal = 1
only). "Done" goes out for a mail ticket only with the list's second switch (lists.req_mail_done, default off); a form's ticket
keeps its done mail as before."""
import email.utils
import hashlib
import hmac
import re
import secrets

from flask import jsonify

from ..core.config import app, APP_NAME, MAX_FILE_MB
from ..core.db import body, bump, db, err, iso, iso_ms, now_utc
from ..core.i18n import lang, tr
from ..core.pg import insert_id
from ..core.access import Denied, MANAGE_ROLES, need_list, task_visible
from ..core.pages import save_attachment_bytes
from ..accounts.session import _token_hash, me
from ..accounts.bgjobs import bgj_add, bgj_fn
from ..api.common import hit_limit
from ..collab.comments import collab_user
from ..collab.liste2eguard import le2b_list_locked, le2b_off
from ..collab.news import news_add
from ..hub import hubmail as H
from ..lists.public import public_links_on
from ..tasks.attachments import unexec_name
from ..tasks.validation import log_act
from ..tasks.watchers import wat_users
from ..team import portal as P
from ..team.forms import frm_mail_ok, r81c_form_mail_day
from ..team.formq import fq_md
from . import mail as M
from .taskmail import tmr_ids, tmr_trim

RQ_REF_RE = re.compile(r"\[T(\d{1,12})-([0-9a-f]{8})\]", re.I)
_MID_RE = re.compile(r"<[^<>\s]{1,290}>")
RQ_FILES = 20             # files of one mail at most
RQ_IN_HOUR = 60           # new tickets per list and hour (by mail)
RQ_IN_SENDER_HOUR = 10    # new tickets per list, sender and hour
RQ_TITLE_MAX = 300
_AUTO_PREC = ("bulk", "junk", "list", "auto_reply")
_AUTO_LOCAL = ("mailer-daemon", "postmaster")


# ---- the reference of a ticket and the request address of a list
def rq_ref(c, p):
    return P.pt_ref(c, p)


def rq_token(c, lid):
    return c.execute("SELECT * FROM hub_tokens WHERE kind='ticket' AND list_id=?", (lid,)).fetchone()


def rq_address(c, lid):
    """The request address of list lid while its switch is on ('' otherwise)."""
    l = c.execute("SELECT req_mail FROM lists WHERE id=?", (lid,)).fetchone()
    r = rq_token(c, lid) if l and l["req_mail"] else None
    return M.mail_addr(r["token"]) if r and M.MAIL_IN_ON else ""


def _addr(v):
    return email.utils.parseaddr(str(v or ""))[1].strip().lower()


def rq_own(sender):
    """A mail from one of the server's own addresses (its mailbox incl. plus addresses, its sender address): never taken (loops)."""
    if not sender:
        return True
    own = set()
    for a in (M.MAIL_ADDRESS, M.SMTP.get("from") or ""):
        a = _addr(a)
        if a:
            own.add(a)
    loc, _, dom = sender.partition("@")
    return sender in own or any(f"{loc.split('+', 1)[0]}@{dom}" == o for o in own)


def rq_auto(msg, sender):
    """An automatic mail (RFC 3834 Auto-Submitted, Precedence, out-of-office headers, a delivery report)."""
    a = str(msg.get("Auto-Submitted", "") or "").strip().lower()
    if a and a != "no":
        return True
    if str(msg.get("Precedence", "") or "").strip().lower() in _AUTO_PREC:
        return True
    if msg.get("X-Autoreply") or msg.get("X-Autorespond"):
        return True
    if msg.get_content_type() == "multipart/report":
        return True
    return sender.partition("@")[0] in _AUTO_LOCAL


def _list_ok(c, lid):
    """The list row when its request address takes mails: switch on, the list alive, a project that may have an address, no lock,
    its owner active, the customer portal on."""
    l = c.execute(f"SELECT l.id, l.org_id, l.owner_id, l.name, l.e2e, l.req_mail, l.req_mail_done, l.deleted_at, u.disabled AS o_off, "
                  f"{H._NO_MAIL} AS no_mail FROM lists l JOIN users u ON u.id=l.owner_id WHERE l.id=?", (lid,)).fetchone()
    if not l or not l["req_mail"] or l["deleted_at"] or l["e2e"] or l["no_mail"] or l["o_off"] or le2b_list_locked(c, lid):
        return None
    if not public_links_on(c, "portal"):
        return None
    return l


# ---- the mail in (hub/hubmail.py hbm_mail_import -> HBM_TICKET_HOOK["take"], inside its system context; the caller commits)
def rq_find(c, msg, lid, sender):
    """(ticket row or None, the ticket id a reference named): the live ticket of list lid that the mail answers -- by the reference
    of its subject or a Message-ID of that ticket -- and whose reporter is the sender. A reference with another sender: (None, id)."""
    named = []
    for pid, sig in RQ_REF_RE.findall(str(msg.get("Subject", "") or "")):
        named.append((int(pid), sig.lower()))
    refs = [x for x in re.findall(r"<[^<>\s]{1,290}>", " ".join(str(v) for v in msg.get_all("In-Reply-To", []) + msg.get_all("References", [])))][-30:]
    cand = []
    for pid, sig in named:
        p = c.execute(f"""SELECT p.* FROM portal_tickets p JOIN tasks t ON t.id=p.task_id JOIN lists l ON l.id=t.list_id
                          WHERE p.id=? AND p.list_id=? AND t.list_id=? AND t.deleted_at IS NULL AND {P._pt_space_sql()}""", (pid, lid, lid)).fetchone()
        if p and hmac.compare_digest(sig, rq_ref(c, p).split("-", 1)[1]):
            cand.append(p)
    if refs:
        q = ",".join("?" * len(refs))
        for r in c.execute(f"""SELECT DISTINCT p.* FROM task_mail m JOIN portal_tickets p ON p.task_id=m.task_id JOIN tasks t ON t.id=p.task_id
                               JOIN lists l ON l.id=t.list_id WHERE m.msg_id IN ({q}) AND p.list_id=? AND t.list_id=? AND t.deleted_at IS NULL
                               AND {P._pt_space_sql()}""", (*refs, lid, lid)).fetchall():
            cand.append(r)
    for p in cand:
        if sender and P.pt_email_norm(P.pt_email(c, p)) == sender:
            return p, p["id"]
    return None, (cand[0]["id"] if cand else None)


def _keep(c, tid, mid, kind):
    """A Message-ID of the ticket's task (task_mail, no address kept: the reporter lives in portal_tickets)."""
    mid = str(mid or "").strip()
    if _MID_RE.fullmatch(mid):
        c.execute("INSERT INTO task_mail(task_id,msg_id,sender,kind,created_at) VALUES(?,?,?,?,?)", (tid, mid, "", kind, iso(now_utc())))


def _files(c, tid, files, owner, top_comment=None):
    """The mail's files as files of task tid (the usual checks in save_attachment_bytes); -> False when one was too large / not stored."""
    whole = len(files) <= RQ_FILES
    top = c.execute("SELECT COALESCE(MAX(id),0) FROM attachments WHERE task_id=?", (tid,)).fetchone()[0]
    for name, mime, data in files[:RQ_FILES]:
        if 0 < len(data) <= MAX_FILE_MB * 1024 * 1024:
            try:
                save_attachment_bytes(c, tid, unexec_name(name), mime, data, owner=owner)
            except OSError:
                whole = False
                break
        elif data:
            whole = False
    if top_comment:
        c.execute("UPDATE attachments SET comment_id=? WHERE task_id=? AND id>?", (top_comment, tid, top))
    return whole


def rq_comment(c, msg, mid, p, l, verified):
    """The reporter's reply as a comment of ticket p that the customer sees (portal = 1, no account). -> task id (MailKept when a
    file could not be stored)."""
    text, files = M.mail_text(msg)
    text = tmr_trim(text)
    lg = lang(c, l["owner_id"])
    if not verified:
        text = (text + "\n\n" if text else "") + "— " + tr("By e-mail, the sender is not verified", lg=lg)
    if not text and not files:
        return 0
    name = (p["name"] or "").strip() or email.utils.parseaddr(str(msg.get("From", "")))[0].strip()[:120] or tr("Client", lg=lg)
    tid = p["task_id"]
    cid = insert_id(c, "INSERT INTO comments(task_id,user_id,body,mentions,created_at,ext_name,portal) VALUES(?,?,?,?,?,?,1)",
                    (tid, None, (text or "—")[:P.PT_CMT_MAX], "", iso_ms(now_utc()), name[:120]))
    whole = _files(c, tid, files, l["owner_id"], top_comment=cid)
    _keep(c, tid, mid, "in")
    t = c.execute("SELECT t.*, l.owner_id AS l_owner FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.id=?", (tid,)).fetchone()
    people = ({t["l_owner"], t["created_by"], t["assignee_id"]} | wat_users(c, tid)) - {None}
    ag = {r[0] for r in c.execute("SELECT id FROM users WHERE kind='agent'")} if people else set()  # agents get the event below
    for u in sorted(people - ag):
        s = collab_user(c, u, t["list_id"])
        if s and task_visible(c, tid, u, full=True):  # News only: the mail round has no request (no pushes)
            news_add(c, u, "comment", task_id=tid, comment_id=cid, actor=0, s=s, data={"excerpt": text[:300], "ext_name": name, "portal": True})
    M.agent_comment_events(c, t, cid, [], [])
    bump(c)
    return tid if whole else M.MailKept(tid)


def rq_new(c, msg, mid, l, sender, verified, auto, hint=""):
    """A new ticket of list l from the mail; -> (task id or MailKept, the confirmation to queue or None)."""
    lid = l["id"]
    lg = lang(c, l["owner_id"])
    subj = re.sub(r"\s+", " ", M.MAIL_PREFIX_RE.sub("", str(msg.get("Subject", "") or ""))).strip()
    subj = RQ_REF_RE.sub("", subj).strip()
    text, files = M.mail_text(msg)
    name = re.sub(r"\s+", " ", email.utils.parseaddr(str(msg.get("From", "")))[0]).strip()[:120]
    title = (subj or (text.split("\n", 1)[0][:120] if text else "") or tr("E-mail", lg=lg))[:RQ_TITLE_MAX]
    who = (fq_md(name) + " " if name else "") + (f"<{sender}>" if re.fullmatch(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+", sender) else fq_md(sender))
    meta = tr("Sent by e-mail to the request address by {0}", who, lg=lg)
    if not verified:
        meta += " · " + tr("the sender is not verified", lg=lg)
    if hint:
        meta += " · " + hint
    content = (text + "\n\n" if text else "") + "— " + meta
    ts = iso(now_utc())
    srt = c.execute("SELECT COALESCE(MIN(sort),0)-1 FROM tasks WHERE list_id=? AND parent_id IS NULL", (lid,)).fetchone()[0]
    tid = insert_id(c, "INSERT INTO tasks(list_id,title,content,sort,created_at,updated_at,tt_id,created_by) VALUES(?,?,?,?,?,?,?,?)",
                    (lid, title, content, srt, ts, ts, "mail:" + mid, None))
    ptid, ptok = P.pt_create(c, tid, {"id": lid, "org_id": l["org_id"], "owner_id": l["owner_id"]}, None, name, sender)
    c.execute("UPDATE portal_tickets SET via='mail', unverified=?, lang=? WHERE id=?", (0 if verified else 1, lg, ptid))
    _keep(c, tid, mid, "src")
    whole = _files(c, tid, files, l["owner_id"])
    log_act(c, tid, "created", {"portal": 1, "mail": 1})
    M.agent_added_events(c, tid, source="mail", info={"portal": True})
    bump(c)
    conf = None
    e = P.pt_email_norm(sender)
    if e and not auto and frm_mail_ok(c, P.pt_email_hash(c, e), e) and r81c_form_mail_day(c, None, key=f"rq:{lid}"):
        p = {"id": ptid, "token_hash": _token_hash(ptok)}
        ref = rq_ref(c, p)
        url = P.pt_mail_url(c, p, ptok)
        out = _msg_id()
        _keep(c, tid, out, "out")
        subject = (tr("Your request: {0}", " ".join(title.split()), lg=lg)[:180] + f" [{ref}]")
        body_ = "\n\n".join((tr("Thank you for your request “{0}”. It has been received.", " ".join(title.split()), lg=lg),
                             tr("You can see its status and our answers at any time with this link:", lg=lg) + "\n" + url,
                             tr("Reply to this e-mail to add something to your request.", lg=lg),
                             tr("Keep this link to yourself: anyone who has it can see this request.", lg=lg),
                             tr("You get this e-mail because a request was sent from this address. If that was not you, you can ignore it.", lg=lg)))
        conf = (e, subject, body_, "", "", rq_address(c, lid), out, [mid] if _MID_RE.fullmatch(mid) else [], True)
    return (tid if whole else M.MailKept(tid)), conf


def _msg_id():
    frm = M.SMTP.get("from") or ""
    return email.utils.make_msgid(domain=(frm.rpartition("@")[2] or "kalmido.local"))


def rq_take(c, r, msg, raw):
    """A mail to the request address r (hub_tokens kind 'ticket'). -> task id (MailKept: a file not stored) or 0 (not taken)."""
    l = _list_ok(c, r["list_id"])
    if not l:
        return 0  # switch off, list gone / locked / no portal: like an unknown address (the mail stays seen in the mailbox)
    sender = _addr(msg.get("From"))
    if rq_own(sender):
        return 0
    mid = str(msg.get("Message-ID", "") or "").strip()[:300] or ("sha:" + hashlib.sha256(raw).hexdigest())
    lid = l["id"]
    if c.execute("SELECT 1 FROM tasks WHERE tt_id=? AND list_id=?", ("mail:" + mid, lid)).fetchone() or \
            c.execute("SELECT 1 FROM task_mail m JOIN tasks t ON t.id=m.task_id WHERE m.msg_id=? AND m.kind IN ('src','in') AND t.list_id=?",
                      (mid, lid)).fetchone():
        return 0  # the same mail again
    auto = rq_auto(msg, sender)
    verified = H.hbm_from_verified(msg, sender)
    p, named = rq_find(c, msg, lid, sender)
    if p:
        if auto:
            return 0  # an out-of-office answer to an answer never becomes a comment
        return rq_comment(c, msg, mid, p, l, verified)
    if msg.get_content_type() == "multipart/report" or sender.partition("@")[0] in _AUTO_LOCAL:
        return 0  # review N5: a delivery report / mailer daemon (a bounce of our own confirmation) is never a ticket
    if hit_limit(f"rqin:{lid}", RQ_IN_HOUR, 3600) or hit_limit(f"rqine:{lid}:{P.pt_email_hash(c, sender)}", RQ_IN_SENDER_HOUR, 3600):
        return 0
    hint = tr("Reply to ticket T{0}, the sender is not its reporter", named, lg=lang(c, l["owner_id"])) if named else ""
    tid, conf = rq_new(c, msg, mid, l, sender, verified, auto, hint)
    if conf:
        c.commit()  # the ticket first, then its confirmation (the worker sends it)
        bgj_add("mail:reqmail", *conf)
    return tid


@bgj_fn("mail:reqmail", tries=1)
def rq_mail_bg(to, subject, text, html_body, unsub, reply_to, msg_id, refs, auto):
    """The background part: one mail of a mail ticket (confirmation / answer) with its thread headers."""
    try:
        m = M.mail_message(to, subject, text, html_body or None, from_name=APP_NAME, reply_to=reply_to or None, unsub=unsub or None)
        if msg_id:
            m.replace_header("Message-ID", msg_id)
        if refs:
            m["In-Reply-To"] = refs[-1]
            m["References"] = " ".join(refs[-10:])
        if auto:
            m["Auto-Submitted"] = "auto-replied"  # RFC 3834: an answering machine on the other side stays quiet
        M.mail_deliver(m)
    except Exception as ex:  # noqa: BLE001  (nobody waits for this; the status page has everything)
        print("request mail failed:", type(ex).__name__, flush=True)  # no addresses in the log


def rq_mail_out(c, p, em, subj, text, html_body, stop):
    """team/portal.py pt_mail_tick -> the queued mail of a mail ticket: the reference in the subject, Reply-To = the request
    address (while the switch is on), the thread headers; its Message-ID is stored before it goes out."""
    ref = rq_ref(c, p)
    out = _msg_id()
    ids = tmr_ids(c, p["task_id"])
    _keep(c, p["task_id"], out, "out")
    return ("mail:reqmail", em, subj[:180] + f" [{ref}]", text, html_body, stop, rq_address(c, p["list_id"]), out, ids, False)


H.HBM_TICKET_HOOK.update(take=rq_take)
P.PT_MAIL_HOOK.update(out=rq_mail_out)


# ---- the switch of a project (owner / project admins, people only)
def _rq_need(c, lid):
    M.need_person(403, tr("Only people can file e-mails"))
    role = need_list(c, lid, write=False)
    if role not in MANAGE_ROLES:
        raise Denied(403, tr("Only the owner and project admins can turn requests by e-mail on"))
    return role


def rq_state(c, lid):
    l = c.execute(f"SELECT l.req_mail, l.req_mail_done, l.e2e, {H._NO_MAIL} AS no_mail FROM lists l WHERE l.id=?", (lid,)).fetchone()
    why = ""
    if not M.MAIL_IN_ON or not M.MAIL_OUT_ON:
        why = "mail"
    elif not public_links_on(c, "portal"):
        why = "portal"
    elif l["no_mail"]:
        why = "kind"
    elif l["e2e"] or le2b_list_locked(c, lid):
        why = "e2e"
    return {"on": bool(l["req_mail"]), "done_mail": bool(l["req_mail_done"]), "address": rq_address(c, lid), "available": not why, "why": why}


@app.get("/api/lists/<int:lid>/request-mail")
def rq_get(lid):
    """{on, done_mail, address, available, why}: the project's switch "Requests by e-mail" (owner / project admins)."""
    c = db()
    _rq_need(c, lid)
    return jsonify(rq_state(c, lid))


@app.patch("/api/lists/<int:lid>/request-mail")
def rq_set(lid):
    """{on?: bool, done_mail?: bool, renew?: true}: on = the request address (made on the first switch-on, kept when switched off
    and on again), renew = a new address (the old one stops), done_mail = also a mail when a ticket is done."""
    c = db()
    _rq_need(c, lid)
    b = body() if isinstance(body(), dict) else {}
    if set(b) - {"on", "done_mail", "renew"} or any(k in b and not isinstance(b[k], bool) for k in ("on", "done_mail", "renew")):
        return err(tr("Expected {0}", '{"on": true|false, "done_mail": true|false, "renew": true}'))
    st = rq_state(c, lid)
    if (b.get("on") or b.get("renew")) and not st["available"]:
        if st["why"] == "e2e":
            return err(le2b_off(), 409)
        if st["why"] == "kind":
            return err(tr("Only projects have an e-mail address"), 409)
        if st["why"] == "portal":
            return err(tr("Public links are turned off on this server"), 409)
        return err(tr("E-mail to tasks is not set up on this server"), 409)
    l = c.execute("SELECT org_id FROM lists WHERE id=?", (lid,)).fetchone()
    if "on" in b:
        c.execute("UPDATE lists SET req_mail=? WHERE id=?", (1 if b["on"] else 0, lid))
    if "done_mail" in b:
        c.execute("UPDATE lists SET req_mail_done=? WHERE id=?", (1 if b["done_mail"] else 0, lid))
    old = rq_token(c, lid)
    if (b.get("on") and not old) or (b.get("renew") and old):
        tok = secrets.token_urlsafe(12).replace("-", "x").replace("_", "y")
        c.execute("DELETE FROM hub_tokens WHERE kind='ticket' AND list_id=?", (lid,))
        c.execute("INSERT INTO hub_tokens(token,kind,user_id,org_id,client_id,list_id,created_at) VALUES(?,?,?,?,?,?,?)",
                  (tok, "ticket", me(), l["org_id"], None, lid, iso(now_utc())))
    bump(c)
    c.commit()
    return jsonify(rq_state(c, lid))
