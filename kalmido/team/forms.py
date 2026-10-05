"""Forms (#463 / #341, module "forms"): a link with a small form that creates a task in a list (requests, bug reports)."""
import html
import re
import secrets

from flask import g, jsonify, request

from ..core.config import app, APP_NAME, PUBLIC_URL
from ..core.i18n import lang, LANGS, tr
from ..core.db import body, bump, db, err, iso, now_utc
from ..accounts.session import _accept_lang, _token_hash, me, rate_ip
from ..accounts.login import seal, unseal
from ..core.access import Denied, MANAGE_ROLES, need_feat, need_list
from ..tasks.validation import log_act
from ..personal.timetrack import BadInput
from ..api.v1 import hit_limit
from ..lists.public import HERON_ERROR, pub_html, public_links_on


# ---------------------------------------------------------------- 2.23.0 (#463 / #341): forms -> tasks
# The owner / an admin of a list creates a form: a link /f/<token> (192 random bits; stored sealed so it can be copied
# again, looked up by its SHA-256) with a title, an intro and the fields subject, description, name and (optionally)
# e-mail. A sent form becomes a task in the list (in the chosen section), with the sender in the notes, attributed to
# "someone via the form" (or the signed-in person), and the usual events: News "added" for the list's people (bell),
# 'task_added' with source "form" and 'tidy' for its agents -- the agent sorts it (duplicates, tags, estimate).
# Access: org (default) = only signed-in people of the organisations of the list's owner (a colleague's request form);
# public = anyone with the link (needs the instance switch "Public links"). The page is server-rendered HTML without
# scripts (CSP of the public links), a honeypot field, limits per address (views, sends) and per form (sends per hour).
FORM_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{20,64}")
FORM_ACCESS = ("org", "public")
FORM_TITLE_MAX, FORM_INTRO_MAX = 120, 2000
FORM_SUBJECT_MAX, FORM_TEXT_MAX, FORM_NAME_MAX = 200, 8000, 120
FORM_VIEW_RATE, FORM_SEND_RATE, FORM_SEND_HOUR = 60, 6, 120   # per address / minute, per address / minute, per form / hour
FORMS_PER_LIST = 20


def forms_on(c, uid):
    from ..core.db import usettings
    return "forms" in (usettings(c, uid).get("features") or "").split(",")


def need_form_manager(c, lid):
    role = need_list(c, lid, write=False)
    if role not in MANAGE_ROLES:
        raise Denied(403, tr("Only the owner and list admins can manage forms"))
    if c.execute("SELECT is_inbox FROM lists WHERE id=?", (lid,)).fetchone()[0]:
        raise BadInput(tr("The inbox cannot have forms"))
    return role


def form_url(c, r):
    return PUBLIC_URL.rstrip("/") + "/f/" + unseal(c, f"form:{r['list_id']}", r["token"])


def form_public(c, r):
    return {"id": r["id"], "list_id": r["list_id"], "title": r["title"], "intro": r["intro"], "access": r["access"],
            "section_id": r["section_id"], "ask_email": bool(r["ask_email"]), "enabled": bool(r["enabled"]), "count": r["count"],
            "last_at": r["last_at"], "created_at": r["created_at"], "url": form_url(c, r),
            "live": bool(r["enabled"]) and (r["access"] != "public" or public_links_on(c))}


def clean_form(c, lid, b, new=False):
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    out = {}
    if "title" in b or new:
        t = re.sub(r"\s+", " ", str(b.get("title") or "")).strip()[:FORM_TITLE_MAX]
        if not t:
            raise BadInput(tr("Title missing"))
        out["title"] = t
    if "intro" in b:
        if not isinstance(b["intro"], str):
            raise BadInput(tr("Invalid value: {0}", "intro"))
        out["intro"] = b["intro"].strip()[:FORM_INTRO_MAX]
    if "access" in b:
        if b["access"] not in FORM_ACCESS:
            raise BadInput(tr("Invalid value: {0}", "access"))
        out["access"] = b["access"]
    if "section_id" in b:
        s = b["section_id"]
        if s is not None and (not isinstance(s, int) or isinstance(s, bool)
                              or not c.execute("SELECT 1 FROM sections WHERE id=? AND list_id=?", (s, lid)).fetchone()):
            raise BadInput(tr("Invalid value: {0}", "section_id"))
        out["section_id"] = s
    for k in ("ask_email", "enabled"):
        if k in b:
            if not isinstance(b[k], bool):
                raise BadInput(tr("Invalid value: {0}", k))
            out[k] = 1 if b[k] else 0
    return out


