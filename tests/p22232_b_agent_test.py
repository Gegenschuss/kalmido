#!/usr/bin/env python3
"""2.223.2 B (#2862) API tests, own container (start.sh): an agent's office requests act only for a person who asked it,
an organisation's agent without an office group reaches only the quotes' scope, and a member without a group ("previous
access") gets no payment suggestions through an agent. Invented people and companies only.
 (a) a team agent shared with admin A and member M: requested_by=A while only M asked -> 403; after A asked (chat) -> 200;
     a letter draft for A after A asked -> 201
 (b) a team agent without a group row (switch on): letters / payment suggestions / leads 403, services and clients 200
 (c) the personal agent of a member without a group, the agent in Bookkeeping: payment suggestions 403 (bank is for admins)
 (d) a person without an organisation, her own agent without a group row: letters, payment suggestions, leads as before
usage: p22232_b_agent_test.py <datadir>      (KMT_NOSTART=1: a running server on KALMIDO_TEST_PORT, no start.sh)
freelancer-matrix: office  tenant-matrix: office"""
import os
import subprocess
import sys
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
from kt import FAILS, OKS, check, sess  # noqa: E402
FEAT = "cal,comments,collab,office,clients,files,docs"
O = "/api/office"
R = O + "/rights"
V = B + "/api/v1/office"


def ag(h, m, path="", **kw):
    return requests.request(m, V + path, headers=h, **kw)


def team_agent(name):
    r = A.post(B + "/api/admin/agents", json={"username": name, "display_name": name.title(), "scopes": ["read", "office"]})
    assert r.ok, r.text
    aid = r.json()["id"]
    assert A.patch(B + f"/api/admin/agents/{aid}", json={"org_id": ORG}).ok
    assert A.patch(B + f"{O}/agents/{aid}", json={"office_drafts": True}).ok
    lid = A.post(B + "/api/lists", json={"name": f"Projekt {name}", "org_id": ORG}).json()["id"]
    for u, role in ((BOB, "admin"), (aid, "edit")):  # Bob a list admin: the list is open to him for its agents
        r2 = A.put(B + f"/api/lists/{lid}/members", json={"user_id": u, "role": role})
        assert r2.ok, r2.text
    return aid, {**H, "Authorization": "Bearer " + r.json()["token"]}


def chat(s, aid, text):
    r = s.post(B + f"/api/agents/{aid}/chat", json={"body": text})
    check(r.status_code in (200, 201), f"setup: a chat message to agent {aid} ({r.status_code} {r.text[:150]})")


if not os.environ.get("KMT_NOSTART"):
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    time.sleep(0.8)
s0 = requests.Session()
s0.headers.update(H)
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
A = sess("alice")
A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True, "modules": ["cal", "comments"]})
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
ALICE = A.get(B + "/api/state").json()["me"]["id"]
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
r = A.post(B + "/api/users", json={"username": "bob", "display_name": "Bob Member", "password": "password123", "email": "bob@example.com"})
assert r.ok, r.text
BOB = r.json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
Bo = sess("bob")
for s in (A, Bo):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done", "workspace": f"org:{ORG}"})
A.get(B + O + "/settings")
check(A.put(B + O + "/settings", json={"agents_read": 1}).ok, "setup: the area's privacy switch on")
CL = A.post(B + "/api/clients", json={"name": "Musterfirma GmbH", "org_id": ORG, "country": "DE"}).json()["id"]
LETTER = {"subject": "Ihre Anfrage", "body": "Vielen Dank fuer Ihre Nachricht.", "notify": False}

# ---------------------------------------------------------------- (a) requested_by only for a person who asked
TB, TH = team_agent("teambot")
check(A.put(B + f"{R}/people/{TB}", json={"groups": ["tpl:projects", "tpl:bookkeeping"]}).ok, "setup: the team agent in Project management + Bookkeeping")
chat(Bo, TB, "Bitte einen Brief an die Musterfirma vorbereiten")
r = ag(TH, "GET", "/services", params={"requested_by": ALICE})
check(r.status_code == 403 and "asked" in r.text, f"(a) requested_by = the admin who never asked: 403 ({r.status_code} {r.text[:200]})")
r = ag(TH, "POST", "/letters", json={**LETTER, "requested_by": ALICE})
check(r.status_code == 403, f"(a) a letter draft in the name of the admin, only the member asked: 403 ({r.status_code} {r.text[:200]})")
r = ag(TH, "GET", "/services", params={"requested_by": BOB})
check(r.ok, f"(a) requested_by = the member who asked: 200 ({r.status_code} {r.text[:200]})")
r = ag(TH, "POST", "/letters", json={**LETTER, "requested_by": BOB})
check(r.status_code == 403, f"(a) letters for the member: 403 (letters are for admins, as before) ({r.status_code} {r.text[:200]})")
chat(A, TB, "Bitte die Antwort an die Musterfirma entwerfen")
r = ag(TH, "GET", "/services", params={"requested_by": ALICE})
check(r.ok, f"(a) after the admin asked: 200 ({r.status_code} {r.text[:200]})")
r = ag(TH, "POST", "/letters", json={**LETTER, "requested_by": ALICE})
check(r.status_code == 201, f"(a) after the admin asked: the letter draft 201 ({r.status_code} {r.text[:200]})")
check(ag(TH, "GET", "/payment-suggestions", params={"requested_by": ALICE}).ok, "(a) the admin asked, the agent in Bookkeeping: payment suggestions 200")

