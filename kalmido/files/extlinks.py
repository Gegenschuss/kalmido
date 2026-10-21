"""2.112.1 B (#2058): external share links of the file store ("Ablage") -- a file or a folder for people without an account.

Who: only who may share the node (its owners: the owner of the branch, an organisation's admins; need_node(manage=True)),
never an agent, never for a link node (kind 'link'), an agent's folder (agent_id on the way up) or a node in the trash.
Several links per node (one per customer), each with an optional label only the owners see, an expiry (1 / 7 / 30 days,
a date or none), an optional password (hashed; an unlock cookie per link, HttpOnly + SameSite=Strict, bound to the
password version and the token), revocable (revoked_at: undo brings it back) and renewable (new token, the old one dies).

The page /s/f/<token> is server-rendered HTML without scripts (the look of the list links, lists/public.py): a file =
name, size, a download button and a preview of safe image types only (own route, magic bytes checked, sandbox CSP); a
folder = its folders (open through ?p=<id> inside the shared tree) and files, each to download, and the whole folder as a
ZIP (files/bulk.py of part A). Only view + download: no upload, no versions, no comments, no names of people.

A link lives only while (checked on EVERY request, also for every download): the server switch of public links is on
(public_links_on, KALMIDO_PUBLIC_LINKS=0), the organisation's switch orgs.ext_links is on (a person without an
organisation: only the server switch), it is neither revoked nor expired, the node and every folder above it are out of
the trash and still in the workspace the link was made in, and its creator is active and can still share the node (the
role is computed anew each time: leaving the organisation or losing the right kills their links). A folder link serves a
node only when its chain really runs through the shared folder (no guessing of ids). Limits per client address (views,
downloads, unknown tokens, wrong passwords) as the list links, a security alert when one link is opened unusually often,
and every view / download goes into the node's history (fs_log, no address). Contents are read like the app does
(fs_version_row + sc_guard + oc_send_file: sealed files of an organisation or a private space are opened with the
server-side key; the file store has no browser-encrypted files). Agents get no route here (no v1, no MCP tool).
"""
import hashlib
import hmac
import html
import os
import secrets
import threading
import time
from datetime import timedelta
from urllib.parse import quote

from flask import g, jsonify, redirect, request, Response
from werkzeug.security import check_password_hash, generate_password_hash

from ..core.config import app, APP_NAME, ATT_DIR, PUBLIC_URL
from ..core.i18n import lang, LANGS, N_, short_day, tr, trn
from ..core.db import body, bump, db, err, iso, now_utc, parse_iso
from ..core.pg import insert_id, system_ctx
from ..core.access import Denied, acx_anon_bind, acx_of
from ..core.orgcrypt import oc_read_file, oc_send_file
from ..accounts.session import _accept_lang, _rate_blocked, _rate_fail, _token_hash, me, rate_ip
from ..accounts.login import auth_key, seal, unseal
from ..notify.alerts import aa_count, aa_now
from ..lists.public import (PUB_ACTOR, PUB_BAD_LIMIT, PUB_BURST, PUB_BURST_S, PUB_PW_LIMIT, PUB_TOKEN_RE,
                            PUB_VIEW_RATE, pub_gone, pub_headers, pub_html, pub_limited, public_links_on)
from ..lists.custview import CV_FILE_RATE, cv_size
from .store import fs_chain, fs_role, fs_version_row, need_node

