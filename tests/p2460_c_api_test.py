#!/usr/bin/env python3
"""2.46.0 API tests of part C, own container (start.sh). Invented names only.
 - #1606 a changed folder role and the roles set per list: GET /api/folders/people/diff and /api/folders/groups/<gid>/diff
   name the lists of the folder where the new role would replace a role of its own (nothing for a first share or the same
   role); PUT with apply: false keeps them ("Only new lists"), without it they are replaced ("Set everywhere"); a person or
   group one may not see gets 404, another person's folder shows nothing
 - #1605 a group picture: a preset, an own photo (re-encoded JPEG without metadata, new token = new URL), removing it; only who
   may manage the group changes it; GET /api/group-avatar/<gid>/<tok>.jpg for the members / admins (an old or wrong token 404,
   not signed in 401, in the mode workspaces somebody outside 404); the backup holds the file (also profile pictures and list
   icons: attachments/avatars|listicons) and a restore brings it back; deleting the group drops it
usage: p2460_c_api_test.py <datadir>"""
import io
import os
import struct
import subprocess
import sys
import time
import zipfile
import zlib

import requests

import dbx as dbxm

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
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


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        if write:
            c.commit()
        return r
    finally:
        c.close()


def png(w=40, h=30):
    """A small RGB PNG (with a text chunk as metadata that must not survive)."""
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"".join(bytes((x * 5 % 256, y * 7 % 256, 90)) for x in range(w)) for y in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"tEXt", b"Comment\x00secret-gps-48.1") + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def restart(extra):
    e = dict(os.environ, KEEP="1", EXTRA=os.environ.get("EXTRA", "") + " " + extra)
    p = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


def own_role(lid, uid):
    r = dbx("SELECT own_role, role FROM list_members WHERE list_id=? AND user_id=?", (lid, uid))
    return tuple(r[0]) if r else None


