#!/usr/bin/env python3
"""2.97.0 API tests, part A (#1950): bookmarks, own container (start.sh) with the small page server of the feed tests inside
(fake_feeds.py: serves /data/feeds/<name>, port 8098, the only internal address the server may fetch). Invented names only.
 - the module "reading" is needed (409 without); people only: an agent token and a personal API token are refused (403)
 - saving a link: 201, the preview follows in the background (title, description, site from OpenGraph, the picture as a
   sealed copy served by the app, the plain reading text without scripts / navigation); the same link again (other spelling)
   comes back as "already saved"; a picture as SVG or above 1 MB is not taken; a page that is no HTML: preview failed
 - fetches refused: localhost, 10.x, 169.254.169.254, [::1], a redirect to an address that is not allowed -> the bookmark is
   saved, preview failed, the page server never got the request
 - search over title / description / note / link / reading text / tags, the tag filter, the states, archived hidden by default
 - change, delete + restore (undo), restore of a link saved again meanwhile: 409
 - an organisation's bookmark: every member reads it, only its owner or an admin of the organisation changes it (403);
   another organisation / a person without it: 404 (tenant-matrix: bookmark)
 - moving between the private space and an organisation: dry run, move, the picture still served, the move back; the same
   link already in the target blocks; a plain member may not move someone else's (403), a foreign organisation 409, agents 403
 - a person without an organisation (freelancer-matrix: bookmarks): the private space works, there is no other workspace (409)
 - the parser on its own (inside the app container) and the nightly boundary check with bookmarks
usage: p297_a_api_test.py <datadir>      (a fresh container; P297A_NOSTART=1 = the server already runs)"""
import json
import os
import shutil
import struct
import subprocess
import sys
import time
import zlib

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
FS = "http://127.0.0.1:8098"
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def put(name, data):
    os.makedirs(os.path.join(DATA, "feeds"), exist_ok=True)
    with open(os.path.join(DATA, "feeds", name), "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode())


def flog():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "feeds.log"), encoding="utf-8")]
    except OSError:
        return []


def py_in_app(code):
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c", "import app, json\n" + code],
                       capture_output=True, text=True)
    return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "ERR " + r.stderr[-400:]


def png(w=2, h=2):
    raw = b"".join(b"\x00" + b"\x80\x40\xc0" * w for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)  # noqa: E731
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def add(s, url, **kw):
    return s.post(B + "/api/bookmarks", json={"url": url, **kw})


def settle(s, bid, wait=25):
    """The bookmark once its preview is no longer pending."""
    t0 = time.time()
    while True:
        r = s.get(B + f"/api/bookmarks/{bid}")
        if not r.ok or r.json()["preview"] not in ("pending", "image") or time.time() - t0 > wait:
            return r.json() if r.ok else {}
        time.sleep(0.5)


def lst(s, **q):
    r = s.get(B + "/api/bookmarks", params=q)
    assert r.ok, r.text
    return r.json()