XL_PREFIX = "/s/f/"
XL_DAYS = {"1d": 1, "7d": 7, "30d": 30}
XL_MAX = 50              # links per node (revoked ones included until they are cleared)
XL_LABEL_MAX = 80
XL_LIST_MAX = 1000       # entries shown per folder
XL_ZIP_RATE = 5          # folder ZIPs per client address and minute
XL_ZIP_LINK_RATE = 10    # 2.112.1 (#2058, review): folder ZIPs per link and minute (all addresses together)
XL_ZIP_MAX_MB = int(os.environ.get("KALMIDO_EXT_ZIP_MAX_MB", "256"))      # a ZIP through a link: lower than signed in
XL_ZIP_MAX_FILES = int(os.environ.get("KALMIDO_EXT_ZIP_MAX_FILES", "1000"))
XL_PW_LINK_LIMIT = 20    # wrong passwords per file link within FAIL_WINDOW (list links: PUB_PW_LINK_LIMIT)
XL_REVOKED_DAYS = 30     # a revoked link is removed for good after this many days (undo works until then)
XL_PREVIEW_MB = 15       # bigger images get no preview (the download stays)
XL_IMG = {"image/png": (b"\x89PNG\r\n\x1a\n",), "image/jpeg": (b"\xff\xd8\xff",), "image/gif": (b"GIF87a", b"GIF89a"),
          "image/webp": (b"RIFF",)}
XL_FILE_CSP = "default-src 'none'; sandbox"
_XL_VIEWS, _XL_LOCK = {}, threading.Lock()


# ---------------------------------------------------------------- rules
def xl_org_on(c, org_id):
    """The organisation's switch "External share links" (default on); a private space has none (server switch only)."""
    if not org_id:
        return True
    r = c.execute("SELECT ext_links FROM orgs WHERE id=?", (int(org_id),)).fetchone()
    return bool(r and r[0])


def xl_chain_ok(chain):
    """A node that can be shared outside: a file or a folder, no link / agent folder on the way up, nothing in the trash."""
    return bool(chain) and chain[0]["kind"] in ("file", "folder") and not any(r["deleted_at"] or r["agent_id"] for r in chain)


def xl_why_not(c, n, chain):
    """Why node n cannot get an external link (a text for the dialog), or None."""
    if not public_links_on(c):
        return tr("Public links are turned off on this server")
    if n["kind"] == "link":
        return tr("A linked file of a task or project cannot be shared outside. Share the original instead.")
    if n["kind"] not in ("file", "folder") or not xl_chain_ok(chain):
        return tr("Folders of agents and items in the trash cannot be shared outside.")
    if not xl_org_on(c, n["org_id"]):
        return tr("External share links are turned off in this organisation.")
    return None


def xl_expiry(b):
    """{expires: 1d | 7d (default) | 30d | none | YYYY-MM-DD, tz?} -> the UTC end (iso) or None."""
    v = b.get("expires", "7d")
    if v in (None, "", "none"):
        return None
    if v in XL_DAYS:
        return iso(now_utc() + timedelta(days=XL_DAYS[v]))
    from .web import _expiry
    exp = _expiry(v, b.get("tz"))
    if not exp or exp <= iso(now_utc()):
        raise Denied(400, tr("The expiry date must be today or later"))
    return exp


def xl_flags(c, ids):
    """Ids of the nodes among ids with a live (not revoked, not expired) external link -- the badge of a row."""
    ids = [int(i) for i in ids if i]
    if not ids:
        return set()
    q = ",".join("?" * len(ids))
    return {r[0] for r in c.execute(f"SELECT DISTINCT node_id FROM fs_ext_links WHERE node_id IN ({q}) AND revoked_at IS NULL "
                                    "AND (expires_at IS NULL OR expires_at > ?)", [*ids, iso(now_utc())])}


