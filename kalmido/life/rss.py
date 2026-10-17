"""Home & life: feeds (RSS 2.0, Atom 1.0, RSS 1.0 / RDF) of one person, fetched by the server, read in the view "Feeds"."""
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser

from ..core.i18n import N_, tr
from ..core.db import iso, now_utc, parse_iso
from ..core.pg import insert_id
from ..core.access import Denied
from ..tasks.validation import as_int, TITLE_MAX
from ..personal.timetrack import BadInput
from ..calendars.caldav import _DtdRefused, xml_no_dtd
from ..calendars.subscriptions import CalError, cal_allow, cal_err_text, cal_http, cal_norm_url, cal_rate
from ..life.model import _insert, life_list, need_life


# ---------------------------------------------------------------- 2.85.0 B (#1162): feeds
# Module "feeds" (off by default). Feeds belong to the person (no organisation, never shared, never an agent's: no v1
# route, no MCP tool). Every fetch goes through the SSRF guard of the calendar subscriptions (cal_http: http/https only,
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
RSS_UA = {"Accept": "application/rss+xml, application/atom+xml, application/rdf+xml, application/xml, text/xml;q=0.9, */*;q=0.5"}
RSS_ERR = {"parse": N_("This address does not deliver a feed (RSS or Atom)"),
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
    if not u or len(u) > RSS_URL_MAX:
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
    return cal_http(url, headers=hd, allow=cal_allow(c), cross_redirects=True, max_bytes=RSS_MAX_BYTES,
                    timeout=RSS_TIMEOUT, deadline=RSS_DEADLINE)


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
    except CalError as e:
        c.execute("UPDATE rss_feeds SET last_fetch=?, last_error=?, fails=fails+1 WHERE id=?", (iso(now), e.stored()[:40], f["id"]))
        return 0, e.stored()


# ---- the feeds of a person
def rss_feed_out(r, unread=0):
    return {"id": r["id"], "url": r["url"], "title": r["title"] or urllib.parse.urlsplit(r["url"]).hostname or r["url"],
            "site_url": r["site_url"], "last_fetch": r["last_fetch"], "last_ok": r["last_ok"],
            "error": rss_err_text(r["last_error"]) if r["last_error"] else "", "unread": unread}


def rss_feeds(c, uid):
    un = dict(c.execute("SELECT feed_id, COUNT(*) FROM rss_items WHERE user_id=? AND read_at IS NULL GROUP BY feed_id", (uid,)).fetchall())
    rows = c.execute("SELECT * FROM rss_feeds WHERE user_id=? AND deleted_at IS NULL ORDER BY LOWER(title), id", (uid,)).fetchall()
    feeds = [rss_feed_out(r, un.get(r["id"], 0)) for r in rows]
    return {"feeds": feeds, "unread": sum(x["unread"] for x in feeds), "max": RSS_MAX_FEEDS}


def rss_unread(c, uid):
    return c.execute("""SELECT COUNT(*) FROM rss_items i JOIN rss_feeds f ON f.id=i.feed_id WHERE i.user_id=? AND i.read_at IS NULL
                        AND f.deleted_at IS NULL""", (uid,)).fetchone()[0]


def rss_own(c, uid, fid):
    r = c.execute("SELECT * FROM rss_feeds WHERE id=? AND user_id=?", (fid, uid)).fetchone()
    if not r:
        raise Denied(404, tr("Not found"))
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


def _count(c, uid):
    return c.execute("SELECT COUNT(*) FROM rss_feeds WHERE user_id=? AND deleted_at IS NULL", (uid,)).fetchone()[0]


def rss_add(c, uid, b):
    """{url}: subscribes after one successful fetch (the error says why not)."""
    rss_need(c, uid)
    raw = b.get("url")
    url = _norm(raw) if isinstance(raw, str) else None
    if not url:
        raise BadInput(tr("Please enter the address of a feed (http or https)"))
    old = c.execute("SELECT * FROM rss_feeds WHERE user_id=? AND url=? ORDER BY deleted_at IS NOT NULL, id LIMIT 1", (uid, url)).fetchone()
    if old and not old["deleted_at"]:
        raise BadInput(tr("You already follow this feed"))
    if _count(c, uid) >= RSS_MAX_FEEDS:
        raise BadInput(tr("At most {0} feeds", RSS_MAX_FEEDS))
    if not cal_rate(uid):
        raise Denied(429, tr("Too many attempts, please wait a few minutes"))
    if old:  # a deleted one comes back with its articles
        c.execute("UPDATE rss_feeds SET deleted_at=NULL WHERE id=?", (old["id"],))
        fid = old["id"]
    else:
        fid = insert_id(c, "INSERT INTO rss_feeds(user_id,url,created_at) VALUES(?,?,?)", (uid, url, iso(now_utc())))
    f = c.execute("SELECT * FROM rss_feeds WHERE id=?", (fid,)).fetchone()
    new, code = rss_fetch(c, f)
    if code:
        if old:
            c.execute("UPDATE rss_feeds SET deleted_at=? WHERE id=?", (old["deleted_at"], fid))
        else:
            c.execute("DELETE FROM rss_feeds WHERE id=?", (fid,))
        raise BadInput(rss_err_text(code))
    f = c.execute("SELECT * FROM rss_feeds WHERE id=?", (fid,)).fetchone()
    return {"feed": rss_feed_out(f, c.execute("SELECT COUNT(*) FROM rss_items WHERE feed_id=? AND read_at IS NULL", (fid,)).fetchone()[0]),
            "new": new}


def rss_delete(c, uid, fid):
    """Deleted with its articles hidden; POST .../restore brings it back (purged after RSS_TRASH_DAYS)."""
    rss_need(c, uid)
    f = rss_own(c, uid, fid)
    if not f["deleted_at"]:
        c.execute("UPDATE rss_feeds SET deleted_at=? WHERE id=?", (iso(now_utc()), fid))
    return {"ok": True}


def rss_restore(c, uid, fid):
    rss_need(c, uid)
    f = rss_own(c, uid, fid)
    if f["deleted_at"]:
        if c.execute("SELECT 1 FROM rss_feeds WHERE user_id=? AND url=? AND deleted_at IS NULL", (uid, f["url"])).fetchone():
            raise BadInput(tr("You already follow this feed"))
        if _count(c, uid) >= RSS_MAX_FEEDS:
            raise BadInput(tr("At most {0} feeds", RSS_MAX_FEEDS))
        c.execute("UPDATE rss_feeds SET deleted_at=NULL WHERE id=?", (fid,))
    return {"feed": rss_feed_out(rss_own(c, uid, fid))}


def _item_out(r):
    return {"id": r["id"], "feed_id": r["feed_id"], "feed": r["ftitle"] or urllib.parse.urlsplit(r["furl"]).hostname or "",
            "url": r["url"], "title": r["title"], "summary": r["summary"], "published": r["published"],
            "read": bool(r["read_at"]), "task_id": r["saved_task_id"]}


def rss_items(c, uid, feed=None, unread=False, offset=0):
    """The newest articles first (one feed / only unread on request), RSS_PAGE per page."""
    rss_need(c, uid)
    q, a = "", [uid]
    if feed:
        rss_own(c, uid, feed)
        q += " AND i.feed_id=?"
        a.append(feed)
    if unread:
        q += " AND i.read_at IS NULL"
    rows = c.execute(f"""SELECT i.*, f.title AS ftitle, f.url AS furl FROM rss_items i JOIN rss_feeds f ON f.id=i.feed_id
                         WHERE i.user_id=? AND f.deleted_at IS NULL{q} ORDER BY i.published DESC, i.id DESC LIMIT ? OFFSET ?""",
                     (*a, RSS_PAGE + 1, offset)).fetchall()
    return {"items": [_item_out(r) for r in rows[:RSS_PAGE]], "more": len(rows) > RSS_PAGE, "unread": rss_unread(c, uid)}


def rss_mark(c, uid, b):
    """{ids?: [...], feed_id?, read: bool}: the given articles, else every unread one (of the feed) -> {ids} changed."""
    rss_need(c, uid)
    unknown = sorted(set(b) - {"ids", "feed_id", "read"})
    if unknown:
        raise BadInput(tr("Unknown field: {0}", ", ".join(unknown)[:200]))
    read = b.get("read", True)
    if not isinstance(read, bool):
        raise BadInput(tr("Invalid value: {0}", "read"))
    ts = iso(now_utc()) if read else None
    cond = "read_at IS NULL" if read else "read_at IS NOT NULL"
    if b.get("ids") is not None:
        ids = b["ids"]
        if not isinstance(ids, list) or len(ids) > 1000:
            raise BadInput(tr("Invalid value: {0}", "ids"))
        ids = [as_int(x, "ids", 1) for x in ids]
        if not ids:
            return {"ids": []}
        rows = c.execute(f"UPDATE rss_items SET read_at=? WHERE user_id=? AND {cond} AND id IN ({','.join('?' * len(ids))}) RETURNING id",
                         (ts, uid, *ids)).fetchall()
    else:
        q, a = "", []
        if b.get("feed_id") not in (None, ""):
            fid = as_int(b["feed_id"], "feed_id", 1)
            rss_own(c, uid, fid)
            q, a = " AND feed_id=?", [fid]
        rows = c.execute(f"""UPDATE rss_items SET read_at=? WHERE user_id=? AND {cond}{q}
                             AND feed_id IN (SELECT id FROM rss_feeds WHERE user_id=? AND deleted_at IS NULL) RETURNING id""",
                         (ts, uid, *a, uid)).fetchall()
    return {"ids": sorted(r[0] for r in rows)}


def rss_later(c, uid, iid):
    """"Read later": a task (title + link) in the person's reading list, once per article -> {task_id, list_id, created}."""
    rss_need(c, uid)
    it = c.execute("SELECT * FROM rss_items WHERE id=? AND user_id=?", (iid, uid)).fetchone()
    if not it:
        raise Denied(404, tr("Not found"))
    if it["saved_task_id"]:
        t = c.execute("SELECT id, list_id FROM tasks WHERE id=? AND deleted_at IS NULL", (it["saved_task_id"],)).fetchone()
        if t:
            return {"task_id": t["id"], "list_id": t["list_id"], "created": False}
    lid = life_list(c, uid, "reading")
    tid = _insert(c, uid, lid, (it["title"] or it["url"] or tr("Article"))[:TITLE_MAX], url=it["url"] or None)
    c.execute("UPDATE rss_items SET saved_task_id=?, read_at=COALESCE(read_at, ?) WHERE id=?", (tid, iso(now_utc()), iid))
    return {"task_id": tid, "list_id": lid, "created": True}


# ---- OPML
def _xml_attr(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
            .replace("\n", "&#10;").replace("\r", ""))


def rss_opml_export(c, uid):
    rss_need(c, uid)
    rows = c.execute("SELECT url, title, site_url FROM rss_feeds WHERE user_id=? AND deleted_at IS NULL ORDER BY LOWER(title), id", (uid,)).fetchall()
    body = "".join(f'    <outline type="rss" text="{_xml_attr(r["title"] or r["url"])}" title="{_xml_attr(r["title"] or r["url"])}" '
                   f'xmlUrl="{_xml_attr(r["url"])}"' + (f' htmlUrl="{_xml_attr(r["site_url"])}"' if r["site_url"] else "") + "/>\n"
                   for r in rows)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<opml version="2.0">\n  <head>\n    <title>Kalmido feeds</title>\n'
            f'    <dateCreated>{_xml_attr(now_utc().strftime("%a, %d %b %Y %H:%M:%S +0000"))}</dateCreated>\n  </head>\n'
            f'  <body>\n{body}  </body>\n</opml>\n')