if not os.environ.get("P297A_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_BOOKMARK_ALLOW_HOSTS=127.0.0.1:8098")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
shutil.copy(os.path.join(N, "fake_feeds.py"), DATA)
PIC = png()
put("pic.png", PIC)
put("pic.svg", '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')
put("big.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * (1200 * 1024))
LONG = "The first paragraph of the article talks about gardening in the city, raised beds on balconies and much more for everyone."
put("page.html", f"""<!doctype html><html><head><meta charset="utf-8"><title>Fallback title</title>
<meta property="og:title" content="A long read &amp; more">
<meta property="og:description" content="What the page is about">
<meta property="og:site_name" content="Example Site">
<meta property="og:image" content="/pic.png">
<script>var secret = "do-not-store";</script><style>.x{{color:red}}</style></head>
<body><nav>Menu Home About Contact navigation words</nav><header>Site header text here and there</header>
<main><article><h1>The heading of the article</h1><p>{LONG}</p>
<p>Second paragraph with <b>bold</b> words and <a href="javascript:alert(1)">a link</a> and the rare word zebrafish in it.</p>
<script>document.write("injected text")</script></article></main>
<footer>Footer legal text and imprint lines</footer></body></html>""")
put("svg.html", '<html><head><title>Picture as SVG</title><meta property="og:image" content="/pic.svg"></head><body><p>Some words here for the text.</p></body></html>')
put("big.html", '<html><head><title>Big picture</title><meta name="twitter:image" content="/big.png"></head><body><p>Some words here for the text.</p></body></html>')
put("plain.html", '<html><head><title>Only a &lt;title&gt;</title><meta name="description" content="The description meta"></head><body><p>Text of a plain page.</p></body></html>')
subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_feeds.py"])
time.sleep(1)

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
SP = f"org:{ORG}"
uid = {}
for u in ("bob", "carol", "frank"):
    r = A.post(B + "/api/users", json={"orgs": [ORG] if u != "frank" else [], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["frank"]})
assert r.status_code in (200, 201), r.text
ORG2 = r.json().get("id") or r.json().get("org", {}).get("id")
Bo, Ca, Fr = sess("bob"), sess("carol"), sess("frank")
for s in (A, Bo, Ca, Fr):
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done", "features": "comments,reading"}).ok

# ================================================================ the module, people only
Fr.patch(B + "/api/settings", json={"features": "comments"})
check(add(Fr, "https://example.com/x").status_code == 409 and Fr.get(B + "/api/bookmarks").status_code == 409, "module off: 409")
Fr.patch(B + "/api/settings", json={"features": "comments,reading"})
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "write"], "username": "helper", "display_name": "Helper"})
AGH = {"Authorization": "Bearer " + r.json()["token"], **H}
r = A.post(B + "/api/me/tokens", json={"name": "t1", "scopes": ["read", "write", "private"]})
PTH = {"Authorization": "Bearer " + r.json()["token"], **H}
for who, hd in (("agent", AGH), ("API token", PTH)):
    check(requests.get(B + "/api/bookmarks", headers=hd).status_code in (401, 403), f"{who}: no list")
    check(requests.post(B + "/api/bookmarks", headers=hd, json={"url": "https://example.com/a"}).status_code in (401, 403), f"{who}: no saving")

# ================================================================ saving + the preview
r = add(Bo, FS + "/page.html", tags=["Reading", "#news", "reading"], note="for the weekend")
check(r.status_code == 201 and r.json()["bookmark"]["preview"] == "pending" and r.json()["existed"] is False, "saved: 201, preview pending " + r.text[:200])
P1 = r.json()["bookmark"]["id"]
d = settle(Bo, P1)
check(d.get("preview") == "ok" and d["title"] == "A long read & more" and d["description"] == "What the page is about"
      and d["site"] == "Example Site", "the preview: OpenGraph title, description, site " + json.dumps(d)[:300])
check(d.get("tags") == ["Reading", "news"] and d["note"] == "for the weekend" and d["state"] == "unread" and d["space"] == "private",
      "tags (no #, no double), note, state, space " + str(d.get("tags")))
t = d.get("text", "")
check(LONG in t and "zebrafish" in t and "heading of the article" in t, "the reading text has the article " + t[:200])
check(not any(x in t for x in ("do-not-store", "injected", "Menu Home", "Footer legal", "color:red", "<b>", "javascript")),
      "no script, style, navigation, footer or markup in the reading text")
check(d.get("image", "").startswith(f"/api/bookmarks/{P1}/image"), "a picture " + d.get("image", ""))
r = Bo.get(B + d.get("image", "/x"))
check(r.ok and r.content == PIC and r.headers.get("Content-Type", "").startswith("image/png") and "nosniff" in r.headers.get("X-Content-Type-Options", ""),
      "the picture is served by the app " + str(r.status_code))
