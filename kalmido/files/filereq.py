"""2.122.0 A (#2097): file requests ("Dateien anfordern") -- a client uploads documents into a folder of the file store
through a public link, without an account.

- Somebody who may write in a folder creates a request there: a title and a note for the client, an end date (at most
  FRQ_DAYS_MAX days ahead), the size per file, how many files in all, the allowed kinds (groups of endings, FRQ_TYPES; never
  programs, HTML or SVG) and optionally a subfolder per request. The link /u/<token> (192 random bits) is stored sealed (it
  can be copied again) and found by its SHA-256, like the forms' links.
- The page shows the title, the note and a file field (drag and drop and a progress bar with the small script /u/v/up.js;
  without it the plain form works). It never shows files, folder names or other uploads. An unknown, expired, revoked or
  dead link gets the same answer (frq_gone). A link dies when the request is revoked / deleted / over, the folder is in the
  trash or moved into another workspace, or its creator lost the write right there (or the account is disabled).
- An upload lands in the folder (or the request's subfolder) as a file of the creator: the shared upload path of the file
  store (files/store.py fs_put: virus scan, photo metadata, sealed, the creator's storage quota, a free name instead of
  overwriting). The type comes from the name, never from the sender; the content must fit it (files/scan.py). The history
  says "received through a file request". A documents inbox folder recognises it as usual (docs/ingest.py inbox_scan).
- Limits: views and sends per address and minute, sends per link and hour, bytes per link and day (FRQ_DAY_MB); the body
  is refused from its length before it is read (h6d / max_content_length) and every file is read with its cap.
- The creator gets ONE News item (+ push) per request and FRQ_NOTIFY_S; later uploads in that time raise its count.
  Event "filereq" of the notification settings (News and push can be switched off).
- Agents and children do not manage requests (people only, no API: the client is the uploader).
"""
import hashlib
import hmac
import html
import json
import mimetypes
import os
import re
import secrets
import time
from datetime import timedelta

from flask import g, jsonify, request, Response

from ..core.config import app, MAX_FILE_MB, PUBLIC_URL
from ..core.pg import insert_id, system_ctx
from ..core.i18n import lang, LANGS, N_, tr, trn
from ..core.db import body, bump, db, err, iso, now_utc, write_lock
from ..core.access import acx_anon_bind, Denied
from ..accounts.session import _accept_lang, _token_hash, me, rate_ip
from ..accounts.login import auth_key, seal, unseal
from ..api.v1 import hit_limit
from ..lists.public import BOT_ERROR, PUB_CSP, pub_html, public_links_on
from .store import fs_chain, fs_deleted, fs_role, fs_put, safe_fs_name, _free_name, _now, _place

FRQ_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{20,64}")
FRQ_TITLE_MAX, FRQ_NOTE_MAX, FRQ_NAME_MAX = 120, 2000, 120
FRQ_DAYS_DEFAULT, FRQ_DAYS_MAX = 14, 90
FRQ_FILES_DEFAULT, FRQ_FILES_MAX = 20, 200
FRQ_MB_DEFAULT = min(25, MAX_FILE_MB)
FRQ_PER_FOLDER = 50   # requests per folder (not deleted)
FRQ_PER_POST = 10     # files in one send of the plain form (the script sends one per request)
FRQ_VIEW_RATE, FRQ_SEND_RATE, FRQ_SEND_HOUR = 60, 30, 300  # per address / minute, per address / minute, per link / hour
FRQ_NOTIFY_S = 600
FRQ_MIN_S, FRQ_MAX_S = 2, 24 * 3600  # the page's signed stamp: not sooner, not later after loading
try:  # a typo in the variable must not stop the server
    FRQ_DAY_MB = max(1, int(os.environ.get("KALMIDO_FILE_REQUEST_MB_DAY") or 1000))
except ValueError:
    FRQ_DAY_MB = 1000
# the kinds a request may allow (endings); the default is documents + pictures. Programs, scripts, HTML and SVG never
# (tasks/attachments.py EXEC_EXT, FRQ_NEVER) -- also not inside an allowed ending (the content check, frq_content_ok)
FRQ_TYPES = {
    "docs": ("pdf", "txt", "csv", "md", "rtf", "odt", "ods", "odp", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "xml", "eml"),
    "images": ("jpg", "jpeg", "png", "gif", "webp", "heic", "heif", "avif", "tif", "tiff", "bmp"),
    "design": ("ai", "eps", "psd", "indd", "idml"),
    "archives": ("zip", "7z", "rar", "tar", "gz"),
    "media": ("mp3", "m4a", "wav", "aac", "ogg", "mp4", "mov", "m4v", "webm"),
}
FRQ_TYPES_DEFAULT = ("docs", "images")
FRQ_NEVER = {"html", "htm", "xhtml", "shtml", "svg", "svgz", "js", "mjs", "php", "py", "pl", "rb", "swf", "xsl", "xslt"}
# endings whose content the magic bytes know: the file must really be one of them
FRQ_MAGIC = {"pdf": ("application/pdf",), "jpg": ("image/jpeg",), "jpeg": ("image/jpeg",), "png": ("image/png",),
             "gif": ("image/gif",), "webp": ("image/webp",), "heic": ("image/heic", "image/heif"), "heif": ("image/heic", "image/heif"),
             "avif": ("image/avif",), "bmp": ("image/bmp",), "zip": ("application/zip",),
             "docx": ("application/zip",), "xlsx": ("application/zip",), "pptx": ("application/zip",), "odt": ("application/zip",),
             "ods": ("application/zip",), "odp": ("application/zip",)}