# ---------------------------------------------------------------- the public side
def xl_find(c, token):
    """The live link of a token + the shared node's chain (dict link, chain) or None -- every rule of the module docstring."""
    if not PUB_TOKEN_RE.fullmatch(token or ""):
        return None
    with system_ctx(c):  # resolve the token (one row) across organisations; everything after it reads as nobody inside the node's workspace
        r = c.execute("""SELECT x.*, u.disabled AS u_disabled, COALESCE(u.kind, 'user') AS u_kind FROM fs_ext_links x
                         JOIN users u ON u.id=x.created_by WHERE x.token_hash=?""", (_token_hash(token),)).fetchone()
    if not r or r["revoked_at"] or r["u_disabled"] or r["u_kind"] == "agent" \
            or (r["expires_at"] and parse_iso(r["expires_at"]) <= now_utc()):
        return None
    acx_anon_bind(c, r["org_id"])
    g.user, g.auth_via = PUB_ACTOR, "public"  # a signed-in visitor too: the page is nobody's
    chain = fs_chain(c, r["node_id"])
    if not xl_chain_ok(chain) or (chain[0]["org_id"] or None) != (r["org_id"] or None) or not xl_org_on(c, r["org_id"]):
        return None
    if fs_role(c, r["node_id"], r["created_by"], chain) != "owner":  # the creator can still share it (left / lost the right = dead)
        return None
    return dict(r), chain


def xl_open(c, token):
    """Common checks of every /s/f/ request -> (link, chain, None) or (None, None, response)."""
    ip = rate_ip()
    if not public_links_on(c):
        return None, None, pub_gone()
    bad = [("pubbad:" + ip, PUB_BAD_LIMIT)]  # unknown tokens count together with the list links
    if _rate_blocked(bad):
        return None, None, pub_limited(_accept_lang())
    got = xl_find(c, token)
    if not got:
        _rate_fail(bad)
        aa_count("security", "publink", ip)
        return None, None, pub_gone()
    return got[0], got[1], None


