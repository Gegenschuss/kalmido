"""HTML pages, security headers, /api/version, the share target, quick capture, /drop and the ntfy share inbox."""
import json
import mimetypes
import os
import re
import uuid
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from flask import jsonify, redirect, request, Response, send_from_directory

from ..core.config import app, APP_VERSION, ATT_DIR, MAX_FILE_MB, ntfy_attachment_url, NTFY_IN, safe_urlopen
from ..core.i18n import lang, N_, tr, trn
from ..core.db import bump, connect, db, default_uid, err, gset, gsetting, iso, now_utc
from ..accounts.session import client_ip, GATE, me
from ..core.access import my_inbox


# ---------------------------------------------------------------- pages

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; connect-src 'self'; manifest-src 'self'; worker-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")
PERMISSIONS_POLICY = ("camera=(), microphone=(), geolocation=(), payment=(), usb=(), serial=(), bluetooth=(), "
                      "midi=(), hid=(), magnetometer=(), gyroscope=(), accelerometer=(), display-capture=(), "
                      "browsing-topics=()")


@app.after_request
def headers(resp):
    # own CSPs (attachments, Paperless thumbnails) are kept; everything else gets the app CSP
    resp.headers.setdefault("Content-Security-Policy", CSP)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
    if request.is_secure:  # https (directly or from a trusted proxy): browsers stay on https; a proxy's own header wins
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    if request.path.startswith("/api/") and not request.path.startswith(("/api/attachments/", "/api/chat-files/", "/api/avatar/", "/api/list-icon/", "/api/list-files/")):
        resp.headers["Cache-Control"] = "no-store"
    return resp


_INDEX = {}


def index_page():
    """index.html with the version of this code (2.27.0, #968): the client compares it with /api/version "app" and offers a reload
    when the server runs a newer version than the code in the browser."""
    path = os.path.join(app.static_folder, "index.html")
    mt = os.path.getmtime(path)
    if _INDEX.get("mt") != mt:
        with open(path, encoding="utf-8") as f:
            _INDEX.update(mt=mt, html=f.read().replace('<meta name="kalmido-version" content="">',
                                                       f'<meta name="kalmido-version" content="{APP_VERSION}">', 1))
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
    return err(tr("Upload too large (max. {0} MB per file)", MAX_FILE_MB), 413)


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
    tid = c.execute("INSERT INTO tasks(list_id,title,content,sort,created_at,updated_at,tt_id,created_by,url,assignee_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (inbox, (title or tr("Shared", lg=lang(c, uid)))[:300], content or "", srt, ts, ts, tt_id, uid,
                     url if valid_url(url) else None, uid)).lastrowid
    log_act(c, tid, "created", uid=uid)
    return tid


# ---- website link (tasks.url): http/https only, no server-side fetching
URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)


def valid_url(u):
    return bool(u) and len(u) <= 2000 and bool(re.fullmatch(r"https?://[^\s/?#]+[^\s]*", u, re.I))


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


def save_attachment_bytes(c, tid, name, mime, data):
    from ..tasks.attachments import safe_name
    from ..notify.alerts import aa_count, aa_oserr
    from ..admin.hosting import quota_fits
    name = safe_name(name)
    who = c.execute("SELECT created_by FROM tasks WHERE id=?", (tid,)).fetchone()
    who = who[0] if who else None
    if not quota_fits(c, who, len(data)):  # 2.24.0 (#910): storage full -> the task comes without the file (never an error)
        print("share / mail file skipped: storage quota of user", who, "reached", flush=True)
        return
    rel = os.path.join(str(tid), f"{uuid.uuid4().hex[:12]}-{name}")
    try:
        os.makedirs(os.path.join(ATT_DIR, str(tid)), exist_ok=True)
        with open(os.path.join(ATT_DIR, rel), "wb") as f:
            f.write(data)
    except OSError as e:
        aa_count("storage", "attachments", aa_oserr(e))
        raise
    mime = mime if mime and mime != "application/octet-stream" else (mimetypes.guess_type(name)[0] or "application/octet-stream")
    c.execute("INSERT INTO attachments(task_id,name,mime,size,path,created_at,user_id) VALUES(?,?,?,?,?,?,?)",
              (tid, name, mime, len(data), rel, iso(now_utc()), who))


def inbox_user(c):
    """User whose inbox receives the ntfy share inbox (NTFY_INBOX_USER, default the first admin)."""
    if NTFY_IN["user"]:
        r = c.execute("SELECT id FROM users WHERE username=? AND disabled=0", (NTFY_IN["user"],)).fetchone()
        if r:
            return r[0]
    return default_uid(c)


