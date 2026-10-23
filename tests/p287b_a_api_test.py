#!/usr/bin/env python3
"""2.87.9 API tests, part A (#1913): an organisation's own picture as its symbol (like a profile picture / a list icon).
Invented names only.
 - an admin of the organisation (not an admin of the server) uploads a picture: icon = "" (no emoji any more), icon_url in
   GET /api/orgs and in the state's workspaces; the picture is re-encoded (PNG), sealed on disk with the organisation's key
   and served decrypted to its members
 - members, people of another organisation, a person without an organisation, agents: no upload / removal (403 / 404);
   only members get the picture, a wrong or old token 404; not a picture 400
 - an emoji set later replaces the picture (the file goes); an empty symbol from an older dialog keeps it; removing it
   leaves the symbol empty; deleting the organisation drops the file
usage: p287b_a_api_test.py <datadir>      (a fresh container with KALMIDO_SECRET_KEY; KMT_NOSTART=1 = the server already runs)"""
import base64
import os
import struct
import subprocess
import sys
import zlib

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import freelancer, login  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
from kt import FAILS, OKS, check  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def dbx(sql, args=()):
    return dbxm.connect(DATA).execute(sql, args).fetchall()


def png(w=8, h=8):
    """A tiny valid PNG (red square), no image library needed."""
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def icon_file(oid):
    v = dbx("SELECT icon FROM orgs WHERE id=?", (oid,))[0][0] or ""
    return os.path.join(DATA, "attachments", "listicons", f"o{oid}-{v[2:]}.png"), v


def head(p):
    with open(p, "rb") as f:
        return f.read(6)


def up(s, oid, data=None):
    return s.post(B + f"/api/orgs/{oid}/icon", files={"file": ("icon.png", data if data is not None else png(), "image/png")})


if not os.environ.get("KMT_NOSTART"):
    env = dict(os.environ, EXTRA=(os.environ.get("EXTRA", "") + " -e KALMIDO_SECRET_KEY=" + KEY).strip())
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL, env=env)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = login(B, "alice")
A.post(B + "/api/admin/setup", json={"org_name": "Nordwind", "lang": "en", "collab_all": True, "modules": ["comments"]})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u, orgs in (("bob", [ORG]), ("carol", [ORG]), ("dave", [])):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123",
                                       "email": f"{u}@example.com", "orgs": orgs})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
