"""HTML pages, security headers, /api/version, the share target, quick capture, /drop and the ntfy share inbox."""
import hashlib
import json
import mimetypes
import os
import re
import threading
import uuid
import time
import urllib.error
import urllib.parse
import urllib.request
from flask import g, jsonify, redirect, request, Response, send_from_directory

from ..core.config import app, APP_VERSION, ATT_DIR, ICAL_PREFIX, PUB_PREFIX, SEARCH_INDEX, MAX_FILE_MB, ntfy_attachment_url, NTFY_IN, PUBLIC_URL, safe_urlopen
from .pg import insert_id
from ..core.i18n import lang, N_, tr, trn
from ..core.db import bump, connect, db, default_uid, err, gset, gsetting, iso, now_utc, usettings
from ..accounts.session import client_ip, GATE, me
from ..core.access import Denied, my_inbox, time_all, acx_token_bind, collab_all
from ..core.orgcrypt import oc_task_org  # 2.149.0 G (#2517): pulled up from functions
from ..core.tokenhash import tkh_hash, tkh_match  # 2.149.0 G (#2517): pulled up from functions
from ..core.errors import BadInput  # 2.149.0 G (#2517): pulled up from functions
from ..core.db import GLOBAL_DEFAULTS, lv_versions_fmt, lv_versions_q  # 2.149.0 G (#2517): pulled up from functions
from ..core.strip import strip_asset  # 2.191.0 B (#1824)


# ---------------------------------------------------------------- pages

# 2.99.1 A (#1959): frames only of the two video players (the embed URL is built from a checked id: videos/review.py vdr_embed),
# media over https (a video sign-off's direct file link); no script of theirs is loaded (script-src stays 'self')
# 2.139.0 B (#2128): media-src blob: = the preview of a voice message before it is sent; microphone=(self) = recording in the app
# 2.182.0 (#2717): media-src keeps https: -- a video sign-off plays a direct file link from any host (videos/review.py), no fixed
# list of hosts exists; media cannot run code (script-src stays 'self')
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; connect-src 'self'; manifest-src 'self'; worker-src 'self'; "
       "frame-src 'self' https://player.vimeo.com https://www.youtube-nocookie.com; media-src 'self' https: blob:; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")
PERMISSIONS_POLICY = ("camera=(), microphone=(self), geolocation=(), payment=(), usb=(), serial=(), bluetooth=(), "
                      "midi=(), hid=(), magnetometer=(), gyroscope=(), accelerometer=(), display-capture=(), "
                      "browsing-topics=()")


@app.after_request
def headers(resp):
    # own CSPs (attachments) are kept; everything else gets the app CSP
    resp.headers.setdefault("Content-Security-Policy", CSP)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
    # 2.182.0 (#2717): other sites cannot load the app's answers (files, images, API) into their pages; the public links
    # (/s/..., forms, calendar feeds) stay loadable from anywhere. A window opened from another site gets no handle on the app.
    resp.headers.setdefault("Cross-Origin-Resource-Policy",
                            "cross-origin" if request.path.startswith((PUB_PREFIX, ICAL_PREFIX, "/f/")) else "same-origin")
    resp.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    if request.is_secure:  # https (directly or from a trusted proxy): browsers stay on https; a proxy's own header wins
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    # 2.29.0 (#1026): never indexed unless the operator allows it; public list links, forms and feeds never
    if not SEARCH_INDEX or request.path.startswith((PUB_PREFIX, ICAL_PREFIX, "/f/", "/api/", "/dav")):
        resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    if request.path.startswith("/api/") and not request.path.startswith(("/api/attachments/", "/api/chat-files/", "/api/avatar/", "/api/group-avatar/", "/api/list-icon/", "/api/list-files/", "/api/list-header/")):
        resp.headers["Cache-Control"] = "no-store"
    # 2.149.0 B (#2505): a static file asked for with ?v=<its content hash> never changes: the browser keeps it a year without
    # asking again. Any other ?v= (the version of the code, an old hash after an update) and no ?v= stay as before.
    v = request.args.get("v")
    if v and resp.status_code in (200, 304) and request.path.startswith("/static/") and v == static_hash(request.path[8:]):
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp


# ---------------------------------------------------------------- 2.149.0 B (#2505 #2506): content hashes of static files

_SHASH, _SHASH_LOCK = {}, threading.Lock()
_ASSET_RE = re.compile(r'(<(?:script|link)\b[^>]*?\b(?:src|href)="/static/)([\w./-]+\.(?:js|css))"')
_SW_LISTS_RE = re.compile(r"const (?:SHELL|LAZY|LAZY_CSS) = \[(.*?)\];", re.S)


