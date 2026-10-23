#!/usr/bin/env python3
"""2.199.0 A (#2742): the folder foundation -- reference nodes (files/fsref.py) and folders sorted by hand. Invented names only.
The test container registers the test kind 'probe' (KALMIDO_TEST_FSREF=1): its objects are files of the store, the base
role = the role on that file, "keep*" is protected, "hide*" is hidden from folder shares, on_trash notes probe_trash /
probe_back in the file's history.
 - a folder share view / edit gives that role on the object filed in it, also through a folder above and for objects filed
   later; withdrawing the share and moving the node out (or into no folder) take it away; a folder in the trash gives nothing
 - an agent only with a share on exactly it (organisation access gives it nothing); another organisation never; an object
   only in the tree of its own workspace (409 across)
 - deleting a folder: protected nodes move one level up (kept), the others go along (on_trash, restored with the folder);
   a protected node alone cannot go; removing a node for good keeps the object
 - hidden objects: a folder share does not open them (left out of the listing), the base role stays
 - sorting by hand: before / after / to the end, folders first; view only = 403; with a move into another folder
 - freelancer-matrix: files (a person without an organisation: the same in her private tree, with her private agent)
 - tenant-matrix: file (the reference routes: another organisation gets 404, never across workspaces)
usage: p2199_a_fsref_test.py <datadir>"""
import base64
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
KEY = base64.b64encode(os.urandom(32)).decode()
FEAT = "cal,comments,collab,files,docs,office"

