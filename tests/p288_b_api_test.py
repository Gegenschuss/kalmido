#!/usr/bin/env python3
"""2.88.0 API tests, part B (#1980): the admin user management for hundreds of accounts. Invented names only.
 - DELETE /api/users/{id}: without a parameter still 409 while the account owns lists; ?lists=transfer&to={id} hands every
   list to one person (an unknown / invisible person 404, an agent / a disabled account / the account itself 400, a person
   who does not fit one list -- an organisation's list stays in its organisation -- 409 and nothing changes);
   ?lists=delete&confirm={user name} deletes the lists along (a wrong name 400); an account without organisation too
 - GET /api/users/{id}/delete-info: the lists (names only where the admin may see the list), the common candidates
 - an organisation admin deletes an account of their organisation alone; another organisation too, a server admin or
   private lists: 403 (delete-info says so and names the members for "Remove"); DELETE /api/orgs/{o}/members/{u}?to=
 - GET /api/users?all=1&limit=&offset=&q=&filter=: one page + total, search by name / user name / e-mail, the filters;
   300 accounts: a page of 50 under one second; without limit the whole list as before
 - POST /api/users/bulk: disable / enable / org_add per account through the single route (own account, invisible: failed)
usage: p288_b_api_test.py <datadir>      (a fresh container; P288B_NOSTART=1 = the server already runs)"""
import os
import subprocess
import sys
import time

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


