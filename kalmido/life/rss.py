"""Reading: feeds (RSS 2.0, Atom 1.0, RSS 1.0 / RDF) of one person or of an organisation (2.172.0 B, #2677), fetched by
the server, read in the view "Feeds"."""
import re
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser

from ..core.config import APP_NAME, APP_VERSION
from ..core.i18n import N_, tr
from ..core.db import connect, iso, now_utc, parse_iso
from ..core.pg import IntegrityError, insert_id
from ..core.access import Denied, task_visible
from ..tasks.validation import as_int, TITLE_MAX
from ..core.errors import BadInput
from ..calendars.caldav import _DtdRefused, xml_no_dtd
from ..calendars.subscriptions import CalError, cal_allow, cal_err_text, cal_http, cal_norm_url, cal_rate
from ..life.model import _insert, need_life


# ---------------------------------------------------------------- 2.85.0 B (#1162): feeds
# Module "feeds" (off by default). Feeds belong to the person or (2.172.0 B, #2677) to an organisation (never an agent's:
# no v1 route, no MCP tool). Every fetch goes through the SSRF guard of the calendar subscriptions (cal_http: http/https only,
# no proxies, every redirect hop and every resolved address checked, internal hosts only where an admin allowed them),
# small (RSS_MAX_BYTES) and short (RSS_TIMEOUT / RSS_DEADLINE), without credentials. The XML parser refuses a DTD
# (no entities: XXE, billion laughs). Titles and summaries are stored as plain text (tags dropped, entities resolved),
# links only as http(s): no foreign HTML ever reaches the client, no pictures are loaded. "Read later" makes a task
# (title + link) in the person's reading list, once per article.
RSS_MAX_FEEDS = 100        # per person (also the OPML import)
RSS_EVERY = 3600           # s between two fetches of one feed
RSS_SLOW_AFTER = 10        # failed fetches in a row -> only once a day
RSS_SLOW = 86400
RSS_KEEP_DAYS = 30         # articles older than this go (the tasks made of them stay)
RSS_ITEMS_FETCH = 200      # articles taken per fetch
RSS_ITEMS_FEED = 500       # articles kept per feed
RSS_MAX_BYTES = 2 * 1024 * 1024
RSS_TIMEOUT, RSS_DEADLINE = 10, 20
RSS_TICK_FEEDS, RSS_TICK_S = 5, 8.0   # per watchdog tick: at most 5 feeds, no new fetch after 8 s
RSS_OPML_MAX = 1024 * 1024
RSS_SUMMARY_MAX = 500
RSS_TITLE_MAX = 300
RSS_URL_MAX = 2000
RSS_PAGE = 50
RSS_TRASH_DAYS = 7         # a deleted feed (undo possible) is purged after this
RSS_UA = {"Accept": "application/rss+xml, application/atom+xml, application/rdf+xml, application/xml, text/xml;q=0.9, */*;q=0.5",
          # 2.172.0 B (#2678): an own sender for feeds (the calendar one stays for calendars)
          "User-Agent": f"{APP_NAME}/{APP_VERSION} (feed reader; +https://kalmido.com)"}
RSS_ERR = {"parse": N_("This address does not deliver a feed (RSS or Atom)"),
           # 2.172.0 B (#2678): 403 is not a wrong password for a feed (sites behind a firewall refuse server fetches)
           "forbidden": N_("The website does not allow fetches by servers (403)"),
           "dtd": N_("The feed contains a DTD, which is not allowed"),
           "too_large": N_("The feed is larger than {0} MB")}


