#!/usr/bin/env python3
"""2.172.0 API tests (part B): Reading per space (#2677 #2679), own container (start.sh) with the fake feed server inside.
Feeds and read later live in a space: private (only the person) or an organisation (every member reads; its admins
manage the feed sources). Guarded here:
 - a member sees the organisation's feed, a non-member / guest gets 404 (feeds, articles, delete, read later, the view)
 - a member who is no admin cannot follow / unfollow / import a source of the organisation (403); read-only reads, marks
   read, but saves nothing (403)
 - private feeds never appear in the organisation's view and the other way round; the same address privately and for the
   organisation is two feeds; the read mark of an organisation's article is per person
 - "Read later" of an organisation's article lands in the organisation's read-later project (open to every member, who may
   tick it), of a private one in the private project; the view of each space shows only its own entries
 - the background fetch also fetches the feeds of an organisation; agents / API tokens reach none of it
 - a person without an organisation uses everything privately (freelancer-matrix: reading)
tenant-matrix: reading"""
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from freelancer_fixture import freelancer  # noqa: E402

N = os.path.dirname(os.path.abspath(__file__))
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
FAILS, OKS = [], [0]
FS = "http://127.0.0.1:8098"
FEATS = "comments,collab,feeds,reading"


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


def sess(u):
    s = requests.Session()
    s.headers.update(H)
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


def feed(title, slug, n=2):
    items = "".join(f"<item><title>{title} {i}</title><link>https://example.com/{slug}/{i}</link><guid>{slug}-{i}</guid>"
                    f"<pubDate>{R822(i)}</pubDate><description>About {slug} {i}</description></item>" for i in range(1, n + 1))
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>{title}</title><link>https://example.com/{slug}</link>{items}</channel></rss>'


env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1:8098")
r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
shutil.copy(os.path.join(N, "fake_feeds.py"), DATA)
put("team.xml", feed("Team Blog", "team"))
put("mine.xml", feed("My Blog", "mine"))
put("opml1.xml", feed("Imported", "imp"))
put("frida.xml", feed("Frida Blog", "frida"))
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_feeds.py"])
time.sleep(1)

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A = sess("alice")
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
SP = f"org:{ORG}"
uid = {}
for u, orgs in (("bob", [{"id": ORG, "role": "member"}]), ("rita", [{"id": ORG, "role": "readonly"}]),
                ("gina", [{"id": ORG, "role": "guest"}]), ("frank", [])):
    r = A.post(B + "/api/users", json={"orgs": orgs, "username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["frank"]})
assert r.status_code in (200, 201), r.text
Bo, Ri, Gi, Fr = sess("bob"), sess("rita"), sess("gina"), sess("frank")
for s in (A, Bo, Ri, Gi, Fr):
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATS}).ok


def feeds(s, sp=None):
    return s.get(B + "/api/feeds" + (f"?space={sp}" if sp else ""))


def items(s, sp=None, **kw):
    q = "&".join(([f"space={sp}"] if sp else []) + [f"{k}={v}" for k, v in kw.items()])
    return s.get(B + "/api/feeds/items" + (f"?{q}" if q else ""))


def reading(s, sp=None, done=False):
    return s.get(B + "/api/reading?" + "&".join(([f"space={sp}"] if sp else []) + (["done=1"] if done else [])))


