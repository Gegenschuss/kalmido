"""2.97.0 A (#1950): bookmarks -- links with a preview (title, description, picture), tags, a note, read / archived and
full-text search; the Karakeep connection (life/karakeep.py) fills the same store. Built by part A."""
import codecs
import json
import os
import queue
import re
import threading
import urllib.parse
import uuid
from datetime import timedelta
from html.parser import HTMLParser

from flask import g, has_request_context, jsonify, request

from ..core.config import app, ATT_DIR, APP_NAME, APP_VERSION
from ..core.i18n import N_, tr, trn
from ..core.db import body, connect, db, iso, iso_ms, now_utc
from ..core.pg import insert_id, write_lock
from ..core.access import Denied
from ..core.orgcrypt import oc_copy_file, oc_send_file, oc_user_space, oc_write_file
from ..accounts.session import me
from ..accounts.orgs import is_org_admin, user_orgs
from ..accounts.spacemove import SMV_MAX, smv_answer, smv_refuse_agent, smv_target
from ..tasks.validation import as_int
from ..personal.timetrack import BadInput
from ..calendars.subscriptions import CalError, cal_allow_parse, cal_err_text, cal_http, cal_rate
from ..life.model import need_life
from ..life.rss import rss_url


# ---------------------------------------------------------------- 2.97.0 A (#1950): bookmarks
# Part of the module "reading" (off by default). A bookmark lives in a space like a table: org_id NULL = private (only its
# owner), else every member of the organisation reads it; changing, deleting and moving it is for its owner or an admin of
# the organisation. People only: no agent, no API token (no v1 route in 2.97.0).
# The preview (title, description, picture, the plain reading text) is fetched by the server once, in a worker thread
# (never inside the request): through the SSRF guard of the calendar subscriptions (cal_http: http/https only, every
# redirect hop and every resolved address checked, internal hosts only where an admin allowed them), small and short
# (BM_HTML_MAX, BM_TIMEOUT / BM_DEADLINE), no credentials, only text/html. The page is parsed with html.parser into
# plain text: no foreign HTML is stored or sent to the client. The picture: its own fetch with the same guard, at most
# BM_IMG_MAX, only PNG / JPEG / WebP / GIF recognised by their first bytes (never SVG), stored as a sealed copy (the
# space's key, like attachments) and served by the app. A failed fetch keeps the bookmark (preview "failed").
BM_MAX = 5000              # bookmarks per person (not deleted)
BM_URL_MAX = 2000
BM_TITLE_MAX = 300
BM_DESC_MAX = 1000
BM_NOTE_MAX = 5000
BM_SITE_MAX = 100
BM_TAGS_MAX, BM_TAG_MAX = 20, 40
BM_TEXT_MAX = 200_000      # characters of the reading text
BM_HTML_MAX = 1024 * 1024
BM_IMG_MAX = 1024 * 1024
BM_TIMEOUT, BM_DEADLINE = 8, 10
BM_PAGE = 60
BM_TRASH_DAYS = 7          # a deleted bookmark (undo possible) is purged after this
BM_TICK = 20               # pending previews the watchdog queues per tick
BM_STATES = ("unread", "read", "archived")
# 2.97.0 review (M2): internal hosts a preview may reach -- only the operator's own list (env), never the calendar list: a
# preview hands the page's text to the person, a calendar only reads events
BM_ALLOW = frozenset(cal_allow_parse(os.environ.get("KALMIDO_BOOKMARK_ALLOW_HOSTS", ""))[0])
BM_DIR = os.path.join(ATT_DIR, "bookmarks")
BM_UA = f"{APP_NAME}/{APP_VERSION} (bookmark preview)"
BM_IMG_TYPES = ((b"\x89PNG\r\n\x1a\n", "image/png", "png"), (b"\xff\xd8\xff", "image/jpeg", "jpg"),
                (b"GIF87a", "image/gif", "gif"), (b"GIF89a", "image/gif", "gif"))
BM_ERR = {"type": N_("The address is not a web page"), "parse": N_("The page could not be read"),
          "too_large": N_("The page is larger than {0} MB")}
BM_ONLY = N_("Only who saved this bookmark or an admin of the organisation can change it")