def static_hash(rel):
    """The first 12 hex digits of the SHA-256 of static/<rel> as it goes out (None: no such file), kept until the file changes.
    2.191.0 B (#1824): for .js / .css the hash runs over the bytes without comments (st_asset), so ?v= and the sw manifest
    follow what the browser gets."""
    hit = st_asset(rel)
    return hit[1] if hit else None


def st_asset(rel):
    """2.191.0 B (#1824): (bytes that go out instead of the file or None = the file as it is, content hash, mtime) of
    static/<rel>; None: no such file. .js / .css (not static/vendor/) go out without comments (core/strip.py), computed once
    per file version."""
    root = os.path.realpath(app.static_folder)
    try:  # 2.191.0 F1 (#1824): a NUL in the name (/static/x%00.js) is no such file (ValueError), as before
        path = os.path.realpath(os.path.join(root, rel))
        if not path.startswith(root + os.sep):
            return None
        st = os.stat(path)
    except (OSError, ValueError):
        return None
    key = (st.st_mtime_ns, st.st_size)
    hit = _SHASH.get(path)
    if hit and hit[0] == key:
        return hit[1]
    rel = os.path.relpath(path, root).replace(os.sep, "/")
    h, served = hashlib.sha256(), None
    try:
        if rel.endswith((".js", ".css")) and not rel.startswith("vendor/"):
            with open(path, "rb") as f:
                data = f.read()
            served = strip_asset(rel, data)
            if served is None:
                app.logger.warning("static %s goes out with its comments (strip unsure)", rel)
            h.update(data if served is None else served)
        else:
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 16), b""):
                    h.update(chunk)
    except OSError:
        return None
    with _SHASH_LOCK:
        _SHASH[path] = (key, (served, h.hexdigest()[:12], st.st_mtime))
    return _SHASH[path][1]


def st_static(filename):
    """2.191.0 B (#1824): the /static/ route; .js / .css without comments (ETag = content hash, 304 on If-None-Match),
    everything else as before through flask's own sender."""
    hit = st_asset(filename) if filename.endswith((".js", ".css")) else None
    if not hit or hit[0] is None:
        return app.send_static_file(filename)
    r = Response(hit[0], mimetype=mimetypes.guess_type(filename)[0] or "application/octet-stream")
    r.cache_control.no_cache = True
    r.set_etag(hit[1])
    r.last_modified = hit[2]
    return r.make_conditional(request, accept_ranges=True, complete_length=len(hit[0]))  # F1: Range = 206 as before


app.view_functions["static"] = st_static


def _versioned(html):
    """index.html: every start script and stylesheet under /static/ gets ?v=<content hash> (the file list itself stays in
    index.html; tools/check_layout.py compares it with sw.js)."""
    def sub(m):
        h = static_hash(m.group(2))
        return m.group(0) if not h else f'{m.group(1)}{m.group(2)}?v={h}"'
    return _ASSET_RE.sub(sub, html)


def st_warm():
    """2.191.0 (#1824): strip + hash the start scripts / styles of index.html once in the background at start, so the first
    page after a restart does not wait for it (about 1-3 s)."""
    try:
        with open(os.path.join(app.static_folder, "index.html"), encoding="utf-8") as f:
            for m in _ASSET_RE.finditer(f.read()):
                static_hash(m.group(2))
    except Exception:  # only a head start: the first request does it itself
        print("static warm-up failed (the first page does it)", flush=True)


_INDEX = {}


def index_page():
    """index.html with the version of this code (2.27.0, #968): the client compares it with /api/version "app" and offers a reload
    when the server runs a newer version than the code in the browser."""
    path = os.path.join(app.static_folder, "index.html")
    mt = os.path.getmtime(path)
    if _INDEX.get("mt") != mt or time.monotonic() - _INDEX.get("at", 0) > 5:  # 2.149.0 B (#2505): the hashes follow changed files
        from ..core.i18nparts import i18np_ver  # 2.191.0 A (#1410 #2518): the version of the split texts (i18n.js ?v=)
        with open(path, encoding="utf-8") as f:
            _INDEX.update(mt=mt, at=time.monotonic(),
                          html=_versioned(f.read().replace('<meta name="kalmido-version" content="">',
                                                           f'<meta name="kalmido-version" content="{APP_VERSION}">', 1)
                                          .replace('<meta name="kalmido-i18n" content="">', f'<meta name="kalmido-i18n" content="{i18np_ver()}">', 1)))
    r = Response(_INDEX["html"], mimetype="text/html")
    r.headers["Cache-Control"] = "no-cache"
    return r


