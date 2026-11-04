#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.539.0 part A: an admin who saw the recovery key goes (#4373) and the operator's account list of a hosted instance (#4374).
Own container (start.sh, a server key, workspaces; first self-hosted, then restarted with KEEP=1 and KALMIDO_HOSTED=1, same
data). Invented accounts only (example.com).
#4373 (self-hosted):
 - an admin who showed the organisation's recovery key is taken out: the remaining admins get the News item "orgkey" with
   action renew (named, never the value), a member gets none, the key is not rotated (the same recovery key again)
 - an admin who never showed it is demoted: no News item; one who showed it is demoted / leaves / is locked: News
 - a person without an organisation (freelancer) keeps the recovery key of the own office, no News item
#4374:
 - self-hosted: the account list (whole and paged) carries e-mail, name, sign-in methods and organisation ids of every
   account, the search finds an account by its e-mail address, the instance admin sees every photo (unchanged)
 - hosted: a client's account carries only id, user name (as its name), lock, admin right, storage, kind, the number of its
   organisations and apart -- no e-mail, name, photo, 2FA, password flag, OIDC, organisation ids; the search finds it by its
   user name only, not by its e-mail address or name; its photo answers 404 to the operator (200 to its owner); the accounts
   of the operator's own organisation stay complete and searchable; with a support grant the account is complete again
 - a person without an organisation: as a client account on the hosted instance, her own list and photo unchanged