check(A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": uid["bob"], "role": "admin"}).ok, "setup: bob administers the organisation")
r = A.post(B + "/api/admin/orgs", json={"name": "Suedwind", "admin_id": uid["dave"]})
assert r.status_code in (200, 201), r.text
ORG2 = r.json()["id"]
Bo, Ca, Da = login(B, "bob"), login(B, "carol"), login(B, "dave")
FID, Fr = freelancer(B, A)
r = A.post(B + "/api/admin/agents", json={"scopes": ["read"], "username": "nordbot", "display_name": "Nordbot"})
assert r.ok, r.text
AG = {"Authorization": "Bearer " + r.json()["token"], **H}
A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": r.json()["id"], "role": "member"})

# ================================================================== #1913 an own picture as the organisation's symbol
# tenant-matrix: org
A.patch(B + f"/api/admin/orgs/{ORG}", json={"icon": "⛵"})
r = up(Bo, ORG)
check(r.ok, f"#1913: an admin of the organisation uploads a picture {r.status_code} {r.text[:160]}")
j = r.json() if r.ok else {}
check(j.get("icon") == "" and (j.get("icon_url") or "").startswith(f"/api/org-icon/{ORG}/"), f"#1913: the symbol is the picture, no emoji {j.get('icon')!r} {j.get('icon_url')!r}")
URL = j.get("icon_url") or "/api/org-icon/0/x.png"
p1, v1 = icon_file(ORG)
check(v1.startswith("u:") and os.path.isfile(p1), "#1913: stored as u:<token> next to the list icons")
check(os.path.isfile(p1) and head(p1) == b"KENC1\n", "#1913: sealed on disk with the organisation's key")
ws = Ca.get(B + "/api/state").json()["me"]["workspaces"]
check(any(w["id"] == ORG and w.get("icon_url") == URL and w.get("icon") == "" for w in ws), "#1913: the workspaces in the state carry the picture")
check(any(o["id"] == ORG and o.get("icon_url") == URL for o in Ca.get(B + "/api/orgs").json()["orgs"]), "#1913: Settings > Workspaces carries it")
r = Ca.get(B + URL)
check(r.status_code == 200 and r.headers.get("Content-Type", "").startswith("image/png") and r.content[:8] == b"\x89PNG\r\n\x1a\n",
      f"#1913: a member gets the picture, decrypted {r.status_code}")
check(Bo.get(B + URL).status_code == 200, "#1913: the admin gets it")
# outsiders: nothing
check(Da.get(B + URL).status_code == 404, "#1913: an admin of another organisation: 404")
check(Fr.get(B + URL).status_code == 404, "#1913: a person without an organisation: 404")
check(A.get(B + URL).status_code == 200, "#1913: alice is a member (the first admin) and gets it")
check(requests.get(B + URL, headers=H).status_code in (401, 404), "#1913: without a login: no picture")
check(Ca.get(B + f"/api/org-icon/{ORG}/{'A' * 16}.png").status_code == 404, "#1913: a wrong token: 404")
check(Ca.get(B + f"/api/org-icon/{ORG2}/{v1[2:]}.png").status_code == 404, "#1913: the token under another organisation: 404")
adm = {o["id"]: o for o in A.get(B + "/api/admin/orgs").json()["orgs"]}
check(adm[ORG].get("icon_url") == URL and adm[ORG2].get("icon_url") == "", "#1913: the server's organisation list: the picture only for a member")
# who may change it
check(up(Ca, ORG).status_code == 403 and Ca.delete(B + f"/api/orgs/{ORG}/icon").status_code == 403, "#1913: a member cannot change it (403)")
check(up(Da, ORG).status_code == 404 and Da.delete(B + f"/api/orgs/{ORG}/icon").status_code == 404, "#1913: another organisation's admin: 404")
check(up(Fr, ORG).status_code == 404, "#1913: a person without an organisation: 404")
check(requests.post(B + f"/api/orgs/{ORG}/icon", headers=AG, files={"file": ("i.png", png(), "image/png")}).status_code in (401, 403),
      "#1913: an agent cannot change it")
check(icon_file(ORG)[1] == v1, "#1913: the refused attempts changed nothing")
check(up(Bo, ORG, b"<svg xmlns='http://www.w3.org/2000/svg'/>").status_code == 400, "#1913: not a picture: 400")
check(Bo.post(B + f"/api/orgs/{ORG}/icon").status_code == 400, "#1913: no file: 400")
check(Bo.patch(B + f"/api/orgs/{ORG}", json={"icon": "u:" + "B" * 16}).ok and icon_file(ORG)[1] == v1, "#1913: a token cannot be set as an emoji")
# a new picture replaces the old one; an empty symbol of an older dialog keeps it; an emoji replaces it
r = up(Bo, ORG, png(16, 16))
p2, v2 = icon_file(ORG)
check(r.ok and v2 != v1 and os.path.isfile(p2) and not os.path.exists(p1), "#1913: a new picture: new token, the old file gone")
check(Ca.get(B + URL).status_code == 404 and Ca.get(B + r.json()["icon_url"]).status_code == 200, "#1913: the old address is gone, the new one works")
check(A.patch(B + f"/api/admin/orgs/{ORG}", json={"name": "Nordwind", "icon": ""}).ok and icon_file(ORG)[1] == v2, "#1913: an empty symbol keeps the picture")
check(Bo.patch(B + f"/api/orgs/{ORG}", json={"icon": "⚓"}).ok, "#1913: an emoji instead")
check(dbx("SELECT icon FROM orgs WHERE id=?", (ORG,))[0][0] == "⚓" and not os.path.exists(p2), "#1913: the emoji replaced the picture, the file is gone")
r = up(Bo, ORG)
p3, v3 = icon_file(ORG)
r = Bo.delete(B + f"/api/orgs/{ORG}/icon")
check(r.ok and r.json().get("icon") == "" and r.json().get("icon_url") == "" and not os.path.exists(p3), "#1913: removed: empty symbol, file gone")
# deleting an organisation drops its picture
r = up(Da, ORG2)
p4, v4 = icon_file(ORG2)
check(r.ok and os.path.isfile(p4), "#1913: the other organisation's own picture")
r = A.delete(B + f"/api/admin/orgs/{ORG2}")
check(r.ok and not os.path.exists(p4), f"#1913: deleting the organisation drops its picture {r.status_code}")

print(f"p287b_a_api: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
