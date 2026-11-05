#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.558.0 API tests (#4693: the file store shows who a node is shared with), own container (start.sh). Invented names only.
 - GET /api/files?parent=<folder>: the open folder (node.share_with) and every row carry the names of the live shares
   for the owner, the shares of the folders above included (inherited); people / groups as k u|g, agents as k a, the whole
   organisation as k o; a share with an end date in the past is not named
 - the top of the own space: the rows' own shares; a folder without any share = [] ("Only you")
 - a receiver (shared space, the shared folder itself, a row inside) gets NO share_with: no names of other people's
   shares; it still has the owner's name for "Shared by <name>"
 - the scan's answer (POST /api/files/scan) carries share_with of the new file for its owner
 - the names come in ONE bundled read per listing (fs_share_with), not one query per row (the code path, not timed)
 - 2.558.0 D (#4693, review F4): in an organisation the org admin (not the folder's maker) gets the names; a member, a
   read-only person, a guest with a share and an agent with a share get none
 - a person without an organisation gets the same (freelancer-matrix: files)
usage: p2558_4693_share_names_test.py <datadir>"""
import io
import os
import struct
import sys
import zlib

import requests

import kt
from kt import B, check, sess
from freelancer_fixture import freelancer

kt.fresh(prefix="P2558SN")
kt.docker_logs_on_first_fail()
A = kt.setup()
A.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
ids = {}
for u, nm in (("bob", "Bob Example"), ("carol", "Carol Example"), ("dan", "Dan Example"), ("erin", "Erin Example")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": nm, "password": kt.PASSWORD})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
AG = A.post(B + "/api/admin/agents", json={"username": "helperbot", "display_name": "Helper bot"}).json()["id"]
Bob = sess("bob")
Bob.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})


def folder(s, name, parent=None):
    r = s.post(B + "/api/files/folders", json={"name": name, **({"parent_id": parent} if parent else {"space": "private"})})
    assert r.ok, r.text
    return r.json()["id"]


def up(s, name, parent):
    r = s.post(B + "/api/files/upload", data={"parent_id": str(parent)}, files={"file": (name, b"hello")})
    assert r.ok, r.text
    return r.json()["items"][0]["id"]


def share(s, nid, **kw):
    r = s.post(B + f"/api/files/nodes/{nid}/shares", json={"role": "view", **kw})
    assert r.ok, (nid, kw, r.text)
    return r.json()


def lst(s, **q):
    r = s.get(B + "/api/files", params=q)
    assert r.ok, (q, r.text)
    return r.json()


def row(j, nid):
    return next((x for x in j["items"] if x["id"] == nid), None)


def names(sw):
    return [(e["k"], e["n"]) for e in sw or []]


# ---- the owner: own + inherited, agents after people, from three on the client shortens ("Anna +2")
PROJ = folder(A, "Project")
SUB = folder(A, "Invoices", PROJ)
QUIET = folder(A, "Quiet")
FILE = up(A, "plan.txt", SUB)
share(A, PROJ, user_id=ids["bob"])
share(A, PROJ, agent_id=AG)
for u in ("carol", "dan", "erin"):
    share(A, FILE, user_id=ids[u])
top = lst(A, space="private")
check(names(row(top, PROJ).get("share_with")) == [("u", "Bob Example"), ("a", "Helper bot")], f"top: the folder's own shares {row(top, PROJ)}")
check(row(top, QUIET).get("share_with") == [], f"top: a folder without shares = [] (Only you) {row(top, QUIET)}")
j = lst(A, parent=PROJ)
check(names(j["node"].get("share_with")) == [("u", "Bob Example"), ("a", "Helper bot")], f"the open folder's head: its shares {j['node']}")
check(names(row(j, SUB).get("share_with")) == [("u", "Bob Example"), ("a", "Helper bot")], f"a subfolder: the inherited shares {row(j, SUB)}")
j2 = lst(A, parent=SUB)
check(names(j2["node"].get("share_with")) == [("u", "Bob Example"), ("a", "Helper bot")], f"the subfolder's head: inherited from above {j2['node']}")
f = names(row(j2, FILE).get("share_with"))
check(f == [("u", "Carol Example"), ("u", "Dan Example"), ("u", "Erin Example"), ("u", "Bob Example"), ("a", "Helper bot")],
      f"the file: own shares, then the inherited ones, agents last {f}")

# ---- an expired share is not named (the end date in the past, set straight in the data: the API refuses a past date)
kt.dbx("UPDATE fs_shares SET expires_at=? WHERE node_id=? AND user_id=?", ("2000-01-01T00:00:00+00:00", FILE, ids["erin"]))
f = names(row(lst(A, parent=SUB), FILE).get("share_with"))
check(("u", "Erin Example") not in f and ("u", "Dan Example") in f, f"an expired share is not named {f}")

# ---- a receiver: no names of other shares, but the owner's name
sh = lst(Bob, space="shared")
r = row(sh, PROJ)
check(r is not None and "share_with" not in r and r.get("owner") == "Alice Admin", f"Bob, Shared with me: no names, the owner's name {r}")
jb = lst(Bob, parent=PROJ)
check("share_with" not in jb["node"] and jb["node"].get("owner") == "Alice Admin", f"Bob in the folder: no names on the head {jb['node']}")
check(all("share_with" not in x for x in jb["items"]), f"Bob in the folder: no names on the rows {jb['items']}")
jb2 = lst(Bob, parent=SUB)
rb = row(jb2, FILE)
check(rb is not None and "share_with" not in rb and "Carol" not in str(jb2), f"Bob never sees the file's other receivers {rb}")
check("Carol" not in str(Bob.get(B + f"/api/files/nodes/{FILE}").json()), "the details for Bob neither (unchanged)")

# ---- the scan's answer names the new file's shares for its owner
def png():
    raw = b"\x00\xff\xff\xff" * 1
    ch = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + ch(b"IDAT", zlib.compress(raw)) + ch(b"IEND", b"")


rs = A.post(B + "/api/files/scan", data={"parent_id": str(SUB), "name": "Scan one", "bw": "0"}, files=[("page", ("p1.png", io.BytesIO(png()), "image/png"))])
check(rs.status_code == 201, f"the scan saves {rs.status_code} {rs.text[:200]}")
if rs.ok:
    it = rs.json()["items"][0]
    check(it.get("share_with") == [], f"the scan's file: its own shares (none yet; the folder's come from the open folder) {it}")

# ---- one bundled read per listing (the code: fs_share_with once in _items, no query in the loop)
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "kalmido", "files", "web.py"), encoding="utf-8").read()
body = src[src.index("def _items("):src.index("def fs_sort_key(")]
loop = body[body.index("for r in rows:"):body.index("if sw_ids:")]
check("fs_share_with" not in loop and body.count("fs_share_with(") == 1, "the names are read once per listing, not per row")

# ---- 2.558.0 D (#4693, review F4): in an organisation only who manages the shares sees the names: the org admin (not the
# folder's maker) yes; a member, read-only, a guest with a share and an agent with a share never
ORG = A.post(B + "/api/admin/orgs", json={"name": "Team Example", "admin_id": A.get(B + "/api/state").json()["me"]["id"]}).json()["id"]
oids = {}
for u, nm, rk in (("olga", "Olga Admin", "admin"), ("mia", "Mia Maker", "member"), ("nora", "Nora Member", "member"),
                  ("rita", "Rita Readonly", "readonly"), ("gina", "Gina Guest", "guest")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": nm, "password": kt.PASSWORD, "orgs": [{"id": ORG, "role": rk}]})
    assert r.ok, r.text
    oids[u] = r.json()["id"]
S = {u: sess(u) for u in oids}
for x in S.values():
    x.patch(B + "/api/settings", json={"lang": "en", "tour": "done"})
r = A.post(B + "/api/admin/agents", json={"username": "teambot", "display_name": "Team bot", "org_id": ORG})
assert r.ok, r.text
TAG_ID, AGS = r.json()["id"], requests.Session()
AGS.headers.update({**kt.H, "Authorization": "Bearer " + r.json()["token"]})
r = S["mia"].post(B + "/api/files/folders", json={"name": "Team files", "space": f"org:{ORG}"})
assert r.ok, r.text
TEAM = r.json()["id"]
TFILE = up(S["mia"], "team.txt", TEAM)
check(S["mia"].patch(B + f"/api/files/nodes/{TEAM}", json={"org_access": "view"}).ok, "org: the folder opened to the members")
share(S["mia"], TEAM, user_id=oids["gina"])
share(S["mia"], TEAM, agent_id=TAG_ID)
want = {("u", "Gina Guest"), ("a", "Team bot")}
jo = lst(S["olga"], parent=TEAM)
check(want <= set(names(jo["node"].get("share_with"))) and want <= set(names((row(jo, TFILE) or {}).get("share_with"))),
      f"org admin (not the maker): the names on the head and the rows {jo['node'].get('share_with')} {row(jo, TFILE)}")
for who in ("nora", "rita", "gina"):
    r = S[who].get(B + "/api/files", params={"parent": TEAM})
    j = r.json() if r.ok else {"node": {}, "items": []}
    check(r.ok and "share_with" not in str(j) and "Team bot" not in str(j) and (who == "gina" or "Gina Guest" not in str(j)),
          f"org {who}: no names of the shares {r.status_code} {str(j)[:300]}")
r = AGS.get(B + "/api/files", params={"parent": TEAM})
j = r.json() if r.ok else {}
check(r.status_code in (200, 401, 403, 404) and "share_with" not in str(j) and "Gina Guest" not in str(j),
      f"org agent with a share: no names {r.status_code} {str(j)[:300]}")

# ---- a person without an organisation (freelancer-matrix: files)
FID, Fr = freelancer(B, A)
FF = folder(Fr, "Freelance")
check(row(lst(Fr, space="private"), FF).get("share_with") == [], "freelancer: own folder, Only you")
t = Fr.get(B + f"/api/files/nodes/{FF}/share-targets").json()
pal = next((p for p in t.get("people", []) if p["id"] == ids["bob"]), None) or (t.get("people") or [None])[0]
if pal:
    share(Fr, FF, user_id=pal["id"])
    check(names(row(lst(Fr, space="private"), FF).get("share_with")) == [("u", pal["name"])], "freelancer: the name of the share")
    FS = folder(Fr, "Inside", FF)
    check(names(row(lst(Fr, parent=FF), FS).get("share_with")) == [("u", pal["name"])], "freelancer: inherited into a subfolder")
else:
    check(True, "freelancer: nobody to share with (workspace rule)")

sys.exit(kt.done("p2558_4693_share_names"))
