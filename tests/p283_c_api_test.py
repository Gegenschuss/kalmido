#!/usr/bin/env python3
"""2.83.0 API tests, part C (#1427): the header strip of a list and of an owner's folder. Invented names only.
 - PUT /api/lists/{id}/header {style}: owner and list admins; a member who edits, a reader 403; someone who cannot see
   the list 404; an unknown style 400; 'image' without a picture 400; agents 403 (the strip is a setting of the app)
 - POST /api/lists/{id}/header (multipart file): JPEG / PNG / WebP by content (a GIF, a text named .png: 400), at most 2 MB
   (413); stored re-encoded as JPEG (no metadata), served at /api/list-header/{id}/{token}.jpg to everybody who sees the
   list (a reader too), 404 for others, for a wrong token and for the token of a replaced picture
 - the list in the state carries header_style / header_file; a list of another organisation stays unreadable
 - GET / PUT /api/folder-heads: per person, only gradient | dots | lines | grid ('' removes), another person sees nothing
usage: p283_c_api_test.py <datadir>      (a fresh container; P283C_NOSTART=1 = the server already runs)"""
import os
import struct
import subprocess
import sys
import zlib

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
FAILS, OKS = [], [0]


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def png(w=40, h=10, rgb=(120, 80, 200)):
    """A small PNG built by hand (no Pillow needed on the test machine)."""
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


GIF = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"

if not os.environ.get("P283C_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carol", "erin", "dave"):
    r = A.post(B + "/api/users", json={"orgs": [ORG] if u != "dave" else [], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["dave"]})
assert r.status_code in (200, 201), r.text
BETA = r.json()["id"]
Bo, Ca, Er, Da = sess("bob"), sess("carol"), sess("erin"), sess("dave")
W = A.post(B + "/api/lists", json={"name": "Garden", "org_id": ORG}).json()["id"]
check(A.put(B + f"/api/lists/{W}/members", json={"user_id": uid["bob"], "role": "edit"}).ok, "setup: bob edits the list")
check(A.put(B + f"/api/lists/{W}/members", json={"user_id": uid["carol"], "role": "view"}).ok, "setup: carol reads the list")
check(A.put(B + f"/api/lists/{W}/members", json={"user_id": uid["erin"], "role": "admin"}).ok, "setup: erin is a list admin")
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write"], "username": "helper", "display_name": "Helper"})
AGH = {"Authorization": "Bearer " + r.json()["token"]}
A.put(B + f"/api/lists/{W}/members", json={"user_id": r.json()["id"], "role": "admin"})


def lst(s, lid):
    return next((x for x in s.get(B + "/api/state").json()["lists"] if x["id"] == lid), None)


# ---- the style
check(lst(A, W)["header_style"] == "" and lst(A, W)["header_file"] == "", "a new list has no header strip")
r = A.put(B + f"/api/lists/{W}/header", json={"style": "dots"})
check(r.ok and r.json()["header_style"] == "dots", "owner sets the dots " + r.text[:200])
check(lst(Ca, W)["header_style"] == "dots", "a reader sees the same strip (it belongs to the list)")
r = Er.put(B + f"/api/lists/{W}/header", json={"style": "gradient"})
check(r.ok and lst(A, W)["header_style"] == "gradient", "a list admin sets the gradient " + r.text[:200])
check(Bo.put(B + f"/api/lists/{W}/header", json={"style": "grid"}).status_code == 403, "a member who edits: 403")
check(Ca.put(B + f"/api/lists/{W}/header", json={"style": "grid"}).status_code == 403, "a reader: 403")
check(Da.put(B + f"/api/lists/{W}/header", json={"style": "grid"}).status_code == 404, "someone who cannot see the list: 404")
check(A.put(B + f"/api/lists/{W}/header", json={"style": "neon"}).status_code == 400, "an unknown style: 400")
check(A.put(B + f"/api/lists/{W}/header", json={"style": "image"}).status_code == 400, "'image' without a picture: 400")
r = requests.put(B + f"/api/lists/{W}/header", json={"style": "lines"}, headers={**H, **AGH})
check(r.status_code in (401, 403), f"an agent token: refused ({r.status_code})")
check(lst(A, W)["header_style"] == "gradient", "the refused writes changed nothing")

