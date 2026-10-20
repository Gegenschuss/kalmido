"""Tasks by e-mail (IMAP) and the daily summary by e-mail (SMTP)."""
import email.message
import email.policy
import email.utils
import hashlib
import html
import imaplib
import os
import re
import secrets
import smtplib
import threading
from datetime import date, timedelta
from flask import g, jsonify, request

from ..core.config import app, APP_NAME, MAX_FILE_MB, PUBLIC_URL
from ..core.pg import insert_id, table_exists
from ..core.i18n import lang, md_plain, tr, trn
from ..core.db import body, bump, connect, db, err, iso, local_now, now_utc, uset, usettings
from ..accounts.session import GATE, me
from ..core.access import Denied, list_role, need_list, vis_sql, WRITE_ROLES
from ..core.pages import new_inbox_task, save_attachment_bytes, split_link, valid_url
from ..tasks.validation import as_int, log_act
from ..collab.news import news_unread
from ..accounts.users import need_admin
from ..notify.alerts import aa_err, aa_fail, aa_ok
from ..agents.core import is_agent
from ..collab.teamchat import tchat_unread


# ---------------------------------------------------------------- 2.17.0 (#443): tasks by e-mail + the daily summary by e-mail
# In: one mailbox the admin sets up (KALMIDO_IMAP_*), polled every KALMIDO_IMAP_INTERVAL seconds. Every person gets a
# personal address with a secret token (plus addressing: tasks+<token>@example.com -> their inbox) and may make one per
# list (-> that list, while they may change it). Subject = title, the text = the description, attachments = files (the
# usual size limit), "Fwd:" / "WG:" prefixes are dropped. Optionally (setting mail_from_me) mails FROM the person's own
# e-mail address to the plain address land in their inbox too (sender addresses can be forged: off by default).
# Read mails are marked \Seen and never imported twice (Message-ID). Out: KALMIDO_SMTP_* sends the daily summary (digest
# time of the push, setting digest_mail) to the person's e-mail address.
MAIL_ADDRESS = os.environ.get("KALMIDO_MAIL_ADDRESS", "").strip()
IMAP = {"host": os.environ.get("KALMIDO_IMAP_HOST", "").strip(), "port": int(os.environ.get("KALMIDO_IMAP_PORT", "0") or 0),
        "user": os.environ.get("KALMIDO_IMAP_USER", "").strip(), "password": os.environ.get("KALMIDO_IMAP_PASSWORD", ""),
        "folder": os.environ.get("KALMIDO_IMAP_FOLDER", "INBOX").strip() or "INBOX",
        "ssl": os.environ.get("KALMIDO_IMAP_SSL", "1").strip().lower() not in ("0", "false", "no", "off"),
        "interval": max(10, int(os.environ.get("KALMIDO_IMAP_INTERVAL", "60") or 60))}
SMTP = {"host": os.environ.get("KALMIDO_SMTP_HOST", "").strip(), "port": int(os.environ.get("KALMIDO_SMTP_PORT", "0") or 0),
        "user": os.environ.get("KALMIDO_SMTP_USER", "").strip(), "password": os.environ.get("KALMIDO_SMTP_PASSWORD", ""),
        "tls": (os.environ.get("KALMIDO_SMTP_TLS", "starttls").strip().lower() or "starttls"),
        "from": os.environ.get("KALMIDO_MAIL_FROM", "").strip() or MAIL_ADDRESS}
MAIL_IN_ON = bool(MAIL_ADDRESS and IMAP["host"] and IMAP["user"])
MAIL_OUT_ON = bool(SMTP["host"] and SMTP["from"])
MAIL_TOKEN_RE = re.compile(r"\+([A-Za-z0-9_-]{10,40})@")
MAIL_BODY_MAX, MAIL_PREFIX_RE = 20000, re.compile(r"^\s*((fwd?|wg|aw|re|tr|rv|fw|doorst|antw)\s*:\s*)+", re.I)


def mail_addr(token):
    local, _, dom = MAIL_ADDRESS.partition("@")
    return f"{local}+{token}@{dom}" if token and dom else ""


def mail_tokens(c, uid):
    return {r["list_id"]: r["token"] for r in c.execute("SELECT * FROM mail_tokens WHERE user_id=?", (uid,))}


