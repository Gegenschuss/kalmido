"""2.393.2 B (#3375): the mail thread of a task -- replies by e-mail become comments, a comment can go back to the reporter.

task_mail (core/migrations.d/3375.py) keeps the Message-IDs of a task: 'src' = the mail that made the task (a task made by the
server's mailbox; its sender = the reporter), 'in' = a reply taken in as a comment, 'out' = a mail Kalmido sent about it (an
assignment / mention mail about this one task, an answer to the reporter).

Taken in as a comment (integrations/mail.py mail_import, before a new task would be made): a mail whose In-Reply-To / References
names a stored Message-ID of a task, or whose recipient is the reply address of a task. The reply address is the server's
address with a plus token "r<task id>[u<account>]x<signature>": the signature is an HMAC with the server key over the task (and the
account on a person's address, review 4) AND the address the
mail went to, so the token is no bare task id and works only for mails from that address (a forwarded token from another sender
counts as none). The same checks as the import today: a reply by In-Reply-To alone counts only when the mail went to an address
the import takes (a personal / list token), a reply address only with a valid signature. Then only the reporter's address or a
person (no agent, not disabled) who sees the task and its comments by the account's e-mail address; a list with the lock takes
nothing. The comment is in the person's name only when it came through the signed reply address (a notification mail of theirs);
by In-Reply-To alone it carries the sender's address like the reporter's. 2.539.0 (#4381): in the person's name also only when the
receiving mail server confirmed the sender's domain (hub/hubmail.py hbm_from_verified, KALMIDO_MAIL_AUTHSERV_ID); else the
comment carries the address ("By e-mail from ...") without the account. Everything else goes on as today (a new task where the address leads), with the note "Reply to #N, sender not allowed".
The comment shows the sender ("By e-mail from ..."), the quoted part below the usual separator lines is cut off, files become files
of the comment. Sender addresses can be forged: the signed reply address and the membership check are the two locks; an outsider
who knows a Message-ID and forges a member's address is the case mail_from_me accepts today too.

Answer to the reporter (the comment field's switch, API "mail_reporter": true): only on a task with a reporter, by people (and
agents the task is shared with) who may change it, never in a list with the lock (400). Through the workspace mailbox's SMTP when the
workspace has one, else the server's (hub/mailbox.py _sender), Reply-To = the task's reply address for the reporter,
In-Reply-To / References = the task's Message-IDs, its own Message-ID stored as 'out'. Per person TMR_SEND_HOUR mails an hour."""
import email.utils
import hashlib
import hmac
import re

from ..core.config import APP_NAME, EMAIL_RE, MAX_FILE_MB
from ..core.db import bump, iso, iso_ms, now_utc
from ..core.i18n import lang, tr
from ..core.pg import insert_id
from ..core.access import task_visible
from ..core.pages import save_attachment_bytes
from ..accounts.login import auth_key
from ..admin.hosting import mail_budget
from ..api.common import hit_limit
from ..collab.comments import MAIL_REPLY, MENTION_RE, collab_user, task_say_refusal, user_names
from ..collab.liste2e import le2e_mode
from ..collab.liste2eguard import le2b_list_locked
from ..collab.news import news_add
from ..hub.hubmail import hbm_from_verified  # 2.539.0 (#4381): module level, hubmail comes earlier in the layer order
from ..hub.mailbox import _refs, _sender
from . import mail as M

TMR_TOKEN_RE = re.compile(r"\+r(\d{1,12})(?:u(\d{1,12}))?x([0-9a-f]{16})@", re.I)  # review 4: "u<account>" on a person's address
TMR_SEND_HOUR = 30
_MID_RE = re.compile(r"<[^<>\s]{1,290}>")
TMR_FILES = 20
# the first line of a quoted part: "On ... wrote:", "Am ... schrieb ...:", "Le ... a écrit :", "El ... escribió:", "Il ... ha scritto:",
# "Op ... schreef ...:", the signature separator "-- ", Outlook's "-----Original Message-----" / "-----Ursprüngliche Nachricht-----"
# and its header block "From: / Von: / De: / Da: / Van:" followed by a "Sent: / Gesendet: / Date:" line
_QUOTE = re.compile(r"^(?:On\s.+\swrote:\s*$|Am\s.+\sschrieb.*:\s*$|Le\s.+\sa\s+écrit\s*:\s*$|El\s.+\sescribió\s*:\s*$|Il\s.+\sha\s+scritto\s*:\s*$"
                    r"|Op\s.+\sschreef.*:\s*$|-- $|--$|-{3,}\s*(?:Original Message|Ursprüngliche Nachricht|Message d'origine|Mensaje original"
                    r"|Messaggio originale|Oorspronkelijk bericht)\s*-{3,}\s*$|_{20,}\s*$)", re.I)