# ================================================================ an organisation's feed: admins follow, members read
r = A.post(B + "/api/feeds", json={"url": FS + "/team.xml", "space": SP})
check(r.status_code == 201 and r.json()["feed"]["space"] == SP and r.json()["new"] == 2, "admin follows a feed for the organisation " + r.text[:200])
OF = r.json()["feed"]["id"]
check(dbx("SELECT org_id FROM rss_feeds WHERE id=?", (OF,))[0][0] == ORG, "stored with the organisation")
r = Bo.post(B + "/api/feeds", json={"url": FS + "/mine.xml", "space": SP})
check(r.status_code == 403, f"a member who is no admin cannot follow for the organisation ({r.status_code})")
r = Ri.post(B + "/api/feeds", json={"url": FS + "/mine.xml", "space": SP})
check(r.status_code == 403, f"read-only cannot follow for the organisation ({r.status_code})")
j = feeds(Bo, SP).json()
check([f["id"] for f in j["feeds"]] == [OF] and j["unread"] == 2 and j["manage"] is False and j["space"] == SP, "member sees the organisation's feed " + json.dumps(j)[:200])
check(feeds(A, SP).json()["manage"] is True, "admin may manage")
check(feeds(Ri, SP).ok and len(items(Ri, SP).json()["items"]) == 2, "read-only reads the feed and its articles")
for who, s in (("non-member", Fr), ("guest", Gi)):
    check(feeds(s, SP).status_code == 404, f"{who}: the organisation's feeds 404")
    check(items(s, SP).status_code == 404, f"{who}: its articles 404")
    check(s.get(B + f"/api/feeds/items?feed={OF}").status_code == 404, f"{who}: the feed's articles via the private view 404")
    check(s.delete(B + f"/api/feeds/{OF}").status_code == 404, f"{who}: unfollow 404")
    check(s.get(B + f"/api/feeds/opml?space={SP}").status_code == 404, f"{who}: OPML export 404")
check(Bo.delete(B + f"/api/feeds/{OF}").status_code == 403, "member: unfollow the organisation's feed 403")
OI = [x["id"] for x in items(Bo, SP).json()["items"]]

# ================================================================ private and organisation never mix
r = A.post(B + "/api/feeds", json={"url": FS + "/team.xml"})
check(r.status_code == 201 and r.json()["feed"]["space"] == "private", "the same address privately: a second feed " + r.text[:200])
PF = r.json()["feed"]["id"]
r = A.post(B + "/api/feeds", json={"url": FS + "/mine.xml", "space": "private"})
check(r.status_code == 201, "a private feed")
PF2 = r.json()["feed"]["id"]
check(A.post(B + "/api/feeds", json={"url": FS + "/team.xml", "space": SP}).status_code == 400, "the same address twice in the organisation: 400")
check(sorted(f["id"] for f in feeds(A).json()["feeds"]) == sorted([PF, PF2]), "private view: only the private feeds")
check([f["id"] for f in feeds(A, SP).json()["feeds"]] == [OF], "organisation view: only its feed")
pit = items(A).json()["items"]
check(len(pit) == 4 and all(x["feed_id"] in (PF, PF2) for x in pit), "private articles: none of the organisation's")
check(all(x["feed_id"] == OF for x in items(A, SP).json()["items"]), "organisation articles: none of the private ones")
check(A.get(B + f"/api/feeds/items?space={SP}&feed={PF}").status_code == 404, "a private feed in the organisation's view: 404")
check(A.get(B + f"/api/feeds/items?feed={OF}").status_code == 404, "the organisation's feed in the private view: 404")
check(not any(f["id"] == PF for f in feeds(Bo, SP).json()["feeds"]), "the admin's private feed is not in the organisation")
check(Bo.get(B + f"/api/feeds/items?feed={PF}").status_code == 404, "another person's private feed: 404")
# the read mark is per person
r = Bo.post(B + "/api/feeds/read", json={"ids": [OI[0]], "read": True, "space": SP})
check(r.ok and r.json()["ids"] == [OI[0]], "member marks an article of the organisation read " + r.text[:200])
check(feeds(Bo, SP).json()["unread"] == 1 and feeds(A, SP).json()["unread"] == 2, "the read mark is per person")
r = Ri.post(B + "/api/feeds/read", json={"read": True, "space": SP})
check(r.ok and sorted(r.json()["ids"]) == sorted(OI) and feeds(Ri, SP).json()["unread"] == 0, "read-only: all read (own mark)")
check(Bo.post(B + "/api/feeds/read", json={"ids": [OI[0]], "read": False, "space": SP}).json()["ids"] == [OI[0]], "unread again")
r = A.post(B + "/api/feeds/read", json={"ids": OI, "read": True})
check(r.ok and r.json()["ids"] == [], "the organisation's articles cannot be marked in the private space")
check(Fr.post(B + "/api/feeds/read", json={"ids": OI, "read": True}).json().get("ids") == [], "non-member: marks nothing")
check(Fr.post(B + "/api/feeds/read", json={"ids": OI, "read": True, "space": SP}).status_code == 404, "non-member in the space: 404")
check(not dbx("SELECT 1 FROM rss_items WHERE feed_id=? AND read_at IS NOT NULL", (OF,)), "the shared article row keeps no read mark")