# the page's texts that go through the local t() helper (marked so the translation check sees them)
FRQ_PAGE_TEXTS = (N_("Not uploaded"), N_("Thank you! Your files have arrived."), N_("The link works until {0}."),
                  N_("this file type is not accepted"), N_("too large"), N_("Your name (optional)"))

def frq_ext(name):
    n = (name or "").lower()
    return n.rsplit(".", 1)[1] if "." in n.strip(".") else ""


def frq_allowed(types):
    """The endings of the kinds in types (a list of FRQ_TYPES keys)."""
    out = set()
    for t in types:
        out.update(FRQ_TYPES.get(t, ()))
    return out


def frq_types_of(r):
    return [t for t in (r["types"] or "").split(",") if t in FRQ_TYPES]


def frq_content_ok(name, data):
    """False when the bytes are a program / HTML / SVG, or an ending the magic bytes know does not match them."""
    from ..tasks.attachments import EXEC_EXT
    from .scan import SC_EXEC, _sc_magic
    ext = frq_ext(name)
    if not ext or ext in EXEC_EXT or ext in FRQ_NEVER:
        return False
    got = _sc_magic(data)
    if got in (SC_EXEC, "text/html", "image/svg+xml"):
        return False
    want = FRQ_MAGIC.get(ext)
    return not want or got in want


# ---------------------------------------------------------------- the request rows
def frq_state(r, now=None):
    now = now or _now()
    if r["deleted_at"]:
        return "deleted"
    if r["revoked_at"]:
        return "revoked"
    if (r["expires_at"] or "") <= now:
        return "expired"
    return "active"


def frq_alive(c, r):
    """Does the link of request r still work? (not revoked / over, the folder outside the trash and in its workspace, the
    creator active and with the write right there). Reads across organisations: the caller decides (system_ctx for a token)."""
    if frq_state(r) != "active":
        return False
    u = c.execute("SELECT disabled, kind FROM users WHERE id=?", (r["created_by"],)).fetchone()
    if not u or u["disabled"] or (u["kind"] or "user") == "agent":
        return False
    chain = fs_chain(c, r["node_id"])
    if not chain or fs_deleted(chain) or chain[0]["kind"] != "folder" or (chain[0]["org_id"] or None) != (r["org_id"] or None):
        return False
    return fs_role(c, r["node_id"], r["created_by"], chain=chain) in ("owner", "edit")


def frq_url(c, r):
    return PUBLIC_URL.rstrip("/") + "/u/" + unseal(c, f"frq:{r['node_id']}", r["token"])


def frq_json(c, r, role, names=None):
    """The request for the app; the link only for its creator and the folder's owners."""
    from .web import _names
    names = names if names is not None else _names(c, [r["created_by"]])
    st = frq_state(r)
    mine = r["created_by"] == me()
    out = {"id": r["id"], "node_id": r["node_id"], "title": r["title"], "note": r["note"], "expires_at": r["expires_at"],
           "max_mb": r["max_mb"], "max_files": r["max_files"], "types": frq_types_of(r), "subfolder": bool(r["subfolder"]),
           "count": r["count"], "bytes": r["bytes"], "last_at": r["last_at"], "created_at": r["created_at"],
           "created_by": r["created_by"], "created_by_name": names.get(r["created_by"], ""), "state": st,
           "mine": mine, "manage": mine or role == "owner"}
    if st == "active" and not frq_alive(c, r):
        out["state"] = "inactive"  # the creator lost the write right (or the account is disabled): the link does not work
    if out["manage"]:
        out["url"] = frq_url(c, r)
    return out


def _gate():
    from ..agents.core import is_agent
    if not g.user or is_agent(g.user) or g.user["kid"]:
        raise Denied(403, tr("Only people can request files"))


def _folder(c, nid, write=True):
    from .store import need_node
    n = need_node(c, nid, write=write)
    if n["kind"] != "folder":
        raise Denied(409, tr("Not a folder"))
    return n