@app.get("/api/me/mail")
def mail_info():
    """My e-mail addresses for new tasks (personal = inbox, per list), the daily summary by mail."""
    c = db()
    uid = me()
    s = usettings(c, uid)
    toks = mail_tokens(c, uid)
    lists = []
    for lid, t in toks.items():
        if lid is None:
            continue
        l = c.execute("SELECT id, name, e2e FROM lists WHERE id=?", (lid,)).fetchone()
        if l and list_role(c, lid) in WRITE_ROLES:
            if l["e2e"]:  # 2.64.1 B (#1817): the address is off in a list with the lock (the dialog shows why)
                from ..collab.liste2eguard import le2b_off
                lists.append({"list_id": lid, "name": l["name"], "address": "", "e2e": True, "reason": le2b_off()})
                continue
            lists.append({"list_id": lid, "name": l["name"], "address": mail_addr(t)})
    u = c.execute("SELECT email FROM users WHERE id=?", (uid,)).fetchone()
    return jsonify(enabled=MAIL_IN_ON, address=mail_addr(toks.get(None)) if MAIL_IN_ON else "", plain=MAIL_ADDRESS if MAIL_IN_ON else "",
                   lists=lists if MAIL_IN_ON else [], from_me=s.get("mail_from_me") == "1",
                   trim_fwd=s.get("mail_trim_fwd") == "1", trim_eml=s.get("mail_trim_eml") != "0",  # 2.49.0 (#971) email=(u["email"] if u else "") or "",
                   digest={"enabled": MAIL_OUT_ON, "on": s.get("digest_mail") == "1", "time": s.get("digest_time") or ""})


@app.post("/api/me/mail/token")
def mail_token_new():
    """{list_id?} -- a new address (the old one stops working): personal (inbox) or for a list I may change."""
    c = db()
    if not MAIL_IN_ON:
        return err(tr("E-mail to tasks is not set up on this server"), 409)
    if is_agent(g.user):
        raise Denied(403)
    lid = body().get("list_id")
    if lid is not None:
        if isinstance(lid, bool) or not isinstance(lid, int):
            return err(tr("Invalid value: {0}", "list_id"))
        need_list(c, lid)
        from ..collab.liste2eguard import le2b_list_locked, le2b_off
        if le2b_list_locked(c, lid):  # 2.64.1 B (#1817): no mail address for a list with the lock
            return jsonify(error=le2b_off(), code="list_e2e"), 409
    tok = secrets.token_urlsafe(12).replace("-", "x").replace("_", "y")
    c.execute("DELETE FROM mail_tokens WHERE user_id=? AND list_id IS NOT DISTINCT FROM ?", (me(), lid))
    c.execute("INSERT INTO mail_tokens(token,user_id,list_id,created_at) VALUES(?,?,?,?)", (tok, me(), lid, iso(now_utc())))
    c.commit()
    return jsonify(address=mail_addr(tok), list_id=lid)


@app.delete("/api/me/mail/token")
def mail_token_del():
    """?list_id= (none = the personal address) -- the address stops working."""
    c = db()
    lid = request.args.get("list_id")
    lid = as_int(lid, "list_id", 1) if lid else None
    c.execute("DELETE FROM mail_tokens WHERE user_id=? AND list_id IS NOT DISTINCT FROM ?", (me(), lid))
    c.commit()
    return jsonify(ok=True)


def mail_text(msg, limit=MAIL_BODY_MAX):
    """(text, [(name, mime, bytes)]) of an email.message.EmailMessage: text/plain preferred, else HTML without tags.
    2.84.0 (#1198): limit = characters kept (the hub files longer texts)."""
    plain = html_ = None
    files = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        disp = (part.get_content_disposition() or "").lower()
        ctype = part.get_content_type()
        name = part.get_filename()
        if disp == "attachment" or (name and disp != "inline") or (name and not ctype.startswith("text/")):
            try:
                data = part.get_payload(decode=True) or b""
            except Exception:  # noqa: BLE001
                data = b""
            if data:
                files.append((name or "file", ctype, data))
            continue
        try:
            txt = part.get_content()
        except Exception:  # noqa: BLE001
            continue
        if ctype == "text/plain" and plain is None:
            plain = txt
        elif ctype == "text/html" and html_ is None:
            html_ = txt
    if plain is None and html_:
        t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", html_)
        t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>", "\n", t)
        t = re.sub(r"<[^>]+>", "", t)
        plain = html.unescape(t)
    text = re.sub(r"\n{3,}", "\n\n", (plain or "").replace("\r\n", "\n")).strip()
    return text[:limit], files