# ================================================================ read later lands in the article's space
r = Bo.post(B + f"/api/feeds/items/{OI[0]}/later")
check(r.status_code == 201 and r.json()["created"] and r.json()["space"] == SP, "member: read later from the organisation's feed " + r.text[:200])
OT, OL = r.json()["task_id"], r.json()["list_id"]
row = dbx("SELECT org_id, org_visibility, org_edit, COALESCE(life, '') FROM lists WHERE id=?", (OL,))[0]
check(row[0] == ORG and row[1] == "org" and row[2] == 1 and row[3] == "", f"the organisation's read-later project, open to its members {row}")
check(dbx("SELECT list_id FROM reading_orgs WHERE org_id=?", (ORG,))[0][0] == OL, "remembered for the organisation")
check(not dbx("SELECT 1 FROM list_members lm JOIN users u ON u.id=lm.user_id WHERE lm.list_id=? AND u.kind='agent'", (OL,)), "no agent in it")
r2 = A.post(B + f"/api/feeds/items/{OI[0]}/later")
check(r2.status_code == 200 and not r2.json()["created"] and r2.json()["task_id"] == OT, "another member: the same entry, no second one")
check(Ri.post(B + f"/api/feeds/items/{OI[1]}/later").status_code == 403, "read-only: read later 403")
check(Fr.post(B + f"/api/feeds/items/{OI[1]}/later").status_code == 404, "non-member: read later 404")
r = A.post(B + f"/api/feeds/items/{pit[0]['id']}/later")
check(r.status_code == 201 and r.json()["space"] == "private", "read later from a private feed")
PT, PL = r.json()["task_id"], r.json()["list_id"]
check(dbx("SELECT org_id, life FROM lists WHERE id=?", (PL,))[0] == (None, "reading"), "in the private read-later project")

# ================================================================ the view "Read later" per space
v = reading(A, SP).json()
check([x["id"] for x in v["items"]] == [OT] and v["space"] == SP and v["list_id"] == OL, "organisation view: its entry " + json.dumps(v)[:300])
check(v["items"][0]["url"].startswith("https://example.com/team/") and v["items"][0]["site"] == "example.com", "with link and site")
v = reading(A).json()
check([x["id"] for x in v["items"]] == [PT] and v["list_id"] == PL, "private view: only the private entry " + json.dumps(v)[:300])
check(OT not in [x["id"] for x in reading(Bo).json()["items"]], "the organisation's entry is not in a member's private view")
check([x["id"] for x in reading(Ri, SP).json()["items"]] == [OT] and not reading(Ri, SP).json()["items"][0]["can_edit"], "read-only sees it, cannot change it")
for who, s in (("non-member", Fr), ("guest", Gi)):
    check(reading(s, SP).status_code == 404, f"{who}: the organisation's read later 404")
    check(s.post(B + "/api/reading", json={"url": "https://example.com/x", "space": SP}).status_code == 404, f"{who}: save there 404")
    check(s.post(B + f"/api/tasks/{OT}/complete").status_code in (403, 404), f"{who}: tick its entry refused")