def _int(b, k, lo, hi):
    v = b.get(k)
    if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
        raise Denied(400, tr("Invalid value: {0}", k))
    return v


def frq_clean(b, new=False):
    """The fields of a request from the body {title, note, expires_at (a date / ISO time) | days, max_mb, max_files, types,
    subfolder} (PATCH: only what is given; revoked separately)."""
    if not isinstance(b, dict):
        raise Denied(400, tr("Invalid data"))
    out = {}
    if "title" in b or new:
        t = re.sub(r"\s+", " ", str(b.get("title") or "")).strip()[:FRQ_TITLE_MAX]
        if not t:
            raise Denied(400, tr("Title missing"))
        out["title"] = t
    if "note" in b:
        if not isinstance(b["note"], str):
            raise Denied(400, tr("Invalid value: {0}", "note"))
        out["note"] = b["note"].strip()[:FRQ_NOTE_MAX]
    if "days" in b:
        out["expires_at"] = iso(now_utc() + timedelta(days=_int(b, "days", 1, FRQ_DAYS_MAX)))
    elif "expires_at" in b:
        from .web import _expiry
        x = _expiry(b["expires_at"], b.get("tz"))
        if not x:
            raise Denied(400, tr("Please choose until when the link works"))
        out["expires_at"] = x
    elif new:
        raise Denied(400, tr("Please choose until when the link works"))
    if "expires_at" in out:
        if out["expires_at"] <= _now():
            raise Denied(400, tr("The end date must lie in the future"))
        if out["expires_at"] > iso(now_utc() + timedelta(days=FRQ_DAYS_MAX + 1)):
            raise Denied(400, tr("A file request works at most {0} days", FRQ_DAYS_MAX))
    if "max_mb" in b:
        out["max_mb"] = _int(b, "max_mb", 1, MAX_FILE_MB)
    if "max_files" in b:
        out["max_files"] = _int(b, "max_files", 1, FRQ_FILES_MAX)
    if "types" in b:
        t = b["types"]
        if not isinstance(t, list) or not t or any(x not in FRQ_TYPES for x in t):
            raise Denied(400, tr("Invalid value: {0}", "types"))
        out["types"] = ",".join(k for k in FRQ_TYPES if k in t)
    if "subfolder" in b:
        if not isinstance(b["subfolder"], bool):
            raise Denied(400, tr("Invalid value: {0}", "subfolder"))
        out["subfolder"] = 1 if b["subfolder"] else 0
    return out


def _row(c, rid, manage=True):
    """The request rid and the asker's role on its folder; 404 without the write right there, 403 to manage someone else's."""
    r = c.execute("SELECT * FROM fs_upload_requests WHERE id=?", (rid,)).fetchone()
    if not r:
        raise Denied(404)
    n = _folder(c, r["node_id"])
    if manage and r["created_by"] != me() and n["role"] != "owner":
        raise Denied(403)
    return r, n["role"]


@app.get("/api/files/nodes/<int:nid>/requests")
def frq_list(nid):
    """The file requests of a folder (people with the write right there)."""
    from .web import _names
    c = db()
    _gate()
    n = _folder(c, nid)
    rows = c.execute("SELECT * FROM fs_upload_requests WHERE node_id=? AND deleted_at IS NULL ORDER BY id DESC", (nid,)).fetchall()
    names = _names(c, [r["created_by"] for r in rows])
    return jsonify(requests=[frq_json(c, r, n["role"], names) for r in rows], public_links=public_links_on(c),
                   limits={"max_mb": MAX_FILE_MB, "max_files": FRQ_FILES_MAX, "days": FRQ_DAYS_MAX, "types": list(FRQ_TYPES),
                           "default_mb": FRQ_MB_DEFAULT, "default_files": FRQ_FILES_DEFAULT, "default_days": FRQ_DAYS_DEFAULT,
                           "default_types": list(FRQ_TYPES_DEFAULT)})


@app.post("/api/files/nodes/<int:nid>/requests")
def frq_create(nid):
    """{title, note?, days | expires_at (+ tz), max_mb?, max_files?, types?, subfolder?} -> 201 with its link."""
    c = db()
    _gate()
    n = _folder(c, nid)
    if not public_links_on(c):
        return err(tr("Public links are turned off on this server"), 409)
    f = frq_clean(body(), new=True)
    f.setdefault("max_mb", FRQ_MB_DEFAULT)
    f.setdefault("max_files", FRQ_FILES_DEFAULT)
    f.setdefault("types", ",".join(FRQ_TYPES_DEFAULT))
    if c.execute("SELECT COUNT(*) FROM fs_upload_requests WHERE node_id=? AND deleted_at IS NULL", (nid,)).fetchone()[0] >= FRQ_PER_FOLDER:
        return err(tr("At most {0} file requests per folder", FRQ_PER_FOLDER), 409)
    tok = secrets.token_urlsafe(24)
    f.update(node_id=nid, org_id=n["org_id"], created_by=me(), token=seal(c, f"frq:{nid}", tok), token_hash=_token_hash(tok),
             created_at=_now())
    rid = insert_id(c, f"INSERT INTO fs_upload_requests({','.join(f)}) VALUES({','.join('?' * len(f))})", list(f.values()))
    _log(c, nid, me(), "frq_create", f["title"])
    bump(c)
    c.commit()
    return jsonify(frq_json(c, c.execute("SELECT * FROM fs_upload_requests WHERE id=?", (rid,)).fetchone(), n["role"])), 201