raw = [f for f in os.listdir(os.path.join(DATA, "attachments", "bookmarks"))] if os.path.isdir(os.path.join(DATA, "attachments", "bookmarks")) else []
check(len(raw) == 1, "one stored copy of the picture " + str(raw))
check(any(x["p"] == "/pic.png" for x in flog()), "the picture was fetched from the page")

r = add(Bo, "HTTP://127.0.0.1:8098/page.html/?utm_source=x#top")
check(r.status_code == 200 and r.json()["existed"] and r.json()["bookmark"]["id"] == P1, "the same link again: the saved one comes back " + r.text[:200])
check(add(Bo, "javascript:alert(1)").status_code == 400 and add(Bo, "ftp://example.com/x").status_code == 400 and add(Bo, "").status_code == 400,
      "only http(s) links")
check(add(Bo, "https://example.com/y", evil=1).status_code == 400 and add(Bo, "https://example.com/y", image_url="http://10.0.0.1/").status_code == 400,
      "unknown fields 400 (no picture address from outside)")
check(add(Bo, "https://example.com/z", state="gone").status_code == 400, "a bad state 400")
check(add(Bo, "https://example.com/t", tags=["x"] * 1 + [f"t{i}" for i in range(25)]).status_code == 400, "at most 20 tags")

d = settle(Bo, add(Bo, FS + "/svg.html").json()["bookmark"]["id"])
check(d.get("preview") == "ok" and d["title"] == "Picture as SVG" and d["image"] == "", "an SVG picture is not taken " + json.dumps(d)[:200])
d = settle(Bo, add(Bo, FS + "/big.html").json()["bookmark"]["id"])
check(d.get("preview") == "ok" and d["image"] == "", "a picture above 1 MB is not taken")
d = settle(Bo, add(Bo, FS + "/plain.html").json()["bookmark"]["id"])
check(d.get("title") == "Only a <title>" and d["description"] == "The description meta", "title and description meta as fallback " + json.dumps(d)[:200])
d = settle(Bo, add(Bo, FS + "/nothing-here.html").json()["bookmark"]["id"])
check(d.get("preview") == "failed" and d["preview_error"], "a missing page: preview failed, the bookmark stays")

# ================================================================ refused fetches
put("rss.xml", '<?xml version="1.0"?><rss version="2.0"><channel><title>Feed</title></channel></rss>')
for url, what in ((FS.replace("127.0.0.1", "localhost") + "/local.html", "localhost"), ("http://10.1.2.3/x", "10.x"),
                  ("http://169.254.169.254/latest/meta-data/", "the metadata address"), ("http://[::1]:8098/local6.html", "[::1]"),
                  (FS + "/redir-private", "a redirect to a port not allowed"), (FS + "/redir-meta", "a redirect to the metadata address"),
                  (FS + "/rss.xml", "no web page")):
    r = add(Bo, url)
    check(r.status_code == 201, f"{what}: saved anyway " + r.text[:200])
    d = settle(Bo, r.json()["bookmark"]["id"]) if r.ok else {}
    check(d.get("preview") == "failed" and d.get("preview_error") and d.get("image") == "" and not d.get("text"),
          f"{what}: preview failed, nothing taken " + json.dumps(d)[:200])
check(not any(x["p"] in ("/local.html", "/local6.html") for x in flog()), "the page server never got the refused requests")

