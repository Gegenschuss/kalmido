#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.1045.0 C (#5822): GET /api/agents/<id>/sees -- what is shared with exactly this agent (agents/agsees.py), the section
"Sees now" of the dialog "Edit agent". Invented names only (example.com).
 - the list is right: a knowledge folder shared through the file store's share route (role edit), a project (membership,
   role view), each with its kind, path from "Knowledge", role and whether the asker may end it; ending the knowledge share
   through the existing route takes it off the list and the agent reads the page no more (404)
 - counts per kind (for the hint "Nothing shared yet") count every share; a private share of another person with a team
   agent is only counted for the admin: "+ n more" (hidden), never its name or path
 - who may ask: the owner of a personal agent only (an instance admin 404), an instance admin for a team agent (a member 404);
   tenant-matrix: agent -- the admin of another organisation (not an instance admin) gets 404 for both
 - options (?options=1) for "Share…": the private knowledge area with its root ("Entire knowledge area") and folders, the
   organisation's area greyed for a private personal agent with the reason, the private folders of the file store, the
   projects not yet shared
 - freelancer-matrix: agents -- a person without an organisation: her own agent sees her shared folder, she reads the list
 - the root of a knowledge area as a share target (part B of 2.1045): checked only when that part is there (else a note)
tenant-matrix: agent
usage: p21045_c_sees_test.py <datadir>      (P21045C_NOSTART=1: the server already runs on KALMIDO_TEST_PORT)"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import FEATURES, freelancer  # noqa: E402
from kt import FAILS, OKS, check, sess  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else ""
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
FEAT = "wiki,files,collab,comments"
WS = ["read", "tasks:write", "wiki:read", "wiki:write", "files:read", "files:write"]