_QUOTE_MAX = 300  # 2.393.2 F (#3375): review 5 - only short lines are matched (the patterns backtrack on long ones)
_OUTLOOK_FROM = re.compile(r"^\*?(?:From|Von|De|Da|Van)\s*:\*?\s", re.I)
_OUTLOOK_NEXT = re.compile(r"^\*?(?:Sent|Gesendet|Envoyé|Enviado|Inviato|Verzonden|Date|Datum)\s*:\*?\s", re.I)


def tmr_trim(text):
    """The new part of a reply: everything from the first quote / signature line on goes, as do the '>' lines at the end."""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    for i, ln in enumerate(lines):
        if i and len(ln) <= _QUOTE_MAX and (_QUOTE.match(ln) or (_OUTLOOK_FROM.match(ln) and i + 1 < len(lines) and _OUTLOOK_NEXT.match(lines[i + 1]))):
            lines = lines[:i]
            break
    while lines and (not lines[-1].strip() or lines[-1].lstrip().startswith(">")):
        lines.pop()
    return "\n".join(lines).strip()


def _addr(v):
    return email.utils.parseaddr(str(v or ""))[1].strip().lower()


def tmr_sig(c, tid, addr, uid=0):
    """2.393.2 F (#3375): review 4 - a person's address is signed with the account too (the reporter's: uid 0)."""
    what = f"task-mail-reply-u:{int(tid)}:{int(uid)}:" if uid else f"task-mail-reply:{int(tid)}:"
    return hmac.new(auth_key(c), (what + addr.strip().lower()).encode(), hashlib.sha256).hexdigest()[:16]


def tmr_reply_to(c, tid, addr, uid=0):
    """The reply address of task tid for the reporter at addr, or for account uid at addr ('' without a server mailbox)."""
    if not M.MAIL_IN_ON or not addr:
        return ""
    return M.mail_addr(f"r{int(tid)}" + (f"u{int(uid)}" if uid else "") + f"x{tmr_sig(c, tid, addr, uid)}")


def tmr_keep(c, tid, msg_id, sender, kind):
    """Stores one Message-ID of task tid (caller commits). 2.393.2 F (#3375): review 6 - only the form hub/mailbox.py _refs reads
    ("<...>" without spaces): such an id is sent again as In-Reply-To / References."""
    mid = str(msg_id or "").strip()
    if not _MID_RE.fullmatch(mid):
        if kind != "src":
            return
        mid = ""  # the reporter stays, without its id
    c.execute("INSERT INTO task_mail(task_id,msg_id,sender,kind,created_at) VALUES(?,?,?,?,?)",  # review 3: an address only for the
              (tid, mid, (sender or "")[:300] if kind == "src" else "", kind, iso(now_utc())))  # reporter (none outlives an account)


def tmr_reporter(c, tid):
    """The reporter's address of task tid (the sender of the mail that made it) or ''. 2.393.2 F (#3375): review 2 - only the
    'src' row: a reply ('in') never makes its sender the reporter."""
    r = c.execute("SELECT sender FROM task_mail WHERE task_id=? AND kind='src' ORDER BY id LIMIT 1", (tid,)).fetchone()
    return _addr(r[0]) if r else ""


def tmr_ids(c, tid):
    return [r[0] for r in c.execute("SELECT msg_id FROM task_mail WHERE task_id=? AND substr(msg_id, 1, 1) = '<' ORDER BY id DESC LIMIT 20", (tid,))][::-1]


def _hdrs(msg):
    return " ".join(str(msg.get_all(h, [])) for h in ("To", "Cc", "Delivered-To", "X-Original-To", "Envelope-To"))


def tmr_find(c, msg, sender):
    """(task id or None, signed, account): the task a mail answers -- a valid reply address of the sender first (account = the
    one the address was made for, 0 = the reporter's), else a stored Message-ID in In-Reply-To / References (the newest)."""
    for tid, tu, sig in TMR_TOKEN_RE.findall(_hdrs(msg)):
        if sender and hmac.compare_digest(sig.lower(), tmr_sig(c, int(tid), sender, int(tu or 0))):
            return int(tid), True, int(tu or 0)
    refs = _refs(msg)
    if refs:
        r = c.execute("SELECT task_id FROM task_mail WHERE msg_id IN (" + ",".join("?" * len(refs)) + ") ORDER BY id DESC LIMIT 1", refs).fetchone()
        if r:
            return r[0], False, 0
    return None, False, 0


def tmr_who(c, tid, sender, tu=0):
    """(allowed, user id or None) for a reply to task tid from sender: the reporter (no account needed) or a person who sees
    the task with its comments by the account's address. A list with the lock never. 2.393.2 F (#3375): review 4 - in a
    person's name only as account tu of the signed address (still that address, still sees the task), never found by address."""
    t = c.execute("SELECT id, list_id, deleted_at FROM tasks WHERE id=?", (tid,)).fetchone()
    if not t or t["deleted_at"] or not sender or (t["list_id"] and le2b_list_locked(c, t["list_id"])):
        return False, None
    if tu:
        r = c.execute("SELECT id FROM users WHERE id=? AND lower(email)=? AND disabled=0 AND COALESCE(kind,'user')<>'agent'", (tu, sender)).fetchone()
        if r and task_visible(c, tid, tu, full=True) and not task_say_refusal(c, tid, tu):  # 2.607.0 (#4549): a guest /
            return True, tu  # read-only person of the list's organisation comments by mail as little as in the app
    else:
        for r in c.execute("SELECT id FROM users WHERE lower(email)=? AND disabled=0 AND COALESCE(kind,'user')<>'agent' ORDER BY id", (sender,)).fetchall():
            if task_visible(c, tid, r[0], full=True) and not task_say_refusal(c, tid, r[0]):  # 2.607.0 (#4549)
                return True, None
    return sender == tmr_reporter(c, tid), None


def tmr_take(c, msg, mid, uid, how_to=None):
    """mail_import's step before a new task (mail.py MAIL_TASK_HOOK): ('comment', task id) when the mail became a comment,
    ('note', text) for the new task when it answers a task but may not comment, (None, '') otherwise. uid = the person the
    import would give the mail to (None = no address the import takes), how_to = how it found them (mail_target: "token" / "from")."""
    sender = _addr(msg.get("From"))
    tid, signed, tu = tmr_find(c, msg, sender)
    if not tid:
        return None, ""
    ok, who = tmr_who(c, tid, sender, tu)
    if who:  # 2.539.0 (#4381, audit #2483 M5): in a person's name only when the receiving server confirmed the sender's domain
        # (KALMIDO_MAIL_AUTHSERV_ID); else "By e-mail from <address>", no account
        if not hbm_from_verified(msg, sender):
            who = None
    # 2.393.2 F (#3375): review 1 - by In-Reply-To alone only when the account of the address the mail went to sees the task (the
    # reporter answers to the address their mail went to): an address of another account never leads into a task it does not see.
    # #4071: only a token in the address counts; "from" (mail_from_me) comes from the sender's address, which anyone can forge
    if ok and (signed or (uid and how_to == "token" and task_visible(c, tid, uid, full=True))):  # in a person's name only through the signed address
        return "comment", tmr_comment(c, msg, mid, tid, sender, who)
    lg = lang(c, uid) if uid else "en"
    return "note", tr("Reply to #{0}, sender not allowed", tid, lg=lg)


def tmr_comment(c, msg, mid, tid, sender, uid):
    """The reply as a comment of task tid (its files as files of the comment); the people of the task hear it (News); caller commits.
    Returns the task id, 2.393.2 F (#3375): review 8 - mail.MailKept(tid) when a file could not be stored or was too large (the
    mail stays in the mailbox, like the import of a new task)."""
    text, files = M.mail_text(msg)
    text = tmr_trim(text)
    t = c.execute("SELECT t.*, l.owner_id AS l_owner FROM tasks t LEFT JOIN lists l ON l.id=t.list_id WHERE t.id=?", (tid,)).fetchone()
    lg = lang(c, t["l_owner"] or t["created_by"]) if (t["l_owner"] or t["created_by"]) else "en"
    name = email.utils.parseaddr(str(msg.get("From", "")))[0].strip()[:120]
    body = (text + "\n\n" if text else "") + "— " + tr("By e-mail from {0}", sender, lg=lg)
    cid = insert_id(c, "INSERT INTO comments(task_id,user_id,body,mentions,created_at,ext_name) VALUES(?,?,?,?,?,?)",
                    (tid, uid, body[:10000], "", iso_ms(now_utc()), None if uid else (name or sender)[:120]))
    top = c.execute("SELECT COALESCE(MAX(id),0) FROM attachments WHERE task_id=?", (tid,)).fetchone()[0]
    whole = len(files) <= TMR_FILES
    for fname, mime, data in files[:TMR_FILES]:
        if 0 < len(data) <= MAX_FILE_MB * 1024 * 1024:
            try:
                save_attachment_bytes(c, tid, fname, mime, data)
            except OSError:
                whole = False
                break
        elif data:
            whole = False
    c.execute("UPDATE attachments SET comment_id=? WHERE task_id=? AND id>?", (cid, tid, top))
    tmr_keep(c, tid, mid, sender, "in")
    rcpt = {t["l_owner"], t["created_by"], t["assignee_id"]} | {r[0] for r in c.execute(
        "SELECT DISTINCT user_id FROM comments WHERE task_id=? AND deleted_at IS NULL AND id<?", (tid, cid))}
    for u in sorted(rcpt - {None, uid}):
        s = collab_user(c, u, t["list_id"])
        if s and task_visible(c, tid, u, full=True):
            news_add(c, u, "comment", task_id=tid, comment_id=cid, actor=uid or 0, s=s,
                     data={"excerpt": text[:300], **({} if uid else {"ext_name": name or sender})})
    bump(c)
    return tid if whole else M.MailKept(tid)


def tmr_plain(c, text):
    """2.393.2 F (#3375): review 7 - a comment as mail text: tokens -> @name, paragraphs and lines kept (comment_plain is one line, for pushes)."""
    names = user_names(c, [int(x) for x in MENTION_RE.findall(text or "")])
    text = MENTION_RE.sub(lambda m: "@" + names.get(int(m.group(1)), "?"), (text or "").replace("\r\n", "\n"))
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


# ---- the comment field's switch "also by e-mail to the reporter"
def tmr_info(c, tid, uid):
    """The timeline's mail_reporter: {address, may} when task tid has a reporter, else None."""
    rep = tmr_reporter(c, tid)
    if not rep or not M.MAIL_OUT_ON:
        return None
    t = c.execute("SELECT list_id FROM tasks WHERE id=?", (tid,)).fetchone()
    lock = bool(t and t["list_id"] and le2e_mode(c, t["list_id"]))
    return {"address": rep, "may": not lock and task_visible(c, tid, uid, write=True), "e2e": lock}


def tmr_check(c, tid, uid, v):
    """The mail_reporter flag of a new comment: False when not asked for; raises ValueError(message) when it cannot go."""
    if v in (None, False, 0, "0", "false", ""):
        return False
    if v not in (True, 1, "1", "true", "on"):
        raise ValueError(tr("mail_reporter: true or false"))
    t = c.execute("SELECT list_id FROM tasks WHERE id=?", (tid,)).fetchone()
    if t and t["list_id"] and (le2e_mode(c, t["list_id"]) or le2b_list_locked(c, t["list_id"])):
        raise ValueError(tr("No e-mail from a list with end-to-end encryption"))
    if not tmr_reporter(c, tid):
        raise ValueError(tr("This task has no reporter by e-mail"))
    if not task_visible(c, tid, uid, write=True):
        raise ValueError(tr("Only people who may change the task answer the reporter"))
    if not M.MAIL_OUT_ON and not _sender(c, None, uid)[3]:
        raise ValueError(tr("Sending e-mails is not set up on this server"))
    return True


def tmr_send(c, tid, uid, cid):
    """Sends comment cid of task tid to the reporter (after the comment's commit). Returns '' or an error code."""
    rep = tmr_reporter(c, tid)
    t = c.execute("SELECT t.title, l.org_id FROM tasks t LEFT JOIN lists l ON l.id=t.list_id WHERE t.id=?", (tid,)).fetchone()
    k = c.execute("SELECT body FROM comments WHERE id=?", (cid,)).fetchone()
    if not rep or not t or not k or not EMAIL_RE.fullmatch(rep):
        return "no_reporter"
    smtp, name, _own, via = _sender(c, t["org_id"] or None, uid)
    if not via:
        return "no_smtp"
    if hit_limit(f"tmrsend:{uid}", TMR_SEND_HOUR, 3600):
        return "limit"
    if via == "server":
        if not mail_budget(c, uid, rep):
            c.commit()
            return "limit"
    title = M.MAIL_PREFIX_RE.sub("", re.sub(r"\s+", " ", t["title"] or "")).strip() or APP_NAME
    text = tmr_plain(c, k["body"])
    m = M.mail_message(rep, "Re: " + title[:250], text, from_name=name or APP_NAME, reply_to=tmr_reply_to(c, tid, rep) or None, smtp=smtp)
    ids = tmr_ids(c, tid)
    if ids:
        m["In-Reply-To"] = ids[-1]
        m["References"] = " ".join(ids[-10:])
    tmr_keep(c, tid, m["Message-ID"], rep, "out")
    c.commit()
    try:
        M.mail_deliver(m, smtp)
    except Exception as e:  # noqa: BLE001
        print("task mail: answer to the reporter failed:", type(e).__name__, flush=True)  # no addresses in the log
        return "failed"
    return ""


MAIL_REPLY.update(info=tmr_info, check=tmr_check, send=tmr_send)
M.MAIL_TASK_HOOK.update(take=tmr_take, keep=tmr_keep, reply_to=tmr_reply_to)
