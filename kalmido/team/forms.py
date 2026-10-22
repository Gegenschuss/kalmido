"""Forms (#463 / #341, module "forms"): a link with a small form that creates a task in a list (requests, bug reports)."""
import hashlib
import hmac
import html
import os
import re
import secrets
import threading
import time

from flask import g, jsonify, request

from ..core.config import app, APP_NAME, PUBLIC_URL
from ..core.pg import insert_id, system_ctx
from ..core.i18n import lang, LANGS, N_, tr
from ..core.db import body, bump, db, err, iso, now_utc, usettings
from ..accounts.session import _accept_lang, _token_hash, me, rate_ip
from ..accounts.login import auth_key, seal, unseal
from ..core.access import acx_anon_bind, Denied, MANAGE_ROLES, need_feat, need_list
from ..tasks.validation import log_act
from ..core.errors import BadInput
from ..api.common import hit_budget, hit_limit
from ..lists.public import BOT_ERROR, pub_html, public_links_on


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
# 2.63.0 (#1513): a public report form. forms.ttype = the type the task gets ('bug' = bug report), forms.files = one file
# (FRM_FILE_MAX, stored like the mail-in files: sealed, counted against the list owner's storage, an executable ending gets
# ".txt"), forms.portal = a visitor gets a status link (team/portal.py pt_create) on the thank-you page and in ONE mail to the
# address just typed (needs the e-mail field). Spam without an outside service: the honeypot and limits stay; a signed stamp
# (server key, form id, time) in every visitor page -- sent sooner than FRM_MIN_S after loading or later than FRM_MAX_S =
# "please send it again" with a fresh stamp; per address FRM_EMAIL_HOUR reports per form and hour, FRM_MAIL_HOUR
# confirmations per address and hour (plus the server's mails per address and day); more than FRM_LINKS_MAX links = refused.
FRM_FILE_MAX = 10 * 1024 * 1024
FRM_MIN_S, FRM_MAX_S = 3, 24 * 3600
FRM_EMAIL_HOUR, FRM_MAIL_HOUR, FRM_LINKS_MAX = 5, 3, 5
FRM_MAIL_DAY = 50  # 2.81.0 (#1866): confirmation mails per form and day
FRM_TTYPES = ("", "bug", "feature", "task")
# 2.86.0 (N24): the file bytes anonymous visitors may send through ONE form per hour (20 full files); more = the report
# is refused with a "try later" page (a link in the open cannot fill the disk); signed-in senders count on their quota.
try:  # 2.86.0 (review): a typo in the variable must not stop the server
    FRM_BYTES_HOUR = max(1, int(os.environ.get("KALMIDO_FORM_FILES_MB_HOUR") or 200)) * 1024 * 1024
except ValueError:
    FRM_BYTES_HOUR = 200 * 1024 * 1024
_FRM_BYTES, _FRM_BYTES_LOCK = {}, threading.Lock()


def h6d_form_bytes(form_id, n):
    """2.86.0 (N24): True (= refuse) when n more bytes would exceed FRM_BYTES_HOUR of the form in the last hour; else
    the bytes are counted."""
    now = time.time()
    with _FRM_BYTES_LOCK:
        arr = [(t, b) for t, b in _FRM_BYTES.get(form_id, ()) if now - t < 3600]
        if sum(b for _t, b in arr) + n > FRM_BYTES_HOUR:
            _FRM_BYTES[form_id] = arr
            return True
        arr.append((now, n))
        _FRM_BYTES[form_id] = arr
    return False


def forms_on(c, uid):
    return "forms" in (usettings(c, uid).get("features") or "").split(",")


def need_form_manager(c, lid):
    role = need_list(c, lid, write=False)
    if role not in MANAGE_ROLES:
        raise Denied(403, tr("Only the owner and project admins can manage forms"))
    if c.execute("SELECT is_inbox FROM lists WHERE id=?", (lid,)).fetchone()[0]:
        raise BadInput(tr("The basket cannot have forms"))
    return role


def form_url(c, r):
    return PUBLIC_URL.rstrip("/") + "/f/" + unseal(c, f"form:{r['list_id']}", r["token"])