@app.errorhandler(413)
def too_large(_):  # json, not flask's html page (the client treats html as "session expired")
    from ..integrations.importers import IMPORT_MAX_MB
    from ..admin.backup import BK_ERR, BK_MAX_BYTES
    if request.path == "/api/admin/backups/upload":
        return err(tr(BK_ERR["too_large"], BK_MAX_BYTES // 1048576), 413)
    if request.path.startswith(("/api/import/", "/api/v1/import/")):
        return err(tr("The file is too large (at most {0} MB)", IMPORT_MAX_MB), 413)
    return err(tr("Upload too large: at most {0} MB per file and {1} MB all files together", MAX_FILE_MB, MAX_FILE_MB * 4), 413)  # 2.273.0 D (#3051): the request limit is the total


@app.get("/")
def index():
    return index_page()


@app.get("/capture")
def capture():
    # 2.4.0 (#187): quick capture page (the bookmarklet opens it as a small popup with ?title&url; without them it shows
    # the bookmarklet and the keyboard shortcuts). The client does it all; saving is a normal session request.
    return index_page()


@app.get("/share")
def share():
    # Android Web Share Target (manifest share_target): the client reads ?title&text&url
    return index_page()


def new_inbox_task(c, uid, title, content="", tt_id=None, url=None):
    from ..tasks.validation import log_act
    inbox = my_inbox(c, uid)
    ts = iso(now_utc())
    srt = c.execute("SELECT COALESCE(MIN(sort),0)-1 FROM tasks WHERE list_id=? AND parent_id IS NULL", (inbox,)).fetchone()[0]
    # 2.27.0 (#1001): what lands in your own inbox (mail, the share sheet, /drop, the ntfy inbox) is yours: assigned to you,
    # so it also shows in "My tasks"
    tid = insert_id(c, "INSERT INTO tasks(list_id,title,content,sort,created_at,updated_at,tt_id,created_by,url,assignee_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (inbox, (title or tr("Shared", lg=lang(c, uid)))[:300], content or "", srt, ts, ts, tt_id, uid,
                     url if valid_url(url) else None, uid))
    log_act(c, tid, "created", uid=uid)
    return tid


# ---- website link (tasks.url): http/https only, no server-side fetching
URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)


def valid_url(u):
    return bool(u) and len(u) <= 2000 and bool(re.fullmatch(r"https?://[^\s/?#]+[^\s]*", u, re.I))


# 2.35.0 (#186): links to files on a network drive / the computer instead of uploading big files: smb://, afp://, nfs://,
# webdav(s)://, file:// and Windows paths \\server\share\... (spaces allowed, paths often have them; no control characters).
# Never javascript: / data: / anything else. Nextcloud and other web shares are https links anyway. Kalmido never opens them.
FILE_LINK_RE = re.compile(r"(?:(?:smb|afp|nfs|webdavs?|davs?)://[^\s/?#\\]+(?:[/?#][^\x00-\x1f\x7f]*)?"
                          r"|file:///?[^\s\x00-\x1f\x7f][^\x00-\x1f\x7f]*"
                          r"|\\\\[^\s\\/]+\\[^\x00-\x1f\x7f]+)", re.I)


def file_link(u):
    """True for a link to a file / folder on a network drive (see FILE_LINK_RE)."""
    return isinstance(u, str) and bool(u) and len(u) <= 2000 and u == u.strip() and bool(FILE_LINK_RE.fullmatch(u))


def valid_link(u):
    """A website link (http/https) or a file link (#186): the task link, key links of a project, link fields."""
    return valid_url(u) or file_link(u)


def url_title(u):
    """Readable title for a bare link: domain (without www.) + path."""
    p = urllib.parse.urlsplit(u)
    host = p.netloc.lower().split("@")[-1]
    host = host[4:] if host.startswith("www.") else host
    return (host + p.path.rstrip("/"))[:120] or u[:120]


def split_link(title, content=""):
    """Shared text -> (title, content, url): the first URL goes into the link field. A URL in the title is
    removed from it (a title that was only the URL becomes domain + path); a URL in the content stays there."""
    for where, txt in (("title", title or ""), ("content", content or "")):
        m = URL_RE.search(txt)
        if not m:
            continue
        url = m.group(0).rstrip(".,;:!?")
        if where == "title":
            title = re.sub(r"\s+", " ", txt[:m.start()] + txt[m.end():]).strip(" -–—|:·")
        return title or url_title(url), content, url
    return title, content, None


