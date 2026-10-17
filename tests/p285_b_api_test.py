#!/usr/bin/env python3
"""2.85.0 API tests (part B): feeds (#1162), own container (start.sh) with a fake feed server inside (fake_feeds.py).
The module "feeds" is off by default (409); following a feed fetches it once (RSS 2.0, Atom, RSS 1.0 / RDF), titles and
summaries as plain text (no <script>, no tags), links only http(s); articles older than 30 days are not taken; ETag on
the next fetch; the SSRF guard (localhost, 127.0.0.1 on a port not allowed, 10.x, 169.254.169.254, [::1], a redirect to a
private address or to javascript:), a DTD / entity is refused, a feed above 2 MB too; "Read later" makes exactly one task in
the reading list; read / unread / all read (+ undo by ids); delete + restore; another person's feeds and articles are 404;
API tokens / agents never reach the routes (no v1 route); OPML import (nested, duplicates, a DTD refused, the limit of
100) and export; the data export lists the feeds."""
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import requests

import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
FAILS, OKS = [], [0]
FS = "http://127.0.0.1:8098"


def check(c, what):
    if c:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def dbx(q, a=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(q, a).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def sess(u=None):
    s = requests.Session()
    s.headers.update(H)
    if u:
        assert s.post(B + "/api/auth/login", json={"username": u, "password": "password123"}).ok, u
    return s


def put(name, text):
    os.makedirs(os.path.join(DATA, "feeds"), exist_ok=True)
    with open(os.path.join(DATA, "feeds", name), "w", encoding="utf-8") as f:
        f.write(text)


def flog():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "feeds.log"), encoding="utf-8")]
    except OSError:
        return []


