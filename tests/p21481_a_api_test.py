#!/usr/bin/env python3
"""2.148.1 API tests, part A (#2478 #2480 #2486 #2490): memberships, invitations, public links, names. Own container (start.sh).
Invented people only (example.com).
tenant-matrix: org
freelancer-matrix: own
 - #2480 an organisation admin (not the server's admin) who adds an existing account by e-mail or id only invites it: the
   person is a member after POST /api/orgs/<oid>/join (DELETE declines); only the invited person answers (others 404); the
   answer to the admin is the same for every address; the server's admin still adds directly; a person without an
   organisation can accept an invitation too
 - #2480 a new list without org_id is private unless the workspace switch shows an organisation
 - #2480 the organisation admins act only on shared lists of the organisation (also in the list trash); a removed member's
   lists go to the admin, logged, and the person is told
 - #2478 an owner change gives the public link a new token (the old one: 404) and switches the deploy webhook off; the new
   owner is told; a freelancer's own public link stays; the account export takes notepads only from lists one still sees
 - #2486 an organisation admin never gets the invitation link (no mail on this server), the server's admin does; resend
   at most three times a day per invitation
 - #2490 a mention of an account the writer may not see becomes '@?'; adding an unseen account to a channel names nobody;
   sharing a table by address answers the same without a share list; no support address = none (not an admin's)
usage: p21481_a_api_test.py <datadir>      (P21481A_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)"""
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import FEATURES, freelancer  # noqa: E402

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


def member(oid, uid):
    return bool(dbx("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (oid, uid)))


def news_kinds(s):
    return [x["kind"] for x in s.get(B + "/api/news?limit=50").json().get("items", [])]


def news_of(s, kind):
    return [x for x in s.get(B + "/api/news?limit=50").json().get("items", []) if x["kind"] == kind]


def pub_token(s, lid):
    r = s.put(B + f"/api/lists/{lid}/public-link", json={"mode": "view"})
    assert r.ok, r.text
    return r.json()["link"]["url"].split("/s/", 1)[1]


if not os.environ.get("P21481A_NOSTART"):
    e = dict(os.environ, EXTRA=os.environ.get("EXTRA", "") + " -e KALMIDO_INSTANCE_MODE=workspaces")
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=e, check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
ids = {}
for u in ("bob", "carol", "dave", "erin"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com", "orgs": []})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, DAVE, ERIN = ids["bob"], ids["carol"], ids["dave"], ids["erin"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB}).json()["id"]
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": ERIN}).json()["id"]
ORG3 = A.post(B + "/api/admin/orgs", json={"name": "Gamma"}).json()["id"]
dbx("DELETE FROM org_members WHERE NOT ((org_id=? AND user_id=?) OR (org_id=? AND user_id=?))", (ORG, BOB, ORG2, ERIN), write=True)
dbx("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'admin') ON CONFLICT DO NOTHING", (ORG3, 1), write=True)
FID, Fr = freelancer(B, A)
Bo, Ca, Da, Er = sess("bob"), sess("carol"), sess("dave"), sess("erin")
A = sess("alice")
for s in (Bo, Ca, Da, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES + ",sheets", "tour": "done"})

# ---- rollback: a new table only
check(dbx("SELECT 1 FROM information_schema.tables WHERE table_name='org_joins'"), "new table org_joins")

# ================================================================ #2480 joining needs the person's yes
r = Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com"})
r2 = Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "nobody@example.com"})
check(r.ok and r.json() == r2.json() == {"ok": True, "by_email": True}, "membership by address: the same answer for any address " + r.text[:200] + r2.text[:200])
check(not member(ORG, CAROL), "membership needs acceptance: not a member yet")
j = Ca.get(B + "/api/orgs").json()
check([x["org_id"] for x in j.get("joins", [])] == [ORG] and j["joins"][0]["name"] == "Alpha" and j["joins"][0]["role"] == "member",
      "the invited person sees the open invitation " + str(j.get("joins")))
check("orgjoin" in news_kinds(Ca), "the invitation is in the person's News")
check(Da.post(B + f"/api/orgs/{ORG}/join").status_code == 404 and Bo.post(B + f"/api/orgs/{ORG}/join").status_code == 404,
      "only the invited person answers (others 404)")