def form_public(c, r):
    from .formq import fq_public
    return {"id": r["id"], "list_id": r["list_id"], "title": r["title"], "intro": r["intro"], "access": r["access"],
            "section_id": r["section_id"], "ask_email": bool(r["ask_email"]), "enabled": bool(r["enabled"]), "count": r["count"],
            "last_at": r["last_at"], "created_at": r["created_at"], "url": form_url(c, r),
            "ttype": r["ttype"] or "", "files": bool(r["files"]), "portal": bool(r["portal"]),  # 2.63.0 (#1513)
            "live": bool(r["enabled"]) and (r["access"] != "public" or public_links_on(c)), **fq_public(r)}  # 2.98.0 B (#1954)


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
    if "ttype" in b:  # 2.63.0 (#1513): the type of the sent report ('' = none)
        if b["ttype"] not in FRM_TTYPES:
            raise BadInput(tr("Invalid value: {0}", "ttype"))
        out["ttype"] = b["ttype"]
    for k in ("ask_email", "enabled", "files", "portal"):
        if k in b:
            if not isinstance(b[k], bool):
                raise BadInput(tr("Invalid value: {0}", k))
            out[k] = 1 if b[k] else 0
    from .formq import fq_clean_form
    fq_clean_form(b, out)  # 2.98.0 B (#1954): the own questions, steps, client matching
    return out


def _form_row(c, fid):
    r = c.execute("SELECT * FROM forms WHERE id=?", (fid,)).fetchone()
    if not r:
        raise Denied(404)
    need_form_manager(c, r["list_id"])
    return r