# ================================================================ search, tags, states
Bo.patch(B + f"/api/bookmarks/{P1}", json={"note": "for the weekend, ask Carol"})
check([x["id"] for x in lst(Bo, q="zebrafish")["items"]] == [P1], "search in the reading text")
check([x["id"] for x in lst(Bo, q="weekend carol")["items"]] == [P1], "search in the note (all words)")
check([x["id"] for x in lst(Bo, q="page.html")["items"]] == [P1], "search in the link")
check([x["id"] for x in lst(Bo, tag="news")["items"]] == [P1] and lst(Bo, tag="new")["items"] == [], "the tag filter (whole tags only)")
check({"tag": "news", "n": 1} in lst(Bo)["tags"], "the tags with their counts")
# 2.97.0 review (L3, L1): a tag with umlauts is found; a port that is no number is refused (400, no 500)
r = add(Bo, FS + "/plain.html?umlaut=1", tags=["Bücher"])
check(r.status_code == 201 and [x["id"] for x in lst(Bo, tag="Bücher")["items"]] == [r.json()["bookmark"]["id"]], "a tag with umlauts filters")
check(add(Bo, "https://example.com:abc/x").status_code == 400, "a port that is no number: 400")
Bo.delete(B + f"/api/bookmarks/{r.json()['bookmark']['id']}")  # out of the way of the counts below
check(lst(Bo, q="100%_")["items"] == [], "search: % and _ are plain characters")
r = Bo.patch(B + f"/api/bookmarks/{P1}", json={"state": "archived"})
check(r.ok and r.json()["state"] == "archived", "archived")
check(P1 not in [x["id"] for x in lst(Bo)["items"]] and [x["id"] for x in lst(Bo, state="archived")["items"]] == [P1]
      and P1 in [x["id"] for x in lst(Bo, state="all")["items"]], "archived ones are hidden by default")
r = Bo.patch(B + f"/api/bookmarks/{P1}", json={"state": "read", "title": "My title", "tags": "a, b"})
check(r.ok and r.json()["title"] == "My title" and r.json()["tags"] == ["a", "b"] and r.json()["state"] == "read", "change title, tags, state")
check(Bo.patch(B + f"/api/bookmarks/{P1}", json={"state": "x"}).status_code == 400 and Bo.patch(B + f"/api/bookmarks/{P1}", json={"user_id": 1}).status_code == 400,
      "bad changes 400")
check(Bo.get(B + "/api/bookmarks", params={"space": SP}).json()["items"] == [], "the organisation's space has none of the private ones")

# delete + restore
check(Bo.delete(B + f"/api/bookmarks/{P1}").ok and Bo.get(B + f"/api/bookmarks/{P1}").status_code == 404
      and P1 not in [x["id"] for x in lst(Bo, state="all")["items"]], "deleted")
r = Bo.post(B + f"/api/bookmarks/{P1}/restore")
check(r.ok and r.json()["title"] == "My title", "restored (undo)")
Bo.delete(B + f"/api/bookmarks/{P1}")
P1b = add(Bo, FS + "/page.html").json()["bookmark"]["id"]
check(P1b != P1 and Bo.post(B + f"/api/bookmarks/{P1}/restore").status_code == 409, "restore while the link is saved again: 409")
Bo.delete(B + f"/api/bookmarks/{P1b}")
check(Bo.post(B + f"/api/bookmarks/{P1}/restore").ok, "… and after deleting the new one it comes back")
r = Bo.post(B + f"/api/bookmarks/{P1}/refresh")
check(r.ok and r.json()["preview"] == "pending" and settle(Bo, P1).get("preview") == "ok" and settle(Bo, P1)["title"] == "My title",
      "refresh: fetched again, the own title stays")

# ================================================================ an organisation's bookmark (tenant-matrix: bookmark)
r = add(Bo, FS + "/plain.html?team=1", space=SP, tags=["team"])
check(r.status_code == 201 and r.json()["bookmark"]["space"] == SP, "saved in the organisation " + r.text[:200])
O1 = r.json()["bookmark"]["id"]
settle(Bo, O1)
check([x["id"] for x in lst(Ca, space=SP)["items"]] == [O1] and Ca.get(B + f"/api/bookmarks/{O1}").ok, "another member reads it")
x = Ca.get(B + f"/api/bookmarks/{O1}").json()
check(x["can_edit"] is False and x["mine"] is False and lst(Ca, space=SP)["items"][0]["can_edit"] is False, "… without the right to change it")
check(Ca.patch(B + f"/api/bookmarks/{O1}", json={"note": "x"}).status_code == 403 and Ca.delete(B + f"/api/bookmarks/{O1}").status_code == 403
      and Ca.post(B + f"/api/bookmarks/{O1}/refresh").status_code == 403, "a plain member may not change, delete or refresh it (403)")