def _form_row(c, fid):
    r = c.execute("SELECT * FROM forms WHERE id=?", (fid,)).fetchone()
    if not r:
        raise Denied(404)
    need_form_manager(c, r["list_id"])
    return r


def _gate():
    from ..agents.core import is_agent
    if not is_agent(g.user):
        need_feat("forms")


@app.get("/api/lists/<int:lid>/forms")
def forms_list(lid):
    c = db()
    _gate()
    need_form_manager(c, lid)
    return jsonify(forms=[form_public(c, r) for r in c.execute("SELECT * FROM forms WHERE list_id=? ORDER BY id", (lid,))],
                   public_links=public_links_on(c))


@app.post("/api/lists/<int:lid>/forms")
def form_create(lid):
    """{title, intro?, access?: org | public, section_id?, ask_email?} -> 201 with its link."""
    c = db()
    _gate()
    need_form_manager(c, lid)
    f = clean_form(c, lid, body(), new=True)
    f.setdefault("access", "org")
    if f["access"] == "public" and not public_links_on(c):
        return err(tr("Public links are turned off on this server"), 409)
    if c.execute("SELECT COUNT(*) FROM forms WHERE list_id=?", (lid,)).fetchone()[0] >= FORMS_PER_LIST:
        return err(tr("At most {0} forms per list", FORMS_PER_LIST), 409)
    tok = secrets.token_urlsafe(24)
    f.update(list_id=lid, token=seal(c, f"form:{lid}", tok), token_hash=_token_hash(tok), created_by=me(), created_at=iso(now_utc()))
    fid = c.execute(f"INSERT INTO forms({','.join(f)}) VALUES({','.join('?' * len(f))})", list(f.values())).lastrowid
    bump(c)
    c.commit()
    return jsonify(form_public(c, c.execute("SELECT * FROM forms WHERE id=?", (fid,)).fetchone())), 201