def _public_approval(c, lid, title):
    """2.148.1 D (#2495): a public form takes input from anyone in the owner's name: an agent opening one (make a form
    public, turn a public one on, give it a new link) waits for a person's approval (api/scopes.py need_approval, 202)."""
    from ..api.scopes import need_approval
    need_approval(c, N_("Open the public form “{0}”"), ((title or "")[:80],), list_id=lid)


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
    if f["access"] == "public":
        _public_approval(c, lid, f.get("title"))
    if f.get("portal"):
        f["ask_email"] = 1  # 2.63.0 (#1513): the status link goes to the reporter's address
    if f["access"] == "public" and not public_links_on(c):
        return err(tr("Public links are turned off on this server"), 409)
    if c.execute("SELECT COUNT(*) FROM forms WHERE list_id=?", (lid,)).fetchone()[0] >= FORMS_PER_LIST:
        return err(tr("At most {0} forms per project", FORMS_PER_LIST), 409)
    tok = secrets.token_urlsafe(24)
    f.update(list_id=lid, token=seal(c, f"form:{lid}", tok), token_hash=_token_hash(tok), created_by=me(), created_at=iso(now_utc()))
    fid = insert_id(c, f"INSERT INTO forms({','.join(f)}) VALUES({','.join('?' * len(f))})", list(f.values()))
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
    if (f.get("access") == "public" and r["access"] != "public") or (r["access"] == "public" and (f.get("enabled") or b.get("regenerate") is True)):
        _public_approval(c, r["list_id"], f.get("title") or r["title"])
    if f.get("access") == "public" and not public_links_on(c):
        return err(tr("Public links are turned off on this server"), 409)
    if f.get("portal", r["portal"]):
        f["ask_email"] = 1  # 2.63.0 (#1513): a status link needs the address
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
    with system_ctx(c):  # 2.37.0 (#1150): resolve the token (one row) across organisations ...
        r = c.execute("""SELECT f.*, l.owner_id AS l_owner, l.name AS l_name, l.org_id AS l_org FROM forms f JOIN lists l ON l.id=f.list_id
                         JOIN users u ON u.id=l.owner_id WHERE f.token_hash=? AND f.enabled=1 AND u.disabled=0 AND l.archived=0
                         AND l.deleted_at IS NULL""",  # 2.148.1 D (#2495): a list in the trash takes nothing in
                      (_token_hash(token),)).fetchone()
    if r is not None and g.user and r["access"] == "public" and r["l_org"]:
        from ..accounts.orgroles import user_orgs_full
        if r["l_org"] not in user_orgs_full(c, g.user["id"], write=True):  # 2.143.0 A (#2151, review): limited roles = visitor
            # 2.37.0 (review K2-2): a signed-in person of another organisation uses a public form like a visitor (the
            # context hook prefers g.user, whose organisations do not include the list's)
            g.user = None
    if r is not None and not g.user:
        acx_anon_bind(c, r["l_org"])  # ... a visitor without an account works inside exactly the list's organisation
    return r


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
    return pub_html(tr("Form not available", lg=lg), f'<div class="msg">{BOT_ERROR}<h1>{html.escape(tr("Form not available", lg=lg))}</h1>'
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
    from ..accounts.orgroles import user_orgs_full
    # 2.143.0 A (#2151, review): an organisation's internal form is for its writing roles (not guest / read-only / accounting)
    owner_orgs, mine = set(user_orgs(c, f["l_owner"])), set(user_orgs_full(c, g.user["id"], write=True))
    # 2.30.0 (#1036): the form of an organisation's list is for the people of THAT organisation (not of every organisation of
    # its owner); in the mode workspaces instance admins are no exception (as everywhere there)
    if f["l_org"]:
        owner_orgs = {f["l_org"]}
    if not owner_orgs:  # 2.148.1 D (#2495): an internal form of someone without an organisation is private: who sees the list
        from ..core.access import list_role
        return None if g.user["id"] == f["l_owner"] or list_role(c, f["list_id"], g.user["id"]) else _gone(lg)
    if owner_orgs and not owner_orgs & mine and not (g.user["is_admin"] and instance_mode(c) != "workspaces"):
        return _gone(lg)
    return None


def frm_stamp(c, fid, t=None, n=None):
    """2.63.0 (#1513): the signed time a visitor's page was made (form id + seconds, server key). 2.81.0 (#1866): plus a
    random part n, so two pages of the same second differ (a stamp counts once, r81c_stamp_once)."""
    t = int(time.time()) if t is None else t
    n = secrets.token_hex(6) if n is None else n
    sig = hmac.new(auth_key(c), f"kalmido-form-stamp|{fid}|{t}|{n}".encode(), hashlib.sha256).hexdigest()[:32]
    return f"{t}.{n}.{sig}"


def frm_stamp_age(c, fid, v):
    """Seconds since the stamp v was made for form fid; None when it is missing or not ours."""
    t, _, rest = (v or "").partition(".")
    n, _, sig = rest.partition(".")
    if not t.isdigit() or len(t) > 12 or not re.fullmatch(r"[0-9a-f]{12}", n) or not hmac.compare_digest(frm_stamp(c, fid, int(t), n), f"{t}.{n}.{sig}"):
        return None
    return time.time() - int(t)


def r81c_stamp_once(c, v):
    """2.81.0 (#1866): a stamp counts once: the first send marks it used until it has expired (mail_counts keeps the
    marks, the day = the stamp's last valid day, mail_budget's daily sweep drops them after). False = used before."""
    t, _, sig = (v or "").partition(".")  # sig = the random part + the signature, unique per page
    last = time.strftime("%Y-%m-%d", time.gmtime(int(t) + FRM_MAX_S))
    c.execute("DELETE FROM mail_counts WHERE k LIKE 'fs:%' AND day<?", (now_utc().strftime("%Y-%m-%d"),))  # pg-ok: the app writes the prefix itself
    return c.execute("INSERT INTO mail_counts(k,day,n) VALUES(?,?,1) ON CONFLICT(k) DO NOTHING", (f"fs:{sig}", last)).rowcount == 1


def _page(c, f, token, lg, vals=None, error="", qvals=None, cur=None):
    from .formq import fq_fields, fq_file_count, fq_list
    e = html.escape
    v = vals or {}
    qs = fq_list(f)  # 2.98.0 B (#1954): own questions instead of subject and description
    t = lambda s, *a: tr(s, *a, lg=lg)  # noqa: E731
    me_row = g.user
    who = ""
    if me_row:
        who = f'<p class="sub">{e(tr("Sent as {0}", me_row["display_name"] or me_row["username"], lg=lg))}</p>'
    fields = [] if qs else [f'<label for="ff-subject">{e(t("Subject"))}</label><input id="ff-subject" name="subject" required maxlength="{FORM_SUBJECT_MAX}" value="{e(v.get("subject", ""))}">',
                            f'<label for="ff-text">{e(t("Description"))}</label><textarea id="ff-text" name="text" rows="6" maxlength="{FORM_TEXT_MAX}">{e(v.get("text", ""))}</textarea>']
    if not me_row:
        fields.append(f'<label for="ff-name">{e(t("Your name"))}</label><input id="ff-name" name="name" autocomplete="name" maxlength="{FORM_NAME_MAX}" value="{e(v.get("name", ""))}">')
        if f["portal"]:  # 2.63.0 (#1513): the status link goes to this address
            fields.append(f'<label for="ff-email">{e(tr("Your e-mail (for the status link)", lg=lg))}</label><input id="ff-email" name="email" type="email" required autocomplete="email" maxlength="200" value="{e(v.get("email", ""))}">')
        elif f["ask_email"]:
            fields.append(f'<label for="ff-email">{e(t("Your e-mail (for questions)"))}</label><input id="ff-email" name="email" type="email" autocomplete="email" maxlength="200" value="{e(v.get("email", ""))}">')
        fields.append(f'<input type="hidden" name="stamp" value="{e(frm_stamp(c, f["id"]))}">')
    from .formq import fq_ck_in
    ck = fq_ck_in()  # 2.102.0 C (#2201): the client link goes along unchecked (the same page for a right or a wrong one)
    if ck:
        fields.append(f'<input type="hidden" name="ck" value="{e(ck)}">')
    if f["files"]:  # 2.63.0 (#1513): one file (a screenshot, a log)
        fields.append(f'<label for="ff-file">{e(tr("Attachment (optional, at most {0} MB)", FRM_FILE_MAX // (1024 * 1024), lg=lg))}</label><input id="ff-file" name="file" type="file">')
    hp = '<div class="hp" aria-hidden="true"><label for="ff-web">Website</label><input id="ff-web" name="website" tabindex="-1" autocomplete="off"></div>'
    enc = ' enctype="multipart/form-data"' if f["files"] or fq_file_count(qs) else ""  # 2.63.0 (#1513): the file field
    step = bool(qs) and bool(f["one_per_step"])
    if qs:  # 2.98.0 B (#1954): the questions (on one page or one per step), then name / e-mail / file and the button
        inner = fq_fields(qs, lg, qvals or {}, step, "".join(fields) + hp + f'<button type="submit">{e(t("Send"))}</button>', cur)
        cls = "fform fq-form" + (" fq-steps" if step else "")
        main = (f'<header><h1>{e(f["title"])}</h1>{who}</header>'
                + (f'<div class="intro">{"".join(f"<p>{e(p)}</p>" for p in f["intro"].split(chr(10)) if p.strip())}</div>' if f["intro"] else "")
                + (f'<p class="err" role="alert">{e(error)}</p>' if error else "")
                + f'<form method="post" action="/f/{e(token)}" class="{cls}"{enc}{" novalidate" if step else ""}>{inner}</form>')
        return pub_html(f["title"], main, lg, 400 if error else 200, foot=True)
    main = (f'<header><h1>{e(f["title"])}</h1>{who}</header>'
            + (f'<div class="intro">{"".join(f"<p>{e(p)}</p>" for p in f["intro"].split(chr(10)) if p.strip())}</div>' if f["intro"] else "")
            + (f'<p class="err" role="alert">{e(error)}</p>' if error else "")
            + f'<form method="post" action="/f/{e(token)}" class="fform"{enc}>{"".join(fields)}{hp}<button type="submit">{e(t("Send"))}</button></form>')
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
    from .formq import FqRefused, fq_ck_client, fq_ck_in, fq_client, fq_entry_save, fq_file_count, fq_list, fq_markdown, fq_read, fq_text_of, fq_vals
    qs = fq_list(f)  # 2.98.0 B (#1954): a questionnaire (own questions instead of subject / description)
    if hit_limit("forms:" + rate_ip(), FORM_SEND_RATE) or hit_budget(f"formh:{f['id']}", FORM_SEND_HOUR, rate_ip()):  # 2.126.0 C (#1979 I1)
        return _msg(tr("Too many requests", lg=lg), tr("Please wait a minute and try again.", lg=lg), lg, 429)
    # 2.86.0 (N22): a body longer than one file + the text fields is refused before it is read
    if (request.content_length or 0) > (FRM_FILE_MAX if f["files"] else 0) + fq_file_count(qs) * FRM_FILE_MAX + 256 * 1024:
        return _msg(tr("File too large", lg=lg), tr("The file is too large (at most {0} MB).", FRM_FILE_MAX // (1024 * 1024), lg=lg), lg, 413)
    fv = request.form
    vals = {k: (fv.get(k) or "").strip() for k in ("subject", "text", "name", "email")}
    qv = fq_vals(fv) if qs else None
    again = lambda msg, cur="": _page(c, f, token, lg, vals, msg, qv, cur)  # noqa: E731  (the page again, typed values kept; cur "" = the last step)
    if fv.get("website"):  # the honeypot: a bot filled the hidden field -> pretend it worked
        return _msg(tr("Thank you!", lg=lg), tr("Your request has been sent.", lg=lg), lg)
    anon = not g.user
    if anon:  # 2.63.0 (#1513): the page's signed stamp: not sooner than FRM_MIN_S, not later than FRM_MAX_S after loading
        age = frm_stamp_age(c, f["id"], fv.get("stamp"))
        if age is None or not FRM_MIN_S <= age <= FRM_MAX_S or not r81c_stamp_once(c, fv.get("stamp")):
            return again(tr("Please send the form once more: it was sent very quickly or the page was open for a long time.", lg=lg))
    subject = re.sub(r"\s+", " ", vals["subject"])[:FORM_SUBJECT_MAX]
    if not subject and not qs:
        return again(tr("Please enter a subject.", lg=lg))
    email = vals["email"][:200]
    if email and (not re.fullmatch(r"[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+", email) or re.search(r"[,;\"'()\[\]\\]", email)):
        return again(tr("Please check the e-mail address.", lg=lg))  # 2.63.0 (#1513): one address only (it may get a mail)
    portal = bool(f["portal"]) and anon
    if portal and not email:
        return again(tr("Please enter your e-mail address: the link to the status of your report goes there.", lg=lg))
    answers, q_ups = {}, []
    if qs:  # 2.98.0 B (#1954): required answers, values, file types and sizes checked here (the page may be in steps)
        try:
            answers, q_ups = fq_read(qs, fv, request.files, lg, anon, f["id"])
        except FqRefused as x:
            return again(str(x), x.qid)
    if len(re.findall(r"https?://", subject + " " + vals["text"] + " " + fq_text_of(qs, answers), re.I)) > FRM_LINKS_MAX:
        return again(tr("Please include at most {0} links.", FRM_LINKS_MAX, lg=lg))
    upload = None
    if f["files"]:  # 2.63.0 (#1513): one file, hard size limit, a clean name, the type from the name (never the sender's)
        from ..tasks.attachments import safe_name, unexec_name
        fs = request.files.get("file")
        if fs and fs.filename:
            data = fs.read(FRM_FILE_MAX + 1)
            if len(data) > FRM_FILE_MAX:
                return again(tr("The file is too large (at most {0} MB).", FRM_FILE_MAX // (1024 * 1024), lg=lg))
            if data and anon and h6d_form_bytes(f["id"], len(data)):
                return _msg(tr("Too many requests", lg=lg), tr("This form takes no more files right now. Please try again later or send your report without a file.", lg=lg), lg, 429)
            if data:
                upload = (unexec_name(safe_name(fs.filename)), "", data)
    ehash = ""
    if anon and email:
        from .portal import pt_email_hash
        ehash = pt_email_hash(c, email)
        if ehash and hit_limit(f"frme:{f['id']}:{ehash}", FRM_EMAIL_HOUR, 3600):
            return _msg(tr("Too many requests", lg=lg), tr("You have sent several reports in a short time. Please try again later.", lg=lg), lg, 429)
    name = re.sub(r"\s+", " ", vals["name"])[:FORM_NAME_MAX]
    olg = lang(c, f["l_owner"])
    sender = (g.user["display_name"] or g.user["username"]) if g.user else (name or tr("someone", lg=olg))
    # 2.148.1 G (#2496): the sender's name and address as plain Markdown text (like the answers)
    from .formq import fq_md
    shown = (f" <{email}>" if re.fullmatch(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+", email) else " · " + fq_md(email)) if email and not g.user else ""
    meta = tr("Sent with the form “{0}” by {1}", f["title"], fq_md(sender), lg=olg) + shown
    if portal:
        meta += " · " + tr("the sender has a status link", lg=olg)
    if qs:  # 2.98.0 B (#1954): the title names the form and the sender, the answers as Markdown
        subject = re.sub(r"\s+", " ", f"{f['title']} – {sender if g.user or name else (email or sender)}")[:FORM_SUBJECT_MAX]
        content = fq_markdown(qs, answers, olg) + "\n\n— " + meta
    else:
        content = (vals["text"][:FORM_TEXT_MAX] + "\n\n" if vals["text"] else "") + "— " + meta
    lid = f["list_id"]
    from ..collab.liste2eguard import LE2B_OFF_MSG, le2b_list_locked
    if le2b_list_locked(c, lid):  # 2.64.1 B (#1817): a form cannot write plain texts into a list with the lock
        return again(tr(LE2B_OFF_MSG, lg=lg))
    # 2.102.0 C (#2201): a valid client link first (also without the e-mail matching), else as before
    cid, cnote = fq_ck_client(c, f, fq_ck_in())
    if not cid:
        cid, cnote = fq_client(c, f, email, name, olg) if f["client_match"] else (None, "")  # 2.98.0 B (#1954): only the list's space
    if cnote:
        content += "\n\n" + cnote
    srt = c.execute("SELECT COALESCE(MIN(sort),0)-1 FROM tasks WHERE list_id=? AND parent_id IS NULL", (lid,)).fetchone()[0]
    ts = iso(now_utc())
    sec = f["section_id"] if f["section_id"] and c.execute("SELECT 1 FROM sections WHERE id=? AND list_id=?", (f["section_id"], lid)).fetchone() else None
    uid = g.user["id"] if g.user else None
    tid = insert_id(c, """INSERT INTO tasks(list_id,section_id,title,content,sort,created_at,updated_at,created_by,ttype) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (lid, sec, subject, content, srt, ts, ts, uid, f["ttype"] or ""))
    c.execute("UPDATE forms SET count=count+1, last_at=? WHERE id=?", (ts, f["id"]))
    if upload:
        from ..core.pages import save_attachment_bytes
        save_attachment_bytes(c, tid, *upload, owner=None if uid else f["l_owner"])
    if qs:  # 2.98.0 B (#1954): the answers for the evaluation, the files as attachments (sealed, scanned, counted)
        from ..core.pages import save_attachment_bytes
        fq_entry_save(c, tid, f, cid, sender if g.user or name else "", email if not g.user else "", answers)
        for up in q_ups:
            save_attachment_bytes(c, tid, *up, owner=None if uid else f["l_owner"])
    status_url = ""
    if portal:  # 2.63.0 (#1513): the report becomes a ticket with a status link (team/portal.py)
        from .portal import pt_create, pt_status_url
        status_url = pt_status_url(pt_create(c, tid, {"id": lid, "org_id": f["l_org"], "owner_id": f["l_owner"]}, f["id"], name, email, client_id=cid)[1])
    if not g.user:
        from ..lists.public import PUB_ACTOR
        g.user, g.auth_via = PUB_ACTOR, "public"  # "someone via the form" in the history, News and pushes
    try:
        log_act(c, tid, "created", {"form": f["title"], **({"portal": 1} if portal else {})})
        newtask_events(c, tid)
        agent_tidy_events(c, tid)
        agent_added_events(c, tid, source="form", info={**({"portal": True} if portal else {}), **({"ttype": f["ttype"]} if f["ttype"] else {})})
    finally:
        if not uid:
            g.user = None
    mailed = portal and frm_mail_ok(c, ehash, email, f["id"])
    bump(c)
    c.commit()
    if mailed:
        threading.Thread(target=frm_mail, args=(email, *frm_mail_text(f["title"], subject, status_url, lg)), daemon=True).start()
    if status_url:
        return frm_thanks(token, status_url, email if mailed else "", lg)
    ck = fq_ck_in()  # 2.102.0 C (#2201): "Send another one" keeps the client link
    return _msg(tr("Thank you!", lg=lg), tr("Your request has been sent.", lg=lg), lg, 200,
                (f"/f/{token}" + (f"?k={ck}" if ck else ""), tr("Send another one", lg=lg)))


# ---- 2.63.0 (#1513): the thank-you page with the status link and the one confirmation mail
def frm_thanks(token, url, mailed_to, lg):
    e = html.escape
    keep = tr("We have also sent the link to {0}.", mailed_to, lg=lg) if mailed_to else tr("Please keep this link: it is the way back to your report.", lg=lg)
    return pub_html(tr("Thank you!", lg=lg), f'<div class="msg"><h1>{e(tr("Thank you!", lg=lg))}</h1><p>{e(tr("Your report has been sent.", lg=lg))}</p>'
                    f'<p>{e(tr("With this link you can see the status of your report and our answers at any time:", lg=lg))}</p>'
                    f'<input class="frm-link" readonly value="{e(url)}" aria-label="{e(tr("Status link", lg=lg))}">'
                    f'<p class="sub">{e(keep)}</p><a class="btn" href="{e(url)}">{e(tr("Show the status", lg=lg))}</a>'
                    f'<p><a href="/f/{e(token)}">{e(tr("Send another one", lg=lg))}</a></p></div>', lg, 200, foot=False)


def frm_mail_ok(c, ehash, email, fid=None):
    """One confirmation per report, and only a few per address: nobody floods someone else's mailbox (caller commits)."""
    from ..integrations.mail import MAIL_OUT_ON
    from ..admin.hosting import mail_budget
    if not MAIL_OUT_ON or not ehash or hit_limit(f"frmm:{ehash}", FRM_MAIL_HOUR, 3600):
        return False
    return (fid is None or r81c_form_mail_day(c, fid)) and mail_budget(c, None, email)


def r81c_form_mail_day(c, fid):
    """2.81.0 (#1866): at most FRM_MAIL_DAY confirmation mails per form and day (counted in mail_counts like mail_budget)."""
    day = now_utc().strftime("%Y-%m-%d")
    k = f"fm:{fid}"
    r = c.execute("SELECT n, day FROM mail_counts WHERE k=?", (k,)).fetchone()
    if r and r[1] == day and r[0] >= FRM_MAIL_DAY:
        return False
    c.execute("""INSERT INTO mail_counts(k,day,n) VALUES(?,?,1) ON CONFLICT(k) DO UPDATE SET
                 n=CASE WHEN mail_counts.day=excluded.day THEN mail_counts.n+1 ELSE 1 END, day=excluded.day""", (k, day))
    return True


def frm_mail_text(form_title, subject, url, lg):
    text = "\n\n".join((tr("Thank you for your report “{0}”.", subject, lg=lg),
                         tr("You can see its status and our answers at any time with this link:", lg=lg) + "\n" + url,
                         tr("Keep this link to yourself: anyone who has it can see this report.", lg=lg),
                         tr("You get this mail because this address was entered in the form “{0}”. If that was not you, you can ignore it.", form_title, lg=lg)))
    return tr("Your report: {0}", subject, lg=lg), text


def frm_mail(to, subject, text):
    """The background part: talks to the mail server after the page has gone out."""
    from ..integrations.mail import mail_send
    try:
        mail_send(to, subject, text, from_name=APP_NAME)
    except Exception as x:  # noqa: BLE001  (nobody waits for this; the thank-you page showed the link)
        print("form confirmation mail failed:", type(x).__name__, flush=True)
