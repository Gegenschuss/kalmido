"""2.63.0 (#1513): customer reports and the customer portal (module "portal").

A form with "status link" on (forms.portal, team/forms.py) turns a sent report into a ticket: the task (type from forms.ttype,
e.g. 'bug') plus one portal_tickets row. The reporter gets a status link /p/<token> (192 random bits, stored sealed so it can
be sent again, looked up by its SHA-256) on the thank-you page and by mail. The status page shows only that ticket: title,
state, the public answers and the reporter's own comments (comments.portal = 1); internal comments (portal = 0) never leave
the app. From there (or the form) the reporter can ask for a sign-in link by mail and then sees all their tickets of the same
space (org_id, or owner_id for a list without organisation) -- never another space's, never another person's.

The space and the e-mail are the whole identity of a reporter: there is no account. The e-mail is stored sealed (server key)
and as a keyed hash (pt_email_hash) for the sign-in lookup, so the table does not hold readable addresses.

Shared helpers (leader, 2.63.0): part A (the form) calls pt_create; part B (status page, portal, answers, mails, office
client) fills the rest of this module. Keep the signatures; a changed contract goes into iface.txt."""
import hashlib
import hmac
import html
import os
import re
import secrets
import threading
import time
from datetime import date, timedelta

from ..core.config import app, PUBLIC_URL
from ..core.db import db, iso, now_utc
from ..core.i18n import N_
from ..core.pg import insert_id
from ..accounts.session import _token_hash
from ..accounts.login import auth_key, seal, unseal

PT_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{20,64}")
PT_EMAIL_MAX = 200


def pt_email_norm(email):
    """The form of an address that identifies a reporter ('' when it is no address)."""
    e = (email or "").strip().lower()[:PT_EMAIL_MAX]
    return e if re.fullmatch(r"[^@\s<>,;\"()\[\]\\]+@[^@\s<>,;\"'()\[\]\\]+\.[^@\s<>,;\"'()\[\]\\]+", e) else ""  # review: one plain address


def pt_email_hash(c, email):
    """Keyed hash of an address (server key): the portal finds a reporter's tickets without readable addresses."""
    e = pt_email_norm(email)
    return hmac.new(auth_key(c), b"kalmido-portal-email|" + e.encode(), hashlib.sha256).hexdigest() if e else ""


def pt_status_url(token):
    return f"{PUBLIC_URL}/p/{token}"