def rss_err_text(stored):
    """The text of a stored fetch error ("code" or "code:detail", the codes of the calendar subscriptions + parse / dtd)."""
    code = (stored or "error").partition(":")[0]
    if code == "too_large":
        return tr(RSS_ERR["too_large"], RSS_MAX_BYTES // (1024 * 1024))
    if code in RSS_ERR:
        return tr(RSS_ERR[code])
    return cal_err_text(stored)


def rss_need(c, uid):
    """The person's own module; never an agent, never an API token (feeds are only for people in 2.85.0)."""
    from flask import g, has_request_context
    from ..agents.core import is_agent
    if has_request_context() and (is_agent(getattr(g, "user", None)) or g.get("auth_via") == "token"):
        raise Denied(403, tr("Feeds are only available in the app"))
    need_life(c, uid, "feeds")


# ---- parsing
class _Text(HTMLParser):
    """HTML -> plain text (script / style content dropped)."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "template"):
            self.skip += 1
        elif tag in ("br", "p", "div", "li", "h1", "h2", "h3", "h4", "tr"):
            self.out.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template") and self.skip:
            self.skip -= 1

    def handle_data(self, d):
        if not self.skip:
            self.out.append(d)


def rss_text(s, n):
    """Plain text of an HTML / text snippet, whitespace collapsed, at most n characters."""
    s = str(s or "")
    if "<" in s or "&" in s:
        p = _Text()
        try:
            p.feed(s[:200000])
            p.close()
            s = "".join(p.out)
        except Exception:  # noqa: BLE001  (broken markup: drop what looks like tags)
            s = unescape(re.sub(r"<[^>]*>", " ", s))
    s = re.sub(r"\s+", " ", "".join(ch for ch in s if ch >= " " or ch in "\t\n")).strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def rss_url(u, base=""):
    """An absolute http(s) link (relative ones against base), else ''."""
    u = str(u or "").strip()
    if not u or len(u.encode()) > RSS_URL_MAX:  # 2.122.4 (#1906): bytes, the unique index caps a row
        return ""
    if base:
        try:
            u = urllib.parse.urljoin(base, u)
        except ValueError:
            return ""
    if any(ch.isspace() or ord(ch) < 32 for ch in u):
        return ""
    p = urllib.parse.urlsplit(u)
    if p.scheme.lower() not in ("http", "https") or not p.netloc or p.username or p.password:
        return ""
    return u[:RSS_URL_MAX]


def rss_date(s):
    """RFC 822 (RSS) or ISO 8601 (Atom, dc:date) -> ISO UTC, else None."""
    s = str(s or "").strip()
    if not s:
        return None
    d = None
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d is None:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    try:
        return iso(d.astimezone(timezone.utc))
    except (OverflowError, ValueError):
        return None


def _ln(el):
    return el.tag.rsplit("}", 1)[-1] if isinstance(el.tag, str) else ""


def _kid(el, *names):
    for ch in el:
        if _ln(ch) in names:
            return ch
    return None


def _txt(el, *names):
    ch = _kid(el, *names)
    return "".join(ch.itertext()) if ch is not None else ""


def _atom_link(el):
    best = ""
    for ch in el:
        if _ln(ch) == "link" and ch.get("href"):
            rel = ch.get("rel") or "alternate"
            if rel == "alternate":
                return ch.get("href")
            best = best or (ch.get("href") if rel not in ("self", "hub", "enclosure", "replies") else "")
    return best


def rss_parse(data, base):
    """(feed {title, site_url}, [articles {guid, url, title, summary, published}]) of a feed body; CalError("parse" / "dtd")."""
    try:
        root = xml_no_dtd(data)
    except _DtdRefused:
        raise CalError("dtd") from None
    except (ET.ParseError, ValueError, UnicodeError):
        raise CalError("parse") from None
    kind = _ln(root)
    if kind == "rss":
        ch = _kid(root, "channel")
        if ch is None:
            raise CalError("parse")
        site = rss_url(_txt(ch, "link"), base)
        entries = [x for x in ch if _ln(x) == "item"]
        meta = {"title": rss_text(_txt(ch, "title"), RSS_TITLE_MAX), "site_url": site}
    elif kind == "feed":
        site = rss_url(_atom_link(root), base)
        entries = [x for x in root if _ln(x) == "entry"]
        meta = {"title": rss_text(_txt(root, "title"), RSS_TITLE_MAX), "site_url": site}
    elif kind == "RDF":
        ch = _kid(root, "channel")
        site = rss_url(_txt(ch, "link"), base) if ch is not None else ""
        entries = [x for x in root if _ln(x) == "item"]
        meta = {"title": rss_text(_txt(ch, "title"), RSS_TITLE_MAX) if ch is not None else "", "site_url": site}
    else:
        raise CalError("parse")
    lbase = site or base
    out = []
    for e in entries[:RSS_ITEMS_FETCH]:
        if kind == "feed":
            url = rss_url(_atom_link(e), lbase)
            guid = _txt(e, "id").strip()
            pub = rss_date(_txt(e, "published") or _txt(e, "updated"))
            summ = _txt(e, "summary") or _txt(e, "content")
        else:
            url = rss_url(_txt(e, "link"), lbase)
            guid = _txt(e, "guid").strip() or (e.get("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about") or "").strip()
            pub = rss_date(_txt(e, "pubDate") or _txt(e, "date") or _txt(e, "published") or _txt(e, "updated"))
            summ = _txt(e, "description") or _txt(e, "encoded") or _txt(e, "summary")
        title = rss_text(_txt(e, "title"), RSS_TITLE_MAX)
        summary = rss_text(summ, RSS_SUMMARY_MAX)
        if not title:
            title = summary[:120] or url or ""
        guid = (guid or url or title)[:500]
        if not guid or not (title or url):
            continue
        out.append({"guid": guid, "url": url, "title": title[:RSS_TITLE_MAX], "summary": summary, "published": pub})
    return meta, out


# ---- fetching
def rss_get(c, url, etag="", modified=""):
    """(status, headers, body, final url) through the SSRF guard (redirects to another host only over https)."""
    hd = dict(RSS_UA)
    if etag:
        hd["If-None-Match"] = etag[:200]
    if modified:
        hd["If-Modified-Since"] = modified[:100]
    try:
        return cal_http(url, headers=hd, allow=cal_allow(c), cross_redirects=True, max_bytes=RSS_MAX_BYTES,
                        timeout=RSS_TIMEOUT, deadline=RSS_DEADLINE)
    except CalError as e:  # 2.172.0 B (#2678): cal_http maps 401 and 403 to "auth"; for feeds only 401 is a login
        if e.code == "auth" and e.detail == "403":
            raise CalError("forbidden", 403) from None
        raise


def rss_store(c, f, items, now):
    """New articles of feed row f (one per guid; older than RSS_KEEP_DAYS are not taken) -> how many."""
    cut = iso(now - timedelta(days=RSS_KEEP_DAYS))
    ts, n = iso(now), 0
    for it in items:
        pub = it["published"] or ts
        if pub < cut:
            continue
        r = c.execute("""INSERT INTO rss_items(feed_id,user_id,guid,url,title,summary,published,fetched_at)
                         VALUES(?,?,?,?,?,?,?,?) ON CONFLICT (feed_id, guid) DO NOTHING RETURNING id""",
                      (f["id"], f["user_id"], it["guid"], it["url"], it["title"], it["summary"], min(pub, ts), ts)).fetchone()
        n += 1 if r else 0
    if n:
        c.execute("""DELETE FROM rss_items WHERE feed_id=? AND id NOT IN (SELECT id FROM rss_items WHERE feed_id=?
                     ORDER BY published DESC, id DESC LIMIT ?)""", (f["id"], f["id"], RSS_ITEMS_FEED))
    return n


def rss_fetch(c, f):
    """Fetches feed row f once and stores what came; the outcome (error code or '') is stored in the feed. -> (new, code)."""
    now = now_utc()
    try:
        with c.savepoint():  # 2.85.0 review: a database error inside rolls back only this fetch
            st, hdrs, raw, final = rss_get(c, f["url"], f["etag"], f["last_modified"])
            new = 0
            if st != 304:
                try:
                    meta, items = rss_parse(raw, final)
                except CalError:
                    raise
                except Exception:  # noqa: BLE001  (whatever a hostile body does to the parser: never stall the other feeds)
                    raise CalError("parse") from None
                new = rss_store(c, f, items, now)
                c.execute("UPDATE rss_feeds SET title=CASE WHEN title='' THEN ? ELSE title END, site_url=? WHERE id=?",
                          (meta["title"] or "", meta["site_url"] or "", f["id"]))
            c.execute("UPDATE rss_feeds SET etag=?, last_modified=?, last_fetch=?, last_ok=?, last_error='', fails=0 WHERE id=?",
                      (((hdrs.get("ETag") if hdrs else "") or f["etag"] or "")[:200],
                       ((hdrs.get("Last-Modified") if hdrs else "") or f["last_modified"] or "")[:100], iso(now), iso(now), f["id"]))
            return new, ""
    except Exception as e:  # noqa: BLE001  (2.85.0 review: any error moves the feed into the back-off, the queue goes on)
        code = e.stored() if isinstance(e, CalError) else "error"
        c.execute("UPDATE rss_feeds SET last_fetch=?, last_error=?, fails=fails+1 WHERE id=?", (iso(now), code[:40], f["id"]))
        return 0, code


# ---- the feeds of a person
# 2.172.0 B (#2677): feeds live in a space like bookmarks -- org_id NULL = private (only its owner), else every member of
# the organisation (not guests / accounting) reads them; the sources of an organisation are followed, unfollowed and
# imported by its admins. The read mark is per person: rss_items.read_at for private feeds (as before), rss_reads for the
# feeds of an organisation. Every view shows ONE space (no mixed view); without a space the private one (the API before).
def rss_space(c, uid, v, write=False):
    """org id (None = private) of a space value "private" | "org:<id>" | <id>; 404 for an organisation uid is not in (or
    only as guest / accounting), 403 for a change by a read-only member (write)."""
    if v in (None, "", "private", 0, "0"):
        return None
    s = str(v)
    if s.startswith("org:"):
        s = s[4:]
    try:
        oid = int(s)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", "space")) from None
    from ..accounts.orgs import user_orgs
    from ..accounts.orgroles import need_org_area
    if oid not in user_orgs(c, uid):
        raise Denied(404)
    need_org_area(c, uid, oid, write=write)
    return oid


def rss_space_key(oid):
    return f"org:{oid}" if oid else "private"


def rss_may_manage(c, uid, oid):
    """Follow / unfollow / import the sources of a space: private = the person, an organisation = its admins."""
    if not oid:
        return True
    from ..accounts.orgs import is_org_admin
    from ..accounts.orgroles import org_writes
    return is_org_admin(c, uid, oid) and org_writes(c, uid, oid)


def rss_need_manage(c, uid, oid):
    if not rss_may_manage(c, uid, oid):
        raise Denied(403, tr("Only admins of the organisation can change its feeds"))


def _fw(oid, uid, a="f"):
    """SQL + args: the feeds (alias a) of a space."""
    return (f"{a}.org_id=?", [oid]) if oid else (f"{a}.org_id IS NULL AND {a}.user_id=?", [uid])


def _rd(oid):
    """SQL of the person's read mark of article i (one ? = the person in an organisation's space)."""
    return "(SELECT r.read_at FROM rss_reads r WHERE r.item_id=i.id AND r.user_id=?)" if oid else "i.read_at"


def rss_feed_out(r, unread=0):
    return {"id": r["id"], "url": r["url"], "title": r["title"] or urllib.parse.urlsplit(r["url"]).hostname or r["url"],
            "site_url": r["site_url"], "last_fetch": r["last_fetch"], "last_ok": r["last_ok"],
            "error": rss_err_text(r["last_error"]) if r["last_error"] else "", "unread": unread,
            "space": rss_space_key(r["org_id"] if "org_id" in r.keys() else None)}


def rss_feeds(c, uid, oid=None):
    w, a = _fw(oid, uid)
    ra = [uid] if oid else []
    un = dict(c.execute(f"""SELECT i.feed_id, COUNT(*) FROM rss_items i JOIN rss_feeds f ON f.id=i.feed_id WHERE {w}
                            AND f.deleted_at IS NULL AND {_rd(oid)} IS NULL GROUP BY i.feed_id""", (*a, *ra)).fetchall())
    rows = c.execute(f"SELECT f.* FROM rss_feeds f WHERE {w} AND f.deleted_at IS NULL ORDER BY LOWER(f.title), f.id", a).fetchall()
    feeds = [rss_feed_out(r, un.get(r["id"], 0)) for r in rows]
    return {"feeds": feeds, "unread": sum(x["unread"] for x in feeds), "max": RSS_MAX_FEEDS, "space": rss_space_key(oid),
            "manage": rss_may_manage(c, uid, oid)}


def rss_unread(c, uid, oid=None):
    w, a = _fw(oid, uid)
    return c.execute(f"""SELECT COUNT(*) FROM rss_items i JOIN rss_feeds f ON f.id=i.feed_id WHERE {w} AND f.deleted_at IS NULL
                         AND {_rd(oid)} IS NULL""", (*a, *([uid] if oid else []))).fetchone()[0]


def rss_own(c, uid, fid, manage=False):
    """The feed row if uid sees it (404 otherwise: another person's private feed, an organisation uid is not in);
    manage: 403 unless uid may change the sources of its space."""
    r = c.execute("SELECT * FROM rss_feeds WHERE id=?", (fid,)).fetchone()
    if not r:
        raise Denied(404, tr("Not found"))
    if r["org_id"] is None:
        if r["user_id"] != uid:
            raise Denied(404, tr("Not found"))
    else:
        rss_space(c, uid, r["org_id"])
        if manage:
            rss_need_manage(c, uid, r["org_id"])
    return r


def _norm(u):
    """A feed address as http(s)://… (feed:// and webcal:// become https://), or None."""
    u = str(u or "").strip()
    if u.lower().startswith("feed://"):
        u = "https://" + u[7:]
    u = cal_norm_url(u)
    if not u:
        return None
    return u if rss_url(u) == u else None


def _count(c, uid, oid=None):
    w, a = _fw(oid, uid, "rss_feeds")
    return c.execute(f"SELECT COUNT(*) FROM rss_feeds WHERE {w} AND deleted_at IS NULL", a).fetchone()[0]


def rss_add(c, uid, b):
    """{url, space?}: subscribes after one successful fetch (the error says why not)."""
    rss_need(c, uid)
    oid = rss_space(c, uid, b.get("space"), write=True)
    rss_need_manage(c, uid, oid)
    raw = b.get("url")
    url = _norm(raw) if isinstance(raw, str) else None
    if not url:
        raise BadInput(tr("Please enter the address of a feed (http or https)"))
    w, a = _fw(oid, uid, "rss_feeds")
    old = c.execute(f"SELECT * FROM rss_feeds WHERE {w} AND url=? ORDER BY deleted_at IS NOT NULL, id LIMIT 1", (*a, url)).fetchone()
    if old and not old["deleted_at"]:
        raise BadInput(tr("You already follow this feed"))
    if _count(c, uid, oid) >= RSS_MAX_FEEDS:
        raise BadInput(tr("At most {0} feeds", RSS_MAX_FEEDS))
    if not cal_rate(uid):
        raise Denied(429, tr("Too many attempts, please wait a few minutes"))
    if old:  # a deleted one comes back with its articles
        fid = old["id"] if rg4_feed_restore(c, old["id"]) else None
    else:  # 2.122.4 A (#1906): a parallel request (double tap) that inserted first wins (unique index per space)
        fid = insert_id(c, "INSERT INTO rss_feeds(user_id,org_id,url,created_at) VALUES(?,?,?,?) ON CONFLICT DO NOTHING",
                        (uid, oid, url, iso(now_utc())))
    if not fid:
        raise BadInput(tr("You already follow this feed"))
    f = c.execute("SELECT * FROM rss_feeds WHERE id=?", (fid,)).fetchone()
    new, code = rss_fetch(c, f)
    if code:
        if old:
            c.execute("UPDATE rss_feeds SET deleted_at=? WHERE id=?", (old["deleted_at"], fid))
        else:
            c.execute("DELETE FROM rss_feeds WHERE id=?", (fid,))
        raise BadInput(rss_err_text(code))
    f = c.execute("SELECT * FROM rss_feeds WHERE id=?", (fid,)).fetchone()
    return {"feed": rss_feed_out(f, rss_items_unread(c, uid, f)), "new": new}


def rss_items_unread(c, uid, f):
    """Unread articles of feed row f for uid."""
    if f["org_id"]:
        return c.execute("""SELECT COUNT(*) FROM rss_items i WHERE i.feed_id=? AND NOT EXISTS
                            (SELECT 1 FROM rss_reads r WHERE r.item_id=i.id AND r.user_id=?)""", (f["id"], uid)).fetchone()[0]
    return c.execute("SELECT COUNT(*) FROM rss_items WHERE feed_id=? AND read_at IS NULL", (f["id"],)).fetchone()[0]


def rss_delete(c, uid, fid):
    """Deleted with its articles hidden; POST .../restore brings it back (purged after RSS_TRASH_DAYS)."""
    rss_need(c, uid)
    f = rss_own(c, uid, fid, manage=True)
    if not f["deleted_at"]:
        c.execute("UPDATE rss_feeds SET deleted_at=? WHERE id=?", (iso(now_utc()), fid))
    return {"ok": True}


def rss_restore(c, uid, fid):
    rss_need(c, uid)
    f = rss_own(c, uid, fid, manage=True)
    if f["deleted_at"]:
        oid = f["org_id"]
        w, a = _fw(oid, uid, "rss_feeds")
        if c.execute(f"SELECT 1 FROM rss_feeds WHERE {w} AND url=? AND deleted_at IS NULL", (*a, f["url"])).fetchone():
            raise BadInput(tr("You already follow this feed"))
        if _count(c, uid, oid) >= RSS_MAX_FEEDS:
            raise BadInput(tr("At most {0} feeds", RSS_MAX_FEEDS))
        if not rg4_feed_restore(c, fid):  # 2.122.4 A (#1906): followed again in parallel
            raise BadInput(tr("You already follow this feed"))
    return {"feed": rss_feed_out(rss_own(c, uid, fid))}


def _item_out(r):
    return {"id": r["id"], "feed_id": r["feed_id"], "feed": r["ftitle"] or urllib.parse.urlsplit(r["furl"]).hostname or "",
            "url": r["url"], "title": r["title"], "summary": r["summary"], "published": r["published"],
            "read": bool(r["rd"]), "task_id": r["saved_task_id"]}


def rss_items(c, uid, feed=None, unread=False, offset=0, oid=None):
    """The newest articles of a space first (one feed / only unread on request), RSS_PAGE per page."""
    rss_need(c, uid)
    w, a = _fw(oid, uid)
    ra = [uid] if oid else []
    q, qa = "", []
    if feed:
        f = rss_own(c, uid, feed)
        if f["org_id"] != oid:  # 2.172.0 B (#2677): a feed of another space is not in this view
            raise Denied(404, tr("Not found"))
        q += " AND i.feed_id=?"
        qa.append(feed)
    if unread:
        q += f" AND {_rd(oid)} IS NULL"
        qa += ra
    rows = c.execute(f"""SELECT i.*, {_rd(oid)} AS rd, f.title AS ftitle, f.url AS furl FROM rss_items i JOIN rss_feeds f ON f.id=i.feed_id
                         WHERE {w} AND f.deleted_at IS NULL{q} ORDER BY i.published DESC, i.id DESC LIMIT ? OFFSET ?""",
                     (*ra, *a, *qa, RSS_PAGE + 1, offset)).fetchall()
    return {"items": [_item_out(r) for r in rows[:RSS_PAGE]], "more": len(rows) > RSS_PAGE, "unread": rss_unread(c, uid, oid),
            "space": rss_space_key(oid)}


def rss_mark(c, uid, b):
    """{ids?: [...], feed_id?, read: bool, space?}: the given articles, else every unread one (of the feed) of the space ->
    {ids} changed. The read mark is the person's own (also in an organisation: read-only members may set it)."""
    rss_need(c, uid)
    unknown = sorted(set(b) - {"ids", "feed_id", "read", "space"})
    if unknown:
        raise BadInput(tr("Unknown field: {0}", ", ".join(unknown)[:200]))
    oid = rss_space(c, uid, b.get("space"))  # a GET-like gate: the mark is personal
    read = b.get("read", True)
    if not isinstance(read, bool):
        raise BadInput(tr("Invalid value: {0}", "read"))
    ids = None
    if b.get("ids") is not None:
        ids = b["ids"]
        if not isinstance(ids, list) or len(ids) > 1000:
            raise BadInput(tr("Invalid value: {0}", "ids"))
        ids = [as_int(x, "ids", 1) for x in ids]
        if not ids:
            return {"ids": []}
    fq, fa = "", []
    if ids is None and b.get("feed_id") not in (None, ""):
        fid = as_int(b["feed_id"], "feed_id", 1)
        if rss_own(c, uid, fid)["org_id"] != oid:
            raise Denied(404, tr("Not found"))
        fq, fa = " AND i.feed_id=?", [fid]
    iq, ia = (f" AND i.id IN ({','.join('?' * len(ids))})", ids) if ids is not None else ("", [])
    ts = iso(now_utc())
    w, a = _fw(oid, uid)
    if not oid:
        cond = "i.read_at IS NULL" if read else "i.read_at IS NOT NULL"
        rows = c.execute(f"""UPDATE rss_items SET read_at=? WHERE id IN (SELECT i.id FROM rss_items i JOIN rss_feeds f ON f.id=i.feed_id
                             WHERE {w} AND f.deleted_at IS NULL AND {cond}{iq}{fq}) RETURNING id""",
                         (ts if read else None, *a, *ia, *fa)).fetchall()
        return {"ids": sorted(r[0] for r in rows)}
    sel = (f"SELECT i.id FROM rss_items i JOIN rss_feeds f ON f.id=i.feed_id WHERE {w} AND f.deleted_at IS NULL{iq}{fq} AND "
           f"{'NOT ' if read else ''}EXISTS (SELECT 1 FROM rss_reads r WHERE r.item_id=i.id AND r.user_id=?)")
    if read:
        rows = c.execute(f"INSERT INTO rss_reads(item_id,user_id,read_at) SELECT x.id, ?, ? FROM ({sel}) x ON CONFLICT DO NOTHING RETURNING item_id",
                         (uid, ts, *a, *ia, *fa, uid)).fetchall()
    else:
        rows = c.execute(f"DELETE FROM rss_reads WHERE user_id=? AND item_id IN ({sel}) RETURNING item_id", (uid, *a, *ia, *fa, uid)).fetchall()
    return {"ids": sorted(r[0] for r in rows)}


def rss_later(c, uid, iid):
    """"Read later": a task (title + link) in the read-later project of the article's space (2.172.0 B, #2677: private or
    the organisation's), once per article -> {task_id, list_id, created, space}."""
    rss_need(c, uid)
    it = c.execute("SELECT i.*, f.org_id AS forg, f.user_id AS fuser FROM rss_items i JOIN rss_feeds f ON f.id=i.feed_id WHERE i.id=?",
                   (iid,)).fetchone()
    if not it or (it["forg"] is None and it["fuser"] != uid):
        raise Denied(404, tr("Not found"))
    oid = it["forg"]
    if oid:
        rss_space(c, uid, oid, write=True)
    if it["saved_task_id"]:
        t = c.execute("SELECT id, list_id FROM tasks WHERE id=? AND deleted_at IS NULL", (it["saved_task_id"],)).fetchone()
        if t and task_visible(c, t["id"], uid):  # 2.85.0 review: a task in a list the person lost access to counts as gone
            return {"task_id": t["id"], "list_id": t["list_id"], "created": False, "space": rss_space_key(oid)}
    from ..life.reading import rl_list
    lid = rl_list(c, uid, oid)
    tid = _insert(c, uid, lid, (it["title"] or it["url"] or tr("Article"))[:TITLE_MAX], url=it["url"] or None)
    ts = iso(now_utc())
    c.execute("UPDATE rss_items SET saved_task_id=? WHERE id=?", (tid, iid))
    if oid:
        c.execute("INSERT INTO rss_reads(item_id,user_id,read_at) VALUES(?,?,?) ON CONFLICT DO NOTHING", (iid, uid, ts))
    else:
        c.execute("UPDATE rss_items SET read_at=COALESCE(read_at, ?) WHERE id=?", (ts, iid))
    return {"task_id": tid, "list_id": lid, "created": True, "space": rss_space_key(oid)}


# ---- OPML
def _xml_attr(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
            .replace("\n", "&#10;").replace("\r", ""))


def rss_opml_export(c, uid, oid=None):
    rss_need(c, uid)
    w, a = _fw(oid, uid, "rss_feeds")
    rows = c.execute(f"SELECT url, title, site_url FROM rss_feeds WHERE {w} AND deleted_at IS NULL ORDER BY LOWER(title), id", a).fetchall()
    body = "".join(f'    <outline type="rss" text="{_xml_attr(r["title"] or r["url"])}" title="{_xml_attr(r["title"] or r["url"])}" '
                   f'xmlUrl="{_xml_attr(r["url"])}"' + (f' htmlUrl="{_xml_attr(r["site_url"])}"' if r["site_url"] else "") + "/>\n"
                   for r in rows)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<opml version="2.0">\n  <head>\n    <title>Kalmido feeds</title>\n'
            f'    <dateCreated>{_xml_attr(now_utc().strftime("%a, %d %b %Y %H:%M:%S +0000"))}</dateCreated>\n  </head>\n'
            f'  <body>\n{body}  </body>\n</opml>\n')