def mail_target(c, msg):
    """(user id, list id or None) the mail is for, or (None, None): a token in To / Cc / Delivered-To / X-Original-To, else
    (mail_from_me) the sender's address of a person who allowed that."""
    hdrs = " ".join(str(msg.get_all(h, [])) for h in ("To", "Cc", "Delivered-To", "X-Original-To", "Envelope-To"))
    for tok in MAIL_TOKEN_RE.findall(hdrs):
        r = c.execute("SELECT * FROM mail_tokens WHERE token=?", (tok,)).fetchone()
        if r:
            u = c.execute("SELECT disabled FROM users WHERE id=?", (r["user_id"],)).fetchone()
            if not u or u["disabled"]:
                return None, None
            from ..collab.liste2eguard import le2b_list_locked
            if r["list_id"] and le2b_list_locked(c, r["list_id"]):
                return None, None  # 2.64.1 B (#1817): a list with the lock takes no mail (like an unknown address)
            if r["list_id"] and list_role(c, r["list_id"], r["user_id"]) not in WRITE_ROLES:
                return r["user_id"], None  # no longer allowed in that list: the inbox
            return r["user_id"], r["list_id"]
    sender = email.utils.parseaddr(str(msg.get("From", "")))[1].strip().lower()
    if sender:
        for r in c.execute("SELECT u.id FROM users u JOIN user_settings s ON s.user_id=u.id AND s.key='mail_from_me' AND s.value='1' "
                           "WHERE lower(u.email)=? AND u.disabled=0", (sender,)):
            return r[0], None
    return None, None