def save_attachment_bytes(c, tid, name, mime, data, owner=None):
    from ..tasks.attachments import safe_name
    from ..notify.alerts import aa_count, aa_oserr
    from ..admin.hosting import quota_fits
    from ..files.upsafe import up_check, up_after_store, UploadRefused
    name = safe_name(name)
    from ..collab.liste2efile import le2f_plain_skip
    if le2f_plain_skip(c, tid):  # 2.64.2 B (#1817): no plain file in a list with the lock
        print("share / mail file skipped: list encrypted in the browser", flush=True)
        return
    who = c.execute("SELECT created_by FROM tasks WHERE id=?", (tid,)).fetchone()
    who = who[0] if who else None
    if owner is not None:  # 2.63.0 (#1513): a form's file without an account counts against the list owner's storage
        who = owner
    org = oc_task_org(c, tid) or None
    mime = mime if mime and mime != "application/octet-stream" else (mimetypes.guess_type(name)[0] or "application/octet-stream")
    try:  # 2.61.0 (#1818 #1819 #1820): a virus find -> the task comes without the file (never an error), like a full quota
        data, mime, info = up_check(c, name, data, mime, who, org, "att")
    except UploadRefused as e:
        print("share / mail file skipped:", e, flush=True)
        return
    if not quota_fits(c, who, len(data)):  # 2.24.0 (#910): storage full -> the task comes without the file (never an error)
        print("share / mail file skipped: storage quota of user", who, "reached", flush=True)
        return
    rel = os.path.join(str(tid), f"{uuid.uuid4().hex[:12]}-{name}")
    try:
        os.makedirs(os.path.join(ATT_DIR, str(tid)), exist_ok=True)
        with open(os.path.join(ATT_DIR, rel), "wb") as f:
            f.write(data)
        from ..core.orgcrypt import oc_seal_path, oc_task_space
        oc_seal_path(c, oc_task_space(c, tid), os.path.join(ATT_DIR, rel), fresh=True)  # 2.42.0 (#828), 2.64.0 (#1864): sealed, also private
    except OSError as e:
        aa_count("storage", "attachments", aa_oserr(e))
        raise
    except Denied as e:  # 2.126.0 review (#1979 L5): a refused file -> the task comes without it (never an error), like a virus find
        print("share / mail file skipped:", e, flush=True)
        try:
            os.remove(os.path.join(ATT_DIR, rel))
        except OSError:
            pass
        return
    aid = insert_id(c, "INSERT INTO attachments(task_id,name,mime,size,path,created_at,user_id) VALUES(?,?,?,?,?,?,?)",
                    (tid, name, mime, len(data), rel, iso(now_utc()), who))
    up_after_store(c, "att", aid, org, info)


def inbox_user(c):
    """User whose inbox receives the ntfy share inbox (NTFY_INBOX_USER, default the first admin)."""
    if NTFY_IN["user"]:
        r = c.execute("SELECT id FROM users WHERE username=? AND disabled=0", (NTFY_IN["user"],)).fetchone()
        if r:
            return r[0]
    return default_uid(c)


