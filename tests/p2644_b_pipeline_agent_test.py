#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.644.0 B (#3663): agents read and add inquiries and deals of the sales pipeline and set a deal's stage, the leads' way
(scope office, the office switches, acting only for an admin of the office area). Own container (kt.fresh). Invented
companies, people and figures only.
 - switches: without the agent's office switch, without an office group, without the area's privacy switch, without the
   scope office: 403; acting for a member of the office: refused
 - list: inquiries and deals with value / probability / updated_at, never leads; ?stage= one stage or open; a lead as stage 400
 - add: stage inquiry by default (preset 20 %), source agent, a client of the area; a lead stage, another area's client,
   an unknown field 400
 - set the stage: expect_updated_at required (400), an old version 409 with the deal under current, the person's change
   stays; offer 50 %, lost 0 % with lost_reason; a lead 409; another field 400; every request in the office log (target deals)
 - another organisation's deal 404 and not listed (tenant-matrix: office)
 - a person without organisation: her own agent lists, adds and sets the stage in her personal office; another person's
   agent never reaches it (freelancer-matrix: office)
usage: p2644_b_pipeline_agent_test.py <datadir>   (P2644B_NOSTART=1: a running server on KALMIDO_TEST_PORT)"""
import os
import sys

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
import kt  # noqa: E402
from kt import B, check, sess  # noqa: E402
from freelancer_fixture import freelancer  # noqa: E402

V = B + "/api/v1"
H = {"X-Requested-With": "kalmido"}
O = "/api/office"
P = O + "/deals"


def hd(token):
    return {**H, "Authorization": "Bearer " + token}


def cur_of(r):
    j = r.json() if r.headers.get("Content-Type", "").startswith("application/json") else {}
    return (j.get("error") or {}).get("current") or j.get("current") or {}


def seen(h, did):
    return next((x for x in requests.get(V + "/office/deals", headers=h).json().get("data", []) if x["id"] == did), {})


kt.fresh(env={"KALMIDO_INSTANCE_MODE": "workspaces"}, prefix="P2644B")
A = kt.setup()
for u, n in (("bob", "Bob Member"), ("carol", "Carol Other")):
    r = A.post(B + "/api/users", json={"username": u, "display_name": n, "password": "password123", "email": f"{u}@example.com"})
    assert r.ok, r.text
Bo, Ca = sess("bob"), sess("carol")
ALICE, BOB, CAROL = (s.get(B + "/api/state").json()["me"]["id"] for s in (A, Bo, Ca))
FEAT = "cal,comments,collab,office,clients,agents"
for s in (A, Bo, Ca):
    s.patch(B + "/api/settings", json={"lang": "en", "features": FEAT, "tour": "done"})
ORG = A.post(B + "/api/admin/orgs", json={"name": "Alpha", "admin_id": ALICE}).json()["id"]
assert A.put(B + f"/api/orgs/{ORG}/members", json={"email": "bob@example.com", "role": "member"}).ok
ORG2 = A.post(B + "/api/admin/orgs", json={"name": "Beta", "admin_id": CAROL}).json()["id"]
for s, o in ((A, ORG), (Bo, ORG), (Ca, ORG2)):
    s.patch(B + "/api/settings", json={"workspace": f"org:{o}"})

CL = A.post(B + "/api/clients", json={"name": "Beispiel Studio GmbH", "org_id": ORG}).json()["id"]
CLX = Ca.post(B + "/api/clients", json={"name": "Fremdkunde AG", "org_id": ORG2}).json()["id"]
r = A.post(B + P, json={"title": "Imagefilm Muster AG", "client_id": CL, "value": "8000", "stage": "inquiry"})
check(r.status_code == 201, f"setup: a person's inquiry {r.text[:200]}")
I1 = r.json()["id"]
L1 = A.post(B + P, json={"title": "Neuer Kontakt KG", "stage": "lead", "contact": "Frau Beispiel"}).json()["id"]
X1 = Ca.post(B + P, json={"title": "Fremdes Projekt", "client_id": CLX, "value": "999", "stage": "offer"}).json()["id"]

# ---------------------------------------------------------------- the switches
A.put(B + "/api/admin/agent-policy", json={"user_agents": True})
r = A.post(B + "/api/my/agents", json={"username": "dealbot", "display_name": "Deal Bot", "scopes": ["read", "office"], "org_id": ORG})
assert r.ok, r.text
AG, AH = r.json()["id"], hd(r.json()["token"])
PH = hd(A.post(B + "/api/my/agents", json={"username": "plainbot", "display_name": "Plain Bot", "scopes": ["read"], "org_id": ORG}).json()["token"])
check(requests.get(V + "/office/deals", headers=AH).status_code == 403, "#3663: the agent's office switch off: 403")
A.patch(B + f"{O}/agents/{AG}", json={"office_drafts": True})
check(requests.get(V + "/office/deals", headers=AH).status_code == 403, "#3663: without an office group (pipeline): 403")
check(A.put(B + f"{O}/rights/people/{AG}", json={"groups": ["tpl:projects"]}).ok, "setup: the agent in Project management")
check(requests.post(V + "/office/deals", headers=AH, json={"title": "Zu frueh"}).status_code == 403, "#3663: the area's privacy switch off: 403 (add)")
A.put(B + O + "/settings", json={"agents_read": 1})
check(requests.get(V + "/office/deals", headers=PH).status_code == 403, "#3663: an agent without the scope office: 403")
check(requests.get(V + "/office/deals", headers=AH, params={"requested_by": BOB}).status_code in (403, 404),
      "#3663: acting for a member of the office: refused")

# ---------------------------------------------------------------- list
r = requests.get(V + "/office/deals", headers=AH)
data = r.json().get("data", []) if r.ok else []
ids = [x["id"] for x in data]
check(r.ok and I1 in ids and L1 not in ids and X1 not in ids, f"#3663: the agent lists the area's deals, no lead, no other organisation {r.status_code} {r.text[:300]}")
d1 = next((x for x in data if x["id"] == I1), {})
check(d1.get("stage") == "inquiry" and d1.get("value") == "8000.00" and d1.get("probability") == 20 and d1.get("client_id") == CL
      and d1.get("client_name") == "Beispiel Studio GmbH" and d1.get("updated_at") and d1.get("app_url") == "#office/pipeline", f"#3663: the deal's fields {d1}")
r = requests.get(V + "/office/deals", headers=AH, params={"stage": "offer"})
check(r.ok and I1 not in [x["id"] for x in r.json()["data"]], "#3663: ?stage=offer leaves the inquiry out")
r = requests.get(V + "/office/deals", headers=AH, params={"stage": "open"})
check(r.ok and I1 in [x["id"] for x in r.json()["data"]], "#3663: ?stage=open = inquiry + offer")
check(requests.get(V + "/office/deals", headers=AH, params={"stage": "lead"}).status_code == 400, "#3663: ?stage=lead 400 (leads have their own route)")

# ---------------------------------------------------------------- add
r = requests.post(V + "/office/deals", headers=AH, json={"title": "Website Relaunch", "client_id": CL, "value": "2500", "expected_date": "2026-12-15",
                                                          "next_step": "Termin vereinbaren"})
check(r.status_code == 201, f"#3663: the agent adds an inquiry {r.status_code} {r.text[:200]}")
D2 = r.json() if r.status_code == 201 else {}
check(D2.get("stage") == "inquiry" and D2.get("probability") == 20 and D2.get("source") == "agent" and D2.get("value") == "2500.00"
      and D2.get("client_id") == CL and D2.get("expected_date") == "2026-12-15", f"#3663: an inquiry with the preset 20 %, source agent {D2}")
DID = D2.get("id")
items = {x["id"]: x for x in A.get(B + P).json()["items"]}
check(DID in items and items[DID]["stage"] == "inquiry", "#3663: the person sees the agent's inquiry in the pipeline")
r = requests.post(V + "/office/deals", headers=AH, json={"title": "Auftrag direkt", "stage": "won", "value": "1200"})
check(r.status_code == 201 and r.json()["stage"] == "won" and r.json()["probability"] == 100, f"#3663: a deal in another stage {r.text[:200]}")
check(requests.post(V + "/office/deals", headers=AH, json={"title": "X", "stage": "lead"}).status_code == 400, "#3663: add: the stage lead 400")
check(requests.post(V + "/office/deals", headers=AH, json={"title": "X", "client_id": CLX}).status_code == 400, "#3663: add: another organisation's client 400")
check(requests.post(V + "/office/deals", headers=AH, json={"title": "X", "offer_id": 1}).status_code == 400, "#3663: add: an unknown field 400")
check(requests.post(V + "/office/deals", headers=AH, json={"value": "10"}).status_code == 400, "#3663: add: without a title 400")

# ---------------------------------------------------------------- set the stage
r = requests.patch(V + f"/office/deals/{DID}", headers=AH, json={"stage": "offer"})
check(r.status_code == 400, f"#3663: stage without expect_updated_at: 400 {r.status_code}")
old = seen(AH, DID).get("updated_at")
kt.until(lambda: A.patch(B + f"{P}/{DID}", json={"note": "Kunde ruft zurueck"}).ok and seen(AH, DID).get("updated_at") != old)
r = requests.patch(V + f"/office/deals/{DID}", headers=AH, json={"stage": "offer", "expect_updated_at": old})
check(r.status_code == 409 and cur_of(r).get("id") == DID and cur_of(r).get("note") == "Kunde ruft zurueck", f"#3663: an old version 409 with the deal now {r.status_code} {r.text[:200]}")
check(next(x for x in A.get(B + P).json()["items"] if x["id"] == DID)["stage"] == "inquiry", "#3663: the person's state stays after the 409")
r = requests.patch(V + f"/office/deals/{DID}", headers=AH, json={"stage": "offer", "expect_updated_at": seen(AH, DID)["updated_at"]})
check(r.ok and r.json()["stage"] == "offer" and r.json()["probability"] == 50 and r.json()["note"] == "Kunde ruft zurueck", f"#3663: stage offer, preset 50 % {r.status_code} {r.text[:200]}")
r = requests.patch(V + f"/office/deals/{DID}", headers=AH, json={"stage": "lost", "lost_reason": "Budget gestrichen", "expect_updated_at": seen(AH, DID)["updated_at"]})
check(r.ok and r.json()["stage"] == "lost" and r.json()["probability"] == 0 and r.json()["lost_reason"] == "Budget gestrichen", f"#3663: stage lost with a reason {r.text[:200]}")
h = A.get(B + f"{P}/{DID}/history")
check(h.ok, f"#3663: the deal's history answers after the agent's changes {h.status_code}")
check(requests.patch(V + f"/office/deals/{DID}", headers=AH, json={"title": "Umbenannt", "stage": "offer",
                                                                     "expect_updated_at": seen(AH, DID)["updated_at"]}).status_code == 400, "#3663: stage: another field 400")
check(requests.patch(V + f"/office/deals/{DID}", headers=AH, json={"stage": "lead", "expect_updated_at": seen(AH, DID)["updated_at"]}).status_code == 400,
      "#3663: stage lead 400 (a person turns a deal back into a lead)")
check(requests.patch(V + f"/office/deals/{DID}", headers=AH, json={"expect_updated_at": seen(AH, DID)["updated_at"]}).status_code == 400, "#3663: without a stage 400")
lv = next(x for x in A.get(B + P).json()["items"] if x["id"] == L1)["updated_at"]
r = requests.patch(V + f"/office/deals/{L1}", headers=AH, json={"stage": "inquiry", "expect_updated_at": lv})
check(r.status_code == 409, f"#3663: a lead's stage 409 (a person converts it) {r.status_code} {r.text[:200]}")
check(next(x for x in A.get(B + P).json()["items"] if x["id"] == L1)["stage"] == "lead", "#3663: the lead stays a lead")
check(requests.delete(B + f"{P}/{I1}", headers=AH).status_code in (401, 403), "#3663: an agent never deletes over the app route")
n = kt.dbx("SELECT COUNT(*) FROM office_doc_log WHERE org_id=? AND user_id=? AND target='deals'", (ORG, AG))[0][0]
check(n >= 8, f"#3663: the agent's requests in the office log (target deals): {n}")

# ---------------------------------------------------------------- another organisation (tenant-matrix: office)
r = requests.patch(V + f"/office/deals/{X1}", headers=AH, json={"stage": "won", "expect_updated_at": "2026-01-01T00:00:00Z"})
check(r.status_code == 404, f"#3663: another organisation's deal 404 {r.status_code}")
check(next(x for x in Ca.get(B + P).json()["items"] if x["id"] == X1)["stage"] == "offer", "#3663: the other organisation's deal is untouched")
r = requests.get(V + "/openapi.json", headers=AH)
if r.ok:
    pth = r.json().get("paths", {})
    check(pth.get("/office/deals", {}).get("get", {}).get("x-kalmido-scope") == "office" and "patch" in pth.get("/office/deals/{id}", {}),
          "#3663: OpenAPI with scope office")

# ---------------------------------------------------------------- a person without organisation (freelancer-matrix: office)
FID, Fr = freelancer(B, A)
Fr.get(B + O + "/settings")
r = Fr.post(B + "/api/my/agents", json={"username": "fridabot", "display_name": "Frida Bot", "scopes": ["read", "office"]})
check(r.status_code == 201, "setup: the freelancer's own agent " + r.text[:200])
FAG, FH = r.json()["id"], hd(r.json()["token"])
check(requests.get(V + "/office/deals", headers=FH).status_code == 403, "#3663: freelancer: switches off: 403")
check(Fr.patch(B + f"{O}/agents/{FAG}", json={"office_drafts": True}).ok and Fr.put(B + O + "/settings", json={"agents_read": 1}).ok,
      "setup: both office switches of the personal office")
r = Fr.post(B + P, json={"title": "Hochzeitsfilm Beispiel", "value": "3000"})
check(r.status_code == 201, f"freelancer: setup: an inquiry {r.text[:200]}")
FD = r.json()["id"]
r = requests.get(V + "/office/deals", headers=FH)
check(r.ok and [x["id"] for x in r.json()["data"]] == [FD], f"#3663: freelancer: her agent lists her inquiry only {r.text[:200]}")
r = requests.post(V + "/office/deals", headers=FH, json={"title": "Portraits Beispiel", "stage": "offer", "value": "800"})
check(r.status_code == 201 and r.json()["stage"] == "offer", f"#3663: freelancer: her agent adds a deal {r.text[:200]}")
r = requests.patch(V + f"/office/deals/{FD}", headers=FH, json={"stage": "won", "expect_updated_at": seen(FH, FD)["updated_at"]})
check(r.ok and r.json()["stage"] == "won" and r.json()["probability"] == 100, f"#3663: freelancer: stage won {r.text[:200]}")
check(next(x for x in Fr.get(B + P).json()["items"] if x["id"] == FD)["stage"] == "won", "#3663: freelancer: she sees the stage")
check(FD not in [x["id"] for x in requests.get(V + "/office/deals", headers=AH).json()["data"]]
      and requests.patch(V + f"/office/deals/{FD}", headers=AH, json={"stage": "lost", "expect_updated_at": "2026-01-01T00:00:00Z"}).status_code == 404,
      "#3663: freelancer: another person's agent never reaches her deals")
check(requests.patch(V + f"/office/deals/{DID}", headers=FH, json={"stage": "won", "expect_updated_at": "2026-01-01T00:00:00Z"}).status_code == 404,
      "#3663: freelancer: her agent never reaches the organisation's deals")
sys.exit(kt.done("p2644_b_pipeline_agent"))
