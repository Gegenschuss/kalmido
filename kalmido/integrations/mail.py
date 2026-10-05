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
from ..core.i18n import lang, tr, trn
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
        l = c.execute("SELECT id, name FROM lists WHERE id=?", (lid,)).fetchone()
        if l and list_role(c, lid) in WRITE_ROLES:
            lists.append({"list_id": lid, "name": l["name"], "address": mail_addr(t)})
    u = c.execute("SELECT email FROM users WHERE id=?", (uid,)).fetchone()
    return jsonify(enabled=MAIL_IN_ON, address=mail_addr(toks.get(None)) if MAIL_IN_ON else "", plain=MAIL_ADDRESS if MAIL_IN_ON else "",
                   lists=lists if MAIL_IN_ON else [], from_me=s.get("mail_from_me") == "1", email=(u["email"] if u else "") or "",
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
    tok = secrets.token_urlsafe(12).replace("-", "x").replace("_", "y")
    c.execute("DELETE FROM mail_tokens WHERE user_id=? AND list_id IS ?", (me(), lid))
    c.execute("INSERT INTO mail_tokens(token,user_id,list_id,created_at) VALUES(?,?,?,?)", (tok, me(), lid, iso(now_utc())))
    c.commit()
    return jsonify(address=mail_addr(tok), list_id=lid)


@app.delete("/api/me/mail/token")
def mail_token_del():
    """?list_id= (none = the personal address) -- the address stops working."""
    c = db()
    lid = request.args.get("list_id")
    lid = as_int(lid, "list_id", 1) if lid else None
    c.execute("DELETE FROM mail_tokens WHERE user_id=? AND list_id IS ?", (me(), lid))
    c.commit()
    return jsonify(ok=True)


def mail_text(msg):
    """(text, [(name, mime, bytes)]) of an email.message.EmailMessage: text/plain preferred, else HTML without tags."""
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
    return text[:MAIL_BODY_MAX], files


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
    mid = str(msg.get("Message-ID", "")).strip()[:300] or ("sha:" + hashlib.sha256(raw).hexdigest())
    if c.execute("SELECT 1 FROM tasks WHERE tt_id=?", ("mail:" + mid,)).fetchone():
        return None
    uid, lid = mail_target(c, msg)
    if not uid:
        return None
    subj = MAIL_PREFIX_RE.sub("", str(msg.get("Subject", "")).replace("\n", " ")).strip()
    text, files = mail_text(msg)
    lg = lang(c, uid)
    sender = str(msg.get("From", "")).strip()
    title = subj or (text.split("\n", 1)[0][:120] if text else tr("E-mail", lg=lg))
    content = (text + "\n\n" if text else "") + f"— {tr('E-mail from {0}', sender, lg=lg)}" if sender else text
    title, content, url = split_link(title, content)
    if lid:
        ts = iso(now_utc())
        srt = c.execute("SELECT COALESCE(MIN(sort),0)-1 FROM tasks WHERE list_id=? AND parent_id IS NULL", (lid,)).fetchone()[0]
        tid = c.execute("INSERT INTO tasks(list_id,title,content,sort,created_at,updated_at,tt_id,created_by,url) VALUES(?,?,?,?,?,?,?,?,?)",
                        (lid, title[:300], content, srt, ts, ts, "mail:" + mid, uid, url if valid_url(url) else None)).lastrowid
        log_act(c, tid, "created", uid=uid)
    else:
        tid = new_inbox_task(c, uid, title, content, "mail:" + mid, url)
    for name, mime, data in files[:20]:
        if 0 < len(data) <= MAX_FILE_MB * 1024 * 1024:
            try:
                save_attachment_bytes(c, tid, name, mime, data)
            except OSError:
                break
    bump(c)
    c.commit()
    return tid


def mail_poll_once():
    """One round: the unseen mails of the folder -> tasks; each one is marked \\Seen afterwards (also when it was for
    nobody: it is never looked at again)."""
    port = IMAP["port"] or (993 if IMAP["ssl"] else 143)
    M = imaplib.IMAP4_SSL(IMAP["host"], port, timeout=60) if IMAP["ssl"] else imaplib.IMAP4(IMAP["host"], port, timeout=60)
    n = 0
    try:
        M.login(IMAP["user"], IMAP["password"])
        M.select(IMAP["folder"])
        typ, data = M.uid("SEARCH", None, "UNSEEN")
        for u in (data[0] or b"").split()[:200]:
            typ, parts = M.uid("FETCH", u, "(RFC822)")
            raw = next((p[1] for p in parts if isinstance(p, tuple) and len(p) > 1), None)
            if raw:
                with GATE.bg():
                    c = connect()
                    try:
                        if mail_import(c, raw):
                            n += 1
                    finally:
                        c.close()
            M.uid("STORE", u, "+FLAGS", "(\\Seen)")
    finally:
        try:
            M.logout()
        except Exception:  # noqa: BLE001
            pass
    return n


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


def mail_send(to, subject, text, html_body=None):
    """Sends one mail with KALMIDO_SMTP_*; raises on failure."""
    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"] = SMTP["from"], to, subject
    m["Date"] = email.utils.formatdate(localtime=True)
    m["Message-ID"] = email.utils.make_msgid(domain=(SMTP["from"].rpartition("@")[2] or "kalmido.local"))
    m.set_content(text)
    if html_body:
        m.add_alternative(html_body, subtype="html")
    tls = SMTP["tls"]
    port = SMTP["port"] or (465 if tls == "ssl" else 587 if tls == "starttls" else 25)
    S_ = smtplib.SMTP_SSL(SMTP["host"], port, timeout=30) if tls == "ssl" else smtplib.SMTP(SMTP["host"], port, timeout=30)
    try:
        if tls == "starttls":
            S_.starttls()
        if SMTP["user"]:
            S_.login(SMTP["user"], SMTP["password"])
        S_.send_message(m)
    finally:
        try:
            S_.quit()
        except Exception:  # noqa: BLE001
            pass


def digest_mail_content(c, uid, today):
    """(subject, text, html) of a person's daily summary: due today / overdue, tomorrow, what waits for them, unread."""
    lg = lang(c, uid)
    rows = c.execute(f"""SELECT t.id, t.title, t.due, t.due_time, t.priority, l.name AS lname FROM tasks t JOIN lists l ON l.id=t.list_id
                         WHERE t.status=0 AND t.deleted_at IS NULL AND t.parent_id IS NULL AND t.due IS NOT NULL AND t.due<=? AND l.archived=0
                           AND ((l.owner_id=? AND (t.assignee_id IS NULL OR t.assignee_id=?)) OR (t.assignee_id=? AND t.list_id IN {vis_sql()}))
                         ORDER BY t.due, t.due_time IS NULL, t.due_time, t.priority DESC LIMIT 60""",
                     ((date.fromisoformat(today) + timedelta(days=1)).isoformat(), uid, uid, uid, uid, uid)).fetchall()
    tom = (date.fromisoformat(today) + timedelta(days=1)).isoformat()
    over = [r for r in rows if r["due"] < today]
    tod = [r for r in rows if r["due"] == today]
    tmr = [r for r in rows if r["due"] == tom]
    waits = c.execute("SELECT COUNT(*) FROM agent_jobs WHERE state='waiting' AND (user_id=? OR user_id IS NULL)", (uid,)).fetchone()[0] \
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='agent_jobs'").fetchone() else 0
    unread = news_unread(c, uid)
    chat = tchat_unread(c, uid)
    line = lambda r: f"- {r['title']}" + (f" ({r['due_time']})" if r["due_time"] else "") + f" · {r['lname']}"  # noqa: E731
    parts = []
    for head, xs in ((tr("Overdue", lg=lg), over), (tr("Today", lg=lg), tod), (tr("Tomorrow", lg=lg), tmr)):
        if xs:
            parts.append(f"{head} ({len(xs)})\n" + "\n".join(line(r) for r in xs[:25]))
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
    lg = lang(c, me())
    m = digest_mail_content(c, me(), local_now().date().isoformat()) or (f"{APP_NAME}: " + tr("Test", lg=lg), tr("E-mails from {0} are arriving.", APP_NAME, lg=lg), None)
    try:
        mail_send(u["email"].strip(), *m)
    except Exception as e:  # noqa: BLE001
        return err(tr("Sending failed: {0}", type(e).__name__), 502)
    return jsonify(ok=True, to=u["email"].strip())