def ntfy_inbox_import(c, m, who=None):
    """One ntfy message -> one inbox task (+ attachment). Idempotent via tt_id 'ntfy:<id>'.
    2.142.0 C (#2150): who = a person's own share inbox {"uid", "fetch": url -> bytes | None, "since": id -> stored}; without it
    the environment's inbox (NTFY_INBOX_*) and its user as before."""
    mid = m["id"]
    uid = who["uid"] if who else inbox_user(c)
    if uid and not c.execute("SELECT 1 FROM tasks WHERE tt_id=?", ("ntfy:" + mid,)).fetchone():
        att = m.get("attachment") or None
        msg = (m.get("message") or "").strip()
        if att and any(msg.startswith(p) for p in SHARE_PLACEHOLDERS):  # ntfy / Android placeholder texts
            msg = ""
        first = msg.split("\n", 1)[0].strip()
        if (m.get("title") or "").strip():
            title, content = m["title"].strip(), msg
        else:  # first line becomes the title, the rest the description
            title = first or (os.path.splitext(att["name"])[0] if att else tr("Shared", lg=lang(c, uid)))
            content = msg.split("\n", 1)[1].strip() if "\n" in msg else ""
        title, content, url = split_link(title, content)
        tid = new_inbox_task(c, uid, title, content, "ntfy:" + mid, url)
        if att and att.get("url"):
            # only attachments stored on the configured ntfy server (public name -> fetched via the internal URL);
            # anything else (other hosts, file://, ...) is never fetched and never gets the token
            if who:  # 2.142.0 C (#2150): the person's own server (checked in integrations/ntfyin.py)
                data = who["fetch"](att["url"])
            else:
                data, url = None, ntfy_attachment_url(att["url"])
                if not url:
                    print("ntfy inbox: attachment URL is not on the ntfy server, not fetched:", repr(str(att["url"])[:200]), flush=True)
                else:
                    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {NTFY_IN['token']}"})
                    try:
                        with safe_urlopen(req, timeout=120) as r:
                            data = r.read(MAX_FILE_MB * 1024 * 1024 + 1)
                    except (urllib.error.URLError, OSError, ValueError) as e:
                        print("ntfy inbox: attachment download failed:", e, flush=True)
            if data and len(data) <= MAX_FILE_MB * 1024 * 1024:  # 2.13.2: never a 0-byte file
                save_attachment_bytes(c, tid, str(att.get("name") or "datei"), "", data)  # 2.306.0 D3 (#2875): type from the content, not the sender
        print("ntfy inbox: task", tid, "user", uid, repr(title), "attachment" if att else "", flush=True)
    if who:
        who["since"](mid)
    else:
        gset(c, "ntfy_inbox_since", mid)
    bump(c)
    c.commit()


def ntfy_inbox_loop():
    """Stream the inbox topic (ntfy sends keepalives every 45 s); reconnect with the last id."""
    from ..notify.alerts import aa_err, aa_fail, aa_ok
    while True:
        try:
            c = connect()
            since = gsetting(c, "ntfy_inbox_since") or ""
            if not since:  # first start: only messages from now on
                since = str(int(time.time()))
                gset(c, "ntfy_inbox_since", since)
                c.commit()
            c.close()
            req = urllib.request.Request(f"{NTFY_IN['url']}/{NTFY_IN['topic']}/json?since={since}",
                                         headers={"Authorization": f"Bearer {NTFY_IN['token']}"})
            # read timeout > ntfy keepalive-interval (ntfy server setting)
            with safe_urlopen(req, timeout=300) as r:
                aa_ok("inbox")
                for line in r:
                    m = json.loads(line or b"{}")
                    if m.get("event") == "message":
                        with GATE.bg():
                            c = connect()
                            try:
                                ntfy_inbox_import(c, m)
                            finally:
                                c.close()
        except Exception as e:  # noqa: BLE001
            print("ntfy inbox:", e, flush=True)
            aa_fail("inbox", aa_err(e))
        time.sleep(10)


def h6a_share_origin_ok():
    """2.86.0 (N7): POST /share comes from the installed app's share sheet (Sec-Fetch-Site none / same-origin). A page of
    another origin (cross-site, or same-site such as another app under the same domain) is refused; a browser without
    Sec-Fetch-Site must not send a foreign Origin (compared with this request's host and PUBLIC_URL)."""
    sfs = request.headers.get("Sec-Fetch-Site", "")
    if sfs:
        return sfs in ("none", "same-origin")
    o = (request.headers.get("Origin") or "").strip()
    if not o or o == "null":
        return True
    host = (urllib.parse.urlsplit(o).netloc or "").lower()
    return host in (request.host.lower(), (urllib.parse.urlsplit(PUBLIC_URL).netloc or "").lower())