def bm_err_text(stored):
    code = (stored or "").partition(":")[0]
    if not code:
        return ""
    if code == "too_large":
        return tr(BM_ERR["too_large"], BM_HTML_MAX // (1024 * 1024))
    if code in BM_ERR:
        return tr(BM_ERR[code])
    return cal_err_text(stored)


def bm_need(c, uid):
    """The person's own module "reading"; never an agent, never an API token (bookmarks are only for people in 2.97.0)."""
    from ..agents.core import is_agent
    if has_request_context() and (is_agent(getattr(g, "user", None)) or g.get("auth_via") == "token"):
        raise Denied(403, tr("Bookmarks are only available in the app"))
    need_life(c, uid, "reading")


# ---- values
def bm_norm_url(u):
    """An absolute http(s) link (a bare host gets https://), else ''."""
    u = str(u or "").strip()
    if u and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", u) and re.match(r"^[\w-]+(\.[\w-]+)+([/:?#]|$)", u):
        u = "https://" + u
    try:
        urllib.parse.urlsplit(u).port  # 2.97.0 review (L1): a port that is no number is no link
    except ValueError:
        return ""
    return rss_url(u)


def bm_key(u):
    """The link as it is compared (scheme + host lower case, no fragment, no tracking parameters, no trailing slash)."""
    p = urllib.parse.urlsplit(u)
    q = "&".join(x for x in p.query.split("&") if x and not re.match(r"(utm_[a-z]+|fbclid|gclid|mc_eid)=", x, re.I))
    path = p.path.rstrip("/") or ""
    host = (p.hostname or "").lower() + (f":{p.port}" if p.port else "")
    return f"{p.scheme.lower()}://{host}{path}" + (f"?{q}" if q else "")


def bm_site(u):
    h = (urllib.parse.urlsplit(u).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def bm_tags(v):
    if v in (None, ""):
        return []
    if isinstance(v, str):
        v = [x for x in re.split(r"[,\s]+", v) if x]
    if not isinstance(v, list):
        raise BadInput(tr("Invalid value: {0}", "tags"))
    out, seen = [], set()
    for x in v:
        if not isinstance(x, str):
            raise BadInput(tr("Invalid value: {0}", "tags"))
        t = re.sub(r"\s+", "-", x.strip().lstrip("#"))[:BM_TAG_MAX]
        t = "".join(ch for ch in t if ch >= " ")
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    if len(out) > BM_TAGS_MAX:
        raise BadInput(tr("At most {0} tags", BM_TAGS_MAX))
    return out


def _txt(v, what, n):
    if v is None:
        return ""
    if not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", what))
    return "".join(ch for ch in v if ch >= " " or ch in "\n\t").strip()[:n]


def bm_space_key(oid):
    return f"org:{oid}" if oid else "private"


def bm_space(c, uid, v):
    """org id (None = private) of a space value "private" | "org:<id>" | <id>; 404 for an organisation uid is not in."""
    if v in (None, "", "private", 0, "0"):
        return None
    s = str(v)
    if s.startswith("org:"):
        s = s[4:]
    try:
        oid = int(s)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", "space")) from None
    if oid not in user_orgs(c, uid):
        raise Denied(404)
    return oid


def bm_may_write(c, uid, r):
    return r["user_id"] == uid if not r["org_id"] else (r["user_id"] == uid or is_org_admin(c, uid, r["org_id"]))


def bm_get(c, uid, bid, write=False, deleted=False):
    """The bookmark row if uid may see it (404 otherwise); write: 403 unless uid owns it or administers its organisation."""
    r = c.execute("SELECT * FROM bookmarks WHERE id=?", (bid,)).fetchone()
    if not r or (r["deleted_at"] is not None) != deleted:
        raise Denied(404)
    if r["org_id"] is None:
        if r["user_id"] != uid:
            raise Denied(404)
    elif r["org_id"] not in user_orgs(c, uid):
        raise Denied(404)
    if write and not bm_may_write(c, uid, r):
        raise Denied(403, tr(BM_ONLY))
    return r


def bm_out(c, uid, r, full=False, can=None):
    """The bookmark for the client (r: a row or dict; can = the write right when the caller knows it already)."""
    try:
        tags = json.loads(r["tags"] or "[]")
    except ValueError:
        tags = []
    d = {"id": r["id"], "url": r["url"], "title": r["title"] or bm_site(r["url"]) or r["url"], "description": r["description"],
         "site": r["site"] or bm_site(r["url"]), "tags": tags, "note": r["note"], "state": r["state"],
         "image": f"/api/bookmarks/{r['id']}/image?v={urllib.parse.quote(r['updated_at'] or '')}" if r["image"] else "",
         "preview": r["preview"], "preview_error": bm_err_text(r["preview_error"]) if r["preview"] == "failed" else "",
         "has_text": bool(r["has_text"] if "has_text" in r.keys() else r["text"]), "src": r["src"], "space": bm_space_key(r["org_id"]),
         "mine": r["user_id"] == uid, "can_edit": bm_may_write(c, uid, r) if can is None else can,
         "created_at": r["created_at"], "updated_at": r["updated_at"]}
    if full:
        d["text"] = r["text"]
    return d


def _like(q):
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def bm_where(c, uid, space):
    """SQL + args of the bookmarks uid sees in a space ("all" = every space)."""
    if space in (None, "", "all"):
        orgs = list(user_orgs(c, uid))
        if not orgs:
            return "(b.org_id IS NULL AND b.user_id=?)", [uid]
        return f"((b.org_id IS NULL AND b.user_id=?) OR b.org_id IN ({','.join('?' * len(orgs))}))", [uid, *orgs]
    oid = bm_space(c, uid, space)
    return ("b.org_id=?", [oid]) if oid else ("(b.org_id IS NULL AND b.user_id=?)", [uid])


def bm_list(c, uid, a):
    """?space=private|org:<id>|all &q= &tag= &state=unread|read|archived|all (default: not archived) &offset= ->
    {items, more, tags: [{tag, n}], count}."""
    w, args = bm_where(c, uid, a.get("space"))
    w += " AND b.deleted_at IS NULL"
    tw, targs = w, list(args)
    st = a.get("state") or ""
    if st in BM_STATES:
        w += " AND b.state=?"
        args.append(st)
    elif st != "all":
        w += " AND b.state<>'archived'"
    q = (a.get("q") or "").strip()[:200]
    if q:
        for word in q.split()[:8]:
            lk = _like(word)
            w += (" AND (b.title ILIKE ? ESCAPE '\\' OR b.description ILIKE ? ESCAPE '\\' OR b.note ILIKE ? ESCAPE '\\' "
                  "OR b.url ILIKE ? ESCAPE '\\' OR b.text ILIKE ? ESCAPE '\\' OR b.tags ILIKE ? ESCAPE '\\' OR b.site ILIKE ? ESCAPE '\\')")
            args += [lk] * 7
    tag = (a.get("tag") or "").strip()[:BM_TAG_MAX]
    if tag:
        w += " AND b.tags ILIKE ? ESCAPE '\\'"
        args.append(_like(json.dumps(tag, ensure_ascii=False)))  # stored with ensure_ascii=False (review L3)
    off = as_int(a.get("offset") or 0, "offset", 0, 1_000_000)
    rows = c.execute(f"""SELECT b.id, b.user_id, b.org_id, b.url, b.title, b.description, b.site, b.tags, b.note, b.state, b.image,
                         b.preview, b.preview_error, b.src, b.created_at, b.updated_at, b.text<>'' AS has_text FROM bookmarks b WHERE {w}
                         ORDER BY b.created_at DESC, b.id DESC LIMIT ? OFFSET ?""", (*args, BM_PAGE + 1, off)).fetchall()
    admin = {}
    items = []
    for r in rows[:BM_PAGE]:
        if r["org_id"] and r["org_id"] not in admin:
            admin[r["org_id"]] = is_org_admin(c, uid, r["org_id"])
        items.append(bm_out(c, uid, r, can=r["user_id"] == uid or bool(r["org_id"] and admin[r["org_id"]])))
    tags = {}
    for (t,) in c.execute(f"SELECT b.tags FROM bookmarks b WHERE {tw} AND b.tags<>'[]'", targs).fetchall():
        try:
            for x in json.loads(t):
                tags[x] = tags.get(x, 0) + 1
        except ValueError:
            continue
    n = c.execute(f"SELECT COUNT(*) FROM bookmarks b WHERE {w}", args).fetchone()[0]
    return {"items": items, "more": len(rows) > BM_PAGE, "count": n,
            "tags": [{"tag": k, "n": v} for k, v in sorted(tags.items(), key=lambda x: (-x[1], x[0].lower()))][:200]}


def bm_create(c, uid, b, src="", src_id="", preview="pending"):
    """{url, space?, title?, description?, note?, tags?, state?} -> (row, existed). The same link in the same space of the same
    person is not saved twice: the existing one comes back (existed)."""
    unknown = sorted(set(b) - {"url", "space", "title", "description", "note", "tags", "state", "image_url"})
    if unknown:
        raise BadInput(tr("Unknown field: {0}", ", ".join(unknown)[:200]))
    url = bm_norm_url(b.get("url"))
    if not url:
        raise BadInput(tr("Please enter a web address (http or https)"))
    oid = bm_space(c, uid, b.get("space"))
    key = bm_key(url)
    write_lock(c, f"bm:{uid}")
    old = c.execute("SELECT * FROM bookmarks WHERE user_id=? AND org_id IS NOT DISTINCT FROM ? AND url_key=? AND deleted_at IS NULL",
                    (uid, oid, key)).fetchone()
    if old:
        return old, True
    if c.execute("SELECT COUNT(*) FROM bookmarks WHERE user_id=? AND deleted_at IS NULL", (uid,)).fetchone()[0] >= BM_MAX:
        raise BadInput(tr("At most {0} bookmarks", BM_MAX))
    st = b.get("state") or "unread"
    if st not in BM_STATES:
        raise BadInput(tr("Invalid value: {0}", "state"))
    title = _txt(b.get("title"), "title", BM_TITLE_MAX)
    img = rss_url(b.get("image_url") or "", url) if src else ""
    ts = iso_ms(now_utc())
    bid = insert_id(c, """INSERT INTO bookmarks(user_id,org_id,url,url_key,title,description,site,tags,note,state,preview,image_url,
                          src,src_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (uid, oid, url, key, title, _txt(b.get("description"), "description", BM_DESC_MAX), bm_site(url)[:BM_SITE_MAX],
                     json.dumps(bm_tags(b.get("tags")), ensure_ascii=False), _txt(b.get("note"), "note", BM_NOTE_MAX), st,
                     preview if (preview != "image" or img) else "ok", img, src, src_id, ts, ts))
    return c.execute("SELECT * FROM bookmarks WHERE id=?", (bid,)).fetchone(), False


def bm_patch(c, uid, bid, b):
    """{title?, description?, note?, tags?, state?, url?} -> the row (a new link: the preview is fetched again)."""
    r = bm_get(c, uid, bid, write=True)
    unknown = sorted(set(b) - {"title", "description", "note", "tags", "state", "url"})
    if unknown:
        raise BadInput(tr("Unknown field: {0}", ", ".join(unknown)[:200]))
    sets, args = [], []
    if "title" in b:
        sets.append("title=?")
        args.append(_txt(b["title"], "title", BM_TITLE_MAX))
    if "description" in b:
        sets.append("description=?")
        args.append(_txt(b["description"], "description", BM_DESC_MAX))
    if "note" in b:
        sets.append("note=?")
        args.append(_txt(b["note"], "note", BM_NOTE_MAX))
    if "tags" in b:
        sets.append("tags=?")
        args.append(json.dumps(bm_tags(b["tags"]), ensure_ascii=False))
    if "state" in b:
        if b["state"] not in BM_STATES:
            raise BadInput(tr("Invalid value: {0}", "state"))
        sets.append("state=?")
        args.append(b["state"])
    refetch = False
    if "url" in b:
        url = bm_norm_url(b["url"])
        if not url:
            raise BadInput(tr("Please enter a web address (http or https)"))
        if url != r["url"]:
            key = bm_key(url)
            if c.execute("SELECT 1 FROM bookmarks WHERE user_id=? AND org_id IS NOT DISTINCT FROM ? AND url_key=? AND deleted_at IS NULL "
                         "AND id<>?", (r["user_id"], r["org_id"], key, bid)).fetchone():
                raise Denied(409, tr("This link is already saved"))
            # 2.97.0 review (L2): the old picture goes with the old link
            sets += ["url=?", "url_key=?", "site=?", "preview='pending'", "preview_error=''", "text=''", "image_url=''", "image=''",
                     "image_mime=''"]
            args += [url, key, bm_site(url)[:BM_SITE_MAX]]
            refetch = True
    if sets:
        sets.append("updated_at=?")
        args.append(iso_ms(now_utc()))
        c.execute(f"UPDATE bookmarks SET {', '.join(sets)} WHERE id=?", (*args, bid))
    return c.execute("SELECT * FROM bookmarks WHERE id=?", (bid,)).fetchone(), refetch


# ---- the preview
class _BmPage(HTMLParser):
    """<title>, OpenGraph / Twitter / description meta, and the plain text of the page (paragraphs; inside article / main
    when there are any; scripts, styles, navigation, headers, footers and forms dropped)."""
    SKIP = ("script", "style", "noscript", "template", "svg", "nav", "header", "footer", "aside", "form", "iframe", "button",
            "select", "textarea", "figure", "object")
    BLOCK = ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre", "section", "article", "main", "tr", "br",
             "dd", "dt", "td", "ul", "ol", "table")
    VOID = ("br", "img", "meta", "link", "input", "hr", "source", "area", "base", "col", "embed", "param", "track", "wbr")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta, self.title, self.in_title = {}, [], False
        self.skip, self.main, self.buf, self.paras, self.n = 0, 0, [], [], 0

    def _flush(self):
        s = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        self.buf = []
        if s and self.n < BM_TEXT_MAX * 2:
            self.paras.append((self.main > 0, s))
            self.n += len(s)

    def handle_starttag(self, tag, attrs):
        if tag == "meta":
            a = {k.lower(): (v or "") for k, v in attrs if k}
            k = (a.get("property") or a.get("name") or "").lower().strip()
            if k and "content" in a and k not in self.meta and len(self.meta) < 200:
                self.meta[k] = a["content"][:4000]
            return
        if tag == "title" and not self.skip:
            self.in_title = True
        if tag in self.VOID:
            if tag == "br" and not self.skip:
                self._flush()
            return
        if tag in self.SKIP:
            self.skip += 1
        elif not self.skip and tag in self.BLOCK:
            self._flush()
        if tag in ("article", "main") and not self.skip:
            self.main += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif not self.skip and tag in self.BLOCK:
            self._flush()
        if tag in ("article", "main") and self.main and not self.skip:
            self.main -= 1

    def handle_data(self, d):
        if self.in_title and len(self.title) < 50:
            self.title.append(d)
        elif not self.skip:
            self.buf.append(d)


def bm_charset(ctype, raw):
    m = re.search(r"charset=[\"']?([\w.:-]+)", ctype or "", re.I) or re.search(rb"<meta[^>]+charset=[\"']?([\w.:-]+)", raw[:4096], re.I)
    cs = m.group(1) if m else "utf-8"
    cs = cs.decode("ascii", "replace") if isinstance(cs, bytes) else cs
    try:
        return codecs.lookup(cs).name
    except LookupError:
        return "utf-8"


def _plain(v, n):
    """Text the parser already decoded (titles, meta content): control characters out, whitespace collapsed, at most n."""
    v = re.sub(r"\s+", " ", "".join(ch for ch in str(v or "") if ch >= " " or ch in "\t\n")).strip()
    return v if len(v) <= n else v[:n - 1].rstrip() + "\u2026"


def bm_parse(html_text, base):
    """The preview of an HTML page (text) -> {title, description, site, image_url, text}; base = its final address."""
    p = _BmPage()
    p.feed(html_text[:BM_HTML_MAX])
    p.close()
    p._flush()
    m = p.meta

    def first(*keys):
        for k in keys:
            if m.get(k, "").strip():
                return m[k]
        return ""
    title = _plain(first("og:title", "twitter:title") or "".join(p.title), BM_TITLE_MAX)
    desc = _plain(first("og:description", "twitter:description", "description"), BM_DESC_MAX)
    img = ""
    for k in ("og:image:secure_url", "og:image", "og:image:url", "twitter:image", "twitter:image:src"):
        img = rss_url(m.get(k, "").strip(), base)
        if img:
            break
    main = [s for inside, s in p.paras if inside]
    paras = main if sum(len(s) for s in main) >= 200 else [s for _, s in p.paras]
    paras = [s for s in paras if len(s.split()) >= 3 or len(s) >= 40]
    text, n = [], 0
    for s in paras:
        if n + len(s) > BM_TEXT_MAX:
            text.append(s[:max(0, BM_TEXT_MAX - n)])
            break
        text.append(s)
        n += len(s) + 2
    return {"title": title, "description": desc, "site": _plain(m.get("og:site_name", ""), BM_SITE_MAX), "image_url": img,
            "text": "\n\n".join(text).strip()}


def bm_image_type(data):
    for magic, mime, ext in BM_IMG_TYPES:
        if data.startswith(magic):
            return mime, ext
    if len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None, None


def bm_fetch_image(url, allow):
    """(bytes, mime, ext) of a preview picture or None (refused, too large, not a known image)."""
    try:
        st, _h, data, _f = cal_http(url, headers={"User-Agent": BM_UA, "Accept": "image/png, image/jpeg, image/webp, image/gif"},
                                    allow=allow, cross_redirects=True, max_bytes=BM_IMG_MAX, timeout=BM_TIMEOUT, deadline=BM_DEADLINE)
    except CalError:
        return None
    if st != 200 or not data:
        return None
    mime, ext = bm_image_type(data)
    return (data, mime, ext) if mime else None


def bm_preview(url, allow):
    """Fetch and parse a page -> the parse result + error ('' or a code); never raises for what the page does."""
    try:
        st, hd, raw, final = cal_http(url, headers={"User-Agent": BM_UA, "Accept": "text/html, application/xhtml+xml;q=0.9, */*;q=0.1"},
                                      allow=allow, cross_redirects=True, max_bytes=BM_HTML_MAX, timeout=BM_TIMEOUT, deadline=BM_DEADLINE)
    except CalError as e:
        return {"error": e.stored()}
    ctype = (hd.get("Content-Type") if hd else "") or ""
    if st != 200 or not re.match(r"\s*(text/html|application/xhtml\+xml)", ctype, re.I):
        return {"error": "type"}
    try:
        out = bm_parse(raw.decode(bm_charset(ctype, raw), "replace"), final)
    except Exception:  # noqa: BLE001  (whatever a hostile page does to the parser: the bookmark stays, without preview)
        return {"error": "parse"}
    out["error"] = ""
    return out


def bm_space_id(r):
    """The key space of a bookmark's picture: its organisation, else its owner's account (like the files of a private list)."""
    return int(r["org_id"]) if r["org_id"] else oc_user_space(r["user_id"])


def bm_path(rel):
    return os.path.join(ATT_DIR, rel)


def bm_store_image(c, r, img):
    """Writes the picture sealed for the bookmark's space -> its relative path."""
    os.makedirs(BM_DIR, exist_ok=True)
    rel = os.path.join("bookmarks", f"{int(r['id'])}-{uuid.uuid4().hex[:12]}.{img[2]}")
    oc_write_file(c, bm_space_id(r), bm_path(rel), img[0], fresh=True)
    return rel


def bm_rm_file(rel):
    if rel and rel.startswith("bookmarks/") and ".." not in rel:
        try:
            os.remove(bm_path(rel))
        except OSError:
            pass


def bm_fetch_one(bid):
    """Fetches the preview of bookmark bid (preview pending: the page + its picture; image: only the picture Karakeep named)
    and stores it. Background work for a row the person saved: the connection's system context (connect()) is needed to
    write an organisation's row outside the request; nothing is handed to anybody here."""
    c = connect()
    try:
        r = c.execute("SELECT * FROM bookmarks WHERE id=? AND deleted_at IS NULL", (bid,)).fetchone()
        if not r or r["preview"] not in ("pending", "image"):
            return
        allow = BM_ALLOW
        c.commit()  # no transaction stays open during the fetch
        if r["preview"] == "pending":
            res = bm_preview(r["url"], allow)
        else:
            res = {"error": "", "image_url": r["image_url"]}
        img = bm_fetch_image(res["image_url"], allow) if not res["error"] and res.get("image_url") else None
        cur = c.execute("SELECT * FROM bookmarks WHERE id=? AND deleted_at IS NULL", (bid,)).fetchone()
        if not cur or cur["url"] != r["url"] or cur["preview"] != r["preview"]:
            c.commit()
            return  # changed meanwhile (a new link, deleted): its own fetch follows
        rel = bm_store_image(c, cur, img) if img else ""
        ts = iso_ms(now_utc())
        if res["error"]:
            c.execute("UPDATE bookmarks SET preview='failed', preview_error=?, fetched_at=?, updated_at=? WHERE id=?",
                      (res["error"][:40], ts, ts, bid))
        else:
            c.execute("""UPDATE bookmarks SET preview='ok', preview_error='', fetched_at=?, updated_at=?,
                         title=CASE WHEN title='' THEN ? ELSE title END, description=CASE WHEN description='' THEN ? ELSE description END,
                         site=CASE WHEN ?<>'' THEN ? ELSE site END, text=CASE WHEN ?<>'' THEN ? ELSE text END,
                         image_url=CASE WHEN ?<>'' THEN ? ELSE image_url END, image=CASE WHEN ?<>'' THEN ? ELSE image END,
                         image_mime=CASE WHEN ?<>'' THEN ? ELSE image_mime END WHERE id=?""",
                      (ts, ts, res.get("title", ""), res.get("description", ""), res.get("site", ""), res.get("site", ""),
                       res.get("text", ""), res.get("text", ""), res.get("image_url", ""), res.get("image_url", ""), rel, rel,
                       img[1] if img else "", img[1] if img else "", bid))
        c.commit()
        if rel and cur["image"] and cur["image"] != rel:
            bm_rm_file(cur["image"])
    finally:
        c.close()


_BM_Q = queue.Queue(maxsize=2000)
_BM_LOCK = threading.Lock()
_BM_STATE = {"run": False, "queued": set()}


def bm_kick(ids):
    """Queues previews (after the commit that made the rows) for the one worker thread (started when it is not running)."""
    with _BM_LOCK:
        for i in ids:
            i = int(i)
            if i in _BM_STATE["queued"]:
                continue
            try:
                _BM_Q.put_nowait(i)
            except queue.Full:
                break  # the watchdog queues the rest later
            _BM_STATE["queued"].add(i)
        if _BM_STATE["run"] or _BM_Q.empty():
            return
        _BM_STATE["run"] = True
    threading.Thread(target=_bm_worker, daemon=True).start()


def _bm_worker():
    """One preview after the other (at most one fetch at a time on the server); ends when the queue stays empty."""
    while True:
        try:
            bid = _BM_Q.get(timeout=5)
        except queue.Empty:
            with _BM_LOCK:
                if _BM_Q.empty():
                    _BM_STATE["run"] = False
                    return
            continue
        try:
            bm_fetch_one(bid)
        except Exception as e:  # noqa: BLE001
            print("bookmark preview error:", type(e).__name__, flush=True)
        finally:
            with _BM_LOCK:
                _BM_STATE["queued"].discard(bid)


def _wd_bookmarks(c, users, S, LG, now):  # noqa: ARG001
    """Watchdog: queues previews still pending (a restart, a full queue, Karakeep's new bookmarks) of people with the module
    on, and purges bookmarks deleted longer than BM_TRASH_DAYS ago (with their pictures)."""
    on = [u for u in users if "reading" in (S[u].get("features") or "").split(",")]
    if on:
        # 2.97.0 review (M1): at most 3 per person and tick, so one person's many links never hold up the others
        ids = [r[0] for r in c.execute(f"""SELECT id FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY id) AS n
                                          FROM bookmarks WHERE preview IN ('pending', 'image') AND deleted_at IS NULL
                                          AND user_id IN ({",".join("?" * len(on))})) x WHERE n<=3 ORDER BY id LIMIT ?""",
                                       (*on, BM_TICK)).fetchall()]
        if ids:
            bm_kick(ids)
    old = iso(now_utc() - timedelta(days=BM_TRASH_DAYS))
    gone = c.execute("SELECT id, image FROM bookmarks WHERE deleted_at IS NOT NULL AND deleted_at<? LIMIT 500", (old,)).fetchall()
    if gone:
        c.execute(f"DELETE FROM bookmarks WHERE id IN ({','.join('?' * len(gone))})", [r[0] for r in gone])
        c.commit()
        for r in gone:
            bm_rm_file(r[1])


# ---- moving between workspaces (2.96.0 rules: accounts/spacemove.py)
def bm_move(c, uid, b):
    """{ids, to, dry} -> the dry run / the move. Write right on each (owner, or admin of its organisation); the same link
    already saved by the person in the target stays where it is (named). The picture is sealed again with the target's key."""
    smv_refuse_agent()
    ids = b.get("ids")
    if not isinstance(ids, list) or not ids or len(ids) > SMV_MAX:
        raise Denied(400, tr("Invalid value: {0}", "ids"))
    try:
        ids = list(dict.fromkeys(int(i) for i in ids))
    except (TypeError, ValueError):
        raise Denied(400, tr("Invalid value: {0}", "ids")) from None
    to = smv_target(c, uid, b.get("to"))
    rows = [bm_get(c, uid, i, write=True) for i in ids]
    rows = [r for r in rows if (r["org_id"] or None) != (to or None)]
    if not rows:
        raise Denied(409, tr("This is already in that workspace"))
    have = {x[0] for x in c.execute("SELECT url_key FROM bookmarks WHERE user_id=? AND org_id IS NOT DISTINCT FROM ? AND deleted_at IS NULL",
                                    (uid, to)).fetchall()}
    dup = [r for r in rows if r["url_key"] in have]
    go = [r for r in rows if r["url_key"] not in have]
    notes = [trn("{0} link is already saved there: it stays where it is", "{0} links are already saved there: they stay where they are",
                 len(dup)) if dup else "",
             tr("Every member of the organisation can then see it") if to else ""]
    if b.get("dry"):
        return smv_answer(notes, None if go else tr("Everything is already saved there"), count=len(go))
    if not go:
        raise Denied(409, tr("Everything is already saved there"))
    ts = iso_ms(now_utc())
    old_files = []
    for r in go:
        rel = r["image"]
        if rel and os.path.exists(bm_path(rel)):
            new = os.path.join("bookmarks", f"{int(r['id'])}-{uuid.uuid4().hex[:12]}{os.path.splitext(rel)[1]}")
            oc_copy_file(c, bm_path(rel), bm_path(new), int(to) if to else oc_user_space(uid))
            old_files.append(rel)
            rel = new
        c.execute("UPDATE bookmarks SET org_id=?, user_id=?, image=?, updated_at=? WHERE id=?", (to, uid, rel, ts, r["id"]))
        c.execute("INSERT INTO space_moves(kind,obj_id,from_org,to_org,by_id,at,detail) VALUES('bookmark',?,?,?,?,?,?)",
                  (r["id"], r["org_id"], to, uid, ts, json.dumps({"owner": r["user_id"]})))
    c.commit()
    for rel in old_files:
        bm_rm_file(rel)
    return smv_answer(notes, None, ok=True, moved=[r["id"] for r in go], from_space=bm_space_key(go[0]["org_id"]), space=bm_space_key(to))


# ---- routes (/api/bookmarks; people only)
@app.get("/api/bookmarks")
def bookmarks_get():
    c, uid = db(), me()
    bm_need(c, uid)
    return jsonify(bm_list(c, uid, request.args))


@app.post("/api/bookmarks")
def bookmarks_post():
    """{url, space?, title?, description?, note?, tags?, state?} -> {bookmark, existed} (201 when new; the preview follows in
    the background: preview "pending" until it is there)."""
    c, uid = db(), me()
    bm_need(c, uid)
    b = body()
    if not isinstance(b, dict) or "image_url" in b:
        raise BadInput(tr("Invalid value: {0}", "body"))
    r, existed = bm_create(c, uid, b)
    c.commit()
    if not existed and cal_rate(uid):  # 2.97.0 review (M1): beyond the limit the watchdog fetches it later
        bm_kick([r["id"]])
    return jsonify({"bookmark": bm_out(c, uid, r, full=True), "existed": existed}), 200 if existed else 201


@app.get("/api/bookmarks/<int:bid>")
def bookmark_get(bid):
    c, uid = db(), me()
    bm_need(c, uid)
    return jsonify(bm_out(c, uid, bm_get(c, uid, bid), full=True))


@app.patch("/api/bookmarks/<int:bid>")
def bookmark_patch(bid):
    c, uid = db(), me()
    bm_need(c, uid)
    old = c.execute("SELECT image FROM bookmarks WHERE id=?", (bid,)).fetchone()
    r, refetch = bm_patch(c, uid, bid, body())
    c.commit()
    if refetch and old and old["image"] and old["image"] != r["image"]:
        bm_rm_file(old["image"])  # 2.97.0 review (L2): the old link's picture
    if refetch and cal_rate(uid):  # 2.97.0 review (M1)
        bm_kick([bid])
    return jsonify(bm_out(c, uid, r, full=True))


@app.delete("/api/bookmarks/<int:bid>")
def bookmark_delete(bid):
    """Deleted (undo: POST /api/bookmarks/<id>/restore within BM_TRASH_DAYS)."""
    c, uid = db(), me()
    bm_need(c, uid)
    bm_get(c, uid, bid, write=True)
    c.execute("UPDATE bookmarks SET deleted_at=? WHERE id=?", (iso_ms(now_utc()), bid))
    c.commit()
    return jsonify({"ok": True, "id": bid})


@app.post("/api/bookmarks/<int:bid>/restore")
def bookmark_restore(bid):
    c, uid = db(), me()
    bm_need(c, uid)
    r = bm_get(c, uid, bid, write=True, deleted=True)
    if c.execute("SELECT 1 FROM bookmarks WHERE user_id=? AND org_id IS NOT DISTINCT FROM ? AND url_key=? AND deleted_at IS NULL",
                 (r["user_id"], r["org_id"], r["url_key"])).fetchone():
        raise Denied(409, tr("This link is already saved"))
    c.execute("UPDATE bookmarks SET deleted_at=NULL WHERE id=?", (bid,))
    c.commit()
    return jsonify(bm_out(c, uid, c.execute("SELECT * FROM bookmarks WHERE id=?", (bid,)).fetchone(), full=True))


@app.post("/api/bookmarks/<int:bid>/refresh")
def bookmark_refresh(bid):
    """Fetch the preview again (title / description stay when they were changed by hand; the picture and the text are new)."""
    c, uid = db(), me()
    bm_need(c, uid)
    bm_get(c, uid, bid, write=True)
    if not cal_rate(uid):
        raise Denied(429, tr("Too many requests, please slow down"))
    c.execute("UPDATE bookmarks SET preview='pending', preview_error='', updated_at=? WHERE id=?", (iso_ms(now_utc()), bid))
    c.commit()
    bm_kick([bid])
    return jsonify(bm_out(c, uid, c.execute("SELECT * FROM bookmarks WHERE id=?", (bid,)).fetchone(), full=True))


@app.get("/api/bookmarks/<int:bid>/image")
def bookmark_image(bid):
    c, uid = db(), me()
    bm_need(c, uid)
    r = bm_get(c, uid, bid)
    if not r["image"] or not r["image_mime"].startswith("image/") or r["image_mime"] == "image/svg+xml" or not os.path.exists(bm_path(r["image"])):
        raise Denied(404)
    resp = oc_send_file(c, bm_path(r["image"]), mimetype=r["image_mime"], max_age=86400)
    resp.headers["Cache-Control"] = "private, max-age=86400"
    resp.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@app.post("/api/bookmarks/move-space")
def bookmarks_move_space():
    c, uid = db(), me()
    bm_need(c, uid)
    return jsonify(bm_move(c, uid, body()))
