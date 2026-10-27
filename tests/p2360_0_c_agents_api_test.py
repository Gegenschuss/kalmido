#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.360.0 part C (#2496, after-audit hardening: agents / API and integrations), own container (start.sh).
 - a read-only agent token: its own jobs stay open, but no job for a person (user_id) and none that waits for one (state
   waiting), no withdrawing of answer buttons (403, required_scope comments); an agent with comments may
 - dispo: other people's bookings are changed / deleted / restored only by an admin of the area; the own ones as before;
   a freelancer edits own bookings
 - leave: an open vacation request of a member keeps its kind (409), an approved one may become a day off
 - hub mail of a client: moved / deleted by its recipient, the client's creator or an organisation admin, not by every
   member who sees the client
 - an approved request replays with the token that asked: that token gone = the request does not run (not with the
   agent's newest token)
 - browser error reports: at most 3 new tickets per person and hour, more are only counted; another person still makes one
 - an agent ruled by office groups suggests receipts only with the receipts area (no group row: as before)
usage: p2360_0_c_agents_api_test.py <datadir>"""
import os
import subprocess
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import dbx as dbxm  # noqa: E402
from freelancer_fixture import FEATURES, freelancer, org_join  # noqa: E402

from kt import FAILS, OKS, check, sess, B, H, DATA  # noqa: E402
V = B + "/api/v1"


def dbx(sql, args=(), write=False):
    c = dbxm.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall() if not write else None
        if write:
            c.execute(sql, args)
            c.commit()
        return r
    finally:
        c.close()


def hdr(token):
    return {"Authorization": "Bearer " + token, "X-Requested-With": "kalmido"}


def need(r, scope):
    return r.status_code == 403 and ((r.json().get("error") or {}).get("required_scope") == scope)


if not os.environ.get("P23600C_NOSTART"):
    subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], check=True, stdout=subprocess.DEVNULL)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["agents", "comments"]})
ids = {}
for u in ("bob", "carol", "erin"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
BOB, CAROL, ERIN = ids["bob"], ids["carol"], ids["erin"]
r = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": BOB})
assert r.status_code == 201, r.text
ORG = r.json()["id"]
Bo = sess("bob")
check(Bo.put(B + f"/api/orgs/{ORG}/members", json={"email": "carol@example.com"}).ok and org_join(B, "carol", ORG), "setup: carol joins Alpha")
dbx("DELETE FROM org_members WHERE org_id=? AND user_id NOT IN (?,?)", (ORG, BOB, CAROL), write=True)
Bo, Ca, Er = sess("bob"), sess("carol"), sess("erin")
for s in (A, Bo, Ca, Er):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEATURES, "tour": "done"})
FID, Fr = freelancer(B, A)

# ================================================================ 1. read-only tokens: jobs for a person
r = A.post(B + "/api/admin/agents", json={"scopes": ["read"], "username": "reader", "display_name": "Reader"})
assert r.ok, r.text
ROH = hdr(r.json()["token"])
# claude: alice's personal agent (it shares with her, she approves its requests)
check(A.put(B + "/api/admin/agent-policy", json={"user_agents": True}).ok, "setup: personal agents on")
r = A.post(B + "/api/my/agents", json={"scopes": ["read", "tasks:write", "comments", "structure", "delete"], "username": "claude",
                                       "display_name": "Claude", "org_id": "private"})
assert r.ok, r.text
CL, CLT = r.json()["id"], r.json()["token"]
CLH = hdr(CLT)
r = requests.post(V + "/agent/jobs", headers=ROH, json={"title": "Reading the backlog"})
check(r.status_code == 201, f"read-only agent: its own job stays open ({r.status_code} {r.text[:150]})")
J = r.json().get("id") if r.ok else 0
r = requests.patch(V + f"/agent/jobs/{J}", headers=ROH, json={"append_log": "half way"})
check(r.ok, f"read-only agent: its job log stays open ({r.status_code} {r.text[:150]})")
r = requests.post(V + "/agent/jobs", headers=ROH, json={"title": "For Alice", "user_id": 1})
check(need(r, "comments"), f"read-only agent: no job for a person ({r.status_code} {r.text[:150]})")
r = requests.post(V + "/agent/jobs", headers=ROH, json={"title": "Waiting", "state": "waiting"})
check(need(r, "comments"), f"read-only agent: no waiting job ({r.status_code} {r.text[:150]})")
r = requests.patch(V + f"/agent/jobs/{J}", headers=ROH, json={"state": "waiting"})
check(need(r, "comments"), f"read-only agent: its job does not start waiting ({r.status_code} {r.text[:150]})")
r = requests.post(V + "/agent/chats/1/messages/1/withdraw", headers=ROH, json={})
check(need(r, "comments"), f"read-only agent: no withdraw ({r.status_code} {r.text[:150]})")
r = requests.post(V + "/agent/jobs", headers=CLH, json={"title": "For Alice", "user_id": 1, "state": "waiting"})
check(r.status_code == 201, f"an agent with comments: a waiting job for a person as before ({r.status_code} {r.text[:150]})")

# ================================================================ 5. replay with the token that asked
r = requests.post(V + "/lists", headers=CLH, json={"name": "Agent scratch"})
check(r.status_code == 201, "setup: the agent's own list " + r.text[:120])
AL = r.json().get("id")
check(requests.patch(V + f"/lists/{AL}", headers=CLH, json={"archived": True}).ok, "setup: the agent archives it")
r = requests.delete(V + f"/lists/{AL}", headers=CLH)
check(r.status_code == 202 and r.json().get("job", {}).get("state") == "waiting", f"deleting a list waits for an approval ({r.status_code} {r.text[:150]})")
JA = (r.json().get("job") or {}).get("id")
# a second, newer token of the same agent (another computer), then the asking one is revoked
dbx("INSERT INTO api_tokens(user_id,name,token_hash,prefix,scopes,created_at) VALUES(?,?,?,?,?,?)",
    (CL, "Second computer", "f" * 64, "abk_second", "read,tasks:write,comments,structure,delete", "2026-10-26T10:00:00Z"), write=True)
dbx("DELETE FROM api_tokens WHERE user_id=? AND prefix=?", (CL, CLT[:12]), write=True)
r = A.post(B + f"/api/agents/jobs/{JA}/action", json={"action": "approve"})
check(r.ok and r.json().get("state") == "failed", f"the asking token is gone: the approved request does not run ({r.status_code} {r.text[:200]})")
check(dbx("SELECT COUNT(*) FROM lists WHERE id=? AND deleted_at IS NULL", (AL,))[0][0] == 1, "the list is still there (no replay with the newest token)")

# ================================================================ 2a. dispo: other people's bookings only by an admin
DAY = "2026-11-17"


def book(s, title, rid):
    r = s.post(B + "/api/team/dispo/bookings", json={"title": title, "start": DAY, "status": "option", "resources": [{"kind": "user", "id": rid}]})
    assert r.status_code == 201, r.text
    return r.json()["bookings"][0]["id"]


bb = book(Bo, "Bob's shoot", CAROL)
bc = book(Ca, "Carol's shoot", BOB)
check(Ca.patch(B + f"/api/team/dispo/bookings/{bc}", json={"title": "Carol's shoot day"}).ok, "carol changes her own booking")
r = Ca.patch(B + f"/api/team/dispo/bookings/{bb}", json={"title": "taken over"})
check(r.status_code == 403, f"carol (member) cannot change bob's booking ({r.status_code})")
check(Ca.patch(B + f"/api/team/dispo/bookings/{bb}", json={"status": "firm", "all": True}).status_code == 403, "... nor its whole job")
check(Ca.delete(B + f"/api/team/dispo/bookings/{bb}").status_code == 403, "carol cannot delete bob's booking")
check(dbx("SELECT title, deleted_at FROM hub_bookings WHERE id=?", (bb,))[0] == ("Bob's shoot", None), "bob's booking unchanged")
# 2.360.0 R (#2496, review): a job with a colleague's booking: carol's change of the whole job changes her own, skips bob's
dbx("UPDATE hub_bookings SET job=(SELECT job FROM hub_bookings WHERE id=?) WHERE id=?", (bc, bb))
r = Ca.patch(B + f"/api/team/dispo/bookings/{bc}", json={"note": "bring the lamp", "all": True})
check(r.ok and r.json().get("skipped") == 1 and [x["id"] for x in r.json().get("bookings", [])] == [bc],
      f"#2496 R: the whole job: her own booking changes, bob's is skipped ({r.status_code} {r.text[:200]})")
check(dbx("SELECT note FROM hub_bookings WHERE id=?", (bc,))[0][0] == "bring the lamp" and dbx("SELECT note FROM hub_bookings WHERE id=?", (bb,))[0][0] == "",
      "#2496 R: bob's booking keeps its note")
check(Bo.patch(B + f"/api/team/dispo/bookings/{bc}", json={"status": "firm"}).ok, "bob (admin) changes carol's booking")
r = Bo.delete(B + f"/api/team/dispo/bookings/{bb}")
check(r.ok, "bob deletes his own booking")
check(Ca.post(B + "/api/team/dispo/bookings/restore", json={"ids": r.json().get("ids", [])}).status_code == 403, "carol cannot restore bob's booking")
check(Bo.post(B + "/api/team/dispo/bookings/restore", json={"ids": r.json().get("ids", [])}).json().get("restored") == 1, "bob restores it")
r = Ca.delete(B + f"/api/team/dispo/bookings/{bc}")
check(r.ok and Ca.post(B + "/api/team/dispo/bookings/restore", json={"ids": r.json().get("ids", [])}).json().get("restored") == 1,
      "carol deletes and restores her own booking")
# a freelancer: their own area, they are its admin
r = Fr.post(B + "/api/team/dispo/bookings", json={"title": "Solo shoot", "start": DAY, "resources": [{"kind": "user", "id": FID}]})
check(r.status_code == 201, "freelancer: books in the own area " + r.text[:150])
fb = r.json()["bookings"][0]["id"] if r.status_code == 201 else 0
check(Fr.patch(B + f"/api/team/dispo/bookings/{fb}", json={"title": "Solo shoot 2"}).ok and Fr.delete(B + f"/api/team/dispo/bookings/{fb}").ok,
      "freelancer: changes and deletes the own booking")

# ================================================================ 2b. leave: an open request keeps its kind
check(Bo.put(B + "/api/team/leave/approval", json={"on": True}).ok, "setup: approvals on in Alpha")
r = Ca.post(B + "/api/team/absences", json={"kind": "vacation", "start_date": "2027-05-03", "end_date": "2027-05-07"})
check(r.status_code == 201 and r.json()["status"] == "pending", "carol's vacation is a request " + r.text[:150])
REQ = r.json()["id"]
r = Ca.patch(B + f"/api/team/absences/{REQ}", json={"kind": "off"})
check(r.status_code == 409, f"an open request does not become an approved day off ({r.status_code} {r.text[:150]})")
st = dbx("SELECT status FROM hub_absences WHERE id=?", (REQ,))
check(st and st[0][0] == "pending", f"still a request ({st})")
check(Bo.post(B + f"/api/team/absences/{REQ}/decide", json={"action": "reject"}).ok, "setup: bob rejects it")
check(Ca.patch(B + f"/api/team/absences/{REQ}", json={"kind": "other"}).status_code == 409, "a rejected request keeps its kind too")
r = Ca.post(B + "/api/team/absences", json={"kind": "vacation", "start_date": "2027-06-07", "end_date": "2027-06-07"})
R2 = r.json()["id"]
check(Bo.post(B + f"/api/team/absences/{R2}/decide", json={"action": "approve"}).ok, "setup: another request approved")
r = Ca.patch(B + f"/api/team/absences/{R2}", json={"kind": "off"})
check(r.ok and r.json()["status"] == "approved", f"an approved vacation may become a day off ({r.status_code} {r.text[:150]})")
r = Ca.post(B + "/api/team/absences", json={"kind": "off", "start_date": "2027-07-05", "end_date": "2027-07-05"})
check(r.status_code == 201 and r.json()["status"] == "approved", "a new day off needs no approval (as before)")

# ================================================================ 2c. a client's mails: recipient, the client's creator, admins
CB = Bo.post(B + "/api/clients", json={"name": "Acme", "org_id": ORG, "email": "acme@example.com"}).json()["id"]
CC = Ca.post(B + "/api/clients", json={"name": "Carol's client", "org_id": ORG, "email": "cc@example.com"}).json()["id"]


def hub_mail(owner, cid, n):
    dbx("INSERT INTO hub_mails(org_id,owner_id,client_id,ws,message_id,created_at) VALUES(?,?,?,?,?,?)",
        (ORG, owner, cid, f"o{ORG}", f"<p2360c-{n}@example.com>", "2026-10-26T10:00:00Z"), write=True)
    return dbx("SELECT id FROM hub_mails WHERE message_id=?", (f"<p2360c-{n}@example.com>",))[0][0]


m1 = hub_mail(BOB, CB, 1)
check(Ca.get(B + f"/api/hubmail/mails/{m1}").ok, "carol sees Acme's mail (she sees the client)")
check(Ca.get(B + f"/api/hubmail/mails/{m1}").json().get("can_write") is False, "... without the write right")
check(Ca.delete(B + f"/api/hubmail/mails/{m1}").status_code == 403, "carol cannot delete Acme's mail")
check(Ca.post(B + f"/api/hubmail/mails/{m1}/assign", json={"client_id": CC}).status_code == 403, "carol cannot move it to another client")
check(dbx("SELECT client_id, deleted_at FROM hub_mails WHERE id=?", (m1,))[0] == (CB, None), "Acme's mail unchanged")
m2 = hub_mail(BOB, CC, 2)  # filed by bob with carol's client
check(Ca.delete(B + f"/api/hubmail/mails/{m2}").ok, "carol (the client's creator) deletes its mail")
check(Ca.post(B + f"/api/hubmail/mails/{m2}/restore").ok, "... and restores it")
m3 = hub_mail(CAROL, CB, 3)  # carol is the recipient
check(Ca.post(B + f"/api/hubmail/mails/{m3}/assign", json={"client_id": CC}).ok, "carol moves a mail she received")
check(Bo.delete(B + f"/api/hubmail/mails/{m1}").ok, "bob (admin) deletes Acme's mail")

# ================================================================ 7. browser error reports: new tickets per person
P = A.post(B + "/api/lists", json={"name": "Kalmido errors", "kind": "project"}).json()["id"]
check(A.patch(B + f"/api/lists/{P}/error-hook", json={"state": "on"}).ok, "setup: error reports on")
check(A.patch(B + "/api/admin/settings", json={"client_errors_list": P}).ok, "setup: browser reports go there")


def tickets():
    return dbx("SELECT COUNT(*) FROM tasks WHERE list_id=? AND deleted_at IS NULL", (P,))[0][0]


n0 = tickets()
for i in range(4):
    check(Er.post(B + "/api/client-errors", json={"msg": f"TypeError: step {chr(65 + i)} failed", "src": "/static/js/render.js",
                                                    "line": 10 + i, "col": 1, "ver": "2.360.0", "view": "tasks"}).status_code == 204, f"erin reports {i}")
check(tickets() == n0 + 3, f"erin: at most 3 new tickets an hour ({tickets() - n0})")
cnt = dbx("SELECT COUNT(*) FROM issue_reports WHERE list_id=? AND task_id IS NULL", (P,))[0][0]
check(cnt == 1, f"the fourth is only counted ({cnt})")
Bo.post(B + "/api/client-errors", json={"msg": "RangeError: other place", "src": "/static/js/core.js", "line": 99, "col": 1})
check(tickets() == n0 + 4, "another person still makes a new ticket")

# ================================================================ 8. receipt suggestions follow the office groups
r = A.post(B + "/api/admin/agents", json={"scopes": ["read", "files:read"], "username": "bookkeeper", "display_name": "Bookkeeper"})
assert r.ok, r.text
BK, BKH = r.json()["id"], hdr(r.json()["token"])
r = requests.post(V + "/documents/999999/receipt-suggestion", headers=BKH, json={"category": "travel"})
check(r.status_code == 404, f"an unknown document stays 404 ({r.status_code})")
check(r.status_code != 500, "no server error")

print(f"p2360_0_c_agents_api: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
sys.exit(1 if FAILS else 0)
