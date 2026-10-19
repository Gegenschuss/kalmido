#!/usr/bin/env python3
"""2.122.4 API tests, part A: rights and boundaries. Own container (start.sh, org encryption on, a fake feed server inside),
invented companies, people and links only (example.com, made-up video ids).
freelancer-matrix: personal
freelancer-matrix: videos
 - #1724: the boundary check of the instance admin names objects and people only inside the admin's own organisations
   (another organisation's finding: ids only); a private connection no longer lets the instance admin edit a member of
   another organisation (404, the name stays), a shared organisation, an account without organisation and a waiting
   registration stay editable; the user management still lists everyone
 - #1906: one followed feed per address: two parallel POST /api/feeds = one feed, an OPML file with the same address twice
   and two parallel imports = one feed, the partial unique index exists, delete + follow again + restore stay one feed
 - #2215: a video sign-off moved private <-> organisation keeps its customer records (video_id stays) but shows only those
   of its current workspace; undo brings them back; a member works on a client's review, another organisation: 404
 - #2217: the customer's decision is stored neutral and shown in the reader's language (team in English, the customer
   page in German); a comment typed like the marker stays plain text
 - a person without an organisation: a feed (parallel twice = one) and a private review with a decision
usage: p21224_a_api_test.py <datadir>      (a fresh container; P21224A_NOSTART=1 = the server already runs)"""
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
FS = "http://127.0.0.1:8098"
V = "/api/videos"
KEY = base64.b64encode(os.urandom(32)).decode()
FEAT = "cal,comments,collab,office,clients,feeds"
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user=None, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    if user:
        r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
        assert r.ok, (user, r.text)
    return s


