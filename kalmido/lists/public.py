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
from ..core.db import body, bump, db, err, gsetting, inbox_default, iso, local_now, now_utc, parse_iso
from ..accounts.session import _accept_lang, _rate_blocked, _rate_fail, _token_hash, me, rate_ip
from ..accounts.login import auth_key, seal, unseal
from ..core.access import Denied, need_list
from ..tasks.validation import log_act, valid_date
from ..tasks.lifecycle import do_complete, trash_task
from ..collab.comments import task_event
from ..personal.timetrack import BadInput
from ..tasks.dependencies import completed_ids, unblock_events
from ..notify.alerts import _env_int, aa_count, aa_now
from ..api.v1 import hit_limit, PUB_ENV


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
    r = c.execute("""SELECT p.*, l.name AS l_name, l.is_inbox AS l_inbox, l.checklist AS l_checklist, l.owner_id AS l_owner
                     FROM public_links p JOIN lists l ON l.id=p.list_id JOIN users u ON u.id=l.owner_id
                     WHERE p.token_hash=? AND u.disabled=0""", (_token_hash(token),)).fetchone()
    if not r or (r["expires_at"] and parse_iso(r["expires_at"]) <= now_utc()):
        return None
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


# 2.14.0: the heron of the error pages (same drawing as in the app: lines in the text colour, the sun = the accent)
HERON_ERROR = ('<svg class="heron" viewBox="0 0 120 120" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" '
               'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle class="hr-sun" cx="77" cy="108" r="2.6"/><path d="M34 64L24 70"/>'
               '<path d="M34 64C46 55 68 57 80 67C72 75 54 77 42 72"/><path d="M72 63C73 53 79 46 85 48C88 49 89 53 87 57"/>'
               '<circle class="hr-eye" cx="84.5" cy="51.5" r="1.6"/><path d="M87.5 56L95 74"/><path d="M60 76V106"/>'
               '<path d="M60 88L52 84L57 79"/><path d="M30 108H71M83 108L100 104.5M48 113H66"/></svg>')