if not os.environ.get("P2199A_NOSTART"):
    env = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={KEY} -e KALMIDO_TEST_FSREF=1")
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
assert sess().post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Example Studio", "lang": "en", "collab_all": True, "modules": ["cal", "comments", "collab"]})
A.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {}
for u in ("bob", "carl"):
    r = A.post(B + "/api/users", json={"orgs": [{"id": ORG, "role": "member"}], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    check(r.ok, f"setup: {u} as member " + r.text[:200])
    uid[u] = r.json().get("id")
r = A.post(B + "/api/users", json={"orgs": [], "username": "olga", "display_name": "Olga", "password": "password123", "email": "olga@example.com"})
check(r.ok, "setup: olga " + r.text[:200])
uid["olga"] = r.json().get("id")
r = A.post(B + "/api/admin/orgs", json={"name": "Other Example", "admin_id": uid["olga"]})
check(r.ok, "setup: another organisation with olga as its admin " + r.text[:200])
Bo, Ca, Ol = sess("bob"), sess("carl"), sess("olga")
for s in (A, Bo, Ca, Ol):
    s.patch(B + "/api/settings", json={"tour": "done", "lang": "en", "features": FEAT})


def folder(s, name, parent=None, space=None):
    r = s.post(B + "/api/files/folders", json={"name": name, **({"parent_id": parent} if parent else {"space": space or f"org:{ORG}"})})
    assert r.status_code == 201, (name, r.status_code, r.text)
    return r.json()["id"]


def upload(s, name, parent=None, space=None):
    r = s.post(B + "/api/files/upload", data={"parent_id": parent} if parent else {"space": space or f"org:{ORG}"},
               files={"file": (name, f"content of {name}".encode(), "text/plain")})
    assert r.status_code == 201, (name, r.status_code, r.text)
    return r.json()["items"][0]["id"]


def place(s, obj, parent, name=None):
    r = s.post(B + "/api/files/refs", json={"ref_kind": "probe", "ref_id": obj, "parent_id": parent, **({"name": name} if name else {})})
    return r.status_code, (r.json().get("node") if r.ok else r.text[:200])


def role(s, obj):
    r = s.get(B + f"/api/files/refs/probe/{obj}")
    return r.json().get("role") if r.ok else r.status_code


def kids(s, parent):
    r = s.get(B + "/api/files", params={"parent": parent})
    return r.json().get("items", []) if r.ok else r.status_code


def share(s, nid, **kw):
    r = s.post(B + f"/api/files/nodes/{nid}/shares", json=kw)
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---------------------------------------------------------------- objects + folders (organisation)
STORE = folder(A, "Objects")  # alice's, not shared: bob has no base role on the files in it
O1, O2 = upload(A, "invoice-1.txt", STORE), upload(A, "invoice-2.txt", STORE)
F1 = folder(A, "Office")
F2 = folder(A, "Clients", F1)
check(role(A, O1) == "edit" and role(Bo, O1) == 404, f"base: alice edit, bob nothing ({role(A, O1)} {role(Bo, O1)})")
st, R1 = place(A, O1, F2)
check(st == 200 and R1 and R1["kind"] == "ref" and R1["ref_id"] == O1 and R1["open"] == f"ablage/{O1}" and R1["name"] == "invoice-1.txt",
      f"alice files O1 into Office/Clients ({st} {R1})")
R1 = R1["id"] if isinstance(R1, dict) else 0
check(role(Bo, O1) == 404, "the folder is not shared yet: bob nothing")
S1 = share(A, F1, user_id=uid["bob"], role="view")
check(role(Bo, O1) == "view", f"share view on the folder above: bob view ({role(Bo, O1)})")
k = kids(Bo, F2)
check(isinstance(k, list) and [x["id"] for x in k] == [R1] and k[0].get("label") == "Test object", f"bob lists the node in the folder {k}")
r = Bo.get(B + f"/api/files/nodes/{R1}/content")
check(r.ok and r.content == f"probe {O1}".encode() and r.headers.get("X-Content-Type-Options") == "nosniff", f"the content of the area (content hook) with view ({r.status_code})")
check(Bo.patch(B + f"/api/files/shares/{S1}", json={"role": "edit"}).status_code == 403, "bob does not change alice's share")
check(A.patch(B + f"/api/files/shares/{S1}", json={"role": "edit"}).ok and role(Bo, O1) == "edit", "share edit: bob edit")
st, _ = place(A, O2, F2)
check(st == 200 and role(Bo, O2) == "edit", f"filed later: bob edit on O2 too ({st} {role(Bo, O2)})")
check(A.delete(B + f"/api/files/shares/{S1}").ok and role(Bo, O1) == 404 and role(Bo, O2) == 404, "the share withdrawn: bob nothing")
S1 = share(A, F1, user_id=uid["bob"], role="view")
ELSE = folder(A, "Elsewhere")
st, _ = place(A, O1, ELSE)
check(st == 200 and role(Bo, O1) == 404 and role(Bo, O2) == "view", f"moved out of the folder: bob nothing on O1, view on O2 ({st})")
check(place(Bo, O2, ELSE)[0] == 403, "bob (view) cannot file O2 elsewhere")
st, _ = place(A, O1, None)
check(st == 200 and A.get(B + f"/api/files/nodes/{R1}").status_code == 404 and role(A, O1) == "edit", "into no folder: the node goes, the object stays")
check(place(A, O1, F2)[0] == 200 and role(Bo, O1) == "view", "filed again: bob view")

# ---------------------------------------------------------------- organisation boundary, workspace of the object
check(role(Ol, O1) == 404 and place(Ol, O1, None)[0] == 404, "another organisation's admin: 404")
PRIV = folder(A, "Private stuff", space="private")
check(place(A, O1, PRIV)[0] == 409, "an organisation's object never into a private folder")
P1 = upload(A, "private-note.txt", PRIV)
check(place(A, P1, F2)[0] == 409, "a private object never into an organisation's folder")
OLF = Ol.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
OF = folder(Ol, "Theirs", space=f"org:{OLF}")
check(place(A, O1, OF)[0] == 404, "alice cannot file into the other organisation's folder")

# ---------------------------------------------------------------- agents: only with a share on exactly them
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
r = A.post(B + "/api/my/agents", json={"username": "shelfbot", "display_name": "Shelf Bot", "scopes": ["read", "files:read"], "org_id": ORG})
check(r.ok, "setup: alice's organisation agent " + r.text[:200])
AG, AH = r.json().get("id"), {**H, "Authorization": "Bearer " + r.json().get("token", "")}


def ag_kids(parent):
    r = requests.get(B + "/api/v1/files", headers=AH, params={"parent_id": parent})
    return [x["id"] for x in r.json().get("data", [])] if r.ok else r.status_code


R1 = place(A, O1, F2)[1]["id"]
check(A.patch(B + f"/api/files/nodes/{F1}", json={"org_access": "view"}).ok, "setup: Office opened to the whole organisation")
check(role(Ca, O1) == 404, f"organisation access opens no object: carl (member) nothing ({role(Ca, O1)})")
k = kids(Ca, F2)
check(isinstance(k, list) and R1 not in [x["id"] for x in k], f"organisation access: carl lists the folder without the object's node {k}")
check(Ca.get(B + f"/api/files/nodes/{R1}").status_code == 404, "organisation access: the node itself 404 for carl")
check(ag_kids(F2) == 404 and requests.get(B + f"/api/v1/files/{R1}", headers=AH).status_code == 404, "organisation access gives the agent nothing")
share(A, F2, agent_id=AG, role="view")
r = requests.get(B + f"/api/v1/files/{R1}", headers=AH)
check(R1 in ag_kids(F2) and r.ok and r.json().get("kind") == "ref" and r.json().get("open") == f"ablage/{O1}" and r.json().get("content_url"),
      f"a share with the agent: it lists the node with ref_kind / open ({r.status_code} {r.text[:200]})")
r = requests.get(B + f"/api/v1/files/{R1}/content", headers=AH)
t = requests.get(B + f"/api/v1/files/{R1}/text", headers=AH)
check(r.ok and r.content == f"probe {O1}".encode() and t.ok and "probe" in str(t.json().get("text", "")), f"the agent reads the content / text over its share ({r.status_code} {t.status_code})")
log = [x["action"] for x in A.get(B + f"/api/files/nodes/{R1}").json().get("log", []) if x.get("agent")]
check("download" in log and "text" in log, f"the agent's reads are in the node's history {log}")
A.patch(B + f"/api/files/nodes/{F1}", json={"org_access": ""})

# ---------------------------------------------------------------- hidden objects
OH = upload(A, "hide-receipt.txt", STORE)
st, RH = place(A, OH, F2)
check(st == 200 and role(A, OH) == "edit" and role(Bo, OH) == 404, f"hidden: the folder share does not open it, alice keeps edit ({st})")
k = kids(Bo, F2)
check(isinstance(k, list) and RH["id"] not in [x["id"] for x in k] and R1 in [x["id"] for x in k], f"hidden: left out of bob's listing {k}")
check(Bo.get(B + f"/api/files/nodes/{RH['id']}").status_code == 404, "hidden: the node itself 404 for bob")

# ---------------------------------------------------------------- trash: protected nodes move up, on_trash, purge keeps the object
OK_ = upload(A, "keep-invoice.txt", STORE)
st, RK = place(A, OK_, F2)
check(st == 200, "setup: a protected object filed")
r = A.delete(B + f"/api/files/nodes/{RK['id']}")
check(r.status_code == 409 and "kept for the test" in r.text, f"a protected node alone cannot go into the trash ({r.status_code})")
r = A.delete(B + f"/api/files/nodes/{F1}")
kept = r.json().get("kept") if r.ok else r.text
check(r.ok and [x["id"] for x in kept] == [RK["id"]] and kept[0]["reason"] == "kept for the test", f"Office into the trash: the protected node stays ({kept})")
n = A.get(B + f"/api/files/nodes/{RK['id']}").json()
check(n.get("parent_id") is None and not n.get("in_trash"), f"it moved one level up (the top of the organisation's tree) {n.get('parent_id')}")
check(role(Bo, O1) == 404 and role(Bo, O2) == 404, "a folder in the trash gives nothing")
log = [x["action"] for x in A.get(B + f"/api/files/nodes/{O1}").json().get("log", [])]
check("probe_trash" in log, f"on_trash told the area {log[:5]}")
check(A.post(B + f"/api/files/nodes/{F1}/restore").ok and role(Bo, O1) == "view", "restored with the folder: bob view again")
log = [x["action"] for x in A.get(B + f"/api/files/nodes/{O1}").json().get("log", [])]
check("probe_back" in log, f"on_trash(restore) told the area {log[:5]}")
R2 = A.get(B + f"/api/files/refs/probe/{O2}").json()["node"]["id"]
r = A.post(B + "/api/files/trash", json={"ids": [R2]})
check(r.ok and r.json().get("kept") == [], "the bulk trash takes a reference node")
r = A.delete(B + f"/api/files/nodes/{R2}", params={"purge": "1"})
check(r.ok and A.get(B + f"/api/files/nodes/{O2}").ok and role(A, O2) == "edit", f"removed for good: the object stays ({r.status_code})")
check(A.get(B + f"/api/files/refs/probe/{O2}").json().get("node") is None, "and it is in no folder")

# ---------------------------------------------------------------- sorting by hand
SO = folder(A, "Sorted")
fa, fb, fc = upload(A, "a.txt", SO), upload(A, "b.txt", SO), upload(A, "c.txt", SO)
sz = folder(A, "z-folder", SO)


def order(s, parent):
    k = kids(s, parent)
    return [x["id"] for x in k] if isinstance(k, list) else k


check(order(A, SO) == [sz, fa, fb, fc], "by name, folders first")
r = A.post(B + f"/api/files/nodes/{fc}/order", json={"before": fa})
check(r.ok and order(A, SO) == [sz, fc, fa, fb], f"c before a ({r.status_code} {order(A, SO)})")
check(A.post(B + f"/api/files/nodes/{fa}/order", json={"after": fb}).ok and order(A, SO) == [sz, fc, fb, fa], "a after b")
check(A.post(B + f"/api/files/nodes/{fc}/order", json={}).ok and order(A, SO) == [sz, fb, fa, fc], "c to the end")
check(A.post(B + f"/api/files/nodes/{fc}/order", json={"before": sz}).ok and order(A, SO) == [sz, fc, fb, fa], "a file before a folder: folders stay first")
check(A.post(B + f"/api/files/nodes/{fb}/order", json={"before": 999999}).status_code == 400, "an anchor that is no sibling: 400")
share(A, SO, user_id=uid["bob"], role="view")
check(Bo.post(B + f"/api/files/nodes/{fa}/order", json={"before": fc}).status_code == 403, "view only: 403")
r = A.post(B + f"/api/files/nodes/{fa}/order", json={"parent_id": sz})
check(r.ok and order(A, sz) == [fa] and order(A, SO) == [sz, fc, fb], f"with a move into another folder ({r.status_code})")
check(A.patch(B + f"/api/files/nodes/{fc}", json={"parent_id": sz}).ok and order(A, sz) == [fa, fc], "a plain move: by name at the end")
check(Bo.post(B + f"/api/files/nodes/{F1}/order", json={}).status_code in (403, 404), "bob does not sort the organisation's top folders of alice")

# ---------------------------------------------------------------- freelancer-matrix: files (no organisation)
FID, Fr = freelancer(B, A)
FF = folder(Fr, "Office", space="private")
FS = folder(Fr, "Store", space="private")
PO = upload(Fr, "quote-1.txt", FS)
st, FR = place(Fr, PO, FF)
check(st == 200 and FR and FR["org_id"] is None, f"freelancer: files her object into her folder ({st})")
check(role(Fr, PO) == "edit" and role(A, PO) == 404 and role(Bo, PO) == 404, "freelancer: only she reaches it")
check(place(Fr, PO, F2)[0] == 404, "freelancer: never into an organisation's folder")
r = Fr.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida Bot", "scopes": ["read", "files:read"]})
if r.ok:
    FAH = {**H, "Authorization": "Bearer " + r.json().get("token", "")}
    fl = requests.get(B + "/api/v1/files", headers=FAH, params={"parent_id": FF})
    check(fl.status_code == 404, "freelancer's agent without a share: nothing")
    share(Fr, FF, agent_id=r.json()["id"], role="view")
    fl = requests.get(B + "/api/v1/files", headers=FAH, params={"parent_id": FF})
    check(fl.ok and [x["id"] for x in fl.json().get("data", [])] == [FR["id"]], f"freelancer's agent with the share lists the node ({fl.status_code})")
else:
    check(False, "freelancer: her private agent " + r.text[:200])
q1, q2 = upload(Fr, "q1.txt", FS), upload(Fr, "q2.txt", FS)
check(Fr.post(B + f"/api/files/nodes/{q2}/order", json={"before": q1}).ok and order(Fr, FS) == [q2, q1, PO], f"freelancer: sorts by hand {order(Fr, FS)}")
r = Fr.post(B + f"/api/files/nodes/{FS}/order", json={"before": FF})
top = [x["id"] for x in Fr.get(B + "/api/files", params={"space": "private"}).json()["items"]]
check(r.ok and top[:2] == [FS, FF], f"freelancer: sorts her top folders ({r.status_code} {top})")
KO = upload(Fr, "keep-contract.txt", FS)
place(Fr, KO, FF)
r = Fr.delete(B + f"/api/files/nodes/{FF}")
check(r.ok and [x["name"] for x in r.json().get("kept", [])] == ["keep-contract.txt"], f"freelancer: the protected node stays when the folder goes ({r.text[:200]})")

print(f"p2199_a_fsref: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