def xl_lang(c, link):
    for part in (request.headers.get("Accept-Language") or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in LANGS:
            return code
    return lang(c, link["created_by"])


def xl_cookie(link):
    return f"kalmido_fsxl{link['id']}"


def xl_cookie_val(c, link):
    return hmac.new(auth_key(c), f"fsxl:{link['id']}:{link['pw_ver']}:{link['token_hash']}".encode(), hashlib.sha256).hexdigest()


def xl_unlocked(c, link):
    return not link["pw_hash"] or hmac.compare_digest(request.cookies.get(xl_cookie(link), ""), xl_cookie_val(c, link))


def xl_in_tree(c, link, nid):
    """The chain of node nid from itself up to the shared node when it lies inside the shared tree (nothing on the way in
    the trash, no link / agent folder, the same workspace), else None."""
    try:
        nid = int(nid)
    except (TypeError, ValueError):
        return None
    chain = fs_chain(c, nid)
    ids = [r["id"] for r in chain]
    if link["node_id"] not in ids:
        return None
    part = chain[:ids.index(link["node_id"]) + 1]
    if any(r["deleted_at"] or r["agent_id"] or r["kind"] not in ("file", "folder") or (r["org_id"] or None) != (link["org_id"] or None)
           for r in part):
        return None
    if any(r["hub_mail_id"] for r in part):  # 2.148.1 G (#2488): filed mail only for who may read the mail (the link's creator)
        from ..hub.hubmail import hbm_node_ok
        if any(r["hub_mail_id"] and not hbm_node_ok(c, link["created_by"], r["hub_mail_id"]) for r in part):
            return None
    return part


def xl_log(c, nid, action, link):
    """The node's history: a view / download through an external link (no person, no address; the label for the owners)."""
    c.execute("INSERT INTO fs_log(node_id,user_id,agent,action,detail,at) VALUES(?,?,?,?,?,?)",
              (int(nid), None, 0, action, (link["label"] or "")[:300], iso(now_utc())))


def xl_seen(c, link):
    """Counts a view; an unusual burst of views of one link -> a security alert (once per PUB_BURST_S)."""
    now, ip = time.time(), rate_ip()
    with _XL_LOCK:
        s = _XL_VIEWS.setdefault(link["id"], {"hits": [], "alerted": 0.0})
        s["hits"] = [h for h in s["hits"] if now - h[0] < PUB_BURST_S] + [(now, ip)]
        burst = len(s["hits"]) >= PUB_BURST and now - s["alerted"] >= PUB_BURST_S
        if burst:
            s["alerted"] = now
            n, ips = len(s["hits"]), len({h[1] for h in s["hits"]})
        if len(_XL_VIEWS) > 5000:
            _XL_VIEWS.clear()
    if burst:
        aa_now("security", f"fsxl_burst:{link['id']}",
               N_("The external link {0} of the file store was opened {1} times within {2} minutes (from {3} addresses)."),
               [link["id"], n, PUB_BURST_S // 60, ips])
    c.execute("UPDATE fs_ext_links SET views=views+1, last_seen_at=? WHERE id=?", (iso(now_utc()), link["id"]))


def xl_file_headers(resp):
    resp.headers["Content-Security-Policy"] = XL_FILE_CSP
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-store, private"
    return resp


def xl_zip_ready():
    """True when the folder ZIP of part A (files/bulk.py) is there."""
    try:
        from .bulk import fs_zip_build, abm_send_zip  # noqa: F401
    except ImportError:
        return False
    return True


def xl_preview_ok(n):
    return n["kind"] == "file" and (n["mime"] or "") in XL_IMG and 0 < (n["size"] or 0) <= XL_PREVIEW_MB * 1024 * 1024


_ICON = {"folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
         "file": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>'}


def xl_icon(kind):
    return (f'<svg class="xl-ic" viewBox="0 0 24 24" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" '
            f'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">{_ICON[kind]}</svg>')


def xl_pw_page(token, lg, folder, wrong=False):
    e = html.escape
    main = (f'<div class="msg"><h1>{e(tr("Password required", lg=lg))}</h1>'
            f'<p>{e(tr("This link is protected with a password.", lg=lg))}</p>'
            f'<form method="post" action="{XL_PREFIX}{e(token)}/unlock" class="pw"><input type="password" name="password" '
            f'autocomplete="current-password" aria-label="{e(tr("Password", lg=lg))}" required autofocus><button>{e(tr("Open", lg=lg))}</button></form>'
            + (f'<p class="err">{e(tr("Wrong password", lg=lg))}</p>' if wrong else "") + '</div>')
    return pub_html(tr("Password required", lg=lg), main, lg, 401 if wrong else 200)


def xl_until(link, lg):
    if not link["expires_at"]:
        return ""
    from ..core.config import TZ
    d = parse_iso(link["expires_at"]).astimezone(TZ).date()
    return tr("Available until {0}", short_day(d, lg, year=True), lg=lg)


def xl_render(c, link, chain, token, lg, cur):
    """The page: a file (preview + download) or the folder cur (a chain inside the shared tree, cur[0] = the folder shown)."""
    e = html.escape
    base = XL_PREFIX + e(token)
    root = chain[0]
    sub = [x for x in (e(tr("View and download only.", lg=lg)), e(xl_until(link, lg))) if x]
    if root["kind"] == "file":
        prev = ""
        if xl_preview_ok(root):
            prev = f'<figure class="xl-prev"><img src="{base}/v/{root["id"]}" alt="{e(root["name"])}"></figure>'
        main = (f'<header><h1>{e(root["name"])}</h1><p class="sub">{e(cv_size(root["size"] or 0, lg))} · {" · ".join(sub)}</p></header>{prev}'
                f'<p class="xl-act"><a class="xl-btn" href="{base}/d/{root["id"]}" download rel="nofollow">{e(tr("Download", lg=lg))}</a></p>')
        return pub_html(f"{root['name']} · {APP_NAME}", main, lg)
    folder = cur[0]
    rows = c.execute("""SELECT id, kind, name, size, mime, hub_mail_id FROM fs_nodes WHERE parent_id=? AND deleted_at IS NULL AND agent_id IS NULL
                        AND kind IN ('folder', 'file') AND (org_id=? OR (? IS NULL AND org_id IS NULL))
                        ORDER BY kind='file', lower(name), id LIMIT ?""",
                     (folder["id"], link["org_id"], link["org_id"], XL_LIST_MAX + 1)).fetchall()
    from .store import fs_mail_rows  # 2.148.1 G (#2488): the same rule for filed mail as in the app
    rows = fs_mail_rows(c, link["created_by"], rows)
    more = len(rows) > XL_LIST_MAX
    rows = rows[:XL_LIST_MAX]
    from .upsafe import up_marks
    marks = up_marks(c, "fs", [r["id"] for r in rows if r["kind"] == "file"])
    items = []
    for r in rows:
        if r["kind"] == "folder":
            items.append(f'<li class="xl-dir"><a href="{base}?p={r["id"]}">{xl_icon("folder")}<span>{e(r["name"])}</span></a></li>')
            continue
        locked = (marks.get(r["id"]) or {}).get("scan") == "infected"
        name = (f'<a href="{base}/d/{r["id"]}" download rel="nofollow">{xl_icon("file")}<span>{e(r["name"])}</span></a>' if not locked
                else f'<span class="xl-off">{xl_icon("file")}<span>{e(r["name"])}</span></span>')
        items.append(f'<li>{name} <span class="fs">{e(cv_size(r["size"] or 0, lg))}</span></li>')
    crumbs = ""
    if len(cur) > 1:  # the way from the shared folder down to the one shown (inside the shared tree only)
        way = list(reversed(cur))
        crumbs = ('<nav class="xl-crumbs">' + ' <span aria-hidden="true">/</span> '.join(
            f'<a href="{base}' + (f'?p={r["id"]}' if i else '') + f'">{e(r["name"])}</a>' if i < len(way) - 1 else f'<span>{e(r["name"])}</span>'
            for i, r in enumerate(way)) + '</nav>')
    nf, nd = sum(1 for r in rows if r["kind"] == "file"), sum(1 for r in rows if r["kind"] == "folder")
    count = ", ".join(x for x in (trn("{0} folder", "{0} folders", nd, lg=lg) if nd else "", trn("{0} file", "{0} files", nf, lg=lg) if nf else "") if x)
    zip_btn = ""
    if (nf or nd) and xl_zip_ready():  # 2.112.1 (#2058): the folder shown as a ZIP (files/bulk.py of part A)
        zip_btn = (f'<p class="xl-act"><a class="xl-btn" href="{base}/zip' + (f'?p={folder["id"]}' if len(cur) > 1 else '')
                   + f'" rel="nofollow">{e(tr("Download all as ZIP", lg=lg))}</a></p>')
    body_ = (f'<ul class="files xl-list">{"".join(items)}</ul>' if items else f'<p class="empty">{e(tr("This folder is empty", lg=lg))}</p>')
    if more:
        body_ += f'<p class="empty">{e(tr("Only the first {0} entries are shown.", XL_LIST_MAX, lg=lg))}</p>'
    main = (f'<header><h1>{e(root["name"])}</h1><p class="sub">{e(count) + " · " if count else ""}{" · ".join(sub)}</p></header>'
            f'{crumbs}{zip_btn}{body_}')
    return pub_html(f"{root['name']} · {APP_NAME}", main, lg)


@app.get("/s/f/<token>")
def xl_page(token):
    from ..api.v1 import hit_limit
    c = db()
    if hit_limit("pubv:" + rate_ip(), PUB_VIEW_RATE):
        return pub_limited(_accept_lang())
    link, chain, bad = xl_open(c, token)
    if bad:
        return bad
    lg = xl_lang(c, link)
    if not xl_unlocked(c, link):
        return xl_pw_page(token, lg, chain[0]["kind"] == "folder")
    cur = [chain[0]]
    if request.args.get("p") and chain[0]["kind"] == "folder":
        cur = xl_in_tree(c, link, request.args.get("p"))
        if not cur or cur[0]["kind"] != "folder":
            return pub_gone(lg)
    xl_seen(c, link)
    xl_log(c, cur[0]["id"], "ext_view", link)
    c.commit()
    return xl_render(c, link, chain, token, lg, cur)


@app.post("/s/f/<token>/unlock")
def xl_unlock(token):
    c = db()
    link, chain, bad = xl_open(c, token)
    if bad:
        return bad
    lg, ip = xl_lang(c, link), rate_ip()
    if not link["pw_hash"]:
        return redirect(XL_PREFIX + quote(token), 303)
    keys = [(f"fsxlpw:{link['id']}:{ip}", PUB_PW_LIMIT), (f"fsxlpwl:{link['id']}", XL_PW_LINK_LIMIT)]
    if _rate_blocked(keys):
        return pub_limited(lg)
    if not check_password_hash(link["pw_hash"], request.form.get("password") or ""):
        _rate_fail(keys)
        aa_count("security", "publink", ip)
        return xl_pw_page(token, lg, chain[0]["kind"] == "folder", wrong=True)
    resp = redirect(XL_PREFIX + quote(token), 303)
    secure = request.is_secure or request.headers.get("X-Forwarded-Proto", "") == "https"
    resp.set_cookie(xl_cookie(link), xl_cookie_val(c, link), max_age=30 * 86400, httponly=True, samesite="Strict",
                    secure=secure, path=XL_PREFIX + token)
    return pub_headers(resp)


def xl_gate(c, token, nid):
    """A file of a live, unlocked link -> (link, node row, None) or (None, None, response)."""
    from ..api.v1 import hit_limit
    if hit_limit("pubf:" + rate_ip(), CV_FILE_RATE):
        return None, None, pub_limited(_accept_lang())
    link, chain, bad = xl_open(c, token)
    if bad:
        return None, None, bad
    lg = xl_lang(c, link)
    if not xl_unlocked(c, link):
        return None, None, pub_gone(lg)
    part = xl_in_tree(c, link, nid)
    if not part or part[0]["kind"] != "file":
        return None, None, pub_gone(lg)
    return link, dict(part[0]), None


def xl_version(c, n):
    """The current version row of file n and its path, or None (missing / locked by the virus scanner)."""
    v = fs_version_row(c, n["id"])
    if not v:
        return None, None
    from .scan import sc_guard
    try:
        sc_guard(c, "fs", n["id"], v["no"])  # a version found infected (or, strict mode, not checked yet) is never handed out
    except Denied:
        return None, None
    full = os.path.join(ATT_DIR, v["path"])
    return (v, full) if os.path.isfile(full) else (None, None)


@app.get("/s/f/<token>/d/<int:nid>")
def xl_download(token, nid):
    c = db()
    link, n, bad = xl_gate(c, token, nid)
    if bad:
        return bad
    v, full = xl_version(c, n)
    if not v:
        return pub_gone(xl_lang(c, link))
    xl_log(c, n["id"], "ext_download", link)
    c.commit()
    resp = oc_send_file(c, full, mimetype="application/octet-stream", as_attachment=True, download_name=n["name"], max_age=0)
    return xl_file_headers(resp)


@app.get("/s/f/<token>/v/<int:nid>")
def xl_preview(token, nid):
    """The preview of a png / jpeg / gif / webp (type checked by its first bytes as well), never anything else inline."""
    c = db()
    link, n, bad = xl_gate(c, token, nid)
    if bad:
        return bad
    v, full = xl_version(c, n)
    mime = (v["mime"] if v else "") or n["mime"]
    if not v or mime not in XL_IMG or not xl_preview_ok({**n, "mime": mime, "size": v["size"]}):
        return pub_gone(xl_lang(c, link))
    data = oc_read_file(c, full)
    if not data.startswith(XL_IMG[mime]) or (mime == "image/webp" and data[8:12] != b"WEBP"):
        return pub_gone(xl_lang(c, link))
    return xl_file_headers(Response(data, mimetype=mime))


@app.get("/s/f/<token>/zip")
def xl_zip(token):
    """The shared folder (or the subfolder ?p=) as a ZIP: only what lies inside the shared tree (files/bulk.py of part A)."""
    from ..api.v1 import hit_limit
    c = db()
    if hit_limit("pubz:" + rate_ip(), XL_ZIP_RATE):
        return pub_limited(_accept_lang())
    link, chain, bad = xl_open(c, token)
    if bad:
        return bad
    lg = xl_lang(c, link)
    if not xl_unlocked(c, link) or chain[0]["kind"] != "folder" or not xl_zip_ready():
        return pub_gone(lg)
    cur = xl_in_tree(c, link, request.args.get("p") or link["node_id"])
    if not cur or cur[0]["kind"] != "folder":
        return pub_gone(lg)
    if hit_limit(f"pubzl:{link['id']}", XL_ZIP_LINK_RATE):
        return pub_limited(lg)
    from .bulk import fs_zip_build, abm_send_zip, abm_drop

    def can_read(c2, row):
        return xl_in_tree(c2, link, row["id"]) is not None

    try:
        path, name = fs_zip_build(c, [cur[0]], can_read, max_files=XL_ZIP_MAX_FILES, max_mb=XL_ZIP_MAX_MB)
    except Denied as x:
        return pub_limited(lg) if x.code in (413, 429) else pub_gone(lg)
    try:
        xl_log(c, cur[0]["id"], "ext_download", link)  # one history line for the whole ZIP (the folder)
        c.commit()
        return xl_file_headers(abm_send_zip(path, name))
    except BaseException:
        abm_drop(path)
        raise


# ---------------------------------------------------------------- managing the links (the node's details, owners only)
def xl_need(c, nid):
    """The node for the signed-in person who may share it (owners: need_node manage); agents never."""
    if acx_of(c, me()).role == "agent" or g.get("token"):
        raise Denied(403)
    return need_node(c, nid, manage=True)


def xl_url(c, r):
    return PUBLIC_URL.rstrip("/") + XL_PREFIX + unseal(c, f"fsxl:{r['node_id']}", r["token"])


def xl_json(c, r, names):
    now = now_utc()
    return {"id": r["id"], "url": xl_url(c, r), "label": r["label"], "has_password": bool(r["pw_hash"]), "expires_at": r["expires_at"],
            "expired": bool(r["expires_at"] and parse_iso(r["expires_at"]) <= now), "created_at": r["created_at"],
            "created_by": r["created_by"], "by": names.get(r["created_by"], ""), "last_seen_at": r["last_seen_at"], "views": r["views"]}


def xl_answer(c, n, extra=None):
    from .web import _names
    c.execute("DELETE FROM fs_ext_links WHERE node_id=? AND revoked_at IS NOT NULL AND revoked_at < ?",
              (n["id"], iso(now_utc() - timedelta(days=XL_REVOKED_DAYS))))
    rows = c.execute("SELECT * FROM fs_ext_links WHERE node_id=? AND revoked_at IS NULL ORDER BY id", (n["id"],)).fetchall()
    names = _names(c, [r["created_by"] for r in rows])
    out = {"enabled": public_links_on(c), "blocked": xl_why_not(c, n, fs_chain(c, n["id"])), "links": [xl_json(c, r, names) for r in rows]}
    return {**out, **(extra or {})}


def xl_new_token(c, nid):
    tok = secrets.token_urlsafe(24)
    return _token_hash(tok), seal(c, f"fsxl:{nid}", tok)


def xl_row(c, xid):
    """A link row and its node for an owner of the node (404 for everybody else)."""
    r = c.execute("SELECT * FROM fs_ext_links WHERE id=?", (int(xid),)).fetchone()
    if not r:
        raise Denied(404)
    try:
        return r, xl_need(c, r["node_id"])
    except Denied:  # 2.112.1 (#2058, review): no hint which link ids exist
        raise Denied(404) from None


@app.get("/api/files/nodes/<int:nid>/ext-links")
def xl_list(nid):
    """The external links of a node (its owners): {enabled, blocked: text | null, links: [...]}."""
    c = db()
    n = xl_need(c, nid)
    out = xl_answer(c, n)
    c.commit()
    return jsonify(out)


@app.post("/api/files/nodes/<int:nid>/ext-links")
def xl_create(nid):
    """{expires?: 1d | 7d | 30d | none | YYYY-MM-DD (default 7d), tz?, password?, label?} -> a new link (several per node)."""
    c = db()
    n = xl_need(c, nid)
    why = xl_why_not(c, n, fs_chain(c, nid))
    if why:
        return err(why, 409)
    b = body()
    exp = xl_expiry(b)
    label = " ".join(str(b.get("label") or "").split())[:XL_LABEL_MAX]
    pw = b.get("password") or ""
    if not isinstance(pw, str) or (pw and not 4 <= len(pw) <= 200):
        return err(tr("Password: at least {0} characters", 4))
    if c.execute("SELECT COUNT(*) FROM fs_ext_links WHERE node_id=?", (nid,)).fetchone()[0] >= XL_MAX:
        return err(tr("At most {0} links per item", XL_MAX), 409)
    h, sealed = xl_new_token(c, nid)
    xid = insert_id(c, """INSERT INTO fs_ext_links(node_id,org_id,created_by,label,token_hash,token,pw_hash,pw_ver,expires_at,created_at)
                          VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (nid, n["org_id"], me(), label, h, sealed, generate_password_hash(pw) if pw else None, 0, exp, iso(now_utc())))
    from .store import fs_log_add
    fs_log_add(c, nid, "ext_link")
    bump(c)
    c.commit()
    print("external link created for file store node", nid, flush=True)
    return jsonify(xl_answer(c, n, {"id": xid}))


@app.post("/api/files/ext-links/<int:xid>/regenerate")
def xl_regen(xid):
    """A new token: the old address (and its unlock cookies) stops working at once."""
    c = db()
    r, n = xl_row(c, xid)
    if r["revoked_at"]:
        raise Denied(404)
    h, sealed = xl_new_token(c, r["node_id"])
    c.execute("UPDATE fs_ext_links SET token_hash=?, token=?, pw_ver=pw_ver+1, views=0, last_seen_at=NULL WHERE id=?", (h, sealed, xid))
    bump(c)
    c.commit()
    return jsonify(xl_answer(c, n, {"id": xid}))


@app.delete("/api/files/ext-links/<int:xid>")
def xl_revoke(xid):
    """Revoke: dead at once; kept XL_REVOKED_DAYS days so undo (restore) can bring the same address back."""
    c = db()
    r, n = xl_row(c, xid)
    c.execute("UPDATE fs_ext_links SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (iso(now_utc()), xid))
    from .store import fs_log_add
    fs_log_add(c, n["id"], "ext_unlink")
    bump(c)
    c.commit()
    return jsonify(xl_answer(c, n))


@app.post("/api/files/ext-links/<int:xid>/restore")
def xl_restore(xid):
    """Undo of a revoke (only while the node can still be shared outside)."""
    c = db()
    r, n = xl_row(c, xid)
    why = xl_why_not(c, n, fs_chain(c, n["id"]))
    if why:
        return err(why, 409)
    c.execute("UPDATE fs_ext_links SET revoked_at=NULL WHERE id=?", (xid,))
    bump(c)
    c.commit()
    return jsonify(xl_answer(c, n, {"id": xid}))


def xl_space_moved(c, ids):
    """files/fsmove.py: nodes that went into another workspace lose their external links (the other workspace's rules)."""
    ids = [int(i) for i in ids]
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        c.execute(f"DELETE FROM fs_ext_links WHERE node_id IN ({','.join('?' * len(part))})", part)