@app.patch("/api/files/requests/<int:rid>")
def frq_update(rid):
    """{title?, note?, days? | expires_at?, max_mb?, max_files?, types?, subfolder?, revoked?: true | false} (its creator or
    an owner of the folder). revoked: the link stops at once (false = back, the undo of a revoke)."""
    c = db()
    _gate()
    r, role = _row(c, rid)
    if r["deleted_at"]:
        raise Denied(404)
    b = body()
    f = frq_clean({k: v for k, v in b.items() if k != "revoked"})
    if "revoked" in b:
        if not isinstance(b["revoked"], bool):
            raise Denied(400, tr("Invalid value: {0}", "revoked"))
        f["revoked_at"] = (r["revoked_at"] or _now()) if b["revoked"] else None
    if f:
        c.execute(f"UPDATE fs_upload_requests SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), rid])
        if "revoked_at" in f and bool(f["revoked_at"]) != bool(r["revoked_at"]):
            _log(c, r["node_id"], me(), "frq_revoke" if f["revoked_at"] else "frq_open", r["title"])
    bump(c)
    c.commit()
    return jsonify(frq_json(c, c.execute("SELECT * FROM fs_upload_requests WHERE id=?", (rid,)).fetchone(), role))


@app.delete("/api/files/requests/<int:rid>")
def frq_delete(rid):
    """Removes the request from the folder's list (deleted_at; the link stops; POST .../restore brings it back)."""
    c = db()
    _gate()
    r, _role = _row(c, rid)
    if not r["deleted_at"]:
        c.execute("UPDATE fs_upload_requests SET deleted_at=? WHERE id=?", (_now(), rid))
        _log(c, r["node_id"], me(), "frq_delete", r["title"])
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.post("/api/files/requests/<int:rid>/restore")
def frq_restore(rid):
    c = db()
    _gate()
    r, role = _row(c, rid)
    if r["deleted_at"]:
        c.execute("UPDATE fs_upload_requests SET deleted_at=NULL WHERE id=?", (rid,))
    bump(c)
    c.commit()
    return jsonify(frq_json(c, c.execute("SELECT * FROM fs_upload_requests WHERE id=?", (rid,)).fetchone(), role))


def _log(c, nid, uid, action, detail=""):
    """The folder's / file's history (files/store.py fs_log): who = the request's creator, also for the client's uploads."""
    c.execute("INSERT INTO fs_log(node_id,user_id,agent,action,detail,at) VALUES(?,?,?,?,?,?)",
              (int(nid), uid, 0, action, str(detail or "")[:300], _now()))


# ---------------------------------------------------------------- the page /u/<token>
def frq_find(c, token):
    """The live request of a token (frq_alive), else None. A visitor then works inside exactly the folder's workspace."""
    if not FRQ_TOKEN_RE.fullmatch(token or "") or not public_links_on(c):
        return None
    with system_ctx(c):  # resolve the token (one row) across organisations, like the forms' links
        r = c.execute("SELECT * FROM fs_upload_requests WHERE token_hash=?", (_token_hash(token),)).fetchone()
        if not r or not frq_alive(c, r):
            return None
    g.user = None  # the page is the same for everybody (signed in or not): the creator's rights decide, never the visitor's
    acx_anon_bind(c, r["org_id"])
    return r


def frq_lang(c, r):
    for part in (request.headers.get("Accept-Language") or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in LANGS:
            return code
    return lang(c, r["created_by"])


def frq_headers(resp):
    """The public links' headers; plus the page's own small script (drag and drop, progress) and its sends to itself."""
    resp.headers["Content-Security-Policy"] = PUB_CSP + "; script-src 'self'; connect-src 'self'"
    return resp


def frq_gone(lg=None):
    """The same answer for an unknown, expired, revoked and dead link (no oracle)."""
    lg = lg or _accept_lang()
    if _wants_json():
        return jsonify(error=tr("This upload link does not exist or is no longer open.", lg=lg)), 404
    return pub_html(tr("Link not available", lg=lg), f'<div class="msg">{BOT_ERROR}<h1>{html.escape(tr("Link not available", lg=lg))}</h1>'
                    f'<p>{html.escape(tr("This upload link does not exist or is no longer open.", lg=lg))}</p></div>', lg, 404, foot=False)


def _wants_json():
    return request.method == "POST" and request.headers.get("X-Kalmido-Upload") == "1"


def _msg(title, text, lg, code=200, link=None):
    if _wants_json():
        return jsonify(error=text), code
    e = html.escape
    return pub_html(title, f'<div class="msg"><h1>{e(title)}</h1><p>{e(text)}</p>'
                    + (f'<a class="btn" href="{e(link[0])}">{e(link[1])}</a>' if link else "") + '</div>', lg, code, foot=False)


def frq_stamp(c, rid, t=None, n=None):
    """The signed time the page was made (request id + seconds + a random part, server key)."""
    t = int(time.time()) if t is None else t
    n = secrets.token_hex(6) if n is None else n
    sig = hmac.new(auth_key(c), f"kalmido-frq-stamp|{rid}|{t}|{n}".encode(), hashlib.sha256).hexdigest()[:32]
    return f"{t}.{n}.{sig}"


def frq_stamp_age(c, rid, v):
    t, _, rest = (v or "").partition(".")
    n, _, sig = rest.partition(".")
    if not t.isdigit() or len(t) > 12 or not re.fullmatch(r"[0-9a-f]{12}", n) or not hmac.compare_digest(frq_stamp(c, rid, int(t), n), f"{t}.{n}.{sig}"):
        return None
    return time.time() - int(t)


def _more(n, lg):
    return trn("At most {0} more file.", "At most {0} more files.", n, lg=lg)


def _left(r):
    return max(0, int(r["max_files"]) - int(r["count"] or 0))


def _page(c, r, token, lg, error="", name=""):
    e = html.escape
    t = lambda s, *a: tr(s, *a, lg=lg)  # noqa: E731
    exts = sorted(frq_allowed(frq_types_of(r)))
    left = _left(r)
    intro = "".join(f"<p>{e(p)}</p>" for p in (r["note"] or "").split("\n") if p.strip())
    facts = trn("Up to {0} file, at most {1} MB. Allowed: {2}.", "Up to {0} files, at most {1} MB each. Allowed: {2}.", left, r["max_mb"],
                ", ".join(exts), lg=lg)
    until = t("The link works until {0}.", (r["expires_at"] or "")[:10])
    if not left:
        return _msg(t("Thank you!"), t("This upload link takes no more files."), lg)
    form = (f'<form method="post" action="/u/{e(token)}" class="fform frq-form" enctype="multipart/form-data" '
            f'data-max="{int(r["max_mb"]) * 1024 * 1024}" data-left="{left}" data-ext="{e(",".join(exts))}" '
            f'data-t-done="{e(t("Thank you! Your files have arrived."))}" data-t-fail="{e(t("Not uploaded"))}" '
            f'data-t-big="{e(t("too large"))}" data-t-type="{e(t("this file type is not accepted"))}" '
            f'data-t-many="{e(_more(left, lg))}">'
            f'<label for="fq-file">{e(t("Files"))}</label>'
            f'<div class="frq-drop"><input id="fq-file" name="file" type="file" multiple required accept="{e(",".join("." + x for x in exts))}">'
            f'<p class="sub">{e(facts)}</p></div><ul class="frq-list" aria-live="polite"></ul>'
            f'<label for="fq-name">{e(t("Your name (optional)"))}</label>'
            f'<input id="fq-name" name="name" autocomplete="name" maxlength="{FRQ_NAME_MAX}" value="{e(name)}">'
            f'<input type="hidden" name="stamp" value="{e(frq_stamp(c, r["id"]))}">'
            '<div class="hp" aria-hidden="true"><label for="fq-web">Website</label><input id="fq-web" name="website" tabindex="-1" autocomplete="off"></div>'
            f'<button type="submit">{e(t("Upload"))}</button></form>')
    main = (f'<header><h1>{e(r["title"])}</h1></header>' + (f'<div class="intro">{intro}</div>' if intro else "")
            + (f'<p class="err" role="alert">{e(error)}</p>' if error else "") + form
            + f'<p class="sub frq-until">{e(until)}</p><script src="/u/v/up.js" defer></script>')
    return frq_headers(pub_html(r["title"], main, lg, 400 if error else 200, foot=True))


@app.get("/u/<token>")
def frq_page(token):
    c = db()
    if hit_limit("frqv:" + rate_ip(), FRQ_VIEW_RATE):
        return _msg(tr("Too many requests"), tr("Please wait a minute and try again."), _accept_lang(), 429)
    r = frq_find(c, token)
    if not r:
        return frq_gone()
    return _page(c, r, token, frq_lang(c, r))


def frq_day_full(c, rid, n, book=True):
    """True (= refuse) when n more bytes would pass FRQ_DAY_MB of the request today; else they are counted (mail_counts,
    one row per request; the caller commits). book=False: only the check (review: refused files do not use up the day)."""
    day = now_utc().strftime("%Y-%m-%d")
    k = f"frqd:{rid}"
    cur = c.execute("SELECT n, day FROM mail_counts WHERE k=?", (k,)).fetchone()
    used = cur[0] if cur and cur[1] == day else 0
    if used + n > FRQ_DAY_MB * 1024 * 1024:
        return True
    if not book:
        return False
    c.execute("""INSERT INTO mail_counts(k,day,n) VALUES(?,?,?) ON CONFLICT(k) DO UPDATE SET
                 n=CASE WHEN mail_counts.day=excluded.day THEN mail_counts.n+excluded.n ELSE excluded.n END, day=excluded.day""", (k, day, n))
    return False


def _target(c, r):
    """The folder the files go into: the request's folder, or its own subfolder (made on the first upload, again when it
    was deleted)."""
    if not r["subfolder"]:
        return r["node_id"]
    cur = c.execute("SELECT sub_id FROM fs_upload_requests WHERE id=?", (r["id"],)).fetchone()[0]  # this send may have made it
    if cur:
        ch = fs_chain(c, cur)
        if ch and not fs_deleted(ch) and ch[0]["parent_id"] == r["node_id"] and ch[0]["kind"] == "folder":
            return cur
    uid = r["created_by"]
    owner, org = _place(c, uid, r["node_id"], None)
    ts = _now()
    sid = insert_id(c, "INSERT INTO fs_nodes(parent_id,kind,name,owner_id,org_id,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (r["node_id"], "folder", _free_name(c, r["node_id"], owner, org, safe_fs_name(r["title"])), owner, org, uid, ts, ts))
    _log(c, sid, uid, "frq_upload", r["title"])
    c.execute("UPDATE fs_upload_requests SET sub_id=? WHERE id=?", (sid, r["id"]))
    return sid


@app.post("/u/<token>")
def frq_send(token):
    """The client's upload: multipart file (repeatable; the script sends one per request), name?, stamp, website (honeypot).
    With the header X-Kalmido-Upload: 1 the answer is JSON ({ok, n} or {error}), else a page."""
    from .upsafe import H6D_SLACK, UploadRefused, h6d_read
    from ..admin.hosting import QuotaExceeded
    if hit_limit("frqs:" + rate_ip(), FRQ_SEND_RATE):  # review: before the token lookup (no unbounded database work per request)
        lg0 = _accept_lang()
        return _msg(tr("Too many requests", lg=lg0), tr("Please wait a minute and try again.", lg=lg0), lg0, 429)
    c = db()
    r = frq_find(c, token)
    if not r:
        return frq_gone()
    lg = frq_lang(c, r)
    if request.headers.get("Sec-Fetch-Site", "") == "cross-site":
        return _msg(tr("Not allowed", lg=lg), tr("Please upload the files from the page of the link.", lg=lg), lg, 403)
    if hit_limit(f"frqh:{r['id']}", FRQ_SEND_HOUR, 3600):
        return _msg(tr("Too many requests", lg=lg), tr("Please wait a minute and try again.", lg=lg), lg, 429)
    left = _left(r)
    if not left:
        return _msg(tr("Thank you!", lg=lg), tr("This upload link takes no more files.", lg=lg), lg, 409)
    cap = min(int(r["max_mb"]), MAX_FILE_MB) * 1024 * 1024
    # a body longer than the files it may carry is refused before it is read (werkzeug answers 413)
    request.max_content_length = cap * min(left, FRQ_PER_POST) + H6D_SLACK
    if (request.content_length or 0) > request.max_content_length:
        return _msg(tr("File too large", lg=lg), tr("The file is too large (at most {0} MB).", r["max_mb"], lg=lg), lg, 413)
    fv = request.form
    name = re.sub(r"\s+", " ", (fv.get("name") or "")).strip()[:FRQ_NAME_MAX]
    again = lambda msg, code=400: (jsonify(error=msg), code) if _wants_json() else _page(c, r, token, lg, msg, name)  # noqa: E731
    files = [f for f in request.files.getlist("file") if f and f.filename]
    if fv.get("website"):  # the honeypot: a bot filled the hidden field -> pretend it worked
        return jsonify(ok=True, n=len(files)) if _wants_json() else _msg(tr("Thank you!", lg=lg), tr("Your files have arrived.", lg=lg), lg)
    age = frq_stamp_age(c, r["id"], fv.get("stamp"))
    if age is None or not FRQ_MIN_S <= age <= FRQ_MAX_S:
        return again(tr("Please send the files once more: the page was open for a long time.", lg=lg))
    if not files:
        return again(tr("Please choose at least one file.", lg=lg))
    if len(files) > min(left, FRQ_PER_POST):
        return again(_more(min(left, FRQ_PER_POST), lg))
    allowed = frq_allowed(frq_types_of(r))
    write_lock(c, f"frq:{r['id']}")  # two sends at once: the count stays within max_files
    cnt = c.execute("SELECT count FROM fs_upload_requests WHERE id=?", (r["id"],)).fetchone()[0]
    if cnt + len(files) > int(r["max_files"]):
        return again(_more(max(0, int(r["max_files"]) - cnt), lg), 409)
    saved, size, bad = [], 0, []
    for f in files:
        nm = safe_fs_name(f.filename)
        if frq_ext(nm) not in allowed:
            bad.append(tr("{0}: this file type is not accepted", nm, lg=lg))
            continue
        data = h6d_read(f, cap)
        if len(data) > cap:
            bad.append(tr("{0}: larger than {1} MB", nm, r["max_mb"], lg=lg))
            continue
        if not data:
            bad.append(tr("{0}: the file is empty and was not uploaded", nm, lg=lg))
            continue
        if not frq_content_ok(nm, data):
            bad.append(tr("{0}: this file type is not accepted", nm, lg=lg))
            continue
        from ..admin.hosting import quota_fits
        with system_ctx(c):  # the creator's storage over every workspace (sums only; fs_put checks again in the visitor's context)
            room = quota_fits(c, r["created_by"], len(data))
        if not room:
            bad.append(tr("{0}: there is no room for more files right now.", nm, lg=lg))
            break
        if frq_day_full(c, r["id"], len(data), book=False):
            bad.append(tr("{0}: this link takes no more files today. Please try again tomorrow.", nm, lg=lg))
            break
        try:
            with c.savepoint():
                tgt = _target(c, r)
                nid = fs_put(c, r["created_by"], tgt, nm, data, mimetypes.guess_type(nm)[0] or "application/octet-stream",
                             org_id=r["org_id"])
        except (UploadRefused, ValueError) as x:
            bad.append(str(x))
            continue
        except QuotaExceeded:
            bad.append(tr("{0}: there is no room for more files right now.", nm, lg=lg))
            break
        except Denied:
            c.rollback()
            return frq_gone(lg)
        frq_day_full(c, r["id"], len(data))  # counted only once the file is stored
        _log(c, nid, r["created_by"], "frq_upload", r["title"] + (f" · {name}" if name else ""))
        saved.append(nid)
        size += len(data)
    ts = _now()
    if saved:
        c.execute("UPDATE fs_upload_requests SET count=count+?, bytes=bytes+?, last_at=? WHERE id=?", (len(saved), size, ts, r["id"]))
        frq_notify(c, r, len(saved), name, tgt)
        bump(c)
    c.commit()
    if _wants_json():
        if bad and not saved:
            return jsonify(error=bad[0]), 400
        return jsonify(ok=True, n=len(saved), errors=bad)
    if not saved:
        return again(bad[0] if bad else tr("Please choose at least one file.", lg=lg))
    text = trn("{0} file has arrived.", "{0} files have arrived.", len(saved), lg=lg) + ((" " + " ".join(bad)) if bad else "")
    return _msg(tr("Thank you!", lg=lg), text, lg, 200, (f"/u/{token}", tr("Upload more files", lg=lg)))


# ---------------------------------------------------------------- the creator's News item (+ push), bundled
def frq_notify(c, r, n, name, node):
    """One News item + push per request and FRQ_NOTIFY_S; uploads in between raise the count of the unread item."""
    from ..collab.news import news_add, notif_ok
    from ..collab.comments import collab_user
    from ..notify.push import push_prio
    uid = r["created_by"]
    now = now_utc()
    if r["notified_at"] and r["notified_at"] > iso(now - timedelta(seconds=FRQ_NOTIFY_S)):
        for x in c.execute("SELECT id, data FROM notifications WHERE user_id=? AND kind='filereq' AND read_at IS NULL ORDER BY id DESC LIMIT 20",
                           (uid,)).fetchall():
            try:
                d = json.loads(x["data"] or "{}")
            except ValueError:
                continue
            if d.get("req") == r["id"]:
                d["n"] = int(d.get("n") or 0) + n
                c.execute("UPDATE notifications SET data=? WHERE id=?", (json.dumps(d, ensure_ascii=False), x["id"]))
                return
        return  # read meanwhile: the next item after FRQ_NOTIFY_S
    c.execute("UPDATE fs_upload_requests SET notified_at=? WHERE id=?", (iso(now), r["id"]))
    news_add(c, uid, "filereq", data={"req": r["id"], "node": node, "folder": r["node_id"],
                                      "title": r["title"], "n": n, "name": name}, actor=0, row="filereq")
    s = collab_user(c, uid, None)
    if s and notif_ok(c, uid, s, "filereq", "push"):
        lg = lang(c, uid)
        g.setdefault("pushes", []).append((uid, tr("Files received", lg=lg), trn("{0} new file for “{1}”", "{0} new files for “{1}”", n, r["title"], lg=lg),
                                           f"{PUBLIC_URL}/#ablage/{r['node_id']}", push_prio(s)))


def frq_news_live(c, uid, data):
    """A News item "filereq" shows while its person may still write in the request's folder."""
    try:
        nid = int(json.loads(data or "{}").get("folder") or 0)
    except (ValueError, TypeError, AttributeError):
        return False
    return bool(nid) and fs_role(c, nid, uid) in ("owner", "edit")


# ---------------------------------------------------------------- the page's script
FRQ_JS = r"""
(() => {
  const f = document.querySelector('.frq-form'); if (!f || !window.FormData || !window.XMLHttpRequest) return;
  const inp = f.querySelector('input[type=file]'), list = f.querySelector('.frq-list'), btn = f.querySelector('button[type=submit]');
  const drop = f.querySelector('.frq-drop'), max = +f.dataset.max, exts = (f.dataset.ext || '').split(','), d = f.dataset;
  let left = +d.left, picked = [], busy = false;
  inp.required = false;  // dropped files do not sit in the field
  const ext = n => { const i = n.lastIndexOf('.'); return i > 0 ? n.slice(i + 1).toLowerCase() : ''; };
  const row = (file, note, cls) => { const li = document.createElement('li'); li.className = cls || '';
    const s = document.createElement('span'); s.textContent = file.name; li.appendChild(s);
    const b = document.createElement('span'); b.className = 'bar'; const i = document.createElement('i'); b.appendChild(i); li.appendChild(b);
    const m = document.createElement('small'); m.textContent = note || ''; li.appendChild(m); list.appendChild(li); return li; };
  const show = files => {
    list.textContent = ''; picked = [];
    for (const file of files) {
      if (picked.length >= left) { row(file, d.tMany, 'bad'); continue; }
      if (!exts.includes(ext(file.name))) { row(file, d.tType, 'bad'); continue; }
      if (file.size > max) { row(file, d.tBig, 'bad'); continue; }
      picked.push({file, li: row(file, '')});
    }
  };
  inp.addEventListener('change', () => show(inp.files));
  ['dragenter', 'dragover'].forEach(k => drop.addEventListener(k, e => { e.preventDefault(); drop.classList.add('on'); }));
  ['dragleave', 'drop'].forEach(k => drop.addEventListener(k, () => drop.classList.remove('on')));
  drop.addEventListener('drop', e => { e.preventDefault(); if (e.dataTransfer && e.dataTransfer.files.length) show(e.dataTransfer.files); });
  const send = p => new Promise(res => {
    const fd = new FormData(); fd.append('file', p.file, p.file.name);
    ['name', 'stamp', 'website'].forEach(k => { const x = f.elements[k]; if (x) fd.append(k, x.value); });
    const x = new XMLHttpRequest(), bar = p.li.querySelector('i'), note = p.li.querySelector('small');
    x.open('POST', f.action); x.setRequestHeader('X-Kalmido-Upload', '1');
    x.upload.onprogress = e => { if (e.lengthComputable) bar.style.transform = 'scaleX(' + (e.loaded / e.total) + ')'; };
    x.onload = () => { let j = {}; try { j = JSON.parse(x.responseText); } catch (e) { /* not JSON */ }
      if (x.status < 300 && j.ok) { p.li.className = 'ok'; bar.style.transform = 'scaleX(1)'; left -= 1; } else { p.li.className = 'bad'; note.textContent = d.tFail + ': ' + (j.error || x.status); }
      res(); };
    x.onerror = () => { p.li.className = 'bad'; note.textContent = d.tFail; res(); };
    x.send(fd);
  });
  f.addEventListener('submit', async e => {
    e.preventDefault(); if (busy) return; if (!picked.length) { inp.focus(); return; }
    busy = true; btn.disabled = true;
    for (const p of picked) await send(p);
    const ok = picked.filter(p => p.li.className === 'ok').length; picked = []; busy = false; btn.disabled = false; inp.value = '';
    if (ok) { const m = document.createElement('p'); m.className = 'frq-done'; m.setAttribute('role', 'status'); m.textContent = d.tDone; list.after(m); }
  });
})();
"""


@app.get("/u/v/up.js")
def frq_js():
    resp = Response("'use strict';\n" + FRQ_JS, mimetype="application/javascript")
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp
