#!/usr/bin/env python3
"""2.99.1 API tests, part A (#1959, video sign-off with comments at a timecode, links only), own container (start.sh, org
encryption on). Invented companies, people and links only (example.com and made-up video ids).
tenant-matrix: video
freelancer-matrix: videos
 - links: Vimeo (also unlisted with its hash, the player URL), YouTube (watch, youtu.be, shorts) -> the embed URL built from
   the checked id (youtube-nocookie), a direct file (MP4 / WebM / MOV; Dropbox dl=0 -> raw=1), anything else = a link without
   time control; http, javascript:, data:, user:password@ and spaces refused (400)
 - comments: the second stored, answers (one level, no timecode of their own), done and back, the author edits, delete +
   restore; versions: a new link = v2, the comments stay at v1, the newest version can be taken back while it has no comments
 - export: CSV (timecode mm:ss, name, text, done; no formulas) and as text
 - customer link (signoff kind video): the page with the player of the newest version, its own CSP (frame-src of the two
   players, script-src 'self'), the customer's comments + the team's answers only (internal comments stay internal), a
   comment with timecode (form check value, Sec-Fetch-Site, name >= 2, a stale version 409, the limit per address),
   "Request changes" / "Approve" -> the review's state + a comment line, a new link stops the old one, revoked / deleted =
   the same answer as unknown
 - rights: another organisation / a stranger / an agent: 404 (or an empty list) on every route; a member who sees the client
   works on a client's review; moving needs its creator or an admin; move-space private <-> organisation into a project
   there and back (undo), the place and the customer links come back
 - a person without an organisation: everything at a private task / list / client
 - the app page's CSP allows exactly the two players as frames and media over https
usage: p2991_a_api_test.py <datadir>      (P2991A_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import base64
import os
import re
import subprocess
import sys
import time

import dbx as dbxm
import requests
from freelancer_fixture import freelancer

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check, sess  # 2.192.0 (#2514): shared helpers (tests/kt.py)
FEAT = "cal,comments,collab,office,clients"
V = "/api/videos"


def sql(q, args=()):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        return c.execute(q, args).fetchall()
    finally:
        c.close()


def app_log():
    """The server's last traceback (a 500 shows in the suite's log)."""
    out = subprocess.run(["docker", "logs", "--tail", "400", os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")], capture_output=True, text=True)
    text = out.stdout + out.stderr
    i = text.rfind("Traceback")
    print(text[i:i + 4000] if i >= 0 else text[-2000:], flush=True)


def anon(path, **kw):  # 2.99.1: the customer page in English (it falls back to German without Accept-Language)
    kw.setdefault("headers", {}).setdefault("Accept-Language", "en")
    return requests.get(B + path, allow_redirects=False, **kw)


def keys(html):
    f = re.findall(r'name="f" value="([0-9a-f]+)"', html)
    v = re.findall(r'name="v" value="(\d+)"', html)
    return f, v


def ppost(path, **d):
    hd = {"User-Agent": "TestBrowser/1.0", "Accept-Language": "en"}
    hd.update(d.pop("_h", {}))
    return requests.post(B + path, data=d, allow_redirects=False, headers=hd)


if os.environ.get("P2991A_NOSTART") != "1":
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY}")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
ALICE = A.get(B + "/api/state").json()["me"]["id"]
Bo, Ca = sess("bob"), sess("carol")
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
CAROL = Ca.get(B + "/api/state").json()["me"]["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "claude", "display_name": "Claude"}).json()
AGH = {"Authorization": "Bearer " + ag["token"], "X-Requested-With": "kalmido"}
FID, Fr = freelancer(B, A)

L = A.post(B + "/api/lists", json={"name": "Imagefilm Frühling", "org_id": ORG}).json()["id"]
LP = A.post(B + "/api/lists", json={"name": "Privat Alice", "org_id": None}).json()["id"]
T = A.post(B + "/api/tasks", json={"title": "Schnitt Rohfassung", "list_id": L}).json()["id"]
CL = A.post(B + "/api/clients", json={"name": "Kunde Eins GmbH"}).json()["id"]
L2 = Ca.post(B + "/api/lists", json={"name": "Fremdprojekt", "org_id": ORG2}).json()["id"]
T2 = Ca.post(B + "/api/tasks", json={"title": "Fremd", "list_id": L2}).json()["id"]
check(sql("SELECT org_id FROM clients WHERE id=?", (CL,))[0][0] == ORG, "the client lies in the organisation")

# ---------------------------------------------------------------- links: provider, embed URL
r = A.post(B + V, json={"task_id": T, "title": "Imagefilm Schnitt", "url": "https://vimeo.com/123456789"})
check(r.ok, f"a review at a task {r.status_code} {r.text[:200]}")
if not r.ok:
    app_log()
    sys.exit(1)
R = r.json()
VID = R["id"]
v1 = R["versions"][0]
check(v1["provider"] == "vimeo" and v1["embed"].startswith("https://player.vimeo.com/video/123456789?") and "dnt=1" in v1["embed"] and v1["timed"]
      and R["org_id"] == ORG and R["task_id"] == T and R["state"] == "open" and R["version"] == 1, f"Vimeo -> its player {v1}")
LINKS = [
    ("https://vimeo.com/123456789/abcdef1234", "vimeo", "https://player.vimeo.com/video/123456789?h=abcdef1234&dnt=1&playsinline=1"),
    ("https://player.vimeo.com/video/76979871?h=8272103f6e", "vimeo", "https://player.vimeo.com/video/76979871?h=8272103f6e&dnt=1&playsinline=1"),
    ("https://youtu.be/AbCdEfGhI_9", "youtube", "https://www.youtube-nocookie.com/embed/AbCdEfGhI_9?enablejsapi=1&rel=0&playsinline=1"),
    ("https://www.youtube.com/watch?v=AbCdEfGhI-9&t=42s", "youtube", "https://www.youtube-nocookie.com/embed/AbCdEfGhI-9?enablejsapi=1&rel=0&playsinline=1"),
    ("https://youtube.com/shorts/ZyXwVuTsR01", "youtube", "https://www.youtube-nocookie.com/embed/ZyXwVuTsR01?enablejsapi=1&rel=0&playsinline=1"),
    ("https://cloud.example.com/s/Ab12/download/Schnitt_v3.MP4", "file", "https://cloud.example.com/s/Ab12/download/Schnitt_v3.MP4"),
    ("https://www.dropbox.com/scl/fi/xyz/clip.mov?rlkey=k1&dl=0", "file", "https://www.dropbox.com/scl/fi/xyz/clip.mov?rlkey=k1&raw=1"),
    # 2.99.1 review L6: an explicit :443, the video of a showcase
    ("https://www.youtube.com:443/watch?v=AbCdEfGhI-9", "youtube", "https://www.youtube-nocookie.com/embed/AbCdEfGhI-9?enablejsapi=1&rel=0&playsinline=1"),
    ("https://vimeo.com/showcase/1234567/video/76979871", "vimeo", "https://player.vimeo.com/video/76979871?dnt=1&playsinline=1"),
    ("https://www.youtube.com:8443/watch?v=AbCdEfGhI-9", "link", None),
    ("https://drive.example.com/file/d/xyz/view", "link", None),
    ("https://www.youtube.com/watch?v=short", "link", None),
    ("https://evil.example.com/player.vimeo.com/video/1", "link", None),
    ("https://vimeo.com.evil.example/123456789", "link", None),
]
for url, prov, emb in LINKS:
    r = A.post(B + f"{V}/{VID}/versions", json={"url": url})
    vv = r.json()["versions"][-1] if r.ok else {}
    check(r.ok and vv.get("provider") == prov and vv.get("embed") == emb and vv.get("timed") == (prov != "link"), f"{url} -> {prov} {emb} ({r.status_code} {vv})")
for bad in ("http://example.com/clip.mp4", "javascript:alert(1)", "data:video/mp4;base64,AAAA", "https://user:pw@example.com/clip.mp4",
            "https://example.com/a b.mp4", "ftp://example.com/clip.mp4", "", "  ", "https://" + "a" * 2001 + ".mp4", 42):
    check(A.post(B + f"{V}/{VID}/versions", json={"url": bad}).status_code == 400, f"refused: {str(bad)[:40]!r}")
R = A.get(B + f"{V}/{VID}").json()
check([x["n"] for x in R["versions"]] == list(range(1, len(LINKS) + 2)), "a version per link (v1, v2 ...)")
# the newest version without comments can be taken back (the undo of "New version"); an older one not
NEW = R["versions"][-1]["id"]
check(A.delete(B + f"{V}/{VID}/versions/{R['versions'][1]['id']}").status_code == 409, "only the newest version can be taken back")
check(A.delete(B + f"{V}/{VID}/versions/{NEW}").ok and len(A.get(B + f"{V}/{VID}").json()["versions"]) == len(LINKS), "the newest version taken back")

# ---------------------------------------------------------------- comments at a timecode
V1 = v1["id"]
r = A.post(B + f"{V}/{VID}/comments", json={"version_id": V1, "at_sec": 83.46, "body": "Schnitt hier zu hart"})
check(r.ok and r.json()["comment_id"], f"a comment at 01:23 {r.status_code} {r.text[:200]}")
C1 = r.json()["comment_id"]
c1 = next(x for x in r.json()["comments"] if x["id"] == C1)
check(c1["at_sec"] == 83.5 and c1["version_id"] == V1 and c1["author"] == "Alice Admin" and not c1["done"] and not c1["customer"], f"the second stored {c1}")
r = A.post(B + f"{V}/{VID}/comments", json={"version_id": V1, "at_sec": "1:02:03", "body": "=SUM(1)"})
check(r.ok and next(x for x in r.json()["comments"] if x["id"] == r.json()["comment_id"])["at_sec"] == 3723.0, "a timecode as h:mm:ss")
C2 = r.json()["comment_id"]
for bad in (-1, 86401, "aa", True, "12:xx"):
    check(A.post(B + f"{V}/{VID}/comments", json={"version_id": V1, "at_sec": bad, "body": "x"}).status_code == 400, f"a bad timecode {bad!r}: 400")
check(A.post(B + f"{V}/{VID}/comments", json={"version_id": V1, "body": "  "}).status_code == 400, "an empty comment: 400")
check(Ca.post(B + f"{V}/{VID}/comments", json={"version_id": V1, "body": "x"}).status_code == 404, "another organisation cannot comment")
r = A.post(B + f"{V}/{VID}/comments", json={"parent_id": C1, "at_sec": 5, "body": "Erledige ich"})
RE = r.json()["comment_id"] if r.ok else 0
x = next((x for x in r.json()["comments"] if x["id"] == RE), {}) if r.ok else {}
check(r.ok and x.get("parent_id") == C1 and x.get("at_sec") is None and x.get("version_id") == V1, f"an answer: no timecode of its own {x}")
check(A.post(B + f"{V}/{VID}/comments", json={"parent_id": RE, "body": "tiefer"}).status_code == 400, "an answer to an answer: 400 (one level)")
r = A.patch(B + f"{V}/{VID}/comments/{C1}", json={"done": True})
check(r.ok and next(x for x in r.json()["comments"] if x["id"] == C1)["done"] and r.json()["open_comments"] == 1, "done (open comments counted)")
r = A.patch(B + f"{V}/{VID}/comments/{C1}", json={"done": False})
check(r.ok and not next(x for x in r.json()["comments"] if x["id"] == C1)["done"], "done taken back")
check(A.patch(B + f"{V}/{VID}/comments/{C2}", json={"body": "=SUM(1) neu"}).ok, "the author edits")
LINKV = A.get(B + f"{V}/{VID}").json()["versions"][-1]
check(LINKV["provider"] == "link", "the newest version is a link without time control")
r = A.post(B + f"{V}/{VID}/comments", json={"version_id": LINKV["id"], "at_sec": 12, "body": "Ohne Zeit"})
check(r.ok and next(x for x in r.json()["comments"] if x["id"] == r.json()["comment_id"])["at_sec"] is None, "no timecode at a link without time control")
CX = r.json()["comment_id"]
check(A.delete(B + f"{V}/{VID}/comments/{CX}").ok and all(x["id"] != CX for x in A.get(B + f"{V}/{VID}").json()["comments"]), "a comment deleted")
check(A.post(B + f"{V}/{VID}/comments/{CX}/restore").ok and any(x["id"] == CX for x in A.get(B + f"{V}/{VID}").json()["comments"]), "and restored (undo)")
check(sql("SELECT org_id FROM video_comments WHERE id=?", (C1,))[0][0] == ORG and sql("SELECT org_id FROM video_versions WHERE id=?", (V1,))[0][0] == ORG,
      "versions and comments carry the organisation")

# ---------------------------------------------------------------- export
r = A.get(B + f"{V}/{VID}/export?version_id={V1}")
txt = r.content.decode("utf-8-sig") if r.ok else ""
check(r.ok and r.headers["Content-Type"].startswith("text/csv") and "attachment" in r.headers.get("Content-Disposition", "")
      and "v1;01:23;Alice Admin;Schnitt hier zu hart;;" in txt and "1:02:03" in txt and "'=SUM(1) neu" in txt and "Erledige ich" in txt
      and "Ohne Zeit" not in txt, f"CSV of version 1 (timecode, name, text; no formulas) {txt[:300]!r}")
r = A.get(B + f"{V}/{VID}/export?format=text")
t = r.json().get("text", "") if r.ok else ""
check("[ ] v1 01:23 Alice Admin: Schnitt hier zu hart" in t and "    > Alice Admin: Erledige ich" in t and "--:--" in t, f"as text for the cut {t[:300]!r}")

# ---------------------------------------------------------------- the tenant matrix: another organisation, an agent, a stranger
for s, who in ((Ca, "another organisation"), (Fr, "a person without organisation")):
    check(s.get(B + f"{V}/{VID}").status_code == 404, f"{who}: GET 404")
    check(s.patch(B + f"{V}/{VID}", json={"title": "x"}).status_code == 404, f"{who}: PATCH 404")
    check(s.post(B + f"{V}/{VID}/versions", json={"url": "https://vimeo.com/1234567"}).status_code == 404, f"{who}: new version 404")
    check(s.patch(B + f"{V}/{VID}/comments/{C1}", json={"done": True}).status_code == 404, f"{who}: done 404")
    check(s.delete(B + f"{V}/{VID}/comments/{C1}").status_code == 404, f"{who}: delete a comment 404")
    check(s.get(B + f"{V}/{VID}/export").status_code == 404, f"{who}: export 404")
    check(s.post(B + f"{V}/{VID}/signoff", json={}).status_code == 404, f"{who}: customer link 404")
    check(s.post(B + f"{V}/{VID}/move-space", json={"to": "private", "dry": 1}).status_code == 404, f"{who}: move 404")
    check(s.delete(B + f"{V}/{VID}").status_code == 404, f"{who}: delete 404")
    check(s.get(B + f"{V}?task_id={T}").json().get("reviews") == [], f"{who}: the task's list is empty")
    check(s.post(B + V, json={"task_id": T, "url": "https://vimeo.com/1234567"}).status_code == 404, f"{who}: no review at a foreign task")
    check(s.post(B + V, json={"client_id": CL, "url": "https://vimeo.com/1234567"}).status_code == 404, f"{who}: none at a foreign client")
    check(s.post(B + V, json={"list_id": L, "url": "https://vimeo.com/1234567"}).status_code == 404, f"{who}: none at a foreign list")
AGC = (requests.get(B + f"{V}/{VID}", headers=AGH).status_code, requests.post(B + V, json={"task_id": T, "url": "https://vimeo.com/1234567"}, headers=AGH).status_code,
       requests.get(B + f"{V}?task_id={T}", headers=AGH).json().get("reviews", []))
check(AGC[0] in (401, 403, 404) and AGC[1] in (401, 403, 404) and AGC[2] == [], f"an agent: not through the app's routes {AGC}")
check(A.post(B + V, json={"task_id": T2, "url": "https://vimeo.com/1234567"}).status_code == 404, "Alice: none at another organisation's task")
check(A.post(B + V, json={"task_id": T, "list_id": L, "url": "https://vimeo.com/1234567"}).status_code == 400, "exactly one place")
check(Ca.get(B + f"{V}/999999").status_code == 404, "unknown id 404")

# a client's review: a member of the organisation who sees the client works on it
r = A.post(B + V, json={"client_id": CL, "url": "https://youtu.be/AbCdEfGhI_9", "title": "Kundenfilm"})
CV = r.json()["id"] if r.ok else 0
check(r.ok and r.json()["client_id"] == CL and r.json()["org_id"] == ORG, "a review at a client")
check(Bo.get(B + f"{V}?client_id={CL}").json()["reviews"][0]["id"] == CV and Bo.post(B + f"{V}/{CV}/comments", json={"body": "Ton zu leise", "at_sec": 3}).ok,
      "Bob (member) sees the client's review and comments")
check(Bo.post(B + f"{V}/{CV}/move-space", json={"to": "private", "dry": 1}).status_code == 403, "Bob is neither its creator nor an admin: no move")
check(Ca.get(B + f"{V}?client_id={CL}").json()["reviews"] == [], "Carol: no reviews of a foreign client")
r = A.post(B + V, json={"list_id": L, "url": "https://example.com/film.webm"})
check(r.ok and r.json()["list_id"] == L and r.json()["versions"][0]["provider"] == "file", "a review at a project list")
LV = r.json()["id"]

# ---------------------------------------------------------------- the customer link (signoff kind video)
r = A.post(B + f"{V}/{CV}/signoff", json={"expires": None})
check(r.ok and r.json()["kind"] == "video" and r.json()["video_id"] == CV and r.json()["url"], f"a customer link {r.status_code} {r.text[:200]}")
S1 = r.json()
TOK = S1["url"].split("/s/q/")[1]
UNKNOWN = anon("/s/q/" + "z" * 43)
pg = anon("/s/q/" + TOK)
csp = pg.headers.get("Content-Security-Policy", "")
check(pg.status_code == 200 and "frame-src https://player.vimeo.com https://www.youtube-nocookie.com" in csp and "script-src 'self'" in csp
      and "default-src 'none'" in csp and "frame-ancestors 'none'" in csp, f"the page's own CSP {csp}")
check('src="https://www.youtube-nocookie.com/embed/AbCdEfGhI_9?enablejsapi=1&amp;rel=0&amp;playsinline=1&amp;origin=' in pg.text
      and 'referrerpolicy="strict-origin-when-cross-origin"' in pg.text and '<script src="/static/js/pubvideo.js" defer></script>' in pg.text,
      "the player of the newest version, no script of the provider")
check("Ton zu leise" not in pg.text, "the team's internal comment is not on the customer page")
js = anon("/static/js/pubvideo.js")
check(js.status_code == 200 and "postMessage" in js.text, "the customer page's script is served from the app itself")
fk, vk = keys(pg.text)
check(len(fk) == 2 and fk[0] != fk[1] and vk, "a form check value for comments and one for the decision")
CF, DF, VV = fk[0], fk[1], vk[0]
r = ppost(f"/s/q/{TOK}/comments", f=CF, v=VV, name="Erika Beispiel", text="Logo bitte <b>größer</b>", at="00:42")
check(r.status_code == 303 and "sent=1" in r.headers.get("Location", ""), f"a customer comment {r.status_code}")
row = sql("SELECT at_sec, ext_name, author_id, body FROM video_comments WHERE review_id=? AND ext_name IS NOT NULL", (CV,))
check(len(row) == 1 and row[0][0] == 42.0 and row[0][1] == "Erika Beispiel" and row[0][2] is None, f"stored with the second and the name {row}")
CC = sql("SELECT id FROM video_comments WHERE review_id=? AND ext_name IS NOT NULL", (CV,))[0][0]
check(A.post(B + f"{V}/{CV}/comments", json={"parent_id": CC, "body": "Machen wir"}).ok, "the team answers the customer")
pg = anon("/s/q/" + TOK + "?sent=1")
check("Logo bitte &lt;b&gt;größer&lt;/b&gt;" in pg.text and "Machen wir" in pg.text and 'data-at="42.0"' in pg.text and "00:42" in pg.text
      and "Ton zu leise" not in pg.text, "the page: the customer's comment (escaped), the team's answer, the mark at 00:42")
check(ppost(f"/s/q/{TOK}/comments", f=CF, v=VV, name="Erika", text="x", _h={"Sec-Fetch-Site": "cross-site"}).status_code == 403, "cross-site: 403")
check(ppost(f"/s/q/{TOK}/comments", f="0" * 64, v=VV, name="Erika", text="x").status_code == 403, "a wrong form key: 403")
check(ppost(f"/s/q/{TOK}/comments", f=CF, v=VV, name="E", text="x").status_code == 400, "a name of one letter: 400")
check(ppost(f"/s/q/{TOK}/comments", f=CF, v=VV, name="Erika", text="  ").status_code == 400, "no text: 400")
check(ppost(f"/s/q/{TOK}/comments", f=CF, v=str(int(VV) + 999), name="Erika", text="alt").status_code == 409, "a stale version: 409")
# 2.99.1 (#1959) review L8: a bad timecode is said (400 with the way back), not silently dropped
check(ppost(f"/s/q/{TOK}/comments", f=CF, v=VV, name="Erika", text="x", at="zz").status_code == 400, "a bad timecode: 400")
# a new version keeps the link; the decision names the version shown
r = A.post(B + f"{V}/{CV}/versions", json={"url": "https://vimeo.com/987654321"})
pg = anon("/s/q/" + TOK)
check(pg.status_code == 200 and "player.vimeo.com/video/987654321" in pg.text and "Version 2" in pg.text, "the link shows the newest version")
fk2, vk2 = keys(pg.text)
r = ppost("/s/q/" + TOK, f=fk2[1], v=VV, do="decline", name="Erika Beispiel", reason="Musik tauschen")
check(r.status_code == 409, f"a decision about the older version: 409 ({r.status_code})")
r = ppost("/s/q/" + TOK, f=fk2[1], v=vk2[0], do="decline", name="Erika Beispiel", reason="Musik tauschen")
check(r.status_code == 303, f"Request changes {r.status_code}")
R = A.get(B + f"{V}/{CV}").json()
check(R["state"] == "changes" and any(x["customer"] and x["body"] == "Changes requested: Musik tauschen" for x in R["comments"])
      and R["signoffs"][0]["state"] == "declined" and R["signoffs"][0]["signer_name"] == "Erika Beispiel", f"the review's state + the decision as a comment line {R.get('state')} {[(x['customer'], x['body']) for x in R.get('comments', [])][-3:]} {R.get('signoffs', [{}])[:1]}")
pg = anon("/s/q/" + TOK)
check(pg.status_code == 200 and "Changes requested" in pg.text and 'name="text"' not in pg.text and "frame-src" not in pg.headers.get("Content-Security-Policy", ""),
      f"after the decision: the confirmation only (no form, the strict CSP) {pg.status_code} {pg.headers.get('Content-Security-Policy', '')[:120]} {'name=\"text\"' in pg.text} {'Changes requested' in pg.text}")
check(ppost(f"/s/q/{TOK}/comments", f=CF, v=vk2[0], name="Erika", text="noch was").status_code == 303
      and len(sql("SELECT 1 FROM video_comments WHERE review_id=? AND body='noch was'", (CV,))) == 0, "no comments after the decision")
enc = sql("SELECT signer_name FROM office_signoffs WHERE id=?", (S1["id"],))[0][0]
check(enc.startswith("kenc1:"), "the signer's name encrypted at rest")
r = A.post(B + f"{V}/{CV}/signoff", json={})
S2 = r.json()
T2K = S2["url"].split("/s/q/")[1]
r = A.post(B + f"{V}/{CV}/signoff", json={})
S3 = r.json()
T3K = S3["url"].split("/s/q/")[1]
check(anon("/s/q/" + T2K).text == UNKNOWN.text and anon("/s/q/" + T2K).status_code == 404, "a new link stops the older open one (same answer as unknown)")
pg = anon("/s/q/" + T3K)
fk3, vk3 = keys(pg.text)
r = ppost("/s/q/" + T3K, f=fk3[1], v=vk3[0], do="accept", name="Erika Beispiel", ok="1")
check(r.status_code == 303 and A.get(B + f"{V}/{CV}").json()["state"] == "approved", "Approve -> approved")
S4 = A.post(B + f"{V}/{LV}/signoff", json={}).json()
T4K = S4["url"].split("/s/q/")[1]
check(Ca.post(B + f"{V}/{LV}/signoffs/{S4['id']}/revoke").status_code == 404, "another organisation cannot stop the link")
check(A.post(B + f"{V}/{LV}/signoffs/{S4['id']}/revoke").ok and anon("/s/q/" + T4K).text == UNKNOWN.text, "revoked: the same answer as unknown")
S5 = A.post(B + f"{V}/{LV}/signoff", json={}).json()
T5K = S5["url"].split("/s/q/")[1]
pg = anon("/s/q/" + T5K)
check(pg.status_code == 200 and '<video src="https://example.com/film.webm"' in pg.text, "a direct file: <video>")
check(A.delete(B + f"{V}/{LV}").ok and anon("/s/q/" + T5K).text == UNKNOWN.text and A.get(B + f"{V}/{LV}").status_code == 404,
      "deleted: the link is gone, the review in the trash")
check(A.post(B + f"{V}/{LV}/restore").ok and A.get(B + f"{V}/{LV}").ok and anon("/s/q/" + T5K).text == UNKNOWN.text,
      "restored (undo); the stopped link stays stopped")
check(Ca.post(B + f"{V}/{LV}/restore").status_code == 404, "another organisation cannot restore")
# the limit per address
S6 = A.post(B + f"{V}/{VID}/signoff", json={}).json()
T6K = S6["url"].split("/s/q/")[1]
pg = anon("/s/q/" + T6K)
fk6, vk6 = keys(pg.text)
check("Schnitt hier zu hart" not in pg.text and "no time control" in pg.text and 'name="at"' not in pg.text,
      f"internal comments stay internal; a link without time control: the hint, no timecode field {'Schnitt hier zu hart' in pg.text} {'no time control' in pg.text} {'name=\"at\"' in pg.text}")
codes = [ppost(f"/s/q/{T6K}/comments", f=fk6[0], v=vk6[0], name="Erika", text=f"Nr {i}").status_code for i in range(12)]
check(429 in codes, f"customer comments are limited per address {codes}")

# ---------------------------------------------------------------- the app page's CSP
h = requests.get(B + "/").headers.get("Content-Security-Policy", "")
check("frame-src 'self' https://player.vimeo.com https://www.youtube-nocookie.com" in h and "media-src 'self' https:" in h and "script-src 'self';" in h,
      f"the app's CSP: the two players, media over https, no foreign script {h}")

# ---------------------------------------------------------------- to the other workspace and back
r = A.post(B + f"{V}/{VID}/move-space", json={"to": "private", "dry": 1})
check(r.ok and r.json()["block"] and any("no longer attached to its task" in n for n in r.json()["notes"]), f"dry run without a place: blocked {r.text[:300]}")
r = A.post(B + f"{V}/{VID}/move-space", json={"to": "private", "place": L2, "dry": 1})
check(r.status_code == 404, "a place in another workspace: 404")
r = A.post(B + f"{V}/{VID}/move-space", json={"to": "private", "place": LP, "dry": 1})
check(r.ok and not r.json()["block"] and any("customer link stops" in n for n in r.json()["notes"]), f"dry run into a private project {r.text[:300]}")
check(A.post(B + f"{V}/{VID}/move-space", json={"to": f"org:{ORG2}", "place": LP}).status_code == 409, "an organisation Alice is not in: 409")
r = A.post(B + f"{V}/{VID}/move-space", json={"to": "private", "place": LP})
MID = r.json().get("move_id") if r.ok else 0
row = sql("SELECT org_id, owner_id, task_id, list_id FROM video_reviews WHERE id=?", (VID,))[0]
check(r.ok and r.json()["ok"] and tuple(row) == (None, ALICE, None, LP), f"moved to the private project {tuple(row)}")
check(sql("SELECT COUNT(*) FROM video_comments WHERE review_id=? AND org_id IS NOT NULL", (VID,))[0][0] == 0
      and sql("SELECT COUNT(*) FROM video_versions WHERE review_id=? AND org_id IS NOT NULL", (VID,))[0][0] == 0, "versions and comments follow")
# 2.122.4 (#2215 L3): the records keep video_id (were emptied) and stay out of the private review's list
check(sql("SELECT COUNT(*) FROM office_signoffs WHERE video_id=? AND org_id IS NULL", (VID,))[0][0] == 0
      and sql("SELECT COUNT(*) FROM office_signoffs WHERE video_id=?", (VID,))[0][0] >= 1
      and A.get(B + f"{V}/{VID}").json()["signoffs"] == [] and anon("/s/q/" + T6K).text == UNKNOWN.text,
      "the customer links stay in the old workspace (the open one stopped)")
check(Bo.get(B + f"{V}/{VID}").status_code == 404 and A.get(B + f"{V}?list_id={LP}").json()["reviews"][0]["id"] == VID, "now private: Bob no longer sees it")
r = A.post(B + f"{V}/{VID}/move-space", json={"to": f"org:{ORG}", "undo": MID})
row = sql("SELECT org_id, owner_id, task_id, list_id FROM video_reviews WHERE id=?", (VID,))[0]
check(r.ok and tuple(row) == (ORG, None, T, None) and r.json()["revived"] >= 1, f"undo: back at the task, the links again {tuple(row)} {r.text[:200]}")

# ---------------------------------------------------------------- a person without an organisation
FL = Fr.post(B + "/api/lists", json={"name": "Meine Filme"}).json()["id"]
FT = Fr.post(B + "/api/tasks", json={"title": "Showreel", "list_id": FL}).json()["id"]
r = Fr.post(B + "/api/clients", json={"name": "Beispielkunde AG"})
FC = r.json()["id"]
r = Fr.post(B + V, json={"task_id": FT, "url": "https://vimeo.com/55555555", "title": "Showreel"})
check(r.ok and r.json()["org_id"] is None, f"freelancer: a review at a private task {r.status_code} {r.text[:200]}")
FV = r.json()["id"]
check(Fr.post(B + V, json={"client_id": FC, "url": "https://youtu.be/AbCdEfGhI_9"}).ok and Fr.post(B + V, json={"list_id": FL, "url": "https://example.com/a.mp4"}).ok,
      "freelancer: at a private client and a private list")
check(Fr.post(B + f"{V}/{FV}/comments", json={"at_sec": 10, "body": "Farbe"}).ok and Fr.post(B + f"{V}/{FV}/versions", json={"url": "https://vimeo.com/55555556"}).ok,
      "freelancer: comments and versions")
check(Fr.get(B + f"{V}?task_id={FT}").json()["reviews"][0]["version"] == 2 and Fr.get(B + f"{V}/{FV}/export").ok, "freelancer: list and export")
r = Fr.post(B + f"{V}/{FV}/signoff", json={})
check(r.ok and anon("/s/q/" + r.json()["url"].split("/s/q/")[1]).status_code == 200, "freelancer: the customer link works")
check(Fr.post(B + f"{V}/{FV}/move-space", json={"to": f"org:{ORG}", "dry": 1}).status_code == 409, "freelancer: no organisation to move to")
check(A.get(B + f"{V}/{FV}").status_code == 404 and Ca.get(B + f"{V}/{FV}").status_code == 404, "a private review: nobody else sees it")
check(Fr.delete(B + f"{V}/{FV}").ok and Fr.post(B + f"{V}/{FV}/restore").ok and Fr.patch(B + f"{V}/{FV}", json={"state": "approved"}).json()["state"] == "approved",
      "freelancer: delete, restore, state")
check(Fr.patch(B + f"{V}/{FV}", json={"state": "lost"}).status_code == 400, "an unknown state: 400")

if FAILS:
    app_log()
print(f"p2991_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
