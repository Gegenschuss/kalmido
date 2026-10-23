"""Public links of lists and checklist mode."""
import hashlib
import hmac
import html
import re
import secrets
import threading
import time
from datetime import date, datetime, timedelta
from flask import g, jsonify, redirect, request, Response
from werkzeug.security import check_password_hash, generate_password_hash

from ..core.config import app, APP_NAME, PUB_PREFIX, PUBLIC_URL, TZ
from ..core.i18n import lang, LANGS, N_, short_day, tr, trn
from ..core.db import body, bump, db, err, gsetting, inbox_default, iso, local_now, now_utc, parse_iso, iso_ms
from ..accounts.session import _accept_lang, _rate_blocked, _rate_fail, _token_hash, me, rate_ip
from ..accounts.login import auth_key, seal, unseal
from ..core.access import acx_anon_bind, Denied, need_list, task_visible
from ..core.pg import insert_id, system_ctx
from ..tasks.validation import log_act, valid_date
from ..tasks.lifecycle import complete_stale, do_complete, trash_task
from ..collab.comments import task_event
from ..core.errors import BadInput
from ..tasks.dependencies import completed_ids, unblock_events
from ..notify.alerts import _env_int, aa_count, aa_now
from ..api.v1 import PUB_ENV
from ..api.common import hit_budget, hit_limit
from .custview import CV_FB_HOUR, CV_FB_NAME, CV_FB_RATE, CV_FB_TEXT, CV_FILE_RATE, cv_brand, cv_clean, cv_extras, cv_file, cv_options, cv_progress, cv_show, cv_size, cv_tag_sql
from ..core.orgcrypt import oc_send_file  # 2.149.0 G (#2517): pulled up from functions


# ---------------------------------------------------------------- package B: public links + checklist mode
# The OWNER of a list can create one public link (/s/<token>, 192 random bits; the token is stored sealed so the owner can
# copy it again, lookups go by its SHA-256): "view only" or "view + tick off", optional expiry, optional password
# (hashed; an unlock cookie per link, HttpOnly + SameSite=Strict, bound to the password version), revoke / regenerate.
# The page is server-rendered HTML without scripts and without the app: only that list's name, sections, open tasks
# with their subtasks and the recently completed ones (a checklist: all done items), with due dates; notes only when
# the owner switched them on (escaped plain text). Never comments, assignees, tags, attachments, fields or other lists.
# Ticking off goes through the same completion code as the app (history "via the public link", notifications to the
# creator / assigner like a normal completion, subject to the collaboration switches, webhooks). Limits per client
# address (views, ticks, unknown tokens, wrong passwords), noindex, no caching, a strict CSP, and an admin alert when one
# link is opened unusually often. Admin switch Settings > Users > Whole server; KALMIDO_PUBLIC_LINKS=0 turns it off for good.
PUB_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{20,64}")
PUB_VIEW_RATE = _env_int("KALMIDO_PUBLIC_RATE", 60)    # page views per client address and minute
PUB_TICK_RATE = 30                                    # ticks per client address and minute
PUB_BAD_LIMIT = 30                                    # unknown / expired tokens per address within FAIL_WINDOW
PUB_PW_LIMIT, PUB_PW_LINK_LIMIT = 10, 50              # wrong passwords per link + address / per link within FAIL_WINDOW
PUB_BURST = _env_int("KALMIDO_PUBLIC_BURST", 300)      # views of one link within PUB_BURST_S -> security alert
PUB_BURST_S = 600
PUB_DONE_DAYS = 7
PUB_MAX_TASKS = 2000
PUB_NOTES_MAX = 2000
PUB_CSP = ("default-src 'none'; style-src 'self'; img-src 'self'; font-src 'self'; form-action 'self'; frame-ancestors 'none'; "
           "base-uri 'none'")
PUB_ACTOR = {"id": 0, "username": "", "display_name": "", "is_admin": 0, "disabled": 0, "password_hash": None, "proxy_login": None}
_PUB_VIEWS, _PUB_LOCK = {}, threading.Lock()


def public_links_on(c):
    return PUB_ENV and gsetting(c, "public_links") != "0"