def rg4_feed_restore(c, fid):
    """2.122.4 A (#1906): a deleted feed comes back -> False when the same address is followed again meanwhile (the unique
    index rss_feeds_live refuses a second live row)."""
    try:
        with c.savepoint():
            c.execute("UPDATE rss_feeds SET deleted_at=NULL WHERE id=?", (fid,))
        return True
    except IntegrityError:
        return False


def rg4_feed_unique(c):
    """2.122.4 A (#1906), at start: one followed feed per address and person (partial unique index, additive). A database
    that already holds such duplicates keeps them (nothing is deleted) and only gets the index once they are gone.
    2.172.0 B (#2677): replaced by p2172b_feed_unique (one per address and space); kept for the record, not called."""
    if c.execute("SELECT 1 FROM pg_indexes WHERE indexname='rss_feeds_live'").fetchone():
        return
    if c.execute("SELECT 1 FROM rss_feeds WHERE deleted_at IS NULL GROUP BY user_id, url HAVING COUNT(*) > 1 LIMIT 1").fetchone():
        print("feeds (#1906): duplicate followed feeds found, the unique index waits until they are removed", flush=True)
        return
    try:
        with c.savepoint():
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS rss_feeds_live ON rss_feeds(user_id, url) WHERE deleted_at IS NULL")
    except IntegrityError:
        print("feeds (#1906): the unique index could not be built (duplicates)", flush=True)