def ntfy_inbox_import(c, m):
    """One ntfy message -> one inbox task (+ attachment). Idempotent via tt_id 'ntfy:<id>'."""
    mid = m["id"]
    uid = inbox_user(c)
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
            url = ntfy_attachment_url(att["url"])
            if not url:
                print("ntfy inbox: attachment URL is not on the ntfy server, not fetched:", repr(str(att["url"])[:200]), flush=True)
            else:
                req = urllib.request.Request(url, headers={"Authorization": f"Bearer {NTFY_IN['token']}"})
                try:
                    with safe_urlopen(req, timeout=120) as r:
                        data = r.read(MAX_FILE_MB * 1024 * 1024 + 1)
                except (urllib.error.URLError, OSError, ValueError) as e:
                    print("ntfy inbox: attachment download failed:", e, flush=True)
                    data = None
                if data and len(data) <= MAX_FILE_MB * 1024 * 1024:  # 2.13.2: never a 0-byte file
                    save_attachment_bytes(c, tid, str(att.get("name") or "datei"), str(att.get("type") or ""), data)
        print("ntfy inbox: task", tid, "user", uid, repr(title), "attachment" if att else "", flush=True)
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


@app.post("/share")
def share_post():
    """Android share sheet with files, when the service worker did not catch it (first launch):
    create the task in the inbox right away and open it."""
    from ..tasks.attachments import safe_name, save_attachments
    c = db()
    files = [f for key in request.files for f in request.files.getlist(key) if f and f.filename]
    print("share POST (server path): content_length", request.content_length, "form keys", list(request.form.keys()),
          "file keys", list(request.files.keys()), {k: request.form.get(k) for k in ("title", "text", "url")},
          [(f.filename, f.mimetype) for f in files], flush=True)
    text, url = (request.form.get("text") or "").strip(), (request.form.get("url") or "").strip()
    m = None if url else URL_RE.search(text)  # most apps put the link into "text"
    if m:
        url, text = m.group(0).rstrip(".,;:!?"), text[:m.start()] + text[m.end():]
    title = (request.form.get("title") or "").strip() or re.sub(r"\s+", " ", text.replace(url, "") if url else text).strip(" -–—|:·") \
        or (url_title(url) if url else "") or (os.path.splitext(safe_name(files[0].filename))[0] if files else tr("Shared"))
    tid = new_inbox_task(c, me(), title, "", url=url or None)  # the link goes into the link field
    save_attachments(c, tid, files)
    bump(c)
    c.commit()
    return redirect(f"/#t/{tid}", 303)


# Placeholder texts some Android apps put next to a shared file; never a useful title.
SHARE_PLACEHOLDERS = ("You received a file:", "Ein Bild wurde mit Dir geteilt", "Ein Bild wurde mit dir geteilt")


def drop_user(c, auth):
    """User whose personal drop token is in the Authorization header (constant-time compare)."""
    if not auth.startswith("Bearer "):
        return None
    got, hit = auth[7:].encode(), None
    for r in c.execute("SELECT * FROM users WHERE drop_token IS NOT NULL AND drop_token!='' AND disabled=0"):
        if secrets.compare_digest(got, r["drop_token"].encode()):
            hit = r
    return hit


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
    from ..personal.timetrack import BadInput
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


@app.get("/manifest.json")
def manifest():
    """static/manifest.json with description + lang in the UI language."""
    with open(os.path.join(app.static_folder, "manifest.json"), encoding="utf-8") as f:
        m = json.load(f)
    lg = lang()
    m["lang"], m["description"] = lg, tr("Tasks, lists, calendar, habits, focus", lg=lg)
    # long-press menu of the installed app (Android / desktop); the client handles these start URLs
    m["shortcuts"] = [{"name": tr(n, lg=lg), "short_name": tr(n, lg=lg), "url": u,
                       "icons": [{"src": f"/static/shortcuts/{k}-{z}.png", "sizes": f"{z}x{z}", "type": "image/png"} for z in (96, 192)]}
                      for k, n, u in (("new", N_("New task"), "/?action=new"), ("capture", N_("Quick add"), "/?action=capture"),
                                      ("today", N_("Today"), "/#today"),
                                      ("news", N_("News"), "/#news"), ("search", N_("Search"), "/#search"))]
    return Response(json.dumps(m, ensure_ascii=False, indent=2), mimetype="application/json")


@app.get("/sw.js")
def sw():
    r = send_from_directory(app.static_folder, "sw.js")
    r.headers["Cache-Control"] = "no-cache"
    return r


@app.get("/api/health")
def health():
    db().execute("SELECT 1").fetchone()
    return jsonify(ok=True)


@app.get("/api/version")
def version():
    from ..collab.news import news_sig
    from ..calendars.subscriptions import cal_sig
    from ..collab.teamchat import tchat_sig
    from ..agents.chat import task_typing_for
    c = db()
    return jsonify(v=int(gsetting(c, "version")), app=APP_VERSION, n=news_sig(c, me()), c=cal_sig(c, me()), t=tchat_sig(c, me()),  # app: 2.27.0 (#968), t: 2.17.0 (#419)
                   ty=task_typing_for(c, me()))  # ty: 2.22.0 (#693) who is writing a comment where