@app.patch("/api/forms/<int:fid>")
def form_update(fid):
    """{title?, intro?, access?, section_id?, ask_email?, enabled?, regenerate?: true (a new link; the old one stops)}"""
    c = db()
    _gate()
    r = _form_row(c, fid)
    b = body()
    f = clean_form(c, r["list_id"], {k: v for k, v in b.items() if k != "regenerate"})
    if f.get("access") == "public" and not public_links_on(c):
        return err(tr("Public links are turned off on this server"), 409)
    if b.get("regenerate") is True:
        tok = secrets.token_urlsafe(24)
        f.update(token=seal(c, f"form:{r['list_id']}", tok), token_hash=_token_hash(tok))
    if f:
        c.execute(f"UPDATE forms SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), fid])
    bump(c)
    c.commit()
    return jsonify(form_public(c, c.execute("SELECT * FROM forms WHERE id=?", (fid,)).fetchone()))


@app.delete("/api/forms/<int:fid>")
def form_delete(fid):
    c = db()
    _gate()
    _form_row(c, fid)
    c.execute("DELETE FROM forms WHERE id=?", (fid,))
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.post("/api/qr")
def qr_svg():
    """{text}: a QR code (SVG data URI) of a link, for the forms' and sign-in links (signed in; at most 2000 characters)."""
    import segno
    t = body().get("text")
    if not isinstance(t, str) or not 0 < len(t) <= 2000:
        return err(tr("Invalid value: {0}", "text"))
    return jsonify(qr=segno.make(t, error="m").svg_data_uri(scale=6, border=2, dark="#000", light="#fff"))


# ---- the page /f/<token>
def _find(c, token):
    if not FORM_TOKEN_RE.fullmatch(token or ""):
        return None
    return c.execute("""SELECT f.*, l.owner_id AS l_owner, l.name AS l_name FROM forms f JOIN lists l ON l.id=f.list_id
                        JOIN users u ON u.id=l.owner_id WHERE f.token_hash=? AND f.enabled=1 AND u.disabled=0 AND l.archived=0""",
                     (_token_hash(token),)).fetchone()


def _lang(c, f):
    if g.user:
        return lang(c, g.user["id"])
    for part in (request.headers.get("Accept-Language") or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in LANGS:
            return code
    return lang(c, f["l_owner"])


def _gone(lg=None):
    lg = lg or _accept_lang()
    return pub_html(tr("Form not available", lg=lg), f'<div class="msg">{HERON_ERROR}<h1>{html.escape(tr("Form not available", lg=lg))}</h1>'
                    f'<p>{html.escape(tr("This form does not exist or is no longer open.", lg=lg))}</p></div>', lg, 404, foot=False)


def _msg(title, text, lg, code=200, link=None):
    e = html.escape
    return pub_html(title, f'<div class="msg"><h1>{e(title)}</h1><p>{e(text)}</p>'
                    + (f'<a class="btn" href="{e(link[0])}">{e(link[1])}</a>' if link else "") + '</div>', lg, code, foot=False)


def _may_use(c, f):
    """None if the current visitor may use form f, else a response."""
    if f["access"] == "public":
        return None if public_links_on(c) else _gone()
    lg = _lang(c, f)
    if not g.user:
        return _msg(tr("Please log in", lg=lg), tr("This form is for the people of {0}. Log in and open the link again.", APP_NAME, lg=lg),
                    lg, 401, ("/", tr("To the login", lg=lg)))
    from ..accounts.orgs import instance_mode, may_see, user_orgs
    if g.user["kid"]:
        return _gone(lg)
    if instance_mode(c) == "shared":  # 2.23.0 (#799): a shared instance: the owner's contacts
        if not g.user["is_admin"] and not may_see(c, f["l_owner"], g.user["id"]):
            return _gone(lg)
        return None
    owner_orgs, mine = set(user_orgs(c, f["l_owner"])), set(user_orgs(c, g.user["id"]))
    if owner_orgs and not owner_orgs & mine and not g.user["is_admin"]:
        return _gone(lg)
    return None


def _page(c, f, token, lg, vals=None, error=""):
    e = html.escape
    v = vals or {}
    t = lambda s, *a: tr(s, *a, lg=lg)  # noqa: E731
    me_row = g.user
    who = ""
    if me_row:
        who = f'<p class="sub">{e(t("Sent as {0}", me_row["display_name"] or me_row["username"]))}</p>'
    fields = [f'<label for="ff-subject">{e(t("Subject"))}</label><input id="ff-subject" name="subject" required maxlength="{FORM_SUBJECT_MAX}" value="{e(v.get("subject", ""))}">',
              f'<label for="ff-text">{e(t("Description"))}</label><textarea id="ff-text" name="text" rows="6" maxlength="{FORM_TEXT_MAX}">{e(v.get("text", ""))}</textarea>']
    if not me_row:
        fields.append(f'<label for="ff-name">{e(t("Your name"))}</label><input id="ff-name" name="name" autocomplete="name" maxlength="{FORM_NAME_MAX}" value="{e(v.get("name", ""))}">')
        if f["ask_email"]:
            fields.append(f'<label for="ff-email">{e(t("Your e-mail (for questions)"))}</label><input id="ff-email" name="email" type="email" autocomplete="email" maxlength="200" value="{e(v.get("email", ""))}">')
    hp = '<div class="hp" aria-hidden="true"><label for="ff-web">Website</label><input id="ff-web" name="website" tabindex="-1" autocomplete="off"></div>'
    main = (f'<header><h1>{e(f["title"])}</h1>{who}</header>'
            + (f'<div class="intro">{"".join(f"<p>{e(p)}</p>" for p in f["intro"].split(chr(10)) if p.strip())}</div>' if f["intro"] else "")
            + (f'<p class="err" role="alert">{e(error)}</p>' if error else "")
            + f'<form method="post" action="/f/{e(token)}" class="fform">{"".join(fields)}{hp}<button type="submit">{e(t("Send"))}</button></form>')
    return pub_html(f["title"], main, lg, 400 if error else 200, foot=True)


@app.get("/f/<token>")
def form_page(token):
    c = db()
    if hit_limit("formv:" + rate_ip(), FORM_VIEW_RATE):
        return _msg(tr("Too many requests"), tr("Please wait a minute and try again."), _accept_lang(), 429)
    f = _find(c, token)
    if not f:
        return _gone()
    bad = _may_use(c, f)
    if bad:
        return bad
    return _page(c, f, token, _lang(c, f))


@app.post("/f/<token>")
def form_send(token):
    from ..tasks.dependencies import newtask_events
    from ..agents.core import agent_added_events, agent_tidy_events
    c = db()
    f = _find(c, token)
    if not f:
        return _gone()
    lg = _lang(c, f)
    if request.headers.get("Sec-Fetch-Site", "") == "cross-site":
        return _msg(tr("Not allowed", lg=lg), tr("Please send the form from its own page.", lg=lg), lg, 403)
    bad = _may_use(c, f)
    if bad:
        return bad
    if hit_limit("forms:" + rate_ip(), FORM_SEND_RATE) or hit_limit(f"formh:{f['id']}", FORM_SEND_HOUR, 3600):
        return _msg(tr("Too many requests", lg=lg), tr("Please wait a minute and try again.", lg=lg), lg, 429)
    fv = request.form
    vals = {k: (fv.get(k) or "").strip() for k in ("subject", "text", "name", "email")}
    if fv.get("website"):  # the honeypot: a bot filled the hidden field -> pretend it worked
        return _msg(tr("Thank you!", lg=lg), tr("Your request has been sent.", lg=lg), lg)
    subject = re.sub(r"\s+", " ", vals["subject"])[:FORM_SUBJECT_MAX]
    if not subject:
        return _page(c, f, token, lg, vals, tr("Please enter a subject.", lg=lg))
    email = vals["email"][:200]
    if email and not re.fullmatch(r"[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+", email):
        return _page(c, f, token, lg, vals, tr("Please check the e-mail address.", lg=lg))
    name = re.sub(r"\s+", " ", vals["name"])[:FORM_NAME_MAX]
    olg = lang(c, f["l_owner"])
    sender = (g.user["display_name"] or g.user["username"]) if g.user else (name or tr("someone", lg=olg))
    meta = tr("Sent with the form “{0}” by {1}", f["title"], sender, lg=olg) + (f" <{email}>" if email and not g.user else "")
    content = (vals["text"][:FORM_TEXT_MAX] + "\n\n" if vals["text"] else "") + "— " + meta
    lid = f["list_id"]
    srt = c.execute("SELECT COALESCE(MIN(sort),0)-1 FROM tasks WHERE list_id=? AND parent_id IS NULL", (lid,)).fetchone()[0]
    ts = iso(now_utc())
    sec = f["section_id"] if f["section_id"] and c.execute("SELECT 1 FROM sections WHERE id=? AND list_id=?", (f["section_id"], lid)).fetchone() else None
    uid = g.user["id"] if g.user else None
    tid = c.execute("""INSERT INTO tasks(list_id,section_id,title,content,sort,created_at,updated_at,created_by) VALUES(?,?,?,?,?,?,?,?)""",
                    (lid, sec, subject, content, srt, ts, ts, uid)).lastrowid
    c.execute("UPDATE forms SET count=count+1, last_at=? WHERE id=?", (ts, f["id"]))
    if not g.user:
        from ..lists.public import PUB_ACTOR
        g.user, g.auth_via = PUB_ACTOR, "public"  # "someone via the form" in the history, News and pushes
    try:
        log_act(c, tid, "created", {"form": f["title"]})
        newtask_events(c, tid)
        agent_tidy_events(c, tid)
        agent_added_events(c, tid, source="form")
    finally:
        if not uid:
            g.user = None
    bump(c)
    c.commit()
    return _msg(tr("Thank you!", lg=lg), tr("Your request has been sent.", lg=lg), lg, 200,
                (f"/f/{token}", tr("Send another one", lg=lg)))