def p2172b_feed_unique(c):
    """2.172.0 B (#2677), at start: one followed feed per address and space -- private (person, org_id NULL) and per
    organisation (partial unique indexes). The index of 2.122.4 (one per person, rss_feeds_live) would refuse an admin who
    follows the same address privately and for the organisation; it goes once the private index stands. A rollback to an
    older version builds it again where no person has the same address twice (else that version logs and waits)."""
    for name, cols, cond, dup in (
            ("rss_feeds_live_p", "user_id, url", "deleted_at IS NULL AND org_id IS NULL", "org_id IS NULL GROUP BY user_id, url"),
            ("rss_feeds_live_o", "org_id, url", "deleted_at IS NULL AND org_id IS NOT NULL", "org_id IS NOT NULL GROUP BY org_id, url")):
        if c.execute("SELECT 1 FROM pg_indexes WHERE indexname=?", (name,)).fetchone():
            continue
        if c.execute(f"SELECT 1 FROM rss_feeds WHERE deleted_at IS NULL AND {dup} HAVING COUNT(*) > 1 LIMIT 1").fetchone():
            print(f"feeds (#2677): duplicate followed feeds found, the unique index {name} waits until they are removed", flush=True)
            continue
        try:
            with c.savepoint():
                c.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {name} ON rss_feeds({cols}) WHERE {cond}")
        except IntegrityError:
            print(f"feeds (#2677): the unique index {name} could not be built (duplicates)", flush=True)
    if c.execute("SELECT 1 FROM pg_indexes WHERE indexname='rss_feeds_live_p'").fetchone():
        c.execute("DROP INDEX IF EXISTS rss_feeds_live")