if not os.environ.get("P288B_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Alpha", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
ORG = A.get(B + "/api/state").json()["me"]["workspaces"][0]["id"]
uid = {"alice": 1}
r = A.post(B + "/api/users", json={"username": "dave", "display_name": "Dave Example", "password": "password123", "email": "dave@example.com"})
assert r.ok, r.text
uid["dave"] = r.json()["id"]
r = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": uid["dave"]})  # alice is not in Beta
assert r.status_code in (200, 201), r.text
BETA = r.json()["id"]
for u, orgs in (("bob", [ORG]), ("carol", [ORG]), ("erin", [{"id": ORG, "role": "admin"}]), ("frank", [ORG, BETA]),
                ("ivy", [ORG, BETA]), ("jack", [ORG, BETA]), ("kim", [ORG]), ("hank", [ORG]), ("gina", []), ("lena", []),
                ("max", [ORG])):
    r = A.post(B + "/api/users", json={"orgs": orgs, "username": u, "display_name": u.title() + " Example",
                                       "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
check(A.patch(B + f"/api/users/{uid['hank']}", json={"disabled": True}).ok, "setup: hank disabled")
r = A.post(B + "/api/admin/agents", json={"scopes": ["read"], "username": "helper", "display_name": "Helper"})
check(r.ok, "setup: an agent " + r.text[:200])
AG = r.json().get("id")


def mklist(s, name, org=None):
    r = s.post(B + "/api/lists", json={"name": name, "org_id": org})  # None = private (else the default workspace)
    assert r.ok, r.text
    return r.json()["id"]


def owner(lid):
    """The owner as alice reads it (the state of a member: alice is added to the lists checked this way)."""
    r = A.get(B + f"/api/lists/{lid}/owner")
    return r.json().get("owner", {}).get("id") if r.ok else None


def deluser(s, who, **q):
    return s.delete(B + f"/api/users/{uid[who]}", params=q)


Fr, Ca, Ki, Gi, Le, Ja, Er, Bo = (sess(x) for x in ("frank", "carol", "kim", "gina", "lena", "jack", "erin", "bob"))
FA = mklist(Fr, "Frank alpha plan", ORG)
FB = mklist(Fr, "Frank beta plan", BETA)
FP = mklist(Fr, "Frank private notes")
check(Fr.put(B + f"/api/lists/{FA}/members", json={"user_id": uid["bob"], "role": "edit"}).ok, "setup: Frank shares his Alpha list with Bob")
check(Fr.put(B + f"/api/lists/{FP}/members", json={"user_id": 1, "role": "view"}).ok, "setup: Frank shares his private list with Alice")
Fr.post(B + "/api/tasks", json={"title": "Plan the fence", "list_id": FA})

# ---- without a parameter: the old 409
r = deluser(A, "frank")
check(r.status_code == 409 and "3 lists" in r.json().get("error", ""), "no parameter: 409 as before " + r.text[:200])

# ---- delete-info: names only where alice may see the list
r = A.get(B + f"/api/users/{uid['frank']}/delete-info")
check(r.ok and r.json()["can_delete"] and r.json()["by"] == "instance", "delete-info for the instance admin " + r.text[:300])
info = {x["id"]: x for x in r.json().get("lists", [])}
check(set(info) == {FA, FB, FP}, "delete-info: the three lists")
check(info.get(FB, {}).get("name") is None and info.get(FB, {}).get("org") == "Beta", "a Beta list alice is not in: no name, the organisation " + str(info.get(FB)))
check(info.get(FP, {}).get("name") == "Frank private notes", "a private list shared with alice: named")
check(info.get(FA, {}).get("shared") == 1, "the Alpha list: shared with one person " + str(info.get(FA)))
cand = {x["id"] for x in r.json().get("candidates", [])}
check(uid["ivy"] in cand and uid["bob"] not in cand and uid["hank"] not in cand and AG not in cand and uid["frank"] not in cand,
      "candidates: Alpha + Beta people only, never disabled / agents / the account itself " + str(cand))

# ---- target checks
check(deluser(A, "frank", lists="transfer", to=uid["dave"]).status_code == 404, "an invisible target (Beta only): 404 as unknown")
check(deluser(A, "frank", lists="transfer", to=999999).status_code == 404, "an unknown target: 404")
r = deluser(A, "frank", lists="transfer", to=AG)
check(r.status_code in (400, 404), "an agent as target: refused " + r.text[:200])
check(deluser(A, "frank", lists="transfer", to=uid["hank"]).status_code == 400, "a disabled target: 400")
check(deluser(A, "frank", lists="transfer", to=uid["frank"]).status_code == 400, "the account itself as target: 400")
check(deluser(A, "frank", lists="transfer").status_code == 400, "transfer without a target: 400")
check(deluser(A, "frank", lists="nonsense").status_code == 400, "an unknown mode: 400")
r = deluser(A, "frank", lists="transfer", to=uid["bob"])
check(r.status_code == 409 and FB in r.json().get("lists", []) and FA not in r.json().get("lists", []), "Bob is not in Beta: 409 naming the Beta list " + r.text[:200])
check(Fr.get(B + f"/api/lists/{FA}/owner").json().get("owner", {}).get("id") == uid["frank"], "409: nothing changed (Frank still owns the Alpha list)")
check(Fr.get(B + "/api/me").ok, "409: Frank's account is still there")
r = deluser(A, "frank", lists="delete", confirm="Frank")
check(r.status_code == 400, "delete along with a wrong name: 400")

# ---- transfer to ivy (Alpha + Beta)
r = deluser(A, "frank", lists="transfer", to=uid["ivy"])
check(r.ok and r.json().get("lists") == 3, "transfer: the account goes, 3 lists handed over " + r.text[:200])
Iv = sess("ivy")
own = {x: Iv.get(B + f"/api/lists/{x}/owner").json().get("owner", {}).get("id") for x in (FA, FB, FP)}
check(all(v == uid["ivy"] for v in own.values()), "Ivy owns the three lists " + str(own))
check(requests.post(B + "/api/auth/login", headers=H, json={"username": "frank", "password": "password123"}).status_code in (401, 403, 400), "Frank cannot log in any more")
check(Bo.get(B + f"/api/lists/{FA}/owner").ok, "Bob keeps the shared list")

# ---- delete along: an account without organisation (P4)
LP1 = mklist(Le, "Lena garden")
LP2 = mklist(Le, "Lena books")
Le.post(B + "/api/tasks", json={"title": "Sow carrots", "list_id": LP1})
check(Le.put(B + f"/api/lists/{LP1}/members", json={"user_id": 1, "role": "edit"}).status_code in (200, 403, 404), "setup: Lena shares a list (if she may)")
r = A.get(B + f"/api/users/{uid['lena']}/delete-info")
check(r.ok and r.json()["can_delete"] and len(r.json()["lists"]) == 2 and r.json().get("username") == "lena", "delete-info: an account without organisation " + r.text[:300])
r = deluser(A, "lena", lists="delete", confirm="lena")
check(r.ok and r.json().get("lists") == 2, "delete along: the account and its 2 lists go " + r.text[:200])
check(A.get(B + f"/api/lists/{LP1}/owner").status_code == 404, "the list is gone")
check(A.get(B + f"/api/users/{uid['lena']}/delete-info").status_code == 404, "the account is gone")

# ---- transfer of an account without organisation (P4): its private lists to alice
GP = mklist(Gi, "Gina recipes")
r = deluser(A, "gina", lists="transfer", to=1)
check(r.ok, "an account without organisation: its private list to the admin " + r.text[:200])
check(owner(GP) == 1, "Alice owns Gina's list now")

# ---- an organisation admin (erin, Alpha)
CA = mklist(Ca, "Carol alpha", ORG)
r = Er.get(B + f"/api/users/{uid['carol']}/delete-info")
check(r.ok and r.json()["can_delete"] and r.json()["by"] == "org" and r.json()["org_id"] == ORG, "org admin: delete-info for a member of Alpha alone " + r.text[:300])
check(deluser(Er, "carol").status_code == 409, "org admin: without a parameter 409")
r = deluser(Er, "carol", lists="transfer", to=uid["bob"])
check(r.ok, "org admin deletes a member of only their organisation, lists to Bob " + r.text[:200])
check(Bo.get(B + f"/api/lists/{CA}/owner").json().get("owner", {}).get("id") == uid["bob"], "Bob owns Carol's list")
check(deluser(Er, "jack").status_code == 403, "org admin: a person also in Beta -> 403")
r = Er.get(B + f"/api/users/{uid['jack']}/delete-info")
check(r.ok and not r.json()["can_delete"] and r.json()["org_id"] == ORG and any(x["id"] == uid["bob"] for x in r.json()["heirs"]) and r.json()["reason"],
      "org admin: delete-info says no + names the members for Remove " + r.text[:300])
check(deluser(Er, "alice").status_code in (403, 400), "org admin: the server admin -> 403")
KP = mklist(Ki, "Kim private")
check(deluser(Er, "kim", lists="transfer", to=uid["bob"]).status_code == 403, "org admin: an account with private lists -> 403")
r = Er.get(B + f"/api/users/{uid['kim']}/delete-info")
check(r.ok and not r.json()["can_delete"], "org admin: delete-info for private lists: no " + r.text[:200])
check(Ki.get(B + f"/api/lists/{KP}/owner").json().get("owner", {}).get("id") == uid["kim"], "Kim's private list untouched")
check(deluser(Er, "dave").status_code == 404, "org admin: a person of another organisation -> 404")
check(deluser(Bo, "kim").status_code == 403, "a plain member -> 403")
check(Bo.get(B + f"/api/users/{uid['kim']}/delete-info").status_code == 403, "a plain member: no delete-info")
r = deluser(Er, "max")
check(r.ok, "org admin: a member of Alpha alone without lists " + r.text[:200])
# remove from the organisation with a chosen heir
JA = mklist(Ja, "Jack alpha", ORG)
check(Er.delete(B + f"/api/orgs/{ORG}/members/{uid['jack']}", params={"to": uid["dave"]}).status_code == 400, "remove: an heir outside the organisation 400")
check(Er.delete(B + f"/api/orgs/{ORG}/members/{uid['jack']}", params={"to": uid["hank"]}).status_code == 400, "remove: a disabled heir 400")
r = Er.delete(B + f"/api/orgs/{ORG}/members/{uid['jack']}", params={"to": uid["bob"]})
check(r.ok and r.json().get("transferred") == 1, "remove with heir Bob " + r.text[:200])
check(Bo.get(B + f"/api/lists/{JA}/owner").json().get("owner", {}).get("id") == uid["bob"], "Bob owns Jack's Alpha list")

# ---- pages, search, filter: 300 accounts
for i in range(300):
    r = A.post(B + "/api/users", json={"username": f"load{i:03d}", "display_name": f"Load {i:03d}", "email": f"load{i:03d}@example.com"})
    if not r.ok:
        time.sleep(1)
        r = A.post(B + "/api/users", json={"username": f"load{i:03d}", "display_name": f"Load {i:03d}", "email": f"load{i:03d}@example.com"})
    assert r.ok, r.text
t = time.time()
r = A.get(B + "/api/users", params={"all": 1, "limit": 50, "offset": 0, "q": "load"})
dt = time.time() - t
j = r.json()
check(r.ok and j["total"] == 300 and len(j["users"]) == 50 and j["users"][0]["username"] == "load000", "a page of 50 of 300 " + str({k: j.get(k) for k in ("total", "offset", "limit")}))
check(dt < 1.0, f"a page answers under one second ({dt:.2f} s)")
check(len(A.get(B + "/api/users", params={"all": 1, "limit": 50, "offset": 250, "q": "load"}).json()["users"]) == 50, "the last page")
check(A.get(B + "/api/users", params={"all": 1, "limit": 50, "offset": 300, "q": "load"}).json()["users"] == [], "after the end: empty")
check(A.get(B + "/api/users", params={"all": 1, "limit": 50, "q": "LOAD123@EXAMPLE"}).json()["total"] == 1, "search by e-mail, any case")
check(A.get(B + "/api/users", params={"all": 1, "limit": 50, "q": "ivy ex"}).json()["total"] == 1, "search by display name")
check(A.get(B + "/api/users", params={"all": 1, "limit": 50, "q": "50%"}).json()["total"] == 0, "a % is literal")
dis = A.get(B + "/api/users", params={"all": 1, "limit": 50, "filter": "disabled"}).json()
check([u["username"] for u in dis["users"]] == ["hank"], "filter disabled " + str([u["username"] for u in dis["users"]]))
adm = A.get(B + "/api/users", params={"all": 1, "limit": 50, "filter": "admin"}).json()
check([u["username"] for u in adm["users"]] == ["alice"], "filter admin")
ags = A.get(B + "/api/users", params={"all": 1, "limit": 50, "filter": "agents"}).json()
check([u["id"] for u in ags["users"]] == [AG], "filter agents")
ppl = A.get(B + "/api/users", params={"all": 1, "limit": 200, "filter": "people"}).json()
check(AG not in [u["id"] for u in ppl["users"]] and ppl["agents"] >= 1, "people: no agents, their number apart")
check(A.get(B + "/api/users", params={"all": 1, "limit": 50, "filter": "bogus"}).status_code == 400, "an unknown filter 400")
full = A.get(B + "/api/users?all=1").json()
check("total" not in full and len(full["users"]) >= 300, "without limit: the whole list as before")
pa = next(u for u in A.get(B + "/api/users", params={"all": 1, "limit": 50, "q": "ivy"}).json()["users"] if u["username"] == "ivy")
fa = next(u for u in full["users"] if u["username"] == "ivy")
check(pa == fa, "a page's account dict equals the single one " + str({k: (pa.get(k), fa.get(k)) for k in set(pa) | set(fa) if pa.get(k) != fa.get(k)}))
check(Bo.get(B + "/api/users", params={"all": 1, "limit": 50}).json().get("total") is None, "a plain member gets no user management page")

# ---- several accounts at once
ld = [u["id"] for u in A.get(B + "/api/users", params={"all": 1, "limit": 3, "q": "load"}).json()["users"]]
r = A.post(B + "/api/users/bulk", json={"ids": ld + [1, uid["dave"]], "action": "disable"})
j = r.json()
check(r.ok and j["ok"] == ld and {x["id"] for x in j["failed"]} == {1, uid["dave"]}, "bulk disable: own account and an invisible one fail " + r.text[:300])
check(A.get(B + "/api/users", params={"all": 1, "limit": 50, "filter": "disabled", "q": "load"}).json()["total"] == 3, "three disabled")
check(A.post(B + "/api/users/bulk", json={"ids": ld, "action": "enable"}).json()["ok"] == ld, "bulk enable")
r = A.post(B + "/api/users/bulk", json={"ids": ld[:2], "action": "org_add", "org_id": ORG})
check(r.ok and r.json()["ok"] == ld[:2], "bulk: add to Alpha " + r.text[:200])
check(all(ORG in u["orgs"] for u in A.get(B + "/api/users", params={"all": 1, "limit": 2, "q": "load"}).json()["users"]), "both in Alpha")
check(A.post(B + "/api/users/bulk", json={"ids": ld, "action": "org_add", "org_id": 99999}).status_code == 404, "bulk: unknown organisation 404")
check(A.post(B + "/api/users/bulk", json={"ids": ld, "action": "drop"}).status_code == 400, "bulk: unknown action 400")
check(A.post(B + "/api/users/bulk", json={"ids": [], "action": "disable"}).status_code == 400, "bulk: no ids 400")
check(Er.post(B + "/api/users/bulk", json={"ids": ld, "action": "disable"}).status_code == 403, "bulk: an organisation admin 403")
check(Bo.post(B + "/api/users/bulk", json={"ids": ld, "action": "disable"}).status_code == 403, "bulk: a member 403")

print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