def pt_create(c, task_id, list_row, form_id=None, name="", email="", client_id=None):
    """A reported task becomes a ticket: one portal_tickets row in the list's space. list_row needs id, org_id, owner_id.
    Returns (ticket id, token); the token is only in the status link. The caller commits."""
    tok = secrets.token_urlsafe(24)
    e = pt_email_norm(email)
    if client_id is None:  # 2.63.0 B (#1513): the list's client, else the organisation's client with this address
        client_id = pt_client_for(c, list_row, e)
    ts = iso(now_utc())
    tid = insert_id(c, """INSERT INTO portal_tickets(task_id,list_id,org_id,owner_id,form_id,client_id,name,email,email_hash,token,token_hash,
                          notify,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (task_id, list_row["id"], list_row["org_id"], None if list_row["org_id"] else list_row["owner_id"], form_id, client_id,
                     (name or "")[:120], seal(c, "portal-email", e) if e else "", pt_email_hash(c, e) if e else "",
                     seal(c, "portal-token", tok), _token_hash(tok), 1 if e else 0, ts))
    return tid, tok


def pt_email(c, row):
    """The reporter's address of a portal_tickets row ('' when none was given)."""
    return unseal(c, "portal-email", row["email"]) if row["email"] else ""


def pt_token(c, row):
    """The status-link token of a portal_tickets row (to send the link again)."""
    return unseal(c, "portal-token", row["token"])


# ---------------------------------------------------------------- 2.63.0 B (#1513): status page, portal, answers, mails
# Every page here is server-rendered HTML without scripts (pub_html: strict CSP, noindex, no referrer, no caching). A token
# is resolved as "system" (one row by its hash) and the page then reads as nobody inside exactly the ticket's space
# (acx_anon_bind), like the public list links. Unknown, guessed, deleted, moved (into another space) and switched-off
# tickets all get the same 404 page; unknown tokens count towards a per-address block. The reporter sees the title, the
# state, the text they sent (only while the team has not edited the description), the public answers (comments.portal = 1;
# the team's display name, an agent's answer as "Team") and their own comments -- never internal comments, notes,
# assignees, other tasks or files. Writing (answer, sign-in request, sign-out) needs a form check value bound to the
# ticket / cookie, refuses cross-site posts and is rate-limited per address and per ticket / space.
PT_VIEW_RATE = 60          # status / portal pages per client address and minute
PT_BAD_LIMIT = 30          # unknown tokens per address within FAIL_WINDOW
PT_CMT_RATE, PT_CMT_HOUR, PT_CMT_MAX = 10, 30, 4000   # answers per address and minute / per ticket and hour / characters
PT_LOGIN_IP, PT_LOGIN_ADDR, PT_LOGIN_SPACE = 5, 3, 200  # sign-in requests per address / per e-mail / sign-in mails per space (window below)
PT_LOGIN_WIN = 3600
try:  # 2.138.3 C (#2380): the space's sign-in mails per window can be set (tests use a small one)
    PT_LOGIN_SPACE = max(1, int(os.environ.get("KALMIDO_PORTAL_LOGIN_SPACE") or PT_LOGIN_SPACE))
except ValueError:
    pass
PT_LOGIN_TTL = 30 * 60     # s: a sign-in link is valid this long, once
PT_COOKIE_DAYS = 7
PT_COOKIE = "kalmido_portal"
PT_MAIL_GAP = 600          # s: at most one mail per ticket in this time (answers in between go out together)
PT_PAD = 0.35              # s: the sign-in request answers no faster than this (found / unknown look alike)
PT_TYPES = {"bug": N_("Bug report"), "feature": N_("Feature request")}
_PT_EDITS = ("content", "md_subtasks", "tidy")  # history kinds after which the description is no longer the reporter's text


def _pt_rt():
    """The public-page helpers of lists/public.py (imported late: that module imports a lot)."""
    from ..lists import public as P
    return P


def _pt_space_sql(p="p.", l="l."):
    """The ticket's list is still in the ticket's space (a task moved into another space leaves its ticket behind) and has no
    lock: 2.64.1 (#1817) a list encrypted in the browser has no customer portal (like forms and public links; its texts and
    answers are ciphertexts the server cannot show or mail, a customer's plain answer must not land in it)."""
    return f"(({l}org_id={p}org_id OR ({p}org_id IS NULL AND {l}org_id IS NULL AND {l}owner_id={p}owner_id)) AND {l}e2e IS NULL)"


def pt_find(c, token):
    """The live ticket of a status-link token (+ the task's fields, the list's owner) or None. Binds the request to the
    ticket's space as nobody."""
    from flask import g
    from ..core.access import acx_anon_bind
    from ..core.pg import system_ctx
    if not PT_TOKEN_RE.fullmatch(token or ""):
        return None
    with system_ctx(c):  # resolve the token (one row) across organisations ...
        r = c.execute(f"""SELECT p.*, t.title, t.content, t.status, t.ttype, t.assignee_id, t.assignee_group_id, t.list_id AS t_list,
                          t.completed_at, l.owner_id AS l_owner, l.org_id AS l_org FROM portal_tickets p JOIN tasks t ON t.id=p.task_id
                          JOIN lists l ON l.id=t.list_id JOIN users u ON u.id=l.owner_id
                          WHERE p.token_hash=? AND t.deleted_at IS NULL AND u.disabled=0 AND {_pt_space_sql()}""",
                      (_token_hash(token),)).fetchone()
    if not r:
        return None
    acx_anon_bind(c, r["org_id"])  # ... then the page reads as nobody, inside exactly the ticket's space
    g.user, g.auth_via = _pt_rt().PUB_ACTOR, "public"
    return r


def pt_open(c, token):
    """Common checks of every /p/ request -> (ticket, None) or (None, response)."""
    from ..accounts.session import _accept_lang, _rate_blocked, _rate_fail, rate_ip
    from ..notify.alerts import aa_count
    P = _pt_rt()
    if not P.public_links_on(c):
        return None, P.pub_gone()
    bad = [("ptbad:" + rate_ip(), PT_BAD_LIMIT)]  # 2.126.0 C (#1979 I2): limited only when the link is not valid
    p = pt_find(c, token)
    if not p:
        if _rate_blocked(bad):
            return None, P.pub_limited(_accept_lang())
        _rate_fail(bad)
        aa_count("security", "portal", rate_ip())
        return None, P.pub_gone()
    return p, None


def pt_lang(c, p):
    from flask import request
    from ..core.i18n import lang, LANGS
    for part in (request.headers.get("Accept-Language") or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in LANGS:
            return code
    return lang(c, p["l_owner"] if "l_owner" in p.keys() else p["owner_id"])


def pt_state(c, p):
    """'done' | 'progress' (someone took it or a subtask is done) | 'open'."""
    if p["status"] != 0:
        return "done"
    if p["assignee_id"] or p["assignee_group_id"] or c.execute(
            "SELECT 1 FROM tasks WHERE parent_id=? AND status!=0 AND deleted_at IS NULL LIMIT 1", (p["task_id"],)).fetchone():
        return "progress"
    return "open"


PT_STATE_TXT = {"open": N_("Received"), "progress": N_("In progress"), "done": N_("Done")}


def pt_original(c, p):
    """The text the reporter sent: the description without the form's signature line ("— Sent with the form ..."), only
    while nobody edited the description (no history entry, the signature still last; else '' -- the page then shows the
    title only; nothing extra is stored)."""
    txt = p["content"] or ""
    if not txt or c.execute(f"SELECT 1 FROM activity WHERE task_id=? AND kind IN ({','.join('?' * len(_PT_EDITS))}) LIMIT 1",
                            (p["task_id"], *_PT_EDITS)).fetchone():
        return ""
    head, sep, tail = txt.rpartition("\n\n— ")
    # the form's signature must still close the text (else the team rewrote it: then the title only)
    return head.strip() if sep and "\n" not in tail.strip() else ""


def pt_plain(text):
    """A comment as plain text for customers: mention tokens of the app (team members' ids) removed."""
    return re.sub(r"<@\d+>", "", text or "").strip()


def pt_answers(c, task_id):
    """The comments the customer sees: public answers + their own, oldest first, with the shown author name."""
    out = []
    rows = c.execute("""SELECT k.id, k.user_id, k.body, k.created_at, k.ext_name, u.display_name, u.kind FROM comments k
                        LEFT JOIN users u ON u.id=k.user_id WHERE k.task_id=? AND k.portal=1 AND k.deleted_at IS NULL ORDER BY k.id""",
                     (task_id,)).fetchall()
    for r in rows:
        mine = r["user_id"] is None
        who = (r["ext_name"] or "") if mine else ("" if (r["kind"] or "user") == "agent" else (r["display_name"] or "").strip())
        out.append({"id": r["id"], "customer": mine, "who": who, "body": pt_plain(r["body"]), "at": r["created_at"]})
    return out


def pt_day(s, lg):
    from ..core.db import parse_iso
    from ..core.i18n import short_day
    try:
        return short_day(parse_iso(s).date() if "T" in s else date.fromisoformat(s[:10]), lg, year=True)
    except (TypeError, ValueError):
        return ""


def pt_key(c, p, what="c"):
    """The form check value of a ticket's forms (answer / sign-in), bound to the ticket and its token."""
    return hmac.new(auth_key(c), f"pt{what}:{p['id']}:{p['token_hash']}".encode(), hashlib.sha256).hexdigest()


def _pt_paras(text):
    e = html.escape
    return "".join(f"<p>{e(x).replace(chr(10), '<br>')}</p>" for x in re.split(r"\n\s*\n", text) if x.strip())


def pt_render(c, p, token, lg, note=""):
    from flask import request
    from ..core.config import APP_NAME
    from ..core.i18n import tr
    e = html.escape
    t = lambda s, *a: tr(s, *a, lg=lg)  # noqa: E731
    st = pt_state(c, p)
    orig = pt_original(c, p)
    ans = pt_answers(c, p["task_id"])
    kind = PT_TYPES.get(p["ttype"] or "")
    meta = " · ".join(x for x in (t(kind) if kind else "", t(N_("Reported on {0}"), pt_day(p["created_at"], lg))) if x)
    head = (f'<header><p class="sub">{e(meta)}</p><h1>{e(p["title"])}</h1>'
            f'<p class="ptst ptst-{st}">{e(t(PT_STATE_TXT[st]))}</p></header>')
    msgs = {"sent": t(N_("Thank you, your answer has arrived.")), "mail": t(N_("If there are reports for this address, a mail with a sign-in link is on its way.")),
            "on": t(N_("Mails about this report are on again."))}
    flash = msgs.get(request.args.get("m") or "", "") or note
    out = head + (f'<p class="ok" role="status">{e(flash)}</p>' if flash else "")
    if orig:
        out += f'<section class="ptd"><h2>{e(t(N_("Your report")))}</h2>{_pt_paras(orig)}</section>'
    items = "".join(
        f'<li class="{"me" if a["customer"] else "tm"}"><div class="ptw"><b>{e(a["who"] or (t(N_("You")) if a["customer"] else t(N_("Team"))))}</b>'
        f'<span>{e(pt_day(a["at"], lg))}</span></div>{_pt_paras(a["body"])}</li>' for a in ans)
    out += (f'<section class="ptc"><h2>{e(t(N_("Answers")))}</h2>'
            + (f'<ol class="ptlist">{items}</ol>' if items else f'<p class="empty">{e(t(N_("No answer yet. You will see it here.")))}</p>') + '</section>')
    out += (f'<section class="fb" id="answer"><h2>{e(t(N_("Your answer")))}</h2><form method="post" action="/p/{e(token)}/comment" class="fform">'
            f'<input type="hidden" name="f" value="{pt_key(c, p)}"><label for="pt-text">{e(t(N_("Message to the team")))}</label>'
            f'<textarea id="pt-text" name="text" rows="4" maxlength="{PT_CMT_MAX}" required></textarea>'
            f'<button type="submit">{e(t(N_("Send")))}</button></form></section>')
    out += (f'<section class="fb ptlog" id="all"><h2>{e(t(N_("All my reports")))}</h2><p class="sub">{e(t(N_("We send a sign-in link to your e-mail address. No account needed.")))}</p>'
            f'<form method="post" action="/p/{e(token)}/login" class="fform"><input type="hidden" name="f" value="{pt_key(c, p, "l")}">'
            f'<label for="pt-mail">{e(t(N_("Your e-mail")))}</label><input id="pt-mail" name="email" type="email" autocomplete="email" maxlength="{PT_EMAIL_MAX}" required>'
            f'<button type="submit">{e(t(N_("Send the link")))}</button></form></section>')
    if p["notify"] and p["email"]:
        out += f'<p class="sub ptstop"><a href="/p/{e(token)}/stop">{e(t(N_("No more mails about this report")))}</a></p>'
    return _pt_rt().pub_html(f'{p["title"]} · {APP_NAME}', out, lg)


@app.get("/p/<token>")
def pt_page(token):
    from ..accounts.session import _accept_lang, rate_ip
    from ..api.v1 import hit_limit
    c = db()
    if hit_limit("ptv:" + rate_ip(), PT_VIEW_RATE):
        return _pt_rt().pub_limited(_accept_lang())
    p, bad = pt_open(c, token)
    if bad:
        return bad
    lg = pt_lang(c, p)
    # 2.81.0 (#1866): a page view writes only when the last one is older than 5 minutes (or the language changed)
    c.execute("UPDATE portal_tickets SET last_seen_at=?, lang=? WHERE id=? AND (last_seen_at IS NULL OR last_seen_at<? OR lang<>?)",
              (iso(now_utc()), lg, p["id"], iso(now_utc() - timedelta(minutes=5)), lg))
    if p["client_id"] is None:
        cl = pt_client_for(c, {"id": p["list_id"], "org_id": p["org_id"]}, pt_email(c, p))
        if cl:
            c.execute("UPDATE portal_tickets SET client_id=? WHERE id=?", (cl, p["id"]))
    c.commit()
    return pt_render(c, p, token, lg)


def _pt_denied(lg):
    from ..core.i18n import tr
    return _pt_rt().pub_html(tr("Not allowed", lg=lg), f'<div class="msg"><h1>{html.escape(tr("Not allowed", lg=lg))}</h1></div>', lg, 403)


def _pt_post_ok(c, p, what):
    from flask import request
    return request.headers.get("Sec-Fetch-Site", "") != "cross-site" and hmac.compare_digest(request.form.get("f") or "", pt_key(c, p, what))


@app.post("/p/<token>/comment")
def pt_comment(token):
    """The reporter answers: a comment with portal = 1 and their name (no account), News + push to the team like a comment
    on their task, a comment event to the agents that follow the task."""
    from flask import redirect, request
    from ..core.db import bump, iso_ms
    from ..core.i18n import tr
    from ..accounts.session import rate_ip
    from ..api.v1 import hit_budget, hit_limit
    from ..agents.core import agent_comment_events
    c = db()
    p, bad = pt_open(c, token)
    if bad:
        return bad
    lg = pt_lang(c, p)
    if not _pt_post_ok(c, p, "c"):
        return _pt_denied(lg)
    if hit_limit("ptc:" + rate_ip(), PT_CMT_RATE) or hit_budget(f"ptch:{p['id']}", PT_CMT_HOUR, rate_ip()):  # 2.126.0 C (#1979 I1)
        return _pt_rt().pub_limited(lg)
    text = _pt_rt().cv_fb_clean(request.form.get("text"), PT_CMT_MAX)
    if not text:
        return pt_render(c, p, token, lg, tr("Please write a message.", lg=lg))
    name = (p["name"] or "").strip() or tr("Customer", lg=lg)
    cid = insert_id(c, "INSERT INTO comments(task_id,user_id,body,mentions,created_at,ext_name,portal) VALUES(?,?,?,?,?,?,1)",
                    (p["task_id"], None, text, "", iso_ms(now_utc()), name))
    t = c.execute("SELECT t.*, l.owner_id AS l_owner FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.id=?", (p["task_id"],)).fetchone()
    pt_team_news(c, t, cid, text, name)
    agent_comment_events(c, t, cid, [], [])
    bump(c)
    c.commit()
    print("portal answer on task", p["task_id"], flush=True)
    return _pt_rt().pub_headers(redirect(f"/p/{token}?m=sent#answer", 303))


def pt_team_news(c, t, cid, text, name):
    """News + push for the people of task t (owner, creator, assignee, "urgent" bell) like a customer's comment through a
    public link (lists/public.py cv_fb_post); the caller commits."""
    from flask import g
    from ..core.access import task_visible
    from ..core.i18n import tr
    from ..collab.comments import collab_user, lang_of
    from ..collab.news import KIND_ROW, news_add, notif_ok
    from ..notify.push import push_prio, push_reachable
    from ..notify.taskbell import tbl_level, tbl_sent, tbl_urgent_users, TBL_PRIO
    from ..agents.core import agent_ids
    rcpt = ({t["l_owner"], t["created_by"], t["assignee_id"]} | tbl_urgent_users(c, t["id"])) - {None} - agent_ids(c)
    for uid in sorted(rcpt):
        s = collab_user(c, uid, t["list_id"])
        if not s or not task_visible(c, t["id"], uid, full=True):
            continue
        news_add(c, uid, "comment", task_id=t["id"], comment_id=cid, actor=0, s=s, data={"excerpt": text[:300], "ext_name": name, "portal": True})
        lv = tbl_level(c, uid, t["id"], s)
        if lv == "urgent" and tbl_sent(uid, t["id"]):
            continue
        if lv != "mute" and (lv == "urgent" or notif_ok(c, uid, s, KIND_ROW["comment"], "push", t["list_id"])) and push_reachable(c, uid, s):
            g.pushes.append((uid, tr("{0} (customer, via the link)", name, lg=lang_of(s)) + ": " + t["title"], text[:200],
                             f"{PUBLIC_URL}/#t/{t['id']}", TBL_PRIO if lv == "urgent" else push_prio(s)))


# ---- mails off / on again (every mail has the off link; it opens a page with one button -- review: mail scanners and link
# previews open every link of a mail, a plain GET must not turn the mails off -- and the page offers the way back)
@app.get("/p/<token>/stop")
def pt_stop_ask(token):
    from ..core.i18n import tr
    c = db()
    p, bad = pt_open(c, token)
    if bad:
        return bad
    lg = pt_lang(c, p)
    e = html.escape
    return _pt_rt().pub_html(tr("Turn mails off", lg=lg), f'<div class="msg"><h1>{e(tr("Turn mails off", lg=lg))}</h1>'
                             f'<p>{e(tr("No more mails about “{0}”? The status page stays available.", p["title"], lg=lg))}</p>'
                             f'<form method="post" action="/p/{e(token)}/stop" class="fform"><input type="hidden" name="f" value="{pt_key(c, p, "s")}">'
                             f'<button type="submit">{e(tr("Turn mails off", lg=lg))}</button></form>'
                             f'<a class="btn" href="/p/{e(token)}">{e(tr("To the status page", lg=lg))}</a></div>', lg)


@app.post("/p/<token>/stop")
def pt_stop(token):
    from ..core.i18n import tr
    c = db()
    p, bad = pt_open(c, token)
    if bad:
        return bad
    lg = pt_lang(c, p)
    if not _pt_post_ok(c, p, "s"):
        return _pt_denied(lg)
    c.execute("UPDATE portal_tickets SET notify=0 WHERE id=?", (p["id"],))
    c.commit()
    e = html.escape
    return _pt_rt().pub_html(tr("Mails turned off", lg=lg), f'<div class="msg"><h1>{e(tr("Mails turned off", lg=lg))}</h1>'
                             f'<p>{e(tr("You get no more mails about “{0}”. The status page stays available.", p["title"], lg=lg))}</p>'
                             f'<form method="post" action="/p/{e(token)}/notify" class="fform"><input type="hidden" name="f" value="{pt_key(c, p, "n")}">'
                             f'<button type="submit">{e(tr("Turn mails on again", lg=lg))}</button></form>'
                             f'<a class="btn" href="/p/{e(token)}">{e(tr("To the status page", lg=lg))}</a></div>', lg)


@app.post("/p/<token>/notify")
def pt_notify_on(token):
    from flask import redirect
    c = db()
    p, bad = pt_open(c, token)
    if bad:
        return bad
    if not _pt_post_ok(c, p, "n"):
        return _pt_denied(pt_lang(c, p))
    if p["email"]:
        c.execute("UPDATE portal_tickets SET notify=1 WHERE id=?", (p["id"],))
        c.commit()
    return _pt_rt().pub_headers(redirect(f"/p/{token}?m=on", 303))


# ---- the portal: a sign-in link by mail (one-time, PT_LOGIN_TTL), then a cookie for /portal (signed, PT_COOKIE_DAYS days)
# that lists every ticket of the same address in the same space. The request always gets the same answer.
def _pt_mail_bg(to, subject, text, html_body):
    from ..core.config import APP_NAME
    from ..integrations.mail import mail_send
    try:
        mail_send(to, subject, text, html_body, from_name=APP_NAME)
    except Exception as ex:  # noqa: BLE001  (nobody waits for this; the reporter can ask again)
        print("portal mail failed:", type(ex).__name__, flush=True)


def _pt_mail_html(lines, url, button, foot=""):
    e = html.escape
    return ('<div style="font-family:system-ui,sans-serif;max-width:34rem;line-height:1.5">'
            + "".join(f"<p>{e(x).replace(chr(10), '<br>')}</p>" for x in lines if x)
            + f'<p><a href="{e(url)}" style="display:inline-block;background:#6d4ad8;color:#fff;padding:.6rem 1rem;border-radius:.5rem;'
              f'text-decoration:none">{e(button)}</a></p>' + (f'<p style="color:#777;font-size:.85rem">{foot}</p>' if foot else "") + "</div>")


@app.post("/p/<token>/login")
def pt_limit_note(c, org_id, owner_id):
    """2.138.3 C (#2380): the space's budget of sign-in mails (ptls) is used up: a News item for its admins (an organisation)
    or its owner (the private space), at most once per window and process; no push, no mail. Caller commits."""
    import json
    from ..api.v1 import hit_limit
    from ..core.db import iso_ms
    from ..core.pg import system_ctx
    if hit_limit(f"ptlsn:{org_id or ''}:{owner_id or ''}", 1, PT_LOGIN_WIN):
        return 0
    with system_ctx(c):  # who administers the space (structure); the notice names no customer
        if org_id:
            ids = [r[0] for r in c.execute("SELECT m.user_id FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? "
                                           "AND m.role='admin' AND u.kind!='agent' AND u.disabled=0 ORDER BY m.user_id", (int(org_id),))]
            on = (c.execute("SELECT name FROM orgs WHERE id=?", (int(org_id),)).fetchone() or [""])[0]
        else:
            ids, on = [int(owner_id)] if owner_id else [], ""
        for uid in ids:
            c.execute("INSERT INTO notifications(user_id,kind,task_id,list_id,actor_id,comment_id,data,created_at) VALUES(?,?,?,?,?,?,?,?)",
                      (uid, "ptlimit", None, None, None, None, json.dumps({"org_id": org_id, "org": on, "limit": PT_LOGIN_SPACE,
                                                                           "hours": PT_LOGIN_WIN // 3600}, ensure_ascii=False), iso_ms(now_utc())))
    return len(ids)


def pt_login_ask(token):
    from flask import redirect, request
    from ..core.i18n import tr
    from ..accounts.session import rate_ip
    from ..api.v1 import hit_limit
    from ..admin.hosting import mail_budget
    from ..integrations.mail import MAIL_OUT_ON
    t0 = time.monotonic()
    c = db()
    p, bad = pt_open(c, token)
    if bad:
        return bad
    lg = pt_lang(c, p)
    if not _pt_post_ok(c, p, "l"):
        return _pt_denied(lg)
    em = pt_email_norm(request.form.get("email"))
    eh = pt_email_hash(c, em) if em else ""
    space = f"{p['org_id'] or ''}:{p['owner_id'] or ''}"
    if hit_limit("ptl:" + rate_ip(), PT_LOGIN_IP, PT_LOGIN_WIN):
        return _pt_rt().pub_limited(lg)
    mail = None
    if eh and MAIL_OUT_ON and not hit_limit(f"ptla:{eh}", PT_LOGIN_ADDR, PT_LOGIN_WIN):
        with_ticket = c.execute(f"""SELECT 1 FROM portal_tickets p JOIN tasks t ON t.id=p.task_id JOIN lists l ON l.id=t.list_id
                                    WHERE p.email_hash=? AND p.org_id IS NOT DISTINCT FROM ? AND p.owner_id IS NOT DISTINCT FROM ?
                                    AND t.deleted_at IS NULL AND {_pt_space_sql()} LIMIT 1""", (eh, p["org_id"], p["owner_id"])).fetchone()
        # review: the space's limit counts only sign-in mails that really go out (others cannot lock a space's customers out)
        full = bool(with_ticket) and hit_limit(f"ptls:{space}", PT_LOGIN_SPACE, PT_LOGIN_WIN)
        if full:  # 2.138.3 C (#2380): tell the space's admins / owner (committed below)
            pt_limit_note(c, p["org_id"], p["owner_id"])
        if with_ticket and not full and mail_budget(c, None, em):
            tok = secrets.token_urlsafe(32)
            now = now_utc()
            c.execute("INSERT INTO portal_logins(email_hash,org_id,owner_id,token_hash,created_at,expires_at) VALUES(?,?,?,?,?,?)",
                      (eh, p["org_id"], p["owner_id"], _token_hash(tok), iso(now), iso(now + timedelta(seconds=PT_LOGIN_TTL))))
            url = f"{PUBLIC_URL}/portal/login/{tok}"
            lines = [tr("Hello,", lg=lg), tr("here is your link to all your reports. It is valid for 30 minutes and can be used once.", lg=lg),
                     tr("If you did not ask for it, you can ignore this mail.", lg=lg)]
            mail = (em, tr("Your reports: sign-in link", lg=lg), "\n\n".join(lines[:2]) + f"\n\n{url}\n\n" + lines[2],
                    _pt_mail_html(lines[:2], url, tr("Show my reports", lg=lg), html.escape(lines[2])))
    # 2.81.0 (#1866): a used sign-in row is the cookie's (PT_COOKIE_DAYS); unused ones go a day after their link expired
    c.execute("DELETE FROM portal_logins WHERE (used_at IS NULL AND expires_at<?) OR used_at<?",
              (iso(now_utc() - timedelta(days=1)), iso(now_utc() - timedelta(days=PT_COOKIE_DAYS + 1))))
    c.commit()
    if mail:
        threading.Thread(target=_pt_mail_bg, args=mail, daemon=True).start()
    time.sleep(max(0.0, PT_PAD - (time.monotonic() - t0)))
    return _pt_rt().pub_headers(redirect(f"/p/{token}?m=mail#all", 303))


def _pt_login_row(c, tok):
    from ..core.db import parse_iso
    from ..core.pg import system_ctx
    if not re.fullmatch(r"[A-Za-z0-9_-]{30,64}", tok or ""):
        return None
    with system_ctx(c):  # resolve the one-time token (one row) across organisations
        r = c.execute("SELECT * FROM portal_logins WHERE token_hash=?", (_token_hash(tok),)).fetchone()
    if not r or r["used_at"] or parse_iso(r["expires_at"]) <= now_utc():
        return None
    return r


def _pt_link_gone(lg):
    from ..core.i18n import tr
    e = html.escape
    return _pt_rt().pub_html(tr("Link not available", lg=lg), f'<div class="msg"><h1>{e(tr("Link not available", lg=lg))}</h1>'
                             f'<p>{e(tr("This sign-in link has expired or was used already. Ask for a new one on the status page of a report.", lg=lg))}</p></div>', lg, 404)


@app.get("/portal/login/<tok>")
def pt_login_page(tok):
    """A button, not the sign-in itself: mail scanners that open links must not use the one-time link up."""
    from ..accounts.session import _accept_lang, _rate_blocked, _rate_fail, rate_ip
    from ..core.i18n import tr
    c = db()
    lg = _accept_lang()
    bad = [("ptbad:" + rate_ip(), PT_BAD_LIMIT)]  # 2.126.0 C (#1979 I2): limited only when the link is not valid
    r = _pt_login_row(c, tok) if _pt_rt().public_links_on(c) else None
    if not r:
        if _rate_blocked(bad):
            return _pt_rt().pub_limited(lg)
        _rate_fail(bad)
        return _pt_link_gone(lg)
    e = html.escape
    from ..office.portaldocs import kp_login_docs
    if kp_login_docs(c, r):  # 2.120.0 (#2088): a space with documents in the portal
        head, btn = tr("Customer portal", lg=lg), tr("Show my documents", lg=lg)
    else:
        head, btn = tr("Your reports", lg=lg), tr("Show my reports", lg=lg)
    return _pt_rt().pub_html(head, f'<div class="msg"><h1>{e(head)}</h1>'
                             f'<form method="post" action="/portal/login/{e(tok)}" class="fform"><button type="submit">{e(btn)}</button></form></div>', lg)


def pt_cookie_make(c, eh, org_id, owner_id, exp, lid):
    # 2.81.0 (#1866): the cookie names its sign-in (portal_logins.id), so signing out revokes it on the server
    raw = f"{eh}.{org_id or 0}.{owner_id or 0}.{exp}.{lid}"
    return raw + "." + hmac.new(auth_key(c), b"kalmido-portal-cookie|" + raw.encode(), hashlib.sha256).hexdigest()


def r81c_cookie_login(c):
    """2.81.0 (#1866): the sign-in row of a valid, signed, unexpired portal cookie that was not revoked, else None.
    Cookies from before 2.81.0 (without the sign-in id) no longer count: the customer signs in once more."""
    from flask import request
    from ..core.pg import system_ctx
    v = request.cookies.get(PT_COOKIE, "")
    m = re.fullmatch(r"([0-9a-f]{64})\.(\d+)\.(\d+)\.(\d+)\.(\d+)\.([0-9a-f]{64})", v)
    if not m or int(m.group(4)) < time.time():
        return None
    if not hmac.compare_digest(pt_cookie_make(c, m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))), v):
        return None
    with system_ctx(c):  # the signed id of one sign-in row; address and space are compared below
        r = c.execute("SELECT * FROM portal_logins WHERE id=?", (int(m.group(5)),)).fetchone()
    if (not r or r["revoked_at"] or not r["used_at"] or r["email_hash"] != m.group(1)
            or (r["org_id"] or 0) != int(m.group(2)) or (r["owner_id"] or 0) != int(m.group(3))):
        return None
    return r


def pt_cookie_read(c):
    """(email_hash, org_id, owner_id) of a valid portal cookie, else None."""
    r = r81c_cookie_login(c)
    return (r["email_hash"], r["org_id"], r["owner_id"]) if r else None


@app.post("/portal/login/<tok>")
def pt_login(tok):
    from flask import redirect, request
    from ..accounts.session import _accept_lang, _rate_blocked, _rate_fail, rate_ip
    from ..core.access import acx_anon_bind
    c = db()
    lg = _accept_lang()
    bad = [("ptbad:" + rate_ip(), PT_BAD_LIMIT)]  # 2.126.0 C (#1979 I2): limited only when the link is not valid
    if request.headers.get("Sec-Fetch-Site", "") == "cross-site":
        return _pt_denied(lg)
    r = _pt_login_row(c, tok) if _pt_rt().public_links_on(c) else None
    if not r:
        if _rate_blocked(bad):
            return _pt_rt().pub_limited(lg)
        _rate_fail(bad)
        return _pt_link_gone(lg)
    acx_anon_bind(c, r["org_id"])
    n = c.execute("UPDATE portal_logins SET used_at=? WHERE id=? AND used_at IS NULL", (iso(now_utc()), r["id"])).rowcount
    c.commit()
    if n != 1:  # used in the meantime (a second click)
        return _pt_link_gone(lg)
    resp = redirect("/portal", 303)
    secure = request.is_secure or request.headers.get("X-Forwarded-Proto", "") == "https"
    resp.set_cookie(PT_COOKIE, pt_cookie_make(c, r["email_hash"], r["org_id"], r["owner_id"], int(time.time()) + PT_COOKIE_DAYS * 86400, r["id"]),
                    max_age=PT_COOKIE_DAYS * 86400, httponly=True, samesite="Lax", secure=secure, path="/portal")
    return _pt_rt().pub_headers(resp)


def pt_my_tickets(c, eh, org_id, owner_id):
    """The tickets of one address in one space (newest first), live ones only."""
    return c.execute(f"""SELECT p.*, t.title, t.status, t.ttype, t.assignee_id, t.assignee_group_id FROM portal_tickets p
                         JOIN tasks t ON t.id=p.task_id JOIN lists l ON l.id=t.list_id JOIN users u ON u.id=l.owner_id
                         WHERE p.email_hash=? AND p.org_id IS NOT DISTINCT FROM ? AND p.owner_id IS NOT DISTINCT FROM ?
                         AND t.deleted_at IS NULL AND u.disabled=0 AND {_pt_space_sql()} ORDER BY p.id DESC LIMIT 200""",
                     (eh, org_id, owner_id)).fetchall()


@app.get("/portal")
def pt_portal():
    from flask import g
    from ..accounts.session import _accept_lang, rate_ip
    from ..api.v1 import hit_limit
    from ..core.access import acx_anon_bind
    from ..core.config import APP_NAME
    from ..core.i18n import tr
    c = db()
    lg = _accept_lang()
    if hit_limit("ptv:" + rate_ip(), PT_VIEW_RATE):
        return _pt_rt().pub_limited(lg)
    e = html.escape
    who = pt_cookie_read(c) if _pt_rt().public_links_on(c) else None
    if not who:
        return _pt_rt().pub_html(tr("Your reports", lg=lg), f'<div class="msg"><h1>{e(tr("Your reports", lg=lg))}</h1>'
                                 f'<p>{e(tr("Open the status link of one of your reports and choose “All my reports”: we send you a sign-in link.", lg=lg))}</p></div>', lg)
    acx_anon_bind(c, who[1])  # nobody, inside exactly the space of the sign-in
    g.user, g.auth_via = _pt_rt().PUB_ACTOR, "public"
    from ..core.pg import system_ctx
    with system_ctx(c):  # the owners' accounts (disabled = gone); the query itself is bound to the cookie's address and space
        rows = pt_my_tickets(c, *who)
    items = []
    for r in rows:
        st = pt_state(c, r)
        kind = PT_TYPES.get(r["ttype"] or "")
        items.append(f'<li><a href="/p/{e(pt_token(c, r))}"><b>{e(r["title"])}</b><span class="sub">'
                     f'{e(" · ".join(x for x in (tr(kind, lg=lg) if kind else "", pt_day(r["created_at"], lg)) if x))}</span></a>'
                     f'<span class="ptst ptst-{st}">{e(tr(PT_STATE_TXT[st], lg=lg))}</span></li>')
    from ..office.portaldocs import kp_portal_html
    docs = kp_portal_html(c, who, lg)  # 2.120.0 B (#2088): the documents of the address (None = off: the page as before)
    tickets = f'<ul class="ptall">{"".join(items)}</ul>' if items else f'<p class="empty">{e(tr("No reports for this address.", lg=lg))}</p>'
    if docs is not None:
        tickets = docs + (f'<h2>{e(tr("Your reports", lg=lg))}</h2>{tickets}' if items else "")
    out = (f'<header><h1>{e(tr("Your reports", lg=lg) if docs is None else tr("Customer portal", lg=lg))}</h1></header>'
           + tickets
           + f'<form method="post" action="/portal/logout" class="ptout"><input type="hidden" name="f" value="{pt_out_key(c)}">'
           f'<button type="submit">{e(tr("Sign out", lg=lg))}</button></form>')
    return _pt_rt().pub_html(f'{tr("Your reports", lg=lg)} · {APP_NAME}', out, lg)


def pt_out_key(c):
    from flask import request
    return hmac.new(auth_key(c), b"kalmido-portal-out|" + (request.cookies.get(PT_COOKIE, "")).encode(), hashlib.sha256).hexdigest()


@app.post("/portal/logout")
def pt_logout():
    from flask import redirect, request
    c = db()
    if request.headers.get("Sec-Fetch-Site", "") == "cross-site" or not hmac.compare_digest(request.form.get("f") or "", pt_out_key(c)):
        from ..accounts.session import _accept_lang
        return _pt_denied(_accept_lang())
    r = r81c_cookie_login(c)
    if r:  # 2.81.0 (#1866): the cookie stops working everywhere, not only in this browser
        from ..core.pg import system_ctx
        with system_ctx(c):  # the one sign-in row the signed cookie names
            c.execute("UPDATE portal_logins SET revoked_at=? WHERE id=?", (iso(now_utc()), r["id"]))
        c.commit()
    resp = redirect("/portal", 303)
    resp.delete_cookie(PT_COOKIE, path="/portal")
    return _pt_rt().pub_headers(resp)


# ---- the app side: the ticket of a task (task panel), the comment switch "To the customer", the notify switch
def pt_client_for(c, list_row, email):
    """The client (office module) of a report: the list's client, else the client of the list's organisation whose
    e-mail or a contact person's e-mail is the reporter's address (only inside that organisation). None when none."""
    lr = c.execute("SELECT id, org_id, client_id FROM lists WHERE id=?", (list_row["id"],)).fetchone()
    if not lr:
        return None
    if lr["client_id"]:
        cl = c.execute("SELECT id, org_id FROM clients WHERE id=?", (lr["client_id"],)).fetchone()
        if cl and cl["org_id"] == lr["org_id"]:
            return cl["id"]
    e = pt_email_norm(email)
    if not lr["org_id"] or not e:
        return None
    r = c.execute("SELECT id FROM clients WHERE org_id=? AND archived=0 AND lower(email)=? ORDER BY id LIMIT 1", (lr["org_id"], e)).fetchone() \
        or c.execute("""SELECT cl.id FROM office_client_contacts k JOIN clients cl ON cl.id=k.client_id WHERE cl.org_id=? AND cl.archived=0
                        AND lower(k.email)=? ORDER BY cl.id LIMIT 1""", (lr["org_id"], e)).fetchone()
    return r["id"] if r else None


def pt_ticket_of(c, tid):
    """The live ticket of task tid (its list still in the ticket's space) or None."""
    return c.execute(f"""SELECT p.* FROM portal_tickets p JOIN tasks t ON t.id=p.task_id JOIN lists l ON l.id=t.list_id
                         WHERE p.task_id=? AND {_pt_space_sql()}""", (tid,)).fetchone()


def pt_ticket_info(c, tid, uid):
    """{..} for the task panel (GET /timeline: ticket) or None. Everyone who sees the task sees that it is a customer's
    report and the name; the address, the status link and the mail switch only people who may change the task."""
    from ..core.access import task_visible
    p = pt_ticket_of(c, tid)
    if not p:
        return None
    w = task_visible(c, tid, uid, write=True)
    d = {"id": p["id"], "name": p["name"], "created_at": p["created_at"], "can_write": bool(w), "client_id": p["client_id"]}
    if p["client_id"]:
        cl = c.execute("SELECT name FROM clients WHERE id=?", (p["client_id"],)).fetchone()
        d["client_name"] = cl["name"] if cl else None
    if w:
        d.update(email=pt_email(c, p), url=pt_status_url(pt_token(c, p)), notify=bool(p["notify"]), last_seen_at=p["last_seen_at"])
    return d


def pt_comment_flag(c, tid, uid, v):
    """2.63.0 B (#1513): the portal flag of a new comment: 1 only when asked for, the task has a ticket and the writer may
    change the task. Raises BadInput otherwise (the client never sends it without a ticket)."""
    from ..core.access import task_visible
    from ..core.i18n import tr
    from ..personal.timetrack import BadInput
    if v in (None, False, 0, "0", "false", ""):
        return 0
    if v not in (True, 1, "1", "true", "on"):
        raise BadInput(tr("portal: true or false"))
    if not pt_ticket_of(c, tid):
        raise BadInput(tr("This task has no customer report: the comment cannot go to a customer"))
    if not task_visible(c, tid, uid, write=True):
        raise BadInput(tr("Only people who may change the task answer the customer"))
    return 1


@app.patch("/api/tasks/<int:tid>/ticket")
def pt_ticket_set(tid):
    """{notify: bool}: mails to the reporter on / off (people who may change the task)."""
    from flask import jsonify
    from ..core.db import body, bump, err
    from ..core.access import need_task
    from ..core.i18n import tr
    from ..accounts.session import me
    c = db()
    need_task(c, tid, write=True)
    p = pt_ticket_of(c, tid)
    b = body()
    if not p:
        return err(tr("This task has no customer report"), 404)
    if set(b) - {"notify"} or not isinstance(b.get("notify"), bool):
        return err(tr("Expected {0}", '{"notify": true|false}'))
    if b["notify"] and not p["email"]:
        return err(tr("The reporter left no e-mail address"), 409)
    c.execute("UPDATE portal_tickets SET notify=? WHERE id=?", (1 if b["notify"] else 0, p["id"]))
    bump(c)
    c.commit()
    return jsonify(pt_ticket_info(c, tid, me()))


def pt_client_tickets(c, uid, cid):
    """The reports of a client the person may see (client card): newest first, at most 50."""
    from ..core.access import task_visible
    out = []
    for r in c.execute(f"""SELECT p.task_id, p.name, p.created_at, t.title, t.status FROM portal_tickets p JOIN tasks t ON t.id=p.task_id
                           JOIN lists l ON l.id=t.list_id WHERE (p.client_id=? OR (p.client_id IS NULL AND l.client_id=?))
                           AND t.deleted_at IS NULL AND {_pt_space_sql()} ORDER BY p.id DESC LIMIT 200""", (cid, cid)):
        if task_visible(c, r["task_id"], uid):
            out.append({"task_id": r["task_id"], "title": r["title"], "done": r["status"] != 0, "created_at": r["created_at"]})
            if len(out) >= 50:
                break
    return out


# ---- mails to the reporter: a public answer and "done" (only with notify and an address; at most one mail per ticket
# within PT_MAIL_GAP -- what happened in between goes out together). The watchdog (notify/push.py) calls this.
def pt_mail_tick(c):
    from ..core.db import parse_iso
    from ..core.i18n import lang, tr
    from ..core.pg import system_ctx
    from ..admin.hosting import mail_budget
    from ..integrations.mail import MAIL_OUT_ON
    if not MAIL_OUT_ON:
        return
    now = now_utc()
    cut = iso(now - timedelta(seconds=PT_MAIL_GAP))
    mails = []
    with system_ctx(c):  # the reporters of every organisation (the watchdog is nobody's request)
        rows = c.execute(f"""SELECT p.*, t.title, t.status, l.owner_id AS l_owner FROM portal_tickets p JOIN tasks t ON t.id=p.task_id
                             JOIN lists l ON l.id=t.list_id JOIN users u ON u.id=l.owner_id
                             WHERE p.notify=1 AND p.email!='' AND t.deleted_at IS NULL AND u.disabled=0 AND {_pt_space_sql()}
                             AND (p.last_mail_at IS NULL OR p.last_mail_at<=?)
                             AND ((t.status=2 AND p.mailed_status!=2) OR (t.status!=2 AND p.mailed_status=2) OR EXISTS(
                               SELECT 1 FROM comments k WHERE k.task_id=p.task_id AND k.portal=1 AND k.user_id IS NOT NULL
                               AND k.deleted_at IS NULL AND k.created_at>COALESCE(p.last_mail_at, p.created_at)))
                             ORDER BY p.id LIMIT 100""", (cut,)).fetchall()
        for p in rows:
            since = parse_iso(p["last_mail_at"] or p["created_at"])
            new = [a for a in pt_answers(c, p["task_id"]) if not a["customer"] and parse_iso(a["at"]) > since]
            done = p["status"] == 2 and p["mailed_status"] != 2
            if not new and not done:  # reopened without news: only remember the state
                c.execute("UPDATE portal_tickets SET mailed_status=? WHERE id=?", (p["status"], p["id"]))
                continue
            em = pt_email(c, p)
            if em and not mail_budget(c, None, em):  # review: the day's mails to this address are used up -> try again later
                continue
            c.execute("UPDATE portal_tickets SET last_mail_at=?, mailed_status=? WHERE id=?", (iso(now), p["status"], p["id"]))
            if not em:
                continue
            lg = p["lang"] or lang(c, p["l_owner"])
            tok = pt_token(c, p)
            url, stop = pt_status_url(tok), pt_status_url(tok) + "/stop"
            head = tr("Your report “{0}” is done.", p["title"], lg=lg) if done else \
                tr("There is a new answer to your report “{0}”.", p["title"], lg=lg)
            body_ = [(a["who"] or tr("Team", lg=lg)) + ":\n" + a["body"][:2000] for a in new[-3:]]
            foot = tr("You get this mail because you sent the report. No more mails about it: {0}", stop, lg=lg)
            ttl = " ".join(p["title"].split())  # review: no line breaks in the subject
            subj = (tr("Done: {0}", ttl, lg=lg) if done else tr("New answer: {0}", ttl, lg=lg))[:200]
            text = "\n\n".join([head, *body_, tr("Status and answers: {0}", url, lg=lg), foot])
            hfoot = html.escape(tr("You get this mail because you sent the report.", lg=lg)) + \
                f' <a href="{html.escape(stop)}">{html.escape(tr("No more mails about this report", lg=lg))}</a>'
            mails.append((em, subj, text, _pt_mail_html([head, *body_], url, tr("Show the report", lg=lg), hfoot)))
        c.commit()
    for m in mails:
        threading.Thread(target=_pt_mail_bg, args=m, daemon=True).start()