@app.post("/share")
def share_post():
    """Android share sheet with files, when the service worker did not catch it (first launch):
    create the task in the inbox right away and open it."""
    from flask import g
    from ..tasks.attachments import safe_name, save_attachments
    if not h6a_share_origin_ok():  # 2.86.0 (N7): the only cookie-authenticated write outside /api/: no foreign page
        print("share POST refused: Sec-Fetch-Site", repr(request.headers.get("Sec-Fetch-Site", "")[:20]), flush=True)
        return Response(tr("not allowed") + "\n", 403, mimetype="text/plain")
    if g.user["kid"]:  # 2.86.0 (N3): a child account writes only what family.KID_WRITE allows
        return Response(tr("Not possible with a child account") + "\n", 403, mimetype="text/plain")
    c = db()
    files = [f for key in request.files for f in request.files.getlist(key) if f and f.filename]
    # 2.86.0 (N7): the log names keys and lengths only, never the shared title / text / link
    print("share POST (server path): content_length", request.content_length, "form keys", list(request.form.keys()),
          "file keys", list(request.files.keys()), {k: len(request.form.get(k) or "") for k in ("title", "text", "url")},
          len(files), "files", flush=True)
    text, url = (request.form.get("text") or "").strip(), (request.form.get("url") or "").strip()
    m = None if url else URL_RE.search(text)  # most apps put the link into "text"
    if m:
        url, text = m.group(0).rstrip(".,;:!?"), text[:m.start()] + text[m.end():]
    title = (request.form.get("title") or "").strip() or re.sub(r"\s+", " ", text.replace(url, "") if url else text).strip(" -–—|:·") \
        or (url_title(url) if url else "") or (os.path.splitext(safe_name(files[0].filename))[0] if files else tr("Shared"))
    tid = new_inbox_task(c, me(), title, "", url=url or None)  # the link goes into the link field
    e = save_attachments(c, tid, files)
    bump(c)
    c.commit()
    if e:  # 2.81.0 (#1856): a refused file (too large, empty, the upload check) is named to the person, not only logged
        print("share POST: file refused", e, flush=True)
        return redirect(f"/?share=refused#t/{tid}", 303)
    return redirect(f"/#t/{tid}", 303)


# Placeholder texts some Android apps put next to a shared file; never a useful title.
SHARE_PLACEHOLDERS = ("You received a file:", "Ein Bild wurde mit Dir geteilt", "Ein Bild wurde mit dir geteilt")


def drop_user(c, auth):
    """User whose personal drop token is in the Authorization header (2.138.0 C #1907: looked up by its hash)."""
    if not auth.startswith("Bearer ") or not auth[7:]:
        return None
    got = auth[7:]
    # 2.86.0 (N3): never a child account (its writes are limited to family.KID_WRITE; /api/me hides its token)
    r = c.execute("SELECT * FROM users WHERE drop_token_hash=? AND disabled=0 AND kid=0", (tkh_hash(got),)).fetchone()
    return r if r and tkh_match(got, r["drop_token_hash"]) else None


@app.post("/drop")
@app.post("/drop/drop")  # 2.0.2: a shortcut that appends /drop to an address already ending in /drop still works
def drop_post():
    """Upload endpoint for the Android app HTTP Shortcuts (Chrome drops files shared to PWAs):
    one request = one inbox task with every file attached. Exclude /drop from the proxy login;
    the bearer token (TASKS_DROP_TOKEN) is its lock. Every user has an own token (task lands in their inbox)."""
    from ..tasks.attachments import safe_name, save_attachments
    from ..notify.alerts import aa_count
    auth = request.headers.get("Authorization", "")
    c = db()
    u = drop_user(c, auth)
    if not u:
        aa_count("security", "drop", client_ip())
        print("drop: 403, auth header", "missing" if not auth else
              f"len {len(auth)} starts {auth[:7]!r} ends-with-space {auth != auth.rstrip()}", flush=True)
        return Response(tr("not allowed") + "\n", 403, mimetype="text/plain")
    acx_token_bind(u["id"])  # 2.37.0 (#1150): reads and writes with the token owner's context (row-level security)
    lg = lang(c, u["id"])
    files = [f for key in request.files for f in request.files.getlist(key) if f and f.filename]
    text = (request.form.get("text") or "").strip()
    if any(text.startswith(p) for p in SHARE_PLACEHOLDERS):
        text = ""
    if not files and not text:
        return Response(tr("nothing received", lg=lg) + "\n", 400, mimetype="text/plain")
    to = (request.form.get("to") or "").strip()
    if to:  # 2.13.1 (#465): "Send to agent" (iOS Shortcut / HTTP Shortcuts): the files + text go into an agent chat
        return drop_to_agent(c, u, lg, to, text, files)
    first, _, rest = text.partition("\n")
    first, rest, url = split_link(first.strip(), rest.strip())
    title = first or (os.path.splitext(safe_name(files[0].filename))[0] if len(files) == 1
                      else tr("{0} files shared", len(files), lg=lg))
    tid = new_inbox_task(c, u["id"], title, rest, url=url)
    e = save_attachments(c, tid, files, uid=u["id"]) if files else None
    bump(c)
    c.commit()
    print("drop: task", tid, "user", u["id"], repr(title), len(files), "files", e or "", flush=True)
    n = trn(", {0} file", ", {0} files", len(files), lg=lg) if files and title != tr("{0} files shared", len(files), lg=lg) else ""
    return Response(f"Kalmido: {title}{n}" + (f" ({tr('error: {0}', e, lg=lg)})" if e else "") + "\n", mimetype="text/plain")