if not os.environ.get("P21045C_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)

s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {"alice": A.get(B + "/api/state").json()["me"]["id"]}
for u in ("bob", "olga"):
    r = A.post(B + "/api/users", json={"orgs": [ORG] if u == "bob" else [], "username": u, "display_name": u.title(),
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["olga"]})
assert r.status_code in (200, 201), r.text
Bo, Ol = sess("bob"), sess("olga")
for s in (A, Bo, Ol):
    s.patch(B + "/api/settings", json={"features": FEAT, "lang": "en", "tour": "done"})


def bearer(tok):
    s = requests.Session()
    s.headers.update({"Authorization": "Bearer " + tok})
    return s


def agent(name, org=None, owner=None, scopes=WS):
    body = {"scopes": list(scopes), "username": name, "display_name": name.title(), "org_id": org}
    if owner:
        body["owner_id"] = owner
    r = A.post(B + "/api/admin/agents", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"], bearer(r.json()["token"])


def page(s, path, text="", space="private"):
    r = s.post(B + "/api/wiki/pages", json={"space": space, "path": path, "body": text})
    assert r.status_code == 201, (path, r.status_code, r.text)
    return r.json()["id"]


def tree(s, space="private"):
    j = s.get(B + "/api/wiki", params={"space": space}).json()
    return j.get("root"), {f["path"]: f["id"] for f in j.get("folders", [])}


def fshare(s, nid, **kw):
    r = s.post(B + f"/api/files/nodes/{nid}/shares", json=kw)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def sees(s, aid, options=False):
    r = s.get(B + f"/api/agents/{aid}/sees", params={"options": "1"} if options else None)
    return r.json() if r.ok else {"status": r.status_code}


# ================================================================ a personal agent of bob (private)
BA, ba = agent("bobbot", owner=uid["bob"])
P1 = page(Bo, "Recipes/Soup", "salt")
P2 = page(Bo, "Diary", "secret")
ROOT, FB = tree(Bo)
REC = FB.get("Recipes")
check(ROOT and REC, f"setup: bob's private tree {ROOT} {FB}")
j = sees(Bo, BA)
check(j.get("items") == [] and j.get("hidden") == 0 and j.get("counts") == {"project": 0, "wiki": 0, "files": 0},
      f"nothing shared yet: an empty list, every count 0 {j}")
check(ba.get(V + f"/wiki/pages/{P1}").status_code == 404, "the agent sees no page without a share")
S1 = fshare(Bo, REC, agent_id=BA, role="edit")
L1 = Bo.post(B + "/api/lists", json={"name": "Garden", "org_id": None}).json()["id"]
r = Bo.put(B + f"/api/lists/{L1}/members", json={"user_id": BA, "role": "view"})
check(r.ok, f"setup: the project shared with the agent (view) {r.status_code} {r.text[:120]}")
j = sees(Bo, BA)
it = {(x["kind"], x["id"]): x for x in j.get("items", [])}
w = it.get(("wiki", S1), {})
check(w.get("name") == "Recipes" and w.get("role") == "edit" and w.get("node_id") == REC and not w.get("whole") and w.get("can_remove") is True,
      f"the knowledge folder: name, role edit, removable {w}")
check(str(w.get("path", "")).split("/")[-1] == "Recipes" and w.get("path", "").count("/") == 1, f"its path starts at the knowledge root {w.get('path')}")
p = it.get(("project", L1), {})
check(p.get("name") == "Garden" and p.get("role") == "view" and p.get("can_remove") is True, f"the project: name, role view {p}")
check(j.get("counts") == {"project": 1, "wiki": 1, "files": 0} and j.get("hidden") == 0, f"counts {j.get('counts')}")
check(ba.get(V + f"/wiki/pages/{P1}").json().get("body") == "salt", "the agent reads the page of the shared folder")
check(ba.get(V + f"/wiki/pages/{P2}").status_code == 404, "and not a page outside it")

# who may ask
check(sees(A, BA).get("status") == 404, "an instance admin: another person's personal agent 404")
check(sees(Ol, BA).get("status") == 404, "tenant: the admin of another organisation 404")
check(ba.get(B + f"/api/agents/{BA}/sees").status_code in (401, 403, 404), "the agent itself never")

# options for "Share…"
o = sees(Bo, BA, options=True).get("options", {})
wk = {(b["org_id"] or 0): b for b in o.get("wiki", [])}
check(wk.get(0, {}).get("root") == ROOT and not wk[0].get("disabled") and any(f["id"] == REC for f in wk[0].get("folders", [])),
      f"options: the private area with its root and folders {wk.get(0)}")
check(wk.get(ORG, {}).get("disabled") == "A private personal agent never sees the pages of an organisation" and not wk[ORG].get("folders"),
      f"options: the organisation's area greyed with the reason {wk.get(ORG)}")
check(L1 not in {x["id"] for x in o.get("projects", [])}, "options: a project already shared is not offered again")
FD = Bo.post(B + "/api/files/folders", json={"space": "private", "name": "Invoices"}).json().get("id")
o = sees(Bo, BA, options=True).get("options", {})
check(FD in {x["id"] for x in o.get("files", [])}, f"options: the private folder of the file store {o.get('files')}")
check(not any(x["id"] == REC for x in o.get("files", [])), "options: a knowledge folder is not offered as a file store folder")

# ending a share through the existing route
r = Bo.delete(B + f"/api/files/shares/{S1}")
check(r.ok, f"the share ended through the file store's route {r.status_code}")
j = sees(Bo, BA)
check(("wiki", S1) not in {(x["kind"], x["id"]) for x in j.get("items", [])} and j.get("counts", {}).get("wiki") == 0, "it is off the list")
check(ba.get(V + f"/wiki/pages/{P1}").status_code == 404, "and the agent reads the page no more")
r = Bo.delete(B + f"/api/lists/{L1}/members/{BA}")
check(r.ok and sees(Bo, BA).get("counts", {}).get("project") == 0, f"the project share ended through the members route {r.status_code}")

# the whole knowledge area (part B makes the root a share target)
r = Bo.post(B + f"/api/files/nodes/{ROOT}/shares", json={"agent_id": BA, "role": "view"})
if r.status_code == 201:
    x = next((i for i in sees(Bo, BA).get("items", []) if i.get("node_id") == ROOT), {})
    check(x.get("whole") is True and x.get("name") == "Entire knowledge area", f"the root shared: 'Entire knowledge area' {x}")
    check(ba.get(V + f"/wiki/pages/{P2}").json().get("body") == "secret", "and the agent reads every page of the area")
    Bo.delete(B + f"/api/files/shares/{r.json()['id']}")
else:
    print(f"NOTE: the root is no share target yet ({r.status_code}): part B (#5823) of 2.1045 brings it; checked after the merge")

# ================================================================ a team agent: a share the asker cannot see is only counted
# ivan: an instance admin who is a plain member of Alpha (not its admin): bob's folder of the organisation is not his to see
r = A.post(B + "/api/users", json={"orgs": [ORG], "username": "ivan", "display_name": "Ivan", "password": "password123",
                                   "email": "ivan@example.com", "is_admin": True})
assert r.ok, r.text
Iv = sess("ivan")
Iv.patch(B + "/api/settings", json={"features": FEAT, "lang": "en", "tour": "done"})
TA, ta = agent("alphateam", org=ORG)
BS = Bo.post(B + "/api/files/folders", json={"space": f"org:{ORG}", "name": "ZQXsecretfolder"}).json().get("id")
r = Bo.post(B + f"/api/files/nodes/{BS}/shares", json={"agent_id": TA, "role": "view"})
check(r.status_code == 201, f"setup: bob shares his folder of the organisation with the team agent {r.status_code} {r.text[:160]}")
IF = Iv.post(B + "/api/files/folders", json={"space": f"org:{ORG}", "name": "Shared by ivan"}).json().get("id")
SI = fshare(Iv, IF, agent_id=TA, role="edit")
seen_by_ivan = Iv.get(B + f"/api/files/nodes/{BS}").status_code
r = Iv.get(B + f"/api/agents/{TA}/sees")
j = r.json() if r.ok else {}
if seen_by_ivan == 404:
    check(r.ok and [x["id"] for x in j.get("items", [])] == [SI] and j.get("hidden") == 1 and j.get("counts", {}).get("files") == 2,
          f"the admin sees his own share, bob's only as '+ 1 more' {r.status_code} {j}")
    check("ZQXsecretfolder" not in r.text and "Bob" not in r.text, "no name or path of bob's share in the answer")
else:
    check(False, f"setup: ivan must not see bob's folder of the organisation ({seen_by_ivan})")
j = sees(A, TA)
check({x["name"] for x in j.get("items", [])} == {"ZQXsecretfolder", "Shared by ivan"} and j.get("hidden") == 0,
      f"the organisation's admin sees both {j}")
check(sees(Bo, TA).get("status") == 404, "a member who may not edit the team agent: 404")
check(sees(Ol, TA).get("status") == 404, "tenant: another organisation's admin, a team agent of Alpha: 404")

# ================================================================ a person without an organisation
# freelancer-matrix: agents
FID, Fl = freelancer(B, A, features=FEATURES + ",wiki,files")
DA, da = agent("fridabot", owner=FID)
Q1 = page(Fl, "Clients/Acme", "Jane")
_, FF = tree(Fl)
fshare(Fl, FF["Clients"], agent_id=DA, role="view")
j = sees(Fl, DA)
check([x["name"] for x in j.get("items", [])] == ["Clients"] and j["items"][0]["role"] == "view", f"the freelancer: her agent's list {j}")
check(da.get(V + f"/wiki/pages/{Q1}").json().get("body") == "Jane", "and her agent reads the page")
o = sees(Fl, DA, options=True).get("options", {})
check([b["org_id"] for b in o.get("wiki", [])] == [None] and o["wiki"][0].get("root"), f"the freelancer: only her private area in the options {o.get('wiki')}")
check(sees(A, DA).get("status") == 404, "the instance admin: the freelancer's personal agent 404")

print(f"\n{OKS[0]} ok, {len(FAILS)} failed")
for f in FAILS:
    print("FAIL:", f)
sys.exit(1 if FAILS else 0)