freelancer-matrix: own
usage: p2539_a_admin_test.py <datadir>"""
import io
import os
import sys

from PIL import Image

import kt
from kt import B, check, sess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from freelancer_fixture import freelancer, login  # noqa: E402

KEY = "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA="  # a test server key (32 bytes, base64)
ENV = {"KALMIDO_SECRET_KEY": KEY, "KALMIDO_INSTANCE_MODE": "workspaces", "KALMIDO_ORGCRYPT_DELAY": "0"}
BRIEF = {"id", "username", "display_name", "avatar", "kind", "is_admin", "disabled", "signup", "storage", "apart", "org_count", "agent"}


def show(s, oid, **b):
    return s.post(B + f"/api/orgs/{oid}/encryption/recovery", json={"password": "password123", **b})


def renew(s):
    return [x for x in s.get(B + "/api/news").json().get("items", []) if x["kind"] == "orgkey" and x["data"].get("action") == "renew"]


def photo(s):
    png = io.BytesIO()
    Image.new("RGB", (64, 64), (30, 90, 200)).save(png, "PNG")
    r = s.post(B + "/api/me/avatar", files={"file": ("p.png", png.getvalue(), "image/png")})
    assert r.ok, r.text
    return r.json()["avatar"]


def page(s, q="", flt="people"):
    return s.get(B + "/api/users", params={"all": "1", "limit": "50", "q": q, "filter": flt}).json()


kt.fresh(env=ENV)
A = kt.setup("alice", "Alice Admin")
ALICE = A.get(B + "/api/state").json()["me"]["id"]
uid = {}
for u in ("bruno", "carol", "dave", "erin", "mia", "carl"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title() + " Person", "password": "password123",
                                       "email": f"{u}-box@example.com"})
    assert r.ok, r.text
    uid[u] = r.json()["id"]
FID, Fr = freelancer(B, A)
S = {u: login(B, u) for u in uid}
for s in S.values():
    assert s.patch(B + "/api/settings", json={"lang": "en", "tour": "done"}).ok
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
for u, role in (("bruno", "admin"), ("carol", "admin"), ("dave", "admin"), ("erin", "admin"), ("mia", "member")):
    assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": f"{u}-box@example.com", "role": role}).ok
CO = A.post(B + "/api/admin/orgs", json={"name": "Client Studio", "admin_id": uid["carl"]}).json()["id"]
assert kt.dbx("SELECT role FROM org_members WHERE org_id=? AND user_id=?", (ORG, uid["erin"])) == [("admin",)]
assert not kt.dbx("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (CO, ALICE))

# ================================================================ #4373: an admin who saw the recovery key goes
r = show(S["bruno"], ORG)
R1 = r.json().get("recovery_key", "") if r.ok else ""
check(r.ok and R1.startswith("R2-"), "bruno shows the recovery key " + r.text[:100])
check(not renew(A) and not renew(S["carol"]), "showing alone asks nobody to renew")
r = A.patch(B + f"/api/admin/orgs/{ORG}", json={"members_remove": [uid["bruno"]]})
check(r.ok, "alice takes bruno out " + r.text[:100])
na, nc = renew(A), renew(S["carol"])
check(len(na) == 1 and len(nc) == 1 and nc[0]["data"].get("org_id") == ORG and nc[0]["data"].get("by_name") == "Bruno Person",
      f"#4373: the remaining admins are asked to renew the recovery key {nc[:1]}")
check(not renew(S["mia"]) and not renew(S["bruno"]), "#4373: no News for a member, none for the one taken out")
check(R1 not in str(kt.dbx("SELECT data FROM notifications")), "#4373: the value is in no News item")
r = show(A, ORG)
check(r.ok and r.json().get("recovery_key") == R1 and r.json().get("new") is False, "#4373: nothing rotated (the same recovery key)")
n0 = len(renew(S["carol"]))
r = S["dave"].put(B + f"/api/orgs/{ORG}/members", json={"user_id": uid["erin"], "role": "member"})
check(r.ok and kt.dbx("SELECT role FROM org_members WHERE org_id=? AND user_id=?", (ORG, uid["erin"])) == [("member",)],
      "dave demotes erin " + r.text[:100])
check(len(renew(S["carol"])) == n0, "#4373: an admin who never showed the key is demoted: no News item")
assert show(S["carol"], ORG).ok
r = A.put(B + f"/api/orgs/{ORG}/members", json={"user_id": uid["carol"], "role": "member"})
check(r.ok and any(x["data"].get("by_name") == "Carol Person" for x in renew(S["dave"])),
      "#4373: an admin who showed the key is demoted: News for the others " + r.text[:100])
assert show(S["dave"], ORG).ok
r = S["dave"].delete(B + f"/api/orgs/{ORG}/members/{uid['dave']}")
check(r.ok and any(x["data"].get("by_name") == "Dave Person" for x in renew(A)), "#4373: ... leaves on their own: News " + r.text[:100])
check(not any(x["data"].get("by_name") == "Dave Person" for x in renew(S["carol"])), "#4373: a former admin gets none")
# locked
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "erin-box@example.com", "role": "admin"}).ok
assert show(S["erin"], ORG).ok
r = A.patch(B + f"/api/users/{uid['erin']}", json={"disabled": True})
check(r.ok and any(x["data"].get("by_name") == "Erin Person" for x in renew(A)), "#4373: ... is locked: News " + r.text[:100])
assert A.patch(B + f"/api/users/{uid['erin']}", json={"disabled": False}).ok
# a person without an organisation: her own office, no News
r = Fr.post(B + "/api/orgs/0/encryption/recovery", json={"password": "password123"})
check(r.status_code in (200, 404) and not renew(Fr), f"freelancer: the own office's recovery key as before, no News {r.status_code}")

# ================================================================ #4374 self-hosted: unchanged
CARL_AV = photo(S["carl"])
FR_AV = photo(Fr)
users = {u["id"]: u for u in A.get(B + "/api/users?all=1").json()["users"]}
check(users[uid["carl"]].get("email") == "carl-box@example.com" and users[uid["carl"]].get("orgs") == [CO]
      and "twofa" in users[uid["carl"]] and users[uid["carl"]].get("display_name") == "Carl Person" and not users[uid["carl"]].get("apart"),
      f"self-hosted: the whole list carries every field (as before) {users[uid['carl']]}")
j = page(A, "carl-box")
check(j["total"] == 1 and j["users"][0]["id"] == uid["carl"] and j["users"][0].get("email"), "self-hosted: the search finds an e-mail address (as before)")
check(A.get(B + CARL_AV).status_code == 200, "self-hosted: the instance admin sees the photo (as before)")
check(Fr.get(B + "/api/users").ok and Fr.get(B + FR_AV).status_code == 200, "self-hosted: the freelancer's list and own photo")

# ================================================================ #4374 hosted (KEEP=1)
kt.fresh(env={**ENV, "KALMIDO_HOSTED": "1"}, keep=True)
A = sess("alice")
S = {u: login(B, u) for u in uid}
Fr = login(B, "frida")
for whole in (True, False):
    users = {u["id"]: u for u in (A.get(B + "/api/users?all=1").json()["users"] if whole else page(A)["users"])}
    what = "whole list" if whole else "page"
    cu = users[uid["carl"]]
    check(cu.get("apart") is True and set(cu) <= BRIEF and cu.get("display_name") == "carl" and cu.get("avatar") == ""
          and cu.get("org_count") == 1 and "storage" in cu and cu.get("disabled") is False,
          f"#4374 hosted ({what}): a client's account is reduced to id, user name, lock, storage, number of organisations {cu}")
    blob = str(cu)
    check("carl-box" not in blob and "Carl Person" not in blob and "orgs" not in cu and "twofa" not in cu and "has_password" not in cu
          and "oidc_linked" not in cu, f"#4374 hosted ({what}): no e-mail, name, sign-in methods or organisation ids")
    fu = users[FID]
    check(fu.get("apart") is True and "email" not in fu and fu.get("org_count") == 0, f"#4374 hosted ({what}): the freelancer is a client too {fu}")
    mu = users[uid["mia"]]
    check(not mu.get("apart") and mu.get("email") == "mia-box@example.com" and ORG in mu.get("orgs", []),
          f"#4374 hosted ({what}): a member of the operator's own organisation stays complete")
j = page(A, "carl-box")
check(j["total"] == 0 and not j["users"], f"#4374 hosted: the search does not find a client by its e-mail address {j['total']}")
check(page(A, "Carl Person")["total"] == 0, "#4374 hosted: ... nor by its name")
j = page(A, "carl")
check(j["total"] == 1 and j["users"][0]["id"] == uid["carl"] and "email" not in j["users"][0], "#4374 hosted: ... by its user name, reduced")
j = page(A, "mia-box")
check(j["total"] == 1 and j["users"][0].get("email"), "#4374 hosted: the own organisation's people by their e-mail address")
check(A.get(B + CARL_AV).status_code == 404, "#4374 hosted: a client's photo answers 404 to the operator")
check(S["carl"].get(B + CARL_AV).status_code == 200 and Fr.get(B + FR_AV).status_code == 200, "#4374 hosted: the owner sees the own photo")
r = A.patch(B + f"/api/users/{FID}", json={"disabled": False})
check(r.ok and "email" not in r.json() and r.json().get("apart") is True, "#4374 hosted: the answer of a change is reduced too " + r.text[:160])
r = S["carl"].post(B + "/api/support-access", json={"hours": 24})
check(r.ok, "carl grants support access " + r.text[:100])
j = page(A, "carl-box")
check(j["total"] == 1 and j["users"][0].get("email") == "carl-box@example.com" and j["users"][0].get("support_until"),
      f"#4374 hosted: with a support grant the account is complete and found by its address {j['users'][:1]}")
check(Fr.get(B + "/api/users").ok, "freelancer: her own list on the hosted instance")

sys.exit(kt.done("p2539_a_admin"))