check(Ca.delete(B + f"/api/orgs/{ORG}/join").ok and Ca.get(B + "/api/orgs").json().get("joins") == [], "declined: no open invitation")
check(Ca.post(B + f"/api/orgs/{ORG}/join").status_code == 404 and not member(ORG, CAROL), "... and accepting it later: 404")
check("orgjoin" not in news_kinds(Ca), "a declined invitation leaves the News")
Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com", "role": "admin"})
r = Ca.post(B + f"/api/orgs/{ORG}/join")
check(r.ok and member(ORG, CAROL) and dbx("SELECT role FROM org_members WHERE org_id=? AND user_id=?", (ORG, CAROL))[0][0] == "admin",
      "accepted: a member in the invited role " + r.text[:200])
check(Bo.put(B + f"/api/orgs/{ORG}/members", json={"user_id": CAROL, "role": "member"}).ok
      and dbx("SELECT role FROM org_members WHERE org_id=? AND user_id=?", (ORG, CAROL))[0][0] == "member", "a member's role changes as before")
# the invitation way: the same answer for an existing and a new address
r = Bo.post(B + f"/api/orgs/{ORG}/invites", json={"email": "dave@example.com"})
r2 = Bo.post(B + f"/api/orgs/{ORG}/invites", json={"email": "newbie@example.com"})
check(r.ok and r2.ok and set(r.json()) - {"notice"} == set(r2.json()) - {"notice"} == {"ok", "by_email", "invites"},
      "invitations: no 'invited' / 'user_id' in the answer " + r.text[:200] + " | " + r2.text[:200])
check("user_id" not in r2.json() and "#invite/" not in r2.text, "invitations: no account id, no link")
check(not member(ORG, DAVE) and Da.post(B + f"/api/orgs/{ORG}/join").ok and member(ORG, DAVE), "an existing account joins after accepting")
# the server's admin adds directly
check(A.put(B + f"/api/orgs/{ORG3}/members", json={"email": "erin@example.com"}).ok and member(ORG3, ERIN), "the server's admin adds directly")
# a person without an organisation accepts an invitation the same way (freelancer-matrix: own)
GID, Gi = freelancer(B, A, "gina")
Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "gina@example.com"})
check(not member(ORG, GID) and [x["org_id"] for x in Gi.get(B + "/api/orgs").json().get("joins", [])] == [ORG], "freelancer: the invitation waits")
check(Gi.post(B + f"/api/orgs/{ORG}/join").ok and member(ORG, GID), "freelancer: joins by accepting")
check(Fr.post(B + f"/api/orgs/{ORG}/join").status_code == 404 and Fr.delete(B + f"/api/orgs/{ORG}/join").status_code == 404,
      "freelancer without an invitation: 404")

# ---- the default workspace of a new list
Ca, Er = sess("carol"), sess("erin")
check(Ca.post(B + "/api/lists", json={"name": "Only org"}).json().get("org_id") == ORG, "one organisation: a new list is its list")
check(Er.post(B + "/api/lists", json={"name": "No choice"}).json().get("org_id") is None, "several organisations, none chosen: private")
Er.patch(B + "/api/settings", json={"workspace": f"org:{ORG3}"})
check(Er.post(B + "/api/lists", json={"name": "Chosen"}).json().get("org_id") == ORG3, "several organisations: the one chosen in the switch")
Er.patch(B + "/api/settings", json={"workspace": "all"})
check(Fr.post(B + "/api/lists", json={"name": "Free"}).json().get("org_id") is None, "freelancer: a new list is private")