def pub_find(c, token):
    """The live link of a token (owner enabled, not expired) + the list, or None."""
    if not PUB_TOKEN_RE.fullmatch(token or ""):
        return None
    with system_ctx(c):  # 2.37.0 (#1150): resolve the token (one row) across organisations ...
        r = c.execute("""SELECT p.*, l.name AS l_name, l.is_inbox AS l_inbox, l.checklist AS l_checklist, l.owner_id AS l_owner,
                         l.org_id AS l_org FROM public_links p JOIN lists l ON l.id=p.list_id JOIN users u ON u.id=l.owner_id
                         WHERE p.token_hash=? AND u.disabled=0 AND l.deleted_at IS NULL AND COALESCE(l.life,'') NOT IN ('budget', 'health')""", (_token_hash(token),)).fetchone()  # 2.72.0 (#1333): never a budget; 2.102.0 review F4: never a list in the trash; 2.190.0 C (#2496): never a health list
    if not r or (r["expires_at"] and parse_iso(r["expires_at"]) <= now_utc()):
        return None
    acx_anon_bind(c, r["l_org"])  # ... then the page reads as nobody, inside exactly the list's organisation
    # 2.37.0 (review K2-2): also for a signed-in visitor (the context hook prefers g.user): a public page is nobody's
    g.user, g.auth_via = PUB_ACTOR, "public"
    return r