def drop_agent(c, uid, to):
    """The agent a /drop with `to` means: 'agent' = the one uid chatted with last (else the first one uid may chat with),
    else an agent id or username; only agents uid may chat with."""
    from ..agents.core import agent_shares
    ok = [r[0] for r in c.execute("SELECT id FROM users WHERE kind='agent' AND disabled=0 ORDER BY id") if agent_shares(c, r[0], uid)]
    if to.lower() == "agent":
        last = c.execute(f"SELECT agent_id FROM agent_chat WHERE user_id=? AND agent_id IN ({','.join('?' * len(ok)) or 'NULL'}) "
                         "ORDER BY id DESC LIMIT 1", (uid, *ok)).fetchone()
        return last[0] if last else (ok[0] if ok else None)
    for aid in ok:
        u = c.execute("SELECT username FROM users WHERE id=?", (aid,)).fetchone()
        if to == str(aid) or to.casefold() == (u["username"] or "").casefold():
            return aid
    return None


def drop_to_agent(c, u, lg, to, text, files):
    from ..collab.comments import user_names
    from ..agents.core import agent_active, agent_row, CHAT_MAX
    from ..agents.chat import chat_emit, CHAT_FILES_MAX, chat_post, chat_unlink_trimmed
    aid = drop_agent(c, u["id"], to)
    a = agent_row(c, aid) if aid else None
    if not a:
        return Response(tr("No agent to send this to", lg=lg) + "\n", 404, mimetype="text/plain")
    if not agent_active(a):
        return Response(tr("This agent is paused", lg=lg) + "\n", 409, mimetype="text/plain")
    try:
        r = chat_post(c, aid, u["id"], "user", {"body": text[:CHAT_MAX]}, files[:CHAT_FILES_MAX])
    except BadInput as e:
        return Response(f"Kalmido: {e}\n", 400, mimetype="text/plain")
    chat_emit(c, aid, r)
    c.commit()
    chat_unlink_trimmed()
    name = user_names(c, [aid]).get(aid, "")
    print("drop: chat message", r["id"], "user", u["id"], "agent", aid, len(files), "files", flush=True)
    return Response(tr("Kalmido: sent to {0}", name, lg=lg) + "\n", mimetype="text/plain")


@app.get("/robots.txt")
def robots_txt():  # 2.29.0 (#1026): was a redirect to the sign-in page
    body = "User-agent: *\n" + (f"Disallow: {PUB_PREFIX}\nDisallow: /f/\nDisallow: {ICAL_PREFIX}\nDisallow: /api/\n" if SEARCH_INDEX
                                else "Disallow: /\n")
    r = Response(body, mimetype="text/plain")
    r.headers["Cache-Control"] = "public, max-age=3600"
    return r


@app.get("/manifest.json")
def manifest():
    """static/manifest.json with description + lang in the UI language."""
    with open(os.path.join(app.static_folder, "manifest.json"), encoding="utf-8") as f:
        m = json.load(f)
    lg = lang()
    m["lang"], m["description"] = lg, tr("Tasks, projects, calendar, habits, focus", lg=lg)
    m["kalmido_max_file_mb"] = MAX_FILE_MB  # 2.143.0 C2 (#2154): the service worker's limit for shared files (browsers ignore the key)
    # long-press menu of the installed app (Android / desktop); the client handles these start URLs
    m["shortcuts"] = [{"name": tr(n, lg=lg), "short_name": tr(n, lg=lg), "url": u,
                       "icons": [{"src": f"/static/shortcuts/{k}-{z}.png", "sizes": f"{z}x{z}", "type": "image/png"} for z in (96, 192)]}
                      for k, n, u in (("new", N_("New task"), "/?action=new"), ("capture", N_("Quick add"), "/?action=capture"),
                                      ("today", N_("Today"), "/#today"),
                                      ("news", N_("News"), "/#news"), ("search", N_("Search"), "/#search"))]
    # 2.125.0 C (#2121): start / stop the timer from the home screen, only for a signed-in person with the module on
    u = getattr(g, "user", None)
    if u and "time" in (usettings(db(), u["id"]).get("features") or "").split(",") and time_all():
        m["shortcuts"].append({"name": tr("Start / stop timer", lg=lg), "short_name": tr("Timer", lg=lg), "url": "/?action=timer",
                               "icons": [{"src": f"/static/shortcuts/timer-{z}.png", "sizes": f"{z}x{z}", "type": "image/png"} for z in (96, 192)]})
    return Response(json.dumps(m, ensure_ascii=False, indent=2), mimetype="application/json")