check(Fr.post(B + f"/api/tasks/{PT}/complete").status_code in (403, 404), "another person's private entry: refused")
r = Bo.post(B + "/api/reading", json={"url": "example.org/article", "title": "Shared from the phone", "space": SP})
check(r.status_code == 201 and r.json()["list_id"] == OL, "member saves a link for the organisation (share sheet) " + r.text[:200])
ST = r.json()["task_id"]
r = Bo.post(B + "/api/reading", json={"url": "https://example.org/article", "space": SP})
check(r.status_code == 200 and not r.json()["created"] and r.json()["task_id"] == ST, "the same open link: no second entry")
check(Ri.post(B + "/api/reading", json={"url": "https://example.org/b", "space": SP}).status_code == 403, "read-only: save 403")
check(Bo.post(B + "/api/reading", json={"url": "javascript:alert(1)", "space": SP}).status_code == 400, "no http(s) link: 400")
check(Bo.post(B + f"/api/tasks/{ST}/complete").ok, "member ticks an entry of the organisation")
v = reading(A, SP).json()
check([x["id"] for x in v["items"]] == [OT] and v["done_count"] == 1, "ticked: out of the open ones")
check([x["id"] for x in reading(A, SP, done=True).json()["items"]] == [ST], "the ticked ones on request")
# the organisation's project closed again by its owner: nobody else adds to it through Read later
OWN = dbx("SELECT owner_id FROM lists WHERE id=?", (OL,))[0][0]
OTHER = A if OWN != 1 else Bo
dbx("UPDATE lists SET org_edit=0 WHERE id=?", (OL,))
check(OTHER.post(B + "/api/reading", json={"url": "https://example.org/closed", "space": SP}).status_code == 403, "a closed project: saving 403")
check(OTHER.post(B + f"/api/feeds/items/{OI[1]}/later").status_code == 403, "a closed project: read later 403")
dbx("UPDATE lists SET org_edit=1 WHERE id=?", (OL,))
# 2.172.0 review (#2677): the project no longer open to the organisation (or locked): a new one is made, never a dead end
dbx("UPDATE lists SET org_visibility='' WHERE id=?", (OL,))
r = OTHER.post(B + "/api/reading", json={"url": "https://example.org/reopened", "space": SP})
check(r.status_code == 201 and r.json()["list_id"] != OL, "the project closed for the organisation: a new read-later project " + r.text[:200])
NL = r.json()["list_id"]
check(dbx("SELECT list_id FROM reading_orgs WHERE org_id=?", (ORG,))[0][0] == NL, "the new one is remembered")
check(dbx("SELECT org_visibility FROM lists WHERE id=?", (NL,))[0][0] == "org", "and open to the organisation")
dbx("UPDATE reading_orgs SET list_id=? WHERE org_id=?", (OL, ORG))
dbx("UPDATE lists SET org_visibility='org' WHERE id=?", (OL,))
r = A.post(B + "/api/reading", json={"url": "https://example.net/p"})
check(r.status_code == 201 and r.json()["space"] == "private" and r.json()["list_id"] == PL, "without a space: private (as before)")

# ================================================================ sources of the organisation: unfollow, OPML
check(A.delete(B + f"/api/feeds/{OF}").ok and A.post(B + f"/api/feeds/{OF}/restore").ok, "admin unfollows + restores")
opml = f'<?xml version="1.0"?><opml version="2.0"><body><outline type="rss" text="Imp" xmlUrl="{FS}/opml1.xml"/></body></opml>'
r = Bo.post(B + "/api/feeds/opml", files={"file": ("f.opml", opml)}, data={"space": SP})
check(r.status_code == 403, f"member: OPML import into the organisation 403 ({r.status_code})")
r = A.post(B + "/api/feeds/opml", files={"file": ("f.opml", opml)}, data={"space": SP})
check(r.ok and r.json()["added"] == 1, "admin: OPML import into the organisation " + r.text[:200])
IF = dbx("SELECT id, org_id FROM rss_feeds WHERE url=?", (FS + "/opml1.xml",))
check(len(IF) == 1 and IF[0][1] == ORG, "imported into the organisation")
x = Bo.get(B + f"/api/feeds/opml?space={SP}").text
check("team.xml" in x and "opml1.xml" in x and "mine.xml" not in x, "OPML export of the organisation: only its feeds")
check("opml1.xml" not in A.get(B + "/api/feeds/opml").text, "OPML export private: none of the organisation's")
# the background fetches the organisation's feeds too (here one added by a person who reads no feeds herself)
Gi.patch(B + "/api/settings", json={"features": "comments"})
dbx("UPDATE rss_feeds SET user_id=?, last_fetch=NULL WHERE id=?", (uid["gina"], IF[0][0]))
n0 = len(flog())
t0 = time.time()
while time.time() - t0 < 90 and not any(e["p"] == "/opml1.xml" for e in flog()[n0:]):
    time.sleep(1)
check(any(e["p"] == "/opml1.xml" for e in flog()[n0:]), "the background fetches a feed of the organisation")