# ---- the own picture
up = lambda s, data, name="head.png", mime="image/png": s.post(B + f"/api/lists/{W}/header", files={"file": (name, data, mime)})
check(up(A, GIF, "head.gif", "image/gif").status_code == 400, "a GIF: 400")
check(up(A, b"not a picture at all", "head.png").status_code == 400, "text named .png: 400 (the content decides)")
check(up(A, os.urandom(2 * 1024 * 1024 + 10), "big.png").status_code == 413, "more than 2 MB: 413")
check(up(Bo, png()).status_code == 403 and up(Ca, png()).status_code == 403, "upload: an editing member / a reader 403")
check(up(Da, png()).status_code == 404, "upload: someone who cannot see the list 404")
r = up(A, png())
check(r.ok and r.json()["header_style"] == "image" and len(r.json()["header_file"]) >= 8, "owner uploads a PNG " + r.text[:200])
TOK = r.json().get("header_file", "x")
url = B + f"/api/list-header/{W}/{TOK}.jpg"
r = A.get(url)
check(r.ok and r.headers.get("Content-Type", "").startswith("image/jpeg") and r.content[:2] == b"\xff\xd8", "served as a JPEG (re-encoded)")
check("immutable" in r.headers.get("Cache-Control", "") and "no-store" not in r.headers.get("Cache-Control", ""), "cached for good (new picture = new URL)")
check(Ca.get(url).ok and Bo.get(url).ok, "a reader and a member see the picture")
check(Da.get(url).status_code == 404, "someone who cannot see the list: 404")
check(requests.get(url).status_code in (401, 403, 404), "without login: no picture")
check(A.get(B + f"/api/list-header/{W}/AAAAAAAAAAAAAAAA.jpg").status_code == 404, "a wrong token: 404")
check(lst(Ca, W)["header_file"] == TOK, "the state carries the token")
r = up(Er, png(rgb=(10, 160, 90)))
check(r.ok and r.json()["header_file"] != TOK, "a list admin replaces the picture")
check(A.get(url).status_code == 404, "the replaced picture is gone (404)")
check(A.put(B + f"/api/lists/{W}/header", json={"style": ""}).ok and lst(A, W)["header_style"] == "" and lst(A, W)["header_file"], "no strip: the picture stays stored (undo brings it back)")
check(A.put(B + f"/api/lists/{W}/header", json={"style": "image"}).ok, "'image' again with the stored picture")

# ---- another organisation: its list and its picture stay out of reach
DL = Da.post(B + "/api/lists", json={"name": "Beta plans", "org_id": BETA}).json()["id"]
r = Da.post(B + f"/api/lists/{DL}/header", files={"file": ("p.png", png(), "image/png")})
check(r.ok, "the other organisation's owner uploads " + r.text[:200])
DT = r.json().get("header_file", "x")
check(Bo.get(B + f"/api/list-header/{DL}/{DT}.jpg").status_code == 404, "a person of Alpha: the Beta list's picture 404")
check(Bo.put(B + f"/api/lists/{DL}/header", json={"style": "dots"}).status_code == 404, "a person of Alpha: the Beta list's strip 404")
check(lst(Bo, DL) is None, "the Beta list is not in the Alpha person's state")

# ---- folders: per person, style only
r = A.put(B + "/api/folder-heads", json={"folder": "Home", "style": "lines"})
check(r.ok and r.json()["heads"] == {"Home": "lines"}, "a folder's strip " + r.text[:200])
check(A.put(B + "/api/folder-heads", json={"folder": "Home", "style": "image"}).status_code == 400, "a folder has no picture: 400")
check(A.put(B + "/api/folder-heads", json={"folder": "", "style": "dots"}).status_code == 400, "no folder: 400")
check(Bo.get(B + "/api/folder-heads").json()["heads"] == {}, "another person does not see my folder strips")
check(A.put(B + "/api/folder-heads", json={"folder": "Home", "style": ""}).json()["heads"] == {}, "'' removes it")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