@app.get("/sw.js")
def sw():
    r = send_from_directory(app.static_folder, "sw.js")
    r.headers["Cache-Control"] = "no-cache"
    return r


_SWM = {}


@app.get("/sw-manifest.json")
def sw_manifest():
    """2.149.0 B (#2506): what the service worker precaches (the lists SHELL / LAZY / LAZY_CSS in static/sw.js stay the one
    source), each static file with its content hash. The worker keeps a file under "<url>?v=<hash>" and takes an unchanged
    one over from its old cache on an update instead of loading it again. Computed here, so it can never be out of date."""
    path = os.path.join(app.static_folder, "sw.js")
    mt = os.path.getmtime(path)
    if _SWM.get("mt") != mt or time.monotonic() - _SWM.get("at", 0) > 5:
        with open(path, encoding="utf-8") as f:
            urls = [u for blk in _SW_LISTS_RE.findall(f.read()) for u in re.findall(r"'(/static/[\w./-]+)'", blk)]
        _SWM.update(mt=mt, at=time.monotonic(), urls=list(dict.fromkeys(urls)))
    files = {}
    from ..core.i18nparts import i18np_url_ver  # 2.191.0 A (#1410 #2518)
    for u in _SWM["urls"]:
        h = static_hash(u[8:]) or i18np_url_ver(u)
        if h:
            files[u] = h
    r = jsonify(v=1, files=files)
    r.headers["Cache-Control"] = "no-cache"
    return r


@app.get("/api/health")
def health():
    db().execute("SELECT 1").fetchone()
    return jsonify(ok=True)


@app.get("/api/version")
def version():
    from ..agents.chat import task_typing_for
    c = db()
    v, n, cs, t, sp, a = version_sigs(c, me())  # 2.149.0 C (#2507): one statement instead of ten (same values)
    return jsonify(v=v, app=APP_VERSION, n=n, c=cs, t=t,  # app: 2.27.0 (#968), t: 2.17.0 (#419)
                   ty=task_typing_for(c, me()),  # ty: 2.22.0 (#693) who is writing a comment where
                   sp=sp,  # sp: 2.32.0 (#1081) a new step of an agent for me (the open chat fetches)
                   a=a)  # a: 2.41.0 (#1376) a change counter per area (tasks, comments, agentchat, team, office, ...)


def version_sigs(c, uid):
    """2.149.0 C (#2507): the values of the 4-second poll -- the version, news_sig, cal_sig, tchat_sig, steps_sig and
    lv_versions -- read in ONE statement (each module keeps its query + formatting: *_sig_q / *_sig_fmt, the single
    functions use the same). Returns (v, n, c, t, sp, a)."""
    from ..collab.news import news_sig_fmt, news_sig_q
    from ..calendars.subscriptions import cal_sig_fmt, cal_sig_q
    from ..collab.teamchat import TCHAT_SIG_COLS, tchat_sig_fmt, tchat_sig_q
    from ..agents.steps import steps_sig_fmt, steps_sig_q
    parts = [("SELECT (SELECT value FROM settings WHERE key='version')", (), 1), (*news_sig_q(uid), 2), (*cal_sig_q(uid), 3),
             (*steps_sig_q(uid), 1), (*lv_versions_q(), 2)]
    chat = collab_all()
    if chat:
        parts.append((*tchat_sig_q(uid), TCHAT_SIG_COLS))
    sql = "SELECT * FROM " + " CROSS JOIN ".join(f"({q}) p{i}" for i, (q, _, _) in enumerate(parts))
    row = c.execute(sql, tuple(x for _, a, _ in parts for x in a)).fetchone()
    cols, i = [], 0
    for _, _, k in parts:
        cols.append(tuple(row[i:i + k]))
        i += k
    v = cols[0][0] if cols[0][0] is not None else GLOBAL_DEFAULTS.get("version", "")
    return (int(v), news_sig_fmt(cols[1]), cal_sig_fmt(cols[2]), tchat_sig_fmt(cols[5]) if chat else "",
            steps_sig_fmt(cols[3]), lv_versions_fmt(cols[4]))
