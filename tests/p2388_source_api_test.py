#!/usr/bin/env python3
# kalmido-suite:
"""2.388.0 API tests (#3341): a chat message of an agent carries a source, own container (start.sh).
 - POST /api/v1/agent/chats/{uid}: source is stored and comes back in the answer, the agent's list and the app's chat
 - without the field: null as before; also on a notice and in a multipart message
 - not a short lower-case name -> 400 and no message
 - a person without an organisation: the same with their own agent
usage: p2388_source_api_test.py <datadir>      (KMT_NOSTART=1: a running server)"""
import sys

import requests

from freelancer_fixture import freelancer
from kt import B, H, check, done, fresh, sess

V = B + "/api/v1"
fresh(prefix="P2388")
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"org_name": "Kalmido", "lang": "en", "collab_all": True, "modules": ["comments"]})
A.patch(B + "/api/settings", json={"lang": "en"})
me = A.get(B + "/api/state").json()["me"]
ag = A.post(B + "/api/admin/agents", json={"scopes": ["read", "tasks:write", "comments"], "username": "devbot", "display_name": "Dev Bot"}).json()
AID, TOK = ag["id"], ag["token"]
A.patch(B + f"/api/admin/agents/{AID}", json={"org_id": me["workspaces"][0]["id"]})
L = A.post(B + "/api/lists", json={"name": "Work", "org_id": me["workspaces"][0]["id"]}).json()["id"]
A.put(B + f"/api/lists/{L}/members", json={"user_id": AID, "role": "edit"})
HA = {"Authorization": "Bearer " + TOK}


def say(body, tok=None, uid=None, **kw):
    return requests.post(V + f"/agent/chats/{uid or me['id']}", headers={"Authorization": "Bearer " + (tok or TOK)}, json={"body": body, **kw})


def app_msg(mid):
    return next(m for m in A.get(B + f"/api/agents/{AID}/chat").json()["messages"] if m["id"] == mid)


r = say("Dispatcher: three jobs started", source="dispatcher")
check(r.status_code == 201 and r.json()["source"] == "dispatcher", f"source comes back in the answer {r.status_code} {r.text[:200]}")
mid = r.json()["id"]
check(app_msg(mid)["source"] == "dispatcher", "the app's chat delivers the source")
r = say("A plain answer")
check(r.status_code == 201 and r.json()["source"] is None, "without the field: source null")
check(app_msg(r.json()["id"])["source"] is None, "without the field: null in the app's chat")
r = say("One grey line", kind="notice", source="dispatcher")
check(r.status_code == 201 and r.json()["kind"] == "notice" and r.json()["source"] == "dispatcher", f"a notice keeps its source {r.status_code} {r.text[:200]}")
r = requests.post(V + f"/agent/chats/{me['id']}", headers=HA, data={"body": "With a file", "source": "dispatcher"}, files={"file": ("a.txt", b"x", "text/plain")})
check(r.status_code == 201 and r.json()["source"] == "dispatcher", f"multipart: source stored {r.status_code} {r.text[:200]}")
n0 = len(A.get(B + f"/api/agents/{AID}/chat").json()["messages"])
for bad in ("Dispatcher", "1x", "a b", "x" * 25, 5, ["dispatcher"]):
    r = say("never", source=bad)
    check(r.status_code == 400, f"invalid source {bad!r}: 400, got {r.status_code}")
check(len(A.get(B + f"/api/agents/{AID}/chat").json()["messages"]) == n0, "an invalid source posts nothing")
r = say("Empty source", source="")
check(r.status_code == 201 and r.json()["source"] is None, "an empty source counts as none")
r = requests.get(V + "/openapi.json")
if r.ok:
    check("source" in r.text, "the API description names source")

# a person without an organisation, their own agent
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
FU, F = freelancer(B, A)
fa = F.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida Bot", "scopes": ["read", "tasks:write", "comments"]}).json()
ft = fa.get("token") or F.post(B + f"/api/my/agents/{fa['id']}/token", json={}).json()["token"]
r = say("Dispatcher: one job started", tok=ft, uid=FU, source="dispatcher")
check(r.status_code == 201 and r.json()["source"] == "dispatcher", f"without an organisation: source stored {r.status_code} {r.text[:200]}")
m = next(x for x in F.get(B + f"/api/agents/{fa['id']}/chat").json()["messages"] if x["id"] == r.json()["id"])
check(m["source"] == "dispatcher", "without an organisation: delivered in the app's chat")
sys.exit(done("p2388_source_api"))