def rss_opml_import(c, uid, raw):
    """The feeds of an OPML file (nested outlines too) are subscribed without fetching (the background does that) ->
    {added, skipped, errors}; at most RSS_MAX_FEEDS in all."""
    rss_need(c, uid)
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
    have = {r[0]: r[1] for r in c.execute("SELECT url, deleted_at FROM rss_feeds WHERE user_id=?", (uid,)).fetchall()}
    n = _count(c, uid)
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
        if url in have:  # deleted before: back
            c.execute("UPDATE rss_feeds SET deleted_at=NULL WHERE user_id=? AND url=? AND deleted_at IS NOT NULL", (uid, url))
        else:
            c.execute("INSERT INTO rss_feeds(user_id,url,title,site_url,created_at) VALUES(?,?,?,?,?)",
                      (uid, url, title, rss_url(o.get("htmlUrl") or ""), ts))
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


def _wd_feeds(c, users, S, LG, now):  # noqa: ARG001
    """Watchdog: due feeds of people with the module on (a few per tick, the oldest first), the clean-up of old articles
    and of deleted feeds."""
    t0, done = time.monotonic(), 0
    nu = now_utc()
    on = [u for u in users if "feeds" in (S[u].get("features") or "").split(",")]
    rows = []
    if on:  # only due feeds of people with the module on (a feed nobody reads never holds up the others)
        rows = c.execute(f"""SELECT * FROM rss_feeds WHERE deleted_at IS NULL AND user_id IN ({",".join("?" * len(on))}) AND
                             (last_fetch IS NULL OR (fails<? AND last_fetch<?) OR last_fetch<?) ORDER BY COALESCE(last_fetch, '') LIMIT 20""",
                         (*on, RSS_SLOW_AFTER, iso(nu - timedelta(seconds=RSS_EVERY)), iso(nu - timedelta(seconds=RSS_SLOW)))).fetchall()
    for f in rows:
        if done >= RSS_TICK_FEEDS or time.monotonic() - t0 > RSS_TICK_S:
            break
        if not rss_due(f, nu):
            continue
        rss_fetch(c, f)
        c.commit()
        done += 1
    c.execute("DELETE FROM rss_items WHERE published<?", (iso(nu - timedelta(days=RSS_KEEP_DAYS)),))
    c.execute("DELETE FROM rss_feeds WHERE deleted_at IS NOT NULL AND deleted_at<?", (iso(nu - timedelta(days=RSS_TRASH_DAYS)),))
    c.commit()