check(A.patch(B + f"/api/bookmarks/{O1}", json={"note": "checked"}).ok and lst(A, space=SP)["items"][0]["can_edit"] is True, "the organisation's admin may")
for who, s in (("another organisation", Fr),):
    check(s.get(B + f"/api/bookmarks/{O1}").status_code == 404 and s.patch(B + f"/api/bookmarks/{O1}", json={"note": "x"}).status_code == 404
          and s.delete(B + f"/api/bookmarks/{O1}").status_code == 404 and s.get(B + f"/api/bookmarks/{O1}/image").status_code == 404
          and s.post(B + f"/api/bookmarks/{O1}/restore").status_code == 404 and s.post(B + f"/api/bookmarks/{O1}/refresh").status_code == 404,
          f"{who}: 404 everywhere")
    check(s.get(B + "/api/bookmarks", params={"space": SP}).status_code == 404 and O1 not in [i["id"] for i in lst(s, state="all")["items"]],
          f"{who}: the space is unknown, nothing listed")
    check(s.post(B + "/api/bookmarks", json={"url": "https://example.com/q", "space": SP}).status_code == 404, f"{who}: may not save into it")
for who, s in (("another member", Ca), ("another organisation", Fr), ("the admin", A)):
    check(s.get(B + f"/api/bookmarks/{P1}").status_code == 404 and s.get(B + f"/api/bookmarks/{P1}/image").status_code == 404
          and s.patch(B + f"/api/bookmarks/{P1}", json={"note": "x"}).status_code == 404, f"{who}: a private bookmark of Bob is 404")
for hd in (AGH, PTH):
    check(requests.get(B + f"/api/bookmarks/{O1}", headers=hd).status_code in (401, 403), "agent / API token: no single bookmark")

# ================================================================ moving between workspaces
mv = lambda s, **b: s.post(B + "/api/bookmarks/move-space", json=b)  # noqa: E731
r = mv(Bo, ids=[P1], to=SP, dry=1)
check(r.ok and r.json()["count"] == 1 and r.json()["block"] is None and r.json()["notes"], "dry run: 1, a note " + r.text[:200])
check(Bo.get(B + f"/api/bookmarks/{P1}").json()["space"] == "private", "the dry run changed nothing")
pics = lambda: sorted(f for f in os.listdir(os.path.join(DATA, "attachments", "bookmarks")) if f.startswith(f"{P1}-"))  # noqa: E731
before = pics()
r = mv(Bo, ids=[P1], to=SP)
check(r.ok and r.json()["moved"] == [P1] and r.json()["space"] == SP and r.json()["from_space"] == "private", "private -> organisation " + r.text[:200])
check(Ca.get(B + f"/api/bookmarks/{P1}").ok and Ca.get(B + Ca.get(B + f"/api/bookmarks/{P1}").json()["image"]).content == PIC,
      "a member sees it with its picture (sealed again)")
check(len(before) == 1 and len(pics()) == 1 and pics() != before, "a new sealed copy of the picture, the old one is gone " + str((before, pics())))
check(mv(Ca, ids=[P1], to="private").status_code == 403, "a plain member may not move Bob's bookmark out (403)")
check(mv(Bo, ids=[P1], to=f"org:{ORG2}").status_code == 409, "an organisation Bob is not in: 409")
check(mv(Fr, ids=[P1], to=f"org:{ORG2}").status_code == 404, "someone of another organisation: 404")
check(mv(Bo, ids=[P1], to=SP).status_code == 409, "the same workspace: 409")
check(requests.post(B + "/api/bookmarks/move-space", headers=AGH, json={"ids": [P1], "to": "private"}).status_code in (401, 403), "an agent: refused")
r = mv(Bo, ids=[P1], to="private")
check(r.ok and Bo.get(B + f"/api/bookmarks/{P1}").json()["space"] == "private" and Ca.get(B + f"/api/bookmarks/{P1}").status_code == 404,
      "organisation -> private back (the undo)")