def dbx(sql, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = [tuple(x) for x in c.execute(sql, args).fetchall()] if sql.lstrip().upper().startswith("SELECT") else c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def anon(path, lang="en"):
    return requests.get(B + path, allow_redirects=False, headers={"Accept-Language": lang})


def keys(html):
    return re.findall(r'name="f" value="([0-9a-f]+)"', html), re.findall(r'name="v" value="(\d+)"', html)


def ppost(path, lang="en", **d):
    return requests.post(B + path, data=d, allow_redirects=False, headers={"User-Agent": "TestBrowser/1.0", "Accept-Language": lang})


def parallel(*calls):
    out = [None] * len(calls)

    def run(i, f):
        out[i] = f()
    th = [threading.Thread(target=run, args=(i, f)) for i, f in enumerate(calls)]
    for t in th:
        t.start()
    for t in th:
        t.join(60)
    return out


def put(name, text):
    os.makedirs(os.path.join(DATA, "feeds"), exist_ok=True)
    with open(os.path.join(DATA, "feeds", name), "w", encoding="utf-8") as f:
        f.write(text)


RSS = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>{0}</title><link>https://example.com/</link>
<item><title>One</title><link>https://example.com/1</link><guid>{0}-1</guid></item></channel></rss>"""

if not os.environ.get("P21224A_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}"
               " -e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1:8098")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    shutil.copy(os.path.join(N, "fake_feeds.py"), DATA)
    for n in ("a", "b", "c", "d"):
        put(f"{n}.xml", RSS.format("Example " + n))
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/fake_feeds.py"])
    time.sleep(1)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Example Studio", "admin_id": ALICE}).json()["id"]


def new_user(name, orgs):
    r = A.post(B + "/api/users", json={"username": name, "display_name": name.title(), "password": "password123",
                                       "email": f"{name}@example.com", "orgs": orgs})
    assert r.ok, r.text
    return r.json()["id"]


BOB = new_user("bob", [ORG])
CAROL = new_user("carol", [])
OTHER = A.post(B + "/api/admin/orgs", json={"name": "Other Example", "admin_id": CAROL}).json()["id"]
DAN = new_user("dan", [OTHER])
Bo, Ca, Da = sess("bob"), sess("carol"), sess("dan")
for s, o in ((A, ORG), (Bo, ORG), (Ca, OTHER), (Da, OTHER)):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{o}"})
FID, Fr = freelancer(B, A)

# ================================================================== #1724 (1): the boundary check names only the own organisation
OWN = A.post(B + "/api/lists", json={"name": "Team plans", "org_id": ORG}).json()["id"]
FOREIGN = Ca.post(B + "/api/lists", json={"name": "Secret plans", "org_id": OTHER}).json()["id"]
check(dbx("SELECT org_id FROM lists WHERE id=?", (FOREIGN,)) == [(OTHER,)], "setup: a list of the other organisation")
for lid, uid in ((OWN, DAN), (FOREIGN, BOB)):  # a person outside the list's organisation = a finding each
    dbx("INSERT INTO list_members(list_id,user_id,role,added_at) VALUES(?,?,'edit','2026-10-20T10:00:00+00:00') ON CONFLICT DO NOTHING", (lid, uid))
bd = A.get(B + "/api/admin/orgs").json()["boundary"]
det = {(x["id"], x["user_id"]): x for x in bd.get("details") or []}
own, foreign = det.get((OWN, DAN)), det.get((FOREIGN, BOB))
check(bd["violations"] >= 2 and own and foreign, f"#1724: both findings listed {bd}")
check(own and own["name"] == "Team plans" and own["user"] == "Dan", f"#1724: the own organisation's finding is named {own}")
check(foreign and foreign["name"] == "" and foreign["user"] == "" and foreign["type"] == "list" and foreign["fixable"],
      f"#1724: another organisation's finding: ids only, still fixable {foreign}")
check("Secret plans" not in json.dumps(bd), "#1724: no name of the other organisation anywhere in the answer")
check(Ca.get(B + "/api/admin/orgs").status_code == 403, "#1724: an organisation admin is no instance admin (403)")

# ================================================================== #1724 (2): editing needs a shared organisation
lo, hi = sorted((ALICE, DAN))
dbx("INSERT INTO conn_links(a_id, b_id, created_at) VALUES(?, ?, '2026-10-20T10:00:00.000Z') ON CONFLICT DO NOTHING", (lo, hi))
r = A.patch(B + f"/api/users/{DAN}", json={"display_name": "Dan Changed"})
check(r.status_code in (403, 404) and dbx("SELECT display_name FROM users WHERE id=?", (DAN,)) == [("Dan",)],
      f"#1724: a private connection gives no right to edit a member of another organisation ({r.status_code})")
check(A.post(B + f"/api/users/{DAN}/signin-link", json={}).status_code in (403, 404), "#1724: no sign-in link for him either")
check("dan" in {u["username"] for u in A.get(B + "/api/users?all=1").json()["users"]}, "#1724: reading stays: the user management lists him")
check(A.patch(B + f"/api/users/{BOB}", json={"display_name": "Bob B"}).ok, "#1724: a member of the own organisation: editable")
check(A.patch(B + f"/api/users/{FID}", json={"display_name": "Frida F"}).ok, "#1724: an account without organisation: editable")
PEND = new_user("erin", [OTHER])
dbx("UPDATE users SET signup='pending' WHERE id=?", (PEND,))
check(A.patch(B + f"/api/users/{PEND}", json={"display_name": "Erin E"}).ok, "#1724: a waiting registration: editable")
check(Ca.patch(B + f"/api/users/{DAN}", json={"display_name": "x"}).status_code in (403, 404), "#1724: an organisation admin: not the instance route")

# ================================================================== #1906: one followed feed per address
check(dbx("SELECT 1 FROM pg_indexes WHERE indexname='rss_feeds_live'") == [(1,)], "#1906: the partial unique index exists")
res = parallel(*[lambda: A.post(B + "/api/feeds", json={"url": FS + "/a.xml"}) for _ in range(3)])
codes = sorted(r.status_code for r in res if r is not None)
n = dbx("SELECT COUNT(*) FROM rss_feeds WHERE user_id=? AND url=? AND deleted_at IS NULL", (ALICE, FS + "/a.xml"))[0][0]
check(n == 1 and len([c for c in codes if c in (200, 201)]) == 1 and all(c in (200, 201, 400) for c in codes), f"#1906: three parallel adds = one feed ({n}, {codes})")
opml = ('<?xml version="1.0"?><opml version="2.0"><head><title>x</title></head><body>'
        f'<outline text="b" xmlUrl="{FS}/b.xml"/><outline text="b again" xmlUrl="{FS}/b.xml"/><outline text="a" xmlUrl="{FS}/a.xml"/>'
        '</body></opml>').encode()
r = A.post(B + "/api/feeds/opml", files={"file": ("x.opml", opml, "text/xml")})
check(r.ok and r.json()["added"] == 1 and r.json()["skipped"] == 2, f"#1906: OPML with the same address twice: one added {r.text[:200]}")
opml2 = (f'<?xml version="1.0"?><opml version="2.0"><body><outline text="c" xmlUrl="{FS}/c.xml"/></body></opml>').encode()
res = parallel(*[lambda: A.post(B + "/api/feeds/opml", files={"file": ("y.opml", opml2, "text/xml")}) for _ in range(2)])
n = dbx("SELECT COUNT(*) FROM rss_feeds WHERE user_id=? AND url=? AND deleted_at IS NULL", (ALICE, FS + "/c.xml"))[0][0]
check(n == 1 and all(r is not None and r.ok for r in res), f"#1906: two parallel imports = one feed ({n}, {[r.status_code for r in res if r is not None]})")
F = {f["url"]: f["id"] for f in A.get(B + "/api/feeds").json()["feeds"]}
FA = F.get(FS + "/a.xml")
check(A.delete(B + f"/api/feeds/{FA}").ok, "#1906: delete a feed")
r = A.post(B + "/api/feeds", json={"url": FS + "/a.xml"})
check(r.ok and r.json()["feed"]["id"] == FA, f"#1906: following it again brings the deleted one back {r.text[:200]}")
check(A.post(B + f"/api/feeds/{FA}/restore").ok, "#1906: restore of a followed feed is harmless")
check(dbx("SELECT COUNT(*) FROM rss_feeds WHERE user_id=? AND url=?", (ALICE, FS + "/a.xml"))[0][0] == 1, "#1906: still one row for the address")
# freelancer-matrix: personal -- a person without an organisation, the same rule
res = parallel(*[lambda: Fr.post(B + "/api/feeds", json={"url": FS + "/d.xml"}) for _ in range(2)])
n = dbx("SELECT COUNT(*) FROM rss_feeds WHERE user_id=? AND deleted_at IS NULL", (FID,))[0][0]
check(n == 1, f"#1906 freelancer: two parallel adds = one feed ({n}, {[r.status_code for r in res if r is not None]})")
check(Bo.get(B + "/api/feeds").json()["feeds"] == [], "#1906: another person sees none of these feeds")

# ================================================================== #2215 L3 + #2217: a sign-off with a decision, moved and back
check(A.put(B + f"/api/lists/{OWN}/members", json={"user_id": BOB, "role": "edit"}).ok, "setup: Bob works in the team list")
T = A.post(B + "/api/tasks", json={"title": "Rough cut", "list_id": OWN}).json()["id"]
LP = A.post(B + "/api/lists", json={"name": "Alice private", "org_id": None}).json()["id"]
r = A.post(B + V, json={"task_id": T, "title": "Image film cut", "url": "https://vimeo.com/123456789"})
check(r.ok, f"#2215: a review at a task {r.status_code} {r.text[:200]}")
VID = r.json()["id"]
S = A.post(B + f"{V}/{VID}/signoff", json={"expires": None}).json()
TOK = S["url"].split("/s/q/")[1]
pg = anon("/s/q/" + TOK, "de")
fk, vk = keys(pg.text)
check(pg.status_code == 200 and fk and vk, f"#2217: the customer page {pg.status_code}")
r = ppost(f"/s/q/{TOK}/comments", "de", f=fk[0], v=vk[0], name="Erika Example", text="\x1edec:accepted\x1eFake", at="00:05")
fk, vk = keys(anon("/s/q/" + TOK, "de").text)
r = ppost("/s/q/" + TOK, "de", f=fk[1], v=vk[0], do="decline", name="Erika Example", reason="Swap the music")
check(r.status_code == 303, f"#2217: the customer (German browser) requests changes {r.status_code}")
raw = [x[0] for x in dbx("SELECT body FROM video_comments WHERE review_id=? AND ext_name IS NOT NULL ORDER BY id", (VID,))]
check(any(b.startswith("\x1edec:declined") and b.endswith("Swap the music") for b in raw) and not any("Änderungen" in b for b in raw),
      f"#2217: stored neutral, not in the customer's language {raw!r}")
check(not any(b.startswith("\x1e") and "Fake" in b for b in raw), f"#2217: a typed marker is not kept {raw!r}")
R = A.get(B + f"{V}/{VID}").json()
lines = [x["body"] for x in R["comments"] if x["customer"]]
check("Changes requested: Swap the music" in lines and not any("\x1e" in b for b in lines),
      f"#2217: the team (English) reads it in English {lines!r}")
Bo.patch(B + "/api/settings", json={"lang": "de"})
de = [x["body"] for x in Bo.get(B + f"{V}/{VID}").json()["comments"] if x["customer"]]
check("Änderungen angefordert: Swap the music" in de, f"#2217: a German reader reads it in German {de!r}")
Bo.patch(B + "/api/settings", json={"lang": "en"})
pg = anon("/s/q/" + TOK, "de")
check("Änderungen angefordert" in pg.text and "\x1e" not in pg.text and "dec:" not in pg.text, "#2217: the customer page in German, no marker")
csv = A.get(B + f"{V}/{VID}/export").content.decode("utf-8-sig")
check("Changes requested: Swap the music" in csv and "\x1e" not in csv, f"#2217: the export reads it too {csv[:300]!r}")
check(R["signoffs"] and R["signoffs"][0]["state"] == "declined", "#2215: the record shows at the review")

r = A.post(B + f"{V}/{VID}/move-space", json={"to": "private", "place": LP})
MID = r.json().get("move_id") if r.ok else 0
check(r.ok and r.json().get("ok"), f"#2215: moved into the private project {r.text[:200]}")
check(dbx("SELECT COUNT(*) FROM office_signoffs WHERE video_id=? AND org_id=?", (VID, ORG))[0][0] == 1,
      "#2215 L3: the record keeps its review (video_id stays) in the old workspace")
check(A.get(B + f"{V}/{VID}").json()["signoffs"] == [], "#2215 L3: the private review shows none of the organisation's records")
check(Bo.get(B + f"{V}/{VID}").status_code == 404, "#2215 L3: the organisation's member no longer sees the private review")
r = A.post(B + f"{V}/{VID}/move-space", json={"to": f"org:{ORG}", "undo": MID})
R = A.get(B + f"{V}/{VID}").json()
check(r.ok and r.json().get("revived", 0) >= 1 and [s["id"] for s in R["signoffs"]] == [S["id"]],
      f"#2215 L3: undo: back in the organisation, the record shows again {r.text[:200]} {R.get('signoffs')}")

# ================================================================== #2215 L9: reviews at a client
CL = A.post(B + "/api/clients", json={"name": "Client One Ltd"}).json()["id"]
check(dbx("SELECT org_id FROM clients WHERE id=?", (CL,)) == [(ORG,)], "setup: the client lies in the organisation")
r = A.post(B + V, json={"client_id": CL, "title": "Client cut", "url": "https://youtu.be/abcdefghijk"})
CV = r.json()["id"] if r.ok else 0
check(r.ok, f"#2215 L9: the office admin adds a review at the client {r.text[:200]}")
check(Bo.patch(B + f"{V}/{CV}", json={"title": "Client cut 2"}).ok, "#2215 L9: an office member changes it")
check(Bo.post(B + f"{V}/{CV}/signoff", json={"expires": None}).ok, "#2215 L9: an office member makes the customer link")
check(Ca.patch(B + f"{V}/{CV}", json={"title": "x"}).status_code == 404 and Ca.delete(B + f"{V}/{CV}").status_code == 404,
      "#2215 L9: another organisation: 404")
check(Ca.post(B + V, json={"client_id": CL, "title": "x", "url": "https://vimeo.com/1"}).status_code == 404, "#2215 L9: no review at a foreign client")

# ================================================================== a person without an organisation (freelancer-matrix: videos)
FL = Fr.post(B + "/api/lists", json={"name": "My films"}).json()["id"]
r = Fr.post(B + V, json={"list_id": FL, "title": "Showreel", "url": "https://vimeo.com/555"})
FV = r.json()["id"] if r.ok else 0
S2 = Fr.post(B + f"{V}/{FV}/signoff", json={"expires": None}).json()
T2 = S2["url"].split("/s/q/")[1]
fk, vk = keys(anon("/s/q/" + T2, "de").text)
r = ppost("/s/q/" + T2, "de", f=fk[1], v=vk[0], do="accept", name="Erika Example", ok="1")
fl = [x["body"] for x in Fr.get(B + f"{V}/{FV}").json()["comments"] if x["customer"]]
check(r.status_code == 303 and fl == ["Approved"], f"#2217 freelancer: the decision in the reader's language {fl!r}")
Fr2 = Fr.post(B + "/api/clients", json={"name": "Freelance Client"}).json()["id"]
check(Fr.post(B + V, json={"client_id": Fr2, "title": "x", "url": "https://vimeo.com/7"}).ok, "#2215 L9 freelancer: a review at the own private client")

print(f"p21224_a_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