# ================================================================ 2.172.0 review (#2677): the adder's account deleted, the feed stays
r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "admin"}], "username": "dora", "display_name": "Dora", "password": "password123"})
DID = r.json()["id"]
Do = sess("dora")
Do.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": FEATS})
put("dora.xml", feed("Dora", "dora"))
r = Do.post(B + "/api/feeds", json={"url": FS + "/dora.xml", "space": SP})
check(r.status_code == 201, "a second admin follows a feed for the organisation " + r.text[:200])
DF = r.json()["feed"]["id"]
check(A.delete(B + f"/api/users/{DID}").ok, "the second admin's account deleted")
row = dbx("SELECT user_id, org_id FROM rss_feeds WHERE id=?", (DF,))
check(row and row[0][1] == ORG and row[0][0] != DID, f"the organisation's feed stays with the organisation {row}")
check(DF in [f["id"] for f in feeds(Bo, SP).json()["feeds"]] and dbx("SELECT COUNT(*) FROM rss_items WHERE feed_id=?", (DF,))[0][0] == 2,
      "members still read it with its articles")

# ================================================================ agents and API tokens: nothing
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "helper", "display_name": "Helper"})
AGH = {"Authorization": "Bearer " + r.json()["token"], **H}
r = A.post(B + "/api/me/tokens", json={"name": "t1", "scopes": ["read", "write", "private"]})
PTH = {"Authorization": "Bearer " + r.json()["token"], **H}
for who, hd in (("agent", AGH), ("API token", PTH)):
    check(requests.get(B + f"/api/feeds?space={SP}", headers=hd).status_code in (401, 403), f"{who}: no organisation feeds")
    check(requests.get(B + f"/api/feeds/items?space={SP}", headers=hd).status_code in (401, 403), f"{who}: no organisation articles")
    check(requests.get(B + f"/api/reading?space={SP}", headers=hd).status_code in (401, 403), f"{who}: no organisation read later")
    check(requests.get(B + "/api/reading", headers=hd).status_code in (401, 403), f"{who}: no private read later")
    check(requests.post(B + "/api/reading", headers=hd, json={"url": "https://example.com/z", "space": SP}).status_code in (401, 403), f"{who}: no saving")

# ================================================================ a person without an organisation (freelancer-matrix: reading)
FID, Fl = freelancer(B, A)
r = Fl.post(B + "/api/feeds", json={"url": FS + "/frida.xml", "space": "private"})
check(r.status_code == 201 and r.json()["feed"]["space"] == "private", "freelancer: follows privately " + r.text[:200])
j = feeds(Fl, "private").json()
check(len(j["feeds"]) == 1 and j["manage"] is True and j["unread"] == 2, "freelancer: the own feeds, manages them")
fi = items(Fl, "private").json()["items"]
r = Fl.post(B + f"/api/feeds/items/{fi[0]['id']}/later")
check(r.status_code == 201 and r.json()["space"] == "private", "freelancer: read later")
check([x["id"] for x in reading(Fl, "private").json()["items"]] == [r.json()["task_id"]], "freelancer: the read-later view")
r = Fl.post(B + "/api/reading", json={"url": "https://example.com/f", "title": "Later", "space": "private"})
check(r.status_code == 201, "freelancer: save a link")
check(Fl.post(B + f"/api/tasks/{r.json()['task_id']}/complete").ok, "freelancer: tick it")
check(feeds(Fl, SP).status_code == 404 and reading(Fl, SP).status_code == 404, "freelancer: no organisation space (404)")
check(Fl.post(B + "/api/reading", json={"url": "https://example.com/g", "space": SP}).status_code == 404, "freelancer: cannot save into an organisation")

# ================================================================ before 2.172: every feed stays private
check(not dbx("SELECT 1 FROM rss_feeds WHERE org_id IS NULL AND id IN (?, ?) AND user_id<>?", (PF, PF2, 1)), "private feeds keep their owner")
check(dbx("SELECT COUNT(*) FROM pg_indexes WHERE indexname IN ('rss_feeds_live_p', 'rss_feeds_live_o')")[0][0] == 2
      and not dbx("SELECT 1 FROM pg_indexes WHERE indexname='rss_feeds_live'"), "one feed per address and space (unique indexes)")

print(f"p2172_b_reading_scope: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