D2 = add(Bo, FS + "/page.html", space=SP).json()["bookmark"]["id"]
r = mv(Bo, ids=[P1], to=SP, dry=1)
check(r.ok and r.json()["block"] and r.json()["count"] == 0, "the same link in the target: the dry run blocks " + r.text[:200])
check(mv(Bo, ids=[P1], to=SP).status_code == 409, "… and the move 409")
r = mv(A, ids=[D2], to="private")
check(r.ok and A.get(B + f"/api/bookmarks/{D2}").json()["space"] == "private" and Bo.get(B + f"/api/bookmarks/{D2}").status_code == 404,
      "the admin may take a member's bookmark out of the organisation (it is then theirs)")
check(mv(Bo, ids=[], to=SP).status_code == 400 and mv(Bo, ids=["x"], to=SP).status_code == 400, "bad ids 400")

# ================================================================ a person without an organisation (freelancer-matrix: bookmarks)
FID, Fl = freelancer(B, A)
r = add(Fl, FS + "/plain.html?free=1", tags=["solo"])
check(r.status_code == 201 and r.json()["bookmark"]["space"] == "private", "freelancer: saved in the private space")
FB = r.json()["bookmark"]["id"]
check([x["id"] for x in lst(Fl)["items"]] == [FB] and lst(Fl, space="private")["items"][0]["can_edit"], "freelancer: listed, may change")
check(Fl.patch(B + f"/api/bookmarks/{FB}", json={"state": "read"}).ok and Fl.delete(B + f"/api/bookmarks/{FB}").ok
      and Fl.post(B + f"/api/bookmarks/{FB}/restore").ok, "freelancer: change, delete, restore")
check(mv(Fl, ids=[FB], to=SP).status_code == 409 and mv(Fl, ids=[FB], to="private", dry=1).status_code == 409, "freelancer: no other workspace (409)")
check(Fl.get(B + f"/api/bookmarks/{O1}").status_code == 404 and Bo.get(B + f"/api/bookmarks/{FB}").status_code == 404, "freelancer and others: 404 both ways")

# ================================================================ the parser on its own, the boundary check
out = py_in_app("""from kalmido.life.bookmarks import bm_parse, bm_key, bm_norm_url
p = bm_parse('<html><head><title> T &amp; x </title><meta name="twitter:image" content="javascript:alert(1)"><meta property="og:image" content="img/a.webp"></head>'
             '<body><div>Short</div><p>one two three four</p><script>evil()</script></body></html>', 'https://example.com/dir/page')
print(json.dumps([p['title'], p['image_url'], p['text'], bm_key('HTTPS://Example.com/a/?utm_medium=x&b=1#f'), bm_norm_url('example.org/x'), bm_norm_url('data:x')]))""")
try:
    pv = json.loads(out)
except ValueError:
    pv = None
check(pv == ["T & x", "https://example.com/dir/img/a.webp", "one two three four", "https://example.com/a?b=1", "https://example.org/x", ""],
      "the parser: title, relative picture, javascript: dropped, plain text; the link key " + out[:300])
dbx = py_in_app("""from kalmido.core.db import connect
from kalmido.accounts.tenancy import boundary_check
c = connect(); c.execute("DELETE FROM org_members WHERE org_id=? AND user_id=?", (%d, %d)); r = boundary_check(c); c.rollback(); c.close()
print(json.dumps(r["kinds"].get("bookmark_owner", 0)))""" % (ORG, uid["bob"]))
check(dbx.strip() not in ("", "0") and not dbx.startswith("ERR"), "the boundary check counts an organisation's bookmark of someone who left " + dbx[:300])

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