# ---------------------------------------------------------------- (b) an organisation's agent without a group row
T2, T2H = team_agent("plainbot")
chat(A, T2, "Hallo")
rb = {"requested_by": ALICE}
check(ag(T2H, "GET", "", params=rb).ok, "(b) without a group row: the office overview 200")
check(ag(T2H, "GET", "/services", params=rb).ok, "(b) without a group row: services 200 (the quotes' scope)")
check(ag(T2H, "GET", "/clients", params=rb).ok, "(b) without a group row: clients 200")
check(ag(T2H, "GET", "/docs", params=rb).ok, "(b) without a group row: documents 200")
r = ag(T2H, "GET", "/letters", params=rb)
check(r.status_code == 403, f"(b) without a group row: letters 403 ({r.status_code} {r.text[:200]})")
r = ag(T2H, "POST", "/letters", json={**LETTER, **rb})
check(r.status_code == 403, f"(b) without a group row: a letter draft 403 ({r.status_code} {r.text[:200]})")
r = ag(T2H, "GET", "/payment-suggestions", params=rb)
check(r.status_code == 403, f"(b) without a group row: payment suggestions 403 ({r.status_code} {r.text[:200]})")
r = ag(T2H, "GET", "/leads", params=rb)
check(r.status_code == 403, f"(b) without a group row: leads 403 ({r.status_code} {r.text[:200]})")

# ---------------------------------------------------------------- (c) a member without a group: no bank through an agent
r = Bo.post(B + "/api/my/agents", json={"username": "bobbot", "display_name": "Bob's bot", "scopes": ["read", "office"], "org_id": ORG})
check(r.status_code == 201, "setup: bob's agent " + r.text[:200])
BAG, BH = r.json()["id"], {**H, "Authorization": "Bearer " + r.json()["token"]}
check(A.patch(B + f"{O}/agents/{BAG}", json={"office_drafts": True}).ok, "setup: bob's agent's office switch")
check(A.put(B + f"{R}/people/{BAG}", json={"groups": ["tpl:bookkeeping"]}).ok, "setup: bob's agent in Bookkeeping")
check(Bo.get(B + R).json().get("mine", {}).get("legacy") is True, "(c) bob has no group (previous access)")
check(Bo.get(B + O + "/bank/tx").status_code == 403, "(c) bob himself: bank 403")
r = ag(BH, "GET", "/payment-suggestions")
check(r.status_code == 403, f"(c) bob's agent: payment suggestions 403 ({r.status_code} {r.text[:200]})")
r = ag(BH, "POST", "/payment-suggestions", json={"invoice_id": 999999, "amount": "10.00"})
check(r.status_code == 403, f"(c) bob's agent: a payment suggestion 403 ({r.status_code} {r.text[:200]})")
check(ag(BH, "GET", "/services").ok, "(c) bob's agent: services as before")
r = ag(BH, "GET", "/services", params={"requested_by": ALICE})
check(r.status_code == 404, f"(c) a personal agent never acts for another person: 404 ({r.status_code})")

# ---------------------------------------------------------------- (d) a person without an organisation  freelancer-matrix: office
FID, Fr = freelancer(B, A, "erin", features=FEAT)
check(Fr.put(B + O + "/settings", json={"agents_read": 1}).ok, "freelancer: her privacy switch on")
r = Fr.post(B + "/api/my/agents", json={"username": "erinbot", "display_name": "Erin's bot", "scopes": ["read", "office"]})
check(r.status_code == 201, "freelancer: her agent " + r.text[:200])
FAG, FH = r.json()["id"], {**H, "Authorization": "Bearer " + r.json()["token"]}
check(Fr.patch(B + f"{O}/agents/{FAG}", json={"office_drafts": True}).ok, "freelancer: her agent's office switch")
check({p["id"]: p for p in Fr.get(B + R).json().get("people", [])}.get(FAG, {}).get("groups") == ["tpl:legacy"],
      "freelancer: her agent without a group row (previous access)")
for path in ("/letters", "/payment-suggestions", "/leads", "/services"):
    r = ag(FH, "GET", path)
    check(r.ok, f"freelancer: her own agent {path} as before ({r.status_code} {r.text[:200]})")
r = ag(FH, "POST", "/letters", json=LETTER)
check(r.status_code == 201, f"freelancer: her own agent drafts a letter ({r.status_code} {r.text[:200]})")
r = ag(TH, "GET", "/services", params={"requested_by": FID})
check(r.status_code == 404, f"tenant-matrix: office -- Alpha's agent for the freelancer: 404 ({r.status_code})")
r = ag(FH, "GET", "/services", params={"requested_by": ALICE})
check(r.status_code == 404, f"tenant-matrix: office -- her agent for Alpha's admin: 404 ({r.status_code})")

print(f"\np22232_b_agent: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