NOW = datetime.now(timezone.utc)
R822 = lambda d: format_datetime(NOW - timedelta(days=d))  # noqa: E731
ISO = lambda d: (NOW - timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731

env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1:8098")
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
shutil.copy(os.path.join(N, "fake_feeds.py"), DATA)
put("rss.xml", f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
<title>Example News</title><link>https://example.com/</link>
<item><title>First &amp; best</title><link>https://example.com/a1</link><guid>a1</guid><pubDate>{R822(1)}</pubDate>
<description>&lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt;&lt;script&gt;alert(1)&lt;/script&gt;&lt;/p&gt;</description></item>
<item><title>&lt;script&gt;alert('t')&lt;/script&gt;Second</title><link>javascript:alert(2)</link><guid>a2</guid><pubDate>{R822(2)}</pubDate>
<description><![CDATA[<img src="https://tracker.example/x.gif" onerror="alert(3)">Text <a href="javascript:x()">link</a>]]></description></item>
<item><title>Relative</title><link>/rel</link><guid>a3</guid><pubDate>{R822(3)}</pubDate></item>
<item><title>Too old</title><link>https://example.com/old</link><guid>old</guid><pubDate>{R822(40)}</pubDate></item>
</channel></rss>""")
put("atom.xml", f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title type="html">Atom &lt;i&gt;Blog&lt;/i&gt;</title>
<link href="https://atom.example/" rel="alternate"/><link href="https://atom.example/feed" rel="self"/>
<entry><title>Atom one</title><id>urn:uuid:1</id><updated>{ISO(1)}</updated><link href="https://atom.example/1"/>
<summary type="html">&lt;p&gt;Atom summary&lt;/p&gt;</summary></entry>
<entry><title>Atom two</title><id>urn:uuid:2</id><published>{ISO(0)}</published><link rel="alternate" href="https://atom.example/2"/>
<content type="html">{"x" * 900}</content></entry>
</feed>""")
put("rdf.xml", f"""<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel rdf:about="https://rdf.example/"><title>RDF Feed</title><link>https://rdf.example/</link></channel>
<item rdf:about="https://rdf.example/1"><title>RDF one</title><link>https://rdf.example/1</link><dc:date>{ISO(1)}</dc:date>
<description>Plain</description></item></rdf:RDF>""")
put("dtd.xml", """<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]>
<rss version="2.0"><channel><title>&b;</title></channel></rss>""")
put("xxe.xml", """<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY x SYSTEM "file:///etc/passwd">]>
<rss version="2.0"><channel><title>&x;</title></channel></rss>""")
put("page.html", "<html><body>no feed</body></html>")
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_feeds.py"])
time.sleep(1)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": "cal"})
A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123", "email": "bob@example.com"})
BO = sess("bob")
BO.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": "cal,feeds"})

# ================================================================== off by default
check("feeds" not in A.get(B + "/api/state").json()["settings"]["features"].split(","), "the module is off by default")
r = A.get(B + "/api/feeds")
check(r.status_code == 409 and "turned off" in r.json().get("error", ""), f"GET /api/feeds while off: 409 ({r.status_code})")
check(A.post(B + "/api/feeds", json={"url": FS + "/rss.xml"}).status_code == 409, "POST /api/feeds while off: 409")
A.patch(B + "/api/settings", json={"features": "cal,feeds"})
check(A.get(B + "/api/feeds").json() == {"feeds": [], "unread": 0, "max": 100}, "on: no feeds yet")

# ================================================================== follow: RSS 2.0
r = A.post(B + "/api/feeds", json={"url": FS + "/rss.xml"})
check(r.status_code == 201 and r.json()["feed"]["title"] == "Example News" and r.json()["new"] == 3, "follow RSS: fetched at once, 3 new (not the old one) " + r.text[:300])
F1 = r.json()["feed"]["id"]
check(r.json()["feed"]["site_url"] == "https://example.com/", "the site link")
check(A.post(B + "/api/feeds", json={"url": FS + "/rss.xml"}).status_code == 400, "the same feed twice: 400")
it = A.get(B + "/api/feeds/items").json()
items = {x["title"]: x for x in it["items"]}
check(it["unread"] == 3 and len(it["items"]) == 3, "3 unread articles " + json.dumps(it)[:300])
check(items.get("First & best", {}).get("summary") == "Hello world", "the summary as plain text (tags and the script dropped) " + json.dumps(items.get("First & best"))[:200])
sec = [x for x in it["items"] if x["title"].endswith("Second")]
check(sec and "<" not in sec[0]["title"] and "alert" not in sec[0]["title"], "a title with a script: plain text " + json.dumps(sec)[:200])
check(sec and sec[0]["url"] == "", "a javascript: link is dropped")
check(sec and "<" not in sec[0]["summary"] and "onerror" not in sec[0]["summary"] and "tracker" not in sec[0]["summary"], "no tags / pictures in a summary " + json.dumps(sec)[:200])
check(items.get("Relative", {}).get("url") == "https://example.com/rel", "a relative link against the site")
check([x["title"] for x in it["items"]][0] == "First & best", "newest first")
check(not dbx("SELECT 1 FROM rss_items WHERE guid='old'"), "an article older than 30 days is not taken")

# ================================================================== Atom + RDF
r = A.post(B + "/api/feeds", json={"url": FS + "/atom.xml"})
check(r.ok and r.json()["feed"]["title"] == "Atom Blog" and r.json()["new"] == 2, "Atom: title as text, 2 articles " + r.text[:300])
F2 = r.json()["feed"]["id"]
r = A.post(B + "/api/feeds", json={"url": FS + "/rdf.xml"})
check(r.ok and r.json()["feed"]["title"] == "RDF Feed" and r.json()["new"] == 1, "RSS 1.0 / RDF: 1 article " + r.text[:300])
F3 = r.json()["feed"]["id"]
at = A.get(B + f"/api/feeds/items?feed={F2}").json()["items"]
check([x["title"] for x in at] == ["Atom two", "Atom one"] and at[1]["url"] == "https://atom.example/1", "Atom: links + newest first")
check(len(at[0]["summary"]) <= 500, "a summary is cut to 500 characters")
check(A.get(B + "/api/feeds").json()["unread"] == 6, "6 unread in all")

# ================================================================== ETag on the next fetch
dbx("UPDATE rss_feeds SET last_fetch=NULL WHERE id=?", (F1,))
n0 = len(flog())
time.sleep(1)
t0 = time.time()
while time.time() - t0 < 90 and not any(x["p"] == "/rss.xml" and x["inm"] for x in flog()[n0:]):
    time.sleep(1)
check(any(x["p"] == "/rss.xml" and x["inm"] for x in flog()[n0:]), "the background fetch sends the ETag (If-None-Match)")

# ================================================================== the SSRF guard and bad feeds
for url in ("http://localhost:8098/rss.xml", "http://127.0.0.1:8099/rss.xml", "http://10.1.2.3/feed", "http://169.254.169.254/latest/meta-data/",
            "http://[::1]:8098/rss.xml", FS + "/redir-private", FS + "/redir-meta", FS + "/redir-js"):
    r = A.post(B + "/api/feeds", json={"url": url})
    check(r.status_code == 400, f"refused: {url} ({r.status_code} {r.text[:120]})")
check(not dbx("SELECT 1 FROM rss_feeds WHERE url LIKE '%8099%' OR url LIKE '%169.254%' OR url LIKE '%redir%'"), "a refused feed is not stored")
for url in ("javascript:alert(1)", "file:///etc/passwd", "ftp://example.com/feed", "", "http://user:pw@example.com/feed"):
    r = A.post(B + "/api/feeds", json={"url": url})
    check(r.status_code == 400 and "address" in r.json().get("error", ""), f"not an http(s) address: {url!r} ({r.status_code})")
r = A.post(B + "/api/feeds", json={"url": FS + "/dtd.xml"})
check(r.status_code == 400 and "DTD" in r.json().get("error", ""), "a DTD with entities (billion laughs): refused " + r.text[:200])
r = A.post(B + "/api/feeds", json={"url": FS + "/xxe.xml"})
check(r.status_code == 400 and "DTD" in r.json().get("error", ""), "an external entity (XXE): refused " + r.text[:200])
r = A.post(B + "/api/feeds", json={"url": FS + "/big.xml"})
check(r.status_code == 400 and "2 MB" in r.json().get("error", ""), "a feed above 2 MB: refused " + r.text[:200])
r = A.post(B + "/api/feeds", json={"url": FS + "/page.html"})
check(r.status_code == 400 and "feed" in r.json().get("error", "").lower(), "an HTML page: not a feed " + r.text[:200])
r = A.post(B + "/api/feeds", json={"url": FS + "/missing.xml"})
check(r.status_code == 400, "404: refused")

# ================================================================== read later: exactly one task
first = items["First & best"]
r = A.post(B + f"/api/feeds/items/{first['id']}/later")
check(r.status_code == 201 and r.json()["created"], "read later: a task " + r.text[:200])
TID, LID = r.json()["task_id"], r.json()["list_id"]
r2 = A.post(B + f"/api/feeds/items/{first['id']}/later")
check(r2.status_code == 200 and not r2.json()["created"] and r2.json()["task_id"] == TID, "a second press: no second task")
check(dbx("SELECT COUNT(*) FROM tasks WHERE url='https://example.com/a1' AND deleted_at IS NULL")[0][0] == 1, "exactly one task with the link")
check(dbx("SELECT life FROM lists WHERE id=?", (LID,))[0][0] == "reading", "in the reading list")
check(dbx("SELECT title FROM tasks WHERE id=?", (TID,))[0][0] == "First & best", "the title of the article")
x = [i for i in A.get(B + "/api/feeds/items").json()["items"] if i["id"] == first["id"]][0]
check(x["read"] and x["task_id"] == TID, "the article: read, with its task")
A.delete(B + f"/api/tasks/{TID}")
r = A.post(B + f"/api/feeds/items/{first['id']}/later")
check(r.json().get("created") and r.json()["task_id"] != TID, "after the task was deleted: a new one")

# ================================================================== read / unread / all
r = A.post(B + "/api/feeds/read", json={"ids": [first["id"]], "read": False})
check(r.json()["ids"] == [first["id"]], "unread again")
r = A.post(B + "/api/feeds/read", json={"feed_id": F1, "read": True})
ids = r.json()["ids"]
check(len(ids) == 3 and A.get(B + f"/api/feeds/items?feed={F1}&unread=1").json()["items"] == [], "all of one feed read")
check(A.get(B + "/api/feeds").json()["unread"] == 3, "the others stay unread")
r = A.post(B + "/api/feeds/read", json={"ids": ids, "read": False})
check(sorted(r.json()["ids"]) == sorted(ids), "undo: unread by ids")
check(A.post(B + "/api/feeds/read", json={"read": "yes"}).status_code == 400, "read must be a boolean")
check(A.post(B + "/api/feeds/read", json={"ids": "x"}).status_code == 400, "ids must be a list")

# ================================================================== another person, agents, tokens
check(BO.get(B + "/api/feeds").json()["feeds"] == [], "bob sees no feed of alice")
check(BO.get(B + "/api/feeds/items").json()["items"] == [], "… no article")
check(BO.get(B + f"/api/feeds/items?feed={F1}").status_code == 404, "alice's feed as a filter: 404")
check(BO.post(B + f"/api/feeds/items/{first['id']}/later").status_code == 404, "read later on alice's article: 404")
check(BO.delete(B + f"/api/feeds/{F1}").status_code == 404, "deleting alice's feed: 404")
check(BO.post(B + f"/api/feeds/{F1}/restore").status_code == 404, "restoring alice's feed: 404")
check(BO.post(B + "/api/feeds/read", json={"ids": [first["id"]], "read": True}).json()["ids"] == [], "marking alice's article: nothing changes")
check(BO.post(B + "/api/feeds/read", json={"feed_id": F1, "read": True}).status_code == 404, "all read of alice's feed: 404")
r = BO.post(B + "/api/feeds", json={"url": FS + "/rss.xml"})
check(r.status_code == 201, "bob follows the same address: his own feed")
check(len(A.get(B + "/api/feeds").json()["feeds"]) == 3, "alice still has her three")
r = A.post(B + "/api/admin/agents", json={"scopes": ["write"], "username": "claude", "display_name": "Claude"})
AGH = {"Authorization": "Bearer " + r.json()["token"]}
check(requests.get(B + "/api/feeds", headers=AGH).status_code in (401, 403), "an agent token on /api/feeds: refused")
check(requests.get(B + "/api/v1/feeds", headers=AGH).status_code == 404, "no v1 route for feeds")
tk = A.post(B + "/api/me/tokens", json={"name": "t1", "scopes": ["read", "private"]}).json()["token"]
check(requests.get(B + "/api/feeds", headers={"Authorization": "Bearer " + tk}).status_code in (401, 403), "a person's API token: refused")

# ================================================================== delete + restore
check(A.delete(B + f"/api/feeds/{F3}").ok, "unfollow")
check(F3 not in [f["id"] for f in A.get(B + "/api/feeds").json()["feeds"]], "gone from the list")
check(not any(i["feed_id"] == F3 for i in A.get(B + "/api/feeds/items").json()["items"]), "its articles hidden")
check(A.post(B + f"/api/feeds/{F3}/restore").ok and F3 in [f["id"] for f in A.get(B + "/api/feeds").json()["feeds"]], "undo: back")
check(any(i["feed_id"] == F3 for i in A.get(B + "/api/feeds/items").json()["items"]), "with its articles")

# ================================================================== OPML
r = A.get(B + "/api/feeds/opml")
check(r.ok and "attachment" in r.headers.get("Content-Disposition", "") and r.text.count("<outline") == 3 and FS + "/atom.xml" in r.text, "OPML export: 3 feeds " + r.text[:300])
check('htmlUrl="https://example.com/"' in r.text, "… with the site links")
opml = """<?xml version="1.0"?><opml version="2.0"><head><title>x</title></head><body>
<outline text="Tech"><outline type="rss" text="Nested &amp; new" xmlUrl="https://feeds.example.org/a.xml"/>
<outline type="rss" text="Again" xmlUrl="%s/rss.xml"/></outline>
<outline type="rss" text="Bad" xmlUrl="javascript:alert(1)"/><outline type="rss" text="Feed scheme" xmlUrl="feed://feeds.example.org/b.xml"/>
</body></opml>""" % FS
r = A.post(B + "/api/feeds/opml", files={"file": ("x.opml", opml.encode(), "text/xml")})
check(r.ok and r.json()["added"] == 2 and r.json()["skipped"] == 1 and r.json()["errors"] == 1, "OPML import: nested + feed://, a duplicate skipped, a bad one counted " + r.text[:200])
fl = {f["url"]: f for f in A.get(B + "/api/feeds").json()["feeds"]}
check("https://feeds.example.org/a.xml" in fl and fl["https://feeds.example.org/a.xml"]["title"] == "Nested & new" and "https://feeds.example.org/b.xml" in fl, "the imported feeds with their names")
check(fl["https://feeds.example.org/a.xml"]["last_fetch"] is None, "fetched later in the background")
r = A.post(B + "/api/feeds/opml", files={"file": ("x.opml", b'<?xml version="1.0"?><!DOCTYPE opml [<!ENTITY a "x">]><opml><body/></opml>', "text/xml")})
check(r.status_code == 400 and "DTD" in r.json().get("error", ""), "OPML with a DTD: refused")
check(A.post(B + "/api/feeds/opml", files={"file": ("x.opml", b"<html/>", "text/xml")}).status_code == 400, "not an OPML file: 400")
check(A.post(B + "/api/feeds/opml").status_code == 400, "no file: 400")
# the limit of 100
have = len(A.get(B + "/api/feeds").json()["feeds"])
many = "".join(f'<outline type="rss" text="n{i}" xmlUrl="https://many.example.org/{i}.xml"/>' for i in range(105))
r = A.post(B + "/api/feeds/opml", files={"file": ("m.opml", f'<?xml version="1.0"?><opml version="2.0"><body>{many}</body></opml>'.encode(), "text/xml")})
check(r.ok and r.json()["added"] == 100 - have and r.json()["errors"] == 105 - (100 - have), "OPML: at most 100 feeds in all " + r.text[:200])
check(len(A.get(B + "/api/feeds").json()["feeds"]) == 100, "100 feeds")
r = A.post(B + "/api/feeds", json={"url": FS + "/rdf.xml?x=1"})
check(r.status_code == 400 and "100" in r.json().get("error", ""), "the 101st feed: refused " + r.text[:200])

# ================================================================== the data export
r = A.get(B + "/api/export.json")
check(r.ok and len(r.json().get("feeds", [])) == 100 and "etag" not in r.json()["feeds"][0], "the data export lists the feeds " + r.text[:100])

# ================================================================== the module off again: refused, data stays
A.patch(B + "/api/settings", json={"features": "cal"})
check(A.get(B + "/api/feeds/items").status_code == 409, "off: the articles refused")
A.patch(B + "/api/settings", json={"features": "cal,feeds"})
check(len(A.get(B + "/api/feeds").json()["feeds"]) == 100, "on again: the feeds are still there")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