def rss_opml_import(c, uid, raw, oid=None):
    """The feeds of an OPML file (nested outlines too) are subscribed without fetching (the background does that) ->
    {added, skipped, errors}; at most RSS_MAX_FEEDS in all (per space; an organisation's: its admins)."""
    rss_need(c, uid)
    rss_need_manage(c, uid, oid)
    if not raw or len(raw) > RSS_OPML_MAX:
        raise BadInput(tr("The file is too large (at most {0} MB)", RSS_OPML_MAX // (1024 * 1024)))
    try:
        root = xml_no_dtd(raw)
    except _DtdRefused:
        raise BadInput(tr(RSS_ERR["dtd"])) from None
    except (ET.ParseError, ValueError, UnicodeError):
        raise BadInput(tr("Not a valid OPML file")) from None
    if _ln(root) != "opml":
        raise BadInput(tr("Not a valid OPML file"))
    # 2.122.4 A (#1906): a followed feed wins over a deleted one with the same address (live rows last)
    w, a = _fw(oid, uid, "rss_feeds")
    have = {r[0]: r[1] for r in c.execute(f"SELECT url, deleted_at FROM rss_feeds WHERE {w} ORDER BY deleted_at IS NULL, id", a).fetchall()}
    n = _count(c, uid, oid)
    added = skipped = errors = 0
    ts = iso(now_utc())
    seen = 0
    for o in root.iter():
        if _ln(o) != "outline" or not o.get("xmlUrl"):
            continue
        seen += 1
        if seen > 1000:
            break
        url = _norm(o.get("xmlUrl"))
        if not url:
            errors += 1
            continue
        if url in have and not have[url]:
            skipped += 1
            continue
        if n >= RSS_MAX_FEEDS:
            errors += 1
            continue
        title = rss_text(o.get("title") or o.get("text") or "", RSS_TITLE_MAX)
        if url in have:  # deleted before: back (2.122.4 A (#1906): the newest one only, never twice)
            r = c.execute(f"SELECT MAX(id) FROM rss_feeds WHERE {w} AND url=? AND deleted_at IS NOT NULL", (*a, url)).fetchone()
            done = bool(r and r[0]) and rg4_feed_restore(c, r[0])
        else:  # 2.122.4 A (#1906): a parallel import / add of the same address keeps one feed
            done = insert_id(c, "INSERT INTO rss_feeds(user_id,org_id,url,title,site_url,created_at) VALUES(?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                             (uid, oid, url, title, rss_url(o.get("htmlUrl") or ""), ts))
        if not done:
            have[url] = None
            skipped += 1
            continue
        have[url] = None
        n += 1
        added += 1
    return {"added": added, "skipped": skipped, "errors": errors, "max": RSS_MAX_FEEDS}


# ---- background
def rss_due(f, now):
    if not f["last_fetch"]:
        return True
    gap = RSS_SLOW if f["fails"] >= RSS_SLOW_AFTER else RSS_EVERY
    return (now - parse_iso(f["last_fetch"])).total_seconds() >= gap


_RSS_RUN = threading.Lock()


def _wd_feeds(c, users, S, LG, now):  # noqa: ARG001
    """Watchdog: starts the fetch of due feeds of people with the module on in a thread of its own (2.85.0 review: a slow
    feed server never holds up reminders and the other sections; at most one run at a time) and cleans up old articles
    and deleted feeds."""
    on = [u for u in users if "feeds" in (S[u].get("features") or "").split(",")]
    if on and _RSS_RUN.acquire(blocking=False):
        threading.Thread(target=_rss_run, args=(on,), daemon=True).start()
    nu = now_utc()
    c.execute("DELETE FROM rss_items WHERE published<?", (iso(nu - timedelta(days=RSS_KEEP_DAYS)),))
    c.execute("DELETE FROM rss_feeds WHERE deleted_at IS NOT NULL AND deleted_at<?", (iso(nu - timedelta(days=RSS_TRASH_DAYS)),))
    c.commit()


def _rss_run(on):
    """Due feeds of the people `on` (a few per run, the oldest first; a feed nobody reads never holds up the others)."""
    try:
        c = connect()
        try:
            t0, done, nu = time.monotonic(), 0, now_utc()
            ph = ",".join("?" * len(on))  # 2.172.0 B (#2677): + the feeds of organisations with a member who reads feeds
            rows = c.execute(f"""SELECT * FROM rss_feeds WHERE deleted_at IS NULL AND (user_id IN ({ph}) OR org_id IN
                                 (SELECT org_id FROM org_members WHERE user_id IN ({ph}))) AND
                                 (last_fetch IS NULL OR (fails<? AND last_fetch<?) OR last_fetch<?) ORDER BY COALESCE(last_fetch, '') LIMIT 20""",
                             (*on, *on, RSS_SLOW_AFTER, iso(nu - timedelta(seconds=RSS_EVERY)), iso(nu - timedelta(seconds=RSS_SLOW)))).fetchall()
            for f in rows:
                if done >= RSS_TICK_FEEDS or time.monotonic() - t0 > RSS_TICK_S:
                    break
                if not rss_due(f, nu):
                    continue
                rss_fetch(c, f)
                c.commit()
                done += 1
        finally:
            c.close()
    except Exception as e:  # noqa: BLE001
        print("feeds run error:", type(e).__name__, flush=True)
    finally:
        _RSS_RUN.release()  # 2.137.0 (#2408): no statement after c.close() -- the clean-up runs in _wd_feeds on its own connection