# ---- the organisation admins act only on shared lists
U = Ca.post(B + "/api/lists", json={"name": "Carol alone", "org_id": ORG}).json()["id"]
S = Ca.post(B + "/api/lists", json={"name": "Carol shared", "org_id": ORG}).json()["id"]
check(Ca.put(B + f"/api/lists/{S}/members", json={"user_id": DAVE, "role": "edit"}).ok, "setup: shared with dave")
ov = [x["id"] for x in Bo.get(B + f"/api/orgs/{ORG}/lists").json()["lists"]]
check(S in ov and U not in ov, "the overview shows only shared lists")
check(Bo.post(B + f"/api/orgs/{ORG}/lists/{U}/archive", json={"archived": True}).status_code == 404, "an unshared list by id: 404")
check(Bo.post(B + f"/api/orgs/{ORG}/lists/{U}/owner", json={"user_id": BOB}).status_code == 404, "... no takeover either")
check(Bo.post(B + f"/api/orgs/{ORG}/lists/{S}/archive", json={"archived": True}).ok, "a shared list: archived by the admin")
Bo.post(B + f"/api/orgs/{ORG}/lists/{S}/archive", json={"archived": False})
T = Ca.post(B + "/api/lists", json={"name": "Carol trash", "org_id": ORG}).json()["id"]
Ca.patch(B + f"/api/lists/{T}", json={"archived": True})
check(Ca.delete(B + f"/api/lists/{T}").ok, "setup: an unshared list in the trash")
check(T not in [x["id"] for x in Bo.get(B + "/api/trash/lists").json()["lists"]] and Bo.post(B + f"/api/trash/lists/{T}/restore").status_code == 404,
      "the list trash: an unshared list stays the owner's")
check(T in [x["id"] for x in Ca.get(B + "/api/trash/lists").json()["lists"]], "... the owner sees it")

# ================================================================ #2478 secrets of a list on an owner change
P = Ca.post(B + "/api/lists", json={"name": "Carol project", "org_id": ORG, "kind": "project"}).json()["id"]
Ca.patch(B + f"/api/lists/{P}", json={"ptype": "software"})
TOK = pub_token(Ca, P)
check(requests.get(B + "/s/" + TOK).status_code == 200, "setup: the public link works")
r = Ca.post(B + f"/api/lists/{P}/envs", json={"name": "Live"})
EID = r.json().get("id") if r.ok else None
r = Ca.patch(B + f"/api/envs/{EID}", json={"hook": "on"})
HOOK = (r.json().get("url") or "").split("/api/hooks/deploy/", 1)[-1] if r.ok else ""
check(HOOK and requests.post(B + "/api/hooks/deploy/" + HOOK, json={"version": "1.0"}).status_code == 201, "setup: the deploy webhook works " + r.text[:200])
check(Ca.post(B + f"/api/lists/{P}/notepads", json={"title": "Pad", "body": "carol wrote"}).ok, "setup: a notepad")
check(any(x["list_id"] == P for x in Ca.get(B + "/api/export.json").json()["list_notepads"]), "setup: the notepad is in carol's export")
# carol is removed from the organisation: her lists go to bob
r = Bo.delete(B + f"/api/orgs/{ORG}/members/{CAROL}")
check(r.ok and r.json().get("transferred", 0) >= 3, "removed: the lists go to the admin " + r.text[:200])
check(requests.get(B + "/s/" + TOK).status_code == 404, "the former member's public link: 404")
time.sleep(2.2)  # the webhook's own pace (one call per 2 s)
check(requests.post(B + "/api/hooks/deploy/" + HOOK, json={"version": "2.0"}).status_code == 403, "the former member's webhook: 403")
lk = Bo.get(B + f"/api/lists/{P}/public-link").json().get("link") or {}
check(lk.get("url") and TOK not in lk["url"] and requests.get(B + "/s/" + lk["url"].split("/s/", 1)[1]).status_code == 200,
      "the new owner has the link with a new token")
own = [x for x in news_of(Bo, "owner") if x.get("list_id") == P]
check(own and set((own[0].get("data") or {}).get("reset") or []) == {"link", "hook"}, "the new owner is told about the reset " + str(own[:1]))
check(any(x["action"] == "owner" and x["list_id"] == U for x in Bo.get(B + f"/api/orgs/{ORG}/lists").json()["log"]),
      "the handover of an unshared list is in the admins' history")
un = [x for x in news_of(Ca, "unshare") if (x.get("data") or {}).get("org")]
check(un and (un[0]["data"].get("lists") or 0) >= 3 and un[0]["data"].get("to") == "Bob", "the removed person is told where the lists went " + str(un[:1]))
check(not any(x["list_id"] == P for x in Ca.get(B + "/api/export.json").json()["list_notepads"]), "the export: no notepad of a list one no longer sees")
# a voluntary hand-over: a list owner gives a list to a member
Q = Bo.post(B + "/api/lists", json={"name": "Bob handover", "org_id": ORG}).json()["id"]
Bo.put(B + f"/api/lists/{Q}/members", json={"user_id": DAVE, "role": "edit"})
TQ = pub_token(Bo, Q)
check(Bo.post(B + f"/api/lists/{Q}/owner", json={"user_id": DAVE}).ok and requests.get(B + "/s/" + TQ).status_code == 404, "a hand-over resets the link too")
# the boundary check counts a public link made by someone without a role in the list
dbx("UPDATE public_links SET created_by=? WHERE list_id=?", (CAROL, Q), write=True)
k = A.get(B + "/api/admin/orgs").json()
check((k.get("boundary") or {}).get("kinds", {}).get("public_link_creator") == 1,
      "the boundary check counts a public link of somebody outside the list")