def pub_gone(lg=None):
    """The same answer for unknown, expired, revoked and switched-off links (no oracle)."""
    lg = lg or _accept_lang()
    return pub_html(tr("Link not available", lg=lg), f'<div class="msg">{HERON_ERROR}<h1>{html.escape(tr("Link not available", lg=lg))}</h1>'
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
    bad = [("pubbad:" + ip, PUB_BAD_LIMIT)]
    if _rate_blocked(bad):
        return None, pub_limited(_accept_lang())
    link = pub_find(c, token)
    if not link:
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
               N_("The public link of list {0} was opened {1} times within {2} minutes (from {3} addresses)."),
               [link["list_id"], n, PUB_BURST_S // 60, ips])
    c.execute("UPDATE public_links SET views=views+1, last_used_at=? WHERE id=?", (iso(now_utc()), link["id"]))
    c.commit()


def pub_tasks(c, link):
    cut = iso(now_utc() - timedelta(days=PUB_DONE_DAYS))
    return [dict(r) for r in c.execute(
        """SELECT id, parent_id, section_id, title, content, status, due, due_time, priority, completed_at, sort FROM tasks
           WHERE list_id=? AND deleted_at IS NULL AND (status=0 OR ? OR completed_at>=?) ORDER BY sort, id LIMIT ?""",
        (link["list_id"], 1 if link["l_checklist"] else 0, cut, PUB_MAX_TASKS))]


def pub_render(c, link, token, lg):
    e = html.escape
    tasks = pub_tasks(c, link)
    ids = {t["id"] for t in tasks}
    kids = {}
    for t in tasks:
        kids.setdefault(t["parent_id"] if t["parent_id"] in ids else None, []).append(t)
    tick, check = link["mode"] == "tick", bool(link["l_checklist"])
    today = local_now().date().isoformat()

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
        if t["due"] and not check and not done:
            cls = " over" if t["due"] < today else " today" if t["due"] == today else ""
            meta += f'<span class="due{cls}">{e(pub_day(t["due"], lg))}{" " + e(t["due_time"]) if t["due_time"] else ""}</span>'
        notes = ""
        if link["notes"] and (t["content"] or "").strip():
            txt = t["content"].strip()
            txt = txt[:PUB_NOTES_MAX] + ("…" if len(txt) > PUB_NOTES_MAX else "")
            notes = f'<details class="notes"><summary>{e(tr("Notes", lg=lg))}</summary><p>{e(txt)}</p></details>'
        sub = "".join(row(k, depth + 1) for k in kids.get(t["id"], []))
        pr = f" p{t['priority']}" if t["priority"] and not check else ""
        return (f'<li id="t{t["id"]}" class="t{" done" if done else ""}{pr}">{box}<div class="tt"><span class="ttl">{e(t["title"])}</span>'
                f'{meta}{notes}</div>{"<ul>" + sub + "</ul>" if sub else ""}</li>')
    top = kids.get(None, [])
    open_top, done_top = [t for t in top if t["status"] == 0], [t for t in top if t["status"] != 0]
    secs = [dict(r) for r in c.execute("SELECT id, name FROM sections WHERE list_id=? ORDER BY sort, id", (link["list_id"],))]
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
    name = tr("Inbox") if link["l_inbox"] and inbox_default(link["l_name"]) else link["l_name"]
    mode = tr("You can tick off items on this page.", lg=lg) if tick else tr("View only.", lg=lg)
    head = (f'<header><h1>{e(name)}</h1><p class="sub">{e(trn("{0} open item", "{0} open items", n_open, lg=lg))} · {e(mode)}</p></header>')
    return pub_html(f"{name} · {APP_NAME}", head + body_, lg)


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
    main = (f'<div class="msg"><h1>{e(tr("Password required", lg=lg))}</h1><p>{e(tr("This list is protected with a password.", lg=lg))}</p>'
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
    if to == "done" and st == 0:
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


# ---- managing the link (list dialog, owner only)
def pub_public(c, r):
    tok = unseal(c, f"publink:{r['list_id']}", r["token"])
    return {"url": PUBLIC_URL.rstrip("/") + PUB_PREFIX + tok, "mode": r["mode"], "notes": bool(r["notes"]),
            "has_password": bool(r["password_hash"]), "expires_at": r["expires_at"], "created_at": r["created_at"],
            "last_used_at": r["last_used_at"], "views": r["views"],
            "expired": bool(r["expires_at"] and parse_iso(r["expires_at"]) <= now_utc())}


def need_pub_owner(c, lid):
    need_list(c, lid, owner=True)
    if c.execute("SELECT is_inbox FROM lists WHERE id=?", (lid,)).fetchone()[0]:
        raise BadInput(tr("The inbox cannot be shared"))


def pub_new_token(c, lid):
    tok = secrets.token_urlsafe(24)
    return tok, _token_hash(tok), seal(c, f"publink:{lid}", tok)


@app.get("/api/lists/<int:lid>/public-link")
def pub_get(lid):
    c = db()
    need_list(c, lid, owner=True)
    r = c.execute("SELECT * FROM public_links WHERE list_id=?", (lid,)).fetchone()
    return jsonify(enabled=public_links_on(c), link=pub_public(c, r) if r else None)


@app.put("/api/lists/<int:lid>/public-link")
def pub_set(lid):
    """{mode: view|tick, notes: bool, password: str ('' = none; left out = keep), expires: YYYY-MM-DD | null} -> the link
    (created on the first call; the token stays the same on later changes)."""
    c = db()
    need_pub_owner(c, lid)
    if not public_links_on(c):
        return err(tr("Public links are turned off on this server"), 409)
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
    pw_hash, rev = (old["password_hash"], old["pw_rev"]) if old else (None, 0)
    if "password" in b:
        pw = b["password"]
        if pw is not None and not isinstance(pw, str):
            return err(tr("Invalid value: {0}", "password"))
        if pw and not 4 <= len(pw) <= 200:
            return err(tr("Password: at least {0} characters", 4))
        pw_hash, rev = (generate_password_hash(pw) if pw else None), rev + 1
    if old:
        c.execute("UPDATE public_links SET mode=?, notes=?, password_hash=?, pw_rev=?, expires_at=? WHERE id=?",
                  (mode, 1 if notes else 0, pw_hash, rev, exp, old["id"]))
    else:
        _, h, sealed = pub_new_token(c, lid)
        c.execute("""INSERT INTO public_links(list_id,token_hash,token,mode,notes,password_hash,pw_rev,expires_at,created_by,created_at)
                     VALUES(?,?,?,?,?,?,?,?,?,?)""", (lid, h, sealed, mode, 1 if notes else 0, pw_hash, rev, exp, me(), iso(now_utc())))
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