if not os.environ.get("P2460C_RUNNING"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
BOB = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob", "password": "password123"}).json()["id"]
CAROL = A.post(B + "/api/users", json={"username": "carol", "display_name": "Carol", "password": "password123"}).json()["id"]
DAN = A.post(B + "/api/users", json={"username": "dan", "display_name": "Dan", "password": "password123"}).json()["id"]
Bo, Ca = sess("bob"), sess("carol")

# ---- #1606 people
F = "Work"
L1 = A.post(B + "/api/lists", json={"name": "Alpha", "folder": F}).json()["id"]
L2 = A.post(B + "/api/lists", json={"name": "Beta", "folder": F}).json()["id"]
L3 = A.post(B + "/api/lists", json={"name": "Gamma", "folder": F + "/Sub"}).json()["id"]
LX = A.post(B + "/api/lists", json={"name": "Outside"}).json()["id"]
D = B + "/api/folders/people/diff"
r = A.get(D, params={"folder": F, "user_id": BOB, "role": "view"})
check(r.ok and r.json()["lists"] == [], f"not shared yet: nothing to ask {r.status_code} {r.text[:200]}")
check(A.put(B + "/api/folders/people", json={"folder": F, "user_id": BOB, "role": "edit"}).ok, "share the folder with Bob (edit)")
check(own_role(L1, BOB) == ("edit", "edit") and own_role(L3, BOB) == ("edit", "edit"), f"Bob in the lists: {own_role(L1, BOB)}")
assert A.put(B + f"/api/lists/{L2}/members", json={"user_id": BOB, "role": "admin"}).ok  # a role set in one list by hand
assert A.put(B + f"/api/lists/{LX}/members", json={"user_id": BOB, "role": "view"}).ok  # outside the folder
check(own_role(L2, BOB)[0] == "admin", f"Beta: Bob is admin by hand {own_role(L2, BOB)}")
r = A.get(D, params={"folder": F, "user_id": BOB, "role": "edit"})
check(r.ok and r.json()["lists"] == [], f"same role: nothing to ask {r.text[:200]}")
r = A.get(D, params={"folder": F, "user_id": BOB, "role": "view"})
j = r.json()["lists"] if r.ok else None
check(j == [{"list_id": L2, "name": "Beta", "role": "admin"}], f"view: only Beta has a role of its own {r.status_code} {r.text[:300]}")
r = A.get(D, params={"folder": F, "user_id": BOB, "role": "admin"})
check(r.ok and r.json()["lists"] == [], f"admin = the role in Beta already: nothing to ask {r.text[:200]}")
check(A.get(D, params={"folder": F, "user_id": BOB, "role": "boss"}).status_code == 400, "bad role 400")
check(A.get(D, params={"folder": "", "user_id": BOB, "role": "view"}).status_code == 400, "no folder 400")
check(A.get(D, params={"folder": F, "user_id": 99999, "role": "view"}).status_code == 404, "unknown person 404")
check(A.get(D, params={"folder": F, "user_id": dbx("SELECT id FROM users WHERE username='alice'")[0][0], "role": "view"}).status_code == 404, "oneself 404")
r = Ca.get(D, params={"folder": F, "user_id": BOB, "role": "view"})
check(r.ok and r.json()["lists"] == [], f"another person sees nothing of Alice's folder {r.status_code} {r.text[:200]}")
r = requests.get(D, params={"folder": F, "user_id": BOB, "role": "view"}, headers=H)
check(r.status_code == 401, f"not signed in 401: {r.status_code}")

# "Only new lists": the folder role changes, the lists keep their roles
r = A.put(B + "/api/folders/people", json={"folder": F, "user_id": BOB, "role": "view", "apply": False})
check(r.ok and r.json()["updated"] == 0, f"apply false: no list changed {r.text[:200]}")
check(own_role(L2, BOB)[0] == "admin" and own_role(L1, BOB)[0] == "edit", f"lists keep their roles {own_role(L1, BOB)} {own_role(L2, BOB)}")
check(dbx("SELECT role FROM folder_people WHERE user_id=?", (BOB,))[0][0] == "view", "the folder role is view")
L4 = A.post(B + "/api/lists", json={"name": "Delta", "folder": F}).json()["id"]
check(own_role(L4, BOB) == ("view", "view"), f"a new list gets the new folder role {own_role(L4, BOB)}")
check(own_role(LX, BOB)[0] == "view", "a list outside the folder is untouched")
# now Alpha, Gamma (edit) and Beta (admin) differ from the folder role view
r = A.get(D, params={"folder": F, "user_id": BOB, "role": "participant"})
check(r.ok and [x["list_id"] for x in r.json()["lists"]] == [L1, L2, L3], f"participant: Alpha, Beta and Gamma (subfolder) are named {r.text[:300]}")
# "Set everywhere"
r = A.put(B + "/api/folders/people", json={"folder": F, "user_id": BOB, "role": "participant"})
check(r.ok and r.json()["updated"] == 4, f"set everywhere: 4 lists changed {r.text[:200]}")
check(all(own_role(x, BOB)[0] == "participant" for x in (L1, L2, L3, L4)), "every list of the folder has the new role")
check(own_role(LX, BOB)[0] == "view", "still not the list outside the folder")

# ---- #1606 groups
G = A.post(B + "/api/admin/groups", json={"name": "Team", "members": [CAROL]}).json()["id"]
G2 = A.post(B + "/api/admin/groups", json={"name": "Other", "members": [DAN]}).json()["id"]
GD = B + f"/api/folders/groups/{G}/diff"
r = A.get(GD, params={"folder": F, "role": "view"})
check(r.ok and r.json()["lists"] == [], f"group not in the folder: nothing to ask {r.text[:200]}")
assert A.put(B + f"/api/lists/{L1}/groups/{G}", json={"role": "admin"}).ok  # the group's own role in Alpha
assert A.put(B + f"/api/folders/groups/{G}", json={"folder": F, "role": "edit"}).ok
r = A.get(GD, params={"folder": F, "role": "edit"})
check(r.ok and r.json()["lists"] == [], "same group role: nothing to ask")
r = A.get(GD, params={"folder": F, "role": "view"})
check(r.ok and r.json()["lists"] == [{"list_id": L1, "name": "Alpha", "role": "admin"}], f"group: Alpha has its own role {r.text[:300]}")
check(A.get(GD, params={"folder": "", "role": "view"}).status_code == 400, "group diff without folder 400")
check(A.get(B + "/api/folders/groups/99999/diff", params={"folder": F, "role": "view"}).status_code == 404, "unknown group 404")
check(requests.get(GD, params={"folder": F, "role": "view"}, headers=H).status_code == 401, "group diff not signed in 401")
r = Bo.get(GD, params={"folder": F, "role": "view"})
check(r.status_code in (200, 404) and (r.status_code == 404 or r.json()["lists"] == []), f"another person: nothing of Alice's folder {r.text[:200]}")
r = A.put(B + f"/api/folders/groups/{G}", json={"folder": F, "role": "view", "apply": False})
check(r.ok, "group: only new lists")
check(dbx("SELECT role FROM group_shares WHERE list_id=? AND group_id=?", (L1, G))[0][0] == "admin", "Alpha keeps the group's own role")
check(own_role(L1, CAROL)[1] == "admin" and own_role(L2, CAROL)[1] == "view", f"Carol: admin in Alpha, view in Beta {own_role(L1, CAROL)} {own_role(L2, CAROL)}")
r = A.put(B + f"/api/folders/groups/{G}", json={"folder": F, "role": "participant"})
check(r.ok, "group: set everywhere")
check(dbx("SELECT role FROM group_shares WHERE list_id=? AND group_id=?", (L1, G))[0][0] == "participant", "Alpha: the group's own role replaced")
check(own_role(L1, CAROL)[1] == "participant", f"Carol: participant in Alpha {own_role(L1, CAROL)}")
check(dbx("SELECT COUNT(*) FROM group_shares WHERE group_id=?", (G2,))[0][0] == 0, "another group untouched")

# ---- #1605 group pictures
GA = B + f"/api/admin/groups/{G}/avatar"
g_of = lambda s, gid: next((x for x in s.get(B + "/api/groups").json()["groups"] if x["id"] == gid), {})
check(g_of(A, G).get("avatar") == "", f"no picture yet: {g_of(A, G).get('avatar')!r}")
r = A.put(GA, json={"preset": "coffee"})
check(r.ok and r.json()["avatar"] == "/static/avatars/coffee.svg", f"preset: {r.text[:200]}")
check(g_of(Ca, G).get("avatar") == "/static/avatars/coffee.svg", "a member sees the preset in GET /api/groups")
check(A.put(GA, json={"preset": "nope"}).status_code == 400, "unknown preset 400")
check(Ca.put(GA, json={"preset": "plant"}).status_code == 403, "a member who may not manage groups: 403")
check(Ca.post(GA, files={"file": ("a.png", png(), "image/png")}).status_code == 403, "... no upload either")
check(Ca.delete(GA).status_code == 403, "... nor remove it")
check(A.put(B + "/api/admin/groups/99999/avatar", json={"preset": "plant"}).status_code == 404, "unknown group 404")
check(A.post(GA, files={"file": ("a.txt", b"no picture", "text/plain")}).status_code == 400, "not a picture: 400")
r = A.post(GA, files={"file": ("a.png", png(), "image/png")})
check(r.ok and r.json()["avatar"].startswith(f"/api/group-avatar/{G}/") and r.json()["avatar"].endswith(".jpg"), f"upload: {r.text[:200]}")
URL1 = r.json()["avatar"] if r.ok else ""
tok1 = URL1.rsplit("/", 1)[-1][:-4]
r = Ca.get(B + URL1)
check(r.ok and r.headers.get("Content-Type", "").startswith("image/jpeg") and r.content[:2] == b"\xff\xd8", f"a member gets the photo: {r.status_code}")
check(b"secret-gps" not in r.content and b"Comment" not in r.content, "no metadata of the upload survives")
check("immutable" in r.headers.get("Cache-Control", ""), f"cached for good: {r.headers.get('Cache-Control')}")
check(A.get(B + URL1).ok, "the admin gets it")
check(requests.get(B + URL1, headers=H).status_code == 401, "not signed in: 401")
check(A.get(B + f"/api/group-avatar/{G}/AAAAAAAAAAAA.jpg").status_code == 404, "a wrong token: 404")
check(A.get(B + f"/api/group-avatar/{G2}/{tok1}.jpg").status_code == 404, "the token of another group: 404")
check(g_of(Bo, G).get("avatar") == URL1, "the share dialog of another person shows it (GET /api/groups)")
r = A.get(B + "/api/state").json()
check(next((x for x in r["groups"] if x["id"] == G), {}).get("avatar") == URL1, "in /api/state groups")

# the backup holds the file
n0 = len(A.get(B + "/api/admin/backups").json()["items"])
r = A.post(B + "/api/admin/backups")
check(r.status_code == 202, f"back up now: {r.status_code} {r.text[:120]}")
t0, j = time.time(), {}
while time.time() - t0 < 60:
    j = A.get(B + "/api/admin/backups").json()
    if not j["running"] and (len(j["items"]) > n0 or j["last_error"]):
        break
    time.sleep(0.4)
check(len(j.get("items", [])) > n0 and not j.get("last_error"), f"backup done: {j.get('last_error')}")
if j.get("items"):
    z = A.get(B + f"/api/admin/backups/{j['items'][0]['name']}/download")
    try:
        names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    except zipfile.BadZipFile:
        names = []
    check(any(n.endswith(f"avatars/g{G}-{tok1}.jpg") for n in names), f"the backup holds the group picture: {[n for n in names if 'avatars' in n]}")

# a new picture = a new URL, the old one is gone; removing it
r = A.put(GA, json={"preset": "plant"})
check(r.ok and A.get(B + URL1).status_code == 404, "after a change the old photo URL is 404")
check(not dbx("SELECT 1 FROM groups WHERE id=? AND avatar LIKE 'u:%'", (G,)), "the photo is no longer the group's")
r = A.post(GA, files={"file": ("a.png", png(64, 64), "image/png")})
URL2 = r.json().get("avatar", "") if r.ok else ""
check(URL2 and URL2 != URL1, "a second photo has a new URL")
r = A.delete(GA)
check(r.ok and r.json()["avatar"] == "" and g_of(A, G).get("avatar") == "", "removed: the group symbol again")
check(A.get(B + URL2).status_code == 404, "the removed photo is 404")
r = A.post(B + f"/api/admin/groups/{G2}/avatar", files={"file": ("a.png", png(), "image/png")})
URL3 = r.json().get("avatar", "") if r.ok else ""
tok3 = URL3.rsplit("/", 1)[-1][:-4]
check(A.delete(B + f"/api/admin/groups/{G2}").ok, "delete the group Other")
check(A.get(B + URL3).status_code == 404, "a deleted group's photo is gone")
p3 = os.path.join(DATA, "attachments", "avatars", f"g{G2}-{tok3}.jpg")
check(not os.path.exists(p3), "... and its file")

# a restore of that backup brings the photo back (the file too, not only the database row)
BKN = j["items"][0]["name"] if j.get("items") else ""
r = A.post(B + "/api/admin/backups/restore", json={"name": BKN, "confirm": "RESTORE"})
check(r.ok and r.json().get("ok"), f"restored: {r.text[:200]}")
time.sleep(1.0)
A, Ca = sess("alice"), sess("carol")
check(g_of(A, G).get("avatar") == URL1, f"after the restore the group has the first photo again: {g_of(A, G).get('avatar')}")
r = Ca.get(B + URL1)
check(r.ok and r.content[:2] == b"\xff\xd8", f"... and it is served (the file came back): {r.status_code}")

# mode workspaces: somebody outside the group's organisation does not get the picture
if not os.environ.get("P2460C_RUNNING"):
    r = A.post(GA, files={"file": ("a.png", png(), "image/png")})
    URL4 = r.json().get("avatar", "") if r.ok else ""
    restart("-e KALMIDO_INSTANCE_MODE=workspaces")
    A, Bo, Ca = sess("alice"), sess("bob"), sess("carol")
    EVE = A.post(B + "/api/users", json={"username": "eve", "display_name": "Eve", "password": "password123"}).json()["id"]
    dbx("DELETE FROM org_members WHERE user_id=?", (EVE,), write=True)
    Ev = sess("eve")
    check(Ca.get(B + URL4).ok, "workspaces: a member gets the picture")
    check(A.get(B + URL4).ok, "workspaces: the group's creator gets it")
    r = Ev.get(B + URL4)
    check(r.status_code in (403, 404), f"workspaces: a person outside the organisation does not: {r.status_code}")
    check(Ev.put(GA, json={"preset": "plant"}).status_code in (403, 404), "workspaces: nor change it")

print(f"p2460_c_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