dbx("UPDATE public_links SET created_by=? WHERE list_id=?", (DAVE, Q), write=True)
# a freelancer's own public link of a private list stays (freelancer-matrix: own)
FL = Fr.post(B + "/api/lists", json={"name": "Freelance view"}).json()["id"]
FT = pub_token(Fr, FL)
Fr.post(B + "/api/tasks", json={"title": "Visible", "list_id": FL})
check(requests.get(B + "/s/" + FT).status_code == 200 and pub_token(Fr, FL) == FT, "freelancer: the own public link stays valid")

# ================================================================ #2486 the invitation link never to an organisation admin
r = Bo.post(B + f"/api/orgs/{ORG}/invites", json={"email": "nolink@example.com"})
check(r.ok and "#invite/" not in r.text and "invitation" not in r.json() and r.json().get("notice"), "no mail went: no link to the organisation admin " + r.text[:200])
NL = dbx("SELECT id FROM users WHERE email='nolink@example.com'")[0][0]
rs = [Bo.post(B + f"/api/orgs/{ORG}/invites/{NL}/resend") for _ in range(4)]
check(all(x.ok and "#invite/" not in x.text for x in rs[:3]) and rs[3].status_code == 429, "resend: no link, at most three a day " + str([x.status_code for x in rs]))
r = A.post(B + f"/api/orgs/{ORG3}/invites", json={"email": "adminlink@example.com"})
check(r.ok and "#invite/" in ((r.json().get("invitation") or {}).get("link") or ""), "the server's admin still gets the link " + r.text[:200])

# ================================================================ #2490 names
Ca = sess("carol")  # no longer in Alpha: sees erin (Gamma) only through nothing
CL = Ca.post(B + "/api/lists", json={"name": "Carol notes", "org_id": None}).json()["id"]
TID = Ca.post(B + "/api/tasks", json={"title": "Note", "list_id": CL}).json()["id"]
r = Ca.post(B + f"/api/tasks/{TID}/comments", json={"body": f"hello <@{ERIN}> and <@{GID}>"})
body = dbx("SELECT body FROM comments WHERE task_id=? ORDER BY id DESC LIMIT 1", (TID,))
check(r.ok and body and "@?" in body[0][0] and "Erin" not in body[0][0], "a mention of an account one may not see: '@?' " + str(body))
FT2 = Fr.post(B + "/api/tasks", json={"title": "Mine", "list_id": FL}).json()["id"]
check(Fr.post(B + f"/api/tasks/{FT2}/comments", json={"body": f"note <@{FID}>"}).ok, "freelancer: comments with a mention work")
r = Bo.post(B + "/api/team/channels", json={"name": "Alpha talk", "org_id": ORG, "members": [ERIN]})
check(not r.ok and "Erin" not in r.text, "adding an unseen account to a channel names nobody " + r.text[:200])
sh = Bo.post(B + "/api/sheets", json={"title": "Rates", "space": f"org:{ORG}"})
SID = sh.json().get("id") if sh.ok else None
r1 = Bo.post(B + f"/api/sheets/{SID}/shares", json={"email": "dave@example.com", "role": "read"})
r2 = Bo.post(B + f"/api/sheets/{SID}/shares", json={"email": "ghost@example.com", "role": "read"})
check(r1.status_code == r2.status_code == 201 and r1.json() == r2.json() == {"by_email": True}, "a table shared by address: the same answer, no list " + r1.text[:200])
check(Bo.get(B + "/api/me/storage").json().get("support") == "", "no support address set: none (not an admin's)")
check(Fr.get(B + "/api/me/storage").json().get("support") == "", "freelancer: the same")

print(f"\np21481_a_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