def pub_lang(c, link):
    for part in (request.headers.get("Accept-Language") or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in LANGS:
            return code
    return lang(c, link["l_owner"])


def pub_cookie(link):
    return f"kalmido_pub{link['id']}"


def pub_cookie_val(c, link):
    return hmac.new(auth_key(c), f"pub:{link['id']}:{link['pw_rev']}:{link['token_hash']}".encode(), hashlib.sha256).hexdigest()


def pub_unlocked(c, link):
    return not link["password_hash"] or hmac.compare_digest(request.cookies.get(pub_cookie(link), ""), pub_cookie_val(c, link))


def pub_headers(resp):
    resp.headers["Content-Security-Policy"] = PUB_CSP
    resp.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-store, private"
    return resp


def pub_html(title, main, lg, code=200, foot=True):
    e = html.escape
    doc = (f'<!doctype html><html lang="{e(lg)}"><head><meta charset="utf-8">'
           '<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex, nofollow">'
           f'<meta name="referrer" content="no-referrer"><title>{e(title)}</title><link rel="stylesheet" href="/static/public.css">'
           f'<link rel="icon" href="/static/favicon.svg" type="image/svg+xml"></head><body><main>{main}</main>'
           + (f'<footer>{e(tr("Shared with {0}", APP_NAME, lg=lg))}</footer>' if foot else '') + '</body></html>')
    return pub_headers(Response(doc, status=code, mimetype="text/html"))


# 2.14.0: the figure of the error pages; 2.136.0 (#2193): the bot figure, state "schaut" (looks), same drawing and
# colours as in the app (render.js botFig, public.css .bot: plate + body after the colour scheme, the antenna = the accent)
BOT_ERROR = ('<svg class="bot b-schaut" viewBox="0 0 100 100" aria-hidden="true" focusable="false">'
             '<rect class="b-plate" width="100" height="100" rx="22.5"/><g transform="translate(50 50) scale(.9) translate(-50 -40)">'
             '<path class="b-body" d="M50 22C74 22 78 26 78 50S74 78 50 78 22 74 22 50 26 22 50 22Z"/>'
             '<g class="b-eyes" fill="none" stroke-linecap="round"><path d="M48 42V54" stroke-width="6.5"/>'
             '<path d="M66 48V48.1" stroke-width="8.5"/></g><path class="b-ant" d="M58 6V15" stroke-width="7" stroke-linecap="round"/></g></svg>')


def pub_gone(lg=None):
    """The same answer for unknown, expired, revoked and switched-off links (no oracle)."""
    lg = lg or _accept_lang()
    return pub_html(tr("Link not available", lg=lg), f'<div class="msg">{BOT_ERROR}<h1>{html.escape(tr("Link not available", lg=lg))}</h1>'
                    f'<p>{html.escape(tr("This link does not exist or is no longer shared.", lg=lg))}</p></div>', lg, 404)


def pub_limited(lg):
    r = pub_html(tr("Too many requests", lg=lg), f'<div class="msg"><h1>{html.escape(tr("Too many requests", lg=lg))}</h1>'
                 f'<p>{html.escape(tr("Please wait a minute and try again.", lg=lg))}</p></div>', lg, 429)
    r.headers["Retry-After"] = "60"
    return r


def pub_open(c, token):
    """Common checks of every /s/ request -> (link, None) or (None, response)."""
    ip = rate_ip()
    if not public_links_on(c):
        return None, pub_gone()
    bad = [("pubbad:" + ip, PUB_BAD_LIMIT)]  # 2.126.0 C (#1979 I2): limited only when the link is not valid
    link = pub_find(c, token)
    if not link:
        if _rate_blocked(bad):
            return None, pub_limited(_accept_lang())
        _rate_fail(bad)
        aa_count("security", "publink", ip)
        return None, pub_gone()
    return link, None


def pub_seen(c, link):
    """Counts a view; an unusual burst of views of one link -> security alert (once per PUB_BURST_S)."""
    now, ip = time.time(), rate_ip()
    with _PUB_LOCK:
        s = _PUB_VIEWS.setdefault(link["id"], {"hits": [], "alerted": 0.0})
        s["hits"] = [h for h in s["hits"] if now - h[0] < PUB_BURST_S] + [(now, ip)]
        burst = len(s["hits"]) >= PUB_BURST and now - s["alerted"] >= PUB_BURST_S
        if burst:
            s["alerted"] = now
            n, ips = len(s["hits"]), len({h[1] for h in s["hits"]})
    if burst:
        aa_now("security", f"publink_burst:{link['list_id']}",
               N_("The public link of project {0} was opened {1} times within {2} minutes (from {3} addresses)."),
               [link["list_id"], n, PUB_BURST_S // 60, ips])
    c.execute("UPDATE public_links SET views=views+1, last_used_at=? WHERE id=?", (iso(now_utc()), link["id"]))
    c.commit()


def pub_tasks(c, link):
    cut = iso(now_utc() - timedelta(days=PUB_DONE_DAYS))
    tsql, targs = cv_tag_sql(cv_show(link))  # 2.50.0 (#329): "only tasks with tag ..." (ticking too: only what is shown)
    return [dict(r) for r in c.execute(
        """SELECT id, parent_id, section_id, title, content, status, due, due_time, priority, completed_at, sort, assignee_id, ms FROM tasks
           WHERE list_id=? AND deleted_at IS NULL AND (status=0 OR ? OR completed_at>=?)""" + tsql + " ORDER BY sort, id LIMIT ?",
        (link["list_id"], 1 if link["l_checklist"] else 0, cut, *targs, PUB_MAX_TASKS))]


def pub_render(c, link, token, lg):
    e = html.escape
    tasks = pub_tasks(c, link)
    ids = {t["id"] for t in tasks}
    kids = {}
    for t in tasks:
        kids.setdefault(t["parent_id"] if t["parent_id"] in ids else None, []).append(t)
    tick, check = link["mode"] == "tick", bool(link["l_checklist"])
    today = local_now().date().isoformat()
    show = cv_show(link)  # 2.50.0 (#329): what the owner lets the customer see (filtered here, never hidden by CSS)
    ext = cv_extras(c, link, tasks, show, lg, pub_day)

    def row(t, depth=0):
        done = t["status"] != 0
        if tick:
            label = tr("Put back on the list", lg=lg) if done else tr("Mark as done", lg=lg)
            box = (f'<form method="post" action="/s/{e(token)}/tick"><input type="hidden" name="task" value="{t["id"]}">'
                   f'<input type="hidden" name="to" value="{"open" if done else "done"}">'
                   f'<button class="chk{" on" if done else ""}" title="{e(label)}" aria-label="{e(label)}"></button></form>')
        else:
            box = f'<span class="chk{" on" if done else ""}" aria-hidden="true"></span>'
        meta = ""
        if t["due"] and not check and not done and show["due"]:
            cls = " over" if t["due"] < today else " today" if t["due"] == today else ""
            meta += f'<span class="due{cls}">{e(pub_day(t["due"], lg))}{" " + e(t["due_time"]) if t["due_time"] else ""}</span>'
        notes = ""
        if link["notes"] and (t["content"] or "").strip():
            txt = t["content"].strip()
            txt = txt[:PUB_NOTES_MAX] + ("…" if len(txt) > PUB_NOTES_MAX else "")
            notes = f'<details class="notes"><summary>{e(tr("Notes", lg=lg))}</summary><p>{e(txt)}</p></details>'
        x = ext.get(t["id"]) or {}
        info = ([f'<span class="who">{e(x["who"])}</span>'] if x.get("who") else []) + \
            [f'<span class="tag">{e(n)}</span>' for n, _ in x.get("tags", [])] + \
            [f'<span class="fld"><span class="fn">{e(n)}</span> {e(v)}</span>' for n, v in x.get("fields", [])]
        if info:
            meta += f'<div class="cvmeta">{"".join(info)}</div>'
        if x.get("files"):
            meta += '<ul class="files">' + "".join(
                (f'<li><a href="/s/{e(token)}/file/{fid}" download rel="nofollow">{e(fn)}</a> <span class="fs">{e(cv_size(sz, lg))}</span></li>' if ok
                 else f'<li>{e(fn)} <span class="fs">{e(cv_size(sz, lg))}</span></li>') for fid, fn, sz, ok in x["files"]) + '</ul>'
        sub = "".join(row(k, depth + 1) for k in kids.get(t["id"], []))
        pr = f" p{t['priority']}" if t["priority"] and not check else ""
        ms = " ms" if t.get("ms") else ""
        return (f'<li id="t{t["id"]}" class="t{" done" if done else ""}{pr}{ms}">{box}<div class="tt"><span class="ttl">{e(t["title"])}</span>'
                f'{meta}{notes}</div>{"<ul>" + sub + "</ul>" if sub else ""}</li>')
    top = kids.get(None, [])
    open_top, done_top = [t for t in top if t["status"] == 0], [t for t in top if t["status"] != 0]
    secs = [dict(r) for r in c.execute("SELECT id, name FROM sections WHERE list_id=? ORDER BY sort, id", (link["list_id"],))] \
        if show["sections"] else []
    sec_ids = {s["id"] for s in secs}
    body_ = ""
    groups = [(None, [t for t in open_top if t["section_id"] not in sec_ids])] + \
        [(s["name"], [t for t in open_top if t["section_id"] == s["id"]]) for s in secs]
    n_open = sum(1 for t in tasks if t["status"] == 0)
    for name, ts in groups:
        if name is not None and not ts:
            continue
        body_ += (f'<h2>{e(name)}</h2>' if name is not None else "") + f'<ul class="tasks">{"".join(row(t) for t in ts)}</ul>'
    if not n_open:
        body_ += f'<p class="empty">{e(tr("Nothing open.", lg=lg))}</p>'
    if done_top:
        if check:  # a checklist's done items by name (as in the app), otherwise the latest completion first
            done_top.sort(key=lambda t: t["title"].casefold())
        else:
            done_top.sort(key=lambda t: t["completed_at"] or "", reverse=True)
        title = tr("Done|checklist", lg=lg) if check else tr("Recently completed", lg=lg)
        body_ += (f'<details class="donegrp"{" open" if check else ""}><summary>{e(title)} <span class="n">{len(done_top)}</span></summary>'
                  f'<ul class="tasks">{"".join(row(t) for t in done_top)}</ul></details>')
    name = tr("Basket") if link["l_inbox"] and inbox_default(link["l_name"]) else link["l_name"]
    mode = tr("You can tick off items on this page.", lg=lg) if tick else tr("View only.", lg=lg)
    brand = ""
    if show["brand"]:  # 2.50.0 (#329): the organisation's name / logo above the project name
        bname, blogo = cv_brand(c, link)
        if bname or blogo:
            img = f'<img src="/s/{e(token)}/logo" alt="">' if blogo else ""
            brand = f'<div class="brand">{img}' + (f'<span>{e(bname)}</span>' if bname else "") + '</div>'
    prog = ""
    if show["progress"]:
        d, n = cv_progress(c, link, show)
        pct = round(100 * d / n) if n else 0
        prog = (f'<div class="prog" role="img" aria-label="{e(tr("{0} of {1} done", d, n, lg=lg))}"><div class="bar"><i class="w{pct // 5 * 5}"></i></div>'
                f'<span>{e(tr("{0} of {1} done", d, n, lg=lg))}</span></div>')
    head = (f'<header>{brand}<h1>{e(name)}</h1><p class="sub">{e(trn("{0} open item", "{0} open items", n_open, lg=lg))} · {e(mode)}</p>{prog}</header>')
    head += pub_signoffs(c, link, lg)
    if show["feedback"]:
        body_ += cv_fb_form(c, link, token, lg, [t for t in top if t["id"] in ids])
    return pub_html(f"{name} · {APP_NAME}", head + body_, lg)


# 2.50.0 (#329): the customer's comment (switch "Comments from the customer", off by default) -> a comment on the chosen task,
# without an account (user_id NULL) and with the name the customer typed (comments.ext_name); plain text, length limits,
# rate limits per client address and per link, a form check value bound to the link + Sec-Fetch-Site
def cv_fb_key(c, link):
    return hmac.new(auth_key(c), f"pubfb:{link['id']}:{link['token_hash']}".encode(), hashlib.sha256).hexdigest()


def cv_fb_form(c, link, token, lg, tasks):
    e = html.escape
    if not tasks:
        return ""
    sent = request.args.get("sent") == "1"
    opts = "".join(f'<option value="{t["id"]}">{e(t["title"][:120])}</option>' for t in tasks)
    return (f'<section class="fb" id="fb"><h2>{e(tr("Your comment to the team", lg=lg))}</h2>'
            + (f'<p class="ok" role="status">{e(tr("Thank you, your comment has arrived.", lg=lg))}</p>' if sent else "")
            + f'<form method="post" action="/s/{e(token)}/feedback" class="fform"><input type="hidden" name="f" value="{cv_fb_key(c, link)}">'
            f'<label for="fb-task">{e(tr("About which task?", lg=lg))}</label><select id="fb-task" name="task">{opts}</select>'
            f'<label for="fb-name">{e(tr("Your name|public", lg=lg))}</label><input id="fb-name" name="name" maxlength="{CV_FB_NAME}" autocomplete="name" required>'
            f'<label for="fb-text">{e(tr("Comment", lg=lg))}</label><textarea id="fb-text" name="text" rows="4" maxlength="{CV_FB_TEXT}" required></textarea>'
            f'<button type="submit">{e(tr("Send", lg=lg))}</button></form></section>')


def cv_fb_clean(v, mx):
    v = "".join(ch for ch in (v or "").replace("\r", "") if ch == "\n" or ord(ch) >= 32)
    return re.sub(r"<@\d+>", "", v).strip()[:mx]  # no mention tokens of the app


@app.post("/s/<token>/feedback")
def cv_fb_post(token):
    from ..collab.comments import collab_user, lang_of
    from ..collab.news import KIND_ROW, news_add, notif_ok
    from ..notify.push import push_prio, push_reachable
    from ..agents.core import agent_ids
    c = db()
    link, bad = pub_open(c, token)
    if bad:
        return bad
    lg = pub_lang(c, link)
    show = cv_show(link)
    if request.headers.get("Sec-Fetch-Site", "") == "cross-site" or not show["feedback"] \
            or not hmac.compare_digest(request.form.get("f") or "", cv_fb_key(c, link)):
        return pub_html(tr("Not allowed", lg=lg), f'<div class="msg"><h1>{html.escape(tr("Not allowed", lg=lg))}</h1></div>', lg, 403)
    if not pub_unlocked(c, link):
        return redirect(f"/s/{token}", 303)
    if hit_limit("pubfb:" + rate_ip(), CV_FB_RATE) or hit_budget(f"pubfbl:{link['id']}", CV_FB_HOUR, rate_ip()):  # 2.126.0 C (#1979 I1)
        return pub_limited(lg)
    try:
        tid = int(request.form.get("task") or 0)
    except ValueError:
        tid = 0
    visible = {t["id"]: t for t in pub_tasks(c, link)}
    name = " ".join(cv_fb_clean(request.form.get("name"), CV_FB_NAME).split())
    text = cv_fb_clean(request.form.get("text"), CV_FB_TEXT)
    if tid not in visible:
        return pub_gone(lg)
    if len(name) < 2 or not text:
        return pub_html(tr("Please type your name and a comment.", lg=lg),
                        f'<div class="msg"><p class="err">{html.escape(tr("Please type your name and a comment.", lg=lg))}</p>'
                        f'<a class="btn" href="/s/{html.escape(token)}#fb">{html.escape(tr("Back", lg=lg))}</a></div>', lg, 400)
    cid = insert_id(c, "INSERT INTO comments(task_id,user_id,body,mentions,created_at,ext_name) VALUES(?,?,?,?,?,?)",
                    (tid, None, text, "", iso_ms(now_utc()), name))
    t = c.execute("SELECT t.*, l.owner_id AS l_owner FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.id=?", (tid,)).fetchone()
    from ..notify.taskbell import tbl_level, tbl_sent, tbl_urgent_users, TBL_PRIO
    rcpt = ({t["l_owner"], t["created_by"], t["assignee_id"]} | tbl_urgent_users(c, tid)) - {None} - agent_ids(c)  # 2.53.0 C (#1424): + "Urgent"
    for uid in sorted(rcpt):  # News + push like a comment on my task, the notification switch "comment"
        s = collab_user(c, uid, t["list_id"])
        if not s or not task_visible(c, tid, uid, full=True):
            continue
        news_add(c, uid, "comment", task_id=tid, comment_id=cid, actor=0, s=s, data={"excerpt": text[:300], "ext_name": name})
        lv = tbl_level(c, uid, tid, s)  # 2.53.0 C (#1424): the task's bell first (muted: no push; urgent: always, priority 5)
        if lv == "urgent" and tbl_sent(uid, tid):
            continue
        if lv != "mute" and (lv == "urgent" or notif_ok(c, uid, s, KIND_ROW["comment"], "push", t["list_id"])) and push_reachable(c, uid, s):
            ulg = lang_of(s)
            g.pushes.append((uid, tr("{0} (customer, via the link)", name, lg=ulg) + ": " + t["title"], text[:200],
                             f"{PUBLIC_URL}/#t/{tid}", TBL_PRIO if lv == "urgent" else push_prio(s)))
    bump(c)
    c.commit()
    print("public link comment on task", tid, flush=True)
    return pub_headers(redirect(f"/s/{token}?sent=1#fb", 303))


def pub_signoffs(c, link, lg):
    """2.50.0 (#1200): the list's acceptance requests on the customer page (open: a button to the approval page; decided: a line)."""
    from ..office.signoff import sig_url
    e, out = html.escape, []
    for r in c.execute("SELECT * FROM office_signoffs WHERE list_id=? AND kind='acceptance' AND revoked_at IS NULL ORDER BY id DESC LIMIT 10",
                       (link["list_id"],)):
        if r["state"] == "open":
            if r["expires_at"] and parse_iso(r["expires_at"]) <= now_utc():
                continue
            url = sig_url(c, r)
            if url:
                path = url[len(PUBLIC_URL.rstrip("/")):]
                out.append(f'<a class="sgreq" href="{e(path)}">{e(tr("Confirm the acceptance: {0}", r["title"], lg=lg))}</a>')
        else:
            word = tr("Accepted", lg=lg) if r["state"] == "accepted" else tr("Declined", lg=lg)
            out.append(f'<p class="sgdone">{e(word)}: {e(r["title"])} · {e((r["signed_at"] or "")[:10])}</p>')
    return f'<div class="sgbox">{"".join(out)}</div>' if out else ""


def pub_day(d, lg):
    dd = date.fromisoformat(d)
    t = local_now().date()
    if dd == t:
        return tr("today", lg=lg)
    if dd == t + timedelta(days=1):
        return tr("tomorrow", lg=lg)
    return short_day(dd, lg, year=True)


def pub_pw_page(token, lg, wrong=False):
    e = html.escape
    main = (f'<div class="msg"><h1>{e(tr("Password required", lg=lg))}</h1><p>{e(tr("This project is protected with a password.", lg=lg))}</p>'
            f'<form method="post" action="/s/{e(token)}/unlock" class="pw"><input type="password" name="password" autocomplete="current-password" '
            f'aria-label="{e(tr("Password", lg=lg))}" required autofocus><button>{e(tr("Open", lg=lg))}</button></form>'
            + (f'<p class="err">{e(tr("Wrong password", lg=lg))}</p>' if wrong else "") + '</div>')
    return pub_html(tr("Password required", lg=lg), main, lg, 401 if wrong else 200)


@app.get("/s/<token>")
def pub_page(token):
    c = db()
    if hit_limit("pubv:" + rate_ip(), PUB_VIEW_RATE):
        return pub_limited(_accept_lang())
    link, bad = pub_open(c, token)
    if bad:
        return bad
    lg = pub_lang(c, link)
    if not pub_unlocked(c, link):
        return pub_pw_page(token, lg)
    pub_seen(c, link)
    return pub_render(c, link, token, lg)


@app.post("/s/<token>/unlock")
def pub_unlock(token):
    c = db()
    link, bad = pub_open(c, token)
    if bad:
        return bad
    lg, ip = pub_lang(c, link), rate_ip()
    if not link["password_hash"]:
        return redirect(f"/s/{token}", 303)
    keys = [(f"pubpw:{link['id']}:{ip}", PUB_PW_LIMIT), (f"pubpwl:{link['id']}", PUB_PW_LINK_LIMIT)]
    if _rate_blocked(keys):
        return pub_limited(lg)
    if not check_password_hash(link["password_hash"], request.form.get("password") or ""):
        _rate_fail(keys)
        aa_count("security", "publink", ip)
        return pub_pw_page(token, lg, wrong=True)
    resp = redirect(f"/s/{token}", 303)
    secure = request.is_secure or request.headers.get("X-Forwarded-Proto", "") == "https"
    resp.set_cookie(pub_cookie(link), pub_cookie_val(c, link), max_age=30 * 86400, httponly=True, samesite="Strict",
                    secure=secure, path=f"/s/{token}")
    return pub_headers(resp)


@app.post("/s/<token>/tick")
def pub_tick(token):
    """Tick off / put back one task of the list (mode "tick"). A plain form post -> back to the page."""
    c = db()
    link, bad = pub_open(c, token)
    if bad:
        return bad
    lg = pub_lang(c, link)
    if request.headers.get("Sec-Fetch-Site", "") == "cross-site" or link["mode"] != "tick":
        return pub_html(tr("Not allowed", lg=lg), f'<div class="msg"><h1>{html.escape(tr("Not allowed", lg=lg))}</h1></div>', lg, 403)
    if not pub_unlocked(c, link):
        return redirect(f"/s/{token}", 303)
    if hit_limit("pubt:" + rate_ip(), PUB_TICK_RATE):
        return pub_limited(lg)
    try:
        tid = int(request.form.get("task") or 0)
    except ValueError:
        tid = 0
    to = request.form.get("to")
    visible = {t["id"]: t for t in pub_tasks(c, link)}
    if tid not in visible or to not in ("done", "open"):
        return pub_gone(lg)
    g.user, g.auth_via = PUB_ACTOR, "public"  # completion code below: attributed to "someone via the public link"
    st = visible[tid]["status"]
    if to == "done" and st == 0 and not complete_stale(c, tid, visible[tid]["due"]):  # 2.126.0 D (#1987)
        nxt = do_complete(c, tid, 2)
        log_act(c, tid, "complete", {"next": nxt} if nxt else None)
        task_event(c, tid, "complete")
        unblock_events(c, completed_ids(c, tid))
    elif to == "open" and st != 0:
        c.execute("UPDATE tasks SET status=0, completed_at=NULL, completed_by=NULL, updated_at=? WHERE id=?", (iso(now_utc()), tid))
        log_act(c, tid, "reopen")
    bump(c)
    c.commit()
    return pub_headers(redirect(f"/s/{token}#t{tid}", 303))


# 2.50.0 (#329): a task file / the organisation's logo of a link that shows them (only through the token, same checks as the page)
def cv_gate(c, token):
    if hit_limit("pubf:" + rate_ip(), CV_FILE_RATE):
        return None, pub_limited(_accept_lang())
    link, bad = pub_open(c, token)
    if bad:
        return None, bad
    if not pub_unlocked(c, link):
        return None, pub_gone(pub_lang(c, link))
    return link, None


@app.get("/s/<token>/file/<int:aid>")
def cv_file_get(token, aid):
    c = db()
    link, bad = cv_gate(c, token)
    if bad:
        return bad
    show = cv_show(link)
    got = cv_file(c, link, show, {t["id"] for t in pub_tasks(c, link)}, aid)
    if not got:
        return pub_gone(pub_lang(c, link))
    a, full = got
    resp = oc_send_file(c, full, mimetype="application/octet-stream", as_attachment=True, download_name=a["name"], max_age=0)
    resp.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-store, private"
    return resp


@app.get("/s/<token>/logo")
def cv_logo_get(token):
    c = db()
    link, bad = cv_gate(c, token)
    if bad:
        return bad
    path = cv_brand(c, link)[1] if cv_show(link)["brand"] else None
    if not path:
        return pub_gone(pub_lang(c, link))
    resp = oc_send_file(c, path, mimetype="image/png", max_age=0)
    resp.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cache-Control"] = "no-store, private"
    return resp


# ---- managing the link (list dialog, owner only)
def pub_public(c, r):
    tok = unseal(c, f"publink:{r['list_id']}", r["token"])
    return {"url": PUBLIC_URL.rstrip("/") + PUB_PREFIX + tok, "mode": r["mode"], "notes": bool(r["notes"]),
            "has_password": bool(r["password_hash"]), "expires_at": r["expires_at"], "created_at": r["created_at"],
            "last_used_at": r["last_used_at"], "views": r["views"],
            "expired": bool(r["expires_at"] and parse_iso(r["expires_at"]) <= now_utc()),
            "show": cv_show(r), "options": cv_options(c, r["list_id"])}  # 2.50.0 (#329)


def need_pub_owner(c, lid):
    need_list(c, lid, owner=True)
    if c.execute("SELECT is_inbox FROM lists WHERE id=?", (lid,)).fetchone()[0]:
        raise BadInput(tr("The basket cannot be shared"))


def pub_new_token(c, lid):
    tok = secrets.token_urlsafe(24)
    return tok, _token_hash(tok), seal(c, f"publink:{lid}", tok)


@app.get("/api/lists/<int:lid>/public-link")
def pub_get(lid):
    c = db()
    need_list(c, lid, owner=True)
    r = c.execute("SELECT * FROM public_links WHERE list_id=?", (lid,)).fetchone()
    return jsonify(enabled=public_links_on(c), link=pub_public(c, r) if r else None, options=cv_options(c, lid))


@app.put("/api/lists/<int:lid>/public-link")
def pub_set(lid):
    """{mode: view|tick, notes: bool, password: str ('' = none; left out = keep), expires: YYYY-MM-DD | null} -> the link
    (created on the first call; the token stays the same on later changes)."""
    c = db()
    need_pub_owner(c, lid)
    if not public_links_on(c):
        return err(tr("Public links are turned off on this server"), 409)
    from ..collab.liste2e import le2e_mode
    if le2e_mode(c, lid):  # 2.64.1 (#1817): its texts are encrypted in the browser
        return jsonify(error=tr("A project encrypted in the browser cannot have a public link."), code="list_e2e_public"), 409
    if c.execute("SELECT life FROM lists WHERE id=?", (lid,)).fetchone()[0] == "budget":  # 2.72.0 (#1333): a budget stays private
        return err(tr("A budget is private: it cannot get a public link"), 409)
    if c.execute("SELECT life FROM lists WHERE id=?", (lid,)).fetchone()[0] == "health":  # 2.190.0 C (#2496): a health list stays private
        return err(tr("Health projects stay private: they never get a public link."), 409)
    b = body()
    old = c.execute("SELECT * FROM public_links WHERE list_id=?", (lid,)).fetchone()
    mode = b.get("mode", old["mode"] if old else "view")
    if mode not in ("view", "tick"):
        return err(tr("Invalid value: {0}", "mode"))
    notes = b.get("notes", bool(old["notes"]) if old else False)
    if not isinstance(notes, bool):
        return err(tr("Invalid value: {0}", "notes"))
    exp = old["expires_at"] if old else None
    if "expires" in b:
        v = b["expires"]
        if v in (None, ""):
            exp = None
        elif not valid_date(v) or v < local_now().date().isoformat():
            return err(tr("The expiry date must be today or later"))
        else:
            d = date.fromisoformat(v) + timedelta(days=1)  # valid through the end of that day (server time zone)
            exp = iso(datetime(d.year, d.month, d.day, tzinfo=TZ))
    show = old["cv_show"] if old else ""
    if "show" in b:  # 2.50.0 (#329): {progress, sections, due, assignees, tags, files, brand: bool, fields: [ids], tag: id|null}
        try:
            show = cv_clean(c, lid, b["show"], cv_show(old) if old else cv_show({"cv_show": ""}))
        except BadInput as x:
            return err(str(x))
    pw_hash, rev = (old["password_hash"], old["pw_rev"]) if old else (None, 0)
    if "password" in b:
        pw = b["password"]
        if pw is not None and not isinstance(pw, str):
            return err(tr("Invalid value: {0}", "password"))
        if pw and not 4 <= len(pw) <= 200:
            return err(tr("Password: at least {0} characters", 4))
        pw_hash, rev = (generate_password_hash(pw) if pw else None), rev + 1
    if old:
        c.execute("UPDATE public_links SET mode=?, notes=?, password_hash=?, pw_rev=?, expires_at=?, cv_show=? WHERE id=?",
                  (mode, 1 if notes else 0, pw_hash, rev, exp, show, old["id"]))
    else:
        _, h, sealed = pub_new_token(c, lid)
        c.execute("""INSERT INTO public_links(list_id,token_hash,token,mode,notes,password_hash,pw_rev,expires_at,created_by,created_at,cv_show)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (lid, h, sealed, mode, 1 if notes else 0, pw_hash, rev, exp, me(), iso(now_utc()), show))
        print("public link created for list", lid, "mode", mode, flush=True)
    c.commit()
    return jsonify(enabled=True, link=pub_public(c, c.execute("SELECT * FROM public_links WHERE list_id=?", (lid,)).fetchone()))


@app.post("/api/lists/<int:lid>/public-link/regenerate")
def pub_regen(lid):
    """New token: the old link stops working at once (unlock cookies too)."""
    c = db()
    need_pub_owner(c, lid)
    if not c.execute("SELECT 1 FROM public_links WHERE list_id=?", (lid,)).fetchone():
        raise Denied(404)
    _, h, sealed = pub_new_token(c, lid)
    c.execute("UPDATE public_links SET token_hash=?, token=?, pw_rev=pw_rev+1, views=0, last_used_at=NULL, created_at=? WHERE list_id=?",
              (h, sealed, iso(now_utc()), lid))
    c.commit()
    return jsonify(enabled=public_links_on(c), link=pub_public(c, c.execute("SELECT * FROM public_links WHERE list_id=?", (lid,)).fetchone()))


@app.delete("/api/lists/<int:lid>/public-link")
def pub_delete(lid):
    c = db()
    need_list(c, lid, owner=True)
    c.execute("DELETE FROM public_links WHERE list_id=?", (lid,))
    c.commit()
    return jsonify(enabled=public_links_on(c), link=None)


@app.post("/api/lists/<int:lid>/checklist")
def checklist_action(lid):
    """{action: uncheck_all | clear_done}: every done item back on the list, or all done items to the trash."""
    c = db()
    need_list(c, lid)
    a = body().get("action")
    if a not in ("uncheck_all", "clear_done"):
        return err(tr("Invalid value: {0}", "action"))
    ids = [r[0] for r in c.execute("SELECT id FROM tasks WHERE list_id=? AND status!=0 AND deleted_at IS NULL ORDER BY id", (lid,))]
    ts = iso(now_utc())
    for tid in ids:
        if a == "uncheck_all":
            c.execute("UPDATE tasks SET status=0, completed_at=NULL, completed_by=NULL, updated_at=? WHERE id=?", (ts, tid))
            log_act(c, tid, "reopen")
        elif c.execute("SELECT deleted_at FROM tasks WHERE id=?", (tid,)).fetchone()[0] is None:  # not gone with its parent
            trash_task(c, tid)
    bump(c)
    c.commit()
    return jsonify(ok=True, count=len(ids))