def mail_import(c, raw):
    """One message (bytes) -> one task. Returns the task id, None when it is for nobody or already imported."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    from ..docs.ingest import docs_mail_import  # 2.48.0 (#1111): a document address -> its attachments become documents
    d = docs_mail_import(c, msg, raw)
    if d is not None:
        return d or None
    from ..hub.hubmail import hbm_mail_import  # 2.84.0 (#1198): a hub address (client / project / hub inbox) -> a filed mail
    h = hbm_mail_import(c, msg, raw)
    if h is not None:
        return h or None
    mid = str(msg.get("Message-ID", "")).strip()[:300] or ("sha:" + hashlib.sha256(raw).hexdigest())
    if c.execute("SELECT 1 FROM tasks WHERE tt_id=?", ("mail:" + mid,)).fetchone():
        return None
    uid, lid = mail_target(c, msg)
    if not uid:
        return None
    subj = MAIL_PREFIX_RE.sub("", str(msg.get("Subject", "")).replace("\n", " ")).strip()
    text, files = mail_text(msg)
    us = usettings(c, uid)
    eml = None
    if us.get("mail_trim_fwd") == "1":  # 2.49.0 (#971): a forwarded mail shrinks to one header line + the message; the original stays as .eml
        from .mailtrim import md_trim_forward
        short = md_trim_forward(text)
        if short != text:
            text = short
            if us.get("mail_trim_eml") != "0":
                eml = raw
    lg = lang(c, uid)
    sender = str(msg.get("From", "")).strip()
    title = subj or (text.split("\n", 1)[0][:120] if text else tr("E-mail", lg=lg))
    content = (text + "\n\n" if text else "") + f"— {tr('E-mail from {0}', sender, lg=lg)}" if sender else text
    title, content, url = split_link(title, content)
    if lid:
        ts = iso(now_utc())
        srt = c.execute("SELECT COALESCE(MIN(sort),0)-1 FROM tasks WHERE list_id=? AND parent_id IS NULL", (lid,)).fetchone()[0]
        tid = insert_id(c, "INSERT INTO tasks(list_id,title,content,sort,created_at,updated_at,tt_id,created_by,url) VALUES(?,?,?,?,?,?,?,?,?)",
                        (lid, title[:300], content, srt, ts, ts, "mail:" + mid, uid, url if valid_url(url) else None))
        log_act(c, tid, "created", uid=uid)
        from ..agents.core import agent_added_events
        agent_added_events(c, tid, source="mail")  # 2.23.0 (#795)
    else:
        tid = new_inbox_task(c, uid, title, content, "mail:" + mid, url)
    if eml is not None:
        files = [((subj[:60].replace("/", "-").strip() or "mail") + ".eml", "message/rfc822", eml)] + files
    for name, mime, data in files[:20]:
        if 0 < len(data) <= MAX_FILE_MB * 1024 * 1024:
            try:
                save_attachment_bytes(c, tid, name, mime, data)
            except OSError:
                break
    bump(c)
    c.commit()
    return tid


def mail_fetch(M, folder, importer):
    """2.141.0 A (#2141): the unseen mails of folder (a logged-in IMAP connection) -> importer(c, raw), each one marked \\Seen
    afterwards (also when it was for nobody or failed: it is never looked at again). Returns how many were taken in."""
    n = 0
    typ, _ = M.select(folder)
    if typ != "OK":
        raise imaplib.IMAP4.error("SELECT failed")
    typ, data = M.uid("SEARCH", None, "UNSEEN")
    for u in (data[0] or b"").split()[:200]:
        typ, parts = M.uid("FETCH", u, "(RFC822)")
        raw = next((p[1] for p in parts if isinstance(p, tuple) and len(p) > 1), None)
        if raw:
            with GATE.bg():
                c = connect()
                try:
                    if importer(c, raw):
                        n += 1
                except Exception as e:  # noqa: BLE001 - 2.126.0 review: one mail that fails is skipped (marked seen), never blocks the rest
                    print("mail: skipped one mail:", type(e).__name__, e, flush=True)
                    try:
                        c.rollback()
                    except Exception:  # noqa: BLE001
                        pass
                finally:
                    c.close()
        M.uid("STORE", u, "+FLAGS", "(\\Seen)")
    return n


def mail_poll_once():
    """One round: the unseen mails of the folder -> tasks; each one is marked \\Seen afterwards (also when it was for
    nobody: it is never looked at again)."""
    port = IMAP["port"] or (993 if IMAP["ssl"] else 143)
    M = imaplib.IMAP4_SSL(IMAP["host"], port, timeout=60) if IMAP["ssl"] else imaplib.IMAP4(IMAP["host"], port, timeout=60)
    try:
        M.login(IMAP["user"], IMAP["password"])
        return mail_fetch(M, IMAP["folder"], mail_import)
    finally:
        try:
            M.logout()
        except Exception:  # noqa: BLE001
            pass


_MAIL_WAKE = threading.Event()


def mail_loop():
    while True:
        try:
            n = mail_poll_once()
            aa_ok("mail")
            if n:
                print("mail: imported", n, "task(s)", flush=True)
        except Exception as e:  # noqa: BLE001
            print("mail:", type(e).__name__, e, flush=True)
            aa_fail("mail", aa_err(e))
        _MAIL_WAKE.wait(IMAP["interval"])
        _MAIL_WAKE.clear()


@app.post("/api/admin/mail/poll")
def mail_poll_now():
    """Admins: look into the mailbox now (instead of waiting for the next round)."""
    need_admin()
    if not MAIL_IN_ON:
        return err(tr("E-mail to tasks is not set up on this server"), 409)
    _MAIL_WAKE.set()
    return jsonify(ok=True)


class _SafeSMTP(smtplib.SMTP):
    """2.141.0 A (#2141): SMTP to a host a workspace entered: every address of the name is checked (no internal host unless
    the admin allowed it, calendars/subscriptions.py cal_allow) and exactly the checked one is connected to."""
    def __init__(self, host, port, timeout, allow):
        self._kal_allow = allow
        super().__init__(host, port, timeout=timeout)

    def _get_socket(self, host, port, timeout):
        from ..calendars.subscriptions import _cal_connector
        return _cal_connector(self._kal_allow)((host, port), timeout)


class _SafeSMTP_SSL(smtplib.SMTP_SSL):
    def __init__(self, host, port, timeout, allow):
        self._kal_allow = allow
        super().__init__(host, port, timeout=timeout)

    def _get_socket(self, host, port, timeout):
        from ..calendars.subscriptions import _cal_connector
        return self.context.wrap_socket(_cal_connector(self._kal_allow)((host, port), timeout), server_hostname=self._host)


def smtp_open(smtp=None):
    """2.141.0 A (#2141): a connected and logged-in SMTP session: KALMIDO_SMTP_* (smtp None), else a workspace's access
    {host, port, tls, user, password, from, allow} (allow = the hosts that may be internal: the connection is checked)."""
    cfg = smtp or SMTP
    tls = cfg["tls"]
    port = cfg["port"] or (465 if tls == "ssl" else 587 if tls == "starttls" else 25)
    if smtp is None:
        S_ = smtplib.SMTP_SSL(cfg["host"], port, timeout=30) if tls == "ssl" else smtplib.SMTP(cfg["host"], port, timeout=30)
    else:
        allow = cfg.get("allow") or frozenset()
        S_ = _SafeSMTP_SSL(cfg["host"], port, 30, allow) if tls == "ssl" else _SafeSMTP(cfg["host"], port, 30, allow)
    try:
        if tls == "starttls":
            S_.starttls()
        if cfg["user"]:
            S_.login(cfg["user"], cfg["password"])
    except BaseException:
        try:
            S_.close()
        except Exception:  # noqa: BLE001
            pass
        raise
    return S_


def mail_message(to, subject, text, html_body=None, images=None, from_name=None, attachments=None, cc=None, reply_to=None, smtp=None):
    """2.141.0 A (#2141): the message mail_send sends (built first so the e-mail filing can keep it before it goes out)."""
    from ..collab.liste2eguard import le2b_net
    subject, text = le2b_net(subject), le2b_net(text)  # 2.64.1 B (#1817): never a ciphertext of a list with the lock in a mail
    html_body = le2b_net(html_body) if html_body else html_body
    frm = (smtp or SMTP)["from"]
    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"] = (email.utils.formataddr((from_name, frm)) if from_name else frm), to, subject
    if cc:
        m["Cc"] = cc
    if reply_to:
        m["Reply-To"] = reply_to
    m["Date"] = email.utils.formatdate(localtime=True)
    m["Message-ID"] = email.utils.make_msgid(domain=(frm.rpartition("@")[2] or "kalmido.local"))
    m.set_content(text)
    if html_body:
        m.add_alternative(html_body, subtype="html")
        for cid, (data, sub) in (images or {}).items():
            m.get_payload()[1].add_related(data, "image", sub, cid=f"<{cid}>")
    for name, data, mime in attachments or []:
        main, _, sub = (mime or "application/octet-stream").partition("/")
        m.add_attachment(data, maintype=main or "application", subtype=sub or "octet-stream", filename=name)
    return m


def mail_deliver(m, smtp=None):
    """2.141.0 A (#2141): sends a built message (mail_message) through KALMIDO_SMTP_* or the access smtp; raises on failure."""
    S_ = smtp_open(smtp)
    try:
        S_.send_message(m)
    finally:
        try:
            S_.quit()
        except Exception:  # noqa: BLE001
            pass


def mail_send(to, subject, text, html_body=None, images=None, from_name=None, attachments=None, cc=None, reply_to=None, smtp=None):
    """Sends one mail with KALMIDO_SMTP_*; raises on failure. images: {cid: (bytes, subtype)} shown in the HTML part
    (2.22.0: the logo of the invitation); from_name: a display name for the sender. 2.38.0 (#1021): attachments =
    [(file name, bytes, mime type)] (invoice PDF / XML), cc = a second address, reply_to = the sender's own address.
    2.141.0 A (#2141): smtp = a workspace's own SMTP access instead (hub/mailbox.py mbx_smtp); returns the message sent."""
    m = mail_message(to, subject, text, html_body, images, from_name, attachments, cc, reply_to, smtp=smtp)
    mail_deliver(m, smtp)
    return m


def digest_mail_content(c, uid, today):
    """(subject, text, html) of a person's daily summary: due today / overdue, tomorrow, what waits for them, unread."""
    lg = lang(c, uid)
    rows = c.execute(f"""SELECT t.id, t.title, t.due, t.due_time, t.priority, l.name AS lname, l.e2e AS le2e FROM tasks t JOIN lists l ON l.id=t.list_id
                         WHERE t.status=0 AND t.deleted_at IS NULL AND t.parent_id IS NULL AND t.due IS NOT NULL AND t.due<=? AND l.archived=0
                           AND ((l.owner_id=? AND (t.assignee_id IS NULL OR t.assignee_id=?)) OR (t.assignee_id=? AND t.list_id IN {vis_sql()}))
                         ORDER BY t.due, t.due_time IS NULL, t.due_time, t.priority DESC LIMIT 60""",
                     ((date.fromisoformat(today) + timedelta(days=1)).isoformat(), uid, uid, uid, uid, uid)).fetchall()
    tom = (date.fromisoformat(today) + timedelta(days=1)).isoformat()
    over = [r for r in rows if r["due"] < today]
    tod = [r for r in rows if r["due"] == today]
    tmr = [r for r in rows if r["due"] == tom]
    waits = c.execute("SELECT COUNT(*) FROM agent_jobs WHERE state='waiting' AND (user_id=? OR user_id IS NULL)", (uid,)).fetchone()[0] \
        if table_exists(c, "agent_jobs") else 0
    unread = news_unread(c, uid)
    chat = tchat_unread(c, uid)
    line = lambda r: f"- {md_plain(r['title'])}" + (f" ({r['due_time']})" if r["due_time"] else "") + f" · {r['lname']}"  # noqa: E731
    parts = []
    for head, xs in ((tr("Overdue", lg=lg), over), (tr("Today", lg=lg), tod), (tr("Tomorrow", lg=lg), tmr)):
        if xs:
            # 2.64.1 B (#1817): tasks of a list with the lock as one line per list ("3 tasks in <list> (encrypted)")
            lk = {}
            for r in xs:
                if r["le2e"]:
                    lk[r["lname"]] = lk.get(r["lname"], 0) + 1
            shown = [line(r) for r in xs if not r["le2e"]][:25]
            shown += ["- " + trn("{0} task in {1} (encrypted)", "{0} tasks in {1} (encrypted)", k, ln, lg=lg) for ln, k in lk.items()]
            parts.append(f"{head} ({len(xs)})\n" + "\n".join(shown))
    extra = []
    if waits:
        extra.append(trn("{0} approval waits for you", "{0} approvals wait for you", waits, lg=lg))
    if unread:
        extra.append(trn("{0} unread news item", "{0} unread news items", unread, lg=lg))
    if chat:
        extra.append(trn("{0} unread chat message", "{0} unread chat messages", chat, lg=lg))
    if extra:
        parts.append(" · ".join(extra))
    if not parts:
        return None
    subj = f"{APP_NAME}: " + (trn("{0} task today", "{0} tasks today", len(tod) + len(over), lg=lg) if tod or over else tr("Your day", lg=lg))
    text = "\n\n".join(parts) + f"\n\n{PUBLIC_URL}/#today\n"
    hb = "".join(f"<p>{html.escape(p).replace(chr(10), '<br>')}</p>" for p in parts)
    hb += f'<p><a href="{html.escape(PUBLIC_URL)}/#today">{html.escape(tr("Open {0}", APP_NAME, lg=lg))}</a></p>'
    return subj, text, f"<!doctype html><html><body style=\"font-family:sans-serif\">{hb}</body></html>"


def digest_mail_user(c, uid, s, today):
    if not MAIL_OUT_ON or s.get("digest_mail") != "1" or s.get("digest_mail_sent") == today:
        return False
    u = c.execute("SELECT email, disabled FROM users WHERE id=?", (uid,)).fetchone()
    if not u or u["disabled"] or not (u["email"] or "").strip():
        return False
    uset(c, uid, "digest_mail_sent", today)
    c.commit()
    m = digest_mail_content(c, uid, today)
    if not m:
        return False
    try:
        mail_send(u["email"].strip(), *m)
        aa_ok("smtp")
        return True
    except Exception as e:  # noqa: BLE001
        print("mail: summary for user", uid, "failed:", type(e).__name__, e, flush=True)
        aa_fail("smtp", aa_err(e))
        return False


@app.post("/api/me/mail/test")
def mail_test():
    """Sends the daily summary (or a short test text) to my e-mail address now."""
    c = db()
    if not MAIL_OUT_ON:
        return err(tr("E-mail sending is not set up on this server"), 409)
    u = c.execute("SELECT email FROM users WHERE id=?", (me(),)).fetchone()
    if not u or not (u["email"] or "").strip():
        return err(tr("No e-mail address is stored for you: an admin adds it (Settings > Users)"), 409)
    from ..admin.hosting import mail_budget
    from ..api.v1 import hit_limit
    if hit_limit(f"mailtest:{me()}", 5, 3600):  # 2.126.0 C (#1979 I6): a few tests an hour, counted in the daily e-mail limit
        return err(tr("Too many tests, please wait a few minutes"), 429)
    if not mail_budget(c, me(), u["email"]):
        c.rollback()
        return err(tr("Today's e-mail limit is reached. Try again tomorrow."), 429)
    c.commit()
    lg = lang(c, me())
    m = digest_mail_content(c, me(), local_now().date().isoformat()) or (f"{APP_NAME}: " + tr("Test", lg=lg), tr("E-mails from {0} are arriving.", APP_NAME, lg=lg), None)
    try:
        mail_send(u["email"].strip(), *m)
    except Exception as e:  # noqa: BLE001
        return err(tr("Sending failed: {0}", type(e).__name__), 502)
    return jsonify(ok=True, to=u["email"].strip())
